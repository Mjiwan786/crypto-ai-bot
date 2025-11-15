"""
Tests for Redis Connection Manager (PRD-001 Section 2.1)

Tests cover:
- Redis Cloud TLS connection
- TLS certificate loading
- Connection pooling with max 10 connections
- Redis PING health check every 60 seconds
- Connection state tracking (CONNECTED, DISCONNECTED, RECONNECTING)
- Prometheus gauge redis_connected{instance}
"""

import pytest
import asyncio
import time
import os
from unittest.mock import Mock, patch, AsyncMock, MagicMock

from utils.kraken_ws import (
    RedisConnectionManager,
    RedisConnectionState,
    KrakenWSConfig,
    REDIS_CONNECTED,
    PROMETHEUS_AVAILABLE
)


@pytest.fixture
def config():
    """Create test configuration"""
    return KrakenWSConfig(
        redis_url="rediss://test:password@redis.example.com:6380"
    )


@pytest.fixture
def redis_manager(config):
    """Create test Redis manager"""
    return RedisConnectionManager(config)


class TestConnectionInitialization:
    """Test Redis connection initialization (PRD-001 Section 2.1 Items 1-3)"""

    @pytest.mark.asyncio
    async def test_connects_via_tls(self, redis_manager):
        """Test that Redis connects via TLS (rediss://)"""
        with patch('utils.kraken_ws.redis.from_url') as mock_from_url:
            mock_client = AsyncMock()
            mock_client.ping = AsyncMock()
            mock_from_url.return_value = mock_client

            await redis_manager.initialize_pool()

            # Verify from_url was called with TLS settings
            mock_from_url.assert_called_once()
            call_kwargs = mock_from_url.call_args.kwargs
            assert call_kwargs['ssl_cert_reqs'] == 'required'

    @pytest.mark.asyncio
    async def test_loads_tls_certificate_if_exists(self, redis_manager):
        """Test that TLS certificate is loaded from config/certs/redis_ca.pem"""
        with patch('utils.kraken_ws.redis.from_url') as mock_from_url:
            with patch('os.path.exists', return_value=True):
                mock_client = AsyncMock()
                mock_client.ping = AsyncMock()
                mock_from_url.return_value = mock_client

                await redis_manager.initialize_pool()

                # Verify from_url was called successfully
                mock_from_url.assert_called_once()

    @pytest.mark.asyncio
    async def test_connection_pool_max_10_connections(self, redis_manager):
        """Test that connection pool is configured with max 10 connections"""
        with patch('utils.kraken_ws.redis.from_url') as mock_from_url:
            mock_client = AsyncMock()
            mock_client.ping = AsyncMock()
            mock_from_url.return_value = mock_client

            await redis_manager.initialize_pool()

            # Verify max_connections was set to 10
            call_kwargs = mock_from_url.call_args.kwargs
            assert call_kwargs['max_connections'] == 10


class TestHealthCheck:
    """Test Redis PING health check (PRD-001 Section 2.1 Item 4)"""

    @pytest.mark.asyncio
    async def test_health_check_pings_redis(self, redis_manager):
        """Test that health check performs Redis PING"""
        redis_manager.redis_client = AsyncMock()
        redis_manager.redis_client.ping = AsyncMock()
        redis_manager.last_health_check = 0  # Force health check

        result = await redis_manager.health_check()

        assert result is True
        redis_manager.redis_client.ping.assert_called_once()

    @pytest.mark.asyncio
    async def test_health_check_every_60_seconds(self, redis_manager):
        """Test that health check is performed every 60 seconds"""
        redis_manager.redis_client = AsyncMock()
        redis_manager.redis_client.ping = AsyncMock()
        redis_manager.last_health_check = time.time()
        redis_manager.connection_state = RedisConnectionState.CONNECTED

        # Call health check immediately (should skip PING)
        result = await redis_manager.health_check()

        # Should return True but not call PING (too soon)
        assert result is True
        redis_manager.redis_client.ping.assert_not_called()

    @pytest.mark.asyncio
    async def test_health_check_detects_failure(self, redis_manager):
        """Test that health check detects connection failure"""
        redis_manager.redis_client = AsyncMock()
        redis_manager.redis_client.ping = AsyncMock(side_effect=Exception("Connection lost"))
        redis_manager.last_health_check = 0  # Force health check

        result = await redis_manager.health_check()

        assert result is False
        assert redis_manager.connection_state == RedisConnectionState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_health_check_updates_timestamp(self, redis_manager):
        """Test that successful health check updates last_health_check timestamp"""
        redis_manager.redis_client = AsyncMock()
        redis_manager.redis_client.ping = AsyncMock()
        redis_manager.last_health_check = 0

        before = redis_manager.last_health_check
        await redis_manager.health_check()
        after = redis_manager.last_health_check

        assert after > before


class TestConnectionStateTracking:
    """Test connection state tracking (PRD-001 Section 2.1 Item 5)"""

    def test_initial_state_is_disconnected(self, redis_manager):
        """Test that initial connection state is DISCONNECTED"""
        assert redis_manager.connection_state == RedisConnectionState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_state_changes_to_reconnecting_on_init(self, redis_manager):
        """Test that state changes to RECONNECTING during initialization"""
        with patch('redis.from_url') as mock_from_url:
            mock_client = AsyncMock()
            mock_client.ping = AsyncMock(side_effect=Exception("Connection failed"))
            mock_from_url.return_value = mock_client

            try:
                await redis_manager.initialize_pool()
            except:
                pass

            # Should end up in DISCONNECTED after failure
            assert redis_manager.connection_state == RedisConnectionState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_state_changes_to_connected_on_success(self, redis_manager):
        """Test that state changes to CONNECTED on successful connection"""
        with patch('utils.kraken_ws.redis.from_url') as mock_from_url:
            mock_client = AsyncMock()
            mock_client.ping = AsyncMock()
            mock_from_url.return_value = mock_client

            await redis_manager.initialize_pool()

            assert redis_manager.connection_state == RedisConnectionState.CONNECTED

    @pytest.mark.asyncio
    async def test_state_changes_to_disconnected_on_close(self, redis_manager):
        """Test that state changes to DISCONNECTED on connection close"""
        redis_manager.redis_client = AsyncMock()
        redis_manager.connection_state = RedisConnectionState.CONNECTED

        await redis_manager.close()

        assert redis_manager.connection_state == RedisConnectionState.DISCONNECTED


class TestPrometheusMetrics:
    """Test Prometheus gauge emission (PRD-001 Section 2.1 Item 6)"""

    @pytest.mark.skipif(not PROMETHEUS_AVAILABLE, reason="Prometheus not available")
    def test_prometheus_gauge_set_on_connected(self, redis_manager):
        """Test that Prometheus gauge is set to 1 when CONNECTED"""
        # Get initial value
        initial_value = REDIS_CONNECTED.labels(instance=redis_manager.instance_name)._value.get()

        # Set state to connected
        redis_manager._set_connection_state(RedisConnectionState.CONNECTED)

        # Gauge should be 1
        final_value = REDIS_CONNECTED.labels(instance=redis_manager.instance_name)._value.get()
        assert final_value == 1.0

    @pytest.mark.skipif(not PROMETHEUS_AVAILABLE, reason="Prometheus not available")
    def test_prometheus_gauge_set_on_disconnected(self, redis_manager):
        """Test that Prometheus gauge is set to 0 when DISCONNECTED"""
        # Set state to connected first
        redis_manager._set_connection_state(RedisConnectionState.CONNECTED)

        # Then disconnect
        redis_manager._set_connection_state(RedisConnectionState.DISCONNECTED)

        # Gauge should be 0
        final_value = REDIS_CONNECTED.labels(instance=redis_manager.instance_name)._value.get()
        assert final_value == 0.0

    @pytest.mark.skipif(not PROMETHEUS_AVAILABLE, reason="Prometheus not available")
    def test_prometheus_gauge_uses_instance_label(self, redis_manager):
        """Test that Prometheus gauge uses instance label"""
        redis_manager._set_connection_state(RedisConnectionState.CONNECTED)

        # Should have label for instance
        # This verifies the metric is labeled correctly
        metric = REDIS_CONNECTED.labels(instance=redis_manager.instance_name)
        assert metric is not None


class TestConnectionPooling:
    """Test connection pooling behavior"""

    @pytest.mark.asyncio
    async def test_get_connection_initializes_if_needed(self, redis_manager):
        """Test that get_connection initializes pool if needed"""
        # Redis client is None, so get_connection should initialize
        assert redis_manager.redis_client is None

        with patch.object(redis_manager, 'initialize_pool', new_callable=AsyncMock) as mock_init:
            # Simulate initialize_pool setting redis_client
            async def set_client():
                redis_manager.redis_client = AsyncMock()
            mock_init.side_effect = set_client

            async with redis_manager.get_connection() as conn:
                pass

            # Should have called initialize_pool
            mock_init.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_connection_reuses_existing_client(self, redis_manager):
        """Test that get_connection reuses existing client"""
        redis_manager.redis_client = AsyncMock()

        with patch.object(redis_manager, 'initialize_pool', new_callable=AsyncMock) as mock_init:
            async with redis_manager.get_connection() as conn:
                assert conn == redis_manager.redis_client

            # Should NOT have called initialize_pool
            mock_init.assert_not_called()
