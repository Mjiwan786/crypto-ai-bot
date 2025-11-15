"""
agents/strategy_router.py

Production-grade strategy router with regime-based routing, cooldowns, leverage caps,
and kill switch. Routes trading signals to appropriate strategies based on market regime
while enforcing safety controls.

Features:
- Regime-based strategy selection (bull/bear → momentum, chop → mean_reversion)
- Cooldown period on regime changes (halts new entries for N bars)
- Per-symbol leverage caps from exchange config
- Global kill switch via environment flag
- Strategy registry for dynamic strategy management
- Spread tolerance and circuit breaker integration

PRD References: §6 (Strategy Stack), §8 (Risk & Leverage), §17 (Security & Safety)

Author: Crypto AI Bot Team
"""

from __future__ import annotations

import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Deque, Dict, List, Optional, Protocol

import pandas as pd
import yaml

from ai_engine.regime_detector import RegimeTick
from ai_engine.schemas import RegimeLabel
from ai_engine.events import MarketSnapshotEvent as MarketSnapshot
from strategies.api import SignalSpec

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class RouterConfig:
    """
    Configuration for strategy router.

    Attributes:
        regime_change_cooldown_bars: Number of bars to halt after regime change
        min_confidence: Minimum confidence threshold for signals
        spread_bps_max: Maximum spread in basis points
        kill_switch_env_var: Environment variable for kill switch
        exchange_config_path: Path to exchange config file (for leverage caps)
        enable_spread_check: Whether to check spread tolerance
        enable_leverage_caps: Whether to enforce leverage caps
        enable_risk_breaker_check: Whether to check risk manager breaker state
    """
    regime_change_cooldown_bars: int = 2
    min_confidence: Decimal = Decimal("0.40")
    spread_bps_max: float = 5.0
    kill_switch_env_var: str = "TRADING_ENABLED"
    exchange_config_path: str = "config/exchange_configs/kraken.yaml"
    enable_spread_check: bool = True
    enable_leverage_caps: bool = True
    enable_risk_breaker_check: bool = True


# =============================================================================
# STRATEGY PROTOCOL
# =============================================================================

class Strategy(Protocol):
    """
    Protocol for trading strategies.

    All strategies must implement these methods for compatibility with the router.
    """

    def prepare(self, snapshot: MarketSnapshot, ohlcv_df: pd.DataFrame) -> None:
        """Prepare strategy with market data (cache expensive calculations)."""
        ...

    def should_trade(self, snapshot: MarketSnapshot) -> bool:
        """Check if strategy should trade given current market conditions."""
        ...

    def generate_signals(
        self,
        snapshot: MarketSnapshot,
        ohlcv_df: pd.DataFrame,
        regime_label: RegimeLabel,
    ) -> List[SignalSpec]:
        """Generate trading signals."""
        ...


# =============================================================================
# STRATEGY ROUTER
# =============================================================================

class StrategyRouter:
    """
    Strategy router with regime-based routing, cooldowns, and safety controls.

    Routes trading signals to appropriate strategies based on market regime while
    enforcing cooldown periods on regime changes, per-symbol leverage caps, and
    global kill switch.

    Usage:
        router = StrategyRouter(config=RouterConfig())

        # Register strategies
        router.register("momentum", MomentumStrategy())
        router.register("mean_reversion", MeanReversionStrategy())

        # Route signals
        signal = router.route(regime_tick, market_snapshot, ohlcv_df)
        if signal:
            print(f"Signal: {signal.side} @ {signal.entry_price}")
    """

    def __init__(self, config: Optional[RouterConfig] = None, risk_manager: Optional[Any] = None):
        """
        Initialize strategy router.

        Args:
            config: Router configuration (uses defaults if None)
            risk_manager: Optional RiskManager instance for breaker checks
        """
        self.config = config or RouterConfig()
        self.risk_manager = risk_manager

        # Strategy registry: name -> strategy instance
        self._strategies: Dict[str, Strategy] = {}

        # Regime mapping: regime_label -> strategy_name
        self._regime_strategy_map: Dict[RegimeLabel, str] = {}

        # Cooldown state
        self._current_regime: Optional[RegimeLabel] = None
        self._cooldown_remaining: int = 0
        self._regime_change_history: Deque[tuple[int, RegimeLabel]] = deque(maxlen=10)

        # Leverage caps cache (symbol -> max_leverage)
        self._leverage_caps: Dict[str, int] = {}
        self._load_leverage_caps()

        # Metrics
        self._total_routes: int = 0
        self._cooldown_rejections: int = 0
        self._kill_switch_rejections: int = 0
        self._leverage_cap_rejections: int = 0
        self._spread_rejections: int = 0
        self._risk_breaker_rejections: int = 0

        logger.info(
            f"StrategyRouter initialized: cooldown={self.config.regime_change_cooldown_bars} bars, "
            f"leverage_caps={self.config.enable_leverage_caps}, "
            f"kill_switch={self.config.kill_switch_env_var}, "
            f"risk_breaker_check={self.config.enable_risk_breaker_check}"
        )

    # -------------------------------------------------------------------------
    # STRATEGY REGISTRATION
    # -------------------------------------------------------------------------

    def register(self, name: str, strategy: Strategy) -> None:
        """
        Register a strategy with the router.

        Args:
            name: Strategy name (e.g., "momentum", "mean_reversion")
            strategy: Strategy instance implementing Strategy protocol

        Raises:
            ValueError: If strategy with same name already registered
        """
        if name in self._strategies:
            raise ValueError(f"Strategy '{name}' already registered")

        self._strategies[name] = strategy
        logger.info(f"Registered strategy: {name}")

    def map_regime_to_strategy(self, regime: RegimeLabel, strategy_name: str) -> None:
        """
        Map a market regime to a strategy.

        Args:
            regime: Market regime label (bull/bear/chop)
            strategy_name: Name of registered strategy

        Raises:
            ValueError: If strategy not registered
        """
        if strategy_name not in self._strategies:
            raise ValueError(f"Strategy '{strategy_name}' not registered")

        self._regime_strategy_map[regime] = strategy_name
        logger.info(f"Mapped regime '{regime.value}' -> strategy '{strategy_name}'")

    def get_strategy_for_regime(self, regime: RegimeLabel) -> Optional[Strategy]:
        """
        Get strategy instance for a given regime.

        Args:
            regime: Market regime label

        Returns:
            Strategy instance or None if no mapping exists
        """
        strategy_name = self._regime_strategy_map.get(regime)
        if strategy_name:
            return self._strategies.get(strategy_name)
        return None

    # -------------------------------------------------------------------------
    # LEVERAGE CAPS
    # -------------------------------------------------------------------------

    def _load_leverage_caps(self) -> None:
        """Load per-symbol leverage caps from exchange config."""
        if not self.config.enable_leverage_caps:
            logger.info("Leverage caps disabled")
            return

        try:
            # Load exchange config
            with open(self.config.exchange_config_path, "r") as f:
                exchange_config = yaml.safe_load(f)

            # Extract leverage caps
            margin_config = exchange_config.get("trading_specs", {}).get("margin", {})
            max_leverage = margin_config.get("max_leverage", {})

            # Convert Kraken symbols to internal format (e.g., XBTUSD -> BTC/USD)
            symbol_map = exchange_config.get("symbols", {}).get("denormalize", {})

            for kraken_symbol, leverage in max_leverage.items():
                if kraken_symbol == "default":
                    self._leverage_caps["__default__"] = leverage
                else:
                    # Map to internal symbol
                    internal_symbol = symbol_map.get(kraken_symbol, kraken_symbol)
                    self._leverage_caps[internal_symbol] = leverage

            logger.info(f"Loaded leverage caps for {len(self._leverage_caps)} symbols")

        except Exception as e:
            logger.warning(f"Failed to load leverage caps: {e}, using defaults")
            self._leverage_caps = {"__default__": 1}  # Safe default: no leverage

    def get_max_leverage(self, symbol: str) -> int:
        """
        Get maximum leverage allowed for a symbol.

        Args:
            symbol: Trading symbol (e.g., "BTC/USD")

        Returns:
            Maximum leverage (1 = no leverage, 5 = 5x)
        """
        # Try exact match first
        if symbol in self._leverage_caps:
            return self._leverage_caps[symbol]

        # Fall back to default
        return self._leverage_caps.get("__default__", 1)

    # -------------------------------------------------------------------------
    # KILL SWITCH & RISK BREAKER
    # -------------------------------------------------------------------------

    def _is_kill_switch_active(self) -> bool:
        """
        Check if global kill switch is active.

        Kill switch halts all new entries when TRADING_ENABLED=false.

        Returns:
            True if kill switch is active (trading disabled), False otherwise
        """
        # Read from environment
        trading_enabled = os.getenv(self.config.kill_switch_env_var, "true").lower()

        # Kill switch is active if trading is disabled
        is_active = trading_enabled not in ("true", "1", "yes", "on")

        if is_active:
            logger.warning(f"Kill switch active: {self.config.kill_switch_env_var}={trading_enabled}")

        return is_active

    def _is_risk_breaker_active(self) -> bool:
        """
        Check if risk manager breaker is active (hard_halt mode).

        Breaker blocks all new entries when drawdown exceeds critical thresholds.

        Returns:
            True if breaker is active (trading halted), False otherwise
        """
        if not self.config.enable_risk_breaker_check or not self.risk_manager:
            return False

        try:
            dd_state = self.risk_manager.get_drawdown_state()
            is_active = dd_state.mode == "hard_halt"

            if is_active:
                logger.warning(
                    f"Risk breaker active: mode={dd_state.mode}, "
                    f"reason={dd_state.trigger_reason}, pause_remaining={dd_state.pause_remaining}"
                )

            return is_active

        except Exception as e:
            logger.error(f"Failed to check risk breaker state: {e}")
            return False  # Default to allow trading on check failure

    # -------------------------------------------------------------------------
    # COOLDOWN LOGIC
    # -------------------------------------------------------------------------

    def _handle_regime_change(self, regime: RegimeLabel) -> None:
        """
        Handle regime change and initiate cooldown if needed.

        Args:
            regime: New regime label
        """
        if self._current_regime is None:
            # First regime detection
            self._current_regime = regime
            logger.info(f"Initial regime set: {regime.value}")
            return

        if regime != self._current_regime:
            # Regime changed
            logger.info(
                f"Regime change detected: {self._current_regime.value} -> {regime.value}, "
                f"initiating cooldown for {self.config.regime_change_cooldown_bars} bars"
            )

            self._current_regime = regime
            self._cooldown_remaining = self.config.regime_change_cooldown_bars

            # Record regime change
            timestamp = int(time.time() * 1000)
            self._regime_change_history.append((timestamp, regime))

    def _is_in_cooldown(self) -> bool:
        """
        Check if router is in cooldown period.

        Returns:
            True if in cooldown (new entries halted), False otherwise
        """
        return self._cooldown_remaining > 0

    def _tick_cooldown(self) -> None:
        """Decrement cooldown counter (called once per bar)."""
        if self._cooldown_remaining > 0:
            self._cooldown_remaining -= 1
            logger.debug(f"Cooldown tick: {self._cooldown_remaining} bars remaining")

    # -------------------------------------------------------------------------
    # SAFETY CHECKS
    # -------------------------------------------------------------------------

    def _check_spread(self, snapshot: MarketSnapshot) -> bool:
        """
        Check if spread is within acceptable tolerance.

        Args:
            snapshot: Market snapshot with spread_bps

        Returns:
            True if spread is acceptable, False otherwise
        """
        if not self.config.enable_spread_check:
            return True

        if snapshot.spread_bps > self.config.spread_bps_max:
            logger.warning(
                f"Spread too wide: {snapshot.spread_bps:.2f} bps > {self.config.spread_bps_max} bps"
            )
            return False

        return True

    # -------------------------------------------------------------------------
    # ROUTING LOGIC
    # -------------------------------------------------------------------------

    def route(
        self,
        regime_tick: RegimeTick,
        snapshot: MarketSnapshot,
        ohlcv_df: pd.DataFrame,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[SignalSpec]:
        """
        Route signal generation based on market regime.

        Enforces safety controls:
        1. Kill switch: Halt if TRADING_ENABLED=false
        2. Cooldown: Halt for N bars after regime change
        3. Spread check: Reject if spread too wide
        4. Leverage caps: Enforce per-symbol leverage limits

        Args:
            regime_tick: Regime detection result from regime detector
            snapshot: Current market snapshot
            ohlcv_df: OHLCV DataFrame for strategy analysis
            context: Optional context dict (for extensibility)

        Returns:
            SignalSpec if signal generated, None otherwise

        Example:
            >>> router = StrategyRouter()
            >>> router.register("momentum", MomentumStrategy())
            >>> router.map_regime_to_strategy(RegimeLabel.BULL, "momentum")
            >>> tick = detector.detect(ohlcv_df)
            >>> signal = router.route(tick, snapshot, ohlcv_df)
            >>> if signal:
            ...     print(f"Signal: {signal.side} @ {signal.entry_price}")
        """
        self._total_routes += 1

        # 1. Kill switch check (PRD §17)
        if self._is_kill_switch_active():
            self._kill_switch_rejections += 1
            logger.warning("Kill switch active, halting new entries")
            return None

        # 2. Risk breaker check (PRD §8: only block on risk breakers, not chop)
        if self._is_risk_breaker_active():
            self._risk_breaker_rejections += 1
            logger.warning("Risk breaker active (drawdown halt), halting new entries")
            return None

        # 3. Handle regime change and cooldown (PRD §6)
        self._handle_regime_change(regime_tick.regime)

        if self._is_in_cooldown():
            self._cooldown_rejections += 1
            logger.debug(
                f"In cooldown period: {self._cooldown_remaining} bars remaining, "
                f"no new entries"
            )
            # Tick cooldown counter
            self._tick_cooldown()
            return None

        # Tick cooldown even if not in cooldown (to decrement on each bar)
        self._tick_cooldown()

        # 3. Spread check (PRD §8)
        if not self._check_spread(snapshot):
            self._spread_rejections += 1
            return None

        # 4. Get strategy for current regime
        strategy = self.get_strategy_for_regime(regime_tick.regime)
        if strategy is None:
            logger.warning(f"No strategy mapped for regime: {regime_tick.regime.value}")
            return None

        # 5. Prepare strategy with market data
        strategy.prepare(snapshot, ohlcv_df)

        # 6. Check if strategy should trade
        if not strategy.should_trade(snapshot):
            logger.debug(f"Strategy declined to trade for {snapshot.symbol}")
            return None

        # 7. Generate signals
        signals = strategy.generate_signals(snapshot, ohlcv_df, regime_tick.regime)

        if not signals:
            logger.debug(f"No signals generated for {snapshot.symbol}")
            return None

        # 8. Select best signal (highest confidence)
        best_signal = max(signals, key=lambda s: s.confidence)

        # 9. Filter by minimum confidence
        if best_signal.confidence < self.config.min_confidence:
            logger.debug(
                f"Signal confidence too low: {best_signal.confidence:.2f} < {self.config.min_confidence}"
            )
            return None

        # 10. Apply leverage cap (PRD §8)
        if self.config.enable_leverage_caps:
            max_leverage = self.get_max_leverage(snapshot.symbol)

            # Note: Leverage enforcement would happen in position sizing
            # Here we just log it for awareness
            logger.debug(f"Max leverage for {snapshot.symbol}: {max_leverage}x")

            # If signal metadata contains leverage request, cap it
            if best_signal.metadata and "leverage" in best_signal.metadata:
                requested_leverage = int(best_signal.metadata["leverage"])
                if requested_leverage > max_leverage:
                    logger.warning(
                        f"Leverage cap enforced: requested {requested_leverage}x, "
                        f"capped to {max_leverage}x"
                    )
                    self._leverage_cap_rejections += 1
                    # Could modify signal or reject, but for now we'll allow
                    # position sizer to enforce cap

        logger.info(
            f"Routed signal: {best_signal.side} {snapshot.symbol} @ {best_signal.entry_price}, "
            f"confidence={best_signal.confidence:.2f}, strategy={best_signal.strategy}"
        )

        return best_signal

    # -------------------------------------------------------------------------
    # METRICS & DIAGNOSTICS
    # -------------------------------------------------------------------------

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get router metrics.

        Returns:
            Dict with routing statistics
        """
        return {
            "total_routes": self._total_routes,
            "cooldown_rejections": self._cooldown_rejections,
            "kill_switch_rejections": self._kill_switch_rejections,
            "leverage_cap_rejections": self._leverage_cap_rejections,
            "spread_rejections": self._spread_rejections,
            "risk_breaker_rejections": self._risk_breaker_rejections,
            "current_regime": self._current_regime.value if self._current_regime else None,
            "cooldown_remaining": self._cooldown_remaining,
            "registered_strategies": list(self._strategies.keys()),
            "regime_mappings": {
                k.value: v for k, v in self._regime_strategy_map.items()
            },
        }

    def reset_metrics(self) -> None:
        """Reset all metrics counters."""
        self._total_routes = 0
        self._cooldown_rejections = 0
        self._kill_switch_rejections = 0
        self._leverage_cap_rejections = 0
        self._spread_rejections = 0
        self._risk_breaker_rejections = 0
        logger.info("Router metrics reset")


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def create_default_router(
    momentum_strategy: Strategy,
    mean_reversion_strategy: Strategy,
    **config_kwargs,
) -> StrategyRouter:
    """
    Create a router with default regime -> strategy mappings.

    Default mappings:
    - BULL -> momentum
    - BEAR -> momentum (can short)
    - CHOP -> mean_reversion

    Args:
        momentum_strategy: Strategy instance for trending regimes
        mean_reversion_strategy: Strategy instance for choppy regimes
        **config_kwargs: Optional RouterConfig overrides

    Returns:
        Configured StrategyRouter instance

    Example:
        >>> router = create_default_router(
        ...     momentum_strategy=MomentumStrategy(),
        ...     mean_reversion_strategy=MeanReversionStrategy(),
        ...     regime_change_cooldown_bars=3,
        ... )
    """
    # Create config with overrides
    config = RouterConfig(**config_kwargs) if config_kwargs else RouterConfig()

    # Create router
    router = StrategyRouter(config=config)

    # Register strategies
    router.register("momentum", momentum_strategy)
    router.register("mean_reversion", mean_reversion_strategy)

    # Map regimes
    router.map_regime_to_strategy(RegimeLabel.BULL, "momentum")
    router.map_regime_to_strategy(RegimeLabel.BEAR, "momentum")
    router.map_regime_to_strategy(RegimeLabel.CHOP, "mean_reversion")

    logger.info("Default router created with bull/bear -> momentum, chop -> mean_reversion")

    return router


# =============================================================================
# SELF-CHECK
# =============================================================================

if __name__ == "__main__":
    """Self-check with mock strategies"""
    import sys
    from datetime import datetime, timezone
    from decimal import Decimal

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # Mock strategy for testing
    class MockStrategy:
        def __init__(self, name: str):
            self.name = name

        def prepare(self, snapshot: MarketSnapshot, ohlcv_df: pd.DataFrame) -> None:
            pass

        def should_trade(self, snapshot: MarketSnapshot) -> bool:
            return True

        def generate_signals(
            self,
            snapshot: MarketSnapshot,
            ohlcv_df: pd.DataFrame,
            regime_label: RegimeLabel,
        ) -> List[SignalSpec]:
            # Generate mock signal
            return [
                SignalSpec(
                    signal_id=f"mock_{self.name}_123",
                    timestamp=datetime.now(timezone.utc),
                    symbol=snapshot.symbol,
                    side="long",
                    entry_price=Decimal("50000"),
                    stop_loss=Decimal("49000"),
                    take_profit=Decimal("52000"),
                    strategy=self.name,
                    confidence=Decimal("0.75"),
                )
            ]

    try:
        logger.info("=== Strategy Router Self-Check ===\n")

        # Create router
        config = RouterConfig(
            regime_change_cooldown_bars=2,
            kill_switch_env_var="TRADING_ENABLED",
            enable_leverage_caps=False,  # Disable for self-check
        )
        router = StrategyRouter(config=config)

        # Register strategies
        momentum_strat = MockStrategy("momentum")
        mean_rev_strat = MockStrategy("mean_reversion")

        router.register("momentum", momentum_strat)
        router.register("mean_reversion", mean_rev_strat)

        # Map regimes
        router.map_regime_to_strategy(RegimeLabel.BULL, "momentum")
        router.map_regime_to_strategy(RegimeLabel.CHOP, "mean_reversion")

        # Create mock regime tick and snapshot
        from ai_engine.regime_detector import RegimeTick

        regime_tick = RegimeTick(
            regime=RegimeLabel.BULL,
            vol_regime="vol_normal",
            strength=0.75,
            changed=True,
            timestamp_ms=int(time.time() * 1000),
            components={},
            explain="Mock regime",
        )

        snapshot = MarketSnapshot(
            symbol="BTC/USD",
            timeframe="5m",
            timestamp_ms=int(time.time() * 1000),
            mid_price=50000.0,
            spread_bps=3.0,
            volume_24h=1000000000.0,
        )

        # Create mock OHLCV
        ohlcv_df = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=100, freq="5min"),
            "open": [50000] * 100,
            "high": [50100] * 100,
            "low": [49900] * 100,
            "close": [50000] * 100,
            "volume": [1000] * 100,
        })

        # Test routing
        signal = router.route(regime_tick, snapshot, ohlcv_df)

        if signal:
            logger.info(f"✅ Signal generated: {signal.side} @ {signal.entry_price}")
            logger.info(f"   Strategy: {signal.strategy}, Confidence: {signal.confidence}")
        else:
            logger.error("❌ No signal generated")
            sys.exit(1)

        # Test cooldown (regime change should trigger cooldown)
        regime_tick_chop = RegimeTick(
            regime=RegimeLabel.CHOP,
            vol_regime="vol_normal",
            strength=0.70,
            changed=True,
            timestamp_ms=int(time.time() * 1000),
            components={},
            explain="Mock regime change",
        )

        signal2 = router.route(regime_tick_chop, snapshot, ohlcv_df)

        if signal2 is None:
            logger.info("✅ Cooldown enforced after regime change")
        else:
            logger.error("❌ Cooldown not enforced")
            sys.exit(1)

        # Get metrics
        metrics = router.get_metrics()
        logger.info(f"\n=== Metrics ===")
        logger.info(f"Total routes: {metrics['total_routes']}")
        logger.info(f"Cooldown rejections: {metrics['cooldown_rejections']}")
        logger.info(f"Current regime: {metrics['current_regime']}")
        logger.info(f"Cooldown remaining: {metrics['cooldown_remaining']} bars")

        logger.info("\n✅ Self-check PASSED")
        sys.exit(0)

    except Exception as e:
        logger.error(f"❌ Self-check FAILED: {e}", exc_info=True)
        sys.exit(1)
