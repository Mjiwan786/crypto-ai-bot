#!/usr/bin/env python3
"""
Production launcher for crypto-ai-bot.
Loads .env.prod and starts the main module.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load .env.prod
env_path = Path(__file__).parent / ".env.prod"
print(f"Loading environment from: {env_path}")
load_dotenv(env_path)

# Verify key vars loaded
redis_url = os.getenv('REDIS_URL', '')
if redis_url:
    print(f"[OK] REDIS_URL loaded: {redis_url[:30]}...")
else:
    print("[WARN] REDIS_URL not loaded")

trading_pairs = os.getenv('TRADING_PAIRS', '')
if trading_pairs:
    print(f"[OK] TRADING_PAIRS loaded: {trading_pairs}")
else:
    print("[WARN] TRADING_PAIRS not loaded")

# Now run main as subprocess
print("\nStarting crypto-ai-bot...")
import subprocess
result = subprocess.run([
    sys.executable, '-m', 'main',
    'run', '--mode', 'paper', '--config', 'config/settings.yaml'
], env=os.environ.copy())
sys.exit(result.returncode)
