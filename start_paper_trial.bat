@echo off
REM Start Paper Trading Trial - Step 7 Validation
echo ================================================================================
echo STEP 7 PAPER TRADING TRIAL
echo ================================================================================
echo.
echo Duration: 7-14 days
echo Mode: PAPER (no real trading)
echo ML Gate: ENABLED (threshold 0.60)
echo.

REM Set environment variables from .env.paper
set REDIS_URL=rediss://default:Salam78614**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818
set REDIS_CA_CERT=C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem
set MODE=paper
set TRADING_PAIRS=BTC/USD,ETH/USD
set TIMEFRAMES=5m
set INITIAL_EQUITY_USD=10000.0
set METRICS_PORT=9108
set LOG_LEVEL=INFO

echo Environment configured:
echo   REDIS_URL: rediss://***@redis-19818...
echo   TRADING_PAIRS: %TRADING_PAIRS%
echo   MODE: %MODE%
echo   ML threshold: 0.60 (from config/params/ml.yaml)
echo.

REM Test Redis connection first
echo Testing Redis connection...
call conda activate crypto-bot
python test_redis.py
if errorlevel 1 (
    echo.
    echo ERROR: Redis connection test failed
    echo Please check your Redis configuration
    pause
    exit /b 1
)

echo.
echo ================================================================================
echo STARTING PAPER TRADING TRIAL
echo ================================================================================
echo.
echo The trial will now run continuously. Keep this window open.
echo.
echo Monitoring:
echo   - Metrics: http://localhost:9108/metrics
echo   - Logs: logs\paper_trial_*.log
echo.
echo Pass Criteria:
echo   - Profit Factor ^>= 1.5
echo   - Monthly ROI ^>= 0.83%%
echo   - Max Drawdown ^<= -20%%
echo   - P95 latency ^< 500ms
echo.
echo Press Ctrl+C to stop the trial
echo.
echo ================================================================================
echo.

REM Start the paper trial
python scripts\run_paper_trial.py

pause
