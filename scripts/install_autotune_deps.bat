@echo off
REM Install dependencies for autotune_full.py

echo ========================================================================
echo INSTALLING AUTOTUNE DEPENDENCIES
echo ========================================================================
echo.

REM Activate conda environment
call conda activate crypto-bot

REM Install scikit-optimize
echo Installing scikit-optimize for Bayesian optimization...
pip install scikit-optimize==0.10.2

echo.
echo ========================================================================
echo INSTALLATION COMPLETE
echo ========================================================================
echo.
echo You can now run:
echo   python scripts/autotune_full.py
echo.
pause
