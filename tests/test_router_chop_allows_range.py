"""
Test: Strategy Router allows range/mean_reversion strategy in sideways/chop regime

Verifies that:
1. Sideways/chop regime routes to mean_reversion strategy
2. Signals are generated (not blocked by regime alone)
3. Only risk breaker (hard_halt) blocks entries, not chop regime
"""

import sys
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pandas as pd
import pytest

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agents.strategy_router import StrategyRouter, RouterConfig
from ai_engine.regime_detector import RegimeTick
from ai_engine.schemas import MarketSnapshot, RegimeLabel
from strategies.api import SignalSpec


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def chop_regime_tick():
    """Create a chop/sideways regime tick"""
    return RegimeTick(
        regime=RegimeLabel.CHOP,
        vol_regime="vol_normal",
        strength=0.65,
        changed=False,  # No regime change, no cooldown
        timestamp_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
        components={"adx": 15.0, "aroon_up": 50.0, "aroon_down": 50.0, "rsi": 50.0},
        explain="Sideways/chop market",
    )


@pytest.fixture
def market_snapshot():
    """Create a market snapshot with acceptable spread"""
    return MarketSnapshot(
        symbol="BTC/USD",
        timeframe="5m",
        timestamp_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
        mid_price=50000.0,
        spread_bps=3.0,  # Within acceptable range
        volume_24h=1000000000.0,
    )


@pytest.fixture
def ohlcv_df():
    """Create OHLCV DataFrame"""
    return pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=100, freq="5min"),
        "open": [50000] * 100,
        "high": [50100] * 100,
        "low": [49900] * 100,
        "close": [50000] * 100,
        "volume": [1000] * 100,
    })


@pytest.fixture
def mock_mean_reversion_strategy():
    """Create mock mean reversion strategy that generates signals"""
    strategy = MagicMock()
    strategy.prepare = MagicMock()
    strategy.should_trade = MagicMock(return_value=True)
    strategy.generate_signals = MagicMock(
        return_value=[
            SignalSpec(
                signal_id="test_signal_1",
                timestamp=datetime.now(timezone.utc),
                symbol="BTC/USD",
                side="long",
                entry_price=Decimal("50000"),
                stop_loss=Decimal("49500"),
                take_profit=Decimal("51000"),
                strategy="mean_reversion",
                confidence=Decimal("0.75"),
            )
        ]
    )
    return strategy


# =============================================================================
# TESTS
# =============================================================================

def test_chop_regime_routes_to_mean_reversion(
    chop_regime_tick, market_snapshot, ohlcv_df, mock_mean_reversion_strategy
):
    """Test 1: Chop regime routes to mean_reversion strategy"""
    # Create router with chop -> mean_reversion mapping
    router = StrategyRouter(config=RouterConfig(enable_risk_breaker_check=False))
    router.register("mean_reversion", mock_mean_reversion_strategy)
    router.map_regime_to_strategy(RegimeLabel.CHOP, "mean_reversion")

    # Route signal
    signal = router.route(chop_regime_tick, market_snapshot, ohlcv_df)

    # Verify signal generated
    assert signal is not None, "Signal should be generated in chop regime"
    assert signal.strategy == "mean_reversion", "Strategy should be mean_reversion"
    assert signal.symbol == "BTC/USD"

    # Verify strategy was called
    mock_mean_reversion_strategy.prepare.assert_called_once()
    mock_mean_reversion_strategy.should_trade.assert_called_once()
    mock_mean_reversion_strategy.generate_signals.assert_called_once()

    print("[PASS] Test 1: Chop regime successfully routes to mean_reversion")


def test_chop_not_blocked_without_breaker(
    chop_regime_tick, market_snapshot, ohlcv_df, mock_mean_reversion_strategy
):
    """Test 2: Chop regime does not block signals when breaker is inactive"""
    # Create router without risk manager (breaker disabled)
    router = StrategyRouter(config=RouterConfig(enable_risk_breaker_check=False))
    router.register("mean_reversion", mock_mean_reversion_strategy)
    router.map_regime_to_strategy(RegimeLabel.CHOP, "mean_reversion")

    # Route signal
    signal = router.route(chop_regime_tick, market_snapshot, ohlcv_df)

    # Verify signal generated (chop alone doesn't block)
    assert signal is not None, "Chop regime should NOT block signals"

    # Check metrics
    metrics = router.get_metrics()
    assert metrics["total_routes"] == 1
    assert metrics["risk_breaker_rejections"] == 0, "No breaker rejections without risk_manager"

    print("[PASS] Test 2: Chop regime does NOT block signals without breaker")


def test_multiple_chop_bars_generate_signals(
    chop_regime_tick, market_snapshot, ohlcv_df, mock_mean_reversion_strategy
):
    """Test 3: Multiple consecutive chop bars all generate signals"""
    router = StrategyRouter(config=RouterConfig(enable_risk_breaker_check=False))
    router.register("mean_reversion", mock_mean_reversion_strategy)
    router.map_regime_to_strategy(RegimeLabel.CHOP, "mean_reversion")

    # Simulate 5 consecutive chop bars
    for i in range(5):
        signal = router.route(chop_regime_tick, market_snapshot, ohlcv_df)
        assert signal is not None, f"Signal {i+1} should be generated in chop regime"

    # Verify all routes successful
    metrics = router.get_metrics()
    assert metrics["total_routes"] == 5
    assert metrics["cooldown_rejections"] == 0, "No cooldown in stable chop regime"

    print("[PASS] Test 3: Multiple chop bars generate signals consecutively")


if __name__ == "__main__":
    """Run tests standalone"""
    import logging

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # Create fixtures
    chop_tick = RegimeTick(
        regime=RegimeLabel.CHOP,
        vol_regime="vol_normal",
        strength=0.65,
        changed=False,
        timestamp_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
        components={"adx": 15.0, "aroon_up": 50.0, "aroon_down": 50.0, "rsi": 50.0},
        explain="Sideways/chop market",
    )

    snapshot = MarketSnapshot(
        symbol="BTC/USD",
        timeframe="5m",
        timestamp_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
        mid_price=50000.0,
        spread_bps=3.0,
        volume_24h=1000000000.0,
    )

    ohlcv = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=100, freq="5min"),
        "open": [50000] * 100,
        "high": [50100] * 100,
        "low": [49900] * 100,
        "close": [50000] * 100,
        "volume": [1000] * 100,
    })

    mock_strategy = MagicMock()
    mock_strategy.prepare = MagicMock()
    mock_strategy.should_trade = MagicMock(return_value=True)
    mock_strategy.generate_signals = MagicMock(
        return_value=[
            SignalSpec(
                signal_id="test_signal_1",
                timestamp=datetime.now(timezone.utc),
                symbol="BTC/USD",
                side="long",
                entry_price=Decimal("50000"),
                stop_loss=Decimal("49500"),
                take_profit=Decimal("51000"),
                strategy="mean_reversion",
                confidence=Decimal("0.75"),
            )
        ]
    )

    # Run tests
    print("=" * 90)
    print("ROUTER CHOP ALLOWS RANGE - STANDALONE TEST")
    print("=" * 90)
    print()

    try:
        test_chop_regime_routes_to_mean_reversion(chop_tick, snapshot, ohlcv, mock_strategy)
        test_chop_not_blocked_without_breaker(chop_tick, snapshot, ohlcv, mock_strategy)
        test_multiple_chop_bars_generate_signals(chop_tick, snapshot, ohlcv, mock_strategy)

        print()
        print("=" * 90)
        print("ALL TESTS PASSED")
        print("=" * 90)
        sys.exit(0)

    except AssertionError as e:
        print(f"\n[FAIL] Test failed: {e}")
        sys.exit(1)

    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
