"""
Tests for Redis Cloud TLS connection utility.

Tests the RedisCloudClient with proper mocking to avoid external dependencies
while ensuring all functionality works correctly.
"""

import os
import ssl
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import redis.asyncio as redis
from pydantic import ValidationError

from agents.infrastructure.redis_client import (
    RedisCloudClient,
    RedisCloudConfig,
    check_redis_cloud_health,
    create_data_pipeline_redis_client,
    create_kraken_ingestor_redis_client,
    get_redis_cloud_client,
    redis_cloud_connection,
)


class TestRedisCloudConfig:
    """Test Redis Cloud configuration validation."""

    def test_default_config(self):
        """Test default configuration values."""
        config = RedisCloudConfig()
        assert config.url == "rediss://localhost:6380"
        assert config.connect_timeout == 10.0
        assert config.socket_timeout == 10.0
        assert config.max_retries == 5
        assert config.base_delay == 0.5
        assert config.max_delay == 30.0
        assert config.max_connections == 20
        assert config.client_name == "crypto-ai-bot-cloud"
        assert config.decode_responses is True

    def test_config_validation_url(self):
        """Test URL validation requires TLS."""
        # Valid TLS URL
        config = RedisCloudConfig(url="rediss://example.com:6380")
        assert config.url == "rediss://example.com:6380"
        
        # Invalid non-TLS URL
        with pytest.raises(ValidationError, match="Redis Cloud requires TLS connection"):
            RedisCloudConfig(url="redis://example.com:6379")

    def test_config_validation_timeouts(self):
        """Test timeout validation."""
        # Valid timeouts
        config = RedisCloudConfig(connect_timeout=5.0, socket_timeout=5.0)
        assert config.connect_timeout == 5.0
        assert config.socket_timeout == 5.0
        
        # Invalid timeouts
        with pytest.raises(ValidationError):
            RedisCloudConfig(connect_timeout=0.5)  # Too low
        with pytest.raises(ValidationError):
            RedisCloudConfig(socket_timeout=70.0)  # Too high

    def test_config_validation_retries(self):
        """Test retry configuration validation."""
        # Valid retries
        config = RedisCloudConfig(max_retries=10, base_delay=1.0, max_delay=60.0)
        assert config.max_retries == 10
        assert config.base_delay == 1.0
        assert config.max_delay == 60.0
        
        # Invalid retries
        with pytest.raises(ValidationError):
            RedisCloudConfig(max_retries=0)  # Too low
        with pytest.raises(ValidationError):
            RedisCloudConfig(base_delay=0.05)  # Too low
        with pytest.raises(ValidationError):
            RedisCloudConfig(max_delay=400.0)  # Too high

    def test_config_validation_certificates(self):
        """Test certificate path validation."""
        # Valid certificate paths
        with tempfile.NamedTemporaryFile() as ca_cert:
            config = RedisCloudConfig(ca_cert_path=ca_cert.name)
            assert config.ca_cert_path == ca_cert.name
        
        # Invalid certificate paths
        with pytest.raises(FileNotFoundError):
            RedisCloudConfig(ca_cert_path="/nonexistent/ca.crt")
        with pytest.raises(FileNotFoundError):
            RedisCloudConfig(client_cert_path="/nonexistent/client.crt")
        with pytest.raises(FileNotFoundError):
            RedisCloudConfig(client_key_path="/nonexistent/client.key")

    def test_config_from_env(self):
        """Test configuration from environment variables."""
        with patch.dict(os.environ, {
            "REDIS_URL": "rediss://test.example.com:6380",
            "REDIS_CA_CERT": "/test/ca.crt",
            "REDIS_CLIENT_CERT": "/test/client.crt",
            "REDIS_CLIENT_KEY": "/test/client.key",
        }):
            config = RedisCloudConfig()
            assert config.url == "rediss://test.example.com:6380"
            assert config.ca_cert_path == "/test/ca.crt"
            assert config.client_cert_path == "/test/client.crt"
            assert config.client_key_path == "/test/client.key"


class TestRedisCloudClient:
    """Test Redis Cloud client functionality."""

    @pytest.fixture
    def mock_redis_client(self):
        """Create a mock Redis client."""
        client = AsyncMock(spec=redis.Redis)
        client.ping = AsyncMock(return_value=True)
        client.aclose = AsyncMock()
        return client

    @pytest.fixture
    def mock_ssl_context(self):
        """Create a mock SSL context."""
        context = MagicMock(spec=ssl.SSLContext)
        return context

    @pytest.fixture
    def config(self):
        """Create a test configuration."""
        return RedisCloudConfig(
            url="rediss://test.example.com:6380",
            max_retries=3,
            base_delay=0.1,
            max_delay=1.0,
        )

    @pytest.fixture
    def client(self, config):
        """Create a Redis Cloud client with test configuration."""
        return RedisCloudClient(config)

    def test_init(self, config):
        """Test client initialization."""
        client = RedisCloudClient(config)
        assert client.config == config
        assert client._client is None
        assert client._is_connected is False
        assert client._health_checker is not None

    @patch('agents.infrastructure.redis_client.redis.from_url')
    @patch('agents.infrastructure.redis_client.ssl.create_default_context')
    async def test_connect_success(self, mock_ssl_context, mock_from_url, client, mock_redis_client):
        """Test successful connection."""
        mock_from_url.return_value = mock_redis_client
        mock_ssl_context.return_value = MagicMock(spec=ssl.SSLContext)
        
        await client.connect()
        
        assert client._is_connected is True
        assert client._client == mock_redis_client
        mock_from_url.assert_called_once()
        mock_redis_client.ping.assert_called_once()

    @patch('agents.infrastructure.redis_client.redis.from_url')
    async def test_connect_failure_retry(self, mock_from_url, client):
        """Test connection failure with retry logic."""
        mock_from_url.side_effect = [
            redis.ConnectionError("Connection failed"),
            redis.ConnectionError("Connection failed"),
            AsyncMock(spec=redis.Redis)
        ]
        
        # Mock the ping method for successful connection
        mock_client = AsyncMock(spec=redis.Redis)
        mock_client.ping = AsyncMock(return_value=True)
        mock_from_url.side_effect = [
            redis.ConnectionError("Connection failed"),
            redis.ConnectionError("Connection failed"),
            mock_client
        ]
        
        await client.connect()
        
        assert client._is_connected is True
        assert mock_from_url.call_count == 3

    @patch('agents.infrastructure.redis_client.redis.from_url')
    async def test_connect_max_retries_exceeded(self, mock_from_url, client):
        """Test connection failure when max retries exceeded."""
        mock_from_url.side_effect = redis.ConnectionError("Connection failed")
        
        with pytest.raises(redis.ConnectionError):
            await client.connect()
        
        assert client._is_connected is False
        assert mock_from_url.call_count == client.config.max_retries

    async def test_disconnect(self, client, mock_redis_client):
        """Test disconnection."""
        client._client = mock_redis_client
        client._is_connected = True
        
        await client.disconnect()
        
        assert client._is_connected is False
        assert client._client is None
        mock_redis_client.aclose.assert_called_once()

    async def test_disconnect_no_client(self, client):
        """Test disconnection when no client exists."""
        await client.disconnect()  # Should not raise
        
        assert client._is_connected is False
        assert client._client is None

    @patch('agents.infrastructure.redis_client.redis.from_url')
    async def test_context_manager(self, mock_from_url, client, mock_redis_client):
        """Test context manager functionality."""
        mock_from_url.return_value = mock_redis_client
        
        async with client as ctx:
            assert ctx is client
            assert client._is_connected is True
        
        assert client._is_connected is False
        mock_redis_client.aclose.assert_called_once()

    @patch('agents.infrastructure.redis_client.redis.from_url')
    async def test_ping_success(self, mock_from_url, client, mock_redis_client):
        """Test successful ping."""
        mock_from_url.return_value = mock_redis_client
        await client.connect()
        
        result = await client.ping()
        
        assert result is True
        mock_redis_client.ping.assert_called()

    @patch('agents.infrastructure.redis_client.redis.from_url')
    async def test_ping_failure_retry(self, mock_from_url, client, mock_redis_client):
        """Test ping failure with retry logic."""
        mock_from_url.return_value = mock_redis_client
        mock_redis_client.ping.side_effect = [
            redis.ConnectionError("Ping failed"),
            redis.ConnectionError("Ping failed"),
            True
        ]
        await client.connect()
        
        result = await client.ping()
        
        assert result is True
        assert mock_redis_client.ping.call_count == 3

    @patch('agents.infrastructure.redis_client.redis.from_url')
    async def test_ping_max_retries_exceeded(self, mock_from_url, client, mock_redis_client):
        """Test ping failure when max retries exceeded."""
        mock_from_url.return_value = mock_redis_client
        mock_redis_client.ping.side_effect = redis.ConnectionError("Ping failed")
        await client.connect()
        
        result = await client.ping()
        
        assert result is False
        assert mock_redis_client.ping.call_count == client.config.max_retries

    async def test_ping_not_connected(self, client):
        """Test ping when not connected."""
        with pytest.raises(RuntimeError, match="Client not connected"):
            await client.ping()

    async def test_health_check(self, client):
        """Test health check functionality."""
        mock_health_result = MagicMock()
        client._health_checker.check_health = AsyncMock(return_value=mock_health_result)
        
        result = await client.health_check()
        
        assert result == mock_health_result
        client._health_checker.check_health.assert_called_once()

    async def test_health_check_no_checker(self, client):
        """Test health check when no health checker exists."""
        client._health_checker = None
        
        result = await client.health_check()
        
        assert result.connected is False
        assert "Health checker not initialized" in result.error_message

    def test_getattr_delegation(self, client, mock_redis_client):
        """Test attribute delegation to underlying client."""
        client._client = mock_redis_client
        client._is_connected = True
        
        # Test that attributes are delegated
        assert client.ping == mock_redis_client.ping
        assert client.set == mock_redis_client.set
        assert client.get == mock_redis_client.get

    def test_getattr_not_connected(self, client):
        """Test attribute access when not connected."""
        with pytest.raises(RuntimeError, match="Client not connected"):
            _ = client.ping

    @patch('agents.infrastructure.redis_client.ssl.create_default_context')
    def test_build_ssl_context_with_ca_cert(self, mock_ssl_context, config):
        """Test SSL context building with CA certificate."""
        with tempfile.NamedTemporaryFile() as ca_cert:
            config.ca_cert_path = ca_cert.name
            client = RedisCloudClient(config)
            
            context = client._build_ssl_context()
            
            assert context is not None
            mock_ssl_context.assert_called_once_with(cafile=ca_cert.name)

    @patch('agents.infrastructure.redis_client.ssl.create_default_context')
    def test_build_ssl_context_with_mtls(self, mock_ssl_context, config):
        """Test SSL context building with mTLS certificates."""
        with tempfile.NamedTemporaryFile() as ca_cert, \
             tempfile.NamedTemporaryFile() as client_cert, \
             tempfile.NamedTemporaryFile() as client_key:
            
            config.ca_cert_path = ca_cert.name
            config.client_cert_path = client_cert.name
            config.client_key_path = client_key.name
            client = RedisCloudClient(config)
            
            mock_context = MagicMock(spec=ssl.SSLContext)
            mock_ssl_context.return_value = mock_context
            
            context = client._build_ssl_context()
            
            assert context == mock_context
            mock_context.load_cert_chain.assert_called_once_with(
                client_cert.name, client_key.name
            )

    def test_get_connection_params(self, config):
        """Test connection parameters generation."""
        client = RedisCloudClient(config)
        
        with patch.object(client, '_build_ssl_context') as mock_ssl:
            mock_ssl.return_value = MagicMock(spec=ssl.SSLContext)
            params = client._get_connection_params()
            
            assert params["socket_timeout"] == config.socket_timeout
            assert params["socket_connect_timeout"] == config.connect_timeout
            assert params["retry_on_timeout"] == config.retry_on_timeout
            assert params["health_check_interval"] == config.health_check_interval
            assert params["decode_responses"] == config.decode_responses
            assert params["client_name"] == config.client_name
            assert params["max_connections"] == config.max_connections
            assert params["ssl"] is True
            assert params["ssl_context"] is not None

    async def test_exponential_backoff_delay(self, client):
        """Test exponential backoff delay calculation."""
        # Test with jitter (should be within expected range)
        delays = []
        for attempt in range(5):
            delay = await client._exponential_backoff_delay(attempt)
            delays.append(delay)
        
        # Delays should generally increase with attempt number
        assert all(0 <= delay <= client.config.max_delay for delay in delays)
        assert delays[1] > delays[0]  # Generally increasing


class TestConvenienceFunctions:
    """Test convenience functions and integration helpers."""

    @pytest.fixture
    def config(self):
        """Create a test configuration."""
        return RedisCloudConfig(
            url="rediss://test.example.com:6380",
            max_retries=1,
            base_delay=0.1,
            max_delay=1.0,
        )

    @patch('agents.infrastructure.redis_client.RedisCloudClient')
    async def test_get_redis_cloud_client(self, mock_client_class, config):
        """Test get_redis_cloud_client convenience function."""
        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client
        
        result = await get_redis_cloud_client(config)
        
        assert result == mock_client
        mock_client_class.assert_called_once_with(config)
        mock_client.connect.assert_called_once()

    @patch('agents.infrastructure.redis_client.RedisCloudClient')
    async def test_redis_cloud_connection_context_manager(self, mock_client_class, config):
        """Test redis_cloud_connection context manager."""
        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client
        
        async with redis_cloud_connection(config) as client:
            assert client == mock_client
            mock_client.connect.assert_called_once()
        
        mock_client.disconnect.assert_called_once()

    @patch('agents.infrastructure.redis_client.RedisCloudClient')
    async def test_create_data_pipeline_redis_client(self, mock_client_class):
        """Test create_data_pipeline_redis_client integration helper."""
        mock_client = AsyncMock()
        mock_redis_client = AsyncMock(spec=redis.Redis)
        mock_client._client = mock_redis_client
        mock_client_class.return_value = mock_client
        
        result = await create_data_pipeline_redis_client()
        
        assert result == mock_redis_client
        mock_client.connect.assert_called_once()

    @patch('agents.infrastructure.redis_client.RedisCloudClient')
    async def test_create_kraken_ingestor_redis_client(self, mock_client_class):
        """Test create_kraken_ingestor_redis_client integration helper."""
        mock_client = AsyncMock()
        mock_redis_client = AsyncMock(spec=redis.Redis)
        mock_client._client = mock_redis_client
        mock_client_class.return_value = mock_client
        
        result = await create_kraken_ingestor_redis_client()
        
        assert result == mock_redis_client
        mock_client.connect.assert_called_once()

    @patch('agents.infrastructure.redis_client.RedisHealthChecker')
    async def test_check_redis_cloud_health(self, mock_checker_class, config):
        """Test check_redis_cloud_health utility function."""
        mock_checker = AsyncMock()
        mock_health_result = MagicMock()
        mock_checker.check_health = AsyncMock(return_value=mock_health_result)
        mock_checker_class.return_value = mock_checker
        
        result = await check_redis_cloud_health(config)
        
        assert result == mock_health_result
        mock_checker_class.assert_called_once()
        mock_checker.check_health.assert_called_once()


class TestIntegrationScenarios:
    """Test integration scenarios and edge cases."""

    @pytest.mark.asyncio
    async def test_full_connection_lifecycle(self):
        """Test complete connection lifecycle with mocking."""
        config = RedisCloudConfig(
            url="rediss://test.example.com:6380",
            max_retries=1,
            base_delay=0.1,
            max_delay=1.0,
        )
        
        with patch('agents.infrastructure.redis_client.redis.from_url') as mock_from_url:
            mock_client = AsyncMock(spec=redis.Redis)
            mock_client.ping = AsyncMock(return_value=True)
            mock_client.aclose = AsyncMock()
            mock_from_url.return_value = mock_client
            
            client = RedisCloudClient(config)
            
            # Test connection
            await client.connect()
            assert client._is_connected is True
            
            # Test ping
            result = await client.ping()
            assert result is True
            
            # Test disconnection
            await client.disconnect()
            assert client._is_connected is False
            mock_client.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager_with_exception(self):
        """Test context manager behavior when exception occurs."""
        config = RedisCloudConfig(
            url="rediss://test.example.com:6380",
            max_retries=1,
            base_delay=0.1,
            max_delay=1.0,
        )
        
        with patch('agents.infrastructure.redis_client.redis.from_url') as mock_from_url:
            mock_client = AsyncMock(spec=redis.Redis)
            mock_client.ping = AsyncMock(return_value=True)
            mock_client.aclose = AsyncMock()
            mock_from_url.return_value = mock_client
            
            client = RedisCloudClient(config)
            
            # Test context manager with exception
            try:
                async with client:
                    assert client._is_connected is True
                    raise ValueError("Test exception")
            except ValueError:
                pass
            
            # Should still disconnect even with exception
            assert client._is_connected is False
            mock_client.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_ssl_context_building_scenarios(self):
        """Test SSL context building in various scenarios."""
        # Test with no certificates
        config = RedisCloudConfig(url="rediss://test.example.com:6380")
        client = RedisCloudClient(config)
        
        with patch('agents.infrastructure.redis_client.ssl.create_default_context') as mock_ssl:
            mock_context = MagicMock(spec=ssl.SSLContext)
            mock_ssl.return_value = mock_context
            
            context = client._build_ssl_context()
            
            assert context == mock_context
            mock_ssl.assert_called_once()
            # Should not call load_cert_chain without client certs
            mock_context.load_cert_chain.assert_not_called()

    @pytest.mark.asyncio
    async def test_retry_logic_with_different_errors(self):
        """Test retry logic with different types of errors."""
        config = RedisCloudConfig(
            url="rediss://test.example.com:6380",
            max_retries=3,
            base_delay=0.1,
            max_delay=1.0,
        )
        
        with patch('agents.infrastructure.redis_client.redis.from_url') as mock_from_url:
            # Test with different error types
            mock_from_url.side_effect = [
                redis.ConnectionError("Connection failed"),
                redis.TimeoutError("Timeout"),
                AsyncMock(spec=redis.Redis)
            ]
            
            client = RedisCloudClient(config)
            
            # Should retry and eventually succeed
            await client.connect()
            assert client._is_connected is True
            assert mock_from_url.call_count == 3
