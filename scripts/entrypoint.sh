#!/bin/bash
# ===============================================
# Production entrypoint script for crypto_ai_bot
# Handles graceful startup and SIGTERM shutdown
# ===============================================

set -euo pipefail

# Default values
ENVIRONMENT=${ENVIRONMENT:-production}
MODE=${MODE:-production}

# Signal handling for graceful shutdown
cleanup() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Received SIGTERM, shutting down gracefully..."
    if [ ! -z "${MAIN_PID:-}" ]; then
        kill -TERM "$MAIN_PID" 2>/dev/null || true
        wait "$MAIN_PID" 2>/dev/null || true
    fi
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Shutdown complete"
    exit 0
}

# Set up signal handlers
trap cleanup SIGTERM SIGINT

# Main execution
main() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting crypto AI bot..."
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Environment: $ENVIRONMENT"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Mode: $MODE"
    
    # Wait for Redis to be available
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Waiting for Redis connection..."
    python scripts/wait_for_redis.py --timeout 15
    
    if [ $? -ne 0 ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: Redis connection failed"
        exit 1
    fi
    
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Redis connection established"
    
    # Start the main application
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting main application..."
    exec python -m main "$@"
}

# Run main function
main "$@"
