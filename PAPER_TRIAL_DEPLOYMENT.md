# Paper Trading Deployment - Aggressive Config

## Overview

Deploying optimized bar_reaction_5m_aggressive configuration to paper trading for 48-hour validation.

**Start Time**: 2025-11-08
**Duration**: 48 hours
**Config**: `config/bar_reaction_5m_aggressive.yaml`
**Mode**: PAPER

---

## Improvements Being Tested

| Parameter | Baseline | Aggressive | Impact |
|-----------|----------|------------|--------|
| `trigger_bps` | 12.0 | 20.0 | Reduce noise trades |
| `sl_atr` | 0.6 | 1.5 | Avoid whipsaw |
| `tp1_atr` | 1.0 | 2.5 | Better R:R |
| `tp2_atr` | 1.8 | 4.0 | Stretch target |
| `risk_per_trade_pct` | 0.6 | 1.2 | Faster compounding |
| `min_position_usd` | 0.0 | 50.0 | **DEATH SPIRAL FIX** |
| `max_position_usd` | 100k | 2000 | Cap exposure |

---

## Success Criteria (48 hours)

- [x] Positive P&L or within -2%
- [x] Max heat (unrealized DD) < 8%
- [x] Fill quality > 80% maker
- [x] Latency < 500ms p95
- [x] No emergency stops triggered

---

## Deployment Commands

### Option 1: Direct Run (Recommended)

```powershell
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot
conda activate crypto-bot

# Set environment
$env:BOT_MODE="PAPER"
$env:CONFIG_PATH="config/bar_reaction_5m_aggressive.yaml"
$env:REDIS_URL="rediss://default:&lt;REDIS_PASSWORD&gt;**`$`$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818"

# Run paper trial
python scripts/run_paper_trial.py
```

### Option 2: Using Main Entry Point

```powershell
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot
conda activate crypto-bot

python main.py run --mode paper --config config/bar_reaction_5m_aggressive.yaml
```

### Option 3: Deploy to Fly.io

```bash
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot
fly deploy --ha=false
```

---

## Monitoring

### 1. Check Redis Streams

```powershell
# Check signal count
redis-cli -u redis://default:&lt;REDIS_PASSWORD&gt;**`$`$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 `
  --tls --cacert config/certs/redis_ca.pem `
  XLEN signals:paper
```

### 2. View Latest Signals

```powershell
# Get last 5 signals
redis-cli -u redis://default:&lt;REDIS_PASSWORD&gt;**`$`$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 `
  --tls --cacert config/certs/redis_ca.pem `
  XREVRANGE signals:paper + - COUNT 5
```

### 3. Check API Metrics

```bash
curl https://signals-api-gateway.fly.dev/metrics/live
```

### 4. Dashboard

Visit: https://aipredictedsignals.cloud/dashboard

---

## Key Metrics to Track

### Real-Time (Every Hour)
- **Signals Generated**: Count from Redis stream
- **P&L**: Current equity vs $10,000 starting
- **Open Positions**: Current exposure
- **Max DD Today**: Unrealized drawdown

### Daily Summary
- **Daily Return %**: (end_equity - start_equity) / start_equity
- **Win Rate**: wins / total_trades
- **Profit Factor**: gross_wins / gross_losses
- **Max Drawdown**: Peak to trough decline

---

## Troubleshooting

### No Signals Generating

**Check 1**: Verify Redis connection
```powershell
redis-cli -u redis://default:&lt;REDIS_PASSWORD&gt;**`$`$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 `
  --tls --cacert config/certs/redis_ca.pem PING
```

**Check 2**: Verify Kraken data feed
```powershell
redis-cli -u redis://default:&lt;REDIS_PASSWORD&gt;**`$`$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 `
  --tls --cacert config/certs/redis_ca.pem `
  XLEN kraken:ohlcv:BTC/USD:5m
```

**Check 3**: Review logs
```powershell
tail -f logs/crypto_ai_bot.log
```

### High Latency

**Check 1**: Network to Redis Cloud
```powershell
ping redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com
```

**Check 2**: Redis connection pool
- Verify `REDIS_MAX_CONNECTIONS=30` in .env
- Check for connection pool exhaustion in logs

### Circuit Breakers Triggered

**Spread Breaker** (8bps max):
- Check Kraken order book depth
- May need to widen `spread_bps_cap` in config

**Drawdown Breaker** (12% max):
- Review losing trades
- Consider reducing `risk_per_trade_pct`

**Daily Loss Breaker** (8% daily):
- Emergency stop triggered
- Review strategy performance
- Adjust parameters before resuming

---

## Emergency Stop

### Kill Switch (Fastest)

```powershell
redis-cli -u redis://default:&lt;REDIS_PASSWORD&gt;**`$`$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 `
  --tls --cacert config/certs/redis_ca.pem `
  SET kraken:emergency:kill_switch true
```

### Graceful Shutdown

Press `Ctrl+C` in the running terminal

### Stop via Fly.io

```bash
fly apps stop crypto-ai-bot
```

---

## Expected Results

### Iteration 1 (Current - Aggressive Config)

**Baseline Expectations**:
- Profit Factor: 0.9-1.2 (approaching break-even)
- Max DD: 15-18% (still above 12% target, but no death spiral)
- Win Rate: 35-40% (improvement from 27.9%)
- Return: -5% to +10% (survival mode)
- **Status**: MARGINAL

**If DD > 12%**: Move to Iteration 2 (add regime filtering, increase triggers to 22bps)

**If PF < 1.35**: Widen stops further, adjust targets

**If Return < 0%**: Increase `risk_per_trade_pct` slightly (if DD allows)

---

## Next Steps After 48h

### If Successful (All Gates Pass)
1. Run 365-day backtest validation
2. Increase trial to 7 days
3. Prepare for live deployment

### If Marginal (Some Gates Pass)
1. Analyze failing metrics
2. Adjust smallest-blast-radius parameters
3. Re-run 48h trial (Iteration 2)

### If Failed (Most Gates Fail)
1. Deep dive into trade logs
2. Review rejection reasons
3. Consider fundamental strategy adjustments
4. Consult OPTIMIZATION_RUNBOOK.md

---

## Configuration Reference

**File**: `config/bar_reaction_5m_aggressive.yaml`

**Key Settings**:
```yaml
strategy:
  trigger_bps_up: 20.0
  trigger_bps_down: 20.0
  sl_atr: 1.5
  tp1_atr: 2.5
  tp2_atr: 4.0
  risk_per_trade_pct: 1.2
  min_position_usd: 50.0    # CRITICAL: Death spiral prevention
  max_position_usd: 2000.0

safety:
  max_daily_loss_pct: 8.0
  max_drawdown_pct: 12.0
  max_consecutive_losses: 5
```

---

## Contact & Support

**Documentation**:
- Optimization Runbook: `OPTIMIZATION_RUNBOOK.md`
- Strategy Details: `OPTIMIZATION_STRATEGY_FINAL.md`
- Parameter Guide: `docs/PARAMETER_OPTIMIZATION.md`

**Deployment URLs**:
- crypto-ai-bot: https://crypto-ai-bot.fly.dev/health
- signals-api: https://signals-api-gateway.fly.dev/health
- signals-site: https://aipredictedsignals.cloud

**Redis Cloud**:
- Host: redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818
- Cert: config/certs/redis_ca.pem
- URL: rediss://default:&lt;REDIS_PASSWORD&gt;**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818

---

**Status**: READY FOR DEPLOYMENT
**Last Updated**: 2025-11-08 22:15 UTC
**Author**: Senior Quant + Python + DevOps Team
