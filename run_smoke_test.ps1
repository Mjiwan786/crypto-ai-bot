#!/usr/bin/env pwsh
# ============================================================================
# 15-Minute Smoke Test - Quick Start Script (PowerShell)
# ============================================================================
#
# This script sets up the environment and runs the smoke test for
# sub-minute synthetic bars (15s timeframe).
#
# Prerequisites:
#   - conda environment 'crypto-bot' activated
#   - Redis Cloud connection configured
#   - All tests passing
#
# Author: Crypto AI Bot Team
# Date: 2025-11-08
# ============================================================================

Write-Host ""
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host "  15-MINUTE SMOKE TEST - SUB-MINUTE BARS" -ForegroundColor Cyan
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host ""

# Check if conda environment is activated
if (-not $env:CONDA_DEFAULT_ENV) {
    Write-Host "ERROR: Conda environment not activated" -ForegroundColor Red
    Write-Host ""
    Write-Host "Please activate the environment first:"
    Write-Host "  conda activate crypto-bot"
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "[1/5] Checking conda environment..." -ForegroundColor Yellow
Write-Host "      Environment: $env:CONDA_DEFAULT_ENV" -ForegroundColor Gray
if ($env:CONDA_DEFAULT_ENV -ne "crypto-bot") {
    Write-Host "      WARNING: Expected 'crypto-bot', got '$env:CONDA_DEFAULT_ENV'" -ForegroundColor Yellow
    Write-Host ""
}

# Set environment variables
Write-Host ""
Write-Host "[2/5] Setting environment variables..." -ForegroundColor Yellow

$env:REDIS_URL = "rediss://default:Salam78614**`$`$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818"
$env:REDIS_SSL = "true"
$env:REDIS_SSL_CA_CERT = "config/certs/redis_ca.pem"
$env:ENABLE_5S_BARS = "false"
$env:SCALPER_MAX_TRADES_PER_MINUTE = "4"
$env:TRADING_MODE = "paper"
$env:LATENCY_MS_MAX = "100.0"
$env:ENABLE_LATENCY_TRACKING = "true"

Write-Host "      ✓ REDIS_URL set" -ForegroundColor Green
Write-Host "      ✓ ENABLE_5S_BARS=false (production safe)" -ForegroundColor Green
Write-Host "      ✓ SCALPER_MAX_TRADES_PER_MINUTE=4" -ForegroundColor Green
Write-Host "      ✓ TRADING_MODE=paper" -ForegroundColor Green

# Verify Redis connection
Write-Host ""
Write-Host "[3/5] Verifying Redis connection..." -ForegroundColor Yellow

$redisTest = redis-cli -u $env:REDIS_URL --tls --cacert $env:REDIS_SSL_CA_CERT PING 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "      ✗ Redis connection FAILED" -ForegroundColor Red
    Write-Host ""
    Write-Host "      Please check:" -ForegroundColor Yellow
    Write-Host "        - Redis URL is correct"
    Write-Host "        - CA certificate exists: $env:REDIS_SSL_CA_CERT"
    Write-Host "        - Network connectivity"
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
} else {
    Write-Host "      ✓ Redis connection OK" -ForegroundColor Green
}

# Check if unit tests passed (optional - for speed, skip if already run)
Write-Host ""
Write-Host "[4/5] Checking test status..." -ForegroundColor Yellow
Write-Host "      Skipping unit tests (run manually if needed)" -ForegroundColor Gray
Write-Host "      Run: pytest tests/test_synthetic_bars.py tests/test_rate_limiter.py -v" -ForegroundColor Gray

# Check if WSS client is running
Write-Host ""
Write-Host "[5/5] Checking Kraken WebSocket client..." -ForegroundColor Yellow

$wssRunning = Get-Process python -ErrorAction SilentlyContinue |
              Where-Object { $_.CommandLine -like "*kraken_ws*" }

if (-not $wssRunning) {
    Write-Host "      WSS client not running" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "      Starting WSS client in background..." -ForegroundColor Gray
    Start-Process python -ArgumentList "-m", "utils.kraken_ws" -NoNewWindow
    Write-Host "      ✓ WSS client started" -ForegroundColor Green
    Write-Host "      ✓ Waiting 10 seconds for connection..." -ForegroundColor Green
    Start-Sleep -Seconds 10
} else {
    Write-Host "      ✓ WSS client already running" -ForegroundColor Green
}

# Final confirmation
Write-Host ""
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host "  SMOKE TEST READY" -ForegroundColor Cyan
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Configuration:" -ForegroundColor White
Write-Host "  - Duration: 15 minutes"
Write-Host "  - Timeframe: 15s bars only"
Write-Host "  - Rate limit: 4 trades/minute"
Write-Host "  - Latency budget: <150ms E2E"
Write-Host ""
Write-Host "The test will:" -ForegroundColor White
Write-Host "  1. Monitor kraken:ohlc:15s:BTC-USD stream"
Write-Host "  2. Validate latency < 150ms"
Write-Host "  3. Check for circuit breaker trips"
Write-Host "  4. Generate final report"
Write-Host ""
Write-Host "Press Ctrl+C to stop the test early." -ForegroundColor Yellow
Write-Host ""
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host ""

# Ask for confirmation
$confirm = Read-Host "Start smoke test now? (Y/N)"
if ($confirm -ne "Y" -and $confirm -ne "y") {
    Write-Host ""
    Write-Host "Smoke test cancelled." -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 0
}

Write-Host ""
Write-Host "Starting smoke test..." -ForegroundColor Green
Write-Host ""

# Run smoke test
python scripts\run_15min_smoke_test.py

# Check exit code
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "============================================================================" -ForegroundColor Red
    Write-Host "  SMOKE TEST FAILED" -ForegroundColor Red
    Write-Host "============================================================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "Please review the output above for errors." -ForegroundColor Yellow
    Write-Host "See SMOKE_TEST_CHECKLIST.md for troubleshooting." -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
} else {
    Write-Host ""
    Write-Host "============================================================================" -ForegroundColor Green
    Write-Host "  SMOKE TEST PASSED" -ForegroundColor Green
    Write-Host "============================================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor White
    Write-Host "  1. Review SUB_MINUTE_BARS_DEPLOYMENT_GUIDE.md Section 5"
    Write-Host "  2. Plan 24-hour paper trial"
    Write-Host "  3. Set up monitoring dashboards"
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 0
}
