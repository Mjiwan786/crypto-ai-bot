"""
tests/unit/test_backtest_exporter.py - Unit tests for backtest exporter

Tests the per-pair backtest export functionality including:
- Schema validation
- Conversion from runner format to export format
- JSON serialization
- Timezone handling

Author: Crypto AI Bot Team
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from backtests.schema import (
    BacktestFile,
    EquityPoint,
    Trade,
    TradeSide,
    ExitReason,
    normalize_symbol,
    get_backtest_file_path,
)
from backtests.exporter import (
    convert_equity_point,
    convert_trade,
    convert_backtest_result,
)
from backtests.metrics import (
    EquityPoint as RunnerEquityPoint,
    Trade as RunnerTrade,
    BacktestMetrics,
)
from backtests.runner import BacktestResult, BacktestConfig


# =============================================================================
# SCHEMA VALIDATION TESTS
# =============================================================================

def test_equity_point_schema():
    """Test EquityPoint schema validation"""
    # Valid equity point
    point = EquityPoint(
        ts=datetime(2025, 11, 15, 12, 0, 0, tzinfo=timezone.utc),
        equity=10500.0,
        balance=9500.0,
        unrealized_pnl=1000.0,
    )

    assert point.ts.tzinfo is not None
    assert point.equity == 10500.0
    assert point.balance == 9500.0
    assert point.unrealized_pnl == 1000.0


def test_equity_point_requires_utc():
    """Test that EquityPoint requires timezone-aware timestamps"""
    with pytest.raises(ValueError, match="must be timezone-aware"):
        EquityPoint(
            ts=datetime(2025, 11, 15, 12, 0, 0),  # No timezone
            equity=10500.0,
        )


def test_trade_schema():
    """Test Trade schema validation"""
    # Valid trade
    trade = Trade(
        id=1,
        ts_entry=datetime(2025, 11, 15, 12, 0, 0, tzinfo=timezone.utc),
        ts_exit=datetime(2025, 11, 15, 14, 0, 0, tzinfo=timezone.utc),
        side=TradeSide.LONG,
        entry_price=43250.0,
        exit_price=43500.0,
        size=0.02,
        net_pnl=4.50,
        signal="scalper",
        exit_reason=ExitReason.TAKE_PROFIT,
    )

    assert trade.id == 1
    assert trade.side == TradeSide.LONG
    assert trade.net_pnl == 4.50
    assert trade.exit_reason == ExitReason.TAKE_PROFIT


def test_trade_validates_timestamps():
    """Test that Trade validates entry < exit"""
    with pytest.raises(ValueError, match="Exit timestamp must be after entry"):
        Trade(
            id=1,
            ts_entry=datetime(2025, 11, 15, 14, 0, 0, tzinfo=timezone.utc),
            ts_exit=datetime(2025, 11, 15, 12, 0, 0, tzinfo=timezone.utc),  # Before entry!
            side=TradeSide.LONG,
            entry_price=43250.0,
            exit_price=43500.0,
            size=0.02,
            net_pnl=4.50,
        )


def test_backtest_file_schema():
    """Test BacktestFile schema validation"""
    # Valid backtest file
    backtest = BacktestFile(
        symbol="BTC/USD",
        symbol_id="BTC-USD",
        timeframe="1h",
        start_ts=datetime(2025, 8, 1, 0, 0, 0, tzinfo=timezone.utc),
        end_ts=datetime(2025, 11, 15, 23, 59, 59, tzinfo=timezone.utc),
        equity_curve=[
            EquityPoint(
                ts=datetime(2025, 8, 1, 0, 0, 0, tzinfo=timezone.utc),
                equity=10000.0,
                balance=10000.0,
            ),
        ],
        trades=[
            Trade(
                id=1,
                ts_entry=datetime(2025, 8, 1, 12, 0, 0, tzinfo=timezone.utc),
                ts_exit=datetime(2025, 8, 1, 14, 0, 0, tzinfo=timezone.utc),
                side=TradeSide.LONG,
                entry_price=43250.0,
                exit_price=43500.0,
                size=0.02,
                net_pnl=4.50,
            ),
        ],
        initial_capital=10000.0,
        final_equity=10500.0,
        total_return_pct=5.0,
        sharpe_ratio=1.8,
        max_drawdown_pct=-2.5,
        win_rate_pct=55.0,
        total_trades=1,
        profit_factor=1.6,
    )

    assert backtest.symbol == "BTC/USD"
    assert backtest.symbol_id == "BTC-USD"
    assert backtest.total_trades == 1
    assert len(backtest.equity_curve) == 1
    assert len(backtest.trades) == 1


def test_backtest_file_rejects_slash_in_symbol_id():
    """Test that symbol_id must use dash separator"""
    with pytest.raises(ValueError, match="must use dash separator"):
        BacktestFile(
            symbol="BTC/USD",
            symbol_id="BTC/USD",  # Should be "BTC-USD"
            timeframe="1h",
            start_ts=datetime(2025, 8, 1, 0, 0, 0, tzinfo=timezone.utc),
            end_ts=datetime(2025, 11, 15, 23, 59, 59, tzinfo=timezone.utc),
            equity_curve=[],
            trades=[],
            initial_capital=10000.0,
            final_equity=10000.0,
            total_return_pct=0.0,
            sharpe_ratio=0.0,
            max_drawdown_pct=0.0,
            win_rate_pct=0.0,
            total_trades=0,
            profit_factor=0.0,
        )


# =============================================================================
# CONVERSION TESTS
# =============================================================================

def test_convert_equity_point():
    """Test conversion from runner EquityPoint to export EquityPoint"""
    runner_point = RunnerEquityPoint(
        timestamp=datetime(2025, 11, 15, 12, 0, 0, tzinfo=timezone.utc),
        equity=Decimal("10500.00"),
        cash=Decimal("9500.00"),
        position_value=Decimal("1000.00"),
        pnl=Decimal("500.00"),
    )

    export_point = convert_equity_point(runner_point)

    assert export_point.ts == runner_point.timestamp
    assert export_point.equity == 10500.0
    assert export_point.balance == 9500.0
    assert export_point.unrealized_pnl == 1000.0


def test_convert_equity_point_adds_utc():
    """Test that conversion adds UTC timezone if missing"""
    runner_point = RunnerEquityPoint(
        timestamp=datetime(2025, 11, 15, 12, 0, 0),  # No timezone
        equity=Decimal("10500.00"),
        cash=Decimal("9500.00"),
        position_value=Decimal("1000.00"),
        pnl=Decimal("500.00"),
    )

    export_point = convert_equity_point(runner_point)

    assert export_point.ts.tzinfo is not None
    assert export_point.ts.tzinfo == timezone.utc


def test_convert_trade():
    """Test conversion from runner Trade to export Trade"""
    runner_trade = RunnerTrade(
        entry_time=datetime(2025, 11, 15, 12, 0, 0, tzinfo=timezone.utc),
        exit_time=datetime(2025, 11, 15, 14, 0, 0, tzinfo=timezone.utc),
        pair="BTC/USD",
        side="long",
        entry_price=Decimal("43250.00"),
        exit_price=Decimal("43500.00"),
        size=Decimal("0.02"),
        pnl=Decimal("4.50"),
        pnl_pct=Decimal("0.52"),
        fees=Decimal("0.50"),
        strategy="scalper",
    )

    export_trade = convert_trade(runner_trade, trade_id=1, cumulative_pnl=4.50)

    assert export_trade.id == 1
    assert export_trade.side == TradeSide.LONG
    assert export_trade.entry_price == 43250.0
    assert export_trade.exit_price == 43500.0
    assert export_trade.size == 0.02
    assert export_trade.net_pnl == 4.50
    assert export_trade.cumulative_pnl == 4.50
    assert export_trade.signal == "scalper"
    assert export_trade.exit_reason == ExitReason.TAKE_PROFIT  # Inferred from positive P&L


def test_convert_trade_infers_exit_reason():
    """Test that exit reason is inferred from P&L"""
    # Positive P&L -> take profit
    runner_trade_win = RunnerTrade(
        entry_time=datetime(2025, 11, 15, 12, 0, 0, tzinfo=timezone.utc),
        exit_time=datetime(2025, 11, 15, 14, 0, 0, tzinfo=timezone.utc),
        pair="BTC/USD",
        side="long",
        entry_price=Decimal("43250.00"),
        exit_price=Decimal("43500.00"),
        size=Decimal("0.02"),
        pnl=Decimal("4.50"),
        pnl_pct=Decimal("0.52"),
        fees=Decimal("0.50"),
        strategy="scalper",
    )

    export_trade_win = convert_trade(runner_trade_win, trade_id=1, cumulative_pnl=4.50)
    assert export_trade_win.exit_reason == ExitReason.TAKE_PROFIT

    # Negative P&L -> stop loss
    runner_trade_loss = RunnerTrade(
        entry_time=datetime(2025, 11, 15, 12, 0, 0, tzinfo=timezone.utc),
        exit_time=datetime(2025, 11, 15, 14, 0, 0, tzinfo=timezone.utc),
        pair="BTC/USD",
        side="long",
        entry_price=Decimal("43250.00"),
        exit_price=Decimal("43000.00"),
        size=Decimal("0.02"),
        pnl=Decimal("-5.00"),
        pnl_pct=Decimal("-0.58"),
        fees=Decimal("0.50"),
        strategy="scalper",
    )

    export_trade_loss = convert_trade(runner_trade_loss, trade_id=2, cumulative_pnl=-0.50)
    assert export_trade_loss.exit_reason == ExitReason.STOP_LOSS


# =============================================================================
# HELPER FUNCTION TESTS
# =============================================================================

def test_normalize_symbol():
    """Test symbol normalization"""
    assert normalize_symbol("BTC/USD") == "BTC-USD"
    assert normalize_symbol("ETH/USD") == "ETH-USD"
    assert normalize_symbol("SOL/USD") == "SOL-USD"
    assert normalize_symbol("BTC-USD") == "BTC-USD"  # Already normalized


def test_get_backtest_file_path():
    """Test file path generation"""
    assert get_backtest_file_path("BTC/USD") == "data/backtests/BTC-USD.json"
    assert get_backtest_file_path("ETH/USD") == "data/backtests/ETH-USD.json"
    assert get_backtest_file_path("BTC/USD", "out/backtests") == "out/backtests/BTC-USD.json"


# =============================================================================
# JSON SERIALIZATION TESTS
# =============================================================================

def test_backtest_file_json_serialization():
    """Test that BacktestFile can be serialized to JSON"""
    backtest = BacktestFile(
        symbol="BTC/USD",
        symbol_id="BTC-USD",
        timeframe="1h",
        start_ts=datetime(2025, 8, 1, 0, 0, 0, tzinfo=timezone.utc),
        end_ts=datetime(2025, 11, 15, 23, 59, 59, tzinfo=timezone.utc),
        equity_curve=[
            EquityPoint(
                ts=datetime(2025, 8, 1, 0, 0, 0, tzinfo=timezone.utc),
                equity=10000.0,
                balance=10000.0,
            ),
        ],
        trades=[
            Trade(
                id=1,
                ts_entry=datetime(2025, 8, 1, 12, 0, 0, tzinfo=timezone.utc),
                ts_exit=datetime(2025, 8, 1, 14, 0, 0, tzinfo=timezone.utc),
                side=TradeSide.LONG,
                entry_price=43250.0,
                exit_price=43500.0,
                size=0.02,
                net_pnl=4.50,
            ),
        ],
        initial_capital=10000.0,
        final_equity=10500.0,
        total_return_pct=5.0,
        sharpe_ratio=1.8,
        max_drawdown_pct=-2.5,
        win_rate_pct=55.0,
        total_trades=1,
        profit_factor=1.6,
    )

    # Convert to dict (JSON-serializable)
    data = backtest.model_dump(mode='json')

    assert data["symbol"] == "BTC/USD"
    assert data["symbol_id"] == "BTC-USD"
    assert data["total_trades"] == 1
    assert len(data["equity_curve"]) == 1
    assert len(data["trades"]) == 1

    # Verify timestamps are ISO8601 strings
    assert isinstance(data["start_ts"], str)
    assert "2025-08-01T00:00:00" in data["start_ts"]
