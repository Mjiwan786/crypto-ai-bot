# PRD-001: Crypto AI Bot - Core Intelligence Engine

**Version:** 1.0.0
**Status:** Authoritative
**Last Updated:** 2025-11-14
**Owner:** Product & Engineering

---

## Executive Summary

### What This Repository Does

The `crypto-ai-bot` repository is the **core intelligence and signal generation engine** for a production-grade, AI-driven cryptocurrency trading system. It consumes real-time market data from Kraken WebSocket APIs, processes it through a multi-agent AI architecture, and publishes actionable trading signals to Redis Streams for consumption by downstream execution and display systems.

### Role in the 3-Repo Architecture

This repository is **Repo 1 of 3** in the complete trading infrastructure:

1. **crypto-ai-bot** (this repo): Signal generation engine - ingests market data, runs AI analysis, publishes signals
2. **signals-api**: REST/SSE API gateway - serves signals to clients, manages subscriptions, provides health endpoints
3. **signals-site**: Front-end SaaS portal - displays signals, performance metrics, and system health to end users

The crypto-ai-bot operates as a **headless, event-driven service** that:
- Runs continuously (24/7) in production on Fly.io
- Maintains persistent WebSocket connections to Kraken
- Publishes structured signals to Redis Cloud (TLS-secured)
- Exposes Prometheus metrics for observability
- Operates independently of the API and UI layers

### Problems That Existed Before

Prior to this PRD, the system suffered from critical architectural and operational deficiencies:

1. **Undefined Methodology**: No clear algorithmic basis for signal generation; ML models were black boxes
2. **Broken Signal Flow**: Signals generated but not validated; schema inconsistencies between repos
3. **Empty PnL Data**: No performance tracking; impossible to measure profitability or validate strategies
4. **Dropped WebSocket Messages**: No reconnection logic; silent failures on network interruptions
5. **No Reconnection Strategy**: System crashed on connection loss; required manual restarts
6. **Schema Drift**: Signals published with inconsistent fields across different components
7. **Missing Tests**: No unit, integration, or end-to-end tests; deployments were blind
8. **Missing Risk Filters**: No spread checks, volatility limits, or drawdown controls
9. **No ML Transparency**: Models retrained without validation; no feature importance tracking
10. **Missing Documentation**: No runbooks, methodology docs, or architecture diagrams
11. **Multi-Repo Inconsistencies**: Different signal schemas in bot vs API vs UI

### What This PRD Solves

This PRD establishes the **single source of truth** for the crypto-ai-bot repository. It provides:

- **Clear Functional Requirements**: Every subsystem (WebSocket ingestion, Redis publishing, ML engine, risk manager) has defined responsibilities
- **Strict Schema Specification**: Exact JSON structure for all published signals
- **Data Integrity Guarantees**: Ordering, deduplication, idempotency requirements
- **Risk Management Framework**: Spread limits, volatility checks, drawdown controls, position sizing rules
- **ML Transparency Requirements**: Feature dictionaries, validation metrics, ensemble weighting
- **Reliability Standards**: Reconnection logic, health checks, graceful degradation
- **Testing Requirements**: Comprehensive test coverage across unit, integration, and E2E scenarios
- **Documentation Standards**: Runbooks, architecture docs, signal flow diagrams
- **Measurable Success Criteria**: 24/7 uptime, sub-500ms latency, 99.5% signal delivery rate

---

## Problem Analysis (Based on System Review)

### 1. Missing Methodology

**Problem:**
The system generated signals without a documented algorithmic foundation. Engineers and investors could not answer: "How does this bot make trading decisions?"

**Impact:**
- Impossible to audit signal quality
- No basis for performance attribution
- Regulatory risk (unexplainable AI)
- Inability to debug poor performance

**Required Fix:**
Document and implement a clear, deterministic signal generation methodology that combines:
- Technical indicators (RSI, MACD, Bollinger Bands)
- Volume analysis (OBV, VWAP)
- Market microstructure (spread, depth, momentum)
- ML regime detection (trending, ranging, volatile)
- Risk-adjusted position sizing

### 2. Broken Signal Flow

**Problem:**
Signals were generated but never validated end-to-end. The bot published to Redis, but there was no verification that:
- Signals reached the API layer
- The API could parse the signal format
- The UI could display the signals

**Impact:**
- Production outages went undetected for hours
- Silent failures in the signal pipeline
- Downstream systems received malformed data

**Required Fix:**
Implement end-to-end signal flow validation:
- Redis Streams health monitoring
- Schema validation on publish
- Test fixtures simulating full pipeline
- Automated E2E tests running daily

### 3. Empty PnL / Missing Metrics

**Problem:**
The system had no PnL tracking, making it impossible to:
- Measure strategy profitability
- Compare live vs backtest performance
- Validate that signals translated to profitable trades
- Track slippage, fees, and execution quality

**Impact:**
- No accountability for signal quality
- Impossible to detect strategy degradation
- No data for investor reporting

**Required Fix:**
Implement comprehensive performance tracking:
- Redis-backed PnL streams
- Per-signal attribution (entry/exit tracking)
- Slippage and fee calculation
- Daily/weekly/monthly aggregation
- Prometheus metrics for real-time monitoring

### 4. Dropped WebSocket Messages

**Problem:**
The Kraken WebSocket ingestion layer had no handling for:
- Message loss (network interruptions)
- Out-of-order delivery
- Duplicate messages
- Stale data detection

**Impact:**
- Signals based on incomplete data
- Stale prices causing bad trades
- Silent data gaps

**Required Fix:**
Implement robust WebSocket message handling:
- Sequence number validation (detect gaps)
- Timestamp freshness checks (reject stale data > 5s)
- Message deduplication (idempotency keys)
- Gap detection with alerts

### 5. No Reconnection Strategy

**Problem:**
On WebSocket disconnection (network blip, Kraken restart, etc.), the bot crashed. No exponential backoff, no automatic recovery.

**Impact:**
- Downtime requiring manual intervention
- Lost trading opportunities during outages
- Poor user experience (empty dashboards)

**Required Fix:**
Implement production-grade reconnection logic:
- Exponential backoff with jitter (start at 1s, max 60s)
- Max retry limit (10 attempts before escalation)
- Health check integration (mark unhealthy during reconnect)
- Graceful degradation (serve cached data if available)

### 6. Schema Drift Between Repos

**Problem:**
The signal schema evolved independently in each repo:
- Bot published `side: "long"` but API expected `direction: "buy"`
- Timestamp formats differed (Unix ms vs ISO8601)
- Field names inconsistent (`symbol` vs `pair` vs `trading_pair`)

**Impact:**
- API parsing errors
- UI display bugs
- Data pipeline failures

**Required Fix:**
Establish a canonical signal schema:
- Single source of truth (this PRD, Section 5)
- Schema validation on publish (Pydantic models)
- Integration tests verifying cross-repo compatibility
- Automated schema drift detection

### 7. Missing Tests

**Problem:**
The repository had minimal test coverage:
- No unit tests for core logic
- No integration tests for Redis/Kraken
- No end-to-end tests
- No regression test suite

**Impact:**
- Deployment fear (every release was risky)
- Bugs discovered in production
- Inability to refactor safely

**Required Fix:**
Achieve 80%+ test coverage:
- Unit tests for all agents, strategies, risk logic
- Integration tests for WebSocket, Redis, health checks
- E2E tests simulating full signal lifecycle
- Mocked Kraken feeds for deterministic testing
- CI/CD pipeline running tests on every commit

### 8. Missing Risk Filters

**Problem:**
Signals were generated without validating:
- Spread width (avoid illiquid markets)
- Volatility regime (reduce size in high vol)
- Daily drawdown limits
- Position concentration
- Maximum loss streaks

**Impact:**
- Exposure to illiquid, high-slippage conditions
- Oversized positions during volatility spikes
- Uncontrolled drawdowns

**Required Fix:**
Implement multi-layer risk filters (Section 7):
- Pre-signal spread checks (reject if > 0.5%)
- Volatility-adjusted position sizing (ATR-based)
- Daily drawdown circuit breaker (-5% max)
- Per-symbol position limits
- Loss streak tracking (pause after 3 consecutive losses)

### 9. No Transparency in ML

**Problem:**
ML models (regime detector, signal confidence scorer) operated as black boxes:
- No feature importance tracking
- No validation metrics logged
- Retraining happened without performance verification
- No ensemble weighting transparency

**Impact:**
- Impossible to debug ML failures
- Model drift undetected
- No basis for trust in AI outputs

**Required Fix:**
Implement ML transparency requirements (Section 8):
- Feature dictionaries (what inputs drive predictions)
- Validation metrics (accuracy, precision, recall on holdout sets)
- Ensemble weighting (log contribution of each model)
- Retraining audit trail (when, why, performance delta)
- A/B testing framework for model upgrades

### 10. Missing Documentation

**Problem:**
The repository lacked essential docs:
- No architecture diagram
- No signal flow explanation
- No runbook for operations
- No methodology whitepaper

**Impact:**
- New engineers took weeks to onboard
- Debugging required archeology
- Investors had no trust in the system
- Operations team couldn't troubleshoot

**Required Fix:**
Comprehensive documentation (Section 11):
- `METHODOLOGY.md`: Algorithmic foundation
- `ARCHITECTURE.md`: System design, data flow
- `RUNBOOK.md`: Deployment, monitoring, incident response
- `SIGNAL_FLOW.md`: End-to-end signal lifecycle

### 11. Multi-Repo Inconsistencies

**Problem:**
The 3-repo architecture had no coordination mechanism:
- Bot published signals the API couldn't parse
- API returned data the UI couldn't render
- Deployments were out of sync (bot v2.0, API v1.5, UI v1.8)

**Impact:**
- Cross-repo integration failures
- Version mismatch bugs
- Impossible to debug distributed system

**Required Fix:**
Establish multi-repo governance:
- Shared schema definitions (published as npm/PyPI package)
- Coordinated release process (bot → API → UI)
- Integration test suite spanning all 3 repos
- Shared Redis contract (stream names, TTLs, MAXLEN)

---

## Goals & Success Criteria

### Primary Goals

1. **24/7 Uptime**: System runs continuously without manual intervention
2. **Deterministic Signals**: Every signal traceable to input data + algorithm
3. **Sub-500ms Latency**: P95 latency from market data → signal publish < 500ms
4. **Schema-Safe Publishing**: 100% of signals conform to canonical schema
5. **ML Reproducibility**: Model predictions reproducible from logged features
6. **Zero Silent Failures**: All errors logged, alerted, and surfaced to health checks

### Success Criteria (Measurable KPIs)

| Metric | Target | Measurement Method |
|--------|--------|-------------------|
| **Uptime** | ≥ 99.5% (43.8 min downtime/month) | Fly.io health checks, Prometheus `up` metric |
| **Signal Publish Rate** | ≥ 10 signals/hour (per pair) | Redis stream length growth rate |
| **Latency (P50)** | ≤ 200ms (data ingestion → signal publish) | Prometheus histogram `signal_generation_latency_ms` |
| **Latency (P95)** | ≤ 500ms | Same histogram, P95 quantile |
| **Latency (P99)** | ≤ 1000ms | Same histogram, P99 quantile |
| **Schema Compliance** | 100% (0 validation errors) | Pydantic validation metrics |
| **WebSocket Reconnects** | ≤ 5/day (under normal conditions) | Counter `kraken_ws_reconnect_total` |
| **Test Coverage** | ≥ 80% (line coverage) | pytest-cov report |
| **PnL Tracking** | 100% of signals attributed to P&L | Redis stream `pnl:signals` vs `signals:paper` length match |
| **Alert Response Time** | ≤ 5 min (from incident → engineer notified) | PagerDuty/Slack integration |

### Non-Goals (Out of Scope for This Repo)

- **Order Execution**: Handled by signals-api (repo 2)
- **User Interface**: Handled by signals-site (repo 3)
- **Historical Data Storage**: Long-term storage is API responsibility; bot only maintains recent data (24hr window)
- **Multi-Exchange Support**: v1 targets Kraken only; Binance/Coinbase are future work

---

## Core Functional Requirements

### A. Kraken WebSocket Ingestion

**Responsibility:**
Maintain real-time, reliable connections to Kraken WebSocket APIs for market data.

**Requirements:**

1. **Connection Management**
   - Subscribe to Kraken WS feeds: `ticker`, `spread`, `trade`, `book` (L2)
   - Support configurable pairs: `BTC/USD`, `ETH/USD`, `SOL/USD`, `MATIC/USD`, `LINK/USD`
   - Implement heartbeat monitoring (PING/PONG every 30s)
   - Auto-reconnect on disconnect (exponential backoff: 1s, 2s, 4s, 8s, ... max 60s)
   - Max 10 reconnect attempts before marking unhealthy

2. **Data Validation**
   - Verify sequence numbers (detect message loss)
   - Timestamp freshness check (reject data > 5s old)
   - Schema validation (Kraken response format)
   - Deduplication (cache last 100 message IDs)

3. **Error Handling**
   - Log all connection errors (ERROR level)
   - Emit Prometheus metrics: `kraken_ws_errors_total{error_type}`
   - Mark health check unhealthy during sustained failures (> 2 min)
   - Graceful degradation: serve cached data if available

4. **Performance**
   - P95 latency from Kraken → Redis < 50ms
   - Handle 100+ messages/sec per pair
   - Memory bound: max 100MB for WebSocket buffers

**Configuration:**
```yaml
exchange:
  kraken:
    ws_url: "wss://ws.kraken.com"
    timeout_sec: 30
    reconnect_max_attempts: 10
    reconnect_backoff_base_sec: 1
    reconnect_backoff_max_sec: 60
    pairs: ["BTC/USD", "ETH/USD", "SOL/USD", "MATIC/USD", "LINK/USD"]
    channels: ["ticker", "spread", "trade", "book"]
```

### B. Redis Streams Publishing

**Responsibility:**
Publish validated, schema-compliant signals to Redis Cloud for consumption by signals-api.

**Requirements:**

1. **Connection Management**
   - Connect to Redis Cloud via TLS (rediss://)
   - Use connection pooling (max 10 connections)
   - Credential management via environment variable: `REDIS_URL`
   - Certificate path: `config/certs/redis_ca.pem`
   - Health check integration (PING every 60s)

2. **Stream Configuration**
   - Signal stream: `signals:paper` (paper trading) or `signals:live` (production)
   - PnL stream: `pnl:signals` (performance attribution)
   - Events stream: `events:bus` (system events, alerts)
   - MAXLEN: 10,000 messages per stream (automatic trimming)
   - TTL: 7 days (Redis Cloud auto-expiration)

3. **Publishing Guarantees**
   - Idempotency: use `signal_id` as message ID (dedupe)
   - Atomicity: all signal fields published in single XADD command
   - Ordering: timestamp-based (server-side ordering in Redis)
   - Schema validation before publish (Pydantic model)
   - Retry logic: 3 attempts with exponential backoff on publish failure

4. **Performance**
   - P95 publish latency < 20ms
   - Handle 50+ signals/sec
   - Max queue depth: 1000 pending messages (backpressure)

**Configuration:**
```yaml
redis:
  url: "${REDIS_URL}"  # rediss://default:<password>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818
  ssl_cert_path: "config/certs/redis_ca.pem"
  connection_pool:
    max_connections: 10
    timeout_sec: 5
  streams:
    signals_paper: "signals:paper"
    signals_live: "signals:live"
    pnl: "pnl:signals"
    events: "events:bus"
  maxlen: 10000
  ttl_days: 7
```

### C. Multi-Agent ML Engine

**Responsibility:**
Run AI-driven analysis on market data to generate trading signals.

**Requirements:**

1. **Agent Architecture**
   - **Regime Detector**: Classify market state (trending, ranging, volatile)
   - **Signal Analyst**: Generate trade ideas (long/short, confidence score)
   - **Risk Manager**: Validate signals against risk limits
   - **Position Manager**: Track open positions, manage exits

2. **Regime Detector**
   - Input: 1-hour OHLCV data
   - Output: regime label (`TRENDING_UP`, `TRENDING_DOWN`, `RANGING`, `VOLATILE`)
   - Model: Ensemble (Random Forest + LSTM)
   - Retraining: Weekly (Sunday 00:00 UTC)
   - Validation: 70/30 train/test split, min 65% accuracy
   - Features: ADX, ATR, Bollinger Band width, volume profile

3. **Signal Analyst**
   - Input: 5m OHLCV + current regime + order book snapshot
   - Output: signal (side, entry_price, take_profit, stop_loss, confidence)
   - Strategies: Scalper, Trend, Mean Reversion, Breakout
   - Allocation: weighted by recent performance (last 100 trades)
   - Min confidence: 0.6 (reject signals < 60% confidence)

4. **Backtesting Validation**
   - Every strategy must pass backtest before production
   - Min Sharpe ratio: 1.5
   - Max drawdown: -15%
   - Win rate: ≥ 45%
   - Test period: 90 days historical data

**Configuration:**
```yaml
ai_engine:
  regime_detector:
    model_path: "models/regime_rf_lstm_ensemble.pkl"
    retrain_schedule_cron: "0 0 * * 0"  # Weekly Sunday midnight
    min_accuracy: 0.65
    features: ["adx", "atr", "bb_width", "volume_profile"]
  signal_analyst:
    min_confidence: 0.6
    strategies:
      scalper: {allocation: 0.4}
      trend: {allocation: 0.3}
      mean_reversion: {allocation: 0.2}
      breakout: {allocation: 0.1}
  backtesting:
    min_sharpe: 1.5
    max_drawdown: -0.15
    min_win_rate: 0.45
    test_period_days: 90
```

### D. Regime Detector

**Responsibility:**
Classify market conditions to adapt strategy selection.

**Requirements:**

1. **Regime Classification**
   - `TRENDING_UP`: ADX > 25, price > SMA(50)
   - `TRENDING_DOWN`: ADX > 25, price < SMA(50)
   - `RANGING`: ADX < 20, Bollinger Band width < historical 30th percentile
   - `VOLATILE`: ATR > historical 80th percentile

2. **Data Requirements**
   - Lookback: 200 candles (5m timeframe = 16.7 hours history)
   - Update frequency: Every 5 minutes
   - Caching: Store last 24 hours of regime labels in Redis

3. **Performance**
   - Prediction latency: < 100ms
   - Model size: < 50MB (RAM footprint)
   - Retraining time: < 10 minutes

### E. Risk Engine

**Responsibility:**
Enforce risk limits on signal generation and position sizing.

**Requirements:**

1. **Pre-Signal Filters** (reject signals that fail)
   - Spread > 0.5% (illiquid)
   - Volatility (ATR) > 3x daily average (too risky)
   - Daily drawdown > -5% (circuit breaker)
   - Position concentration > 40% of portfolio (over-exposure)

2. **Position Sizing**
   - Base size: $100 per signal
   - Volatility adjustment: `size = base_size / (ATR / ATR_avg)`
   - Confidence scaling: `size *= signal_confidence`
   - Max size per position: $2,000
   - Max total exposure: $10,000

3. **Drawdown Control**
   - Daily max drawdown: -5% (halt new signals until next day)
   - Weekly max drawdown: -10% (reduce position sizes by 50%)
   - Monthly max drawdown: -20% (pause system, alert engineer)

4. **Loss Streak Management**
   - Track consecutive losses per strategy
   - After 3 losses: reduce allocation by 50%
   - After 5 losses: pause strategy, trigger review

**Configuration:**
```yaml
risk:
  filters:
    max_spread_pct: 0.5
    max_volatility_multiple: 3.0
  position_sizing:
    base_usd: 100
    max_position_usd: 2000
    max_total_exposure_usd: 10000
  drawdown_limits:
    daily_pct: -5.0
    weekly_pct: -10.0
    monthly_pct: -20.0
  loss_streaks:
    warn_threshold: 3
    pause_threshold: 5
```

### F. Backtesting Validation

**Responsibility:**
Validate all strategies against historical data before production use.

**Requirements:**

1. **Data Requirements**
   - Historical OHLCV: 1 year (365 days)
   - Trade execution simulation (slippage model)
   - Fee calculation (Kraken fee tiers)
   - Realistic order fills (limit orders require depth check)

2. **Metrics**
   - Total return (%)
   - Sharpe ratio
   - Max drawdown
   - Win rate
   - Profit factor (gross profit / gross loss)
   - Average trade duration

3. **Acceptance Criteria**
   - Sharpe ≥ 1.5
   - Drawdown ≤ -15%
   - Win rate ≥ 45%
   - Profit factor ≥ 1.3
   - Min 200 trades in backtest period

4. **Automation**
   - Run backtests in CI/CD on every strategy change
   - Store results in `out/backtests/` directory
   - Block deployment if backtest fails

**Configuration:**
```yaml
backtesting:
  data_source: "kraken"
  lookback_days: 365
  slippage_bps: 5  # 0.05%
  fees:
    maker_bps: 16  # 0.16%
    taker_bps: 26  # 0.26%
  acceptance_criteria:
    min_sharpe: 1.5
    max_drawdown: -0.15
    min_win_rate: 0.45
    min_profit_factor: 1.3
    min_trades: 200
```

### G. Configuration System

**Responsibility:**
Centralize all system configuration with environment-specific overrides.

**Requirements:**

1. **Configuration Files**
   - Base config: `config/settings.yaml`
   - Environment overrides: `.env.paper`, `.env.live`
   - Strategy configs: `config/strategies/*.yaml`
   - Risk configs: `config/risk/*.yaml`

2. **Environment Variables**
   - `REDIS_URL`: Redis Cloud connection string
   - `TRADING_MODE`: `paper` or `live`
   - `LOG_LEVEL`: `DEBUG`, `INFO`, `WARNING`, `ERROR`
   - `KRAKEN_API_KEY`, `KRAKEN_SECRET`: (for authenticated endpoints)

3. **Validation**
   - Pydantic models for all config sections
   - Schema validation on load (fail fast on invalid config)
   - Type checking (int, float, str, enum)
   - Range validation (min/max values)

4. **Hot Reload** (Optional)
   - Watch config files for changes
   - Reload without restart (for non-critical params like log level)
   - Restricted: cannot hot-reload Redis URL, trading pairs

**Configuration:**
```yaml
# config/settings.yaml
mode:
  bot_mode: PAPER  # or LIVE
  enable_trading: false  # safety switch

logging:
  level: INFO
  dir: logs/
  format: json  # structured logging

redis:
  url: "${REDIS_URL}"
  ssl_cert_path: "config/certs/redis_ca.pem"

exchange:
  primary: "kraken"
  pairs: ["BTC/USD", "ETH/USD", "SOL/USD", "MATIC/USD", "LINK/USD"]

strategies:
  allocations:
    scalper: 0.4
    trend: 0.3
    mean_reversion: 0.2
    breakout: 0.1
```

### H. Logging & Metrics

**Responsibility:**
Provide observability into system behavior for debugging and monitoring.

**Requirements:**

1. **Structured Logging**
   - Format: JSON (parseable by log aggregators)
   - Fields: `timestamp`, `level`, `component`, `message`, `context`
   - Levels: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`
   - Destinations: stdout (Fly.io logs) + `logs/crypto_ai_bot.log`

2. **Log Rotation**
   - Max file size: 100MB
   - Keep last 7 days
   - Compress old logs (gzip)

3. **Prometheus Metrics**
   - **Counters**: `signals_published_total{pair, strategy, side}`
   - **Gauges**: `active_positions{pair}`, `current_drawdown_pct`
   - **Histograms**: `signal_generation_latency_ms`, `redis_publish_latency_ms`
   - **Custom**: `kraken_ws_reconnects_total`, `risk_filter_rejections_total{reason}`

4. **Metrics Endpoint**
   - Expose `/metrics` endpoint (Prometheus scrape format)
   - Update frequency: real-time (on signal publish)
   - Port: 8000 (configurable)

5. **Alerting** (integration with external systems)
   - Critical: WebSocket down > 5 min → PagerDuty
   - Warning: Drawdown > -3% → Slack
   - Info: Daily performance summary → Email

**Configuration:**
```yaml
logging:
  level: INFO
  format: json
  destination: ["stdout", "file"]
  file:
    path: "logs/crypto_ai_bot.log"
    max_size_mb: 100
    retention_days: 7

monitoring:
  metrics_port: 8000
  prometheus:
    enabled: true
  alerts:
    pagerduty:
      enabled: true
      severity_critical: ["websocket_down"]
    slack:
      enabled: true
      severity_warning: ["drawdown_warning"]
```

### I. Crash Recovery

**Responsibility:**
Recover gracefully from crashes, restarts, and transient failures.

**Requirements:**

1. **Graceful Shutdown**
   - Handle SIGTERM, SIGINT signals
   - Close WebSocket connections cleanly
   - Flush pending Redis publishes
   - Log shutdown reason
   - Timeout: 30 seconds (force exit after)

2. **State Persistence**
   - Store active positions in Redis: `state:positions:{pair}`
   - Store regime labels in Redis: `state:regime:{pair}`
   - TTL: 24 hours (auto-expire stale state)

3. **Restart Recovery**
   - On startup, load state from Redis
   - Reconcile positions (verify against Kraken API if live)
   - Re-subscribe to WebSocket feeds
   - Mark health check healthy only after recovery complete

4. **Failure Modes**
   - Transient Redis failure: queue publishes in memory (max 1000), retry
   - Transient Kraken failure: serve cached data, mark stale
   - Persistent failure (> 5 min): mark unhealthy, alert

**Configuration:**
```yaml
crash_recovery:
  graceful_shutdown_timeout_sec: 30
  state_persistence:
    enabled: true
    redis_prefix: "state:"
    ttl_hours: 24
  restart:
    load_state_on_startup: true
    reconcile_positions: true  # only for live mode
```

---

## Signal Schema Specification

All signals published to Redis must conform to the following JSON schema. This is the **canonical schema** shared across all 3 repos (bot, API, UI).

### Signal Schema v1.0

```json
{
  "signal_id": "string (UUID v4)",
  "timestamp": "string (ISO8601 UTC, e.g., 2025-11-14T12:34:56.789Z)",
  "pair": "string (Kraken format, e.g., BTC/USD)",
  "side": "string (enum: LONG, SHORT)",
  "strategy": "string (enum: SCALPER, TREND, MEAN_REVERSION, BREAKOUT)",
  "regime": "string (enum: TRENDING_UP, TRENDING_DOWN, RANGING, VOLATILE)",
  "entry_price": "number (float, USD)",
  "take_profit": "number (float, USD)",
  "stop_loss": "number (float, USD)",
  "position_size_usd": "number (float, USD, nominal size)",
  "confidence": "number (float, 0.0 - 1.0)",
  "risk_reward_ratio": "number (float, e.g., 2.5)",
  "indicators": {
    "rsi_14": "number (float, 0-100)",
    "macd_signal": "string (enum: BULLISH, BEARISH, NEUTRAL)",
    "atr_14": "number (float, USD)",
    "volume_ratio": "number (float, current/average)"
  },
  "metadata": {
    "model_version": "string (e.g., v2.1.0)",
    "backtest_sharpe": "number (float, Sharpe ratio from validation)",
    "latency_ms": "number (int, generation time in ms)"
  }
}
```

### Example Signal

```json
{
  "signal_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "timestamp": "2025-11-14T18:45:23.456Z",
  "pair": "BTC/USD",
  "side": "LONG",
  "strategy": "SCALPER",
  "regime": "TRENDING_UP",
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
  },
  "metadata": {
    "model_version": "v2.1.0",
    "backtest_sharpe": 1.85,
    "latency_ms": 127
  }
}
```

### Schema Validation

**Pydantic Model:**
```python
from pydantic import BaseModel, Field
from enum import Enum
from datetime import datetime
from uuid import UUID

class Side(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"

class Strategy(str, Enum):
    SCALPER = "SCALPER"
    TREND = "TREND"
    MEAN_REVERSION = "MEAN_REVERSION"
    BREAKOUT = "BREAKOUT"

class Regime(str, Enum):
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGING = "RANGING"
    VOLATILE = "VOLATILE"

class MACDSignal(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"

class Indicators(BaseModel):
    rsi_14: float = Field(ge=0, le=100)
    macd_signal: MACDSignal
    atr_14: float = Field(gt=0)
    volume_ratio: float = Field(gt=0)

class Metadata(BaseModel):
    model_version: str
    backtest_sharpe: float
    latency_ms: int = Field(ge=0)

class TradingSignal(BaseModel):
    signal_id: UUID
    timestamp: datetime
    pair: str
    side: Side
    strategy: Strategy
    regime: Regime
    entry_price: float = Field(gt=0)
    take_profit: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    position_size_usd: float = Field(gt=0, le=2000)
    confidence: float = Field(ge=0.0, le=1.0)
    risk_reward_ratio: float = Field(gt=0)
    indicators: Indicators
    metadata: Metadata
```

### Publishing Contract

- **Stream**: `signals:paper` (paper) or `signals:live` (live)
- **Message ID**: Use `signal_id` for idempotency
- **Encoding**: JSON (UTF-8)
- **Validation**: Always validate with Pydantic before XADD
- **Error Handling**: Log validation failures, emit metric `signal_schema_errors_total`

---

## Data Integrity Requirements

### 1. Timestamp Ordering

**Requirement:**
All signals must have monotonically increasing timestamps (server-side clock).

**Implementation:**
- Use `datetime.now(timezone.utc)` for timestamp generation
- Never backdate signals
- Reject signals with timestamps > 5s in the future (clock skew protection)
- Redis Streams preserve insertion order (XADD guarantees)

**Validation:**
```python
def validate_timestamp(signal: TradingSignal) -> bool:
    now = datetime.now(timezone.utc)
    delta = abs((signal.timestamp - now).total_seconds())
    if delta > 5:
        logger.error(f"Signal timestamp skew: {delta}s")
        return False
    return True
```

### 2. Deduplication

**Requirement:**
No duplicate signals (same signal_id published twice).

**Implementation:**
- Generate `signal_id` as UUID v4
- Use as Redis message ID in XADD
- Redis automatically rejects duplicate IDs
- Emit metric on duplicate attempt: `signal_duplicates_rejected_total`

### 3. Sequence Number Enforcement

**Requirement:**
Detect gaps in WebSocket message sequences.

**Implementation:**
- Track last sequence number per channel: `last_seq[channel]`
- On new message, check: `new_seq == last_seq + 1`
- If gap detected, log warning, emit metric: `kraken_ws_message_gaps_total`
- Do not halt system (network reordering is possible), but alert if > 10 gaps/hour

### 4. Checksums (Optional for v1)

**Requirement:**
Verify message integrity (detect corruption).

**Implementation:**
- Compute SHA256 hash of signal JSON
- Store in `metadata.checksum` field
- API can verify on receipt

### 5. Idempotency

**Requirement:**
Publishing the same signal multiple times has no adverse effect.

**Implementation:**
- Use `signal_id` as Redis message ID
- Redis XADD with explicit ID rejects duplicates
- Downstream consumers can safely re-process messages

### 6. MAXLEN Trimming

**Requirement:**
Prevent unbounded Redis stream growth.

**Implementation:**
- Set MAXLEN=10,000 on all streams
- Use approximate trimming: `XADD ... MAXLEN ~ 10000`
- Trim older messages automatically
- API must archive signals if long-term storage needed

**Configuration:**
```yaml
redis:
  streams:
    maxlen: 10000
    trim_strategy: "approximate"  # ~, faster than exact
```

---

## Risk Management Requirements

### 1. Spread Limits

**Requirement:**
Only trade in liquid markets (tight bid-ask spread).

**Implementation:**
- Fetch current spread from Kraken `spread` channel
- Calculate spread %: `(ask - bid) / mid * 100`
- Reject signal if spread > 0.5%
- Emit metric: `risk_filter_rejections_total{reason="wide_spread"}`

**Code:**
```python
def check_spread(pair: str, max_spread_pct: float = 0.5) -> bool:
    spread_data = get_latest_spread(pair)
    spread_pct = (spread_data['ask'] - spread_data['bid']) / spread_data['mid'] * 100
    if spread_pct > max_spread_pct:
        logger.warning(f"Spread too wide: {spread_pct:.2f}% > {max_spread_pct}%")
        return False
    return True
```

### 2. Volatility Limits

**Requirement:**
Reduce position sizes during high volatility.

**Implementation:**
- Calculate ATR (14-period) on 5m candles
- Track 30-day ATR average
- If `current_ATR > 3.0 * avg_ATR`, reduce size by 50%
- If `current_ATR > 5.0 * avg_ATR`, halt new signals

**Code:**
```python
def volatility_adjustment(base_size: float, atr: float, avg_atr: float) -> float:
    ratio = atr / avg_atr
    if ratio > 5.0:
        return 0.0  # Halt
    elif ratio > 3.0:
        return base_size * 0.5  # Reduce
    else:
        return base_size
```

### 3. Daily Drawdown

**Requirement:**
Circuit breaker on daily losses.

**Implementation:**
- Track P&L from midnight UTC
- If daily P&L < -5%, halt new signals until next day
- Log event: `Daily drawdown limit reached: -5.2%`
- Emit metric: `circuit_breaker_triggered{reason="daily_drawdown"}`

### 4. Position Sizing

**Requirement:**
Risk-adjusted position sizing based on confidence and volatility.

**Implementation:**
```python
def calculate_position_size(
    base_size: float,
    confidence: float,
    atr: float,
    avg_atr: float,
    max_size: float = 2000.0
) -> float:
    # Volatility adjustment
    vol_adjustment = avg_atr / atr if atr > 0 else 1.0
    # Confidence scaling
    size = base_size * confidence * vol_adjustment
    # Cap at max
    return min(size, max_size)
```

### 5. Max Loss Streak

**Requirement:**
Pause strategy after consecutive losses.

**Implementation:**
- Track per-strategy loss count
- Reset on win
- After 3 losses: reduce allocation by 50%
- After 5 losses: pause strategy, manual review required

**Code:**
```python
class LossStreakTracker:
    def __init__(self, warn_threshold=3, pause_threshold=5):
        self.streaks = {}  # {strategy: count}
        self.warn_threshold = warn_threshold
        self.pause_threshold = pause_threshold

    def record_trade(self, strategy: str, profit: float):
        if profit < 0:
            self.streaks[strategy] = self.streaks.get(strategy, 0) + 1
        else:
            self.streaks[strategy] = 0

        count = self.streaks[strategy]
        if count >= self.pause_threshold:
            logger.critical(f"Strategy {strategy} paused: {count} losses")
            return "PAUSED"
        elif count >= self.warn_threshold:
            logger.warning(f"Strategy {strategy} loss streak: {count}")
            return "REDUCED"
        return "ACTIVE"
```

---

## Machine Learning Requirements

### 1. Model Transparency

**Requirement:**
Every ML prediction must be explainable (no black boxes).

**Implementation:**
- Log feature importance for every prediction
- Store in `metadata.feature_importance` (top 5 features)
- Use SHAP values for deep learning models
- Publish to `events:bus` stream for auditing

**Example:**
```json
{
  "model": "regime_detector",
  "prediction": "TRENDING_UP",
  "confidence": 0.78,
  "feature_importance": {
    "adx_14": 0.35,
    "price_sma_ratio": 0.28,
    "atr_14": 0.18,
    "volume_ratio": 0.12,
    "bb_width": 0.07
  }
}
```

### 2. Feature Dictionary

**Requirement:**
Maintain a canonical list of all ML features.

**Implementation:**
- Document in `docs/ML_FEATURES.md`
- Include: feature name, formula, purpose, expected range
- Version control (update on feature changes)

**Example:**
```markdown
| Feature | Formula | Purpose | Range |
|---------|---------|---------|-------|
| rsi_14 | RSI(close, 14) | Overbought/oversold | 0-100 |
| adx_14 | ADX(high, low, close, 14) | Trend strength | 0-100 |
| atr_14 | ATR(high, low, close, 14) | Volatility | > 0 |
| volume_ratio | volume / SMA(volume, 20) | Volume surge | > 0 |
```

### 3. Training Methodology

**Requirement:**
Document and automate model training.

**Implementation:**
- Training script: `scripts/train_predictor_v2.py`
- Data split: 70% train, 15% validation, 15% test
- Cross-validation: 5-fold time-series split
- Hyperparameter tuning: Grid search or Bayesian optimization
- Artifact storage: `models/` directory + version tags

**Training Pipeline:**
```bash
# Weekly retraining (Sunday 00:00 UTC)
python scripts/train_predictor_v2.py \
  --model regime_detector \
  --data-period 365 \
  --validation-split 0.15 \
  --test-split 0.15 \
  --output models/regime_detector_v2.2.pkl
```

### 4. Retraining Schedule

**Requirement:**
Regular model updates to prevent drift.

**Implementation:**
- Schedule: Weekly (Sunday 00:00 UTC)
- Trigger: Cron job on Fly.io or external scheduler
- Validation: Compare new model vs old on test set
- Promotion: Deploy only if new model improves accuracy by ≥ 2%
- Rollback: Keep last 3 model versions for quick revert

### 5. Validation Metrics

**Requirement:**
Track model performance over time.

**Implementation:**
- Metrics: Accuracy, Precision, Recall, F1, ROC-AUC
- Per-regime breakdown (e.g., accuracy for TRENDING_UP vs RANGING)
- Log to `monitoring/model_validation.log`
- Emit Prometheus metrics: `model_accuracy{model, regime}`

**Acceptance Thresholds:**
- Accuracy: ≥ 65%
- Precision: ≥ 60%
- Recall: ≥ 60%
- F1: ≥ 0.60

### 6. Ensemble + Confidence Weighting

**Requirement:**
Combine multiple models for robustness.

**Implementation:**
- Ensemble: Random Forest (60%) + LSTM (40%)
- Weighting: Based on recent accuracy (last 100 predictions)
- Confidence score: Agreement metric (if both models agree, confidence = 0.9; if disagree, confidence = 0.5)

**Code:**
```python
def ensemble_predict(rf_pred, lstm_pred, rf_weight=0.6, lstm_weight=0.4):
    # Weighted voting
    weighted_pred = rf_weight * rf_pred + lstm_weight * lstm_pred
    regime = threshold(weighted_pred)

    # Confidence from agreement
    if rf_pred == lstm_pred:
        confidence = 0.9
    else:
        confidence = 0.5

    return regime, confidence
```

### 7. Market Regime Detection

**Requirement:**
Classify market state to select appropriate strategies.

**Implementation:**
- Regimes: TRENDING_UP, TRENDING_DOWN, RANGING, VOLATILE
- Detection frequency: Every 5 minutes
- Strategies enabled per regime:
  - TRENDING_UP: Trend (high), Breakout (medium), Scalper (low)
  - TRENDING_DOWN: Mean Reversion (high), Trend (medium)
  - RANGING: Mean Reversion (high), Scalper (high), Breakout (low)
  - VOLATILE: Scalper (low), all others disabled

---

## Reliability & DevOps Requirements

### 1. Reconnection Behavior

**Requirement:**
Automatic recovery from WebSocket/Redis disconnections.

**Implementation:**
- **WebSocket Reconnection:**
  - Exponential backoff: 1s, 2s, 4s, 8s, 16s, 32s, 60s (max)
  - Jitter: ±20% randomization to avoid thundering herd
  - Max attempts: 10
  - After 10 failures: mark unhealthy, alert PagerDuty

- **Redis Reconnection:**
  - Built-in redis-py retry logic (3 attempts)
  - Connection pool auto-reconnect
  - On failure: queue messages in memory (max 1000), retry every 5s

**Code:**
```python
async def reconnect_with_backoff(connect_fn, max_attempts=10):
    for attempt in range(max_attempts):
        backoff = min(2 ** attempt, 60)  # Cap at 60s
        jitter = random.uniform(-0.2 * backoff, 0.2 * backoff)
        wait_time = backoff + jitter

        logger.info(f"Reconnect attempt {attempt + 1}/{max_attempts} in {wait_time:.1f}s")
        await asyncio.sleep(wait_time)

        try:
            await connect_fn()
            logger.info("Reconnection successful")
            return True
        except Exception as e:
            logger.error(f"Reconnect failed: {e}")

    logger.critical("Max reconnect attempts exceeded")
    return False
```

### 2. Fly.io-Compatible Health Pings

**Requirement:**
Expose health check endpoint for Fly.io orchestration.

**Implementation:**
- Endpoint: `GET /health`
- Port: 8080 (configurable)
- Response: JSON `{"status": "healthy", "uptime_sec": 12345, "last_signal_sec_ago": 45}`
- Unhealthy conditions:
  - WebSocket disconnected > 2 min
  - Redis unavailable > 1 min
  - No signals published in last 10 min (during market hours)

**fly.toml:**
```toml
[http_service]
  internal_port = 8080
  force_https = true

[[services.http_checks]]
  interval = "30s"
  timeout = "5s"
  grace_period = "10s"
  method = "GET"
  path = "/health"
```

**Implementation:**
```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
def health_check():
    status = "healthy"
    issues = []

    if not kraken_ws_connected():
        issues.append("kraken_ws_down")
        status = "unhealthy"

    if not redis_available():
        issues.append("redis_unavailable")
        status = "unhealthy"

    last_signal_age = time.time() - last_signal_timestamp()
    if last_signal_age > 600 and is_market_hours():
        issues.append("stale_signals")
        status = "degraded"

    return {
        "status": status,
        "uptime_sec": time.time() - startup_time,
        "last_signal_sec_ago": last_signal_age,
        "issues": issues
    }
```

### 3. Prometheus Metrics

**Requirement:**
Expose operational metrics for Grafana dashboards.

**Implementation:**
- **Endpoint**: `GET /metrics` (port 8000)
- **Format**: Prometheus text format
- **Update**: Real-time (on event)

**Key Metrics:**
```python
from prometheus_client import Counter, Gauge, Histogram

# Counters
signals_published_total = Counter('signals_published_total', 'Total signals published', ['pair', 'strategy', 'side'])
risk_rejections_total = Counter('risk_rejections_total', 'Signals rejected by risk filters', ['reason'])
kraken_ws_reconnects_total = Counter('kraken_ws_reconnects_total', 'WebSocket reconnection attempts')

# Gauges
active_positions = Gauge('active_positions', 'Current open positions', ['pair'])
current_drawdown_pct = Gauge('current_drawdown_pct', 'Current drawdown %')
kraken_ws_latency_ms = Gauge('kraken_ws_latency_ms', 'WebSocket message latency', ['quantile'])

# Histograms
signal_generation_latency_ms = Histogram('signal_generation_latency_ms', 'Signal generation time')
redis_publish_latency_ms = Histogram('redis_publish_latency_ms', 'Redis publish time')
```

### 4. Structured JSON Logs

**Requirement:**
Machine-parseable logs for aggregation (Datadog, CloudWatch, etc.).

**Implementation:**
```python
import logging
import json
from datetime import datetime

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_obj = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "component": record.name,
            "message": record.getMessage(),
            "context": getattr(record, 'context', {})
        }
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_obj)

# Usage
logger = logging.getLogger("signal_generator")
logger.info("Signal published", extra={"context": {"pair": "BTC/USD", "signal_id": "abc123"}})
```

**Output:**
```json
{
  "timestamp": "2025-11-14T18:45:23.456Z",
  "level": "INFO",
  "component": "signal_generator",
  "message": "Signal published",
  "context": {
    "pair": "BTC/USD",
    "signal_id": "abc123"
  }
}
```

### 5. Graceful Shutdown & Restart

**Requirement:**
Clean shutdown on SIGTERM (Fly.io deployments).

**Implementation:**
```python
import signal
import asyncio

shutdown_event = asyncio.Event()

def handle_shutdown(sig, frame):
    logger.info(f"Received signal {sig}, initiating graceful shutdown...")
    shutdown_event.set()

signal.signal(signal.SIGTERM, handle_shutdown)
signal.signal(signal.SIGINT, handle_shutdown)

async def main():
    # Start services
    await kraken_ws.connect()
    await redis_client.connect()

    # Run until shutdown
    await shutdown_event.wait()

    # Cleanup
    logger.info("Closing WebSocket...")
    await kraken_ws.close()
    logger.info("Flushing Redis...")
    await redis_client.flush()
    logger.info("Shutdown complete")
```

**Timeout:**
- Max shutdown time: 30 seconds
- After 30s, force exit (kill -9)

---

## Testing Requirements

### 1. Unit Tests

**Requirement:**
Test individual components in isolation.

**Coverage Targets:**
- Core logic (agents, strategies, risk): 90%
- Utility functions: 80%
- Configuration loaders: 70%

**Examples:**
```python
# tests/agents/test_regime_detector.py
def test_regime_detector_trending_up():
    data = create_trending_data()  # Mock OHLCV
    regime = detect_regime(data)
    assert regime == "TRENDING_UP"

# tests/risk/test_spread_filter.py
def test_spread_filter_rejects_wide_spread():
    spread_data = {"bid": 100, "ask": 101, "mid": 100.5}  # 1% spread
    assert not check_spread(spread_data, max_spread_pct=0.5)
```

**Tools:**
- Framework: pytest
- Coverage: pytest-cov
- Mocking: pytest-mock, unittest.mock

**Run:**
```bash
pytest tests/unit/ --cov=agents --cov=strategies --cov-report=html
```

### 2. Integration Tests

**Requirement:**
Test interactions between components (WebSocket, Redis, health checks).

**Examples:**
```python
# tests/integration/test_redis_publish.py
@pytest.mark.asyncio
async def test_signal_publish_to_redis():
    redis_client = RedisCloudClient(url=TEST_REDIS_URL)
    signal = create_test_signal()

    await publish_signal(redis_client, signal)

    # Verify in stream
    messages = await redis_client.xread({"signals:paper": "0"}, count=1)
    assert len(messages) == 1
    assert messages[0]["signal_id"] == signal.signal_id

# tests/integration/test_kraken_ws.py
@pytest.mark.asyncio
async def test_kraken_ws_reconnect():
    ws = KrakenWebSocket()
    await ws.connect()

    # Simulate disconnect
    await ws.disconnect()

    # Should auto-reconnect
    await asyncio.sleep(2)
    assert ws.is_connected()
```

### 3. End-to-End Tests (Simulating Fake WS Feeds)

**Requirement:**
Test full signal lifecycle from WebSocket → Redis.

**Implementation:**
- Use mock WebSocket server (returns fake Kraken messages)
- Run full bot pipeline
- Verify signals published to Redis
- Check schema compliance

**Example:**
```python
# tests/e2e/test_signal_pipeline.py
@pytest.mark.asyncio
async def test_full_signal_pipeline():
    # Start mock Kraken WS server
    mock_ws_server = MockKrakenWS()
    await mock_ws_server.start()

    # Start bot (pointing to mock server)
    bot = CryptoAIBot(kraken_url=mock_ws_server.url)
    await bot.start()

    # Inject fake trade data
    await mock_ws_server.send_trade({"pair": "BTC/USD", "price": 43250, "volume": 1.5})

    # Wait for signal generation
    await asyncio.sleep(1)

    # Verify signal in Redis
    redis_client = RedisCloudClient()
    signals = await redis_client.xread({"signals:paper": "0"}, count=1)
    assert len(signals) == 1

    # Validate schema
    signal = TradingSignal(**signals[0])
    assert signal.pair == "BTC/USD"
    assert signal.confidence >= 0.6
```

### 4. Regression Tests

**Requirement:**
Prevent reintroduction of fixed bugs.

**Implementation:**
- Tag tests with `@pytest.mark.regression`
- Run on every CI build
- Covers historical bugs (e.g., schema drift, reconnection failures)

**Example:**
```python
@pytest.mark.regression
def test_signal_schema_no_drift():
    """Regression: Ensure signal schema matches API expectations (issue #42)"""
    signal = create_test_signal()
    serialized = signal.json()

    # API expects these exact field names
    assert "signal_id" in serialized
    assert "timestamp" in serialized
    assert "entry_price" in serialized  # Not "entryPrice" (camelCase)
```

### 5. Load Tests

**Requirement:**
Verify system handles production-scale traffic.

**Scenarios:**
- 100 messages/sec from Kraken WS
- 50 signals/sec published to Redis
- 10 concurrent strategies running

**Tools:**
- Locust (HTTP load testing)
- Custom async script for WebSocket/Redis load

**Example:**
```python
# tests/load/test_redis_throughput.py
@pytest.mark.asyncio
async def test_redis_publish_throughput():
    redis_client = RedisCloudClient()
    signals = [create_test_signal() for _ in range(1000)]

    start = time.time()

    tasks = [publish_signal(redis_client, s) for s in signals]
    await asyncio.gather(*tasks)

    duration = time.time() - start
    throughput = 1000 / duration

    assert throughput >= 50  # At least 50 signals/sec
```

**Acceptance:**
- Throughput: ≥ 50 signals/sec
- P95 latency: ≤ 500ms
- Memory: < 500MB
- CPU: < 50% (single core)

---

## Documentation Requirements

### 1. METHODOLOGY.md

**Purpose:**
Explain the algorithmic foundation of signal generation.

**Contents:**
- Overview of trading approach (scalper, trend, mean reversion, breakout)
- Technical indicators used (RSI, MACD, ATR, etc.)
- Regime detection logic
- Position sizing formula
- Risk management rules
- Example walkthrough (from market data → signal)

**Location:** `docs/METHODOLOGY.md`

**Audience:** Engineers, investors, auditors

### 2. ARCHITECTURE.md

**Purpose:**
Describe system design and data flow.

**Contents:**
- High-level architecture diagram (Kraken → Bot → Redis → API → UI)
- Component responsibilities (agents, strategies, risk manager, etc.)
- Technology stack (Python, Redis, Kraken API, Prometheus)
- Data models (signal schema, position schema)
- Scalability considerations (horizontal scaling, Redis sharding)

**Location:** `docs/ARCHITECTURE.md`

**Audience:** Engineers, DevOps

### 3. RUNBOOK.md

**Purpose:**
Operational procedures for deployment, monitoring, incident response.

**Contents:**
- Deployment steps (Fly.io, environment setup)
- Environment variables (REDIS_URL, TRADING_MODE, etc.)
- Health check verification
- Common incidents and resolutions (e.g., WebSocket down, Redis timeout)
- Rollback procedure
- Performance tuning (scaling, Redis optimization)

**Location:** `docs/RUNBOOK.md`

**Audience:** DevOps, SRE, on-call engineers

### 4. SIGNAL_FLOW.md

**Purpose:**
Trace the end-to-end signal lifecycle.

**Contents:**
- Step-by-step flow diagram (market data → ingestion → analysis → risk check → publish)
- Timing breakdown (target latencies per stage)
- Error handling at each stage
- Example signal JSON at each stage
- Integration points with API and UI

**Location:** `docs/SIGNAL_FLOW.md`

**Audience:** Engineers, QA

---

## Deliverables for Claude Code

This section provides an actionable checklist for Claude Code to implement the requirements in this PRD.

### Phase 1: Foundation (Week 1-2)

- [ ] **Schema Validation**
  - [ ] Implement `TradingSignal` Pydantic model (Section 5)
  - [ ] Add schema validation tests
  - [ ] Integrate validation into Redis publish flow

- [ ] **WebSocket Reliability**
  - [ ] Implement exponential backoff reconnection (Section 4.A)
  - [ ] Add sequence number validation
  - [ ] Add timestamp freshness checks
  - [ ] Add deduplication logic

- [ ] **Redis Publishing**
  - [ ] Implement TLS connection to Redis Cloud (Section 4.B)
  - [ ] Add MAXLEN trimming (10,000)
  - [ ] Add publish retry logic (3 attempts)
  - [ ] Add idempotency (signal_id as message ID)

### Phase 2: Risk & ML (Week 3-4)

- [ ] **Risk Filters**
  - [ ] Implement spread limit check (Section 7.1)
  - [ ] Implement volatility adjustment (Section 7.2)
  - [ ] Implement daily drawdown circuit breaker (Section 7.3)
  - [ ] Implement position sizing logic (Section 7.4)
  - [ ] Implement loss streak tracking (Section 7.5)

- [ ] **Regime Detection**
  - [ ] Train regime detector model (Section 8)
  - [ ] Implement ensemble (RF + LSTM)
  - [ ] Add feature importance logging
  - [ ] Add validation metrics

### Phase 3: Observability (Week 5)

- [ ] **Logging**
  - [ ] Implement structured JSON logging (Section 9.4)
  - [ ] Add log rotation (100MB, 7 days)
  - [ ] Add context fields (pair, signal_id, etc.)

- [ ] **Metrics**
  - [ ] Implement Prometheus endpoint (Section 9.3)
  - [ ] Add counters (signals_published_total, etc.)
  - [ ] Add gauges (active_positions, current_drawdown_pct)
  - [ ] Add histograms (signal_generation_latency_ms)

- [ ] **Health Checks**
  - [ ] Implement `/health` endpoint (Section 9.2)
  - [ ] Add Fly.io health check config in `fly.toml`
  - [ ] Add unhealthy conditions (WebSocket down, Redis unavailable, stale signals)

### Phase 4: Testing (Week 6)

- [ ] **Unit Tests**
  - [ ] Regime detector tests
  - [ ] Risk filter tests
  - [ ] Position sizing tests
  - [ ] Schema validation tests
  - [ ] Target: 80% coverage

- [ ] **Integration Tests**
  - [ ] Redis publish/subscribe tests
  - [ ] WebSocket reconnection tests
  - [ ] Health check tests

- [ ] **E2E Tests**
  - [ ] Mock Kraken WebSocket server
  - [ ] Full pipeline test (WS → Redis)
  - [ ] Schema compliance verification

### Phase 5: Documentation (Week 7)

- [ ] **Core Docs**
  - [ ] Write `METHODOLOGY.md`
  - [ ] Write `ARCHITECTURE.md`
  - [ ] Write `RUNBOOK.md`
  - [ ] Write `SIGNAL_FLOW.md`

- [ ] **Operational Docs**
  - [ ] Document environment variables (`.env.example`)
  - [ ] Document Redis setup (TLS cert installation)
  - [ ] Document Fly.io deployment steps

### Phase 6: Production Readiness (Week 8)

- [ ] **Performance Tuning**
  - [ ] Load test (50 signals/sec)
  - [ ] Latency optimization (P95 < 500ms)
  - [ ] Memory profiling (< 500MB)

- [ ] **Deployment**
  - [ ] Configure Fly.io (`fly.toml`)
  - [ ] Set environment variables (REDIS_URL, TRADING_MODE)
  - [ ] Deploy to staging
  - [ ] Run E2E tests on staging
  - [ ] Deploy to production

- [ ] **Monitoring Setup**
  - [ ] Configure Prometheus scraping
  - [ ] Create Grafana dashboards
  - [ ] Set up PagerDuty alerts (WebSocket down, circuit breaker)
  - [ ] Set up Slack notifications (drawdown warnings)

### Acceptance Criteria (Go/No-Go)

Before declaring Phase 6 complete, verify:

- [ ] 24hr uptime test passed (no crashes, no manual intervention)
- [ ] All tests passing (unit, integration, E2E)
- [ ] Test coverage ≥ 80%
- [ ] All 4 core docs written and reviewed
- [ ] Prometheus metrics exposed and scraped
- [ ] Health checks returning 200 OK
- [ ] Signals published to Redis and validated by API
- [ ] PnL tracking operational (signals → P&L attribution)
- [ ] Backtest results documented (Sharpe ≥ 1.5, Drawdown ≤ -15%)

---

## Environment Setup

### Conda Environment

**Environment Name:** `crypto-bot`

**Activation:**
```bash
conda activate crypto-bot
```

**Dependencies:** (install via `requirements.txt`)
```
redis[hiredis]==5.0.1
websockets==12.0
pydantic==2.5.0
fastapi==0.104.1
uvicorn==0.24.0
prometheus-client==0.19.0
pytest==7.4.3
pytest-asyncio==0.21.1
pytest-cov==4.1.0
```

### Redis Cloud Connection

**Connection String (URL-encoded):**
```
rediss://default:Salam78614%2A%2A%24%24@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818
```

**CLI Connection (for debugging):**
```bash
redis-cli -u redis://default:<PASSWORD>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 \
  --tls \
  --cacert C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem
```

**Environment Variable:**
```bash
# .env.paper
REDIS_URL=rediss://default:Salam78614**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818
REDIS_SSL=true
REDIS_SSL_CA_CERT=config/certs/redis_ca.pem
```

**Certificate Location:**
```
C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem
```

### Environment Variables (Reference)

```bash
# .env.paper (paper trading)
TRADING_MODE=paper
REDIS_URL=rediss://default:Salam78614**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818
REDIS_SSL=true
REDIS_SSL_CA_CERT=config/certs/redis_ca.pem
ENABLE_5S_BARS=false
SCALPER_MAX_TRADES_PER_MINUTE=4
LATENCY_MS_MAX=100.0
ENABLE_LATENCY_TRACKING=true
LOG_LEVEL=INFO
TRADING_PAIRS=BTC/USD,ETH/USD,SOL/USD,MATIC/USD,LINK/USD
TIMEFRAMES=15s,1m,5m
```

```bash
# .env.live (production)
TRADING_MODE=live
REDIS_URL=rediss://default:Salam78614**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818
REDIS_SSL=true
REDIS_SSL_CA_CERT=config/certs/redis_ca.pem
ENABLE_TRADING=true
LIVE_TRADING_CONFIRMATION=I_UNDERSTAND_REAL_MONEY
KRAKEN_API_KEY=${KRAKEN_API_KEY}
KRAKEN_SECRET=${KRAKEN_SECRET}
LOG_LEVEL=INFO
```

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0.0 | 2025-11-14 | Product & Engineering | Initial authoritative PRD |

---

## Appendix A: Glossary

- **Signal**: A trading recommendation (long/short, entry/exit prices, confidence)
- **Regime**: Market state classification (trending, ranging, volatile)
- **Spread**: Bid-ask spread (width between buy and sell prices)
- **ATR**: Average True Range (volatility indicator)
- **Drawdown**: Peak-to-trough decline in portfolio value
- **Sharpe Ratio**: Risk-adjusted return metric (higher = better)
- **MAXLEN**: Redis Streams max length (auto-trims old messages)
- **XADD**: Redis command to add message to stream
- **Idempotency**: Publishing the same message multiple times has no side effect

---

## Appendix B: Redis Streams Contract

### Stream Names

| Stream | Purpose | Producer | Consumer | MAXLEN | TTL |
|--------|---------|----------|----------|--------|-----|
| `signals:paper` | Paper trading signals | crypto-ai-bot | signals-api | 10,000 | 7 days |
| `signals:live` | Live trading signals | crypto-ai-bot | signals-api | 10,000 | 7 days |
| `pnl:signals` | P&L attribution | crypto-ai-bot | signals-api | 50,000 | 30 days |
| `events:bus` | System events | crypto-ai-bot | signals-api, monitoring | 5,000 | 7 days |

### Message Format (Redis Streams)

```
XADD signals:paper <signal_id> field1 value1 field2 value2 ...
```

**Example:**
```
XADD signals:paper a1b2c3d4-e5f6-7890-abcd-ef1234567890 \
  timestamp "2025-11-14T18:45:23.456Z" \
  pair "BTC/USD" \
  side "LONG" \
  strategy "SCALPER" \
  entry_price "43250.50" \
  confidence "0.72"
```

---

## Appendix C: Success Metrics Dashboard

### Real-Time Metrics (Prometheus)

```promql
# Signal generation rate (per minute)
rate(signals_published_total[1m])

# P95 latency
histogram_quantile(0.95, signal_generation_latency_ms)

# Current drawdown
current_drawdown_pct

# Active positions
sum(active_positions) by (pair)

# Risk rejections (per hour)
rate(risk_rejections_total[1h])
```

### Daily Reports

- Total signals published
- Win rate (profitable signals / total)
- P&L (daily, weekly, monthly)
- Sharpe ratio (rolling 30 days)
- Max drawdown (rolling 30 days)
- Strategy attribution (which strategy contributed most to P&L)

---

**END OF PRD-001**

---

This document is the **single source of truth** for the crypto-ai-bot repository. All development, testing, deployment, and documentation work must align with the requirements, specifications, and standards defined herein.

For questions or clarifications, contact: Product & Engineering Team

**Approval:** Awaiting stakeholder sign-off
**Next Review Date:** 2025-12-14
