# Windows Prerequisites Checklist

## Environment Setup
- [ ] **Conda Environment**: Create `crypto-bot` environment
  ```powershell
  conda create -n crypto-bot python=3.10
  conda activate crypto-bot
  ```

## System Requirements
- [ ] **Python 3.10**: Verify installation
  ```powershell
  python --version
  # Expected: Python 3.10.x
  ```
- [ ] **Git**: Verify installation
  ```powershell
  git --version
  # Expected: git version 2.x.x or later
  ```

## Trading Platform Credentials
- [ ] **Kraken API Key**: Live trading API credentials
- [ ] **Kraken API Secret**: Corresponding secret key
- [ ] **Kraken Sandbox**: Optional for testing (see note below)

## Infrastructure Services
- [ ] **Redis Cloud TLS Credentials**: 
  - Redis Cloud connection string
  - TLS certificate files (if required)
  - Authentication credentials

## Optional Integrations
- [ ] **Discord Webhook**: For notifications and alerts
- [ ] **Telegram Bot**: For mobile notifications and commands

## Network Requirements
- [ ] **Outbound Internet Access**:
  - [ ] Kraken API endpoints (api.kraken.com)
  - [ ] Kraken WebSocket (ws.kraken.com)
  - [ ] Redis Cloud endpoints
  - [ ] Discord/Telegram APIs (if using notifications)

## Environment Variables
- [ ] **Paper Trading Mode**: Set `PAPER_TRADING=true`
- [ ] **Kraken Sandbox**: `KRAKEN_SANDBOX=false` is acceptable in paper mode

> **Note**: Start with `PAPER_TRADING=true`. `KRAKEN_SANDBOX=false` is okay because paper mode blocks live orders regardless of sandbox setting.

## Verification Commands
Run these PowerShell commands to verify your setup:

```powershell
# Check Python version
python --version

# Check Git version  
git --version

# Verify conda environment
conda info --envs

# Activate crypto-bot environment
conda activate crypto-bot

# Verify environment is active
echo $env:CONDA_DEFAULT_ENV
```

## Next Steps
1. Clone the repository
2. Install dependencies: `pip install -r requirements.txt`
3. Configure environment variables
4. Run preflight checks: `python scripts/preflight.py`
