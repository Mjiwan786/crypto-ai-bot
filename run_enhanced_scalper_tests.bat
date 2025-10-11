@echo off
REM Enhanced Scalper Agent Test Runner for Windows
REM Runs pytest on scalper tests with proper environment activation

setlocal enabledelayedexpansion

echo ========================================
echo Enhanced Scalper Agent Test Runner
echo ========================================
echo.

REM Check if we're in a conda environment
if defined CONDA_DEFAULT_ENV (
    echo ✓ Already in conda environment: !CONDA_DEFAULT_ENV!
    set ACTIVATED_ENV=!CONDA_DEFAULT_ENV!
) else (
    echo Checking for conda installation...
    conda --version >nul 2>&1
    if !errorlevel! neq 0 (
        echo ✗ ERROR: Conda is not available. Please install Anaconda or Miniconda.
        pause
        exit /b 1
    )
    
    REM Check if crypto-bot environment exists
    conda env list | findstr crypto-bot >nul 2>&1
    if !errorlevel! neq 0 (
        echo ✗ ERROR: crypto-bot conda environment not found.
        echo Please create it first: conda create -n crypto-bot python=3.10
        pause
        exit /b 1
    )
    
    echo ✓ Activating crypto-bot conda environment...
    call conda activate crypto-bot
    if !errorlevel! neq 0 (
        echo ✗ ERROR: Failed to activate crypto-bot environment
        pause
        exit /b 1
    )
    set ACTIVATED_ENV=crypto-bot
)

echo.
echo Running enhanced scalper tests...
echo Command: pytest agents/scalper/tests -q
echo.

REM Run pytest with proper error handling
pytest agents/scalper/tests -q
set TEST_EXIT_CODE=!errorlevel!

echo.
echo ========================================
echo Test Summary
echo ========================================

if !TEST_EXIT_CODE! equ 0 (
    echo ✓ ALL TESTS PASSED!
    echo The enhanced scalper agent tests completed successfully.
) else (
    echo ✗ SOME TESTS FAILED!
    echo Exit code: !TEST_EXIT_CODE!
    echo Please review the test output above for details.
)

if defined ACTIVATED_ENV (
    if !ACTIVATED_ENV! neq !CONDA_DEFAULT_ENV! (
        echo.
        echo Deactivating conda environment...
        call conda deactivate
    )
)

echo.
echo Check the logs directory for detailed results if available.
echo.

REM Exit with the same code as pytest
exit /b !TEST_EXIT_CODE!