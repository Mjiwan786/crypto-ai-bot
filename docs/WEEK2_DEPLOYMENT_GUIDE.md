# Week 2: PRD-001 Deployment Guide

**Date:** 2025-11-30
**Status:** Ready for Deployment
**Owner:** Senior Python Engineer

---

## Summary

Week 2 implementation ensures `crypto-ai-bot` publishes PRD-001 compliant signals with backward-compatible aliases for `signals-api` consumption.

### Key Changes

| File | Change |
|------|--------|
| `agents/infrastructure/prd_publisher.py` | Added backward-compatible aliases (ts, entry, sl, tp) |
| `production_engine.py` | Updated to use PRDPublisher |
| `live_signal_publisher.py` | Updated to use PRDPublisher |

---

## Signal Schema: Dual Compatibility

Signals now include **both** PRD-001 fields and legacy API aliases:

### PRD-001 Fields (New)
```json
{
  "signal_id": "uuid-v4",
  "timestamp": "2025-11-30T14:00:00.000+00:00",
  "pair": "BTC/USD",
  "side": "LONG",
  "strategy": "SCALPER",
  "regime": "TRENDING_UP",
  "entry_price": "95000.0",
  "take_profit": "97000.0",
  "stop_loss": "94000.0",
  "confidence": "0.85",
  "position_size_usd": "100.0",
  "risk_reward_ratio": "2.0"
}
```

### API Aliases (Legacy - for signals-api compatibility)
```json
{
  "id": "uuid-v4",
  "symbol": "BTCUSDT",
  "signal_type": "LONG",
  "price": "95000.0",
  "ts": "1732975200000",
  "entry": "95000.0",
  "sl": "94000.0",
  "tp": "97000.0"
}
```

---

## Current State

### Local (Verified)
- PRDPublisher correctly publishes signals with all fields
- Test scripts confirm PRD-001 + API alias compliance
- Telemetry keys (`engine:last_signal_meta`, `engine:last_pnl_meta`) populated

### Remote (Pending Deployment)
- `signals-api-gateway.fly.dev`: Health OK, `/v1/signals/paper` returns 500
- Root cause: Fly.io still running old code that doesn't include new fields
- Fix: Redeploy crypto-ai-bot to Fly.io

---

## Deployment Steps

### 1. Verify Local Changes

```bash
# Run test to confirm signals publish correctly
python test_prd_publish.py
```

Expected output:
```
[OK] All PRD-001 fields present
[OK] All PRD-002 API aliases present
```

### 2. Commit Changes

```bash
git add agents/infrastructure/prd_publisher.py production_engine.py live_signal_publisher.py
git commit -m "feat: Add backward-compatible aliases for signals-api (Week 2)"
git push origin feature/add-trading-pairs
```

### 3. Deploy to Fly.io

```bash
# Deploy crypto-ai-bot
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot
flyctl deploy --remote-only
```

### 4. Verify Deployment

```bash
# Check API health
curl https://signals-api-gateway.fly.dev/health

# Check signals endpoint (should return 200 with data)
curl https://signals-api-gateway.fly.dev/v1/signals/paper?limit=3
```

### 5. Verify Front-End

Visit `signals-site` and confirm:
- No more "Failed to load performance metrics"
- Real signal data instead of placeholders
- Metrics (uptime, signal count) populated

---

## Files Modified

### 1. `agents/infrastructure/prd_publisher.py`

**Lines 243-257:** Added backward-compatible aliases in `to_redis_dict()`:

```python
# Add backward-compatible field aliases for signals-api consumption
result["ts"] = str(ts_ms)  # Timestamp in milliseconds for legacy API
result["entry"] = str(self.entry_price)  # Legacy alias for entry_price
result["sl"] = str(self.stop_loss)  # Legacy alias for stop_loss
result["tp"] = str(self.take_profit)  # Legacy alias for take_profit
```

### 2. `production_engine.py`

Updated imports to use PRDPublisher:
```python
from agents.infrastructure.prd_publisher import (
    PRDPublisher,
    PRDSignal,
    PRDPnLUpdate,
    create_prd_signal,
    Side,
    Strategy,
    Regime,
)
```

### 3. `live_signal_publisher.py`

Updated to use PRDPublisher with PRD-001 enums:
```python
from agents.infrastructure.prd_publisher import (
    PRDPublisher,
    create_prd_signal,
    PRDPnLUpdate,
)
```

---

## Rollback Plan

If issues occur after deployment:

```bash
# Rollback to previous version
flyctl releases list -a crypto-ai-bot
flyctl releases rollback -a crypto-ai-bot <previous-version>
```

---

## Success Criteria

| Criterion | Status |
|-----------|--------|
| Signals include PRD-001 fields | Verified |
| Signals include API aliases (ts, entry, sl, tp) | Verified |
| API `/v1/signals/paper` returns 200 | Pending Deployment |
| Front-end shows real metrics | Pending Deployment |
| No schema mismatch errors | Pending Deployment |

---

## Troubleshooting

### API returns 500 on `/v1/signals/paper`

**Cause:** Schema mismatch - API expects fields that don't exist in Redis data

**Fix:**
1. Verify signals in Redis have `ts`, `entry`, `sl`, `tp` fields
2. If missing, redeploy crypto-ai-bot with updated code
3. Wait for new signals to be published

### Front-end shows placeholder data

**Cause:** No signals published since deployment, or API cache

**Fix:**
1. Check `engine:last_signal_meta` telemetry key in Redis
2. Verify signals are being published (`XREVRANGE signals:paper:BTC-USD COUNT 3`)
3. Check API logs for errors

---

## Related Documentation

- `docs/WEEK2_IMPLEMENTATION_SUMMARY.md` - Full implementation details
- `docs/WEEK2_SCHEMA_ALIGNMENT.md` - Schema comparison analysis
- `docs/PRD-001-CRYPTO-AI-BOT.md` - PRD specification
