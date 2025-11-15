# PowerShell script for 24/7 live trading system startup

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  CRYPTO AI BOT - Live System Startup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if PM2 is installed
try {
    $pm2Version = pm2 --version
    Write-Host "[✓] PM2 installed: $pm2Version" -ForegroundColor Green
} catch {
    Write-Host "[✗] PM2 not installed" -ForegroundColor Red
    Write-Host "Please install: npm install -g pm2" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

# Check Redis connectivity
Write-Host ""
Write-Host "[1/5] Checking Redis connectivity..." -ForegroundColor Yellow
try {
    python check_pnl_data.py
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[✓] Redis connection OK" -ForegroundColor Green
    } else {
        throw "Redis connection failed"
    }
} catch {
    Write-Host "[✗] Redis connection failed" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# Stop existing processes
Write-Host ""
Write-Host "[2/5] Stopping any existing processes..." -ForegroundColor Yellow
pm2 stop all 2>&1 | Out-Null
pm2 delete all 2>&1 | Out-Null
Write-Host "[✓] Cleaned up old processes" -ForegroundColor Green

# Start all services
Write-Host ""
Write-Host "[3/5] Starting all services..." -ForegroundColor Yellow
pm2 start ecosystem.all.config.js
if ($LASTEXITCODE -eq 0) {
    Write-Host "[✓] All services started" -ForegroundColor Green
} else {
    Write-Host "[✗] Failed to start services" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# Save PM2 configuration
Write-Host ""
Write-Host "[4/5] Saving PM2 configuration..." -ForegroundColor Yellow
pm2 save
Write-Host "[✓] Configuration saved" -ForegroundColor Green

# Setup PM2 startup
Write-Host ""
Write-Host "[5/5] Setting up PM2 startup script..." -ForegroundColor Yellow
pm2 startup
Write-Host "[✓] Startup script configured" -ForegroundColor Green

# Show status
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  System Started Successfully!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Quick Commands:" -ForegroundColor Yellow
Write-Host "  View status:  pm2 status"
Write-Host "  View logs:    pm2 logs"
Write-Host "  Monitor:      pm2 monit"
Write-Host "  Stop all:     pm2 stop all"
Write-Host ""
Write-Host "Access Points:" -ForegroundColor Yellow
Write-Host "  - Trading Bot:   Check pm2 logs bot-*"
Write-Host "  - Signals API:   http://localhost:8000"
Write-Host "  - Signals Site:  http://localhost:3000"
Write-Host "  - Prometheus:    http://localhost:9100/metrics"
Write-Host ""
Write-Host "Press Ctrl+C to exit this script (services will continue running)"
Write-Host ""

# Show live logs
Write-Host "Showing live logs (Ctrl+C to exit)..." -ForegroundColor Yellow
pm2 logs
