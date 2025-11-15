# PnL Backfill Guide - Crypto AI Bot

**Bootstrap equity charts with historical fill data.**

## Overview

The backfill script generates historical equity data from past trades to provide a complete equity curve from day 1. This is useful for:

- **Bootstrapping dashboards** - Show complete equity history, not just recent data
- **Testing** - Validate PnL aggregator with known historical data
- **Migration** - Import data from legacy trading systems

## Quick Start

```bash
# Activate conda environment
conda activate crypto-bot

# Backfill from CSV
python scripts/backfill_pnl_from_fills.py --file data/fills/sample.csv --start-equity 10000

# Backfill from JSONL
python scripts/backfill_pnl_from_fills.py --file data/fills/sample.jsonl --start-equity 10000
```

## Input Format

### CSV Format

**File**: `data/fills/*.csv`

**Required columns**:
- `timestamp` - Unix timestamp in milliseconds
- `pair` - Trading pair (e.g., "BTC/USD")
- `side` - "long" or "short"
- `entry_price` - Entry price
- `exit_price` - Exit price
- `quantity` - Position size
- `pnl` - Realized profit/loss in USD

**Example**:
```csv
timestamp,pair,side,entry_price,exit_price,quantity,pnl
1704067200000,BTC/USD,long,45000.0,46000.0,0.1,100.0
1704070800000,BTC/USD,short,46000.0,45500.0,0.1,50.0
1704074400000,ETH/USD,long,2300.0,2350.0,1.0,50.0
```

### JSONL Format

**File**: `data/fills/*.jsonl` or `data/fills/*.json`

**Required fields**:
- `ts` (or `timestamp`) - Unix timestamp in milliseconds
- `pair` (or `symbol`) - Trading pair
- `side` - "long" or "short"
- `entry` (or `entry_price`) - Entry price
- `exit` (or `exit_price`) - Exit price
- `qty` (or `quantity`) - Position size
- `pnl` - Realized profit/loss in USD

**Example**:
```jsonl
{"ts":1704067200000,"pair":"BTC/USD","side":"long","entry":45000.0,"exit":46000.0,"qty":0.1,"pnl":100.0}
{"ts":1704070800000,"pair":"BTC/USD","side":"short","entry":46000.0,"exit":45500.0,"qty":0.1,"pnl":50.0}
{"ts":1704074400000,"pair":"ETH/USD","side":"long","entry":2300.0,"exit":2350.0,"qty":1.0,"pnl":50.0}
```

## Usage

### Basic Backfill

```bash
# From specific file
python scripts/backfill_pnl_from_fills.py \
  --file data/fills/mydata.csv \
  --start-equity 10000
```

### Auto-Discovery

If `--file` is omitted, the script automatically discovers the first CSV/JSONL file in `data/fills/`:

```bash
python scripts/backfill_pnl_from_fills.py --start-equity 10000
```

### Force Re-Run

The script uses marker key `pnl:backfill:done` to prevent duplicate backfills. Use `--force` to override:

```bash
python scripts/backfill_pnl_from_fills.py \
  --file data/fills/sample.csv \
  --start-equity 10000 \
  --force
```

### Dry Run (Preview)

Preview the backfill without writing to Redis:

```bash
python scripts/backfill_pnl_from_fills.py \
  --file data/fills/sample.csv \
  --dry-run
```

**Output**:
```
🔍 DRY RUN - Preview fills:
============================================================
1. BTC/USD long @ 1704067200000: PnL +$100.00 → Equity $10,100.00
2. BTC/USD short @ 1704070800000: PnL +$50.00 → Equity $10,150.00
3. ETH/USD long @ 1704074400000: PnL +$50.00 → Equity $10,200.00
...
```

## Configuration

### Environment Variables

```bash
# Redis connection (required)
export REDIS_URL=rediss://default:${REDIS_PASSWORD}@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818/0

# Or use local Redis for testing
export REDIS_URL=redis://localhost:6379/0
```

### Command-Line Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--file` | Auto-discover | Path to fills file (CSV or JSONL) |
| `--start-equity` | 10000.0 | Starting equity in USD |
| `--force` | false | Force backfill even if marker exists |
| `--dry-run` | false | Preview without writing to Redis |

## Redis Keys Updated

The backfill script writes to:

1. **Stream: `pnl:equity`**
   - Time series of equity snapshots
   - Each entry has field `json` with serialized `{ts, equity, daily_pnl}`

2. **Key: `pnl:equity:latest`**
   - Latest equity snapshot (JSON blob)
   - Format: `{"ts":..., "equity":..., "daily_pnl":...}`

3. **Key: `pnl:backfill:done`**
   - Marker to prevent duplicate backfills
   - Value: `"true"`

## Verification

### Redis Cloud with TLS

```bash
# Set connection details
REDIS_HOST="redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com"
REDIS_PORT=19818
REDIS_PASSWORD="${REDIS_PASSWORD}"
REDIS_URL="redis://default:${REDIS_PASSWORD}@${REDIS_HOST}:${REDIS_PORT}"

# Check marker key
redis-cli -u $REDIS_URL --tls --cacert config/certs/ca.crt GET pnl:backfill:done

# Expected output:
"true"

# Check stream length
redis-cli -u $REDIS_URL --tls --cacert config/certs/ca.crt XLEN pnl:equity

# Expected output: (integer) 10

# Check latest equity
redis-cli -u $REDIS_URL --tls --cacert config/certs/ca.crt GET pnl:equity:latest

# Expected output (example):
"{\"ts\":1704164400000,\"equity\":10360.0,\"daily_pnl\":60.0}"

# Read first 5 equity points from stream
redis-cli -u $REDIS_URL --tls --cacert config/certs/ca.crt XREAD COUNT 5 STREAMS pnl:equity 0

# Expected output:
1) 1) "pnl:equity"
   2) 1) 1) "1704067200000-0"
         2) 1) "json"
            2) "{\"ts\":1704067200000,\"equity\":10100.0,\"daily_pnl\":100.0}"
      2) 1) "1704070800000-0"
         2) 1) "json"
            2) "{\"ts\":1704070800000,\"equity\":10150.0,\"daily_pnl\":150.0}"
      ...
```

### Local Redis (No TLS)

```bash
# Check marker
redis-cli GET pnl:backfill:done

# Check stream length
redis-cli XLEN pnl:equity

# Check latest equity
redis-cli GET pnl:equity:latest

# Read stream
redis-cli XREAD COUNT 5 STREAMS pnl:equity 0
```

### Python Verification

```python
import redis
import json

# Connect to Redis
client = redis.from_url(
    "rediss://default:${REDIS_PASSWORD}@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818/0",
    decode_responses=True
)

# Check marker
marker = client.get("pnl:backfill:done")
print(f"Backfill marker: {marker}")

# Check stream length
stream_len = client.xlen("pnl:equity")
print(f"Equity stream length: {stream_len}")

# Get latest equity
latest_json = client.get("pnl:equity:latest")
if latest_json:
    latest = json.loads(latest_json)
    print(f"Latest equity: ${latest['equity']:,.2f}")
    print(f"Daily PnL: ${latest['daily_pnl']:+,.2f}")

# Read first 5 points
messages = client.xread({"pnl:equity": "0"}, count=5)
if messages:
    for stream_name, entries in messages:
        print(f"\nStream: {stream_name}")
        for msg_id, fields in entries:
            data = json.loads(fields["json"])
            print(f"  {msg_id}: Equity ${data['equity']:,.2f}, Daily PnL ${data['daily_pnl']:+,.2f}")
```

## Behavior

### Day Boundary Detection

The backfill script automatically detects UTC day boundaries and resets daily PnL:

- **Day 1** (2024-01-01):
  - Trades at 12:00, 13:00, 14:00 → `daily_pnl` accumulates

- **Day 2** (2024-01-02):
  - First trade at 07:00 → `daily_pnl` resets to 0
  - Subsequent trades accumulate from 0

### Idempotency

The script is safe to re-run:

1. **First run**: Processes all fills, sets marker `pnl:backfill:done=true`
2. **Second run**: Checks marker, exits early
3. **Force run**: `--force` flag ignores marker, re-processes all fills

### Message IDs

The script uses timestamp-based message IDs for historical data:

- Format: `<timestamp_ms>-0`
- Example: `1704067200000-0`

This ensures:
- Chronological ordering in Redis streams
- Deterministic IDs for same data
- Compatibility with real-time aggregator

## Troubleshooting

### "Backfill already completed"

**Cause**: Marker key `pnl:backfill:done` exists

**Solution**:
```bash
# Option 1: Use --force
python scripts/backfill_pnl_from_fills.py --file data/fills/sample.csv --force

# Option 2: Clear marker manually
redis-cli DEL pnl:backfill:done
```

### "No fills files found"

**Cause**: No CSV/JSONL files in `data/fills/`

**Solution**:
```bash
# Create fills directory
mkdir -p data/fills

# Add your fills file
cp /path/to/mydata.csv data/fills/

# Run backfill
python scripts/backfill_pnl_from_fills.py
```

### "Failed to connect to Redis"

**Cause**: Redis connection error

**Solution**:
```bash
# Check Redis URL
echo $REDIS_URL

# Set correct URL
export REDIS_URL=rediss://default:PASSWORD@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818/0

# Test connection
redis-cli -u $REDIS_URL --tls --cacert config/certs/ca.crt PING
```

### "Skipping invalid CSV row"

**Cause**: Malformed CSV data

**Solution**:
1. Validate CSV has all required columns
2. Check for empty rows or missing values
3. Ensure numeric fields are valid numbers
4. Use `--dry-run` to preview parsed data

## Integration with PnL Aggregator

The backfill script populates the same Redis keys that the PnL aggregator uses:

1. **Before first deployment**:
   ```bash
   # Backfill historical data
   python scripts/backfill_pnl_from_fills.py --file data/fills/history.csv

   # Start aggregator (resumes from backfilled data)
   python monitoring/pnl_aggregator.py
   ```

2. **Aggregator behavior**:
   - Reads last ID from `pnl:agg:last_id` (starts at "0-0")
   - Processes backfilled equity points
   - Continues with live trade data seamlessly

3. **Chart rendering**:
   - Dashboard reads entire `pnl:equity` stream
   - Shows complete history from backfill + live updates
   - No gaps in equity curve

## Sample Data

Sample files are provided in `data/fills/`:

- **`sample.csv`** - 10 sample trades in CSV format
- **`sample.jsonl`** - Same 10 trades in JSONL format

Both files represent:
- Start equity: $10,000
- End equity: $10,360
- Total PnL: +$360
- Trades: 10 (7 winners, 3 losers)

Use these for testing:

```bash
# Test with CSV
python scripts/backfill_pnl_from_fills.py --file data/fills/sample.csv

# Test with JSONL
python scripts/backfill_pnl_from_fills.py --file data/fills/sample.jsonl
```

## Best Practices

1. **Always use --dry-run first** to preview data before publishing
2. **Validate input data** before backfilling production Redis
3. **Set correct start-equity** matching your actual starting capital
4. **Use --force sparingly** - only when intentionally re-backfilling
5. **Backup Redis** before large backfills (redis-cli SAVE)

## Command Reference

```bash
# Basic usage
python scripts/backfill_pnl_from_fills.py --file data/fills/sample.csv --start-equity 10000

# Auto-discover
python scripts/backfill_pnl_from_fills.py --start-equity 10000

# Force re-run
python scripts/backfill_pnl_from_fills.py --file data/fills/sample.csv --force

# Dry run
python scripts/backfill_pnl_from_fills.py --file data/fills/sample.csv --dry-run

# With Redis Cloud
export REDIS_URL=rediss://default:PASSWORD@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818/0
python scripts/backfill_pnl_from_fills.py --file data/fills/sample.csv
```

---

**Last Updated**: 2025-01-13
**Conda Environment**: crypto-bot
**Python Version**: 3.10.18
**Redis Cloud**: redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 (TLS)
