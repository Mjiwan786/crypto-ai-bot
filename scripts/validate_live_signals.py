#!/usr/bin/env python3
"""
Live Signal Validator
======================

Validates signals published by live_signal_publisher.py to ensure:
- Schema compliance (Pydantic validation)
- Correct stream keys
- Timestamp accuracy and freshness
- No duplicates (idempotent IDs)
- Latency within SLO (<500ms p95)
- Heartbeat presence
- Metrics availability

USAGE:
    # Validate last 100 signals
    python scripts/validate_live_signals.py --mode paper --count 100

    # Continuous validation (real-time monitoring)
    python scripts/validate_live_signals.py --mode live --continuous

    # Validate specific pair
    python scripts/validate_live_signals.py --mode paper --pair BTC/USD

    # Export validation report
    python scripts/validate_live_signals.py --mode paper --report validation_report.json

"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set

from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from signals.schema import Signal
from agents.infrastructure.redis_client import RedisCloudClient, RedisCloudConfig

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# =============================================================================
# Validation Results
# =============================================================================


@dataclass
class ValidationResult:
    """Results from signal validation"""

    total_signals: int = 0
    valid_signals: int = 0
    invalid_signals: int = 0
    duplicate_ids: int = 0

    # Schema validation errors
    schema_errors: List[Dict] = field(default_factory=list)

    # Timestamp issues
    future_timestamps: int = 0
    stale_signals: int = 0  # >5 min old

    # Stream key issues
    wrong_stream_keys: int = 0

    # Latency tracking
    freshness_latencies: List[float] = field(default_factory=list)  # ms

    # Seen IDs (for duplicate detection)
    seen_ids: Set[str] = field(default_factory=set)

    def record_signal(
        self,
        signal_data: Dict,
        stream_key: str,
        entry_id: str,
        expected_mode: str,
    ) -> None:
        """Validate and record a signal"""
        self.total_signals += 1

        try:
            # Parse signal
            signal = Signal.from_dict(signal_data)

            # Check for duplicates
            if signal.id in self.seen_ids:
                self.duplicate_ids += 1
                logger.warning(f"Duplicate signal ID: {signal.id}")
            else:
                self.seen_ids.add(signal.id)

            # Validate timestamp
            current_ts_ms = int(time.time() * 1000)
            signal_age_ms = current_ts_ms - signal.ts_ms

            # Check if timestamp is in future
            if signal_age_ms < 0:
                self.future_timestamps += 1
                logger.warning(f"Future timestamp: {signal.id} ({signal_age_ms}ms in future)")

            # Check if signal is stale (>5 minutes old)
            elif signal_age_ms > 300_000:  # 5 minutes
                self.stale_signals += 1
                logger.warning(f"Stale signal: {signal.id} ({signal_age_ms/1000:.1f}s old)")

            # Track freshness latency
            self.freshness_latencies.append(signal_age_ms)

            # Validate stream key matches signal mode and pair
            expected_stream_key = signal.get_stream_key()
            if stream_key != expected_stream_key:
                self.wrong_stream_keys += 1
                logger.error(
                    f"Wrong stream key: {stream_key} (expected: {expected_stream_key}) for signal {signal.id}"
                )

            # Validate mode matches expected
            if signal.mode != expected_mode:
                logger.error(
                    f"Mode mismatch: signal has mode={signal.mode}, expected {expected_mode}"
                )

            # All checks passed
            self.valid_signals += 1

        except Exception as e:
            self.invalid_signals += 1
            self.schema_errors.append({
                "entry_id": entry_id,
                "stream_key": stream_key,
                "error": str(e),
                "data": signal_data,
            })
            logger.error(f"Schema validation failed for {entry_id}: {e}")

    def get_latency_stats(self) -> Dict[str, float]:
        """Calculate latency statistics"""
        if not self.freshness_latencies:
            return {"p50": 0, "p95": 0, "p99": 0, "max": 0}

        sorted_latencies = sorted(self.freshness_latencies)

        def percentile(data: List[float], p: float) -> float:
            idx = int(len(data) * p)
            return data[min(idx, len(data) - 1)]

        return {
            "p50": round(percentile(sorted_latencies, 0.50), 2),
            "p95": round(percentile(sorted_latencies, 0.95), 2),
            "p99": round(percentile(sorted_latencies, 0.99), 2),
            "max": round(max(sorted_latencies), 2),
        }

    def print_summary(self) -> None:
        """Print validation summary"""
        print("\n" + "=" * 70)
        print(" " * 20 + "SIGNAL VALIDATION SUMMARY")
        print("=" * 70)

        print(f"\nTotal Signals: {self.total_signals}")
        print(f"  ✓ Valid:     {self.valid_signals} ({self.valid_signals/self.total_signals*100:.1f}%)")
        print(f"  ✗ Invalid:   {self.invalid_signals}")
        print(f"  ⚠ Duplicates: {self.duplicate_ids}")

        if self.future_timestamps > 0:
            print(f"\n⚠ Timestamp Issues:")
            print(f"  Future timestamps: {self.future_timestamps}")

        if self.stale_signals > 0:
            print(f"  Stale signals (>5min): {self.stale_signals}")

        if self.wrong_stream_keys > 0:
            print(f"\n✗ Stream Key Issues: {self.wrong_stream_keys}")

        # Latency stats
        latency_stats = self.get_latency_stats()
        print(f"\nFreshness Latency (ms):")
        print(f"  p50: {latency_stats['p50']}ms")
        print(f"  p95: {latency_stats['p95']}ms")
        print(f"  p99: {latency_stats['p99']}ms")
        print(f"  max: {latency_stats['max']}ms")

        # SLO check
        slo_threshold_ms = 500  # PRD requirement: <500ms p95
        slo_met = latency_stats['p95'] < slo_threshold_ms

        print(f"\nSLO Status (p95 < {slo_threshold_ms}ms):")
        if slo_met:
            print(f"  ✓ PASS: {latency_stats['p95']}ms < {slo_threshold_ms}ms")
        else:
            print(f"  ✗ FAIL: {latency_stats['p95']}ms >= {slo_threshold_ms}ms")

        # Schema errors
        if self.schema_errors:
            print(f"\nSchema Errors ({len(self.schema_errors)}):")
            for i, error in enumerate(self.schema_errors[:5], 1):
                print(f"  {i}. {error['stream_key']} ({error['entry_id']}): {error['error']}")

            if len(self.schema_errors) > 5:
                print(f"  ... and {len(self.schema_errors) - 5} more")

        print("\n" + "=" * 70)

    def to_dict(self) -> Dict:
        """Convert to dictionary for export"""
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "total_signals": self.total_signals,
                "valid_signals": self.valid_signals,
                "invalid_signals": self.invalid_signals,
                "duplicate_ids": self.duplicate_ids,
                "future_timestamps": self.future_timestamps,
                "stale_signals": self.stale_signals,
                "wrong_stream_keys": self.wrong_stream_keys,
            },
            "latency_stats": self.get_latency_stats(),
            "schema_errors": self.schema_errors,
        }


# =============================================================================
# Validator
# =============================================================================


class LiveSignalValidator:
    """Validates live signals from Redis streams"""

    def __init__(
        self,
        mode: str,
        pairs: Optional[List[str]] = None,
        redis_url: Optional[str] = None,
        redis_ca_cert: Optional[str] = None,
    ):
        self.mode = mode
        self.pairs = pairs or ["BTC/USD", "ETH/USD", "SOL/USD", "MATIC/USD", "LINK/USD"]

        # Redis configuration
        self.redis_url = redis_url or os.getenv("REDIS_URL", "")
        self.redis_ca_cert = redis_ca_cert or os.getenv(
            "REDIS_CA_CERT",
            str(project_root / "config" / "certs" / "redis_ca.pem")
        )

        self.redis_client: Optional[RedisCloudClient] = None
        self.result = ValidationResult()

    async def connect(self) -> None:
        """Connect to Redis"""
        logger.info("Connecting to Redis Cloud...")

        redis_config = RedisCloudConfig(
            url=self.redis_url,
            ca_cert_path=self.redis_ca_cert,
        )

        self.redis_client = RedisCloudClient(redis_config)
        await self.redis_client.connect()

        logger.info("✓ Connected to Redis Cloud")

    async def disconnect(self) -> None:
        """Disconnect from Redis"""
        if self.redis_client:
            await self.redis_client.disconnect()

    async def validate_stream(self, pair: str, count: int = 100) -> None:
        """Validate signals from a specific stream"""
        if not self.redis_client:
            raise RuntimeError("Not connected to Redis")

        # Build stream key
        pair_key = pair.replace("/", "-")
        stream_key = f"signals:{self.mode}:{pair_key}"

        logger.info(f"Validating stream: {stream_key} (last {count} signals)")

        try:
            # Read latest signals from stream
            entries = await self.redis_client.xrevrange(stream_key, count=count)

            if not entries:
                logger.warning(f"No signals found in stream: {stream_key}")
                return

            logger.info(f"Found {len(entries)} signals in {stream_key}")

            # Validate each signal
            for entry_id, fields in entries:
                # Decode entry_id
                entry_id_str = entry_id.decode() if isinstance(entry_id, bytes) else entry_id

                # Decode fields
                signal_data = {}
                for k, v in fields.items():
                    key = k.decode() if isinstance(k, bytes) else k
                    val = v.decode() if isinstance(v, bytes) else v

                    # Convert numeric fields
                    if key in ["ts_ms"]:
                        signal_data[key] = int(val)
                    elif key in ["entry", "sl", "tp", "confidence"]:
                        signal_data[key] = float(val)
                    else:
                        signal_data[key] = val

                # Validate signal
                self.result.record_signal(signal_data, stream_key, entry_id_str, self.mode)

        except Exception as e:
            logger.error(f"Error validating stream {stream_key}: {e}", exc_info=True)

    async def validate_heartbeat(self) -> Dict:
        """Validate heartbeat presence"""
        if not self.redis_client:
            raise RuntimeError("Not connected to Redis")

        try:
            # Read last heartbeat
            entries = await self.redis_client.xrevrange("ops:heartbeat", count=1)

            if not entries:
                return {
                    "status": "missing",
                    "reason": "No heartbeat found in ops:heartbeat stream",
                }

            # Decode heartbeat
            entry_id, fields = entries[0]
            heartbeat_data = {}
            for k, v in fields.items():
                key = k.decode() if isinstance(k, bytes) else k
                val = v.decode() if isinstance(v, bytes) else v
                heartbeat_data[key] = val

            # Parse heartbeat JSON
            heartbeat = json.loads(heartbeat_data.get("json", "{}"))

            # Check freshness
            current_ts = int(time.time() * 1000)
            heartbeat_age_sec = (current_ts - heartbeat.get("ts", 0)) / 1000

            if heartbeat_age_sec > 60:  # >1 minute
                return {
                    "status": "stale",
                    "reason": f"Last heartbeat {heartbeat_age_sec:.1f}s ago",
                    "data": heartbeat,
                }

            return {
                "status": "healthy",
                "reason": f"Heartbeat age: {heartbeat_age_sec:.1f}s",
                "data": heartbeat,
            }

        except Exception as e:
            logger.error(f"Error checking heartbeat: {e}")
            return {
                "status": "error",
                "reason": str(e),
            }

    async def validate_metrics(self) -> Dict:
        """Validate metrics presence"""
        if not self.redis_client:
            raise RuntimeError("Not connected to Redis")

        try:
            # Read last metrics entry
            entries = await self.redis_client.xrevrange("metrics:publisher", count=1)

            if not entries:
                return {
                    "status": "missing",
                    "reason": "No metrics found in metrics:publisher stream",
                }

            # Decode metrics
            entry_id, fields = entries[0]
            metrics_data = {}
            for k, v in fields.items():
                key = k.decode() if isinstance(k, bytes) else k
                val = v.decode() if isinstance(v, bytes) else v
                metrics_data[key] = val

            # Check freshness
            timestamp = int(metrics_data.get("timestamp", 0))
            current_ts = int(time.time() * 1000)
            metrics_age_sec = (current_ts - timestamp) / 1000

            if metrics_age_sec > 120:  # >2 minutes
                return {
                    "status": "stale",
                    "reason": f"Last metrics {metrics_age_sec:.1f}s ago",
                    "data": metrics_data,
                }

            return {
                "status": "healthy",
                "reason": f"Metrics age: {metrics_age_sec:.1f}s",
                "data": metrics_data,
            }

        except Exception as e:
            logger.error(f"Error checking metrics: {e}")
            return {
                "status": "error",
                "reason": str(e),
            }

    async def validate_all(self, count: int = 100) -> ValidationResult:
        """Validate all configured streams"""
        await self.connect()

        try:
            # Validate each pair
            for pair in self.pairs:
                await self.validate_stream(pair, count)

            # Validate heartbeat
            logger.info("\nValidating heartbeat...")
            heartbeat_status = await self.validate_heartbeat()
            logger.info(f"Heartbeat: {heartbeat_status['status']} - {heartbeat_status['reason']}")

            # Validate metrics
            logger.info("\nValidating metrics...")
            metrics_status = await self.validate_metrics()
            logger.info(f"Metrics: {metrics_status['status']} - {metrics_status['reason']}")

        finally:
            await self.disconnect()

        return self.result

    async def validate_continuous(self, interval_sec: int = 10) -> None:
        """Continuously validate signals (real-time monitoring)"""
        await self.connect()

        logger.info(f"Starting continuous validation (interval={interval_sec}s)")
        logger.info("Press Ctrl+C to stop")

        try:
            while True:
                # Reset result for this iteration
                self.result = ValidationResult()

                # Validate latest signals from each stream
                for pair in self.pairs:
                    await self.validate_stream(pair, count=10)

                # Print quick status
                valid_pct = (
                    self.result.valid_signals / self.result.total_signals * 100
                    if self.result.total_signals > 0
                    else 0
                )

                latency_stats = self.result.get_latency_stats()

                logger.info(
                    f"[{datetime.now().strftime('%H:%M:%S')}] "
                    f"Validated {self.result.total_signals} signals: "
                    f"{self.result.valid_signals} valid ({valid_pct:.1f}%), "
                    f"latency p95={latency_stats['p95']}ms"
                )

                if self.result.invalid_signals > 0:
                    logger.warning(f"  ⚠ {self.result.invalid_signals} invalid signals detected")

                await asyncio.sleep(interval_sec)

        except KeyboardInterrupt:
            logger.info("\nStopping continuous validation")
        finally:
            await self.disconnect()


# =============================================================================
# CLI Interface
# =============================================================================


def parse_args():
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(
        description="Validate live signals from Redis streams",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--mode",
        choices=["paper", "live"],
        required=True,
        help="Trading mode to validate",
    )

    parser.add_argument(
        "--pair",
        help="Validate specific pair (default: all pairs)",
    )

    parser.add_argument(
        "--count",
        type=int,
        default=100,
        help="Number of signals to validate per stream (default: 100)",
    )

    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Continuous validation mode (real-time monitoring)",
    )

    parser.add_argument(
        "--interval",
        type=int,
        default=10,
        help="Interval for continuous mode in seconds (default: 10)",
    )

    parser.add_argument(
        "--report",
        type=Path,
        help="Export validation report to JSON file",
    )

    parser.add_argument(
        "--env-file",
        type=Path,
        default=project_root / ".env.paper",
        help="Environment file (default: .env.paper)",
    )

    return parser.parse_args()


async def main():
    """Main entry point"""
    args = parse_args()

    # Load environment
    if args.env_file.exists():
        load_dotenv(args.env_file)
        logger.info(f"Loaded environment from {args.env_file}")

    # Determine pairs
    pairs = [args.pair] if args.pair else None

    # Create validator
    validator = LiveSignalValidator(mode=args.mode, pairs=pairs)

    if args.continuous:
        # Continuous validation
        await validator.validate_continuous(interval_sec=args.interval)
    else:
        # One-time validation
        result = await validator.validate_all(count=args.count)

        # Print summary
        result.print_summary()

        # Export report if requested
        if args.report:
            report_data = result.to_dict()
            args.report.write_text(json.dumps(report_data, indent=2))
            logger.info(f"\nValidation report exported to: {args.report}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\nValidation stopped")
        sys.exit(0)
