# ===========================================
# CRYPTO AI BOT - WINDOWS ENVIRONMENT VALIDATOR
# ===========================================
# PowerShell wrapper that activates conda crypto-bot environment
# and forwards arguments to the Python preflight script

param(
    [Parameter(Mandatory=$false)]
    [string]$DotEnvPath = ".env",
    
    [Parameter(Mandatory=$false)]
    [switch]$VerboseOutput
)

# Set error action preference
$ErrorActionPreference = "Stop"

# Function to check if conda is available
function Test-CondaAvailable {
    try {
        $null = Get-Command conda -ErrorAction Stop
        return $true
    }
    catch {
        return $false
    }
}

# Function to check if crypto-bot conda environment exists
function Test-CondaEnvironment {
    param([string]$EnvName)
    
    try {
        $envs = conda env list --json | ConvertFrom-Json
        return $envs.envs -contains $envs.root_prefix + "\envs\" + $EnvName
    }
    catch {
        return $false
    }
}

# Function to activate conda environment and run command
function Invoke-WithConda {
    param(
        [string]$EnvName,
        [string]$Command,
        [string[]]$Arguments
    )
    
    try {
        # Activate conda environment and run command
        $activateScript = conda info --root
        $activateScript = Join-Path $activateScript "Scripts\activate.bat"
        
        if (Test-Path $activateScript) {
            $fullCommand = "& `"$activateScript`" $EnvName && $Command $($Arguments -join ' ')"
            Invoke-Expression $fullCommand
        } else {
            # Fallback: try conda run
            $fullCommand = "conda run -n $EnvName $Command $($Arguments -join ' ')"
            Invoke-Expression $fullCommand
        }
    }
    catch {
        Write-Error "Failed to run command with conda environment: $_"
        exit 1
    }
}

# Main execution
try {
    Write-Host "[Preflight] Windows PowerShell wrapper starting..." -ForegroundColor Cyan
    
    # Check if conda is available
    if (-not (Test-CondaAvailable)) {
        Write-Warning "Conda not found in PATH. Attempting to run Python directly..."
        
        # Try to run Python directly
        $pythonCommand = "python"
        $scriptPath = Join-Path $PSScriptRoot "..\preflight.py"
        
        # Build arguments
        $args = @("--env", $DotEnvPath)
        if ($VerboseOutput) {
            $args += "--verbose"
        }
        
        & $pythonCommand $scriptPath @args
        exit $LASTEXITCODE
    }
    
    # Check if crypto-bot environment exists
    if (-not (Test-CondaEnvironment "crypto-bot")) {
        Write-Warning "Conda environment 'crypto-bot' not found. Attempting to run Python directly..."
        
        # Try to run Python directly
        $pythonCommand = "python"
        $scriptPath = Join-Path $PSScriptRoot "..\preflight.py"
        
        # Build arguments
        $args = @("--env", $DotEnvPath)
        if ($VerboseOutput) {
            $args += "--verbose"
        }
        
        & $pythonCommand $scriptPath @args
        exit $LASTEXITCODE
    }
    
    # Activate conda environment and run preflight
    Write-Host "[Preflight] Activating conda environment 'crypto-bot'..." -ForegroundColor Green
    
    $scriptPath = Join-Path $PSScriptRoot "..\preflight.py"
    $pythonCommand = "python"
    
    # Build arguments
    $args = @("--env", $DotEnvPath)
    if ($Verbose) {
        $args += "--verbose"
    }
    
    # Run with conda environment
    Invoke-WithConda -EnvName "crypto-bot" -Command $pythonCommand -Arguments @($scriptPath) + $args
    
    # Exit with the same code as the Python script
    exit $LASTEXITCODE
    
}
catch {
    Write-Error "Preflight validation failed: $_"
    exit 1
}
