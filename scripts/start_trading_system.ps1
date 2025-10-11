# PowerShell script to start the complete trading system

Write-Host "🚀 Starting Crypto AI Trading System..." -ForegroundColor Green
Write-Host ""

# Set environment variables (modify as needed)
$env:ENVIRONMENT = "production"
$env:REDIS_URL = "redis://localhost:6379"
$env:KRAKEN_API_KEY = "your_api_key_here"
$env:KRAKEN_API_SECRET = "your_api_secret_here"

# Change to project directory
$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location (Join-Path $scriptPath "..")

# Check if Python is available
try {
    $pythonVersion = python --version 2>&1
    Write-Host "✅ Python found: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "❌ Python not found. Please install Python 3.8+ and add it to PATH." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# Check if virtual environment exists
if (Test-Path "venv\Scripts\Activate.ps1") {
    Write-Host "🔧 Activating virtual environment..." -ForegroundColor Yellow
    & "venv\Scripts\Activate.ps1"
}

# Install dependencies if requirements.txt exists
if (Test-Path "requirements.txt") {
    Write-Host "📦 Installing dependencies..." -ForegroundColor Yellow
    pip install -r requirements.txt
}

# Start the trading system
Write-Host "🚀 Starting trading system..." -ForegroundColor Green
try {
    python scripts\start_trading_system.py --environment $env:ENVIRONMENT
} catch {
    Write-Host "❌ Trading system failed to start: $_" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
