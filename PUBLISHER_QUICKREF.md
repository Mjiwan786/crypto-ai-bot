# Signal Publisher Quick Reference

## Import
```python
from models.signal_dto import (
    SignalDTO,             # Pydantic signal model
    generate_signal_id,    # ID generation
    create_signal_dto,     # Convenience creator
)

from streams.publisher import (
    PublisherConfig,       # Configuration
    SignalPublisher,       # Main publisher class
    create_publisher,      # Convenience creator
)
```

## Basic Usage

### Option 1: Convenience Function
```python
from streams.publisher import create_publisher
from models.signal_dto import create_signal_dto
from datetime import datetime, timezone

# Create publisher
publisher = create_publisher(
    redis_url="redis://localhost:6379",
    max_retries=3,
)

# Create signal
ts_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
signal = create_signal_dto(
    ts_ms=ts_ms,
    pair="BTC-USD",
    side="long",
    entry=50000.0,
    sl=49000.0,
    tp=52000.0,
    strategy="momentum_v1",
    confidence=0.75,
    mode="paper",
)

# Publish with context manager
with publisher:
    entry_id = publisher.publish(signal)
    print(f"Published: {entry_id}")
```

### Option 2: Manual Configuration
```python
from streams.publisher import PublisherConfig, SignalPublisher

# Create config
config = PublisherConfig(
    redis_url="redis://localhost:6379",
    max_retries=3,
    base_delay_ms=100,
    max_delay_ms=5000,
    jitter=True,
    stream_maxlen=10000,
)

# Create publisher
publisher = SignalPublisher(config=config)

# Connect
publisher.connect()

# Publish
entry_id = publisher.publish(signal)

# Disconnect
publisher.disconnect()
```

## Redis Cloud (TLS)

### Setup with SSL Certificate
```python
from streams.publisher import create_publisher

publisher = create_publisher(
    redis_url="rediss://default:YOUR_PASSWORD@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818",
    ssl_ca_certs="C:\\Users\\Maith\\OneDrive\\Desktop\\crypto_ai_bot\\config\\certs\\redis_ca.pem",
    max_retries=3,
)

with publisher:
    entry_id = publisher.publish(signal)
```

**Note**:
- Use `rediss://` (with double 's') for TLS
- Provide path to Redis Cloud CA certificate
- Get cert from Redis Cloud dashboard

## Creating Signals

### From Strategy Router Signal
```python
from agents.strategy_router import StrategyRouter
from models.signal_dto import create_signal_dto

# Get signal from router
signal = router.route(tick, snapshot, ohlcv_df)

if signal:
    # Convert to SignalDTO
    ts_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    signal_dto = create_signal_dto(
        ts_ms=ts_ms,
        pair=signal.symbol,
        side=signal.side,
        entry=float(signal.entry_price),
        sl=float(signal.stop_loss),
        tp=float(signal.take_profit),
        strategy=signal.strategy,
        confidence=float(signal.confidence),
        mode="paper",  # or "live"
    )

    publisher.publish(signal_dto)
```

### From Risk Manager Position
```python
from agents.risk_manager import RiskManager
from models.signal_dto import create_signal_dto

# Size position
position = rm.size_position(signal, equity)

if position.allowed:
    # Create SignalDTO
    ts_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    signal_dto = create_signal_dto(
        ts_ms=ts_ms,
        pair=position.symbol,
        side=position.side,
        entry=float(position.entry_price),
        sl=float(position.stop_loss),
        tp=float(position.take_profit),
        strategy="momentum_v1",
        confidence=0.75,
        mode="paper",
    )

    publisher.publish(signal_dto)
```

## Reading Signals

### Read Latest Signals
```python
from streams.publisher import create_publisher

publisher = create_publisher(redis_url="redis://localhost:6379")

with publisher:
    # Read latest 10 paper signals
    signals = publisher.read_stream("paper", count=10)

    for sig in signals:
        print(f"{sig['entry_id']}: {sig['pair']} {sig['side']} @ ${sig['entry']}")
```

### Read from Both Modes
```python
with publisher:
    paper_signals = publisher.read_stream("paper", count=5)
    live_signals = publisher.read_stream("live", count=5)

    print(f"Paper signals: {len(paper_signals)}")
    print(f"Live signals: {len(live_signals)}")
```

### Get Stream Length
```python
with publisher:
    paper_count = publisher.get_stream_length("paper")
    live_count = publisher.get_stream_length("live")

    print(f"Paper stream: {paper_count} signals")
    print(f"Live stream: {live_count} signals")
```

## Idempotency

### Generate Signal ID
```python
from models.signal_dto import generate_signal_id

# Same inputs = same ID
ts_ms = 1730000000000
pair = "BTC-USD"
strategy = "momentum_v1"

id1 = generate_signal_id(ts_ms, pair, strategy)
id2 = generate_signal_id(ts_ms, pair, strategy)

assert id1 == id2  # Deterministic!
```

### Deduplication Downstream
```python
# In signals-api or consumer
seen_ids = set()

for signal in read_stream():
    if signal['id'] in seen_ids:
        continue  # Skip duplicate

    seen_ids.add(signal['id'])
    process_signal(signal)
```

## Metrics

### Get Metrics
```python
with publisher:
    # Publish some signals...

    metrics = publisher.get_metrics()
    print(f"Total published: {metrics['total_published']}")
    print(f"Paper mode: {metrics['mode_paper']}")
    print(f"Live mode: {metrics['mode_live']}")
    print(f"Total retries: {metrics['total_retries']}")
    print(f"Total failures: {metrics['total_failures']}")
```

### Reset Metrics
```python
with publisher:
    publisher.reset_metrics()

    # Metrics now zeroed
    metrics = publisher.get_metrics()
    assert metrics["total_published"] == 0
```

## Error Handling

### Retry on Failure
```python
from streams.publisher import create_publisher
import redis

publisher = create_publisher(
    redis_url="redis://localhost:6379",
    max_retries=3,  # Will retry 3 times
)

try:
    with publisher:
        entry_id = publisher.publish(signal)
except redis.RedisError as e:
    # Failed after all retries
    print(f"Publish failed: {e}")
```

### Connection Errors
```python
from streams.publisher import SignalPublisher, PublisherConfig

config = PublisherConfig(redis_url="redis://localhost:6379")
publisher = SignalPublisher(config=config)

# Must connect before publishing
try:
    publisher.publish(signal)  # Will raise ConnectionError
except ConnectionError as e:
    print(f"Not connected: {e}")

# Correct usage
publisher.connect()
publisher.publish(signal)
publisher.disconnect()
```

## Configuration Reference

### PublisherConfig Fields
```python
class PublisherConfig:
    redis_url: str                  # Redis URL (redis:// or rediss://)
    ssl_ca_certs: Optional[str]     # Path to SSL CA cert
    max_retries: int = 3            # Max retry attempts
    base_delay_ms: int = 100        # Base backoff delay
    max_delay_ms: int = 5000        # Max backoff cap
    jitter: bool = True             # Add jitter to backoff
    stream_maxlen: int = 10000      # Stream max length (~)
```

### SignalDTO Fields
```python
class SignalDTO:
    id: str                         # Idempotent signal ID
    ts: int                         # Timestamp (milliseconds)
    pair: str                       # Trading pair (e.g., BTC-USD)
    side: Literal["long", "short"]  # Trade direction
    entry: float                    # Entry price
    sl: float                       # Stop loss price
    tp: float                       # Take profit price
    strategy: str                   # Strategy name
    confidence: float               # Confidence [0,1]
    mode: Literal["paper", "live"]  # Trading mode
```

## Common Patterns

### Pattern 1: Complete Trading Flow
```python
from ai_engine.regime_detector import RegimeDetector
from agents.strategy_router import StrategyRouter
from agents.risk_manager import RiskManager
from models.signal_dto import create_signal_dto
from streams.publisher import create_publisher
from datetime import datetime, timezone

# Setup
detector = RegimeDetector()
router = StrategyRouter()
rm = RiskManager()
publisher = create_publisher(redis_url="redis://localhost:6379")

# Main loop
with publisher:
    for ohlcv_batch in live_stream:
        # 1. Detect regime
        tick = detector.detect(ohlcv_batch)

        # 2. Route signal
        signal = router.route(tick, snapshot, ohlcv_batch)

        if signal:
            # 3. Size position
            position = rm.size_position(signal, equity)

            # 4. Publish
            if position.allowed:
                ts_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
                signal_dto = create_signal_dto(
                    ts_ms=ts_ms,
                    pair=signal.symbol,
                    side=signal.side,
                    entry=float(signal.entry_price),
                    sl=float(signal.stop_loss),
                    tp=float(signal.take_profit),
                    strategy=signal.strategy,
                    confidence=float(signal.confidence),
                    mode="paper",
                )

                entry_id = publisher.publish(signal_dto)
```

### Pattern 2: Paper vs Live Mode Switching
```python
import os

# Determine mode from environment
trading_mode = os.getenv("TRADING_MODE", "paper")  # Default to paper

# Create signal with appropriate mode
signal_dto = create_signal_dto(
    ts_ms=ts_ms,
    pair="BTC-USD",
    side="long",
    entry=50000.0,
    sl=49000.0,
    tp=52000.0,
    strategy="momentum_v1",
    confidence=0.75,
    mode=trading_mode,  # "paper" or "live"
)

with publisher:
    entry_id = publisher.publish(signal_dto)
```

### Pattern 3: Batch Publishing
```python
signals = []

# Collect signals
for opportunity in opportunities:
    signal = create_signal_dto(...)
    signals.append(signal)

# Publish batch
with publisher:
    for signal in signals:
        entry_id = publisher.publish(signal)
        print(f"Published {signal.pair}: {entry_id}")
```

### Pattern 4: Monitoring Published Signals
```python
import time

with publisher:
    # Publish
    entry_id = publisher.publish(signal)

    # Wait and verify
    time.sleep(0.1)

    # Read back
    signals = publisher.read_stream("paper", count=1)
    latest = signals[0]

    # Verify
    assert latest["id"] == signal.id
    assert latest["pair"] == signal.pair
    print(f"Verified: {latest['pair']} published successfully")
```

## Stream Naming Convention

Per PRD §4, consistent with exchange/ohlc streams:

```
signals:paper    - Paper trading signals
signals:live     - Live trading signals

# Consistent with:
kraken:ohlc:1m:BTC-USD   - OHLC data
kraken:trade             - Trade data
kraken:book              - Order book
```

## Troubleshooting

### Problem: Connection Timeout
**Symptoms**: `redis.ConnectionError: Connection timeout`

**Solutions**:
1. Check Redis is running: `redis-cli ping`
2. Verify URL: `redis://host:port` or `rediss://host:port`
3. Check firewall/network
4. For Redis Cloud, ensure TLS cert is correct

### Problem: SSL Certificate Error
**Symptoms**: `ssl.SSLError: certificate verify failed`

**Solutions**:
1. Verify cert path: `ssl_ca_certs` points to valid file
2. Download cert from Redis Cloud dashboard
3. Use absolute path to cert file
4. Check cert permissions (readable)

### Problem: Signals Not Appearing
**Symptoms**: `publish()` succeeds but signals not in stream

**Check**:
```python
with publisher:
    # Publish
    entry_id = publisher.publish(signal)
    print(f"Entry ID: {entry_id}")

    # Verify stream
    length = publisher.get_stream_length(signal.mode)
    print(f"Stream length: {length}")

    # Read back
    signals = publisher.read_stream(signal.mode, count=1)
    print(f"Latest: {signals}")
```

### Problem: Retry Exhaustion
**Symptoms**: `RedisError` after multiple retries

**Check**:
```python
metrics = publisher.get_metrics()
print(f"Total failures: {metrics['total_failures']}")
print(f"Total retries: {metrics['total_retries']}")

# Increase retries
config = PublisherConfig(
    redis_url="...",
    max_retries=5,        # More retries
    base_delay_ms=200,    # Longer delays
    max_delay_ms=10000,
)
```

### Problem: Idempotency Not Working
**Issue**: Duplicate signals processed

**Solution**:
```python
# Implement deduplication in consumer
seen_ids = set()

def process_signal(signal):
    if signal['id'] in seen_ids:
        print(f"Skipping duplicate: {signal['id']}")
        return

    seen_ids.add(signal['id'])
    # Process signal...
```

## Performance Tips

1. **Use Context Manager**:
   ```python
   # Good (auto connect/disconnect)
   with publisher:
       publisher.publish(signal)

   # Avoid (manual management)
   publisher.connect()
   publisher.publish(signal)
   publisher.disconnect()
   ```

2. **Batch Reads**:
   ```python
   # Read multiple at once
   signals = publisher.read_stream("paper", count=100)

   # Process batch
   for sig in signals:
       process(sig)
   ```

3. **Connection Pooling**:
   ```python
   # Reuse publisher instance
   publisher = create_publisher(redis_url="...")

   with publisher:
       for signal in signals:
           publisher.publish(signal)  # Reuses connection
   ```

4. **Optimize Backoff**:
   ```python
   # Fast retries for local Redis
   config = PublisherConfig(
       redis_url="redis://localhost:6379",
       max_retries=2,
       base_delay_ms=50,  # Faster
   )

   # Slower retries for remote Redis
   config = PublisherConfig(
       redis_url="rediss://remote:6379",
       max_retries=5,
       base_delay_ms=200,  # Slower
   )
   ```

## Testing

### Unit Tests
```bash
pytest tests/test_publisher.py -v
```

### Run Specific Test
```bash
pytest tests/test_publisher.py::test_publisher_publish_basic -v
```

### Test with Coverage
```bash
pytest tests/test_publisher.py --cov=streams.publisher --cov=models.signal_dto
```

### Self-Check (requires local Redis)
```bash
python streams/publisher.py
```

## Environment Variables

Recommended setup:
```bash
# .env file
REDIS_URL=redis://localhost:6379
REDIS_TLS_CERT=/path/to/redis_ca.pem
TRADING_MODE=paper
MAX_RETRIES=3
```

Usage:
```python
import os

publisher = create_publisher(
    redis_url=os.getenv("REDIS_URL"),
    ssl_ca_certs=os.getenv("REDIS_TLS_CERT"),
    max_retries=int(os.getenv("MAX_RETRIES", "3")),
)
```

## Redis CLI Verification

### Check Stream
```bash
# Count entries
redis-cli XLEN signals:paper

# Read latest 10
redis-cli XREVRANGE signals:paper + - COUNT 10

# Read all
redis-cli XRANGE signals:paper - +
```

### With TLS (Redis Cloud)
```bash
redis-cli -u "rediss://default:PASSWORD@host:port" \
  --tls \
  --cacert C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem \
  XLEN signals:paper
```

## Integration Examples

See `STEP6_SUMMARY.md` for complete integration with:
- Regime Detector (STEP 2)
- Strategy Router (STEP 3)
- Risk Manager (STEP 5)
- Main trading loop
