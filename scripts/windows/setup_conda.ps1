# ===============================================
# Crypto AI Trading Bot — Windows Conda Setup Script
# ===============================================
# This script creates a reproducible conda environment for the crypto trading bot
# on Windows with TA-Lib and all required dependencies.

param(
    [switch]$Force = $false,
    [switch]$SkipCondaInstall = $false
)

# Set error action preference
$ErrorActionPreference = "Stop"

# Colors for output
$Green = "`e[32m"
$Yellow = "`e[33m"
$Red = "`e[31m"
$Reset = "`e[0m"

function Write-ColorOutput {
    param([string]$Message, [string]$Color = $Reset)
    Write-Host "${Color}${Message}${Reset}"
}

function Test-CondaInstalled {
    try {
        $condaVersion = conda --version 2>$null
        return $true
    }
    catch {
        return $false
    }
}

function Test-EnvironmentExists {
    param([string]$EnvName)
    try {
        $envs = conda env list --json | ConvertFrom-Json
        return $envs.envs -contains $envName
    }
    catch {
        return $false
    }
}

# Main execution
Write-ColorOutput "===============================================" $Green
Write-ColorOutput "Crypto AI Trading Bot - Windows Setup" $Green
Write-ColorOutput "===============================================" $Green
Write-Host ""

# Check if conda is installed
if (-not (Test-CondaInstalled)) {
    Write-ColorOutput "❌ Conda is not installed or not in PATH" $Red
    Write-ColorOutput "Please install Miniconda or Anaconda first:" $Yellow
    Write-ColorOutput "  https://docs.conda.io/en/latest/miniconda.html" $Yellow
    Write-ColorOutput "  https://www.anaconda.com/products/distribution" $Yellow
    exit 1
}

Write-ColorOutput "✅ Conda found: $(conda --version)" $Green

# Check if environment already exists
$envName = "crypto-bot"
if ((Test-EnvironmentExists -EnvName $envName) -and -not $Force) {
    Write-ColorOutput "⚠️  Environment '$envName' already exists" $Yellow
    Write-ColorOutput "Use -Force to recreate it, or activate it manually:" $Yellow
    Write-ColorOutput "  conda activate $envName" $Yellow
    Write-ColorOutput "  pip install -r requirements.txt" $Yellow
    exit 0
}

# Remove existing environment if Force is specified
if ((Test-EnvironmentExists -EnvName $envName) -and $Force) {
    Write-ColorOutput "🗑️  Removing existing environment '$envName'..." $Yellow
    conda env remove -n $envName -y
}

# Create conda environment
Write-ColorOutput "🐍 Creating conda environment '$envName' with Python 3.10..." $Green
conda create -n $envName python=3.10 -y

if ($LASTEXITCODE -ne 0) {
    Write-ColorOutput "❌ Failed to create conda environment" $Red
    exit 1
}

# Activate environment and install TA-Lib
Write-ColorOutput "📦 Installing TA-Lib from conda-forge..." $Green
conda activate $envName
conda install -c conda-forge ta-lib=0.6.4 -y

if ($LASTEXITCODE -ne 0) {
    Write-ColorOutput "❌ Failed to install TA-Lib" $Red
    Write-ColorOutput "This might be due to conda-forge connectivity issues." $Yellow
    Write-ColorOutput "You can try installing manually after activation:" $Yellow
    Write-ColorOutput "  conda activate $envName" $Yellow
    Write-ColorOutput "  pip install TA-Lib" $Yellow
    exit 1
}

# Upgrade pip
Write-ColorOutput "⬆️  Upgrading pip..." $Green
python -m pip install --upgrade pip

# Install requirements
Write-ColorOutput "📋 Installing requirements from requirements.txt..." $Green
pip install -r requirements.txt

if ($LASTEXITCODE -ne 0) {
    Write-ColorOutput "❌ Failed to install requirements" $Red
    Write-ColorOutput "Check the error messages above for specific package issues." $Yellow
    exit 1
}

# Check for dependency conflicts
Write-ColorOutput "🔍 Checking for dependency conflicts..." $Green
pip check

if ($LASTEXITCODE -ne 0) {
    Write-ColorOutput "⚠️  Some dependency conflicts detected. Check output above." $Yellow
    Write-ColorOutput "The environment may still work, but conflicts should be resolved." $Yellow
} else {
    Write-ColorOutput "✅ No dependency conflicts found" $Green
}

# Test critical imports
Write-ColorOutput "🧪 Testing critical imports..." $Green
python -c "import talib, numpy, pandas; print('TA-Lib & Sci stack OK')"

if ($LASTEXITCODE -ne 0) {
    Write-ColorOutput "❌ Critical imports failed" $Red
    Write-ColorOutput "The environment setup may have issues." $Yellow
    exit 1
}

Write-ColorOutput "===============================================" $Green
Write-ColorOutput "✅ Setup completed successfully!" $Green
Write-ColorOutput "===============================================" $Green
Write-Host ""
Write-ColorOutput "To activate the environment, run:" $Yellow
Write-ColorOutput "  conda activate $envName" $Yellow
Write-Host ""
Write-ColorOutput "To verify the installation, run:" $Yellow
Write-ColorOutput "  python -c \"import talib, numpy, pandas, ccxt; print('All imports successful')\"" $Yellow
Write-Host ""
Write-ColorOutput "To run the bot:" $Yellow
Write-ColorOutput "  conda activate $envName" $Yellow
Write-ColorOutput "  python main.py" $Yellow
