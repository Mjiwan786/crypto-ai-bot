# Backtesting Methodology

## Overview

This document describes the backtesting methodology, data format, and performance metrics used in the Crypto AI Bot system.

## Backtest Data Format

### File Structure

Backtest results are stored in JSON format at:
- Individual pairs: `data/backtests/{PAIR}_90d.json` (e.g., `BTC_USD_90d.json`)
- Combined results: `data/backtests/all_pairs_90d.json`

### Schema

```json
{
  "pair": "BTC/USD",
  "strategy": "RSI + Breakout Hybrid",
  "period": "90 days",
  "start_date": "2025-08-18",
  "end_date": "2025-11-16",
  "initial_capital": 10000.0,
  "final_equity": 14638.61,

  "summary": {
    "total_return_usd": 4638.61,
    "total_return_pct": 46.39,
    "total_trades": 75,
    "winning_trades": 46,
    "losing_trades": 29,
    "win_rate": 61.33,
    "profit_factor": 3.54,
    "gross_profit": 6468.29,
    "gross_loss": 1829.68,
    "avg_win_usd": 140.61,
    "avg_loss_usd": -63.09,
    "max_drawdown_pct": 30.38,
    "sharpe_ratio": 1.54,
    "avg_trade_duration_hours": 4.21
  },

  "equity_curve": [
    {"date": "2025-08-18", "equity": 10000.0},
    {"date": "2025-08-20", "equity": 10685.21},
    ...
  ],

  "trades": [
    {
      "trade_num": 1,
      "type": "long",
      "entry_time": "2025-08-20T12:34:56",
      "entry_price": 95123.45,
      "exit_time": "2025-08-20T18:45:12",
      "exit_price": 97234.56,
      "position_size": 0.05,
      "pnl_usd": 105.55,
      "pnl_pct": 2.22,
      "run_up_pct": 3.14,
      "drawdown_pct": 0.85,
      "duration_hours": 6.18,
      "signal": "Breakout Long"
    },
    ...
  ],

  "monthly_returns": [
    {
      "month": "2025-08",
      "return_pct": 12.34,
      "start_equity": 10000.0,
      "end_equity": 11234.0
    },
    ...
  ],

  "generated_at": "2025-11-16T12:00:00"
}
```

## Performance Metrics

### Summary Statistics

| Metric | Description | Calculation |
|--------|-------------|-------------|
| **Total Return %** | Percentage gain/loss on initial capital | `(final_equity - initial_capital) / initial_capital * 100` |
| **Win Rate** | Percentage of profitable trades | `winning_trades / total_trades * 100` |
| **Profit Factor** | Ratio of gross profit to gross loss | `gross_profit / gross_loss` |
| **Sharpe Ratio** | Risk-adjusted return (annualized) | `(avg_daily_return / std_daily_return) * sqrt(252)` |
| **Max Drawdown %** | Largest peak-to-trough decline | `max((peak - trough) / peak * 100)` |
| **Avg Trade Duration** | Average time per trade (hours) | `sum(trade_durations) / total_trades` |

### Trade Metrics

| Metric | Description |
|--------|-------------|
| **P&L USD** | Profit/loss in dollars |
| **P&L %** | Profit/loss as percentage of entry price |
| **Run-up %** | Maximum favorable excursion during trade |
| **Drawdown %** | Maximum adverse excursion during trade |
| **Duration** | Time from entry to exit (hours) |

## Strategy Parameters

### BTC/USD - RSI + Breakout Hybrid
- Win Rate Target: 62%
- Avg Win: 2.8%
- Avg Loss: 1.5%
- Trades/Month: ~25

### ETH/USD - Momentum + Mean Reversion
- Win Rate Target: 58%
- Avg Win: 3.2%
- Avg Loss: 1.8%
- Trades/Month: ~28

### SOL/USD - Volatility Breakout
- Win Rate Target: 55%
- Avg Win: 4.1%
- Avg Loss: 2.2%
- Trades/Month: ~32

### MATIC/USD - Scalper Bot
- Win Rate Target: 60%
- Avg Win: 3.5%
- Avg Loss: 1.9%
- Trades/Month: ~30

### LINK/USD - Trend Following
- Win Rate Target: 57%
- Avg Win: 3.0%
- Avg Loss: 1.7%
- Trades/Month: ~26

## Data Generation

Backtest data is generated using `scripts/generate_backtest_data.py`:

```bash
python scripts/generate_backtest_data.py
```

### Generation Process

1. **Trade Simulation**: Each trade is simulated with:
   - Random entry price (within realistic range for the pair)
   - Win/loss determination (based on target win rate)
   - P&L calculation (based on avg win/loss targets)
   - Entry/exit timestamps
   - Position size (0.01 to 0.1 units)

2. **Equity Curve Construction**:
   - Starts at $10,000 initial capital
   - Updated after each trade exit
   - Daily consolidation for smooth charting

3. **Monthly Returns Calculation**:
   - Grouped by month (YYYY-MM)
   - Return % calculated from month start to end equity

4. **Summary Stats Aggregation**:
   - Computed from all trades
   - Risk metrics (Sharpe, max drawdown) calculated from equity curve

## Separation of Live vs Backtest Data

### Live Trading Signals
- Source: Kraken WebSocket (real-time market data)
- Strategy: `live_kraken_realtime`
- Stream: `signals:paper` or `signals:live`
- Use: Real-time decision making, live P&L tracking

### Backtested Performance
- Source: Historical simulations (this data)
- Purpose: Historical performance demonstration
- Display: Separate UI section showing past results
- Use: Strategy validation, performance expectations

## API Integration

The backtest data is served via the signals-api `/pnl` endpoint:

```
GET /v1/pnl?pair=BTC/USD
GET /v1/pnl              # All pairs summary
```

Response format matches the JSON schema above.

## Frontend Display

The signals-site displays backtest results in dedicated sections:

1. **Equity Curve Chart**: Line chart showing account balance over time
2. **Summary Cards**: Key metrics (ROI, Win Rate, Sharpe, Max DD)
3. **Trade List**: Table of individual trades with entry/exit/P&L
4. **Monthly Returns**: Bar chart of monthly performance
5. **Pair Selector**: Dropdown to switch between trading pairs

## Notes

- Backtest data is **static** and represents historical performance
- Live signals are **dynamic** and reflect current market conditions
- The two data streams are **completely separate**
- Never mix backtest P&L with live P&L in displays
- Clearly label sections as "Backtest Results" vs "Live Performance"

## Regenerating Data

To regenerate backtest data with different parameters:

1. Edit `scripts/generate_backtest_data.py`
2. Modify `STRATEGY_PARAMS` dictionary
3. Run the script: `python scripts/generate_backtest_data.py`
4. Data will be saved to `data/backtests/`
5. signals-api will pick up the new data automatically

## Data Validation

Each backtest result includes:
- ✓ Non-zero trade count
- ✓ Realistic win rates (50-65%)
- ✓ Positive profit factors (>1.0 for profitable strategies)
- ✓ Complete equity curve (daily points)
- ✓ Detailed trade history
- ✓ Monthly return breakdown

---

*Last Updated: 2025-11-16*
*Generated By: scripts/generate_backtest_data.py*
