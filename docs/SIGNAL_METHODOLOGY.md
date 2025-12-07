# Signal Methodology & Risk Disclosures

**Version:** 1.0
**Last Updated:** 2025-12-03
**Status:** Authoritative Reference for Front-End Display

---

## Overview

This document provides a plain-English explanation of how AI Predicted Signals generates trading signals. It is designed for use on the signals-site front-end and investor communications.

---

## How Signals Are Generated

### 1. Real-Time Market Data Ingestion

Our system connects directly to Kraken's WebSocket API to receive:

- **Live Price Data**: Real-time bid/ask prices and trades
- **Order Book Depth**: Level 2 order book snapshots
- **Volume Data**: Trade volume and market activity
- **OHLCV Candles**: Price candles at multiple timeframes (15s, 1m, 5m)

Data is processed with sub-second latency and validated for freshness (reject data older than 5 seconds).

### 2. Technical Analysis Layer

Each market data point is processed through a comprehensive technical analysis engine:

| Indicator | Purpose | Timeframe |
|-----------|---------|-----------|
| RSI (14) | Overbought/Oversold detection | 5m, 15m |
| MACD | Momentum and trend direction | 5m |
| Bollinger Bands | Volatility and mean reversion | 5m |
| ATR (14) | Volatility measurement | 5m |
| Volume Profile | Volume surge detection | 5m |
| ADX | Trend strength | 15m |

### 3. AI Ensemble Model

Our proprietary AI system combines multiple machine learning models:

**Regime Detector (Random Forest + LSTM)**
- Classifies market conditions: TRENDING_UP, TRENDING_DOWN, RANGING, VOLATILE
- 200-candle lookback window
- Updates every 5 minutes
- Minimum 65% accuracy threshold

**Signal Analyst (Multi-Strategy)**
- Scalper: Short-term momentum trades (40% allocation)
- Trend Following: Directional trades with momentum (30% allocation)
- Mean Reversion: Counter-trend opportunities (20% allocation)
- Breakout: Volatility expansion trades (10% allocation)

**Confidence Scoring**
- Each signal receives a confidence score (0.0 - 1.0)
- Minimum confidence threshold: 60%
- Higher confidence = stronger signal agreement across models

### 4. Risk Management Filters

Before any signal is published, it must pass multiple risk checks:

| Filter | Threshold | Action |
|--------|-----------|--------|
| Spread Check | < 0.5% | Reject wide spreads |
| Volatility | < 3x ATR average | Reduce size or reject |
| Daily Drawdown | < -5% | Halt signals for the day |
| Loss Streak | 3 consecutive losses | Reduce allocation 50% |
| Position Concentration | < 40% per pair | Limit exposure |

### 5. Signal Publication

Validated signals are published to Redis Streams with:
- Unique idempotent signal ID (prevents duplicates)
- Precise entry price, stop loss, and take profit levels
- Confidence score and strategy attribution
- Risk-reward ratio calculation

---

## Supported Trading Pairs

| Symbol | Name | Status |
|--------|------|--------|
| BTC/USD | Bitcoin | Active |
| ETH/USD | Ethereum | Active |
| SOL/USD | Solana | Active |
| MATIC/USD | Polygon | Active |
| LINK/USD | Chainlink | Active |

All pairs are traded against USD on Kraken exchange.

---

## Signal Frequency

**Typical Output:**
- 2-10 high-confidence signals per day (confidence > 70%)
- 10-50 medium-confidence signals per day (confidence 60-70%)
- Signal frequency varies by market conditions

**Note:** Signal frequency claims on marketing materials should reflect the actual 30-day rolling average computed by the metrics aggregator.

---

## Performance Metrics Explained

### Win Rate
Percentage of signals that achieved their take-profit target before hitting stop-loss.

### Profit Factor
Ratio of gross profits to gross losses. A profit factor > 1.0 indicates profitable trading.

**Formula:** `Profit Factor = Gross Profits / Gross Losses`

### Sharpe Ratio
Risk-adjusted return metric. Higher is better.

**Formula:** `Sharpe = (Portfolio Return - Risk-Free Rate) / Portfolio Volatility`

### Maximum Drawdown
The largest peak-to-trough decline in portfolio value. Lower is better.

**Formula:** `Max DD = (Peak Value - Trough Value) / Peak Value`

### CAGR (Compound Annual Growth Rate)
Annualized return assuming compound growth.

**Formula:** `CAGR = (Ending Value / Beginning Value)^(1/years) - 1`

---

## Trading Assumptions (PRD-001)

Performance metrics are calculated using the following assumptions from PRD-001:

| Parameter | Value | Description |
|-----------|-------|-------------|
| **Slippage** | 0.1% (10 bps) | Expected price movement between signal and execution |
| **Maker Fee** | 0.075% | Fee for providing liquidity (limit orders) |
| **Taker Fee** | 0.15% | Fee for taking liquidity (market orders) |
| **Initial Capital** | $10,000 | Starting paper trading balance |
| **Risk-Free Rate** | 5.0% | Annual rate for Sharpe ratio calculation |
| **Trading Days** | 365/year | Crypto markets trade 24/7/365 |

**Fee Calculation Example:**

For a $1,000 trade:
- Maker order: $1,000 x 0.075% = $0.75 fee
- Taker order: $1,000 x 0.15% = $1.50 fee
- Slippage cost: $1,000 x 0.1% = $1.00

Total round-trip cost (market orders): ~0.5% ($5.00 on $1,000)

---

## Risk Disclosures

### Important Disclaimers

**HYPOTHETICAL PERFORMANCE DISCLAIMER**

The performance results shown are hypothetical and based on paper trading simulations. Hypothetical performance results have many inherent limitations:

1. **No actual capital at risk**: Paper trading does not involve real money and therefore does not account for the psychological aspects of trading with actual funds.

2. **Benefit of hindsight**: Hypothetical results are prepared with the benefit of hindsight and may be adjusted or optimized based on historical performance.

3. **No guarantee of future results**: Past performance, whether actual or hypothetical, is not indicative of future results.

4. **Execution differences**: Actual trading involves slippage, partial fills, and execution delays that are not fully captured in paper trading simulations.

5. **Market impact**: Large position sizes in live trading may impact market prices in ways not reflected in simulations.

6. **Assumptions may not reflect reality**: The fee and slippage assumptions (0.1% slippage, 0.075%/0.15% fees) are estimates. Actual costs may vary significantly during volatile market conditions.

**TRADING RISKS**

Cryptocurrency trading involves substantial risk of loss. You should:
- Only trade with capital you can afford to lose
- Understand that past performance does not guarantee future results
- Be aware that cryptocurrency markets are highly volatile
- Consider your own financial situation and risk tolerance
- Consult a financial advisor before making investment decisions

**NO FINANCIAL ADVICE**

The signals provided by this system are for informational purposes only and do not constitute financial, investment, or trading advice. We are not registered investment advisors.

**SYSTEM LIMITATIONS**

- The AI system may produce incorrect signals during extreme market conditions
- Technical failures, network outages, or exchange issues may disrupt signal delivery
- Historical backtesting may not accurately predict future performance
- Market conditions change and strategies that worked historically may not work in the future

**LIMITATIONS OF HYPOTHETICAL PERFORMANCE**

There is no guarantee that live trading will match paper trading results for the following reasons:

1. **Liquidity Constraints**: Paper trading assumes infinite liquidity. Live trading may face partial fills or inability to execute at desired prices, especially for larger position sizes.

2. **Slippage Variation**: The 0.1% slippage assumption is an average estimate. During flash crashes, news events, or low liquidity periods, actual slippage may be 5-10x higher.

3. **Emotional Factors**: Paper trading does not account for the psychological stress of risking real capital. Fear and greed can lead to poor decision-making that deviates from the strategy.

4. **Technical Glitches**: Real trading is subject to API rate limits, network latency, exchange downtime, and other technical issues not present in simulations.

5. **Regulatory Changes**: Cryptocurrency regulations evolve rapidly. Changes in tax treatment, exchange access, or trading restrictions may impact real-world results.

6. **Model Drift**: Machine learning models may degrade over time as market dynamics change. Regular retraining is required to maintain performance.

**CFTC RULE 4.41 DISCLAIMER**

HYPOTHETICAL OR SIMULATED PERFORMANCE RESULTS HAVE CERTAIN INHERENT LIMITATIONS. UNLIKE AN ACTUAL PERFORMANCE RECORD, SIMULATED RESULTS DO NOT REPRESENT ACTUAL TRADING. ALSO, SINCE THE TRADES HAVE NOT ACTUALLY BEEN EXECUTED, THE RESULTS MAY HAVE UNDER- OR OVER-COMPENSATED FOR THE IMPACT, IF ANY, OF CERTAIN MARKET FACTORS, SUCH AS LACK OF LIQUIDITY. SIMULATED TRADING PROGRAMS IN GENERAL ARE ALSO SUBJECT TO THE FACT THAT THEY ARE DESIGNED WITH THE BENEFIT OF HINDSIGHT. NO REPRESENTATION IS BEING MADE THAT ANY ACCOUNT WILL OR IS LIKELY TO ACHIEVE PROFITS OR LOSSES SIMILAR TO THOSE SHOWN.

---

## Technical Architecture

```
Market Data (Kraken WS)
        |
        v
+------------------+
| Data Validation  |
| - Freshness check|
| - Schema valid   |
+------------------+
        |
        v
+------------------+
| Technical        |
| Indicators       |
| (RSI, MACD, ATR) |
+------------------+
        |
        v
+------------------+
| Regime Detector  |
| (RF + LSTM)      |
+------------------+
        |
        v
+------------------+
| Signal Analyst   |
| (Multi-Strategy) |
+------------------+
        |
        v
+------------------+
| Risk Filters     |
| - Spread         |
| - Volatility     |
| - Drawdown       |
+------------------+
        |
        v
+------------------+
| Signal Publish   |
| -> Redis Streams |
+------------------+
        |
        v
signals-api -> signals-site
```

---

## Data Sources & Freshness

| Source | Update Frequency | Latency Target |
|--------|-----------------|----------------|
| Kraken WebSocket | Real-time | < 50ms |
| Price Feed | Per tick | < 100ms |
| Signal Generation | Per 5m candle | < 500ms |
| Redis Publication | Per signal | < 20ms |

---

## Contact & Support

For questions about signal methodology or system operations:
- GitHub Issues: [crypto-ai-bot repository]
- Technical Documentation: See PRD-001

---

**Document Version History**

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-12-03 | Initial methodology document for Week 3 harmonization |
