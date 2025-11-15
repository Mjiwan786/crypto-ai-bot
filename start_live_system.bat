@echo off
REM Quick start script for 24/7 live trading system
REM This starts all services using PM2

echo ========================================
echo   CRYPTO AI BOT - Live System Startup
echo ========================================
echo.

REM Check if PM2 is installed
where pm2 >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: PM2 not installed
    echo Please install: npm install -g pm2
    pause
    exit /b 1
)

echo [1/5] Checking Redis connectivity...
python check_pnl_data.py
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Redis connection failed
    pause
    exit /b 1
)

echo.
echo [2/5] Stopping any existing processes...
pm2 stop all
pm2 delete all

echo.
echo [3/5] Starting all services...
pm2 start ecosystem.all.config.js

echo.
echo [4/5] Saving PM2 configuration...
pm2 save

echo.
echo [5/5] Setting up PM2 startup script...
pm2 startup

echo.
echo ========================================
echo   System Started Successfully!
echo ========================================
echo.
echo View status:  pm2 status
echo View logs:    pm2 logs
echo Monitor:      pm2 monit
echo Stop all:     pm2 stop all
echo.
echo Access points:
echo - Trading Bot: Check pm2 logs
echo - Signals API: http://localhost:8000
echo - Signals Site: http://localhost:3000
echo - Prometheus: http://localhost:9100/metrics
echo.
pause
