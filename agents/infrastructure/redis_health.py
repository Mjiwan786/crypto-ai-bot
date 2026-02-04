"""
Redis health utilities for crypto-ai-bot.

Features:
- TLS/MTLS context building (optional)
- Robust connection params for Redis Cloud
- Exponential backoff with full jitter
- Precise PING RTT latency
- Memory metrics (MB and %, prefers maxmemory if set)
- Basic role/cluster visibility for ops
"""

from __future__ import annotations

import asyncio
import os
import random
import ssl
import time
from typing import Any

import redis.asyncio as redis
from pydantic import BaseModel, Field, field_validator

# ----------------------------- Models ----------------------------- #


class RedisHealthConfig(BaseModel):
    """Configuration for Redis health checks.

    Attributes:
        url: Redis connection URL (rediss:// for TLS)
        ca_cert_path: Path to CA certificate for TLS verification
        client_cert_path: Path to client certificate for mTLS
        client_key_path: Path to client key for mTLS
        max_retries: Maximum number of retry attempts
        base_delay: Base delay in seconds for exponential backoff
        max_delay: Maximum delay in seconds for exponential backoff
        connect_timeout: Socket connection timeout in seconds
        socket_timeout: Socket operation timeout in seconds
        ping_timeout: PING command timeout in seconds
        decode_responses: Whether to decode responses to strings
        keepalive: Whether to enable TCP keepalive
        memory_threshold_mb: Fallback memory threshold when maxmemory not set
    """

    url: str = Field(default="")
    ca_cert_path: str | None = None
    client_cert_path: str | None = None
    client_key_path: str | None = None

    max_retries: int = 3
    base_delay: float = 0.5  # seconds
    max_delay: float = 10.0  # seconds

    connect_timeout: float = 5.0  # seconds (socket_connect_timeout)
    socket_timeout: float = 5.0  # seconds (socket_timeout)
    ping_timeout: float = 2.0  # seconds

    decode_responses: bool = False
    keepalive: bool = True

    # Fallback when Redis doesn't expose maxmemory
    memory_threshold_mb: int = 100

    @field_validator("max_retries")
    @classmethod
    def _vr_retries(cls, v: int) -> int:
        """Validate max_retries is at least 1.

        Args:
            v: Value to validate

        Returns:
            Validated value

        Raises:
            ValueError: If value is less than 1
        """
        if v < 1:
            raise ValueError("max_retries must be >= 1")
        return v

    @field_validator("base_delay")
    @classmethod
    def _vr_base_delay(cls, v: float) -> float:
        """Validate base_delay is at least 0.1 seconds.

        Args:
            v: Value to validate

        Returns:
            Validated value

        Raises:
            ValueError: If value is less than 0.1
        """
        if v < 0.1:
            raise ValueError("base_delay must be >= 0.1")
        return v

    @field_validator("max_delay")
    @classmethod
    def _vr_max_delay(cls, v: float) -> float:
        """Validate max_delay is at least 0.5 seconds.

        Args:
            v: Value to validate

        Returns:
            Validated value

        Raises:
            ValueError: If value is less than 0.5
        """
        if v < 0.5:
            raise ValueError("max_delay must be >= 0.5")
        return v


class RedisHealthResult(BaseModel):
    """Outcome of a Redis health check.

    Attributes:
        connected: Whether connection was successful
        latency_ms: Round-trip time for PING in milliseconds
        memory_usage_mb: Current memory usage in megabytes
        memory_usage_percent: Memory usage as percentage of max
        connection_count: Number of connected clients
        error_message: Error description if connection failed
        role: Redis role (master/slave)
        cluster_enabled: Whether cluster mode is enabled
        master_link_status: Master link status for replicas
        tls_active: Whether TLS is active
        tls_cipher: TLS cipher suite in use
        timestamp: Unix timestamp of the check
    """

    connected: bool = False
    latency_ms: float = 0.0
    memory_usage_mb: float = 0.0
    memory_usage_percent: float = 0.0
    connection_count: int = 0
    error_message: str | None = None

    # Bonus visibility (non-breaking optional fields)
    role: str | None = None
    cluster_enabled: bool | None = None
    master_link_status: str | None = None
    tls_active: bool = False
    tls_cipher: str | None = None

    timestamp: float = Field(default_factory=lambda: time.time())


# ----------------------------- Checker ----------------------------- #


class RedisHealthChecker:
    """Health checker for Redis (supports TLS/Redis Cloud).

    Provides robust health checking with retry logic, TLS support,
    and comprehensive metrics collection.
    """

    def __init__(self, config: RedisHealthConfig) -> None:
        """Initialize Redis health checker.

        Args:
            config: Health check configuration
        """
        self.config = config

    # ---- TLS helpers ---- #

    def _build_ssl_context(self) -> ssl.SSLContext | None:
        """Build an SSLContext if CA cert path provided, optionally load mTLS.

        Returns:
            SSL context for TLS connections, or None if no CA cert configured

        Raises:
            FileNotFoundError: If certificate files don't exist
        """
        if self.config.ca_cert_path is None:
            return None

        if not os.path.exists(self.config.ca_cert_path):
            raise FileNotFoundError(f"CA certificate not found: {self.config.ca_cert_path}")

        ctx = ssl.create_default_context(cafile=self.config.ca_cert_path)
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED

        if self.config.client_cert_path is not None and self.config.client_key_path is not None:
            if not os.path.exists(self.config.client_cert_path):
                raise FileNotFoundError(f"Client cert not found: {self.config.client_cert_path}")
            if not os.path.exists(self.config.client_key_path):
                raise FileNotFoundError(f"Client key not found: {self.config.client_key_path}")
            ctx.load_cert_chain(self.config.client_cert_path, self.config.client_key_path)

        return ctx

    def _get_connection_params(self) -> dict[str, Any]:
        """Assemble redis.from_url kwargs based on config.

        Returns:
            Dictionary of connection parameters for redis.from_url()

        Raises:
            ValueError: If Redis URL is not configured
        """
        url = (self.config.url or "").strip()
        if not url:
            raise ValueError("Redis URL not configured")

        params: dict[str, Any] = {
            "socket_timeout": self.config.socket_timeout,
            "socket_connect_timeout": self.config.connect_timeout,
            "decode_responses": self.config.decode_responses,
            "socket_keepalive": self.config.keepalive,
        }

        # TLS for rediss://
        if url.startswith("rediss://"):
            ctx = self._build_ssl_context()
            if ctx is not None:
                params["ssl_context"] = ctx

        return params

    async def _exponential_backoff_delay(self, attempt: int) -> float:
        """Full-jitter backoff: random(0, base * 2^attempt) capped by max_delay.

        Args:
            attempt: Current retry attempt number (0-indexed)

        Returns:
            Delay in seconds with full jitter
        """
        raw = self.config.base_delay * (2**attempt)
        jittered = random.uniform(0.0, raw)
        return min(jittered, self.config.max_delay)

    # Factored for testability (patched in tests)
    def _create_client(self, url: str, **params: Any) -> redis.Redis[bytes]:
        """Create Redis client (factored for testing).

        Args:
            url: Redis connection URL
            **params: Additional connection parameters

        Returns:
            Redis client instance
        """
        return redis.from_url(url, **params)

    async def check_health(self) -> RedisHealthResult:
        """Run a robust health check with retries.

        Returns:
            Health check result with connection status and metrics

        Note:
            Implements exponential backoff with full jitter for retry attempts.
            Collects comprehensive metrics including memory, connections, and TLS info.
        """
        try:
            params = self._get_connection_params()
            url = self.config.url

            # Open a single connection for the check
            async with self._create_client(url, **params) as cli:
                # Retry ping with jitter backoff; measure precise RTT for success
                last_error: Exception | None = None
                rtt_ms: float | None = None

                for attempt in range(self.config.max_retries):
                    try:
                        t0 = time.perf_counter()
                        await asyncio.wait_for(cli.ping(), timeout=self.config.ping_timeout)
                        rtt_ms = (time.perf_counter() - t0) * 1000.0
                        last_error = None
                        break
                    except (asyncio.TimeoutError, redis.ConnectionError, redis.TimeoutError) as e:
                        last_error = e
                        if attempt < self.config.max_retries - 1:
                            await asyncio.sleep(await self._exponential_backoff_delay(attempt))
                        continue

                if last_error is not None:
                    # Exhausted retries
                    if isinstance(last_error, asyncio.TimeoutError):
                        return RedisHealthResult(
                            connected=False, error_message=f"Connection timeout: {last_error}"
                        )
                    return RedisHealthResult(
                        connected=False, error_message=f"Connection error: {last_error}"
                    )

                # Gather INFO metrics
                info = await cli.info()
                used_mb = float(info.get("used_memory", 0.0)) / (1024 * 1024)
                max_mb = float(info.get("maxmemory", 0.0)) / (1024 * 1024)

                if max_mb > 0.0:
                    pct = (used_mb / max_mb) * 100.0
                else:
                    thr = (
                        float(self.config.memory_threshold_mb)
                        if self.config.memory_threshold_mb
                        else 0.0
                    )
                    pct = (used_mb / thr) * 100.0 if thr > 0.0 else 0.0

                clients = int(info.get("connected_clients", 0))

                # Optional visibility
                role_val: Any = info.get("role")
                role = str(role_val) if role_val is not None else None
                cluster_enabled = str(info.get("cluster_enabled", "0")) == "1"
                master_link_val: Any = info.get("master_link_status")
                master_link_status = str(master_link_val) if master_link_val is not None else None

                tls_active = bool(params.get("ssl"))
                tls_cipher: str | None = None
                try:
                    if tls_active and getattr(cli, "connection_pool", None):
                        # Peek cipher if accessible (best-effort; may vary by redis-py version)
                        conn = await cli.connection_pool.get_connection("_")
                        sock = None
                        if getattr(conn, "connection", None) and getattr(
                            conn.connection, "transport", None
                        ):
                            sock = conn.connection.transport.get_extra_info("ssl_object")
                        if sock:
                            c = sock.cipher()
                            tls_cipher = c[0] if isinstance(c, tuple) and c else None
                except Exception:
                    pass

                return RedisHealthResult(
                    connected=True,
                    latency_ms=rtt_ms or 0.0,
                    memory_usage_mb=used_mb,
                    memory_usage_percent=pct,
                    connection_count=clients,
                    role=role,
                    cluster_enabled=cluster_enabled,
                    master_link_status=master_link_status,
                    tls_active=tls_active,
                    tls_cipher=tls_cipher,
                )

        except redis.AuthenticationError as e:
            return RedisHealthResult(connected=False, error_message=f"Auth error: {e}")
        except asyncio.TimeoutError as e:
            return RedisHealthResult(connected=False, error_message=f"Connection timeout: {e}")
        except redis.ConnectionError as e:
            return RedisHealthResult(connected=False, error_message=f"Connection error: {e}")
        except Exception as e:
            return RedisHealthResult(connected=False, error_message=f"Unexpected error: {e}")

    async def check_health_simple(self) -> bool:
        """Convenience boolean check.

        Returns:
            True if Redis is connected and healthy, False otherwise
        """
        res = await self.check_health()
        return res.connected


# ----------------------------- Convenience ----------------------------- #


async def check_redis_health(**kwargs: Any) -> RedisHealthResult:
    """Convenience function for Redis health checks.

    Args:
        **kwargs: Configuration parameters passed to RedisHealthConfig
            (url, ca_cert_path, max_retries, etc.)

    Returns:
        Health check result with connection status and metrics

    Example:
        >>> result = await check_redis_health(
        ...     url="rediss://localhost:6379",
        ...     ca_cert_path="/path/to/ca.crt",
        ...     max_retries=5
        ... )
        >>> print(result.connected)
        True
    """
    cfg = RedisHealthConfig(**kwargs)
    return await RedisHealthChecker(cfg).check_health()
