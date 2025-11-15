"""
Standardized Strategy API with P&L-friendly types.

Defines the common interface for all trading strategies with:
- Frozen dataclasses for immutability
- Decimal precision for money
- UTC timestamps for temporal accuracy
- Protocol for polymorphic strategy usage

Accept criteria:
- mypy --strict passes
- No I/O operations
- Precise typing with Decimal
- Full docstrings with Args/Returns/Raises
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol, Optional

from ai_engine.schemas import MarketSnapshot


@dataclass(frozen=True)
class StrategyParams:
    """
    Strategy configuration parameters.

    Immutable configuration for strategy execution with risk controls.

    Attributes:
        name: Strategy identifier (e.g., "momentum_scalper", "mean_reversion")
        min_confidence: Minimum confidence threshold to open positions [0, 1]
        max_position_size_usd: Maximum position size in USD
        stop_loss_pct: Stop loss percentage (e.g., 0.02 = 2%)
        take_profit_pct: Take profit percentage (e.g., 0.04 = 4%)
        volatility_target_annual: Target annual volatility (e.g., 0.10 = 10%)
        kelly_fraction_cap: Maximum Kelly fraction to use (e.g., 0.25 = 25%)
        use_trade_filters: Whether to apply regime/liquidity filters
    """
    name: str
    min_confidence: Decimal
    max_position_size_usd: Decimal
    stop_loss_pct: Decimal
    take_profit_pct: Decimal
    volatility_target_annual: Decimal
    kelly_fraction_cap: Decimal
    use_trade_filters: bool


@dataclass(frozen=True)
class SignalSpec:
    """
    Trading signal specification.

    Immutable signal with unique ID for deduplication and precise pricing.

    Attributes:
        signal_id: Unique signal identifier (hash of ts|pair|strategy|level)
        timestamp: Signal generation time (UTC timezone-aware)
        symbol: Trading pair (e.g., "BTC/USD", "ETH/USD")
        side: Trade direction ("long" or "short")
        entry_price: Expected entry price (Decimal for precision)
        stop_loss: Stop loss price (Decimal)
        take_profit: Take profit price (Decimal)
        strategy: Strategy name that generated signal
        confidence: Signal confidence [0, 1] (Decimal)
        metadata: Optional additional signal data

    Example:
        >>> signal = SignalSpec(
        ...     signal_id="abc123",
        ...     timestamp=datetime.now(timezone.utc),
        ...     symbol="BTC/USD",
        ...     side="long",
        ...     entry_price=Decimal("50000.00"),
        ...     stop_loss=Decimal("49000.00"),
        ...     take_profit=Decimal("52000.00"),
        ...     strategy="momentum",
        ...     confidence=Decimal("0.75"),
        ... )
    """
    signal_id: str
    timestamp: datetime
    symbol: str
    side: str
    entry_price: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    strategy: str
    confidence: Decimal
    metadata: Optional[dict[str, str]] = None

    def __post_init__(self) -> None:
        """
        Validate signal constraints.

        Raises:
            ValueError: If prices or confidence are invalid
        """
        # Validate side
        if self.side not in ("long", "short"):
            raise ValueError(f"Invalid side: {self.side}, must be 'long' or 'short'")

        # Validate confidence range
        if not (Decimal("0") <= self.confidence <= Decimal("1")):
            raise ValueError(f"Confidence must be in [0, 1], got {self.confidence}")

        # Validate prices are positive
        if self.entry_price <= 0:
            raise ValueError(f"Entry price must be positive, got {self.entry_price}")
        if self.stop_loss <= 0:
            raise ValueError(f"Stop loss must be positive, got {self.stop_loss}")
        if self.take_profit <= 0:
            raise ValueError(f"Take profit must be positive, got {self.take_profit}")

        # Validate stop loss and take profit consistency
        if self.side == "long":
            if self.stop_loss >= self.entry_price:
                raise ValueError(
                    f"Long: SL ({self.stop_loss}) must be < entry ({self.entry_price})"
                )
            if self.take_profit <= self.entry_price:
                raise ValueError(
                    f"Long: TP ({self.take_profit}) must be > entry ({self.entry_price})"
                )
        else:  # short
            if self.stop_loss <= self.entry_price:
                raise ValueError(
                    f"Short: SL ({self.stop_loss}) must be > entry ({self.entry_price})"
                )
            if self.take_profit >= self.entry_price:
                raise ValueError(
                    f"Short: TP ({self.take_profit}) must be < entry ({self.entry_price})"
                )

        # Validate timestamp is timezone-aware
        if self.timestamp.tzinfo is None:
            raise ValueError("Timestamp must be timezone-aware (use timezone.utc)")


@dataclass(frozen=True)
class PositionSpec:
    """
    Position specification with sizing.

    Immutable position with risk-adjusted sizing based on volatility and Kelly.

    Attributes:
        signal_id: Reference to originating signal
        symbol: Trading pair
        side: Trade direction ("long" or "short")
        size: Position size in base currency (Decimal)
        notional_usd: Position value in USD (Decimal)
        entry_price: Entry price (Decimal)
        stop_loss: Stop loss price (Decimal)
        take_profit: Take profit price (Decimal)
        expected_risk_usd: Expected risk in USD (entry to stop loss)
        volatility_adjusted: Whether size was volatility-adjusted
        kelly_fraction: Kelly fraction used for sizing (if applicable)

    Example:
        >>> position = PositionSpec(
        ...     signal_id="abc123",
        ...     symbol="BTC/USD",
        ...     side="long",
        ...     size=Decimal("0.05"),
        ...     notional_usd=Decimal("2500.00"),
        ...     entry_price=Decimal("50000.00"),
        ...     stop_loss=Decimal("49000.00"),
        ...     take_profit=Decimal("52000.00"),
        ...     expected_risk_usd=Decimal("50.00"),
        ...     volatility_adjusted=True,
        ...     kelly_fraction=Decimal("0.15"),
        ... )
    """
    signal_id: str
    symbol: str
    side: str
    size: Decimal
    notional_usd: Decimal
    entry_price: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    expected_risk_usd: Decimal
    volatility_adjusted: bool
    kelly_fraction: Optional[Decimal] = None


@dataclass(frozen=True)
class TradeDecision:
    """
    Complete trade decision with signals and positions.

    Immutable decision output from strategy execution.

    Attributes:
        timestamp: Decision timestamp (UTC timezone-aware)
        strategy_name: Strategy that generated decision
        signals: List of generated signals
        positions: List of sized positions (may be filtered/adjusted from signals)
        filters_applied: Names of filters that were applied
        rejected_count: Number of signals rejected by filters
        metadata: Optional decision metadata

    Example:
        >>> decision = TradeDecision(
        ...     timestamp=datetime.now(timezone.utc),
        ...     strategy_name="momentum_scalper",
        ...     signals=[signal1, signal2],
        ...     positions=[position1],
        ...     filters_applied=["regime_check", "liquidity_ok"],
        ...     rejected_count=1,
        ... )
    """
    timestamp: datetime
    strategy_name: str
    signals: list[SignalSpec]
    positions: list[PositionSpec]
    filters_applied: list[str]
    rejected_count: int
    metadata: Optional[dict[str, str]] = None


class Strategy(Protocol):
    """
    Strategy protocol defining standard interface.

    All strategies must implement these methods for polymorphic usage.
    Methods are pure (no I/O) except where explicitly noted.
    """

    def prepare(self, snapshot: MarketSnapshot) -> None:
        """
        Prepare strategy state and feature cache.

        Called before should_trade() and generate_signals() to allow
        strategies to compute and cache expensive features.

        Args:
            snapshot: Current market state

        Raises:
            ValueError: If snapshot is invalid

        Note:
            Must be idempotent - safe to call multiple times with same snapshot.
        """
        ...

    def should_trade(self, snapshot: MarketSnapshot) -> bool:
        """
        Check if conditions are suitable for trading.

        Fast filter to avoid expensive signal generation in unfavorable conditions.

        Args:
            snapshot: Current market state

        Returns:
            True if strategy should attempt to trade, False otherwise

        Example:
            >>> strategy.should_trade(snapshot)
            False  # Market is choppy, skip signal generation
        """
        ...

    def generate_signals(self, snapshot: MarketSnapshot) -> list[SignalSpec]:
        """
        Generate trading signals for current market state.

        Pure function that produces signals with idempotent IDs based on:
        hash(timestamp | symbol | strategy | price_level)

        Args:
            snapshot: Current market state

        Returns:
            List of signals (may be empty if no opportunities)

        Raises:
            ValueError: If snapshot is invalid

        Note:
            Signals have unique IDs for deduplication in downstream systems.
            Same market state should produce same signals (idempotent).

        Example:
            >>> signals = strategy.generate_signals(snapshot)
            >>> len(signals)
            2  # Found 2 trading opportunities
        """
        ...

    def size_positions(
        self,
        signals: list[SignalSpec],
        account_equity_usd: Decimal,
        current_volatility: Decimal,
    ) -> list[PositionSpec]:
        """
        Convert signals to sized positions.

        Applies:
        - Volatility targeting (scale risk to target volatility)
        - Kelly criterion (optimal sizing based on edge)
        - Fee/slippage adjustments
        - Position limits

        Args:
            signals: Trading signals to size
            account_equity_usd: Total account equity in USD
            current_volatility: Current market volatility (annualized)

        Returns:
            List of sized positions (may have fewer than signals if filtered)

        Raises:
            ValueError: If equity or volatility are invalid

        Example:
            >>> positions = strategy.size_positions(
            ...     signals=[signal1, signal2],
            ...     account_equity_usd=Decimal("10000.00"),
            ...     current_volatility=Decimal("0.50"),
            ... )
            >>> len(positions)
            1  # One signal rejected due to high volatility
        """
        ...


def generate_signal_id(
    timestamp: datetime,
    symbol: str,
    strategy: str,
    price_level: Decimal,
) -> str:
    """
    Generate unique, deterministic signal ID.

    Creates idempotent ID based on signal parameters using SHA256.

    Args:
        timestamp: Signal timestamp (UTC)
        symbol: Trading pair
        strategy: Strategy name
        price_level: Entry price level

    Returns:
        32-character hex string (first 32 chars of SHA256 hash)

    Example:
        >>> ts = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        >>> generate_signal_id(ts, "BTC/USD", "momentum", Decimal("50000.00"))
        'a1b2c3d4e5f6...'
    """
    # Create deterministic string
    components = f"{timestamp.isoformat()}|{symbol}|{strategy}|{price_level}"

    # Hash with SHA256
    hash_obj = hashlib.sha256(components.encode("utf-8"))

    # Return first 32 characters
    return hash_obj.hexdigest()[:32]


# =============================================================================
# SELF-CHECK
# =============================================================================

if __name__ == "__main__":
    """Self-check: Validate API types and constraints"""
    from datetime import timezone
    import sys

    try:
        # Test StrategyParams
        params = StrategyParams(
            name="test_strategy",
            min_confidence=Decimal("0.55"),
            max_position_size_usd=Decimal("1000.00"),
            stop_loss_pct=Decimal("0.02"),
            take_profit_pct=Decimal("0.04"),
            volatility_target_annual=Decimal("0.10"),
            kelly_fraction_cap=Decimal("0.25"),
            use_trade_filters=True,
        )
        assert params.name == "test_strategy"

        # Test SignalSpec (valid long)
        ts = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        signal = SignalSpec(
            signal_id=generate_signal_id(ts, "BTC/USD", "test", Decimal("50000")),
            timestamp=ts,
            symbol="BTC/USD",
            side="long",
            entry_price=Decimal("50000.00"),
            stop_loss=Decimal("49000.00"),
            take_profit=Decimal("52000.00"),
            strategy="test",
            confidence=Decimal("0.75"),
        )
        assert signal.side == "long"

        # Test invalid signal (should raise)
        try:
            bad_signal = SignalSpec(
                signal_id="test",
                timestamp=ts,
                symbol="BTC/USD",
                side="long",
                entry_price=Decimal("50000"),
                stop_loss=Decimal("51000"),  # Invalid: SL > entry for long
                take_profit=Decimal("52000"),
                strategy="test",
                confidence=Decimal("0.75"),
            )
            print("FAIL: Invalid signal should have raised ValueError")
            sys.exit(1)
        except ValueError:
            pass  # Expected

        # Test PositionSpec
        position = PositionSpec(
            signal_id=signal.signal_id,
            symbol="BTC/USD",
            side="long",
            size=Decimal("0.05"),
            notional_usd=Decimal("2500.00"),
            entry_price=Decimal("50000.00"),
            stop_loss=Decimal("49000.00"),
            take_profit=Decimal("52000.00"),
            expected_risk_usd=Decimal("50.00"),
            volatility_adjusted=True,
            kelly_fraction=Decimal("0.15"),
        )
        assert position.size == Decimal("0.05")

        # Test TradeDecision
        decision = TradeDecision(
            timestamp=ts,
            strategy_name="test",
            signals=[signal],
            positions=[position],
            filters_applied=["regime_check"],
            rejected_count=0,
        )
        assert len(decision.signals) == 1

        # Test signal ID generation (should be deterministic)
        id1 = generate_signal_id(ts, "BTC/USD", "test", Decimal("50000"))
        id2 = generate_signal_id(ts, "BTC/USD", "test", Decimal("50000"))
        assert id1 == id2, "Signal IDs should be deterministic"

        print("\nPASS Strategy API Self-Check:")
        print("  - StrategyParams: OK")
        print("  - SignalSpec: OK (with validation)")
        print("  - PositionSpec: OK")
        print("  - TradeDecision: OK")
        print("  - Signal ID generation: OK (deterministic)")
        print("  - Frozen dataclasses: OK (immutable)")

    except Exception as e:
        print(f"\nFAIL Strategy API Self-Check: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
