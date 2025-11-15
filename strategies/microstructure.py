"""
Enhanced microstructure filters for liquidity and timing gates.

Implements 24/7 trading without zombie hours by checking:
- Rolling 1m notional volume (pair-specific thresholds)
- Book depth imbalance
- Optional UTC time windows for entries (exits always allowed)

All thresholds configurable via YAML and CLI.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================


@dataclass
class PairLiquidityConfig:
    """Liquidity thresholds for a specific trading pair."""

    symbol: str
    min_notional_1m_usd: float = 50000.0  # Minimum 1-minute rolling volume
    max_spread_bps: float = 10.0  # Maximum spread in basis points
    max_depth_imbalance: float = 0.7  # Maximum bid/ask imbalance (0.7 = 70/30)

    def __post_init__(self):
        """Validate configuration."""
        if self.min_notional_1m_usd < 0:
            raise ValueError(f"min_notional_1m_usd must be >= 0, got {self.min_notional_1m_usd}")
        if self.max_spread_bps < 0:
            raise ValueError(f"max_spread_bps must be >= 0, got {self.max_spread_bps}")
        if not 0.5 <= self.max_depth_imbalance <= 1.0:
            raise ValueError(f"max_depth_imbalance must be in [0.5, 1.0], got {self.max_depth_imbalance}")


@dataclass
class TimeWindowConfig:
    """Time window configuration for entry filtering."""

    enabled: bool = False
    start_utc_hour: int = 12  # 12:00 UTC
    end_utc_hour: int = 22  # 22:00 UTC
    restrict_symbols: List[str] = field(default_factory=list)  # e.g., ["*USD", "*USDT"]

    def __post_init__(self):
        """Validate configuration."""
        if not 0 <= self.start_utc_hour <= 23:
            raise ValueError(f"start_utc_hour must be in [0, 23], got {self.start_utc_hour}")
        if not 0 <= self.end_utc_hour <= 23:
            raise ValueError(f"end_utc_hour must be in [0, 23], got {self.end_utc_hour}")


@dataclass
class MicrostructureConfig:
    """Global microstructure filter configuration."""

    # Pair-specific thresholds
    pair_configs: Dict[str, PairLiquidityConfig] = field(default_factory=dict)

    # Default thresholds (used if pair not in pair_configs)
    default_min_notional_1m_usd: float = 50000.0
    default_max_spread_bps: float = 10.0
    default_max_depth_imbalance: float = 0.7

    # Time window
    time_window: TimeWindowConfig = field(default_factory=TimeWindowConfig)

    # Rolling window size for notional tracking
    notional_window_seconds: int = 60

    def get_pair_config(self, symbol: str) -> PairLiquidityConfig:
        """Get config for a symbol, falling back to defaults."""
        if symbol in self.pair_configs:
            return self.pair_configs[symbol]

        # Return default config for symbol
        return PairLiquidityConfig(
            symbol=symbol,
            min_notional_1m_usd=self.default_min_notional_1m_usd,
            max_spread_bps=self.default_max_spread_bps,
            max_depth_imbalance=self.default_max_depth_imbalance,
        )


# =============================================================================
# Rolling Notional Filter
# =============================================================================


@dataclass
class TradeVolume:
    """Single trade volume data point."""

    timestamp: float  # Unix timestamp
    notional_usd: float


class RollingNotionalFilter:
    """
    Tracks rolling 1-minute notional volume per symbol.

    Maintains a sliding window of trade volumes and computes
    the sum of notional USD traded in the last N seconds.
    """

    def __init__(self, window_seconds: int = 60):
        """
        Initialize rolling notional filter.

        Args:
            window_seconds: Rolling window size in seconds
        """
        self.window_seconds = window_seconds
        self._volumes: Dict[str, deque] = {}  # symbol -> deque[TradeVolume]

    def add_trade(self, symbol: str, notional_usd: float, timestamp: float) -> None:
        """
        Add a trade to the rolling window.

        Args:
            symbol: Trading pair symbol
            notional_usd: Notional value in USD
            timestamp: Trade timestamp (Unix seconds)
        """
        if symbol not in self._volumes:
            self._volumes[symbol] = deque()

        self._volumes[symbol].append(TradeVolume(timestamp=timestamp, notional_usd=notional_usd))

        # Cleanup old trades outside window
        self._cleanup_old_trades(symbol, timestamp)

    def get_rolling_notional(self, symbol: str, current_time: float) -> float:
        """
        Get rolling notional volume for a symbol.

        Args:
            symbol: Trading pair symbol
            current_time: Current timestamp (Unix seconds)

        Returns:
            Sum of notional USD in rolling window
        """
        if symbol not in self._volumes:
            return 0.0

        # Cleanup old trades
        self._cleanup_old_trades(symbol, current_time)

        # Sum notional in window
        return sum(tv.notional_usd for tv in self._volumes[symbol])

    def check_min_notional(
        self, symbol: str, min_notional_usd: float, current_time: float
    ) -> Tuple[bool, str]:
        """
        Check if rolling notional meets minimum threshold.

        Args:
            symbol: Trading pair symbol
            min_notional_usd: Minimum required notional
            current_time: Current timestamp (Unix seconds)

        Returns:
            (passed, reason) - True if passed, False with reason if failed
        """
        rolling = self.get_rolling_notional(symbol, current_time)

        if rolling < min_notional_usd:
            return False, f"rolling_notional={rolling:.0f} < min={min_notional_usd:.0f}"

        return True, f"rolling_notional={rolling:.0f} OK"

    def _cleanup_old_trades(self, symbol: str, current_time: float) -> None:
        """Remove trades outside rolling window."""
        if symbol not in self._volumes:
            return

        cutoff_time = current_time - self.window_seconds

        while self._volumes[symbol] and self._volumes[symbol][0].timestamp < cutoff_time:
            self._volumes[symbol].popleft()


# =============================================================================
# Depth Imbalance Filter
# =============================================================================


class DepthImbalanceFilter:
    """
    Checks orderbook depth imbalance.

    Computes bid_volume / (bid_volume + ask_volume) and rejects
    if imbalance exceeds threshold (e.g., 0.7 = 70% bids, 30% asks).
    """

    @staticmethod
    def calculate_imbalance(bid_volume: float, ask_volume: float) -> float:
        """
        Calculate depth imbalance ratio.

        Args:
            bid_volume: Total bid volume
            ask_volume: Total ask volume

        Returns:
            Imbalance ratio in [0, 1] where 0.5 = balanced
        """
        total = bid_volume + ask_volume

        if total == 0:
            return 0.5  # Neutral if no depth

        return bid_volume / total

    @staticmethod
    def check_imbalance(
        bid_volume: float, ask_volume: float, max_imbalance: float
    ) -> Tuple[bool, str]:
        """
        Check if depth imbalance is within acceptable range.

        Args:
            bid_volume: Total bid volume
            ask_volume: Total ask volume
            max_imbalance: Maximum allowed imbalance (0.5-1.0)

        Returns:
            (passed, reason) - True if passed, False with reason if failed
        """
        imbalance = DepthImbalanceFilter.calculate_imbalance(bid_volume, ask_volume)

        # Check if imbalance exceeds threshold in either direction
        # max_imbalance=0.7 means reject if >70% bids or >70% asks
        min_imbalance = 1.0 - max_imbalance

        if imbalance > max_imbalance or imbalance < min_imbalance:
            direction = "bid-heavy" if imbalance > 0.5 else "ask-heavy"
            return False, f"depth_imbalance={imbalance:.2f} ({direction}) exceeds [{min_imbalance:.2f}, {max_imbalance:.2f}]"

        return True, f"depth_imbalance={imbalance:.2f} OK"


# =============================================================================
# Time Window Filter
# =============================================================================


class TimeWindowFilter:
    """
    Filters entries based on UTC time windows.

    Allows restricting entries to specific hours (e.g., 12:00-22:00 UTC)
    while always allowing exits/position management.
    """

    def __init__(self, config: TimeWindowConfig):
        """
        Initialize time window filter.

        Args:
            config: Time window configuration
        """
        self.config = config

    def check_entry_allowed(
        self, symbol: str, current_time: Optional[float] = None, is_entry: bool = True
    ) -> Tuple[bool, str]:
        """
        Check if entry is allowed based on time window.

        Args:
            symbol: Trading pair symbol
            current_time: Current timestamp (Unix seconds), None = now
            is_entry: True for new entries, False for exits/management

        Returns:
            (passed, reason) - True if passed, False with reason if failed
        """
        # Always allow exits
        if not is_entry:
            return True, "exit_allowed_24_7"

        # Skip check if time window disabled
        if not self.config.enabled:
            return True, "time_window_disabled"

        # Check if symbol matches restricted patterns
        symbol_restricted = self._is_symbol_restricted(symbol)
        if not symbol_restricted:
            return True, f"symbol_not_restricted"

        # Get current UTC hour
        if current_time is None:
            current_time = datetime.now(timezone.utc).timestamp()

        current_hour = datetime.fromtimestamp(current_time, tz=timezone.utc).hour

        # Check if within window
        start = self.config.start_utc_hour
        end = self.config.end_utc_hour

        if start <= end:
            # Simple range (e.g., 12:00-22:00)
            in_window = start <= current_hour < end
        else:
            # Wrap around midnight (e.g., 22:00-06:00)
            in_window = current_hour >= start or current_hour < end

        if not in_window:
            return False, f"outside_time_window ({start:02d}:00-{end:02d}:00 UTC, now={current_hour:02d}:xx)"

        return True, f"in_time_window ({current_hour:02d}:xx UTC)"

    def _is_symbol_restricted(self, symbol: str) -> bool:
        """Check if symbol matches any restricted patterns."""
        if not self.config.restrict_symbols:
            # If no patterns specified, restrict all symbols
            return True

        for pattern in self.config.restrict_symbols:
            if pattern.startswith("*"):
                # Suffix match (e.g., "*USD" matches "BTC/USD", "ETH/USD")
                if symbol.endswith(pattern[1:]):
                    return True
            elif pattern.endswith("*"):
                # Prefix match (e.g., "BTC*" matches "BTC/USD", "BTC/EUR")
                if symbol.startswith(pattern[:-1]):
                    return True
            elif pattern == symbol:
                # Exact match
                return True

        return False


# =============================================================================
# Integrated Microstructure Gate
# =============================================================================


class MicrostructureGate:
    """
    Integrated microstructure filter combining all checks.

    Before allowing entry:
    1. Check rolling 1m notional >= threshold
    2. Check spread_bps <= max
    3. Check depth imbalance <= max
    4. Check UTC time window (if enabled)

    Exits always allowed (24/7 position management).
    """

    def __init__(self, config: MicrostructureConfig):
        """
        Initialize microstructure gate.

        Args:
            config: Microstructure configuration
        """
        self.config = config
        self.notional_filter = RollingNotionalFilter(config.notional_window_seconds)
        self.time_filter = TimeWindowFilter(config.time_window)

    def add_trade(self, symbol: str, notional_usd: float, timestamp: float) -> None:
        """
        Update rolling notional filter with new trade.

        Args:
            symbol: Trading pair symbol
            notional_usd: Notional value in USD
            timestamp: Trade timestamp (Unix seconds)
        """
        self.notional_filter.add_trade(symbol, notional_usd, timestamp)

    def check_can_enter(
        self,
        symbol: str,
        bid: float,
        ask: float,
        bid_volume: float,
        ask_volume: float,
        current_time: Optional[float] = None,
        is_entry: bool = True,
    ) -> Tuple[bool, List[str]]:
        """
        Check if entry is allowed based on all microstructure filters.

        Args:
            symbol: Trading pair symbol
            bid: Best bid price
            ask: Best ask price
            bid_volume: Total bid volume
            ask_volume: Total ask volume
            current_time: Current timestamp (Unix seconds), None = now
            is_entry: True for new entries, False for exits

        Returns:
            (allowed, reasons) - True if all checks pass, list of pass/fail reasons
        """
        if current_time is None:
            current_time = datetime.now(timezone.utc).timestamp()

        reasons = []
        all_passed = True

        # Always allow exits
        if not is_entry:
            return True, ["exit_allowed_24_7"]

        # Get pair config
        pair_config = self.config.get_pair_config(symbol)

        # Check 1: Rolling notional
        notional_passed, notional_reason = self.notional_filter.check_min_notional(
            symbol, pair_config.min_notional_1m_usd, current_time
        )
        reasons.append(f"notional: {notional_reason}")
        all_passed = all_passed and notional_passed

        # Check 2: Spread
        mid = (bid + ask) / 2
        spread = ask - bid
        spread_bps = (spread / mid) * 10000 if mid > 0 else 0

        if spread_bps > pair_config.max_spread_bps:
            reasons.append(f"spread: {spread_bps:.1f}bps > max={pair_config.max_spread_bps:.1f}bps FAIL")
            all_passed = False
        else:
            reasons.append(f"spread: {spread_bps:.1f}bps OK")

        # Check 3: Depth imbalance
        imbalance_passed, imbalance_reason = DepthImbalanceFilter.check_imbalance(
            bid_volume, ask_volume, pair_config.max_depth_imbalance
        )
        reasons.append(f"imbalance: {imbalance_reason}")
        all_passed = all_passed and imbalance_passed

        # Check 4: Time window
        time_passed, time_reason = self.time_filter.check_entry_allowed(
            symbol, current_time, is_entry=True
        )
        reasons.append(f"time: {time_reason}")
        all_passed = all_passed and time_passed

        return all_passed, reasons


# =============================================================================
# SELF-CHECK
# =============================================================================

if __name__ == "__main__":
    """Self-check: Test microstructure filters"""
    import time

    print("\n[TEST] Microstructure Filters Self-Check\n")

    # Test 1: Rolling notional filter
    print("Test 1: Rolling Notional Filter")
    notional = RollingNotionalFilter(window_seconds=60)

    now = time.time()

    # Add trades
    notional.add_trade("BTC/USD", 10000.0, now - 50)
    notional.add_trade("BTC/USD", 20000.0, now - 30)
    notional.add_trade("BTC/USD", 15000.0, now - 10)

    rolling = notional.get_rolling_notional("BTC/USD", now)
    assert rolling == 45000.0, f"Expected 45000, got {rolling}"

    passed, reason = notional.check_min_notional("BTC/USD", 40000.0, now)
    assert passed, f"Should pass with 45000 > 40000"
    print(f"  [+] Rolling notional: {rolling} USD - {reason}")

    # Test 2: Depth imbalance filter
    print("\nTest 2: Depth Imbalance Filter")

    # Balanced book
    imbalance = DepthImbalanceFilter.calculate_imbalance(100.0, 100.0)
    assert abs(imbalance - 0.5) < 0.01, f"Expected 0.5, got {imbalance}"
    passed, reason = DepthImbalanceFilter.check_imbalance(100.0, 100.0, 0.7)
    assert passed, "Balanced book should pass"
    print(f"  [+] Balanced book: {reason}")

    # Imbalanced book (80% bids)
    imbalance = DepthImbalanceFilter.calculate_imbalance(80.0, 20.0)
    assert abs(imbalance - 0.8) < 0.01, f"Expected 0.8, got {imbalance}"
    passed, reason = DepthImbalanceFilter.check_imbalance(80.0, 20.0, 0.7)
    assert not passed, "Imbalanced book should fail"
    print(f"  [+] Imbalanced book: {reason}")

    # Test 3: Time window filter
    print("\nTest 3: Time Window Filter")

    # Enabled window 12:00-22:00 UTC for USD pairs
    time_config = TimeWindowConfig(
        enabled=True, start_utc_hour=12, end_utc_hour=22, restrict_symbols=["*USD"]
    )
    time_filter = TimeWindowFilter(time_config)

    # Always allow exits
    passed, reason = time_filter.check_entry_allowed("BTC/USD", now, is_entry=False)
    assert passed, "Exits should always be allowed"
    print(f"  [+] Exit check: {reason}")

    # Test 4: Integrated gate
    print("\nTest 4: Integrated Microstructure Gate")

    config = MicrostructureConfig(
        default_min_notional_1m_usd=40000.0,
        default_max_spread_bps=10.0,
        default_max_depth_imbalance=0.7,
        time_window=TimeWindowConfig(enabled=False),  # Disable for test
    )

    gate = MicrostructureGate(config)

    # Add trades
    gate.add_trade("BTC/USD", 10000.0, now - 50)
    gate.add_trade("BTC/USD", 20000.0, now - 30)
    gate.add_trade("BTC/USD", 15000.0, now - 10)

    # Good conditions
    allowed, reasons = gate.check_can_enter(
        symbol="BTC/USD",
        bid=50000.0,
        ask=50010.0,  # 2 bps spread
        bid_volume=100.0,
        ask_volume=100.0,  # Balanced
        current_time=now,
        is_entry=True,
    )

    assert allowed, f"Should allow entry with good conditions: {reasons}"
    print(f"  [+] Good conditions: ALLOWED")
    for r in reasons:
        print(f"      {r}")

    # Bad conditions (wide spread)
    allowed, reasons = gate.check_can_enter(
        symbol="BTC/USD",
        bid=50000.0,
        ask=50100.0,  # 20 bps spread
        bid_volume=100.0,
        ask_volume=100.0,
        current_time=now,
        is_entry=True,
    )

    assert not allowed, f"Should reject with wide spread: {reasons}"
    print(f"  [+] Wide spread: REJECTED")
    for r in reasons:
        print(f"      {r}")

    print("\n[PASS] Microstructure Filters Self-Check\n")
