# Start Paper Trading Trial - Step 7 Validation
# This script starts the 7-14 day paper trading trial with full monitoring

param(
    [int]$DurationDays = 7
)

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "STEP 7 PAPER TRADING TRIAL" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Duration: $DurationDays days" -ForegroundColor Yellow
Write-Host "Mode: PAPER (no real trading)" -ForegroundColor Green
Write-Host "ML Gate: ENABLED (threshold 0.60)" -ForegroundColor Green
Write-Host ""

# Check if .env.paper exists
$envFile = "C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\.env.paper"
if (-not (Test-Path $envFile)) {
    Write-Host "ERROR: .env.paper not found at $envFile" -ForegroundColor Red
    Write-Host "Please create .env.paper from .env.paper.example" -ForegroundColor Red
    exit 1
}

Write-Host "Loading environment from .env.paper..." -ForegroundColor Yellow

# Load environment variables from .env.paper
Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    # Skip comments and empty lines
    if ($line -and !$line.StartsWith("#")) {
        $parts = $line.Split("=", 2)
        if ($parts.Length -eq 2) {
            $key = $parts[0].Trim()
            $value = $parts[1].Trim()
            [System.Environment]::SetEnvironmentVariable($key, $value, "Process")

            # Print key variables (mask passwords)
            if ($key -in @("REDIS_URL", "TRADING_PAIRS", "MODE", "INITIAL_EQUITY_USD")) {
                $displayValue = $value
                if ($key -eq "REDIS_URL") {
                    $displayValue = $value -replace "://[^@]+@", "://***:***@"
                }
                Write-Host "  $key = $displayValue" -ForegroundColor Gray
            }
        }
    }
}

Write-Host ""
Write-Host "Environment loaded successfully!" -ForegroundColor Green
Write-Host ""

# Verify Redis connection
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "VERIFYING REDIS CONNECTION" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan

$redisUrl = [System.Environment]::GetEnvironmentVariable("REDIS_URL", "Process")
$caCertPath = [System.Environment]::GetEnvironmentVariable("REDIS_CA_CERT", "Process")

if (-not $redisUrl) {
    Write-Host "ERROR: REDIS_URL not set in environment" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $caCertPath)) {
    Write-Host "WARNING: Redis CA certificate not found at: $caCertPath" -ForegroundColor Yellow
    Write-Host "TLS connection may fail" -ForegroundColor Yellow
} else {
    Write-Host "CA Certificate: $caCertPath" -ForegroundColor Green
}

Write-Host ""
Write-Host "Testing Redis connection..." -ForegroundColor Yellow

# Test Redis connection with python
conda activate crypto-bot
python -c @"
import redis
import sys
import os
from urllib.parse import urlparse

redis_url = os.getenv('REDIS_URL')
ca_cert = os.getenv('REDIS_CA_CERT')

try:
    # Parse URL
    parsed = urlparse(redis_url)

    # Create Redis client
    r = redis.Redis(
        host=parsed.hostname,
        port=parsed.port,
        password=parsed.password,
        ssl=True,
        ssl_ca_certs=ca_cert,
        decode_responses=True
    )

    # Test connection
    r.ping()
    print('✅ Redis connection successful')

    # Test write
    r.set('paper_trial:test', 'ok', ex=10)
    val = r.get('paper_trial:test')
    if val == 'ok':
        print('✅ Redis read/write working')
    else:
        print('⚠️  Redis read/write failed')
        sys.exit(1)

except Exception as e:
    print(f'❌ Redis connection failed: {e}')
    sys.exit(1)
"@

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "ERROR: Redis connection test failed" -ForegroundColor Red
    Write-Host "Please check your REDIS_URL and certificate path" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "STARTING PAPER TRADING TRIAL" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "The paper trial will run for $DurationDays days" -ForegroundColor Yellow
Write-Host ""
Write-Host "Monitoring endpoints:" -ForegroundColor Cyan
Write-Host "  - Metrics: http://localhost:9108/metrics" -ForegroundColor Gray
Write-Host "  - Logs: logs/paper_trial_*.log" -ForegroundColor Gray
Write-Host ""
Write-Host "Pass Criteria:" -ForegroundColor Cyan
Write-Host "  ✓ Profit Factor >= 1.5" -ForegroundColor Gray
Write-Host "  ✓ Monthly ROI >= 0.83% (10% annualized)" -ForegroundColor Gray
Write-Host "  ✓ Max Drawdown <= -20%" -ForegroundColor Gray
Write-Host "  ✓ Trade count: 60-80% of baseline" -ForegroundColor Gray
Write-Host "  ✓ P95 latency < 500ms" -ForegroundColor Gray
Write-Host "  ✓ No system crashes" -ForegroundColor Gray
Write-Host ""
Write-Host "Press Ctrl+C to stop the trial" -ForegroundColor Yellow
Write-Host ""
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host ""

# Create logs directory if it doesn't exist
$logsDir = "C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\logs"
if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir | Out-Null
    Write-Host "Created logs directory: $logsDir" -ForegroundColor Green
}

# Start the paper trial
Write-Host "Starting paper trial engine..." -ForegroundColor Green
Write-Host ""

try {
    conda activate crypto-bot
    python scripts/run_paper_trial.py
} catch {
    Write-Host ""
    Write-Host "ERROR: Paper trial stopped with error: $_" -ForegroundColor Red
    exit 1
}
