#!/usr/bin/env python3
"""
preflight.py — Crypto AI Bot
Production preflight & environment validator.

Checks:
  1) Required environment variables present
  2) Redis PING + XADD test (signals:*)
  3) Kraken public status OK
  4) Rate-limit module loaded (if applicable)
  5) Risk allocations sane (≈1.0)

Exit codes:
  0 = READY
  2 = DEGRADED  
  1 = NOT_READY

Usage:
  python scripts/preflight.py --env .env.staging --verbose
"""

from __future__ import annotations
import os
import sys
import time
import json
import argparse
import logging
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timezone

# Dependencies
try:
    from dotenv import load_dotenv
except ImportError:
    print("Error: python-dotenv required. Install with: pip install python-dotenv")
    sys.exit(1)

try:
    import redis
except ImportError:
    print("Error: redis required. Install with: pip install redis")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("Error: requests required. Install with: pip install requests")
    sys.exit(1)

try:
    import yaml
except ImportError:
    print("Error: PyYAML required. Install with: pip install PyYAML")
    sys.exit(1)

# Setup logging
LOG = logging.getLogger("preflight")

# Result codes
READY = 0
DEGRADED = 2
NOT_READY = 1

# Required environment variables
REQUIRED_ENVS = [
    "ENVIRONMENT", "TIMEZONE", "LOG_LEVEL", "PAPER_TRADING_ENABLED", 
    "LIVE_TRADING_CONFIRMATION", "REDIS_URL", "KRAKEN_API_URL"
]


def ok(msg: str) -> None:
    """Print success message with ✅"""
    print(f"[OK] {msg}")


def warn(msg: str) -> None:
    """Print warning message with ⚠️"""
    print(f"[WARN] {msg}")


def fail(msg: str) -> None:
    """Print failure message with ❌"""
    print(f"[FAIL] {msg}")


def timeit(func):
    """Simple timing decorator"""
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        elapsed = (time.time() - start) * 1000
        return result, elapsed
    return wrapper


def check_required_envs() -> Tuple[bool, List[str]]:
    """Check if all required environment variables are present"""
    missing = []
    for env_var in REQUIRED_ENVS:
        if not os.getenv(env_var):
            missing.append(env_var)
    
    if missing:
        fail(f"Missing required environment variables: {', '.join(missing)}")
        return False, missing
    
    present_vars = [var for var in REQUIRED_ENVS if os.getenv(var)]
    ok(f"Envs present: {', '.join(present_vars)}")
    return True, []


def test_redis_connection() -> Tuple[bool, str, float]:
    """Test Redis connection, PING, and XADD/XREAD"""
    start_time = time.time()
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        return False, "REDIS_URL not set", 0.0
    
    try:
        # Parse Redis URL
        if not redis_url.startswith(("redis://", "rediss://")):
            return False, "REDIS_URL must start with redis:// or rediss://", 0.0
        
        # Connect with timeout
        r = redis.Redis.from_url(redis_url, socket_timeout=5, socket_connect_timeout=5)
        
        # PING test
        if not r.ping():
            return False, "Redis PING failed", 0.0
        
        # Determine stream name based on mode
        paper_mode = os.getenv("PAPER_TRADING_ENABLED", "true").lower() in ("true", "1", "yes")
        stream_name = "signals:paper" if paper_mode else "signals:live"
        
        # XADD test
        test_entry = {
            "preflight": "ok",
            "ts": datetime.now(timezone.utc).isoformat()
        }
        
        entry_id = r.xadd(stream_name, test_entry)
        
        # XREAD back the last item
        result = r.xread({stream_name: "0-0"}, count=1, block=1000)
        
        if not result:
            return False, "XREAD failed - no data returned", 0.0
        
        elapsed = (time.time() - start_time) * 1000
        return True, f"PING ok, XADD/XREAD ok on stream {stream_name}", elapsed
        
    except redis.exceptions.ConnectionError as e:
        return False, f"Redis connection failed: {e}", 0.0
    except redis.exceptions.TimeoutError as e:
        return False, f"Redis timeout: {e}", 0.0
    except Exception as e:
        return False, f"Redis error: {e}", 0.0


def test_kraken_status() -> Tuple[bool, str, float]:
    """Test Kraken public API status"""
    start_time = time.time()
    kraken_url = os.getenv("KRAKEN_API_URL", "https://api.kraken.com")
    status_url = f"{kraken_url}/0/public/SystemStatus"
    
    try:
        response = requests.get(status_url, timeout=10)
        
        if response.status_code != 200:
            return False, f"HTTP {response.status_code}", 0.0
        
        data = response.json()
        
        if "result" in data and "status" in data["result"]:
            status = data["result"]["status"]
            if status in ["online", "healthy", "operational"]:
                elapsed = (time.time() - start_time) * 1000
                return True, f"SystemStatus={status}", elapsed
            else:
                return False, f"SystemStatus={status} (not healthy)", 0.0
        else:
            return False, "Invalid response format", 0.0
            
    except requests.exceptions.Timeout:
        return False, "Request timeout", 0.0
    except requests.exceptions.ConnectionError:
        return False, "Connection failed", 0.0
    except json.JSONDecodeError:
        return False, "Invalid JSON response", 0.0
    except Exception as e:
        return False, f"Error: {e}", 0.0


def check_rate_limit_module() -> Tuple[bool, str]:
    """Check if rate-limit module is available"""
    modules_to_try = [
        "utils.rate_limit",
        "agents.common.rate_limit", 
        "agents.rate_limit"
    ]
    
    for module_name in modules_to_try:
        try:
            __import__(module_name)
            return True, f"Rate-limit module found: {module_name}"
        except ImportError:
            continue
    
    return False, "Rate-limit module not found"


def check_risk_allocations() -> Tuple[bool, str]:
    """Check if risk allocations sum to approximately 1.0"""
    try:
        # Try to load config via merge_config
        from config.merge_config import load_config
        
        env = os.getenv("ENVIRONMENT", "staging")
        config = load_config(env)
        
        if "strategies" not in config or "allocations" not in config["strategies"]:
            return False, "No allocations found in config"
        
        allocations = config["strategies"]["allocations"]
        total = sum(allocations.values())
        
        if 0.99 <= total <= 1.01:
            return True, f"Allocations sum={total:.3f} (good)"
        else:
            return False, f"Allocations sum={total:.3f} (expected ~1.0)"
            
    except ImportError:
        return False, "Config loader not available"
    except Exception as e:
        return False, f"Config error: {e}"


def main():
    """Main preflight function"""
    parser = argparse.ArgumentParser(description="Crypto AI Bot preflight validator")
    parser.add_argument("--env", default=".env", help="Path to .env file (default: .env)")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()
    
    # Setup logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="[Preflight] %(message)s")
    
    print(f"[Preflight] Start — env: {args.env}")
    
    # Load environment file
    if os.path.exists(args.env):
        load_dotenv(args.env, override=True)
        if args.verbose:
            print(f"[Preflight] Loaded environment from {args.env}")
    else:
        if args.verbose:
            print(f"[Preflight] No .env file found at {args.env}, using system environment")
    
    # Track results
    results = []
    
    # 1. Check required environment variables
    env_ok, missing = check_required_envs()
    results.append(NOT_READY if not env_ok else READY)
    
    if not env_ok:
        print("RESULT: NOT_READY")
        sys.exit(NOT_READY)
    
    # 2. Test Redis connection
    redis_ok, redis_msg, redis_time = test_redis_connection()
    if redis_ok:
        ok(f"Redis: {redis_msg} ({redis_time:.1f} ms)")
        results.append(READY)
    else:
        fail(f"Redis: {redis_msg}")
        results.append(NOT_READY)
    
    # 3. Test Kraken status
    kraken_ok, kraken_msg, kraken_time = test_kraken_status()
    if kraken_ok:
        ok(f"Kraken: {kraken_msg} ({kraken_time:.0f} ms)")
        results.append(READY)
    else:
        fail(f"Kraken: {kraken_msg}")
        results.append(NOT_READY)
    
    # 4. Check rate-limit module
    rate_ok, rate_msg = check_rate_limit_module()
    if rate_ok:
        ok(f"Rate-limit module: {rate_msg}")
        results.append(READY)
    else:
        warn(f"Rate-limit module: {rate_msg} — enable for prod to avoid 429s")
        results.append(DEGRADED)
    
    # 5. Check risk allocations
    alloc_ok, alloc_msg = check_risk_allocations()
    if alloc_ok:
        ok(f"Allocations: {alloc_msg}")
        results.append(READY)
    else:
        warn(f"Allocations: {alloc_msg}")
        results.append(DEGRADED)
    
    # Determine final result
    if NOT_READY in results:
        print("RESULT: NOT_READY")
        sys.exit(NOT_READY)
    elif DEGRADED in results:
        print("RESULT: DEGRADED")
        sys.exit(DEGRADED)
    else:
        print("RESULT: READY")
        sys.exit(READY)


if __name__ == "__main__":
    main()