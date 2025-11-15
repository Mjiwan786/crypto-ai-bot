# PnL Accounting + Prometheus Metrics (Task 8)

## Overview

Comprehensive PnL monitoring system with **daily targets** and **alert flags** exported to Prometheus:

- **Daily PnL Target**: Calculated from target CAGR path (Sharpe 1.0, PF 1.35)
- **Rolling Metrics**: 7d win rate, 30d profit factor, 30d trade count
- **Alert Flags**: Drawdown soft/hard, loss streak detection
- **Prometheus Export**: 11 gauges + 1 counter for monitoring/alerting

**Service**: `monitoring/pnl_aggregator.py` consumes `trades:closed` stream and exports metrics

## Architecture

```
trades:closed stream → PnL Aggregator → Prometheus /metrics
                   ↓
            pnl:equity stream
            pnl:stats:* keys
            Alert detection
```

### Flow

1. **Trade Execution** → Publish to `trades:closed` stream
2. **PnL Aggregator** → Consume trades, update equity
3. **Target Calculation** → Compute daily target from CAGR path
4. **Alert Detection** → Check drawdown and loss streaks
5. **Prometheus Export** → Expose metrics on `/metrics`
6. **Grafana/Alertmanager** → Scrape and alert

## Configuration

### Environment Variables

```bash
# Redis connection
REDIS_URL="redis://default:PASSWORD@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818"

# Starting equity
START_EQUITY=10000.0

# Prometheus metrics
PNL_METRICS_PORT=9100

# Statistics (requires pandas)
USE_PANDAS=true
STATS_WINDOW_SIZE=5000
```

### Start PnL Aggregator

```bash
conda activate crypto-bot

# With Prometheus metrics
export PNL_METRICS_PORT=9100
export USE_PANDAS=true
python monitoring/pnl_aggregator.py
```

## Prometheus Metrics

### Core PnL Metrics

**1. Current Equity (`pnl_equity_usd`)**
- Type: Gauge
- Description: Current account equity in USD
- Example: `10245.67`

**2. Daily PnL (`pnl_daily_usd`)**
- Type: Gauge
- Description: Daily profit/loss in USD (resets at UTC midnight)
- Example: `+125.50` or `-45.20`

**3. Daily Target (`pnl_daily_target_usd`)**
- Type: Gauge
- Description: Daily PnL target based on 12% CAGR path
- Calculation: `equity × 0.000309` (0.0309% daily)
- Example: $10,000 equity → $3.09/day target

### Rolling Metrics

**4. Rolling Equity (`pnl_rolling_equity_usd`)**
- Type: Gauge
- Description: 30-day rolling equity (currently same as current equity)
- Future: Implement EMA or sliding window average

**5. 7-Day Win Rate (`pnl_win_rate_7d`)**
- Type: Gauge
- Description: Win rate over last 7 days (0-1 scale)
- Example: `0.58` = 58% win rate

**6. 30-Day Profit Factor (`pnl_profit_factor_30d`)**
- Type: Gauge
- Description: Profit factor over last 30 days
- Calculation: `gross_profit / abs(gross_loss)`
- Example: `1.45` (good), `2.0` (excellent)

**7. 30-Day Trade Count (`pnl_trades_30d`)**
- Type: Gauge
- Description: Number of trades in last 30 days
- Example: `87`

**8. Total Trades Counter (`pnl_trades_total`)**
- Type: Counter
- Description: Total trades processed since start
- Example: `342`

### Alert Flags

**9. Soft Drawdown Alert (`alert_drawdown_soft`)**
- Type: Gauge (0=OK, 1=TRIGGERED)
- Trigger: Daily DD >= 4%
- Action: Soft stop (no new positions, reduce-only mode)
- Example: `1.0` when daily PnL drops -4% or more

**10. Hard Drawdown Alert (`alert_drawdown_hard`)**
- Type: Gauge (0=OK, 1=TRIGGERED)
- Trigger: Daily DD >= 6%
- Action: Hard halt (emergency stop, close positions)
- Example: `1.0` when daily PnL drops -6% or more

**11. Loss Streak Alert (`alert_loss_streak`)**
- Type: Gauge (0=OK, 1=TRIGGERED)
- Trigger: 3+ consecutive losing trades
- Action: Cooldown period, re-evaluate strategy
- Example: `1.0` after 3 straight losses

## Daily Target Calculation

### Target CAGR Path

Target derived from realistic performance goals:
- **Target Sharpe**: 1.0 (good risk-adjusted returns)
- **Target Profit Factor**: 1.35 (decent edge over costs)
- **Implied CAGR**: ~12% annually

**Daily Return Target:**
```python
CAGR = 12% annually
Daily return = 1.12^(1/365) - 1 = 0.000309 = 0.0309%

Daily target = equity × 0.000309
```

**Examples:**
```
$10,000 equity → $3.09/day target
$25,000 equity → $7.73/day target
$50,000 equity → $15.45/day target
```

### Target Interpretation

**On-Track:**
- Daily PnL >= target → You're ahead of CAGR path
- Green light to continue trading

**Below Target:**
- Daily PnL < target → Behind CAGR path
- Not necessarily bad (daily variance expected)
- Monitor over weeks, not days

**Significantly Below:**
- Daily PnL << target for multiple days
- Review strategy parameters
- Check market conditions

## Alert Detection

### 1. Soft Drawdown Alert (4%)

**Trigger Logic:**
```python
daily_dd_pct = (equity - day_start_equity) / day_start_equity × 100
soft_alert = (daily_dd_pct <= -4.0)
```

**Example:**
```
Day start equity: $10,000
Current equity: $9,600
Daily DD: -4.0% → SOFT ALERT TRIGGERED
```

**Actions:**
- Set `alert_drawdown_soft = 1.0`
- Log alert message
- Trigger risk gates (soft stop mode)
- No new positions until next day

### 2. Hard Drawdown Alert (6%)

**Trigger Logic:**
```python
daily_dd_pct = (equity - day_start_equity) / day_start_equity × 100
hard_alert = (daily_dd_pct <= -6.0)
```

**Example:**
```
Day start equity: $10,000
Current equity: $9,400
Daily DD: -6.0% → HARD ALERT TRIGGERED
```

**Actions:**
- Set `alert_drawdown_hard = 1.0`
- Log alert message
- Trigger risk gates (hard halt mode)
- Emergency stop, close all positions

### 3. Loss Streak Alert (3+ losses)

**Trigger Logic:**
```python
last_3_trades = trades[-3:]
all_losses = all(trade.pnl < 0 for trade in last_3_trades)
loss_streak_alert = all_losses
```

**Example:**
```
Trade N-2: PnL = -$50
Trade N-1: PnL = -$35
Trade N:   PnL = -$42
→ LOSS STREAK ALERT TRIGGERED
```

**Actions:**
- Set `alert_loss_streak = 1.0`
- Log alert message
- Trigger cooldown period
- Re-evaluate strategy/parameters

## Integration

### Prometheus Scraping

**prometheus.yml:**
```yaml
scrape_configs:
  - job_name: 'crypto_bot_pnl'
    static_configs:
      - targets: ['localhost:9100']
    scrape_interval: 5s
```

### Grafana Dashboards

**Panel Examples:**

**1. Equity Curve**
```promql
pnl_equity_usd
```

**2. Daily PnL vs Target**
```promql
# Daily PnL
pnl_daily_usd

# Daily target
pnl_daily_target_usd
```

**3. Win Rate Trend**
```promql
pnl_win_rate_7d * 100  # Convert to percentage
```

**4. Profit Factor**
```promql
pnl_profit_factor_30d
```

**5. Alert Status**
```promql
# Soft drawdown
alert_drawdown_soft

# Hard drawdown
alert_drawdown_hard

# Loss streak
alert_loss_streak
```

### Alertmanager Rules

**alertmanager.yml:**
```yaml
groups:
  - name: crypto_bot_alerts
    interval: 10s
    rules:
      # Hard drawdown alert
      - alert: HardDrawdownTriggered
        expr: alert_drawdown_hard == 1
        for: 0m
        labels:
          severity: critical
        annotations:
          summary: "Hard drawdown alert triggered (6% daily DD)"
          description: "Emergency stop activated. Review positions immediately."

      # Soft drawdown alert
      - alert: SoftDrawdownTriggered
        expr: alert_drawdown_soft == 1
        for: 0m
        labels:
          severity: warning
        annotations:
          summary: "Soft drawdown alert triggered (4% daily DD)"
          description: "Soft stop activated. No new positions until next day."

      # Loss streak alert
      - alert: LossStreakDetected
        expr: alert_loss_streak == 1
        for: 0m
        labels:
          severity: warning
        annotations:
          summary: "Loss streak detected (3+ consecutive losses)"
          description: "Cooldown period activated. Re-evaluate strategy."

      # Profit factor below threshold
      - alert: ProfitFactorLow
        expr: pnl_profit_factor_30d < 1.2
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "30-day profit factor below 1.2"
          description: "Edge degrading. Review strategy performance."
```

### Slack/PagerDuty Integration

```yaml
# alertmanager.yml
receivers:
  - name: 'slack'
    slack_configs:
      - api_url: 'https://hooks.slack.com/services/YOUR/WEBHOOK/URL'
        channel: '#trading-alerts'
        title: 'Crypto Bot Alert'
        text: '{{ .CommonAnnotations.summary }}'

  - name: 'pagerduty'
    pagerduty_configs:
      - service_key: 'YOUR_PAGERDUTY_KEY'
```

## Redis Keys

PnL aggregator publishes to Redis for other services:

**Stream Keys:**
- `pnl:equity` - Equity snapshots stream (time-series)

**Latest Value:**
- `pnl:equity:latest` - Current equity snapshot (JSON)

**Statistics:**
- `pnl:stats:win_rate` - Overall win rate
- `pnl:stats:win_rate_7d` - 7-day win rate
- `pnl:stats:profit_factor_30d` - 30-day profit factor
- `pnl:stats:trades_30d` - 30-day trade count
- `pnl:stats:max_drawdown` - Max drawdown from window
- `pnl:stats:sharpe` - Sharpe ratio from window

**State:**
- `pnl:agg:last_id` - Last processed stream ID (for resumption)

## Testing

### 1. Start PnL Aggregator with Metrics

```bash
conda activate crypto-bot
export REDIS_URL="redis://default:PASSWORD@HOST:PORT"
export START_EQUITY=10000.0
export PNL_METRICS_PORT=9100
export USE_PANDAS=true

python monitoring/pnl_aggregator.py
```

**Expected Output:**
```
============================================================
PNL AGGREGATOR SERVICE
============================================================
Redis URL: redis://default:***@redis-19818...
Start Equity: $10,000.00
Poll Interval: 500ms
State Key: pnl:agg:last_id
[INFO] Pandas Stats: ENABLED (window size: 5000)
============================================================
[OK] Prometheus metrics server started on port 9100
     Metrics: /metrics
[OK] Connected to Redis
[INFO] Starting fresh from: 0-0
[INFO] Restored equity: $10,000.00 (daily PnL: $0.00)

[START] Starting aggregator loop...
```

### 2. Check Metrics Endpoint

```bash
curl http://localhost:9100/metrics
```

**Expected Response:**
```
# HELP pnl_equity_usd Current account equity in USD
# TYPE pnl_equity_usd gauge
pnl_equity_usd 10245.67

# HELP pnl_daily_usd Daily profit/loss in USD
# TYPE pnl_daily_usd gauge
pnl_daily_usd 125.5

# HELP pnl_daily_target_usd Daily PnL target based on CAGR path
# TYPE pnl_daily_target_usd gauge
pnl_daily_target_usd 3.16

# HELP pnl_win_rate_7d 7-day rolling win rate (0-1)
# TYPE pnl_win_rate_7d gauge
pnl_win_rate_7d 0.58

# HELP pnl_profit_factor_30d 30-day profit factor
# TYPE pnl_profit_factor_30d gauge
pnl_profit_factor_30d 1.45

# HELP alert_drawdown_soft Soft drawdown alert (4% daily DD)
# TYPE alert_drawdown_soft gauge
alert_drawdown_soft 0.0

# HELP alert_drawdown_hard Hard drawdown alert (6% daily DD)
# TYPE alert_drawdown_hard gauge
alert_drawdown_hard 0.0

# HELP alert_loss_streak Loss streak alert (3+ consecutive losses)
# TYPE alert_loss_streak gauge
alert_loss_streak 0.0
```

### 3. Simulate Trades

Use `scripts/seed_closed_trades.py` to publish test trades:

```bash
python scripts/seed_closed_trades.py --count 10 --pnl_range -50,100
```

Watch PnL aggregator process trades and update metrics.

### 4. Trigger Alerts

**Soft Drawdown Test:**
```bash
# Publish losing trades totaling -4% of equity
python scripts/seed_closed_trades.py --count 5 --pnl -80
# Check: alert_drawdown_soft should become 1.0
```

**Loss Streak Test:**
```bash
# Publish 3 consecutive losses
python scripts/seed_closed_trades.py --count 3 --pnl -50
# Check: alert_loss_streak should become 1.0
```

## Benefits

### 1. Real-Time Monitoring

**Before:**
- Check logs manually
- No visibility into daily targets
- Alerts buried in terminal output

**After:**
- Grafana dashboard with live equity curve
- Daily target vs actual comparison
- Alert badges on metrics

### 2. Proactive Alerting

**Before:**
- Discover drawdowns after the fact
- No loss streak detection
- Manual intervention required

**After:**
- Instant Slack/PagerDuty alerts
- Automatic risk gates triggered
- Cooldown periods enforced

### 3. Performance Tracking

**Before:**
- Weekly manual review of trades CSV
- No rolling metrics
- Difficult to spot degradation

**After:**
- 7d win rate trend visible
- 30d profit factor tracked
- Early warning of edge degradation

### 4. Target Accountability

**Before:**
- No clear daily goal
- Ambiguous "profitable" definition
- Hard to assess if on-track

**After:**
- Concrete daily target ($3.09 for $10k)
- Visual comparison on dashboard
- Long-term CAGR path visible

## Files

- **PnL Aggregator**: `monitoring/pnl_aggregator.py` - Main service
- **Procfile**: `procfiles/pnl_aggregator.proc` - Process management
- **Tests**: `tests/monitoring/test_pnl_aggregator_resume.py` - Unit tests
- **Docs**: `docs/PNL_MONITORING.md` - This file

## References

- **Risk Gates**: `docs/RISK_GATES.md` - Drawdown protection integration
- **PnL Pipeline**: `docs/PNL_PIPELINE.md` - Trade flow architecture
- **Operations**: `docs/OPERATIONS.md` - Deployment guide

---

**Status**: ✅ Enhanced with targets and alerts

**Last Updated**: 2025-10-17

**Next Steps**: Deploy to production, configure Grafana dashboards, set up Alertmanager
