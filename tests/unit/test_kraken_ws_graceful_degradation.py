"""
Unit tests for Kraken WebSocket graceful degradation (PRD-001 Section 1.4)

Tests verify:
- WebSocket protocol error handling (close codes 1000, 1001, 1006, 1011, 1012)
- Data caching with 5-minute TTL
- Cached data serving when WebSocket unavailable > 30s
- Health check marks unhealthy during sustained failures (> 2 min)
"""

import pytest
import asyncio
import time
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from utils.kraken_ws import KrakenWebSocketClient, KrakenWSConfig, ConnectionState
import websockets.exceptions


class TestWebSocketCloseCodeHandling:
    """Test WebSocket protocol error handling"""

    @pytest.fixture
    def config(self):
        """Create test configuration"""
        return KrakenWSConfig(
            url="wss://ws.kraken.com",
            pairs=["BTC/USD"],
            redis_url=""
        )

    @pytest.fixture
    def client(self, config):
        """Create WebSocket client for testing"""
        return KrakenWebSocketClient(config)

    @pytest.mark.asyncio
    async def test_normal_closure_1000_logged_at_info(self, client, caplog):
        """Test that normal closure (code 1000) is logged at INFO level"""
        import logging

        # Create a mock exception with code attribute
        exc = Mock(spec=websockets.exceptions.ConnectionClosed)
        exc.code = 1000
        exc.reason = "Normal closure"

        # Mock the websocket connect to raise ConnectionClosed
        async def mock_connect(*args, **kwargs):
            class MockWS:
                async def __aenter__(self):
                    return self
                async def __aexit__(self, *args):
                    pass
                def __aiter__(self):
                    return self
                async def __anext__(self):
                    raise exc
            return MockWS()

        with patch('websockets.connect', side_effect=mock_connect):
            with caplog.at_level(logging.INFO):
                try:
                    await client.connect_once()
                except:
                    pass

        # Should have INFO log for normal closure
        info_logs = [record for record in caplog.records if record.levelname == "INFO"]
        assert any("closed normally" in log.message.lower() and "1000" in log.message for log in info_logs)

    @pytest.mark.asyncio
    async def test_abnormal_closure_1006_logged_at_warning(self, client, caplog):
        """Test that abnormal closure (code 1006) is logged at WARNING level"""
        import logging

        exc = Mock(spec=websockets.exceptions.ConnectionClosed)
        exc.code = 1006
        exc.reason = "Connection lost"

        async def mock_connect(*args, **kwargs):
            class MockWS:
                async def __aenter__(self):
                    return self
                async def __aexit__(self, *args):
                    pass
                def __aiter__(self):
                    return self
                async def __anext__(self):
                    raise exc
            return MockWS()

        with patch('websockets.connect', side_effect=mock_connect):
            with caplog.at_level(logging.WARNING):
                try:
                    await client.connect_once()
                except:
                    pass

        # Should have WARNING log for abnormal closure
        warning_logs = [record for record in caplog.records if record.levelname == "WARNING"]
        assert any("abnormal closure" in log.message.lower() and "1006" in log.message for log in warning_logs)

    @pytest.mark.asyncio
    async def test_protocol_error_1006_increments_counter(self, client):
        """Test that abnormal closure increments error counter"""
        from utils.kraken_ws import PROMETHEUS_AVAILABLE, KRAKEN_WS_ERRORS_TOTAL

        if not PROMETHEUS_AVAILABLE:
            pytest.skip("Prometheus not available")

        # Get initial counter value
        initial_value = KRAKEN_WS_ERRORS_TOTAL.labels(error_type='protocol_error_1006')._value.get()

        exc = Mock(spec=websockets.exceptions.ConnectionClosed)
        exc.code = 1006
        exc.reason = "Connection lost"

        async def mock_connect(*args, **kwargs):
            class MockWS:
                async def __aenter__(self):
                    return self
                async def __aexit__(self, *args):
                    pass
                def __aiter__(self):
                    return self
                async def __anext__(self):
                    raise exc
            return MockWS()

        with patch('websockets.connect', side_effect=mock_connect):
            try:
                await client.connect_once()
            except:
                pass

        # Counter should have incremented
        final_value = KRAKEN_WS_ERRORS_TOTAL.labels(error_type='protocol_error_1006')._value.get()
        assert final_value == initial_value + 1

    @pytest.mark.asyncio
    async def test_server_error_1011_logged_at_error(self, client, caplog):
        """Test that server error (code 1011) is logged at ERROR level"""
        import logging

        exc = Mock(spec=websockets.exceptions.ConnectionClosed)
        exc.code = 1011
        exc.reason = "Server error"

        async def mock_connect(*args, **kwargs):
            class MockWS:
                async def __aenter__(self):
                    return self
                async def __aexit__(self, *args):
                    pass
                def __aiter__(self):
                    return self
                async def __anext__(self):
                    raise exc
            return MockWS()

        with patch('websockets.connect', side_effect=mock_connect):
            with caplog.at_level(logging.ERROR):
                try:
                    await client.connect_once()
                except:
                    pass

        # Should have ERROR log for server error
        error_logs = [record for record in caplog.records if record.levelname == "ERROR"]
        assert any("server error" in log.message.lower() and "1011" in log.message for log in error_logs)


class TestDataCaching:
    """Test data caching for graceful degradation"""

    @pytest.fixture
    def config(self):
        """Create test configuration"""
        return KrakenWSConfig(
            url="wss://ws.kraken.com",
            pairs=["BTC/USD"],
            redis_url=""
        )

    @pytest.fixture
    def client(self, config):
        """Create WebSocket client for testing"""
        return KrakenWebSocketClient(config)

    def test_cache_data_stores_with_timestamp(self, client):
        """Test that cache_data stores data with timestamp"""
        test_data = {"price": 50000, "volume": 1.5}

        client.cache_data("trade", "BTC/USD", test_data)

        cache_key = "trade:BTC/USD"
        assert cache_key in client.data_cache
        assert client.data_cache[cache_key]["data"] == test_data
        assert "timestamp" in client.data_cache[cache_key]
        assert client.data_cache[cache_key]["channel"] == "trade"
        assert client.data_cache[cache_key]["pair"] == "BTC/USD"

    def test_cache_ttl_is_5_minutes(self, client):
        """Test that cache TTL is 5 minutes (300 seconds)"""
        assert client.cache_ttl == 300

    def test_is_cache_valid_returns_true_for_fresh_cache(self, client):
        """Test that is_cache_valid returns True for fresh cache"""
        test_data = {"price": 50000}
        client.cache_data("trade", "BTC/USD", test_data)

        assert client.is_cache_valid("trade", "BTC/USD") is True

    def test_is_cache_valid_returns_false_for_stale_cache(self, client):
        """Test that is_cache_valid returns False for stale cache"""
        test_data = {"price": 50000}

        # Manually create old cache entry
        cache_key = "trade:BTC/USD"
        client.data_cache[cache_key] = {
            "data": test_data,
            "timestamp": time.time() - 400,  # 400 seconds ago (> 5 minutes)
            "channel": "trade",
            "pair": "BTC/USD"
        }

        assert client.is_cache_valid("trade", "BTC/USD") is False

    def test_is_cache_valid_returns_false_for_missing_cache(self, client):
        """Test that is_cache_valid returns False when no cache exists"""
        assert client.is_cache_valid("trade", "BTC/USD") is False

    def test_get_cached_data_returns_none_when_connected(self, client):
        """Test that get_cached_data returns None when WebSocket is connected"""
        test_data = {"price": 50000}
        client.cache_data("trade", "BTC/USD", test_data)

        # Set connection state to CONNECTED
        client._set_connection_state(ConnectionState.CONNECTED, "Test connection")

        # Should not serve cache when connected
        cached = client.get_cached_data("trade", "BTC/USD")
        assert cached is None

    def test_get_cached_data_returns_none_when_recently_disconnected(self, client):
        """Test that cached data not served if disconnected < 30s"""
        test_data = {"price": 50000}
        client.cache_data("trade", "BTC/USD", test_data)

        # Set connection state to DISCONNECTED (just now)
        client._set_connection_state(ConnectionState.DISCONNECTED, "Just disconnected")

        # Should not serve cache yet (< 30s since disconnect)
        cached = client.get_cached_data("trade", "BTC/USD")
        assert cached is None

    def test_get_cached_data_returns_data_when_disconnected_over_30s(self, client):
        """Test that cached data served if disconnected > 30s"""
        test_data = {"price": 50000}
        client.cache_data("trade", "BTC/USD", test_data)

        # Manually set connection state changed time to > 30s ago
        client.connection_state = ConnectionState.DISCONNECTED
        client.connection_state_changed_at = time.time() - 40  # 40 seconds ago

        # Should serve cache now
        cached = client.get_cached_data("trade", "BTC/USD")
        assert cached is not None
        assert cached["data"] == test_data
        assert cached["cached"] is True
        assert "age" in cached
        assert "timestamp" in cached

    def test_get_cached_data_returns_none_for_stale_cache(self, client):
        """Test that stale cache (> 5 min) is not served"""
        # Create old cache entry
        cache_key = "trade:BTC/USD"
        client.data_cache[cache_key] = {
            "data": {"price": 50000},
            "timestamp": time.time() - 400,  # 400 seconds ago
            "channel": "trade",
            "pair": "BTC/USD"
        }

        # Set disconnected for > 30s
        client.connection_state = ConnectionState.DISCONNECTED
        client.connection_state_changed_at = time.time() - 40

        # Should not serve stale cache
        cached = client.get_cached_data("trade", "BTC/USD")
        assert cached is None

    def test_cache_data_logged_at_debug(self, client, caplog):
        """Test that caching is logged at DEBUG level"""
        import logging

        with caplog.at_level(logging.DEBUG):
            client.cache_data("trade", "BTC/USD", {"price": 50000})

        debug_logs = [record for record in caplog.records if record.levelname == "DEBUG"]
        assert any("cached data" in log.message.lower() and "trade:btc/usd" in log.message.lower() for log in debug_logs)

    def test_serving_cached_data_logged_at_info(self, client, caplog):
        """Test that serving cached data is logged at INFO level"""
        import logging

        # Cache data
        client.cache_data("trade", "BTC/USD", {"price": 50000})

        # Set disconnected for > 30s
        client.connection_state = ConnectionState.DISCONNECTED
        client.connection_state_changed_at = time.time() - 40

        with caplog.at_level(logging.INFO):
            client.get_cached_data("trade", "BTC/USD")

        info_logs = [record for record in caplog.records if record.levelname == "INFO"]
        assert any("serving cached data" in log.message.lower() for log in info_logs)


class TestHealthCheckSustainedFailures:
    """Test health check during sustained failures"""

    @pytest.fixture
    def config(self):
        """Create test configuration"""
        return KrakenWSConfig(
            url="wss://ws.kraken.com",
            pairs=["BTC/USD"],
            redis_url="",
            max_retries=5
        )

    @pytest.fixture
    def client(self, config):
        """Create WebSocket client for testing"""
        return KrakenWebSocketClient(config)

    def test_is_healthy_returns_true_when_connected(self, client):
        """Test that is_healthy returns True when connected"""
        client._set_connection_state(ConnectionState.CONNECTED, "Test connection")
        assert client.is_healthy is True

    def test_is_healthy_returns_true_when_recently_disconnected(self, client):
        """Test that is_healthy returns True if disconnected < 2 min"""
        client._set_connection_state(ConnectionState.DISCONNECTED, "Just disconnected")
        assert client.is_healthy is True

    def test_is_healthy_returns_false_when_disconnected_over_2_min(self, client):
        """Test that is_healthy returns False if disconnected > 2 min"""
        # Manually set disconnection time to > 2 minutes ago
        client.connection_state = ConnectionState.DISCONNECTED
        client.connection_state_changed_at = time.time() - 130  # 130 seconds = 2 min 10 sec

        assert client.is_healthy is False

    def test_is_healthy_returns_false_when_max_retries_reached(self, client):
        """Test that is_healthy returns False when max retries reached"""
        client.reconnection_attempt = client.config.max_retries
        assert client.is_healthy is False

    def test_is_healthy_returns_true_during_reconnection(self, client):
        """Test that is_healthy returns True during reconnection"""
        client._set_connection_state(ConnectionState.RECONNECTING, "Attempting reconnection")
        assert client.is_healthy is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
