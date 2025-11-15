"""
Tests for KrakenWSClient data persistence features (PRD-001 Section 1.6)

Tests cover:
- Ticker data stored in Redis with 60s TTL
- Spread data stored in Redis with 60s TTL
- Book snapshot stored in Redis with 60s TTL
- Trade events published to Redis stream with MAXLEN 1000
- Timestamp and sequence number included in all persisted data
"""

import pytest
import asyncio
import time
import json
from unittest.mock import Mock, patch, AsyncMock, MagicMock

from utils.kraken_ws import KrakenWebSocketClient, KrakenWSConfig


@pytest.fixture
def config():
    """Create test configuration"""
    return KrakenWSConfig(
        url="wss://ws.kraken.com",
        pairs=["BTC/USD"],
        channels=["ticker", "trade", "spread", "book"],
        enable_latency_tracking=True
    )


@pytest.fixture
def client(config):
    """Create test client"""
    return KrakenWebSocketClient(config)


@pytest.fixture
def mock_redis():
    """Create mock Redis connection"""
    redis_mock = AsyncMock()
    redis_mock.setex = AsyncMock()
    redis_mock.xadd = AsyncMock()
    return redis_mock


class TestTickerPersistence:
    """Test ticker data persistence (PRD-001 Section 1.6 Item 1)"""

    @pytest.mark.asyncio
    async def test_ticker_stored_in_redis_with_ttl(self, client, mock_redis):
        """Test that ticker data is stored in Redis with 60s TTL"""
        # Mock Redis connection
        client.redis_manager.redis_client = True  # Enable Redis
        with patch.object(client.redis_manager, 'get_connection') as mock_conn:
            mock_conn.return_value.__aenter__.return_value = mock_redis

            # Create test ticker data
            ticker_data = {
                "a": ["50000.00", "1", "1.000"],
                "b": ["49990.00", "2", "2.000"],
                "c": ["49995.00", "0.5"],
                "v": ["100.5", "250.3"],
                "p": ["49950.00", "49900.00"],
                "t": [150, 300],
                "l": ["49800.00", "49700.00"],
                "h": ["50100.00", "50200.00"],
                "o": ["49900.00", "49850.00"]
            }

            # Handle ticker data
            await client.handle_ticker_data(123, ticker_data, "ticker", "BTC/USD")

            # Verify Redis setex was called with correct parameters
            mock_redis.setex.assert_called_once()
            call_args = mock_redis.setex.call_args
            assert call_args[0][0] == "kraken:ticker:BTC-USD"  # Redis key
            assert call_args[0][1] == 60  # TTL
            # Verify JSON data
            stored_data = json.loads(call_args[0][2])
            assert stored_data["pair"] == "BTC/USD"
            assert "timestamp" in stored_data
            assert "sequence" in stored_data

    @pytest.mark.asyncio
    async def test_ticker_includes_timestamp_and_sequence(self, client, mock_redis):
        """Test that ticker data includes timestamp and sequence number"""
        client.redis_manager.redis_client = True  # Enable Redis
        with patch.object(client.redis_manager, 'get_connection') as mock_conn:
            mock_conn.return_value.__aenter__.return_value = mock_redis

            ticker_data = {
                "a": ["50000.00", "1", "1.000"],
                "b": ["49990.00", "2", "2.000"],
                "c": ["49995.00", "0.5"]
            }

            await client.handle_ticker_data(456, ticker_data, "ticker", "BTC/USD")

            # Extract stored data
            call_args = mock_redis.setex.call_args
            stored_data = json.loads(call_args[0][2])

            # Verify timestamp and sequence
            assert "timestamp" in stored_data
            assert stored_data["timestamp"] > 0
            assert "sequence" in stored_data
            assert stored_data["sequence"] == 456


class TestSpreadPersistence:
    """Test spread data persistence (PRD-001 Section 1.6 Item 2)"""

    @pytest.mark.asyncio
    async def test_spread_stored_in_redis_with_ttl(self, client, mock_redis):
        """Test that spread data is stored in Redis with 60s TTL"""
        client.redis_manager.redis_client = True  # Enable Redis
        with patch.object(client.redis_manager, 'get_connection') as mock_conn:
            mock_conn.return_value.__aenter__.return_value = mock_redis

            spread_data = ["49990.00", "50000.00", "1234567890.123", "10.5", "8.3"]

            await client.handle_spread_data(123, spread_data, "spread", "BTC/USD")

            # Verify Redis setex was called for key storage
            assert mock_redis.setex.call_count >= 1
            setex_call = mock_redis.setex.call_args_list[0]
            assert setex_call[0][0] == "kraken:spread:BTC-USD"
            assert setex_call[0][1] == 60

            # Verify stored data
            stored_data = json.loads(setex_call[0][2])
            assert stored_data["pair"] == "BTC/USD"
            assert "timestamp" in stored_data
            assert "sequence" in stored_data

    @pytest.mark.asyncio
    async def test_spread_includes_timestamp_and_sequence(self, client, mock_redis):
        """Test that spread data includes timestamp and sequence number"""
        client.redis_manager.redis_client = True  # Enable Redis
        with patch.object(client.redis_manager, 'get_connection') as mock_conn:
            mock_conn.return_value.__aenter__.return_value = mock_redis

            spread_data = ["49990.00", "50000.00", "1234567890.123", "10.5", "8.3"]

            await client.handle_spread_data(789, spread_data, "spread", "BTC/USD")

            setex_call = mock_redis.setex.call_args_list[0]
            stored_data = json.loads(setex_call[0][2])

            assert stored_data["sequence"] == 789
            assert "timestamp" in stored_data or "received_at" in stored_data


class TestBookPersistence:
    """Test book snapshot persistence (PRD-001 Section 1.6 Item 3)"""

    @pytest.mark.asyncio
    async def test_book_stored_in_redis_with_ttl(self, client, mock_redis):
        """Test that book snapshot is stored in Redis with 60s TTL"""
        client.redis_manager.redis_client = True  # Enable Redis
        with patch.object(client.redis_manager, 'get_connection') as mock_conn:
            mock_conn.return_value.__aenter__.return_value = mock_redis

            book_data = {
                "bs": [["49990.00", "1.5", "1234567890.123"]],
                "as": [["50000.00", "2.0", "1234567890.124"]],
                "c": "1234567890"
            }

            await client.handle_book_data(123, book_data, "book", "BTC/USD")

            # Verify Redis setex was called
            assert mock_redis.setex.call_count >= 1
            setex_call = mock_redis.setex.call_args_list[0]
            assert setex_call[0][0] == "kraken:book:BTC-USD"
            assert setex_call[0][1] == 60

            # Verify stored data
            stored_data = json.loads(setex_call[0][2])
            assert stored_data["pair"] == "BTC/USD"
            assert "bids" in stored_data
            assert "asks" in stored_data
            assert "sequence" in stored_data

    @pytest.mark.asyncio
    async def test_book_includes_timestamp_and_sequence(self, client, mock_redis):
        """Test that book data includes timestamp and sequence number"""
        client.redis_manager.redis_client = True  # Enable Redis
        with patch.object(client.redis_manager, 'get_connection') as mock_conn:
            mock_conn.return_value.__aenter__.return_value = mock_redis

            book_data = {
                "bs": [["49990.00", "1.5", "1234567890.123"]],
                "as": [["50000.00", "2.0", "1234567890.124"]],
                "c": "1234567890"
            }

            await client.handle_book_data(321, book_data, "book", "BTC/USD")

            setex_call = mock_redis.setex.call_args_list[0]
            stored_data = json.loads(setex_call[0][2])

            assert stored_data["sequence"] == 321
            assert "received_at" in stored_data


class TestTradeStreamPersistence:
    """Test trade stream persistence (PRD-001 Section 1.6 Item 4)"""

    @pytest.mark.asyncio
    async def test_trade_published_to_stream_with_maxlen_1000(self, client, mock_redis):
        """Test that trade events are published to Redis stream with MAXLEN 1000"""
        client.redis_manager.redis_client = True  # Enable Redis
        with patch.object(client.redis_manager, 'get_connection') as mock_conn:
            mock_conn.return_value.__aenter__.return_value = mock_redis

            trade_data = [
                ["50000.00", "1.5", "1234567890.123", "b", "m", ""]
            ]

            await client.handle_trade_data(123, trade_data, "trade", "BTC/USD")

            # Verify Redis xadd was called with MAXLEN 1000
            mock_redis.xadd.assert_called_once()
            call_args = mock_redis.xadd.call_args
            assert call_args[1]['maxlen'] == 1000

    @pytest.mark.asyncio
    async def test_trade_stream_includes_timestamp_and_sequence(self, client, mock_redis):
        """Test that trade stream data includes timestamp and sequence number"""
        client.redis_manager.redis_client = True  # Enable Redis
        with patch.object(client.redis_manager, 'get_connection') as mock_conn:
            mock_conn.return_value.__aenter__.return_value = mock_redis

            trade_data = [
                ["50000.00", "1.5", "1234567890.123", "b", "m", ""]
            ]

            await client.handle_trade_data(999, trade_data, "trade", "BTC/USD")

            call_args = mock_redis.xadd.call_args
            stream_data = call_args[0][1]

            assert "timestamp" in stream_data
            assert "sequence" in stream_data
            assert stream_data["sequence"] == "999"


class TestSequenceNumbers:
    """Test sequence number tracking (PRD-001 Section 1.6 Item 5)"""

    @pytest.mark.asyncio
    async def test_all_persist_operations_include_sequence(self, client, mock_redis):
        """Test that all persisted data includes sequence numbers"""
        client.redis_manager.redis_client = True  # Enable Redis
        with patch.object(client.redis_manager, 'get_connection') as mock_conn:
            mock_conn.return_value.__aenter__.return_value = mock_redis

            # Test ticker
            ticker_data = {"a": ["50000.00", "1", "1.000"], "b": ["49990.00", "2", "2.000"], "c": ["49995.00", "0.5"]}
            await client.handle_ticker_data(100, ticker_data, "ticker", "BTC/USD")

            # Test spread
            spread_data = ["49990.00", "50000.00", "1234567890.123", "10.5", "8.3"]
            await client.handle_spread_data(200, spread_data, "spread", "BTC/USD")

            # Test book
            book_data = {"bs": [["49990.00", "1.5", "1234567890.123"]], "as": [["50000.00", "2.0", "1234567890.124"]], "c": "1234567890"}
            await client.handle_book_data(300, book_data, "book", "BTC/USD")

            # Test trade
            trade_data = [["50000.00", "1.5", "1234567890.123", "b", "m", ""]]
            await client.handle_trade_data(400, trade_data, "trade", "BTC/USD")

            # Verify all setex calls have sequence
            for call in mock_redis.setex.call_args_list:
                stored_data = json.loads(call[0][2])
                assert "sequence" in stored_data

            # Verify xadd call has sequence
            if mock_redis.xadd.called:
                call_args = mock_redis.xadd.call_args
                stream_data = call_args[0][1]
                assert "sequence" in stream_data


class TestTickerRouting:
    """Test ticker message routing"""

    @pytest.mark.asyncio
    async def test_ticker_messages_routed_to_handler(self, client):
        """Test that ticker messages are routed to handle_ticker_data"""
        with patch.object(client, 'handle_ticker_data', new_callable=AsyncMock) as mock_handler:
            # Simulate ticker message
            ticker_message = json.dumps([
                192,
                {"a": ["50000.00", "1", "1.000"], "b": ["49990.00", "2", "2.000"], "c": ["49995.00", "0.5"]},
                "ticker",
                "BTC/USD"
            ])

            await client.handle_message(ticker_message)

            # Verify handler was called
            assert mock_handler.called
