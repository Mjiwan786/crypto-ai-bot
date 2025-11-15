"""
Overnight Momentum Strategy

Detects momentum during Asian session with low volume conditions.
Uses larger notional on spot (leverage proxy) for 1-3% swing targets.

Features:
- Asian session detection (00:00-08:00 UTC)
- Low volume filtering
- Momentum detection (trend + volatility expansion)
- Tight trailing exits (0.5-1.0% trailing stop)
- Hard cap: 1 concurrent overnight position
- Backtest-only mode with promotion gates

Target: 1.0-3.0% swing
Risk: Tight trailing stops

Author: Crypto AI Bot Team
Date: 2025-11-08
"""

import os
import time
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone
from decimal import Decimal
from dataclasses import dataclass
from enum import Enum


class SessionType(Enum):
    """Trading session types."""
    ASIAN = "asian"
    EUROPEAN = "european"
    US = "us"
    UNKNOWN = "unknown"


@dataclass
class OvernightSignal:
    """Overnight momentum signal."""
    signal_id: str
    symbol: str
    side: str  # "long" or "short"
    entry_price: Decimal
    target_price: Decimal  # 1-3% target
    trailing_stop_pct: Decimal  # 0.5-1.0% trailing
    confidence: Decimal
    session: SessionType
    volume_percentile: float  # Current volume vs 24h average
    momentum_strength: float  # 0.0 to 1.0
    timestamp: float
    metadata: Dict


class OvernightMomentumStrategy:
    """
    Overnight momentum strategy for Asian session.

    Entry Criteria:
    - Asian session (00:00-08:00 UTC)
    - Low volume (< 50th percentile of 24h)
    - Momentum detected (trend + volatility expansion)
    - No existing overnight position

    Exit Criteria:
    - Trailing stop hit (0.5-1.0%)
    - Target reached (1.0-3.0%)
    - Session end (08:00 UTC)
    - Risk-off conditions
    """

    def __init__(
        self,
        redis_manager=None,
        logger=None,
        enabled: bool = None,
        backtest_only: bool = True,
    ):
        """
        Initialize overnight momentum strategy.

        Args:
            redis_manager: Redis client
            logger: Logger instance
            enabled: Override feature flag
            backtest_only: Only run in backtest mode (default: True)
        """
        self.redis = redis_manager
        self.logger = logger or logging.getLogger(__name__)

        # Feature flags
        if enabled is None:
            self.enabled = os.getenv("OVERNIGHT_MOMENTUM_ENABLED", "false").lower() == "true"
        else:
            self.enabled = enabled

        self.backtest_only = backtest_only

        # Configuration from env/YAML
        self.target_swing_min_pct = float(os.getenv("OVERNIGHT_TARGET_MIN", "1.0"))
        self.target_swing_max_pct = float(os.getenv("OVERNIGHT_TARGET_MAX", "3.0"))
        self.trailing_stop_pct = float(os.getenv("OVERNIGHT_TRAILING_STOP", "0.7"))
        self.volume_percentile_max = float(os.getenv("OVERNIGHT_VOLUME_PERCENTILE_MAX", "50.0"))
        self.momentum_threshold = float(os.getenv("OVERNIGHT_MOMENTUM_THRESHOLD", "0.6"))

        # Hard caps
        self.max_concurrent_positions = 1  # Hard cap: 1 position

        # Session detection (UTC hours)
        self.asian_session_start = 0   # 00:00 UTC
        self.asian_session_end = 8     # 08:00 UTC

        # State tracking
        self.active_positions: Dict[str, Dict] = {}  # symbol -> position

        # Promotion gates (for backtest -> live)
        self.promotion_gates = {
            "min_trades": int(os.getenv("OVERNIGHT_PROMOTION_MIN_TRADES", "50")),
            "min_win_rate": float(os.getenv("OVERNIGHT_PROMOTION_MIN_WIN_RATE", "0.55")),
            "min_sharpe": float(os.getenv("OVERNIGHT_PROMOTION_MIN_SHARPE", "1.5")),
            "max_drawdown": float(os.getenv("OVERNIGHT_PROMOTION_MAX_DRAWDOWN", "0.10")),
        }

        if not self.enabled:
            self.logger.info("OvernightMomentumStrategy disabled")
        else:
            self.logger.info(
                f"OvernightMomentumStrategy enabled: "
                f"backtest_only={backtest_only}, "
                f"target={self.target_swing_min_pct}-{self.target_swing_max_pct}%, "
                f"trailing={self.trailing_stop_pct}%"
            )

    def detect_session(self, current_time: Optional[float] = None) -> SessionType:
        """
        Detect current trading session based on UTC time.

        Args:
            current_time: Unix timestamp (default: now)

        Returns:
            SessionType
        """
        if current_time is None:
            current_time = time.time()

        dt = datetime.fromtimestamp(current_time, tz=timezone.utc)
        hour = dt.hour

        # Asian session: 00:00-08:00 UTC
        if self.asian_session_start <= hour < self.asian_session_end:
            return SessionType.ASIAN

        # European session: 08:00-16:00 UTC
        elif 8 <= hour < 16:
            return SessionType.EUROPEAN

        # US session: 16:00-24:00 UTC
        elif 16 <= hour < 24:
            return SessionType.US

        else:
            return SessionType.UNKNOWN

    def check_volume_filter(
        self,
        current_volume: float,
        avg_24h_volume: float,
    ) -> Tuple[bool, float]:
        """
        Check if current volume is in low percentile.

        Args:
            current_volume: Current period volume
            avg_24h_volume: 24h average volume

        Returns:
            (passes_filter, percentile)
        """
        if avg_24h_volume == 0:
            return False, 0.0

        # Calculate percentile (rough estimate)
        volume_ratio = current_volume / avg_24h_volume
        percentile = min(volume_ratio * 100, 100.0)

        # Pass if below threshold (low volume)
        passes = percentile <= self.volume_percentile_max

        return passes, percentile

    def detect_momentum(
        self,
        prices: List[Decimal],
        volumes: List[float],
        current_price: Decimal,
    ) -> Tuple[bool, float, str]:
        """
        Detect momentum from price and volume data.

        Momentum criteria:
        - Price trend (EMA crossover or directional move)
        - Volatility expansion
        - Volume confirmation (optional in low volume environment)

        Args:
            prices: Recent prices (last 20+ bars)
            volumes: Recent volumes
            current_price: Current price

        Returns:
            (has_momentum, strength, direction)
            direction: "long" or "short"
        """
        if len(prices) < 20:
            return False, 0.0, "none"

        # Calculate short and long EMAs
        ema_short = self._calculate_ema(prices[-10:], period=5)
        ema_long = self._calculate_ema(prices, period=20)

        # Price trend
        if ema_short > ema_long:
            direction = "long"
            trend_strength = float((ema_short - ema_long) / ema_long)
        elif ema_short < ema_long:
            direction = "short"
            trend_strength = float((ema_long - ema_short) / ema_long)
        else:
            return False, 0.0, "none"

        # Volatility expansion
        recent_volatility = self._calculate_volatility(prices[-10:])
        baseline_volatility = self._calculate_volatility(prices)

        if baseline_volatility > 0:
            volatility_ratio = recent_volatility / baseline_volatility
        else:
            volatility_ratio = 1.0

        # Momentum strength (combined trend + volatility)
        momentum_strength = min(
            abs(trend_strength) * volatility_ratio * 10,
            1.0
        )

        # Check threshold
        has_momentum = momentum_strength >= self.momentum_threshold

        return has_momentum, momentum_strength, direction

    def generate_signal(
        self,
        symbol: str,
        current_price: Decimal,
        prices: List[Decimal],
        volumes: List[float],
        avg_24h_volume: float,
        current_time: Optional[float] = None,
    ) -> Optional[OvernightSignal]:
        """
        Generate overnight momentum signal.

        Args:
            symbol: Trading symbol
            current_price: Current price
            prices: Recent prices
            volumes: Recent volumes
            avg_24h_volume: 24h average volume
            current_time: Current timestamp

        Returns:
            OvernightSignal or None
        """
        if not self.enabled:
            return None

        if current_time is None:
            current_time = time.time()

        # Check if at position cap
        if len(self.active_positions) >= self.max_concurrent_positions:
            self.logger.debug(f"At position cap ({self.max_concurrent_positions}), skipping signal")
            return None

        # Check session
        session = self.detect_session(current_time)
        if session != SessionType.ASIAN:
            return None

        # Check volume filter
        current_volume = volumes[-1] if volumes else 0.0
        volume_passes, volume_percentile = self.check_volume_filter(
            current_volume, avg_24h_volume
        )

        if not volume_passes:
            self.logger.debug(
                f"Volume filter failed: {volume_percentile:.1f}th percentile "
                f"(max: {self.volume_percentile_max})"
            )
            return None

        # Check momentum
        has_momentum, momentum_strength, direction = self.detect_momentum(
            prices, volumes, current_price
        )

        if not has_momentum:
            self.logger.debug(
                f"Momentum not detected: strength={momentum_strength:.2f} "
                f"(threshold: {self.momentum_threshold})"
            )
            return None

        # Calculate target and stop
        target_pct = Decimal(str(self.target_swing_min_pct))  # Conservative target
        trailing_stop_pct = Decimal(str(self.trailing_stop_pct))

        if direction == "long":
            target_price = current_price * (Decimal("1") + target_pct / Decimal("100"))
        else:  # short
            target_price = current_price * (Decimal("1") - target_pct / Decimal("100"))

        # Generate signal
        signal = OvernightSignal(
            signal_id=f"overnight_{symbol}_{int(current_time)}",
            symbol=symbol,
            side=direction,
            entry_price=current_price,
            target_price=target_price,
            trailing_stop_pct=trailing_stop_pct,
            confidence=Decimal(str(momentum_strength)),
            session=session,
            volume_percentile=volume_percentile,
            momentum_strength=momentum_strength,
            timestamp=current_time,
            metadata={
                "strategy": "overnight_momentum",
                "session": session.value,
                "volume_percentile": volume_percentile,
                "target_pct": float(target_pct),
                "trailing_stop_pct": float(trailing_stop_pct),
            }
        )

        self.logger.info(
            f"Overnight signal generated: {symbol} {direction.upper()} @ ${current_price:.2f}, "
            f"target=${target_price:.2f} ({target_pct:.1f}%), "
            f"momentum={momentum_strength:.2f}, volume_pct={volume_percentile:.1f}"
        )

        return signal

    def update_trailing_stop(
        self,
        position: Dict,
        current_price: Decimal,
    ) -> Decimal:
        """
        Update trailing stop for position.

        Args:
            position: Position dictionary
            current_price: Current price

        Returns:
            New stop loss price
        """
        entry_price = Decimal(str(position["entry_price"]))
        side = position["side"]
        trailing_pct = Decimal(str(position["trailing_stop_pct"]))
        current_stop = Decimal(str(position.get("stop_loss", 0)))

        if side == "long":
            # For long: stop loss trails below price
            new_stop = current_price * (Decimal("1") - trailing_pct / Decimal("100"))

            # Only update if new stop is higher (never lower the stop)
            if current_stop == 0 or new_stop > current_stop:
                return new_stop
            else:
                return current_stop

        else:  # short
            # For short: stop loss trails above price
            new_stop = current_price * (Decimal("1") + trailing_pct / Decimal("100"))

            # Only update if new stop is lower (never raise the stop)
            if current_stop == 0 or new_stop < current_stop:
                return new_stop
            else:
                return current_stop

    def check_exit(
        self,
        position: Dict,
        current_price: Decimal,
        current_time: Optional[float] = None,
    ) -> Tuple[bool, str]:
        """
        Check if position should exit.

        Exit reasons:
        - Trailing stop hit
        - Target reached
        - Session end
        - Risk-off conditions

        Args:
            position: Position dictionary
            current_price: Current price
            current_time: Current timestamp

        Returns:
            (should_exit, reason)
        """
        if current_time is None:
            current_time = time.time()

        side = position["side"]
        entry_price = Decimal(str(position["entry_price"]))
        target_price = Decimal(str(position["target_price"]))
        stop_loss = Decimal(str(position.get("stop_loss", 0)))

        # Check target reached
        if side == "long":
            if current_price >= target_price:
                return True, "target_reached"
        else:  # short
            if current_price <= target_price:
                return True, "target_reached"

        # Check trailing stop
        if stop_loss > 0:
            if side == "long":
                if current_price <= stop_loss:
                    return True, "trailing_stop"
            else:  # short
                if current_price >= stop_loss:
                    return True, "trailing_stop"

        # Check session end
        session = self.detect_session(current_time)
        if session != SessionType.ASIAN:
            return True, "session_end"

        return False, ""

    def _calculate_ema(self, prices: List[Decimal], period: int) -> Decimal:
        """Calculate Exponential Moving Average."""
        if not prices or len(prices) < period:
            return Decimal("0")

        multiplier = Decimal("2") / Decimal(str(period + 1))
        ema = prices[0]

        for price in prices[1:]:
            ema = (price * multiplier) + (ema * (Decimal("1") - multiplier))

        return ema

    def _calculate_volatility(self, prices: List[Decimal]) -> float:
        """Calculate price volatility (standard deviation of returns)."""
        if len(prices) < 2:
            return 0.0

        returns = [
            float((prices[i] - prices[i-1]) / prices[i-1])
            for i in range(1, len(prices))
        ]

        if not returns:
            return 0.0

        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        volatility = variance ** 0.5

        return volatility

    def get_position_count(self) -> int:
        """Get count of active overnight positions."""
        return len(self.active_positions)

    def can_open_position(self) -> bool:
        """Check if new position can be opened."""
        return self.get_position_count() < self.max_concurrent_positions

    def check_promotion_gates(self, backtest_results: Dict) -> Tuple[bool, List[str]]:
        """
        Check if strategy passes promotion gates for live trading.

        Args:
            backtest_results: Backtest statistics

        Returns:
            (passes, failed_gates)
        """
        failed_gates = []

        # Check minimum trades
        if backtest_results.get("total_trades", 0) < self.promotion_gates["min_trades"]:
            failed_gates.append(
                f"Insufficient trades: {backtest_results.get('total_trades', 0)} "
                f"< {self.promotion_gates['min_trades']}"
            )

        # Check win rate
        win_rate = backtest_results.get("win_rate", 0.0)
        if win_rate < self.promotion_gates["min_win_rate"]:
            failed_gates.append(
                f"Low win rate: {win_rate:.1%} < {self.promotion_gates['min_win_rate']:.1%}"
            )

        # Check Sharpe ratio
        sharpe = backtest_results.get("sharpe_ratio", 0.0)
        if sharpe < self.promotion_gates["min_sharpe"]:
            failed_gates.append(
                f"Low Sharpe ratio: {sharpe:.2f} < {self.promotion_gates['min_sharpe']:.2f}"
            )

        # Check max drawdown
        max_dd = backtest_results.get("max_drawdown", 1.0)
        if max_dd > self.promotion_gates["max_drawdown"]:
            failed_gates.append(
                f"High max drawdown: {max_dd:.1%} > {self.promotion_gates['max_drawdown']:.1%}"
            )

        passes = len(failed_gates) == 0
        return passes, failed_gates


def create_overnight_momentum_strategy(
    redis_manager=None,
    logger=None,
    enabled: bool = None,
    backtest_only: bool = True,
) -> OvernightMomentumStrategy:
    """
    Create overnight momentum strategy.

    Args:
        redis_manager: Redis client
        logger: Logger instance
        enabled: Override feature flag
        backtest_only: Only run in backtest (default: True)

    Returns:
        OvernightMomentumStrategy instance
    """
    return OvernightMomentumStrategy(
        redis_manager=redis_manager,
        logger=logger,
        enabled=enabled,
        backtest_only=backtest_only,
    )
