#!/bin/bash
# ==============================================================================
# Docker Entrypoint Script for crypto-ai-bot
# Starts health server and main signal pipeline
# ==============================================================================

set -e

echo "========================================================================"
echo "crypto-ai-bot Starting..."
echo "========================================================================"
echo "Environment: ${ENVIRONMENT:-unknown}"
echo "Trading Mode: ${TRADING_MODE:-paper}"
echo "Trading Pairs: ${TRADING_PAIRS:-BTC/USD,ETH/USD,SOL/USD,MATIC/USD,LINK/USD}"
echo "Redis SSL: ${REDIS_SSL:-true}"
echo "========================================================================"

# Preflight checks
echo "[Preflight] Running production checks..."
if [ -f "scripts/preflight_production.py" ]; then
    python scripts/preflight_production.py || {
        echo "[ERROR] Preflight checks failed!"
        exit 1
    }
else
    echo "[WARNING] Preflight script not found, skipping..."
fi

# Start health server in background
echo "[Health] Starting health check server on port ${HEALTH_PORT:-8080}..."
python health_server.py &
HEALTH_PID=$!

# Give health server time to start
sleep 2

# Verify health server is running
if ! curl -f http://localhost:${HEALTH_PORT:-8080}/health > /dev/null 2>&1; then
    echo "[WARNING] Health server may not be running properly"
fi

# Trap signals for graceful shutdown
shutdown() {
    echo "[Shutdown] Received shutdown signal..."
    echo "[Shutdown] Stopping health server (PID: $HEALTH_PID)..."
    kill -TERM $HEALTH_PID 2>/dev/null || true

    echo "[Shutdown] Stopping signal pipeline (PID: $PIPELINE_PID)..."
    kill -TERM $PIPELINE_PID 2>/dev/null || true

    # Wait for graceful shutdown
    sleep 5

    echo "[Shutdown] Cleanup complete. Exiting."
    exit 0
}

trap shutdown SIGTERM SIGINT

# Start main signal pipeline
echo "[Pipeline] Starting live signal publisher..."
python -u live_signal_publisher.py --mode ${TRADING_MODE:-paper} &
PIPELINE_PID=$!

echo "========================================================================"
echo "crypto-ai-bot Running!"
echo "Health Server PID: $HEALTH_PID"
echo "Pipeline PID: $PIPELINE_PID"
echo "========================================================================"
echo "Health: http://localhost:${HEALTH_PORT:-8080}/health"
echo "Metrics: http://localhost:${METRICS_PORT:-9108}/metrics"
echo "========================================================================"

# Wait for pipeline process
wait $PIPELINE_PID
