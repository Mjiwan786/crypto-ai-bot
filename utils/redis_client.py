"""
Production-ready Redis client utility for 24/7 crypto trading systems.

Features:
- TLS-correct SSL context building with optional mTLS support
- Version-tolerant for redis-py 6.x/7.x
- Exponential backoff with jitter for resilient operations
- JSON helpers with optional orjson support
- Minimal Pub/Sub and Streams convenience functions
- Built-in health checks and connection management
- CLI self-test functionality

Usage:
    from utils.redis_client import get_redis, set_json, get_json, xadd_simple
    r = get_redis()
    assert r.ping()
    set_json(r, "bot:ping", {"ok": True}, ex=10)
    print(get_json(r, "bot:ping"))
    xadd_simple(r, "stream:signals", {"hello": "world"}, maxlen=1000)

Environment Variables:
    REDIS_URL: Redis connection URL (redis:// or rediss://)
    REDIS_CA_CERT: Path to CA certificate file (optional)
    REDIS_CLIENT_CERT: Path to client certificate file (optional, for mTLS)
    REDIS_CLIENT_KEY: Path to client private key file (optional, for mTLS)
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import ssl
import time
from typing import Any, Callable, TypeVar
from urllib.parse import urlparse

import redis

# Optional fast JSON library
try:
    import orjson
    HAS_ORJSON = True
except ImportError:
    HAS_ORJSON = False

__version__ = "1.0.0"

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Default configuration
_DEFAULT_SOCKET_TIMEOUT = 5.0
_DEFAULT_CONNECT_TIMEOUT = 5.0
_DEFAULT_CLIENT_NAME = "crypto-ai-bot"
_DEFAULT_HEALTH_CHECK_INTERVAL = 15


def _redact_password(url: str) -> str:
    """Redact password from Redis URL for safe logging."""
    if not url:
        return url
    
    # Match password in URL like redis://user:password@host:port/db
    pattern = r'(redis[s]?://[^:]+:)([^@]+)(@.*)'
    match = re.match(pattern, url)
    if match:
        return f"{match.group(1)}***{match.group(3)}"
    return url


def _get_redis_version() -> tuple[int, int, int]:
    """Get redis-py version as tuple for compatibility checks."""
    try:
        version_str = redis.__version__
        parts = version_str.split('.')
        return tuple(int(p) for p in parts[:3])
    except (AttributeError, ValueError):
        # Fallback for unknown versions
        return (4, 0, 0)


def _supports_client_name() -> bool:
    """Check if redis-py version supports client_name parameter."""
    version = _get_redis_version()
    # client_name was added in redis-py 4.2.0
    return version >= (4, 2, 0)


def build_ssl_context(
    cafile_path: str | None,
    *,
    certfile: str | None = None,
    keyfile: str | None = None,
) -> ssl.SSLContext | None:
    """
    Build SSL context for Redis TLS connections.
    
    Args:
        cafile_path: Path to CA certificate file. If None, returns None.
        certfile: Path to client certificate file (for mTLS, optional).
        keyfile: Path to client private key file (for mTLS, optional).
        
    Returns:
        Configured SSL context or None if no CA file provided.
        
    Raises:
        FileNotFoundError: If cafile_path is provided but file doesn't exist.
        ssl.SSLError: If certificate files are invalid.
    """
    if not cafile_path:
        return None
    
    if not os.path.exists(cafile_path):
        raise FileNotFoundError(f"REDIS_CA_CERT not found at: {cafile_path}")
    
    logger.debug(f"Building SSL context with CA file: {cafile_path}")
    
    # Create context with system defaults + custom CA
    ctx = ssl.create_default_context(cafile=cafile_path)
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    
    # Add mTLS support if cert/key provided
    if certfile and keyfile:
        if not os.path.exists(certfile):
            raise FileNotFoundError(f"REDIS_CLIENT_CERT not found at: {certfile}")
        if not os.path.exists(keyfile):
            raise FileNotFoundError(f"REDIS_CLIENT_KEY not found at: {keyfile}")
        
        logger.debug(f"Adding mTLS client cert: {certfile}")
        ctx.load_cert_chain(certfile, keyfile)
    elif certfile or keyfile:
        logger.warning("Both certfile and keyfile must be provided for mTLS")
    
    return ctx


def get_redis(
    url: str | None = None,
    cafile_path: str | None = None,
    *,
    socket_timeout: float = _DEFAULT_SOCKET_TIMEOUT,
    connect_timeout: float = _DEFAULT_CONNECT_TIMEOUT,
    client_name: str | None = _DEFAULT_CLIENT_NAME,
    decode_responses: bool = False,
) -> redis.Redis:
    """
    Create Redis client with proper TLS configuration.
    
    Args:
        url: Redis URL. If None, uses REDIS_URL environment variable.
        cafile_path: Path to CA cert. If None, uses REDIS_CA_CERT env var.
        socket_timeout: Socket operation timeout in seconds.
        connect_timeout: Connection timeout in seconds.
        client_name: Client name for Redis connection tracking.
        decode_responses: Whether to decode responses to strings.
        
    Returns:
        Configured Redis client instance.
        
    Raises:
        ValueError: If no Redis URL is provided or available.
        FileNotFoundError: If CA certificate file is missing.
    """
    # Get URL from parameter or environment
    redis_url = url or os.getenv("REDIS_URL")
    if not redis_url:
        raise ValueError(
            "REDIS_URL is not set. Please provide url parameter or set "
            "REDIS_URL environment variable."
        )
    
    # Parse URL to determine if TLS is needed
    parsed = urlparse(redis_url)
    use_tls = parsed.scheme == "rediss"
    
    logger.debug(f"Connecting to Redis: {_redact_password(redis_url)} (TLS: {use_tls})")
    
    # Build SSL context if needed
    ca_path = cafile_path or os.getenv("REDIS_CA_CERT")
    ssl_context = None
    
    if use_tls:
        # For TLS connections, try to build SSL context
        cert_file = os.getenv("REDIS_CLIENT_CERT")
        key_file = os.getenv("REDIS_CLIENT_KEY")
        ssl_context = build_ssl_context(ca_path, certfile=cert_file, keyfile=key_file)
        
        if not ssl_context and ca_path:
            logger.warning("TLS connection requested but SSL context build failed")
    elif ca_path:
        logger.warning("CA certificate provided but connection URL is not TLS (rediss://)")
    
    # Prepare connection parameters
    connection_kwargs = {
        "socket_timeout": socket_timeout,
        "socket_connect_timeout": connect_timeout,
        "retry_on_timeout": True,
        "health_check_interval": _DEFAULT_HEALTH_CHECK_INTERVAL,
        "socket_keepalive": True,
        "decode_responses": decode_responses,
    }
    
    # Add TLS parameters only for TLS connections
    if use_tls:
        connection_kwargs.update({
            "ssl": True,
            "ssl_context": ssl_context,
        })
    
    # Add client_name if supported by redis-py version
    if client_name and _supports_client_name():
        connection_kwargs["client_name"] = client_name
    elif client_name and not _supports_client_name():
        logger.debug("client_name not supported in this redis-py version")
    
    try:
        client = redis.Redis.from_url(redis_url, **connection_kwargs)
        logger.debug("Redis client created successfully")
        return client
    except Exception as e:
        logger.error(f"Failed to create Redis client: {e}")
        raise


def safe_ping(
    client: redis.Redis,
    *,
    attempts: int = 3,
    base: float = 0.25,
    cap: float = 2.0,
) -> bool:
    """
    Ping Redis with exponential backoff and jitter.
    
    Args:
        client: Redis client instance.
        attempts: Maximum number of retry attempts.
        base: Base delay for exponential backoff in seconds.
        cap: Maximum delay cap in seconds.
        
    Returns:
        True if ping succeeded, False otherwise.
    """
    for attempt in range(attempts):
        try:
            result = client.ping()
            logger.debug(f"Ping successful on attempt {attempt + 1}")
            return bool(result)
        except (redis.ConnectionError, redis.TimeoutError) as e:
            if attempt == attempts - 1:
                logger.warning(f"Ping failed after {attempts} attempts: {e}")
                return False
            
            # Exponential backoff with jitter
            delay = min(base * (2 ** attempt), cap)
            jitter = random.uniform(0, delay * 0.1)
            sleep_time = delay + jitter
            
            logger.debug(f"Ping attempt {attempt + 1} failed, retrying in {sleep_time:.2f}s: {e}")
            time.sleep(sleep_time)
        except Exception as e:
            logger.error(f"Unexpected error during ping: {e}")
            return False
    
    return False


def with_redis(
    func: Callable[[redis.Redis], T],
    *,
    url: str | None = None,
    cafile_path: str | None = None,
    attempts: int = 3,
) -> T:
    """
    Execute function with Redis client, with automatic retry on connection errors.
    
    Args:
        func: Function to execute, will be passed Redis client as first argument.
        url: Redis URL override.
        cafile_path: CA certificate path override.
        attempts: Maximum retry attempts.
        
    Returns:
        Return value from func.
        
    Raises:
        The last exception if all attempts fail.
    """
    last_exception = None
    
    for attempt in range(attempts):
        try:
            client = get_redis(url=url, cafile_path=cafile_path)
            return func(client)
        except (redis.ConnectionError, redis.TimeoutError) as e:
            last_exception = e
            if attempt == attempts - 1:
                logger.error(f"Function execution failed after {attempts} attempts: {e}")
                break
            
            logger.debug(f"Attempt {attempt + 1} failed, retrying: {e}")
            time.sleep(0.5 * (attempt + 1))  # Simple linear backoff
        except Exception as e:
            # Non-connection errors should not be retried
            logger.error(f"Non-retryable error in with_redis: {e}")
            raise
    
    # Re-raise the last connection error
    if last_exception:
        raise last_exception
    
    # Should never reach here, but just in case
    raise RuntimeError("Unexpected error in with_redis retry logic")


def set_json(client: redis.Redis, key: str, obj: Any, ex: int | None = None) -> bool:
    """
    Store object as JSON in Redis with deterministic byte encoding.
    
    Args:
        client: Redis client instance.
        key: Redis key.
        obj: Object to serialize as JSON.
        ex: Expiration time in seconds (optional).
        
    Returns:
        True if successful, False otherwise.
    """
    try:
        if HAS_ORJSON:
            # orjson returns bytes directly
            json_bytes = orjson.dumps(obj, option=orjson.OPT_SORT_KEYS)
        else:
            # Standard json with sorted keys for deterministic output
            json_str = json.dumps(obj, ensure_ascii=False, separators=(',', ':'), sort_keys=True)
            json_bytes = json_str.encode('utf-8')
        
        result = client.set(key, json_bytes, ex=ex)
        return bool(result)
    except Exception as e:
        logger.error(f"Failed to set JSON for key '{key}': {e}")
        return False


def get_json(client: redis.Redis, key: str) -> Any:
    """
    Retrieve and deserialize JSON object from Redis.
    
    Args:
        client: Redis client instance.
        key: Redis key.
        
    Returns:
        Deserialized object or None if key doesn't exist.
        
    Raises:
        json.JSONDecodeError: If stored data is not valid JSON.
    """
    try:
        data = client.get(key)
        if data is None:
            return None
        
        # Handle both bytes and string responses
        if isinstance(data, bytes):
            json_str = data.decode('utf-8')
        else:
            json_str = str(data)
        
        if HAS_ORJSON:
            return orjson.loads(json_str)
        else:
            return json.loads(json_str)
    except Exception as e:
        logger.error(f"Failed to get JSON for key '{key}': {e}")
        raise


def pubsub_subscribe(client: redis.Redis, channels: list[str]) -> redis.client.PubSub:
    """
    Create PubSub instance and subscribe to channels.
    
    Args:
        client: Redis client instance.
        channels: List of channel names to subscribe to.
        
    Returns:
        Configured PubSub instance.
    """
    pubsub = client.pubsub()
    if channels:
        pubsub.subscribe(*channels)
        logger.debug(f"Subscribed to channels: {channels}")
    return pubsub


def pubsub_get_message(ps: redis.client.PubSub, timeout_ms: int = 100) -> Any:
    """
    Non-blocking poll for PubSub message.
    
    Args:
        ps: PubSub instance.
        timeout_ms: Timeout in milliseconds for get_message.
        
    Returns:
        Message dict or None if no message available.
    """
    try:
        # Convert ms to seconds for redis-py timeout
        timeout_sec = timeout_ms / 1000.0
        return ps.get_message(timeout=timeout_sec)
    except Exception as e:
        logger.error(f"Error getting PubSub message: {e}")
        return None


def xadd_simple(
    client: redis.Redis, 
    stream: str, 
    fields: dict[str, Any], 
    maxlen: int | None = None
) -> str:
    """
    Add entry to Redis stream with optional length limiting.
    
    Args:
        client: Redis client instance.
        stream: Stream name.
        fields: Fields to add to stream entry.
        maxlen: Maximum stream length (optional, uses approximate trimming).
        
    Returns:
        Entry ID string.
    """
    try:
        kwargs = {}
        if maxlen is not None:
            kwargs['maxlen'] = maxlen
            kwargs['approximate'] = True  # More efficient than exact trimming
        
        entry_id = client.xadd(stream, fields, **kwargs)
        logger.debug(f"Added entry to stream '{stream}': {entry_id}")
        return entry_id
    except Exception as e:
        logger.error(f"Failed to add entry to stream '{stream}': {e}")
        raise


def _run_self_test() -> int:
    """
    Run CLI self-test functionality.
    
    Returns:
        Exit code: 0 for success, 1 for failure.
    """
    print(f"Redis Client Utility v{__version__}")
    print(f"redis-py version: {redis.__version__}")
    
    try:
        # Check environment
        redis_url = os.getenv("REDIS_URL")
        if not redis_url:
            print("❌ REDIS_URL environment variable not set")
            return 1
        
        parsed = urlparse(redis_url)
        print(f"📡 Connecting to: {parsed.scheme}://{parsed.hostname}:{parsed.port or 6379}")
        
        # Test basic connection and ping
        print("🔄 Testing connection...")
        client = get_redis()
        
        if not safe_ping(client):
            print("❌ Ping failed")
            return 1
        print("✅ Ping successful")
        
        # Test JSON operations
        print("🔄 Testing JSON operations...")
        test_data = {"timestamp": time.time(), "test": True, "nested": {"value": 42}}
        test_key = f"test:self-check:{int(time.time())}"
        
        if not set_json(client, test_key, test_data, ex=60):
            print("❌ JSON set failed")
            return 1
        
        retrieved = get_json(client, test_key)
        if retrieved != test_data:
            print("❌ JSON round-trip failed")
            return 1
        print("✅ JSON operations successful")
        
        # Test stream operations
        print("🔄 Testing stream operations...")
        stream_name = f"test:stream:{int(time.time())}"
        stream_data = {"test": "self-check", "timestamp": str(time.time())}
        
        entry_id = xadd_simple(client, stream_name, stream_data, maxlen=10)
        if not entry_id:
            print("❌ Stream add failed")
            return 1
        print(f"✅ Stream operations successful (entry: {entry_id})")
        
        # Cleanup
        client.delete(test_key)
        client.delete(stream_name)
        
        print("🎉 All tests passed!")
        return 0
        
    except Exception as e:
        print(f"❌ Self-test failed: {e}")
        logger.exception("Self-test exception details")
        return 1


if __name__ == "__main__":
    import sys
    
    # Configure basic logging for CLI mode
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    exit_code = _run_self_test()
    sys.exit(exit_code)