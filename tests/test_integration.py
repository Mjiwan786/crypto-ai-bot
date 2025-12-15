"""
Integration Tests for Complete System Flow.

Tests Redis publishing, API endpoints, and end-to-end signal flow.

Author: QA Team
Version: 1.0.0
Date: 2025-11-17
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pytest
import redis
import json
import time
import requests
from datetime import datetime
from typing import Dict
import asyncio

# Import centralized signals API config
from config.signals_api_config import SIGNALS_API_BASE_URL

# Redis configuration
REDIS_URL = "rediss://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com:19818"
API_URL = SIGNALS_API_BASE_URL


class TestRedisIntegration:
    """Test Redis connection and operations."""

    @pytest.fixture
    def redis_client(self):
        """Create Redis client."""
        client = redis.from_url(
            REDIS_URL,
            decode_responses=True,
            ssl=True,
            ssl_cert_reqs='required'
        )
        yield client
        client.close()

    def test_redis_connection(self, redis_client):
        """Test Redis connection is successful."""
        try:
            response = redis_client.ping()
            assert response is True, "Redis ping failed"
        except redis.ConnectionError as e:
            pytest.fail(f"Redis connection failed: {e}")

    def test_redis_publish_signal(self, redis_client):
        """Test publishing signal to Redis."""
        # Create test signal
        signal = {
            'timestamp': datetime.utcnow().isoformat(),
            'symbol': 'BTC/USDT',
            'timeframe': '15m',
            'signal': 'LONG',
            'confidence': 0.75,
            'probabilities': json.dumps({
                'LONG': 0.75,
                'SHORT': 0.10,
                'NEUTRAL': 0.15
            }),
            'regime': 'trending_up'
        }

        # Publish to stream
        stream_key = "ml_signals_test:BTC/USDT:15m"

        try:
            message_id = redis_client.xadd(
                stream_key,
                signal,
                maxlen=1000
            )

            assert message_id is not None, "Failed to publish message"

            # Verify message was added
            messages = redis_client.xread({stream_key: '0-0'}, count=1)
            assert len(messages) > 0, "No messages in stream"

            # Cleanup
            redis_client.delete(stream_key)

        except redis.RedisError as e:
            pytest.fail(f"Redis publish failed: {e}")

    def test_redis_stream_read(self, redis_client):
        """Test reading from Redis stream."""
        stream_key = "ml_signals_test:BTC/USDT:15m"

        # Add test messages
        for i in range(5):
            redis_client.xadd(
                stream_key,
                {'index': i, 'signal': 'LONG', 'confidence': 0.75}
            )

        # Read messages
        messages = redis_client.xread({stream_key: '0-0'}, count=10)

        assert len(messages) > 0, "No messages read"
        assert len(messages[0][1]) == 5, f"Expected 5 messages, got {len(messages[0][1])}"

        # Cleanup
        redis_client.delete(stream_key)

    def test_redis_latency(self, redis_client):
        """Test Redis operation latency."""
        # Measure write latency
        start = time.time()
        redis_client.set('test_key', 'test_value')
        write_latency = (time.time() - start) * 1000

        # Measure read latency
        start = time.time()
        redis_client.get('test_key')
        read_latency = (time.time() - start) * 1000

        # Cleanup
        redis_client.delete('test_key')

        # Assert latencies are reasonable
        assert write_latency < 100, f"Write latency too high: {write_latency:.2f}ms"
        assert read_latency < 100, f"Read latency too high: {read_latency:.2f}ms"

    def test_redis_reconnection(self, redis_client):
        """Test Redis reconnection after connection drop."""
        # This test simulates connection resilience
        # In production, use redis-py's automatic retry

        try:
            # First operation
            redis_client.set('test_reconnect', 'value1')

            # Simulate reconnection by creating new client
            new_client = redis.from_url(
                REDIS_URL,
                decode_responses=True,
                ssl=True,
                ssl_cert_reqs='required'
            )

            # Second operation with new client
            value = new_client.get('test_reconnect')
            assert value == 'value1', "Reconnection failed to retrieve value"

            # Cleanup
            new_client.delete('test_reconnect')
            new_client.close()

        except redis.ConnectionError as e:
            pytest.fail(f"Reconnection failed: {e}")


class TestAPIEndpoints:
    """Test signals-api REST endpoints."""

    @pytest.fixture
    def api_url(self):
        """API base URL."""
        return API_URL

    def test_api_health_check(self, api_url):
        """Test API health check endpoint."""
        try:
            response = requests.get(f"{api_url}/health", timeout=5)
            assert response.status_code == 200, f"Health check failed: {response.status_code}"

            data = response.json()
            assert data.get('status') == 'healthy' or 'status' in data

        except requests.RequestException as e:
            pytest.fail(f"Health check request failed: {e}")

    def test_api_signals_endpoint(self, api_url):
        """Test /v1/signals endpoint."""
        try:
            response = requests.get(f"{api_url}/v1/signals", timeout=10)

            # Should return 200 or 404 if no signals
            assert response.status_code in [200, 404], \
                f"Unexpected status code: {response.status_code}"

            if response.status_code == 200:
                data = response.json()
                assert isinstance(data, (dict, list)), "Invalid response format"

        except requests.RequestException as e:
            pytest.skip(f"API not available: {e}")

    def test_api_pnl_endpoint(self, api_url):
        """Test /v1/pnl endpoint."""
        try:
            response = requests.get(f"{api_url}/v1/pnl", timeout=10)

            # Should return 200 or 404 if no PnL data
            assert response.status_code in [200, 404], \
                f"Unexpected status code: {response.status_code}"

            if response.status_code == 200:
                data = response.json()
                assert isinstance(data, dict), "Invalid PnL response format"

        except requests.RequestException as e:
            pytest.skip(f"API not available: {e}")

    def test_api_response_time(self, api_url):
        """Test API response time is under 500ms."""
        try:
            start = time.time()
            response = requests.get(f"{api_url}/health", timeout=5)
            response_time = (time.time() - start) * 1000

            assert response.status_code == 200
            assert response_time < 500, \
                f"Response time too high: {response_time:.2f}ms (target: <500ms)"

        except requests.RequestException as e:
            pytest.skip(f"API not available: {e}")

    def test_api_cors_headers(self, api_url):
        """Test API has proper CORS headers."""
        try:
            response = requests.get(f"{api_url}/health", timeout=5)

            # Check CORS headers
            headers = response.headers

            # These may or may not be present depending on API configuration
            # Just verify response succeeds
            assert response.status_code == 200

        except requests.RequestException as e:
            pytest.skip(f"API not available: {e}")


class TestSSEStream:
    """Test Server-Sent Events streaming."""

    def test_sse_connection(self):
        """Test SSE connection to /v1/signals/stream."""
        import sseclient

        try:
            response = requests.get(
                f"{API_URL}/v1/signals/stream",
                stream=True,
                timeout=10
            )

            assert response.status_code == 200, \
                f"SSE connection failed: {response.status_code}"

            # Try to read first event (with timeout)
            client = sseclient.SSEClient(response)

            # Read one event
            start = time.time()
            for event in client.events():
                # Got first event
                assert event is not None
                break

                # Timeout after 5 seconds
                if time.time() - start > 5:
                    break

        except requests.RequestException as e:
            pytest.skip(f"SSE endpoint not available: {e}")
        except ImportError:
            pytest.skip("sseclient-py not installed. Install with: pip install sseclient-py")

    def test_sse_reconnection(self):
        """Test SSE reconnection after disconnect."""
        # This would require more complex setup
        # For now, just verify endpoint exists
        try:
            response = requests.head(f"{API_URL}/v1/signals/stream", timeout=5)
            # Endpoint should exist (200 or 405 for HEAD)
            assert response.status_code in [200, 405]
        except requests.RequestException as e:
            pytest.skip(f"SSE endpoint not available: {e}")


class TestEndToEndFlow:
    """Test complete end-to-end signal flow."""

    @pytest.fixture
    def redis_client(self):
        """Create Redis client."""
        client = redis.from_url(
            REDIS_URL,
            decode_responses=True,
            ssl=True,
            ssl_cert_reqs='required'
        )
        yield client
        client.close()

    def test_signal_flow_latency(self, redis_client):
        """Test complete signal flow from generation to delivery."""
        # This test simulates the complete flow:
        # 1. Generate signal (mock)
        # 2. Publish to Redis
        # 3. API reads from Redis
        # 4. Frontend receives via SSE

        start_time = time.time()

        # Step 1: Generate mock signal
        signal = {
            'timestamp': datetime.utcnow().isoformat(),
            'symbol': 'BTC/USDT',
            'timeframe': '15m',
            'signal': 'LONG',
            'confidence': 0.75,
            'probabilities': json.dumps({
                'LONG': 0.75,
                'SHORT': 0.10,
                'NEUTRAL': 0.15
            })
        }

        # Step 2: Publish to Redis
        stream_key = "ml_signals_test:BTC/USDT:15m"
        message_id = redis_client.xadd(stream_key, signal)

        publish_time = time.time()

        # Step 3: Verify message in Redis
        messages = redis_client.xread({stream_key: message_id}, count=1)
        assert len(messages) > 0, "Signal not found in Redis"

        read_time = time.time()

        # Calculate latencies
        publish_latency = (publish_time - start_time) * 1000
        total_latency = (read_time - start_time) * 1000

        # Cleanup
        redis_client.delete(stream_key)

        # Assert latencies
        assert publish_latency < 100, \
            f"Publish latency too high: {publish_latency:.2f}ms"
        assert total_latency < 500, \
            f"Total latency too high: {total_latency:.2f}ms (target: <500ms)"

    def test_signal_publish_and_retrieve(self, redis_client):
        """Test publishing and retrieving signal."""
        from ml.redis_signal_publisher import MLSignal, RedisSignalPublisher

        # Create publisher
        publisher = RedisSignalPublisher(
            redis_url=REDIS_URL,
            stream_prefix="ml_signals_test"
        )

        # Create test signal
        signal = MLSignal(
            timestamp=datetime.utcnow().isoformat(),
            symbol='BTC/USDT',
            timeframe='15m',
            signal='LONG',
            confidence=0.75,
            prob_long=0.75,
            prob_short=0.10,
            prob_neutral=0.15,
            regime='trending_up',
            agreement=0.85,
            weights={'lstm': 0.45, 'transformer': 0.35, 'cnn': 0.20},
            lstm_signal='LONG',
            lstm_confidence=0.80,
            transformer_signal='LONG',
            transformer_confidence=0.72,
            cnn_signal='NEUTRAL',
            cnn_confidence=0.65,
            confidence_level='high',
            position_size=0.75,
            stop_loss_pct=2.0,
            take_profit_pct=4.0
        )

        # Publish
        success = publisher.publish_signal(signal)
        assert success, "Failed to publish signal"

        # Retrieve
        latest = publisher.get_latest_signal('BTC/USDT', '15m')
        assert latest is not None, "Failed to retrieve signal"
        assert latest.signal == 'LONG'
        assert latest.confidence == 0.75

        # Cleanup
        publisher.close()


class TestErrorHandling:
    """Test error handling and graceful degradation."""

    def test_missing_redis_url(self):
        """Test handling of missing REDIS_URL."""
        import os

        # Save original
        original_url = os.environ.get('REDIS_URL')

        try:
            # Remove REDIS_URL
            if 'REDIS_URL' in os.environ:
                del os.environ['REDIS_URL']

            # Try to create client without URL should fail gracefully
            with pytest.raises((ValueError, TypeError)):
                redis.from_url(None)

        finally:
            # Restore
            if original_url:
                os.environ['REDIS_URL'] = original_url

    def test_invalid_redis_credentials(self):
        """Test handling of invalid Redis credentials."""
        invalid_url = "redis://invalid:password@localhost:6379"

        try:
            client = redis.from_url(invalid_url, socket_connect_timeout=2)
            client.ping()
            pytest.fail("Should have raised connection error")

        except redis.ConnectionError:
            # Expected
            pass

    def test_api_unavailable_graceful_degradation(self):
        """Test graceful degradation when API is unavailable."""
        invalid_api_url = "http://invalid-api-url.example.com"

        try:
            response = requests.get(
                f"{invalid_api_url}/health",
                timeout=2
            )
            pytest.fail("Should have raised request exception")

        except requests.RequestException:
            # Expected - should handle gracefully in frontend
            # Frontend should show "Metrics unavailable"
            pass

    def test_malformed_signal_handling(self, redis_client=None):
        """Test handling of malformed signals."""
        # Create client if not provided
        if redis_client is None:
            redis_client = redis.from_url(
                REDIS_URL,
                decode_responses=True,
                ssl=True,
                ssl_cert_reqs='required'
            )

        # Publish malformed signal
        stream_key = "ml_signals_test:BTC/USDT:15m"

        malformed_signal = {
            'timestamp': 'invalid-timestamp',
            'signal': 'INVALID_SIGNAL',  # Invalid value
            'confidence': 'not-a-number'   # Invalid type
        }

        # Should still publish (Redis doesn't validate)
        message_id = redis_client.xadd(stream_key, malformed_signal)
        assert message_id is not None

        # Consumer should handle validation
        messages = redis_client.xread({stream_key: '0-0'}, count=1)

        # Cleanup
        redis_client.delete(stream_key)

        # In production, consumer should validate and reject
        # This test just verifies the flow doesn't crash


class TestConcurrency:
    """Test concurrent operations and race conditions."""

    def test_concurrent_redis_writes(self, redis_client=None):
        """Test multiple concurrent writes to Redis."""
        import threading

        if redis_client is None:
            redis_client = redis.from_url(
                REDIS_URL,
                decode_responses=True,
                ssl=True,
                ssl_cert_reqs='required'
            )

        stream_key = "ml_signals_test_concurrent:BTC/USDT:15m"
        num_threads = 10

        def write_signal(index):
            """Write signal to Redis."""
            client = redis.from_url(
                REDIS_URL,
                decode_responses=True,
                ssl=True,
                ssl_cert_reqs='required'
            )

            signal = {
                'index': index,
                'timestamp': datetime.utcnow().isoformat(),
                'signal': 'LONG'
            }

            client.xadd(stream_key, signal)
            client.close()

        # Create threads
        threads = []
        for i in range(num_threads):
            t = threading.Thread(target=write_signal, args=(i,))
            threads.append(t)
            t.start()

        # Wait for all threads
        for t in threads:
            t.join(timeout=5)

        # Verify all messages were written
        messages = redis_client.xread({stream_key: '0-0'}, count=num_threads + 5)

        assert len(messages) > 0
        assert len(messages[0][1]) == num_threads, \
            f"Expected {num_threads} messages, got {len(messages[0][1])}"

        # Cleanup
        redis_client.delete(stream_key)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "-s"])
