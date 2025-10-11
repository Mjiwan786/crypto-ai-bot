"""
Real Redis Client - Production implementation.

Implements RedisClientProtocol for real Redis Cloud connection.
Can be swapped with FakeRedisClient for testing.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import redis.asyncio as redis

from agents.core.types import RedisClientProtocol

logger = logging.getLogger(__name__)


class RealRedisClient:
    """Real Redis client implementing RedisClientProtocol.

    This is a production-ready implementation that connects to real Redis
    (including Redis Cloud). It can be swapped with FakeRedisClient for testing.

    Example:
        # Production (Redis Cloud)
        client = RealRedisClient(
            host="redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com",
            port=19818,
            password="...",
            ssl=True,
        )

        # Testing
        client = FakeRedisClient()

        # Both implement same Protocol - no code changes needed!
        processor = SignalProcessor(redis_client=client)
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        password: Optional[str] = None,
        username: str = "default",
        ssl: bool = False,
        db: int = 0,
    ):
        """Initialize real Redis client.

        Args:
            host: Redis host
            port: Redis port
            password: Redis password
            username: Redis username (default for Redis Cloud)
            ssl: Use SSL/TLS connection
            db: Redis database number
        """
        self.host = host
        self.port = port
        self.ssl = ssl

        # Create Redis client
        self.client = redis.Redis(
            host=host,
            port=port,
            password=password,
            username=username,
            ssl=ssl,
            ssl_cert_reqs="required" if ssl else None,
            decode_responses=False,  # Keep bytes for Protocol compatibility
            socket_timeout=30,
            socket_keepalive=True,
            socket_keepalive_options={
                "TCP_KEEPIDLE": 1,
                "TCP_KEEPINTVL": 3,
                "TCP_KEEPCNT": 5,
            },
            db=db,
        )

        logger.info(
            f"Redis client initialized: {host}:{port} (ssl={ssl})"
        )

    @classmethod
    def from_url(cls, url: str) -> RealRedisClient:
        """Create client from Redis URL.

        Args:
            url: Redis connection URL
                (e.g., redis://user:pass@host:port/db or rediss:// for SSL)

        Returns:
            RealRedisClient instance

        Example:
            client = RealRedisClient.from_url(
                "rediss://default:password@redis-19818...redis-cloud.com:19818/0"
            )
        """
        import urllib.parse

        parsed = urllib.parse.urlparse(url)

        host = parsed.hostname or "localhost"
        port = parsed.port or 6379
        password = parsed.password
        username = parsed.username or "default"
        ssl = parsed.scheme == "rediss"
        db = int(parsed.path.lstrip("/")) if parsed.path else 0

        return cls(
            host=host,
            port=port,
            password=password,
            username=username,
            ssl=ssl,
            db=db,
        )

    async def xadd(self, stream: str, fields: dict[str, str]) -> str:
        """Add entry to Redis stream.

        Args:
            stream: Stream name
            fields: Field-value pairs

        Returns:
            Message ID

        Raises:
            redis.ConnectionError: If connection fails
        """
        try:
            message_id = await self.client.xadd(stream, fields)
            return message_id.decode("utf-8") if isinstance(message_id, bytes) else message_id
        except redis.ConnectionError as e:
            logger.error(f"Redis connection error in xadd: {e}")
            raise
        except Exception as e:
            logger.error(f"Error adding to stream {stream}: {e}")
            raise

    async def xreadgroup(
        self,
        groupname: str,
        consumername: str,
        streams: dict[str, str],
        count: Optional[int] = None,
        block: Optional[int] = None,
    ) -> list[tuple[bytes, list[tuple[bytes, dict[bytes, bytes]]]]]:
        """Read from stream using consumer group.

        Args:
            groupname: Consumer group name
            consumername: Consumer name
            streams: Stream names and IDs
            count: Maximum number of messages
            block: Block time in milliseconds

        Returns:
            List of stream messages

        Raises:
            redis.ConnectionError: If connection fails
        """
        try:
            result = await self.client.xreadgroup(
                groupname=groupname,
                consumername=consumername,
                streams=streams,
                count=count,
                block=block,
            )
            return result or []
        except redis.ConnectionError as e:
            logger.error(f"Redis connection error in xreadgroup: {e}")
            raise
        except Exception as e:
            logger.error(f"Error reading from streams: {e}")
            raise

    async def xgroup_create(
        self,
        name: str,
        groupname: str,
        id: str = "0",
        mkstream: bool = False,
    ) -> bool:
        """Create consumer group.

        Args:
            name: Stream name
            groupname: Consumer group name
            id: Start ID (default "0" for beginning)
            mkstream: Create stream if doesn't exist

        Returns:
            True if successful

        Raises:
            redis.ResponseError: If group already exists
        """
        try:
            await self.client.xgroup_create(
                name=name,
                groupname=groupname,
                id=id,
                mkstream=mkstream,
            )
            return True
        except redis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                # Group already exists - not an error
                return True
            logger.error(f"Error creating consumer group: {e}")
            raise
        except Exception as e:
            logger.error(f"Error creating consumer group: {e}")
            raise

    async def xack(
        self,
        name: str,
        groupname: str,
        *ids: str,
    ) -> int:
        """Acknowledge stream messages.

        Args:
            name: Stream name
            groupname: Consumer group name
            *ids: Message IDs to acknowledge

        Returns:
            Number of messages acknowledged
        """
        try:
            count = await self.client.xack(name, groupname, *ids)
            return count
        except Exception as e:
            logger.error(f"Error acknowledging messages: {e}")
            raise

    async def xrevrange(
        self,
        name: str,
        max: str = "+",
        min: str = "-",
        count: Optional[int] = None,
    ) -> list[tuple[bytes, dict[bytes, bytes]]]:
        """Read stream messages in reverse order.

        Args:
            name: Stream name
            max: Maximum ID (default "+" for latest)
            min: Minimum ID (default "-" for oldest)
            count: Maximum number of messages

        Returns:
            List of messages in reverse order
        """
        try:
            result = await self.client.xrevrange(
                name=name,
                max=max,
                min=min,
                count=count,
            )
            return result or []
        except Exception as e:
            logger.error(f"Error reading stream in reverse: {e}")
            raise

    async def ping(self) -> bool:
        """Ping Redis server.

        Returns:
            True if successful

        Raises:
            redis.ConnectionError: If ping fails
        """
        try:
            response = await self.client.ping()
            return response is True
        except redis.ConnectionError as e:
            logger.error(f"Redis ping failed: {e}")
            raise

    async def aclose(self) -> None:
        """Close Redis connection."""
        try:
            await self.client.aclose()
            logger.info("Redis connection closed")
        except Exception as e:
            logger.error(f"Error closing Redis connection: {e}")


# ==============================================================================
# Factory Function
# ==============================================================================


def create_redis_client(
    host: Optional[str] = None,
    port: Optional[int] = None,
    password: Optional[str] = None,
    url: Optional[str] = None,
    use_fake: bool = False,
) -> RedisClientProtocol:
    """Factory function to create appropriate Redis client.

    Args:
        host: Redis host
        port: Redis port
        password: Redis password
        url: Redis connection URL (alternative to host/port/password)
        use_fake: Return fake client for testing

    Returns:
        Client implementing RedisClientProtocol

    Example:
        # For production (Redis Cloud)
        client = create_redis_client(
            url="rediss://default:pass@redis-19818...redis-cloud.com:19818"
        )

        # For testing
        client = create_redis_client(use_fake=True)

        # Both return same Protocol interface!
    """
    if use_fake:
        from agents.core.test_fakes import FakeRedisClient

        logger.info("Creating FAKE Redis client for testing")
        return FakeRedisClient()
    elif url:
        logger.info("Creating REAL Redis client from URL")
        return RealRedisClient.from_url(url)
    else:
        logger.info("Creating REAL Redis client")
        return RealRedisClient(
            host=host or "localhost",
            port=port or 6379,
            password=password,
        )


# ==============================================================================
# Exports
# ==============================================================================

__all__ = [
    "RealRedisClient",
    "create_redis_client",
]
