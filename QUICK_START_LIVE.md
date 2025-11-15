# QUICK START - 24/7 LIVE SYSTEM

**Get your trading system running in 5 minutes**

---

## Option 1: Quick Start (Recommended for Testing)

### Step 1: Install PM2 (One-time setup)
```bash
npm install -g pm2
```

### Step 2: Start Everything
```bash
# PowerShell (Recommended)
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot
.\start_live_system.ps1

# Or CMD
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot
start_live_system.bat
```

### Step 3: Check Status
```bash
pm2 status
pm2 logs
```

### Step 4: View Your System
- **Trading Logs**: `pm2 logs bot-signal-processor`
- **API**: http://localhost:8000/health
- **Website**: http://localhost:3000
- **Metrics**: http://localhost:9100/metrics

---

## Option 2: Manual Start (Development)

### Terminal 1: Trading Bot
```bash
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot
conda activate crypto-bot
python scripts/start_trading_system.py
```

### Terminal 2: Signals API
```bash
cd C:\Users\Maith\OneDrive\Desktop\signals_api
conda activate signals-api
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Terminal 3: Signals Site
```bash
cd C:\Users\Maith\OneDrive\Desktop\signals-site\web
npm run dev
```

### Terminal 4: PnL Aggregator (Optional - for live tracking)
```bash
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot
conda activate crypto-bot
python monitoring/pnl_aggregator.py
```

---

## Health Check

### Run Full Health Check
```bash
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot
python scripts/health_check_all.py
```

**Expected Output:**
```
✅ Redis Cloud: OK
✅ Signals API: OK
✅ Signals Site: OK

Components OK: 3/3
✅ ALL SYSTEMS OPERATIONAL
```

---

## Common Commands

### PM2 Management
```bash
# View all services
pm2 status

# View logs
pm2 logs

# View specific service logs
pm2 logs bot-signal-processor

# Restart a service
pm2 restart bot-execution-agent

# Stop all
pm2 stop all

# Start all
pm2 start ecosystem.all.config.js

# Real-time monitoring
pm2 monit
```

### Generate Test Data
```bash
cd C:\Users\Maint\OneDrive\Desktop\crypto_ai_bot
conda activate crypto-bot

# Generate trades
python seed_trades_turbo.py

# Process into PnL
python process_trades_once.py

# Check data
python check_pnl_data.py
```

---

## Troubleshooting

### Problem: "PM2 not found"
```bash
# Install PM2
npm install -g pm2
```

### Problem: "Python not found"
```bash
# Activate conda environment
conda activate crypto-bot

# Or use full path in ecosystem.all.config.js
```

### Problem: "Redis connection failed"
```bash
# Check connectivity
python check_pnl_data.py

# Verify cert path
dir C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem
```

### Problem: "Port already in use"
```bash
# Find what's using the port
netstat -ano | findstr "8000"

# Kill the process (replace PID)
taskkill /PID <process_id> /F
```

### Problem: "No signals generated"
```bash
# Check Kraken connection
pm2 logs bot-kraken-ingestor

# Check signal processor
pm2 logs bot-signal-processor

# Verify Redis streams
python -c "import redis; r=redis.from_url('rediss://...'); print(r.xlen('md:trades'))"
```

---

## Safety Reminders ⚠️

### Before Going Live:

1. ✅ **Paper trade for 2+ weeks** (100+ trades)
2. ✅ **Verify win rate > 55%** and profit factor > 1.3
3. ✅ **Test all safety gates** (soft stop, hard halt)
4. ✅ **Secure API keys** (disable withdrawals!)
5. ✅ **Start small** ($1,000-$5,000 max)
6. ✅ **Monitor first 10 trades** closely
7. ✅ **Set alerts** for critical issues

### To Switch from PAPER to LIVE:

1. Edit `ecosystem.all.config.js`
2. Change `MODE: 'PAPER'` to `MODE: 'LIVE'`
3. Add Kraken API keys:
   ```javascript
   KRAKEN_API_KEY: 'your_key_here',
   KRAKEN_API_SECRET: 'your_secret_here'
   ```
4. Restart: `pm2 restart bot-execution-agent`
5. **MONITOR CLOSELY** for first hour!

---

## Access URLs

| Service | URL | Status |
|---------|-----|--------|
| **Signals Site** | http://localhost:3000 | PnL Charts, Performance |
| **Signals API** | http://localhost:8000 | REST API |
| **API Docs** | http://localhost:8000/docs | Swagger UI |
| **Health Check** | http://localhost:8000/health | System Status |
| **Prometheus** | http://localhost:9100/metrics | Metrics |

---

## File Locations

| File | Purpose |
|------|---------|
| `ecosystem.all.config.js` | PM2 configuration |
| `start_live_system.ps1` | PowerShell startup script |
| `start_live_system.bat` | CMD startup script |
| `scripts/health_check_all.py` | Health check tool |
| `LIVE_DEPLOYMENT_24_7_GUIDE.md` | Full deployment guide |
| `config/turbo_mode.yaml` | Turbo configuration |

---

## Support

- **Full Guide**: `LIVE_DEPLOYMENT_24_7_GUIDE.md`
- **Turbo Config**: `TURBO_MODE_IMPLEMENTATION_COMPLETE.md`
- **Health Check**: `python scripts/health_check_all.py`
- **PM2 Docs**: https://pm2.keymetrics.io/docs/

---

**Quick Start Time**: ~5 minutes
**Prerequisites**: Node.js, Python, conda environments
**Status**: Ready to Deploy

---

*Last Updated: 2025-11-02*
