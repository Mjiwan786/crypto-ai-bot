# STEP 3: Launch Real-Time Feed & Signal Publishing

**Goal**: Start Kraken WebSocket → Enhanced Scalper → Redis → API → Site pipeline

**Status**: Ready to Launch ✅

---

## Quick Start

```bash
# Terminal 1: Start crypto-ai-bot scalper (crypto-bot env)
conda activate crypto-bot
python scripts/launch_live_feed.py

# Terminal 2: Monitor Redis streams
python scripts/monitor_redis_streams.py --stream signals:live

# Terminal 3: Start signals-api (signals-api env)
cd ../signals_api
conda activate signals-api
uvicorn app.main:app --reload --port 8000

# Terminal 4: Start signals-site (if needed)
cd ../signals-site
npm run dev
```

---

## Prerequisites Checklist

### ✅ 1. Environment Configuration

**crypto-ai-bot** (crypto-bot env):
```bash
# Verify .env configuration
MODE=LIVE  # or PAPER for testing
LIVE_TRADING_CONFIRMATION=I-accept-the-risk  # Required for LIVE
REDIS_URL=rediss://default:<password>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818
REDIS_CA_CERT_PATH=config/certs/redis_ca.pem
KRAKEN_EMERGENCY_STOP=false  # Must be false
```

**signals-api** (signals-api env):
```bash
# Verify .env configuration
REDIS_URL=rediss://default:<password>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818
REDIS_CA_CERT=<path_to_cert>
```

**signals-site**:
```bash
# Verify Redis connection in config
REDIS_URL=redis://default:<password>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818
REDIS_TLS=true
```

### ✅ 2. Redis Connectivity

Test Redis connection:
```bash
# From crypto-ai-bot
python scripts/test_redis_live.py

# Expected output:
# [OK] Connection successful (PING OK)
# [OK] ACTIVE_SIGNALS -> signals:live
```

### ✅ 3. Conda Environments

Verify all conda environments exist:
```bash
conda env list

# Expected:
# crypto-bot
# signals-api
```

---

## Launch Procedures

### Option 1: Automated Launcher (Recommended)

```bash
conda activate crypto-bot
python scripts/launch_live_feed.py
```

**Features**:
- ✅ Validates environment configuration
- ✅ Tests Redis connectivity
- ✅ Verifies trading mode
- ✅ Starts Kraken scalper agent
- ✅ Monitors signal flow
- ✅ Real-time health checks

**Output**:
```
======================================================================
 LIVE FEED LAUNCHER (STARTING PIPELINE)
======================================================================

[CHECK] Validating environment configuration...
   [OK] Loaded .env
   [OK] REDIS_URL configured
   [OK] KRAKEN_API_KEY configured
   [OK] KRAKEN_API_SECRET configured

[CHECK] Validating Redis Cloud connectivity...
   [OK] Using CA cert: config/certs/redis_ca.pem
   [OK] Redis connected (PING OK)
   [OK] ACTIVE_SIGNALS -> signals:live

[CHECK] Validating trading mode...
   Current MODE: LIVE
   [WARNING] LIVE mode - real money trading!
   [OK] LIVE_TRADING_CONFIRMATION verified
   [OK] Emergency stop: inactive

[STARTING] Initializing trading components...
   [OK] Imported KrakenScalperAgent
   [INFO] Using config: config/enhanced_scalper_config.yaml
   [OK] Created agent instance

[STARTING] Starting Kraken Scalper Agent...
   [OK] Agent started successfully
   [INFO] Agent state: active
   [INFO] Publishing signals to: signals:live

[MONITORING] Starting pipeline monitoring...
[MONITOR] Monitoring signals:live stream...
[MONITOR] Press Ctrl+C to stop

[HEALTH] Agent State: active
         Active Positions: 0
         Trades Today: 0
         PnL: $0.00

[SIGNALS] 1 new signal(s) published to signals:live
          Entry ID: 1761755375860-0
          Pair: BTC/USD
          Side: long
          Strategy: kraken_scalper
          Confidence: 0.82

[STATS] Stream: signals:live
        Total signals: 15
        Signal rate: 0.03 signals/sec
        Runtime: 450s
```

### Option 2: Direct Agent Launch

```bash
conda activate crypto-bot
python -m agents.scalper --mode live
```

Or:
```bash
python agents/scalper/kraken_scalper_agent.py --mode live
```

**Note**: This option requires manual monitoring of signal streams.

---

## Verification Checklist

### 🟢 Step 1: Verify Redis Stream Population

**Check signals are being written**:
```bash
# Method 1: Using redis-cli
redis-cli -u "redis://default:<password>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818" \
  --tls \
  --cacert "C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem" \
  XREAD COUNT 10 STREAMS signals:live 0-0

# Method 2: Using Python
python -c "
import redis
r = redis.from_url('rediss://default:<password>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818',
                    decode_responses=True,
                    ssl_ca_certs='config/certs/redis_ca.pem')
signals = r.xrevrange('signals:live', count=5)
for entry_id, fields in signals:
    print(f'{entry_id}: {fields}')
"

# Method 3: Using monitoring script
python scripts/monitor_redis_streams.py --stream signals:live --interval 5
```

**Expected Output**:
```
1761755375860-0: {
    'id': 'scalp_1761755375',
    'ts': '1761755375000',
    'pair': 'BTC/USD',
    'side': 'long',
    'entry': '67500.50',
    'sl': '67200.00',
    'tp': '68000.00',
    'strategy': 'kraken_scalper',
    'confidence': '0.82',
    'mode': 'live'
}
```

### 🟢 Step 2: Verify signals-api Integration

**Start signals-api**:
```bash
cd ../signals_api
conda activate signals-api
uvicorn app.main:app --reload --port 8000
```

**Test API endpoints**:
```bash
# Method 1: GET /stream/signals (REST)
curl http://localhost:8000/v1/signals?mode=live&limit=10

# Expected:
# [
#   {
#     "id": "scalp_1761755375",
#     "timestamp": 1761755375000,
#     "pair": "BTC/USD",
#     "side": "long",
#     "entry": 67500.50,
#     "sl": 67200.00,
#     "tp": 68000.00,
#     "strategy": "kraken_scalper",
#     "confidence": 0.82,
#     "mode": "live"
#   }
# ]

# Method 2: WebSocket streaming
wscat -c ws://localhost:8000/v1/signals/stream

# Expected: Real-time signal stream as JSON messages
```

**Alternative: Using Python**:
```python
import requests

# REST endpoint
response = requests.get("http://localhost:8000/v1/signals?mode=live&limit=5")
signals = response.json()
print(f"Retrieved {len(signals)} signals")
for signal in signals:
    print(f"  {signal['pair']} {signal['side']} @ ${signal['entry']}")

# WebSocket endpoint (requires websockets library)
import asyncio
import websockets

async def test_websocket():
    async with websockets.connect("ws://localhost:8000/v1/signals/stream") as ws:
        for i in range(5):
            message = await ws.recv()
            print(f"Received: {message}")

asyncio.run(test_websocket())
```

### 🟢 Step 3: Verify signals-site Dashboard

**Start signals-site**:
```bash
cd ../signals-site
npm run dev
```

**Access dashboard**:
```
http://localhost:3000
```

**Verify display**:
- ✅ Real-time signals appear in dashboard
- ✅ Timestamps are accurate and updating
- ✅ Signal details (pair, side, entry, SL, TP) display correctly
- ✅ Confidence scores shown
- ✅ Strategy names visible

**Dashboard Features to Check**:
1. **Signal Feed**: Live scrolling list of signals
2. **Signal Cards**: Individual signal details
3. **Timestamps**: Should show "X seconds ago" or absolute time
4. **Filters**: Ability to filter by pair, strategy, mode
5. **WebSocket Status**: Connection indicator (green = connected)

---

## Monitoring & Health Checks

### Real-Time Monitoring

**Agent Health**:
```bash
# Automated (included in launcher)
python scripts/launch_live_feed.py

# Manual health check
python -c "
import asyncio
from agents.scalper.kraken_scalper_agent import KrakenScalperAgent

async def check_health():
    agent = KrakenScalperAgent()
    await agent.startup()
    health = await agent.get_health_status()
    print(f'State: {health[\"state\"]}')
    print(f'Positions: {health[\"active_positions\"]}')
    print(f'Trades: {health[\"trades_today\"]}')
    print(f'PnL: ${health[\"pnl\"]:.2f}')

asyncio.run(check_health())
"
```

**Stream Metrics**:
```bash
# Stream length
redis-cli -u "..." --tls --cacert "..." XLEN signals:live

# Stream info
redis-cli -u "..." --tls --cacert "..." XINFO STREAM signals:live

# Consumer groups
redis-cli -u "..." --tls --cacert "..." XINFO GROUPS signals:live
```

### Performance Metrics

**Signal Latency** (Decision → Publish):
```python
# Add to agent monitoring
import time

signal_generated_ts = time.time()
# ... signal processing ...
entry_id = publisher.publish(signal)
latency_ms = (time.time() - signal_generated_ts) * 1000

print(f"Signal latency: {latency_ms:.2f}ms")
# Target: < 500ms per PRD
```

**Stream Lag** (API → Site):
```python
# Check difference between signal timestamp and current time
import time

current_time_ms = int(time.time() * 1000)
signal_ts_ms = int(signal_data['ts'])
lag_ms = current_time_ms - signal_ts_ms

print(f"Stream lag: {lag_ms}ms")
# Target: < 200ms per PRD
```

---

## Troubleshooting

### Issue: No signals appearing in stream

**Diagnosis**:
```bash
# Check agent is running
ps aux | grep kraken_scalper_agent

# Check Redis connection
python scripts/test_redis_live.py

# Check MODE configuration
grep "MODE=" .env

# Check ACTIVE_SIGNALS
redis-cli -u "..." --tls --cacert "..." GET ACTIVE_SIGNALS
```

**Solution**:
1. Verify agent started successfully (check logs)
2. Ensure MODE matches ACTIVE_SIGNALS stream
3. Check Kraken API credentials are valid
4. Verify market data is flowing (check kraken:book stream)

### Issue: signals-api not receiving signals

**Diagnosis**:
```bash
# Check API is running
curl http://localhost:8000/health

# Check API Redis connection
curl http://localhost:8000/v1/status

# Check API logs
tail -f logs/signals-api.log
```

**Solution**:
1. Verify API Redis URL matches bot Redis URL
2. Check CA certificate path in API config
3. Ensure API is subscribed to correct stream (signals:live)
4. Restart API service

### Issue: signals-site not displaying signals

**Diagnosis**:
```bash
# Check site is running
curl http://localhost:3000

# Check browser console for errors (F12)

# Check WebSocket connection
# In browser console:
# ws = new WebSocket('ws://localhost:8000/v1/signals/stream')
# ws.onmessage = (e) => console.log('Received:', e.data)
```

**Solution**:
1. Verify API WebSocket endpoint is accessible
2. Check site API URL configuration
3. Clear browser cache
4. Check for CORS issues in API
5. Verify Redis connection in site config

### Issue: High latency (> 500ms)

**Diagnosis**:
```bash
# Check Redis latency
redis-cli -u "..." --tls --cacert "..." --latency

# Check network connectivity
ping redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com

# Check system load
top
```

**Solution**:
1. Verify Redis Cloud plan has sufficient resources
2. Check network bandwidth
3. Reduce stream MAXLEN to trim old entries
4. Optimize agent signal generation logic
5. Consider Redis connection pooling

---

## Architecture Overview

```
┌──────────────────┐
│  Kraken WebSocket│
│  (Market Data)   │
└────────┬─────────┘
         │ real-time
         ▼
┌──────────────────┐
│ Enhanced Scalper │
│     Agent        │◄──── Redis Streams
│  (crypto-bot)    │      (kraken:book,
└────────┬─────────┘       kraken:trade)
         │ signals
         ▼
┌──────────────────┐
│   Redis Cloud    │
│  signals:live /  │◄──── ACTIVE_SIGNALS
│  signals:paper   │      routing
└────────┬─────────┘
         │ subscribe
         ▼
┌──────────────────┐
│   signals-api    │
│   (FastAPI +     │◄──── REST + WebSocket
│   Redis streams) │      endpoints
└────────┬─────────┘
         │ HTTP/WS
         ▼
┌──────────────────┐
│  signals-site    │
│  (Next.js)       │◄──── Real-time
│   Dashboard      │      signal display
└──────────────────┘
```

---

## Signal Flow Timeline

```
T+0ms    : Market data received from Kraken WebSocket
T+50ms   : Order book processed, liquidity signal generated
T+100ms  : Scalper signal generated (buy/sell decision)
T+150ms  : Risk management checks passed
T+200ms  : Order intent created
T+250ms  : Signal published to Redis signals:live
         ──────────────────────────────────────
T+300ms  : signals-api reads from stream (consumer group)
T+350ms  : API publishes to WebSocket subscribers
T+400ms  : signals-site receives via WebSocket
T+450ms  : Dashboard UI updates with new signal
         ──────────────────────────────────────
Total latency: Decision→Display < 500ms ✅
```

---

## Next Steps

After verifying the pipeline is working:

1. **Monitor for 1 hour**: Ensure stable signal generation
2. **Check signal quality**: Review confidence scores and strategy logic
3. **Validate PnL tracking**: Ensure filled orders update metrics
4. **Tune parameters**: Adjust scalper settings based on performance
5. **Scale up**: Increase position sizes gradually
6. **Set alerts**: Configure Discord/Telegram notifications
7. **Document observations**: Note any issues or improvements

---

## Emergency Procedures

### Stop Trading Immediately

```bash
# Method 1: Set emergency stop in .env
echo "KRAKEN_EMERGENCY_STOP=true" >> .env

# Method 2: Set in Redis
redis-cli -u "..." --tls --cacert "..." SET kraken:emergency:kill_switch "true"

# Method 3: Kill agent process
pkill -f kraken_scalper_agent
```

### Switch to PAPER Mode

```bash
# Update .env
sed -i 's/MODE=LIVE/MODE=PAPER/' .env

# Update Redis routing
redis-cli -u "..." --tls --cacert "..." SET ACTIVE_SIGNALS "signals:paper"

# Restart agent
python scripts/launch_live_feed.py
```

---

## Support & References

- **PRD**: `PRD.md` - System architecture and requirements
- **Setup Guide**: `LIVE_TRADING_SETUP_SUMMARY.md` - Configuration details
- **Operations**: `OPERATIONS_RUNBOOK.md` - Operational procedures
- **signals-api PRD**: `../signals_api/PRD_AGENTIC.md`
- **signals-site PRD**: `../signals-site/PRD_AGENTIC.MD`

---

**Status**: ✅ Ready to Launch
**Last Updated**: 2025-10-29

*End of Document*
