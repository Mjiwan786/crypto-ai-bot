# Paper Trial Quick Reference

**One-page reference for paper trading trial deployment**

---

## Setup (Once)

```bash
conda activate crypto-bot
python scripts/setup_paper_trial.py
```

---

## Deploy

### Python Direct
```bash
conda activate crypto-bot
python scripts/run_paper_trial.py
```

### Docker
```bash
docker-compose --profile paper up -d
docker-compose --profile paper logs -f paper-bot
```

---

## Monitor

### Real-Time Dashboard
```bash
python scripts/monitor_paper_trial.py
```

### Metrics
```bash
curl http://localhost:9108/metrics
```

### Redis Signals
```bash
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem
> XLEN signals:paper
> XREVRANGE signals:paper + - COUNT 10
```

---

## Validate

### Daily
```bash
python scripts/validate_paper_trading.py --from-redis
```

### Weekly (Day 7, 14)
```bash
python scripts/validate_paper_trading.py \
  --from-redis \
  --start-date 2025-10-23 \
  --end-date $(date +%Y-%m-%d) \
  --output reports/paper_validation_day7.txt
```

---

## DoD Checklist

- [ ] PF ≥1.5 OR Win-rate ≥60%
- [ ] DD ≤15%
- [ ] Latency p95 <500ms
- [ ] No missed publishes
- [ ] 14-21 days runtime

---

## Key Metrics

| Metric | Target | Alert |
|--------|--------|-------|
| signals_published_total | >0 | N/A |
| publish_latency_ms (p95) | <500ms | >500ms |
| redis_publish_errors_total | 0 | >0 |
| bot_heartbeat_seconds | <60s ago | >120s |
| stream_lag_seconds | <1s | >5s |

---

## Troubleshooting

### No signals?
Wait 8+ hours for OHLCV cache to fill (100 bars @ 5m)

### High latency?
```bash
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem --latency
```

### Bot crashed?
```bash
tail -f logs/paper_trial_*.log
```

---

## Files

- **Guide:** `PAPER_TRIAL_E2E_GUIDE.md`
- **Setup:** `scripts/setup_paper_trial.py`
- **Deploy:** `scripts/run_paper_trial.py`
- **Monitor:** `scripts/monitor_paper_trial.py`
- **Validate:** `scripts/validate_paper_trading.py`
- **Dashboard:** `monitoring/grafana/paper_trial_dashboard.json`

---

## Go-Live

After 14-21 days, if DoD passed:
```bash
export MODE=live
export LIVE_TRADING_CONFIRMATION="I-accept-the-risk"
python scripts/start_trading_system.py
```

---

**Full docs:** `PAPER_TRIAL_E2E_GUIDE.md`
