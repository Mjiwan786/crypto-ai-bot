# Minimal Usage Examples

Developer-friendly examples demonstrating core functionality with minimal setup.

## Quick Start

### Prerequisites

1. **Conda environment**:
   ```bash
   conda activate crypto-bot
   ```

2. **Environment variables** (`.env` file):
   ```bash
   REDIS_URL=rediss://your-redis-url
   MODE=paper
   ```

That's it! No additional setup required.

## Examples

### 1. Scan and Publish

Generate fake market data, analyze it, and publish trading signals to Redis.

**Features:**
- Creates realistic fake trade stream
- Runs simple signal analyst (RSI + MA crossover)
- Publishes signals to Redis in paper mode
- Real-time logging of trades and signals

**Quick Start:**
```bash
# 60-second demo
python -m agents.examples.scan_and_publish --pair BTC/USD --duration 60

# Custom parameters
python -m agents.examples.scan_and_publish \
    --pair ETH/USD \
    --duration 120 \
    --interval 5 \
    --volatility 0.002
```

**CLI Arguments:**
- `--pair`: Trading pair (default: BTC/USD)
- `--duration`: Run time in seconds (default: 60)
- `--interval`: Seconds between trades (default: 3.0)
- `--base-price`: Starting price (default: 50000.0)
- `--volatility`: Price volatility (default: 0.001)

**Output:**
```
==========================================
SCAN AND PUBLISH EXAMPLE
==========================================
Pair: BTC/USD
Duration: 60s
Mode: PAPER (safe)
==========================================

🎯 SIGNAL: BUY @ $50245.32 (confidence: 75%)
   Reason: RSI oversold + MA crossover + high volume
   RSI: 28.5, Vol Ratio: 1.45
   ✅ Published to Redis

📊 Progress: 40 trades, 3 signals, Price: $50312.15

✅ Example completed successfully
```

**What it demonstrates:**
- Fake market data generation
- Signal analysis with technical indicators
- Redis stream publishing
- Paper mode trading

---

### 2. Backtest One Pair

Run a backtest on historical or generated data and save an equity curve chart.

**Features:**
- Simple MA crossover strategy
- Performance metrics (returns, win rate, Sharpe ratio)
- Equity curve visualization
- Works with CSV data or generates fake data

**Quick Start:**
```bash
# Generate fake data (no CSV needed)
python -m agents.examples.backtest_one_pair --generate-data --bars 1000

# Use your own CSV data
python -m agents.examples.backtest_one_pair --data data/BTC_USD_1h.csv

# Custom strategy parameters
python -m agents.examples.backtest_one_pair \
    --generate-data \
    --bars 2000 \
    --fast-ma 5 \
    --slow-ma 20 \
    --equity 10000
```

**CLI Arguments:**

*Data Source:*
- `--data PATH`: CSV file with OHLCV data
- `--generate-data`: Generate fake data (no CSV needed)

*Data Generation:*
- `--bars`: Number of bars to generate (default: 1000)
- `--base-price`: Starting price (default: 50000)
- `--volatility`: Price volatility (default: 0.02)

*Trading Parameters:*
- `--pair`: Trading pair (default: BTC/USD)
- `--equity`: Initial equity (default: 10000)
- `--trade-size`: Position size (default: 1.0)
- `--commission`: Commission in bps (default: 10)

*Strategy:*
- `--strategy`: Strategy name (default: ma_crossover)
- `--fast-ma`: Fast MA period (default: 10)
- `--slow-ma`: Slow MA period (default: 30)

*Output:*
- `--output PATH`: Custom output path for chart

**Output:**
```
==========================================
BACKTEST RESULTS
==========================================
Initial Equity:  $10,000.00
Final Equity:    $11,245.67
Total Return:    +12.46%
==========================================
Total Trades:    42
Winning Trades:  26
Losing Trades:   16
Win Rate:        61.9%
==========================================
Max Drawdown:    -8.32%
Sharpe Ratio:    1.45
==========================================

✅ Equity chart saved to: backtest_BTC_USD_20250111_143022.png
```

**Chart Output:**

The script generates a two-panel PNG chart:
1. **Equity Curve**: Shows portfolio value over time with buy/sell markers
2. **Metrics Table**: Summary of performance statistics

**What it demonstrates:**
- Backtesting workflow
- Strategy implementation
- Performance calculation
- Chart generation with matplotlib

---

## CSV Data Format

If you want to use your own historical data with `backtest_one_pair.py`, use this CSV format:

```csv
timestamp,open,high,low,close,volume
1704067200,50000.00,50250.00,49950.00,50100.00,125.45
1704070800,50100.00,50300.00,50050.00,50200.00,98.23
...
```

**Fields:**
- `timestamp`: Unix timestamp (seconds since epoch)
- `open`: Opening price
- `high`: High price for the period
- `low`: Low price for the period
- `close`: Closing price
- `volume`: Trading volume

### Generate Sample CSV

Quick script to generate sample CSV data:

```python
import csv
import time
from datetime import datetime, timedelta

# Generate 1000 hourly bars
base_price = 50000
current_time = datetime.now() - timedelta(hours=1000)

with open('sample_data.csv', 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['timestamp', 'open', 'high', 'low', 'close', 'volume'])

    for i in range(1000):
        # Simple price movement
        open_price = base_price + (i % 100) * 10
        close_price = open_price + ((-1) ** i) * 50
        high_price = max(open_price, close_price) + 25
        low_price = min(open_price, close_price) - 25
        volume = 100 + (i % 50)

        writer.writerow([
            int(current_time.timestamp()),
            open_price,
            high_price,
            low_price,
            close_price,
            volume
        ])

        current_time += timedelta(hours=1)
```

---

## Troubleshooting

### Redis Connection Issues

**Problem:** `❌ Redis connection failed`

**Solutions:**
1. Check `.env` file has `REDIS_URL` set
2. Verify Redis URL format: `rediss://username:password@host:port/db`
3. Test connection: `redis-cli -u $REDIS_URL ping`
4. Check firewall/network settings

### Import Errors

**Problem:** `ModuleNotFoundError`

**Solutions:**
1. Activate conda environment: `conda activate crypto-bot`
2. Install dependencies: `pip install -r requirements.txt`
3. Run from project root directory

### Matplotlib Not Found (backtest_one_pair.py)

**Problem:** `matplotlib not installed, skipping chart generation`

**Solution:**
```bash
conda activate crypto-bot
pip install matplotlib
```

The backtest will still run and show metrics without matplotlib, just no chart will be saved.

---

## Advanced Usage

### Customize Signal Logic

Edit `scan_and_publish.py` to implement your own signal logic:

```python
class SimpleSignalAnalyst:
    def generate_signal(self, current_price: float) -> Dict:
        # Your custom logic here
        if your_condition:
            return {
                'action': 'buy',
                'confidence': 0.75,
                'reason': 'Your reason',
                'indicators': {...}
            }
```

### Implement Custom Strategy

Edit `backtest_one_pair.py` to add your strategy:

```python
class YourStrategy:
    def generate_signal(self, prices: List[float]) -> str:
        # Your strategy logic
        if your_buy_condition:
            return 'buy'
        elif your_sell_condition:
            return 'sell'
        return 'hold'
```

### Run Multiple Backtests

Batch test different parameters:

```bash
# Test different MA periods
for fast in 5 10 15; do
    for slow in 20 30 40; do
        python -m agents.examples.backtest_one_pair \
            --generate-data \
            --fast-ma $fast \
            --slow-ma $slow \
            --output "backtest_${fast}_${slow}.png"
    done
done
```

---

## Integration with Main Bot

These examples demonstrate patterns used in the full bot:

1. **scan_and_publish.py** → Similar to `agents/core/signal_processor.py`
2. **backtest_one_pair.py** → Similar to `scripts/backtest.py`

Use these examples to:
- Learn the codebase structure
- Test new ideas quickly
- Debug issues in isolation
- Prototype new features

---

## Performance Notes

**scan_and_publish.py:**
- Generates ~20 trades/minute (configurable)
- Redis latency typically <10ms
- Memory usage: ~50MB

**backtest_one_pair.py:**
- 1000 bars: ~1 second
- 10,000 bars: ~10 seconds
- Chart generation: ~2 seconds
- Memory usage: ~100MB for 10k bars

---

## Next Steps

After running these examples:

1. **Explore the full codebase**:
   - `agents/core/` - Core trading agents
   - `strategies/` - Trading strategies
   - `protections/` - Safety systems

2. **Run integration tests**:
   ```bash
   python -m pytest tests/
   ```

3. **Try the full bot**:
   ```bash
   python -m main run --mode paper
   ```

4. **Read the docs**:
   - [Architecture Guide](../../docs/ARCHITECTURE.md)
   - [Configuration Guide](../../config/README.md)
   - [Protection Systems](../../protections/README.md)

---

## Questions?

- Check logs for detailed error messages
- Review example code - it's heavily commented
- Check main bot documentation
- File an issue on GitHub

**Happy trading! 🚀**
