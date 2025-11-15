@echo off
REM ==============================================================================
REM Windows Runner for Paper Local Publisher
REM ==============================================================================
REM Purpose: Start local publisher for SOL/USD and ADA/USD to signals:paper
REM Created: 2025-11-08
REM Usage: Double-click this file or run from cmd: scripts\run_publisher_paper.bat
REM ==============================================================================

echo ======================================================================
echo PAPER LOCAL PUBLISHER - WINDOWS RUNNER
echo ======================================================================
echo.
echo This will start a LOCAL publisher that adds SOL/USD and ADA/USD
echo to the PRODUCTION stream (signals:paper) alongside Fly.io
echo.
echo Configuration:
echo   - Env File: .env.paper.local
echo   - Target Stream: signals:paper (PRODUCTION)
echo   - Base Pairs: BTC/USD, ETH/USD (from Fly.io)
echo   - Extra Pairs: SOL/USD, ADA/USD (from this local publisher)
echo.
echo Safety:
echo   - Instant rollback: Press Ctrl+C to stop
echo   - No Fly.io changes required
echo   - Both publishers write to same stream
echo.
echo ======================================================================
echo.

REM Change to project root directory
cd /d "%~dp0\.."

REM Verify conda environment exists
echo [1/4] Checking conda environment...
conda env list | findstr /C:"crypto-bot" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ERROR: Conda environment 'crypto-bot' not found!
    echo Please create it first: conda create -n crypto-bot python=3.10
    pause
    exit /b 1
)
echo [OK] Conda environment 'crypto-bot' found
echo.

REM Verify .env.paper.local exists
echo [2/4] Checking environment file...
if not exist ".env.paper.local" (
    echo ERROR: .env.paper.local not found!
    echo Expected location: %CD%\.env.paper.local
    pause
    exit /b 1
)
echo [OK] .env.paper.local found
echo.

REM Verify Python script exists
echo [3/4] Checking publisher script...
if not exist "run_paper_local_publisher.py" (
    echo ERROR: run_paper_local_publisher.py not found!
    echo Expected location: %CD%\run_paper_local_publisher.py
    pause
    exit /b 1
)
echo [OK] run_paper_local_publisher.py found
echo.

REM Create logs directory if it doesn't exist
if not exist "logs" mkdir logs

REM Start publisher with conda environment
echo [4/4] Starting publisher...
echo.
echo ======================================================================
echo PUBLISHER STARTING
echo ======================================================================
echo.
echo Logs will be saved to: logs\paper_local_canary.txt
echo.
echo To stop: Press Ctrl+C
echo.
echo ======================================================================
echo.

REM Run with conda and tee output to log file
call conda activate crypto-bot && python run_paper_local_publisher.py 2>&1 | tee logs\paper_local_canary.txt

REM Capture exit code
set EXIT_CODE=%ERRORLEVEL%

echo.
echo ======================================================================
echo PUBLISHER STOPPED
echo ======================================================================
echo Exit code: %EXIT_CODE%
echo.

if %EXIT_CODE% equ 0 (
    echo Publisher stopped cleanly
) else (
    echo Publisher stopped with errors - check logs\paper_local_canary.txt
)

echo.
pause
