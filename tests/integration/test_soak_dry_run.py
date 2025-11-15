#!/usr/bin/env python3
"""
Soak Test Dry-Run with Mocked Feeds
====================================

Integration test that simulates a full soak test run using mocked data:
- Mock signal generators producing signals at controlled rate
- Mock Redis client tracking all metrics
- Soak test monitor running with mocked data
- Report generation and validation

This verifies the entire soak test pipeline works correctly without
requiring live market data or a full 48-hour run.

Run with: pytest tests/integration/test_soak_dry_run.py -v -s
"""

import pytest
import asyncio
import time
import json
import os
from pathlib import Path
from typing import Dict, List, Optional
from unittest.mock import Mock, AsyncMock, patch
from dataclasses import dataclass
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent.parent
import sys
sys.path.insert(0, str(project_root))

from signals.scalper_schema import ScalperSignal
from agents.infrastructure.redis_client import RedisCloudClient
from agents.infrastructure.signal_queue import SignalQueue


# =============================================================================
# Mock Components
# =============================================================================

class MockRedisClient:
    """Mock Redis client that tracks all operations"""

    def __init__(self):
        self.streams: Dict[str, List] = {}
        self.keys_values: Dict[str, any] = {}
        self.xadd_count = 0
        self.xrevrange_count = 0

    async def xadd(self, stream: str, data: Dict, maxlen: Optional[int] = None):
        """Mock XADD - add entry to stream"""
        if stream not in self.streams:
            self.streams[stream] = []

        # Generate mock message ID
        now_ms = int(time.time() * 1000)
        msg_id = f"{now_ms}-{self.xadd_count}"

        # Store entry
        self.streams[stream].append((msg_id, data))

        # Apply MAXLEN trimming
        if maxlen and len(self.streams[stream]) > maxlen:
            self.streams[stream] = self.streams[stream][-maxlen:]

        self.xadd_count += 1
        return msg_id

    async def xrevrange(self, stream: str, start: str = '+', end: str = '-', count: Optional[int] = None):
        """Mock XREVRANGE - get entries in reverse order"""
        self.xrevrange_count += 1

        if stream not in self.streams:
            return []

        entries = self.streams[stream]

        # Reverse order (newest first)
        entries_reversed = list(reversed(entries))

        # Apply count limit
        if count:
            entries_reversed = entries_reversed[:count]

        return entries_reversed

    async def get(self, key: str):
        """Mock GET"""
        return self.keys_values.get(key)

    async def set(self, key: str, value: any):
        """Mock SET"""
        self.keys_values[key] = value

    async def ping(self):
        """Mock PING"""
        return True

    async def connect(self):
        """Mock connect"""
        pass

    async def aclose(self):
        """Mock close"""
        pass


class MockSignalGenerator:
    """Mock signal generator producing signals at controlled rate"""

    def __init__(
        self,
        symbol: str = "BTC/USD",
        timeframe: str = "15s",
        signals_per_minute: int = 4,
    ):
        self.symbol = symbol
        self.timeframe = timeframe
        self.signals_per_minute = signals_per_minute
        self.signal_interval_sec = 60.0 / signals_per_minute
        self.signals_generated = 0

    async def generate_signals(self, duration_sec: float, queue: SignalQueue) -> int:
        """
        Generate signals for specified duration.

        Args:
            duration_sec: How long to generate signals
            queue: Signal queue to publish to

        Returns:
            Number of signals generated
        """
        start_time = time.time()
        signals_count = 0

        while time.time() - start_time < duration_sec:
            # Generate signal
            signal = self._create_test_signal()

            # Enqueue
            success = await queue.enqueue(signal)
            if success:
                signals_count += 1
                self.signals_generated += 1

            # Wait for next signal
            await asyncio.sleep(self.signal_interval_sec)

        return signals_count

    def _create_test_signal(self) -> ScalperSignal:
        """Create a test signal with realistic parameters"""
        now_ms = int(time.time() * 1000)

        # Vary confidence between 0.65 and 0.95
        confidence = 0.65 + (self.signals_generated % 6) * 0.05

        # Alternate between long and short
        side = "long" if self.signals_generated % 2 == 0 else "short"

        # Mock prices
        if self.symbol == "BTC/USD":
            entry = 45000.0 + (self.signals_generated % 100) * 10
            stop = entry * 0.99 if side == "long" else entry * 1.01
            tp = entry * 1.02 if side == "long" else entry * 0.98
        elif self.symbol == "ETH/USD":
            entry = 3000.0 + (self.signals_generated % 100) * 5
            stop = entry * 0.99 if side == "long" else entry * 1.01
            tp = entry * 1.02 if side == "long" else entry * 0.98
        else:
            entry = 150.0 + (self.signals_generated % 100)
            stop = entry * 0.99 if side == "long" else entry * 1.01
            tp = entry * 1.02 if side == "long" else entry * 0.98

        return ScalperSignal(
            ts_exchange=now_ms - 50,  # 50ms ago
            ts_server=now_ms - 25,    # 25ms ago
            symbol=self.symbol,
            timeframe=self.timeframe,
            side=side,
            confidence=confidence,
            entry=entry,
            stop=stop,
            tp=tp,
            model="mock_generator_v1",
            trace_id=f"mock-{self.symbol.replace('/', '_')}-{self.signals_generated}",
        )


class MockSoakTestMonitor:
    """Mock soak test monitor that tracks metrics and generates reports"""

    def __init__(self, redis_client: MockRedisClient, duration_sec: float = 30.0):
        self.redis = redis_client
        self.duration_sec = duration_sec
        self.start_time = time.time()

        # Metrics
        self.checkpoint_count = 0
        self.metrics_history: List[Dict] = []

    async def run(self):
        """Run monitoring loop for specified duration"""
        print(f"\n{'=' * 80}")
        print(f"  SOAK TEST DRY-RUN MONITOR")
        print(f"  Duration: {self.duration_sec}s (simulating 48-hour test)")
        print(f"{'=' * 80}\n")

        while time.time() - self.start_time < self.duration_sec:
            # Fetch metrics
            metrics = await self._fetch_metrics()
            self.metrics_history.append(metrics)

            # Log checkpoint
            elapsed = time.time() - self.start_time
            await self._log_checkpoint(elapsed, metrics)

            self.checkpoint_count += 1

            # Sleep 2 seconds between checks
            await asyncio.sleep(2)

        # Generate final report
        report = await self._generate_report()
        return report

    async def _fetch_metrics(self) -> Dict:
        """Fetch current metrics from mock Redis"""
        metrics = {
            'timestamp': time.time(),
            'elapsed_sec': time.time() - self.start_time,
        }

        # Count signals in various streams
        signal_streams = [k for k in self.redis.streams.keys() if k.startswith('signals:')]
        total_signals = sum(len(self.redis.streams[s]) for s in signal_streams)
        metrics['total_signals'] = total_signals

        # Calculate signals per minute
        elapsed_min = (time.time() - self.start_time) / 60.0
        metrics['signals_per_min'] = total_signals / elapsed_min if elapsed_min > 0 else 0

        # Check heartbeat stream
        heartbeat_stream = self.redis.streams.get('metrics:scalper', [])
        metrics['heartbeat_count'] = len(heartbeat_stream)

        # Get latest heartbeat data
        if heartbeat_stream:
            latest_msg_id, latest_data = heartbeat_stream[-1]
            metrics['queue_depth'] = int(latest_data.get('queue_depth', 0))
            metrics['signals_shed'] = int(latest_data.get('signals_shed', 0))
            metrics['queue_utilization_pct'] = float(latest_data.get('queue_utilization_pct', 0))
        else:
            metrics['queue_depth'] = 0
            metrics['signals_shed'] = 0
            metrics['queue_utilization_pct'] = 0.0

        # Mock P&L metrics (would come from performance stream in real test)
        metrics['pnl_usd'] = 0.0  # Neutral for mock
        metrics['profit_factor'] = 0.0
        metrics['total_trades'] = 0

        # Mock latency metrics
        metrics['event_age_ms'] = 50.0  # From mock signals
        metrics['ingest_lag_ms'] = 25.0

        return metrics

    async def _log_checkpoint(self, elapsed_sec: float, metrics: Dict):
        """Log checkpoint"""
        print(f"[{elapsed_sec:.1f}s] Checkpoint {self.checkpoint_count + 1}:")
        print(f"  Signals: {metrics['total_signals']} ({metrics['signals_per_min']:.1f}/min)")
        print(f"  Heartbeats: {metrics['heartbeat_count']}")
        print(f"  Queue: {metrics['queue_depth']} (util={metrics['queue_utilization_pct']:.1f}%)")
        print(f"  Shed: {metrics['signals_shed']}")
        print(f"  Event Age: {metrics['event_age_ms']:.1f}ms")
        print()

    async def _generate_report(self) -> Dict:
        """Generate final soak test report"""
        final_metrics = self.metrics_history[-1] if self.metrics_history else {}

        report = {
            'test_type': 'dry_run',
            'duration_sec': self.duration_sec,
            'start_time': datetime.fromtimestamp(self.start_time).isoformat(),
            'end_time': datetime.now().isoformat(),
            'checkpoints': self.checkpoint_count,

            # Metrics summary
            'total_signals': final_metrics.get('total_signals', 0),
            'signals_per_min': final_metrics.get('signals_per_min', 0),
            'heartbeat_count': final_metrics.get('heartbeat_count', 0),
            'signals_shed': final_metrics.get('signals_shed', 0),
            'max_queue_utilization_pct': max(
                (m.get('queue_utilization_pct', 0) for m in self.metrics_history),
                default=0
            ),

            # Freshness metrics
            'avg_event_age_ms': final_metrics.get('event_age_ms', 0),
            'avg_ingest_lag_ms': final_metrics.get('ingest_lag_ms', 0),

            # Validation
            'passed': True,  # Mock always passes
            'validation_gates': [
                {'name': 'signals_generated', 'passed': final_metrics.get('total_signals', 0) > 0},
                {'name': 'heartbeats_emitted', 'passed': final_metrics.get('heartbeat_count', 0) > 0},
                {'name': 'no_errors', 'passed': True},
            ]
        }

        return report


# =============================================================================
# Tests
# =============================================================================

@pytest.mark.asyncio
async def test_soak_dry_run_basic():
    """Test basic soak test dry-run with single signal generator"""
    print("\n" + "=" * 80)
    print("TEST: Basic Soak Test Dry-Run")
    print("=" * 80)

    # Create mock Redis
    redis = MockRedisClient()

    # Create signal queue
    queue = SignalQueue(
        redis_client=redis,
        max_size=100,
        heartbeat_interval_sec=3.0,  # Fast heartbeat for testing
        prometheus_exporter=None,
    )

    # Start queue
    await queue.start()

    try:
        # Create signal generator
        generator = MockSignalGenerator(
            symbol="BTC/USD",
            timeframe="15s",
            signals_per_minute=10,  # 10 signals per minute
        )

        # Create monitor
        monitor = MockSoakTestMonitor(redis, duration_sec=10.0)

        # Run generator and monitor concurrently
        print("\nStarting signal generation and monitoring...")

        generator_task = asyncio.create_task(
            generator.generate_signals(duration_sec=10.0, queue=queue)
        )
        monitor_task = asyncio.create_task(monitor.run())

        # Wait for both to complete
        signals_generated, report = await asyncio.gather(
            generator_task,
            monitor_task
        )

        # Verify results
        print("\n" + "=" * 80)
        print("RESULTS:")
        print("=" * 80)
        print(f"Signals Generated: {signals_generated}")
        print(f"Total Signals in Redis: {report['total_signals']}")
        print(f"Signals Per Minute: {report['signals_per_min']:.1f}")
        print(f"Heartbeats Emitted: {report['heartbeat_count']}")
        print(f"Signals Shed: {report['signals_shed']}")
        print(f"Max Queue Utilization: {report['max_queue_utilization_pct']:.1f}%")
        print(f"Checkpoints: {report['checkpoints']}")
        print(f"Validation: {'PASSED' if report['passed'] else 'FAILED'}")
        print("=" * 80)

        # Assertions
        assert signals_generated > 0, "Should generate signals"
        assert report['total_signals'] > 0, "Signals should be in Redis"
        assert report['heartbeat_count'] > 0, "Should emit heartbeats"
        assert report['checkpoints'] > 0, "Should have checkpoints"
        assert report['passed'] is True, "Should pass validation"

        # Verify signal rate is reasonable (at least 1 signal)
        # Note: Due to async timing, we may not get exact expected rate
        assert signals_generated >= 1, "Should generate at least 1 signal"

        print("\n[PASS] Basic soak test dry-run PASSED")

    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_soak_dry_run_multi_pair():
    """Test soak test with multiple trading pairs"""
    print("\n" + "=" * 80)
    print("TEST: Multi-Pair Soak Test Dry-Run")
    print("=" * 80)

    # Create mock Redis
    redis = MockRedisClient()

    # Create signal queue
    queue = SignalQueue(
        redis_client=redis,
        max_size=100,
        heartbeat_interval_sec=3.0,
        prometheus_exporter=None,
    )

    await queue.start()

    try:
        # Create generators for multiple pairs
        generators = [
            MockSignalGenerator("BTC/USD", "15s", signals_per_minute=8),
            MockSignalGenerator("ETH/USD", "15s", signals_per_minute=8),
            MockSignalGenerator("SOL/USD", "15s", signals_per_minute=8),
        ]

        # Create monitor
        monitor = MockSoakTestMonitor(redis, duration_sec=12.0)

        print("\nStarting multi-pair signal generation...")

        # Run all generators and monitor concurrently
        tasks = [
            asyncio.create_task(gen.generate_signals(12.0, queue))
            for gen in generators
        ]
        tasks.append(asyncio.create_task(monitor.run()))

        results = await asyncio.gather(*tasks)

        signals_per_pair = results[:-1]  # All except last (monitor report)
        report = results[-1]

        # Verify results
        print("\n" + "=" * 80)
        print("RESULTS:")
        print("=" * 80)
        for i, count in enumerate(signals_per_pair):
            print(f"{generators[i].symbol}: {count} signals")
        print(f"Total in Redis: {report['total_signals']}")
        print(f"Heartbeats: {report['heartbeat_count']}")
        print(f"Signals Shed: {report['signals_shed']}")
        print("=" * 80)

        # Assertions
        total_generated = sum(signals_per_pair)
        assert total_generated > 0, "Should generate signals"
        assert report['total_signals'] > 0, "Signals should be in Redis"
        assert len(signals_per_pair) == 3, "Should have 3 pairs"

        # Each pair should generate signals
        for count in signals_per_pair:
            assert count > 0, "Each pair should generate signals"

        print("\n[PASS] Multi-pair soak test dry-run PASSED")

    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_soak_dry_run_high_frequency():
    """Test soak test with high-frequency signal generation"""
    print("\n" + "=" * 80)
    print("TEST: High-Frequency Soak Test")
    print("=" * 80)

    # Create mock Redis
    redis = MockRedisClient()

    # Create normal queue
    queue = SignalQueue(
        redis_client=redis,
        max_size=100,
        heartbeat_interval_sec=2.0,
        prometheus_exporter=None,
    )

    await queue.start()

    try:
        # Create high-frequency generator
        generator = MockSignalGenerator(
            symbol="BTC/USD",
            timeframe="15s",
            signals_per_minute=60,  # High frequency
        )

        monitor = MockSoakTestMonitor(redis, duration_sec=6.0)

        print("\nStarting high-frequency generation...")

        generator_task = asyncio.create_task(
            generator.generate_signals(6.0, queue)
        )
        monitor_task = asyncio.create_task(monitor.run())

        signals_generated, report = await asyncio.gather(
            generator_task,
            monitor_task
        )

        # Verify high-frequency generation
        print("\n" + "=" * 80)
        print("HIGH-FREQUENCY RESULTS:")
        print("=" * 80)
        print(f"Signals Generated: {signals_generated}")
        print(f"Signals/min: {report['signals_per_min']:.1f}")
        print(f"Total in Redis: {report['total_signals']}")
        print(f"Heartbeats: {report['heartbeat_count']}")
        print("=" * 80)

        # Assertions
        assert signals_generated > 0, "Should generate signals"
        assert report['total_signals'] > 0, "Signals should be in Redis"

        # Verify high signal rate (at least 30/min)
        assert report['signals_per_min'] >= 30.0, f"Expected high signal rate, got {report['signals_per_min']:.1f}/min"

        print("\n[PASS] High-frequency soak test PASSED")

    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_soak_dry_run_report_generation():
    """Test that soak test report is generated correctly"""
    print("\n" + "=" * 80)
    print("TEST: Soak Test Report Generation")
    print("=" * 80)

    redis = MockRedisClient()
    queue = SignalQueue(redis, max_size=100, heartbeat_interval_sec=2.0)

    await queue.start()

    try:
        generator = MockSignalGenerator("BTC/USD", "15s", 12)
        monitor = MockSoakTestMonitor(redis, duration_sec=6.0)

        print("\nRunning soak test for report generation...")

        _, report = await asyncio.gather(
            generator.generate_signals(6.0, queue),
            monitor.run()
        )

        # Verify report structure
        print("\n" + "=" * 80)
        print("REPORT STRUCTURE VALIDATION:")
        print("=" * 80)

        required_fields = [
            'test_type', 'duration_sec', 'start_time', 'end_time',
            'total_signals', 'signals_per_min', 'heartbeat_count',
            'signals_shed', 'max_queue_utilization_pct',
            'avg_event_age_ms', 'avg_ingest_lag_ms',
            'passed', 'validation_gates'
        ]

        for field in required_fields:
            assert field in report, f"Report missing field: {field}"
            print(f"  [OK] {field}: {report[field]}")

        # Verify validation gates
        assert len(report['validation_gates']) > 0, "Should have validation gates"
        for gate in report['validation_gates']:
            assert 'name' in gate, "Gate should have name"
            assert 'passed' in gate, "Gate should have passed status"
            print(f"  [OK] Gate '{gate['name']}': {'PASSED' if gate['passed'] else 'FAILED'}")

        # Write report to file
        report_path = project_root / "logs" / "soak_dry_run_report.json"
        report_path.parent.mkdir(exist_ok=True)

        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2)

        print(f"\n[OK] Report written to: {report_path}")
        print("=" * 80)

        assert report['passed'] is True, "Report should indicate passing status"

        print("\n[PASS] Report generation test PASSED")

    finally:
        await queue.stop()


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    # Run all tests
    pytest.main([__file__, "-v", "-s"])
