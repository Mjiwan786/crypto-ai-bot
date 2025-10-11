# Prometheus Acceptance Test

## Test Steps

1. **Start the bot with metrics enabled:**
   ```bash
   # Ensure the bot is running with metrics on port 9108
   python main.py --environment staging
   ```

2. **Start Prometheus with monitoring profile:**
   ```bash
   docker compose --profile monitoring up -d prometheus
   ```

3. **Verify Prometheus is running:**
   ```bash
   # Check container status
   docker compose --profile monitoring ps prometheus
   
   # Check logs
   docker compose --profile monitoring logs prometheus
   ```

4. **Access Prometheus UI:**
   - Open http://localhost:9090 in browser
   - Navigate to Status → Targets
   - Verify crypto-ai-bot target shows as "UP"

5. **Verify bot metrics are being scraped:**
   - In Prometheus UI, go to Graph
   - Query: `signals_published_total`
   - Query: `bot_heartbeat_seconds`
   - Query: `up{job="crypto-ai-bot"}`

## Expected Results

- ✅ Prometheus UI accessible at http://localhost:9090
- ✅ crypto-ai-bot target shows as "UP" in targets page
- ✅ Bot metrics are visible in Prometheus queries
- ✅ Self-monitoring shows Prometheus is healthy

## Troubleshooting

If the target shows as "DOWN":

1. **Check bot metrics endpoint:**
   ```bash
   curl http://localhost:9108/metrics
   ```

2. **Check Docker network connectivity:**
   ```bash
   # From Prometheus container
   docker exec crypto-prometheus wget -qO- http://host.docker.internal:9108/metrics
   ```

3. **Verify configuration:**
   ```bash
   # Check Prometheus config
   docker exec crypto-prometheus cat /etc/prometheus/prometheus.yml
   ```

4. **Check logs:**
   ```bash
   docker compose --profile monitoring logs prometheus
   ```
