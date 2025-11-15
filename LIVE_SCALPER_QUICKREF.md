# Live Scalper - Quick Reference Card

**Version:** 1.0 | **Status:** ✅ Production Ready

---

## 🚀 Quick Start

### Paper Mode (Safe)
```bash
conda activate crypto-bot
python scripts/run_live_scalper.py
```

### Live Mode (Real Money)
```bash
export LIVE_MODE=true
export LIVE_TRADING_CONFIRMATION="I confirm live trading"
python scripts/run_live_scalper.py --env-file .env.live
```

---

## 📋 Safety Rails

| Limit | Value | Action |
|-------|-------|--------|
| Daily Stop | -6% | Stop all trading |
| Daily Target | +2.5% | Stop to preserve gains |
| Portfolio Heat | 75% max | No new positions |
| BTC/USD Max | $5,000 | Per-pair cap |
| ETH/USD Max | $3,000 | Per-pair cap |

---

## ✅ Preflight Checks

```bash
# Run checks without trading
python scripts/run_live_scalper.py --dry-run
```

**Checks:**
- ✓ Redis TLS connection
- ✓ Kraken WebSocket
- ✓ Trading pairs validity
- ✓ Safety rails config

---

## 📊 Monitoring

### Health
```bash
curl http://localhost:8080/health
```

### Logs
```bash
tail -f logs/live_scalper.log
```

### Redis
```bash
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem \
  XREVRANGE signals:paper:BTC-USD + - COUNT 10
```

---

## ⚙️ Configuration

### Environment Variables
```bash
LIVE_MODE=false                # true for live
REDIS_URL=rediss://...         # TLS required
KRAKEN_API_KEY=...            # For live mode
KRAKEN_API_SECRET=...         # For live mode
```

### Config File
`config/live_scalper_config.yaml`

---

## 🛑 Emergency Stop

Press `Ctrl+C` for graceful shutdown

---

## 📖 Documentation

- **Full Guide:** `LIVE_SCALPER_GUIDE.md`
- **Deployment Summary:** `LIVE_SCALPER_DEPLOYMENT_SUMMARY.md`
- **Config:** `config/live_scalper_config.yaml`

---

## ⚠️ Safety Checklist

Before going live:
- [ ] 7+ days paper trading
- [ ] Safety rails tested
- [ ] Preflight checks passing
- [ ] Monitoring configured
- [ ] Emergency plan ready
- [ ] Start with small positions

---

**Status:** 🚀 Ready for Paper Testing
