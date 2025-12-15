@echo off
REM Start Kraken WebSocket Client with Proper Configuration

echo ========================================================================
echo KRAKEN WEBSOCKET CLIENT STARTUP
echo ========================================================================
echo.

REM Set Redis Cloud Connection
set REDIS_URL=rediss://default:&lt;REDIS_PASSWORD&gt;**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818

REM Trading Configuration
set TRADING_PAIRS=BTC/USD,ETH/USD,SOL/USD,ADA/USD
set TIMEFRAMES=15s,1m,5m

REM Scalping Configuration
set SCALP_ENABLED=true
set SCALP_MIN_VOLUME=0.1
set SCALP_MAX_TRADES_PER_MINUTE=4
set SCALP_TARGET_BPS=10

REM Circuit Breaker Limits
set LATENCY_MS_MAX=100.0
set SPREAD_BPS_MAX=5.0
set CIRCUIT_BREAKER_REDIS_ERRORS=3
set CIRCUIT_BREAKER_COOLDOWN_SECONDS=45

REM Performance Monitoring
set ENABLE_LATENCY_TRACKING=true
set ENABLE_HEALTH_MONITORING=true
set METRICS_INTERVAL=15

REM Redis Cloud Optimization
set REDIS_CLOUD_OPTIMIZED=true
set REDIS_CONNECTION_POOL_SIZE=10
set REDIS_SOCKET_TIMEOUT=10
set REDIS_STREAM_BATCH_SIZE=25
set REDIS_MEMORY_THRESHOLD_MB=100

REM WebSocket Configuration
set WEBSOCKET_RECONNECT_DELAY=3
set WEBSOCKET_MAX_RETRIES=10
set WEBSOCKET_PING_INTERVAL=20
set WEBSOCKET_CLOSE_TIMEOUT=5

REM Logging
set LOG_LEVEL=INFO

echo Configuration Set:
echo   TRADING_PAIRS=%TRADING_PAIRS%
echo   SCALP_MAX_TRADES_PER_MINUTE=%SCALP_MAX_TRADES_PER_MINUTE%
echo   LATENCY_MS_MAX=%LATENCY_MS_MAX%
echo   SPREAD_BPS_MAX=%SPREAD_BPS_MAX%
echo   CIRCUIT_BREAKER_COOLDOWN=%CIRCUIT_BREAKER_COOLDOWN_SECONDS%s
echo.

echo Starting Kraken WebSocket Client...
echo Logs: logs\kraken_ws_live.log
echo.

python -m utils.kraken_ws > logs\kraken_ws_live.log 2>&1

echo.
echo Kraken WebSocket Client stopped.
