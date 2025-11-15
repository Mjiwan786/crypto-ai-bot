# Real-Time Performance Metrics - Complete Guide

**Date**: 2025-11-08
**Status**: ✅ FULLY IMPLEMENTED
**Repos**: crypto-ai-bot, signals-api, signals-site

---

## 🎯 Overview

Your system already has **complete end-to-end performance metrics tracking** with:

1. **Aggressive Mode Score**: `(win_rate × avg_win) / (loss_rate × avg_loss)`
2. **Velocity to Target**: `(equity - $10k) / ($20k - $10k)`
3. **Days Remaining Estimate**: Based on current daily rate

All metrics flow through:
- **crypto-ai-bot** → Calculates & publishes to Redis + Prometheus
- **signals-api** → REST/SSE endpoints
- **signals-site** → Live dashboard with sparkline charts

---

## 📊 Metrics Explained

### 1. Aggressive Mode Score

**Formula**: `(win_rate × avg_win) / (loss_rate × avg_loss)`

**Purpose**: Risk-adjusted performance measure. Higher = better risk/reward profile.

**Interpretation**:
- **≥ 2.0**: Excellent - Strong risk-adjusted returns
- **≥ 1.5**: Very Good - Positive risk profile
- **≥ 1.0**: Good - Balanced performance
- **≥ 0.5**: Fair - Room for improvement
- **< 0.5**: Poor - Review strategy

**Example**:
```
Win rate: 50%, Avg win: $100
Loss rate: 50%, Avg loss: $60
Score = (0.5 × 100) / (0.5 × 60) = 50 / 30 = 1.67 ✅ Very Good
```

### 2. Velocity to Target

**Formula**: `(current_equity - starting_equity) / (target_equity - starting_equity)`

**Purpose**: Track progress towards equity goal ($10k → $20k default).

**Interpretation**:
- **0.0**: At starting equity ($10,000)
- **0.5**: Halfway to target ($15,000) - 50% progress
- **1.0**: Reached target ($20,000) - 100% complete
- **>1.0**: Exceeded target

**Example**:
```
Starting: $10,000
Current: $14,000
Target: $20,000
Velocity = (14,000 - 10,000) / (20,000 - 10,000) = 4,000 / 10,000 = 0.4 = 40%
```

### 3. Days Remaining Estimate

**Formula**: `(target_equity - current_equity) / daily_rate`

**Purpose**: Project time to reach goal at current pace.

**Interpretation**:
- **< 7 days**: Target within a week! 🚀
- **< 30 days**: On track - good progress
- **< 90 days**: Moderate pace
- **> 90 days**: Slow progress - consider strategy adjustments
- **null/∞**: Insufficient data or negative daily rate

**Example**:
```
Current: $14,000
Target: $20,000
Daily rate: +$200/day
Days = (20,000 - 14,000) / 200 = 6,000 / 200 = 30 days
```

---

## 🔧 Configuration (crypto-ai-bot)

### Environment Variables

Add to `.env`:

```bash
# Performance Metrics
ENABLE_PERFORMANCE_METRICS=true       # Master toggle
STARTING_EQUITY_USD=10000             # Starting equity
TARGET_EQUITY_USD=20000               # Target equity
METRICS_UPDATE_INTERVAL_SEC=30        # Update frequency (seconds)

# Already configured (from existing setup)
METRICS_PORT=9108                     # Prometheus port
METRICS_ADDR=0.0.0.0                  # Prometheus bind address
```

### Redis Streams Used

The metrics are published to these Redis streams:

```bash
# Main performance snapshot (all metrics)
metrics:performance

# Individual metric streams (for granular SSE)
metrics:aggressive_mode_score
metrics:velocity_to_target
metrics:days_remaining
```

### Prometheus Metrics Exposed

Available at `http://localhost:9108/metrics`:

```prometheus
# Aggressive mode score
aggressive_mode_score 1.45

# Velocity to target (0.0 to 1.0+)
velocity_to_target 0.42

# Days remaining (capped at 9999 for Prometheus)
days_remaining_estimate 28.5

# Supporting metrics
current_equity_usd 14200.00
daily_rate_usd 214.29
win_rate_percent 48.5
```

### Python Integration

The metrics are automatically calculated by `PerformanceMetricsCalculator`:

```python
from metrics.performance_metrics import PerformanceMetricsCalculator
from metrics.metrics_publisher import MetricsPublisher

# In your main bot initialization
calculator = PerformanceMetricsCalculator(
    redis_manager=redis_manager,
    starting_equity=10000.0,
    target_equity=20000.0,
)

# Create publisher (runs in background thread)
publisher = MetricsPublisher(
    redis_manager=redis_manager,
    trade_manager=trade_manager,
    equity_tracker=equity_tracker,
    update_interval=30,  # Update every 30 seconds
)

# Start publishing
publisher.start()

# Later, when you need metrics
metrics = calculator.calculate_metrics(
    trades=closed_trades_list,
    current_equity=current_account_balance,
)

# Metrics are automatically published to:
# - Redis streams (for signals-api SSE)
# - Prometheus (for monitoring)
```

### File Locations

**crypto-ai-bot**:
- `metrics/performance_metrics.py` - Calculator (423 lines) ✅
- `metrics/metrics_publisher.py` - Background publisher (80+ lines) ✅
- `monitoring/metrics_exporter.py` - Prometheus exporter ✅

---

## 🌐 API Endpoints (signals-api)

### Base URL
```
Production: https://crypto-signals-api.fly.dev
Local: http://localhost:8000
```

### REST Endpoints

#### 1. Get All Performance Metrics
```http
GET /metrics/performance
```

**Response**:
```json
{
  "timestamp": 1699463520.5,
  "aggressive_mode_score": 1.45,
  "win_rate": 0.485,
  "loss_rate": 0.515,
  "avg_win_usd": 142.50,
  "avg_loss_usd": 95.30,
  "velocity_to_target": 0.42,
  "current_equity_usd": 14200.00,
  "target_equity_usd": 20000.00,
  "starting_equity_usd": 10000.00,
  "days_remaining_estimate": 28.5,
  "daily_rate_usd": 203.57,
  "days_elapsed": 28.5,
  "total_trades": 142,
  "winning_trades": 69,
  "losing_trades": 73,
  "total_pnl_usd": 4200.00
}
```

#### 2. Get Aggressive Mode Score
```http
GET /metrics/performance/aggressive-mode-score
```

**Response**:
```json
{
  "timestamp": 1699463520.5,
  "value": 1.45,
  "metric": "aggressive_mode_score"
}
```

#### 3. Get Velocity to Target
```http
GET /metrics/performance/velocity-to-target
```

**Response**:
```json
{
  "timestamp": 1699463520.5,
  "value": 0.42,
  "percent": 42.0,
  "metric": "velocity_to_target"
}
```

#### 4. Get Days Remaining
```http
GET /metrics/performance/days-remaining
```

**Response**:
```json
{
  "timestamp": 1699463520.5,
  "value": 28.5,
  "metric": "days_remaining_estimate"
}
```

#### 5. Get Performance Summary (Human-Readable)
```http
GET /metrics/performance/summary
```

**Response**:
```json
{
  "available": true,
  "timestamp": 1699463520.5,
  "aggressive_mode_score": {
    "value": 1.45,
    "interpretation": "Very Good - Positive risk profile",
    "description": "Risk-adjusted performance: (win_rate * avg_win) / (loss_rate * avg_loss)"
  },
  "velocity_to_target": {
    "value": 0.42,
    "percent": 42.0,
    "description": "Progress: $14,200 / $20,000"
  },
  "days_remaining_estimate": {
    "value": 28.5,
    "daily_rate": 203.57,
    "description": "On track - 29 days to target"
  },
  "trading_stats": {
    "total_trades": 142,
    "win_rate": 0.485,
    "avg_win": 142.50,
    "avg_loss": 95.30,
    "total_pnl": 4200.00
  }
}
```

### SSE Streaming Endpoint

#### Real-Time Performance Metrics Stream
```http
GET /metrics/performance/stream?heartbeat=30
```

**Query Parameters**:
- `heartbeat` (optional): Heartbeat interval in seconds (5-120, default: 30)

**Response**: Server-Sent Events stream

**Event Types**:
```
event: performance
data: {"metric":"performance","data":{...},"stream":"metrics:performance"}

event: aggressive_mode_score
data: {"metric":"aggressive_mode_score","data":{"timestamp":...,"value":1.45},"stream":"metrics:aggressive_mode_score"}

event: velocity_to_target
data: {"metric":"velocity_to_target","data":{"timestamp":...,"value":0.42},"stream":"metrics:velocity_to_target"}

event: days_remaining
data: {"metric":"days_remaining","data":{"timestamp":...,"value":28.5},"stream":"metrics:days_remaining"}

event: heartbeat
data: {"type":"heartbeat","timestamp":1699463520.5,"messages_sent":45,"messages_dropped":0}

event: error
data: {"error":"stream_error","message":"Redis connection lost"}
```

### JavaScript Client Example

```javascript
// Connect to SSE stream
const eventSource = new EventSource(
  'https://crypto-signals-api.fly.dev/metrics/performance/stream?heartbeat=30'
);

// Handle full performance snapshot
eventSource.addEventListener('performance', (e) => {
  const data = JSON.parse(e.data);
  console.log('Performance metrics:', data.data);
  updateDashboard(data.data);
});

// Handle individual metric updates
eventSource.addEventListener('aggressive_mode_score', (e) => {
  const data = JSON.parse(e.data);
  console.log('Aggressive score:', data.data.value);
  updateAggressiveScore(data.data.value);
});

eventSource.addEventListener('velocity_to_target', (e) => {
  const data = JSON.parse(e.data);
  console.log('Velocity:', data.data.value);
  updateVelocity(data.data.value);
});

eventSource.addEventListener('days_remaining', (e) => {
  const data = JSON.parse(e.data);
  console.log('Days remaining:', data.data.value);
  updateDaysRemaining(data.data.value);
});

// Handle heartbeat
eventSource.addEventListener('heartbeat', (e) => {
  const data = JSON.parse(e.data);
  console.log('Heartbeat:', data.timestamp);
});

// Handle errors
eventSource.addEventListener('error', (e) => {
  const data = JSON.parse(e.data);
  console.error('Stream error:', data.message);
});

// Connection state
eventSource.onopen = () => {
  console.log('SSE connected');
};

eventSource.onerror = (err) => {
  console.error('SSE connection error:', err);
  // Will auto-reconnect
};

// Cleanup
window.addEventListener('beforeunload', () => {
  eventSource.close();
});
```

### File Locations

**signals-api**:
- `app/routers/performance_metrics.py` - Endpoints (595 lines) ✅

---

## 🎨 UI Components (signals-site)

### Components Included

1. **`PerformanceMetricsWidget`** - Main dashboard widget
   - SSE connection management
   - Live metric updates
   - Error handling & reconnection
   - History tracking (20 data points)
   - Grid layout (3 cards)

2. **`PerformanceMetricsCard`** - Individual metric display
   - Live value display
   - Sparkline chart
   - Trend indicators
   - Color-coded status
   - Interpretations

### Usage Example

Add to any Next.js page:

```tsx
import PerformanceMetricsWidget from '@/components/PerformanceMetricsWidget';

export default function Dashboard() {
  return (
    <div className="container mx-auto p-6">
      <h1 className="text-3xl font-bold mb-6">Trading Dashboard</h1>

      {/* Performance metrics with live updates */}
      <PerformanceMetricsWidget />

      {/* Your other components */}
    </div>
  );
}
```

### Environment Variables

Add to `.env.local`:

```bash
NEXT_PUBLIC_API_BASE_URL=https://crypto-signals-api.fly.dev
```

For local development:
```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

### Features

✅ **Real-time SSE updates** - Connects to `/metrics/performance/stream`
✅ **Sparkline charts** - Shows last 20 data points per metric
✅ **Trend indicators** - Up/down arrows based on recent changes
✅ **Color-coded cards** - Green (good), yellow (fair), red (poor)
✅ **Auto-reconnection** - Reconnects on disconnect with 5s delay
✅ **Loading states** - Skeleton screens while fetching
✅ **Error handling** - User-friendly error messages with retry
✅ **Responsive design** - Mobile-friendly grid layout
✅ **Smooth animations** - Framer Motion transitions

### File Locations

**signals-site**:
- `web/components/PerformanceMetricsWidget.tsx` - Main widget (379 lines) ✅
- `web/components/PerformanceMetricsCard.tsx` - Card component (301 lines) ✅

---

## 🚀 Quick Start

### 1. Enable Metrics (crypto-ai-bot)

```bash
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot

# Activate environment
conda activate crypto-bot

# Edit .env
echo "ENABLE_PERFORMANCE_METRICS=true" >> .env
echo "STARTING_EQUITY_USD=10000" >> .env
echo "TARGET_EQUITY_USD=20000" >> .env

# Start bot (metrics will auto-publish)
python main.py run --mode paper
```

### 2. Verify Redis Streams

```powershell
# Check Redis connection
redis-cli -u rediss://default:Salam78614**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 `
  --tls --cacert C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem `
  PING

# Check metrics streams
redis-cli -u rediss://default:Salam78614**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 `
  --tls --cacert C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem `
  XLEN metrics:performance

# Read latest metric
redis-cli -u rediss://default:Salam78614**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 `
  --tls --cacert C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem `
  XREVRANGE metrics:performance + - COUNT 1
```

### 3. Verify API Endpoints

```powershell
# Test REST endpoint
curl https://crypto-signals-api.fly.dev/metrics/performance

# Test SSE stream (PowerShell)
$url = "https://crypto-signals-api.fly.dev/metrics/performance/stream?heartbeat=30"
Invoke-WebRequest -Uri $url -Method Get
```

### 4. Verify Prometheus

```bash
# Access Prometheus metrics
curl http://localhost:9108/metrics | Select-String "aggressive_mode_score"
curl http://localhost:9108/metrics | Select-String "velocity_to_target"
curl http://localhost:9108/metrics | Select-String "days_remaining_estimate"
```

### 5. View in Browser

Navigate to your signals-site deployment where `PerformanceMetricsWidget` is integrated.

Expected behavior:
- Cards load with skeleton screens
- Data fetches from REST API
- SSE connection establishes
- Live updates appear every 30 seconds
- Sparkline charts update with history
- Trend arrows show up/down movement

---

## 📈 Grafana Dashboard (Optional)

If you want to visualize these metrics in Grafana:

```yaml
# grafana-dashboard.json
{
  "dashboard": {
    "title": "Trading Performance Metrics",
    "panels": [
      {
        "title": "Aggressive Mode Score",
        "targets": [
          {
            "expr": "aggressive_mode_score",
            "legendFormat": "Score"
          }
        ],
        "thresholds": [
          {"value": 2.0, "color": "green"},
          {"value": 1.5, "color": "green"},
          {"value": 1.0, "color": "yellow"},
          {"value": 0.5, "color": "red"}
        ]
      },
      {
        "title": "Velocity to Target",
        "targets": [
          {
            "expr": "velocity_to_target * 100",
            "legendFormat": "Progress %"
          }
        ]
      },
      {
        "title": "Days Remaining",
        "targets": [
          {
            "expr": "days_remaining_estimate",
            "legendFormat": "Days"
          }
        ]
      },
      {
        "title": "Current Equity",
        "targets": [
          {
            "expr": "current_equity_usd",
            "legendFormat": "Equity USD"
          }
        ]
      }
    ]
  }
}
```

---

## 🔍 Monitoring & Debugging

### Check Metrics Calculation

```python
# In crypto-ai-bot Python shell
from metrics.performance_metrics import PerformanceMetricsCalculator

calculator = PerformanceMetricsCalculator(
    starting_equity=10000,
    target_equity=20000,
)

# Mock trade data
trades = [
    {"status": "closed", "pnl_usd": 150},
    {"status": "closed", "pnl_usd": -80},
    {"status": "closed", "pnl_usd": 200},
    {"status": "closed", "pnl_usd": -60},
]

metrics = calculator.calculate_metrics(
    trades=trades,
    current_equity=10210,
)

print(f"Aggressive Score: {metrics.aggressive_mode_score:.2f}")
print(f"Velocity: {metrics.velocity_to_target:.2%}")
print(f"Days Remaining: {metrics.days_remaining_estimate:.1f}")
```

### Check Redis Streams

```powershell
# View all streams
redis-cli -u rediss://default:Salam78614**$$@... `
  --tls --cacert ... `
  KEYS "metrics:*"

# Count messages in performance stream
redis-cli -u rediss://default:Salam78614**$$@... `
  --tls --cacert ... `
  XLEN metrics:performance

# Read last 5 messages
redis-cli -u rediss://default:Salam78614**$$@... `
  --tls --cacert ... `
  XREVRANGE metrics:performance + - COUNT 5
```

### Check API Health

```bash
# Health check
curl https://crypto-signals-api.fly.dev/health

# Check if performance endpoint works
curl https://crypto-signals-api.fly.dev/metrics/performance

# Check SSE stream
curl -N https://crypto-signals-api.fly.dev/metrics/performance/stream
```

### Logs

**crypto-ai-bot**:
```bash
# Check metrics publishing logs
grep "Performance Metrics" logs/*.log
grep "aggressive_mode_score" logs/*.log
```

**signals-api**:
```bash
# Check SSE connections
fly logs --app crypto-signals-api | Select-String "Performance metrics SSE"
fly logs --app crypto-signals-api | Select-String "aggressive_mode_score"
```

---

## ⚙️ Customization

### Change Target Equity

```bash
# crypto-ai-bot/.env
STARTING_EQUITY_USD=10000
TARGET_EQUITY_USD=50000  # Changed from 20k to 50k
```

This will update:
- Velocity calculation (now 0.0 to 1.0 represents $10k to $50k)
- Days remaining estimate (projects to $50k)
- Dashboard display (shows "$X / $50,000")

### Change Update Frequency

```bash
# crypto-ai-bot/.env
METRICS_UPDATE_INTERVAL_SEC=10  # Update every 10 seconds (faster)
```

**Trade-off**: More frequent updates = higher Redis/CPU usage

### Change History Length

In `PerformanceMetricsWidget.tsx`:

```tsx
const MAX_HISTORY = 50; // Keep last 50 data points (was 20)
```

**Trade-off**: More history = smoother charts but more memory

### Disable Metrics

```bash
# crypto-ai-bot/.env
ENABLE_PERFORMANCE_METRICS=false
```

This stops:
- Background metric calculation
- Redis stream publishing
- Prometheus metric updates

API endpoints will return 404 when no data available.

---

## 🐛 Troubleshooting

### Metrics Not Showing in UI

**Check**:
1. Is bot running? `ps aux | grep python`
2. Are metrics enabled? `grep ENABLE_PERFORMANCE_METRICS .env`
3. Any trades yet? Metrics need ≥1 closed trade
4. Redis connected? Check bot logs for connection errors
5. API accessible? `curl https://crypto-signals-api.fly.dev/metrics/performance`
6. Environment variable set? Check `NEXT_PUBLIC_API_BASE_URL` in signals-site

### SSE Connection Fails

**Check**:
1. API endpoint exists: `curl https://crypto-signals-api.fly.dev/metrics/performance/stream`
2. Redis streams exist: `redis-cli ... KEYS "metrics:*"`
3. Browser console for errors
4. Network tab shows SSE connection
5. CORS configured (should be allowed by default)

### Prometheus Metrics Missing

**Check**:
1. Metrics server running: `curl http://localhost:9108/metrics`
2. Prometheus client installed: `pip install prometheus-client`
3. Metrics initialized: Check `performance_metrics.py` logs
4. No exceptions in metric update

### Incorrect Values

**Check**:
1. Trade data format correct (needs `status: "closed"` and `pnl_usd`)
2. Equity value accurate
3. Starting equity configured correctly
4. Time zone issues (all timestamps UTC)

---

## 📚 Reference

### Key Files

**crypto-ai-bot**:
- `metrics/performance_metrics.py` - Calculator
- `metrics/metrics_publisher.py` - Publisher
- `monitoring/metrics_exporter.py` - Prometheus

**signals-api**:
- `app/routers/performance_metrics.py` - Endpoints

**signals-site**:
- `web/components/PerformanceMetricsWidget.tsx` - Widget
- `web/components/PerformanceMetricsCard.tsx` - Card

### Redis Streams

- `metrics:performance` - Full snapshots (all metrics)
- `metrics:aggressive_mode_score` - Individual metric
- `metrics:velocity_to_target` - Individual metric
- `metrics:days_remaining` - Individual metric

### Environment Variables Summary

**crypto-ai-bot**:
```bash
ENABLE_PERFORMANCE_METRICS=true
STARTING_EQUITY_USD=10000
TARGET_EQUITY_USD=20000
METRICS_UPDATE_INTERVAL_SEC=30
METRICS_PORT=9108
METRICS_ADDR=0.0.0.0
```

**signals-api**: None required (uses Redis streams)

**signals-site**:
```bash
NEXT_PUBLIC_API_BASE_URL=https://crypto-signals-api.fly.dev
```

### API Endpoints Summary

- `GET /metrics/performance` - All metrics
- `GET /metrics/performance/aggressive-mode-score` - Aggressive score
- `GET /metrics/performance/velocity-to-target` - Velocity
- `GET /metrics/performance/days-remaining` - Days remaining
- `GET /metrics/performance/summary` - Human-readable summary
- `GET /metrics/performance/stream` - SSE real-time stream

---

## ✅ Status

| Component | Status | Implementation |
|-----------|--------|----------------|
| **crypto-ai-bot** | ✅ DONE | PerformanceMetricsCalculator + MetricsPublisher |
| **signals-api** | ✅ DONE | REST endpoints + SSE streaming |
| **signals-site** | ✅ DONE | Live dashboard with sparklines |
| **Redis Streams** | ✅ DONE | 4 streams configured |
| **Prometheus** | ✅ DONE | 6 metrics exported |
| **Documentation** | ✅ DONE | This guide |

**Everything is ready to use! Just enable the feature flag and start the bot.**

---

## 🚀 Next Steps

1. **Enable metrics** in crypto-ai-bot: Set `ENABLE_PERFORMANCE_METRICS=true`
2. **Run backtest** or **paper trading** to generate trade data
3. **Verify Redis** streams are populating
4. **Check API** endpoints return data
5. **View dashboard** in signals-site to see live updates

Your optimization journey to +25% annual returns now has **live performance tracking**! 📊🚀

---

**Last Updated**: 2025-11-08
**Author**: Senior Quant + Python + DevOps Team
