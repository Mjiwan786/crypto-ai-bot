"""
Unit tests for Kraken WebSocket error handling (PRD-001 Section 1.4)

Tests verify:
- All WebSocket operations wrapped in try/except
- Connection errors logged at ERROR level with exception details
- Message parsing errors logged at WARNING level with raw message data
- Prometheus counter kraken_ws_errors_total{error_type} emitted for all error types
"""

import pytest
import asyncio
import json
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from utils.kraken_ws import KrakenWebSocketClient, KrakenWSConfig


class TestErrorLogging:
    """Test error logging at appropriate levels"""

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
    async def test_json_decode_error_logged_at_warning(self, client, caplog):
        """Test that JSON parsing errors are logged at WARNING level"""
        import logging

        # Invalid JSON message
        invalid_message = "{invalid json"

        with caplog.at_level(logging.WARNING):
            await client.handle_message(invalid_message)

        # Should have WARNING log for parsing error
        warning_logs = [record for record in caplog.records if record.levelname == "WARNING"]
        assert len(warning_logs) > 0
        assert any("parsing error" in log.message.lower() for log in warning_logs)

    @pytest.mark.asyncio
    async def test_json_decode_error_includes_raw_message(self, client, caplog):
        """Test that parsing errors include raw message data at DEBUG level"""
        import logging

        invalid_message = "{invalid json message}"

        with caplog.at_level(logging.DEBUG):
            await client.handle_message(invalid_message)

        # Should have DEBUG log with raw message
        debug_logs = [record for record in caplog.records if record.levelname == "DEBUG"]
        assert any("raw message" in log.message.lower() for log in debug_logs)

    @pytest.mark.asyncio
    async def test_connection_error_logged_at_error_level(self, client, caplog):
        """Test that connection errors are logged at ERROR level"""
        import logging

        # Mock websockets.connect to raise exception
        with patch('websockets.connect', side_effect=Exception("Connection failed")):
            with caplog.at_level(logging.ERROR):
                try:
                    await client.connect_once()
                except:
                    pass

        # Should have ERROR log for connection error
        error_logs = [record for record in caplog.records if record.levelname == "ERROR"]
        assert len(error_logs) > 0
        assert any("connection error" in log.message.lower() for log in error_logs)

    @pytest.mark.asyncio
    async def test_handler_error_logged_at_error_level(self, client, caplog):
        """Test that handler errors are logged at ERROR level"""
        import logging

        # Create message that will cause handler error
        message_data = [123, {"bad": "data"}, "trade", "BTC/USD"]
        message = json.dumps(message_data)

        # Mock handler to raise exception
        async def failing_handler(*args, **kwargs):
            raise Exception("Handler failed")

        client.handle_trade_data = failing_handler

        with caplog.at_level(logging.ERROR):
            await client.handle_message(message)

        # Should have ERROR log for handler error
        error_logs = [record for record in caplog.records if record.levelname == "ERROR"]
        assert len(error_logs) > 0
        assert any("handler error" in log.message.lower() for log in error_logs)


class TestPrometheusErrorCounter:
    """Test Prometheus kraken_ws_errors_total counter"""

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

    def test_errors_counter_exists(self):
        """Test that Prometheus errors counter is defined"""
        from utils.kraken_ws import PROMETHEUS_AVAILABLE, KRAKEN_WS_ERRORS_TOTAL

        if PROMETHEUS_AVAILABLE:
            assert KRAKEN_WS_ERRORS_TOTAL is not None
            assert hasattr(KRAKEN_WS_ERRORS_TOTAL, 'labels')

    @pytest.mark.asyncio
    async def test_json_decode_error_increments_counter(self, client):
        """Test that JSON decode errors increment counter"""
        from utils.kraken_ws import PROMETHEUS_AVAILABLE, KRAKEN_WS_ERRORS_TOTAL

        if not PROMETHEUS_AVAILABLE:
            pytest.skip("Prometheus not available")

        # Get initial counter value
        initial_value = KRAKEN_WS_ERRORS_TOTAL.labels(error_type='json_decode')._value.get()

        # Send invalid JSON
        await client.handle_message("{invalid json")

        # Counter should have incremented
        final_value = KRAKEN_WS_ERRORS_TOTAL.labels(error_type='json_decode')._value.get()
        assert final_value == initial_value + 1

    @pytest.mark.asyncio
    async def test_handler_error_increments_counter(self, client):
        """Test that handler errors increment counter"""
        from utils.kraken_ws import PROMETHEUS_AVAILABLE, KRAKEN_WS_ERRORS_TOTAL

        if not PROMETHEUS_AVAILABLE:
            pytest.skip("Prometheus not available")

        # Get initial counter value
        initial_value = KRAKEN_WS_ERRORS_TOTAL.labels(error_type='handler_error')._value.get()

        # Create message that will cause handler error
        message_data = [123, {"bad": "data"}, "trade", "BTC/USD"]
        message = json.dumps(message_data)

        # Mock handler to raise exception
        async def failing_handler(*args, **kwargs):
            raise Exception("Handler failed")

        client.handle_trade_data = failing_handler

        await client.handle_message(message)

        # Counter should have incremented
        final_value = KRAKEN_WS_ERRORS_TOTAL.labels(error_type='handler_error')._value.get()
        assert final_value == initial_value + 1

    @pytest.mark.asyncio
    async def test_connection_error_increments_counter(self, client):
        """Test that connection errors increment counter"""
        from utils.kraken_ws import PROMETHEUS_AVAILABLE, KRAKEN_WS_ERRORS_TOTAL

        if not PROMETHEUS_AVAILABLE:
            pytest.skip("Prometheus not available")

        # Get initial counter value
        initial_value = KRAKEN_WS_ERRORS_TOTAL.labels(error_type='connection')._value.get()

        # Mock websockets.connect to raise exception
        with patch('websockets.connect', side_effect=Exception("Connection failed")):
            try:
                await client.connect_once()
            except:
                pass

        # Counter should have incremented
        final_value = KRAKEN_WS_ERRORS_TOTAL.labels(error_type='connection')._value.get()
        assert final_value == initial_value + 1

    def test_counter_has_error_type_label(self):
        """Test that counter has error_type label"""
        from utils.kraken_ws import PROMETHEUS_AVAILABLE, KRAKEN_WS_ERRORS_TOTAL

        if not PROMETHEUS_AVAILABLE:
            pytest.skip("Prometheus not available")

        # Should be able to create labels for different error types
        metric1 = KRAKEN_WS_ERRORS_TOTAL.labels(error_type='json_decode')
        metric2 = KRAKEN_WS_ERRORS_TOTAL.labels(error_type='handler_error')
        metric3 = KRAKEN_WS_ERRORS_TOTAL.labels(error_type='connection')

        assert metric1 is not None
        assert metric2 is not None
        assert metric3 is not None

    @pytest.mark.asyncio
    async def test_different_error_types_counted_separately(self, client):
        """Test that different error types are counted separately"""
        from utils.kraken_ws import PROMETHEUS_AVAILABLE, KRAKEN_WS_ERRORS_TOTAL

        if not PROMETHEUS_AVAILABLE:
            pytest.skip("Prometheus not available")

        # Get initial values for different error types
        json_initial = KRAKEN_WS_ERRORS_TOTAL.labels(error_type='json_decode')._value.get()
        handler_initial = KRAKEN_WS_ERRORS_TOTAL.labels(error_type='handler_error')._value.get()

        # Cause JSON decode error
        await client.handle_message("{invalid")

        # Cause handler error
        message_data = [123, {"data": "test"}, "trade", "BTC/USD"]
        async def failing_handler(*args, **kwargs):
            raise Exception("fail")
        client.handle_trade_data = failing_handler
        await client.handle_message(json.dumps(message_data))

        # Both should have incremented
        json_final = KRAKEN_WS_ERRORS_TOTAL.labels(error_type='json_decode')._value.get()
        handler_final = KRAKEN_WS_ERRORS_TOTAL.labels(error_type='handler_error')._value.get()

        assert json_final == json_initial + 1
        assert handler_final == handler_initial + 1

    def test_metric_name_and_description(self):
        """Test that metric has correct name and description"""
        from utils.kraken_ws import PROMETHEUS_AVAILABLE, KRAKEN_WS_ERRORS_TOTAL

        if not PROMETHEUS_AVAILABLE:
            pytest.skip("Prometheus not available")

        # Check metric name (Prometheus auto-removes _total suffix)
        assert KRAKEN_WS_ERRORS_TOTAL._name == 'kraken_ws_errors'
        assert KRAKEN_WS_ERRORS_TOTAL._documentation == 'Total WebSocket errors by type'


class TestErrorRecovery:
    """Test that client continues processing after errors"""

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
    async def test_client_continues_after_json_decode_error(self, client):
        """Test that client continues processing after JSON decode error"""
        # Send invalid message
        initial_errors = client.stats["errors"]
        await client.handle_message("{invalid}")

        # Error count should increment
        assert client.stats["errors"] == initial_errors + 1

        # Client should still be able to process valid messages
        valid_message = json.dumps({"event": "heartbeat"})
        await client.handle_message(valid_message)

        # Should still work (no exception raised)
        assert client.stats["messages_received"] > 0

    @pytest.mark.asyncio
    async def test_client_continues_after_handler_error(self, client, caplog):
        """Test that client continues processing after handler error"""
        import logging

        # Create failing handler
        async def failing_handler(*args, **kwargs):
            raise Exception("Handler failed")

        client.handle_trade_data = failing_handler

        # Send message that will cause handler error
        message_data = [123, {"data": "test"}, "trade", "BTC/USD"]

        with caplog.at_level(logging.ERROR):
            await client.handle_message(json.dumps(message_data))

        # Should continue (not raise exception to caller)
        # Error should be logged
        error_logs = [record for record in caplog.records if record.levelname == "ERROR"]
        assert len(error_logs) > 0
        assert any("handler error" in log.message.lower() for log in error_logs)

        # Client should still be functional
        valid_message = json.dumps({"event": "heartbeat"})
        await client.handle_message(valid_message)
        assert client.stats["messages_received"] > 0

    @pytest.mark.asyncio
    async def test_error_count_increments_correctly(self, client):
        """Test that error count increments for each error"""
        initial_errors = client.stats["errors"]

        # Cause multiple errors
        await client.handle_message("{invalid1}")
        await client.handle_message("{invalid2}")
        await client.handle_message("{invalid3}")

        # Should have 3 new errors
        assert client.stats["errors"] == initial_errors + 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
