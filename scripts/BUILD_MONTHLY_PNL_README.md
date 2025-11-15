# Monthly P&L Aggregator - Documentation

**Script**: `scripts/build_monthly_pnl.py`
**Purpose**: Aggregate fills/trades to monthly P&L in Acquire.com Annual Snapshot format
**Author**: Crypto AI Bot Team

---

## Overview

This script reads trade data from multiple sources (Redis, CSV, or synthetic), calculates per-trade P&L with fees and slippage, and aggregates into monthly summaries with all required metrics for Acquire.com submission.

### Features

✅ **Multiple Data Sources**:
- Redis Cloud `trades:closed` stream (live/paper trading)
- CSV backtest results
- Synthetic data generator (fallback/demo)
- Auto-detect mode (tries sources in priority order)

✅ **Complete Metrics**:
- Starting/Ending Balance per month
- Net P&L with fees & slippage breakdown
- Monthly and Cumulative Return %
- Trade count and Win Rate %
- Detailed notes (pairs, avg trade P&L)

✅ **Exact Acquire.com Format**:
```
Month,Starting Balance,Deposits/Withdrawals,Net P&L ($),Fees ($),Slippage ($),
Ending Balance,Monthly Return %,Cumulative Return %,Trades,Win Rate %,Notes
```

---

## Quick Start

### Default (Auto-detect)
```bash
# Tries Redis → CSV → Synthetic
python scripts/build_monthly_pnl.py
```

### From Redis Cloud (Live/Paper Data)
```bash
# Uses Redis Cloud stream 'trades:closed'
python scripts/build_monthly_pnl.py --source redis
```

### From CSV Backtest Results
```bash
# Read from specific CSV file
python scripts/build_monthly_pnl.py --source csv --input out/trades_detailed_real.csv
```

### Generate 12-Month Synthetic
```bash
# For demo/testing when no real data available
python scripts/build_monthly_pnl.py --source synthetic --months 12
```

---

## Command-Line Options

### Required Arguments
None - all arguments are optional with sensible defaults

### Optional Arguments

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--source` | choice | `auto` | Data source: `redis`, `csv`, `synthetic`, `auto` |
| `--input` | string | - | CSV file path (required if `--source csv`) |
| `--output` | string | `/tmp/backtest_annual_snapshot.csv` | Output CSV path |
| `--months` | int | `12` | Number of months for synthetic data |
| `--debug` | flag | `false` | Enable debug logging |

### Examples

```bash
# Auto-detect with custom output path
python scripts/build_monthly_pnl.py --output reports/annual_pnl.csv

# CSV source with specific file
python scripts/build_monthly_pnl.py \
    --source csv \
    --input out/trades_detailed_real.csv \
    --output /tmp/monthly_pnl.csv

# Synthetic 6-month demo
python scripts/build_monthly_pnl.py \
    --source synthetic \
    --months 6 \
    --output demo_pnl.csv

# Redis with debug logging
python scripts/build_monthly_pnl.py --source redis --debug
```

---

## Environment Variables

Configure via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_URL` | Redis Cloud URL | Redis connection string with TLS |
| `REDIS_TLS_CERT` | `config/certs/redis_ca.pem` | Path to TLS CA certificate |
| `INITIAL_CAPITAL` | `10000` | Starting capital in USD |
| `FEE_BPS` | `5` | Default fee in basis points (0.05%) |
| `SLIP_BPS` | `2` | Default slippage in basis points (0.02%) |

### Example with Environment Variables

```bash
# Custom Redis connection
REDIS_URL="rediss://user:pass@host:port" \
REDIS_TLS_CERT="/path/to/cert.pem" \
INITIAL_CAPITAL=50000 \
python scripts/build_monthly_pnl.py --source redis

# Custom fees/slippage
FEE_BPS=10 \
SLIP_BPS=3 \
python scripts/build_monthly_pnl.py --source csv --input trades.csv
```

---

## Data Sources

### 1. Redis Cloud (Live/Paper Trading)

**Stream**: `trades:closed`

**Format**: JSON messages with fields:
```json
{
  "ts": 1234567890000,           // Unix timestamp (ms)
  "symbol": "BTC/USD",
  "side": "long",
  "entry_price": 50000.0,
  "exit_price": 51000.0,
  "size": 0.1,
  "pnl": 100.0,                  // Net P&L
  "fees": 5.0,
  "slippage": 2.0
}
```

**Connection**:
- URL: `rediss://default:****@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818`
- TLS: Required with CA certificate
- Cert: `config/certs/redis_ca.pem`

**Real Data Example** (Nov 2025):
- 200 trades from live/paper trading
- Multiple pairs (BTC, ETH, LINK, SOL, AVAX, MATIC)
- 60% win rate
- +15.55% return in 1 month

### 2. CSV Backtest Results

**Format**: CSV with columns:
```csv
exit_time,symbol,side,entry_price,exit_price,size,gross_pnl,fees,slippage,net_pnl
2025-10-01 12:00:00,BTC/USD,long,50000,51000,0.1,100,5,2,93
```

**Required Columns**:
- Timestamp: `exit_time`, `timestamp`, `close_time`, or `time`
- Symbol: `symbol` or `pair`
- Side: `side` (long/short)
- Prices: `entry_price`, `exit_price`
- Size: `size`, `quantity`, or `qty`

**Optional Columns** (will be calculated if missing):
- `gross_pnl`, `fees`, `slippage`, `net_pnl`

**Auto-detected CSV Files** (in priority order):
1. `out/trades_detailed_real.csv`
2. `out/trades.csv`
3. `reports/trades.csv`

### 3. Synthetic Data Generator

**Use Cases**:
- Demo when no real data available
- Testing aggregation logic
- Generating sample reports

**Algorithm**:
- Realistic win rate (~55%)
- Random position sizes (1-2% of capital)
- Multiple pairs (BTC/USD, ETH/USD)
- Monthly volatility (~10%)
- Kraken-standard fees (5bps) + slippage (2bps)

**Deterministic**: Uses fixed seed (42) for reproducibility

---

## Output Format

### CSV Structure

```csv
Month,Starting Balance,Deposits/Withdrawals,Net P&L ($),Fees ($),Slippage ($),Ending Balance,Monthly Return %,Cumulative Return %,Trades,Win Rate %,Notes
2025-10,"$10,000.00",$0.00,$+3.29,$1.35,$0.54,"$10,003.29",+0.03%,+0.03%,18,33.3%,"Pairs: BTC/USD, ETH/USD, Avg trade: $0.18"
```

### Column Descriptions

| Column | Format | Description |
|--------|--------|-------------|
| **Month** | `YYYY-MM` | Calendar month |
| **Starting Balance** | `$X,XXX.XX` | Balance at month start |
| **Deposits/Withdrawals** | `$X,XXX.XX` | Capital changes (always $0.00 for backtests) |
| **Net P&L ($)** | `$+X,XXX.XX` | Net profit/loss after all costs |
| **Fees ($)** | `$X,XXX.XX` | Trading fees (maker/taker) |
| **Slippage ($)** | `$X,XXX.XX` | Market impact costs |
| **Ending Balance** | `$X,XXX.XX` | Balance at month end |
| **Monthly Return %** | `+X.XX%` | Percentage return for the month |
| **Cumulative Return %** | `+X.XX%` | Total return from start |
| **Trades** | `123` | Number of trades executed |
| **Win Rate %** | `XX.X%` | Percentage of profitable trades |
| **Notes** | `text` | Additional details (pairs, avg P&L) |

---

## Per-Trade P&L Calculation

### Formula

```python
# Gross P&L
if side == "long":
    gross_pnl = (exit_price - entry_price) * size
else:  # short
    gross_pnl = (entry_price - exit_price) * size

# Fees (applied to both entry and exit)
entry_fee = entry_price * size * (fee_bps / 10000)
exit_fee = exit_price * size * (fee_bps / 10000)
total_fees = entry_fee + exit_fee

# Slippage (applied to both entry and exit)
entry_slip = entry_price * size * (slip_bps / 10000)
exit_slip = exit_price * size * (slip_bps / 10000)
total_slip = entry_slip + exit_slip

# Net P&L
net_pnl = gross_pnl - total_fees - total_slip
```

### Example Trade

**Setup**:
- Symbol: BTC/USD
- Side: Long
- Entry: $50,000
- Exit: $51,000
- Size: 0.1 BTC
- Fees: 5 bps (0.05%)
- Slippage: 2 bps (0.02%)

**Calculation**:
```
Gross P&L = ($51,000 - $50,000) × 0.1 = $100.00

Fees:
  Entry: $50,000 × 0.1 × 0.0005 = $2.50
  Exit:  $51,000 × 0.1 × 0.0005 = $2.55
  Total: $5.05

Slippage:
  Entry: $50,000 × 0.1 × 0.0002 = $1.00
  Exit:  $51,000 × 0.1 × 0.0002 = $1.02
  Total: $2.02

Net P&L = $100.00 - $5.05 - $2.02 = $92.93
```

---

## Monthly Aggregation Logic

### Process

1. **Load Trades**: Read from selected source
2. **Convert Timestamps**: Parse to datetime and extract month (YYYY-MM)
3. **Group by Month**: Aggregate all trades within each calendar month
4. **Calculate Metrics**:
   - Sum: `net_pnl`, `fees`, `slippage`
   - Count: `trades`, `wins`, `losses`
   - Compute: `win_rate`, `monthly_return`, `cumulative_return`
5. **Track Equity**: Maintain running balance month-over-month
6. **Export CSV**: Write to output file in Acquire.com format

### Equity Curve

```python
balance = initial_capital

for month in months:
    starting_balance = balance

    # Aggregate month trades
    net_pnl = sum(trade.net_pnl for trade in month_trades)

    # Update balance
    balance += net_pnl
    ending_balance = balance

    # Calculate returns
    monthly_return = (ending_balance - starting_balance) / starting_balance
    cumulative_return = (ending_balance - initial_capital) / initial_capital
```

---

## Real-World Results

### Redis Cloud Data (Nov 2025)

**Source**: Live/Paper trading stream `trades:closed`

**Summary**:
- Period: November 2025 (1 month)
- Trades: 200
- Pairs: BTC/USD, ETH/USD, LINK/USD, SOL/USD, AVAX/USD, MATIC/USD
- Starting: $10,000.00
- Ending: $11,555.39
- Return: +15.55%
- Win Rate: 60.0%
- Fees: $5,719.41
- Avg Trade: $7.78

**CSV Output**:
```csv
Month,Starting Balance,Deposits/Withdrawals,Net P&L ($),Fees ($),Slippage ($),Ending Balance,Monthly Return %,Cumulative Return %,Trades,Win Rate %,Notes
2025-11,"$10,000.00",$0.00,"$+1,555.39","$5,719.41",$0.00,"$11,555.39",+15.55%,+15.55%,200,60.0%,"Pairs: ETH/USD, LINK/USD, BTC/USD, MATIC/USD, SOL/USD, AVAX/USD, Avg trade: $7.78"
```

### CSV Backtest Data (Oct 2025)

**Source**: `out/trades_detailed_real.csv`

**Summary**:
- Period: October 2025 (1 month)
- Trades: 18
- Pairs: BTC/USD, ETH/USD
- Starting: $10,000.00
- Ending: $10,003.29
- Return: +0.03%
- Win Rate: 33.3%
- Fees: $1.35
- Slippage: $0.54
- Avg Trade: $0.18

**CSV Output**:
```csv
Month,Starting Balance,Deposits/Withdrawals,Net P&L ($),Fees ($),Slippage ($),Ending Balance,Monthly Return %,Cumulative Return %,Trades,Win Rate %,Notes
2025-10,"$10,000.00",$0.00,$+3.29,$1.35,$0.54,"$10,003.29",+0.03%,+0.03%,18,33.3%,"Pairs: ETH/USD, BTC/USD, Avg trade: $0.18"
```

---

## Validation & Testing

### Run All Tests

```bash
# Test CSV source
python scripts/build_monthly_pnl.py \
    --source csv \
    --input out/trades_detailed_real.csv \
    --output test_csv.csv

# Test Redis source
python scripts/build_monthly_pnl.py \
    --source redis \
    --output test_redis.csv

# Test synthetic
python scripts/build_monthly_pnl.py \
    --source synthetic \
    --months 12 \
    --output test_synthetic.csv

# Test auto-detect
python scripts/build_monthly_pnl.py \
    --output test_auto.csv
```

### Validate Output

```bash
# Check header
head -1 /tmp/backtest_annual_snapshot.csv

# Count rows (should be number of months + 1 header)
wc -l /tmp/backtest_annual_snapshot.csv

# View first 5 months
head -6 /tmp/backtest_annual_snapshot.csv
```

---

## Integration with Trading System

### Continuous P&L Tracking

**Setup**: Run as cron job or systemd service

```bash
# Cron example: Generate daily at midnight
0 0 * * * /path/to/conda/envs/crypto-bot/bin/python \
    /path/to/scripts/build_monthly_pnl.py \
    --source redis \
    --output /reports/daily/pnl_$(date +\%Y\%m\%d).csv
```

### Paper Trading Workflow

1. **Trading Engine**: Publishes fills to `trades:closed` stream
2. **PnL Aggregator**: Runs this script hourly/daily
3. **Reporting**: CSV uploaded to dashboard or sent to stakeholders
4. **Monitoring**: Track cumulative return vs targets

### Live Trading Workflow

1. **Execution Engine**: Real trades → `trades:closed` stream
2. **Risk Manager**: Monitors cumulative return and drawdown
3. **Monthly Reports**: Auto-generated for compliance/investors
4. **Acquire.com**: Direct upload of monthly P&L CSV

---

## Troubleshooting

### Redis Connection Failed

**Error**: `ConnectionError: Failed to connect to Redis`

**Solutions**:
1. Check `REDIS_URL` environment variable
2. Verify TLS certificate path: `REDIS_TLS_CERT`
3. Test connection: `redis-cli -u $REDIS_URL --tls --cacert $REDIS_TLS_CERT`
4. Check firewall/network access to Redis Cloud

### No Trades Found

**Error**: `No trades loaded - cannot generate report`

**Solutions**:
1. **Redis**: Check if `trades:closed` stream exists: `redis-cli XLEN trades:closed`
2. **CSV**: Verify file path exists: `ls -la out/trades_detailed_real.csv`
3. **Auto**: Run with `--debug` to see which sources were tried
4. **Fallback**: Use `--source synthetic` for demo data

### CSV Parse Error

**Error**: `ValueError: No timestamp column found in CSV`

**Solutions**:
1. Ensure CSV has one of: `exit_time`, `timestamp`, `close_time`, `time`
2. Check CSV format: `head -5 your_trades.csv`
3. Verify delimiter is comma (not semicolon or tab)
4. Ensure no extra header rows

### Incorrect Monthly Aggregation

**Error**: Months are wrong or missing

**Solutions**:
1. Check timestamp format in source data
2. Ensure timezones are handled (UTC recommended)
3. Verify trades span the expected date range
4. Run with `--debug` to see per-trade parsing

---

## Future Enhancements

### Planned Features

- [ ] Support for PostgreSQL database source
- [ ] Real-time streaming mode (continuous aggregation)
- [ ] Multi-currency support (EUR, GBP, crypto pairs)
- [ ] Tax reporting integration (capital gains)
- [ ] Benchmark comparison (S&P 500, BTC hold)
- [ ] Risk metrics (Sharpe, Sortino, Calmar ratios)
- [ ] Visual charts (equity curve, drawdown)
- [ ] Email/Slack notifications on completion

### Contributing

Pull requests welcome! Please:
1. Add tests for new data sources
2. Update this README
3. Follow PEP 8 style
4. Include example usage

---

## References

- **Acquire.com Annual Snapshot**: [Format Spec](https://acquire.com)
- **Redis Cloud**: [Documentation](https://redis.io/docs/stack/cloud/)
- **Kraken Fees**: [Fee Schedule](https://www.kraken.com/features/fee-schedule)
- **PRD-001**: Crypto-AI-Bot Core Intelligence Engine
- **PRD-002**: Signals-API Gateway & Middleware
- **PRD-003**: Signals-Site Front-End SaaS Portal

---

**Script**: `scripts/build_monthly_pnl.py`
**Version**: 1.0
**Author**: Crypto AI Bot Team
**License**: MIT
**Last Updated**: 2025-11-07
