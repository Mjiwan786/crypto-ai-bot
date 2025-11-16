#!/usr/bin/env python
"""
scripts/test_schema_only.py - Standalone schema validation test

Tests the backtest export schema without dependencies on the full runner.
This demonstrates that the schema is self-contained and can be used
independently in the API and UI repos.

Usage:
    python scripts/test_schema_only.py

Author: Crypto AI Bot Team
"""

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtests.schema import (
    BacktestFile,
    EquityPoint,
    Trade,
    TradeSide,
    ExitReason,
    normalize_symbol,
    get_backtest_file_path,
)

print("=" * 70)
print("BACKTEST SCHEMA VALIDATION TEST")
print("=" * 70)

# Test 1: Create a simple equity point
print("\n[1/5] Testing EquityPoint creation...")
equity_point = EquityPoint(
    ts=datetime(2025, 11, 15, 12, 0, 0, tzinfo=timezone.utc),
    equity=10500.0,
    balance=9500.0,
    unrealized_pnl=1000.0,
)
print(f"[OK] Created EquityPoint: {equity_point.equity} @ {equity_point.ts}")

# Test 2: Create a simple trade
print("\n[2/5] Testing Trade creation...")
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
print(f"[OK] Created Trade: {trade.side.value} {trade.size} @ {trade.entry_price} -> {trade.exit_price}")

# Test 3: Create a complete backtest file
print("\n[3/5] Testing BacktestFile creation...")
start_ts = datetime(2025, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
end_ts = datetime(2025, 11, 15, 23, 59, 59, tzinfo=timezone.utc)

backtest = BacktestFile(
    symbol="BTC/USD",
    symbol_id="BTC-USD",
    timeframe="1h",
    start_ts=start_ts,
    end_ts=end_ts,
    equity_curve=[
        EquityPoint(
            ts=start_ts,
            equity=10000.0,
            balance=10000.0,
        ),
        EquityPoint(
            ts=start_ts + timedelta(hours=1),
            equity=10050.0,
            balance=9500.0,
            unrealized_pnl=550.0,
        ),
        EquityPoint(
            ts=end_ts,
            equity=10500.0,
            balance=10500.0,
        ),
    ],
    trades=[trade],
    initial_capital=10000.0,
    final_equity=10500.0,
    total_return_pct=5.0,
    sharpe_ratio=1.8,
    max_drawdown_pct=-2.5,
    win_rate_pct=55.0,
    total_trades=1,
    profit_factor=1.6,
)
print(f"[OK] Created BacktestFile for {backtest.symbol}")
print(f"  - Period: {backtest.start_ts} to {backtest.end_ts}")
print(f"  - Equity points: {len(backtest.equity_curve)}")
print(f"  - Trades: {len(backtest.trades)}")
print(f"  - Total return: {backtest.total_return_pct}%")

# Test 4: JSON serialization
print("\n[4/5] Testing JSON serialization...")
data = backtest.model_dump(mode='json')
json_str = json.dumps(data, indent=2, default=str)
print(f"[OK] Serialized to JSON ({len(json_str)} bytes)")

# Test 5: Write to file
print("\n[5/5] Testing file export...")
output_dir = Path("data/backtests")
output_dir.mkdir(parents=True, exist_ok=True)

file_path = output_dir / f"{backtest.symbol_id}.json"
with open(file_path, 'w') as f:
    json.dump(data, f, indent=2, default=str)

print(f"[OK] Exported to: {file_path}")

# Verify file contents
with open(file_path, 'r') as f:
    loaded_data = json.load(f)

print(f"[OK] Verified file contents")
print(f"  - Symbol: {loaded_data['symbol']}")
print(f"  - Trades: {loaded_data['total_trades']}")
print(f"  - Sharpe: {loaded_data['sharpe_ratio']}")

# Test helper functions
print("\n[BONUS] Testing helper functions...")
print(f"normalize_symbol('BTC/USD') = {normalize_symbol('BTC/USD')}")
print(f"get_backtest_file_path('ETH/USD') = {get_backtest_file_path('ETH/USD')}")

print("\n" + "=" * 70)
print("SUCCESS: All schema tests passed!")
print("=" * 70)
print(f"\nGenerated file: {file_path.absolute()}")
print("\nYou can now:")
print("1. View the JSON file to see the schema structure")
print("2. Use this file to test signals-api endpoints")
print("3. Use this file to test signals-site UI components")
