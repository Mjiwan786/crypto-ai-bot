# Crypto AI Bot - Operations Runbook

**Production Operations Guide for Trading System**

Last Updated: 2025-10-18
Environment: crypto-bot conda environment
Redis: Redis Cloud with TLS

---

## Table of Contents

1. [Quick Reference](#quick-reference)
2. [Daily Operations](#daily-operations)
3. [Starting the System](#starting-the-system)
4. [Monitoring](#monitoring)
5. [Protection Mode](#protection-mode)
6. [Emergency Procedures](#emergency-procedures)
7. [Mode Switching (PAPER ↔ LIVE)](#mode-switching)
8. [Troubleshooting](#troubleshooting)
9. [Maintenance Windows](#maintenance-windows)

---

## Quick Reference

### Essential Commands

```bash
# Activate conda environment
conda activate crypto-bot

# Check system health
python scripts/monitor_redis_streams.py --health

# View monitoring dashboard
python scripts/monitor_redis_streams.py

# Tail live streams (real-time)
python scripts/monitor_redis_streams.py --tail

# Emergency stop (FASTEST)
redis-cli -u $REDIS_URL SET kraken:emergency:kill_switch true

# Verify emergency stop active
redis-cli -u $REDIS_URL GET kraken:emergency:kill_switch

# Deactivate emergency stop
redis-cli -u $REDIS_URL DEL kraken:emergency:kill_switch
```

### Critical Redis Streams

- **`ACTIVE_SIGNALS`** - Current mode (signals:paper or signals:live)
- **`signals:paper`** - Paper trading signals
- **`signals:live`** - Live trading signals
- **`metrics:emergency`** - Emergency stop events
- **`metrics:circuit_breakers`** - Circuit breaker trips
- **`kraken:status`** - General status events

### Emergency Contacts

| Role | Contact | Responsibility |
|------|---------|----------------|
| On-call Engineer | [Your contact] | System operations, kill-switch |
| Trading Lead | [Your contact] | Trading decisions, risk management |
| DevOps | [Your contact] | Infrastructure, Redis, deployments |

---

## Daily Operations

### Morning Checklist (Before Market Open)

```bash
# 1. Activate environment
conda activate crypto-bot

# 2. Health check
python scripts/monitor_redis_streams.py --health

# 3. Verify mode
python -c "from dotenv import load_dotenv; load_dotenv(); import os; print(f'Mode: {os.getenv(\"TRADING_MODE\", \"PAPER\")}')"

# 4. Check for overnight issues
python scripts/monitor_redis_streams.py --count 20 | grep -i "error\|emergency\|circuit"

# 5. Verify Redis connection
redis-cli -u $REDIS_URL PING

# 6. Check emergency stop status
redis-cli -u $REDIS_URL GET kraken:emergency:kill_switch
```

**Expected Results:**
- Health check: ✓ PASSED
- Mode: PAPER (or LIVE if authorized)
- No recent emergencies or circuit breakers
- Redis: PONG
- Emergency stop: (nil) or false

### During Market Hours

Monitor continuously:

```bash
# Open terminal 1 - Real-time stream monitoring
python scripts/monitor_redis_streams.py --tail

# Open terminal 2 - Health checks every 5 minutes
watch -n 300 "python scripts/monitor_redis_streams.py --health"
```

**Watch for:**
- Frequent circuit breaker trips (>5 per hour)
- Emergency stop activations
- Mode changes (should be intentional only)
- Signal generation rate (should be steady, not erratic)

### End of Day Checklist

```bash
# 1. Review day's activity
python scripts/monitor_redis_streams.py --streams metrics:circuit_breakers metrics:emergency --count 100

# 2. Check for any warnings
python scripts/monitor_redis_streams.py --health

# 3. Verify no emergency stops active
redis-cli -u $REDIS_URL GET kraken:emergency:kill_switch

# 4. Optional: Review PnL (if in LIVE mode)
# python scripts/health_check_pnl.py

# 5. Document any incidents
# Update INCIDENTS_LOG.md if any issues occurred
```

---

## Starting the System

### Paper Trading (Default - Safe)

```bash
# 1. Activate environment
conda activate crypto-bot

# 2. Set mode
export TRADING_MODE=PAPER

# 3. Dry run (validate only, don't start)
python scripts/start_trading_system.py --mode paper --dry-run

# 4. Start system
python scripts/start_trading_system.py --mode paper

# 5. Verify running
python scripts/monitor_redis_streams.py --health
```

### Live Trading (Requires Authorization)

⚠️ **DANGER: REAL MONEY AT RISK** ⚠️

```bash
# 1. Activate environment
conda activate crypto-bot

# 2. Set mode and confirmation
export TRADING_MODE=LIVE
export LIVE_TRADING_CONFIRMATION=I-accept-the-risk

# 3. Verify credentials
echo "API Key: ${KRAKEN_API_KEY:0:8}..."
echo "Confirmation: $LIVE_TRADING_CONFIRMATION"

# 4. Dry run first
python scripts/start_trading_system.py --mode live --dry-run

# 5. Start system (only if dry run passed)
python scripts/start_trading_system.py --mode live

# 6. Monitor CLOSELY for first hour
python scripts/monitor_redis_streams.py --tail
```

### Stopping the System

```bash
# Graceful shutdown (Ctrl+C in terminal)
# Or if running in background:
pkill -SIGTERM -f "start_trading_system.py"

# Verify stopped
ps aux | grep start_trading_system
```

---

## Monitoring

### Health Check

```bash
python scripts/monitor_redis_streams.py --health
```

**Interpretation:**
- **✓ HEALTH CHECK PASSED** - All systems operational
- **❌ HEALTH CHECK FAILED** - Investigate issues immediately
- **⚠️ Warnings** - Review but system can continue

### Dashboard View

```bash
# Show last 10 entries per stream
python scripts/monitor_redis_streams.py

# Show more history
python scripts/monitor_redis_streams.py --count 50

# Watch specific streams
python scripts/monitor_redis_streams.py --streams signals:paper kraken:status
```

### Real-Time Monitoring (Tail Mode)

```bash
# Tail all critical streams
python scripts/monitor_redis_streams.py --tail

# Tail specific streams
python scripts/monitor_redis_streams.py --tail --streams signals:paper metrics:circuit_breakers
```

**What to Watch:**
- ✓ = Normal operation
- ⚠️ = Warning (review but continue)
- ❌ = Error (investigate immediately)
- 🚨 = Emergency (take action now)

### Grafana Dashboard (Optional)

If Grafana is set up:

1. Navigate to: `http://localhost:3000`
2. Dashboard: "Crypto AI Bot - Go-Live Controls"
3. Panels:
   - Signal generation rate
   - Circuit breaker trips
   - Emergency stop status
   - Mode changes timeline

---

## Protection Mode

**Auto-switches when equity >= $18k or win streak >= 5 to protect profits**

### What is Protection Mode?

Protection Mode automatically reduces risk when:
- **Equity reaches $18,000** (protect accumulated profits)
- **Win streak reaches 5** (prevent overconfidence)

When enabled, Protection Mode:
- **Halves position sizes** (0.5x multiplier)
- **Tightens stops by 30%** (exit faster on reversals)
- **Reduces max trades/min by 50%** (slower pace)

### Check Protection Mode Status

```bash
# Check current status
python -c "from config.protection_mode_controller import get_protection_controller; print(get_protection_controller().get_status_summary())"

# Or via Redis stream
redis-cli -u $REDIS_URL XREVRANGE protection:status + - COUNT 1
```

**Expected Output:**
```
============================================================
PROTECTION MODE STATUS
============================================================
Status: [ACTIVE] or [INACTIVE]

Current State:
  Equity: $20,500.00 (threshold: $18,000.00)
  Win Streak: 3 (threshold: 5)

Configuration:
  Auto Enable: Yes
  Manual Override: No
  Controlled By: auto
============================================================
```

### Manual Override Commands

**Enable Protection Mode (Manual)**
```bash
# Force enable regardless of triggers
redis-cli -u $REDIS_URL XADD protection:commands * command enable

# Enable manual override (stays on until manually disabled)
redis-cli -u $REDIS_URL XADD protection:commands * command enable_manual_override
```

**Disable Protection Mode (Manual)**
```bash
# Force disable
redis-cli -u $REDIS_URL XADD protection:commands * command disable

# Disable manual override (return to auto mode)
redis-cli -u $REDIS_URL XADD protection:commands * command disable_manual_override
```

### Update Triggers via Redis

```bash
# Update equity (triggers auto-enable if >= $18k)
redis-cli -u $REDIS_URL XADD protection:commands * command update_equity equity_usd 20000

# Update win streak (triggers auto-enable if >= 5)
redis-cli -u $REDIS_URL XADD protection:commands * command update_win_streak win_streak 6
```

### Configuration File

Edit `config/protection_mode.yaml`:

```yaml
# Mode control
enabled: false  # Current state (auto-managed)
auto_enable: true  # Auto-enable based on triggers
manual_override: false  # Manual override (ignores triggers)

# Triggers
triggers:
  equity_threshold_usd: 18000.0  # Protect profits at $18k
  win_streak_threshold: 5  # Reduce risk after 5 consecutive wins

# Protection parameters
parameters:
  position_size_multiplier: 0.5  # Halve all position sizes
  stop_loss_tightening_pct: 0.3  # Tighten stops by 30%
  max_trades_per_minute_reduction_pct: 0.5  # Reduce by 50%
```

### When to Use Manual Override

**Enable Manual Override When:**
- Approaching major resistance levels
- High volatility expected (news events, Fed announcements)
- Profit target for day/week nearly reached
- Want to lock in profits and trade conservatively

**Disable Manual Override When:**
- Market conditions normalize
- Equity drops significantly below threshold
- Want to resume aggressive profit-taking

### Hysteresis Behavior

Protection Mode uses hysteresis to prevent oscillation:

- **Auto-enable:** Equity >= $18,000 or Win Streak >= 5
- **Auto-disable:**
  - Equity < $17,100 (95% of threshold)
  - Win Streak = 0 (streak broken)

This prevents rapid on/off switching near the threshold.

### Monitoring Protection Mode

**Add to Daily Checklist:**
```bash
# Check protection mode status
python -c "from config.protection_mode_controller import get_protection_controller; c = get_protection_controller(); print(f'Protection Mode: {\"ACTIVE\" if c.config.enabled else \"INACTIVE\"}'); print(f'Equity: ${c.config.current_equity_usd:.2f}'); print(f'Win Streak: {c.config.current_win_streak}')"
```

**Watch for Protection Mode Events:**
```bash
# Monitor protection status stream
redis-cli -u $REDIS_URL XREAD BLOCK 0 STREAMS protection:status $
```

### Troubleshooting

**Issue: Protection Mode not auto-enabling at $18k**
```bash
# Check configuration
cat config/protection_mode.yaml | grep equity_threshold_usd

# Check auto_enable flag
cat config/protection_mode.yaml | grep auto_enable

# Manually trigger
redis-cli -u $REDIS_URL XADD protection:commands * command enable
```

**Issue: Protection Mode stuck ON**
```bash
# Check if manual override is enabled
python -c "from config.protection_mode_controller import get_protection_controller; print(get_protection_controller().config.manual_override)"

# Disable manual override
redis-cli -u $REDIS_URL XADD protection:commands * command disable_manual_override
```

**Issue: Want to change threshold**
```bash
# Edit config/protection_mode.yaml
vim config/protection_mode.yaml

# Change equity_threshold_usd to desired value (e.g., 20000.0)
# Restart trading system to apply changes
```

---

## Emergency Procedures

### Emergency Stop Activation

**When to Activate:**
- Unexpected market behavior
- Strategy malfunction
- Excessive losses
- Exchange maintenance
- Regulatory concerns
- System instability

**Method 1: Redis (Instant - FASTEST) ⚡**

```bash
redis-cli -u $REDIS_URL SET kraken:emergency:kill_switch true
```

**Method 2: Environment Variable (Requires Restart)**

```bash
export KRAKEN_EMERGENCY_STOP=true
# Then restart trading system
```

**Method 3: Python API**

```python
from config.trading_mode_controller import TradingModeController
import redis, os

r = redis.from_url(os.getenv('REDIS_URL'), ...)
controller = TradingModeController(r)
controller.activate_emergency_stop(reason="[Your reason here]")
```

### Verify Emergency Stop Active

```bash
# Check Redis
redis-cli -u $REDIS_URL GET kraken:emergency:kill_switch
# Expected: "true"

# Check via monitoring
python scripts/monitor_redis_streams.py --health
# Expected: Warning about emergency stop

# Check recent events
redis-cli -u $REDIS_URL XREVRANGE metrics:emergency + - COUNT 1
```

### During Emergency Stop

**What Happens:**
- ❌ New entries blocked
- ✅ Position exits allowed
- ✅ Market data continues
- ✅ Monitoring continues

**Actions to Take:**

1. **Assess Situation**
   ```bash
   # Check positions
   # Check recent trades
   # Review error logs
   tail -f logs/trading_system_*.log
   ```

2. **Close Positions (if needed)**
   ```bash
   # Exits are still allowed during emergency stop
   # Use exchange UI or API to close positions
   ```

3. **Investigate Root Cause**
   - Review circuit breaker events
   - Check for repeated errors
   - Verify market data quality
   - Check system resources

4. **Document Incident**
   ```bash
   # Create incident report
   echo "$(date): Emergency stop activated - [reason]" >> INCIDENTS_LOG.md
   ```

### Deactivate Emergency Stop

**Only deactivate when:**
- Root cause identified and fixed
- Positions closed or under control
- Market conditions normalized
- System validated in paper mode
- Team approval obtained

```bash
# Clear Redis flag
redis-cli -u $REDIS_URL DEL kraken:emergency:kill_switch

# Verify cleared
redis-cli -u $REDIS_URL GET kraken:emergency:kill_switch
# Expected: (nil)

# Confirm via monitoring
python scripts/monitor_redis_streams.py --health
# Expected: No emergency stop warnings
```

---

## Mode Switching

### Prerequisites

Before switching modes:

- [ ] System health check passed
- [ ] No active emergency stops
- [ ] Proper authorization obtained
- [ ] Configuration validated
- [ ] Monitoring in place

### PAPER → LIVE

⚠️ **CRITICAL: REAL MONEY RISK** ⚠️

**Step-by-step:**

```bash
# 1. Verify currently in PAPER
redis-cli -u $REDIS_URL GET ACTIVE_SIGNALS
# Expected: "signals:paper"

# 2. Run in PAPER for 24-48 hours first
# Monitor signals:paper stream
python scripts/monitor_redis_streams.py --streams signals:paper --count 100

# 3. Review performance
# Check signal quality, win rate, error rate

# 4. Set confirmation
export LIVE_TRADING_CONFIRMATION=I-accept-the-risk

# 5. Update trading mode
export TRADING_MODE=LIVE

# 6. Restart system
# Stop current: Ctrl+C
python scripts/start_trading_system.py --mode live

# 7. Verify LIVE mode active
redis-cli -u $REDIS_URL GET ACTIVE_SIGNALS
# Expected: "signals:live"

# 8. Monitor CLOSELY for first hour
python scripts/monitor_redis_streams.py --tail
```

### LIVE → PAPER

**Step-by-step:**

```bash
# 1. Stop trading system
# Ctrl+C or pkill

# 2. Close all positions (IMPORTANT)
# Use exchange UI or API

# 3. Update mode
export TRADING_MODE=PAPER

# 4. Remove live confirmation
unset LIVE_TRADING_CONFIRMATION

# 5. Restart system
python scripts/start_trading_system.py --mode paper

# 6. Verify PAPER mode active
redis-cli -u $REDIS_URL GET ACTIVE_SIGNALS
# Expected: "signals:paper"
```

---

## Troubleshooting

### System Won't Start

**Check:**

```bash
# 1. Environment active?
conda info --envs | grep crypto-bot
# Should show * next to crypto-bot

# 2. Required env vars set?
env | grep -E "REDIS_URL|TRADING_MODE|KRAKEN_"

# 3. Redis connection?
redis-cli -u $REDIS_URL PING
# Expected: PONG

# 4. Config valid?
python scripts/start_trading_system.py --mode paper --dry-run

# 5. Check logs
tail -50 logs/trading_system_*.log
```

### No Signals Being Generated

**Check:**

```bash
# 1. System running?
ps aux | grep start_trading_system

# 2. Active signal stream?
redis-cli -u $REDIS_URL GET ACTIVE_SIGNALS

# 3. Emergency stop active?
redis-cli -u $REDIS_URL GET kraken:emergency:kill_switch

# 4. Recent errors?
python scripts/monitor_redis_streams.py --streams kraken:status --count 20
```

### Circuit Breakers Triggering Frequently

**Investigate:**

```bash
# View recent breakers
python scripts/monitor_redis_streams.py --streams metrics:circuit_breakers --count 50

# Check latency
# Review spread widening
# Verify WebSocket connection
# Check system resources (CPU, memory, network)
```

**Solutions:**
- Increase latency threshold if network is slow
- Increase spread threshold if market is volatile
- Check exchange API status
- Verify system clock sync (NTP)
- Review rate limiting configuration

### Redis Connection Issues

**Check:**

```bash
# 1. URL correct?
echo $REDIS_URL

# 2. TLS enabled?
echo $REDIS_TLS

# 3. Network connectivity?
ping redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com

# 4. Test connection
redis-cli -u $REDIS_URL --tls PING

# 5. Check credentials
# Verify password in .env matches Redis Cloud
```

---

## Maintenance Windows

### Planned Maintenance Checklist

**Before Maintenance:**

```bash
# 1. Activate emergency stop
redis-cli -u $REDIS_URL SET kraken:emergency:kill_switch true

# 2. Close all positions
# Use exchange UI

# 3. Stop trading system
pkill -SIGTERM -f "start_trading_system.py"

# 4. Backup current state
redis-cli -u $REDIS_URL --rdb backup_$(date +%Y%m%d_%H%M%S).rdb

# 5. Document maintenance window
echo "$(date): Maintenance started - [reason]" >> MAINTENANCE_LOG.md
```

**During Maintenance:**

- Perform updates/changes
- Test in paper mode
- Validate configuration
- Run health checks

**After Maintenance:**

```bash
# 1. Health check
python scripts/monitor_redis_streams.py --health

# 2. Dry run
python scripts/start_trading_system.py --mode paper --dry-run

# 3. Start in PAPER first
python scripts/start_trading_system.py --mode paper

# 4. Verify functioning
python scripts/monitor_redis_streams.py --tail

# 5. Clear emergency stop (if appropriate)
redis-cli -u $REDIS_URL DEL kraken:emergency:kill_switch

# 6. Document completion
echo "$(date): Maintenance completed successfully" >> MAINTENANCE_LOG.md
```

### Exchange Maintenance

When Kraken announces maintenance:

```bash
# 1. Activate emergency stop
redis-cli -u $REDIS_URL SET kraken:emergency:kill_switch true

# 2. System can continue running
# Market data will pause, no new entries

# 3. After exchange maintenance
redis-cli -u $REDIS_URL DEL kraken:emergency:kill_switch
```

---

## Appendix

### Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `REDIS_URL` | Yes | - | Redis Cloud connection URL |
| `TRADING_MODE` | Yes | PAPER | PAPER or LIVE |
| `LIVE_TRADING_CONFIRMATION` | LIVE only | - | Must be "I-accept-the-risk" |
| `KRAKEN_API_KEY` | LIVE only | - | Kraken API key |
| `KRAKEN_API_SECRET` | LIVE only | - | Kraken API secret |
| `KRAKEN_EMERGENCY_STOP` | No | false | Emergency kill-switch |
| `TRADING_PAIR_WHITELIST` | No | - | Comma-separated pairs |
| `NOTIONAL_CAPS` | No | - | PAIR:CAP,PAIR:CAP |
| `MAX_DAILY_VOLUME` | No | 1000000 | Max daily volume USD |

### Log Files

| File | Location | Purpose |
|------|----------|---------|
| Trading system | `logs/trading_system_*.log` | Main system logs |
| Redis events | Redis streams | Real-time events |
| Incidents | `INCIDENTS_LOG.md` | Incident tracking |
| Maintenance | `MAINTENANCE_LOG.md` | Maintenance history |

### Monitoring Endpoints

| Endpoint | Description |
|----------|-------------|
| Redis health | `redis-cli -u $REDIS_URL PING` |
| Go-live health | `python scripts/monitor_redis_streams.py --health` |
| Stream dashboard | `python scripts/monitor_redis_streams.py` |
| Real-time tail | `python scripts/monitor_redis_streams.py --tail` |

---

## Revision History

| Date | Version | Changes | Author |
|------|---------|---------|--------|
| 2025-10-18 | 1.0 | Initial runbook creation | System |

---

**For technical details, see:**
- `docs/GO_LIVE_CONTROLS.md` - Complete go-live controls documentation
- `EMERGENCY_KILLSWITCH_QUICKREF.md` - Emergency procedures quick reference
- `GO_LIVE_IMPLEMENTATION_SUMMARY.md` - Implementation summary

**Need help?** Refer to emergency contacts above or see troubleshooting section.
