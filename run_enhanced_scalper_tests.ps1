# Enhanced Scalper Agent Test Runner for PowerShell
# Runs pytest on scalper tests with proper environment activation

param(
    [switch]$Verbose
)

# Set error action preference
$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Enhanced Scalper Agent Test Runner" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if we're already in a conda environment
$currentEnv = $env:CONDA_DEFAULT_ENV
$activatedEnv = $null

if ($currentEnv) {
    Write-Host "✓ Already in conda environment: $currentEnv" -ForegroundColor Green
    $activatedEnv = $currentEnv
} else {
    # Check if conda is available
    try {
        $condaVersion = conda --version
        Write-Host "✓ Conda found: $condaVersion" -ForegroundColor Green
    } catch {
        Write-Host "✗ ERROR: Conda is not available. Please install Anaconda or Miniconda." -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
    
    # Check if crypto-bot environment exists
    try {
        $envList = conda env list
        if ($envList -match "crypto-bot") {
            Write-Host "✓ crypto-bot conda environment found" -ForegroundColor Green
        } else {
            Write-Host "✗ ERROR: crypto-bot conda environment not found." -ForegroundColor Red
            Write-Host "Please create it first: conda create -n crypto-bot python=3.10" -ForegroundColor Yellow
            Read-Host "Press Enter to exit"
            exit 1
        }
    } catch {
        Write-Host "✗ ERROR: Could not check conda environments." -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
    
    # Activate crypto-bot environment
    Write-Host "✓ Activating crypto-bot conda environment..." -ForegroundColor Yellow
    try {
        conda activate crypto-bot
        $activatedEnv = "crypto-bot"
    } catch {
        Write-Host "✗ ERROR: Failed to activate crypto-bot environment" -ForegroundColor Red
        Write-Host "Error: $($_.Exception.Message)" -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
}

Write-Host ""
Write-Host "Running enhanced scalper tests..." -ForegroundColor Yellow
Write-Host "Command: pytest agents/scalper/tests -q" -ForegroundColor Gray
Write-Host ""

# Run pytest with proper error handling
$testExitCode = 0
try {
    if ($Verbose) {
        pytest agents/scalper/tests -v
    } else {
        pytest agents/scalper/tests -q
    }
    $testExitCode = $LASTEXITCODE
} catch {
    Write-Host "✗ ERROR: Failed to run pytest." -ForegroundColor Red
    Write-Host "Error: $($_.Exception.Message)" -ForegroundColor Red
    $testExitCode = 1
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Test Summary" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

if ($testExitCode -eq 0) {
    Write-Host "✓ ALL TESTS PASSED!" -ForegroundColor Green
    Write-Host "The enhanced scalper agent tests completed successfully." -ForegroundColor Green
} else {
    Write-Host "✗ SOME TESTS FAILED!" -ForegroundColor Red
    Write-Host "Exit code: $testExitCode" -ForegroundColor Red
    Write-Host "Please review the test output above for details." -ForegroundColor Red
}

# Deactivate environment if we activated it
if ($activatedEnv -and $activatedEnv -ne $currentEnv) {
    Write-Host ""
    Write-Host "Deactivating conda environment..." -ForegroundColor Yellow
    try {
        conda deactivate
    } catch {
        Write-Host "Warning: Failed to deactivate conda environment" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "Check the logs directory for detailed results if available." -ForegroundColor Yellow
Write-Host ""

# Exit with the same code as pytest
exit $testExitCode