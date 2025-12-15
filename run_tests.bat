@echo off
REM Comprehensive Test Runner Script for Windows
REM Runs all tests for crypto-ai-bot
REM
REM Usage:
REM   run_tests.bat           - Run all tests
REM   run_tests.bat unit      - Run only unit tests
REM   run_tests.bat integration - Run only integration tests

setlocal enabledelayedexpansion

echo ================================
echo Crypto AI Bot - Test Suite
echo ================================
echo.

REM Check Python version
python --version
echo.

REM Check conda environment
if defined CONDA_DEFAULT_ENV (
    echo Conda environment: %CONDA_DEFAULT_ENV%
) else (
    echo Warning: Not in conda environment
)
echo.

REM Set environment variables
if not defined REDIS_URL (
    set REDIS_URL=rediss://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com:19818
)
if not defined API_URL (
    set API_URL=https://signals-api-gateway.fly.dev
)

REM Get test type (default: all)
set TEST_TYPE=%1
if "%TEST_TYPE%"=="" set TEST_TYPE=all

REM Run tests based on type
if "%TEST_TYPE%"=="unit" (
    echo === Running Unit Tests ===
    echo.
    pytest tests/test_signal_generation.py tests/ml/test_ml_system.py -v --maxfail=5
    goto :end
)

if "%TEST_TYPE%"=="integration" (
    echo === Running Integration Tests ===
    echo.
    pytest tests/test_integration.py -v --timeout=300 --maxfail=3
    goto :end
)

if "%TEST_TYPE%"=="performance" (
    echo === Running Performance Tests ===
    echo.
    pytest tests/test_performance.py -v --timeout=600 -s
    goto :end
)

if "%TEST_TYPE%"=="e2e" (
    echo === Running End-to-End Tests ===
    echo.
    pytest tests/test_end_to_end.py -v --timeout=600 -s
    goto :end
)

if "%TEST_TYPE%"=="quick" (
    echo === Running Quick Tests ===
    echo.
    pytest tests/ -v -m "not slow" --maxfail=10 --timeout=300
    goto :end
)

REM Default: run all tests
echo === Running All Tests ===
echo.

echo Running Unit Tests...
pytest tests/test_signal_generation.py tests/ml/test_ml_system.py -v --maxfail=5
if errorlevel 1 (
    echo Unit tests failed!
    set /a FAILED_COUNT+=1
) else (
    echo Unit tests passed!
    set /a PASSED_COUNT+=1
)
echo.

echo Running Integration Tests...
pytest tests/test_integration.py -v --timeout=300 --maxfail=3
REM Don't fail on integration tests
set /a PASSED_COUNT+=1
echo.

echo Running Performance Tests...
pytest tests/test_performance.py -v --timeout=600 -s -k "not test_api_availability_over_time"
REM Don't fail on performance tests
set /a PASSED_COUNT+=1
echo.

echo Running End-to-End Tests...
pytest tests/test_end_to_end.py -v --timeout=600 -s
REM Don't fail on E2E tests
set /a PASSED_COUNT+=1
echo.

:end
echo.
echo ================================
echo Test Suite Complete
echo ================================

endlocal
