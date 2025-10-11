# Quick Start Guide

Get up and running with the examples in under 5 minutes!

## Prerequisites (One-Time Setup)

### 1. Environment Setup

```bash
# Activate conda environment
conda activate crypto-bot

# Verify installation
python --version  # Should show Python 3.10+
```

### 2. Configure .env File

Create `.env` in project root (if not exists):

```bash
# Required for scan_and_publish.py
REDIS_URL=rediss://username:password@host:port/db

# Optional (for safety)
MODE=paper
LIVE_TRADING_CONFIRMATION=
```

**Redis Cloud Connection:**
```bash
REDIS_URL=rediss://default:your_password@redis-xxxxx.redns.redis-cloud.com:port/0
```

### 3. Install Optional Dependencies (for charts)

```bash
pip install matplotlib
```

## 5-Minute Examples

### Example 1: Generate and Backtest (No Setup Needed!)

```bash
# Activate environment
conda activate crypto-bot

# Run backtest with generated data
cd /path/to/crypto_ai_bot
python -m agents.examples.backtest_one_pair --generate-data --bars 1000

# Output:
# - Performance metrics printed to console
# - Equity chart saved as PNG
```

**That's it!** You just ran a complete backtest with:
- ✅ 1000 bars of generated data
- ✅ MA crossover strategy
- ✅ Full performance metrics
- ✅ Equity curve chart

**Expected Output:**
```
==========================================
BACKTEST RESULTS
==========================================
Initial Equity:  $10,000.00
Final Equity:    $10,523.45
Total Return:    +5.23%
==========================================
Total Trades:    28
Win Rate:        57.1%
Max Drawdown:    -3.45%
Sharpe Ratio:    1.23
==========================================

✅ Equity chart saved to: backtest_BTC_USD_20250111_143022.png
```

---

### Example 2: Real-Time Signal Generation (Requires Redis)

```bash
# Activate environment
conda activate crypto-bot

# Run for 30 seconds
python -m agents.examples.scan_and_publish --pair BTC/USD --duration 30

# Watch real-time signals!
```

**Expected Output:**
```
==========================================
SCAN AND PUBLISH EXAMPLE
==========================================
Pair: BTC/USD
Duration: 30s
Mode: PAPER (safe)
==========================================

✅ Connected to Redis Cloud

🎯 SIGNAL: BUY @ $50,245.32 (confidence: 75%)
   Reason: RSI oversold + MA crossover + high volume
   RSI: 28.5, Vol Ratio: 1.45
   ✅ Published to Redis

📊 Progress: 20 trades, 2 signals, Price: $50,312.15
```

---

## Common Scenarios

### Scenario: "I want to test my own strategy"

1. Copy `backtest_one_pair.py`
2. Modify the `SimpleStrategy` class
3. Run with `--generate-data`

```python
class YourStrategy:
    def generate_signal(self, prices):
        # Your logic here
        if your_condition:
            return 'buy'
        return 'hold'
```

---

### Scenario: "I have historical CSV data"

**CSV Format Required:**
```csv
timestamp,open,high,low,close,volume
1704067200,50000.00,50250.00,49950.00,50100.00,125.45
```

**Run Backtest:**
```bash
python -m agents.examples.backtest_one_pair --data your_data.csv
```

---

### Scenario: "I want to generate test data"

```bash
# Generate 2000 bars
python -m agents.examples.generate_sample_csv --bars 2000 --output my_data.csv

# Use it
python -m agents.examples.backtest_one_pair --data my_data.csv
```

---

## Troubleshooting (30 Seconds)

### Error: "REDIS_URL not set"
**Solution:** Add to `.env` file:
```bash
REDIS_URL=rediss://your-redis-cloud-url
```

### Error: "matplotlib not installed"
**Solution:**
```bash
conda activate crypto-bot
pip install matplotlib
```
(Charts will be skipped without matplotlib, but backtest still runs)

### Error: "ModuleNotFoundError"
**Solution:** Run from project root:
```bash
cd /path/to/crypto_ai_bot
python -m agents.examples.backtest_one_pair --generate-data
```

---

## Next Steps

**After running examples:**

1. **Explore the code** - Both examples are <400 lines and well-commented
2. **Try different parameters** - Use `--help` to see all options
3. **Integrate with main bot** - Examples show patterns used in production

**Learn More:**
- [Full Examples Documentation](README.md)
- [Protection Systems](../../protections/README.md)
- [Main Bot Documentation](../../README.md)

---

## Quick Reference

### Backtest Commands

```bash
# Basic (uses generated data)
python -m agents.examples.backtest_one_pair --generate-data

# With your CSV
python -m agents.examples.backtest_one_pair --data data.csv

# Custom parameters
python -m agents.examples.backtest_one_pair \
    --generate-data \
    --bars 2000 \
    --fast-ma 5 \
    --slow-ma 20 \
    --equity 50000
```

### Scan and Publish Commands

```bash
# Basic (30 seconds)
python -m agents.examples.scan_and_publish --duration 30

# Custom pair and volatility
python -m agents.examples.scan_and_publish \
    --pair ETH/USD \
    --duration 60 \
    --volatility 0.003
```

### Generate Data Commands

```bash
# Basic
python -m agents.examples.generate_sample_csv

# Custom
python -m agents.examples.generate_sample_csv \
    --bars 5000 \
    --base-price 3000 \
    --output eth_data.csv
```

---

## Success Checklist

- ✅ Conda environment activated
- ✅ Can run backtest with `--generate-data`
- ✅ Equity chart generated successfully
- ✅ (Optional) Redis connection working
- ✅ (Optional) Can scan and publish signals

**You're ready to go! 🚀**

---

**Questions?** Check [README.md](README.md) for detailed documentation.
