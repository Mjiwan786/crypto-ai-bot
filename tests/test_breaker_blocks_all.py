"""
Test: Risk breaker blocks ALL new entries when active (hard_halt mode)

Verifies that:
1. When risk breaker is active (hard_halt), all new entries are blocked
2. Breaker blocks entries regardless of regime (bull/bear/chop)
3. Breaker overrides all other routing logic
4. Metrics correctly track breaker rejections
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
from agents.risk_manager import DrawdownState
from ai_engine.regime_detector import RegimeTick
from ai_engine.schemas import MarketSnapshot, RegimeLabel
from strategies.api import SignalSpec


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_risk_manager_halted():
    """Create mock risk manager in hard_halt mode (breaker active)"""
    risk_manager = MagicMock()
    risk_manager.get_drawdown_state = MagicMock(
        return_value=DrawdownState(
            daily_dd_pct=-18.0,
            rolling_dd_pct=-22.0,
            mode="hard_halt",  # Breaker active
            risk_multiplier=0.0,
            pause_remaining=10,
            trigger_reason="rolling_dd_exceeded_-20%",
        )
    )
    return risk_manager


@pytest.fixture
def mock_risk_manager_normal():
    """Create mock risk manager in normal mode (breaker inactive)"""
    risk_manager = MagicMock()
    risk_manager.get_drawdown_state = MagicMock(
        return_value=DrawdownState(
            daily_dd_pct=-2.0,
            rolling_dd_pct=-3.0,
            mode="normal",  # Breaker inactive
            risk_multiplier=1.0,
            pause_remaining=0,
            trigger_reason=None,
        )
    )
    return risk_manager


@pytest.fixture
def bull_regime_tick():
    """Create a bull regime tick"""
    return RegimeTick(
        regime=RegimeLabel.BULL,
        vol_regime="vol_normal",
        strength=0.80,
        changed=False,
        timestamp_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
        components={"adx": 30.0, "aroon_up": 80.0, "aroon_down": 20.0, "rsi": 65.0},
        explain="Strong bull trend",
    )


@pytest.fixture
def chop_regime_tick():
    """Create a chop regime tick"""
    return RegimeTick(
        regime=RegimeLabel.CHOP,
        vol_regime="vol_normal",
        strength=0.65,
        changed=False,
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
        spread_bps=3.0,
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
def mock_momentum_strategy():
    """Create mock momentum strategy that generates signals"""
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
                take_profit=Decimal("51500"),
                strategy="momentum",
                confidence=Decimal("0.80"),
            )
        ]
    )
    return strategy


@pytest.fixture
def mock_mean_reversion_strategy():
    """Create mock mean reversion strategy that generates signals"""
    strategy = MagicMock()
    strategy.prepare = MagicMock()
    strategy.should_trade = MagicMock(return_value=True)
    strategy.generate_signals = MagicMock(
        return_value=[
            SignalSpec(
                signal_id="test_signal_2",
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

def test_breaker_blocks_bull_regime(
    mock_risk_manager_halted,
    bull_regime_tick,
    market_snapshot,
    ohlcv_df,
    mock_momentum_strategy,
):
    """Test 1: Breaker blocks entries in bull regime"""
    # Create router with risk manager in hard_halt mode
    router = StrategyRouter(
        config=RouterConfig(enable_risk_breaker_check=True),
        risk_manager=mock_risk_manager_halted,
    )
    router.register("momentum", mock_momentum_strategy)
    router.map_regime_to_strategy(RegimeLabel.BULL, "momentum")

    # Route signal
    signal = router.route(bull_regime_tick, market_snapshot, ohlcv_df)

    # Verify signal blocked
    assert signal is None, "Breaker should block signal in bull regime"

    # Verify metrics
    metrics = router.get_metrics()
    assert metrics["risk_breaker_rejections"] == 1, "Breaker rejection should be tracked"

    # Verify strategy was NOT called (blocked before routing)
    mock_momentum_strategy.prepare.assert_not_called()
    mock_momentum_strategy.should_trade.assert_not_called()
    mock_momentum_strategy.generate_signals.assert_not_called()

    print("[PASS] Test 1: Breaker blocks entries in bull regime")


def test_breaker_blocks_chop_regime(
    mock_risk_manager_halted,
    chop_regime_tick,
    market_snapshot,
    ohlcv_df,
    mock_mean_reversion_strategy,
):
    """Test 2: Breaker blocks entries in chop regime"""
    # Create router with risk manager in hard_halt mode
    router = StrategyRouter(
        config=RouterConfig(enable_risk_breaker_check=True),
        risk_manager=mock_risk_manager_halted,
    )
    router.register("mean_reversion", mock_mean_reversion_strategy)
    router.map_regime_to_strategy(RegimeLabel.CHOP, "mean_reversion")

    # Route signal
    signal = router.route(chop_regime_tick, market_snapshot, ohlcv_df)

    # Verify signal blocked
    assert signal is None, "Breaker should block signal in chop regime"

    # Verify metrics
    metrics = router.get_metrics()
    assert metrics["risk_breaker_rejections"] == 1, "Breaker rejection should be tracked"

    print("[PASS] Test 2: Breaker blocks entries in chop regime")


def test_normal_mode_allows_entries(
    mock_risk_manager_normal,
    bull_regime_tick,
    market_snapshot,
    ohlcv_df,
    mock_momentum_strategy,
):
    """Test 3: Normal mode (breaker inactive) allows entries"""
    # Create router with risk manager in normal mode
    router = StrategyRouter(
        config=RouterConfig(enable_risk_breaker_check=True),
        risk_manager=mock_risk_manager_normal,
    )
    router.register("momentum", mock_momentum_strategy)
    router.map_regime_to_strategy(RegimeLabel.BULL, "momentum")

    # Route signal
    signal = router.route(bull_regime_tick, market_snapshot, ohlcv_df)

    # Verify signal generated
    assert signal is not None, "Normal mode should allow signal"
    assert signal.strategy == "momentum"

    # Verify metrics
    metrics = router.get_metrics()
    assert metrics["risk_breaker_rejections"] == 0, "No breaker rejections in normal mode"

    # Verify strategy was called
    mock_momentum_strategy.prepare.assert_called_once()
    mock_momentum_strategy.should_trade.assert_called_once()
    mock_momentum_strategy.generate_signals.assert_called_once()

    print("[PASS] Test 3: Normal mode allows entries")


def test_breaker_blocks_multiple_attempts(
    mock_risk_manager_halted,
    bull_regime_tick,
    market_snapshot,
    ohlcv_df,
    mock_momentum_strategy,
):
    """Test 4: Breaker blocks multiple consecutive routing attempts"""
    router = StrategyRouter(
        config=RouterConfig(enable_risk_breaker_check=True),
        risk_manager=mock_risk_manager_halted,
    )
    router.register("momentum", mock_momentum_strategy)
    router.map_regime_to_strategy(RegimeLabel.BULL, "momentum")

    # Attempt 5 routes
    for i in range(5):
        signal = router.route(bull_regime_tick, market_snapshot, ohlcv_df)
        assert signal is None, f"Breaker should block attempt {i+1}"

    # Verify all rejections tracked
    metrics = router.get_metrics()
    assert metrics["total_routes"] == 5
    assert metrics["risk_breaker_rejections"] == 5, "All 5 attempts should be blocked by breaker"

    print("[PASS] Test 4: Breaker blocks multiple consecutive attempts")


if __name__ == "__main__":
    """Run tests standalone"""
    import logging

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # Create fixtures
    risk_mgr_halted = MagicMock()
    risk_mgr_halted.get_drawdown_state = MagicMock(
        return_value=DrawdownState(
            daily_dd_pct=-18.0,
            rolling_dd_pct=-22.0,
            mode="hard_halt",
            risk_multiplier=0.0,
            pause_remaining=10,
            trigger_reason="rolling_dd_exceeded_-20%",
        )
    )

    risk_mgr_normal = MagicMock()
    risk_mgr_normal.get_drawdown_state = MagicMock(
        return_value=DrawdownState(
            daily_dd_pct=-2.0,
            rolling_dd_pct=-3.0,
            mode="normal",
            risk_multiplier=1.0,
            pause_remaining=0,
            trigger_reason=None,
        )
    )

    bull_tick = RegimeTick(
        regime=RegimeLabel.BULL,
        vol_regime="vol_normal",
        strength=0.80,
        changed=False,
        timestamp_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
        components={"adx": 30.0, "aroon_up": 80.0, "aroon_down": 20.0, "rsi": 65.0},
        explain="Strong bull trend",
    )

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

    mock_momentum = MagicMock()
    mock_momentum.prepare = MagicMock()
    mock_momentum.should_trade = MagicMock(return_value=True)
    mock_momentum.generate_signals = MagicMock(
        return_value=[
            SignalSpec(
                signal_id="test_signal_1",
                timestamp=datetime.now(timezone.utc),
                symbol="BTC/USD",
                side="long",
                entry_price=Decimal("50000"),
                stop_loss=Decimal("49500"),
                take_profit=Decimal("51500"),
                strategy="momentum",
                confidence=Decimal("0.80"),
            )
        ]
    )

    mock_mean_rev = MagicMock()
    mock_mean_rev.prepare = MagicMock()
    mock_mean_rev.should_trade = MagicMock(return_value=True)
    mock_mean_rev.generate_signals = MagicMock(
        return_value=[
            SignalSpec(
                signal_id="test_signal_2",
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
    print("BREAKER BLOCKS ALL - STANDALONE TEST")
    print("=" * 90)
    print()

    try:
        test_breaker_blocks_bull_regime(risk_mgr_halted, bull_tick, snapshot, ohlcv, mock_momentum)
        test_breaker_blocks_chop_regime(risk_mgr_halted, chop_tick, snapshot, ohlcv, mock_mean_rev)
        test_normal_mode_allows_entries(risk_mgr_normal, bull_tick, snapshot, ohlcv, mock_momentum)
        test_breaker_blocks_multiple_attempts(risk_mgr_halted, bull_tick, snapshot, ohlcv, mock_momentum)

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
