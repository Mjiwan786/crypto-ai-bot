#!/usr/bin/env python3
"""
Integration Tests for Redis Publish/Read-back
==============================================

Tests (marked live opt-in):
- Publish signal → read-back from Redis
- Assert ordering & fields preserved
- Test with actual Redis connection

Run with: pytest -m live
Skip with: pytest -m "not live"
"""

import pytest
import asyncio
import time
import os
import json
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
import sys
sys.path.insert(0, str(project_root))

from signals.scalper_schema import ScalperSignal
from agents.infrastructure.redis_client import RedisCloudClient, RedisCloudConfig
from agents.infrastructure.signal_queue import SignalQueue
from dotenv import load_dotenv


@pytest.mark.live
class TestRedisPublishReadback:
    """Integration tests with actual Redis connection"""

    @pytest.fixture(scope="class")
    async def redis_client(self):
        """Create Redis client for tests"""
        # Load environment
        env_file = project_root / ".env.paper"
        if env_file.exists():
            load_dotenv(env_file)

        redis_url = os.getenv("REDIS_URL")
        redis_ca_cert = os.getenv("REDIS_CA_CERT", "config/certs/redis_ca.pem")

        if not redis_url:
            pytest.skip("REDIS_URL not set - skipping Redis integration tests")

        # Connect to Redis
        config = RedisCloudConfig(url=redis_url, ca_cert_path=redis_ca_cert)
        client = RedisCloudClient(config)

        try:
            await client.connect()
            yield client
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_publish_and_readback_single_signal(self, redis_client):
        """Test publishing a single signal and reading it back"""
        # Create test signal with unique trace_id
        now_ms = int(time.time() * 1000)
        trace_id = f"test-integration-{now_ms}"

        signal = ScalperSignal(
            ts_exchange=now_ms - 100,
            ts_server=now_ms - 50,
            symbol="BTC/USD",
            timeframe="15s",
            side="long",
            confidence=0.85,
            entry=45000.0,
            stop=44500.0,
            tp=46000.0,
            model="test_integration_v1",
            trace_id=trace_id,
        )

        # Publish to Redis
        stream_key = signal.get_stream_key()
        signal_json = signal.to_json_str()

        await redis_client.xadd(
            stream_key,
            {"signal": signal_json},
            maxlen=10000,
        )

        # Read back from Redis (get latest entry)
        messages = await redis_client.xrevrange(stream_key, count=1)

        assert len(messages) > 0, "No messages in stream"

        # Parse the signal
        msg_id, msg_data = messages[0]
        read_signal_json = msg_data.get("signal")

        if isinstance(read_signal_json, bytes):
            read_signal_json = read_signal_json.decode("utf-8")

        read_signal_dict = json.loads(read_signal_json)

        # Assert all fields preserved
        assert read_signal_dict["trace_id"] == trace_id
        assert read_signal_dict["symbol"] == "BTC/USD"
        assert read_signal_dict["timeframe"] == "15s"
        assert read_signal_dict["side"] == "long"
        assert read_signal_dict["confidence"] == 0.85
        assert read_signal_dict["entry"] == 45000.0
        assert read_signal_dict["stop"] == 44500.0
        assert read_signal_dict["tp"] == 46000.0
        assert read_signal_dict["model"] == "test_integration_v1"
        assert read_signal_dict["ts_exchange"] == now_ms - 100
        assert read_signal_dict["ts_server"] == now_ms - 50

    @pytest.mark.asyncio
    async def test_publish_ordering_preserved(self, redis_client):
        """Test that signal ordering is preserved in Redis"""
        # Create multiple signals with sequential trace IDs
        base_time = int(time.time() * 1000)
        signals = []

        for i in range(5):
            signal = ScalperSignal(
                ts_exchange=base_time + i * 100,
                ts_server=base_time + i * 100 + 50,
                symbol="ETH/USD",
                timeframe="15s",
                side="long" if i % 2 == 0 else "short",
                confidence=0.70 + i * 0.05,
                entry=3000.0 + i,
                stop=2950.0 + i,
                tp=3100.0 + i,
                model="test_ordering",
                trace_id=f"test-order-{base_time}-{i}",
            )
            signals.append(signal)

        # Publish all signals
        stream_key = signals[0].get_stream_key()

        for signal in signals:
            signal_json = signal.to_json_str()
            await redis_client.xadd(
                stream_key,
                {"signal": signal_json},
                maxlen=10000,
            )

        # Small delay to ensure writes complete
        await asyncio.sleep(0.1)

        # Read back all signals (in reverse order - newest first)
        messages = await redis_client.xrevrange(stream_key, count=5)

        # Should have at least 5 messages
        assert len(messages) >= 5

        # Extract trace_ids from newest to oldest
        trace_ids = []
        for msg_id, msg_data in messages[:5]:
            signal_json = msg_data.get("signal")
            if isinstance(signal_json, bytes):
                signal_json = signal_json.decode("utf-8")

            signal_dict = json.loads(signal_json)
            trace_id = signal_dict["trace_id"]

            # Only include our test signals
            if trace_id.startswith(f"test-order-{base_time}"):
                trace_ids.append(trace_id)

        # Ordering should be preserved (newest first = index 4, 3, 2, 1, 0)
        expected_order = [
            f"test-order-{base_time}-4",
            f"test-order-{base_time}-3",
            f"test-order-{base_time}-2",
            f"test-order-{base_time}-1",
            f"test-order-{base_time}-0",
        ]

        assert trace_ids == expected_order, f"Ordering not preserved. Got: {trace_ids}"

    @pytest.mark.asyncio
    async def test_signal_queue_publish_and_readback(self, redis_client):
        """Test signal queue publishing with read-back verification"""
        # Create signal queue
        queue = SignalQueue(
            redis_client=redis_client,
            max_size=100,
            heartbeat_interval_sec=60,
            prometheus_exporter=None,
        )

        # Start queue
        await queue.start()

        try:
            # Create test signal
            now_ms = int(time.time() * 1000)
            trace_id = f"test-queue-{now_ms}"

            signal = ScalperSignal(
                ts_exchange=now_ms - 100,
                ts_server=now_ms - 50,
                symbol="SOL/USD",
                timeframe="15s",
                side="short",
                confidence=0.92,
                entry=150.0,
                stop=148.0,
                tp=155.0,
                model="test_queue_integration",
                trace_id=trace_id,
            )

            # Enqueue signal
            success = await queue.enqueue(signal)
            assert success is True

            # Wait for signal to be published
            await asyncio.sleep(2)

            # Read back from Redis
            stream_key = signal.get_stream_key()
            messages = await redis_client.xrevrange(stream_key, count=10)

            # Find our signal
            found = False
            for msg_id, msg_data in messages:
                signal_json = msg_data.get("signal")
                if isinstance(signal_json, bytes):
                    signal_json = signal_json.decode("utf-8")

                signal_dict = json.loads(signal_json)

                if signal_dict["trace_id"] == trace_id:
                    found = True

                    # Verify fields
                    assert signal_dict["symbol"] == "SOL/USD"
                    assert signal_dict["side"] == "short"
                    assert signal_dict["confidence"] == 0.92
                    assert signal_dict["entry"] == 150.0
                    break

            assert found, f"Signal with trace_id {trace_id} not found in Redis"

            # Verify queue stats
            stats = queue.get_stats()
            assert stats["signals_enqueued"] >= 1
            assert stats["signals_published"] >= 1

        finally:
            await queue.stop()

    @pytest.mark.asyncio
    async def test_multiple_signals_different_pairs(self, redis_client):
        """Test publishing signals for different pairs"""
        base_time = int(time.time() * 1000)

        signals_data = [
            ("BTC/USD", "long", 0.85, 45000.0),
            ("ETH/USD", "short", 0.78, 3000.0),
            ("SOL/USD", "long", 0.90, 150.0),
            ("LINK/USD", "short", 0.82, 15.0),
        ]

        published_signals = {}

        for i, (symbol, side, conf, entry) in enumerate(signals_data):
            trace_id = f"test-multi-{base_time}-{i}"

            signal = ScalperSignal(
                ts_exchange=base_time + i * 100,
                ts_server=base_time + i * 100 + 50,
                symbol=symbol,
                timeframe="15s",
                side=side,
                confidence=conf,
                entry=entry,
                stop=entry * 0.99 if side == "long" else entry * 1.01,
                tp=entry * 1.02 if side == "long" else entry * 0.98,
                model="test_multi_pair",
                trace_id=trace_id,
            )

            # Publish
            stream_key = signal.get_stream_key()
            signal_json = signal.to_json_str()

            await redis_client.xadd(
                stream_key,
                {"signal": signal_json},
                maxlen=10000,
            )

            published_signals[trace_id] = (symbol, stream_key)

        # Wait for writes
        await asyncio.sleep(0.2)

        # Verify each signal in its respective stream
        for trace_id, (symbol, stream_key) in published_signals.items():
            messages = await redis_client.xrevrange(stream_key, count=10)

            found = False
            for msg_id, msg_data in messages:
                signal_json = msg_data.get("signal")
                if isinstance(signal_json, bytes):
                    signal_json = signal_json.decode("utf-8")

                signal_dict = json.loads(signal_json)

                if signal_dict["trace_id"] == trace_id:
                    found = True
                    assert signal_dict["symbol"] == symbol
                    break

            assert found, f"Signal {trace_id} for {symbol} not found"


@pytest.mark.live
class TestRedisStreamTrimming:
    """Test Redis stream MAXLEN trimming"""

    @pytest.fixture(scope="class")
    async def redis_client(self):
        """Create Redis client"""
        env_file = project_root / ".env.paper"
        if env_file.exists():
            load_dotenv(env_file)

        redis_url = os.getenv("REDIS_URL")
        redis_ca_cert = os.getenv("REDIS_CA_CERT", "config/certs/redis_ca.pem")

        if not redis_url:
            pytest.skip("REDIS_URL not set")

        config = RedisCloudConfig(url=redis_url, ca_cert_path=redis_ca_cert)
        client = RedisCloudClient(config)

        try:
            await client.connect()
            yield client
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_stream_maxlen_trimming(self, redis_client):
        """Test that MAXLEN parameter trims old entries"""
        # Create unique stream key for this test
        test_stream = f"test:maxlen:{int(time.time() * 1000)}"

        # Publish 15 signals with MAXLEN=10
        for i in range(15):
            await redis_client.xadd(
                test_stream,
                {"index": str(i), "data": f"test-{i}"},
                maxlen=10,
            )

        # Wait for trimming
        await asyncio.sleep(0.1)

        # Read all entries
        messages = await redis_client.xrevrange(test_stream, count=20)

        # Should have at most 10 entries
        assert len(messages) <= 10, f"Stream has {len(messages)} entries, expected ≤10"

        # Entries should be the latest (5-14)
        indices = []
        for msg_id, msg_data in messages:
            index_str = msg_data.get("index")
            if isinstance(index_str, bytes):
                index_str = index_str.decode("utf-8")
            indices.append(int(index_str))

        # Latest entries should be present
        assert max(indices) == 14
        assert min(indices) >= 5  # Older entries trimmed


if __name__ == "__main__":
    # Run with: pytest tests/integration/test_redis_publish_readback.py -m live -v
    pytest.main([__file__, "-m", "live", "-v"])
