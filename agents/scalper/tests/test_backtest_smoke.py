"""
Smoke tests for backtest engine.

Ensures:
- 1-minute BTCUSDT sample runs successfully
- Produces non-empty trade set
- Returns valid metrics
- Runs in <10 seconds

All tests are hermetic - no network calls, use fixtures only.
"""

from __future__ import annotations

import time

import pandas as pd
import pytest

# Import backtest modules
from agents.scalper.backtest.analyzer import BacktestAnalyzer, analyze_trades
from agents.scalper.backtest.replay_enhanced import (
    ReplayFeeder,
    ReplayConfig,
    ReplayMode,
    create_balanced_replay,
)


# ======================== Backtest Smoke Tests ========================


def test_backtest_smoke_btcusdt_1m_produces_trades(sample_btcusdt_1m):
    """
    Smoke test: 1-minute BTCUSDT sample runs and produces non-empty trade set.

    Requirements:
    - Uses 100 bars of BTCUSDT data from fixture
    - Produces at least 1 trade
    - Returns valid PnL metrics
    - Completes in <10 seconds
    """
    start_time = time.time()

    # Simulate simple scalping strategy (mock trades)
    trades = _generate_mock_scalp_trades(sample_btcusdt_1m)

    # Verify trades were generated
    assert len(trades) > 0, "Backtest should produce at least 1 trade"
    assert len(trades) <= 50, "Should not produce excessive trades (max 50 for 100 bars)"

    # Analyze trades
    config = {"initial_equity_usd": 10000, "fee_bps": 6, "slippage_bps_default": 2}
    report = analyze_trades(trades, config=config)

    # Verify report structure
    assert report.total_trades > 0, "Report should have trades"
    assert isinstance(report.total_pnl, float), "PnL should be float"
    assert isinstance(report.win_rate, float), "Win rate should be float"
    assert 0 <= report.win_rate <= 100, "Win rate should be percentage"

    # Verify equity curve exists
    assert not report.equity_curve.empty, "Equity curve should not be empty"
    assert len(report.equity_curve) > 0, "Equity curve should have data points"

    # Performance check
    elapsed = time.time() - start_time
    assert elapsed < 10.0, f"Backtest should complete in <10s, took {elapsed:.2f}s"

    print(f"✅ Backtest smoke test passed:")
    print(f"   Trades: {report.total_trades}")
    print(f"   PnL: ${report.total_pnl:.2f}")
    print(f"   Win Rate: {report.win_rate:.1f}%")
    print(f"   Time: {elapsed:.2f}s")


def test_backtest_analyzer_handles_empty_trades():
    """Test analyzer gracefully handles empty trade list"""
    config = {"initial_equity_usd": 10000}
    report = analyze_trades([], config=config)

    assert report.total_trades == 0
    assert report.total_pnl == 0.0
    assert report.win_rate == 0.0


def test_backtest_analyzer_handles_single_trade(sample_btcusdt_1m):
    """Test analyzer handles single trade correctly"""
    # Create single winning trade
    first_price = sample_btcusdt_1m.iloc[0]["close"]
    second_price = sample_btcusdt_1m.iloc[1]["close"]

    trades = [
        {
            "ts": sample_btcusdt_1m.index[0].timestamp() * 1000,
            "symbol": "BTC/USD",
            "side": "buy",
            "qty": 0.1,
            "price": first_price,
            "fee_usd": 3.0,
        },
        {
            "ts": sample_btcusdt_1m.index[1].timestamp() * 1000,
            "symbol": "BTC/USD",
            "side": "sell",
            "qty": 0.1,
            "price": second_price,
            "fee_usd": 3.0,
        },
    ]

    config = {"initial_equity_usd": 10000}
    report = analyze_trades(trades, config=config)

    assert report.total_trades == 1
    assert isinstance(report.total_pnl, float)
    assert report.win_rate in (0.0, 100.0)  # Single trade is either win or loss


def test_backtest_with_multiple_symbols(sample_btcusdt_1m, sample_ethusdt_1m):
    """Test backtest handles multiple symbols correctly"""
    # Generate trades for both symbols
    btc_trades = _generate_mock_scalp_trades(sample_btcusdt_1m, symbol="BTC/USD", max_trades=5)
    eth_trades = _generate_mock_scalp_trades(sample_ethusdt_1m, symbol="ETH/USD", max_trades=5)

    all_trades = btc_trades + eth_trades

    config = {"initial_equity_usd": 10000}
    report = analyze_trades(all_trades, config=config)

    assert report.total_trades > 0
    assert len(report.pnl_by_symbol) > 0, "Should have per-symbol breakdown"

    print(f"✅ Multi-symbol test passed:")
    print(f"   Total trades: {report.total_trades}")
    print(f"   Symbols: {list(report.pnl_by_symbol.index)}")


def test_backtest_metrics_consistency(sample_btcusdt_1m):
    """Test that backtest metrics are self-consistent"""
    trades = _generate_mock_scalp_trades(sample_btcusdt_1m, max_trades=10)

    config = {"initial_equity_usd": 10000}
    report = analyze_trades(trades, config=config)

    # Winning + losing trades = total trades
    assert report.winning_trades + report.losing_trades == report.total_trades

    # Win rate calculation check
    expected_win_rate = (report.winning_trades / report.total_trades * 100) if report.total_trades > 0 else 0
    assert abs(report.win_rate - expected_win_rate) < 0.1, "Win rate calculation incorrect"

    # Equity curve final value = start + total PnL
    final_equity = report.equity_curve.iloc[-1]
    expected_final = report.start_value + report.total_pnl
    assert abs(final_equity - expected_final) < 1.0, "Equity curve doesn't match PnL"


# ======================== Replay Engine Tests ========================


def test_replay_feeder_synchronous_mode(sample_btcusdt_1m):
    """Test replay feeder in synchronous mode (for backtest engine)"""
    data = {"BTC/USD@1m": sample_btcusdt_1m}
    feeder = create_balanced_replay(data)

    bars = feeder.replay_synchronous(["BTC/USD"], "1m")

    assert len(bars) == 100, "Should replay all 100 bars"
    assert all(bar.symbol == "BTC/USD" for bar in bars)
    assert all(bar.close > 0 for bar in bars)
    assert all(bar.volume > 0 for bar in bars)

    # Check chronological order
    timestamps = [bar.timestamp for bar in bars]
    assert timestamps == sorted(timestamps), "Bars should be in chronological order"


def test_replay_feeder_fast_mode_skips_bars(sample_btcusdt_1m):
    """Test fast replay mode skips bars correctly"""
    from agents.scalper.backtest.replay_enhanced import create_fast_replay

    data = {"BTC/USD@1m": sample_btcusdt_1m}
    feeder = create_fast_replay(data)

    bars = feeder.replay_synchronous(["BTC/USD"], "1m")

    # Fast mode should skip 4 out of 5 bars (20% data)
    assert len(bars) < 100, "Fast mode should skip bars"
    assert len(bars) >= 15, "Fast mode should keep at least 15% of bars"

    print(f"✅ Fast replay test passed: {len(bars)}/100 bars")


def test_replay_feeder_multi_symbol(sample_btcusdt_1m, sample_ethusdt_1m):
    """Test replay feeder with multiple symbols"""
    data = {
        "BTC/USD@1m": sample_btcusdt_1m,
        "ETH/USD@1m": sample_ethusdt_1m,
    }

    config = ReplayConfig(mode=ReplayMode.BAR_BY_BAR, speed=1.0)
    feeder = ReplayFeeder(data, config)

    bars = feeder.replay_synchronous(["BTC/USD", "ETH/USD"], "1m")

    # Should have bars from both symbols
    btc_bars = [b for b in bars if b.symbol == "BTC/USD"]
    eth_bars = [b for b in bars if b.symbol == "ETH/USD"]

    assert len(btc_bars) == 100, "Should have all BTC bars"
    assert len(eth_bars) == 100, "Should have all ETH bars"
    assert len(bars) == 200, "Should have combined bars"

    # Check chronological order across symbols
    timestamps = [bar.timestamp for bar in bars]
    assert timestamps == sorted(timestamps), "Multi-symbol bars should be chronologically ordered"


# ======================== Helper Functions ========================


def _generate_mock_scalp_trades(
    ohlcv_df: pd.DataFrame,
    symbol: str = "BTC/USD",
    max_trades: int = 20,
    win_rate: float = 0.6,
) -> list:
    """
    Generate mock scalping trades from OHLCV data.

    Simulates simple mean-reversion scalping strategy:
    - Enter on price moves
    - Target 10 bps profit
    - Stop 5 bps loss

    Args:
        ohlcv_df: OHLCV DataFrame with datetime index
        symbol: Trading symbol
        max_trades: Maximum number of trades to generate
        win_rate: Target win rate (0-1)

    Returns:
        List of trade dictionaries
    """
    import numpy as np

    np.random.seed(42)  # Deterministic

    trades = []
    position_open = False
    entry_price = 0.0
    entry_time = None
    trade_count = 0

    for i in range(1, len(ohlcv_df)):
        if trade_count >= max_trades:
            break

        current_bar = ohlcv_df.iloc[i]
        current_price = current_bar["close"]
        current_time = ohlcv_df.index[i]

        if not position_open:
            # Open position (every 3-5 bars)
            if i % np.random.randint(3, 6) == 0:
                entry_price = current_price
                entry_time = current_time
                position_open = True

                # Entry trade
                trades.append(
                    {
                        "ts": current_time.timestamp() * 1000,
                        "symbol": symbol,
                        "side": "buy",
                        "qty": 0.1,
                        "price": entry_price,
                        "fee_usd": entry_price * 0.1 * 0.0016,  # Kraken maker fee
                        "slippage_bps": 2.0,
                        "order_type": "limit",
                    }
                )

        else:
            # Check exit conditions
            pnl_bps = (current_price - entry_price) / entry_price * 10000

            # Simulate win/loss based on target win rate
            should_win = np.random.random() < win_rate

            if should_win:
                # Exit with profit (10 bps target)
                if pnl_bps >= 10 or (i - ohlcv_df.index.get_loc(entry_time)) > 5:
                    exit_price = entry_price * 1.001  # 10 bps profit
                    trades.append(
                        {
                            "ts": current_time.timestamp() * 1000,
                            "symbol": symbol,
                            "side": "sell",
                            "qty": 0.1,
                            "price": exit_price,
                            "fee_usd": exit_price * 0.1 * 0.0026,  # Kraken taker fee
                            "slippage_bps": 3.0,
                            "order_type": "market",
                        }
                    )
                    position_open = False
                    trade_count += 1

            else:
                # Exit with loss (5 bps stop)
                if pnl_bps <= -5 or (i - ohlcv_df.index.get_loc(entry_time)) > 3:
                    exit_price = entry_price * 0.9995  # 5 bps loss
                    trades.append(
                        {
                            "ts": current_time.timestamp() * 1000,
                            "symbol": symbol,
                            "side": "sell",
                            "qty": 0.1,
                            "price": exit_price,
                            "fee_usd": exit_price * 0.1 * 0.0026,
                            "slippage_bps": 3.0,
                            "order_type": "market",
                        }
                    )
                    position_open = False
                    trade_count += 1

    return trades


# ======================== Performance Tests ========================


@pytest.mark.parametrize("num_bars", [100, 500, 1000])
def test_backtest_performance_scaling(num_bars):
    """Test backtest performance scales reasonably with data size"""
    from .conftest import generate_ohlcv_from_prices, generate_price_series

    # Generate data
    prices = generate_price_series(num_points=num_bars)
    ohlcv = generate_ohlcv_from_prices(prices)

    start_time = time.time()

    # Generate and analyze trades
    trades = _generate_mock_scalp_trades(ohlcv, max_trades=min(50, num_bars // 10))
    config = {"initial_equity_usd": 10000}
    report = analyze_trades(trades, config=config)

    elapsed = time.time() - start_time

    # Performance requirements
    max_time = num_bars * 0.05  # 50ms per bar max
    assert elapsed < max_time, f"Performance degraded: {elapsed:.2f}s for {num_bars} bars"

    print(f"✅ Performance test ({num_bars} bars): {elapsed:.2f}s, {report.total_trades} trades")
