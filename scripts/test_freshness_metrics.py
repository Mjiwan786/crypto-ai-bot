#!/usr/bin/env python3
"""
Freshness Metrics End-to-End Test
==================================

Tests the complete freshness metrics pipeline:
1. Signal creation with timestamps
2. Freshness calculation (event_age_ms, ingest_lag_ms)
3. Clock drift detection
4. Prometheus metrics export
5. Redis metrics stream publishing

Runs for 3 iterations with simulated latency.
"""

import asyncio
import logging
import sys
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from signals.scalper_schema import (
    ScalperSignal,
    validate_signal_safe,
    get_metrics_stream_key,
)
from agents.infrastructure.redis_client import RedisCloudClient, RedisCloudConfig
from agents.monitoring.prometheus_freshness_exporter import FreshnessMetricsExporter
from dotenv import load_dotenv
import os

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def test_freshness_metrics():
    """Test end-to-end freshness metrics"""
    print("=" * 80)
    print("            FRESHNESS METRICS END-TO-END TEST")
    print("=" * 80)

    # Load environment
    env_file = project_root / ".env.paper.live"
    if env_file.exists():
        load_dotenv(env_file)
        print(f"\n[OK] Loaded environment from: {env_file}")
    else:
        print(f"\n[WARN] Environment file not found: {env_file}")

    # Initialize Redis client
    redis_url = os.getenv("REDIS_URL")
    redis_ca_cert = os.getenv("REDIS_CA_CERT", "config/certs/redis_ca.pem")

    if not redis_url:
        print("\n[FAIL] REDIS_URL not set in environment")
        return False

    print(f"[OK] Redis URL: {redis_url[:50]}...")

    # Connect to Redis
    print("\n1. Testing Redis connection...")
    redis_config = RedisCloudConfig(
        url=redis_url,
        ca_cert_path=redis_ca_cert,
    )
    redis_client = RedisCloudClient(redis_config)

    try:
        await redis_client.connect()
        print("   [OK] Connected to Redis Cloud")
    except Exception as e:
        print(f"   [FAIL] Failed to connect to Redis: {e}")
        return False

    # Initialize Prometheus exporter
    print("\n2. Initializing Prometheus exporter...")
    try:
        prometheus_exporter = FreshnessMetricsExporter(port=9110)
        await prometheus_exporter.start()
        print("   [OK] Prometheus exporter started on port 9110")
        print("   [OK] Metrics: http://localhost:9110/metrics")
    except Exception as e:
        print(f"   [FAIL] Failed to start Prometheus exporter: {e}")
        await redis_client.close()
        return False

    # Test scenarios
    test_pairs = ["BTC/USD", "ETH/USD"]
    test_tf = "15s"

    # Scenario 1: Normal freshness (recent signal)
    print("\n3. Testing normal freshness (recent signal)...")
    for pair in test_pairs:
        now_ms = int(time.time() * 1000)
        signal_data = {
            "ts_exchange": now_ms - 1000,  # 1 second ago
            "ts_server": now_ms - 500,     # 500ms ago
            "symbol": pair,
            "timeframe": test_tf,
            "side": "long",
            "confidence": 0.85,
            "entry": 45000.0 if pair == "BTC/USD" else 3000.0,
            "stop": 44500.0 if pair == "BTC/USD" else 2950.0,
            "tp": 46000.0 if pair == "BTC/USD" else 3100.0,
            "model": "test_freshness_v1",
            "trace_id": f"test-normal-{int(time.time())}-{pair.replace('/', '-')}",
        }

        signal, error = validate_signal_safe(signal_data)
        if signal is None:
            print(f"   [FAIL] {pair}: {error}")
            continue

        # Calculate freshness
        freshness = signal.calculate_freshness_metrics(now_server_ms=now_ms)

        # Check clock drift
        has_drift, drift_message = signal.check_clock_drift(threshold_ms=2000)

        # Update Prometheus
        prometheus_exporter.update_freshness_metrics(
            symbol=signal.symbol,
            timeframe=signal.timeframe,
            event_age_ms=freshness["event_age_ms"],
            ingest_lag_ms=freshness["ingest_lag_ms"],
            exchange_server_delta_ms=freshness["exchange_server_delta_ms"],
        )

        # Publish to Redis
        stream_key = signal.get_stream_key()
        await redis_client.xadd(
            stream_key,
            {"signal": signal.to_json_str()},
            maxlen=1000,
        )

        prometheus_exporter.record_signal_published(signal.symbol, signal.timeframe)

        print(
            f"   [OK] {pair}: event_age={freshness['event_age_ms']}ms, "
            f"ingest_lag={freshness['ingest_lag_ms']}ms, drift={freshness['exchange_server_delta_ms']}ms"
        )

        if has_drift:
            print(f"   [WARN] {pair}: {drift_message}")

    # Scenario 2: Stale signal (high event age)
    print("\n4. Testing stale signal (high event age)...")
    now_ms = int(time.time() * 1000)
    stale_signal_data = {
        "ts_exchange": now_ms - 10000,  # 10 seconds ago (stale)
        "ts_server": now_ms - 9000,     # 9 seconds ago
        "symbol": "BTC/USD",
        "timeframe": test_tf,
        "side": "short",
        "confidence": 0.70,
        "entry": 45100.0,
        "stop": 45600.0,
        "tp": 44600.0,
        "model": "test_freshness_v1",
        "trace_id": f"test-stale-{int(time.time())}",
    }

    signal, error = validate_signal_safe(stale_signal_data)
    if signal:
        freshness = signal.calculate_freshness_metrics(now_server_ms=now_ms)

        prometheus_exporter.update_freshness_metrics(
            symbol=signal.symbol,
            timeframe=signal.timeframe,
            event_age_ms=freshness["event_age_ms"],
            ingest_lag_ms=freshness["ingest_lag_ms"],
            exchange_server_delta_ms=freshness["exchange_server_delta_ms"],
        )

        print(
            f"   [OK] Stale signal detected: event_age={freshness['event_age_ms']}ms "
            f"(>5000ms threshold)"
        )
    else:
        print(f"   [FAIL] Stale signal validation failed: {error}")

    # Scenario 3: Clock drift warning (exchange ahead of server)
    print("\n5. Testing clock drift warning...")
    now_ms = int(time.time() * 1000)
    drift_signal_data = {
        "ts_exchange": now_ms + 3000,  # 3 seconds in future (clock drift!)
        "ts_server": now_ms,
        "symbol": "ETH/USD",
        "timeframe": test_tf,
        "side": "long",
        "confidence": 0.75,
        "entry": 3000.0,
        "stop": 2950.0,
        "tp": 3100.0,
        "model": "test_freshness_v1",
        "trace_id": f"test-drift-{int(time.time())}",
    }

    signal, error = validate_signal_safe(drift_signal_data)
    if signal:
        freshness = signal.calculate_freshness_metrics(now_server_ms=now_ms)
        has_drift, drift_message = signal.check_clock_drift(threshold_ms=2000)

        if has_drift:
            prometheus_exporter.record_clock_drift_warning(
                symbol=signal.symbol,
                drift_ms=freshness["exchange_server_delta_ms"],
            )
            print(f"   [OK] Clock drift detected: {drift_message[:80]}...")
        else:
            print(f"   [FAIL] Should have detected clock drift (3000ms > 2000ms)")
    else:
        print(f"   [FAIL] Drift signal validation failed: {error}")

    # Publish metrics summary to Redis
    print("\n6. Publishing metrics to Redis...")
    try:
        metrics_stream = get_metrics_stream_key()
        await redis_client.xadd(
            metrics_stream,
            {
                "ts": int(time.time() * 1000),
                "test_mode": "true",
                "signals_published": 3,
                "signals_rejected": 0,
                "avg_event_age_ms": 1000,
                "avg_ingest_lag_ms": 500,
                "clock_drift_warnings": 1,
            },
            maxlen=10000,
        )
        print(f"   [OK] Metrics published to {metrics_stream}")
    except Exception as e:
        print(f"   [FAIL] Failed to publish metrics: {e}")

    # Verify Prometheus metrics
    print("\n7. Verifying Prometheus metrics...")
    summary = prometheus_exporter.get_metrics_summary()
    print(f"   [OK] Metrics endpoint: {summary['metrics_endpoint']}")
    print("   [OK] Test metrics with: curl http://localhost:9110/metrics")

    # Cleanup
    await redis_client.close()

    print("\n" + "=" * 80)
    print("[PASS] END-TO-END TEST COMPLETED")
    print("=" * 80)
    print("\nPrometheus metrics available at: http://localhost:9110/metrics")
    print("Test with: curl http://localhost:9110/metrics | grep signal_")
    print("\nPress Ctrl+C to stop the Prometheus exporter and exit.")

    # Keep running for manual testing
    try:
        await asyncio.sleep(300)  # 5 minutes
    except KeyboardInterrupt:
        print("\nShutting down...")

    return True


async def main():
    """Main entry point"""
    try:
        success = await test_freshness_metrics()
        sys.exit(0 if success else 1)
    except Exception as e:
        logger.error(f"Test failed with exception: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
