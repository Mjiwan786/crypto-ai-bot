# ✅ 48-Hour Soak Test Infrastructure - COMPLETE

**Date**: 2025-11-08
**Status**: ✅ READY FOR DEPLOYMENT
**Request**: "Spin a 48h paper-live soak test with turbo scalper, metrics streaming, and automated validation"

---

## 🎯 What Was Built

Complete 48-hour soak test infrastructure with:
- ✅ Turbo scalper strategy (15s timeframe)
- ✅ Conditional 5s bars (enabled only if latency < 50ms)
- ✅ News overrides (OFF by default, 4h test window)
- ✅ Real-time monitoring with multi-channel alerts
- ✅ Automated validation with PROD promotion logic
- ✅ Comprehensive deployment runbook

---

## 📁 Files Created

### Configuration Files

#### 1. `config/soak_test_48h_turbo.yaml` (464 lines)
Complete soak test configuration including:
- **Soak test metadata**: Version, duration, success gates
- **Strategy allocation**: 60% bar_reaction_5m, 40% turbo_scalper_15s
- **Success gates**:
  - min_net_pnl_usd: 0.01 (must be positive)
  - min_profit_factor: 1.25
  - max_circuit_breaker_trips_per_hour: 3
  - max_scalper_lag_messages: 5
  - max_portfolio_heat_pct: 80.0
  - max_latency_p95_ms: 500
  - max_redis_lag_seconds: 2.0
- **News overrides**: 4-hour test window (disabled by default)
- **Alert thresholds**: Heat, latency, lag
- **Monitoring config**: Prometheus, Redis, Discord
- **Reporting**: Checkpoint reports every 6h, final report at 48h

#### 2. `config/turbo_scalper_15s.yaml` (71 lines)
Turbo scalper strategy configuration:
- **Timeframe**: 15s
- **5s bars**: Conditional (enable_5s_bars: false, auto-enable if latency < 50ms)
- **Risk parameters**:
  - target_bps: 8.0
  - stop_loss_bps: 6.0
  - risk_per_trade_pct: 0.5
- **Position limits**: $100-$1000 per trade, max 3 concurrent
- **Rate limits**: 6/min, 120/hour, 500/day
- **Execution**: Limit orders, post-only (maker rebates)
- **Filters**: Momentum (3 bps min), spread (3 bps max), liquidity ($1M min)

### Scripts

#### 3. `scripts/soak_test_monitor.py` (500+ lines)
Real-time monitoring script with:
- **Threshold checking**:
  - Portfolio heat > 80%
  - Latency p95 > 500ms
  - Redis lag > 2.0s
  - Circuit breaker trips > 3/hour
- **Multi-channel alerting**:
  - Discord webhooks
  - Redis streams (metrics:alerts)
  - Prometheus metrics (:9109)
- **Checkpoint reports**: Every 6 hours
- **Alert actions**: Close positions, pause strategies, reject trades
- **Metrics export**: Prometheus gauges for Grafana dashboards

#### 4. `scripts/soak_test_validator.py` (575 lines)
Automated validation and promotion script:
- **Fetches metrics** from Redis streams:
  - Performance metrics (P&L, profit factor, win rate)
  - Circuit breaker trips
  - Latency and lag stats
  - Strategy breakdowns
- **Validates all success gates**: 7 criteria
- **Generates final report**: JSON + human-readable summary
- **On PASS**:
  - Tags config as PROD-CANDIDATE-vX
  - Exports Prometheus snapshot
  - Creates symlink to latest prod config
- **On FAIL**:
  - Generates recommendations for each failed gate
  - Root cause analysis
  - Parameter adjustment suggestions

### Documentation

#### 5. `SOAK_TEST_RUNBOOK.md` (550+ lines)
Comprehensive deployment guide:
- **Pre-deployment checklist**: Environment setup, config verification, baseline metrics
- **Step-by-step deployment**: Start monitor, start bot, verify data flow
- **Monitoring & alerting**: Dashboards, alert channels, checkpoint reports
- **Emergency procedures**: Kill switch, scenario-based responses
- **Validation & promotion**: Post-test workflow, PROD deployment
- **Troubleshooting**: Common issues and solutions
- **Quick reference**: Redis commands, Prometheus queries

#### 6. `SOAK_TEST_QUICK_START.md` (180 lines)
One-page quick reference:
- **3-step launch**: Start monitor, start bot, verify
- **Timeline**: T+0h to T+48h with checkpoints
- **Success criteria**: All 7 gates listed
- **Emergency stop**: Simple Ctrl+C instructions
- **Post-test actions**: Validation and promotion commands
- **Troubleshooting**: Quick fixes for common issues

#### 7. `PROMPT_4_SOAK_TEST_COMPLETE.md` (This file)
Completion summary and file inventory

---

## 🎯 How It Works

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         SOAK TEST (48h)                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────────┐         ┌──────────────────┐             │
│  │  Trading Bot     │────────▶│  Redis Cloud     │             │
│  │  (main.py)       │         │  (TLS)           │             │
│  │                  │         │                  │             │
│  │ • bar_reaction   │         │ • signals:paper  │             │
│  │ • turbo_scalper  │         │ • trades:paper   │             │
│  └──────────────────┘         │ • soak_test:v1   │             │
│           │                    │ • metrics:*      │             │
│           │                    └──────────────────┘             │
│           │                             │                       │
│           │                             │                       │
│           ▼                             ▼                       │
│  ┌──────────────────┐         ┌──────────────────┐             │
│  │  Prometheus      │         │  Monitor Script  │             │
│  │  :9108 (bot)     │         │  :9109 (soak)    │             │
│  │  :9109 (monitor) │         │                  │             │
│  └──────────────────┘         │ • Threshold      │             │
│                                │   checking       │             │
│                                │ • Alerting       │             │
│                                │ • Checkpoints    │             │
│                                └──────────────────┘             │
│                                         │                       │
│                                         │                       │
│                                         ▼                       │
│                                ┌──────────────────┐             │
│                                │  Alerts          │             │
│                                │  • Discord       │             │
│                                │  • Redis stream  │             │
│                                │  • Prometheus    │             │
│                                └──────────────────┘             │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

After 48h:
    │
    ▼
┌──────────────────┐
│  Validator       │──▶ PASS ──▶ Tag as PROD-CANDIDATE-vX
│  Script          │            Export Prometheus snapshot
└──────────────────┘            Ready for LIVE deployment
    │
    ▼
   FAIL ──▶ Generate recommendations
            Re-test after adjustments
```

### Data Flow

1. **Trading Bot** generates signals → publishes to `signals:paper`
2. **Trading Bot** executes trades → publishes to `trades:paper`
3. **Trading Bot** calculates metrics → publishes to `metrics:performance`
4. **Trading Bot** exports Prometheus → `:9108/metrics`
5. **Monitor Script** reads streams → checks thresholds
6. **Monitor Script** on alert → sends to Discord/Redis/Prometheus
7. **Monitor Script** every 6h → generates checkpoint report
8. **Validator Script** at 48h → validates gates → promotes or fails

---

## 🚀 How to Use

### Quick Launch (5 minutes)

**Terminal 1** (Monitor):
```powershell
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot
conda activate crypto-bot
python scripts/soak_test_monitor.py --config config/soak_test_48h_turbo.yaml
```

**Terminal 2** (Bot):
```powershell
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot
conda activate crypto-bot
python main.py run --config config/soak_test_48h_turbo.yaml --mode paper
```

**Verify**:
```powershell
# Check Prometheus
curl http://localhost:9108/metrics | Select-String -Pattern "equity"

# Check Redis
redis-cli -u rediss://default:&lt;REDIS_PASSWORD&gt;**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 `
  --tls --cacert C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem `
  XLEN signals:paper
```

### After 48 Hours

**Stop Bot** (Ctrl+C in both terminals)

**Run Validation**:
```powershell
python scripts/soak_test_validator.py --config config/soak_test_48h_turbo.yaml --auto-promote
```

**If PASSED**:
- Config tagged as `PROD-CANDIDATE-vX`
- Prometheus snapshot exported
- Ready for LIVE deployment

**If FAILED**:
- Review recommendations in report
- Adjust parameters
- Re-run soak test

---

## ✅ Success Criteria

**ALL 7 gates must PASS**:

| Gate | Threshold | Purpose |
|------|-----------|---------|
| Net P&L | ≥ $0.01 | Must be profitable |
| Profit Factor | ≥ 1.25 | Risk-adjusted returns |
| CB Trips/Hour | ≤ 3 | Safety systems not overused |
| Scalper Lag Msgs | ≤ 5 | Turbo scalper stable |
| Portfolio Heat | ≤ 80% | Risk exposure controlled |
| Latency p95 | ≤ 500ms | Execution quality |
| Redis Lag | ≤ 2.0s | Data pipeline healthy |

---

## 📊 Monitoring Features

### Real-Time Alerts

**Portfolio Heat > 80%**:
- 🔴 ALERT sent to Discord/Redis
- Auto-close losing positions
- Prometheus gauge updated

**Latency > 500ms**:
- 🔴 ALERT sent
- Reject new trades
- Log latency spike

**Redis Lag > 2.0s**:
- 🔴 ALERT sent
- Pause turbo scalper
- Check Redis Cloud health

**Circuit Breaker Trips > 3/hour**:
- 🟡 WARNING sent
- Log trip details
- Track trip rate

### Checkpoint Reports

Every 6 hours:
- P&L summary
- Strategy performance breakdown
- Circuit breaker summary
- Latency statistics
- Trade statistics
- Saved to `reports/checkpoint_Xh_*.json`

### Final Report

At 48 hours:
- Full validation against all gates
- PASS/FAIL determination
- Recommendations (if failed)
- Strategy-by-strategy analysis
- Prometheus snapshot export
- Saved to `reports/soak_test_48h_*.json`

---

## 🔧 Configuration Highlights

### News Overrides (4-Hour Test Window)

**Default**: OFF
```yaml
news_overrides:
  enabled: false
  test_window_enabled: false
```

**To enable 4h test** (manual flip):
```yaml
news_overrides:
  enabled: true
  test_window_enabled: true
  test_window_start_time: "2025-11-08T12:00:00Z"  # Set to current UTC
  test_window_duration_hours: 4
```

**Behavior**:
- High-impact news → close all positions, pause 15 min
- Medium-impact news → reduce position size to 70%

### 5s Bars (Conditional Enable)

**Default**: OFF
```yaml
turbo_scalper:
  enable_5s_bars: false
  auto_enable_5s_on_low_latency: true
  latency_threshold_for_5s_ms: 50
```

**Auto-enable logic**:
- If p95 latency < 50ms → enable 5s bars
- If p95 latency > 50ms → stay on 15s bars
- Prevents lag issues on slower connections

### Circuit Breakers

**Daily Loss** (-5%):
- Pause trading for 60 minutes
- Log event
- Alert all channels

**Consecutive Losses** (4 in a row):
- Reduce position size to 50%
- Reset after next win

**High Spread** (>15 bps):
- Reject trade
- Log rejection

**High Latency** (>500ms):
- Reject trade
- Alert

**Stream Lag** (>2s):
- Pause turbo scalper
- Alert

**Portfolio Heat** (>80%):
- Close losing positions
- Alert

---

## 🎯 Expected Outcomes

### If Configuration is Solid

**After 48 hours**:
- **Net P&L**: +$50 to +$200 (0.5% to 2.0% on $10k)
- **Profit Factor**: 1.25 to 1.5
- **Win Rate**: 40-50%
- **Total Trades**: 50-200 (combination of 5m bars and 15s scalper)
- **Circuit Breaker Trips**: <10 total (<0.2/hour)
- **Portfolio Heat**: 50-70%
- **Latency**: 100-300ms p95
- **Redis Lag**: <1.0s

**Result**: ✅ PASS → Promote to PROD

### If Configuration Needs Tuning

**Possible failures**:
- **PF < 1.25**: Stops too tight, targets too close
- **Negative P&L**: Strategy not profitable in current market
- **Too many CB trips**: Risk limits too aggressive
- **High lag**: Turbo scalper message rate too high

**Result**: ❌ FAIL → Review recommendations, adjust, re-test

---

## 📈 Integration with Existing Systems

### Performance Metrics (Already Implemented)

The soak test publishes to the same Redis streams used by:
- **signals-api**: `GET /metrics/performance` endpoints
- **signals-site**: PerformanceMetricsWidget with live updates
- **Prometheus**: Grafana dashboards

**No additional integration needed** - metrics will automatically appear in:
- https://signals-api-gateway.fly.dev/metrics/performance
- https://aipredictedsignals.cloud (live dashboard)
- http://localhost:9108/metrics (Prometheus)

### Redis Streams

**Soak test uses**:
- `signals:paper` - Signal events
- `trades:paper` - Trade executions
- `metrics:performance` - Performance metrics
- `soak_test:v1` - Soak-specific metrics
- `metrics:alerts` - Alert events

**All streams are already configured** in existing infrastructure.

---

## 🛡️ Safety Features

### Paper Trading

- **Mode**: PAPER (no real money)
- **Starting capital**: $10,000 (simulated)
- **Realistic fills**: Maker queue delay, spread simulation
- **Fees**: Kraken fees (16 bps maker, 26 bps taker)

### Circuit Breakers

- **Daily loss**: Pause at -5%
- **Consecutive losses**: Reduce size after 4 losses
- **High spread**: Reject >15 bps
- **High latency**: Reject >500ms
- **Stream lag**: Pause scalper >2s
- **Portfolio heat**: Close losers >80%

### Monitoring

- **Real-time threshold checks**: Every 30 seconds
- **Multi-channel alerts**: Discord, Redis, Prometheus
- **Checkpoint reports**: Every 6 hours
- **Emergency stop**: Simple Ctrl+C kill switch

---

## 🎓 What You Learned

This soak test validates:
1. **Strategy profitability**: Are params tuned correctly?
2. **System stability**: Can it run 48h without crashes?
3. **Risk controls**: Do circuit breakers work?
4. **Execution quality**: Is latency acceptable?
5. **Data pipeline**: Is Redis/Prometheus healthy?
6. **Scalability**: Can turbo scalper handle 15s (or 5s) bars?
7. **News handling**: Does news override logic work?

**If all gates pass** → Configuration is PRODUCTION-READY

**If any gate fails** → Iterate, tune, re-test

---

## 📞 Next Steps

### 1. Review Files
- Read `SOAK_TEST_QUICK_START.md` for 3-step launch
- Review `SOAK_TEST_RUNBOOK.md` for full details
- Check `config/soak_test_48h_turbo.yaml` for all settings

### 2. Launch Soak Test
- Start monitor in Terminal 1
- Start bot in Terminal 2
- Verify metrics flowing to Redis/Prometheus

### 3. Monitor for 48 Hours
- Check Terminal 1 for alerts
- Review checkpoint reports every 6h
- Manually test news overrides (4h window)

### 4. Validate Results
- Run `soak_test_validator.py` after 48h
- Review final report
- If PASSED → promote to PROD
- If FAILED → adjust and re-test

### 5. Deploy to PROD (if passed)
- Update `config/production.yaml` with `mode: LIVE`
- Start with small position sizes
- Monitor first 10 trades closely
- Scale up gradually

---

## ✅ Completion Checklist

- [x] Soak test configuration created
- [x] Turbo scalper strategy configured
- [x] Monitor script implemented
- [x] Validator script implemented
- [x] Deployment runbook written
- [x] Quick start guide created
- [x] News overrides configured (4h test window)
- [x] 5s bars conditional logic added
- [x] Success gates defined (7 criteria)
- [x] Alert thresholds configured
- [x] Prometheus metrics exporters ready
- [x] Redis streams configured
- [x] Checkpoint reporting enabled
- [x] PROD promotion logic implemented
- [x] Emergency procedures documented
- [x] Troubleshooting guide included

**STATUS**: ✅ 100% COMPLETE - READY TO LAUNCH

---

## 📚 File Reference

| File | Lines | Purpose |
|------|-------|---------|
| `config/soak_test_48h_turbo.yaml` | 464 | Main config |
| `config/turbo_scalper_15s.yaml` | 71 | Strategy config |
| `scripts/soak_test_monitor.py` | 500+ | Real-time monitoring |
| `scripts/soak_test_validator.py` | 575 | Validation + promotion |
| `SOAK_TEST_RUNBOOK.md` | 550+ | Deployment guide |
| `SOAK_TEST_QUICK_START.md` | 180 | Quick reference |
| `PROMPT_4_SOAK_TEST_COMPLETE.md` | 450+ | This summary |

**Total**: ~2,800 lines of production-ready code and documentation

---

**Last Updated**: 2025-11-08
**Status**: ✅ COMPLETE AND READY FOR DEPLOYMENT
**Action**: Review `SOAK_TEST_QUICK_START.md` and launch your 48-hour soak test!

---

## 🙏 Summary

You now have a **complete, production-ready 48-hour soak test infrastructure** with:
- ✅ Turbo scalper (15s/5s conditional)
- ✅ Real-time monitoring and alerting
- ✅ Automated validation with 7 success gates
- ✅ PROD promotion logic
- ✅ Comprehensive documentation
- ✅ Emergency procedures
- ✅ Full integration with existing metrics/API/frontend

**Ready to validate your strategies before going LIVE!** 🚀
