"""
Canary Health Check Script
Verifies SOL/USD and ADA/USD are appearing in production API
alongside BTC/USD and ETH/USD from Fly.io
"""
import requests
import sys

def check_health():
    print("=" * 70, flush=True)
    print("CANARY HEALTH CHECK", flush=True)
    print("=" * 70, flush=True)
    print("", flush=True)

    # Check 1: Production API reachable
    try:
        response = requests.get("https://crypto-signals-api.fly.dev/v1/signals?limit=50", timeout=10)
        print(f"[PASS] API HTTP Status: {response.status_code}", flush=True)

        if response.status_code != 200:
            print(f"[FAIL] Expected HTTP 200, got {response.status_code}", flush=True)
            return False

        signals = response.json()
        print(f"[PASS] API Response: {len(signals)} signals returned", flush=True)
    except Exception as e:
        print(f"[FAIL] API Error: {e}", flush=True)
        return False

    # Check 2: All 4 pairs present
    pairs = sorted(set(s['pair'] for s in signals))
    expected_pairs = ['ADA-USD', 'BTC-USD', 'ETH-USD', 'SOL-USD']

    if pairs == expected_pairs:
        print(f"[PASS] All 4 pairs present: {pairs}", flush=True)
    else:
        print(f"[FAIL] Expected {expected_pairs}, got {pairs}", flush=True)
        return False

    # Check 3: SOL/ADA signal counts
    counts = {}
    for s in signals:
        counts[s['pair']] = counts.get(s['pair'], 0) + 1

    if counts.get('SOL-USD', 0) > 0 and counts.get('ADA-USD', 0) > 0:
        print(f"[PASS] Canary pairs have signals: SOL={counts['SOL-USD']}, ADA={counts['ADA-USD']}", flush=True)
    else:
        print(f"[FAIL] Missing canary signals: {counts}", flush=True)
        return False

    # Check 4: BTC/ETH still publishing
    if counts.get('BTC-USD', 0) > 0 and counts.get('ETH-USD', 0) > 0:
        print(f"[PASS] Fly.io pairs still active: BTC={counts['BTC-USD']}, ETH={counts['ETH-USD']}", flush=True)
    else:
        print(f"[WARN] Low Fly.io signal counts: {counts}", flush=True)

    print("", flush=True)
    print("=" * 70, flush=True)
    print("HEALTH CHECK: PASSED", flush=True)
    print("=" * 70, flush=True)
    return True

if __name__ == "__main__":
    success = check_health()
    sys.exit(0 if success else 1)
