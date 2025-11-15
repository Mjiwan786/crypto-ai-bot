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


class TestSequenceNumberValidation:
    """Test sequence number extraction and validation per PRD-001 Section 1.3"""

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

    def test_last_sequence_dict_initialized(self, client):
        """Test that last_sequence dictionary is initialized"""
        assert hasattr(client, "last_sequence")
        assert isinstance(client.last_sequence, dict)
        assert len(client.last_sequence) == 0

    def test_sequence_extraction_from_dict_payload(self, client):
        """Test extracting sequence number from dict payload"""
        # Message with sequence in payload
        data = [
            123,  # channel_id
            {"s": 12345, "data": "test"},  # payload with sequence
            "book",
            "BTC/USD"
        ]

        client.extract_and_validate_sequence(data, "book", "BTC/USD")

        # Should have stored the sequence
        assert "book:BTC/USD" in client.last_sequence
        assert client.last_sequence["book:BTC/USD"] == 12345

    def test_sequence_extraction_with_sequence_field_name(self, client):
        """Test extracting sequence number with 'sequence' field name"""
        data = [
            123,
            {"sequence": 999, "data": "test"},
            "book",
            "BTC/USD"
        ]

        client.extract_and_validate_sequence(data, "book", "BTC/USD")

        assert "book:BTC/USD" in client.last_sequence
        assert client.last_sequence["book:BTC/USD"] == 999

    def test_no_sequence_number_does_not_store(self, client):
        """Test that messages without sequence numbers don't update tracking"""
        data = [
            123,
            {"data": "test"},  # No sequence field
            "trade",
            "BTC/USD"
        ]

        client.extract_and_validate_sequence(data, "trade", "BTC/USD")

        # Should not have stored anything
        assert "trade:BTC/USD" not in client.last_sequence

    def test_list_payload_without_sequence(self, client):
        """Test that list payloads (without sequence) don't cause errors"""
        data = [
            123,
            [{"price": "50000", "volume": "0.1"}],  # List payload
            "trade",
            "BTC/USD"
        ]

        # Should not raise exception
        client.extract_and_validate_sequence(data, "trade", "BTC/USD")

        assert "trade:BTC/USD" not in client.last_sequence

    def test_sequence_gap_detected_and_logged(self, client, caplog):
        """Test that sequence gaps are detected and logged"""
        import logging

        # First message with sequence 100
        data1 = [123, {"s": 100}, "book", "BTC/USD"]
        client.extract_and_validate_sequence(data1, "book", "BTC/USD")

        # Second message with sequence 105 (gap of 4)
        data2 = [123, {"s": 105}, "book", "BTC/USD"]

        with caplog.at_level(logging.WARNING):
            client.extract_and_validate_sequence(data2, "book", "BTC/USD")

        # Should log a warning about the gap
        warning_logs = [record for record in caplog.records if record.levelname == "WARNING"]
        assert len(warning_logs) > 0
        assert any("Sequence gap detected" in log.message for log in warning_logs)
        assert any("expected 101, got 105" in log.message for log in warning_logs)
        assert any("gap: 5" in log.message for log in warning_logs)  # gap = 105 - 100 = 5

    def test_no_gap_logged_for_sequential_messages(self, client, caplog):
        """Test that sequential messages don't log gaps"""
        import logging

        # Message with sequence 100
        data1 = [123, {"s": 100}, "book", "BTC/USD"]
        client.extract_and_validate_sequence(data1, "book", "BTC/USD")

        # Message with sequence 101 (no gap)
        data2 = [123, {"s": 101}, "book", "BTC/USD"]

        with caplog.at_level(logging.WARNING):
            client.extract_and_validate_sequence(data2, "book", "BTC/USD")

        # Should NOT log a warning
        warning_logs = [record for record in caplog.records if record.levelname == "WARNING"]
        gap_warnings = [log for log in warning_logs if "Sequence gap" in log.message]
        assert len(gap_warnings) == 0

    def test_different_channels_tracked_separately(self, client):
        """Test that different channels maintain separate sequence tracking"""
        # Book channel
        data_book = [123, {"s": 100}, "book", "BTC/USD"]
        client.extract_and_validate_sequence(data_book, "book", "BTC/USD")

        # Trade channel (different channel, same pair)
        data_trade = [456, {"s": 50}, "trade", "BTC/USD"]
        client.extract_and_validate_sequence(data_trade, "trade", "BTC/USD")

        # Both should be tracked separately
        assert "book:BTC/USD" in client.last_sequence
        assert "trade:BTC/USD" in client.last_sequence
        assert client.last_sequence["book:BTC/USD"] == 100
        assert client.last_sequence["trade:BTC/USD"] == 50

    def test_different_pairs_tracked_separately(self, client):
        """Test that different pairs maintain separate sequence tracking"""
        # BTC/USD
        data_btc = [123, {"s": 100}, "book", "BTC/USD"]
        client.extract_and_validate_sequence(data_btc, "book", "BTC/USD")

        # ETH/USD
        data_eth = [456, {"s": 200}, "book", "ETH/USD"]
        client.extract_and_validate_sequence(data_eth, "book", "ETH/USD")

        # Both should be tracked separately
        assert client.last_sequence["book:BTC/USD"] == 100
        assert client.last_sequence["book:ETH/USD"] == 200

    def test_invalid_sequence_format_logged(self, client, caplog):
        """Test that invalid sequence formats are logged"""
        import logging

        data = [123, {"s": "not_a_number"}, "book", "BTC/USD"]

        with caplog.at_level(logging.WARNING):
            client.extract_and_validate_sequence(data, "book", "BTC/USD")

        # Should log warning about invalid format
        warning_logs = [record for record in caplog.records if record.levelname == "WARNING"]
        assert any("Invalid sequence number format" in log.message for log in warning_logs)

    def test_sequence_update_after_gap(self, client):
        """Test that sequence is updated correctly even after a gap"""
        # First message
        data1 = [123, {"s": 100}, "book", "BTC/USD"]
        client.extract_and_validate_sequence(data1, "book", "BTC/USD")

        # Message with gap
        data2 = [123, {"s": 105}, "book", "BTC/USD"]
        client.extract_and_validate_sequence(data2, "book", "BTC/USD")

        # Sequence should be updated to 105
        assert client.last_sequence["book:BTC/USD"] == 105

        # Next sequential message should not trigger gap
        data3 = [123, {"s": 106}, "book", "BTC/USD"]
        client.extract_and_validate_sequence(data3, "book", "BTC/USD")

        assert client.last_sequence["book:BTC/USD"] == 106


@pytest.mark.asyncio
class TestSequenceValidationIntegration:
    """Test sequence validation integration with handle_message"""

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

    async def test_sequence_extracted_during_message_handling(self, client):
        """Test that sequence extraction happens during message handling"""
        import json

        # Mock book handler
        client.handle_book_data = AsyncMock()

        # Message with sequence number
        message = json.dumps([
            123,
            {"s": 999, "as": [], "bs": []},
            "book-10",
            "BTC/USD"
        ])

        await client.handle_message(message)

        # Sequence should have been extracted
        assert "book-10:BTC/USD" in client.last_sequence
        assert client.last_sequence["book-10:BTC/USD"] == 999


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

