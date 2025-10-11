# ===========================================
# CRYPTO AI BOT - STAGING PIPELINE WRAPPER
# ===========================================
# Windows PowerShell wrapper for staging pipeline supervisor
# 
# Usage:
#   .\scripts\windows\run_staging.ps1 -DotEnvPath .\.env.staging -IncludeExec:$false -Verbose
#   .\scripts\windows\run_staging.ps1 -DotEnvPath .\.env.staging -IncludeExec -Timeout 60

param(
    [Parameter(Mandatory=$false)]
    [string]$DotEnvPath = ".\.env.staging",
    
    [Parameter(Mandatory=$false)]
    [int]$Timeout = 30,
    
    [Parameter(Mandatory=$false)]
    [switch]$IncludeExec = $false,
    
    [Parameter(Mandatory=$false)]
    [switch]$Verbose = $false
)

# Set error action preference
$ErrorActionPreference = "Stop"

# Get script directory and project root
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

# Change to project root
Set-Location $ProjectRoot

Write-Host "===========================================" -ForegroundColor Cyan
Write-Host "CRYPTO AI BOT - STAGING PIPELINE" -ForegroundColor Cyan
Write-Host "===========================================" -ForegroundColor Cyan
Write-Host ""

# Validate environment file
if (-not (Test-Path $DotEnvPath)) {
    Write-Error "Environment file not found: $DotEnvPath"
    Write-Host "Please create $DotEnvPath from env.example" -ForegroundColor Yellow
    exit 1
}

# Check if conda environment exists
Write-Host "Checking conda environment 'crypto-bot'..." -ForegroundColor Yellow
try {
    $envCheck = conda info --envs | Select-String "crypto-bot"
    if (-not $envCheck) {
        Write-Error "Conda environment 'crypto-bot' not found"
        Write-Host "Please create it with: conda create -n crypto-bot python=3.10" -ForegroundColor Yellow
        exit 1
    }
    Write-Host "✅ Conda environment 'crypto-bot' found" -ForegroundColor Green
} catch {
    Write-Error "Failed to check conda environments: $_"
    exit 1
}

# Activate conda environment
Write-Host "Activating conda environment 'crypto-bot'..." -ForegroundColor Yellow
try {
    conda activate crypto-bot
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to activate conda environment"
        exit 1
    }
    Write-Host "✅ Conda environment activated" -ForegroundColor Green
} catch {
    Write-Error "Failed to activate conda environment: $_"
    exit 1
}

# Check Python version
Write-Host "Checking Python version..." -ForegroundColor Yellow
try {
    $pythonVersion = python --version
    Write-Host "✅ $pythonVersion" -ForegroundColor Green
} catch {
    Write-Error "Python not found in conda environment"
    exit 1
}

# Check required packages
Write-Host "Checking required packages..." -ForegroundColor Yellow
$requiredPackages = @("redis", "pyyaml", "python-dotenv", "aiohttp", "websockets")
foreach ($package in $requiredPackages) {
    try {
        $check = python -c "import $package; print('OK')" 2>$null
        if ($check -eq "OK") {
            Write-Host "✅ $package" -ForegroundColor Green
        } else {
            Write-Warning "⚠️ $package not found"
        }
    } catch {
        Write-Warning "⚠️ $package not found"
    }
}

# Build supervisor command
$supervisorCmd = @(
    "python"
    "scripts/run_staging.py"
    "--env", $DotEnvPath
    "--timeout", $Timeout.ToString()
)

if ($IncludeExec) {
    $supervisorCmd += "--include-exec"
}

if ($Verbose) {
    $supervisorCmd += "--verbose"
}

# Display configuration
Write-Host ""
Write-Host "Configuration:" -ForegroundColor Cyan
Write-Host "  Environment: $DotEnvPath" -ForegroundColor White
Write-Host "  Timeout: $Timeout seconds" -ForegroundColor White
Write-Host "  Include Execution: $IncludeExec" -ForegroundColor White
Write-Host "  Verbose: $Verbose" -ForegroundColor White
Write-Host ""

# Run supervisor
Write-Host "Starting staging pipeline supervisor..." -ForegroundColor Yellow
Write-Host "Command: $($supervisorCmd -join ' ')" -ForegroundColor Gray
Write-Host ""

try {
    & $supervisorCmd[0] $supervisorCmd[1..($supervisorCmd.Length-1)]
    $exitCode = $LASTEXITCODE
    
    if ($exitCode -eq 0) {
        Write-Host ""
        Write-Host "✅ Staging pipeline completed successfully" -ForegroundColor Green
    } else {
        Write-Host ""
        Write-Host "❌ Staging pipeline failed with exit code $exitCode" -ForegroundColor Red
    }
    
    exit $exitCode
    
} catch {
    Write-Error "Failed to run staging supervisor: $_"
    exit 1
} finally {
    # Deactivate conda environment
    Write-Host ""
    Write-Host "Deactivating conda environment..." -ForegroundColor Yellow
    conda deactivate
}

