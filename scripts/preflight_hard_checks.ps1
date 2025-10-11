# =============================================================================
# Crypto AI Bot - Preflight Hard Checks (Windows PowerShell Wrapper)
# =============================================================================
# Activates conda environment and runs preflight checks
# Exit codes: 0 = success, 1 = failure

param(
    [switch]$Verbose
)

# Set error action preference
$ErrorActionPreference = "Stop"

# Script directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$PythonScript = Join-Path $ScriptDir "preflight_hard_checks.py"

Write-Host "[Preflight] Windows PowerShell wrapper starting..." -ForegroundColor Cyan
Write-Host "[Preflight] Project root: $ProjectRoot" -ForegroundColor Gray

# Change to project root directory
Set-Location $ProjectRoot

# Check if Python script exists
if (-not (Test-Path $PythonScript)) {
    Write-Host "❌ Python preflight script not found: $PythonScript" -ForegroundColor Red
    exit 1
}

# Try to activate conda environment
$CondaEnv = "crypto-bot"
$CondaActivated = $false

# Check if conda is available
try {
    $condaInfo = conda info --envs 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[Preflight] Conda is available" -ForegroundColor Green
        
        # Check if crypto-bot environment exists
        if ($condaInfo -match $CondaEnv) {
            Write-Host "[Preflight] Activating conda environment: $CondaEnv" -ForegroundColor Yellow
            
            # Activate conda environment
            $condaActivateScript = conda info --base 2>$null
            if ($condaActivateScript) {
                $condaActivateScript = Join-Path $condaActivateScript "Scripts\activate.bat"
                if (Test-Path $condaActivateScript) {
                    # Use cmd to activate conda environment
                    $activateCmd = "cmd /c `"$condaActivateScript $CondaEnv && python `"$PythonScript`""
                    if ($Verbose) {
                        $activateCmd += " --verbose"
                    }
                    
                    Write-Host "[Preflight] Running preflight checks..." -ForegroundColor Cyan
                    Invoke-Expression $activateCmd
                    $exitCode = $LASTEXITCODE
                    
                    if ($exitCode -eq 0) {
                        Write-Host "[Preflight] All checks passed!" -ForegroundColor Green
                    } else {
                        Write-Host "[Preflight] Some checks failed!" -ForegroundColor Red
                    }
                    
                    exit $exitCode
                } else {
                    Write-Host "⚠️  Conda activate script not found, trying direct conda run..." -ForegroundColor Yellow
                }
            }
            
            # Try direct conda run
            try {
                $condaCmd = "conda run -n $CondaEnv python `"$PythonScript`""
                if ($Verbose) {
                    $condaCmd += " --verbose"
                }
                
                Write-Host "[Preflight] Running: $condaCmd" -ForegroundColor Gray
                Invoke-Expression $condaCmd
                $exitCode = $LASTEXITCODE
                exit $exitCode
            } catch {
                Write-Host "⚠️  Direct conda run failed, trying system Python..." -ForegroundColor Yellow
            }
        } else {
            Write-Host "⚠️  Conda environment '$CondaEnv' not found, trying system Python..." -ForegroundColor Yellow
        }
    } else {
        Write-Host "⚠️  Conda not available, trying system Python..." -ForegroundColor Yellow
    }
} catch {
    Write-Host "⚠️  Conda check failed, trying system Python..." -ForegroundColor Yellow
}

# Fallback to system Python
Write-Host "[Preflight] Using system Python..." -ForegroundColor Yellow

# Check if Python is available
try {
    $pythonVersion = python --version 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[Preflight] Python version: $pythonVersion" -ForegroundColor Gray
        
        # Run preflight script
        $pythonCmd = "python `"$PythonScript`""
        if ($Verbose) {
            $pythonCmd += " --verbose"
        }
        
        Write-Host "[Preflight] Running preflight checks..." -ForegroundColor Cyan
        Invoke-Expression $pythonCmd
        $exitCode = $LASTEXITCODE
        
        if ($exitCode -eq 0) {
            Write-Host "[Preflight] All checks passed!" -ForegroundColor Green
        } else {
            Write-Host "[Preflight] Some checks failed!" -ForegroundColor Red
        }
        
        exit $exitCode
    } else {
        Write-Host "❌ Python not found in PATH" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "❌ Failed to run Python: $_" -ForegroundColor Red
    exit 1
}
