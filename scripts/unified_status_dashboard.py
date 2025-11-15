"""
Unified Status Dashboard for Crypto AI Bot System
Monitors: crypto-ai-bot, signals-api, signals-site, Redis streams
"""
import requests
import redis
import json
import time
from datetime import datetime
import os
import ssl
import sys

# Fix Windows console encoding
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

# Configuration
CRYPTO_AI_BOT_HEALTH = "https://crypto-ai-bot.fly.dev/health"
SIGNALS_API_HEALTH = "https://crypto-signals-api.fly.dev/health"
SIGNALS_SITE_URL = "https://aipredictedsignals.cloud"

REDIS_URL = "rediss://default:Salam78614**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818"
REDIS_CA_CERT = r"C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem"

def get_redis_client():
    """Create Redis client with TLS"""
    return redis.from_url(
        REDIS_URL,
        ssl_cert_reqs=ssl.CERT_REQUIRED,
        ssl_ca_certs=REDIS_CA_CERT,
        decode_responses=True
    )

def check_health_endpoint(url, name, timeout=10):
    """Check a health endpoint"""
    try:
        response = requests.get(url, timeout=timeout)
        return {
            "name": name,
            "status": "✅ HEALTHY" if response.status_code == 200 else f"⚠️  STATUS {response.status_code}",
            "status_code": response.status_code,
            "response_time_ms": round(response.elapsed.total_seconds() * 1000, 2),
            "data": response.json() if response.status_code == 200 else None
        }
    except requests.exceptions.Timeout:
        return {"name": name, "status": "❌ TIMEOUT", "status_code": None, "response_time_ms": None, "data": None}
    except requests.exceptions.RequestException as e:
        return {"name": name, "status": f"❌ ERROR", "status_code": None, "response_time_ms": None, "error": str(e)}

def check_redis_streams():
    """Check Redis streams for recent activity"""
    try:
        r = get_redis_client()

        # Check key Redis streams
        streams_to_check = [
            "signals:paper",
            "kraken:orderbook:BTC/USD",
            "kraken:trades:BTC/USD"
        ]

        stream_status = {}
        for stream_name in streams_to_check:
            try:
                # Get stream info
                info = r.xinfo_stream(stream_name)
                length = info.get('length', 0)

                # Get latest entry
                entries = r.xrevrange(stream_name, count=1)
                if entries:
                    latest_id, latest_data = entries[0]
                    timestamp_ms = int(latest_id.split('-')[0])
                    age_seconds = (time.time() * 1000 - timestamp_ms) / 1000

                    stream_status[stream_name] = {
                        "status": "✅ ACTIVE" if age_seconds < 120 else "⚠️  STALE",
                        "length": length,
                        "age_seconds": round(age_seconds, 2),
                        "last_entry_time": datetime.fromtimestamp(timestamp_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")
                    }
                else:
                    stream_status[stream_name] = {
                        "status": "❌ EMPTY",
                        "length": length,
                        "age_seconds": None,
                        "last_entry_time": None
                    }
            except redis.exceptions.ResponseError:
                stream_status[stream_name] = {
                    "status": "❌ NOT FOUND",
                    "length": 0,
                    "age_seconds": None,
                    "last_entry_time": None
                }

        return {"status": "✅ CONNECTED", "streams": stream_status}
    except Exception as e:
        return {"status": f"❌ ERROR: {str(e)}", "streams": {}}

def print_status_report(results):
    """Print a formatted status report"""
    print("\n" + "="*80)
    print(f"🚀 CRYPTO AI BOT SYSTEM STATUS - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80 + "\n")

    # Health Endpoints
    print("📊 HEALTH ENDPOINTS:")
    print("-" * 80)
    for endpoint_name in ["crypto-ai-bot", "signals-api", "signals-site"]:
        result = results.get(endpoint_name, {})
        print(f"  {endpoint_name:20} {result.get('status', '❌ NOT CHECKED'):15} "
              f"({result.get('response_time_ms', 'N/A')} ms)")
        if result.get('data'):
            data = result['data']
            if 'uptime_seconds' in data:
                uptime_hours = round(data['uptime_seconds'] / 3600, 2)
                print(f"                       Uptime: {uptime_hours}h | Redis ping: {data.get('redis_ping_ms', 'N/A')}ms")

    print("\n")

    # Redis Streams
    redis_result = results.get("redis", {})
    print(f"📡 REDIS CONNECTION: {redis_result.get('status', '❌ NOT CHECKED')}")
    print("-" * 80)
    streams = redis_result.get('streams', {})
    if streams:
        for stream_name, stream_data in streams.items():
            print(f"  {stream_name:40} {stream_data.get('status', 'UNKNOWN'):15}")
            if stream_data.get('age_seconds') is not None:
                print(f"    ├─ Length: {stream_data.get('length', 0):,} entries")
                print(f"    ├─ Last updated: {stream_data.get('age_seconds', 0):.2f}s ago")
                print(f"    └─ Timestamp: {stream_data.get('last_entry_time', 'N/A')}")

    print("\n" + "="*80 + "\n")

    # Summary
    all_healthy = all(
        r.get('status_code') == 200 if 'status_code' in r else False
        for r in [results.get('crypto-ai-bot', {}), results.get('signals-api', {})]
    )
    redis_healthy = "✅" in redis_result.get('status', '')

    if all_healthy and redis_healthy:
        print("✅ ALL SYSTEMS OPERATIONAL")
    else:
        print("⚠️  SOME SYSTEMS REQUIRE ATTENTION")

    print()

def run_dashboard(continuous=False, interval=300):
    """Run the status dashboard"""
    while True:
        results = {}

        # Check all health endpoints
        results['crypto-ai-bot'] = check_health_endpoint(CRYPTO_AI_BOT_HEALTH, "crypto-ai-bot")
        results['signals-api'] = check_health_endpoint(SIGNALS_API_HEALTH, "signals-api")
        results['signals-site'] = check_health_endpoint(SIGNALS_SITE_URL, "signals-site", timeout=5)

        # Check Redis streams
        results['redis'] = check_redis_streams()

        # Print report
        print_status_report(results)

        if not continuous:
            break

        print(f"Next update in {interval} seconds... (Press Ctrl+C to stop)")
        time.sleep(interval)

if __name__ == "__main__":
    import sys

    continuous = "--continuous" in sys.argv or "-c" in sys.argv

    # Get interval from args (default 300 seconds = 5 minutes)
    interval = 300
    for arg in sys.argv:
        if arg.startswith("--interval="):
            interval = int(arg.split("=")[1])

    try:
        run_dashboard(continuous=continuous, interval=interval)
    except KeyboardInterrupt:
        print("\n\n👋 Dashboard stopped by user")
