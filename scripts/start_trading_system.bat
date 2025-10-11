@echo off
REM Windows batch script to start the complete trading system

echo 🚀 Starting Crypto AI Trading System...
echo.

REM Set environment variables (modify as needed)
set ENVIRONMENT=production
set REDIS_URL=redis://localhost:6379
set KRAKEN_API_KEY=your_api_key_here
set KRAKEN_API_SECRET=your_api_secret_here

REM Change to project directory
cd /d "%~dp0.."

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python not found. Please install Python 3.8+ and add it to PATH.
    pause
    exit /b 1
)

REM Check if virtual environment exists
if exist "venv\Scripts\activate.bat" (
    echo 🔧 Activating virtual environment...
    call venv\Scripts\activate.bat
)

REM Install dependencies if requirements.txt exists
if exist "requirements.txt" (
    echo 📦 Installing dependencies...
    pip install -r requirements.txt
)

REM Start the trading system
echo 🚀 Starting trading system...
python scripts\start_trading_system.py --environment %ENVIRONMENT%

REM Keep window open if there was an error
if errorlevel 1 (
    echo.
    echo ❌ Trading system failed to start.
    pause
)
