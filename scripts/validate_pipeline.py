#!/usr/bin/env python3
"""
Pipeline Validation Script
==========================

Validates end-to-end signal delivery from Redis to SSE endpoint:
1. Tails Redis stream(s) for published signals
2. Opens SSE connection to ${API_BASE}/sse/signals
3. Matches signals by trace_id
4. Asserts SSE arrival within ≤ 2s of Redis publish
5. Reports mismatches, duplicates, gaps
6. Prints median/95p latency

Usage:
    # With API validation
    API_BASE=https://crypto-signals-api.fly.dev python scripts/validate_pipeline.py

    # Redis-only (skip SSE)
    python scripts/validate_pipeline.py

    # Custom duration
    VALIDATION_DURATION_SEC=300 API_BASE=https://... python scripts/validate_pipeline.py
"""

import asyncio
import logging
import sys
import time
import os
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
import statistics

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agents.infrastructure.redis_client import RedisCloudClient, RedisCloudConfig
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class SignalRecord:
    """Record of a signal event"""
    trace_id: str
    source: str  # "redis" or "sse"
    timestamp_ms: int  # When observed
    symbol: Optional[str] = None
    side: Optional[str] = None
    confidence: Optional[float] = None
    entry: Optional[float] = None
    redis_publish_time: Optional[int] = None  # ts_server from signal
    data: Optional[Dict] = None


@dataclass
class ValidationMetrics:
    """Validation statistics"""

    # Counters
    redis_signals_received: int = 0
    sse_signals_received: int = 0
    matched_signals: int = 0
    unmatched_redis: int = 0
    unmatched_sse: int = 0
    duplicate_redis: int = 0
    duplicate_sse: int = 0

    # Latency tracking (ms)
    latencies_ms: List[float] = field(default_factory=list)
    median_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    min_latency_ms: float = 0.0

    # SLA tracking
    sla_violations: int = 0  # Signals arriving > 2000ms
    sla_threshold_ms: float = 2000.0

    # Gap tracking
    gaps_detected: int = 0
    gap_details: List[Dict] = field(default_factory=list)

    # Mismatch tracking
    mismatches: List[Dict] = field(default_factory=list)

    # Test metadata
    duration_seconds: float = 0.0
    start_time: Optional[float] = None
    end_time: Optional[float] = None

    def calculate_stats(self):
        """Calculate final statistics"""
        self.end_time = time.time()
        if self.start_time:
            self.duration_seconds = self.end_time - self.start_time

        if self.latencies_ms:
            self.median_latency_ms = statistics.median(self.latencies_ms)
            self.p95_latency_ms = statistics.quantiles(self.latencies_ms, n=20)[18]  # 95th percentile
            self.max_latency_ms = max(self.latencies_ms)
            self.min_latency_ms = min(self.latencies_ms)

            # Count SLA violations
            self.sla_violations = sum(1 for lat in self.latencies_ms if lat > self.sla_threshold_ms)


class PipelineValidator:
    """Validates signal delivery from Redis to SSE"""

    def __init__(
        self,
        redis_client: RedisCloudClient,
        api_base: Optional[str] = None,
        validation_duration_sec: int = 60,
        sla_threshold_ms: float = 2000.0,
    ):
        self.redis = redis_client
        self.api_base = api_base
        self.validation_duration_sec = validation_duration_sec
        self.sla_threshold_ms = sla_threshold_ms

        # Tracking
        self.redis_signals: Dict[str, SignalRecord] = {}  # trace_id -> SignalRecord
        self.sse_signals: Dict[str, SignalRecord] = {}  # trace_id -> SignalRecord
        self.matched_signals: Dict[str, Tuple[SignalRecord, SignalRecord]] = {}

        # Metrics
        self.metrics = ValidationMetrics(sla_threshold_ms=sla_threshold_ms)

        # Control
        self._running = False

        # Signal stream patterns
        self.pairs = ["BTC/USD", "ETH/USD", "SOL/USD", "LINK/USD"]
        self.timeframes = ["15s", "1m"]

        logger.info(f"PipelineValidator initialized (duration={validation_duration_sec}s)")
        if self.api_base:
            logger.info(f"SSE endpoint: {self.api_base}/sse/signals")
        else:
            logger.info("SSE validation disabled (API_BASE not set)")

    async def validate(self):
        """Run validation"""
        self._running = True
        self.metrics.start_time = time.time()

        print("=" * 80)
        print("              PIPELINE VALIDATION")
        print("=" * 80)
        print(f"\nConfiguration:")
        print(f"  Duration: {self.validation_duration_sec} seconds")
        print(f"  SLA Threshold: {self.sla_threshold_ms}ms")
        print(f"  API Base: {self.api_base or 'N/A (Redis-only)'}")
        print(f"  Monitoring: {len(self.pairs)} pairs × {len(self.timeframes)} timeframes")
        print("")

        # Start monitoring tasks
        tasks = [
            asyncio.create_task(self._monitor_redis_streams()),
        ]

        # Add SSE monitor if API_BASE provided
        if self.api_base:
            tasks.append(asyncio.create_task(self._monitor_sse_endpoint()))

        # Add matcher task
        tasks.append(asyncio.create_task(self._match_signals()))

        # Run for specified duration
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=self.validation_duration_sec,
            )
        except asyncio.TimeoutError:
            logger.info(f"Validation duration ({self.validation_duration_sec}s) completed")
        finally:
            self._running = False

            # Cancel all tasks
            for task in tasks:
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

        # Calculate final statistics
        self.metrics.calculate_stats()

        # Generate report
        self._print_report()

    async def _monitor_redis_streams(self):
        """Monitor Redis streams for signals"""
        logger.info("Redis monitor started")

        # Build list of signal streams to monitor
        signal_streams = []
        for pair in self.pairs:
            for tf in self.timeframes:
                # Try both paper and live streams
                stream_key_paper = f"signals:paper:{pair.replace('/', '_')}:{tf}"
                stream_key_live = f"signals:live:{pair.replace('/', '_')}:{tf}"
                signal_streams.append(stream_key_paper)
                signal_streams.append(stream_key_live)

        # Track last ID for each stream
        # Start from 5 minutes ago to catch recent signals
        five_min_ago_ms = int((time.time() - 300) * 1000)
        stream_positions = {stream: f"{five_min_ago_ms}-0" for stream in signal_streams}

        logger.info(f"Monitoring {len(signal_streams)} Redis streams (from 5min ago)")

        while self._running:
            try:
                # Read new signals from all streams
                for stream_key in signal_streams:
                    try:
                        messages = await self.redis.xread(
                            {stream_key: stream_positions[stream_key]},
                            count=100,
                            block=100,  # 100ms timeout
                        )

                        if not messages:
                            continue

                        for stream, msgs in messages:
                            for msg_id, msg_data in msgs:
                                stream_positions[stream] = msg_id
                                await self._process_redis_signal(msg_data, msg_id)

                    except Exception as e:
                        logger.debug(f"Error reading {stream_key}: {e}")
                        continue

                await asyncio.sleep(0.01)  # Small delay to prevent tight loop

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in Redis monitor: {e}", exc_info=True)
                await asyncio.sleep(1)

        logger.info("Redis monitor stopped")

    async def _process_redis_signal(self, signal_data: Dict, msg_id: str):
        """Process a signal from Redis"""
        try:
            # Parse signal JSON
            signal_json = signal_data.get("signal", "{}")
            if isinstance(signal_json, bytes):
                signal_json = signal_json.decode("utf-8")

            signal = json.loads(signal_json)

            # Extract trace_id
            trace_id = signal.get("trace_id")
            if not trace_id:
                logger.warning(f"Signal missing trace_id: {msg_id}")
                return

            # Check for duplicates
            if trace_id in self.redis_signals:
                self.metrics.duplicate_redis += 1
                logger.warning(f"Duplicate Redis signal: {trace_id}")
                return

            # Create record
            record = SignalRecord(
                trace_id=trace_id,
                source="redis",
                timestamp_ms=int(time.time() * 1000),
                symbol=signal.get("symbol"),
                side=signal.get("side"),
                confidence=signal.get("confidence"),
                entry=signal.get("entry"),
                redis_publish_time=signal.get("ts_server"),
                data=signal,
            )

            self.redis_signals[trace_id] = record
            self.metrics.redis_signals_received += 1

            logger.debug(
                f"[REDIS] {record.symbol} {record.side} (trace_id={trace_id[:8]}...)"
            )

        except Exception as e:
            logger.error(f"Error processing Redis signal: {e}", exc_info=True)

    async def _monitor_sse_endpoint(self):
        """Monitor SSE endpoint for signals"""
        if not self.api_base:
            logger.info("SSE monitor skipped (API_BASE not set)")
            return

        logger.info(f"SSE monitor started: {self.api_base}/sse/signals")

        try:
            import httpx
        except ImportError:
            logger.error("httpx not installed. Install with: pip install httpx")
            return

        url = f"{self.api_base}/sse/signals"

        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("GET", url) as response:
                    if response.status_code != 200:
                        logger.error(f"SSE endpoint returned {response.status_code}")
                        return

                    logger.info("SSE connection established")

                    async for line in response.aiter_lines():
                        if not self._running:
                            break

                        # Parse SSE event
                        if line.startswith("data: "):
                            data = line[6:]  # Remove "data: " prefix
                            try:
                                await self._process_sse_signal(data)
                            except Exception as e:
                                logger.error(f"Error processing SSE signal: {e}")

        except asyncio.CancelledError:
            logger.info("SSE monitor cancelled")
        except Exception as e:
            logger.error(f"Error in SSE monitor: {e}", exc_info=True)

        logger.info("SSE monitor stopped")

    async def _process_sse_signal(self, data: str):
        """Process a signal from SSE"""
        try:
            # Parse JSON
            signal = json.loads(data)

            # Extract trace_id
            trace_id = signal.get("trace_id")
            if not trace_id:
                logger.warning("SSE signal missing trace_id")
                return

            # Check for duplicates
            if trace_id in self.sse_signals:
                self.metrics.duplicate_sse += 1
                logger.warning(f"Duplicate SSE signal: {trace_id}")
                return

            # Create record
            record = SignalRecord(
                trace_id=trace_id,
                source="sse",
                timestamp_ms=int(time.time() * 1000),
                symbol=signal.get("symbol"),
                side=signal.get("side"),
                confidence=signal.get("confidence"),
                entry=signal.get("entry"),
                redis_publish_time=signal.get("ts_server"),
                data=signal,
            )

            self.sse_signals[trace_id] = record
            self.metrics.sse_signals_received += 1

            logger.debug(
                f"[SSE] {record.symbol} {record.side} (trace_id={trace_id[:8]}...)"
            )

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse SSE JSON: {e}")
        except Exception as e:
            logger.error(f"Error processing SSE signal: {e}", exc_info=True)

    async def _match_signals(self):
        """Match Redis and SSE signals by trace_id"""
        logger.info("Signal matcher started")

        while self._running:
            try:
                # Check for matches
                redis_trace_ids = set(self.redis_signals.keys())
                sse_trace_ids = set(self.sse_signals.keys())

                # Find new matches
                matched_trace_ids = redis_trace_ids & sse_trace_ids

                for trace_id in matched_trace_ids:
                    if trace_id in self.matched_signals:
                        continue  # Already matched

                    redis_record = self.redis_signals[trace_id]
                    sse_record = self.sse_signals[trace_id]

                    # Calculate latency
                    latency_ms = sse_record.timestamp_ms - redis_record.timestamp_ms

                    # Store match
                    self.matched_signals[trace_id] = (redis_record, sse_record)
                    self.metrics.matched_signals += 1
                    self.metrics.latencies_ms.append(latency_ms)

                    # Check SLA
                    if latency_ms > self.sla_threshold_ms:
                        logger.warning(
                            f"SLA VIOLATION: {trace_id[:8]}... latency={latency_ms:.1f}ms "
                            f"(threshold={self.sla_threshold_ms}ms)"
                        )
                    else:
                        logger.info(
                            f"[MATCH] {trace_id[:8]}... latency={latency_ms:.1f}ms"
                        )

                await asyncio.sleep(0.5)  # Check every 500ms

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in signal matcher: {e}", exc_info=True)
                await asyncio.sleep(1)

        # Final check for unmatched signals
        redis_trace_ids = set(self.redis_signals.keys())
        sse_trace_ids = set(self.sse_signals.keys())

        unmatched_redis = redis_trace_ids - sse_trace_ids
        unmatched_sse = sse_trace_ids - redis_trace_ids

        self.metrics.unmatched_redis = len(unmatched_redis)
        self.metrics.unmatched_sse = len(unmatched_sse)

        # Store mismatches
        for trace_id in unmatched_redis:
            record = self.redis_signals[trace_id]
            self.metrics.mismatches.append({
                "trace_id": trace_id,
                "type": "redis_only",
                "symbol": record.symbol,
                "side": record.side,
                "timestamp": record.timestamp_ms,
            })

        for trace_id in unmatched_sse:
            record = self.sse_signals[trace_id]
            self.metrics.mismatches.append({
                "trace_id": trace_id,
                "type": "sse_only",
                "symbol": record.symbol,
                "side": record.side,
                "timestamp": record.timestamp_ms,
            })

        logger.info("Signal matcher stopped")

    def _print_report(self):
        """Print validation report"""
        print("\n" + "=" * 80)
        print("              VALIDATION REPORT")
        print("=" * 80)

        # Test Summary
        print(f"\nTest Duration: {self.metrics.duration_seconds:.1f}s")
        print(f"SLA Threshold: {self.metrics.sla_threshold_ms}ms")
        print("")

        # Signal Counts
        print("Signal Counts:")
        print(f"  Redis Signals:    {self.metrics.redis_signals_received}")
        print(f"  SSE Signals:      {self.metrics.sse_signals_received}")
        print(f"  Matched:          {self.metrics.matched_signals}")
        print(f"  Unmatched (Redis):{self.metrics.unmatched_redis}")
        print(f"  Unmatched (SSE):  {self.metrics.unmatched_sse}")
        print("")

        # Duplicates
        if self.metrics.duplicate_redis > 0 or self.metrics.duplicate_sse > 0:
            print("Duplicates:")
            print(f"  Redis:            {self.metrics.duplicate_redis}")
            print(f"  SSE:              {self.metrics.duplicate_sse}")
            print("")

        # Latency Statistics
        if self.metrics.latencies_ms:
            print("Latency Statistics:")
            print(f"  Median:           {self.metrics.median_latency_ms:.1f}ms")
            print(f"  95th Percentile:  {self.metrics.p95_latency_ms:.1f}ms")
            print(f"  Min:              {self.metrics.min_latency_ms:.1f}ms")
            print(f"  Max:              {self.metrics.max_latency_ms:.1f}ms")
            print("")

            # SLA Violations
            print("SLA Compliance:")
            print(f"  Violations:       {self.metrics.sla_violations} / {self.metrics.matched_signals}")
            if self.metrics.matched_signals > 0:
                compliance_rate = ((self.metrics.matched_signals - self.metrics.sla_violations) /
                                   self.metrics.matched_signals * 100)
                print(f"  Compliance Rate:  {compliance_rate:.1f}%")
            print("")

        # Mismatches
        if self.metrics.mismatches:
            print("Mismatches:")
            print(f"  Total:            {len(self.metrics.mismatches)}")

            # Show first 5 mismatches
            print("\n  Details (first 5):")
            for i, mismatch in enumerate(self.metrics.mismatches[:5], 1):
                print(f"    {i}. {mismatch['type']}: {mismatch['trace_id'][:8]}... "
                      f"({mismatch['symbol']} {mismatch['side']})")
            print("")

        # Gaps
        if self.metrics.gaps_detected > 0:
            print("Gaps:")
            print(f"  Total:            {self.metrics.gaps_detected}")
            print("")

        # Final Status
        print("=" * 80)
        if self.metrics.sla_violations > 0:
            print("Status: FAILED (SLA violations detected)")
            exit_code = 1
        elif self.metrics.unmatched_redis > 0 or self.metrics.unmatched_sse > 0:
            print("Status: WARNING (unmatched signals)")
            exit_code = 1
        elif self.metrics.matched_signals == 0:
            print("Status: NO DATA (no signals matched)")
            exit_code = 1
        else:
            print("Status: PASSED")
            exit_code = 0

        print("=" * 80)

        return exit_code


async def main():
    """Main entry point"""
    # Load environment
    env_file = project_root / ".env.paper"
    if env_file.exists():
        load_dotenv(env_file)

    # Configuration
    api_base = os.getenv("API_BASE")
    validation_duration = int(os.getenv("VALIDATION_DURATION_SEC", "60"))
    sla_threshold = float(os.getenv("SLA_THRESHOLD_MS", "2000"))

    # Redis connection
    redis_url = os.getenv("REDIS_URL")
    redis_ca_cert = os.getenv("REDIS_CA_CERT", "config/certs/redis_ca.pem")

    if not redis_url:
        print("[FAIL] REDIS_URL not set in environment")
        return 1

    # Connect to Redis
    print("Connecting to Redis...")
    redis_config = RedisCloudConfig(
        url=redis_url,
        ca_cert_path=redis_ca_cert,
    )
    redis_client = RedisCloudClient(redis_config)

    try:
        await redis_client.connect()
        print("[OK] Connected to Redis Cloud")
    except Exception as e:
        print(f"[FAIL] Failed to connect to Redis: {e}")
        return 1

    # Initialize validator
    validator = PipelineValidator(
        redis_client=redis_client,
        api_base=api_base,
        validation_duration_sec=validation_duration,
        sla_threshold_ms=sla_threshold,
    )

    # Run validation
    try:
        await validator.validate()
    except KeyboardInterrupt:
        print("\n\nValidation interrupted by user")
    except Exception as e:
        logger.error(f"Validation error: {e}", exc_info=True)
        return 1
    finally:
        await redis_client.aclose()

    # Return exit code based on validation result
    if validator.metrics.sla_violations > 0:
        return 1
    elif validator.metrics.unmatched_redis > 0 or validator.metrics.unmatched_sse > 0:
        return 1
    elif validator.metrics.matched_signals == 0:
        return 1
    else:
        return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
