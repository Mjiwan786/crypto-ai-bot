# 24/7 LIVE DEPLOYMENT GUIDE

**Complete guide to deploying the crypto trading system for continuous operation**

---

## Table of Contents

1. [System Architecture](#system-architecture)
2. [Prerequisites](#prerequisites)
3. [Safety Checks](#safety-checks)
4. [Deployment Steps](#deployment-steps)
5. [Process Management](#process-management)
6. [Monitoring & Alerts](#monitoring--alerts)
7. [Troubleshooting](#troubleshooting)

---

## System Architecture

### Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     LIVE TRADING SYSTEM                         │
└─────────────────────────────────────────────────────────────────┘

┌──────────────────┐      ┌──────────────────┐      ┌─────────────┐
│  crypto_ai_bot   │─────▶│   signals-api    │─────▶│signals-site │
│  (Trading Core)  │      │  (API Gateway)   │      │ (Frontend)  │
└──────────────────┘      └──────────────────┘      └─────────────┘
         │                         │                        │
         │                         │                        │
         ▼                         ▼                        ▼
┌─────────────────────────────────────────────────────────────────┐
│                    REDIS CLOUD (TLS)                            │
│  • trades:closed  • pnl:equity  • signals:paper/live            │
│  • md:trades  • kraken:status  • metrics:*                      │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│              KRAKEN EXCHANGE (WebSocket + REST)                 │
└─────────────────────────────────────────────────────────────────┘
```

### Components

| Component | Purpose | Language | Port | 24/7? |
|-----------|---------|----------|------|-------|
| **crypto_ai_bot** | Signal generation, trading execution, PnL tracking | Python | - | ✅ Yes |
| **signals-api** | REST API gateway, auth, rate limiting | Python (FastAPI) | 8000 | ✅ Yes |
| **signals-site** | Web UI, charts, real-time updates | Next.js | 3000 | ✅ Yes |
| **Redis Cloud** | Message broker, data store | Redis | 19818 | ✅ Managed |
| **Kraken** | Exchange connectivity | - | - | ✅ External |

---

## Prerequisites

### 1. Environment Setup

#### crypto_ai_bot
```bash
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot
conda activate crypto-bot
pip install -r requirements.txt
```

#### signals-api
```bash
cd C:\Users\Maith\OneDrive\Desktop\signals_api
conda activate signals-api
pip install -r requirements.txt
```

#### signals-site
```bash
cd C:\Users\Maith\OneDrive\Desktop\signals-site\web
npm install
```

### 2. Environment Variables

#### crypto_ai_bot (.env.prod)
```bash
# Trading Mode
MODE=PAPER  # Start with PAPER, switch to LIVE after testing

# Redis Cloud
REDIS_URL=rediss://default:&lt;REDIS_PASSWORD&gt;%2A%2A%24%24@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818
REDIS_CA_CERT=C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem

# Kraken API (for live trading only)
KRAKEN_API_KEY=your_api_key_here
KRAKEN_API_SECRET=your_api_secret_here

# PnL Settings
START_EQUITY=10000.0
USE_PANDAS=true
PNL_METRICS_PORT=9100

# Configuration
CONFIG_FILE=config/turbo_mode.yaml  # or config/settings.yaml for conservative
```

#### signals-api (.env.prod)
```bash
# Application
APP_ENV=prod
APP_HOST=0.0.0.0
APP_PORT=8000

# Redis Cloud
REDIS_URL=rediss://default:&lt;REDIS_PASSWORD&gt;%2A%2A%24%24@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818
REDIS_SSL=true
REDIS_CA_CERT=/path/to/ca.crt

# Streams
SIGNALS_STREAM_ACTIVE=signals:paper  # or signals:live
STREAM_PREFIX=kraken

# Security (REQUIRED for production)
JWT_SECRET=your_jwt_secret_here
JWT_ALGORITHM=RS256

# CORS
CORS_ALLOW_ORIGINS=https://aipredictedsignals.cloud,https://www.aipredictedsignals.cloud

# Supabase (for user management)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_anon_key_here

# Monitoring
PROMETHEUS_ENABLED=true
```

#### signals-site (.env.production)
```bash
# API
NEXT_PUBLIC_API_URL=https://signals-api-gateway.fly.dev
NEXT_PUBLIC_WS_URL=wss://signals-api-gateway.fly.dev

# Redis (if direct access needed)
REDIS_URL=rediss://default:&lt;REDIS_PASSWORD&gt;%2A%2A%24%24@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818

# Analytics
NEXT_PUBLIC_GOOGLE_ANALYTICS=your_ga_id_here
```

---

## Safety Checks

### Before Going Live - CRITICAL ⚠️

#### 1. Paper Trading Validation (MANDATORY)
```bash
# Run paper trading for at least 1-2 weeks
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot
conda activate crypto-bot

# Set MODE=PAPER in .env
echo "MODE=PAPER" > .env.prod

# Start paper trading
python scripts/start_trading_system.py --config turbo_mode
```

**Minimum Requirements Before Live**:
- ✅ 100+ paper trades executed
- ✅ Win rate > 55%
- ✅ Profit factor > 1.3
- ✅ Max drawdown < 8%
- ✅ No critical errors for 48+ hours
- ✅ All safety gates tested (soft stop, hard halt)

#### 2. API Key Security
```bash
# Kraken API key permissions (MINIMUM REQUIRED):
✅ Query Funds
✅ Query Open Orders & Trades
✅ Query Closed Orders & Trades
✅ Create & Modify Orders
❌ Withdraw Funds (MUST BE DISABLED!)
❌ Transfer Funds (MUST BE DISABLED!)

# Set rate limits on Kraken:
- API Call Volume: 15/second
- Order Rate: 60/minute
```

#### 3. Risk Limits Configuration
```yaml
# In config/turbo_mode.yaml or config/settings.yaml
risk:
  # CRITICAL: Start with small amounts!
  max_position_pct: 0.05  # 5% max per position
  day_max_drawdown_pct: 4.0  # Stop trading at -4% daily
  max_concurrent_positions: 3  # Limit exposure

  # Daily limits
  max_daily_trades: 50
  max_daily_loss_pct: 5.0
```

---

## Deployment Steps

### Phase 1: Deploy crypto_ai_bot (Trading Core)

#### Step 1: Configure Trading System
```bash
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot
conda activate crypto-bot

# Create production config
cp .env.dev .env.prod

# Edit .env.prod with your settings
notepad .env.prod
```

#### Step 2: Start Core Services

**Option A: Manual Start (Testing)**
```bash
# Terminal 1: Kraken Data Ingestor (Market Data)
python -m agents.infrastructure.kraken_ingestor

# Terminal 2: Signal Processor (AI/Trading Logic)
python -m agents.core.signal_processor

# Terminal 3: Execution Agent (Order Management)
python -m agents.core.execution_agent --mode paper

# Terminal 4: PnL Aggregator (Performance Tracking)
python monitoring/pnl_aggregator.py
```

**Option B: Process Manager (Production - Recommended)**
```bash
# Using PM2 (Node.js process manager)
npm install -g pm2

# Create ecosystem file
cat > ecosystem.config.js << 'EOF'
module.exports = {
  apps: [
    {
      name: 'kraken-ingestor',
      script: 'conda',
      args: 'run -n crypto-bot python -m agents.infrastructure.kraken_ingestor',
      cwd: 'C:\\Users\\Maith\\OneDrive\\Desktop\\crypto_ai_bot',
      autorestart: true,
      max_restarts: 10,
      min_uptime: '10s',
      env: {
        REDIS_URL: 'rediss://default:&lt;REDIS_PASSWORD&gt;%2A%2A%24%24@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818'
      }
    },
    {
      name: 'signal-processor',
      script: 'conda',
      args: 'run -n crypto-bot python -m agents.core.signal_processor',
      cwd: 'C:\\Users\\Maith\\OneDrive\\Desktop\\crypto_ai_bot',
      autorestart: true,
      max_restarts: 10,
      min_uptime: '10s'
    },
    {
      name: 'execution-agent',
      script: 'conda',
      args: 'run -n crypto-bot python -m agents.core.execution_agent --mode paper',
      cwd: 'C:\\Users\\Maith\\OneDrive\\Desktop\\crypto_ai_bot',
      autorestart: true,
      max_restarts: 5,  // Lower for safety
      min_uptime: '30s'
    },
    {
      name: 'pnl-aggregator',
      script: 'conda',
      args: 'run -n crypto-bot python monitoring/pnl_aggregator.py',
      cwd: 'C:\\Users\\Maith\\OneDrive\\Desktop\\crypto_ai_bot',
      autorestart: true,
      max_restarts: 10,
      min_uptime: '10s'
    }
  ]
}
EOF

# Start all services
pm2 start ecosystem.config.js

# View logs
pm2 logs

# Check status
pm2 status
```

**Option C: Docker Compose (Production - Alternative)**
```bash
# Build and start
docker-compose -f docker-compose.prod.yml up -d

# View logs
docker-compose logs -f

# Check status
docker-compose ps
```

### Phase 2: Deploy signals-api (API Gateway)

#### Step 1: Configure API
```bash
cd C:\Users\Maith\OneDrive\Desktop\signals_api
conda activate signals-api

# Set production environment
cp .env.example .env.prod
notepad .env.prod  # Edit with production values
```

#### Step 2: Start API Server

**Local Development:**
```bash
conda activate signals-api
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Production (PM2):**
```bash
pm2 start "conda run -n signals-api uvicorn app.main:app --host 0.0.0.0 --port 8000" --name signals-api
pm2 save
```

**Production (Docker):**
```bash
docker-compose -f docker-compose.prod.yml up -d signals-api
```

**Production (Fly.io - Recommended for 24/7):**
```bash
# Install Fly CLI
powershell -Command "iwr https://fly.io/install.ps1 -useb | iex"

# Login
fly auth login

# Deploy
fly deploy

# Check status
fly status

# View logs
fly logs
```

### Phase 3: Deploy signals-site (Frontend)

#### Step 1: Build Production
```bash
cd C:\Users\Maith\OneDrive\Desktop\signals-site\web

# Install dependencies
npm install

# Build production bundle
npm run build
```

#### Step 2: Deploy

**Option A: Vercel (Recommended - Free Tier)**
```bash
# Install Vercel CLI
npm install -g vercel

# Login
vercel login

# Deploy
vercel --prod

# Custom domain (optional)
vercel domains add aipredictedsignals.cloud
```

**Option B: Local Production Server**
```bash
# Start production server
npm run start

# Or with PM2
pm2 start npm --name signals-site -- start
pm2 save
```

**Option C: Docker**
```bash
docker-compose -f docker-compose.prod.yml up -d signals-site
```

---

## Process Management

### Using PM2 (Recommended for Windows)

#### Install PM2
```bash
npm install -g pm2
pm2 install pm2-windows-startup
pm2-startup install
```

#### Create Master Ecosystem File

**File**: `ecosystem.all.config.js`
```javascript
module.exports = {
  apps: [
    // ============================================
    // CRYPTO AI BOT (Trading Core)
    // ============================================
    {
      name: 'bot-kraken-ingestor',
      script: 'python',
      args: '-m agents.infrastructure.kraken_ingestor',
      cwd: 'C:\\Users\\Maith\\OneDrive\\Desktop\\crypto_ai_bot',
      interpreter: 'C:\\Users\\Maith\\.conda\\envs\\crypto-bot\\python.exe',
      autorestart: true,
      max_restarts: 10,
      min_uptime: '10s',
      restart_delay: 5000,
      env: {
        REDIS_URL: 'rediss://default:&lt;REDIS_PASSWORD&gt;%2A%2A%24%24@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818',
        MODE: 'PAPER'
      }
    },
    {
      name: 'bot-signal-processor',
      script: 'python',
      args: '-m agents.core.signal_processor',
      cwd: 'C:\\Users\\Maith\\OneDrive\\Desktop\\crypto_ai_bot',
      interpreter: 'C:\\Users\\Maith\\.conda\\envs\\crypto-bot\\python.exe',
      autorestart: true,
      max_restarts: 10,
      min_uptime: '10s',
      restart_delay: 5000
    },
    {
      name: 'bot-execution-agent',
      script: 'python',
      args: '-m agents.core.execution_agent --mode paper',
      cwd: 'C:\\Users\\Maith\\OneDrive\\Desktop\\crypto_ai_bot',
      interpreter: 'C:\\Users\\Maith\\.conda\\envs\\crypto-bot\\python.exe',
      autorestart: true,
      max_restarts: 5,
      min_uptime: '30s',
      restart_delay: 10000
    },
    {
      name: 'bot-pnl-aggregator',
      script: 'python',
      args: 'monitoring/pnl_aggregator.py',
      cwd: 'C:\\Users\\Maith\\OneDrive\\Desktop\\crypto_ai_bot',
      interpreter: 'C:\\Users\\Maith\\.conda\\envs\\crypto-bot\\python.exe',
      autorestart: true,
      max_restarts: 10,
      min_uptime: '10s',
      restart_delay: 5000
    },

    // ============================================
    // SIGNALS API (Gateway)
    // ============================================
    {
      name: 'signals-api',
      script: 'uvicorn',
      args: 'app.main:app --host 0.0.0.0 --port 8000',
      cwd: 'C:\\Users\\Maith\\OneDrive\\Desktop\\signals_api',
      interpreter: 'C:\\Users\\Maith\\.conda\\envs\\signals-api\\python.exe',
      autorestart: true,
      max_restarts: 10,
      min_uptime: '10s',
      restart_delay: 5000,
      env: {
        APP_ENV: 'prod'
      }
    },

    // ============================================
    // SIGNALS SITE (Frontend)
    // ============================================
    {
      name: 'signals-site',
      script: 'npm',
      args: 'start',
      cwd: 'C:\\Users\\Maith\\OneDrive\\Desktop\\signals-site\\web',
      autorestart: true,
      max_restarts: 10,
      min_uptime: '10s',
      restart_delay: 5000,
      env: {
        NODE_ENV: 'production',
        PORT: 3000
      }
    }
  ]
}
```

#### Start All Services
```bash
# Start everything
pm2 start ecosystem.all.config.js

# Save configuration (auto-start on boot)
pm2 save

# Enable startup script
pm2 startup

# View status
pm2 status

# View logs
pm2 logs

# View logs for specific service
pm2 logs bot-signal-processor

# Restart specific service
pm2 restart bot-execution-agent

# Stop all
pm2 stop all

# Delete all
pm2 delete all
```

### Using Windows Services (Alternative)

#### Install NSSM (Non-Sucking Service Manager)
```powershell
# Download NSSM from https://nssm.cc/download
choco install nssm

# Install trading bot as service
nssm install CryptoTradingBot "C:\Users\Maith\.conda\envs\crypto-bot\python.exe" "-m agents.core.signal_processor"
nssm set CryptoTradingBot AppDirectory "C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot"
nssm set CryptoTradingBot AppEnvironmentExtra REDIS_URL=rediss://...

# Start service
nssm start CryptoTradingBot

# Check status
nssm status CryptoTradingBot
```

---

## Monitoring & Alerts

### 1. Health Checks

**Create**: `scripts/health_check_all.py`
```python
#!/usr/bin/env python3
"""
Comprehensive health check for all 3 systems
"""
import sys
import requests
import redis
import json

# Configuration
REDIS_URL = "rediss://default:&lt;REDIS_PASSWORD&gt;%2A%2A%24%24@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818"
REDIS_CERT = r"C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem"
API_URL = "http://localhost:8000"
SITE_URL = "http://localhost:3000"

def check_redis():
    """Check Redis connectivity and data freshness"""
    try:
        client = redis.from_url(
            REDIS_URL,
            ssl_ca_certs=REDIS_CERT,
            decode_responses=True,
            socket_timeout=5
        )
        client.ping()

        # Check stream activity
        trades_len = client.xlen("trades:closed")
        equity_len = client.xlen("pnl:equity")

        # Check data freshness
        latest = client.get("pnl:equity:latest")
        if latest:
            data = json.loads(latest)
            import time
            age_seconds = time.time() - (data['ts'] / 1000)
            fresh = age_seconds < 300  # Less than 5 minutes old
        else:
            fresh = False

        return {
            "status": "✅ OK",
            "trades": trades_len,
            "equity_points": equity_len,
            "data_fresh": fresh
        }
    except Exception as e:
        return {"status": f"❌ FAIL: {e}"}

def check_api():
    """Check signals-api health"""
    try:
        resp = requests.get(f"{API_URL}/health", timeout=5)
        if resp.status_code == 200:
            return {"status": "✅ OK", "data": resp.json()}
        else:
            return {"status": f"❌ FAIL: HTTP {resp.status_code}"}
    except Exception as e:
        return {"status": f"❌ FAIL: {e}"}

def check_site():
    """Check signals-site availability"""
    try:
        resp = requests.get(SITE_URL, timeout=5)
        if resp.status_code == 200:
            return {"status": "✅ OK"}
        else:
            return {"status": f"❌ FAIL: HTTP {resp.status_code}"}
    except Exception as e:
        return {"status": f"❌ FAIL: {e}"}

def main():
    print("=" * 60)
    print("SYSTEM HEALTH CHECK")
    print("=" * 60)

    results = {
        "Redis Cloud": check_redis(),
        "Signals API": check_api(),
        "Signals Site": check_site()
    }

    for component, result in results.items():
        print(f"\n{component}:")
        for key, value in result.items():
            print(f"  {key}: {value}")

    # Exit code
    all_ok = all("✅" in str(r.get("status", "")) for r in results.values())
    sys.exit(0 if all_ok else 1)

if __name__ == "__main__":
    main()
```

**Run Health Check**:
```bash
python scripts/health_check_all.py
```

### 2. Automated Monitoring

**Create**: `scripts/monitor_loop.py`
```python
#!/usr/bin/env python3
"""
Continuous monitoring loop - runs every 60 seconds
Sends alerts if issues detected
"""
import time
import subprocess
import smtplib
from email.mime.text import MIMEText

def send_alert(subject, body):
    """Send email alert"""
    msg = MIMEText(body)
    msg['Subject'] = f"[CRYPTO BOT ALERT] {subject}"
    msg['From'] = "bot@yourdomain.com"
    msg['To'] = "your@email.com"

    # Use your SMTP server
    # smtp = smtplib.SMTP('smtp.gmail.com', 587)
    # smtp.starttls()
    # smtp.login("your@email.com", "password")
    # smtp.send_message(msg)
    # smtp.quit()

    print(f"ALERT: {subject}")
    print(body)

def main():
    print("Starting monitoring loop...")
    failures = 0

    while True:
        # Run health check
        result = subprocess.run(
            ["python", "scripts/health_check_all.py"],
            capture_output=True
        )

        if result.returncode != 0:
            failures += 1
            if failures >= 3:  # 3 consecutive failures
                send_alert(
                    "System Health Check Failed",
                    f"Health check failed {failures} times\n\n{result.stdout.decode()}"
                )
        else:
            failures = 0  # Reset counter

        time.sleep(60)  # Check every 60 seconds

if __name__ == "__main__":
    main()
```

**Start Monitor**:
```bash
pm2 start scripts/monitor_loop.py --name health-monitor
```

### 3. Grafana Dashboard (Optional)

```bash
# Install Prometheus & Grafana
docker run -d -p 9090:9090 prom/prometheus
docker run -d -p 3001:3000 grafana/grafana

# Configure Prometheus to scrape metrics
# Visit http://localhost:9090
# Add scrape targets: localhost:9100 (PnL aggregator)

# Import Grafana dashboard
# Visit http://localhost:3001
# Use dashboard from: monitoring/grafana/paper_trial_dashboard.json
```

---

## Troubleshooting

### Common Issues

#### 1. Services Won't Start
```bash
# Check logs
pm2 logs <service-name>

# Check if ports are in use
netstat -ano | findstr "8000"  # API
netstat -ano | findstr "3000"  # Site

# Check Redis connectivity
python check_pnl_data.py
```

#### 2. No Signals Generated
```bash
# Check Kraken connection
python -c "from agents.infrastructure.kraken_ingestor import test_connection; test_connection()"

# Check signal processor logs
pm2 logs bot-signal-processor

# Verify market data streaming
redis-cli -u $REDIS_URL --tls --cacert <cert> XLEN kraken:trades:BTC/USD
```

#### 3. PnL Charts Not Updating
```bash
# Check trades are being published
python check_pnl_data.py

# Check PnL aggregator is running
pm2 list | grep pnl-aggregator

# Manually process trades
python process_trades_once.py
```

#### 4. High Memory/CPU Usage
```bash
# Check resource usage
pm2 monit

# Restart specific service
pm2 restart bot-signal-processor

# Limit memory (in ecosystem.config.js)
max_memory_restart: '500M'
```

---

## Going LIVE Checklist

### Pre-Launch (Do This First!)

- [ ] **Paper trading complete** (2+ weeks, 100+ trades)
- [ ] **Win rate > 55%**, Profit Factor > 1.3
- [ ] **All safety gates tested** (soft stop, hard halt, killswitch)
- [ ] **API keys secured** (withdraw disabled, rate limits set)
- [ ] **Risk limits configured** (max 5% per trade, 4% daily DD)
- [ ] **Backup funds** (start with $1,000-$5,000, NOT your life savings!)
- [ ] **Monitoring setup** (health checks, alerts)
- [ ] **Emergency contacts** (phone alerts for critical issues)

### Launch Day

- [ ] **Start with PAPER mode** (final validation)
- [ ] **Switch to LIVE mode** (set MODE=LIVE in .env)
- [ ] **Start with 1 position** (max_concurrent_positions: 1)
- [ ] **Monitor first 10 trades** (watch logs, verify execution)
- [ ] **Gradually increase** (add positions, increase size)

### Post-Launch (First Week)

- [ ] **Daily PnL review** (check performance vs targets)
- [ ] **Log analysis** (look for errors, warnings)
- [ ] **Strategy tuning** (adjust parameters based on live data)
- [ ] **Risk validation** (ensure stops working correctly)

---

## Quick Start Commands

### Start Everything (Development)
```bash
# Terminal 1: Trading Bot
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot
conda activate crypto-bot
python scripts/start_trading_system.py

# Terminal 2: Signals API
cd C:\Users\Maith\OneDrive\Desktop\signals_api
conda activate signals-api
uvicorn app.main:app --reload

# Terminal 3: Signals Site
cd C:\Users\Maith\OneDrive\Desktop\signals-site\web
npm run dev
```

### Start Everything (Production)
```bash
# One command to rule them all
pm2 start ecosystem.all.config.js
pm2 save
pm2 logs
```

### Stop Everything
```bash
pm2 stop all
```

### View Status
```bash
pm2 status
pm2 monit  # Real-time monitoring
```

---

## Support

- **Documentation**: See `docs/` folder in each repo
- **Health Checks**: `python scripts/health_check_all.py`
- **Logs**: `pm2 logs` or check `logs/` folder
- **Emergency Stop**: `pm2 stop all` or press Ctrl+C

---

**Status**: Ready for Deployment
**Recommended Path**: Paper → PM2 → Cloud (Fly.io/Vercel)
**Safety Level**: 🟡 Medium Risk (start with paper trading!)

---

*Last Updated: 2025-11-02*
