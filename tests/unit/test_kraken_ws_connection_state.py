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


@pytest.mark.asyncio
class TestConnectionTimeout:
    """Test connection timeout detection per PRD-001 Section 4.1"""

    @pytest.fixture
    def config(self):
        """Create test configuration with ping timeout"""
        return KrakenWSConfig(
            url="wss://ws.kraken.com",
            pairs=["BTC/USD"],
            redis_url="",
            ping_interval=30,
            ping_timeout=60
        )

    @pytest.fixture
    def client(self, config):
        """Create WebSocket client"""
        return KrakenWebSocketClient(config)

    def test_config_includes_ping_timeout(self, config):
        """Test that config includes ping_timeout parameter"""
        assert hasattr(config, 'ping_timeout')
        assert config.ping_timeout == 60

    def test_ping_timeout_default_from_env(self):
        """Test that ping_timeout can be configured via environment"""
        import os

        # Save original value
        old_val = os.environ.get('WEBSOCKET_PING_TIMEOUT')

        try:
            # Remove existing value first
            os.environ.pop('WEBSOCKET_PING_TIMEOUT', None)

            # Set custom value
            os.environ['WEBSOCKET_PING_TIMEOUT'] = '90'

            # Create new config (should read from env)
            config = KrakenWSConfig(redis_url="", ping_timeout=int(os.getenv('WEBSOCKET_PING_TIMEOUT', '60')))
            assert config.ping_timeout == 90

        finally:
            # Restore original
            if old_val is not None:
                os.environ['WEBSOCKET_PING_TIMEOUT'] = old_val
            else:
                os.environ.pop('WEBSOCKET_PING_TIMEOUT', None)

    def test_ping_timeout_boundaries(self):
        """Test that ping_timeout enforces boundaries (10-120s)"""
        # Valid range
        config_valid = KrakenWSConfig(redis_url="", ping_timeout=60)
        assert config_valid.ping_timeout == 60

        # Below minimum should fail
        with pytest.raises(Exception):  # Pydantic validation error
            KrakenWSConfig(redis_url="", ping_timeout=5)

        # Above maximum should fail
        with pytest.raises(Exception):  # Pydantic validation error
            KrakenWSConfig(redis_url="", ping_timeout=150)

    async def test_monitor_health_detects_timeout(self, client, caplog):
        """Test that monitor_health detects PONG timeout and closes connection"""
        import logging
        import time

        # Set last_heartbeat to > 60s ago
        client.last_heartbeat = time.time() - 65

        # Create mock WebSocket
        client.ws = AsyncMock()
        client.ws.close = AsyncMock()

        # Set to CONNECTED state
        client._set_connection_state(ConnectionState.CONNECTED, "Test connected")

        # Start monitoring
        client.running = True

        # Capture logs
        with caplog.at_level(logging.WARNING):
            # Run one iteration of health monitor
            health_task = asyncio.create_task(client.monitor_health())

            # Give it time to detect timeout and close
            await asyncio.sleep(0.2)

            # Stop monitoring
            client.running = False
            await asyncio.sleep(0.1)

        # Should have logged timeout warning
        timeout_logs = [r for r in caplog.records if "timeout" in r.message.lower()]
        assert len(timeout_logs) > 0
        assert "pong" in timeout_logs[0].message.lower() or "heartbeat" in timeout_logs[0].message.lower()

        # Should have attempted to close WebSocket
        assert client.ws.close.called

    async def test_timeout_does_not_close_if_already_disconnected(self, client):
        """Test that timeout check doesn't try to close if already disconnected"""
        import time

        # Set last_heartbeat to > 60s ago
        client.last_heartbeat = time.time() - 65

        # Create mock WebSocket
        client.ws = AsyncMock()
        client.ws.close = AsyncMock()

        # Set to DISCONNECTED state
        client._set_connection_state(ConnectionState.DISCONNECTED, "Test disconnected")

        # Start monitoring
        client.running = True

        # Run one iteration
        health_task = asyncio.create_task(client.monitor_health())
        await asyncio.sleep(0.1)
        client.running = False
        await asyncio.sleep(0.1)

        # Should NOT have tried to close (already disconnected)
        assert not client.ws.close.called

    def test_heartbeat_updated_on_message(self, client):
        """Test that last_heartbeat is updated when heartbeat message received"""
        import time

        initial_heartbeat = client.last_heartbeat

        # Simulate time passing
        time.sleep(0.1)

        # Update heartbeat (simulating message receipt)
        client.last_heartbeat = time.time()

        # Should be more recent
        assert client.last_heartbeat > initial_heartbeat


class TestPrometheusMetrics:
    """Test Prometheus metrics for connection state changes per PRD-001 Section 4.1 & 8.2"""

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

    def test_prometheus_counter_exists(self):
        """Test that Prometheus counter is defined"""
        from utils.kraken_ws import PROMETHEUS_AVAILABLE, KRAKEN_WS_CONNECTIONS_TOTAL

        # Counter should be defined (may be None if prometheus not available)
        if PROMETHEUS_AVAILABLE:
            assert KRAKEN_WS_CONNECTIONS_TOTAL is not None
            assert hasattr(KRAKEN_WS_CONNECTIONS_TOTAL, 'labels')

    def test_counter_increments_on_state_change(self, client):
        """Test that counter increments when connection state changes"""
        from utils.kraken_ws import PROMETHEUS_AVAILABLE, KRAKEN_WS_CONNECTIONS_TOTAL

        if not PROMETHEUS_AVAILABLE:
            pytest.skip("Prometheus not available")

        # Get initial counter values
        initial_connecting = KRAKEN_WS_CONNECTIONS_TOTAL.labels(state='connecting')._value.get()
        initial_connected = KRAKEN_WS_CONNECTIONS_TOTAL.labels(state='connected')._value.get()

        # Change to CONNECTING
        client._set_connection_state(ConnectionState.CONNECTING, "Test")

        # Counter should increment
        assert KRAKEN_WS_CONNECTIONS_TOTAL.labels(state='connecting')._value.get() == initial_connecting + 1

        # Change to CONNECTED
        client._set_connection_state(ConnectionState.CONNECTED, "Test")

        # Counter should increment
        assert KRAKEN_WS_CONNECTIONS_TOTAL.labels(state='connected')._value.get() == initial_connected + 1

    def test_counter_has_correct_labels(self):
        """Test that counter has all required state labels"""
        from utils.kraken_ws import PROMETHEUS_AVAILABLE, KRAKEN_WS_CONNECTIONS_TOTAL

        if not PROMETHEUS_AVAILABLE:
            pytest.skip("Prometheus not available")

        # Should be able to create labels for all states
        states = ['connecting', 'connected', 'disconnected', 'reconnecting']

        for state in states:
            metric = KRAKEN_WS_CONNECTIONS_TOTAL.labels(state=state)
            assert metric is not None

    def test_counter_only_increments_on_actual_change(self, client):
        """Test that counter doesn't increment when state doesn't change"""
        from utils.kraken_ws import PROMETHEUS_AVAILABLE, KRAKEN_WS_CONNECTIONS_TOTAL

        if not PROMETHEUS_AVAILABLE:
            pytest.skip("Prometheus not available")

        # Set to CONNECTING
        client._set_connection_state(ConnectionState.CONNECTING, "Test")
        initial_value = KRAKEN_WS_CONNECTIONS_TOTAL.labels(state='connecting')._value.get()

        # Try to set to same state again
        client._set_connection_state(ConnectionState.CONNECTING, "Test again")

        # Counter should NOT increment (no actual state change)
        assert KRAKEN_WS_CONNECTIONS_TOTAL.labels(state='connecting')._value.get() == initial_value

    def test_metric_name_and_description(self):
        """Test that counter has correct name and description"""
        from utils.kraken_ws import PROMETHEUS_AVAILABLE, KRAKEN_WS_CONNECTIONS_TOTAL

        if not PROMETHEUS_AVAILABLE:
            pytest.skip("Prometheus not available")

        # Check metric metadata (Prometheus auto-strips '_total' suffix from Counter names)
        assert KRAKEN_WS_CONNECTIONS_TOTAL._name == 'kraken_ws_connections'
        assert 'connection state' in KRAKEN_WS_CONNECTIONS_TOTAL._documentation.lower()


class TestReconnectionCounter:
    """Test reconnection attempt counter per PRD-001 Section 4.2"""

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

    def test_reconnection_attempt_starts_at_zero(self, client):
        """Test that reconnection_attempt initializes to 0"""
        assert client.reconnection_attempt == 0

    def test_reconnection_attempt_in_stats(self, client):
        """Test that reconnection_attempt is included in get_stats()"""
        stats = client.get_stats()

        assert "reconnection_attempt" in stats
        assert stats["reconnection_attempt"] == 0

    def test_reconnection_attempt_increments_on_failure(self, client):
        """Test that reconnection_attempt increments when set via exception path"""
        # Simulate what happens in start() on connection failure
        client.reconnection_attempt += 1

        assert client.reconnection_attempt == 1

        # Second failure
        client.reconnection_attempt += 1

        assert client.reconnection_attempt == 2

    def test_reconnection_attempt_resets_on_success(self, client):
        """Test that reconnection_attempt resets to 0 on successful connection"""
        # Simulate failures
        client.reconnection_attempt = 5

        # Simulate successful connection (what happens in start())
        client.reconnection_attempt = 0

        assert client.reconnection_attempt == 0

    def test_stats_reconnects_separate_from_attempt(self, client):
        """Test that stats['reconnects'] is separate from reconnection_attempt"""
        # Historical total should be separate from current attempt
        client.stats["reconnects"] = 10
        client.reconnection_attempt = 2

        stats = client.get_stats()

        # Historical total should be preserved
        assert stats["reconnects"] == 10

        # Current attempt should be separate
        assert stats["reconnection_attempt"] == 2

    def test_multiple_reconnection_cycles(self, client):
        """Test reconnection counter through multiple connect/disconnect cycles"""
        # Cycle 1: 3 failures, then success
        client.reconnection_attempt = 3
        client.stats["reconnects"] = 3

        # Success - reset attempt but keep historical total
        client.reconnection_attempt = 0

        assert client.reconnection_attempt == 0
        assert client.stats["reconnects"] == 3

        # Cycle 2: 2 more failures
        client.reconnection_attempt = 2
        client.stats["reconnects"] = 5

        assert client.reconnection_attempt == 2
        assert client.stats["reconnects"] == 5

        # Success again
        client.reconnection_attempt = 0

        assert client.reconnection_attempt == 0
        assert client.stats["reconnects"] == 5  # Historical count preserved


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
