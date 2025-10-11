"""
Tests for health utilities (Redis and Kraken WebSocket).

Tests both Redis Cloud TLS connection utility and Kraken WebSocket health checker
with proper mocking to avoid external dependencies.
"""

import asyncio
import json
import ssl
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import redis.asyncio as redis
import websockets

from agents.infrastructure.redis_health import (
    RedisHealthChecker,
    RedisHealthConfig,
    RedisHealthResult,
    check_redis_health,
)
from scripts.kraken_ws_health import (
    KrakenWSHealthChecker,
    KrakenWSHealthConfig,
    KrakenWSHealthResult,
    check_kraken_ws_health,
)


class TestRedisHealthConfig:
    """Test Redis health configuration."""

    def test_default_config(self):
        """Test default configuration values."""
        config = RedisHealthConfig()
        assert config.max_retries == 3
        assert config.base_delay == 0.5
        assert config.max_delay == 10.0
        assert config.connect_timeout == 5.0
        assert config.socket_timeout == 5.0
        assert config.ping_timeout == 2.0
        assert config.memory_threshold_mb == 100

    def test_config_validation(self):
        """Test configuration validation."""
        # Valid config
        config = RedisHealthConfig(max_retries=5, base_delay=1.0, max_delay=20.0)
        assert config.max_retries == 5
        assert config.base_delay == 1.0
        assert config.max_delay == 20.0

        # Invalid config should raise validation error
        with pytest.raises(ValueError):
            RedisHealthConfig(max_retries=0)  # Should be >= 1

        with pytest.raises(ValueError):
            RedisHealthConfig(base_delay=-1.0)  # Should be >= 0.1


class TestRedisHealthChecker:
    """Test Redis health checker functionality."""

    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return RedisHealthConfig(
            url="rediss://test.redis.com:6380",
            ca_cert_path="/path/to/ca.crt",
            max_retries=2,
            base_delay=0.1,
            max_delay=2.0,  # Increased to accommodate jitter
        )

    @pytest.fixture
    def checker(self, config):
        """Create health checker instance."""
        return RedisHealthChecker(config)

    def test_build_ssl_context_success(self, checker):
        """Test SSL context building with valid certificates."""
        with patch("os.path.exists", return_value=True):
            with patch("ssl.create_default_context") as mock_ssl:
                mock_ctx = MagicMock()
                mock_ssl.return_value = mock_ctx

                ctx = checker._build_ssl_context()

                assert ctx is not None
                mock_ssl.assert_called_once_with(cafile=checker.config.ca_cert_path)
                mock_ctx.check_hostname = True
                mock_ctx.verify_mode = ssl.CERT_REQUIRED

    def test_build_ssl_context_no_ca_cert(self, checker):
        """Test SSL context building without CA certificate."""
        checker.config.ca_cert_path = None
        ctx = checker._build_ssl_context()
        assert ctx is None

    def test_build_ssl_context_missing_ca_cert(self, checker):
        """Test SSL context building with missing CA certificate."""
        with patch("os.path.exists", return_value=False):
            with pytest.raises(FileNotFoundError):
                checker._build_ssl_context()

    def test_build_ssl_context_with_mtls(self, checker):
        """Test SSL context building with mTLS certificates."""
        checker.config.client_cert_path = "/path/to/client.crt"
        checker.config.client_key_path = "/path/to/client.key"

        with patch("os.path.exists", return_value=True):
            with patch("ssl.create_default_context") as mock_ssl:
                mock_ctx = MagicMock()
                mock_ssl.return_value = mock_ctx

                ctx = checker._build_ssl_context()

                assert ctx is not None
                mock_ctx.load_cert_chain.assert_called_once_with(
                    checker.config.client_cert_path, checker.config.client_key_path
                )

    def test_get_connection_params_tls(self, checker):
        """Test connection parameters for TLS connection."""
        with patch("os.path.exists", return_value=True):
            with patch("ssl.create_default_context"):
                params = checker._get_connection_params()

        assert params["socket_timeout"] == checker.config.socket_timeout
        assert params["socket_connect_timeout"] == checker.config.connect_timeout
        assert params["decode_responses"] is False
        assert params["socket_keepalive"] is True
        assert "ssl" in params
        assert params["ssl"] is True
        assert "ssl_context" in params

    def test_get_connection_params_no_tls(self, checker):
        """Test connection parameters for non-TLS connection."""
        checker.config.url = "redis://test.redis.com:6379"
        params = checker._get_connection_params()

        assert "ssl" not in params
        assert "ssl_context" not in params

    def test_get_connection_params_no_url(self, checker):
        """Test connection parameters without URL."""
        checker.config.url = ""
        with pytest.raises(ValueError, match="Redis URL not configured"):
            checker._get_connection_params()

    @pytest.mark.asyncio
    async def test_exponential_backoff_delay(self, checker):
        """Test exponential backoff delay calculation."""
        # Test first few attempts
        delay1 = await checker._exponential_backoff_delay(0)
        delay2 = await checker._exponential_backoff_delay(1)
        delay3 = await checker._exponential_backoff_delay(2)

        assert 0.1 <= delay1 <= 0.2  # base_delay + jitter
        assert 0.2 <= delay2 <= 0.4  # base_delay * 2 + jitter
        assert 0.4 <= delay3 <= 0.8  # base_delay * 4 + jitter

        # Test max delay cap
        delay_large = await checker._exponential_backoff_delay(10)
        assert delay_large <= checker.config.max_delay

    @pytest.mark.asyncio
    async def test_check_health_success(self, checker):
        """Test successful health check."""
        mock_client = AsyncMock()
        mock_client.ping.return_value = True
        mock_client.info.return_value = {
            "used_memory": 50 * 1024 * 1024,  # 50MB
            "connected_clients": 5,
        }
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch.object(checker, "_create_client", return_value=mock_client):
            with patch("asyncio.wait_for", side_effect=lambda coro, timeout: coro):
                result = await checker.check_health()

        assert result.connected is True
        assert result.latency_ms >= 0
        assert result.memory_usage_mb == 50.0
        assert result.memory_usage_percent == 50.0  # 50MB / 100MB threshold
        assert result.connection_count == 5
        assert result.error_message is None

    @pytest.mark.asyncio
    async def test_check_health_connection_failure(self, checker):
        """Test health check with connection failure."""
        with patch.object(
            checker,
            "_create_client",
            side_effect=redis.ConnectionError("Connection failed"),
        ):
            result = await checker.check_health()

        assert result.connected is False
        assert "Connection error" in result.error_message

    @pytest.mark.asyncio
    async def test_check_health_timeout(self, checker):
        """Test health check with timeout."""
        with patch.object(
            checker, "_create_client", side_effect=asyncio.TimeoutError("Timeout")
        ):
            result = await checker.check_health()

        assert result.connected is False
        assert "Connection timeout" in result.error_message

    @pytest.mark.asyncio
    async def test_check_health_retry_mechanism(self, checker):
        """Test health check retry mechanism."""
        mock_client = AsyncMock()
        mock_client.ping.side_effect = [
            redis.ConnectionError("Fail"),
            redis.ConnectionError("Fail"),
            True,
        ]
        mock_client.info.return_value = {"used_memory": 0, "connected_clients": 0}
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch.object(checker, "_create_client", return_value=mock_client):
            with patch("asyncio.wait_for", side_effect=lambda coro, timeout: coro):
                with patch("asyncio.sleep"):  # Mock sleep to speed up test
                    result = await checker.check_health()

        assert result.connected is True
        assert mock_client.ping.call_count == 3  # Two failures + one success

    @pytest.mark.asyncio
    async def test_check_health_simple_success(self, checker):
        """Test simple health check success."""
        with patch.object(
            checker, "check_health", return_value=RedisHealthResult(connected=True)
        ):
            result = await checker.check_health_simple()

        assert result is True

    @pytest.mark.asyncio
    async def test_check_health_simple_failure(self, checker):
        """Test simple health check failure."""
        with patch.object(
            checker,
            "check_health",
            return_value=RedisHealthResult(connected=False, error_message="Test error"),
        ):
            result = await checker.check_health_simple()

        assert result is False


class TestRedisHealthConvenienceFunction:
    """Test Redis health convenience function."""

    @pytest.mark.asyncio
    async def test_check_redis_health_success(self):
        """Test convenience function with successful check."""
        with patch(
            "agents.infrastructure.redis_health.RedisHealthChecker"
        ) as mock_checker_class:
            mock_checker = AsyncMock()
            mock_checker.check_health.return_value = RedisHealthResult(connected=True)
            mock_checker_class.return_value = mock_checker

            result = await check_redis_health(url="redis://test.com")

            assert result.connected is True
            mock_checker_class.assert_called_once()
            mock_checker.check_health.assert_called_once()


class TestKrakenWSHealthConfig:
    """Test Kraken WebSocket health configuration."""

    def test_default_config(self):
        """Test default configuration values."""
        config = KrakenWSHealthConfig()
        assert config.url == "wss://ws.kraken.com"
        assert config.pairs == ["BTC/USD", "ETH/USD"]
        assert config.ping_interval == 20
        assert config.close_timeout == 5
        assert config.connect_timeout == 10.0
        assert config.max_reconnects == 5
        assert config.reconnect_delay == 3.0
        assert config.heartbeat_timeout == 60.0
        assert config.data_timeout == 30.0
        assert config.test_duration == 30.0

    def test_config_validation(self):
        """Test configuration validation."""
        # Valid config
        config = KrakenWSHealthConfig(
            max_reconnects=10, reconnect_delay=5.0, test_duration=60.0
        )
        assert config.max_reconnects == 10
        assert config.reconnect_delay == 5.0
        assert config.test_duration == 60.0

        # Invalid config should raise validation error
        with pytest.raises(ValueError):
            KrakenWSHealthConfig(max_reconnects=0)  # Should be >= 1

        with pytest.raises(ValueError):
            KrakenWSHealthConfig(reconnect_delay=0.5)  # Should be >= 1.0


class TestKrakenWSHealthChecker:
    """Test Kraken WebSocket health checker functionality."""

    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return KrakenWSHealthConfig(
            url="wss://test.kraken.com",
            pairs=["BTC/USD"],
            test_duration=5.0,
            max_reconnects=2,
            reconnect_delay=1.0,  # Must be >= 1.0
        )

    @pytest.fixture
    def checker(self, config):
        """Create health checker instance."""
        return KrakenWSHealthChecker(config)

    def test_create_subscription(self, checker):
        """Test subscription message creation."""
        sub = checker._create_subscription("trade", ["BTC/USD"], depth=10)

        expected = {
            "event": "subscribe",
            "pair": ["BTC/USD"],
            "subscription": {"name": "trade", "depth": 10},
        }
        assert sub == expected

    @pytest.mark.asyncio
    async def test_handle_message_heartbeat(self, checker):
        """Test handling heartbeat messages."""
        message = json.dumps({"event": "heartbeat"})
        initial_heartbeat = checker.last_heartbeat

        await checker._handle_message(message)

        assert checker.last_heartbeat > initial_heartbeat
        assert checker.messages_received == 1

    @pytest.mark.asyncio
    async def test_handle_message_subscription_status(self, checker):
        """Test handling subscription status messages."""
        # Successful subscription
        message = json.dumps(
            {
                "event": "subscriptionStatus",
                "status": "subscribed",
                "subscription": {"name": "trade"},
            }
        )

        await checker._handle_message(message)
        assert checker.messages_received == 1

        # Failed subscription
        message = json.dumps(
            {
                "event": "subscriptionStatus",
                "status": "error",
                "errorMessage": "Invalid pair",
            }
        )

        await checker._handle_message(message)
        assert checker.messages_received == 2

    @pytest.mark.asyncio
    async def test_handle_message_data(self, checker):
        """Test handling data messages."""
        message = json.dumps([1, [], "trade", "BTC/USD"])

        await checker._handle_message(message)

        assert checker.messages_received == 1
        assert checker.last_data > time.time() - 1  # Should be recent

    @pytest.mark.asyncio
    async def test_handle_message_invalid_json(self, checker):
        """Test handling invalid JSON messages."""
        initial_messages = checker.messages_received

        await checker._handle_message("invalid json")

        # Should not increment message count for invalid JSON
        assert checker.messages_received == initial_messages

    @pytest.mark.asyncio
    async def test_setup_subscriptions(self, checker):
        """Test subscription setup."""
        mock_ws = AsyncMock()
        checker.ws = mock_ws

        await checker._setup_subscriptions()

        # Should send trade and spread subscriptions
        assert mock_ws.send.call_count == 2

        # Check that correct subscriptions were sent
        calls = mock_ws.send.call_args_list
        sent_messages = [json.loads(call[0][0]) for call in calls]

        subscription_names = [msg["subscription"]["name"] for msg in sent_messages]
        assert "trade" in subscription_names
        assert "spread" in subscription_names

    @pytest.mark.asyncio
    async def test_check_health_status_healthy(self, checker):
        """Test health status check when healthy."""
        checker.last_heartbeat = time.time() - 10  # 10 seconds ago
        checker.last_data = time.time() - 5  # 5 seconds ago

        result = await checker._check_health_status()
        assert result is True

    @pytest.mark.asyncio
    async def test_check_health_status_stale_heartbeat(self, checker):
        """Test health status check with stale heartbeat."""
        checker.last_heartbeat = (
            time.time() - 70
        )  # 70 seconds ago (exceeds 60s timeout)
        checker.last_data = time.time() - 5  # 5 seconds ago

        result = await checker._check_health_status()
        assert result is False

    @pytest.mark.asyncio
    async def test_check_health_status_stale_data(self, checker):
        """Test health status check with stale data."""
        checker.last_heartbeat = time.time() - 10  # 10 seconds ago
        checker.last_data = time.time() - 40  # 40 seconds ago (exceeds 30s timeout)

        result = await checker._check_health_status()
        assert result is False

    @pytest.mark.asyncio
    async def test_connect_once_success(self, checker):
        """Test successful single connection."""
        mock_ws = AsyncMock()
        mock_ws.__aenter__.return_value = mock_ws
        mock_ws.__aexit__.return_value = None

        with patch("websockets.connect", return_value=mock_ws):
            with patch.object(checker, "_setup_subscriptions"):
                with patch.object(checker, "_handle_message"):
                    # Mock the async iterator for messages
                    mock_ws.__aiter__.return_value = []

                    result = await checker._connect_once()

        assert result is True

    @pytest.mark.asyncio
    async def test_connect_once_failure(self, checker):
        """Test failed single connection."""
        with patch(
            "websockets.connect",
            side_effect=websockets.exceptions.ConnectionClosed(None, None),
        ):
            result = await checker._connect_once()

        assert result is False

    @pytest.mark.asyncio
    async def test_run_health_check_success(self, checker):
        """Test successful health check run."""
        with patch.object(checker, "_connect_once", return_value=True):
            with patch.object(checker, "_check_health_status", return_value=True):
                with patch("asyncio.sleep"):  # Mock sleep to speed up test
                    result = await checker.run_health_check()

        assert result.connected is True
        assert result.test_duration > 0
        assert result.reconnects == 0

    @pytest.mark.asyncio
    async def test_run_health_check_max_reconnects(self, checker):
        """Test health check with max reconnects reached."""
        with patch.object(checker, "_connect_once", return_value=False):
            with patch("asyncio.sleep"):  # Mock sleep to speed up test
                result = await checker.run_health_check()

        assert result.connected is False
        assert result.reconnects == checker.config.max_reconnects
        assert "Max reconnects" in result.error_message

    @pytest.mark.asyncio
    async def test_run_health_check_health_failure(self, checker):
        """Test health check with health status failure."""
        with patch.object(checker, "_connect_once", return_value=True):
            with patch.object(checker, "_check_health_status", return_value=False):
                with patch("asyncio.sleep"):  # Mock sleep to speed up test
                    result = await checker.run_health_check()

        assert result.connected is False
        assert result.reconnects > 0


class TestKrakenWSHealthConvenienceFunction:
    """Test Kraken WebSocket health convenience function."""

    @pytest.mark.asyncio
    async def test_check_kraken_ws_health_success(self):
        """Test convenience function with successful check."""
        with patch(
            "scripts.kraken_ws_health.KrakenWSHealthChecker"
        ) as mock_checker_class:
            mock_checker = AsyncMock()
            mock_checker.run_health_check.return_value = KrakenWSHealthResult(
                connected=True
            )
            mock_checker_class.return_value = mock_checker

            result = await check_kraken_ws_health(
                url="wss://test.com", pairs=["BTC/USD"]
            )

            assert result.connected is True
            mock_checker_class.assert_called_once()
            mock_checker.run_health_check.assert_called_once()


class TestHealthResultModels:
    """Test health result model functionality."""

    def test_redis_health_result_defaults(self):
        """Test Redis health result default values."""
        result = RedisHealthResult()

        assert result.connected is False
        assert result.latency_ms == 0.0
        assert result.memory_usage_mb == 0.0
        assert result.memory_usage_percent == 0.0
        assert result.connection_count == 0
        assert result.error_message is None
        assert result.timestamp > 0

    def test_kraken_ws_health_result_defaults(self):
        """Test Kraken WebSocket health result default values."""
        result = KrakenWSHealthResult()

        assert result.connected is False
        assert result.reconnects == 0
        assert result.messages_received == 0
        assert result.last_heartbeat is None
        assert result.last_data is None
        assert result.latency_ms == 0.0
        assert result.error_message is None
        assert result.test_duration == 0.0
        assert result.timestamp > 0


@pytest.mark.asyncio
async def test_integration_redis_health_check():
    """Integration test for Redis health check (with mocked Redis)."""
    with patch("redis.asyncio.from_url") as mock_from_url:
        mock_client = AsyncMock()
        mock_client.ping.return_value = True
        mock_client.info.return_value = {
            "used_memory": 25 * 1024 * 1024,  # 25MB
            "connected_clients": 3,
        }
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_from_url.return_value = mock_client

        with patch("os.path.exists", return_value=True):
            with patch("ssl.create_default_context"):
                result = await check_redis_health(
                    url="rediss://test.redis.com:6380",
                    ca_cert_path="/path/to/ca.crt",
                    max_retries=1,
                )

        assert result.connected is True
        assert result.memory_usage_mb == 25.0
        assert result.connection_count == 3


@pytest.mark.asyncio
async def test_integration_kraken_ws_health_check():
    """Integration test for Kraken WebSocket health check (with mocked WebSocket)."""
    with patch("websockets.connect") as mock_connect:
        mock_ws = AsyncMock()
        mock_ws.__aenter__.return_value = mock_ws
        mock_ws.__aexit__.return_value = None
        mock_ws.__aiter__.return_value = []  # No messages
        mock_connect.return_value = mock_ws

        result = await check_kraken_ws_health(
            url="wss://test.kraken.com",
            pairs=["BTC/USD"],
            test_duration=1.0,
            max_reconnects=1,
        )

        # Should succeed even with no messages due to short test duration
        assert result.test_duration >= 1.0
