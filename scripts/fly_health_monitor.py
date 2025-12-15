#!/usr/bin/env python3
"""
Fly.io 24/7 Health Monitor
Continuously checks all system components and alerts on failures
Can be deployed as a separate Fly machine or run as a cron job
"""
import asyncio
import httpx
import json
import time
from datetime import datetime
import sys
import os

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.signals_api_config import SIGNALS_API_HEALTH_URL

# Fix Windows console encoding
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except:
        pass

# Component endpoints
ENDPOINTS = {
    "crypto-ai-bot": "https://crypto-ai-bot.fly.dev/health",
    "signals-api": SIGNALS_API_HEALTH_URL,
    "signals-site": "https://aipredictedsignals.cloud"
}

# Alert thresholds
ALERT_AFTER_FAILURES = 3  # Alert after 3 consecutive failures
CHECK_INTERVAL_SECONDS = 60  # Check every 60 seconds

# State tracking
failure_counts = {name: 0 for name in ENDPOINTS}
last_alert_time = {name: 0 for name in ENDPOINTS}
ALERT_COOLDOWN = 300  # 5 minutes between alerts for same component

async def check_endpoint(client: httpx.AsyncClient, name: str, url: str) -> dict:
    """Check a single endpoint and return health status"""
    try:
        start_time = time.time()
        response = await client.get(url, timeout=10.0)
        elapsed_ms = (time.time() - start_time) * 1000

        return {
            "name": name,
            "url": url,
            "status": "healthy" if response.status_code == 200 else "degraded",
            "status_code": response.status_code,
            "response_time_ms": round(elapsed_ms, 2),
            "timestamp": datetime.utcnow().isoformat(),
            "error": None
        }
    except httpx.TimeoutException:
        return {
            "name": name,
            "url": url,
            "status": "timeout",
            "status_code": None,
            "response_time_ms": None,
            "timestamp": datetime.utcnow().isoformat(),
            "error": "Request timed out after 10s"
        }
    except Exception as e:
        return {
            "name": name,
            "url": url,
            "status": "error",
            "status_code": None,
            "response_time_ms": None,
            "timestamp": datetime.utcnow().isoformat(),
            "error": str(e)
        }

def should_alert(name: str, status: str) -> bool:
    """Determine if we should send an alert for this component"""
    current_time = time.time()

    if status in ["healthy", "degraded"]:
        # Reset failure count on success
        failure_counts[name] = 0
        return False

    # Increment failure count
    failure_counts[name] += 1

    # Check if we should alert
    if failure_counts[name] >= ALERT_AFTER_FAILURES:
        # Check cooldown
        if current_time - last_alert_time[name] > ALERT_COOLDOWN:
            last_alert_time[name] = current_time
            return True

    return False

def send_alert(component: str, status: dict):
    """Send alert for failed component"""
    alert_msg = f"""
🚨 ALERT: {component} is {status['status'].upper()}
Time: {status['timestamp']}
URL: {status['url']}
Error: {status.get('error', 'Unknown error')}
Consecutive failures: {failure_counts[component]}
"""
    print(alert_msg)

    # TODO: Integrate with PagerDuty, Slack, email, etc.
    # For now, just log to stdout/stderr
    sys.stderr.write(alert_msg + "\n")

def print_status_summary(results: list):
    """Print a concise status summary"""
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"\n{'='*80}")
    print(f"Health Check - {timestamp}")
    print(f"{'='*80}")

    all_healthy = True
    for result in results:
        status_emoji = "✅" if result['status'] == "healthy" else "⚠️" if result['status'] == "degraded" else "❌"
        response_time = f"{result['response_time_ms']}ms" if result['response_time_ms'] else "N/A"

        print(f"{status_emoji} {result['name']:20} {result['status']:10} ({response_time})")

        if result['status'] not in ["healthy", "degraded"]:
            all_healthy = False
            print(f"   └─ Error: {result.get('error', 'Unknown')}")

    print(f"{'='*80}")
    if all_healthy:
        print("✅ ALL SYSTEMS OPERATIONAL")
    else:
        print("⚠️  SOME SYSTEMS REQUIRE ATTENTION")
    print()

async def monitor_loop(continuous: bool = True):
    """Main monitoring loop"""
    async with httpx.AsyncClient() as client:
        iteration = 0
        while True:
            iteration += 1
            print(f"\n--- Health Check #{iteration} ---")

            # Check all endpoints concurrently
            tasks = [
                check_endpoint(client, name, url)
                for name, url in ENDPOINTS.items()
            ]
            results = await asyncio.gather(*tasks)

            # Print status summary
            print_status_summary(results)

            # Check for alerts
            for result in results:
                if should_alert(result['name'], result['status']):
                    send_alert(result['name'], result)

            if not continuous:
                break

            # Wait before next check
            print(f"Next check in {CHECK_INTERVAL_SECONDS}s... (Press Ctrl+C to stop)")
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)

async def main():
    """Entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="Fly.io 24/7 Health Monitor")
    parser.add_argument("--once", action="store_true", help="Run once and exit (for cron)")
    parser.add_argument("--interval", type=int, default=60, help="Check interval in seconds (default: 60)")

    args = parser.parse_args()

    global CHECK_INTERVAL_SECONDS
    CHECK_INTERVAL_SECONDS = args.interval

    print("🔍 Fly.io 24/7 Health Monitor")
    print(f"   Monitoring {len(ENDPOINTS)} endpoints")
    print(f"   Check interval: {CHECK_INTERVAL_SECONDS}s")
    print(f"   Alert threshold: {ALERT_AFTER_FAILURES} consecutive failures")
    print()

    try:
        await monitor_loop(continuous=not args.once)
    except KeyboardInterrupt:
        print("\n\n👋 Monitoring stopped by user")

if __name__ == "__main__":
    asyncio.run(main())
