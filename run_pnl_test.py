#!/usr/bin/env python3
"""
Quick PnL pipeline test runner.
Sets environment variables and runs aggregator + seed + health check.
"""
import os
import subprocess
import sys
import time

# Set environment variables
os.environ["REDIS_URL"] = "rediss://default:Salam78614**%24%24@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818/0"
os.environ["EMIT_PNL_EVENTS"] = "true"
os.environ["START_EQUITY"] = "10000"

print("=" * 70)
print("PNL PIPELINE TEST")
print("=" * 70)
print(f"Redis URL: {os.environ['REDIS_URL'][:50]}...")
print(f"Start Equity: ${os.environ['START_EQUITY']}")
print("=" * 70 + "\n")

def run_command(cmd, description, wait=True):
    """Run a command and print output."""
    print(f"\n{'='*70}")
    print(f"  {description}")
    print(f"{'='*70}\n")

    if wait:
        result = subprocess.run(cmd, shell=True)
        return result.returncode == 0
    else:
        # Run in background
        proc = subprocess.Popen(cmd, shell=True)
        return proc

# Step 1: Start aggregator in background
print("Step 1: Starting aggregator...")
aggregator = run_command("python -m monitoring.pnl_aggregator", "PnL Aggregator", wait=False)
time.sleep(3)  # Give it time to start

# Step 2: Seed trades
print("\nStep 2: Seeding trades...")
success = run_command(
    "python scripts/seed_closed_trades.py --count 10 --interval 0.5",
    "Seed 10 trades"
)

if not success:
    print("\nFailed to seed trades!")
    aggregator.terminate()
    sys.exit(1)

# Give aggregator time to process
time.sleep(2)

# Step 3: Health check
print("\nStep 3: Running health check...")
success = run_command(
    "python scripts/health_check_pnl.py --verbose",
    "Health Check"
)

# Step 4: Verify loop
print("\nStep 4: Verifying PnL loop...")
success = run_command(
    "python scripts/verify_pnl_loop.py --verbose",
    "Loop Verification"
)

# Cleanup
print("\n" + "=" * 70)
print("Stopping aggregator...")
aggregator.terminate()
aggregator.wait()

print("\nTest complete!")
print("=" * 70)
