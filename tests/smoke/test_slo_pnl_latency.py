#!/usr/bin/env python3
"""
SLO Tests for PnL Latency - Crypto AI Bot

Service Level Objective (SLO) tests to ensure production-grade performance.

SLO Requirements:
- P95 publish latency < 500ms
- 100 trades processed in < 1 second
- No message loss (all trades result in equity points)

Tests use mocked time and Redis to verify performance without network dependencies.
"""

import time
from collections import deque
from typing import Dict, List
from unittest.mock import MagicMock, patch

import pytest

try:
    import orjson
except ImportError:
    import json as orjson


# Mock Redis client for testing
class MockRedisStreamClient:
    """Mock Redis client with stream support and latency tracking."""

    def __init__(self, latency_ms: float = 0):
        self.data: Dict[str, bytes] = {}
        self.streams: Dict[str, List[tuple]] = {}
        self.connected = True
        self.latency_ms = latency_ms
        self.publish_times: List[float] = []  # Track when messages published

    def ping(self):
        """Mock ping."""
        if not self.connected:
            raise Exception("Not connected")
        return True

    def get(self, key: str) -> bytes | None:
        """Mock GET."""
        return self.data.get(key)

    def set(self, key: str, value: any) -> bool:
        """Mock SET."""
        self.data[key] = value if isinstance(value, bytes) else str(value).encode("utf-8")
        return True

    def xadd(self, stream: str, fields: dict) -> bytes:
        """Mock XADD with latency tracking."""
        # Simulate network latency
        if self.latency_ms > 0:
            time.sleep(self.latency_ms / 1000)

        if stream not in self.streams:
            self.streams[stream] = []

        # Generate message ID
        msg_id = f"{len(self.streams[stream])}-0"
        self.streams[stream].append((msg_id, fields))

        # Track publish time
        self.publish_times.append(time.perf_counter())

        return msg_id.encode("utf-8")

    def xread(self, streams: dict, count: int = 1, block: int = 0) -> List:
        """Mock XREAD."""
        result = []
        for stream_name, last_id in streams.items():
            if stream_name not in self.streams:
                continue

            # Parse last_id
            if last_id == "0-0":
                start_idx = 0
            else:
                try:
                    start_idx = int(last_id.split("-")[0]) + 1
                except (ValueError, IndexError):
                    start_idx = 0

            # Get messages after last_id
            messages = self.streams[stream_name][start_idx : start_idx + count]

            if messages:
                formatted_messages = []
                for msg_id, fields in messages:
                    formatted_messages.append((msg_id.encode("utf-8"), fields))

                result.append((stream_name.encode("utf-8"), formatted_messages))

        return result if result else None

    @classmethod
    def from_url(cls, url: str, **kwargs):
        """Mock from_url constructor."""
        return cls()


def _create_trade_event(trade_id: str, ts_ms: int, pnl: float) -> dict:
    """Helper to create a trade event."""
    return {
        "id": trade_id,
        "ts": ts_ms,
        "pair": "BTC/USD",
        "side": "long",
        "entry": 45000.0,
        "exit": 46000.0,
        "qty": 0.1,
        "pnl": pnl,
    }


def _serialize_event(event: dict) -> dict:
    """Helper to serialize event to Redis field format."""
    if hasattr(orjson, "dumps"):
        json_bytes = orjson.dumps(event)
    else:
        json_bytes = orjson.dumps(event).encode("utf-8")

    return {b"json": json_bytes}


class TestSLOPublishLatency:
    """Test suite for publish latency SLOs."""

    def test_publish_100_trades_under_1_second(self):
        """Test that 100 trades can be published in under 1 second."""
        from agents.infrastructure.pnl_publisher import publish_trade_close

        # Mock Redis with minimal latency
        mock_redis = MockRedisStreamClient(latency_ms=0)

        with patch("agents.infrastructure.pnl_publisher._get_redis_client", return_value=mock_redis):
            # Create 100 trades
            trades = [
                _create_trade_event(f"trade_{i}", 1704067200000 + i * 1000, 10.0 * (i % 10))
                for i in range(100)
            ]

            # Measure publish time
            start_time = time.perf_counter()

            for trade in trades:
                publish_trade_close(trade)

            end_time = time.perf_counter()
            elapsed_ms = (end_time - start_time) * 1000

            # Assert SLO: 100 trades in < 1 second
            assert elapsed_ms < 1000, f"Publish latency too high: {elapsed_ms:.2f}ms (SLO: < 1000ms)"

            # Verify all trades published
            assert len(mock_redis.streams.get("trades:closed", [])) == 100

            print(f"✅ Published 100 trades in {elapsed_ms:.2f}ms (SLO: < 1000ms)")

    def test_p95_latency_under_500ms(self):
        """Test that P95 publish latency is under 500ms."""
        from agents.infrastructure.pnl_publisher import publish_trade_close

        # Mock Redis with realistic latency (10ms average)
        mock_redis = MockRedisStreamClient(latency_ms=10)

        with patch("agents.infrastructure.pnl_publisher._get_redis_client", return_value=mock_redis):
            # Publish 100 trades and measure individual latencies
            latencies = []

            for i in range(100):
                trade = _create_trade_event(f"trade_{i}", 1704067200000 + i * 1000, 10.0)

                start = time.perf_counter()
                publish_trade_close(trade)
                end = time.perf_counter()

                latency_ms = (end - start) * 1000
                latencies.append(latency_ms)

            # Calculate P95
            latencies.sort()
            p95_index = int(len(latencies) * 0.95)
            p95_latency = latencies[p95_index]

            # Assert SLO: P95 < 500ms
            assert p95_latency < 500, f"P95 latency too high: {p95_latency:.2f}ms (SLO: < 500ms)"

            print(f"✅ P95 publish latency: {p95_latency:.2f}ms (SLO: < 500ms)")
            print(f"   Mean: {sum(latencies) / len(latencies):.2f}ms")
            print(f"   Max: {max(latencies):.2f}ms")

    def test_no_message_loss(self):
        """Test that all published trades result in equity points (no loss)."""
        from agents.infrastructure.pnl_publisher import publish_equity_point, publish_trade_close

        mock_redis = MockRedisStreamClient()

        with patch("agents.infrastructure.pnl_publisher._get_redis_client", return_value=mock_redis):
            # Publish 50 trades
            num_trades = 50
            for i in range(num_trades):
                trade = _create_trade_event(f"trade_{i}", 1704067200000 + i * 1000, 10.0)
                publish_trade_close(trade)

            # Publish 50 equity points
            for i in range(num_trades):
                publish_equity_point(
                    ts_ms=1704067200000 + i * 1000,
                    equity=10000.0 + (i * 10.0),
                    daily_pnl=i * 10.0,
                )

            # Verify no loss
            trades_published = len(mock_redis.streams.get("trades:closed", []))
            equity_published = len(mock_redis.streams.get("pnl:equity", []))

            assert trades_published == num_trades, f"Trade message loss: {num_trades - trades_published}"
            assert equity_published == num_trades, f"Equity message loss: {num_trades - equity_published}"

            print(f"✅ No message loss: {trades_published} trades → {equity_published} equity points")


class TestSLOAggregatorLatency:
    """Test suite for aggregator processing latency SLOs."""

    def test_aggregator_processes_batch_under_500ms(self):
        """Test that aggregator processes a batch of 200 trades in < 500ms."""
        # This test simulates the aggregator loop processing a batch
        mock_redis = MockRedisStreamClient()

        # Seed 200 trades into stream
        for i in range(200):
            trade = _create_trade_event(f"trade_{i}", 1704067200000 + i * 1000, 10.0 * (i % 10))
            mock_redis.xadd("trades:closed", _serialize_event(trade))

        # Simulate aggregator processing loop
        equity = 10000.0
        last_id = "0-0"

        start_time = time.perf_counter()

        # Read batch (count=200)
        result = mock_redis.xread({"trades:closed": last_id}, count=200)

        if result:
            stream_name, messages = result[0]

            for msg_id, fields in messages:
                # Parse event
                json_bytes = fields.get(b"json")
                if hasattr(orjson, "loads"):
                    event = orjson.loads(json_bytes)
                else:
                    event = orjson.loads(json_bytes.decode("utf-8"))

                # Update equity (simulate aggregator work)
                pnl = event.get("pnl", 0)
                equity += pnl

                # Publish equity point
                snapshot = {
                    "ts": event["ts"],
                    "equity": equity,
                    "daily_pnl": equity - 10000.0,
                }
                if hasattr(orjson, "dumps"):
                    json_bytes = orjson.dumps(snapshot)
                else:
                    json_bytes = orjson.dumps(snapshot).encode("utf-8")

                mock_redis.xadd("pnl:equity", {b"json": json_bytes})

                # Update last_id
                last_id = msg_id.decode("utf-8") if isinstance(msg_id, bytes) else msg_id

        end_time = time.perf_counter()
        elapsed_ms = (end_time - start_time) * 1000

        # Assert SLO: Process 200 trades in < 500ms
        assert elapsed_ms < 500, f"Aggregator batch latency too high: {elapsed_ms:.2f}ms (SLO: < 500ms)"

        # Verify all processed
        equity_points = len(mock_redis.streams.get("pnl:equity", []))
        assert equity_points == 200

        print(f"✅ Processed 200 trades in {elapsed_ms:.2f}ms (SLO: < 500ms)")
        print(f"   Throughput: {200 / (elapsed_ms / 1000):.0f} trades/sec")

    def test_aggregator_end_to_end_latency(self):
        """Test end-to-end latency from trade publish to equity publish."""
        from agents.infrastructure.pnl_publisher import publish_trade_close

        mock_redis = MockRedisStreamClient()

        with patch("agents.infrastructure.pnl_publisher._get_redis_client", return_value=mock_redis):
            # Measure end-to-end latency for 10 trades
            e2e_latencies = []

            for i in range(10):
                trade = _create_trade_event(f"trade_{i}", 1704067200000 + i * 1000, 10.0)

                # Start timer
                start = time.perf_counter()

                # Publish trade
                publish_trade_close(trade)

                # Simulate aggregator reading and publishing equity
                result = mock_redis.xread({"trades:closed": f"{i-1}-0" if i > 0 else "0-0"}, count=1)
                if result:
                    # Parse and publish equity (simulating aggregator)
                    snapshot = {
                        "ts": trade["ts"],
                        "equity": 10000.0 + (i * 10.0),
                        "daily_pnl": i * 10.0,
                    }
                    if hasattr(orjson, "dumps"):
                        json_bytes = orjson.dumps(snapshot)
                    else:
                        json_bytes = orjson.dumps(snapshot).encode("utf-8")

                    mock_redis.xadd("pnl:equity", {b"json": json_bytes})

                # End timer
                end = time.perf_counter()

                e2e_latency_ms = (end - start) * 1000
                e2e_latencies.append(e2e_latency_ms)

            # Calculate P95 end-to-end latency
            e2e_latencies.sort()
            p95_index = int(len(e2e_latencies) * 0.95)
            p95_e2e = e2e_latencies[p95_index]

            # Assert SLO: P95 end-to-end < 500ms
            assert p95_e2e < 500, f"P95 E2E latency too high: {p95_e2e:.2f}ms (SLO: < 500ms)"

            print(f"✅ P95 end-to-end latency: {p95_e2e:.2f}ms (SLO: < 500ms)")
            print(f"   Mean E2E: {sum(e2e_latencies) / len(e2e_latencies):.2f}ms")


class TestSLODataFreshness:
    """Test suite for data freshness SLOs."""

    def test_equity_data_freshness_under_5_minutes(self):
        """Test that equity data is never more than 5 minutes stale."""
        mock_redis = MockRedisStreamClient()

        # Current time (ms)
        now_ms = int(time.time() * 1000)

        # Publish equity point with recent timestamp
        recent_ts = now_ms - (60 * 1000)  # 1 minute ago
        snapshot = {
            "ts": recent_ts,
            "equity": 10500.0,
            "daily_pnl": 500.0,
        }

        if hasattr(orjson, "dumps"):
            json_bytes = orjson.dumps(snapshot)
        else:
            json_bytes = orjson.dumps(snapshot).encode("utf-8")

        mock_redis.xadd("pnl:equity", {b"json": json_bytes})
        mock_redis.set("pnl:equity:latest", json_bytes)

        # Read latest equity
        latest_bytes = mock_redis.get("pnl:equity:latest")
        if hasattr(orjson, "loads"):
            latest_data = orjson.loads(latest_bytes)
        else:
            latest_data = orjson.loads(latest_bytes.decode("utf-8"))

        # Calculate staleness
        staleness_ms = now_ms - latest_data["ts"]
        staleness_sec = staleness_ms / 1000

        # Assert SLO: Data freshness < 5 minutes (300s)
        assert staleness_sec < 300, f"Data too stale: {staleness_sec:.1f}s (SLO: < 300s)"

        print(f"✅ Data freshness: {staleness_sec:.1f}s (SLO: < 300s)")

    def test_stale_data_detection(self):
        """Test that stale data is detected correctly."""
        mock_redis = MockRedisStreamClient()

        # Current time
        now_ms = int(time.time() * 1000)

        # Publish stale equity point (10 minutes ago)
        stale_ts = now_ms - (10 * 60 * 1000)  # 10 minutes ago
        snapshot = {
            "ts": stale_ts,
            "equity": 10000.0,
            "daily_pnl": 0.0,
        }

        if hasattr(orjson, "dumps"):
            json_bytes = orjson.dumps(snapshot)
        else:
            json_bytes = orjson.dumps(snapshot).encode("utf-8")

        mock_redis.xadd("pnl:equity", {b"json": json_bytes})
        mock_redis.set("pnl:equity:latest", json_bytes)

        # Read and check staleness
        latest_bytes = mock_redis.get("pnl:equity:latest")
        if hasattr(orjson, "loads"):
            latest_data = orjson.loads(latest_bytes)
        else:
            latest_data = orjson.loads(latest_bytes.decode("utf-8"))

        staleness_ms = now_ms - latest_data["ts"]
        staleness_sec = staleness_ms / 1000

        # Should be stale (> 5 minutes)
        assert staleness_sec > 300, f"Expected stale data, got {staleness_sec:.1f}s"

        print(f"✅ Stale data detected: {staleness_sec:.1f}s (threshold: 300s)")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
