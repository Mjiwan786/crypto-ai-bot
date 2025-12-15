@echo off
REM ==============================================================================
REM Local Deployment Test for crypto-ai-bot Engine
REM ==============================================================================
REM Tests the production engine locally before Fly.io deployment
REM
REM USAGE:
REM   1. Open Anaconda Prompt (or Miniconda Prompt)
REM   2. Navigate to crypto_ai_bot directory
REM   3. Run: test_local_deployment.bat
REM ==============================================================================

echo.
echo ================================================================================
echo crypto-ai-bot Local Deployment Test
echo ================================================================================
echo.

REM Check conda environment
echo [1/5] Checking conda environment...
conda activate crypto-bot
if %errorlevel% neq 0 (
    echo [ERROR] Failed to activate crypto-bot conda environment
    echo Please create it with: conda create -n crypto-bot python=3.10
    exit /b 1
)
echo [OK] conda environment: crypto-bot
echo.

REM Check Python version
echo [2/5] Checking Python version...
python --version
if %errorlevel% neq 0 (
    echo [ERROR] Python not found
    exit /b 1
)
echo [OK] Python ready
echo.

REM Check Redis CA certificate
echo [3/5] Checking Redis CA certificate...
if exist "config\certs\redis_ca.pem" (
    echo [OK] Redis CA certificate found
) else (
    echo [ERROR] Redis CA certificate not found at: config\certs\redis_ca.pem
    echo Please ensure the certificate is in place
    exit /b 1
)
echo.

REM Set environment variables for paper mode
echo [4/5] Setting environment variables for PAPER mode...
set ENGINE_MODE=paper
set REDIS_URL=rediss://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com:19818
set REDIS_SSL=true
set REDIS_CA_CERT=config/certs/redis_ca.pem
set LOG_LEVEL=INFO
set TRADING_PAIRS=BTC/USD,ETH/USD,SOL/USD
set TIMEFRAMES=15s,1m,5m
set HEALTH_PORT=8080
set METRICS_PORT=9108

echo [OK] Environment variables set:
echo    ENGINE_MODE=%ENGINE_MODE%
echo    REDIS_SSL=%REDIS_SSL%
echo    TRADING_PAIRS=%TRADING_PAIRS%
echo.

REM Test Redis connection
echo [5/5] Testing Redis connection...
python -c "import sys; sys.path.insert(0, '.'); from agents.infrastructure.redis_client import RedisCloudClient, RedisCloudConfig; import asyncio; config = RedisCloudConfig(url='%REDIS_URL%', ca_cert_path='%REDIS_CA_CERT%'); client = RedisCloudClient(config); asyncio.run(client.connect()); print('[OK] Redis connection successful'); asyncio.run(client.disconnect())"

if %errorlevel% neq 0 (
    echo [ERROR] Redis connection test failed
    echo Please check:
    echo   1. REDIS_URL is correct
    echo   2. Redis CA certificate exists
    echo   3. Network connection is available
    exit /b 1
)
echo.

echo ================================================================================
echo Pre-flight checks PASSED
echo ================================================================================
echo.
echo Ready to start production engine!
echo.
echo To run the engine:
echo   python production_engine.py --mode paper
echo.
echo To inspect Redis streams (in another terminal):
echo   conda activate crypto-bot
echo   python scripts\inspect_redis_streams.py --mode paper
echo.
echo To watch streams in real-time:
echo   python scripts\inspect_redis_streams.py --mode paper --watch
echo.
echo Press Ctrl+C to stop the engine when done testing.
echo ================================================================================
echo.

REM Ask user if they want to start the engine now
set /p START_ENGINE="Start production engine now? (y/n): "
if /i "%START_ENGINE%"=="y" (
    echo.
    echo Starting production engine in PAPER mode...
    echo ================================================================================
    python production_engine.py --mode paper
) else (
    echo.
    echo Test script complete. Run manually when ready:
    echo   python production_engine.py --mode paper
)

echo.
pause
