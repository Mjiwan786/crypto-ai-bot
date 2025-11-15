"""
Unit tests for Kraken WebSocket message validation (PRD-001 Section 1.3)

Tests verify:
- Message schema validation for required fields (channel, pair, data)
- Type validation for each field
- Proper error messages for invalid data
- Logging at WARNING level for schema failures
"""

import pytest
import logging
from unittest.mock import AsyncMock
from utils.kraken_ws import KrakenWebSocketClient, KrakenWSConfig


class TestMessageSchemaValidation:
    """Test message schema validation per PRD-001 Section 1.3"""

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
        """Create WebSocket client"""
        return KrakenWebSocketClient(config)

    def test_valid_dict_message_passes(self, client):
        """Test that dict messages (events) pass validation"""
        message = {"event": "systemStatus", "status": "online"}

        is_valid, error_msg = client.validate_message_schema(message)

        assert is_valid is True
        assert error_msg == ""

    def test_valid_list_message_passes(self, client):
        """Test that valid list messages pass validation"""
        # Valid trade message: [channel_id, payload, channel, pair]
        message = [
            123,  # channel_id (int)
            [{"price": "50000.00", "volume": "0.1"}],  # payload (list)
            "trade",  # channel (str)
            "BTC/USD"  # pair (str)
        ]

        is_valid, error_msg = client.validate_message_schema(message)

        assert is_valid is True
        assert error_msg == ""

    def test_invalid_message_type_fails(self, client):
        """Test that non-list/dict messages fail validation"""
        message = "invalid string message"

        is_valid, error_msg = client.validate_message_schema(message)

        assert is_valid is False
        assert "Invalid message type" in error_msg
        assert "expected list or dict" in error_msg

    def test_short_list_message_fails(self, client):
        """Test that messages with < 4 elements fail validation"""
        message = [123, {"data": "test"}, "trade"]  # Only 3 elements

        is_valid, error_msg = client.validate_message_schema(message)

        assert is_valid is False
        assert "Invalid message length" in error_msg
        assert "expected >= 4, got 3" in error_msg

    def test_invalid_channel_id_type_fails(self, client):
        """Test that non-numeric channel_id fails validation"""
        message = [
            "not_a_number",  # Invalid channel_id (should be int)
            [{"data": "test"}],
            "trade",
            "BTC/USD"
        ]

        is_valid, error_msg = client.validate_message_schema(message)

        assert is_valid is False
        assert "Invalid channel_id type" in error_msg
        assert "expected int" in error_msg

    def test_invalid_payload_type_fails(self, client):
        """Test that non-dict/list payload fails validation"""
        message = [
            123,
            "invalid_payload",  # Invalid payload (should be dict or list)
            "trade",
            "BTC/USD"
        ]

        is_valid, error_msg = client.validate_message_schema(message)

        assert is_valid is False
        assert "Invalid payload type" in error_msg
        assert "expected dict or list" in error_msg

    def test_invalid_channel_type_fails(self, client):
        """Test that non-string channel fails validation"""
        message = [
            123,
            [{"data": "test"}],
            12345,  # Invalid channel (should be str)
            "BTC/USD"
        ]

        is_valid, error_msg = client.validate_message_schema(message)

        assert is_valid is False
        assert "Invalid channel type" in error_msg
        assert "expected str" in error_msg

    def test_invalid_pair_type_fails(self, client):
        """Test that non-string pair fails validation"""
        message = [
            123,
            [{"data": "test"}],
            "trade",
            999  # Invalid pair (should be str)
        ]

        is_valid, error_msg = client.validate_message_schema(message)

        assert is_valid is False
        assert "Invalid pair type" in error_msg
        assert "expected str" in error_msg

    def test_valid_dict_payload_passes(self, client):
        """Test that dict payload (instead of list) passes validation"""
        message = [
            123,
            {"bid": "50000", "ask": "50001"},  # Dict payload is valid
            "spread",
            "BTC/USD"
        ]

        is_valid, error_msg = client.validate_message_schema(message)

        assert is_valid is True
        assert error_msg == ""

    def test_float_channel_id_passes(self, client):
        """Test that float channel_id passes validation"""
        message = [
            123.0,  # Float channel_id is acceptable
            [{"data": "test"}],
            "trade",
            "BTC/USD"
        ]

        is_valid, error_msg = client.validate_message_schema(message)

        assert is_valid is True
        assert error_msg == ""


@pytest.mark.asyncio
class TestMessageValidationIntegration:
    """Test message validation integration with handle_message"""

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
        """Create WebSocket client"""
        return KrakenWebSocketClient(config)

    async def test_invalid_message_logged_as_warning(self, client, caplog):
        """Test that invalid messages are logged at WARNING level"""
        import json

        # Invalid message (too short)
        invalid_message = json.dumps([123, {"data": "test"}, "trade"])

        with caplog.at_level(logging.WARNING):
            await client.handle_message(invalid_message)

        # Check for warning log
        warning_logs = [record for record in caplog.records if record.levelname == "WARNING"]
        assert len(warning_logs) > 0
        assert any("Invalid message schema" in log.message for log in warning_logs)

    async def test_invalid_message_increments_error_count(self, client):
        """Test that invalid messages increment error counter"""
        import json

        initial_errors = client.stats["errors"]

        # Invalid message
        invalid_message = json.dumps([123, "invalid_payload", "trade", "BTC/USD"])

        await client.handle_message(invalid_message)

        # Error count should increase
        assert client.stats["errors"] == initial_errors + 1

    async def test_valid_message_not_rejected(self, client):
        """Test that valid messages are not rejected by validation"""
        import json

        # Mock handler to track if message was processed
        client.handle_trade_data = AsyncMock()

        # Valid trade message
        valid_message = json.dumps([
            123,
            [{"price": "50000", "volume": "0.1"}],
            "trade",
            "BTC/USD"
        ])

        await client.handle_message(valid_message)

        # Handler should have been called (message passed validation)
        client.handle_trade_data.assert_called_once()

    async def test_dict_message_bypasses_validation(self, client):
        """Test that dict messages (events) bypass list validation"""
        import json

        initial_errors = client.stats["errors"]

        # Valid event message
        event_message = json.dumps({"event": "heartbeat"})

        await client.handle_message(event_message)

        # Should not increment errors
        assert client.stats["errors"] == initial_errors


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
