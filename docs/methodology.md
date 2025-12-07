# Signal Methodology

**Version:** 1.0
**Last Updated:** 2025-12-05
**Status:** Authoritative Reference (PRD-001 Compliant)

---

## Quick Reference

This document provides the algorithmic foundation for signal generation as required by PRD-001 Section 11. For detailed methodology, risk disclosures, and hypothetical performance limitations, see the comprehensive [Signal Methodology & Risk Disclosures](SIGNAL_METHODOLOGY.md).

---

## Trading Approach Overview

The crypto-ai-bot generates signals using a multi-strategy ensemble approach with adaptive regime detection. The system combines technical analysis, machine learning, and risk management to produce high-confidence trading signals.

### Strategy Allocation

The system allocates capital across four primary strategies based on historical performance and current market conditions:

| Strategy | Allocation | Description | Timeframes |
|----------|------------|-------------|------------|
| **Scalper** | 40% | Short-term momentum trades on 15s-5m timeframes | 15s, 30s, 1m, 5m |
| **Trend Following** | 30% | Directional trades aligned with detected regime | 5m, 15m, 30m, 1h |
| **Mean Reversion** | 20% | Counter-trend trades at extreme RSI levels | 5m, 15m, 30m |
| **Breakout** | 10% | Volatility expansion trades on range breaks | 15m, 30m, 1h, 4h |

**Dynamic Allocation:**
- Strategy weights adjust based on recent performance (last 100 trades)
- Underperforming strategies (loss streak ≥ 3) have allocation reduced by 50%
- Strategies with loss streak ≥ 5 are paused pending manual review

### Regime Detection

Market conditions are classified using an ML ensemble (Random Forest + LSTM) that analyzes price action, volume, and volatility patterns:

| Regime | Detection Criteria | Strategy Allocation |
|--------|-------------------|-------------------|
| **TRENDING_UP** | ADX > 25, price > SMA(50) | Trend (high), Breakout (medium), Scalper (low) |
| **TRENDING_DOWN** | ADX > 25, price < SMA(50) | Mean Reversion (high), Trend (medium) |
| **RANGING** | ADX < 20, narrow Bollinger Bands | Mean Reversion (high), Scalper (high), Breakout (low) |
| **VOLATILE** | ATR > 80th percentile historical | Scalper (low), all others disabled |

**Regime Detection Frequency:**
- Update interval: Every 5 minutes
- Lookback window: 200 candles (5m timeframe = 16.7 hours)
- Caching: Last 24 hours of regime labels stored in Redis
- Model retraining: Weekly (Sunday 00:00 UTC)

**Ensemble Weighting:**
- Random Forest: 60% weight
- LSTM: 40% weight
- Confidence score: Based on model agreement (both agree = 0.9, disagree = 0.5)

---

## Technical Indicators

| Indicator | Formula | Purpose | Range |
|-----------|---------|---------|-------|
| RSI(14) | Relative Strength Index | Overbought/oversold | 0-100 |
| MACD | 12/26 EMA crossover | Momentum direction | - |
| ATR(14) | Average True Range | Volatility measure | > 0 |
| ADX(14) | Average Directional Index | Trend strength | 0-100 |
| Bollinger Bands | 20-period SMA +/- 2 std | Mean reversion | - |
| Volume Ratio | Current / 20-period average | Volume surge | > 0 |

---

## Risk Management Rules

### Pre-Signal Filters (PRD-001 Section 7)

All signals must pass the following risk filters before publication:

| Filter | Threshold | Action | Implementation |
|--------|-----------|--------|----------------|
| **Spread** | > 0.5% | Reject signal | `(ask - bid) / mid * 100` |
| **Volatility** | > 3x ATR average | Reduce position 50% | ATR(14) on 5m candles |
| **Volatility (Extreme)** | > 5x ATR average | Halt new signals | Circuit breaker |
| **Daily Drawdown** | < -5% | Circuit breaker - halt signals | Tracked from midnight UTC |
| **Weekly Drawdown** | < -10% | Reduce position sizes 50% | Rolling 7-day window |
| **Monthly Drawdown** | < -20% | Pause system, alert engineer | Rolling 30-day window |
| **Loss Streak** | 3 consecutive | Reduce allocation 50% | Per-strategy tracking |
| **Loss Streak (Critical)** | 5 consecutive | Pause strategy, manual review | Per-strategy tracking |
| **Position Concentration** | > 40% of portfolio | Block additional exposure | Sum of concurrent positions |

### Position Sizing

Position sizing follows a risk-adjusted formula based on volatility and confidence:

```
base_size = $100
volatility_adjustment = ATR_avg / ATR_current
confidence_scaling = signal_confidence (0.6 - 1.0)
position_size = min(base_size * volatility_adjustment * confidence_scaling, $2000)
```

**Constraints:**
- Minimum position: $10 USD
- Maximum position: $2,000 USD per signal
- Maximum total exposure: $10,000 USD across all positions
- Per-trade risk: 1-2% of equity (based on stop-loss distance)

**Risk-Adjusted Sizing:**
- High volatility (ATR > 3x average): Position size reduced by 50%
- Low confidence (< 0.7): Position size scaled down proportionally
- Drawdown periods: Additional 0.5x multiplier applied during soft stops

### Drawdown Circuit Breakers

Multi-tier drawdown protection system:

1. **Daily Drawdown (-5%)**: Hard halt on new signals until next day (midnight UTC reset)
2. **Weekly Drawdown (-10%)**: Soft stop - reduce all position sizes by 50%
3. **Monthly Drawdown (-20%)**: Full system pause - requires manual intervention

All drawdown calculations use UTC timestamps for consistency.

---

## Signal Schema (PRD-001 Section 5)

Each signal contains:

```json
{
  "signal_id": "UUID v4",
  "timestamp": "ISO8601 UTC",
  "pair": "BTC/USD",
  "side": "LONG | SHORT",
  "strategy": "SCALPER | TREND | MEAN_REVERSION | BREAKOUT",
  "regime": "TRENDING_UP | TRENDING_DOWN | RANGING | VOLATILE",
  "entry_price": 43250.50,
  "take_profit": 43500.00,
  "stop_loss": 43100.00,
  "position_size_usd": 150.00,
  "confidence": 0.72,
  "risk_reward_ratio": 1.67,
  "indicators": {
    "rsi_14": 58.3,
    "macd_signal": "BULLISH",
    "atr_14": 425.80,
    "volume_ratio": 1.23
  }
}
```

---

## Supported Trading Pairs (PRD-001 Section 4.A)

| Symbol | Name | Status | Signals/30d | Notes |
|--------|------|--------|-------------|-------|
| BTC/USD | Bitcoin | Active | ~10,000+ | Tier 1, highest liquidity |
| ETH/USD | Ethereum | Active | ~10,000+ | Tier 1, high liquidity |
| SOL/USD | Solana | Active | ~10,000+ | Tier 2, medium liquidity |
| MATIC/USD | Polygon | Pending | 0 | Not on Kraken WS - requires Binance fallback |
| LINK/USD | Chainlink | Pending | 0 | Configuration pending - to be enabled |

### Known Limitations

- **MATIC/USD**: Kraken WebSocket API returns "Currency pair not supported" for MATIC/USD. A fallback data source (e.g., Binance via ccxt) is required to enable signal generation for this pair.
- **LINK/USD**: Data feed subscription pending configuration update. Pair is supported by Kraken but not yet subscribed in the production engine.

---

## Performance Calculation Assumptions

Per PRD-001 backtesting requirements:

| Parameter | Value |
|-----------|-------|
| Slippage | 0.1% (10 bps) |
| Maker Fee | 0.075% |
| Taker Fee | 0.15% |
| Initial Capital | $10,000 |
| Risk-Free Rate | 5% annual |

### Acceptance Criteria

- Sharpe Ratio >= 1.5
- Maximum Drawdown <= -15%
- Win Rate >= 45%
- Profit Factor >= 1.3
- Minimum 200 trades in test period

---

## Risk Summary

### Key Risk Factors

1. **Market Risk**: Cryptocurrency markets are highly volatile and can experience rapid price movements
2. **Execution Risk**: Slippage (0.1% assumed) and fees (0.075% maker, 0.15% taker) impact returns
3. **Model Risk**: ML models may underperform during regime shifts or market anomalies
4. **Liquidity Risk**: Wide spreads (> 0.5%) trigger signal rejection to avoid illiquid conditions
5. **Drawdown Risk**: Multi-tier circuit breakers limit maximum drawdown exposure

### Risk Controls

- **Pre-trade Filters**: Spread, volatility, and drawdown checks before signal generation
- **Position Limits**: Maximum $2,000 per position, $10,000 total exposure
- **Circuit Breakers**: Daily (-5%), weekly (-10%), monthly (-20%) drawdown limits
- **Loss Streak Protection**: Automatic allocation reduction after 3 losses, pause after 5
- **Volatility Adjustment**: Position sizes reduced during high volatility periods

### Performance Metrics

All performance metrics are calculated using PRD-001 compliant assumptions:

- **Time Windows**: 30-day, 90-day, and 365-day rolling periods (rolling from current time)
- **Metrics Calculated**: ROI, CAGR, Win Rate, Profit Factor, Sharpe Ratio, Max Drawdown
- **Data Sources**: Redis streams (`signals:paper:<PAIR>`, `pnl:paper:equity_curve`)
- **Update Frequency**: Hourly aggregation and publishing to `engine:summary_metrics`
- **Calculation Method**: Time-windowed equity curve filtering ensures period-specific accuracy

**Track Record Requirements (PRD-001 Section 11):**
- All metrics must be traceable to source data (signals, trades, equity curve)
- Performance attribution by strategy (Scalper, Trend, Mean Reversion, Breakout)
- Per-pair performance breakdown (BTC/USD, ETH/USD, SOL/USD, etc.)
- Historical performance tracking with time-stamped snapshots
- Real-time metrics published to Redis for dashboard consumption

**Metric Calculation Details:**
- **ROI**: `(ending_equity - starting_equity) / starting_equity * 100` (period-specific)
- **CAGR**: Annualized compound growth rate using period days
- **Sharpe Ratio**: Annualized risk-adjusted return using 5% risk-free rate
- **Max Drawdown**: Peak-to-trough decline calculated from filtered equity curve
- **Win Rate**: Percentage of profitable trades (from PnL summary or trade stream)
- **Profit Factor**: Gross profit / Gross loss (period-specific when available)

## Track Record & Performance Reporting

### Track Record Methodology

The system maintains a comprehensive track record of all trading activity for transparency and accountability:

1. **Signal Attribution**: Every signal is tracked with:
   - Signal ID (UUID v4)
   - Timestamp (ISO8601 UTC)
   - Strategy and regime classification
   - Entry/exit prices and position sizing
   - Outcome (WIN, LOSS, BREAKEVEN)

2. **Performance Aggregation**: Metrics are calculated using time-windowed data:
   - **30-day rolling**: Recent performance snapshot
   - **90-day rolling**: Quarterly performance view
   - **365-day rolling**: Annual performance summary

3. **Data Integrity**: 
   - All metrics use filtered equity curve data for period-specific accuracy
   - UTC timestamps ensure consistent time window calculations
   - Redis streams provide audit trail of all signals and PnL events

4. **Reporting Frequency**:
   - Real-time: Metrics updated hourly via `analysis/metrics_summary.py`
   - Published to: `engine:summary_metrics` Redis hash
   - Consumed by: signals-api and signals-site for dashboard display

### Performance Attribution

Performance is attributed across multiple dimensions:

- **By Strategy**: Scalper (40%), Trend (30%), Mean Reversion (20%), Breakout (10%)
- **By Trading Pair**: BTC/USD, ETH/USD, SOL/USD, MATIC/USD, LINK/USD
- **By Regime**: TRENDING_UP, TRENDING_DOWN, RANGING, VOLATILE
- **By Time Period**: 30d, 90d, 365d rolling windows

## Hypothetical Performance Limitations

**IMPORTANT:** All performance metrics displayed are based on paper trading simulations. See [SIGNAL_METHODOLOGY.md](SIGNAL_METHODOLOGY.md) for full risk disclosures including:

- **CFTC Rule 4.41 Disclaimer**: Past performance does not guarantee future results
- **Limitations of Hypothetical Results**: Paper trading results may not reflect live trading performance
- **Execution Risk Factors**: Real-world slippage, fees, and order fills may differ from assumptions
- **Model Drift Considerations**: ML models require periodic retraining to maintain accuracy
- **Market Conditions**: Performance may degrade during extreme volatility or regime shifts
- **Time Window Considerations**: Rolling period metrics may not capture full market cycles

---

## Related Documentation

- [PRD-001: Crypto AI Bot](PRD-001-CRYPTO-AI-BOT.md) - Full product requirements
- [Signal Methodology & Risk Disclosures](SIGNAL_METHODOLOGY.md) - Comprehensive methodology
- [Architecture](ARCHITECTURE.md) - System design
- [Engine Runbook](ENGINE-RUNBOOK.md) - Operations guide

---

**Document Version History**

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-12-05 | Initial PRD-001 compliant methodology |
