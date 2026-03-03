"""
Redis Cloud TLS connection utility for crypto-ai-bot.

Provides production-ready Redis Cloud connectivity with comprehensive error handling,
health monitoring, and integration points for the crypto trading system.

Features:
- Redis Cloud TLS connection with SSL context building
- Exponential backoff with jitter for resilient operations
- Health check integration with existing redis_health module
- Context manager support for proper resource cleanup
- Integration points for data_pipeline and kraken_ingestor
- Settings-driven SSL configuration
- Connection pooling and timeout management
- Comprehensive error handling and logging

Usage:
    from agents.infrastructure.redis_client import RedisCloudClient

    async with RedisCloudClient() as client:
        await client.ping()
        await client.set("key", "value")
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import ssl
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncIterator

import redis.asyncio as redis
from pydantic import BaseModel, Field, field_validator

if TYPE_CHECKING:
    from typing import Protocol

    class RedisAsyncClient(Protocol):
        """Protocol for redis async client with aclose method."""

        async def aclose(self, close_connection_pool: bool | None = None) -> None:
            ...

        async def ping(self) -> bool:
            ...

        def __getattr__(self, name: str) -> Any:
            ...

from agents.infrastructure.redis_health import (
    RedisHealthChecker,
    RedisHealthConfig,
    RedisHealthResult,
)

logger = logging.getLogger(__name__)


class RedisCloudConfig(BaseModel):
    """Configuration for Redis Cloud TLS connection.

    Attributes:
        url: Redis Cloud connection URL (must use rediss:// for TLS)
        ca_cert_path: Path to CA certificate file for TLS verification (optional)
        client_cert_path: Path to client certificate file for mTLS (optional)
        client_key_path: Path to client private key file for mTLS (optional)
        connect_timeout: Connection timeout in seconds
        socket_timeout: Socket operation timeout in seconds
        max_retries: Maximum number of connection retry attempts
        base_delay: Base delay in seconds for exponential backoff
        max_delay: Maximum delay in seconds for exponential backoff
        max_connections: Maximum number of connections in the pool
        retry_on_timeout: Whether to retry operations on timeout
        health_check_interval: Interval in seconds between health checks
        client_name: Client identification name
        decode_responses: Whether to decode responses to strings
    """

    # Connection settings
    url: str = Field(default_factory=lambda: os.getenv("REDIS_URL", ""))
    ca_cert_path: str | None = Field(default_factory=lambda: os.getenv("REDIS_CA_CERT"))
    client_cert_path: str | None = Field(default_factory=lambda: os.getenv("REDIS_CLIENT_CERT"))
    client_key_path: str | None = Field(default_factory=lambda: os.getenv("REDIS_CLIENT_KEY"))

    # Timeout settings
    connect_timeout: float = Field(default=10.0, ge=1.0, le=60.0)
    socket_timeout: float = Field(default=10.0, ge=1.0, le=60.0)

    # Retry settings
    max_retries: int = Field(default=5, ge=1, le=20)
    base_delay: float = Field(default=0.5, ge=0.1, le=5.0)
    max_delay: float = Field(default=30.0, ge=5.0, le=300.0)

    # Connection pool settings — read from REDIS_MAX_CONNECTIONS env var
    max_connections: int = Field(
        default_factory=lambda: int(os.getenv("REDIS_MAX_CONNECTIONS", "10")),
        ge=1,
        le=100,
    )
    retry_on_timeout: bool = Field(default=True)
    health_check_interval: int = Field(default=15, ge=5, le=300)

    # Client identification
    client_name: str = Field(default="crypto-ai-bot-cloud")
    decode_responses: bool = Field(default=True)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Ensure URL is TLS-enabled for Redis Cloud.

        Args:
            v: URL to validate

        Returns:
            Validated URL

        Raises:
            ValueError: If URL does not use rediss:// protocol
        """
        if not v:
            raise ValueError("Redis URL must be provided via config or REDIS_URL")
        if not v.startswith("rediss://"):
            raise ValueError("Redis Cloud requires TLS connection (rediss://)")
        return v

    @field_validator("ca_cert_path")
    @classmethod
    def validate_ca_cert(cls, v: str | None) -> str | None:
        """Validate CA certificate path if provided.

        Args:
            v: Path to CA certificate file

        Returns:
            Validated path or None

        Raises:
            FileNotFoundError: If path is provided but file does not exist
        """
        if v is not None and not os.path.exists(v):
            raise FileNotFoundError(f"CA certificate not found: {v}")
        return v

    @field_validator("client_cert_path")
    @classmethod
    def validate_client_cert(cls, v: str | None) -> str | None:
        """Validate client certificate path if provided.

        Args:
            v: Path to client certificate file

        Returns:
            Validated path or None

        Raises:
            FileNotFoundError: If path is provided but file does not exist
        """
        if v is not None and not os.path.exists(v):
            raise FileNotFoundError(f"Client certificate not found: {v}")
        return v

    @field_validator("client_key_path")
    @classmethod
    def validate_client_key(cls, v: str | None) -> str | None:
        """Validate client key path if provided.

        Args:
            v: Path to client key file

        Returns:
            Validated path or None

        Raises:
            FileNotFoundError: If path is provided but file does not exist
        """
        if v is not None and not os.path.exists(v):
            raise FileNotFoundError(f"Client key not found: {v}")
        return v


class RedisCloudClient:
    """
    Redis Cloud TLS client with exponential backoff, health checks, and context manager support.

    Designed for production use with Redis Cloud, providing:
    - Automatic TLS/SSL context building
    - Exponential backoff with jitter for resilience
    - Health check integration
    - Proper resource cleanup via context manager
    - Connection pooling and timeout management
    """

    def __init__(self, config: RedisCloudConfig | None = None) -> None:
        """Initialize Redis Cloud client with configuration.

        Args:
            config: Redis Cloud configuration. If None, uses default configuration
                from environment variables.
        """
        self.config = config or RedisCloudConfig()
        self._client: redis.Redis[str] | None = None
        self._connection_pool: redis.ConnectionPool[redis.Connection] | None = None
        self._health_checker: RedisHealthChecker | None = None
        self._is_connected = False

        # Setup health checker
        health_config = RedisHealthConfig(
            url=self.config.url,
            ca_cert_path=self.config.ca_cert_path,
            client_cert_path=self.config.client_cert_path,
            client_key_path=self.config.client_key_path,
            connect_timeout=self.config.connect_timeout,
            socket_timeout=self.config.socket_timeout,
            max_retries=self.config.max_retries,
            base_delay=self.config.base_delay,
            max_delay=self.config.max_delay,
        )
        self._health_checker = RedisHealthChecker(health_config)

    def _build_ssl_context(self) -> ssl.SSLContext:
        """Build SSL context for Redis Cloud TLS connection.

        Returns:
            Configured SSL context for TLS connection

        Note:
            If no CA certificate is provided, uses Python's default SSL context.
            If client certificate and key are provided, enables mTLS authentication.
        """
        if self.config.ca_cert_path is None:
            # Use default SSL context if no CA cert provided
            context = ssl.create_default_context()
            context.check_hostname = True
            context.verify_mode = ssl.CERT_REQUIRED
            logger.warning("No CA certificate provided, using default SSL context")
            return context

        # Create context with custom CA
        context = ssl.create_default_context(cafile=self.config.ca_cert_path)
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED

        # Add mTLS support if client cert/key provided
        if self.config.client_cert_path is not None and self.config.client_key_path is not None:
            context.load_cert_chain(self.config.client_cert_path, self.config.client_key_path)
            logger.debug("mTLS client certificates loaded")
        elif self.config.client_cert_path is not None or self.config.client_key_path is not None:
            logger.warning("Both client cert and key must be provided for mTLS")

        return context

    def _get_connection_params(self) -> dict[str, Any]:
        """Get connection parameters for Redis client.

        Returns:
            Dictionary of connection parameters for redis.from_url()
        """
        params = {
            "socket_timeout": self.config.socket_timeout,
            "socket_connect_timeout": self.config.connect_timeout,
            "retry_on_timeout": self.config.retry_on_timeout,
            "health_check_interval": self.config.health_check_interval,
            "decode_responses": self.config.decode_responses,
            "client_name": self.config.client_name,
            "max_connections": self.config.max_connections,
        }

        # PRD-001 Section B.1: For redis-py async, use ssl_ca_certs parameter
        # Based on working code in prd_publisher.py (line 376-377)
        # For rediss:// URLs, redis-py automatically enables SSL/TLS
        if self.config.url.startswith("rediss://"):
            if self.config.ca_cert_path and os.path.exists(self.config.ca_cert_path):
                # Use string format for ssl_cert_reqs (not ssl.CERT_REQUIRED constant)
                params["ssl_ca_certs"] = self.config.ca_cert_path
                params["ssl_cert_reqs"] = "required"  # String, not ssl.CERT_REQUIRED
            # If no CA cert, redis-py will use system certs (acceptable fallback)

        return params

    async def _exponential_backoff_delay(self, attempt: int) -> float:
        """Calculate exponential backoff delay with jitter.

        Args:
            attempt: Current retry attempt number (0-indexed)

        Returns:
            Delay in seconds with exponential backoff and random jitter
        """
        raw_delay = self.config.base_delay * (2**attempt)
        jitter: float = random.uniform(0, raw_delay * 0.1)  # 10% jitter
        return float(min(raw_delay + jitter, self.config.max_delay))

    async def _create_client(self) -> redis.Redis[str]:
        """Create Redis client with retry logic.

        Returns:
            Connected Redis client instance

        Raises:
            Exception: If connection fails after all retry attempts
            RuntimeError: If retry logic encounters an unexpected state
        """
        # Get connection parameters (includes SSL context for TLS)
        conn_params = self._get_connection_params()
        
        # For redis-py 6.x, use the simplified approach like the working TLS check
        for attempt in range(self.config.max_retries):
            try:
                # PRD-001 Section B.1: Use SSL context with CA certificate for TLS
                # conn_params already includes ssl_context from _get_connection_params()
                client = redis.from_url(
                    self.config.url,
                    **conn_params
                )

                # Test connection
                await client.ping()
                logger.info("Redis Cloud connection established successfully")
                return client
            except Exception as e:
                if attempt == self.config.max_retries - 1:
                    logger.error(
                        f"Failed to connect to Redis Cloud after {self.config.max_retries} "
                        f"attempts: {e}"
                    )
                    raise

                delay = await self._exponential_backoff_delay(attempt)
                logger.warning(
                    f"Connection attempt {attempt + 1} failed: {e}. Retrying in {delay:.2f}s"
                )
                await asyncio.sleep(delay)

        raise RuntimeError("Unexpected error in connection retry logic")

    async def connect(self) -> None:
        """Establish connection to Redis Cloud.

        Returns:
            None

        Raises:
            Exception: If connection fails after all retry attempts

        Note:
            If already connected, this method returns immediately without error.
        """
        if self._is_connected:
            return

        try:
            self._client = await self._create_client()
            self._is_connected = True
            logger.info("Connected to Redis Cloud")
        except Exception as e:
            logger.error(f"Failed to connect to Redis Cloud: {e}")
            raise

    async def disconnect(self) -> None:
        """Disconnect from Redis Cloud.

        Returns:
            None

        Note:
            Always cleans up client reference even if disconnect fails.
            Logs warnings but does not raise exceptions on disconnect errors.
        """
        if self._client is not None:
            try:
                # aclose() exists at runtime but not in type stubs - use Protocol for typing
                from typing import cast

                if TYPE_CHECKING:
                    client_typed = cast("RedisAsyncClient", self._client)
                else:
                    client_typed = self._client
                await client_typed.aclose()
                logger.info("Disconnected from Redis Cloud")
            except Exception as e:
                logger.warning(f"Error during disconnect: {e}")
            finally:
                self._client = None
                self._is_connected = False

    def is_connected(self) -> bool:
        """Return True if the client currently has an active Redis connection.

        Returns:
            True if connected, False otherwise
        """
        return self._is_connected and self._client is not None

    @property
    def client(self) -> "redis.Redis[str]":
        """Return the underlying raw redis.asyncio.Redis client.

        Use this when you need direct access to Redis commands (xadd, xread,
        smembers, etc.) without going through the wrapper's __getattr__.

        Raises:
            RuntimeError: If not connected — call connect() first
        """
        if self._client is None:
            raise RuntimeError("Redis client not connected. Call connect() first.")
        return self._client

    async def health_check(self) -> RedisHealthResult:
        """Perform health check using integrated health checker.

        Returns:
            Health check result with connection status and diagnostics

        Note:
            Uses the integrated RedisHealthChecker to verify connection health.
            If health checker is not initialized, returns failed health result.
        """
        if self._health_checker is None:
            return RedisHealthResult(
                connected=False, error_message="Health checker not initialized"
            )

        return await self._health_checker.check_health()

    async def ping(self) -> bool:
        """Ping Redis server with retry logic.

        Returns:
            True if ping succeeds, False if all retry attempts fail

        Raises:
            RuntimeError: If client is not connected

        Note:
            Implements exponential backoff retry logic for transient failures.
        """
        if self._client is None:
            raise RuntimeError("Client not connected")

        for attempt in range(self.config.max_retries):
            try:
                result = await self._client.ping()
                return bool(result)
            except Exception as e:
                if attempt == self.config.max_retries - 1:
                    logger.error(f"Ping failed after {self.config.max_retries} attempts: {e}")
                    return False

                delay = await self._exponential_backoff_delay(attempt)
                logger.warning(f"Ping attempt {attempt + 1} failed: {e}. Retrying in {delay:.2f}s")
                await asyncio.sleep(delay)

        return False

    # Context manager support
    async def __aenter__(self) -> RedisCloudClient:
        """Async context manager entry.

        Returns:
            Self after establishing connection

        Raises:
            Exception: If connection fails
        """
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Async context manager exit.

        Args:
            exc_type: Exception type if an exception occurred
            exc_val: Exception value if an exception occurred
            exc_tb: Exception traceback if an exception occurred

        Returns:
            None

        Note:
            Always disconnects client, even if exception occurred in context.
        """
        await self.disconnect()

    # Delegate Redis operations to underlying client
    def __getattr__(self, name: str) -> Any:
        """Delegate attribute access to underlying Redis client.

        Args:
            name: Attribute name to access on underlying client

        Returns:
            Attribute from underlying Redis client

        Raises:
            RuntimeError: If client is not connected
        """
        if self._client is None:
            raise RuntimeError("Client not connected")
        return getattr(self._client, name)


# Convenience functions for integration points
async def get_redis_cloud_client(config: RedisCloudConfig | None = None) -> RedisCloudClient:
    """Get a Redis Cloud client instance.

    Args:
        config: Optional Redis Cloud configuration. If None, uses default config.

    Returns:
        Connected Redis Cloud client

    Raises:
        Exception: If connection fails

    Example:
        >>> client = await get_redis_cloud_client()
        >>> await client.ping()
        True
    """
    client = RedisCloudClient(config)
    await client.connect()
    return client


@asynccontextmanager
async def redis_cloud_connection(
    config: RedisCloudConfig | None = None,
) -> AsyncIterator[RedisCloudClient]:
    """Context manager for Redis Cloud connection.

    Args:
        config: Optional Redis Cloud configuration. If None, uses default config.

    Yields:
        Connected Redis Cloud client

    Raises:
        Exception: If connection fails

    Example:
        >>> async with redis_cloud_connection() as client:
        ...     await client.ping()
    """
    client = RedisCloudClient(config)
    try:
        await client.connect()
        yield client
    finally:
        await client.disconnect()


# Integration helper for data_pipeline
async def create_data_pipeline_redis_client() -> redis.Redis[str]:
    """Create Redis client for data_pipeline integration.

    Returns:
        Connected Redis client instance (underlying redis.Redis client)

    Raises:
        Exception: If connection fails

    Note:
        Returns the underlying redis.Redis client for compatibility with
        existing data_pipeline code that expects raw redis client.
    """
    config = RedisCloudConfig()
    client = RedisCloudClient(config)
    await client.connect()
    if client._client is None:
        raise RuntimeError("Failed to create client connection")
    return client._client


# Integration helper for kraken_ingestor
async def create_kraken_ingestor_redis_client() -> redis.Redis[str]:
    """Create Redis client for kraken_ingestor integration.

    Returns:
        Connected Redis client instance (underlying redis.Redis client)

    Raises:
        Exception: If connection fails

    Note:
        Returns the underlying redis.Redis client for compatibility with
        existing kraken_ingestor code that expects raw redis client.
    """
    config = RedisCloudConfig()
    client = RedisCloudClient(config)
    await client.connect()
    if client._client is None:
        raise RuntimeError("Failed to create client connection")
    return client._client


# Health check utility
async def check_redis_cloud_health(config: RedisCloudConfig | None = None) -> RedisHealthResult:
    """Check Redis Cloud health without establishing persistent connection.

    Args:
        config: Optional Redis Cloud configuration. If None, uses default config.

    Returns:
        Health check result with connection status and diagnostics

    Example:
        >>> result = await check_redis_cloud_health()
        >>> if result.connected:
        ...     print("Redis is healthy")
    """
    if config is None:
        config = RedisCloudConfig()

    health_config = RedisHealthConfig(
        url=config.url,
        ca_cert_path=config.ca_cert_path,
        client_cert_path=config.client_cert_path,
        client_key_path=config.client_key_path,
        connect_timeout=config.connect_timeout,
        socket_timeout=config.socket_timeout,
        max_retries=config.max_retries,
        base_delay=config.base_delay,
        max_delay=config.max_delay,
    )

    checker = RedisHealthChecker(health_config)
    return await checker.check_health()


# ==============================================================================
# Backward Compatibility Aliases
# ==============================================================================

# Legacy alias for backward compatibility with existing code
RedisClient = RedisCloudClient
RedisClientWithBackoff = RedisCloudClient  # Tests expect this name

logger.debug("RedisClient and RedisClientWithBackoff are aliases for RedisCloudClient")
