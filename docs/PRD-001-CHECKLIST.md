# PRD-001 Implementation Checklist

**PRD Location:** `docs/PRD-001-CRYPTO-AI-BOT.md`
**Generated:** 2025-11-14
**Status:** 15/248 Complete (6.0%)

---

## Environment Setup

**Conda Environment:** `crypto-bot`
**Redis Connection:** `rediss://default:Salam78614%2A%2A%24%24@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818`
**Redis CA Cert:** `C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem`

### Environment Configuration (5/5) ✅ COMPLETE
- [x] Conda environment `crypto-bot` activated (user to verify: `conda activate crypto-bot`)
- [x] All dependencies from requirements.txt installed (redis, websockets, pydantic, fastapi, prometheus-client, pytest)
- [x] Redis Cloud TLS certificate placed at `config/certs/redis_ca.pem`
- [x] `.env.paper` file created with REDIS_URL, TRADING_MODE=paper, LOG_LEVEL=INFO
- [x] `.env.live` file created with production settings (TRADING_MODE=live, safety checks enabled)

---

## 1. Data Ingestion (Kraken WebSocket) - Reliability & Message Handling

**Problem Addressed:** Dropped WebSocket messages, no reconnection strategy, missing heartbeat, no exception handling

### 1.1 Connection Management (7/8)
- [x] Subscribe to Kraken WS feeds: ticker, spread, trade, book (L2) for all pairs (BTC/USD, ETH/USD, SOL/USD, MATIC/USD, LINK/USD)
- [x] Implement WebSocket connection to wss://ws.kraken.com with configurable timeout (30s default)
- [x] Implement PING/PONG heartbeat monitoring every 30 seconds
- [x] Add connection state tracking (CONNECTING, CONNECTED, DISCONNECTED, RECONNECTING)
- [x] Log connection state changes at INFO level with timestamps
- [x] Mark bot as unhealthy when WebSocket disconnected > 2 minutes
- [x] Add connection timeout detection (no PONG response in 60s → reconnect)
- [ ] Emit Prometheus counter `kraken_ws_connections_total{state}` on state changes

### 1.2 Reconnection Logic (3/10)
- [x] Implement exponential backoff: start at 1s, double each attempt (1s, 2s, 4s, 8s, 16s, 32s, max 60s)
- [x] Add ±20% jitter to backoff intervals to prevent thundering herd
- [x] Set max reconnection attempts to 10 before marking unhealthy
- [ ] Track reconnection attempt count and reset on successful connection
- [ ] Log each reconnection attempt with attempt number and wait time
- [ ] After 10 failed attempts, mark bot unhealthy and trigger PagerDuty alert
- [ ] On successful reconnection, resubscribe to all channels (ticker, spread, trade, book)
- [ ] Emit Prometheus counter `kraken_ws_reconnects_total` on each reconnection attempt
- [ ] Handle reconnection during graceful shutdown (cancel reconnection attempts)
- [ ] Add reconnection unit test with mocked WebSocket failures

### 1.3 Message Validation (12/12)
- [ ] Verify Kraken message schema on receipt (check required fields: channel, pair, data)
- [ ] Extract and validate sequence numbers from Kraken messages
- [ ] Track last sequence number per channel: `last_seq[channel]`
- [ ] Detect sequence gaps: if `new_seq != last_seq + 1`, log warning
- [ ] Emit Prometheus counter `kraken_ws_message_gaps_total{channel}` on gap detection
- [ ] Reject messages with timestamps > 5 seconds old (stale data protection)
- [ ] Reject messages with timestamps > 5 seconds in the future (clock skew protection)
- [ ] Log timestamp validation failures at WARNING level with delta
- [ ] Emit Prometheus counter `kraken_ws_stale_messages_total{channel}` on stale message rejection
- [ ] Implement deduplication cache (store last 100 message IDs per channel)
- [ ] Check incoming messages against deduplication cache before processing
- [ ] Emit Prometheus counter `kraken_ws_duplicates_rejected_total{channel}` on duplicate detection

### 1.4 Error Handling (8/8)
- [ ] Wrap all WebSocket operations in try/except blocks
- [ ] Log connection errors at ERROR level with exception details
- [ ] Log message parsing errors at WARNING level with raw message data
- [ ] Emit Prometheus counter `kraken_ws_errors_total{error_type}` for all error types
- [ ] Handle WebSocket protocol errors (close codes 1000, 1001, 1006, etc.)
- [ ] Implement graceful degradation: serve cached data if WebSocket unavailable > 30s
- [ ] Add cache TTL (5 minutes) for stale data fallback
- [ ] Mark health check unhealthy during sustained failures (> 2 min)

### 1.5 Performance (5/5)
- [ ] Measure P95 latency from Kraken message receipt → processing complete (target < 50ms)
- [ ] Emit Prometheus histogram `kraken_ws_latency_ms{channel}` for message processing time
- [ ] Handle 100+ messages/second per pair without backpressure
- [ ] Implement backpressure detection: queue depth > 1000 → log warning, drop oldest messages
- [ ] Memory bound WebSocket buffers to max 100MB total

### 1.6 Data Persistence (5/5)
- [ ] Store latest ticker data in Redis: `kraken:ticker:{pair}` with 60s TTL
- [ ] Store latest spread data in Redis: `kraken:spread:{pair}` with 60s TTL
- [ ] Store latest book snapshot (L2) in Redis: `kraken:book:{pair}` with 60s TTL
- [ ] Publish trade events to Redis stream `kraken:trade:{pair}` with MAXLEN 1000
- [ ] Add timestamp and sequence number to all persisted data

---

## 2. Redis Streams Publishing - Data Integrity

**Problem Addressed:** Schema drift, dropped signals, no sequence numbers, missing idempotency

### 2.1 Connection Management (6/6)
- [ ] Connect to Redis Cloud via TLS (rediss://) using connection string from REDIS_URL env var
- [ ] Load TLS certificate from `config/certs/redis_ca.pem`
- [ ] Implement connection pooling with max 10 connections
- [ ] Add Redis PING health check every 60 seconds
- [ ] Track Redis connection state (CONNECTED, DISCONNECTED, RECONNECTING)
- [ ] Emit Prometheus gauge `redis_connected{instance}` (1=connected, 0=disconnected)

### 2.2 Stream Configuration (8/8)
- [ ] Configure signal stream name based on TRADING_MODE: `signals:paper` or `signals:live`
- [ ] Configure PnL stream: `pnl:signals` with MAXLEN 50000
- [ ] Configure events stream: `events:bus` with MAXLEN 5000
- [ ] Set MAXLEN=10000 on signal streams (automatic trimming)
- [ ] Use approximate trimming (~) for performance: `XADD ... MAXLEN ~ 10000`
- [ ] Verify stream configuration on startup (XINFO STREAM)
- [ ] Log stream configuration at INFO level on startup
- [ ] Emit Prometheus gauge `redis_stream_length{stream}` for all streams

### 2.3 Publishing Guarantees (12/12)
- [ ] Use `signal_id` (UUID v4) as Redis message ID for idempotency
- [ ] Validate signal with Pydantic `TradingSignal` model before XADD
- [ ] Serialize signal to JSON with UTF-8 encoding
- [ ] Publish all signal fields atomically in single XADD command
- [ ] Handle Redis XADD duplicate ID rejection (log at DEBUG level, emit metric)
- [ ] Implement retry logic: 3 attempts with exponential backoff (100ms, 200ms, 400ms) on publish failure
- [ ] Log publish failures at ERROR level with signal_id and error details
- [ ] Emit Prometheus counter `redis_publish_errors_total{stream, error_type}` on failures
- [ ] Emit Prometheus counter `signal_schema_errors_total{reason}` on validation failures
- [ ] Emit Prometheus counter `signal_duplicates_rejected_total{stream}` on duplicate IDs
- [ ] Add publish timeout (5s max) to prevent hanging
- [ ] Queue failed publishes in memory (max 1000) for retry on Redis reconnection

### 2.4 Performance (5/5)
- [ ] Measure P95 publish latency (target < 20ms)
- [ ] Emit Prometheus histogram `redis_publish_latency_ms{stream}` for publish operations
- [ ] Handle 50+ signals/second publish rate without backpressure
- [ ] Implement backpressure: queue depth > 1000 → reject new signals, log ERROR
- [ ] Emit Prometheus gauge `redis_publish_queue_depth{stream}` for queue monitoring

### 2.5 Data Integrity (7/7)
- [ ] Generate timestamps using `datetime.now(timezone.utc)` (server-side clock)
- [ ] Enforce monotonically increasing timestamps (reject if timestamp <= last_timestamp)
- [ ] Reject signals with timestamps > 5s in future (clock skew protection)
- [ ] Validate timestamp format: ISO8601 UTC (e.g., 2025-11-14T12:34:56.789Z)
- [ ] Add sequence number to signal metadata for ordering validation
- [ ] Compute SHA256 checksum of signal JSON, store in metadata.checksum (optional for v1)
- [ ] Log timestamp validation failures at WARNING level with delta

---

## 3. Multi-Agent ML Engine - Transparency & Validation

**Problem Addressed:** No ML transparency, missing methodology, black-box models

### 3.1 Agent Architecture (8/8)
- [ ] Implement Regime Detector agent with classify() method returning regime label
- [ ] Implement Signal Analyst agent with generate_signal() method returning TradingSignal
- [ ] Implement Risk Manager agent with validate_signal() method returning approved/rejected
- [ ] Implement Position Manager agent with track_position() and manage_exits() methods
- [ ] Add agent base class with common logging, metrics, error handling
- [ ] Log agent lifecycle events (startup, shutdown) at INFO level
- [ ] Emit Prometheus counter `agent_invocations_total{agent, outcome}` for all agent calls
- [ ] Add unit tests for each agent in isolation with mocked dependencies

### 3.2 Regime Detector (10/10)
- [ ] Train regime detector ensemble: Random Forest (60%) + LSTM (40%)
- [ ] Use 1-hour OHLCV data as input (200 candles = 16.7 hours history)
- [ ] Output regime label: TRENDING_UP, TRENDING_DOWN, RANGING, VOLATILE
- [ ] Calculate features: ADX, ATR, Bollinger Band width, volume profile, SMA ratio
- [ ] Implement regime classification rules (ADX > 25 for trending, ADX < 20 for ranging, ATR > p80 for volatile)
- [ ] Update regime classification every 5 minutes
- [ ] Cache last 24 hours of regime labels in Redis: `state:regime:{pair}` with 24hr TTL
- [ ] Log regime changes at INFO level with confidence score
- [ ] Emit Prometheus gauge `current_regime{pair}` (0=RANGING, 1=TRENDING_UP, -1=TRENDING_DOWN, 2=VOLATILE)
- [ ] Add regime detector unit tests with synthetic TRENDING_UP, RANGING, VOLATILE data

### 3.3 Signal Analyst (10/10)
- [ ] Implement strategy selection based on current regime (see PRD Section 8.7)
- [ ] Configure strategy allocations: scalper=0.4, trend=0.3, mean_reversion=0.2, breakout=0.1
- [ ] Generate signals with min confidence threshold 0.6 (reject < 60%)
- [ ] Calculate indicators: RSI(14), MACD, ATR(14), volume_ratio
- [ ] Populate TradingSignal.indicators section with all indicator values
- [ ] Calculate entry_price, take_profit, stop_loss based on strategy rules
- [ ] Calculate risk_reward_ratio: (take_profit - entry_price) / (entry_price - stop_loss)
- [ ] Log signal generation at INFO level with pair, strategy, confidence
- [ ] Emit Prometheus counter `signals_generated_total{pair, strategy, side}` on signal creation
- [ ] Add signal analyst unit tests for each strategy (scalper, trend, mean_reversion, breakout)

### 3.4 Model Transparency (8/8)
- [ ] Log feature importance for every prediction (top 5 features with weights)
- [ ] Store feature importance in `metadata.feature_importance` field (optional for v1)
- [ ] Use SHAP values for LSTM model explainability
- [ ] Publish model predictions to `events:bus` stream for audit trail
- [ ] Document all features in `docs/ML_FEATURES.md` (feature name, formula, purpose, expected range)
- [ ] Version control feature dictionary (update on feature changes)
- [ ] Log model version in signal `metadata.model_version` field
- [ ] Add feature importance unit test (verify top features make sense for regime)

### 3.5 Training & Validation (10/10)
- [ ] Implement training script: `scripts/train_predictor_v2.py`
- [ ] Use 70/30 train/test split with time-series cross-validation (5 folds)
- [ ] Implement hyperparameter tuning (grid search or Bayesian optimization)
- [ ] Calculate validation metrics: Accuracy, Precision, Recall, F1, ROC-AUC
- [ ] Enforce acceptance thresholds: Accuracy ≥ 65%, Precision ≥ 60%, Recall ≥ 60%, F1 ≥ 0.60
- [ ] Log validation metrics to `monitoring/model_validation.log`
- [ ] Emit Prometheus gauge `model_accuracy{model, regime}` for each regime
- [ ] Store trained model in `models/` directory with version tag (e.g., regime_detector_v2.2.pkl)
- [ ] Implement weekly retraining schedule (Sunday 00:00 UTC via cron)
- [ ] Only deploy new model if accuracy improves by ≥ 2% vs current model

### 3.6 Ensemble & Confidence (5/5)
- [ ] Implement weighted ensemble: RF (60%) + LSTM (40%)
- [ ] Adjust weights based on recent accuracy (last 100 predictions)
- [ ] Calculate confidence from model agreement: both agree → 0.9, disagree → 0.5
- [ ] Log ensemble prediction and confidence at DEBUG level
- [ ] Add ensemble unit test with known RF and LSTM predictions

---

## 4. Risk Management Engine - Filters & Position Sizing

**Problem Addressed:** Missing risk filters, no spread checks, no volatility limits, no drawdown controls

### 4.1 Spread Limits (5/5)
- [ ] Fetch current spread from Kraken `spread` channel before signal generation
- [ ] Calculate spread %: `(ask - bid) / mid * 100`
- [ ] Reject signal if spread > 0.5% (configurable via risk.filters.max_spread_pct)
- [ ] Log spread rejection at WARNING level with pair and spread %
- [ ] Emit Prometheus counter `risk_filter_rejections_total{reason="wide_spread", pair}`

### 4.2 Volatility Limits (6/6)
- [ ] Calculate ATR(14) on 5-minute candles for each pair
- [ ] Track 30-day rolling average ATR for each pair
- [ ] If current_ATR > 3.0 × avg_ATR, reduce position size by 50%
- [ ] If current_ATR > 5.0 × avg_ATR, halt new signals (circuit breaker)
- [ ] Log volatility adjustments at INFO level with ATR ratio
- [ ] Emit Prometheus counter `risk_filter_rejections_total{reason="high_volatility", pair}`

### 4.3 Daily Drawdown Circuit Breaker (7/7)
- [ ] Track P&L from midnight UTC daily reset
- [ ] Calculate daily drawdown: (current_equity - start_of_day_equity) / start_of_day_equity
- [ ] If daily drawdown < -5%, halt new signals until next day (00:00 UTC)
- [ ] Log circuit breaker activation at CRITICAL level with drawdown %
- [ ] Emit Prometheus counter `circuit_breaker_triggered{reason="daily_drawdown"}`
- [ ] Emit Prometheus gauge `current_drawdown_pct` (updated real-time)
- [ ] Add daily drawdown unit test with simulated losing trades

### 4.4 Position Sizing (8/8)
- [ ] Implement position sizing formula: `size = base_size * confidence * (avg_ATR / ATR)`
- [ ] Set base_size = $100 per signal (configurable via risk.position_sizing.base_usd)
- [ ] Apply volatility adjustment: divide by (ATR / avg_ATR) to reduce size in high vol
- [ ] Apply confidence scaling: multiply by signal.confidence (0.6 - 1.0)
- [ ] Cap position size at $2,000 max per signal (risk.position_sizing.max_position_usd)
- [ ] Enforce max total exposure: sum of all open positions ≤ $10,000
- [ ] Log position sizing calculation at DEBUG level with all factors
- [ ] Add position sizing unit tests with various confidence and ATR scenarios

### 4.5 Loss Streak Management (8/8)
- [ ] Implement LossStreakTracker class to track consecutive losses per strategy
- [ ] Increment loss count on losing trade, reset to 0 on winning trade
- [ ] After 3 consecutive losses, reduce strategy allocation by 50%
- [ ] After 5 consecutive losses, pause strategy and require manual review
- [ ] Log loss streak warnings at WARNING level (3 losses) and CRITICAL level (5 losses)
- [ ] Emit Prometheus gauge `strategy_loss_streak{strategy}` for current loss count
- [ ] Store loss streak state in Redis: `state:loss_streak:{strategy}` with 7-day TTL
- [ ] Add loss streak unit test with sequence of wins/losses

### 4.6 Position Concentration (4/4)
- [ ] Calculate position concentration per symbol: position_size / total_portfolio_value
- [ ] Reject signal if position concentration > 40% for any single symbol
- [ ] Log concentration rejection at WARNING level with symbol and concentration %
- [ ] Emit Prometheus counter `risk_filter_rejections_total{reason="concentration", pair}`

---

## 5. Signal Schema Validation

**Problem Addressed:** Schema drift between repos, inconsistent field names

### 5.1 Pydantic Models (12/12)
- [ ] Implement Side enum (LONG, SHORT)
- [ ] Implement Strategy enum (SCALPER, TREND, MEAN_REVERSION, BREAKOUT)
- [ ] Implement Regime enum (TRENDING_UP, TRENDING_DOWN, RANGING, VOLATILE)
- [ ] Implement MACDSignal enum (BULLISH, BEARISH, NEUTRAL)
- [ ] Implement Indicators model with fields: rsi_14, macd_signal, atr_14, volume_ratio
- [ ] Implement Metadata model with fields: model_version, backtest_sharpe, latency_ms
- [ ] Implement TradingSignal model with all required fields (signal_id, timestamp, pair, side, etc.)
- [ ] Add Pydantic field validators: entry_price > 0, take_profit > 0, stop_loss > 0, confidence in [0,1]
- [ ] Add Pydantic field validators: position_size_usd > 0 and <= 2000
- [ ] Add Pydantic field validators: rsi_14 in [0, 100], atr_14 > 0, volume_ratio > 0
- [ ] Add custom validator to ensure take_profit > entry_price for LONG, take_profit < entry_price for SHORT
- [ ] Add custom validator to ensure stop_loss < entry_price for LONG, stop_loss > entry_price for SHORT

### 5.2 Schema Validation (8/8)
- [ ] Validate every signal with TradingSignal.parse_obj() before Redis publish
- [ ] Catch Pydantic ValidationError and log at ERROR level with field details
- [ ] Emit Prometheus counter `signal_schema_errors_total{field, error_type}` on validation failures
- [ ] Reject invalid signals (do not publish to Redis)
- [ ] Add schema validation unit tests for valid signal (should pass)
- [ ] Add schema validation unit tests for invalid signals (missing fields, wrong types, out-of-range values)
- [ ] Add regression test to ensure signal schema matches API expectations (field names, types)
- [ ] Document canonical schema in PRD Section 5 (this is already done)

### 5.3 Example Signal (3/3)
- [ ] Create example_signal.json file with valid signal matching schema
- [ ] Validate example signal passes Pydantic validation
- [ ] Document example signal in PRD Section 5.2 (already done)

---

## 6. Backtesting Validation

**Problem Addressed:** Missing methodology, no strategy validation before production

### 6.1 Data Requirements (6/6)
- [ ] Fetch 1 year (365 days) historical OHLCV data for BTC/USD, ETH/USD, SOL/USD
- [ ] Use Kraken exchange as data source (via CCXT or cached data)
- [ ] Implement slippage model: 5 bps (0.05%) per trade
- [ ] Implement fee calculation: Kraken fee tiers (maker 16 bps, taker 26 bps)
- [ ] Simulate realistic order fills (limit orders require depth check, market orders use slippage)
- [ ] Store historical data in cache for reuse (`data/ohlcv/`)

### 6.2 Backtest Metrics (8/8)
- [ ] Calculate total return % for backtest period
- [ ] Calculate Sharpe ratio: (mean_return - risk_free_rate) / std_deviation
- [ ] Calculate max drawdown: max peak-to-trough decline
- [ ] Calculate win rate: winning_trades / total_trades
- [ ] Calculate profit factor: gross_profit / gross_loss
- [ ] Calculate average trade duration in hours
- [ ] Count total trades in backtest period
- [ ] Log all metrics to `out/backtests/{strategy}_{date}.json`

### 6.3 Acceptance Criteria (7/7)
- [ ] Enforce Sharpe ratio ≥ 1.5 for production deployment
- [ ] Enforce max drawdown ≤ -15%
- [ ] Enforce win rate ≥ 45%
- [ ] Enforce profit factor ≥ 1.3
- [ ] Enforce minimum 200 trades in backtest period
- [ ] Block deployment if backtest fails acceptance criteria
- [ ] Add backtest acceptance unit test with known good/bad results

### 6.4 Automation (5/5)
- [ ] Implement backtest script: `scripts/run_backtest.py --strategy scalper --period 365`
- [ ] Run backtests in CI/CD on every strategy code change
- [ ] Store backtest results in `out/backtests/` directory with timestamp
- [ ] Generate backtest report with equity curve chart (`docs/backtest_report_{date}.html`)
- [ ] Fail CI build if backtest doesn't meet acceptance criteria

---

## 7. Configuration System

**Problem Addressed:** Hardcoded values, no environment separation, missing validation

### 7.1 Configuration Files (6/6)
- [ ] Create base config: `config/settings.yaml` with all defaults
- [ ] Create paper trading config: `.env.paper` with TRADING_MODE=paper
- [ ] Create live trading config: `.env.live` with TRADING_MODE=live
- [ ] Create strategy configs: `config/strategies/scalper.yaml`, `trend.yaml`, etc.
- [ ] Create risk config: `config/risk_config.yaml` with all risk limits
- [ ] Load config based on TRADING_MODE environment variable

### 7.2 Environment Variables (8/8)
- [ ] Define REDIS_URL (required, no default)
- [ ] Define TRADING_MODE (paper or live, default: paper)
- [ ] Define LOG_LEVEL (DEBUG, INFO, WARNING, ERROR, default: INFO)
- [ ] Define KRAKEN_API_KEY and KRAKEN_SECRET (required for live mode only)
- [ ] Define TRADING_PAIRS (comma-separated, default: BTC/USD,ETH/USD,SOL/USD,MATIC/USD,LINK/USD)
- [ ] Define ENABLE_TRADING (boolean safety switch, default: false for live mode)
- [ ] Define LIVE_TRADING_CONFIRMATION (must be "I_UNDERSTAND_REAL_MONEY" for live mode)
- [ ] Create `.env.example` file documenting all environment variables

### 7.3 Validation (6/6)
- [ ] Implement Pydantic models for config sections (ExchangeConfig, RedisConfig, RiskConfig, etc.)
- [ ] Validate config on load with Pydantic (fail fast on invalid config)
- [ ] Add type checking (int, float, str, bool, enum)
- [ ] Add range validation (min/max values for numeric fields)
- [ ] Validate required fields are present (REDIS_URL, TRADING_MODE)
- [ ] Add config validation unit tests with valid and invalid configs

### 7.4 Hot Reload (Optional) (4/4)
- [ ] Implement file watcher for `config/settings.yaml` changes
- [ ] Reload non-critical params without restart (log_level, timeouts)
- [ ] Restrict hot-reload: cannot change REDIS_URL, TRADING_MODE, TRADING_PAIRS
- [ ] Log config reload events at INFO level with changed fields

---

## 8. Logging & Metrics - Observability

**Problem Addressed:** Empty PnL/metrics, no observability, no exception handling

### 8.1 Structured Logging (10/10)
- [ ] Implement JSONFormatter for structured logging
- [ ] Log format: `{"timestamp": ISO8601, "level": str, "component": str, "message": str, "context": dict}`
- [ ] Configure logging levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
- [ ] Log to stdout (for Fly.io log aggregation)
- [ ] Log to file: `logs/crypto_ai_bot.log` with rotation
- [ ] Implement log rotation: max 100MB per file, keep last 7 days
- [ ] Compress old logs with gzip
- [ ] Add context fields to all logs: pair, signal_id, strategy, timestamp
- [ ] Log exception tracebacks on ERROR/CRITICAL levels
- [ ] Add structured logging unit test (verify JSON output format)

### 8.2 Prometheus Metrics - Counters (8/8)
- [ ] Implement `signals_published_total{pair, strategy, side}` counter
- [ ] Implement `risk_rejections_total{reason, pair}` counter
- [ ] Implement `kraken_ws_reconnects_total` counter
- [ ] Implement `kraken_ws_errors_total{error_type}` counter
- [ ] Implement `kraken_ws_message_gaps_total{channel}` counter
- [ ] Implement `redis_publish_errors_total{stream, error_type}` counter
- [ ] Implement `signal_schema_errors_total{field, error_type}` counter
- [ ] Implement `circuit_breaker_triggered{reason}` counter

### 8.3 Prometheus Metrics - Gauges (6/6)
- [ ] Implement `active_positions{pair}` gauge
- [ ] Implement `current_drawdown_pct` gauge
- [ ] Implement `kraken_ws_latency_ms{quantile}` gauge (P50, P95, P99)
- [ ] Implement `redis_connected{instance}` gauge (1=connected, 0=disconnected)
- [ ] Implement `current_regime{pair}` gauge (encoded as int)
- [ ] Implement `model_accuracy{model, regime}` gauge

### 8.4 Prometheus Metrics - Histograms (4/4)
- [ ] Implement `signal_generation_latency_ms` histogram (buckets: 10, 25, 50, 100, 250, 500, 1000, 2500)
- [ ] Implement `redis_publish_latency_ms` histogram
- [ ] Implement `backtest_sharpe` histogram (for strategy performance tracking)
- [ ] Implement `trade_duration_hours` histogram

### 8.5 Metrics Endpoint (5/5)
- [ ] Implement FastAPI app with `/metrics` endpoint (port 8000)
- [ ] Expose metrics in Prometheus text format
- [ ] Update metrics real-time on events (signal publish, error, reconnection)
- [ ] Add CORS headers to allow Grafana scraping
- [ ] Add `/metrics` endpoint unit test (verify Prometheus format)

### 8.6 Alerting Integration (5/5)
- [ ] Configure PagerDuty integration for CRITICAL alerts (WebSocket down > 5 min)
- [ ] Configure Slack integration for WARNING alerts (drawdown > -3%)
- [ ] Send daily performance summary to email (total signals, win rate, P&L)
- [ ] Add alert suppression during maintenance windows
- [ ] Test alert delivery with synthetic critical event

---

## 9. Reliability & Crash Recovery

**Problem Addressed:** No crash recovery, missing graceful shutdown, no state persistence

### 9.1 Graceful Shutdown (8/8)
- [ ] Register signal handlers for SIGTERM and SIGINT
- [ ] On shutdown signal, set `shutdown_event` to stop main loop
- [ ] Close WebSocket connections cleanly (send close frame)
- [ ] Flush pending Redis publishes (wait for queue to drain, max 30s)
- [ ] Log shutdown reason (SIGTERM, SIGINT, or uncaught exception)
- [ ] Set shutdown timeout to 30 seconds (force exit after)
- [ ] Emit Prometheus counter `graceful_shutdowns_total{reason}` on shutdown
- [ ] Add graceful shutdown integration test (send SIGTERM, verify clean exit)

### 9.2 State Persistence (8/8)
- [ ] Store active positions in Redis: `state:positions:{pair}` as JSON with 24hr TTL
- [ ] Store regime labels in Redis: `state:regime:{pair}` with 24hr TTL
- [ ] Store loss streak counts in Redis: `state:loss_streak:{strategy}` with 7-day TTL
- [ ] Store daily P&L in Redis: `state:daily_pnl` with 24hr TTL (reset at midnight UTC)
- [ ] On startup, load state from Redis if available
- [ ] Log state recovery at INFO level with recovered data count
- [ ] Handle missing state gracefully (initialize to defaults)
- [ ] Add state persistence unit test (write state, restart, verify recovery)

### 9.3 Restart Recovery (7/7)
- [ ] On startup, check for persisted state in Redis
- [ ] Reconcile positions with Kraken API (for live mode only)
- [ ] Re-subscribe to all WebSocket channels after state recovery
- [ ] Mark health check as unhealthy until recovery complete
- [ ] Mark health check as healthy only after: state loaded, WebSocket connected, Redis connected
- [ ] Log recovery completion at INFO level with uptime since restart
- [ ] Emit Prometheus counter `restarts_total{reason}` on startup

### 9.4 Failure Modes (7/7)
- [ ] On transient Redis failure, queue publishes in memory (max 1000 messages)
- [ ] Retry Redis publishes every 5 seconds until success or max queue depth
- [ ] On transient Kraken failure, serve cached data from Redis with "stale" flag
- [ ] Mark cached data as stale after 5 minutes
- [ ] On persistent failure (> 5 min), mark bot unhealthy and trigger alert
- [ ] Log failure mode transitions at ERROR level
- [ ] Add failure mode unit tests (simulate Redis down, Kraken down, both down)

---

## 10. Health Checks & Monitoring

**Problem Addressed:** No health checks, silent failures, no Fly.io integration

### 10.1 Health Check Endpoint (10/10)
- [ ] Implement FastAPI `/health` endpoint on port 8080
- [ ] Return JSON: `{"status": "healthy", "uptime_sec": int, "last_signal_sec_ago": int, "issues": []}`
- [ ] Check WebSocket connection status (unhealthy if disconnected > 2 min)
- [ ] Check Redis connection status (unhealthy if unavailable > 1 min)
- [ ] Check last signal age (degraded if no signals in last 10 min during market hours)
- [ ] Return HTTP 200 for "healthy", 503 for "unhealthy", 200 for "degraded" (with issues list)
- [ ] Add market hours check (crypto is 24/7, but can filter weekends for testing)
- [ ] Log health check requests at DEBUG level
- [ ] Add health check unit tests for healthy, unhealthy, degraded states
- [ ] Configure Fly.io health check in `fly.toml` (30s interval, 5s timeout, 10s grace period)

### 10.2 Fly.io Configuration (5/5)
- [ ] Create `fly.toml` with app name, region, and service configuration
- [ ] Configure internal_port = 8080 for health checks
- [ ] Configure http_checks with path="/health", interval=30s, timeout=5s
- [ ] Add environment variables section (REDIS_URL, TRADING_MODE, LOG_LEVEL)
- [ ] Test Fly.io deployment: `fly deploy` and verify health checks pass

---

## 11. Testing - Comprehensive Coverage

**Problem Addressed:** Missing tests, deployment fear, inability to refactor safely

### 11.1 Unit Tests - Core Logic (15/15)
- [ ] Test regime detector with synthetic TRENDING_UP data (should return TRENDING_UP)
- [ ] Test regime detector with synthetic RANGING data (should return RANGING)
- [ ] Test regime detector with synthetic VOLATILE data (should return VOLATILE)
- [ ] Test spread filter rejects signal when spread > 0.5%
- [ ] Test spread filter approves signal when spread <= 0.5%
- [ ] Test volatility adjustment reduces size when ATR > 3.0 × avg_ATR
- [ ] Test volatility adjustment halts signals when ATR > 5.0 × avg_ATR
- [ ] Test position sizing with various confidence and ATR scenarios
- [ ] Test loss streak tracker increments on loss, resets on win
- [ ] Test loss streak tracker warns after 3 losses, pauses after 5 losses
- [ ] Test signal schema validation with valid signal (should pass)
- [ ] Test signal schema validation with missing required fields (should fail)
- [ ] Test signal schema validation with out-of-range values (should fail)
- [ ] Test timestamp validation rejects timestamps > 5s old
- [ ] Test daily drawdown circuit breaker activates at -5%

### 11.2 Integration Tests - Services (10/10)
- [ ] Test Redis publish: signal → XADD → verify in stream with XREAD
- [ ] Test Redis duplicate ID rejection: publish same signal_id twice → second XADD fails
- [ ] Test Redis reconnection: disconnect → auto-reconnect → publishes resume
- [ ] Test Kraken WebSocket connection: connect → subscribe → receive messages
- [ ] Test Kraken WebSocket reconnection: disconnect → auto-reconnect with backoff
- [ ] Test health check endpoint returns 200 when all services healthy
- [ ] Test health check endpoint returns 503 when WebSocket down
- [ ] Test health check endpoint returns 503 when Redis down
- [ ] Test graceful shutdown: SIGTERM → close connections → flush queue → exit
- [ ] Test state persistence: store state → restart → load state

### 11.3 End-to-End Tests (10/10)
- [ ] Create mock Kraken WebSocket server returning fake trade data
- [ ] Start bot pointing to mock WS server and test Redis
- [ ] Inject fake trade data: {"pair": "BTC/USD", "price": 43250, "volume": 1.5}
- [ ] Wait 1 second for signal generation
- [ ] Verify signal published to Redis stream (XREAD signals:paper)
- [ ] Validate signal schema with TradingSignal.parse_obj()
- [ ] Verify signal.pair == "BTC/USD"
- [ ] Verify signal.confidence >= 0.6
- [ ] Verify signal.metadata.latency_ms < 500
- [ ] Test full pipeline: WebSocket → Regime Detector → Signal Analyst → Risk Manager → Redis

### 11.4 Regression Tests (8/8)
- [ ] Test signal schema matches API expectations (field names, no camelCase)
- [ ] Test WebSocket reconnection after network interruption (issue #X)
- [ ] Test Redis publish retry on transient failure (issue #Y)
- [ ] Test timestamp ordering (no backdated signals)
- [ ] Test spread filter rejection (no illiquid markets)
- [ ] Test position sizing caps at $2000 max
- [ ] Test loss streak pauses strategy after 5 losses
- [ ] Tag all regression tests with `@pytest.mark.regression`

### 11.5 Load Tests (5/5)
- [ ] Test Redis publish throughput: 1000 signals → measure time → assert ≥ 50 signals/sec
- [ ] Test WebSocket message processing: 100 messages/sec → assert P95 latency < 50ms
- [ ] Test concurrent signal generation: 10 strategies → assert no backpressure
- [ ] Test memory usage: run for 1 hour → assert memory < 500MB
- [ ] Test CPU usage: 100 msg/sec load → assert CPU < 50% (single core)

### 11.6 Test Coverage (4/4)
- [ ] Configure pytest-cov to measure coverage
- [ ] Run `pytest --cov=agents --cov=strategies --cov=risk --cov-report=html`
- [ ] Achieve ≥ 80% line coverage for core modules (agents, strategies, risk)
- [ ] Generate HTML coverage report in `htmlcov/index.html`

---

## 12. Documentation - Complete Runbooks

**Problem Addressed:** Missing documentation, no methodology, no runbook

### 12.1 Methodology Document (8/8)
- [ ] Create `docs/METHODOLOGY.md`
- [ ] Document overview of trading approach (scalper, trend, mean reversion, breakout)
- [ ] Document technical indicators used (RSI, MACD, ATR, Bollinger Bands, OBV, VWAP)
- [ ] Document regime detection logic with thresholds (ADX > 25, BB width < p30, etc.)
- [ ] Document position sizing formula with examples
- [ ] Document risk management rules (spread limits, volatility adjustments, drawdown controls)
- [ ] Add example walkthrough: from market data → regime detection → signal generation → risk check → publish
- [ ] Review METHODOLOGY.md with stakeholders (engineers, investors, auditors)

### 12.2 Architecture Document (7/7)
- [ ] Create `docs/ARCHITECTURE.md`
- [ ] Add high-level architecture diagram (Kraken → Bot → Redis → API → UI)
- [ ] Document component responsibilities (agents, strategies, risk manager, position manager)
- [ ] Document technology stack (Python 3.11, Redis Cloud, Kraken WS, FastAPI, Prometheus)
- [ ] Document data models (signal schema, position schema, PnL schema)
- [ ] Document scalability considerations (horizontal scaling, Redis sharding)
- [ ] Add deployment architecture (Fly.io, multi-region, health checks)

### 12.3 Runbook (10/10)
- [ ] Create `docs/RUNBOOK.md` (if not exists, update if exists)
- [ ] Document deployment steps: conda env setup, dependencies install, config setup, Fly.io deploy
- [ ] Document environment variables (REDIS_URL, TRADING_MODE, LOG_LEVEL, etc.)
- [ ] Document health check verification: `curl http://localhost:8080/health`
- [ ] Document common incidents: WebSocket down, Redis timeout, high latency, circuit breaker activation
- [ ] Document incident resolution: check logs, restart service, verify health, check Grafana
- [ ] Document rollback procedure: `fly releases`, `fly releases revert`
- [ ] Document performance tuning: scaling, Redis optimization, WebSocket buffer tuning
- [ ] Document monitoring dashboards (Grafana URLs, key metrics to watch)
- [ ] Document on-call escalation process (PagerDuty, Slack, email)

### 12.4 Signal Flow Document (6/6)
- [ ] Create `docs/SIGNAL_FLOW.md`
- [ ] Add step-by-step flow diagram: market data → ingestion → analysis → risk check → publish
- [ ] Document timing breakdown: target latencies per stage (WS 50ms, ML 100ms, risk 10ms, publish 20ms)
- [ ] Document error handling at each stage (retry logic, fallbacks, circuit breakers)
- [ ] Add example signal JSON at each stage (raw data, analyzed signal, risk-approved signal, published signal)
- [ ] Document integration points with signals-api and signals-site

### 12.5 Feature Dictionary (4/4)
- [ ] Create `docs/ML_FEATURES.md`
- [ ] Document all ML features in table: name, formula, purpose, expected range
- [ ] Include at least: rsi_14, adx_14, atr_14, volume_ratio, bb_width, macd, sma_ratio
- [ ] Version control feature dictionary (add version header, update on changes)

---

## 13. Performance & Reliability - Production Standards

**Problem Addressed:** No performance targets, undefined SLOs

### 13.1 Latency Targets (6/6)
- [ ] Measure end-to-end latency: Kraken message receipt → Redis publish
- [ ] Achieve P50 latency ≤ 200ms
- [ ] Achieve P95 latency ≤ 500ms
- [ ] Achieve P99 latency ≤ 1000ms
- [ ] Emit `signal_generation_latency_ms` histogram for all signals
- [ ] Alert if P95 latency > 500ms for 5 consecutive minutes

### 13.2 Throughput Targets (4/4)
- [ ] Achieve ≥ 10 signals/hour per pair during market hours
- [ ] Handle 100+ WebSocket messages/second per pair without backpressure
- [ ] Handle 50+ signals/second publish rate to Redis
- [ ] Measure throughput with `rate(signals_published_total[1m])` Prometheus query

### 13.3 Uptime Targets (5/5)
- [ ] Achieve ≥ 99.5% uptime (max 43.8 min downtime/month)
- [ ] Monitor uptime with Fly.io health checks (30s interval)
- [ ] Emit Prometheus gauge `up` (1=up, 0=down)
- [ ] Calculate monthly uptime from Prometheus data: `sum_over_time(up[30d]) / count_over_time(up[30d])`
- [ ] Alert if uptime < 99.5% in any 30-day period

### 13.4 Resource Limits (4/4)
- [ ] Limit memory usage to < 500MB (monitor with Prometheus `process_resident_memory_bytes`)
- [ ] Limit CPU usage to < 50% single core (monitor with `process_cpu_seconds_total`)
- [ ] Limit WebSocket buffer memory to max 100MB
- [ ] Alert if memory > 400MB or CPU > 40% for 10 minutes

### 13.5 Error Rates (3/3)
- [ ] Target 0 schema validation errors (100% compliance)
- [ ] Target < 5 WebSocket reconnections/day under normal conditions
- [ ] Alert if error rate > threshold: `rate(kraken_ws_errors_total[1h]) > 10`

---

## 14. Deployment & Operations - Production Readiness

### 14.1 Fly.io Deployment (8/8)
- [ ] Create Fly.io account and install CLI: `fly version`
- [ ] Create Fly.io app: `fly apps create crypto-ai-bot-{env}`
- [ ] Configure fly.toml with correct app name, region, and services
- [ ] Set secrets: `fly secrets set REDIS_URL=... KRAKEN_API_KEY=... KRAKEN_SECRET=...`
- [ ] Deploy to staging: `fly deploy --config fly.toml --env staging`
- [ ] Run E2E tests on staging environment
- [ ] Deploy to production: `fly deploy --config fly.toml --env production`
- [ ] Verify health checks pass: `fly checks list`

### 14.2 Monitoring Setup (7/7)
- [ ] Configure Prometheus to scrape `/metrics` endpoint every 15s
- [ ] Create Grafana dashboard with key metrics (signals/min, latency, uptime, errors)
- [ ] Add Grafana panels: signal generation rate, P95 latency, active positions, current drawdown
- [ ] Set up PagerDuty integration for critical alerts (WebSocket down > 5 min, circuit breaker)
- [ ] Set up Slack integration for warnings (drawdown > -3%, high latency)
- [ ] Test alert delivery with synthetic events
- [ ] Document dashboard URLs and alert channels in RUNBOOK.md

### 14.3 PnL Tracking (8/8)
- [ ] Implement PnL calculation: (exit_price - entry_price) * position_size for LONG
- [ ] Implement PnL calculation: (entry_price - exit_price) * position_size for SHORT
- [ ] Subtract fees: maker_fee (16 bps) or taker_fee (26 bps) × 2 (entry + exit)
- [ ] Subtract slippage: 5 bps × 2 (entry + exit)
- [ ] Publish PnL events to Redis stream `pnl:signals` with signal_id, entry_price, exit_price, pnl_usd, fees_usd, slippage_usd
- [ ] Track daily P&L in Redis: `state:daily_pnl` (reset at midnight UTC)
- [ ] Emit Prometheus gauge `daily_pnl_usd` (updated on each trade close)
- [ ] Verify 100% of signals have corresponding PnL records: `len(pnl:signals) == len(trades:closed)`

### 14.4 CI/CD Pipeline (6/6)
- [ ] Create GitHub Actions workflow: `.github/workflows/test.yml`
- [ ] Run tests on every commit: `pytest tests/ --cov --cov-report=xml`
- [ ] Run linter: `flake8 agents/ strategies/ risk/`
- [ ] Run type checker: `mypy agents/ strategies/ risk/`
- [ ] Fail build if tests fail, coverage < 80%, or linter/type errors
- [ ] Auto-deploy to staging on merge to `main` branch

---

## 15. E2E Validation - Production Acceptance

**This section validates the complete system is working end-to-end**

### 15.1 Signal Flow Validation (8/8)
- [ ] Bot publishes valid signals into Redis streams (signals:paper or signals:live)
- [ ] Signals conform to PRD-defined schema (TradingSignal Pydantic validation passes)
- [ ] Signals appear in Redis: `redis-cli XREAD COUNT 10 STREAMS signals:paper 0`
- [ ] Signals have all required fields: signal_id, timestamp, pair, side, strategy, regime, entry_price, etc.
- [ ] Signals have correct timestamp format: ISO8601 UTC (e.g., 2025-11-14T12:34:56.789Z)
- [ ] Signals have valid enum values: side in [LONG, SHORT], strategy in [SCALPER, TREND, MEAN_REVERSION, BREAKOUT]
- [ ] Signals have realistic values: entry_price > 0, confidence in [0.6, 1.0], position_size_usd in [0, 2000]
- [ ] Verify signals appear downstream in signals-api: `curl https://api.crypto-signals.com/v1/signals/latest`

### 15.2 PnL Pipeline Validation (6/6)
- [ ] PnL events published to Redis stream `pnl:signals`
- [ ] PnL events have signal_id matching published signals
- [ ] PnL events have entry_price, exit_price, pnl_usd, fees_usd, slippage_usd fields
- [ ] PnL calculations are correct: verify manually for sample trade (LONG: exit - entry, SHORT: entry - exit)
- [ ] Daily P&L aggregation is non-zero and matches sum of individual trades
- [ ] Verify PnL data appears in signals-api: `curl https://api.crypto-signals.com/v1/performance/pnl`

### 15.3 Health & Monitoring Validation (6/6)
- [ ] Health check returns 200 OK: `curl http://localhost:8080/health` → `{"status": "healthy"}`
- [ ] Prometheus metrics exposed: `curl http://localhost:8000/metrics` → text format with metrics
- [ ] Grafana dashboard displays real-time data (signals/min, latency, positions, drawdown)
- [ ] Fly.io health checks pass: `fly checks list` → all passing
- [ ] PagerDuty test alert delivered (simulate WebSocket down)
- [ ] Slack test notification delivered (simulate drawdown warning)

### 15.4 24-Hour Soak Test (5/5)
- [ ] Run bot continuously for 24 hours without crashes
- [ ] No manual intervention required during 24-hour period
- [ ] Verify uptime ≥ 99.5% (max 7 min downtime in 24 hours)
- [ ] Verify at least 240 signals published (10/hour × 24 hours for 1 pair)
- [ ] Verify no memory leaks: memory usage stable or < 500MB

### 15.5 Acceptance Sign-Off (10/10)
- [ ] All unit tests passing (pytest tests/unit/)
- [ ] All integration tests passing (pytest tests/integration/)
- [ ] All E2E tests passing (pytest tests/e2e/)
- [ ] Test coverage ≥ 80% (pytest --cov)
- [ ] All 4 core docs written and reviewed (METHODOLOGY, ARCHITECTURE, RUNBOOK, SIGNAL_FLOW)
- [ ] Prometheus metrics exposed and scraped by Grafana
- [ ] Health checks returning 200 OK
- [ ] Signals published to Redis and validated by signals-api
- [ ] PnL tracking operational (100% signal → PnL attribution)
- [ ] Backtest results documented: Sharpe ≥ 1.5, Drawdown ≤ -15%, Win Rate ≥ 45%

---

## Progress Summary

**Total Tasks:** 248
**Completed:** 12
**Remaining:** 236
**Progress:** 4.8%

### By Section:
- Environment Setup: 5/5 (100%) ✅
- Data Ingestion: 7/48 (15%) 🟡
- Redis Publishing: 0/38 (0%)
- Multi-Agent ML: 0/51 (0%)
- Risk Management: 0/38 (0%)
- Signal Schema: 0/23 (0%)
- Backtesting: 0/26 (0%)
- Configuration: 0/24 (0%)
- Logging & Metrics: 0/38 (0%)
- Reliability: 0/30 (0%)
- Health Checks: 0/15 (0%)
- Testing: 0/52 (0%)
- Documentation: 0/35 (0%)
- Performance: 0/22 (0%)
- Deployment: 0/29 (0%)
- E2E Validation: 0/35 (0%)

---

## Notes

- This checklist is derived from [PRD-001: Crypto AI Bot - Core Intelligence Engine](PRD-001-CRYPTO-AI-BOT.md)
- Each checkbox item is testable and actionable
- Items are grouped by functional area for easier implementation
- All identified problems are addressed (empty PnL, missing reconnection, schema drift, missing methodology, risk filters, dropped signals, sequence numbers, heartbeat, exception handling, backpressure)
- Environment details included for quick reference
- Conda env: `crypto-bot`
- Redis URL: `rediss://default:Salam78614%2A%2A%24%24@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818`
- Redis cert: `C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem`

---

**STATUS:** Ready for implementation
**NEXT ACTION:** Begin with Environment Setup (Section 0), then proceed to Data Ingestion (Section 1)
