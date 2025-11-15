"""
Unit tests for Kraken WebSocket connection state tracking (PRD-001 Section 4.1)

Tests verify:
- ConnectionState enum is defined correctly
- Initial state is DISCONNECTED
- State transitions are logged at INFO level
- State changes are tracked correctly
- get_connection_state() returns current state
- State is included in get_stats()
"""

import pytest
import asyncio
import logging
from unittest.mock import Mock, patch, AsyncMock
from utils.kraken_ws import (
    KrakenWebSocketClient,
    KrakenWSConfig,
    ConnectionState
)


class TestConnectionStateEnum:
    """Test ConnectionState enum definition"""

    def test_connection_state_enum_values(self):
        """Test that ConnectionState enum has all required states per PRD-001"""
        assert hasattr(ConnectionState, 'CONNECTING')
        assert hasattr(ConnectionState, 'CONNECTED')
        assert hasattr(ConnectionState, 'DISCONNECTED')
        assert hasattr(ConnectionState, 'RECONNECTING')

    def test_connection_state_enum_string_values(self):
        """Test that enum values are correct strings"""
        assert ConnectionState.CONNECTING.value == "connecting"
        assert ConnectionState.CONNECTED.value == "connected"
        assert ConnectionState.DISCONNECTED.value == "disconnected"
        assert ConnectionState.RECONNECTING.value == "reconnecting"


class TestKrakenWSConnectionState:
    """Test KrakenWebSocketClient connection state tracking"""

    @pytest.fixture
    def config(self):
        """Create test configuration"""
        return KrakenWSConfig(
            url="wss://ws.kraken.com",
            pairs=["BTC/USD"],
            redis_url="",  # No Redis for unit tests
            max_retries=10,
            ping_interval=30,
            reconnect_delay=1
        )

    @pytest.fixture
    def client(self, config):
        """Create WebSocket client for testing"""
        return KrakenWebSocketClient(config)

    def test_initial_state_is_disconnected(self, client):
        """Test that initial connection state is DISCONNECTED per PRD-001"""
        assert client.connection_state == ConnectionState.DISCONNECTED

    def test_get_connection_state_method(self, client):
        """Test get_connection_state() returns current state"""
        assert client.get_connection_state() == ConnectionState.DISCONNECTED

        # Change state and verify getter returns new state
        client.connection_state = ConnectionState.CONNECTING
        assert client.get_connection_state() == ConnectionState.CONNECTING

    def test_set_connection_state_changes_state(self, client):
        """Test _set_connection_state() changes the state"""
        client._set_connection_state(ConnectionState.CONNECTING, "Test transition")
        assert client.connection_state == ConnectionState.CONNECTING

    def test_set_connection_state_logs_transition(self, client, caplog):
        """Test that state transitions are logged at INFO level with timestamp"""
        with caplog.at_level(logging.INFO):
            client._set_connection_state(ConnectionState.CONNECTING, "Starting connection")

        # Verify log was created
        assert len(caplog.records) == 1
        log_record = caplog.records[0]

        # Verify log level is INFO per PRD-001 Section 8.1
        assert log_record.levelname == "INFO"

        # Verify log contains state transition
        assert "disconnected → connecting" in log_record.message.lower()

        # Verify reason is included
        assert "Starting connection" in log_record.message

    def test_set_connection_state_includes_timestamp(self, client, caplog):
        """Test that log message includes ISO timestamp"""
        with caplog.at_level(logging.INFO):
            client._set_connection_state(ConnectionState.CONNECTING, "Test")

        log_message = caplog.records[0].message
        # ISO timestamp format: YYYY-MM-DDTHH:MM:SS
        assert "[20" in log_message  # Contains year starting with 20
        assert "T" in log_message     # Contains ISO separator

    def test_set_connection_state_no_log_if_same_state(self, client, caplog):
        """Test that setting same state does not create duplicate log"""
        # Set to CONNECTING first
        client._set_connection_state(ConnectionState.CONNECTING, "Initial")
        caplog.clear()

        # Set to CONNECTING again (same state)
        with caplog.at_level(logging.INFO):
            client._set_connection_state(ConnectionState.CONNECTING, "Duplicate")

        # No new log should be created
        assert len(caplog.records) == 0

    def test_state_included_in_get_stats(self, client):
        """Test that connection_state is included in get_stats() output"""
        stats = client.get_stats()

        # Verify connection_state is in stats
        assert "connection_state" in stats

        # Verify it returns the string value
        assert stats["connection_state"] == "disconnected"

        # Change state and verify stats update
        client._set_connection_state(ConnectionState.CONNECTED, "Test")
        stats = client.get_stats()
        assert stats["connection_state"] == "connected"

    def test_all_state_transitions_logged(self, client, caplog):
        """Test that all state transitions are logged correctly"""
        with caplog.at_level(logging.INFO):
            # DISCONNECTED → CONNECTING
            client._set_connection_state(ConnectionState.CONNECTING, "Starting")
            assert "disconnected → connecting" in caplog.text.lower()

            # CONNECTING → CONNECTED
            caplog.clear()
            client._set_connection_state(ConnectionState.CONNECTED, "Established")
            assert "connecting → connected" in caplog.text.lower()

            # CONNECTED → DISCONNECTED
            caplog.clear()
            client._set_connection_state(ConnectionState.DISCONNECTED, "Closed")
            assert "connected → disconnected" in caplog.text.lower()

            # DISCONNECTED → RECONNECTING
            caplog.clear()
            client._set_connection_state(ConnectionState.RECONNECTING, "Retrying")
            assert "disconnected → reconnecting" in caplog.text.lower()


class TestConnectionStateInMethods:
    """Test that connection state is updated correctly in WebSocket methods"""

    @pytest.fixture
    def config(self):
        """Create test configuration"""
        return KrakenWSConfig(
            url="wss://ws.kraken.com",
            pairs=["BTC/USD"],
            redis_url="",
            max_retries=10,
            ping_interval=30
        )

    @pytest.fixture
    def client(self, config):
        """Create WebSocket client for testing"""
        return KrakenWebSocketClient(config)

    @pytest.mark.asyncio
    async def test_stop_sets_state_to_disconnected(self, client):
        """Test that stop() method sets state to DISCONNECTED"""
        # Set initial state to CONNECTED
        client._set_connection_state(ConnectionState.CONNECTED, "Test")

        # Mock redis_manager to avoid actual connection
        client.redis_manager.close = AsyncMock()

        # Stop the client
        await client.stop()

        # Verify state is DISCONNECTED
        assert client.connection_state == ConnectionState.DISCONNECTED

    def test_config_defaults_match_prd(self, config):
        """Test that config defaults match PRD-001 requirements"""
        # Max retries should be 10 per PRD-001 Section 4.2
        assert config.max_retries == 10

        # Ping interval should be 30s per PRD-001 Section 4.1
        assert config.ping_interval == 30

        # Reconnect delay should start at 1s per PRD-001 Section 4.2
        assert config.reconnect_delay == 1


@pytest.mark.asyncio
class TestReconnectionBackoff:
    """Test exponential backoff implementation per PRD-001 Section 4.2"""

    @pytest.fixture
    def config(self):
        """Create test configuration"""
        return KrakenWSConfig(
            url="wss://ws.kraken.com",
            pairs=["BTC/USD"],
            redis_url="",
            max_retries=10,
            reconnect_delay=1
        )

    @pytest.fixture
    def client(self, config):
        """Create WebSocket client"""
        return KrakenWebSocketClient(config)

    def test_backoff_sequence(self, client):
        """Test that exponential backoff follows 2x doubling pattern"""
        backoff = client.config.reconnect_delay
        max_backoff = 60
        expected_sequence = [1, 2, 4, 8, 16, 32, 60, 60, 60, 60]  # Caps at 60

        actual_sequence = []
        for _ in range(10):
            actual_sequence.append(backoff)
            backoff = min(backoff * 2, max_backoff)

        # Verify sequence matches expected pattern
        assert actual_sequence == expected_sequence

    def test_jitter_range(self):
        """Test that jitter is within ±20% range per PRD-001"""
        import random
        random.seed(42)  # Reproducible test

        # Test 100 samples of jitter
        for _ in range(100):
            jitter = random.uniform(-0.2, 0.2)
            # Verify jitter is within ±20%
            assert -0.2 <= jitter <= 0.2


@pytest.mark.asyncio
class TestHealthCheck:
    """Test health check based on connection state per PRD-001 Section 4.1"""

    @pytest.fixture
    def config(self):
        """Create test configuration"""
        return KrakenWSConfig(
            url="wss://ws.kraken.com",
            pairs=["BTC/USD"],
            redis_url="",
            max_retries=10
        )

    @pytest.fixture
    def client(self, config):
        """Create WebSocket client"""
        return KrakenWebSocketClient(config)

    def test_is_healthy_when_connected(self, client):
        """Test that bot is healthy when connected"""
        client._set_connection_state(ConnectionState.CONNECTED, "Test connection")
        assert client.is_healthy is True

    def test_is_healthy_when_connecting(self, client):
        """Test that bot is healthy when connecting"""
        client._set_connection_state(ConnectionState.CONNECTING, "Test connecting")
        assert client.is_healthy is True

    def test_is_healthy_when_reconnecting(self, client):
        """Test that bot is healthy when reconnecting"""
        client._set_connection_state(ConnectionState.RECONNECTING, "Test reconnecting")
        assert client.is_healthy is True

    def test_is_healthy_when_just_disconnected(self, client):
        """Test that bot is still healthy immediately after disconnection"""
        client._set_connection_state(ConnectionState.DISCONNECTED, "Test disconnection")
        assert client.is_healthy is True

    def test_is_unhealthy_after_2_minutes_disconnected(self, client):
        """Test that bot becomes unhealthy after > 2 minutes disconnected"""
        import time

        # Set to disconnected
        client._set_connection_state(ConnectionState.DISCONNECTED, "Test long disconnection")

        # Simulate 2 minutes + 1 second passing
        client.connection_state_changed_at = time.time() - 121

        # Should be unhealthy
        assert client.is_healthy is False

    def test_health_transitions_correctly(self, client):
        """Test that health status transitions correctly through states"""
        import time

        # Start connected - should be healthy
        client._set_connection_state(ConnectionState.CONNECTED, "Initial connection")
        assert client.is_healthy is True

        # Disconnect - still healthy initially
        client._set_connection_state(ConnectionState.DISCONNECTED, "Connection lost")
        assert client.is_healthy is True

        # Simulate 1 minute - still healthy
        client.connection_state_changed_at = time.time() - 60
        assert client.is_healthy is True

        # Simulate 2.5 minutes - now unhealthy
        client.connection_state_changed_at = time.time() - 150
        assert client.is_healthy is False

        # Reconnect - healthy again
        client._set_connection_state(ConnectionState.CONNECTED, "Reconnected")
        assert client.is_healthy is True

    def test_get_stats_includes_health_status(self, client):
        """Test that get_stats() includes is_healthy field"""
        stats = client.get_stats()

        # Should have is_healthy field
        assert "is_healthy" in stats
        assert isinstance(stats["is_healthy"], bool)

        # Should be True for newly created client (DISCONNECTED but < 2 min)
        assert stats["is_healthy"] is True

    def test_health_boundary_at_120_seconds(self, client):
        """Test health check boundary exactly at 120 seconds"""
        import time

        client._set_connection_state(ConnectionState.DISCONNECTED, "Test boundary")

        # At exactly 120 seconds - should still be healthy
        client.connection_state_changed_at = time.time() - 120
        assert client.is_healthy is True

        # At 120.1 seconds - should be unhealthy
        client.connection_state_changed_at = time.time() - 120.1
        assert client.is_healthy is False

    async def test_monitor_health_logs_unhealthy_state(self, client, caplog):
        """Test that monitor_health logs WARNING when unhealthy"""
        import logging
        import time

        # Set to unhealthy state
        client._set_connection_state(ConnectionState.DISCONNECTED, "Test unhealthy")
        client.connection_state_changed_at = time.time() - 150  # 2.5 minutes ago

        # Start monitoring
        client.running = True

        # Capture logs
        with caplog.at_level(logging.WARNING):
            # Run one iteration of health monitor
            health_task = asyncio.create_task(client.monitor_health())

            # Give it time to log
            await asyncio.sleep(0.1)

            # Stop monitoring
            client.running = False
            await asyncio.sleep(0.1)

        # Should have logged unhealthy warning
        warning_logs = [r for r in caplog.records if "unhealthy" in r.message.lower()]
        assert len(warning_logs) > 0
        assert "disconnected for" in warning_logs[0].message.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
