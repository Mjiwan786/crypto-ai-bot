# Engine Architecture Overview

**Version:** 1.0.0  
**Last Updated:** 2025-01-27  
**Audience:** Acquire.com Buyers & Technical Stakeholders  
**Reference:** PRD-001-CRYPTO-AI-BOT.md  
**Reading Time:** 10 minutes

---

## Executive Summary

The crypto-ai-bot engine is a **headless, event-driven service** that generates AI-powered trading signals for cryptocurrency markets. It operates 24/7, consuming real-time market data from Kraken exchange and publishing actionable trading signals to Redis Cloud for consumption by downstream systems (signals-api and signals-site).

**Key Value Propositions:**
- **Real-Time Signal Generation:** Sub-second latency from market data to signal publication
- **Multi-Agent AI Architecture:** Four specialized trading strategies (Scalper, Trend, Mean Reversion, Breakout)
- **Investor-Ready Metrics:** Automated calculation and publishing of ROI, Sharpe ratio, win rate, and drawdown
- **Production-Grade Reliability:** Automatic reconnection, health monitoring, and graceful degradation
- **Paper & Live Modes:** Strict separation between simulated and real trading environments

---

## System Architecture

### High-Level Flow

```
┌─────────────┐      ┌──────────────┐      ┌─────────────┐      ┌──────────────┐
│   Kraken    │─────▶│   Engine     │─────▶│    Redis    │─────▶│  signals-api │
│  WebSocket  │      │  (This Repo) │      │    Cloud    │      │   (Repo 2)   │
└─────────────┘      └──────────────┘      └─────────────┘      └──────────────┘
                            │                       │
                            │                       │
                            ▼                       ▼
                    ┌──────────────┐      ┌──────────────┐
                    │   Metrics    │      │   Investor   │
                    │  Calculator  │      │   Dashboard  │
                    └──────────────┘      └──────────────┘
```

### Component Responsibilities

1. **Kraken WebSocket Client** (`utils/kraken_ws.py`)
   - Maintains persistent WebSocket connection to Kraken exchange
   - Receives real-time market data (trades, order book, OHLCV candles)
   - Automatic reconnection with exponential backoff (PRD-001 Section 5.1)
   - Circuit breaker protection against exchange outages

2. **Signal Generation Engine** (`agents/`)
   - Multi-agent architecture with plug-in support
   - Four core strategies: Scalper, Trend, Mean Reversion, Breakout
   - ML-powered regime detection (trending vs ranging markets)
   - Risk-adjusted position sizing and confidence scoring

3. **Metrics Calculator** (`analysis/metrics_summary.py`)
   - Calculates investor-facing performance metrics hourly
   - Computes ROI, Sharpe ratio, win rate, profit factor, max drawdown
   - Publishes to `engine:summary_metrics` Redis hash
   - Consumed by signals-api `/v1/metrics/summary` endpoint

4. **Health Publisher** (`main_engine.py`)
   - Publishes heartbeat every 30 seconds to `engine:heartbeat`
   - Exposes HTTP health endpoint on port 8080 (configurable)
   - Required for Fly.io orchestration and monitoring

5. **Redis Publisher** (`main_engine.py`)
   - Publishes signals to Redis Streams: `signals:paper:<PAIR>` or `signals:live:<PAIR>`
   - Maintains signal ordering and timestamps
   - Auto-expires old signals (7-day TTL)

---

## Agent Architecture

### Strategy Agents

The engine uses a **plug-in agent architecture** (PRD-001 Section 3.1) where each agent implements a specific trading strategy:

| Agent | Strategy | Use Case | Allocation |
|-------|----------|----------|------------|
| **Scalper** | High-frequency, short-term | Volatile markets, tight spreads | 40% |
| **Trend** | Momentum following | Strong directional moves | 30% |
| **Mean Reversion** | Counter-trend | Ranging markets | 20% |
| **Breakout** | Volatility expansion | Range breakouts | 10% |

**Agent Selection Logic:**
1. ML regime detector identifies market state (trending, ranging, volatile)
2. Strategy allocator assigns signals based on regime and allocations
3. Each agent generates signals with confidence scores (0.0-1.0)
4. Signals below 60% confidence are rejected (PRD-001 Section 3.3)

### Signal Flow

```
Market Data → Feature Engineering → ML Inference → Strategy Selection → Risk Filter → Redis Stream
     │              │                    │              │                  │
     │              │                    │              │                  │
  Kraken WS    128 Technical      Ensemble Model    Agent Router    Spread/Volatility
               Indicators         (LSTM+Transformer)                Checks
```

**Processing Latency:** ~100-150ms from market data to signal publication

---

## Redis Streams Architecture

### Signal Streams

**Format:** `signals:<MODE>:<PAIR>`

- **Paper Mode:** `signals:paper:BTC/USD`, `signals:paper:ETH/USD`, etc.
- **Live Mode:** `signals:live:BTC/USD`, `signals:live:ETH/USD`, etc.

**Signal Schema** (PRD-001 Section 4.1):
```json
{
  "signal_id": "uuid",
  "timestamp": "ISO8601",
  "pair": "BTC/USD",
  "side": "LONG" | "SHORT",
  "strategy": "SCALPER" | "TREND" | "MEAN_REVERSION" | "BREAKOUT",
  "entry_price": 50000.0,
  "take_profit": 52000.0,
  "stop_loss": 49000.0,
  "confidence": 0.85,
  "position_size_usd": 100.0,
  "risk_reward_ratio": 2.0
}
```

### Metrics Storage

**Key:** `engine:summary_metrics` (Redis Hash)

**Fields:**
- `roi_30d`: 30-day Return on Investment (percentage)
- `win_rate_pct`: Win rate (0-100)
- `sharpe_ratio`: Risk-adjusted return metric
- `profit_factor`: Gross profit / gross loss ratio
- `max_drawdown_pct`: Maximum drawdown (percentage)
- `signals_per_day`: Average signals per day
- `total_trades`: Total trades in 30-day period
- `performance_30d_json`: Detailed 30-day performance (JSON string)
- `performance_90d_json`: Detailed 90-day performance (JSON string)
- `performance_365d_json`: Detailed 365-day performance (JSON string)

**Update Frequency:** Hourly (automated)

### Health & Status

- `engine:heartbeat`: ISO8601 timestamp (updated every 30 seconds)
- `engine:status`: JSON status object (updated every 30 seconds)

---

## Data Flow

### 1. Market Data Ingestion

```
Kraken WebSocket → KrakenWSClient → Market Data Buffer → Feature Engineering
```

**Data Types:**
- Trades (real-time execution data)
- Order Book (bid/ask depth)
- OHLCV Candles (1m, 5m, 15m, 1h timeframes)

### 2. Signal Generation

```
Feature Engineering → ML Inference → Strategy Selection → Risk Filter → Signal Publisher
```

**Risk Filters** (PRD-001 Section 7):
- Spread check: Reject if spread > 0.5%
- Volatility check: Reduce position size in high volatility
- Drawdown limit: Pause trading if daily drawdown > -5%
- Loss streak: Pause after 3 consecutive losses

### 3. Signal Publishing

```
Signal Publisher → Redis Stream (signals:paper:<PAIR>) → signals-api → signals-site
```

**Ordering:** Signals are published with millisecond-precision timestamps, maintaining strict ordering

### 4. Metrics Calculation

```
Equity Curve → Performance Calculator → Metrics Aggregator → Redis Hash (engine:summary_metrics)
```

**Data Sources:**
- `pnl:paper:equity_curve` stream (equity over time)
- `pnl:paper:summary` key (trade statistics)
- `signals:paper:<PAIR>` streams (signal frequency)

---

## Operational Characteristics

### Reliability Features

1. **Automatic Reconnection** (PRD-001 Section 5.1)
   - Exponential backoff: 1s → 2s → 4s → ... → max 60s
   - Maximum 10 retry attempts
   - Jitter to prevent thundering herd

2. **Circuit Breakers**
   - Spread circuit breaker: Opens if spread > 1.0%
   - Latency circuit breaker: Opens if latency > 500ms
   - Connection circuit breaker: Opens on repeated connection failures

3. **Graceful Degradation**
   - Engine continues operating if non-critical components fail
   - Health endpoint reports component status
   - Metrics continue publishing even if signal generation pauses

### Performance Targets

- **Uptime:** 99.5% (24/7 operation)
- **Signal Latency:** < 500ms (market data to Redis)
- **WebSocket Latency:** < 100ms (p50), < 200ms (p95)
- **Metrics Update:** Hourly (within 5-minute window)

### Mode Separation

**Paper Mode:**
- Streams: `signals:paper:*`
- PnL: `pnl:paper:*`
- No real money at risk
- Used for testing and investor demonstrations

**Live Mode:**
- Streams: `signals:live:*`
- PnL: `pnl:live:*`
- Real money trading
- Requires `LIVE_TRADING_CONFIRMATION` environment variable

**Strict Separation:** Paper and live modes never share streams or data (PRD-001 Section 2.3)

---

## Technology Stack

### Core Technologies

- **Python 3.10+**: Main programming language
- **asyncio**: Asynchronous I/O for WebSocket and Redis
- **Redis Cloud**: Managed Redis with TLS encryption
- **Kraken WebSocket API**: Real-time market data
- **Pydantic v2**: Data validation and schema enforcement
- **Prometheus**: Metrics collection (optional)

### Key Dependencies

- `redis.asyncio`: Redis client with async support
- `websockets`: WebSocket client library
- `orjson`: Fast JSON serialization
- `pydantic`: Data validation

### Deployment

- **Local:** Conda environment (`crypto-bot`)
- **Production:** Fly.io (Docker container)
- **Health Check:** HTTP endpoint on port 8080
- **Logging:** Structured JSON logs (optional) or text logs

---

## Integration Points

### Downstream Systems

1. **signals-api** (Repo 2)
   - Consumes `signals:paper:<PAIR>` streams
   - Serves signals via REST API and Server-Sent Events (SSE)
   - Reads `engine:summary_metrics` for `/v1/metrics/summary` endpoint

2. **signals-site** (Repo 3)
   - Displays signals in real-time via SSE
   - Shows performance metrics from `/v1/metrics/summary`
   - Investor dashboard at aipredictedsignals.cloud

### API Contract

**Signals API Endpoint:** `GET /v1/metrics/summary`

**Response Format:**
```json
{
  "roi_30d": 5.5,
  "win_rate_pct": 55.5,
  "sharpe_ratio": 1.72,
  "profit_factor": 1.85,
  "max_drawdown_pct": -8.2,
  "signals_per_day": 48.0,
  "total_trades": 1420,
  "timestamp": "2025-01-27T12:00:00Z"
}
```

---

## Security & Compliance

### Data Security

- **TLS Encryption:** All Redis connections use TLS (rediss://)
- **CA Certificates:** Required for Redis Cloud connections
- **No Secrets in Code:** All credentials via environment variables
- **Log Redaction:** Sensitive data automatically redacted from logs

### Operational Security

- **Mode Validation:** Engine validates mode before starting
- **Live Mode Confirmation:** Requires explicit confirmation for live trading
- **Circuit Breakers:** Prevent runaway trading in adverse conditions
- **Audit Logging:** All signal generation and publishing logged

---

## Monitoring & Observability

### Health Monitoring

- **Health Endpoint:** `GET /health` (returns 200 OK if healthy)
- **Heartbeat:** Published to Redis every 30 seconds
- **Status JSON:** Component status and uptime metrics

### Metrics & Logging

- **Structured Logs:** JSON format (optional) for log aggregation
- **Log Levels:** INFO (default), DEBUG, WARNING, ERROR
- **Log Rotation:** Automatic rotation with configurable retention
- **Prometheus Metrics:** Optional metrics export for monitoring systems

### Key Metrics to Monitor

1. **Engine Health:** Heartbeat freshness (< 60 seconds)
2. **Signal Generation Rate:** Signals per day (expected: 20-100)
3. **WebSocket Latency:** p50, p95, p99 latencies
4. **Redis Connection:** Connection status and latency
5. **Error Rate:** Failed signal generations, connection errors

---

## Scalability & Limits

### Current Capacity

- **Trading Pairs:** 5 pairs (BTC/USD, ETH/USD, SOL/USD, LINK/USD, DOT/USD)
- **Signal Rate:** ~50-100 signals per day (across all pairs)
- **Concurrent Connections:** Single WebSocket connection (Kraken limit)
- **Redis Throughput:** 10,000+ operations per second

### Scaling Considerations

- **Horizontal Scaling:** Multiple engine instances can run in parallel (different pairs)
- **Redis Sharding:** Can partition streams by pair if needed
- **Agent Scaling:** New agents can be added without core changes (plug-in architecture)

---

## Summary

The crypto-ai-bot engine is a **production-ready, event-driven signal generation system** that:

1. **Ingests** real-time market data from Kraken via WebSocket
2. **Processes** data through multi-agent AI architecture with four trading strategies
3. **Publishes** validated signals to Redis Streams for downstream consumption
4. **Calculates** investor-facing performance metrics hourly
5. **Monitors** its own health and publishes status for orchestration

The system is designed for **24/7 operation** with automatic reconnection, circuit breakers, and graceful degradation. It strictly separates paper and live trading modes, ensuring no cross-contamination between simulated and real trading environments.

**Key Differentiators:**
- Multi-agent plug-in architecture (easy to add new strategies)
- Real-time signal generation (< 500ms latency)
- Investor-ready metrics (automated calculation and publishing)
- Production-grade reliability (automatic reconnection, health monitoring)

---

**For Detailed Operations:** See `docs/RUNBOOK_ENGINE.md`  
**For Requirements:** See `docs/PRD-001-CRYPTO-AI-BOT.md`  
**Last Updated:** 2025-01-27

