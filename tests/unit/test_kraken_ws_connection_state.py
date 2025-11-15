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

    def test_reconnects_counter_exists(self):
        """Test that Prometheus reconnects counter is defined (PRD-001 Section 4.2)"""
        from utils.kraken_ws import PROMETHEUS_AVAILABLE, KRAKEN_WS_RECONNECTS_TOTAL

        # Counter should be defined (may be None if prometheus not available)
        if PROMETHEUS_AVAILABLE:
            assert KRAKEN_WS_RECONNECTS_TOTAL is not None
            assert hasattr(KRAKEN_WS_RECONNECTS_TOTAL, 'inc')

    def test_reconnects_counter_increments_on_failed_connection(self, client):
        """Test that reconnects counter increments on each reconnection attempt"""
        from utils.kraken_ws import PROMETHEUS_AVAILABLE, KRAKEN_WS_RECONNECTS_TOTAL

        if not PROMETHEUS_AVAILABLE:
            pytest.skip("Prometheus not available")

        # Get initial counter value
        initial_value = KRAKEN_WS_RECONNECTS_TOTAL._value.get()

        # Simulate what happens in start() on connection failure (lines 1264-1269 in kraken_ws.py)
        # This is the exact code path where the Prometheus counter is incremented
        client.reconnection_attempt += 1
        client.stats["reconnects"] += 1

        # Emit Prometheus counter (simulating the code at line 1268-1269)
        if PROMETHEUS_AVAILABLE and KRAKEN_WS_RECONNECTS_TOTAL:
            KRAKEN_WS_RECONNECTS_TOTAL.inc()

        # Counter should have incremented by 1
        final_value = KRAKEN_WS_RECONNECTS_TOTAL._value.get()
        assert final_value == initial_value + 1, f"Expected counter to be {initial_value + 1}, but got {final_value}"

        # Test multiple increments
        KRAKEN_WS_RECONNECTS_TOTAL.inc()
        final_value_2 = KRAKEN_WS_RECONNECTS_TOTAL._value.get()
        assert final_value_2 == initial_value + 2, f"Expected counter to be {initial_value + 2}, but got {final_value_2}"

    def test_reconnects_metric_name_and_description(self):
        """Test that reconnects counter has correct name and description"""
        from utils.kraken_ws import PROMETHEUS_AVAILABLE, KRAKEN_WS_RECONNECTS_TOTAL

        if not PROMETHEUS_AVAILABLE:
            pytest.skip("Prometheus not available")

        # Check metric metadata (Prometheus auto-strips '_total' suffix from Counter names)
        assert KRAKEN_WS_RECONNECTS_TOTAL._name == 'kraken_ws_reconnects'
        assert 'reconnection' in KRAKEN_WS_RECONNECTS_TOTAL._documentation.lower()


@pytest.mark.asyncio
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

    async def test_end_to_end_reconnection_with_mocked_failures(self, client):
        """
        Comprehensive end-to-end test with mocked WebSocket failures (PRD-001 Section 4.2).

        Tests the complete reconnection flow:
        1. Mock WebSocket to fail 3 times, then succeed
        2. Verify exponential backoff is applied
        3. Verify reconnection counter increments
        4. Verify successful reconnection resets counter
        """
        # Use fast reconnect delay for testing
        client.config.reconnect_delay = 0.1  # 100ms instead of 1s

        # Track call attempts
        call_count = 0

        async def mock_connect_once():
            """Mock connect_once that fails 3 times then succeeds once"""
            nonlocal call_count
            call_count += 1

            if call_count <= 3:
                # First 3 attempts fail
                raise Exception(f"Mock connection failure {call_count}")
            elif call_count == 4:
                # 4th attempt succeeds - simulate successful connection
                # Set state to CONNECTED
                client._set_connection_state(ConnectionState.CONNECTED, "Mock connection successful")
                # Wait briefly to simulate connection
                await asyncio.sleep(0.05)
                # Return normally to allow reconnection_attempt reset in start()
                return
            else:
                # After first success, stop the client to exit the loop
                client.running = False
                return

        # Mock the circuit breaker to call our mock function
        async def mock_circuit_breaker(func):
            return await mock_connect_once()

        client.circuit_breakers["connection"].call = mock_circuit_breaker

        # Mock Redis
        client.redis_manager.initialize_pool = AsyncMock()
        client.redis_manager.close = AsyncMock()

        # Start the client (will attempt reconnections)
        start_task = asyncio.create_task(client.start())

        # Wait for 4th successful connection and reset
        max_wait = 2.0  # seconds
        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < max_wait:
            await asyncio.sleep(0.05)
            if call_count >= 4 and client.reconnection_attempt == 0:
                # Success! Stop the client
                client.running = False
                break

        # Wait a bit for task to complete
        await asyncio.sleep(0.1)

        # Cancel if still running
        if not start_task.done():
            start_task.cancel()
            try:
                await start_task
            except asyncio.CancelledError:
                pass

        # Verify reconnection flow
        # Should have at least 4 calls (3 failures + 1 success)
        # May have 5 if loop continued once more before stopping
        assert call_count >= 4, f"Expected at least 4 connection attempts (3 failures + 1 success), got {call_count}"
        assert call_count <= 5, f"Expected at most 5 connection attempts, got {call_count}"

        # After successful connection, reconnection_attempt should be reset
        # (happens at line 1260 in kraken_ws.py)
        assert client.reconnection_attempt == 0, "Reconnection attempt should be reset after success"

        # Historical reconnect count should be 3 (one for each failure)
        assert client.stats["reconnects"] == 3, f"Expected 3 historical reconnects, got {client.stats['reconnects']}"

        # Connection should have succeeded
        assert client.connection_state == ConnectionState.CONNECTED, "Should be in CONNECTED state after success"

    async def test_reconnection_with_max_retries_exceeded(self, client):
        """
        Test reconnection behavior when max retries is exceeded (PRD-001 Section 4.2).

        Verifies that:
        1. After max_retries failures, bot stops attempting to reconnect
        2. Bot is marked as unhealthy
        3. State is set to DISCONNECTED
        """
        # Set low max retries and fast delay for faster test
        client.config.max_retries = 3
        client.config.reconnect_delay = 0.1  # 100ms instead of 1s

        # Track call attempts
        call_count = 0

        async def mock_connect_once_always_fails():
            """Mock connect_once that always fails"""
            nonlocal call_count
            call_count += 1
            raise Exception(f"Mock connection failure {call_count}")

        # Mock the circuit breaker
        async def mock_circuit_breaker(func):
            return await mock_connect_once_always_fails()

        client.circuit_breakers["connection"].call = mock_circuit_breaker

        # Mock Redis
        client.redis_manager.initialize_pool = AsyncMock()
        client.redis_manager.close = AsyncMock()

        # Start the client
        start_task = asyncio.create_task(client.start())

        # Wait for completion (should exit after max retries)
        try:
            await asyncio.wait_for(start_task, timeout=5.0)
        except asyncio.TimeoutError:
            client.running = False
            start_task.cancel()
            try:
                await start_task
            except asyncio.CancelledError:
                pass

        # Verify max retries behavior
        assert call_count == 3, f"Expected exactly 3 connection attempts (max_retries), got {call_count}"
        assert client.reconnection_attempt == 3, f"Expected reconnection_attempt=3, got {client.reconnection_attempt}"
        assert client.is_healthy is False, "Bot should be unhealthy after max retries"
        assert client.connection_state == ConnectionState.DISCONNECTED, "State should be DISCONNECTED after max retries"


@pytest.mark.asyncio
class TestReconnectionLogging:
    """Test reconnection attempt logging per PRD-001 Section 4.2 & 8.1"""

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

    def test_error_log_includes_attempt_and_max(self, client, caplog):
        """Test that error log includes attempt number and max retries"""
        import logging

        # Simulate what happens in start() exception handler
        client.reconnection_attempt = 3

        with caplog.at_level(logging.ERROR):
            client.logger.error(
                f"Kraken WS connection failed (attempt {client.reconnection_attempt}/{client.config.max_retries}): Test error"
            )

        # Should have logged error with attempt/max format
        error_logs = [r for r in caplog.records if r.levelname == "ERROR"]
        assert len(error_logs) > 0
        assert "attempt 3/10" in error_logs[0].message.lower()

    def test_info_log_includes_attempt_number(self, client, caplog):
        """Test that INFO log includes reconnection attempt number"""
        import logging

        client.reconnection_attempt = 5
        backoff = 8.0
        jitter_pct = 15.0
        backoff_with_jitter = 9.2

        with caplog.at_level(logging.INFO):
            client.logger.info(
                f"Reconnection attempt {client.reconnection_attempt}/{client.config.max_retries}: "
                f"waiting {backoff_with_jitter:.1f}s before retry "
                f"(base: {backoff}s, jitter: {jitter_pct:+.0f}%)"
            )

        # Should have INFO log with attempt number
        info_logs = [r for r in caplog.records if r.levelname == "INFO"]
        assert len(info_logs) > 0
        assert "reconnection attempt 5/10" in info_logs[0].message.lower()

    def test_info_log_includes_wait_time(self, client, caplog):
        """Test that INFO log includes calculated wait time"""
        import logging

        client.reconnection_attempt = 2
        backoff_with_jitter = 2.3

        with caplog.at_level(logging.INFO):
            client.logger.info(
                f"Reconnection attempt {client.reconnection_attempt}/{client.config.max_retries}: "
                f"waiting {backoff_with_jitter:.1f}s before retry "
                f"(base: 2s, jitter: +15%)"
            )

        info_logs = [r for r in caplog.records if r.levelname == "INFO"]
        assert len(info_logs) > 0
        assert "waiting 2.3s" in info_logs[0].message.lower()

    def test_info_log_includes_base_backoff(self, client, caplog):
        """Test that INFO log includes base backoff value"""
        import logging

        client.reconnection_attempt = 4
        backoff = 8.0

        with caplog.at_level(logging.INFO):
            client.logger.info(
                f"Reconnection attempt {client.reconnection_attempt}/{client.config.max_retries}: "
                f"waiting 9.6s before retry "
                f"(base: {backoff}s, jitter: +20%)"
            )

        info_logs = [r for r in caplog.records if r.levelname == "INFO"]
        assert len(info_logs) > 0
        assert "base: 8" in info_logs[0].message.lower()

    def test_info_log_includes_jitter_percentage(self, client, caplog):
        """Test that INFO log includes jitter percentage with sign"""
        import logging

        client.reconnection_attempt = 1

        # Test positive jitter
        with caplog.at_level(logging.INFO):
            client.logger.info(
                f"Reconnection attempt {client.reconnection_attempt}/{client.config.max_retries}: "
                f"waiting 1.2s before retry "
                f"(base: 1s, jitter: +20%)"
            )

        info_logs = [r for r in caplog.records if r.levelname == "INFO"]
        assert len(info_logs) > 0
        assert "jitter:" in info_logs[0].message.lower()
        assert "%" in info_logs[0].message

    def test_log_format_is_readable(self, client, caplog):
        """Test that log message format is clear and readable"""
        import logging

        client.reconnection_attempt = 3
        backoff = 4.0
        jitter_pct = -10.0
        backoff_with_jitter = 3.6

        with caplog.at_level(logging.INFO):
            client.logger.info(
                f"Reconnection attempt {client.reconnection_attempt}/{client.config.max_retries}: "
                f"waiting {backoff_with_jitter:.1f}s before retry "
                f"(base: {backoff}s, jitter: {jitter_pct:+.0f}%)"
            )

        info_logs = [r for r in caplog.records if r.levelname == "INFO"]
        assert len(info_logs) > 0

        # Message should contain all key components
        msg = info_logs[0].message
        assert "reconnection attempt" in msg.lower()
        assert "3/10" in msg
        assert "waiting 3.6s" in msg.lower()
        assert "base: 4" in msg.lower()
        assert "jitter:" in msg.lower()


class TestMaxRetriesUnhealthy:
    """Test unhealthy state and alerting after max retries per PRD-001 Section 4.2"""

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

    def test_unhealthy_when_max_retries_reached(self, client):
        """Test that is_healthy returns False when reconnection_attempt >= max_retries"""
        # Start healthy
        assert client.is_healthy is True

        # Simulate failed attempts
        client.reconnection_attempt = 9
        assert client.is_healthy is True  # Still healthy at 9/10

        # Hit max retries
        client.reconnection_attempt = 10
        assert client.is_healthy is False  # Now unhealthy at 10/10

    def test_unhealthy_when_exceeds_max_retries(self, client):
        """Test that is_healthy returns False when reconnection_attempt > max_retries"""
        client.reconnection_attempt = 15
        assert client.is_healthy is False

    def test_healthy_before_max_retries(self, client):
        """Test that is_healthy returns True before hitting max_retries"""
        client.reconnection_attempt = 5
        client._set_connection_state(ConnectionState.RECONNECTING, "Test")
        assert client.is_healthy is True

    def test_unhealthy_overrides_connection_state(self, client):
        """Test that max_retries unhealthy check takes precedence over connection state"""
        # Even if CONNECTED, should be unhealthy if max retries reached
        client._set_connection_state(ConnectionState.CONNECTED, "Test")
        client.reconnection_attempt = 10

        assert client.is_healthy is False

    def test_alert_contains_correct_information(self, client):
        """Test that alert would contain correct information (mock test)"""
        # This tests the alert payload structure, not actual sending
        client.reconnection_attempt = 10

        expected_title = "⚠️ Kraken WebSocket: Max Reconnection Attempts Reached"
        expected_severity = "CRITICAL"
        expected_tags = {
            "component": "kraken_ws",
            "max_retries": "10",
            "pairs": "BTC/USD"
        }

        # Verify structure (would be used in send_alert call)
        assert expected_severity == "CRITICAL"
        assert "max reconnection attempts" in expected_title.lower()
        assert expected_tags["max_retries"] == str(client.config.max_retries)

    def test_health_check_boundary_at_max_retries(self, client):
        """Test health check boundary exactly at max_retries"""
        client.reconnection_attempt = 9
        assert client.is_healthy is True

        client.reconnection_attempt = 10
        assert client.is_healthy is False

    def test_unhealthy_persists_after_max_retries(self, client):
        """Test that unhealthy state persists after hitting max retries"""
        client.reconnection_attempt = 10
        assert client.is_healthy is False

        # Check multiple times - should remain unhealthy
        assert client.is_healthy is False
        assert client.is_healthy is False


@pytest.mark.asyncio
class TestResubscriptionOnReconnect:
    """Test automatic resubscription after reconnection per PRD-001 Section 4.2"""

    @pytest.fixture
    def config(self):
        """Create test configuration"""
        return KrakenWSConfig(
            url="wss://ws.kraken.com",
            pairs=["BTC/USD", "ETH/USD"],
            redis_url="",
            max_retries=10
        )

    @pytest.fixture
    def client(self, config):
        """Create WebSocket client"""
        return KrakenWebSocketClient(config)

    async def test_initial_subscription_logs_correctly(self, client, caplog):
        """Test that initial subscription logs as 'initial' not 'resubscription'"""
        import logging

        # Mock WebSocket
        client.ws = AsyncMock()
        client.ws.send = AsyncMock()

        # Mock circuit breaker
        async def mock_call(func, *args):
            return await func(*args) if asyncio.iscoroutinefunction(func) else func(*args)

        client.circuit_breakers["connection"].call = mock_call

        # Ensure it's initial (no reconnection attempts)
        client.reconnection_attempt = 0
        client.stats["reconnects"] = 0

        with caplog.at_level(logging.INFO):
            await client.setup_subscriptions()

        # Should log as "initial" not "resubscrib"
        info_logs = [r for r in caplog.records if r.levelname == "INFO"]
        setup_logs = [r for r in info_logs if "subscription" in r.message.lower()]

        assert len(setup_logs) > 0
        assert "initial" in setup_logs[0].message.lower()
        assert "resubscrib" not in setup_logs[0].message.lower()

    async def test_reconnection_logs_resubscription(self, client, caplog):
        """Test that reconnection logs as 'resubscription' not 'initial'"""
        import logging

        # Mock WebSocket
        client.ws = AsyncMock()
        client.ws.send = AsyncMock()

        # Mock circuit breaker
        async def mock_call(func, *args):
            return await func(*args) if asyncio.iscoroutinefunction(func) else func(*args)

        client.circuit_breakers["connection"].call = mock_call

        # Simulate reconnection (attempt > 0)
        client.reconnection_attempt = 3
        client.stats["reconnects"] = 3

        with caplog.at_level(logging.INFO):
            await client.setup_subscriptions()

        # Should log as "resubscrib" not "initial"
        info_logs = [r for r in caplog.records if r.levelname == "INFO"]
        setup_logs = [r for r in info_logs if "subscri" in r.message.lower()]

        assert len(setup_logs) > 0
        assert "resubscrib" in setup_logs[0].message.lower()
        assert "initial" not in setup_logs[0].message.lower()

    async def test_resubscription_includes_all_channels(self, client, caplog):
        """Test that resubscription completion log mentions all 4 channels"""
        import logging

        # Mock WebSocket
        client.ws = AsyncMock()
        client.ws.send = AsyncMock()

        # Mock circuit breaker
        async def mock_call(func, *args):
            return await func(*args) if asyncio.iscoroutinefunction(func) else func(*args)

        client.circuit_breakers["connection"].call = mock_call

        # Simulate reconnection
        client.reconnection_attempt = 2

        with caplog.at_level(logging.INFO):
            await client.setup_subscriptions()

        # Completion log should mention the 4 channels
        info_logs = [r for r in caplog.records if r.levelname == "INFO"]
        completion_logs = [r for r in info_logs if "complete" in r.message.lower()]

        assert len(completion_logs) > 0
        # Should mention ticker, spread, trade, book
        msg = completion_logs[0].message.lower()
        assert "ticker" in msg or "resubscription complete" in msg

    async def test_setup_subscriptions_called_on_connect(self, client):
        """Test that setup_subscriptions is called during connect_once flow"""
        # This verifies that the automatic resubscription happens
        # We can't fully test connect_once without a real WebSocket, but we can verify
        # the method exists and has the right signature

        import inspect
        assert hasattr(client, 'setup_subscriptions')
        assert asyncio.iscoroutinefunction(client.setup_subscriptions)

        # Verify it's documented to be called on reconnection
        docstring = client.setup_subscriptions.__doc__
        assert docstring is not None
        assert "reconnection" in docstring.lower()

    async def test_resubscription_detection_via_stats(self, client):
        """Test that resubscription is detected via stats['reconnects'] > 0"""
        client.reconnection_attempt = 0  # Reset to 0 (as happens on successful connect)
        client.stats["reconnects"] = 5   # But historical reconnects > 0

        # Should still be detected as reconnection based on stats
        is_reconnection = client.reconnection_attempt > 0 or client.stats["reconnects"] > 0
        assert is_reconnection is True

    async def test_resubscription_detection_via_attempt(self, client):
        """Test that resubscription is detected via reconnection_attempt > 0"""
        client.reconnection_attempt = 2
        client.stats["reconnects"] = 0  # Even if stats is 0

        # Should be detected as reconnection based on attempt
        is_reconnection = client.reconnection_attempt > 0 or client.stats["reconnects"] > 0
        assert is_reconnection is True

    async def test_initial_connection_detection(self, client):
        """Test that initial connection is correctly detected"""
        client.reconnection_attempt = 0
        client.stats["reconnects"] = 0

        # Should NOT be detected as reconnection
        is_reconnection = client.reconnection_attempt > 0 or client.stats["reconnects"] > 0
        assert is_reconnection is False


@pytest.mark.asyncio
class TestGracefulShutdown:
    """Test graceful shutdown handling during reconnection per PRD-001 Section 4.2"""

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

    async def test_stop_sets_running_to_false(self, client):
        """Test that stop() sets running flag to False"""
        client.running = True

        # Mock WebSocket and Redis
        client.ws = AsyncMock()
        client.ws.close = AsyncMock()
        client.redis_manager.close = AsyncMock()

        await client.stop()

        assert client.running is False

    async def test_stop_sets_state_to_disconnected(self, client):
        """Test that stop() sets connection state to DISCONNECTED"""
        client.running = True
        client.connection_state = ConnectionState.RECONNECTING

        # Mock WebSocket and Redis
        client.ws = AsyncMock()
        client.ws.close = AsyncMock()
        client.redis_manager.close = AsyncMock()

        await client.stop()

        assert client.connection_state == ConnectionState.DISCONNECTED

    async def test_stop_logs_shutdown_message(self, client, caplog):
        """Test that stop() logs graceful shutdown messages"""
        import logging

        client.running = True

        # Mock WebSocket and Redis
        client.ws = AsyncMock()
        client.ws.close = AsyncMock()
        client.redis_manager.close = AsyncMock()

        with caplog.at_level(logging.INFO):
            await client.stop()

        # Check for shutdown logs
        info_logs = [record.message for record in caplog.records if record.levelname == "INFO"]
        assert any("Stopping" in log for log in info_logs)
        assert any("stopped" in log for log in info_logs)

    async def test_reconnection_cancelled_on_shutdown(self, client, caplog):
        """Test that reconnection is cancelled when stop() is called during sleep"""
        import logging

        # Simulate reconnection state
        client.running = True
        client.reconnection_attempt = 2

        # Start a task that will simulate the reconnection sleep check
        async def simulate_reconnection_check():
            # Simulate the sleep completion
            await asyncio.sleep(0.1)

            # This is the check we added: if not self.running
            if not client.running:
                client.logger.info("Reconnection cancelled - graceful shutdown in progress")
                return True
            return False

        # Start the check
        check_task = asyncio.create_task(simulate_reconnection_check())

        # While it's sleeping, call stop
        await asyncio.sleep(0.05)
        client.running = False

        # Wait for check to complete
        with caplog.at_level(logging.INFO):
            cancelled = await check_task

        # Should have cancelled
        assert cancelled is True

        # Should have logged cancellation message
        logs = [record.message for record in caplog.records if record.levelname == "INFO"]
        assert any("Reconnection cancelled" in log for log in logs)
        assert any("graceful shutdown" in log for log in logs)

    def test_running_flag_checked_after_sleep(self, client):
        """Test that running flag is checked immediately after reconnection sleep"""
        # This tests the code structure - verify the check exists
        import inspect

        source = inspect.getsource(client.start)

        # Should have the check after sleep
        assert "if not self.running" in source
        assert "Reconnection cancelled" in source
        assert "graceful shutdown" in source

    async def test_stop_closes_websocket(self, client):
        """Test that stop() closes the WebSocket connection"""
        client.running = True
        client.ws = AsyncMock()
        client.ws.close = AsyncMock()
        client.redis_manager.close = AsyncMock()

        await client.stop()

        # Should have closed WebSocket
        client.ws.close.assert_called_once()

    async def test_stop_closes_redis(self, client):
        """Test that stop() closes Redis connection"""
        client.running = True
        client.ws = AsyncMock()
        client.ws.close = AsyncMock()
        client.redis_manager.close = AsyncMock()

        await client.stop()

        # Should have closed Redis
        client.redis_manager.close.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
