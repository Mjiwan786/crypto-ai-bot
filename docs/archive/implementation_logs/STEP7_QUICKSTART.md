# STEP 7 — Quick Start Guide

## 🚀 Run Live Engine in 3 Steps

### Step 1: Set Redis URL
```bash
export REDIS_URL='rediss://default:<your-password>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818'
```

### Step 2: Test Redis Connection
```bash
python scripts/test_redis_connection.py
```

✅ All 6 tests should pass

### Step 3: Run Live Engine
```bash
python scripts/run_paper.py
```

Press **Ctrl+C** to stop and view metrics.

---

## ⚡ Quick Commands

### Check if engine imports work:
```bash
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot
python -c "from engine import LiveEngine; print('OK')"
```

### Monitor Redis signals:
```bash
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem \
  XREVRANGE signals:paper + - COUNT 5
```

### Check stream length:
```bash
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem \
  XLEN signals:paper
```

---

## 📊 What to Expect

### First 8 Hours (Cache Filling):
```
BTC/USD: Cache not ready (20/100)
ETH/USD: Cache not ready (18/100)
...
```

### After Cache Ready:
```
BTC/USD: Regime=bull, Strength=0.75
BTC/USD: Signal generated: long @ 50000.00
BTC/USD: Position sized: $2500.00, risk=$50.00
BTC/USD: Signal published: 45ms decision, 12ms publish
```

---

## 🔧 Configuration

### Reduce cache requirement for testing:
Edit `scripts/run_paper.py`:
```python
config = EngineConfig(
    mode="paper",
    min_bars_required=50,  # Reduced from 100
    # ...
)
```

### Adjust circuit breakers:
```bash
export SPREAD_BPS_MAX=10.0      # Allow wider spreads
export LATENCY_MS_MAX=1000.0    # Allow higher latency
```

---

## ❌ Common Issues

### "REDIS_URL not set"
```bash
export REDIS_URL='rediss://...'
```

### "Import errors"
```bash
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot
python scripts/run_paper.py
```

### "No signals generated"
- Wait for cache to fill (~8 hours for 100 bars @ 5m)
- Or reduce `min_bars_required` in config

---

## 📖 Full Documentation

See: `STEP7_COMPLETE.md`

---

**Ready to trade paper signals!** 🎯
