"""
Tests for metrics.publisher module.
"""

import asyncio
import pytest
import time
import orjson
from unittest.mock import Mock, AsyncMock, patch

# Add parent to path
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from metrics.publisher import MetricsPublisher


class TestMetricsPublisher:
    """Test suite for MetricsPublisher."""

    @pytest.fixture
    async def mock_redis_client(self):
        """Create a mock Redis client."""
        mock_client = AsyncMock()
        mock_client.ping = AsyncMock(return_value=True)
        mock_client.set = AsyncMock()
        mock_client.xadd = AsyncMock(return_value=b'1234567890-0')
        mock_client.xlen = AsyncMock(return_value=100)
        mock_client.aclose = AsyncMock()
        return mock_client

    @pytest.fixture
    async def mock_ws_client(self):
        """Create a mock KrakenWebSocketClient."""
        mock_ws = Mock()
        mock_ws.get_stats = Mock(return_value={
            'messages_received': 1000,
            'reconnects': 0,
            'circuit_breaker_trips': 5,
            'errors': 0,
            'trades_per_minute': 10,
            'running': True,
            'latency_stats': {
                'avg': 25.5,
                'p50': 20.0,
                'p95': 50.0,
                'p99': 75.0,
                'max': 100.0
            },
            'circuit_breakers': {
                'spread': 'closed',
                'latency': 'closed',
                'connection': 'closed'
            }
        })
        return mock_ws

    @pytest.fixture
    def publisher(self):
        """Create a MetricsPublisher instance."""
        return MetricsPublisher(
            redis_url='rediss://localhost:6379',
            redis_cert_path='/path/to/cert.pem'
        )

    def test_publisher_initialization(self, publisher):
        """Test publisher initializes correctly."""
        assert publisher.redis_url == 'rediss://localhost:6379'
        assert publisher.redis_cert_path == '/path/to/cert.pem'
        assert publisher.redis_client is None
        assert publisher.ws_client is None
        assert isinstance(publisher.start_time, float)

    @pytest.mark.asyncio
    async def test_connect_redis_success(self, publisher, mock_redis_client):
        """Test successful Redis connection."""
        with patch('redis.asyncio.from_url', return_value=mock_redis_client):
            result = await publisher.connect_redis()
            assert result is True
            assert publisher.redis_client is not None
            mock_redis_client.ping.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_redis_failure(self, publisher):
        """Test Redis connection failure."""
        with patch('redis.asyncio.from_url', side_effect=Exception("Connection failed")):
            result = await publisher.connect_redis()
            assert result is False
            assert publisher.redis_client is None

    @pytest.mark.asyncio
    async def test_estimate_redis_lag(self, publisher, mock_redis_client):
        """Test Redis lag estimation."""
        publisher.redis_client = mock_redis_client

        # Simulate some delay
        async def slow_ping():
            await asyncio.sleep(0.01)
            return True

        mock_redis_client.ping = slow_ping

        lag = await publisher.estimate_redis_lag()
        assert lag > 0
        assert lag < 100  # Should be less than 100ms in test

    @pytest.mark.asyncio
    async def test_get_stream_sizes(self, publisher, mock_redis_client):
        """Test getting stream sizes."""
        publisher.redis_client = mock_redis_client
        publisher.trading_pairs = ['BTC/USD', 'ETH/USD']

        # Mock xlen to return different sizes
        xlen_values = iter([10, 20, 30, 40, 50, 60, 70, 80, 100, 200, 300, 400])

        async def mock_xlen(stream_name):
            return next(xlen_values)

        mock_redis_client.xlen = mock_xlen

        sizes = await publisher.get_stream_sizes()

        assert isinstance(sizes, dict)
        assert 'kraken:trade:BTC-USD' in sizes
        assert 'kraken:spread:ETH-USD' in sizes
        assert 'kraken:health' in sizes
        assert all(isinstance(v, int) for v in sizes.values())

    @pytest.mark.asyncio
    async def test_collect_metrics_without_ws_client(self, publisher, mock_redis_client):
        """Test metrics collection without WS client."""
        publisher.redis_client = mock_redis_client
        publisher.trading_pairs = ['BTC/USD']

        metrics = await publisher.collect_metrics()

        # Check required fields
        assert 'timestamp' in metrics
        assert 'timestamp_iso' in metrics
        assert 'uptime_s' in metrics
        assert 'last_heartbeat_ts' in metrics
        assert 'ws_latency_ms' in metrics
        assert 'messages_received' in metrics
        assert 'circuit_breaker_trips' in metrics
        assert 'redis_ok' in metrics
        assert 'redis_lag_estimate' in metrics
        assert 'stream_sizes' in metrics

        # Check default values
        assert metrics['messages_received'] == 0
        assert metrics['running'] is False

    @pytest.mark.asyncio
    async def test_collect_metrics_with_ws_client(self, publisher, mock_redis_client, mock_ws_client):
        """Test metrics collection with WS client."""
        publisher.redis_client = mock_redis_client
        publisher.ws_client = mock_ws_client
        publisher.trading_pairs = ['BTC/USD']

        metrics = await publisher.collect_metrics()

        # Check WS client stats are included
        assert metrics['messages_received'] == 1000
        assert metrics['circuit_breaker_trips'] == 5
        assert metrics['trades_per_minute'] == 10
        assert metrics['running'] is True

        # Check latency stats
        assert metrics['ws_latency_ms']['avg'] == 25.5
        assert metrics['ws_latency_ms']['p95'] == 50.0
        assert metrics['ws_latency_ms']['p99'] == 75.0

        # Check circuit breakers
        assert 'spread' in metrics['circuit_breakers']

    @pytest.mark.asyncio
    async def test_publish_metrics(self, publisher, mock_redis_client):
        """Test metrics publishing to Redis."""
        publisher.redis_client = mock_redis_client

        metrics = {
            'timestamp': time.time(),
            'timestamp_iso': '2025-01-01T00:00:00Z',
            'messages_received': 100,
            'uptime_s': 60.0
        }

        await publisher.publish_metrics(metrics)

        # Verify SET was called for summary
        mock_redis_client.set.assert_called_once()
        call_args = mock_redis_client.set.call_args
        assert call_args[0][0] == 'engine:metrics:summary'

        # Verify XADD was called for events stream
        mock_redis_client.xadd.assert_called_once()
        xadd_args = mock_redis_client.xadd.call_args
        assert xadd_args[0][0] == 'engine:metrics:events'
        assert 'maxlen' in xadd_args[1]
        assert xadd_args[1]['maxlen'] == 1000

    @pytest.mark.asyncio
    async def test_publish_once(self, publisher, mock_redis_client):
        """Test single metrics publish."""
        publisher.redis_client = mock_redis_client
        publisher.trading_pairs = ['BTC/USD']

        metrics = await publisher.publish_once()

        assert isinstance(metrics, dict)
        assert 'timestamp' in metrics
        assert publisher.last_heartbeat > 0
        mock_redis_client.set.assert_called_once()
        mock_redis_client.xadd.assert_called_once()

    @pytest.mark.asyncio
    async def test_metrics_json_serialization(self, publisher, mock_redis_client, mock_ws_client):
        """Test that metrics can be serialized to JSON."""
        publisher.redis_client = mock_redis_client
        publisher.ws_client = mock_ws_client
        publisher.trading_pairs = ['BTC/USD']

        metrics = await publisher.collect_metrics()

        # Ensure metrics can be serialized with orjson
        try:
            json_bytes = orjson.dumps(metrics)
            assert isinstance(json_bytes, bytes)

            # Deserialize and verify
            deserialized = orjson.loads(json_bytes)
            assert deserialized['messages_received'] == metrics['messages_received']
        except Exception as e:
            pytest.fail(f"Failed to serialize metrics: {e}")

    @pytest.mark.asyncio
    async def test_close(self, publisher, mock_redis_client):
        """Test closing Redis connection."""
        publisher.redis_client = mock_redis_client

        await publisher.close()

        mock_redis_client.aclose.assert_called_once()


# Integration test (requires real Redis connection)
@pytest.mark.integration
@pytest.mark.asyncio
async def test_integration_full_cycle():
    """
    Full integration test with real Redis (if available).

    Run with: pytest -m integration tests/test_metrics_publisher.py
    """
    import os
    from dotenv import load_dotenv

    load_dotenv('.env.prod')

    redis_url = os.getenv('REDIS_URL')
    redis_cert = os.getenv('REDIS_TLS_CERT_PATH')

    if not redis_url:
        pytest.skip("REDIS_URL not configured")

    publisher = MetricsPublisher(
        redis_url=redis_url,
        redis_cert_path=redis_cert
    )

    try:
        # Connect
        connected = await publisher.connect_redis()
        assert connected is True

        # Publish metrics
        metrics = await publisher.publish_once()

        assert metrics is not None
        assert 'timestamp' in metrics

        # Verify data was written
        summary_data = await publisher.redis_client.get('engine:metrics:summary')
        assert summary_data is not None

        # Deserialize and verify
        summary = orjson.loads(summary_data)
        assert 'timestamp' in summary
        assert 'uptime_s' in summary

        print(f"Integration test passed. Published metrics with uptime: {summary['uptime_s']}s")

    finally:
        await publisher.close()


if __name__ == '__main__':
    # Run tests
    pytest.main([__file__, '-v'])
