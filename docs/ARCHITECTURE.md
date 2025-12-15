# Platform Architecture

**Version:** 1.0.0
**Last Updated:** 2024-11-17

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Four-Stage Architecture](#four-stage-architecture)
3. [Signal Flow](#signal-flow)
4. [Component Details](#component-details)
5. [Data Flow](#data-flow)
6. [Infrastructure](#infrastructure)
7. [Scalability](#scalability)
8. [Security](#security)
9. [Monitoring](#monitoring)

---

## System Overview

AI-Predicted-Signals is built on a four-stage microservices architecture designed for real-time signal generation and delivery. Each stage has a specific responsibility and communicates through well-defined interfaces.

### Design Principles

- **Separation of Concerns**: Each stage handles one primary responsibility
- **Loose Coupling**: Stages communicate through Redis streams
- **High Availability**: Redundant components and automatic failover
- **Scalability**: Horizontally scalable architecture
- **Real-Time**: Sub-second latency for signal delivery
- **Resilience**: Graceful degradation when components fail

---

## Four-Stage Architecture

```
┌────────────────────────────────────────────────────────────────────────────┐
│                     AI-Predicted-Signals Platform                          │
│                                                                            │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌─────────┐ │
│  │              │    │              │    │              │    │         │ │
│  │  Stage 1     │───▶│  Stage 2     │───▶│  Stage 3     │───▶│Stage 4  │ │
│  │  Crypto-AI   │    │  Redis       │    │  Signals     │    │Signals  │ │
│  │  Bot         │    │  Cloud       │    │  API         │    │Site     │ │
│  │              │    │              │    │              │    │         │ │
│  └──────────────┘    └──────────────┘    └──────────────┘    └─────────┘ │
│       Python             Message             FastAPI            Next.js   │
│       ML Models          Queue               REST + SSE         React     │
│       PyTorch            Pub/Sub             Backend            Frontend  │
└────────────────────────────────────────────────────────────────────────────┘
```

### Stage 1: Crypto-AI-Bot (Signal Generation Engine)

**Purpose**: Generate trading signals using machine learning

**Technology**:
- Python 3.10
- PyTorch (ML framework)
- Pandas/NumPy (data processing)
- Redis client (signal publishing)

**Responsibilities**:
1. **Data Ingestion**
   - Connect to exchange WebSocket (Kraken)
   - Receive real-time OHLCV candles
   - Buffer and preprocess market data

2. **Feature Engineering**
   - Calculate 128 technical indicators
   - Price action features (40)
   - Volume metrics (20)
   - Volatility indicators (8)
   - Oscillators (7)
   - Market microstructure (18)

3. **ML Inference**
   - Load ensemble model (LSTM + Transformer + CNN)
   - Run inference on feature sequence (60 candles)
   - Generate probability distribution
   - Calculate confidence score

4. **Signal Publishing**
   - Package signal with metadata
   - Publish to Redis stream
   - Log signal and performance metrics
   - Update monitoring dashboard

**Performance**:
- Inference latency: ~50-80ms
- Feature engineering: ~50ms
- Total processing: ~100-150ms

### Stage 2: Redis Cloud (Message Queue)

**Purpose**: Real-time message broker and signal queue

**Technology**:
- Redis 7.0+
- Redis Streams
- SSL/TLS encryption
- Managed by Redis Cloud

**Responsibilities**:
1. **Signal Buffering**
   - Receive signals from crypto-ai-bot
   - Queue in Redis streams
   - Maintain order and timestamps
   - Auto-expire old signals (24h TTL)

2. **Pub/Sub**
   - Multiple consumers can read streams
   - Fanout to multiple subscribers
   - Consumer groups for load balancing

3. **State Management**
   - Store latest signal per symbol/timeframe
   - Quick lookup for current signals
   - Historical signal buffer

4. **High Availability**
   - Automatic failover
   - Replication across zones
   - 99.9% uptime SLA

**Performance**:
- Write latency: ~20ms
- Read latency: ~15ms
- Throughput: 10,000+ ops/sec

### Stage 3: Signals-API (Backend API)

**Purpose**: Expose signals via REST and SSE

**Technology**:
- Python 3.10
- FastAPI framework
- Uvicorn server
- Deployed on Fly.io

**Responsibilities**:
1. **Signal Consumption**
   - Read from Redis streams
   - Process and validate signals
   - Cache recent signals in memory

2. **REST API**
   - `GET /v1/signals` - Latest signals
   - `GET /v1/pnl` - PnL metrics
   - `GET /v1/metrics` - Performance
   - `GET /health` - Health check

3. **SSE Streaming**
   - `GET /v1/signals/stream` - Real-time stream
   - Push signals to connected clients
   - Handle client reconnection
   - Maintain active connections

4. **Rate Limiting**
   - Per-IP rate limits
   - API key authentication (optional)
   - DDoS protection

**Performance**:
- API response: ~150-450ms
- SSE latency: ~20ms
- Max connections: 1000+
- Uptime: 99.9%

### Stage 4: Signals-Site (Frontend Dashboard)

**Purpose**: User interface for signal display

**Technology**:
- Next.js 14
- React 18
- TypeScript
- Tailwind CSS
- Deployed on Vercel

**Responsibilities**:
1. **Signal Display**
   - Real-time signal cards
   - Color-coded by signal type
   - Confidence indicators
   - Regime display

2. **PnL Tracking**
   - Equity curve chart
   - Cumulative PnL
   - Win rate and metrics
   - Drawdown visualization

3. **Real-Time Updates**
   - SSE connection to API
   - Live signal updates
   - Automatic reconnection
   - Fallback to polling

4. **User Experience**
   - Responsive design
   - Dark/light mode
   - Mobile optimization
   - Graceful error handling

**Performance**:
- Page load: ~1-2s
- SSE update: ~200ms
- Mobile score: 95+
- Desktop score: 98+

---

## Signal Flow

### Detailed Flow with Timing

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Complete Signal Flow (End-to-End)                                       │
└─────────────────────────────────────────────────────────────────────────┘

Step 1: Market Data Reception
┌──────────────┐
│ Exchange     │ WebSocket candle (15m)
│ (Kraken)     │────────────────────────────────┐
└──────────────┘                                │
                                                ▼
                                        ┌──────────────────┐
                                        │ Crypto-AI-Bot    │
                                        │ Data Ingestion   │
                                        └──────────────────┘
                                                │ ~5ms
                                                ▼

Step 2: Feature Engineering
                                        ┌──────────────────┐
                                        │ Feature Engineer │
                                        │ 128 features     │
                                        └──────────────────┘
                                                │ ~50ms
                                                ▼

Step 3: ML Inference
                                        ┌──────────────────┐
                                        │ ML Ensemble      │
                                        │ LSTM+Trans+CNN   │
                                        └──────────────────┘
                                                │ ~50-80ms
                                                ▼

Step 4: Signal Generation
                                        ┌──────────────────┐
                                        │ Signal Publisher │
                                        │ Package + Send   │
                                        └──────────────────┘
                                                │ ~20ms
                                                ▼

Step 5: Message Queue
                                        ┌──────────────────┐
                                        │ Redis Stream     │
                                        │ Signal Queued    │
                                        └──────────────────┘
                                                │ ~20ms
                                                ▼

Step 6: API Processing
                                        ┌──────────────────┐
                                        │ Signals-API      │
                                        │ Consume Signal   │
                                        └──────────────────┘
                                                │ ~20ms
                                                ▼

Step 7: SSE Broadcast
                                        ┌──────────────────┐
                                        │ SSE Stream       │
                                        │ Push to Clients  │
                                        └──────────────────┘
                                                │ ~20ms
                                                ▼

Step 8: Frontend Display
                                        ┌──────────────────┐
                                        │ Dashboard        │
                                        │ Signal Rendered  │
                                        └──────────────────┘

Total Latency: ~200-500ms ✅ (Target: <1000ms)
```

### Data Transformations

```
Raw OHLCV Data
    │
    ├─▶ Price Action Features (40)
    ├─▶ Volume Metrics (20)
    ├─▶ Volatility Indicators (8)
    ├─▶ Oscillators (7)
    └─▶ Market Microstructure (18)
    │
    ▼
Feature Vector (128 dimensions)
    │
    ├─▶ LSTM Model (40% weight)
    ├─▶ Transformer Model (35% weight)
    └─▶ CNN Model (25% weight)
    │
    ▼
Ensemble Prediction
    │
    ├─▶ Signal (LONG/SHORT/NEUTRAL)
    ├─▶ Confidence Score (0-1)
    ├─▶ Probabilities (distribution)
    └─▶ Risk Parameters (position size, stops)
    │
    ▼
Redis Stream Message
    │
    ▼
API JSON Response
    │
    ▼
Dashboard Display
```

---

## Component Details

### Crypto-AI-Bot Components

```
crypto_ai_bot/
├── main.py                          # Entry point
├── ml/
│   ├── models/
│   │   ├── lstm_model.py           # LSTM architecture
│   │   ├── transformer_model.py    # Transformer architecture
│   │   └── cnn_model.py            # CNN architecture
│   ├── deep_ensemble.py            # Ensemble logic
│   ├── feature_engineering.py      # Feature pipeline
│   ├── confidence_calibration.py   # Confidence scoring
│   └── redis_signal_publisher.py   # Redis publishing
├── config/
│   ├── model_config.yaml           # Model hyperparameters
│   └── trading_config.yaml         # Trading parameters
└── monitoring/
    ├── performance_tracker.py      # Performance monitoring
    └── drift_detector.py           # Model drift detection
```

#### ML Model Architecture

**LSTM Model**:
- Input: (batch, 60, 128) - 60 timesteps, 128 features
- Bidirectional LSTM: 3 layers, 256 hidden units
- Multi-head attention: 8 heads
- Output: (batch, 3) - 3 classes (SHORT, NEUTRAL, LONG)
- Parameters: 3.2M

**Transformer Model**:
- Input: (batch, 60, 128)
- Positional encoding: Sinusoidal
- Encoder layers: 6 layers, 512 d_model
- Multi-head attention: 8 heads, 2048 feedforward
- Output: (batch, 3)
- Parameters: 8.5M

**CNN Model**:
- Input: (batch, 60, 128)
- Multi-scale convolutions: 3, 5, 7 kernel sizes
- Inception modules: 2 modules
- Global pooling: Average + Max
- Output: (batch, 3)
- Parameters: 1.8M

**Ensemble**:
- Regime-adaptive weighting
- TRENDING_UP: LSTM 45%, Transformer 35%, CNN 20%
- RANGING: LSTM 35%, Transformer 35%, CNN 30%
- VOLATILE: LSTM 30%, Transformer 45%, CNN 25%

### Signals-API Components

```
signals_api/
├── main.py                     # FastAPI app
├── routers/
│   ├── signals.py             # Signal endpoints
│   ├── pnl.py                 # PnL endpoints
│   └── metrics.py             # Metrics endpoints
├── services/
│   ├── redis_consumer.py      # Redis consumption
│   ├── sse_manager.py         # SSE connection manager
│   └── pnl_calculator.py      # PnL calculations
├── middleware/
│   ├── rate_limiter.py        # Rate limiting
│   └── auth.py                # Authentication
└── models/
    ├── signal.py              # Signal data model
    └── pnl.py                 # PnL data model
```

#### API Architecture

**FastAPI Application**:
- Async/await for high concurrency
- Dependency injection for services
- Automatic OpenAPI docs
- CORS middleware for frontend

**SSE Manager**:
- Maintains active client connections
- Broadcasts signals to all clients
- Handles disconnections
- Implements heartbeat

**Rate Limiter**:
- Per-IP rate limiting
- Sliding window algorithm
- Redis-backed counters
- Configurable limits

### Signals-Site Components

```
signals-site/
├── app/
│   ├── page.tsx               # Homepage
│   ├── signals/
│   │   └── page.tsx           # Signals dashboard
│   └── pnl/
│       └── page.tsx           # PnL dashboard
├── components/
│   ├── SignalCard.tsx         # Signal display card
│   ├── EquityCurve.tsx        # Equity chart
│   ├── PnLMetrics.tsx         # PnL metrics
│   └── SSEConnection.tsx      # SSE client
├── lib/
│   ├── api.ts                 # API client
│   └── sse.ts                 # SSE utilities
└── hooks/
    ├── useSignals.ts          # Signals hook
    └── usePnL.ts              # PnL hook
```

---

## Data Flow

### Signal Publication (Write Path)

```
1. Crypto-AI-Bot generates signal
   ↓
2. Serialize to JSON
   {
     "timestamp": "2024-11-17T12:00:00Z",
     "symbol": "BTC/USDT",
     "signal": "LONG",
     "confidence": 0.75,
     ...
   }
   ↓
3. Publish to Redis stream
   XADD ml_signals:BTC/USDT:15m * <json_fields>
   ↓
4. Redis stores in stream
   Stream: ml_signals:BTC/USDT:15m
   Entry: 1234567890-0 {signal data}
   ↓
5. Also store as latest
   SET ml_signals:latest:BTC/USDT:15m <json>
   EXPIRE 3600
```

### Signal Consumption (Read Path)

```
1. Signals-API reads from Redis
   XREAD BLOCK 1000 STREAMS ml_signals:BTC/USDT:15m $
   ↓
2. Parse and validate signal
   ↓
3. Broadcast via SSE to connected clients
   data: {signal JSON}\n\n
   ↓
4. Dashboard receives via EventSource
   EventSource.onmessage = (event) => {
     const signal = JSON.parse(event.data);
     updateUI(signal);
   }
   ↓
5. UI updates with new signal
```

### PnL Calculation

```
1. Track all signals
   ↓
2. Calculate entry/exit prices
   Entry: Signal price
   Exit: Next signal or current price
   ↓
3. Calculate PnL per trade
   PnL = (Exit - Entry) * Position Size * Direction
   ↓
4. Aggregate metrics
   - Cumulative PnL
   - Win rate
   - Sharpe ratio
   - Max drawdown
   ↓
5. Store in Redis
   SET pnl:metrics <json>
   ↓
6. Expose via API
   GET /v1/pnl
```

---

## Infrastructure

### Deployment Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Production Environment                      │
└─────────────────────────────────────────────────────────────────┘

┌──────────────────┐         ┌──────────────────┐         ┌──────────────────┐
│   Crypto-AI-Bot  │         │   Signals-API    │         │   Signals-Site   │
│                  │         │                  │         │                  │
│   Local/Server   │────────▶│   Fly.io         │◀────────│   Vercel         │
│   Python Process │         │   Docker         │         │   Edge Network   │
│                  │         │   2 instances    │         │   Global CDN     │
└──────────────────┘         └──────────────────┘         └──────────────────┘
         │                            │                            │
         │                            │                            │
         └────────────────────────────┼────────────────────────────┘
                                      │
                                      ▼
                            ┌──────────────────┐
                            │   Redis Cloud    │
                            │   Managed        │
                            │   Multi-AZ       │
                            │   SSL/TLS        │
                            └──────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                         DNS & CDN                               │
│                                                                 │
│  Cloudflare                                                     │
│  - DNS: aipredictedsignals.cloud                               │
│  - SSL Certificate                                              │
│  - DDoS Protection                                              │
│  - Edge Caching                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Redis Cloud Setup

**Configuration**:
- Plan: Redis Cloud (Managed)
- Memory: 500MB
- Persistence: AOF + RDB
- SSL/TLS: Enabled
- Replication: Multi-AZ
- Backup: Daily snapshots

**Connection**:
```bash
redis-cli -u rediss://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com:19818 --tls
```

**Streams**:
- `ml_signals:{symbol}:{timeframe}` - Signal streams
- `ml_signals:latest:{symbol}:{timeframe}` - Latest signals
- `pnl:metrics` - PnL metrics
- `system:metrics` - System metrics

### Fly.io Deployment

**App Configuration** (`fly.toml`):
```toml
app = "crypto-signals-api"
primary_region = "iad"

[build]
  dockerfile = "Dockerfile"

[env]
  PORT = "8000"

[[services]]
  http_checks = []
  internal_port = 8000
  protocol = "tcp"

  [[services.ports]]
    port = 80
    handlers = ["http"]

  [[services.ports]]
    port = 443
    handlers = ["http", "tls"]
```

**Scaling**:
- Instances: 2 (for redundancy)
- Region: US East (IAD)
- Auto-scaling: Enabled
- Health checks: Every 30s

### Vercel Deployment

**Configuration** (`vercel.json`):
```json
{
  "framework": "nextjs",
  "buildCommand": "npm run build",
  "devCommand": "npm run dev",
  "installCommand": "npm install",
  "env": {
    "NEXT_PUBLIC_API_URL": "https://signals-api-gateway.fly.dev"
  }
}
```

**Features**:
- Edge Network: Global CDN
- Automatic SSL: Let's Encrypt
- Preview Deployments: Every PR
- Analytics: Web Vitals tracking

---

## Scalability

### Horizontal Scaling

**Crypto-AI-Bot**:
- Run multiple instances per symbol/timeframe
- Each instance publishes to same Redis stream
- Redis ensures order and deduplication

**Signals-API**:
- Scale to N instances on Fly.io
- Load balanced automatically
- Each instance consumes from Redis
- SSE clients connect to any instance

**Redis Cloud**:
- Cluster mode for >1GB memory
- Horizontal scaling across nodes
- Automatic sharding by key

### Performance Optimization

**Caching**:
- Redis for signal caching (fast reads)
- API response caching (60s TTL)
- Frontend static asset caching

**Connection Pooling**:
- Redis connection pool (10 connections)
- HTTP connection reuse
- Database connection pooling

**Async Operations**:
- Async I/O throughout stack
- Non-blocking signal processing
- Concurrent API requests

---

## Security

### Authentication & Authorization

**API Keys** (Optional):
```
X-API-Key: <api_key>
```

**Rate Limiting**:
- Per-IP: 100 requests/minute
- Per-API-Key: 1000 requests/minute
- SSE: 10 connections/IP

### Data Security

**Encryption**:
- Redis: SSL/TLS encryption
- API: HTTPS only
- Frontend: HTTPS only

**Secrets Management**:
- Environment variables
- Fly.io secrets
- Vercel env vars
- No secrets in code

### Network Security

**Firewall Rules**:
- Fly.io: Only 80/443 exposed
- Redis: Only allows TLS connections
- Private networks between services

---

## Monitoring

### Metrics Collection

**Application Metrics**:
- Signal latency
- API response time
- Error rates
- Cache hit rates

**Infrastructure Metrics**:
- CPU usage
- Memory usage
- Network bandwidth
- Disk I/O

### Alerting

**Alert Rules**:
- API uptime <99.8% → Alert
- Latency >1s for 5min → Alert
- Error rate >5% → Alert
- Redis connection down → Alert

### Logging

**Log Aggregation**:
- Crypto-AI-Bot: File logs + stdout
- Signals-API: Fly.io logs
- Frontend: Vercel logs

**Log Levels**:
- ERROR: Errors requiring attention
- WARN: Potential issues
- INFO: Normal operations
- DEBUG: Detailed debugging

---

## Disaster Recovery

### Backup Strategy

**Redis Backups**:
- Daily automated snapshots
- Retained for 7 days
- Stored in S3

**Code Backups**:
- Git repositories (GitHub)
- Automated backups
- Version history

**Configuration Backups**:
- Environment variables documented
- Configuration files in Git

### Recovery Procedures

**API Failure**:
1. Fly.io auto-restarts failed instances
2. Health checks detect issues
3. Automatic failover to healthy instances
4. Manual intervention if needed

**Redis Failure**:
1. Redis Cloud auto-failover
2. Backup replica promoted
3. Connections auto-reconnect
4. Data integrity maintained

**Complete System Failure**:
1. Restore from backups
2. Redeploy applications
3. Verify connections
4. Resume operations

---

## Future Enhancements

### Planned Features

1. **Multi-Exchange Support**
   - Binance, Coinbase, Bybit
   - Cross-exchange arbitrage
   - Unified signal stream

2. **Enhanced ML Models**
   - Sentiment analysis
   - On-chain metrics
   - Order book depth

3. **Advanced Risk Management**
   - Portfolio optimization
   - Dynamic position sizing
   - Correlation analysis

4. **Mobile Apps**
   - iOS app (React Native)
   - Android app (React Native)
   - Push notifications

5. **Trading Automation**
   - Auto-execution of signals
   - Paper trading mode
   - Backtesting platform

---

**Document Version**: 1.0.0
**Last Updated**: 2024-11-17
**Status**: Production Ready ✅
