"""Redis Cloud Configuration Helper

This module provides utilities for configuring Redis connections,
especially for Redis Cloud with SSL/TLS encryption and authentication.
"""

import logging
import os
import ssl
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import redis
from redis.connection import SSLConnection

logger = logging.getLogger(__name__)


class RedisConfigError(Exception):
    """Raised when Redis configuration is invalid."""

    pass


def create_redis_client(config: Optional[Dict[str, Any]] = None) -> redis.Redis:
    """Create a Redis client with proper SSL configuration for Redis Cloud.

    Args:
        config: Optional configuration dictionary. If not provided,
                will read from environment variables.

    Returns:
        Configured Redis client

    Raises:
        RedisConfigError: If configuration is invalid
    """
    if config is None:
        config = get_redis_config_from_env()

    # Parse Redis URL
    redis_url = config.get("url", os.getenv("REDIS_URL"))
    if not redis_url:
        raise RedisConfigError("Redis URL not provided")

    parsed_url = urlparse(redis_url)

    # Determine if SSL is needed
    use_ssl = (
        parsed_url.scheme == "rediss"
        or config.get("ssl", False)
        or os.getenv("REDIS_SSL", "").lower() == "true"
    )

    # Base connection parameters
    connection_params = {
        "host": parsed_url.hostname,
        "port": parsed_url.port or (6380 if use_ssl else 6379),
        "db": config.get("db", int(os.getenv("REDIS_DB", 0))),
        "decode_responses": config.get("decode_responses", True),
        "encoding": config.get("encoding", "utf-8"),
        "socket_timeout": config.get("socket_timeout", 5),
        "socket_connect_timeout": config.get("socket_connect_timeout", 10),
        "socket_keepalive": config.get("socket_keepalive", True),
        "retry_on_timeout": config.get("retry_on_timeout", True),
        "health_check_interval": config.get("health_check_interval", 30),
    }

    # Add password if provided
    password = config.get("password") or os.getenv("REDIS_PASSWORD") or parsed_url.password
    if password:
        connection_params["password"] = password

    # Add username if provided
    username = parsed_url.username or config.get("username")
    if username and username != "default":
        connection_params["username"] = username

    # SSL Configuration for Redis Cloud
    if use_ssl:
        ssl_context = create_ssl_context(config)
        connection_params.update(
            {
                "connection_class": SSLConnection,
                "ssl_cert_reqs": ssl.CERT_REQUIRED,
                "ssl_ca_certs": config.get("ssl_ca_cert") or os.getenv("REDIS_CA_CERT"),
                "ssl_check_hostname": config.get("ssl_check_hostname", True),
            }
        )

        # Add SSL context if created
        if ssl_context:
            connection_params["ssl_context"] = ssl_context

    # Connection pool settings
    max_connections = config.get("max_connections", int(os.getenv("REDIS_MAX_CONNECTIONS", 50)))

    try:
        # Create connection pool
        pool = redis.ConnectionPool(max_connections=max_connections, **connection_params)

        # Create Redis client
        client = redis.Redis(connection_pool=pool)

        # Test connection
        client.ping()
        logger.info(
            f"Successfully connected to Redis at "
            f"{parsed_url.hostname}:{connection_params['port']}"
        )

        return client

    except redis.ConnectionError as e:
        logger.error(f"Failed to connect to Redis: {e}")
        raise RedisConfigError(f"Redis connection failed: {e}")
    except Exception as e:
        logger.error(f"Unexpected error connecting to Redis: {e}")
        raise RedisConfigError(f"Redis configuration error: {e}")


def create_ssl_context(config: Dict[str, Any]) -> Optional[ssl.SSLContext]:
    """Create SSL context for Redis Cloud connection.

    Args:
        config: Redis configuration dictionary

    Returns:
        SSL context or None if not needed
    """
    ca_cert_path = config.get("ssl_ca_cert") or os.getenv("REDIS_CA_CERT")

    if not ca_cert_path:
        # Use default SSL context for Redis Cloud
        return ssl.create_default_context()

    # Verify CA certificate exists
    if not os.path.exists(ca_cert_path):
        logger.warning(f"Redis CA certificate not found at {ca_cert_path}")
        return ssl.create_default_context()

    try:
        # Create SSL context with custom CA certificate
        context = ssl.create_default_context(cafile=ca_cert_path)
        context.check_hostname = config.get("ssl_check_hostname", True)

        # Set certificate requirements
        cert_reqs = config.get("ssl_cert_reqs", "required")
        if cert_reqs == "none":
            context.verify_mode = ssl.CERT_NONE
        elif cert_reqs == "optional":
            context.verify_mode = ssl.CERT_OPTIONAL
        else:
            context.verify_mode = ssl.CERT_REQUIRED

        logger.info(f"Created SSL context with CA certificate: {ca_cert_path}")
        return context

    except Exception as e:
        logger.error(f"Failed to create SSL context: {e}")
        # Fall back to default context
        return ssl.create_default_context()


def get_redis_config_from_env() -> Dict[str, Any]:
    """Get Redis configuration from environment variables.

    Returns:
        Redis configuration dictionary
    """
    return {
        "url": os.getenv("REDIS_URL"),
        "password": os.getenv("REDIS_PASSWORD"),
        "db": int(os.getenv("REDIS_DB", 0)),
        "ssl": os.getenv("REDIS_SSL", "").lower() == "true",
        "ssl_ca_cert": os.getenv("REDIS_CA_CERT"),
        "ssl_verify": os.getenv("REDIS_SSL_VERIFY", "true").lower() == "true",
        "ssl_check_hostname": os.getenv("REDIS_SSL_CHECK_HOSTNAME", "true").lower() == "true",
        "ssl_cert_reqs": os.getenv("REDIS_SSL_CERT_REQS", "required"),
        "max_connections": int(os.getenv("REDIS_MAX_CONNECTIONS", 50)),
        "connection_timeout": int(os.getenv("REDIS_TIMEOUT", 10)),
        "socket_timeout": int(os.getenv("REDIS_SOCKET_TIMEOUT", 5)),
        "socket_connect_timeout": int(os.getenv("REDIS_CONNECT_TIMEOUT", 10)),
        "socket_keepalive": os.getenv("REDIS_KEEPALIVE", "true").lower() == "true",
        "retry_on_timeout": os.getenv("REDIS_RETRY_TIMEOUT", "true").lower() == "true",
        "retry_on_error": os.getenv("REDIS_RETRY_ERROR", "true").lower() == "true",
        "max_retries": int(os.getenv("REDIS_MAX_RETRIES", 3)),
        "retry_delay": float(os.getenv("REDIS_RETRY_DELAY", 0.1)),
        "health_check_interval": int(os.getenv("REDIS_HEALTH_CHECK", 30)),
        "decode_responses": True,
        "encoding": "utf-8",
    }


def test_redis_connection(client: redis.Redis) -> bool:
    """Test Redis connection and basic operations.

    Args:
        client: Redis client to test

    Returns:
        True if connection is working properly
    """
    try:
        # Test basic operations
        client.ping()

        # Test set/get
        test_key = "scalper:test:connection"
        test_value = "test_value"
        client.set(test_key, test_value, ex=60)  # Expire in 60 seconds

        retrieved_value = client.get(test_key)
        if retrieved_value != test_value:
            logger.error("Redis get/set test failed")
            return False

        # Test delete
        client.delete(test_key)

        # Test pipeline
        pipeline = client.pipeline()
        pipeline.set("scalper:test:pipe1", "value1", ex=60)
        pipeline.set("scalper:test:pipe2", "value2", ex=60)
        pipeline.execute()

        # Cleanup
        client.delete("scalper:test:pipe1", "scalper:test:pipe2")

        logger.info("Redis connection test passed")
        return True

    except Exception as e:
        logger.error(f"Redis connection test failed: {e}")
        return False


def get_redis_info(client: redis.Redis) -> Dict[str, Any]:
    """Get Redis server information.

    Args:
        client: Redis client

    Returns:
        Dictionary with Redis server information
    """
    try:
        info = client.info()

        # Extract key metrics
        redis_info = {
            "redis_version": info.get("redis_version"),
            "redis_mode": info.get("redis_mode"),
            "os": info.get("os"),
            "tcp_port": info.get("tcp_port"),
            "uptime_in_seconds": info.get("uptime_in_seconds"),
            "connected_clients": info.get("connected_clients"),
            "used_memory": info.get("used_memory"),
            "used_memory_human": info.get("used_memory_human"),
            "maxmemory": info.get("maxmemory"),
            "maxmemory_human": info.get("maxmemory_human"),
            "keyspace_hits": info.get("keyspace_hits"),
            "keyspace_misses": info.get("keyspace_misses"),
            "total_commands_processed": info.get("total_commands_processed"),
            "instantaneous_ops_per_sec": info.get("instantaneous_ops_per_sec"),
        }

        # Calculate hit ratio
        hits = redis_info.get("keyspace_hits", 0)
        misses = redis_info.get("keyspace_misses", 0)
        if hits + misses > 0:
            redis_info["hit_ratio"] = hits / (hits + misses)
        else:
            redis_info["hit_ratio"] = 0.0

        return redis_info

    except Exception as e:
        logger.error(f"Failed to get Redis info: {e}")
        return {}


class RedisManager:
    """Redis connection manager for scalping system."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or get_redis_config_from_env()
        self.client: Optional[redis.Redis] = None
        self.is_connected = False

    def connect(self) -> None:
        """Establish Redis connection."""
        try:
            self.client = create_redis_client(self.config)
            self.is_connected = test_redis_connection(self.client)

            if self.is_connected:
                logger.info("Redis manager connected successfully")
            else:
                logger.error("Redis manager connection test failed")

        except Exception as e:
            logger.error(f"Redis manager connection failed: {e}")
            self.is_connected = False
            raise

    def disconnect(self) -> None:
        """Close Redis connection."""
        if self.client:
            try:
                self.client.close()
                logger.info("Redis manager disconnected")
            except Exception as e:
                logger.error(f"Error disconnecting Redis: {e}")
            finally:
                self.client = None
                self.is_connected = False

    def get_client(self) -> redis.Redis:
        """Get Redis client, connecting if necessary."""
        if not self.is_connected or not self.client:
            self.connect()
        return self.client

    def health_check(self) -> bool:
        """Perform health check on Redis connection."""
        if not self.client:
            return False

        try:
            self.client.ping()
            return True
        except Exception:
            self.is_connected = False
            return False

    def get_key(self, key_type: str, identifier: str) -> str:
        """Generate Redis key with proper prefix.

        Args:
            key_type: Type of key (ticks, orders, positions, etc.)
            identifier: Unique identifier for the key

        Returns:
            Formatted Redis key
        """
        prefixes = {
            "ticks": "scalper:ticks:",
            "orders": "scalper:orders:",
            "positions": "scalper:positions:",
            "metrics": "scalper:metrics:",
            "signals": "scalper:signals:",
            "locks": "scalper:locks:",
            "cache": "scalper:cache:",
        }

        prefix = prefixes.get(key_type, f"scalper:{key_type}:")
        return f"{prefix}{identifier}"

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()


# Example usage and testing
if __name__ == "__main__":
    import logging

    # Configure logging
    logging.basicConfig(level=logging.INFO)

    # Test Redis connection
    try:
        with RedisManager() as redis_mgr:
            client = redis_mgr.get_client()

            # Get Redis info
            info = get_redis_info(client)
            logger = logging.getLogger(__name__)
            logger.info("Redis Version: %s", info.get("redis_version"))
            logger.info("Connected Clients: %s", info.get("connected_clients"))
            logger.info("Used Memory: %s", info.get("used_memory_human"))
            logger.info("Hit Ratio: %.2f%%", info.get("hit_ratio", 0) * 100)

            # Test basic operations
            test_key = redis_mgr.get_key("cache", "test")
            client.set(test_key, "test_value", ex=60)
            value = client.get(test_key)
            logger.info("Test value: %s", value)

            logger.info("Redis connection test completed successfully!")

    except Exception as e:
        logger.error("Redis connection test failed: %s", e)
