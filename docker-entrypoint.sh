#!/bin/sh
# ==============================================================================
# Docker Entrypoint Script for crypto-ai-bot
# Starts health server and main signal pipeline
# ==============================================================================

set -e

echo "========================================================================"
echo "crypto-ai-bot Starting..."
echo "========================================================================"
echo "Environment: ${ENVIRONMENT:-unknown}"
echo "Engine Mode: ${ENGINE_MODE:-paper}"
echo "Trading Mode: ${TRADING_MODE:-paper}"
echo "Trading Pairs: ${TRADING_PAIRS:-BTC/USD,ETH/USD,SOL/USD}"
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

# NOTE: production_engine.py includes the health endpoint
# No need to start a separate health server

# Trap signals for graceful shutdown
shutdown() {
    echo "[Shutdown] Received shutdown signal..."
    echo "[Shutdown] Stopping production engine (PID: $PIPELINE_PID)..."
    kill -TERM $PIPELINE_PID 2>/dev/null || true

    # Wait for graceful shutdown (max 30 seconds per PRD-001)
    echo "[Shutdown] Waiting for graceful shutdown (30s max)..."
    sleep 30

    echo "[Shutdown] Cleanup complete. Exiting."
    exit 0
}

trap shutdown SIGTERM SIGINT

# Start main signal pipeline (production engine)
echo "[Pipeline] Starting production engine..."
python -u production_engine.py --mode ${ENGINE_MODE:-paper} &
PIPELINE_PID=$!

echo "========================================================================"
echo "crypto-ai-bot Running!"
echo "Production Engine PID: $PIPELINE_PID"
echo "========================================================================"
echo "Health: http://localhost:${HEALTH_PORT:-8080}/health"
echo "Metrics: http://localhost:${HEALTH_PORT:-8080}/metrics"
echo "========================================================================"

# Wait for pipeline process
wait $PIPELINE_PID
