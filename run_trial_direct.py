"""
Direct Paper Trial Runner
Simple script that bypasses complex environment loading
"""
import os
import sys
from pathlib import Path

# Set working directory
os.chdir(r"C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot")
sys.path.insert(0, str(Path.cwd()))

# Set environment variables directly
os.environ["REDIS_URL"] = "rediss://default:Salam78614**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818"
os.environ["REDIS_CA_CERT"] = r"C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem"
os.environ["MODE"] = "paper"
os.environ["TRADING_PAIRS"] = "BTC/USD,ETH/USD"
os.environ["TIMEFRAMES"] = "5m"
os.environ["INITIAL_EQUITY_USD"] = "10000.0"
os.environ["METRICS_PORT"] = "9108"
os.environ["LOG_LEVEL"] = "INFO"

print("=" * 80)
print("PAPER TRADING TRIAL - Step 7 Validation")
print("=" * 80)
print()
print(f"Environment:")
print(f"  MODE: {os.environ['MODE']}")
print(f"  TRADING_PAIRS: {os.environ['TRADING_PAIRS']}")
print(f"  TIMEFRAMES: {os.environ['TIMEFRAMES']}")
print(f"  ML threshold: 0.60 (from config/params/ml.yaml)")
print()
print("Starting trial...")
print()

# Import and run
try:
    # Test Redis first
    print("Testing Redis connection...")
    exec(open("test_redis.py").read())
    print()
    print("Redis OK! Starting paper trial engine...")
    print()

    # Now run the actual trial
    import asyncio
    from scripts.run_paper_trial import main

    # Run async main
    asyncio.run(main())

except KeyboardInterrupt:
    print("\n\nTrial stopped by user (Ctrl+C)")
    sys.exit(0)
except Exception as e:
    print(f"\n\nERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
