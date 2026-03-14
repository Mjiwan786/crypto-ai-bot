# crypto-ai-bot — Architecture

## Signal Lifecycle

```
Exchange (WS/REST)
    │
    ▼
multi_exchange_streamer.py ──► Redis: {exchange}:ohlc:{tf}:{pair}
    │
    ▼
production_engine.py._generate_signal_v2()
    │
    ├─ 1. ohlcv_reader.py        → Read OHLCV from Redis (3 key formats)
    ├─ 2. volume_scoring.py      → Volume ratio gate (+20%/−30% confidence)
    ├─ 3. consensus_gate.py      → 3-family consensus (momentum/trend/structure, need 2/3)
    ├─ 4. Confidence threshold   → Min confidence check
    ├─ 5. trend_filter.py        → EMA-cross trend alignment (Sprint 3A)
    ├─ 6. Fee-floor check        → 52 bps RT minimum
    ├─ 7. ml_scorer.py           → XGBoost ML scoring (Sprint 4B, default OFF)
    ├─ 8. atr_levels.py          → ATR-based TP/SL calculation (Sprint 3A)
    └─ 9. Publish                → Redis stream: signals:{mode}:{exchange}:{pair}
              │
              ▼
         signals-api (consumer) ──► BotEngine ──► SSE ──► signals-site
```

## Module Reference

### signals/ — Signal Pipeline

| Module | Sprint | Purpose |
|--------|--------|---------|
| `ohlcv_reader.py` | 3 | Read OHLCV candles from Redis streams (3 key formats) |
| `volume_scoring.py` | 3 | Volume ratio, confidence multiplier, suppress gate |
| `consensus_gate.py` | 3 | 3 indicator families: momentum (RSI+MACD), trend (EMA), structure (BB+volume) |
| `strategy_orchestrator.py` | 2 | Routes signals through 6 strategies by detected regime |
| `atr_levels.py` | 3A | ATR-based TP/SL with configurable multipliers |
| `exit_manager.py` | 3B | Trailing stop + partial take-profit manager |
| `trend_filter.py` | 3A | EMA-cross trend alignment filter |
| `ml_scorer.py` | 4B | XGBoost ML signal quality scorer (disabled/shadow/active modes) |
| `signal_generator.py` | 1 | Legacy signal generation |
| `signal_normalizer.py` | 1 | Signal normalization |
| `signal_pipeline.py` | 1 | Signal pipeline orchestration |
| `signal_publisher.py` | 1 | Redis stream publisher |
| `signal_scoring.py` | 1 | Signal confidence scoring |
| `signal_validator.py` | 1 | Signal validation rules |

### trainer/ — Offline ML Training Pipeline (Sprint 4A)

| Module | Purpose |
|--------|---------|
| `feature_builder.py` | 30-feature OHLCV feature engineering. `build_features()` (all candles) and `build_single()` (last candle only, <5ms) |
| `data_exporter.py` | Redis→CSV export via `DataExporter`, `label_candles()` with 52 bps fee floor, `generate_synthetic_ohlcv()` (GBM) |
| `models/xgboost_signal.py` | `XGBoostSignalClassifier` — binary classifier with StandardScaler, auto `scale_pos_weight`, early stopping, .joblib save/load |
| `evaluation/walk_forward.py` | `run_walk_forward()` — expanding-window validation with `WalkForwardConfig` (3000 train / 500 val / 15 purge gap), go/no-go gate |
| `train.py` | CLI entry: `python -m trainer.train --synthetic --validate --output models/signal_model.joblib` |
| `tests/` | 38 tests: feature_builder (14), data_exporter (10), xgboost_signal (8), walk_forward (6) |

### agents/ml/ — ML Agent Wrappers (Sprint 4B)

| Module | Purpose |
|--------|---------|
| `feature_engineer.py` | Wraps `trainer.feature_builder.FeatureBuilder`, provides `compute_features(candles)` interface |
| `predictor.py` | Wraps `signals.ml_scorer.MLScorer`, provides `predict(features)` interface |
| `strategy_selector.py` | Legacy strategy selection agent |
| `model_trainer.py` | Legacy model trainer (dead code — not imported by `__init__.py`) |

### ai_engine/regime_detector/ — Regime Detection (Sprint 4B)

| Module | Purpose |
|--------|---------|
| `deep_ta_analyzer.py` | Real RSI/MACD/BB/ATR/trend_strength/volatility from price arrays via `analyse_prices()` |
| `macro_analyzer.py` | `MacroAnalyzer` class: async Redis reads, `_classify_regime()` (risk_on/risk_off/neutral), legacy `analyse_macro()` preserved |
| `regime_writer.py` | Background task publishing regime classification to Redis |
| `sentiment_analyzer.py` | NLP sentiment analysis |
| `combined_sentiment_agent.py` | Multi-source sentiment aggregator |

### agents/special/ — Special Agents (Sprint 4B)

| Module | Purpose |
|--------|---------|
| `onchain_data_agent.py` | `OnChainDataAgent` — reads Sprint 3 cached on-chain metrics from Redis. `fetch_metrics()` (sync) + `fetch_metrics_async()` |

### exchange/ — Multi-Exchange Adapters

| Module | Purpose |
|--------|---------|
| `ccxt_pro_adapter.py` | CCXT Pro WebSocket adapter for 8 exchanges |
| `multi_exchange_streamer.py` | Publishes OHLCV to Redis `{exchange}:ohlc:{tf}:{pair}` streams |
| `ws_adapter.py` | Base WebSocket adapter ABC |

## Redis Key Patterns

| Key Pattern | Source | Purpose |
|-------------|--------|---------|
| `{exchange}:ohlc:{tf}:{DASH_PAIR}` | Streamer | Per-exchange OHLCV candles (primary) |
| `ohlc:{tf}:{exchange}:{pair}` | OHLCV Aggregator | Aggregator-built candles |
| `ohlc:{tf}:any:{pair}` | OHLCV Aggregator | Cross-exchange merged candles |
| `signals:{mode}:{exchange}:{pair}` | Engine | Trade signals (mode = paper/live) |
| `signals:paper`, `signals:live` | Engine (legacy) | Legacy signal streams |
| `regime:{pair}` | RegimeWriter | Current regime classification |
| `onchain:{metric}:{pair}` | CoinGlass client | Cached on-chain data |

## Feature Vector (30 features, trainer/feature_builder.py)

| # | Feature | Category |
|---|---------|----------|
| 1-3 | `rsi_14`, `rsi_7`, `rsi_21` | Technical |
| 4-5 | `macd_line`, `macd_signal` | Technical |
| 6-7 | `macd_histogram`, `macd_cross` | Technical |
| 8-10 | `ema_12`, `ema_26`, `ema_ratio` | Technical |
| 11-13 | `bb_upper`, `bb_lower`, `bb_position` | Technical |
| 14-15 | `atr_14`, `atr_pct` | Technical |
| 16-18 | `close_pct_1`, `close_pct_3`, `close_pct_5` | Derived |
| 19-20 | `high_low_range`, `close_position` | Derived |
| 21-23 | `volume_ratio_5`, `volume_ratio_10`, `volume_trend` | Volume |
| 24-26 | `volatility_5`, `volatility_10`, `vol_regime` | Volatility |
| 27-29 | `momentum_score`, `trend_score`, `structure_score` | Consensus |
| 30 | `consensus_count` | Consensus |

## Known Issues / Tech Debt

- `agents/ml/model_trainer.py` — dead code, imports `mcp.redis_manager` which may not exist. Not imported by `__init__.py`. Safe to delete.
- ML scorer default OFF — needs trained model deployed to `models/signal_model.joblib` before enabling
- `build_single()` computes features for last candle only (<5ms) but requires full candle history passed in
- Walk-forward validation uses expanding window — sliding window variant not yet implemented
- Fee floor hardcoded at 52 bps RT (26 bps per leg) — should be configurable per exchange
