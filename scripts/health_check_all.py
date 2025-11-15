#!/usr/bin/env python3
"""
Comprehensive health check for all 3 systems:
- Redis Cloud
- Signals API
- Signals Site
"""
import sys
import time
import json

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

try:
    import redis
except ImportError:
    print("ERROR: redis package not installed")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("ERROR: requests package not installed")
    sys.exit(1)

# Configuration
REDIS_URL = "rediss://default:Salam78614%2A%2A%24%24@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818"
REDIS_CERT = r"C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem"
API_URL = "http://localhost:8000"
SITE_URL = "http://localhost:3000"

def check_redis():
    """Check Redis connectivity and data freshness"""
    try:
        client = redis.from_url(
            REDIS_URL,
            ssl_ca_certs=REDIS_CERT,
            decode_responses=True,
            socket_timeout=5
        )
        client.ping()

        # Check stream activity
        trades_len = client.xlen("trades:closed")
        equity_len = client.xlen("pnl:equity")

        # Check data freshness
        latest = client.get("pnl:equity:latest")
        if latest:
            data = json.loads(latest)
            age_seconds = time.time() - (data['ts'] / 1000)
            fresh = age_seconds < 300  # Less than 5 minutes old
            age_str = f"{int(age_seconds)}s ago"
        else:
            fresh = False
            age_str = "N/A"

        # Check for recent trades
        recent_trades = age_seconds < 60 if latest else False

        return {
            "status": "✅ OK",
            "connected": True,
            "trades_total": trades_len,
            "equity_points": equity_len,
            "data_fresh": "✅ Yes" if fresh else "⚠️ No",
            "last_update": age_str,
            "recent_trades": "✅ Yes" if recent_trades else "⚠️ No (>1min)"
        }
    except Exception as e:
        return {
            "status": f"❌ FAIL",
            "connected": False,
            "error": str(e)
        }

def check_api():
    """Check signals-api health"""
    try:
        resp = requests.get(f"{API_URL}/health", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            return {
                "status": "✅ OK",
                "connected": True,
                "response": data,
                "url": API_URL
            }
        else:
            return {
                "status": f"⚠️ WARN",
                "connected": True,
                "http_code": resp.status_code,
                "url": API_URL
            }
    except requests.exceptions.ConnectionError:
        return {
            "status": "❌ NOT RUNNING",
            "connected": False,
            "error": "Connection refused - API not started?",
            "url": API_URL
        }
    except Exception as e:
        return {
            "status": f"❌ FAIL",
            "connected": False,
            "error": str(e),
            "url": API_URL
        }

def check_site():
    """Check signals-site availability"""
    try:
        resp = requests.get(SITE_URL, timeout=5)
        if resp.status_code == 200:
            return {
                "status": "✅ OK",
                "connected": True,
                "url": SITE_URL
            }
        else:
            return {
                "status": f"⚠️ WARN",
                "connected": True,
                "http_code": resp.status_code,
                "url": SITE_URL
            }
    except requests.exceptions.ConnectionError:
        return {
            "status": "❌ NOT RUNNING",
            "connected": False,
            "error": "Connection refused - Site not started?",
            "url": SITE_URL
        }
    except Exception as e:
        return {
            "status": f"❌ FAIL",
            "connected": False,
            "error": str(e),
            "url": SITE_URL
        }

def main():
    print("=" * 70)
    print("SYSTEM HEALTH CHECK - All Components")
    print("=" * 70)

    results = {
        "Redis Cloud": check_redis(),
        "Signals API": check_api(),
        "Signals Site": check_site()
    }

    for component, result in results.items():
        print(f"\n{component}:")
        for key, value in result.items():
            print(f"  {key}: {value}")

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    # Count statuses
    ok_count = sum(1 for r in results.values() if "✅" in str(r.get("status", "")))
    total_count = len(results)

    print(f"\nComponents OK: {ok_count}/{total_count}")

    if ok_count == total_count:
        print("\n✅ ALL SYSTEMS OPERATIONAL")
        exit_code = 0
    elif ok_count > 0:
        print(f"\n⚠️ PARTIAL OPERATION ({ok_count}/{total_count} working)")
        exit_code = 1
    else:
        print("\n❌ ALL SYSTEMS DOWN")
        exit_code = 2

    print("\n" + "=" * 70)
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
