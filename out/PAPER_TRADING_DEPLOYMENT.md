# Paper Trading Deployment - bar_reaction_5m Strategy

**Deployment Date:** 2025-10-25
**Status:** READY FOR DEPLOYMENT
**Purpose:** Accumulate real performance data to validate infrastructure and optimize for profitability

---

## Executive Summary

The infrastructure has been fully fixed and tested. The system is stable with:
- ✅ Position sizing death spiral eliminated
- ✅ Drawdown circuit breaker implemented (-20% threshold)
- ✅ Minimum position size check added ($50 threshold)
- ✅ Configuration optimized for balanced risk/reward

However, historical backtest data is insufficient (only 20 hours instead of 90 days requested), limiting profitability optimization. **Paper trading** is the recommended path to:
1. Validate infrastructure with real market conditions
2. Accumulate statistically significant performance data (30+ trades)
3. Identify optimal parameters for profitability
4. Test all safety mechanisms in live market

---

## Deployment Guide

### Prerequisites

All preflight checks have passed:
```bash
python out/paper_preflight_check.py
```

✅ Conda environment: crypto-bot
✅ Redis connection: Working
✅ Strategy config: bar_reaction_5m.yaml loaded
✅ Mode: PAPER
✅ Trading disabled: ENABLE_TRADING=false
✅ All dependencies installed

### Quick Start

**Terminal 1: Start Paper Trading**
```bash
conda activate crypto-bot
python out/run_bar_reaction_paper.py
```

The script will:
- Connect to Kraken exchange for market data (read-only)
- Fetch live 5m BTC/USD OHLCV data
- Generate signals using bar_reaction_5m strategy
- Execute simulated trades with paper capital
- Track equity, P&L, and performance metrics
- Publish signals and trades to Redis streams

**Terminal 2: Monitor Redis (Optional)**
```bash
# Watch signals being published
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem XREAD STREAMS signals:paper 0

# Watch trades being closed
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem XREAD STREAMS trades:paper 0
```

### What to Expect

**Initial Phase (First 8 hours):**
- Market data accumulation
- Waiting for strategy signals
- May see 0-2 trades depending on market conditions

**Active Phase (Days 1-7):**
- Regular signal generation
- Position entries and exits
- Performance metrics accumulating

**Validation Phase (Days 7-14):**
- Statistical significance achieved (30+ trades target)
- Performance evaluation possible
- Parameter optimization data available

---

## Configuration

### Current Strategy Parameters

File: `config/bar_reaction_5m.yaml`

```yaml
strategy:
  name: "bar_reaction_5m"
  timeframe: "5m"
  mode: "trend"

  # Entry triggers
  trigger_mode: "open_to_close"
  trigger_bps_up: 13.0      # Balanced (not too aggressive)
  trigger_bps_down: 13.0

  # Volatility gates
  min_atr_pct: 0.10         # Filters low volatility
  max_atr_pct: 2.75         # Filters extreme volatility
  atr_window: 14

  # Risk management
  sl_atr: 0.8               # Balanced stop loss
  tp1_atr: 1.25             # First take profit
  tp2_atr: 2.0              # Second take profit

  # Position sizing
  risk_per_trade_pct: 0.8   # Conservative (0.8% per trade)

  # Execution
  maker_only: true
  spread_bps_cap: 10.0
```

### Paper Trading Environment

File: `.env.paper`

```bash
# Mode
MODE=paper
BOT_MODE=PAPER

# Capital
INITIAL_EQUITY_USD=10000.0

# Strategy
STRATEGY=bar_reaction_5m
TRADING_PAIRS=BTC/USD
TIMEFRAME=5m

# Safety
ENABLE_TRADING=false
MAX_DRAWDOWN_PCT=20.0
MAX_DAILY_LOSS_PCT=3.0
```

---

## Monitoring

### Live Status (Every 10 Iterations)

The script prints status every 10 iterations (~10 minutes):

```
================================================================================
PAPER TRADING STATUS
================================================================================
Initial Capital: $10000.00
Current Equity: $10025.50
Total Return: +0.26%
Signals Generated: 5
Signals Taken: 3
Signals Skipped: 2
Trades Completed: 2
Win Rate: 50.0%
Avg P&L per trade: +$12.75
Current Position: LONG @ $67500.00
================================================================================
```

### Log Files

Detailed logs are saved to:
```
logs/paper_trial_YYYYMMDD_HHMMSS.log
```

Contains:
- All signals generated and reasons
- Position entries with price, size, move_bps
- Position exits with P&L, duration, reason
- Errors and warnings
- Status updates

### Redis Streams

**signals:paper** - All generated signals
```json
{
  "timestamp": "2025-10-25T12:00:00",
  "symbol": "BTC/USD",
  "signal": "LONG",
  "price": 67500.00,
  "size_usd": 80.00,
  "move_bps": 15.3,
  "atr_pct": 0.125
}
```

**trades:paper** - All closed trades
```json
{
  "timestamp": "2025-10-25T12:30:00",
  "symbol": "BTC/USD",
  "type": "LONG",
  "entry_price": 67500.00,
  "exit_price": 67675.00,
  "pnl_usd": 0.21,
  "pnl_pct": 0.26,
  "reason": "take_profit"
}
```

---

## Validation Criteria

### Minimum Duration
- **7 days minimum** before first evaluation
- **14 days recommended** for statistical significance

### Minimum Trade Count
- **30 trades minimum** for meaningful analysis
- More trades = better statistical confidence

### Performance Targets (from PRD)

| Metric | Target | Current (Backtest) |
|--------|--------|-------------------|
| Profit Factor | ≥ 1.30 | 0.00 (1 trade) |
| Sharpe Ratio | ≥ 1.0 | 1.16 (inconclusive) |
| Max Drawdown | ≤ 20% | -99.21% (unrealized) |
| Win Rate | ≥ 40% | 0% (1 losing trade) |

**Note:** Backtest results are inconclusive due to insufficient data (1 trade vs 30+ needed)

### Daily Checks

Run these checks daily to monitor progress:

**1. Equity Check**
```bash
# Look at latest status in logs
tail -20 logs/paper_trial_*.log | grep "Current Equity"
```

**2. Trade Count**
```bash
# Count trades in Redis
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem XLEN trades:paper
```

**3. Error Check**
```bash
# Check for errors in logs
grep ERROR logs/paper_trial_*.log | tail -10
```

---

## Exit Strategies

### Simple Exit Logic (Current Implementation)

The simplified paper trader uses basic exit rules:
- **Take Profit:** Close when P&L ≥ +1.0%
- **Stop Loss:** Close when P&L ≤ -1.0%
- **Time Exit:** Close after 30 minutes if no TP/SL hit

### Future Enhancements

Once basic validation is complete, implement ATR-based exits:
- **TP1:** Close 50% at 1.25x ATR profit
- **TP2:** Close remaining 50% at 2.0x ATR profit
- **SL:** Close 100% at 0.8x ATR loss

---

## Troubleshooting

### No Signals Generated

**Causes:**
1. Market not meeting trigger thresholds (13 bps move required)
2. Volatility outside ATR gates (0.10% - 2.75%)
3. Low market activity period

**Solutions:**
- Wait 8+ hours for data accumulation
- Check market conditions (trending vs choppy)
- Verify logs for "Signal skipped" reasons

### Connection Errors

**Redis connection fails:**
```bash
# Test connection
python -c "import redis; import os; from dotenv import load_dotenv; load_dotenv('.env.paper'); url = os.getenv('REDIS_URL'); ca = os.getenv('REDIS_CA_CERT'); client = redis.from_url(url, ssl_ca_certs=ca, ssl_cert_reqs='required', decode_responses=True); client.ping(); print('OK')"
```

**Exchange connection fails:**
```bash
# Test Kraken API
python -c "import ccxt; exchange = ccxt.kraken(); ohlcv = exchange.fetch_ohlcv('BTC/USD', '5m', limit=10); print(f'Fetched {len(ohlcv)} candles')"
```

### Position Stuck

If position doesn't close:
- Check exit conditions in logs
- Verify price data is updating
- Exit conditions: ±1% P&L or 30 minutes duration

---

## Post-Trial Analysis

### After 7 Days

**If 30+ Trades Achieved:**
1. Calculate key metrics:
   - Profit Factor = Gross Profit / Gross Loss
   - Win Rate = Winning Trades / Total Trades
   - Avg Win vs Avg Loss
   - Sharpe Ratio

2. Analyze trade distribution:
   - When are winning trades happening?
   - What market conditions correlate with losses?
   - Are trigger thresholds optimal?

3. Decision:
   - **If profitable:** Continue to day 14 for confirmation
   - **If breakeven/loss:** Adjust parameters and restart

**If < 30 Trades:**
- Continue paper trading
- May need to lower trigger thresholds for more activity
- Consider testing different time periods

### After 14 Days

**Success Criteria:**
- ✅ Profit Factor ≥ 1.30
- ✅ Sharpe Ratio ≥ 1.0
- ✅ Max Drawdown ≤ 20%
- ✅ Win Rate ≥ 40%
- ✅ 30+ completed trades

**If ALL criteria met:**
- ✅ Infrastructure validated in live market
- ✅ Strategy shows edge
- ✅ Ready for parameter optimization
- ✅ Ready to consider live trading (with conservative capital)

**If criteria NOT met:**
- Parameter optimization needed
- Test different trigger thresholds
- Test different ATR gates
- Consider regime filters
- May need strategy redesign

---

## Parameter Optimization

Once paper trading provides sufficient data (30+ trades), run parameter sweeps:

```bash
# Trigger threshold sweep
python out/trigger_sweep.py

# ATR filter sweep
python out/atr_filter_sweep.py

# Grid search (multiple parameters)
python scripts/optimize_grid.py --pairs "BTC/USD" --lookback 180d
```

Apply best parameters to `config/bar_reaction_5m.yaml` and restart paper trading.

---

## Next Steps

### Immediate (Now)

1. **Start paper trading:**
   ```bash
   conda activate crypto-bot
   python out/run_bar_reaction_paper.py
   ```

2. **Let it run for 7-14 days**

3. **Monitor daily:**
   - Check logs for errors
   - Count trades in Redis
   - Verify equity progression

### Short Term (Days 1-7)

1. **Accumulate data**
   - Target: 30+ completed trades
   - Track all signals and reasons

2. **Daily monitoring**
   - Check for connection issues
   - Verify signals are generating
   - Monitor equity changes

3. **Initial analysis (Day 7)**
   - If 30+ trades: Evaluate performance
   - If < 30 trades: Adjust parameters or continue

### Medium Term (Days 7-14)

1. **Performance validation**
   - Calculate all key metrics
   - Compare against targets
   - Identify patterns

2. **Parameter optimization**
   - If profitable: Fine-tune
   - If breakeven: Major adjustments
   - If losing: Redesign or abandon

3. **Go/No-Go decision**
   - Go: Proceed to live with small capital
   - No-Go: More optimization needed

### Long Term (Weeks 3-4+)

1. **Live trading preparation**
   - Review all safety gates
   - Set conservative capital
   - Prepare monitoring dashboard

2. **Gradual scale-up**
   - Start with $100-500 real capital
   - Monitor for 1 week
   - Scale up only if profitable

---

## Safety Reminders

### Circuit Breakers Active

The strategy has multiple safety mechanisms:

1. **Minimum Position Size:** $50 (prevents fee death spiral)
2. **Drawdown Limit:** -20% (stops trading at max loss)
3. **Daily Loss Limit:** -3% (from .env.paper)
4. **Max Daily Trades:** 50 (prevents runaway trading)
5. **Risk Per Trade:** 0.8% (conservative sizing)

### Emergency Stop

To stop paper trading:
```
Ctrl+C in terminal running the script
```

The script will:
- Gracefully shut down
- Print final status
- Save all data
- Close cleanly

### Data Preservation

All data is preserved in:
- **Logs:** `logs/paper_trial_*.log`
- **Redis:** `signals:paper` and `trades:paper` streams
- **Memory:** Script maintains trade history

---

## Files Created/Modified

### New Files
```
.env.paper                         # Paper trading environment
out/paper_preflight_check.py       # Preflight validation script
out/run_bar_reaction_paper.py      # Simple paper trader
out/PAPER_TRADING_DEPLOYMENT.md    # This file
```

### Configuration Files
```
config/bar_reaction_5m.yaml        # Strategy configuration (optimized)
```

### Supporting Files
```
out/profitability_analysis_complete.txt  # Analysis documenting why paper trading
out/fixes_and_results.txt                # Infrastructure fixes summary
```

---

## Success Metrics

### Week 1 Goals
- [ ] System runs stable for 7 days
- [ ] 0 crashes or critical errors
- [ ] 30+ trades completed
- [ ] All trades tracked in Redis

### Week 2 Goals
- [ ] Performance evaluation complete
- [ ] Key metrics calculated
- [ ] Parameter optimization analysis done
- [ ] Go/No-Go decision made

### Final Goals
- [ ] Infrastructure validated in live market
- [ ] Strategy profitability assessed with statistical significance
- [ ] Optimal parameters identified
- [ ] Path to live trading or further optimization clear

---

## Contact & Support

**Log Location:** `logs/paper_trial_*.log`
**Configuration:** `config/bar_reaction_5m.yaml`
**Environment:** `.env.paper`
**Documentation:** Full paper trading guide in `PAPER_TRADING_QUICKSTART.md`

---

**Deployment Status:** ✅ READY
**Recommendation:** START PAPER TRADING NOW
**Expected Duration:** 14 days minimum
**Next Review:** Day 7 (2025-11-01)

---

*Generated: 2025-10-25*
*Strategy: bar_reaction_5m*
*Infrastructure Status: STABLE & PROTECTED*
