# ===============================================
# Procfile for Crypto AI Bot
# Process management for Heroku, Railway, Render, etc.
# ===============================================

# Main trading worker (paper trading by default)
worker: python main.py run --mode paper

# Health check server (optional - runs on port 8080)
health: python health.py

# Live trading worker (ONLY enable if you have proper safeguards)
# Requires: MODE=live and LIVE_TRADING_CONFIRMATION="I-accept-the-risk"
# live_worker: python main.py run --mode live

# Alternative: Use scripts/start_trading_system.py
# worker: python scripts/start_trading_system.py --mode paper

# Prometheus metrics exporter (optional)
# metrics: python -m prometheus_client.exposition --port 9091
