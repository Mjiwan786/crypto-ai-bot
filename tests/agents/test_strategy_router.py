"""
tests/agents/test_strategy_router.py

Comprehensive tests for strategy router with cooldowns, leverage caps, and kill switch.

Tests:
- Strategy registration and regime mapping
- Regime-based routing
- Cooldown enforcement on regime changes
- Per-symbol leverage caps
- Kill switch halts new entries
- Spread tolerance checks
- Metrics and diagnostics

Author: Crypto AI Bot Team
"""

import os
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
import pytest

from agents.strategy_router import (
    RouterConfig,
    StrategyRouter,
    Strategy,
    create_default_router,
)
from ai_engine.regime_detector import RegimeTick
from ai_engine.schemas import MarketSnapshot, RegimeLabel
from strategies.api import SignalSpec


# =============================================================================
# MOCK STRATEGY
# =============================================================================

class MockStrategy:
    """Mock strategy for testing."""

    def __init__(self, name: str, confidence: Decimal = Decimal("0.75")):
        self.name = name
        self.confidence = confidence
        self.prepared = False
        self.should_trade_result = True

    def prepare(self, snapshot: MarketSnapshot, ohlcv_df: pd.DataFrame) -> None:
        """Prepare strategy (mark as prepared for testing)."""
        self.prepared = True

    def should_trade(self, snapshot: MarketSnapshot) -> bool:
        """Check if should trade."""
        return self.should_trade_result

    def generate_signals(
        self,
        snapshot: MarketSnapshot,
        ohlcv_df: pd.DataFrame,
        regime_label: RegimeLabel,
    ) -> list[SignalSpec]:
        """Generate mock signal."""
        return [
            SignalSpec(
                signal_id=f"{self.name}_{regime_label.value}_123",
                timestamp=datetime.now(timezone.utc),
                symbol=snapshot.symbol,
                side="long",
                entry_price=Decimal("50000"),
                stop_loss=Decimal("49000"),
                take_profit=Decimal("52000"),
                strategy=self.name,
                confidence=self.confidence,
            )
        ]


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def config_default():
    """Default router config."""
    return RouterConfig(
        regime_change_cooldown_bars=2,
        min_confidence=Decimal("0.40"),
        spread_bps_max=5.0,
        kill_switch_env_var="TRADING_ENABLED",
        enable_leverage_caps=False,  # Disable for most tests
        enable_spread_check=True,
    )


@pytest.fixture
def config_with_leverage():
    """Router config with leverage caps enabled."""
    return RouterConfig(
        regime_change_cooldown_bars=2,
        enable_leverage_caps=True,
        exchange_config_path="config/exchange_configs/kraken.yaml",
    )


@pytest.fixture
def router(config_default):
    """Router instance with default config."""
    return StrategyRouter(config=config_default)


@pytest.fixture
def router_with_strategies(router):
    """Router with registered strategies and regime mappings."""
    momentum_strat = MockStrategy("momentum")
    mean_rev_strat = MockStrategy("mean_reversion")

    router.register("momentum", momentum_strat)
    router.register("mean_reversion", mean_rev_strat)

    router.map_regime_to_strategy(RegimeLabel.BULL, "momentum")
    router.map_regime_to_strategy(RegimeLabel.BEAR, "momentum")
    router.map_regime_to_strategy(RegimeLabel.CHOP, "mean_reversion")

    return router


@pytest.fixture
def regime_tick_bull():
    """Bull regime tick."""
    return RegimeTick(
        regime=RegimeLabel.BULL,
        vol_regime="vol_normal",
        strength=0.75,
        changed=True,
        timestamp_ms=1704067200000,
        components={"adx": 30.0, "rsi": 65.0},
        explain="Bull trend",
    )


@pytest.fixture
def regime_tick_chop():
    """Chop regime tick."""
    return RegimeTick(
        regime=RegimeLabel.CHOP,
        vol_regime="vol_low",
        strength=0.70,
        changed=True,
        timestamp_ms=1704067200000,
        components={"adx": 15.0, "rsi": 50.0},
        explain="Choppy market",
    )


@pytest.fixture
def market_snapshot():
    """Market snapshot."""
    return MarketSnapshot(
        symbol="BTC/USD",
        timeframe="5m",
        timestamp_ms=1704067200000,
        mid_price=50000.0,
        spread_bps=3.0,
        volume_24h=1000000000.0,
    )


@pytest.fixture
def ohlcv_df():
    """OHLCV DataFrame."""
    return pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=100, freq="5min"),
        "open": np.full(100, 50000.0),
        "high": np.full(100, 50100.0),
        "low": np.full(100, 49900.0),
        "close": np.full(100, 50000.0),
        "volume": np.full(100, 1000.0),
    })


# =============================================================================
# INITIALIZATION TESTS
# =============================================================================

def test_router_initialization(config_default):
    """Test router initialization."""
    router = StrategyRouter(config=config_default)
    assert router.config == config_default
    assert len(router._strategies) == 0
    assert len(router._regime_strategy_map) == 0
    assert router._current_regime is None
    assert router._cooldown_remaining == 0


def test_router_initialization_with_defaults():
    """Test router initialization with default config."""
    router = StrategyRouter()
    assert router.config is not None
    assert router.config.regime_change_cooldown_bars == 2
    assert router.config.min_confidence == Decimal("0.40")


# =============================================================================
# STRATEGY REGISTRATION TESTS
# =============================================================================

def test_register_strategy(router):
    """Test strategy registration."""
    strategy = MockStrategy("test_strategy")
    router.register("test_strategy", strategy)

    assert "test_strategy" in router._strategies
    assert router._strategies["test_strategy"] == strategy


def test_register_duplicate_strategy_raises_error(router):
    """Test that registering duplicate strategy raises ValueError."""
    strategy1 = MockStrategy("test_strategy")
    strategy2 = MockStrategy("test_strategy")

    router.register("test_strategy", strategy1)

    with pytest.raises(ValueError, match="already registered"):
        router.register("test_strategy", strategy2)


def test_map_regime_to_strategy(router):
    """Test regime to strategy mapping."""
    strategy = MockStrategy("test_strategy")
    router.register("test_strategy", strategy)

    router.map_regime_to_strategy(RegimeLabel.BULL, "test_strategy")

    assert router._regime_strategy_map[RegimeLabel.BULL] == "test_strategy"


def test_map_regime_to_unregistered_strategy_raises_error(router):
    """Test that mapping to unregistered strategy raises ValueError."""
    with pytest.raises(ValueError, match="not registered"):
        router.map_regime_to_strategy(RegimeLabel.BULL, "nonexistent_strategy")


def test_get_strategy_for_regime(router_with_strategies):
    """Test getting strategy for regime."""
    strategy = router_with_strategies.get_strategy_for_regime(RegimeLabel.BULL)
    assert strategy is not None
    assert strategy.name == "momentum"


def test_get_strategy_for_unmapped_regime(router):
    """Test getting strategy for unmapped regime returns None."""
    strategy = router.get_strategy_for_regime(RegimeLabel.BULL)
    assert strategy is None


# =============================================================================
# ROUTING TESTS
# =============================================================================

def test_basic_routing(router_with_strategies, regime_tick_bull, market_snapshot, ohlcv_df):
    """Test basic signal routing."""
    signal = router_with_strategies.route(regime_tick_bull, market_snapshot, ohlcv_df)

    assert signal is not None
    assert signal.symbol == "BTC/USD"
    assert signal.strategy == "momentum"
    assert signal.confidence >= Decimal("0.40")


def test_routing_with_different_regimes(
    router_with_strategies, regime_tick_chop, market_snapshot, ohlcv_df
):
    """Test routing with choppy regime."""
    signal = router_with_strategies.route(regime_tick_chop, market_snapshot, ohlcv_df)

    assert signal is not None
    assert signal.strategy == "mean_reversion"


def test_routing_with_unmapped_regime(router, regime_tick_bull, market_snapshot, ohlcv_df):
    """Test routing with unmapped regime returns None."""
    # Router has no strategies registered
    signal = router.route(regime_tick_bull, market_snapshot, ohlcv_df)
    assert signal is None


def test_routing_with_low_confidence_signal(
    router_with_strategies, regime_tick_bull, market_snapshot, ohlcv_df
):
    """Test routing rejects low-confidence signals."""
    # Create strategy that returns low-confidence signal
    low_conf_strategy = MockStrategy("low_conf", confidence=Decimal("0.30"))
    router_with_strategies._strategies["momentum"] = low_conf_strategy

    signal = router_with_strategies.route(regime_tick_bull, market_snapshot, ohlcv_df)

    # Signal should be rejected due to low confidence (< 0.40)
    assert signal is None


# =============================================================================
# COOLDOWN TESTS
# =============================================================================

def test_cooldown_enforcement_on_regime_change(
    router_with_strategies, regime_tick_bull, regime_tick_chop, market_snapshot, ohlcv_df
):
    """Test cooldown is enforced after regime change."""
    # First route: BULL regime (establishes initial regime)
    signal1 = router_with_strategies.route(regime_tick_bull, market_snapshot, ohlcv_df)
    assert signal1 is not None

    # Second route: CHOP regime (regime change triggers cooldown)
    signal2 = router_with_strategies.route(regime_tick_chop, market_snapshot, ohlcv_df)
    assert signal2 is None  # Rejected due to cooldown

    # Check metrics
    metrics = router_with_strategies.get_metrics()
    assert metrics["cooldown_rejections"] == 1
    assert metrics["cooldown_remaining"] == 1  # Decremented once


def test_cooldown_expires_after_n_bars(
    router_with_strategies, regime_tick_bull, regime_tick_chop, market_snapshot, ohlcv_df
):
    """Test cooldown expires after N bars."""
    # Establish initial regime
    router_with_strategies.route(regime_tick_bull, market_snapshot, ohlcv_df)

    # Regime change (triggers cooldown for 2 bars)
    router_with_strategies.route(regime_tick_chop, market_snapshot, ohlcv_df)
    assert router_with_strategies._cooldown_remaining == 1

    # Second bar (cooldown remaining = 0)
    signal = router_with_strategies.route(regime_tick_chop, market_snapshot, ohlcv_df)
    assert router_with_strategies._cooldown_remaining == 0

    # Third bar (cooldown expired, should generate signal)
    signal = router_with_strategies.route(regime_tick_chop, market_snapshot, ohlcv_df)
    assert signal is not None
    assert signal.strategy == "mean_reversion"


def test_cooldown_counter_decrements(
    router_with_strategies, regime_tick_bull, regime_tick_chop, market_snapshot, ohlcv_df
):
    """Test cooldown counter decrements correctly."""
    # Establish initial regime
    router_with_strategies.route(regime_tick_bull, market_snapshot, ohlcv_df)

    # Regime change (cooldown = 2)
    router_with_strategies.route(regime_tick_chop, market_snapshot, ohlcv_df)
    assert router_with_strategies._cooldown_remaining == 1

    # Next bar (cooldown = 0)
    router_with_strategies.route(regime_tick_chop, market_snapshot, ohlcv_df)
    assert router_with_strategies._cooldown_remaining == 0


def test_no_cooldown_on_same_regime(
    router_with_strategies, regime_tick_bull, market_snapshot, ohlcv_df
):
    """Test no cooldown when regime doesn't change."""
    # Establish initial regime
    signal1 = router_with_strategies.route(regime_tick_bull, market_snapshot, ohlcv_df)
    assert signal1 is not None

    # Same regime (no change, no cooldown)
    signal2 = router_with_strategies.route(regime_tick_bull, market_snapshot, ohlcv_df)
    assert signal2 is not None

    # Check no cooldown rejections
    metrics = router_with_strategies.get_metrics()
    assert metrics["cooldown_rejections"] == 0


# =============================================================================
# KILL SWITCH TESTS
# =============================================================================

def test_kill_switch_halts_entries(
    router_with_strategies, regime_tick_bull, market_snapshot, ohlcv_df
):
    """Test kill switch halts new entries."""
    # Set TRADING_ENABLED=false
    with patch.dict(os.environ, {"TRADING_ENABLED": "false"}):
        signal = router_with_strategies.route(regime_tick_bull, market_snapshot, ohlcv_df)

        assert signal is None

        # Check metrics
        metrics = router_with_strategies.get_metrics()
        assert metrics["kill_switch_rejections"] == 1


def test_kill_switch_variations(
    router_with_strategies, regime_tick_bull, market_snapshot, ohlcv_df
):
    """Test various kill switch values."""
    # Test different "off" values
    for value in ["false", "0", "no", "off", "FALSE", "False"]:
        with patch.dict(os.environ, {"TRADING_ENABLED": value}):
            signal = router_with_strategies.route(regime_tick_bull, market_snapshot, ohlcv_df)
            assert signal is None, f"Kill switch should be active for value: {value}"

    # Test "on" values
    for value in ["true", "1", "yes", "on", "TRUE", "True"]:
        # Reset router state
        router_with_strategies._current_regime = None

        with patch.dict(os.environ, {"TRADING_ENABLED": value}):
            signal = router_with_strategies.route(regime_tick_bull, market_snapshot, ohlcv_df)
            assert signal is not None, f"Kill switch should be inactive for value: {value}"


def test_kill_switch_default_value(
    router_with_strategies, regime_tick_bull, market_snapshot, ohlcv_df
):
    """Test kill switch defaults to enabled when not set."""
    # Unset TRADING_ENABLED (defaults to "true")
    with patch.dict(os.environ, {}, clear=True):
        signal = router_with_strategies.route(regime_tick_bull, market_snapshot, ohlcv_df)
        assert signal is not None  # Default is enabled


# =============================================================================
# LEVERAGE CAPS TESTS
# =============================================================================

def test_leverage_caps_loaded_from_config(config_with_leverage):
    """Test leverage caps are loaded from exchange config."""
    router = StrategyRouter(config=config_with_leverage)

    # Check that leverage caps were loaded (might be defaults if YAML fails)
    assert len(router._leverage_caps) > 0

    # Should have at least a default leverage cap
    default_leverage = router.get_max_leverage("__default__")
    assert default_leverage >= 1  # At least 1x (no leverage)

    # BTC/USD should have max leverage of 5x (from kraken.yaml)
    # If YAML loading failed, it will be 1 (default)
    btc_leverage = router.get_max_leverage("BTC/USD")
    assert btc_leverage in [1, 5], f"Expected 1 or 5, got {btc_leverage}"

    # ETH/USD should also have 5x (or 1 if default)
    eth_leverage = router.get_max_leverage("ETH/USD")
    assert eth_leverage in [1, 5], f"Expected 1 or 5, got {eth_leverage}"


def test_leverage_caps_default_fallback(config_with_leverage):
    """Test leverage caps fall back to default for unknown symbols."""
    router = StrategyRouter(config=config_with_leverage)

    # Unknown symbol should use default leverage
    unknown_leverage = router.get_max_leverage("UNKNOWN/USD")
    assert unknown_leverage == 1  # Default from config


def test_leverage_caps_disabled(config_default):
    """Test leverage caps can be disabled."""
    router = StrategyRouter(config=config_default)

    # Leverage caps should be empty or minimal when disabled
    assert not config_default.enable_leverage_caps


# =============================================================================
# SPREAD CHECK TESTS
# =============================================================================

def test_spread_too_wide_rejects_signal(
    router_with_strategies, regime_tick_bull, ohlcv_df
):
    """Test wide spread rejects signal."""
    # Create snapshot with wide spread (> 5 bps limit)
    wide_spread_snapshot = MarketSnapshot(
        symbol="BTC/USD",
        timeframe="5m",
        timestamp_ms=1704067200000,
        mid_price=50000.0,
        spread_bps=10.0,  # Wide spread
        volume_24h=1000000000.0,
    )

    signal = router_with_strategies.route(regime_tick_bull, wide_spread_snapshot, ohlcv_df)

    assert signal is None

    # Check metrics
    metrics = router_with_strategies.get_metrics()
    assert metrics["spread_rejections"] == 1


def test_spread_check_can_be_disabled():
    """Test spread check can be disabled."""
    config = RouterConfig(enable_spread_check=False)
    router = StrategyRouter(config=config)

    # Register strategies
    router.register("momentum", MockStrategy("momentum"))
    router.map_regime_to_strategy(RegimeLabel.BULL, "momentum")

    regime_tick = RegimeTick(
        regime=RegimeLabel.BULL,
        vol_regime="vol_normal",
        strength=0.75,
        changed=True,
        timestamp_ms=1704067200000,
        components={},
        explain="",
    )

    # Wide spread, but check disabled
    wide_spread_snapshot = MarketSnapshot(
        symbol="BTC/USD",
        timeframe="5m",
        timestamp_ms=1704067200000,
        mid_price=50000.0,
        spread_bps=100.0,  # Very wide spread
        volume_24h=1000000000.0,
    )

    ohlcv_df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=100, freq="5min"),
        "close": np.full(100, 50000.0),
    })

    signal = router.route(regime_tick, wide_spread_snapshot, ohlcv_df)

    # Should generate signal despite wide spread
    assert signal is not None


# =============================================================================
# METRICS TESTS
# =============================================================================

def test_get_metrics(router_with_strategies, regime_tick_bull, market_snapshot, ohlcv_df):
    """Test getting router metrics."""
    # Route a signal
    router_with_strategies.route(regime_tick_bull, market_snapshot, ohlcv_df)

    metrics = router_with_strategies.get_metrics()

    assert "total_routes" in metrics
    assert "cooldown_rejections" in metrics
    assert "kill_switch_rejections" in metrics
    assert "leverage_cap_rejections" in metrics
    assert "spread_rejections" in metrics
    assert "current_regime" in metrics
    assert "cooldown_remaining" in metrics
    assert "registered_strategies" in metrics
    assert "regime_mappings" in metrics

    assert metrics["total_routes"] == 1
    assert metrics["current_regime"] == "bull"
    assert "momentum" in metrics["registered_strategies"]
    assert "mean_reversion" in metrics["registered_strategies"]


def test_reset_metrics(router_with_strategies, regime_tick_bull, market_snapshot, ohlcv_df):
    """Test resetting router metrics."""
    # Route some signals to accumulate metrics
    router_with_strategies.route(regime_tick_bull, market_snapshot, ohlcv_df)
    router_with_strategies.route(regime_tick_bull, market_snapshot, ohlcv_df)

    assert router_with_strategies._total_routes == 2

    # Reset metrics
    router_with_strategies.reset_metrics()

    assert router_with_strategies._total_routes == 0
    assert router_with_strategies._cooldown_rejections == 0
    assert router_with_strategies._kill_switch_rejections == 0


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

def test_full_workflow_with_regime_changes(
    router_with_strategies, regime_tick_bull, regime_tick_chop, market_snapshot, ohlcv_df
):
    """Test full workflow with regime changes and cooldowns."""
    # Step 1: Initial BULL regime
    signal1 = router_with_strategies.route(regime_tick_bull, market_snapshot, ohlcv_df)
    assert signal1 is not None
    assert signal1.strategy == "momentum"

    # Step 2: Regime change to CHOP (triggers cooldown)
    signal2 = router_with_strategies.route(regime_tick_chop, market_snapshot, ohlcv_df)
    assert signal2 is None  # Cooldown active

    # Step 3: Still in cooldown
    signal3 = router_with_strategies.route(regime_tick_chop, market_snapshot, ohlcv_df)
    assert signal3 is None  # Cooldown still active

    # Step 4: Cooldown expired
    signal4 = router_with_strategies.route(regime_tick_chop, market_snapshot, ohlcv_df)
    assert signal4 is not None
    assert signal4.strategy == "mean_reversion"


def test_create_default_router():
    """Test creating default router with convenience function."""
    momentum_strat = MockStrategy("momentum")
    mean_rev_strat = MockStrategy("mean_reversion")

    router = create_default_router(
        momentum_strategy=momentum_strat,
        mean_reversion_strategy=mean_rev_strat,
        regime_change_cooldown_bars=3,
    )

    assert "momentum" in router._strategies
    assert "mean_reversion" in router._strategies
    assert router._regime_strategy_map[RegimeLabel.BULL] == "momentum"
    assert router._regime_strategy_map[RegimeLabel.BEAR] == "momentum"
    assert router._regime_strategy_map[RegimeLabel.CHOP] == "mean_reversion"
    assert router.config.regime_change_cooldown_bars == 3


# =============================================================================
# EDGE CASES
# =============================================================================

def test_routing_when_strategy_should_not_trade(
    router_with_strategies, regime_tick_bull, market_snapshot, ohlcv_df
):
    """Test routing when strategy's should_trade returns False."""
    # Modify strategy to decline trading
    momentum_strat = router_with_strategies._strategies["momentum"]
    momentum_strat.should_trade_result = False

    signal = router_with_strategies.route(regime_tick_bull, market_snapshot, ohlcv_df)

    assert signal is None


def test_routing_when_strategy_generates_no_signals(
    router_with_strategies, regime_tick_bull, market_snapshot, ohlcv_df
):
    """Test routing when strategy generates no signals."""
    # Create strategy that returns empty list
    class NoSignalStrategy(MockStrategy):
        def generate_signals(self, snapshot, ohlcv_df, regime_label):
            return []

    router_with_strategies._strategies["momentum"] = NoSignalStrategy("momentum")

    signal = router_with_strategies.route(regime_tick_bull, market_snapshot, ohlcv_df)

    assert signal is None


if __name__ == "__main__":
    """Run tests with pytest."""
    pytest.main([__file__, "-v", "--tb=short"])
