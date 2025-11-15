#!/usr/bin/env python3
"""
Simple Paper Trading Preflight Check
Validates environment is ready for paper trading deployment.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load paper trading environment
load_dotenv('.env.paper')

print("="*80)
print("PAPER TRADING PREFLIGHT CHECK")
print("="*80)

checks_passed = 0
checks_failed = 0

def check(name, condition, message):
    global checks_passed, checks_failed
    status = "PASS" if condition else "FAIL"
    symbol = "[OK]" if condition else "[X]"
    print(f"{symbol} {name}: {message}")
    if condition:
        checks_passed += 1
    else:
        checks_failed += 1
    return condition

# 1. Check conda environment
conda_env = os.getenv("CONDA_DEFAULT_ENV")
check("Conda Environment", conda_env == "crypto-bot", f"{conda_env}")

# 2. Check .env.paper exists
env_paper_path = Path(".env.paper")
check(".env.paper exists", env_paper_path.exists(), str(env_paper_path))

# 3. Check Redis URL
redis_url = os.getenv("REDIS_URL")
check("REDIS_URL set", redis_url is not None and redis_url.startswith("rediss://"),
      "rediss://... configured")

# 4. Check Redis CA cert
ca_cert_path = Path(os.getenv("REDIS_CA_CERT", ""))
check("Redis CA certificate", ca_cert_path.exists() if ca_cert_path else False,
      str(ca_cert_path) if ca_cert_path else "not set")

# 5. Check strategy config
strategy_config = Path(os.getenv("STRATEGY_CONFIG", "config/bar_reaction_5m.yaml"))
check("Strategy config", strategy_config.exists(), str(strategy_config))

# 6. Check mode is paper
mode = os.getenv("MODE", "").lower()
bot_mode = os.getenv("BOT_MODE", "").upper()
check("Mode is PAPER", mode == "paper" or bot_mode == "PAPER",
      f"MODE={mode}, BOT_MODE={bot_mode}")

# 7. Check trading pair
pairs = os.getenv("TRADING_PAIRS", os.getenv("PAIRS", ""))
check("Trading pair set", "BTC/USD" in pairs, f"{pairs}")

# 8. Check timeframe
timeframe = os.getenv("TIMEFRAME", os.getenv("TIMEFRAMES", ""))
check("Timeframe set", "5m" in timeframe, f"{timeframe}")

# 9. Check initial capital
capital = os.getenv("INITIAL_EQUITY_USD", os.getenv("CAPITAL", ""))
check("Initial capital set", capital, f"${capital}")

# 10. Check live trading is disabled
live_enabled = os.getenv("ENABLE_TRADING", "").lower() == "true"
check("Live trading DISABLED", not live_enabled, f"ENABLE_TRADING={os.getenv('ENABLE_TRADING')}")

# 11. Test Redis connection
print("\n" + "-"*80)
print("Testing Redis connection...")
print("-"*80)

try:
    import redis
    client = redis.from_url(
        redis_url,
        ssl_ca_certs=str(ca_cert_path),
        ssl_cert_reqs='required',
        decode_responses=True
    )
    client.ping()
    print(f"[OK] Redis connection successful")
    try:
        info = client.info('server')
        print(f"     Redis version: {info.get('redis_version', 'unknown')}")
    except:
        print(f"     Redis server responding")
    checks_passed += 1
except Exception as e:
    print(f"[X] Redis connection failed: {e}")
    checks_failed += 1

# 12. Check required Python packages
print("\n" + "-"*80)
print("Checking Python dependencies...")
print("-"*80)

required_packages = [
    'redis',
    'pandas',
    'numpy',
    'yaml',
    'ccxt',
    'dotenv',
]

for package in required_packages:
    try:
        __import__(package)
        print(f"[OK] {package}")
        checks_passed += 1
    except ImportError:
        print(f"[X] {package} - NOT INSTALLED")
        checks_failed += 1

# Summary
print("\n" + "="*80)
print("PREFLIGHT SUMMARY")
print("="*80)
print(f"Checks passed: {checks_passed}")
print(f"Checks failed: {checks_failed}")

if checks_failed == 0:
    print("\n[OK] ALL CHECKS PASSED - READY FOR PAPER TRADING")
    print("="*80)
    print("\nNext steps:")
    print("1. Start paper trading: python scripts/run_paper_trial.py")
    print("2. Monitor: python scripts/monitor_paper_trial.py")
    print("3. Validate daily: python scripts/validate_paper_trading.py --from-redis")
    print("="*80)
    sys.exit(0)
else:
    print("\n[X] PREFLIGHT FAILED - FIX ISSUES BEFORE STARTING")
    print("="*80)
    sys.exit(1)
