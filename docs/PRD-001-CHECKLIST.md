# PRD-001 Implementation Checklist

**PRD Reference:** [PRD-001: Crypto AI Bot - Core Intelligence Engine](PRD-001-CRYPTO-AI-BOT.md)

**Environment:**
- Conda env: `crypto-bot`
- Redis Cloud: `rediss://default:Salam78614%2A%2A%24%24@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818`
- Redis CA Cert: `config/certs/redis_ca.pem`

**Status:** In Progress
**Last Updated:** 2025-11-14

---

## Progress Summary

- [ ] **Data Ingestion** (0/22 complete)
- [ ] **Redis Streams Publishing** (0/18 complete)
- [ ] **Multi-Agent ML Engine** (0/20 complete)
- [ ] **Risk Engine** (0/16 complete)
- [ ] **Configuration System** (0/12 complete)
- [ ] **Logging & Metrics** (0/15 complete)
- [ ] **Testing** (0/24 complete)
- [ ] **Documentation** (0/12 complete)

**Total:** 0/139 requirements complete

---

## 1. Data Ingestion (Kraken WebSocket)

### Connection Management (4/4)
- [ ] Subscribe to Kraken WS feeds: ticker, spread, trade, book (L2)
- [ ] Support configurable pairs: BTC/USD, ETH/USD, SOL/USD, MATIC/USD, LINK/USD
- [ ] Implement heartbeat monitoring (PING/PONG every 30s)
- [ ] Auto-reconnect on disconnect with exponential backoff (1s, 2s, 4s, 8s, ...max 60s)

### Reconnection Logic (6/6)
- [ ] Implement exponential backoff with jitter for reconnection
- [ ] Max 10 reconnect attempts before marking unhealthy
- [ ] Log reconnection attempts with ERROR level
- [ ] Emit Prometheus metric: `kraken_ws_reconnects_total`
- [ ] Mark health check unhealthy during sustained failures (> 2 min)
- [ ] Graceful degradation: serve cached data if available

### Data Validation (6/6)
- [ ] Verify sequence numbers to detect message loss
- [ ] Implement timestamp freshness check (reject data > 5s old)
- [ ] Validate Kraken response format (schema validation)
- [ ] Implement deduplication (cache last 100 message IDs)
- [ ] Log all connection errors at ERROR level
- [ ] Emit Prometheus metric: `kraken_ws_errors_total{error_type}`

### Performance Requirements (6/6)
- [ ] P95 latency from Kraken → Redis < 50ms
- [ ] Handle 100+ messages/sec per pair
- [ ] Memory bound: max 100MB for WebSocket buffers
- [ ] Measure and log latency per message
- [ ] Implement backpressure if buffer exceeds 90% capacity
- [ ] Add latency metrics to Prometheus histogram

---

## 2. Redis Streams Publishing

### Connection Management (6/6)
- [ ] Connect to Redis Cloud via TLS (rediss://)
- [ ] Use connection pooling (max 10 connections)
- [ ] Load credentials from environment variable: `REDIS_URL`
- [ ] Load certificate from: `config/certs/redis_ca.pem`
- [ ] Implement health check integration (PING every 60s)
- [ ] Handle TLS certificate verification

### Stream Configuration (6/6)
- [ ] Configure signal stream: `signals:paper` for paper trading
- [ ] Configure signal stream: `signals:live` for production
- [ ] Configure PnL stream: `pnl:signals`
- [ ] Configure events stream: `events:bus`
- [ ] Set MAXLEN: 10,000 messages per stream (approximate trimming)
- [ ] Verify TTL: 7 days (Redis Cloud auto-expiration)

### Publishing Guarantees (6/6)
- [ ] Implement idempotency: use `signal_id` as message ID
- [ ] Ensure atomicity: all signal fields published in single XADD
- [ ] Validate schema with Pydantic before publishing
- [ ] Implement retry logic: 3 attempts with exponential backoff
- [ ] Log validation failures and emit metric: `signal_schema_errors_total`
- [ ] Handle duplicate message ID rejections gracefully

---

## 3. Multi-Agent ML Engine

### Agent Architecture (4/4)
- [ ] Implement Regime Detector agent (classify market state)
- [ ] Implement Signal Analyst agent (generate trade ideas)
- [ ] Implement Risk Manager agent (validate signals against limits)
- [ ] Implement Position Manager agent (track positions, manage exits)

### Regime Detector (8/8)
- [ ] Accept input: 1-hour OHLCV data
- [ ] Output regime label: TRENDING_UP, TRENDING_DOWN, RANGING, VOLATILE
- [ ] Implement ensemble model (Random Forest + LSTM)
- [ ] Schedule weekly retraining (Sunday 00:00 UTC via cron)
- [ ] Use 70/30 train/test split for validation
- [ ] Achieve min 65% accuracy on test set
- [ ] Extract features: ADX, ATR, Bollinger Band width, volume profile
- [ ] Store model at: `models/regime_rf_lstm_ensemble.pkl`

### Signal Analyst (8/8)
- [ ] Accept input: 5m OHLCV + current regime + order book snapshot
- [ ] Output signal: side, entry_price, take_profit, stop_loss, confidence
- [ ] Implement strategies: Scalper, Trend, Mean Reversion, Breakout
- [ ] Weight allocation by recent performance (last 100 trades)
- [ ] Reject signals with confidence < 0.6 (60%)
- [ ] Calculate risk-reward ratio for each signal
- [ ] Include indicators: RSI, MACD, ATR, volume ratio
- [ ] Add metadata: model version, backtest Sharpe, latency

---

## 4. Risk Engine

### Pre-Signal Filters (4/4)
- [ ] Reject signals if spread > 0.5% (illiquid markets)
- [ ] Reject signals if volatility (ATR) > 3x daily average
- [ ] Reject signals if daily drawdown > -5% (circuit breaker)
- [ ] Reject signals if position concentration > 40% of portfolio

### Position Sizing (6/6)
- [ ] Set base size: $100 per signal
- [ ] Implement volatility adjustment: size = base_size / (ATR / ATR_avg)
- [ ] Implement confidence scaling: size *= signal_confidence
- [ ] Enforce max size per position: $2,000
- [ ] Enforce max total exposure: $10,000
- [ ] Calculate and log position size for each signal

### Drawdown Control (3/3)
- [ ] Daily max drawdown: -5% (halt new signals until next day)
- [ ] Weekly max drawdown: -10% (reduce position sizes by 50%)
- [ ] Monthly max drawdown: -20% (pause system, alert engineer)

### Loss Streak Management (3/3)
- [ ] Track consecutive losses per strategy
- [ ] After 3 losses: reduce allocation by 50%
- [ ] After 5 losses: pause strategy, trigger review

---

## 5. Configuration System

### Configuration Files (4/4)
- [ ] Create base config: `config/settings.yaml`
- [ ] Create environment overrides: `.env.paper`, `.env.live`
- [ ] Create strategy configs: `config/strategies/*.yaml`
- [ ] Create risk configs: `config/risk/*.yaml`

### Environment Variables (4/4)
- [ ] Support `REDIS_URL` environment variable
- [ ] Support `TRADING_MODE` environment variable (paper/live)
- [ ] Support `LOG_LEVEL` environment variable
- [ ] Support `KRAKEN_API_KEY` and `KRAKEN_SECRET`

### Validation (4/4)
- [ ] Implement Pydantic models for all config sections
- [ ] Validate schema on load (fail fast on invalid config)
- [ ] Implement type checking (int, float, str, enum)
- [ ] Implement range validation (min/max values)

---

## 6. Logging & Metrics

### Structured Logging (5/5)
- [ ] Implement JSON logging format
- [ ] Include fields: timestamp, level, component, message, context
- [ ] Support levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
- [ ] Output to stdout (for Fly.io logs)
- [ ] Output to file: `logs/crypto_ai_bot.log`

### Log Rotation (3/3)
- [ ] Set max file size: 100MB
- [ ] Keep last 7 days of logs
- [ ] Compress old logs (gzip)

### Prometheus Metrics (7/7)
- [ ] Implement counter: `signals_published_total{pair, strategy, side}`
- [ ] Implement gauge: `active_positions{pair}`
- [ ] Implement gauge: `current_drawdown_pct`
- [ ] Implement histogram: `signal_generation_latency_ms`
- [ ] Implement histogram: `redis_publish_latency_ms`
- [ ] Implement counter: `kraken_ws_reconnects_total`
- [ ] Implement counter: `risk_filter_rejections_total{reason}`

---

## 7. Testing

### Unit Tests (8/8)
- [ ] Unit tests for Regime Detector (regime classification logic)
- [ ] Unit tests for Signal Analyst (signal generation logic)
- [ ] Unit tests for Risk Manager (spread filter, volatility filter, drawdown)
- [ ] Unit tests for Position Manager (position tracking, exits)
- [ ] Unit tests for Position Sizing (volatility adjustment, confidence scaling)
- [ ] Unit tests for Loss Streak Tracking (consecutive loss counting)
- [ ] Unit tests for Schema Validation (Pydantic models)
- [ ] Unit tests for Configuration Loading (YAML parsing, env vars)

### Integration Tests (8/8)
- [ ] Integration test: Redis connection with TLS
- [ ] Integration test: Redis publish/subscribe flow
- [ ] Integration test: Kraken WebSocket connection
- [ ] Integration test: Kraken WebSocket reconnection
- [ ] Integration test: Health check endpoints
- [ ] Integration test: Prometheus metrics endpoint
- [ ] Integration test: Schema validation on publish
- [ ] Integration test: Signal flow (generate → validate → publish)

### End-to-End Tests (4/4)
- [ ] E2E test: Full signal pipeline with mock Kraken WS
- [ ] E2E test: Regime detection → signal generation → risk filtering → publish
- [ ] E2E test: Reconnection behavior (simulate disconnect)
- [ ] E2E test: Graceful shutdown (SIGTERM handling)

### Regression Tests (2/2)
- [ ] Regression test: Schema drift detection (issue #42 - ensure field names match API)
- [ ] Regression test: Reconnection failures (ensure exponential backoff works)

### Load Tests (2/2)
- [ ] Load test: 100 messages/sec from Kraken WS
- [ ] Load test: 50 signals/sec published to Redis

---

## 8. Backtesting Validation

### Data Requirements (4/4)
- [ ] Historical OHLCV: 1 year (365 days)
- [ ] Trade execution simulation (slippage model: 5 bps)
- [ ] Fee calculation (Kraken: maker 16 bps, taker 26 bps)
- [ ] Realistic order fills (limit orders require depth check)

### Metrics Calculation (6/6)
- [ ] Calculate total return (%)
- [ ] Calculate Sharpe ratio
- [ ] Calculate max drawdown
- [ ] Calculate win rate
- [ ] Calculate profit factor (gross profit / gross loss)
- [ ] Calculate average trade duration

### Acceptance Criteria (5/5)
- [ ] Sharpe ≥ 1.5
- [ ] Drawdown ≤ -15%
- [ ] Win rate ≥ 45%
- [ ] Profit factor ≥ 1.3
- [ ] Min 200 trades in backtest period

### Automation (3/3)
- [ ] Run backtests in CI/CD on every strategy change
- [ ] Store results in `out/backtests/` directory
- [ ] Block deployment if backtest fails

---

## 9. Signal Schema

### Pydantic Models (10/10)
- [ ] Implement `Side` enum (LONG, SHORT)
- [ ] Implement `Strategy` enum (SCALPER, TREND, MEAN_REVERSION, BREAKOUT)
- [ ] Implement `Regime` enum (TRENDING_UP, TRENDING_DOWN, RANGING, VOLATILE)
- [ ] Implement `MACDSignal` enum (BULLISH, BEARISH, NEUTRAL)
- [ ] Implement `Indicators` model (rsi_14, macd_signal, atr_14, volume_ratio)
- [ ] Implement `Metadata` model (model_version, backtest_sharpe, latency_ms)
- [ ] Implement `TradingSignal` model (all required fields)
- [ ] Validate signal_id as UUID v4
- [ ] Validate timestamp as ISO8601 UTC
- [ ] Validate confidence range: 0.0 - 1.0

### Schema Validation (4/4)
- [ ] Validate before every Redis publish
- [ ] Log validation failures
- [ ] Emit metric: `signal_schema_errors_total`
- [ ] Test schema against signals-api expectations

---

## 10. Data Integrity

### Timestamp Ordering (2/2)
- [ ] Use `datetime.now(timezone.utc)` for timestamp generation
- [ ] Reject signals with timestamps > 5s in the future (clock skew protection)

### Deduplication (2/2)
- [ ] Generate signal_id as UUID v4
- [ ] Use signal_id as Redis message ID (automatic deduplication)

### Sequence Number Enforcement (3/3)
- [ ] Track last sequence number per WebSocket channel
- [ ] Detect gaps: check if new_seq == last_seq + 1
- [ ] Emit metric: `kraken_ws_message_gaps_total` if gap detected

### Idempotency (2/2)
- [ ] Use signal_id as Redis XADD message ID
- [ ] Handle Redis duplicate ID rejection gracefully

### MAXLEN Trimming (2/2)
- [ ] Set MAXLEN=10,000 on all streams
- [ ] Use approximate trimming: `XADD ... MAXLEN ~ 10000`

---

## 11. Crash Recovery

### Graceful Shutdown (5/5)
- [ ] Handle SIGTERM signal
- [ ] Handle SIGINT signal
- [ ] Close WebSocket connections cleanly
- [ ] Flush pending Redis publishes
- [ ] Log shutdown reason

### State Persistence (3/3)
- [ ] Store active positions in Redis: `state:positions:{pair}`
- [ ] Store regime labels in Redis: `state:regime:{pair}`
- [ ] Set TTL: 24 hours (auto-expire stale state)

### Restart Recovery (4/4)
- [ ] On startup, load state from Redis
- [ ] Reconcile positions (verify against Kraken API if live mode)
- [ ] Re-subscribe to WebSocket feeds
- [ ] Mark health check healthy only after recovery complete

---

## 12. Health Checks & Monitoring

### Health Endpoints (3/3)
- [ ] Implement `GET /health` endpoint (JSON response)
- [ ] Return unhealthy if WebSocket disconnected > 2 min
- [ ] Return unhealthy if Redis unavailable > 1 min

### Fly.io Integration (2/2)
- [ ] Configure health check in `fly.toml`
- [ ] Health endpoint on port 8080

### Metrics Endpoint (2/2)
- [ ] Expose `GET /metrics` endpoint (Prometheus scrape format)
- [ ] Metrics endpoint on port 8000

---

## 13. Documentation

### Required Documentation Files (4/4)
- [ ] Write `METHODOLOGY.md` (algorithmic foundation)
- [ ] Write `ARCHITECTURE.md` (system design, data flow)
- [ ] Write `RUNBOOK.md` (deployment, monitoring, incident response)
- [ ] Write `SIGNAL_FLOW.md` (end-to-end signal lifecycle)

### Code Documentation (4/4)
- [ ] Docstrings for all public functions
- [ ] Docstrings for all classes
- [ ] Inline comments for complex logic
- [ ] README with quickstart instructions

### Configuration Documentation (2/2)
- [ ] Document all environment variables in `.env.example`
- [ ] Document all YAML config options in comments

### ML Documentation (2/2)
- [ ] Document feature dictionary (what inputs drive predictions)
- [ ] Document model retraining procedure

---

## 14. Performance & Reliability

### Success Criteria Validation (10/10)
- [ ] Verify uptime ≥ 99.5% (Fly.io health checks)
- [ ] Verify signal publish rate ≥ 10 signals/hour per pair
- [ ] Verify latency P50 ≤ 200ms
- [ ] Verify latency P95 ≤ 500ms
- [ ] Verify latency P99 ≤ 1000ms
- [ ] Verify schema compliance = 100%
- [ ] Verify WebSocket reconnects ≤ 5/day
- [ ] Verify test coverage ≥ 80%
- [ ] Verify PnL tracking = 100%
- [ ] Verify alert response time ≤ 5 min

---

## 15. Deployment & Operations

### Deployment Configuration (5/5)
- [ ] Create `fly.toml` with health checks
- [ ] Set auto-scaling rules (min 1, max 3 instances)
- [ ] Configure region: iad (US East, close to Redis Cloud)
- [ ] Set CORS origins for signals-api and signals-site
- [ ] Disable auto-stop for 24/7 availability

### Environment Setup (3/3)
- [ ] Create `.env.paper` for paper trading
- [ ] Create `.env.live` for production
- [ ] Create `.env.example` as template

### CI/CD Pipeline (4/4)
- [ ] Run unit tests on every commit
- [ ] Run integration tests on every commit
- [ ] Run backtests on strategy changes
- [ ] Block deployment if tests fail

---

## 16. Risk Management Compliance

### Risk Limits Enforcement (5/5)
- [ ] Enforce spread limit: max 0.5%
- [ ] Enforce volatility limit: max 3x daily average
- [ ] Enforce daily drawdown limit: -5%
- [ ] Enforce position size limit: $2,000 per position
- [ ] Enforce total exposure limit: $10,000

---

## 17. ML Transparency

### Feature Tracking (4/4)
- [ ] Log feature importance for every prediction
- [ ] Store in metadata.feature_importance (top 5 features)
- [ ] Use SHAP values for deep learning models
- [ ] Publish to events:bus stream for auditing

### Model Validation (4/4)
- [ ] Track accuracy on test set
- [ ] Track precision on test set
- [ ] Track recall on test set
- [ ] Log validation metrics to file: `monitoring/model_validation.log`

### Ensemble Weighting (2/2)
- [ ] Log contribution of Random Forest model
- [ ] Log contribution of LSTM model

### Retraining Audit (2/2)
- [ ] Log when retraining occurs
- [ ] Log performance delta (new vs old model)

---

## Completion Checklist

### Phase 1: Foundation (Week 1-2)
- [ ] Schema validation implemented
- [ ] WebSocket reconnection implemented
- [ ] Redis publishing with TLS implemented
- [ ] All Phase 1 tests passing

### Phase 2: Risk & ML (Week 3-4)
- [ ] Risk filters implemented
- [ ] Regime detection implemented
- [ ] Signal analyst implemented
- [ ] All Phase 2 tests passing

### Phase 3: Observability (Week 5)
- [ ] Structured logging implemented
- [ ] Prometheus metrics implemented
- [ ] Health checks implemented
- [ ] All Phase 3 tests passing

### Phase 4: Testing (Week 6)
- [ ] 80%+ test coverage achieved
- [ ] All unit tests passing
- [ ] All integration tests passing
- [ ] All E2E tests passing

### Phase 5: Documentation (Week 7)
- [ ] All 4 core docs written
- [ ] All environment variables documented
- [ ] All config options documented
- [ ] Code documentation complete

### Phase 6: Production Readiness (Week 8)
- [ ] Load test passed (50 signals/sec)
- [ ] Latency optimization complete (P95 < 500ms)
- [ ] Memory profiling complete (< 500MB)
- [ ] All acceptance criteria met

---

## Acceptance Criteria (Go/No-Go)

Before declaring complete, verify:

- [ ] 24hr uptime test passed (no crashes, no manual intervention)
- [ ] All tests passing (unit, integration, E2E)
- [ ] Test coverage ≥ 80%
- [ ] All 4 core docs written and reviewed
- [ ] Prometheus metrics exposed and scraped
- [ ] Health checks returning 200 OK
- [ ] Signals published to Redis and validated by API
- [ ] PnL tracking operational
- [ ] Backtest results documented (Sharpe ≥ 1.5, Drawdown ≤ -15%)

---

**Notes:**
- Mark items complete with `[x]` as you finish them
- Update progress summary at top of document
- Reference PRD section numbers when implementing
- Run `pytest --cov` to check test coverage progress
- Use `redis-cli -u redis://default:Salam78614**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 --tls --cacert config/certs/redis_ca.pem` to test Redis connection

**Last Updated:** 2025-11-14
