# Release Notes - v1.0.0

**Release Date**: 2025-11-08
**Release Type**: Major Feature Release
**Deployment Mode**: 48-Hour Soak Test (Paper Trading)

---

## 🎯 Overview

This release introduces a complete P&L optimization and monitoring system with:
- **48-Hour Soak Test** with Turbo Scalper (15s) + Bar Reaction (5m)
- **Protection Mode** - Automatic capital preservation when nearing target
- **Real-time Performance Metrics** streaming across all 3 services
- **Live Dashboard** with SSE-powered metrics visualization

---

## ✨ New Features

### 1. Protection Mode - Automatic Capital Preservation

**What**: Automatically reduces risk when equity reaches 80% of target ($18k) or after 5 consecutive wins.

**How It Works**:
- **Triggers**:
  - Equity ≥ $18,000 (80% to $20k target)
  - Win streak ≥ 5 consecutive wins

- **Adjustments**:
  - Position sizes: **Halved** (1.2% → 0.6%)
  - Stop losses: **30% tighter** (1.5 ATR → 1.05 ATR)
  - Max trades/min: **50% reduced** (10 → 5 trades/min)

- **Control**:
  - YAML config: `protection_mode.force_enabled: true/false/null`
  - Runtime override via Redis: `SET protection:mode:override "enabled"`
  - API endpoint: `POST /protection-mode/override`

**Files**:
- `core/protection_mode.py` - Main implementation
- `config/protection_mode_controller.py` - Controller logic
- `scripts/test_protection_mode.py` - Comprehensive test suite
- `PROTECTION_MODE_RUNBOOK.md` - Complete documentation

**Benefits**:
- Locks in gains when close to target
- Prevents blow-up from overconfidence
- Automatic + manual control

---

### 2. Real-Time Performance Metrics

**What**: Live tracking of P&L optimization progress with 3 key metrics.

**Metrics**:
1. **Aggressive Mode Score** = (win_rate × avg_win) / (loss_rate × avg_loss)
   - ≥ 2.0: Excellent
   - ≥ 1.5: Very Good
   - ≥ 1.0: Good
   - < 1.0: Needs improvement

2. **Velocity to Target** = (equity - $10k) / ($20k - $10k)
   - Shows % progress to $20k target
   - 0.0 = Starting equity
   - 1.0 = Target reached

3. **Days Remaining** = Based on current daily rate
   - Projected days to reach target
   - Null if negative daily rate

**Publishing**:
- Published every 30 seconds to Redis streams
- Streams: `metrics:performance`, `metrics:aggressive_mode_score`, `metrics:velocity_to_target`, `metrics:days_remaining`
- Exposed via Prometheus metrics

**Files**:
- `metrics/performance_metrics.py` - Calculator
- `metrics/metrics_publisher.py` - Background publisher
- `config/performance_metrics.yaml` - Configuration

**Integration**:
- Integrated in `main.py:210-226`
- Added to `/health` endpoint response
- Auto-start with 30s interval

---

### 3. Signals-API Metrics Endpoints

**What**: REST + SSE endpoints to expose performance metrics.

**Endpoints**:
- `GET /metrics/performance` - Latest metrics snapshot
- `GET /metrics/performance/stream` - SSE real-time streaming
- `GET /metrics/performance/summary` - Human-readable summary
- `GET /metrics/performance/aggressive-mode-score` - Individual metric
- `GET /metrics/performance/velocity-to-target` - Individual metric
- `GET /metrics/performance/days-remaining` - Individual metric

**Features**:
- Redis stream consumption
- SSE broadcasting to clients
- Auto-reconnection handling
- Connection tracking

**Files**:
- `app/routers/performance_metrics.py` - Endpoints (already deployed)

---

### 4. Signals-Site Live Dashboard

**What**: Real-time performance metrics dashboard with sparkline charts.

**Components**:
- `PerformanceMetricsSection.tsx` - SSE-enabled metrics display
- `PerformanceMetricsCard.tsx` - Individual metric cards

**Features**:
- Live SSE updates from signals-api
- Sparkline charts (last 50 data points)
- Color-coded status indicators (green/yellow/red)
- Connection status display
- Auto-reconnection with exponential backoff
- Trend indicators (up/down arrows)

**Dashboard URL**: https://aipredictedsignals.cloud/dashboard

**Integrated Into**: Main dashboard page (top section)

---

### 5. 48-Hour Soak Test Configuration

**What**: Production validation with turbo scalper + bar reaction strategies.

**Strategies**:
1. **Turbo Scalper (15s)**: 40% capital allocation
   - 6 trades/min max
   - 8 bps profit target
   - 6 bps stop loss
   - Maker-only orders

2. **Bar Reaction (5m)**: 60% capital allocation
   - 30 trades/day max
   - 20 bps trigger threshold
   - 2.5 ATR take profit

**5s Bars**: DISABLED by default, auto-enable if p95 latency < 50ms

**News Overrides**: OFF by default, 4h test window capability

**Monitoring**:
- Portfolio heat > 80% → Alert
- Latency p95 > 500ms → Alert + reduce frequency
- Redis lag > 2s → Pause turbo scalper
- Circuit breaker trips > 3/hour → Alert

**Pass Criteria** (Automated Validation):
```yaml
min_net_pnl_usd: 0.01             # Must be positive
min_profit_factor: 1.25
max_circuit_breaker_trips: 5
max_scalper_lag_messages: 5
max_portfolio_heat_pct: 80.0
max_latency_p95_ms: 500
```

**On Success**:
- Tag config as `PROD-CANDIDATE-v1`
- Export Prometheus snapshot
- Generate comprehensive report

**Files**:
- `config/soak_test_48h_turbo.yaml` - Master soak config
- `config/turbo_scalper_15s.yaml` - Turbo scalper config
- `SOAK_TEST_48H_DEPLOYMENT_GUIDE.md` - Complete deployment guide

---

## 🔧 Configuration Changes

### Environment Variables Added

```bash
# Performance Metrics
ENABLE_PERFORMANCE_METRICS=true
STARTING_EQUITY_USD=10000
TARGET_EQUITY_USD=20000
METRICS_UPDATE_INTERVAL=30

# Soak Test
SOAK_TEST_MODE=true
SOAK_TEST_VERSION=v1.0
CONFIG_PATH=config/soak_test_48h_turbo.yaml
```

### YAML Configs Updated

All strategy configs now include:
```yaml
protection_mode:
  enabled: true
  force_enabled: null
  equity_threshold_usd: 18000.0
  win_streak_threshold: 5
  risk_multiplier: 0.5
  sl_multiplier: 0.7
  tp_multiplier: 1.0
  rate_multiplier: 0.5
```

---

## 🚀 Deployment

### Services Deployed

1. **crypto-ai-bot** (Fly.io):
   - Soak test configuration
   - Performance metrics publisher
   - Protection Mode enabled
   - Health endpoint updated

2. **signals-api** (Fly.io):
   - Metrics endpoints (already deployed)
   - SSE streaming active

3. **signals-site** (Vercel):
   - Performance Metrics dashboard
   - Deployed commit: `d8f4b19`

### Deployment Commands

```bash
# crypto-ai-bot
cd crypto_ai_bot
fly deploy --ha=false --config config/soak_test_48h_turbo.yaml

# signals-site (auto-deployed via Vercel on push)
cd signals-site
git push origin main
```

---

## 📊 Monitoring & Observability

### Health Endpoints

| Service | URL | Key Fields |
|---------|-----|------------|
| crypto-ai-bot | `https://crypto-ai-bot.fly.dev/health` | `performance_metrics`, `publisher`, `status` |
| signals-api | `https://crypto-signals-api.fly.dev/health` | `redis_ping_ms`, `stream_lag_ms` |
| signals-site | `https://aipredictedsignals.cloud` | 200 OK |

### Redis Streams

```
metrics:performance          - Complete performance snapshots (30s)
metrics:aggressive_mode_score - Individual metric updates
metrics:velocity_to_target   - Individual metric updates
metrics:days_remaining       - Individual metric updates
protection:mode:state        - Protection mode state hash
protection:mode:events       - Protection mode events stream
```

### Prometheus Metrics

New metrics exposed at `/metrics`:
```
performance_aggressive_mode_score{} - Gauge
performance_velocity_to_target{} - Gauge
performance_days_remaining{} - Gauge
protection_mode_enabled{} - Gauge (0/1)
protection_mode_trades_since_activation{} - Counter
```

---

## 🧪 Testing

### Protection Mode Tests

Run comprehensive test suite:
```bash
cd crypto_ai_bot
conda activate crypto-bot
python scripts/test_protection_mode.py --test all
```

**Test Coverage**:
- ✅ Equity threshold activation ($18k)
- ✅ Win streak activation (5 wins)
- ✅ Manual override via Redis
- ✅ Parameter adjustments
- ✅ Deactivation logic
- ✅ Redis state publishing
- ✅ API endpoints

**Expected Result**: All tests pass (7/7)

### End-to-End Metrics Flow

1. crypto-ai-bot publishes to Redis
2. signals-api reads from Redis
3. signals-api SSE streams to frontend
4. signals-site dashboard displays live

**Verification**:
```bash
# 1. Check crypto-ai-bot publishing
curl https://crypto-ai-bot.fly.dev/health | jq .performance_metrics

# 2. Check signals-api endpoints
curl https://crypto-signals-api.fly.dev/metrics/performance/summary | jq

# 3. Open dashboard in browser
open https://aipredictedsignals.cloud/dashboard
```

---

## 📚 Documentation

### New Documentation

- `PROTECTION_MODE_RUNBOOK.md` - Complete Protection Mode guide
- `SOAK_TEST_48H_DEPLOYMENT_GUIDE.md` - 48h soak test deployment
- `METRICS_INTEGRATION_PATCH.md` - Metrics integration guide
- `METRICS_ENDPOINTS_IMPLEMENTATION.md` - signals-api implementation
- `METRICS_UI_IMPLEMENTATION.md` - signals-site implementation

### Updated Documentation

- `RUNBOOK.md` - Added Protection Mode section
- `main.py` - Inline documentation for metrics publisher

---

## ⚠️  Breaking Changes

**None** - This is a feature-additive release with no breaking changes.

All new features are:
- Feature-flagged (can be disabled)
- Backward compatible
- Opt-in via configuration

---

## 🐛 Known Issues

### Minor Warnings

**signals-site build warnings** (non-blocking):
```
- React Hook useEffect missing dependencies (3 warnings)
```
These are linting warnings that don't affect functionality. Will address in future release.

### Limitations

1. **Metrics display**: Requires completed trades to calculate
   - Initial dashboard may show "Waiting for data..."
   - Resolves after first few trades complete

2. **SSE reconnection**: May take 5-10s after connection drop
   - Built-in exponential backoff
   - Auto-reconnects without data loss

---

## 🔮 Next Steps

### Post-Deployment (48h Soak Test)

1. Monitor health endpoints every 6 hours
2. Check checkpoint reports at 6h, 12h, 24h, 48h
3. Verify no sustained circuit breaker trips
4. Verify latency stays < 500ms p95
5. Validate pass criteria at 48h

### On Success

1. Tag config as `PROD-CANDIDATE-v1`
2. Export Prometheus snapshot
3. Generate final report
4. Prepare for production promotion

### Future Enhancements

- [ ] Protection Mode API endpoints in signals-api
- [ ] Protection Mode status indicator on dashboard
- [ ] Historical metrics charts (longer time windows)
- [ ] SMS/Email alerts for Protection Mode activation
- [ ] Backtesting with Protection Mode enabled

---

## 👥 Contributors

- Claude Code (Implementation, Testing, Documentation)
- User (Product Requirements, Testing)

---

## 📄 License

Proprietary - All Rights Reserved

---

## 🆘 Support

**Issues**: Check runbooks first
**Emergency**: Redis-based kill switch available
**Contact**: See RUNBOOK.md for escalation procedures

---

**End of Release Notes v1.0.0**

---

## Quick Start Commands

```bash
# Deploy all services
cd crypto_ai_bot && fly deploy --ha=false
cd signals-site && git push origin main

# Run Protection Mode tests
python scripts/test_protection_mode.py --test all

# Monitor soak test
fly logs --app crypto-ai-bot | grep -E "PROTECTION|METRICS|SOAK"
curl https://crypto-ai-bot.fly.dev/health | jq .performance_metrics

# Open dashboard
open https://aipredictedsignals.cloud/dashboard

# Manual Protection Mode override (if needed)
redis-cli -u rediss://default:Salam78614**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 \
  --tls --cacert config/certs/redis_ca.pem \
  SET protection:mode:override "enabled"
```
