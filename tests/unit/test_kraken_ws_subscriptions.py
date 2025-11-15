"""
Unit tests for Kraken WebSocket subscriptions (PRD-001 Section 4.1)

Tests verify:
- All 5 required pairs are configured (BTC/USD, ETH/USD, SOL/USD, MATIC/USD, LINK/USD)
- All 4 required channels are subscribed (ticker, spread, trade, book)
- Subscription messages are correctly formatted
- Logging at INFO level occurs
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from utils.kraken_ws import KrakenWebSocketClient, KrakenWSConfig


class TestKrakenWSSubscriptions:
    """Test Kraken WebSocket subscription setup"""

    @pytest.fixture
    def config(self):
        """Create test configuration with all 5 pairs"""
        return KrakenWSConfig(
            url="wss://ws.kraken.com",
            pairs=["BTC/USD", "ETH/USD", "SOL/USD", "MATIC/USD", "LINK/USD"],
            redis_url="",  # No Redis for unit tests
            max_retries=10,
            ping_interval=30
        )

    @pytest.fixture
    def client(self, config):
        """Create WebSocket client for testing"""
        return KrakenWebSocketClient(config)

    def test_default_pairs_match_prd(self):
        """Test that default pairs match PRD-001 Section 2.3"""
        # Create config without specifying pairs (uses defaults)
        import os
        # Temporarily remove TRADING_PAIRS env var
        old_val = os.environ.pop('TRADING_PAIRS', None)

        try:
            config = KrakenWSConfig(redis_url="")

            # Should have exactly 5 pairs per PRD
            assert len(config.pairs) == 5

            # Should have the exact pairs from PRD-001 Section 2.3
            expected_pairs = {"BTC/USD", "ETH/USD", "SOL/USD", "MATIC/USD", "LINK/USD"}
            actual_pairs = set(config.pairs)

            assert actual_pairs == expected_pairs, f"Expected {expected_pairs}, got {actual_pairs}"
        finally:
            # Restore env var if it existed
            if old_val is not None:
                os.environ['TRADING_PAIRS'] = old_val

    def test_config_has_all_five_pairs(self, config):
        """Test configuration includes all 5 required trading pairs"""
        assert len(config.pairs) == 5

        required_pairs = ["BTC/USD", "ETH/USD", "SOL/USD", "MATIC/USD", "LINK/USD"]
        for pair in required_pairs:
            assert pair in config.pairs, f"Missing required pair: {pair}"

    def test_subscription_message_format_ticker(self, client):
        """Test ticker subscription message format"""
        sub = client.create_subscription("ticker", ["BTC/USD"])

        assert sub["event"] == "subscribe"
        assert sub["pair"] == ["BTC/USD"]
        assert sub["subscription"]["name"] == "ticker"

    def test_subscription_message_format_spread(self, client):
        """Test spread subscription message format"""
        sub = client.create_subscription("spread", ["BTC/USD"])

        assert sub["event"] == "subscribe"
        assert sub["pair"] == ["BTC/USD"]
        assert sub["subscription"]["name"] == "spread"

    def test_subscription_message_format_trade(self, client):
        """Test trade subscription message format"""
        sub = client.create_subscription("trade", ["BTC/USD"])

        assert sub["event"] == "subscribe"
        assert sub["pair"] == ["BTC/USD"]
        assert sub["subscription"]["name"] == "trade"

    def test_subscription_message_format_book(self, client):
        """Test book (L2) subscription message format"""
        sub = client.create_subscription("book", ["BTC/USD"], depth=10)

        assert sub["event"] == "subscribe"
        assert sub["pair"] == ["BTC/USD"]
        assert sub["subscription"]["name"] == "book"
        assert sub["subscription"]["depth"] == 10

    @pytest.mark.asyncio
    async def test_setup_subscriptions_creates_all_channels(self, client):
        """Test that setup_subscriptions creates subscriptions for all 4 channels"""
        # Mock the WebSocket send method
        client.ws = AsyncMock()
        client.ws.send = AsyncMock()

        # Mock circuit breaker to pass through
        async def mock_call(func, *args):
            return await func(*args) if asyncio.iscoroutinefunction(func) else func(*args)

        client.circuit_breakers["connection"].call = mock_call

        # Call setup_subscriptions
        await client.setup_subscriptions()

        # Verify send was called (at least for ticker, spread, trade, book = 4 calls minimum)
        # Note: May be more if OHLC timeframes are configured
        assert client.ws.send.call_count >= 4

        # Collect all subscription messages sent
        sent_messages = []
        for call in client.ws.send.call_args_list:
            import json
            msg = json.loads(call[0][0])
            sent_messages.append(msg)

        # Verify all 4 required channels were subscribed
        channels_subscribed = {msg["subscription"]["name"] for msg in sent_messages}
        required_channels = {"ticker", "spread", "trade", "book"}

        for channel in required_channels:
            assert channel in channels_subscribed, f"Missing subscription for channel: {channel}"

    @pytest.mark.asyncio
    async def test_setup_subscriptions_logs_info(self, client, caplog):
        """Test that setup_subscriptions logs at INFO level per PRD-001"""
        import logging

        # Mock the WebSocket send method
        client.ws = AsyncMock()
        client.ws.send = AsyncMock()

        # Mock circuit breaker
        async def mock_call(func, *args):
            return await func(*args) if asyncio.iscoroutinefunction(func) else func(*args)

        client.circuit_breakers["connection"].call = mock_call

        # Capture logs
        with caplog.at_level(logging.INFO):
            await client.setup_subscriptions()

        # Verify INFO logs were created
        info_logs = [record for record in caplog.records if record.levelname == "INFO"]
        assert len(info_logs) >= 2  # At least setup start and completion logs

        # Verify setup log mentions the pairs
        setup_log = [log for log in info_logs if "Setting up" in log.message]
        assert len(setup_log) > 0
        assert "5 pairs" in setup_log[0].message  # Should mention 5 pairs

        # Verify completion log
        completion_log = [log for log in info_logs if "Subscriptions complete" in log.message]
        assert len(completion_log) > 0

    @pytest.mark.asyncio
    async def test_setup_subscriptions_includes_all_pairs(self, client):
        """Test that subscriptions are sent for all 5 configured pairs"""
        client.ws = AsyncMock()
        client.ws.send = AsyncMock()

        async def mock_call(func, *args):
            return await func(*args) if asyncio.iscoroutinefunction(func) else func(*args)

        client.circuit_breakers["connection"].call = mock_call

        await client.setup_subscriptions()

        # Collect all subscription messages
        import json
        sent_messages = []
        for call in client.ws.send.call_args_list:
            msg = json.loads(call[0][0])
            sent_messages.append(msg)

        # Check that at least one message includes all 5 pairs
        # (Kraken allows subscribing to multiple pairs at once)
        all_pairs_found = False
        for msg in sent_messages:
            pairs_in_msg = set(msg.get("pair", []))
            expected_pairs = set(client.config.pairs)
            if pairs_in_msg == expected_pairs:
                all_pairs_found = True
                break

        # All messages should collectively cover all pairs
        all_pairs_in_messages = set()
        for msg in sent_messages:
            all_pairs_in_messages.update(msg.get("pair", []))

        required_pairs = {"BTC/USD", "ETH/USD", "SOL/USD", "MATIC/USD", "LINK/USD"}
        assert required_pairs.issubset(all_pairs_in_messages), \
            f"Not all required pairs found in subscriptions. Expected {required_pairs}, got {all_pairs_in_messages}"

    def test_redis_streams_includes_ticker(self, config):
        """Test that redis_streams config includes ticker stream"""
        assert "ticker" in config.redis_streams
        assert config.redis_streams["ticker"] == "kraken:ticker"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
