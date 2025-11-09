@echo off
REM Staging Publisher Startup Script
REM Publishes to signals:paper:staging with new trading pairs
REM DOES NOT TOUCH FLY.IO OR PRODUCTION

setlocal enabledelayedexpansion

echo ============================================================
echo STAGING SIGNAL PUBLISHER - Local Test Mode
echo ============================================================
echo.

REM Check if .env.staging exists
if not exist ".env.staging" (
    echo [ERROR] .env.staging not found!
    echo Please create .env.staging with PUBLISH_MODE=staging
    exit /b 1
)

echo [1/4] Loading .env.staging configuration...
for /f "usebackq tokens=1,* delims==" %%a in (".env.staging") do (
    set %%a=%%b
)
echo       ✓ Configuration loaded
echo.

echo [2/4] Verifying configuration...
echo       PUBLISH_MODE: %PUBLISH_MODE%
echo       TRADING_PAIRS: %TRADING_PAIRS%
echo       EXTRA_PAIRS: %EXTRA_PAIRS%
echo       Redis Stream: signals:paper:staging
echo.

REM Validate PUBLISH_MODE
if not "%PUBLISH_MODE%"=="staging" (
    echo [ERROR] PUBLISH_MODE must be 'staging' in .env.staging
    echo        Current value: %PUBLISH_MODE%
    exit /b 1
)

echo [3/4] Testing Redis TLS connectivity (dry-run)...
"%CONDA_PREFIX%\python.exe" -c "from dotenv import load_dotenv; load_dotenv('.env.staging'); import redis; import os; r = redis.from_url(os.getenv('REDIS_URL'), ssl_ca_certs=os.getenv('REDIS_SSL_CA_CERT'), decode_responses=True); print('       ✓ Redis PING:', 'OK' if r.ping() else 'FAILED'); print('       ✓ Staging stream exists:', r.exists('signals:paper:staging'))"

if %ERRORLEVEL% neq 0 (
    echo [ERROR] Redis connectivity test failed!
    exit /b 1
)
echo.

echo [4/4] Starting signal publisher...
echo.
echo ============================================================
echo Publishing to: signals:paper:staging
echo Trading Pairs: [BTC/USD, ETH/USD, SOL/USD, ADA/USD, AVAX/USD]
echo Mode: PAPER (no real trades)
echo Impact on Fly.io: ZERO (local process only)
echo Impact on Production: ZERO (isolated staging stream)
echo ============================================================
echo.
echo Press Ctrl+C to stop publisher
echo.

REM Start publisher with staging env
"%CONDA_PREFIX%\python.exe" run_staging_publisher.py

echo.
echo [STOPPED] Staging publisher terminated
echo Staging stream data preserved for analysis
