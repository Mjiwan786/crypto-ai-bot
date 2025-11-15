#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
End-to-End Connectivity Test
Tests: Kraken WS -> Redis Cloud -> signals-api -> signals-site
Outputs: Connection status, latency metrics, data flow verification
"""

import os
import sys
import time
import json
import asyncio
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
import uuid

# Set UTF-8 encoding for Windows console
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import redis.asyncio as redis
    from redis.exceptions import RedisError, ConnectionError as RedisConnectionError
except ImportError:
    print("❌ redis package not installed. Run: pip install redis")
    sys.exit(1)

try:
    import websockets
except ImportError:
    print("❌ websockets package not installed. Run: pip install websockets")
    sys.exit(1)

try:
    from dotenv import load_dotenv
except ImportError:
    print("❌ python-dotenv not installed. Run: pip install python-dotenv")
    sys.exit(1)


# Load environment variables
load_dotenv()


class MetricsCollector:
    """Collects and displays test metrics"""
    def __init__(self):
        self.results = {
            "test_id": str(uuid.uuid4())[:8],
            "timestamp": datetime.utcnow().isoformat(),
            "tests": {}
        }

    def add_result(self, test_name: str, success: bool, latency_ms: Optional[float] = None, details: Dict[str, Any] = None):
        """Add a test result"""
        self.results["tests"][test_name] = {
            "success": success,
            "latency_ms": latency_ms,
            "details": details or {}
        }

    def print_summary(self):
        """Print formatted test summary"""
        print("\n" + "="*80)
        print(f"E2E CONNECTIVITY TEST RESULTS")
        print(f"Test ID: {self.results['test_id']} | Time: {self.results['timestamp']}")
        print("="*80 + "\n")

        total = len(self.results["tests"])
        passed = sum(1 for t in self.results["tests"].values() if t["success"])

        for test_name, result in self.results["tests"].items():
            status = "[PASS]" if result["success"] else "[FAIL]"
            latency = f"{result['latency_ms']:.2f}ms" if result['latency_ms'] else "N/A"
            print(f"{status} | {test_name:40} | Latency: {latency}")

            if result["details"]:
                for key, value in result["details"].items():
                    print(f"       +- {key}: {value}")

        print("\n" + "="*80)
        print(f"SUMMARY: {passed}/{total} tests passed ({passed/total*100:.1f}%)")
        print("="*80 + "\n")

        # Export JSON
        json_path = Path(__file__).parent.parent / "out" / f"e2e_test_{self.results['test_id']}.json"
        json_path.parent.mkdir(parents=True, exist_ok=True)
        with open(json_path, "w") as f:
            json.dump(self.results, f, indent=2)
        print(f"[REPORT] Full results exported to: {json_path}\n")


class E2EConnectivityTest:
    """End-to-end connectivity test suite"""

    def __init__(self, metrics: MetricsCollector):
        self.metrics = metrics
        self.redis_client: Optional[redis.Redis] = None

        # Redis configuration
        self.redis_url = os.getenv("REDIS_URL", "")
        self.redis_ca_cert = Path(__file__).parent.parent / "config" / "certs" / "redis_ca.pem"

        # Kraken WS
        self.kraken_ws_url = "wss://ws.kraken.com"

        # Signals API paths (for verification)
        self.signals_api_path = Path(os.getenv("SIGNALS_API_PATH", "C:/Users/Maith/OneDrive/Desktop/signals_api"))
        self.signals_site_path = Path(os.getenv("SIGNALS_SITE_PATH", "C:/Users/Maith/OneDrive/Desktop/signals-site"))

    async def test_redis_crypto_bot(self) -> bool:
        """Test Redis Cloud TLS connection from crypto-bot environment"""
        print("\n[TEST] Testing Redis Cloud TLS from crypto-bot...")
        start = time.time()

        try:
            # Parse Redis URL
            if not self.redis_url or "<" in self.redis_url:
                raise ValueError("REDIS_URL not properly configured in .env")

            # Create TLS-enabled Redis client
            if self.redis_ca_cert.exists():
                self.redis_client = redis.from_url(
                    self.redis_url,
                    ssl_ca_certs=str(self.redis_ca_cert),
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5
                )
            else:
                # Try without CA cert (some setups don't require it)
                self.redis_client = redis.from_url(
                    self.redis_url,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5
                )

            # Test connection with PING
            ping_result = await self.redis_client.ping()
            latency = (time.time() - start) * 1000

            if ping_result:
                # Get Redis info
                info = await self.redis_client.info("server")
                redis_version = info.get("redis_version", "unknown")

                self.metrics.add_result(
                    "redis_crypto_bot_connection",
                    success=True,
                    latency_ms=latency,
                    details={
                        "redis_version": redis_version,
                        "tls_enabled": "rediss://" in self.redis_url,
                        "ca_cert_used": self.redis_ca_cert.exists()
                    }
                )
                print(f"   [OK] Connected to Redis Cloud (latency: {latency:.2f}ms)")
                return True

        except Exception as e:
            latency = (time.time() - start) * 1000
            self.metrics.add_result(
                "redis_crypto_bot_connection",
                success=False,
                latency_ms=latency,
                details={"error": str(e)}
            )
            print(f"   [ERROR] Failed: {e}")
            return False

    async def test_kraken_ws(self) -> bool:
        """Test Kraken WebSocket connectivity"""
        print("\n[TEST] Testing Kraken WebSocket connection...")
        start = time.time()

        try:
            # Connect to Kraken WS
            async with websockets.connect(self.kraken_ws_url, ping_interval=20, ping_timeout=10) as ws:
                # Send subscription request (ticker for BTC/USD)
                sub_msg = {
                    "event": "subscribe",
                    "pair": ["XBT/USD"],
                    "subscription": {"name": "ticker"}
                }
                await ws.send(json.dumps(sub_msg))

                # Wait for responses (Kraken sends systemStatus first, then subscriptionStatus)
                subscribed = False
                system_status = None

                for _ in range(3):  # Try up to 3 messages
                    response = await asyncio.wait_for(ws.recv(), timeout=10)
                    data = json.loads(response)

                    if data.get("event") == "systemStatus":
                        system_status = data.get("status")
                        continue

                    if data.get("event") == "subscriptionStatus" and data.get("status") == "subscribed":
                        latency = (time.time() - start) * 1000
                        self.metrics.add_result(
                            "kraken_ws_connection",
                            success=True,
                            latency_ms=latency,
                            details={
                                "pair": data.get("pair"),
                                "channel": data.get("channelName"),
                                "subscription_id": data.get("channelID"),
                                "system_status": system_status
                            }
                        )
                        print(f"   [OK] Subscribed to Kraken WS (latency: {latency:.2f}ms, status: {system_status})")
                        subscribed = True
                        break

                if not subscribed:
                    raise Exception("Did not receive subscription confirmation")

        except Exception as e:
            latency = (time.time() - start) * 1000
            self.metrics.add_result(
                "kraken_ws_connection",
                success=False,
                latency_ms=latency,
                details={"error": str(e)}
            )
            print(f"   [ERROR] Failed: {e}")
            return False

    async def test_redis_publish_subscribe(self) -> bool:
        """Test Redis publish/subscribe with test signal"""
        print("\n[TEST] Testing Redis publish/subscribe (signals pipeline)...")

        if not self.redis_client:
            print("   [WARN] Skipped: Redis client not initialized")
            return False

        try:
            # Create test signal
            test_signal = {
                "id": str(uuid.uuid4()),
                "ts": int(time.time() * 1000),
                "pair": "BTC-USD",
                "side": "long",
                "entry": 64321.1,
                "sl": 63500.0,
                "tp": 65500.0,
                "strategy": "e2e_test",
                "confidence": 0.99,
                "mode": "paper"
            }

            # Publish to signals:paper stream
            start_publish = time.time()
            stream_key = "signals:paper"
            message_id = await self.redis_client.xadd(stream_key, {"signal": json.dumps(test_signal)})
            publish_latency = (time.time() - start_publish) * 1000

            # Read back from stream
            start_read = time.time()
            messages = await self.redis_client.xrevrange(stream_key, count=1)
            read_latency = (time.time() - start_read) * 1000

            if messages and len(messages) > 0:
                msg_id, msg_data = messages[0]
                retrieved_signal = json.loads(msg_data["signal"])

                # Verify signal integrity
                if retrieved_signal["id"] == test_signal["id"]:
                    total_latency = publish_latency + read_latency

                    self.metrics.add_result(
                        "redis_publish_subscribe",
                        success=True,
                        latency_ms=total_latency,
                        details={
                            "publish_latency_ms": round(publish_latency, 2),
                            "read_latency_ms": round(read_latency, 2),
                            "stream_key": stream_key,
                            "message_id": message_id.decode() if isinstance(message_id, bytes) else message_id
                        }
                    )
                    print(f"   [OK] Signal published & read (publish: {publish_latency:.2f}ms, read: {read_latency:.2f}ms)")
                    return True
                else:
                    raise Exception("Signal ID mismatch")
            else:
                raise Exception("No messages in stream")

        except Exception as e:
            self.metrics.add_result(
                "redis_publish_subscribe",
                success=False,
                details={"error": str(e)}
            )
            print(f"   [ERROR] Failed: {e}")
            return False

    async def test_redis_from_signals_api(self) -> bool:
        """Test Redis connection from signals-api conda env"""
        print("\n[TEST] Testing Redis connection from signals-api env...")

        if not self.signals_api_path.exists():
            print(f"   [WARN] Skipped: signals-api path not found at {self.signals_api_path}")
            self.metrics.add_result(
                "redis_signals_api_connection",
                success=False,
                details={"error": "signals-api path not found"}
            )
            return False

        try:
            # Try to run a simple Redis test from signals-api env
            test_script = """
import redis.asyncio as redis
import asyncio
import time
import os

async def test():
    start = time.time()
    client = redis.from_url(
        os.getenv('REDIS_URL'),
        ssl_ca_certs='config/certs/redis_ca.pem',
        decode_responses=True
    )
    result = await client.ping()
    latency = (time.time() - start) * 1000
    print(f"PING:{result}|LATENCY:{latency:.2f}")
    await client.close()

asyncio.run(test())
"""

            # Write temp test script
            temp_script = self.signals_api_path / "temp_redis_test.py"
            temp_script.write_text(test_script)

            # Run via conda
            start = time.time()
            result = subprocess.run(
                ["conda", "run", "-n", "signals-api", "python", str(temp_script)],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=str(self.signals_api_path)
            )
            latency = (time.time() - start) * 1000

            # Clean up
            temp_script.unlink(missing_ok=True)

            if result.returncode == 0 and "PING:True" in result.stdout:
                # Parse latency from output
                try:
                    latency_str = result.stdout.split("LATENCY:")[1].strip()
                    api_latency = float(latency_str)
                except:
                    api_latency = latency

                self.metrics.add_result(
                    "redis_signals_api_connection",
                    success=True,
                    latency_ms=api_latency,
                    details={"conda_env": "signals-api"}
                )
                print(f"   [OK] signals-api can connect to Redis (latency: {api_latency:.2f}ms)")
                return True
            else:
                raise Exception(f"Test failed: {result.stderr}")

        except Exception as e:
            self.metrics.add_result(
                "redis_signals_api_connection",
                success=False,
                details={"error": str(e)}
            )
            print(f"   [WARN] Could not verify (signals-api env not available)")
            return False

    async def test_redis_from_signals_site(self) -> bool:
        """Test Redis connection from signals-site (using redis-cli)"""
        print("\n[TEST] Testing Redis connection from signals-site location...")

        site_redis_cert = self.signals_site_path / "redis-ca.crt"

        if not site_redis_cert.exists():
            print(f"   [WARN] Skipped: redis-ca.crt not found at {site_redis_cert}")
            self.metrics.add_result(
                "redis_signals_site_connection",
                success=False,
                details={"error": "redis-ca.crt not found"}
            )
            return False

        try:
            # Extract connection details from REDIS_URL
            import re
            match = re.search(r'rediss://([^:]+):([^@]+)@([^:]+):(\d+)', self.redis_url)
            if not match:
                raise ValueError("Could not parse REDIS_URL")

            username, password, host, port = match.groups()

            # Test with redis-cli
            start = time.time()
            result = subprocess.run(
                [
                    "redis-cli",
                    "-h", host,
                    "-p", port,
                    "-a", password,
                    "--tls",
                    "--cacert", str(site_redis_cert),
                    "PING"
                ],
                capture_output=True,
                text=True,
                timeout=10
            )
            latency = (time.time() - start) * 1000

            if result.returncode == 0 and "PONG" in result.stdout:
                self.metrics.add_result(
                    "redis_signals_site_connection",
                    success=True,
                    latency_ms=latency,
                    details={"tool": "redis-cli", "cert_path": str(site_redis_cert)}
                )
                print(f"   [OK] signals-site can connect to Redis (latency: {latency:.2f}ms)")
                return True
            else:
                raise Exception(f"redis-cli failed: {result.stderr}")

        except Exception as e:
            self.metrics.add_result(
                "redis_signals_site_connection",
                success=False,
                details={"error": str(e)}
            )
            print(f"   [WARN] Could not verify: {e}")
            return False

    async def test_end_to_end_latency(self) -> bool:
        """Test full pipeline latency: publish -> signals-api -> signals-site"""
        print("\n[TEST] Testing end-to-end pipeline latency...")

        if not self.redis_client:
            print("   [WARN] Skipped: Redis client not initialized")
            return False

        try:
            # Simulate full pipeline
            test_signal = {
                "id": str(uuid.uuid4()),
                "ts": int(time.time() * 1000),
                "pair": "ETH-USD",
                "side": "short",
                "entry": 3200.5,
                "strategy": "e2e_latency_test",
                "confidence": 0.85,
                "mode": "paper"
            }

            # Measure full cycle
            start_total = time.time()

            # 1. Publish to Redis (simulates crypto-bot)
            await self.redis_client.xadd("signals:paper", {"signal": json.dumps(test_signal)})
            publish_time = time.time()

            # 2. Read from Redis (simulates signals-api)
            await asyncio.sleep(0.05)  # Small delay to simulate processing
            messages = await self.redis_client.xrevrange("signals:paper", count=1)
            read_time = time.time()

            # 3. Simulate API processing
            if messages:
                retrieved = json.loads(messages[0][1]["signal"])
                processing_time = time.time()

                # Calculate latencies
                publish_latency = (publish_time - start_total) * 1000
                read_latency = (read_time - publish_time) * 1000
                total_latency = (processing_time - start_total) * 1000

                # Check against PRD targets
                meets_target = total_latency < 500  # < 500ms target from PRD

                self.metrics.add_result(
                    "end_to_end_latency",
                    success=meets_target,
                    latency_ms=total_latency,
                    details={
                        "publish_ms": round(publish_latency, 2),
                        "redis_to_api_ms": round(read_latency, 2),
                        "total_ms": round(total_latency, 2),
                        "target_ms": 500,
                        "meets_target": meets_target
                    }
                )

                status = "[OK]" if meets_target else "[WARN]"
                print(f"   {status} E2E latency: {total_latency:.2f}ms (target: <500ms)")
                print(f"      +- Publish: {publish_latency:.2f}ms | Read: {read_latency:.2f}ms")
                return meets_target
            else:
                raise Exception("Could not retrieve test signal")

        except Exception as e:
            self.metrics.add_result(
                "end_to_end_latency",
                success=False,
                details={"error": str(e)}
            )
            print(f"   [ERROR] Failed: {e}")
            return False

    async def cleanup(self):
        """Clean up resources"""
        if self.redis_client:
            await self.redis_client.close()


async def main():
    """Main test runner"""
    print("\n" + "="*80)
    print("CRYPTO AI BOT - END-TO-END CONNECTIVITY TEST")
    print("Testing: Kraken WS -> Redis Cloud -> signals-api -> signals-site")
    print("="*80)

    metrics = MetricsCollector()
    tester = E2EConnectivityTest(metrics)

    try:
        # Run all tests
        await tester.test_redis_crypto_bot()
        await tester.test_kraken_ws()
        await tester.test_redis_publish_subscribe()
        await tester.test_redis_from_signals_api()
        await tester.test_redis_from_signals_site()
        await tester.test_end_to_end_latency()

    finally:
        await tester.cleanup()

    # Print summary
    metrics.print_summary()


if __name__ == "__main__":
    asyncio.run(main())
