@echo off
REM ============================================================================
REM 15-Minute Smoke Test - Quick Start Script
REM ============================================================================
REM
REM This script sets up the environment and runs the smoke test for
REM sub-minute synthetic bars (15s timeframe).
REM
REM Prerequisites:
REM   - conda environment 'crypto-bot' activated
REM   - Redis Cloud connection configured
REM   - All tests passing
REM
REM Author: Crypto AI Bot Team
REM Date: 2025-11-08
REM ============================================================================

echo.
echo ============================================================================
echo   15-MINUTE SMOKE TEST - SUB-MINUTE BARS
echo ============================================================================
echo.

REM Check if conda environment is activated
IF NOT DEFINED CONDA_DEFAULT_ENV (
    echo ERROR: Conda environment not activated
    echo.
    echo Please activate the environment first:
    echo   conda activate crypto-bot
    echo.
    pause
    exit /b 1
)

echo [1/5] Checking conda environment...
echo       Environment: %CONDA_DEFAULT_ENV%
IF NOT "%CONDA_DEFAULT_ENV%"=="crypto-bot" (
    echo       WARNING: Expected 'crypto-bot', got '%CONDA_DEFAULT_ENV%'
    echo.
)

REM Set environment variables
echo.
echo [2/5] Setting environment variables...

set REDIS_URL=rediss://default:&lt;REDIS_PASSWORD&gt;**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818
set REDIS_SSL=true
set REDIS_SSL_CA_CERT=config/certs/redis_ca.pem
set ENABLE_5S_BARS=false
set SCALPER_MAX_TRADES_PER_MINUTE=4
set TRADING_MODE=paper
set LATENCY_MS_MAX=100.0
set ENABLE_LATENCY_TRACKING=true

echo       ✓ REDIS_URL set
echo       ✓ ENABLE_5S_BARS=false (production safe)
echo       ✓ SCALPER_MAX_TRADES_PER_MINUTE=4
echo       ✓ TRADING_MODE=paper

REM Verify Redis connection
echo.
echo [3/5] Verifying Redis connection...
redis-cli -u %REDIS_URL% --tls --cacert %REDIS_SSL_CA_CERT% PING >nul 2>&1
IF ERRORLEVEL 1 (
    echo       ✗ Redis connection FAILED
    echo.
    echo       Please check:
    echo         - Redis URL is correct
    echo         - CA certificate exists: %REDIS_SSL_CA_CERT%
    echo         - Network connectivity
    echo.
    pause
    exit /b 1
) ELSE (
    echo       ✓ Redis connection OK
)

REM Check if unit tests passed (optional - for speed, skip if already run)
echo.
echo [4/5] Checking test status...
echo       Skipping unit tests (run manually if needed)
echo       Run: pytest tests/test_synthetic_bars.py tests/test_rate_limiter.py -v

REM Start WSS client if not running
echo.
echo [5/5] Checking Kraken WebSocket client...
tasklist /FI "IMAGENAME eq python.exe" /FI "WINDOWTITLE eq *kraken_ws*" 2>nul | find /I "python.exe" >nul
IF ERRORLEVEL 1 (
    echo       WSS client not running
    echo.
    echo       Starting WSS client in background...
    start /B python -m utils.kraken_ws
    echo       ✓ WSS client started
    echo       ✓ Waiting 10 seconds for connection...
    timeout /t 10 /nobreak >nul
) ELSE (
    echo       ✓ WSS client already running
)

REM Final confirmation
echo.
echo ============================================================================
echo   SMOKE TEST READY
echo ============================================================================
echo.
echo Configuration:
echo   - Duration: 15 minutes
echo   - Timeframe: 15s bars only
echo   - Rate limit: 4 trades/minute
echo   - Latency budget: ^<150ms E2E
echo.
echo The test will:
echo   1. Monitor kraken:ohlc:15s:BTC-USD stream
echo   2. Validate latency ^< 150ms
echo   3. Check for circuit breaker trips
echo   4. Generate final report
echo.
echo Press Ctrl+C to stop the test early.
echo.
echo ============================================================================
echo.

REM Ask for confirmation
set /p CONFIRM="Start smoke test now? (Y/N): "
IF /I NOT "%CONFIRM%"=="Y" (
    echo.
    echo Smoke test cancelled.
    pause
    exit /b 0
)

echo.
echo Starting smoke test...
echo.

REM Run smoke test
python scripts\run_15min_smoke_test.py

REM Check exit code
IF ERRORLEVEL 1 (
    echo.
    echo ============================================================================
    echo   SMOKE TEST FAILED
    echo ============================================================================
    echo.
    echo Please review the output above for errors.
    echo See SMOKE_TEST_CHECKLIST.md for troubleshooting.
    echo.
    pause
    exit /b 1
) ELSE (
    echo.
    echo ============================================================================
    echo   SMOKE TEST PASSED
    echo ============================================================================
    echo.
    echo Next steps:
    echo   1. Review SUB_MINUTE_BARS_DEPLOYMENT_GUIDE.md Section 5
    echo   2. Plan 24-hour paper trial
    echo   3. Set up monitoring dashboards
    echo.
    pause
    exit /b 0
)
