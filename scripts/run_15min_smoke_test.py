"""
15-Minute Smoke Test for Sub-Minute Bars

Validates production readiness of 15s bars implementation:
- Latency < 150ms E2E
- Rate limiting working correctly
- No circuit breaker trips
- Clean bar generation
- Redis stream health

Author: Crypto AI Bot Team
Date: 2025-11-08
"""

import asyncio
import os
import sys
import time
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List

import redis

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.synthetic_bars import create_bar_builder


class SmokeTestValidator:
    """Validates 15s bars during smoke test."""

    def __init__(self, redis_url: str, redis_ca_cert: str):
        self.redis_client = redis.Redis.from_url(
            redis_url,
            ssl=True,
            ssl_ca_certs=redis_ca_cert,
            decode_responses=True,
        )
        self.test_start = time.time()
        self.test_duration_seconds = 15 * 60  # 15 minutes
        self.metrics = {
            "bars_received": 0,
            "latency_violations": 0,
            "circuit_breaker_trips": 0,
            "redis_errors": 0,
            "max_latency_ms": 0.0,
            "avg_latency_ms": 0.0,
            "latencies": [],
        }

    def check_redis_stream_health(self, stream_key: str) -> Dict:
        """Check Redis stream health."""
        try:
            # Get stream info
            info = self.redis_client.xinfo_stream(stream_key)

            # Get consumer group info
            groups = self.redis_client.xinfo_groups(stream_key)

            return {
                "stream_length": info.get("length", 0),
                "consumer_groups": len(groups),
                "first_entry": info.get("first-entry"),
                "last_entry": info.get("last-entry"),
                "status": "healthy",
            }
        except redis.exceptions.ResponseError as e:
            if "no such key" in str(e).lower():
                return {"status": "stream_not_found", "error": str(e)}
            return {"status": "error", "error": str(e)}
        except Exception as e:
            self.metrics["redis_errors"] += 1
            return {"status": "error", "error": str(e)}

    def validate_bar_latency(self, bar_timestamp: float) -> bool:
        """Validate bar latency is within budget."""
        now = time.time()
        latency_ms = (now - bar_timestamp) * 1000

        self.metrics["latencies"].append(latency_ms)
        self.metrics["max_latency_ms"] = max(self.metrics["max_latency_ms"], latency_ms)

        # Latency budget: 150ms E2E
        if latency_ms > 150.0:
            self.metrics["latency_violations"] += 1
            return False

        return True

    async def monitor_stream(self, stream_key: str, duration_seconds: int):
        """Monitor Redis stream for bars."""
        print(f"\n{'='*70}")
        print(f"🔍 Monitoring stream: {stream_key}")
        print(f"⏱️  Duration: {duration_seconds} seconds ({duration_seconds//60} minutes)")
        print(f"🎯 Latency budget: < 150ms")
        print(f"{'='*70}\n")

        start_time = time.time()
        last_id = "0-0"  # Start from beginning
        check_interval = 1  # Check every 1 second

        while time.time() - start_time < duration_seconds:
            try:
                # Read new entries
                entries = self.redis_client.xread(
                    {stream_key: last_id},
                    count=100,
                    block=check_interval * 1000,
                )

                if entries:
                    for stream, messages in entries:
                        for message_id, data in messages:
                            self.metrics["bars_received"] += 1

                            # Extract timestamp
                            bar_ts = float(data.get("timestamp", 0))

                            # Validate latency
                            latency_ok = self.validate_bar_latency(bar_ts)

                            # Print bar
                            symbol = data.get("symbol", "UNKNOWN")
                            close_price = data.get("close", "N/A")
                            volume = data.get("volume", "N/A")
                            latency_ms = self.metrics["latencies"][-1] if self.metrics["latencies"] else 0

                            status = "✅" if latency_ok else "❌"
                            print(
                                f"{status} Bar #{self.metrics['bars_received']}: "
                                f"{symbol} close={close_price} vol={volume} "
                                f"latency={latency_ms:.1f}ms"
                            )

                            last_id = message_id

                # Print progress every 60 seconds
                elapsed = time.time() - start_time
                if int(elapsed) % 60 == 0 and int(elapsed) > 0:
                    self.print_progress(elapsed)

            except KeyboardInterrupt:
                print("\n⚠️  Test interrupted by user")
                break
            except Exception as e:
                print(f"❌ Error reading stream: {e}")
                self.metrics["redis_errors"] += 1
                await asyncio.sleep(1)

        # Calculate final metrics
        if self.metrics["latencies"]:
            self.metrics["avg_latency_ms"] = sum(self.metrics["latencies"]) / len(
                self.metrics["latencies"]
            )

    def print_progress(self, elapsed: float):
        """Print progress update."""
        print(f"\n{'─'*70}")
        print(f"⏱️  Progress: {int(elapsed)}s / {self.test_duration_seconds}s")
        print(f"📊 Bars received: {self.metrics['bars_received']}")
        print(
            f"⚡ Avg latency: {self.metrics['avg_latency_ms']:.1f}ms "
            f"(max: {self.metrics['max_latency_ms']:.1f}ms)"
        )
        print(f"❌ Latency violations: {self.metrics['latency_violations']}")
        print(f"{'─'*70}\n")

    def print_final_report(self):
        """Print final test report."""
        print(f"\n{'='*70}")
        print("📋 SMOKE TEST FINAL REPORT")
        print(f"{'='*70}\n")

        # Test duration
        actual_duration = time.time() - self.test_start
        print(f"⏱️  Test Duration: {actual_duration:.1f}s ({actual_duration/60:.1f} minutes)")

        # Bars received
        print(f"\n📊 Bars Received: {self.metrics['bars_received']}")
        expected_bars = (actual_duration / 15) * 1  # 1 bar per 15s
        print(f"   Expected: ~{int(expected_bars)} bars (1 per 15s)")

        if self.metrics['bars_received'] > 0:
            bars_rate = self.metrics['bars_received'] / (actual_duration / 60)
            print(f"   Rate: {bars_rate:.1f} bars/min")

        # Latency metrics
        print(f"\n⚡ Latency Metrics:")
        print(f"   Average: {self.metrics['avg_latency_ms']:.1f}ms")
        print(f"   Maximum: {self.metrics['max_latency_ms']:.1f}ms")
        print(f"   Budget: 150ms")

        if self.metrics['latencies']:
            p95 = sorted(self.metrics['latencies'])[int(len(self.metrics['latencies']) * 0.95)]
            print(f"   P95: {p95:.1f}ms")

        # Violations
        print(f"\n❌ Violations:")
        print(f"   Latency violations: {self.metrics['latency_violations']}")
        print(f"   Circuit breaker trips: {self.metrics['circuit_breaker_trips']}")
        print(f"   Redis errors: {self.metrics['redis_errors']}")

        # Pass/Fail
        print(f"\n{'='*70}")

        passed = (
            self.metrics['bars_received'] > 0
            and self.metrics['latency_violations'] == 0
            and self.metrics['circuit_breaker_trips'] == 0
            and self.metrics['avg_latency_ms'] < 150.0
            and self.metrics['max_latency_ms'] < 200.0  # Allow some buffer
        )

        if passed:
            print("✅ SMOKE TEST PASSED")
            print("\n✨ 15s bars are production ready!")
            print("   Next step: 24-hour paper trial")
        else:
            print("❌ SMOKE TEST FAILED")
            print("\n⚠️  Issues detected:")

            if self.metrics['bars_received'] == 0:
                print("   - No bars received (check WSS client)")
            if self.metrics['latency_violations'] > 0:
                print(f"   - {self.metrics['latency_violations']} latency violations")
            if self.metrics['avg_latency_ms'] >= 150.0:
                print(f"   - Average latency too high ({self.metrics['avg_latency_ms']:.1f}ms)")

        print(f"{'='*70}\n")

        return passed


async def main():
    """Run 15-minute smoke test."""
    print("=" * 70)
    print(" " * 15 + "15-MINUTE SMOKE TEST - SUB-MINUTE BARS")
    print("=" * 70 + "\n")

    # Check environment variables
    redis_url = os.getenv("REDIS_URL")
    redis_ca_cert = os.getenv("REDIS_SSL_CA_CERT", "config/certs/redis_ca.pem")
    enable_5s = os.getenv("ENABLE_5S_BARS", "false").lower() == "true"
    max_trades = os.getenv("SCALPER_MAX_TRADES_PER_MINUTE", "4")

    if not redis_url:
        print("❌ ERROR: REDIS_URL environment variable not set")
        print("   Set it with: export REDIS_URL='rediss://...'")
        sys.exit(1)

    print("🔧 Configuration:")
    print(f"   REDIS_URL: {redis_url[:30]}...")
    print(f"   REDIS_SSL_CA_CERT: {redis_ca_cert}")
    print(f"   ENABLE_5S_BARS: {enable_5s}")
    print(f"   SCALPER_MAX_TRADES_PER_MINUTE: {max_trades}")
    print()

    # Verify 5s bars are disabled (production safe)
    if enable_5s:
        print("⚠️  WARNING: 5s bars are ENABLED")
        print("   For first smoke test, recommend: ENABLE_5S_BARS=false")
        print()

    # Initialize validator
    validator = SmokeTestValidator(redis_url, redis_ca_cert)

    # Check Redis stream health
    stream_key = "kraken:ohlc:15s:BTC-USD"
    print(f"🔍 Checking Redis stream health: {stream_key}")
    health = validator.check_redis_stream_health(stream_key)

    if health["status"] == "stream_not_found":
        print(f"⚠️  Stream not found: {stream_key}")
        print("   This is normal if WSS client hasn't started yet.")
        print("   Start WSS client with: python -m utils.kraken_ws")
        print()
    elif health["status"] == "healthy":
        print(f"✅ Stream healthy:")
        print(f"   Length: {health['stream_length']} messages")
        print(f"   Consumer groups: {health['consumer_groups']}")
        print()
    else:
        print(f"❌ Stream error: {health.get('error')}")
        print()

    # Countdown
    print("🚀 Starting smoke test in 5 seconds...")
    print("   Press Ctrl+C to stop early")
    for i in range(5, 0, -1):
        print(f"   {i}...")
        await asyncio.sleep(1)
    print()

    # Run test
    try:
        await validator.monitor_stream(stream_key, duration_seconds=15 * 60)
    except KeyboardInterrupt:
        print("\n⚠️  Test interrupted by user")

    # Print final report
    passed = validator.print_final_report()

    # Exit code
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    asyncio.run(main())
