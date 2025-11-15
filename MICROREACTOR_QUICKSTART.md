# Microreactor (Intra-bar Probes) — Quick Start

**Fast track guide for enabling intra-bar probe trading**

---

## What Is Microreactor?

Intra-bar probe strategy that **increases trade frequency 2-3x** by trading within 5-minute bars:

- **Regular bar_reaction_5m**: 5-15 trades/day (bar-close only)
- **With microreactor**: 15-30 trades/day (bar-close + intra-bar probes)

**Key Features**:
- Monitors cumulative move from 5m bar open using 1m ticks
- Fires tiny probes (30% normal size) when move exceeds ±10 bps
- Max 2 probes per 5m bar
- Min 45s spacing between probes
- Daily caps: 50 probes/day/pair, 5% total risk/day

---

## Quick Test (Backtest)

```python
# Test microreactor backtest
from backtesting.microreactor_engine import MicroreactorBacktestEngine, MicroreactorBacktestConfig
from scripts.run_backtest import fetch_ohlcv

# Configure
config = MicroreactorBacktestConfig(
    symbol="BTC/USD",
    start_date="2024-04-01",
    end_date="2024-10-01",
    initial_capital=10000,
    # Regular params
    trigger_bps_up=12.0,
    min_atr_pct=0.25,
    sl_atr=0.6,
    tp2_atr=1.8,
    # Microreactor params
    enable_microreactor=True,
    probe_trigger_bps=10.0,
    probe_size_factor=0.3,
    min_spacing_seconds=45,
    max_probes_per_bar=2,
)

# Load data
df_1m = fetch_ohlcv("BTC/USD", "1m", "2024-04-01", "2024-10-01")

# Run
engine = MicroreactorBacktestEngine(config)
results = engine.run(df_1m)

# Results
print(f"Total trades: {results.total_trades}")
print(f"  Regular: {results.total_trades - engine.total_probes}")
print(f"  Probes: {engine.total_probes}")
print(f"Return: {results.total_return_pct:+.2f}%")
print(f"Sharpe: {results.sharpe_ratio:.2f}")
```

---

## Configuration

### Enable in YAML

Edit `config/bar_reaction_5m.yaml`:

```yaml
# Add microreactor section
microreactor:
  enabled: true
  probe_trigger_bps: 10.0       # Cumulative move threshold (8-15 bps)
  probe_size_factor: 0.3        # Probe size as % of normal (0.25-0.4)
  min_spacing_seconds: 45       # Min spacing between probes (45-60s)
  max_probes_per_bar: 2         # Max probes per 5m bar
  max_probes_per_day_per_pair: 50   # Daily per-pair cap
  max_probe_risk_pct_per_day: 5.0   # Daily total risk cap (%)
```

### Parameter Presets

**Conservative (Low Frequency)**:
```yaml
microreactor:
  probe_trigger_bps: 15.0
  probe_size_factor: 0.25
  min_spacing_seconds: 60
  max_probes_per_bar: 1
  max_probes_per_day_per_pair: 30
```
Expected: ~20 probes/day, 1.5x frequency

**Balanced (Recommended)**:
```yaml
microreactor:
  probe_trigger_bps: 10.0
  probe_size_factor: 0.3
  min_spacing_seconds: 45
  max_probes_per_bar: 2
  max_probes_per_day_per_pair: 50
```
Expected: ~40 probes/day, 2.8x frequency

**Aggressive (High Frequency)**:
```yaml
microreactor:
  probe_trigger_bps: 8.0
  probe_size_factor: 0.4
  min_spacing_seconds: 45
  max_probes_per_bar: 2
  max_probes_per_day_per_pair: 60
```
Expected: ~50 probes/day, 3.5x frequency

---

## How It Works

### Example Timeline

```
5m bar: 10:00 - 10:05 (bar_5m_open = $50,000)

10:00:00 (1m) → close $50,000 → move = 0 bps → no probe
10:01:00 (1m) → close $50,040 → move = +8 bps → no probe (< 10 bps threshold)
10:02:00 (1m) → close $50,060 → move = +12 bps → PROBE LONG @ $50,060 (probe 1/2)
10:03:00 (1m) → close $50,075 → move = +15 bps → no probe (spacing 60s not met)
10:04:00 (1m) → close $50,090 → move = +18 bps → PROBE LONG @ $50,090 (probe 2/2)
10:05:00       → 5m bar close → regular bar_reaction signal check

10:05 - 10:10 (new 5m bar, reset probe count to 0)
```

### Position Sizing

**Regular Trade**:
- Account: $10,000
- Risk: 0.6% = $60
- SL distance: 0.5% (0.6x ATR)
- Position: $60 / 0.005 = $12,000 → 0.24 BTC @ $50k

**Probe Trade**:
- Account: $10,000
- Risk: 0.6% × 0.3 = 0.18% = $18
- SL distance: 0.5% (0.6x ATR, same)
- Position: $18 / 0.005 = $3,600 → 0.072 BTC @ $50k

**Probe is 30% the size of regular trade**

---

## Guards (L3)

### Per-Bar Limits

- **Max 2 probes per 5m bar**
- **Min 45s spacing** between probes

If exceeded → probe blocked until next 5m bar

### Daily Limits

- **Max 50 probes/day per pair**
- **Max 5% total probe risk/day** (across all pairs)

If exceeded → all probes blocked until next day (00:00 UTC)

### Example Daily Flow

```
00:00 UTC → Daily counters reset
01:00     → 10 probes (BTC/USD) → 10/50, risk 1.8%
02:00     → 15 probes (BTC/USD) → 25/50, risk 4.5%
03:00     → 10 probes (BTC/USD) → 35/50, risk 6.3% → BLOCKED (> 5% risk)
04:00     → probes still blocked
...
00:00 UTC → Daily counters reset, probes resume
```

---

## Expected Performance

### Trade Frequency

| Mode | Trades/Day | Sample (180d) | Hold Time |
|------|------------|---------------|-----------|
| bar_reaction only | 5-15 | 87 | 10-30 min |
| + microreactor | 15-30 | 247 (87 + 160) | Mixed 5-30 min |

**2.8x more trades with controlled risk**

### Profit Targets

Probes should meet:
- **Profit Factor** ≥ 1.2 (lower than regular due to smaller R/R)
- **Win Rate** ≥ 60% (same as regular)
- **Sharpe Ratio** ≥ 0.8 (slightly lower than regular)

---

## Deployment Workflow

### Step 1: Backtest

```bash
# Run microreactor backtest (180 days)
python -c "
from backtesting.microreactor_engine import MicroreactorBacktestEngine, MicroreactorBacktestConfig
from scripts.run_backtest import fetch_ohlcv

config = MicroreactorBacktestConfig(
    symbol='BTC/USD',
    start_date='2024-04-01',
    end_date='2024-10-01',
    initial_capital=10000,
    enable_microreactor=True,
)

df = fetch_ohlcv('BTC/USD', '1m', '2024-04-01', '2024-10-01')
results = MicroreactorBacktestEngine(config).run(df)

print(f'Trades: {results.total_trades}')
print(f'Return: {results.total_return_pct:+.2f}%')
print(f'Sharpe: {results.sharpe_ratio:.2f}')
"
```

### Step 2: Compare with Base

```bash
# Compare: bar_reaction only vs bar_reaction + microreactor

# Base (no probes)
config_base = MicroreactorBacktestConfig(..., enable_microreactor=False)
results_base = engine.run(df)

# With probes
config_probes = MicroreactorBacktestConfig(..., enable_microreactor=True)
results_probes = engine.run(df)

# Compare
print(f"Base:   {results_base.total_trades} trades, {results_base.total_return_pct:+.2f}%")
print(f"Probes: {results_probes.total_trades} trades, {results_probes.total_return_pct:+.2f}%")
```

### Step 3: Enable in Config

If backtest shows improvement:

```yaml
# config/bar_reaction_5m.yaml
microreactor:
  enabled: true
  probe_trigger_bps: 10.0
  probe_size_factor: 0.3
```

### Step 4: Paper Trade

```bash
export MODE=PAPER
export ENABLE_MICROREACTOR=true
python scripts/start_trading_system.py

# Monitor for 7 days
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem \
  XREAD STREAMS microreactor:probes 0
```

### Step 5: Go Live

If paper mode successful:

```bash
export MODE=LIVE
export LIVE_TRADING_CONFIRMATION="I-accept-the-risk"
export ENABLE_MICROREACTOR=true
python scripts/start_trading_system.py
```

---

## Monitoring

### Check Probe Frequency

```python
# Count probes today
from agents.strategies.microreactor_5m import Microreactor5mStrategy

strategy = Microreactor5mStrategy()
guards = strategy.daily_guards

print(f"Probes today:")
for pair, count in guards.probes_today.items():
    print(f"  {pair}: {count}/50")
print(f"Total risk today: {guards.probe_risk_today_pct:.2f}%/5.0%")
```

### Redis Metrics

```bash
# Watch probe events
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem \
  XREAD BLOCK 0 STREAMS microreactor:probes $

# Check daily stats
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem \
  GET microreactor:daily:probes:BTC_USD
```

---

## Troubleshooting

### No Probes Firing

**Check**:
1. Is `enable_microreactor=True`?
2. Is `probe_trigger_bps` too high? (try 8-10 bps)
3. Are ATR% gates blocking? (check logs)
4. Is volatility too low? (try different period)

**Fix**:
```yaml
microreactor:
  probe_trigger_bps: 8.0  # Lower threshold
  min_atr_pct: 0.20       # Widen gates
```

### Too Many Probes

**Fix**:
```yaml
microreactor:
  probe_trigger_bps: 12.0      # Raise threshold
  min_spacing_seconds: 60      # More spacing
  max_probes_per_day_per_pair: 40  # Lower limit
```

### Probes Not Profitable

**Check**:
- Probe win rate (should be ≥60%)
- Probe avg hold time (should be 5-15 min)
- Probe fill rate (should be ~60-70%)

**Tune**:
```yaml
microreactor:
  probe_size_factor: 0.25  # Smaller probes
  tp1_atr: 0.8             # Closer TP1
```

---

## Files

| File | Purpose |
|------|---------|
| `agents/strategies/microreactor_5m.py` | L1 strategy module |
| `backtesting/microreactor_engine.py` | L2 backtest engine |
| `config/bar_reaction_5m.yaml` | Configuration |
| `L_MICROREACTOR_COMPLETE.md` | Full documentation |

---

## Key Differences vs Regular Trades

| Aspect | Regular (bar_reaction) | Probe (microreactor) |
|--------|------------------------|----------------------|
| Trigger | 5m bar close | Intra-bar (1m ticks) |
| Frequency | 5-15/day | 15-30/day additional |
| Size | 100% | 30% (configurable) |
| Risk/trade | 0.6% | 0.18% (0.6% × 0.3) |
| Hold time | 10-30 min | 5-15 min |
| Limits | Position limit only | + 2/bar, 50/day, 5% daily risk |

---

**Full Documentation**: `L_MICROREACTOR_COMPLETE.md`

**Support**: Check OPERATIONS_RUNBOOK.md for production procedures

---

**Last Updated**: 2025-10-20

