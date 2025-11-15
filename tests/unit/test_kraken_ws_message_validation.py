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


class TestSequenceGapPrometheusMetrics:
    """Test Prometheus metrics for sequence gaps per PRD-001 Section 1.3"""

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

    def test_message_gaps_counter_exists(self):
        """Test that Prometheus message gaps counter is defined"""
        from utils.kraken_ws import PROMETHEUS_AVAILABLE, KRAKEN_WS_MESSAGE_GAPS_TOTAL

        # Counter should be defined (may be None if prometheus not available)
        if PROMETHEUS_AVAILABLE:
            assert KRAKEN_WS_MESSAGE_GAPS_TOTAL is not None
            assert hasattr(KRAKEN_WS_MESSAGE_GAPS_TOTAL, 'labels')

    def test_gap_counter_increments_on_gap_detection(self, client):
        """Test that counter increments when sequence gap is detected"""
        from utils.kraken_ws import PROMETHEUS_AVAILABLE, KRAKEN_WS_MESSAGE_GAPS_TOTAL

        if not PROMETHEUS_AVAILABLE:
            pytest.skip("Prometheus not available")

        # Get initial counter value for 'book' channel
        initial_value = KRAKEN_WS_MESSAGE_GAPS_TOTAL.labels(channel='book')._value.get()

        # First message with sequence 100
        data1 = [123, {"s": 100}, "book", "BTC/USD"]
        client.extract_and_validate_sequence(data1, "book", "BTC/USD")

        # Second message with gap (sequence 105)
        data2 = [123, {"s": 105}, "book", "BTC/USD"]
        client.extract_and_validate_sequence(data2, "book", "BTC/USD")

        # Counter should have incremented by 1
        final_value = KRAKEN_WS_MESSAGE_GAPS_TOTAL.labels(channel='book')._value.get()
        assert final_value == initial_value + 1

    def test_gap_counter_not_incremented_without_gap(self, client):
        """Test that counter doesn't increment for sequential messages"""
        from utils.kraken_ws import PROMETHEUS_AVAILABLE, KRAKEN_WS_MESSAGE_GAPS_TOTAL

        if not PROMETHEUS_AVAILABLE:
            pytest.skip("Prometheus not available")

        # Get initial counter value
        initial_value = KRAKEN_WS_MESSAGE_GAPS_TOTAL.labels(channel='trade')._value.get()

        # Sequential messages (no gap)
        data1 = [123, {"s": 100}, "trade", "BTC/USD"]
        client.extract_and_validate_sequence(data1, "trade", "BTC/USD")

        data2 = [123, {"s": 101}, "trade", "BTC/USD"]
        client.extract_and_validate_sequence(data2, "trade", "BTC/USD")

        # Counter should NOT have incremented
        final_value = KRAKEN_WS_MESSAGE_GAPS_TOTAL.labels(channel='trade')._value.get()
        assert final_value == initial_value

    def test_gap_counter_has_channel_label(self):
        """Test that counter has channel label"""
        from utils.kraken_ws import PROMETHEUS_AVAILABLE, KRAKEN_WS_MESSAGE_GAPS_TOTAL

        if not PROMETHEUS_AVAILABLE:
            pytest.skip("Prometheus not available")

        # Should be able to create labels for different channels
        book_metric = KRAKEN_WS_MESSAGE_GAPS_TOTAL.labels(channel='book')
        trade_metric = KRAKEN_WS_MESSAGE_GAPS_TOTAL.labels(channel='trade')
        spread_metric = KRAKEN_WS_MESSAGE_GAPS_TOTAL.labels(channel='spread')

        assert book_metric is not None
        assert trade_metric is not None
        assert spread_metric is not None

    def test_different_channels_counted_separately(self, client):
        """Test that gaps in different channels are counted separately"""
        from utils.kraken_ws import PROMETHEUS_AVAILABLE, KRAKEN_WS_MESSAGE_GAPS_TOTAL

        if not PROMETHEUS_AVAILABLE:
            pytest.skip("Prometheus not available")

        # Get initial values for both channels
        book_initial = KRAKEN_WS_MESSAGE_GAPS_TOTAL.labels(channel='book')._value.get()
        trade_initial = KRAKEN_WS_MESSAGE_GAPS_TOTAL.labels(channel='trade')._value.get()

        # Create gap in book channel
        client.extract_and_validate_sequence([123, {"s": 100}, "book", "BTC/USD"], "book", "BTC/USD")
        client.extract_and_validate_sequence([123, {"s": 105}, "book", "BTC/USD"], "book", "BTC/USD")

        # Create gap in trade channel
        client.extract_and_validate_sequence([456, {"s": 200}, "trade", "BTC/USD"], "trade", "BTC/USD")
        client.extract_and_validate_sequence([456, {"s": 210}, "trade", "BTC/USD"], "trade", "BTC/USD")

        # Both channels should have incremented
        book_final = KRAKEN_WS_MESSAGE_GAPS_TOTAL.labels(channel='book')._value.get()
        trade_final = KRAKEN_WS_MESSAGE_GAPS_TOTAL.labels(channel='trade')._value.get()

        assert book_final == book_initial + 1
        assert trade_final == trade_initial + 1

    def test_metric_name_and_description(self):
        """Test that counter has correct name and description"""
        from utils.kraken_ws import PROMETHEUS_AVAILABLE, KRAKEN_WS_MESSAGE_GAPS_TOTAL

        if not PROMETHEUS_AVAILABLE:
            pytest.skip("Prometheus not available")

        # Check metric metadata (Prometheus auto-strips '_total' suffix from Counter names)
        assert KRAKEN_WS_MESSAGE_GAPS_TOTAL._name == 'kraken_ws_message_gaps'
        assert 'gap' in KRAKEN_WS_MESSAGE_GAPS_TOTAL._documentation.lower()


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


class TestTimestampValidation:
    """Test message timestamp validation per PRD-001 Section 1.3"""

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

    def test_recent_timestamp_accepted(self, client):
        """Test that recent timestamps are accepted"""
        import time

        # Message with current timestamp
        current_time = time.time()
        data = [123, {"timestamp": current_time}, "trade", "BTC/USD"]

        is_valid, reason = client.validate_message_timestamp(data, "trade")

        assert is_valid is True
        assert reason == ""

    def test_stale_message_rejected(self, client, caplog):
        """Test that messages > 5 seconds old are rejected"""
        import logging
        import time

        # Message with timestamp 10 seconds in the past
        old_time = time.time() - 10.0
        data = [123, {"timestamp": old_time}, "trade", "BTC/USD"]

        with caplog.at_level(logging.WARNING):
            is_valid, reason = client.validate_message_timestamp(data, "trade")

        assert is_valid is False
        assert "stale" in reason
        assert "10." in reason  # Should show ~10s age

        # Should log warning
        warning_logs = [record for record in caplog.records if record.levelname == "WARNING"]
        assert any("Rejecting stale message" in log.message for log in warning_logs)

    def test_future_message_rejected(self, client, caplog):
        """Test that messages > 5 seconds in the future are rejected"""
        import logging
        import time

        # Message with timestamp 10 seconds in the future
        future_time = time.time() + 10.0
        data = [123, {"timestamp": future_time}, "trade", "BTC/USD"]

        with caplog.at_level(logging.WARNING):
            is_valid, reason = client.validate_message_timestamp(data, "trade")

        assert is_valid is False
        assert "future" in reason
        assert "10." in reason  # Should show ~10s delta

        # Should log warning
        warning_logs = [record for record in caplog.records if record.levelname == "WARNING"]
        assert any("Rejecting future-dated message" in log.message for log in warning_logs)

    def test_timestamp_exactly_5_seconds_old_accepted(self, client):
        """Test boundary: exactly 5 seconds old should be accepted"""
        import time

        # Message exactly 5 seconds old
        boundary_time = time.time() - 5.0
        data = [123, {"timestamp": boundary_time}, "trade", "BTC/USD"]

        is_valid, reason = client.validate_message_timestamp(data, "trade")

        # Should be accepted (5.0 is not > 5.0)
        assert is_valid is True
        assert reason == ""

    def test_timestamp_slightly_over_5_seconds_rejected(self, client):
        """Test boundary: just over 5 seconds old should be rejected"""
        import time

        # Message 5.1 seconds old
        boundary_time = time.time() - 5.1
        data = [123, {"timestamp": boundary_time}, "trade", "BTC/USD"]

        is_valid, reason = client.validate_message_timestamp(data, "trade")

        # Should be rejected
        assert is_valid is False
        assert "stale" in reason

    def test_message_without_timestamp_accepted(self, client):
        """Test that messages without timestamps are accepted"""
        data = [123, {"data": "no_timestamp"}, "trade", "BTC/USD"]

        is_valid, reason = client.validate_message_timestamp(data, "trade")

        # Should be accepted (no timestamp to validate)
        assert is_valid is True
        assert reason == ""

    def test_timestamp_in_ts_field(self, client):
        """Test timestamp extraction from 'ts' field"""
        import time

        # Message with 'ts' field instead of 'timestamp'
        current_time = time.time()
        data = [123, {"ts": current_time}, "book", "BTC/USD"]

        is_valid, reason = client.validate_message_timestamp(data, "book")

        assert is_valid is True
        assert reason == ""

    def test_timestamp_in_time_field(self, client):
        """Test timestamp extraction from 'time' field"""
        import time

        # Message with 'time' field
        current_time = time.time()
        data = [123, {"time": current_time}, "spread", "BTC/USD"]

        is_valid, reason = client.validate_message_timestamp(data, "spread")

        assert is_valid is True
        assert reason == ""

    def test_timestamp_in_list_payload(self, client):
        """Test timestamp extraction from list payload"""
        import time

        current_time = time.time()
        data = [123, [{"timestamp": current_time}], "trade", "BTC/USD"]

        is_valid, reason = client.validate_message_timestamp(data, "trade")

        assert is_valid is True
        assert reason == ""

    def test_invalid_timestamp_format_accepted(self, client, caplog):
        """Test that invalid timestamp formats don't cause rejection"""
        import logging

        data = [123, {"timestamp": "not_a_number"}, "trade", "BTC/USD"]

        with caplog.at_level(logging.DEBUG):
            is_valid, reason = client.validate_message_timestamp(data, "trade")

        # Should be accepted (can't parse, so don't reject)
        assert is_valid is True
        assert reason == ""

        # Should log debug message
        debug_logs = [record for record in caplog.records if record.levelname == "DEBUG"]
        assert any("Could not parse timestamp" in log.message for log in debug_logs)

    def test_string_timestamp_converted(self, client):
        """Test that string timestamps are converted to float"""
        import time

        current_time = str(time.time())
        data = [123, {"timestamp": current_time}, "trade", "BTC/USD"]

        is_valid, reason = client.validate_message_timestamp(data, "trade")

        assert is_valid is True
        assert reason == ""


class TestStaleMessagePrometheusMetrics:
    """Test Prometheus metrics for stale messages per PRD-001 Section 1.3"""

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

    def test_stale_messages_counter_exists(self):
        """Test that Prometheus stale messages counter is defined"""
        from utils.kraken_ws import PROMETHEUS_AVAILABLE, KRAKEN_WS_STALE_MESSAGES_TOTAL

        if PROMETHEUS_AVAILABLE:
            assert KRAKEN_WS_STALE_MESSAGES_TOTAL is not None
            assert hasattr(KRAKEN_WS_STALE_MESSAGES_TOTAL, 'labels')

    def test_counter_increments_on_stale_message(self, client):
        """Test that counter increments when stale message is rejected"""
        from utils.kraken_ws import PROMETHEUS_AVAILABLE, KRAKEN_WS_STALE_MESSAGES_TOTAL
        import time

        if not PROMETHEUS_AVAILABLE:
            pytest.skip("Prometheus not available")

        # Get initial counter value
        initial_value = KRAKEN_WS_STALE_MESSAGES_TOTAL.labels(channel='trade', reason='stale')._value.get()

        # Stale message (10 seconds old)
        old_time = time.time() - 10.0
        data = [123, {"timestamp": old_time}, "trade", "BTC/USD"]
        client.validate_message_timestamp(data, "trade")

        # Counter should have incremented
        final_value = KRAKEN_WS_STALE_MESSAGES_TOTAL.labels(channel='trade', reason='stale')._value.get()
        assert final_value == initial_value + 1

    def test_counter_increments_on_future_message(self, client):
        """Test that counter increments when future message is rejected"""
        from utils.kraken_ws import PROMETHEUS_AVAILABLE, KRAKEN_WS_STALE_MESSAGES_TOTAL
        import time

        if not PROMETHEUS_AVAILABLE:
            pytest.skip("Prometheus not available")

        # Get initial counter value
        initial_value = KRAKEN_WS_STALE_MESSAGES_TOTAL.labels(channel='book', reason='future')._value.get()

        # Future message (10 seconds ahead)
        future_time = time.time() + 10.0
        data = [123, {"timestamp": future_time}, "book", "BTC/USD"]
        client.validate_message_timestamp(data, "book")

        # Counter should have incremented
        final_value = KRAKEN_WS_STALE_MESSAGES_TOTAL.labels(channel='book', reason='future')._value.get()
        assert final_value == initial_value + 1

    def test_counter_has_channel_and_reason_labels(self):
        """Test that counter has both channel and reason labels"""
        from utils.kraken_ws import PROMETHEUS_AVAILABLE, KRAKEN_WS_STALE_MESSAGES_TOTAL

        if not PROMETHEUS_AVAILABLE:
            pytest.skip("Prometheus not available")

        # Should be able to create labels for different channels and reasons
        metric1 = KRAKEN_WS_STALE_MESSAGES_TOTAL.labels(channel='trade', reason='stale')
        metric2 = KRAKEN_WS_STALE_MESSAGES_TOTAL.labels(channel='book', reason='future')

        assert metric1 is not None
        assert metric2 is not None

    def test_different_reasons_counted_separately(self, client):
        """Test that stale and future rejections are counted separately"""
        from utils.kraken_ws import PROMETHEUS_AVAILABLE, KRAKEN_WS_STALE_MESSAGES_TOTAL
        import time

        if not PROMETHEUS_AVAILABLE:
            pytest.skip("Prometheus not available")

        # Get initial values
        stale_initial = KRAKEN_WS_STALE_MESSAGES_TOTAL.labels(channel='trade', reason='stale')._value.get()
        future_initial = KRAKEN_WS_STALE_MESSAGES_TOTAL.labels(channel='trade', reason='future')._value.get()

        # Reject one stale and one future
        client.validate_message_timestamp([123, {"timestamp": time.time() - 10}, "trade", "BTC/USD"], "trade")
        client.validate_message_timestamp([123, {"timestamp": time.time() + 10}, "trade", "BTC/USD"], "trade")

        # Both should have incremented
        stale_final = KRAKEN_WS_STALE_MESSAGES_TOTAL.labels(channel='trade', reason='stale')._value.get()
        future_final = KRAKEN_WS_STALE_MESSAGES_TOTAL.labels(channel='trade', reason='future')._value.get()

        assert stale_final == stale_initial + 1
        assert future_final == future_initial + 1


class TestMessageDeduplication:
    """Test message deduplication cache (PRD-001 Section 1.3)"""

    @pytest.fixture
    def config(self):
        """Create test configuration"""
        return KrakenWSConfig(
            url="wss://ws.kraken.com",
            pairs=["BTC/USD", "ETH/USD"],
            redis_url=""
        )

    @pytest.fixture
    def client(self, config):
        """Create WebSocket client for testing"""
        return KrakenWebSocketClient(config)

    def test_dedup_cache_initialized(self, client):
        """Test that deduplication cache is initialized"""
        assert hasattr(client, 'dedup_cache')
        assert isinstance(client.dedup_cache, dict)
        assert len(client.dedup_cache) == 0  # Initially empty

    def test_generate_message_id_basic(self, client):
        """Test basic message ID generation"""
        data = [123, {"timestamp": 1234567890.0, "s": 100}, "trade", "BTC/USD"]
        msg_id = client.generate_message_id(data, "trade", "BTC/USD")

        assert msg_id != ""
        assert "trade" in msg_id
        assert "BTC/USD" in msg_id
        assert "1234567890.0" in msg_id
        assert "100" in msg_id

    def test_generate_message_id_without_timestamp(self, client):
        """Test message ID generation without timestamp"""
        data = [123, {"price": "50000"}, "ticker", "BTC/USD"]
        msg_id = client.generate_message_id(data, "ticker", "BTC/USD")

        assert msg_id != ""
        assert "ticker" in msg_id
        assert "BTC/USD" in msg_id

    def test_generate_message_id_with_ts_field(self, client):
        """Test message ID generation with 'ts' field instead of 'timestamp'"""
        data = [123, {"ts": 1234567890.0}, "spread", "ETH/USD"]
        msg_id = client.generate_message_id(data, "spread", "ETH/USD")

        assert msg_id != ""
        assert "1234567890.0" in msg_id

    def test_generate_message_id_consistent(self, client):
        """Test that same message generates same ID"""
        data = [123, {"timestamp": 1234567890.0, "s": 100}, "trade", "BTC/USD"]

        id1 = client.generate_message_id(data, "trade", "BTC/USD")
        id2 = client.generate_message_id(data, "trade", "BTC/USD")

        assert id1 == id2

    def test_generate_message_id_different_for_different_messages(self, client):
        """Test that different messages generate different IDs"""
        data1 = [123, {"timestamp": 1234567890.0, "s": 100}, "trade", "BTC/USD"]
        data2 = [123, {"timestamp": 1234567891.0, "s": 101}, "trade", "BTC/USD"]

        id1 = client.generate_message_id(data1, "trade", "BTC/USD")
        id2 = client.generate_message_id(data2, "trade", "BTC/USD")

        assert id1 != id2

    def test_check_duplicate_new_message(self, client):
        """Test that new messages are not flagged as duplicates"""
        data = [123, {"timestamp": 1234567890.0}, "trade", "BTC/USD"]

        is_duplicate = client.check_duplicate(data, "trade", "BTC/USD")

        assert is_duplicate is False

    def test_check_duplicate_detects_duplicate(self, client):
        """Test that duplicate messages are detected"""
        data = [123, {"timestamp": 1234567890.0, "s": 100}, "trade", "BTC/USD"]

        # First time - not duplicate
        is_dup1 = client.check_duplicate(data, "trade", "BTC/USD")
        assert is_dup1 is False

        # Second time - duplicate
        is_dup2 = client.check_duplicate(data, "trade", "BTC/USD")
        assert is_dup2 is True

    def test_check_duplicate_logs_warning(self, client, caplog):
        """Test that duplicate detection logs warning"""
        import logging

        data = [123, {"timestamp": 1234567890.0}, "trade", "BTC/USD"]

        # First message
        client.check_duplicate(data, "trade", "BTC/USD")

        # Second message (duplicate)
        with caplog.at_level(logging.WARNING):
            client.check_duplicate(data, "trade", "BTC/USD")

        warning_logs = [record for record in caplog.records if record.levelname == "WARNING"]
        assert len(warning_logs) > 0
        assert any("Duplicate message detected" in log.message for log in warning_logs)

    def test_dedup_cache_created_per_channel(self, client):
        """Test that dedup cache is created per channel:pair"""
        data = [123, {"timestamp": 1234567890.0}, "trade", "BTC/USD"]

        client.check_duplicate(data, "trade", "BTC/USD")

        # Cache should be created for this channel:pair
        assert "trade:BTC/USD" in client.dedup_cache
        assert len(client.dedup_cache["trade:BTC/USD"]) == 1

    def test_dedup_cache_different_channels_separate(self, client):
        """Test that different channels maintain separate caches"""
        data1 = [123, {"timestamp": 1234567890.0}, "trade", "BTC/USD"]
        data2 = [456, {"timestamp": 1234567890.0}, "spread", "BTC/USD"]

        client.check_duplicate(data1, "trade", "BTC/USD")
        client.check_duplicate(data2, "spread", "BTC/USD")

        # Should have separate caches
        assert "trade:BTC/USD" in client.dedup_cache
        assert "spread:BTC/USD" in client.dedup_cache
        assert len(client.dedup_cache) == 2

    def test_dedup_cache_different_pairs_separate(self, client):
        """Test that different pairs maintain separate caches"""
        data1 = [123, {"timestamp": 1234567890.0}, "trade", "BTC/USD"]
        data2 = [123, {"timestamp": 1234567890.0}, "trade", "ETH/USD"]

        client.check_duplicate(data1, "trade", "BTC/USD")
        client.check_duplicate(data2, "trade", "ETH/USD")

        # Should have separate caches
        assert "trade:BTC/USD" in client.dedup_cache
        assert "trade:ETH/USD" in client.dedup_cache
        assert len(client.dedup_cache) == 2

    def test_dedup_cache_max_size_100(self, client):
        """Test that dedup cache maintains max 100 entries per channel"""
        # Add 150 unique messages
        for i in range(150):
            data = [123, {"timestamp": float(i), "s": i}, "trade", "BTC/USD"]
            client.check_duplicate(data, "trade", "BTC/USD")

        # Cache should only have 100 entries (oldest 50 evicted)
        assert len(client.dedup_cache["trade:BTC/USD"]) == 100

    def test_dedup_cache_evicts_oldest_messages(self, client):
        """Test that oldest messages are evicted when cache is full"""
        # Add 101 unique messages
        for i in range(101):
            data = [123, {"timestamp": float(i)}, "trade", "BTC/USD"]
            client.check_duplicate(data, "trade", "BTC/USD")

        # First message should be evicted
        first_data = [123, {"timestamp": 0.0}, "trade", "BTC/USD"]
        first_id = client.generate_message_id(first_data, "trade", "BTC/USD")

        # First ID should NOT be in cache anymore
        assert first_id not in client.dedup_cache["trade:BTC/USD"]

        # Last message should still be in cache
        last_data = [123, {"timestamp": 100.0}, "trade", "BTC/USD"]
        last_id = client.generate_message_id(last_data, "trade", "BTC/USD")
        assert last_id in client.dedup_cache["trade:BTC/USD"]

    def test_dedup_gracefully_handles_invalid_data(self, client):
        """Test that dedup handles invalid data gracefully"""
        # Empty list
        is_dup = client.check_duplicate([], "trade", "BTC/USD")
        assert is_dup is False

        # Too short list
        is_dup = client.check_duplicate([123], "trade", "BTC/USD")
        assert is_dup is False


class TestDuplicatePrometheusMetrics:
    """Test Prometheus metrics for duplicate detection"""

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

    def test_duplicates_counter_exists(self):
        """Test that Prometheus duplicates counter is defined"""
        from utils.kraken_ws import PROMETHEUS_AVAILABLE, KRAKEN_WS_DUPLICATES_REJECTED_TOTAL

        if PROMETHEUS_AVAILABLE:
            assert KRAKEN_WS_DUPLICATES_REJECTED_TOTAL is not None
            assert hasattr(KRAKEN_WS_DUPLICATES_REJECTED_TOTAL, 'labels')

    def test_counter_increments_on_duplicate(self, client):
        """Test that counter increments when duplicate is detected"""
        from utils.kraken_ws import PROMETHEUS_AVAILABLE, KRAKEN_WS_DUPLICATES_REJECTED_TOTAL

        if not PROMETHEUS_AVAILABLE:
            pytest.skip("Prometheus not available")

        # Get initial counter value
        initial_value = KRAKEN_WS_DUPLICATES_REJECTED_TOTAL.labels(channel='trade')._value.get()

        # Send same message twice
        data = [123, {"timestamp": 1234567890.0}, "trade", "BTC/USD"]
        client.check_duplicate(data, "trade", "BTC/USD")  # First time
        client.check_duplicate(data, "trade", "BTC/USD")  # Duplicate

        # Counter should have incremented by 1
        final_value = KRAKEN_WS_DUPLICATES_REJECTED_TOTAL.labels(channel='trade')._value.get()
        assert final_value == initial_value + 1

    def test_counter_not_incremented_for_new_message(self, client):
        """Test that counter doesn't increment for new messages"""
        from utils.kraken_ws import PROMETHEUS_AVAILABLE, KRAKEN_WS_DUPLICATES_REJECTED_TOTAL

        if not PROMETHEUS_AVAILABLE:
            pytest.skip("Prometheus not available")

        # Get initial counter value
        initial_value = KRAKEN_WS_DUPLICATES_REJECTED_TOTAL.labels(channel='book')._value.get()

        # Send unique message
        data = [123, {"timestamp": 1234567890.0}, "book", "BTC/USD"]
        client.check_duplicate(data, "book", "BTC/USD")

        # Counter should NOT have incremented
        final_value = KRAKEN_WS_DUPLICATES_REJECTED_TOTAL.labels(channel='book')._value.get()
        assert final_value == initial_value

    def test_counter_has_channel_label(self):
        """Test that counter has channel label"""
        from utils.kraken_ws import PROMETHEUS_AVAILABLE, KRAKEN_WS_DUPLICATES_REJECTED_TOTAL

        if not PROMETHEUS_AVAILABLE:
            pytest.skip("Prometheus not available")

        # Should be able to create labels for different channels
        metric1 = KRAKEN_WS_DUPLICATES_REJECTED_TOTAL.labels(channel='trade')
        metric2 = KRAKEN_WS_DUPLICATES_REJECTED_TOTAL.labels(channel='book')

        assert metric1 is not None
        assert metric2 is not None

    def test_different_channels_counted_separately(self, client):
        """Test that duplicates for different channels are counted separately"""
        from utils.kraken_ws import PROMETHEUS_AVAILABLE, KRAKEN_WS_DUPLICATES_REJECTED_TOTAL

        if not PROMETHEUS_AVAILABLE:
            pytest.skip("Prometheus not available")

        # Get initial values
        trade_initial = KRAKEN_WS_DUPLICATES_REJECTED_TOTAL.labels(channel='trade')._value.get()
        spread_initial = KRAKEN_WS_DUPLICATES_REJECTED_TOTAL.labels(channel='spread')._value.get()

        # Create duplicates for different channels
        trade_data = [123, {"timestamp": 1234567890.0}, "trade", "BTC/USD"]
        client.check_duplicate(trade_data, "trade", "BTC/USD")
        client.check_duplicate(trade_data, "trade", "BTC/USD")  # Duplicate

        spread_data = [456, {"timestamp": 1234567890.0}, "spread", "BTC/USD"]
        client.check_duplicate(spread_data, "spread", "BTC/USD")
        client.check_duplicate(spread_data, "spread", "BTC/USD")  # Duplicate

        # Both should have incremented
        trade_final = KRAKEN_WS_DUPLICATES_REJECTED_TOTAL.labels(channel='trade')._value.get()
        spread_final = KRAKEN_WS_DUPLICATES_REJECTED_TOTAL.labels(channel='spread')._value.get()

        assert trade_final == trade_initial + 1
        assert spread_final == spread_initial + 1

    def test_metric_name_and_description(self):
        """Test that metric has correct name and description"""
        from utils.kraken_ws import PROMETHEUS_AVAILABLE, KRAKEN_WS_DUPLICATES_REJECTED_TOTAL

        if not PROMETHEUS_AVAILABLE:
            pytest.skip("Prometheus not available")

        # Check metric name (Prometheus auto-removes _total suffix from Counter names)
        assert KRAKEN_WS_DUPLICATES_REJECTED_TOTAL._name == 'kraken_ws_duplicates_rejected'
        assert KRAKEN_WS_DUPLICATES_REJECTED_TOTAL._documentation == 'Total duplicate messages rejected'


class TestDeduplicationIntegration:
    """Test deduplication integration with handle_message"""

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
    async def test_duplicate_message_rejected_in_handle_message(self, client, caplog):
        """Test that handle_message rejects duplicate messages"""
        import logging
        import json
        import time

        # Create a valid message
        message_data = [123, {"timestamp": time.time(), "s": 100, "price": "50000"}, "trade", "BTC/USD"]
        message = json.dumps(message_data)

        # Process first time (should succeed)
        with caplog.at_level(logging.DEBUG):
            await client.handle_message(message)

        # Check that it was processed (not rejected)
        initial_errors = client.stats["errors"]

        # Process second time (should be rejected as duplicate)
        await client.handle_message(message)

        # Error count should have incremented
        assert client.stats["errors"] == initial_errors + 1

        # Should have warning log about duplicate detection or debug log about rejection
        all_logs = [record for record in caplog.records]
        assert any("duplicate" in log.message.lower() for log in all_logs)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


