# STEP 8 — Quick Start Guide

## 🚀 Run Backtest in 1 Command

```bash
python scripts/run_backtest_v2.py --pairs BTC/USD --lookback 365
```

---

## ⚡ Common Commands

### Basic Backtest
```bash
python scripts/run_backtest_v2.py --pairs BTC/USD --lookback 365
```

### Multi-Pair
```bash
python scripts/run_backtest_v2.py --pairs BTC/USD,ETH/USD,SOL/USD --lookback 720
```

### With Reports
```bash
python scripts/run_backtest_v2.py \\
    --pairs BTC/USD \\
    --lookback 720 \\
    --report out/report.json \\
    --equity out/equity.csv
```

### Custom Parameters
```bash
python scripts/run_backtest_v2.py \\
    --pairs BTC/USD \\
    --tf 1h \\
    --lookback 180 \\
    --capital 50000 \\
    --fee-bps 10 \\
    --seed 42
```

---

## 📊 Key Metrics

- **Total Return**: Final capital - initial capital (%)
- **Profit Factor (PF)**: Gross profit / gross loss (> 2.0 = excellent)
- **Sharpe Ratio**: Risk-adjusted return (> 1.5 = good)
- **Max Drawdown (DD)**: Largest peak-to-trough decline (< 20% threshold)
- **Win Rate**: % of winning trades
- **Monthly ROI**: Returns aggregated by month

---

## 🧪 Run Tests

```bash
# All tests
pytest tests/test_backtest_math.py -v

# Determinism test
pytest tests/test_backtest_math.py::test_determinism_with_fixed_seed -v
```

---

## 🔧 CLI Options

| Option | Default | Description |
|--------|---------|-------------|
| `--pairs` | (required) | Trading pairs (comma-separated) |
| `--tf` | `5m` | Timeframe (1m, 5m, 15m, 1h, 4h, 1d) |
| `--lookback` | `720` | Days of historical data |
| `--capital` | `10000` | Initial capital |
| `--fee-bps` | `5` | Trading fees (basis points) |
| `--slip-bps` | `2` | Slippage (basis points) |
| `--seed` | `42` | Random seed (determinism) |
| `--max-dd` | `20.0` | Max drawdown threshold (%) |
| `--report` | - | JSON report output path |
| `--equity` | - | Equity CSV output path |
| `--debug` | `false` | Enable debug logging |

---

## 📁 Output Files

### JSON Report (`out/report.json`)
- Summary (pairs, dates, capital, return%)
- Monthly returns (2023-01, 2023-02, ...)
- Trade stats (total, wins, losses, win rate)
- Profit metrics (PF, avg win/loss, expectancy)
- Risk metrics (DD, Sharpe, Sortino, Calmar)
- Costs (total fees, fees%)

### Equity CSV (`out/equity.csv`)
- timestamp: Bar timestamp
- equity: Total equity
- cash: Available cash
- position_value: Current position value
- pnl: Cumulative P&L

---

## ❌ Common Issues

### "Max drawdown exceeds threshold"
```bash
# Increase threshold
--max-dd 30.0
```

### "Insufficient data"
- Need minimum 100 bars
- Increase `--lookback` or use higher `--tf`

### Import errors
```bash
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot
python -c "from backtests import BacktestRunner; print('OK')"
```

---

## ✅ Determinism Test

```bash
# Run twice with same seed
python scripts/run_backtest_v2.py --pairs BTC/USD --seed 42 --report out/run1.json
python scripts/run_backtest_v2.py --pairs BTC/USD --seed 42 --report out/run2.json

# Should be identical
diff out/run1.json out/run2.json
```

---

## 📖 Full Documentation

See: `STEP8_COMPLETE.md`

---

**Ready to backtest!** 📈
