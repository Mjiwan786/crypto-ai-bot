# Signals Dashboard Implementation Guide

**Status**: Backend Complete ✅ | Frontend Pending
**Date**: 2025-11-06
**Repos**: crypto-ai-bot, signals-api, signals-site

---

## Overview

Complete 3-tier live trading signals & health monitoring system:

```
crypto-ai-bot (Fly.io) → Redis Cloud (TLS) → signals-api (Fly.io) → signals-site (Vercel)
```

---

## ✅ Completed: crypto-ai-bot (Engine)

### 1. **Kraken WebSocket Metrics**
**File**: `utils/kraken_ws.py`

Publishes to `kraken:health` stream every 15s:
```json
{
  "timestamp": "1699288800.12",
  "messages_received": "1523",
  "reconnects": "0",
  "errors": "0",
  "circuit_breaker_trips": "0",
  "trades_per_minute": "45",
  "latency_avg": "12.3",
  "latency_p50": "11.5",
  "latency_p95": "23.7",
  "latency_p99": "45.2",
  "latency_max": "67.8",
  "cb_spread": "closed",
  "cb_latency": "closed",
  "cb_connection": "closed",
  "redis_memory_usage_percent": "23"
}
```

### 2. **System Metrics**
**File**: `orchestration/master_orchestrator.py` → `_performance_monitoring_task()`

Publishes to `system:metrics` stream every 30s:
```json
{
  "timestamp": "1699288800.45",
  "agents_active": "4",
  "total_trades": "123",
  "total_pnl": "456.78",
  "system_health": "healthy",
  "redis_lag_ms": "2.5",
  "last_signal_seconds_ago": "3.2",
  "stream_size_signals_paper": "1234",
  "stream_size_signals_live": "567",
  "stream_size_kraken_health": "89",
  "stream_size_ops_heartbeat": "45",
  "stream_size_metrics_pnl_equity": "678",
  "stream_size_system_metrics": "234"
}
```

### 3. **Heartbeat**
**File**: `orchestration/master_orchestrator.py` → `_heartbeat_publishing_task()`

Publishes to `ops:heartbeat` stream every 15s:
```json
{
  "ts": "1699288800123",
  "status": "healthy",
  "agents_active": "4",
  "uptime_seconds": "3600"
}
```

### 4. **PnL Equity**
**File**: `orchestration/master_orchestrator.py` → `_pnl_equity_publishing_task()`

Publishes to `metrics:pnl:equity` stream every 60s:
```json
{
  "ts": "1699288800123",
  "equity": "10456.78",
  "pnl": "456.78",
  "trades_count": "123"
}
```

### 5. **Signal Publishing**
**File**: `agents/core/signal_processor.py` → `ResilientPublisher`

- Rate-limited to 2 signals/sec
- Exponential backoff on Redis errors
- Tracks `last_publish_time` for health monitoring
- Publishes to `signals:paper` or `signals:live`

---

## ✅ Completed: signals-api (Gateway)

### 1. **SSE Streaming - Signals**
**Endpoint**: `GET /streams/sse?type=signals&mode=paper`

Streams from `signals:paper` or `signals:live`

### 2. **SSE Streaming - PnL**
**Endpoint**: `GET /streams/sse?type=pnl`

Streams from `metrics:pnl:equity`

### 3. **SSE Streaming - Health Metrics** ✨ NEW
**Endpoint**: `GET /streams/sse/health`

Streams from 3 sources:
- `system:metrics` → System health
- `kraken:health` → Kraken WS metrics
- `ops:heartbeat` → Heartbeat

**Event Format**:
```javascript
event: health
data: {
  "stream": "system:metrics",
  "data": {
    "timestamp": "1699288800.45",
    "agents_active": "4",
    "total_trades": "123",
    "redis_lag_ms": "2.5",
    "last_signal_seconds_ago": "3.2",
    ...
  },
  "_metadata": {
    "message_id": "1699288800123-0",
    "latency_ms": 45
  }
}
```

### 4. **Health & Status Endpoints**
- `GET /health` → Basic liveness check
- `GET /ready` → Readiness check with Redis validation

### 5. **Prometheus Metrics**
- `GET /metrics` → Prometheus-compatible metrics

---

## 📋 Pending: signals-site (Frontend)

### Required Components

#### 1. **Live Signal Feed Component**
**File**: `components/SignalFeed.tsx`

```tsx
import { useEffect, useState } from 'react';

interface Signal {
  pair: string;
  action: string;
  price: number;
  confidence: number;
  timestamp: string;
}

export default function SignalFeed({ mode = 'paper' }: { mode?: 'paper' | 'live' }) {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const eventSource = new EventSource(
      `https://crypto-signals-api.fly.dev/streams/sse?type=signals&mode=${mode}`
    );

    eventSource.addEventListener('connected', (e) => {
      console.log('Connected:', e.data);
      setConnected(true);
    });

    eventSource.addEventListener('signal', (e) => {
      const signal = JSON.parse(e.data);
      setSignals((prev) => [signal, ...prev].slice(0, 50)); // Keep last 50
    });

    eventSource.onerror = (err) => {
      console.error('SSE Error:', err);
      setConnected(false);
    };

    return () => eventSource.close();
  }, [mode]);

  return (
    <div className="signal-feed">
      <div className="status">
        {connected ? '🟢 Connected' : '🔴 Disconnected'}
      </div>
      <ul>
        {signals.map((sig, idx) => (
          <li key={idx}>
            <span className={`action ${sig.action}`}>{sig.action.toUpperCase()}</span>
            <span className="pair">{sig.pair}</span>
            <span className="price">${sig.price}</span>
            <span className="confidence">{(sig.confidence * 100).toFixed(0)}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

#### 2. **System Health Dashboard Component**
**File**: `components/HealthDashboard.tsx`

```tsx
import { useEffect, useState } from 'react';

interface HealthMetrics {
  'system:metrics'?: {
    redis_lag_ms?: string;
    last_signal_seconds_ago?: string;
    agents_active?: string;
    total_trades?: string;
    system_health?: string;
  };
  'kraken:health'?: {
    latency_avg?: string;
    latency_p95?: string;
    circuit_breaker_trips?: string;
    cb_spread?: string;
    cb_latency?: string;
  };
  'ops:heartbeat'?: {
    status?: string;
    uptime_seconds?: string;
  };
}

export default function HealthDashboard() {
  const [metrics, setMetrics] = useState<HealthMetrics>({});
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const eventSource = new EventSource(
      'https://crypto-signals-api.fly.dev/streams/sse/health'
    );

    eventSource.addEventListener('connected', () => {
      setConnected(true);
    });

    eventSource.addEventListener('health', (e) => {
      const { stream, data } = JSON.parse(e.data);
      setMetrics((prev) => ({
        ...prev,
        [stream]: data
      }));
    });

    eventSource.onerror = () => {
      setConnected(false);
    };

    return () => eventSource.close();
  }, []);

  const systemMetrics = metrics['system:metrics'];
  const krakenHealth = metrics['kraken:health'];
  const heartbeat = metrics['ops:heartbeat'];

  return (
    <div className="health-dashboard">
      <h2>System Health {connected ? '🟢' : '🔴'}</h2>

      <div className="metrics-grid">
        {/* System Metrics */}
        <div className="metric-card">
          <h3>System</h3>
          <div>Health: <strong>{systemMetrics?.system_health || 'unknown'}</strong></div>
          <div>Redis Lag: <strong>{systemMetrics?.redis_lag_ms || '—'}ms</strong></div>
          <div>Last Signal: <strong>{systemMetrics?.last_signal_seconds_ago || '—'}s ago</strong></div>
          <div>Active Agents: <strong>{systemMetrics?.agents_active || '—'}</strong></div>
          <div>Total Trades: <strong>{systemMetrics?.total_trades || '0'}</strong></div>
        </div>

        {/* Kraken WebSocket Health */}
        <div className="metric-card">
          <h3>Kraken WebSocket</h3>
          <div>Avg Latency: <strong>{krakenHealth?.latency_avg || '—'}ms</strong></div>
          <div>P95 Latency: <strong>{krakenHealth?.latency_p95 || '—'}ms</strong></div>
          <div>Circuit Breaker Trips: <strong>{krakenHealth?.circuit_breaker_trips || '0'}</strong></div>
          <div>Spread CB: <strong className={`cb-${krakenHealth?.cb_spread}`}>{krakenHealth?.cb_spread || '—'}</strong></div>
          <div>Latency CB: <strong className={`cb-${krakenHealth?.cb_latency}`}>{krakenHealth?.cb_latency || '—'}</strong></div>
        </div>

        {/* Heartbeat */}
        <div className="metric-card">
          <h3>Heartbeat</h3>
          <div>Status: <strong>{heartbeat?.status || '—'}</strong></div>
          <div>Uptime: <strong>{heartbeat?.uptime_seconds ? `${Math.floor(Number(heartbeat.uptime_seconds) / 60)}m` : '—'}</strong></div>
        </div>
      </div>
    </div>
  );
}
```

#### 3. **PnL Chart Component**
**File**: `components/PnLChart.tsx`

```tsx
import { useEffect, useState } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

interface PnLPoint {
  ts: string;
  equity: string;
  pnl: string;
  trades_count: string;
}

export default function PnLChart() {
  const [pnlData, setPnlData] = useState<PnLPoint[]>([]);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const eventSource = new EventSource(
      'https://crypto-signals-api.fly.dev/streams/sse?type=pnl'
    );

    eventSource.addEventListener('connected', () => {
      setConnected(true);
    });

    eventSource.addEventListener('pnl', (e) => {
      const data = JSON.parse(e.data);
      setPnlData((prev) => [...prev, data].slice(-100)); // Keep last 100 points
    });

    eventSource.onerror = () => {
      setConnected(false);
    };

    return () => eventSource.close();
  }, []);

  const chartData = pnlData.map((point) => ({
    time: new Date(Number(point.ts)).toLocaleTimeString(),
    equity: Number(point.equity),
    pnl: Number(point.pnl)
  }));

  const currentPnL = pnlData[pnlData.length - 1];

  return (
    <div className="pnl-chart">
      <h2>P&L {connected ? '🟢' : '🔴'}</h2>

      <div className="pnl-summary">
        <div>Equity: <strong>${currentPnL?.equity || '10000.00'}</strong></div>
        <div>P&L: <strong className={Number(currentPnL?.pnl || 0) >= 0 ? 'positive' : 'negative'}>
          ${currentPnL?.pnl || '0.00'}
        </strong></div>
        <div>Trades: <strong>{currentPnL?.trades_count || '0'}</strong></div>
      </div>

      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="time" />
          <YAxis />
          <Tooltip />
          <Line type="monotone" dataKey="equity" stroke="#8884d8" />
          <Line type="monotone" dataKey="pnl" stroke="#82ca9d" />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
```

#### 4. **Main Dashboard Page**
**File**: `pages/dashboard.tsx`

```tsx
import SignalFeed from '@/components/SignalFeed';
import HealthDashboard from '@/components/HealthDashboard';
import PnLChart from '@/components/PnLChart';

export default function Dashboard() {
  return (
    <div className="dashboard-layout">
      <h1>Crypto AI Bot - Live Dashboard</h1>

      <div className="grid-layout">
        <div className="col-main">
          <SignalFeed mode="paper" />
        </div>

        <div className="col-sidebar">
          <HealthDashboard />
          <PnLChart />
        </div>
      </div>
    </div>
  );
}
```

---

## 🧪 Testing

### Test Bot → Redis Publishing

```bash
# In crypto-ai-bot repo
conda activate crypto-bot

# Run the bot
python -m main run --mode paper

# Check health endpoint
curl http://localhost:8080/health

# In another terminal, check Redis streams
redis-cli -u redis://default:****@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 --tls --cacert config/certs/redis_ca.pem

# Check streams
XLEN system:metrics
XLEN kraken:health
XLEN ops:heartbeat
XLEN metrics:pnl:equity
XLEN signals:paper

# Read latest from each
XREVRANGE system:metrics + - COUNT 1
XREVRANGE kraken:health + - COUNT 1
XREVRANGE ops:heartbeat + - COUNT 1
```

### Test API → SSE Streaming

```bash
# Test signals SSE
curl -N https://crypto-signals-api.fly.dev/streams/sse?type=signals&mode=paper

# Test PnL SSE
curl -N https://crypto-signals-api.fly.dev/streams/sse?type=pnl

# Test health metrics SSE (NEW)
curl -N https://crypto-signals-api.fly.dev/streams/sse/health

# Test health endpoint
curl https://crypto-signals-api.fly.dev/health

# Test Prometheus metrics
curl https://crypto-signals-api.fly.dev/metrics
```

---

## 📊 Definition of Done

### ✅ Completed
1. ✅ Engine publishes signals & metrics to Redis (TLS)
2. ✅ Engine publishes Kraken WS metrics (latency, circuit breakers)
3. ✅ Engine publishes system health (uptime, stream sizes, Redis lag, last signal time)
4. ✅ Engine publishes heartbeat every 15s
5. ✅ Engine publishes PnL equity every 60s
6. ✅ API has SSE endpoint for signals
7. ✅ API has SSE endpoint for PnL
8. ✅ API has SSE endpoint for health metrics
9. ✅ API has health & readiness endpoints
10. ✅ API has Prometheus metrics

### ⏳ Pending (Frontend)
11. ⏳ Site shows live signals without refresh
12. ⏳ Site shows system health dashboard (uptime, lag, latency, circuit breakers)
13. ⏳ Site shows live PnL chart
14. ⏳ End-to-end test (bot → Redis → API → site)

---

## 🚀 Next Steps

1. **Implement Frontend Components**:
   - Copy the React/Next.js components above to `signals-site`
   - Install dependencies: `recharts` for charts
   - Style components to match your design

2. **Deploy & Test**:
   - Push signals-site to Vercel
   - Test SSE connections from browser
   - Verify all metrics display correctly

3. **Monitoring**:
   - Set up Grafana dashboard using `/metrics` endpoint
   - Configure alerts for degraded health
   - Monitor SSE connection counts

4. **Documentation**:
   - API documentation (OpenAPI)
   - User guide for dashboard
   - Troubleshooting guide

---

## 📚 Resources

- **Redis Cloud Connection**: `rediss://default:****@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818`
- **API URL**: `https://crypto-signals-api.fly.dev`
- **Site URL**: `https://aipredictedsignals.cloud`
- **PRD References**:
  - PRD-001: crypto-ai-bot Core Intelligence Engine
  - PRD-002: Signals-API Gateway & Middleware
  - PRD-003: Signals-Site Front-End SaaS Portal

---

**Status**: Backend implementation complete ✅
**Next**: Frontend dashboard implementation
**ETA**: 4-6 hours for frontend components + styling
