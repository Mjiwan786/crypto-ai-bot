# Windows Environment Setup Guide

This guide explains how to set up a reproducible development environment for the Crypto AI Trading Bot on Windows using Conda and TA-Lib.

## Prerequisites

Before running the setup script, ensure you have:

1. **Conda installed**: Either [Miniconda](https://docs.conda.io/en/latest/miniconda.html) or [Anaconda](https://www.anaconda.com/products/distribution)
2. **PowerShell**: Windows PowerShell 5.1+ or PowerShell Core 6+
3. **Git**: For cloning the repository (if not already done)

## Quick Setup

Run the automated setup script:

```powershell
# Navigate to the project root
cd C:\path\to\crypto_ai_bot

# Run the setup script
.\scripts\windows\setup_conda.ps1
```

## What the Script Does

The `setup_conda.ps1` script performs the following steps:

1. **Validates Prerequisites**: Checks if Conda is installed and accessible
2. **Creates Environment**: Creates a new conda environment named `crypto-bot` with Python 3.10
3. **Installs TA-Lib**: Installs TA-Lib 0.6.4 from conda-forge (handles Windows compilation issues)
4. **Upgrades Pip**: Ensures pip is up to date
5. **Installs Dependencies**: Installs all packages from `requirements.txt`
6. **Validates Installation**: Checks for dependency conflicts and tests critical imports

## Script Options

```powershell
# Force recreate existing environment
.\scripts\windows\setup_conda.ps1 -Force

# Skip conda installation checks (if you're sure conda is available)
.\scripts\windows\setup_conda.ps1 -SkipCondaInstall
```

## Expected Output

When successful, you should see output similar to:

```
===============================================
Crypto AI Trading Bot - Windows Setup
===============================================

✅ Conda found: conda 23.x.x
🐍 Creating conda environment 'crypto-bot' with Python 3.10...
📦 Installing TA-Lib from conda-forge...
⬆️  Upgrading pip...
📋 Installing requirements from requirements.txt...
🔍 Checking for dependency conflicts...
✅ No dependency conflicts found
🧪 Testing critical imports...
TA-Lib & Sci stack OK
===============================================
✅ Setup completed successfully!
===============================================

To activate the environment, run:
  conda activate crypto-bot
```

## Manual Setup (Alternative)

If the automated script fails, you can set up the environment manually:

```powershell
# Create conda environment
conda create -n crypto-bot python=3.10 -y

# Activate environment
conda activate crypto-bot

# Install TA-Lib from conda-forge (recommended for Windows)
conda install -c conda-forge ta-lib=0.6.4 -y

# Upgrade pip
python -m pip install --upgrade pip

# Install requirements
pip install -r requirements.txt

# Verify installation
pip check
python -c "import talib, numpy, pandas; print('TA-Lib & Sci stack OK')"
```

## Activating the Environment

After successful setup, activate the environment:

```powershell
conda activate crypto-bot
```

## Verifying the Installation

Test that everything is working:

```powershell
# Activate environment first
conda activate crypto-bot

# Test critical imports
python -c "import talib, numpy, pandas, ccxt; print('All imports successful')"

# Run a quick test
python -c "import talib; print('TA-Lib version:', talib.__version__)"
```

## Running the Bot

Once the environment is set up and activated:

```powershell
# Activate environment
conda activate crypto-bot

# Run the main application
python main.py
```

## Troubleshooting

### TA-Lib Installation Issues

If TA-Lib installation fails:

1. **Try conda-forge first** (recommended):
   ```powershell
   conda install -c conda-forge ta-lib=0.6.4 -y
   ```

2. **Fallback to pip**:
   ```powershell
   pip install TA-Lib
   ```

3. **Manual wheel installation** (if both fail):
   - Download the appropriate wheel from [PyPI](https://pypi.org/project/TA-Lib/#files)
   - Install: `pip install path\to\downloaded\wheel.whl`

### Dependency Conflicts

If you see dependency conflicts:

```powershell
# Check for conflicts
pip check

# Update conflicting packages
pip install --upgrade package-name

# Or recreate environment
conda env remove -n crypto-bot -y
.\scripts\windows\setup_conda.ps1
```

### Environment Not Found

If conda can't find the environment:

```powershell
# List all environments
conda env list

# If crypto-bot is missing, recreate it
.\scripts\windows\setup_conda.ps1
```

## Environment Management

### Deactivating
```powershell
conda deactivate
```

### Removing Environment
```powershell
conda env remove -n crypto-bot -y
```

### Updating Dependencies
```powershell
conda activate crypto-bot
pip install -r requirements.txt --upgrade
```

## File Structure

The setup creates the following structure:

```
crypto_ai_bot/
├── scripts/
│   └── windows/
│       └── setup_conda.ps1    # This setup script
├── docs/
│   └── env_setup_windows.md   # This documentation
└── requirements.txt           # Python dependencies
```

## Notes

- The environment name is hardcoded as `crypto-bot` to match the project requirements
- TA-Lib is installed from conda-forge to avoid Windows compilation issues
- All dependencies are pinned to specific versions for reproducibility
- The script includes error handling and colored output for better user experience
- PowerShell execution policy may need to be adjusted if script execution is blocked

## Support

If you encounter issues not covered in this guide:

1. Check the [main README](../README.md) for general setup information
2. Review the [architecture documentation](README-ARCH.md) for system requirements
3. Check the project's issue tracker for known problems
4. Ensure your Windows version and PowerShell version are compatible
