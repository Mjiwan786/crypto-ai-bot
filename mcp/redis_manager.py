# mcp/redis_manager.py
"""
Production-ready Redis manager for crypto-ai-bot with streaming, circuit breakers,
compression, and full async/sync support for high-frequency trading operations.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import ssl
import time
import zlib
from contextlib import asynccontextmanager, contextmanager
from decimal import Decimal
from enum import Enum
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Tuple, Union
from urllib.parse import urlparse

try:
    import orjson
    HAS_ORJSON = True
except ImportError:
    import json as orjson
    HAS_ORJSON = False

try:
    import redis
    import redis.asyncio
    from redis.exceptions import ConnectionError as RedisConnErr, TimeoutError as RedisTimeoutErr
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False
    redis = None
    RedisConnErr = Exception
    RedisTimeoutErr = Exception

try:
    from pydantic import BaseModel
    HAS_PYDANTIC = True
except ImportError:
    HAS_PYDANTIC = False
    BaseModel = object

__all__ = ["RedisManager", "AsyncRedisManager", "RedisUnavailable", "RedisConnectionError"]


# ======================
# Exceptions & utilities
# ======================
class RedisUnavailable(Exception):
    """Redis is temporarily unavailable due to circuit breaker."""
    pass


class RedisConnectionError(Exception):
    """Redis connection failed."""
    pass


class CircuitBreakerState(Enum):
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Circuit breaker tripped
    HALF_OPEN = "half_open" # Testing recovery


class CircuitBreaker:
    """Simple circuit breaker for Redis operations."""
    def __init__(self, failure_threshold: int = 5, cooldown_s: int = 60):
        self.failure_threshold = failure_threshold
        self.cooldown_s = cooldown_s
        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self.state = CircuitBreakerState.CLOSED
        self.logger = logging.getLogger(f"{__name__}.CircuitBreaker")

    def can_execute(self) -> bool:
        if self.state == CircuitBreakerState.CLOSED:
            return True
        if self.state == CircuitBreakerState.OPEN:
            if self.last_failure_time and (time.time() - self.last_failure_time) >= self.cooldown_s:
                self.state = CircuitBreakerState.HALF_OPEN
                self.logger.info("Circuit breaker entering HALF_OPEN state")
                return True
            return False
        # HALF_OPEN
        return True

    def on_success(self) -> None:
        if self.state == CircuitBreakerState.HALF_OPEN:
            self.state = CircuitBreakerState.CLOSED
            self.failure_count = 0
            self.logger.info("Circuit breaker reset to CLOSED state")

    def on_failure(self, exc: Exception) -> None:
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            if self.state != CircuitBreakerState.OPEN:
                self.state = CircuitBreakerState.OPEN
                self.logger.error(f"Circuit breaker OPENED after {self.failure_count} failures: {exc}")


# ======================
# Configuration
# ======================
class RedisConfig:
    """Redis configuration container (fallback if not using config_loader)."""

    def __init__(
        self,
        url: str = None,
        ssl: bool = True,
        ssl_verify: bool = True,
        ca_cert: Optional[str] = None,
        health_check_interval: int = 15,
        client_name: str = "crypto-ai-bot",
        connection_pool_size: int = 10,
        socket_timeout: int = 30,
        stream_ack_timeout: int = 5000,
        **kwargs,
    ):
        self.url = url or os.getenv("REDIS_URL", "")
        self.ssl = ssl
        self.ssl_verify = ssl_verify
        # Auto-detect CA cert for Redis Cloud
        if ca_cert:
            self.ca_cert = ca_cert
        else:
            # Try environment variable first
            env_cert = os.getenv("REDIS_CA_CERT")
            if env_cert and os.path.exists(env_cert):
                self.ca_cert = env_cert
            # Fall back to default location if URL is Redis Cloud
            elif self.url and "redis-cloud.com" in self.url:
                default_cert = "config/certs/redis_ca.pem"
                if os.path.exists(default_cert):
                    self.ca_cert = default_cert
                else:
                    self.ca_cert = None
            else:
                self.ca_cert = None
        self.health_check_interval = health_check_interval
        self.client_name = client_name
        self.connection_pool_size = connection_pool_size
        self.socket_timeout = socket_timeout
        self.stream_ack_timeout = stream_ack_timeout

        # Pipeline settings
        self.pipeline = getattr(kwargs.get("pipeline", {}), "__dict__", kwargs.get("pipeline", {}))
        if isinstance(self.pipeline, dict):
            self.pipeline_enabled = self.pipeline.get("enabled", True)
            self.pipeline_batch_size = self.pipeline.get("batch_size", 50)
        else:
            self.pipeline_enabled = getattr(self.pipeline, "enabled", True)
            self.pipeline_batch_size = getattr(self.pipeline, "batch_size", 50)

        # Compression settings
        self.compression = getattr(kwargs.get("compression", {}), "__dict__", kwargs.get("compression", {}))
        if isinstance(self.compression, dict):
            self.compression_enabled = self.compression.get("enabled", True)
            self.compression_threshold_kb = self.compression.get("threshold_kb", 2)
        else:
            self.compression_enabled = getattr(self.compression, "enabled", True)
            self.compression_threshold_kb = getattr(self.compression, "threshold_kb", 2)

        # Stream config
        self.stream_config = getattr(kwargs.get("stream_config", {}), "__dict__", kwargs.get("stream_config", {}))
        if isinstance(self.stream_config, dict):
            self.stream_max_len = self.stream_config.get("max_len", 10000)
            self.stream_approximate = self.stream_config.get("approximate", True)
            self.stream_batch_size = self.stream_config.get("batch_size", 100)
        else:
            self.stream_max_len = getattr(self.stream_config, "max_len", 10000)
            self.stream_approximate = getattr(self.stream_config, "approximate", True)
            self.stream_batch_size = getattr(self.stream_config, "batch_size", 100)

        # Reconnection strategy (used by retry wrapper)
        self.reconnect_strategy = getattr(kwargs.get("reconnect_strategy", {}), "__dict__", kwargs.get("reconnect_strategy", {}))
        if isinstance(self.reconnect_strategy, dict):
            self.reconnect_initial_delay = self.reconnect_strategy.get("initial_delay", 200) / 1000.0
            self.reconnect_max_delay = self.reconnect_strategy.get("max_delay", 10000) / 1000.0
            self.reconnect_jitter = self.reconnect_strategy.get("jitter", 300) / 1000.0
            self.reconnect_retries = self.reconnect_strategy.get("retries", 3)
        else:
            self.reconnect_initial_delay = getattr(self.reconnect_strategy, "initial_delay", 200) / 1000.0
            self.reconnect_max_delay = getattr(self.reconnect_strategy, "max_delay", 10000) / 1000.0
            self.reconnect_jitter = getattr(self.reconnect_strategy, "jitter", 300) / 1000.0
            self.reconnect_retries = getattr(self.reconnect_strategy, "retries", 3)


# ======================
# Base manager
# ======================
class BaseRedisManager:
    """Base Redis manager with shared functionality."""

    def __init__(self, config: Optional[RedisConfig] = None, *, url: Optional[str] = None):
        if not HAS_REDIS:
            raise ImportError("redis package is required but not installed")

        self.config = config or RedisConfig(url=url)
        if url and not config:
            self.config.url = url

        self.logger = logging.getLogger(__name__)
        self.circuit_breaker = CircuitBreaker()

        # Canonical stream names (override via config.streams if provided)
        # Try to use stream registry first, fall back to hardcoded defaults
        try:
            from config.stream_registry import get_all_streams
            registry_streams = get_all_streams()
            # Map registry streams to our internal names
            self.stream_names: Dict[str, str] = {
                "market_trades": registry_streams.get("trades", "md:trades"),
                "candles": registry_streams.get("ohlcv", "md:candles"),
                "signals_paper": registry_streams.get("signals", "signals:paper"),
                "signals_live": registry_streams.get("signals", "signals:live"),
                "events": "events:bus",  # Keep as fallback
                "orderbook": registry_streams.get("orderbook", "md:orderbook"),
                "scalp_signals": "signals:scalp",  # Keep as fallback
            }
        except ImportError:
            # Fallback to hardcoded defaults if stream registry not available
            self.stream_names: Dict[str, str] = {
                "market_trades": "md:trades",
                "candles": "md:candles",
                "signals_paper": "signals:paper",
                "signals_live": "signals:live",
                "events": "events:bus",
                "orderbook": "md:orderbook",
                "scalp_signals": "signals:scalp",
            }
        
        if hasattr(self.config, "streams") and self.config.streams:
            streams_dict = getattr(self.config.streams, "__dict__", self.config.streams)
            if isinstance(streams_dict, dict):
                self.stream_names.update(streams_dict)

    # --------- Serialization helpers ----------
    @staticmethod
    def stable_serialize(obj: Any) -> bytes:
        """Deterministic JSON-safe serialization (sorted keys; pydantic/model aware)."""
        def preprocess(o: Any) -> Any:
            if HAS_PYDANTIC and isinstance(o, BaseModel):
                return o.model_dump(mode="json", by_alias=True, exclude_none=True)
            if isinstance(o, set):
                return sorted(list(o))
            if isinstance(o, dict):
                return {str(k): preprocess(v) for k, v in sorted(o.items())}
            if isinstance(o, Decimal):
                return str(o)
            if isinstance(o, (list, tuple)):
                return [preprocess(i) for i in o]
            return o

        processed = preprocess(obj)
        if HAS_ORJSON:
            return orjson.dumps(processed, option=orjson.OPT_SORT_KEYS)
        return json.dumps(processed, sort_keys=True, separators=(",", ":")).encode("utf-8")

    @staticmethod
    def stable_hash(obj: Any) -> str:
        """Generate stable SHA256 hash of serialized object."""
        return hashlib.sha256(BaseRedisManager.stable_serialize(obj)).hexdigest()

    def maybe_compress(self, payload: bytes) -> Tuple[bytes, str]:
        """Compress payload if it exceeds threshold; return (payload, encoding)."""
        if self.config.compression_enabled and len(payload) >= self.config.compression_threshold_kb * 1024:
            try:
                compressed = zlib.compress(payload, level=6)
                if len(compressed) < len(payload):
                    return compressed, "zlib"
            except Exception as e:
                self.logger.debug(f"Compression failed: {e}")
        return payload, "plain"

    def maybe_decompress(self, payload: bytes, encoding: str) -> bytes:
        """Decompress payload based on encoding."""
        if encoding == "zlib":
            try:
                return zlib.decompress(payload)
            except Exception as e:
                self.logger.error(f"Decompression failed: {e}")
                return payload
        return payload

    @staticmethod
    def decode_message(msg: Dict[bytes, bytes]) -> Dict[str, Any]:
        """
        Decode Redis stream message, handling compression and JSON with correct per-field encoding.
        """
        result: Dict[str, Any] = {}
        global_encoding = "plain"
        field_enc: Dict[str, str] = {}
        raw_fields: Dict[str, bytes] = {}

        # First pass: decode keys and collect encodings
        for k, v in msg.items():
            ks = k.decode("utf-8") if isinstance(k, bytes) else str(k)
            if ks == "__encoding__":
                global_encoding = v.decode("utf-8") if isinstance(v, bytes) else str(v)
                continue
            if ks.endswith("__enc"):
                base = ks[:-5]
                field_enc[base] = v.decode("utf-8") if isinstance(v, bytes) else str(v)
                continue
            raw_fields[ks] = v if isinstance(v, (bytes, bytearray)) else str(v).encode("utf-8")

        # Second pass: per-field decode (prefer per-field over global)
        for ks, vb in raw_fields.items():
            enc = field_enc.get(ks, global_encoding if global_encoding != "mixed" else "plain")
            data = vb

            # Guarded decompression
            if enc == "zlib" and len(data) > 8:
                try:
                    data = zlib.decompress(data)
                except Exception:
                    pass  # fall through

            # Try JSON first
            try:
                if HAS_ORJSON:
                    result[ks] = orjson.loads(data)
                else:
                    result[ks] = json.loads(data.decode("utf-8"))
                continue
            except Exception:
                pass

            # Fallback to text
            try:
                result[ks] = data.decode("utf-8")
            except Exception:
                result[ks] = data

        return result

    def stream_for(self, pair: str, base: str) -> str:
        """Generate shard-friendly stream name."""
        return f"{base}:{pair.replace('/', '-')}"

    def _serialize_fields(self, fields: Dict[str, Any]) -> Dict[str, bytes]:
        """Serialize and compress fields for Redis storage."""
        result: Dict[str, bytes] = {}
        has_compression = False

        for key, value in fields.items():
            if isinstance(value, (str, int, float, bool)):
                result[key] = str(value).encode("utf-8")
            else:
                serialized = self.stable_serialize(value)
                compressed, encoding = self.maybe_compress(serialized)
                result[key] = compressed
                if encoding != "plain":
                    result[f"{key}__enc"] = encoding.encode("utf-8")
                    has_compression = True

        if has_compression:
            result["__encoding__"] = b"mixed"
        return result


# ======================
# Sync manager
# ======================
class RedisManager(BaseRedisManager):
    """Synchronous Redis manager for crypto trading operations."""

    def __init__(self, config: Optional[RedisConfig] = None, *, url: Optional[str] = None):
        super().__init__(config, url=url)
        self.client: Optional[redis.Redis] = None
        self._health_check_task: Optional[int] = None  # placeholder for parity

    # Context manager support
    def __enter__(self) -> "RedisManager":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def connect(self) -> bool:
        """
        Establish Redis connection with production settings.

        IMPORTANT: This method NEVER raises exceptions. It always returns a success boolean.
        If Redis is unavailable, logs warnings and returns False.

        Returns:
            True if connected successfully, False otherwise
        """
        if not self.config.url:
            self.logger.warning("⚠️ Redis URL not configured - app will start anyway")
            return False

        max_retries = self.config.reconnect_retries
        delay = self.config.reconnect_initial_delay
        last_error = None

        redis_kwargs = {
            "decode_responses": False,
            "socket_timeout": self.config.socket_timeout,
            "socket_connect_timeout": self.config.socket_timeout,
            "socket_keepalive": True,
            "health_check_interval": self.config.health_check_interval,
            "client_name": self.config.client_name,
            "retry_on_timeout": True,
            "max_connections": self.config.connection_pool_size,
        }

        for attempt in range(1, max_retries + 1):
            try:
                # For rediss:// URLs (Redis Cloud, TLS connections), let redis-py handle SSL automatically
                # Don't pass SSL parameters - they cause compatibility issues with redis-py 5.x
                if "redis-cloud.com" in self.config.url or self.config.url.startswith("rediss://"):
                    # Use from_url and let redis-py handle SSL for rediss:// URLs
                    self.client = redis.from_url(
                        self.config.url,
                        decode_responses=redis_kwargs["decode_responses"],
                        socket_timeout=redis_kwargs["socket_timeout"],
                        socket_connect_timeout=redis_kwargs["socket_connect_timeout"],
                        socket_keepalive=redis_kwargs["socket_keepalive"],
                        health_check_interval=redis_kwargs["health_check_interval"],
                        client_name=redis_kwargs["client_name"],
                        retry_on_timeout=redis_kwargs["retry_on_timeout"],
                        max_connections=redis_kwargs["max_connections"],
                    )
                else:
                    # Standard redis:// URL (non-TLS)
                    url = self.config.url
                    if self.config.ssl and url.startswith("redis://"):
                        url = url.replace("redis://", "rediss://", 1)

                    # Let redis-py handle SSL automatically for rediss:// URLs
                    self.client = redis.from_url(url, **redis_kwargs)

                # Test connection
                self.client.ping()

                # Create safe URL for logging (hide password)
                parsed = urlparse(self.config.url)
                if parsed.password:
                    safe_url = f"{parsed.scheme}://{parsed.username or 'default'}:***@{parsed.hostname}:{parsed.port or 6379}"
                else:
                    safe_url = self.config.url.split("@")[-1] if "@" in self.config.url else self.config.url

                self.logger.info(f"✅ Connected to Redis on attempt {attempt}/{max_retries}: {safe_url}")
                self.circuit_breaker.on_success()
                return True

            except Exception as e:
                last_error = str(e)
                self.logger.warning(f"Redis connection failed on attempt {attempt}/{max_retries}: {e}")
                self.circuit_breaker.on_failure(e)

            # Exponential backoff with cap at max_delay
            if attempt < max_retries:
                backoff = min(delay * (2 ** (attempt - 1)), self.config.reconnect_max_delay)
                self.logger.debug(f"Retrying in {backoff:.1f}s...")
                time.sleep(backoff)

        # All retries exhausted
        self.logger.warning(
            f"⚠️ Redis unavailable after {max_retries} attempts. Last error: {last_error}\n"
            f"   App will start anyway. Routes/components will degrade gracefully."
        )
        return False

    def close(self) -> None:
        """Close Redis connection."""
        if self.client:
            try:
                self.client.close()
                self.logger.info("Redis connection closed")
            except Exception as e:
                self.logger.error(f"Error closing Redis connection: {e}")
            finally:
                self.client = None

    def _with_retry(self, op_name: str, func, *args, **kwargs):
        """Retry wrapper (connection/timeouts) with exponential backoff + circuit breaker."""
        if not self.circuit_breaker.can_execute():
            raise RedisUnavailable(f"Circuit breaker open for {op_name}")

        delay = self.config.reconnect_initial_delay
        retries = self.config.reconnect_retries
        for attempt in range(retries + 1):
            try:
                if not self.client:
                    self.connect()
                result = func(*args, **kwargs)
                self.circuit_breaker.on_success()
                return result
            except (RedisConnErr, RedisTimeoutErr) as e:
                self.circuit_breaker.on_failure(e)
                if attempt >= retries:
                    raise RedisConnectionError(f"Redis {op_name} failed after retries: {e}") from e
                time.sleep(min(delay, self.config.reconnect_max_delay))
                delay = min(delay * 2 + self.config.reconnect_jitter, self.config.reconnect_max_delay)
            except Exception as e:
                self.circuit_breaker.on_failure(e)
                raise

    def ping(self) -> bool:
        """Test Redis connection."""
        try:
            return self._with_retry("ping", lambda: self.client.ping())
        except Exception:
            return False

    def info(self) -> Dict[str, Union[str, int, float]]:
        """Get Redis server info (subset)."""
        try:
            raw = self._with_retry("info", lambda: self.client.info())
            return {
                "used_memory": raw.get("used_memory", 0),
                "connected_clients": raw.get("connected_clients", 0),
                "instantaneous_ops_per_sec": raw.get("instantaneous_ops_per_sec", 0),
                "role": raw.get("role", "unknown"),
                "redis_version": raw.get("redis_version", "unknown"),
            }
        except Exception as e:
            self.logger.error(f"Failed to get Redis info: {e}")
            return {}

    def ensure_group(self, stream: str, group: str) -> None:
        """Create consumer group if it doesn't exist."""
        try:
            self._with_retry(
                "ensure_group",
                lambda: self.client.xgroup_create(stream, group, id="0", mkstream=True),
            )
            self.logger.debug(f"Created consumer group {group} on stream {stream}")
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise
        except Exception as e:
            self.logger.error(f"Failed to ensure group {group} on {stream}: {e}")
            raise

    def ensure_streams_and_groups(self, mapping: Dict[str, List[str]]) -> None:
        """Ensure multiple streams and their consumer groups exist."""
        for stream, groups in mapping.items():
            for group in groups:
                self.ensure_group(stream, group)

    def xadd(self, stream: str, fields: Dict[str, Any], *, maxlen: Optional[int] = None, approximate: bool = True) -> str:
        """Add message to stream with automatic serialization and compression."""
        if maxlen is None:
            maxlen = self.config.stream_max_len
        if approximate is None:
            approximate = self.config.stream_approximate

        redis_fields = self._serialize_fields(fields)
        if "timestamp" not in redis_fields:
            redis_fields["timestamp"] = str(time.time()).encode("utf-8")

        return self._with_retry(
            "xadd",
            lambda: self.client.xadd(stream, redis_fields, maxlen=maxlen, approximate=approximate),
        )

    def xreadgroup(
        self,
        group: str,
        consumer: str,
        streams: Dict[str, str],
        *,
        count: Optional[int] = None,
        block_ms: Optional[int] = None,
    ) -> List:
        """Read messages from streams using consumer group."""
        if count is None:
            count = self.config.stream_batch_size
        if block_ms is None:
            block_ms = self.config.stream_ack_timeout

        return self._with_retry(
            "xreadgroup",
            lambda: self.client.xreadgroup(group, consumer, streams, count=count, block=block_ms),
        )

    def xack(self, stream: str, group: str, *ids: str) -> int:
        """Acknowledge processed messages."""
        if not ids:
            return 0
        return self._with_retry("xack", lambda: self.client.xack(stream, group, *ids))

    def xclaim_pending(
        self,
        stream: str,
        group: str,
        consumer: str,
        min_idle_ms: int,
        *,
        count: int = 100,
    ) -> List:
        """Claim pending messages from dead consumers."""
        try:
            pending = self._with_retry(
                "xpending",
                lambda: self.client.xpending_range(stream, group, min_idle_ms, "-", "+", count),
            )
            if not pending:
                return []

            if isinstance(pending[0], dict):
                message_ids = [msg["message_id"] for msg in pending]
            else:
                message_ids = [msg[0] if isinstance(msg, (list, tuple)) else msg for msg in pending]

            return self._with_retry(
                "xclaim",
                lambda: self.client.xclaim(stream, group, consumer, min_idle_ms, message_ids),
            )
        except Exception as e:
            self.logger.error(f"Failed to claim pending messages: {e}")
            return []

    @contextmanager
    def pipeline(self):
        """
        Context manager for Redis pipeline.
        Note: This doesn't auto-execute; caller must call execute().
        """
        if not self.client:
            self.connect()
        pipe = self.client.pipeline(transaction=False)
        try:
            yield pipe
        finally:
            pass

    def batch_xadd(
        self,
        stream: str,
        messages: List[Dict[str, Any]],
        *,
        maxlen: Optional[int] = None,
        approximate: bool = True,
    ) -> List[str]:
        """Add multiple messages to stream using pipeline."""
        if not messages:
            return []
        if maxlen is None:
            maxlen = self.config.stream_max_len

        results: List[str] = []
        batch_size = self.config.pipeline_batch_size

        for i in range(0, len(messages), batch_size):
            batch = messages[i : i + batch_size]
            with self.pipeline() as pipe:
                for msg in batch:
                    redis_fields = self._serialize_fields(msg)
                    if "timestamp" not in redis_fields:
                        redis_fields["timestamp"] = str(time.time()).encode("utf-8")
                    pipe.xadd(stream, redis_fields, maxlen=maxlen, approximate=approximate)
                batch_results = self._with_retry("batch_xadd", pipe.execute)
                results.extend(batch_results)
        return results

    def publish(self, channel: str, data: Any) -> int:
        """Publish message to Redis channel with consistent payload format."""
        if isinstance(data, (bytes, str)):
            payload = data.encode("utf-8") if isinstance(data, str) else data
        else:
            payload = self.stable_serialize(data)

        compressed, encoding = self.maybe_compress(payload)

        # Always wrap for predictable subscriber behavior
        message = {"__encoding__": encoding, "data": compressed}
        final_payload = self.stable_serialize(message)

        return self._with_retry("publish", lambda: self.client.publish(channel, final_payload))

    def subscribe(self, channels: List[str]) -> Iterator[Tuple[str, Any]]:
        """Subscribe to Redis channels (generator)."""
        if not self.client:
            self.connect()

        pubsub = self.client.pubsub(ignore_subscribe_messages=True)
        try:
            pubsub.subscribe(*channels)
            for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                channel = message["channel"].decode("utf-8") if isinstance(message["channel"], (bytes, bytearray)) else message["channel"]
                data = message["data"]

                try:
                    if isinstance(data, (bytes, bytearray)):
                        try:
                            parsed = json.loads(data.decode("utf-8"))
                            if isinstance(parsed, dict) and "__encoding__" in parsed:
                                encoding = parsed["__encoding__"]
                                payload = parsed["data"]
                                if isinstance(payload, str):
                                    payload = payload.encode("utf-8")
                                decompressed = self.maybe_decompress(payload, encoding)
                                if HAS_ORJSON:
                                    yield channel, orjson.loads(decompressed)
                                else:
                                    yield channel, json.loads(decompressed.decode("utf-8"))
                            else:
                                yield channel, parsed
                        except (json.JSONDecodeError, KeyError):
                            if HAS_ORJSON:
                                try:
                                    yield channel, orjson.loads(data)
                                except Exception:
                                    yield channel, data.decode("utf-8")
                            else:
                                try:
                                    yield channel, json.loads(data.decode("utf-8"))
                                except Exception:
                                    yield channel, data.decode("utf-8")
                    else:
                        yield channel, data
                except Exception as e:
                    self.logger.error(f"Failed to decode message from {channel}: {e}")
                    yield channel, data
        except Exception as e:
            self.logger.error(f"Subscription error: {e}")
        finally:
            try:
                pubsub.unsubscribe(*channels)
            except Exception:
                pass
            pubsub.close()


# ======================
# Async manager
# ======================
class AsyncRedisManager(BaseRedisManager):
    """Asynchronous Redis manager for crypto trading operations."""

    def __init__(self, config: Optional[RedisConfig] = None, *, url: Optional[str] = None):
        super().__init__(config, url=url)
        self.client: Optional[redis.asyncio.Redis] = None
        self._health_task: Optional[asyncio.Task] = None
        self._running = False

    # Async context manager support
    async def __aenter__(self) -> "AsyncRedisManager":
        await self.aconnect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def aconnect(self) -> bool:
        """
        Establish async Redis connection with retry and exponential backoff.

        IMPORTANT: This method NEVER raises exceptions. It always returns a success boolean.
        If Redis is unavailable, logs warnings and returns False.

        Returns:
            True if connected successfully, False otherwise
        """
        if not self.config.url:
            self.logger.warning("⚠️ Redis URL not configured - app will start anyway")
            return False

        max_retries = self.config.reconnect_retries
        delay = self.config.reconnect_initial_delay

        redis_kwargs = {
            "decode_responses": False,
            "socket_timeout": self.config.socket_timeout,
            "socket_connect_timeout": self.config.socket_timeout,
            "socket_keepalive": True,
            "health_check_interval": self.config.health_check_interval,
            "client_name": self.config.client_name,
            "retry_on_timeout": True,
            "max_connections": self.config.connection_pool_size,
        }

        last_error = None

        for attempt in range(1, max_retries + 1):
            try:
                if "redis-cloud.com" in self.config.url or self.config.url.startswith("rediss://"):
                    # For rediss:// URL, let redis-py handle SSL automatically
                    # Don't pass SSL parameters - they cause issues with redis-py 5.x asyncio
                    self.client = redis.asyncio.from_url(
                        self.config.url,
                        decode_responses=redis_kwargs["decode_responses"],
                        socket_timeout=redis_kwargs["socket_timeout"],
                        socket_connect_timeout=redis_kwargs["socket_connect_timeout"],
                        socket_keepalive=redis_kwargs["socket_keepalive"],
                        health_check_interval=redis_kwargs["health_check_interval"],
                        client_name=redis_kwargs["client_name"],
                        retry_on_timeout=redis_kwargs["retry_on_timeout"],
                        max_connections=redis_kwargs["max_connections"],
                    )
                else:
                    # Normalize to rediss if SSL requested
                    url = self.config.url
                    if self.config.ssl and url.startswith("redis://"):
                        url = url.replace("redis://", "rediss://", 1)

                    # Let redis-py handle SSL automatically for rediss:// URLs
                    self.client = redis.asyncio.from_url(url, **redis_kwargs)

                # Test connection with timeout
                await asyncio.wait_for(self.client.ping(), timeout=3.0)

                # Create safe URL for logging (hide password)
                parsed = urlparse(self.config.url)
                if parsed.password:
                    safe_url = f"{parsed.scheme}://{parsed.username or 'default'}:***@{parsed.hostname}:{parsed.port or 6379}"
                else:
                    safe_url = self.config.url.split("@")[-1] if "@" in self.config.url else self.config.url
                self.logger.info(f"✅ Connected to Redis (async) on attempt {attempt}/{max_retries}: {safe_url}")

                self._running = True
                if self.config.health_check_interval > 0:
                    self._health_task = asyncio.create_task(self._health_monitor())

                self.circuit_breaker.on_success()
                return True

            except asyncio.TimeoutError:
                last_error = "Connection timeout (3s)"
                self.logger.warning(f"Redis connection timeout on attempt {attempt}/{max_retries}")
                self.circuit_breaker.on_failure(Exception(last_error))

            except Exception as e:
                last_error = str(e)
                self.logger.warning(f"Redis connection failed on attempt {attempt}/{max_retries}: {e}")
                self.circuit_breaker.on_failure(e)

            # Exponential backoff with cap at max_delay
            if attempt < max_retries:
                backoff = min(delay * (2 ** (attempt - 1)), self.config.reconnect_max_delay)
                self.logger.debug(f"Retrying in {backoff:.1f}s...")
                await asyncio.sleep(backoff)

        # All retries exhausted
        self._running = False
        self.logger.warning(
            f"⚠️ Redis unavailable after {max_retries} attempts. Last error: {last_error}\n"
            f"   App will start anyway. Routes/components will degrade gracefully."
        )
        return False

    async def aclose(self) -> None:
        """Close async Redis connection."""
        self._running = False
        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass
            finally:
                self._health_task = None
        if self.client:
            try:
                await self.client.aclose()
                self.logger.info("Redis connection closed (async)")
            except Exception as e:
                self.logger.error(f"Error closing Redis connection: {e}")
            finally:
                self.client = None

    async def _health_monitor(self) -> None:
        """Background health monitoring task with exponential backoff."""
        delay = self.config.health_check_interval
        failures = 0
        while self._running:
            try:
                await asyncio.sleep(delay)
                if self.client and self._running:
                    await self.client.ping()
                    self.circuit_breaker.on_success()
                    failures = 0
            except asyncio.CancelledError:
                break
            except Exception as e:
                failures += 1
                backoff = min(delay * (2 ** min(failures, 5)), 60)
                self.logger.warning(
                    f"Health check failed (attempt {failures}): {e}, backing off {backoff}s"
                )
                await asyncio.sleep(max(backoff - delay, 0))
                self.circuit_breaker.on_failure(e)

    async def _with_retry(self, op_name: str, coro_factory):
        """Async retry wrapper (connection/timeouts) with exponential backoff + circuit breaker."""
        if not self.circuit_breaker.can_execute():
            raise RedisUnavailable(f"Circuit breaker open for {op_name}")

        delay = self.config.reconnect_initial_delay
        retries = self.config.reconnect_retries
        for attempt in range(retries + 1):
            try:
                if not self.client:
                    await self.aconnect()
                result = await coro_factory()
                self.circuit_breaker.on_success()
                return result
            except (RedisConnErr, RedisTimeoutErr) as e:
                self.circuit_breaker.on_failure(e)
                if attempt >= retries:
                    raise RedisConnectionError(f"Redis {op_name} failed after retries: {e}") from e
                await asyncio.sleep(min(delay, self.config.reconnect_max_delay))
                delay = min(delay * 2 + self.config.reconnect_jitter, self.config.reconnect_max_delay)
            except Exception as e:
                self.circuit_breaker.on_failure(e)
                raise

    async def ping(self) -> bool:
        """Test Redis connection."""
        try:
            return await self._with_retry("ping", lambda: self.client.ping())
        except Exception:
            return False

    async def info(self) -> Dict[str, Union[str, int, float]]:
        """Get Redis server info (subset)."""
        try:
            raw = await self._with_retry("info", lambda: self.client.info())
            return {
                "used_memory": raw.get("used_memory", 0),
                "connected_clients": raw.get("connected_clients", 0),
                "instantaneous_ops_per_sec": raw.get("instantaneous_ops_per_sec", 0),
                "role": raw.get("role", "unknown"),
                "redis_version": raw.get("redis_version", "unknown"),
            }
        except Exception as e:
            self.logger.error(f"Failed to get Redis info: {e}")
            return {}

    async def ensure_group(self, stream: str, group: str) -> None:
        """Create consumer group if it doesn't exist."""
        try:
            await self._with_retry(
                "ensure_group",
                lambda: self.client.xgroup_create(stream, group, id="0", mkstream=True),
            )
            self.logger.debug(f"Created consumer group {group} on stream {stream}")
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise
        except Exception as e:
            self.logger.error(f"Failed to ensure group {group} on {stream}: {e}")
            raise

    async def ensure_streams_and_groups(self, mapping: Dict[str, List[str]]) -> None:
        """Ensure multiple streams and their consumer groups exist."""
        for stream, groups in mapping.items():
            for group in groups:
                await self.ensure_group(stream, group)

    async def axadd(self, stream: str, fields: Dict[str, Any], *, maxlen: Optional[int] = None, approximate: bool = True) -> str:
        """Add message to stream with automatic serialization and compression."""
        if maxlen is None:
            maxlen = self.config.stream_max_len
        if approximate is None:
            approximate = self.config.stream_approximate

        redis_fields = self._serialize_fields(fields)
        if "timestamp" not in redis_fields:
            redis_fields["timestamp"] = str(time.time()).encode("utf-8")

        return await self._with_retry(
            "xadd",
            lambda: self.client.xadd(stream, redis_fields, maxlen=maxlen, approximate=approximate),
        )

    async def axreadgroup(
        self,
        group: str,
        consumer: str,
        streams: Dict[str, str],
        *,
        count: Optional[int] = None,
        block_ms: Optional[int] = None,
    ) -> List:
        """Read messages from streams using consumer group."""
        if count is None:
            count = self.config.stream_batch_size
        if block_ms is None:
            block_ms = self.config.stream_ack_timeout

        return await self._with_retry(
            "xreadgroup",
            lambda: self.client.xreadgroup(group, consumer, streams, count=count, block=block_ms),
        )

    async def axack(self, stream: str, group: str, *ids: str) -> int:
        """Acknowledge processed messages."""
        if not ids:
            return 0
        return await self._with_retry("xack", lambda: self.client.xack(stream, group, *ids))

    async def axclaim_pending(
        self,
        stream: str,
        group: str,
        consumer: str,
        min_idle_ms: int,
        *,
        count: int = 100,
    ) -> List:
        """Claim pending messages from dead consumers."""
        try:
            pending = await self._with_retry(
                "xpending",
                lambda: self.client.xpending_range(stream, group, min_idle_ms, "-", "+", count),
            )
            if not pending:
                return []

            if isinstance(pending[0], dict):
                message_ids = [msg["message_id"] for msg in pending]
            else:
                message_ids = [msg[0] if isinstance(msg, (list, tuple)) else msg for msg in pending]

            return await self._with_retry(
                "xclaim",
                lambda: self.client.xclaim(stream, group, consumer, min_idle_ms, message_ids),
            )
        except Exception as e:
            self.logger.error(f"Failed to claim pending messages: {e}")
            return []

    @asynccontextmanager
    async def apipeline(self):
        """
        Async context manager for Redis pipeline.
        Note: This doesn't auto-execute; caller must call execute().
        """
        if not self.client:
            await self.aconnect()
        pipe = self.client.pipeline(transaction=False)
        try:
            yield pipe
        finally:
            pass

    async def batch_xadd(
        self,
        stream: str,
        messages: List[Dict[str, Any]],
        *,
        maxlen: Optional[int] = None,
        approximate: bool = True,
    ) -> List[str]:
        """Add multiple messages to stream using pipeline."""
        if not messages:
            return []
        if maxlen is None:
            maxlen = self.config.stream_max_len

        results: List[str] = []
        batch_size = self.config.pipeline_batch_size

        for i in range(0, len(messages), batch_size):
            batch = messages[i : i + batch_size]
            async with self.apipeline() as pipe:
                for msg in batch:
                    redis_fields = self._serialize_fields(msg)
                    if "timestamp" not in redis_fields:
                        redis_fields["timestamp"] = str(time.time()).encode("utf-8")
                    pipe.xadd(stream, redis_fields, maxlen=maxlen, approximate=approximate)
                batch_results = await self._with_retry("batch_xadd", lambda: pipe.execute())
                results.extend(batch_results)
        return results

    async def apublish(self, channel: str, data: Any) -> int:
        """Publish message to Redis channel with consistent payload format."""
        if isinstance(data, (bytes, str)):
            payload = data.encode("utf-8") if isinstance(data, str) else data
        else:
            payload = self.stable_serialize(data)

        compressed, encoding = self.maybe_compress(payload)
        message = {"__encoding__": encoding, "data": compressed}
        final_payload = self.stable_serialize(message)

        return await self._with_retry("publish", lambda: self.client.publish(channel, final_payload))

    async def asubscribe(self, channels: List[str]) -> AsyncIterator[Tuple[str, Any]]:
        """Subscribe to Redis channels (async iterator)."""
        if not self.client:
            await self.aconnect()

        pubsub = self.client.pubsub(ignore_subscribe_messages=True)
        try:
            await pubsub.subscribe(*channels)
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                channel = message["channel"].decode("utf-8") if isinstance(message["channel"], (bytes, bytearray)) else message["channel"]
                data = message["data"]

                try:
                    if isinstance(data, (bytes, bytearray)):
                        try:
                            parsed = json.loads(data.decode("utf-8"))
                            if isinstance(parsed, dict) and "__encoding__" in parsed:
                                encoding = parsed["__encoding__"]
                                payload = parsed["data"]
                                if isinstance(payload, str):
                                    payload = payload.encode("utf-8")
                                decompressed = self.maybe_decompress(payload, encoding)
                                if HAS_ORJSON:
                                    yield channel, orjson.loads(decompressed)
                                else:
                                    yield channel, json.loads(decompressed.decode("utf-8"))
                            else:
                                yield channel, parsed
                        except (json.JSONDecodeError, KeyError):
                            if HAS_ORJSON:
                                try:
                                    yield channel, orjson.loads(data)
                                except Exception:
                                    yield channel, data.decode("utf-8")
                            else:
                                try:
                                    yield channel, json.loads(data.decode("utf-8"))
                                except Exception:
                                    yield channel, data.decode("utf-8")
                    else:
                        yield channel, data
                except Exception as e:
                    self.logger.error(f"Failed to decode message from {channel}: {e}")
                    yield channel, data
        except Exception as e:
            self.logger.error(f"Subscription error: {e}")
        finally:
            try:
                await pubsub.unsubscribe(*channels)
            except Exception:
                pass
            await pubsub.aclose()

    # Aliases for API symmetry
    async def xadd(self, stream: str, fields: Dict[str, Any], *, maxlen: Optional[int] = None, approximate: bool = True) -> str:
        return await self.axadd(stream, fields, maxlen=maxlen, approximate=approximate)

    async def xreadgroup(
        self,
        group: str,
        consumer: str,
        streams: Dict[str, str],
        *,
        count: Optional[int] = None,
        block_ms: Optional[int] = None,
    ) -> List:
        return await self.axreadgroup(group, consumer, streams, count=count, block_ms=block_ms)

    async def xack(self, stream: str, group: str, *ids: str) -> int:
        return await self.axack(stream, group, *ids)

    async def xclaim_pending(
        self,
        stream: str,
        group: str,
        consumer: str,
        min_idle_ms: int,
        *,
        count: int = 100,
    ) -> List:
        return await self.axclaim_pending(stream, group, consumer, min_idle_ms, count=count)

    async def publish(self, channel: str, data: Any) -> int:
        return await self.apublish(channel, data)

    def subscribe(self, channels: List[str]) -> AsyncIterator[Tuple[str, Any]]:
        # Intentionally returns an async iterator for symmetry with asubscribe
        return self.asubscribe(channels)

    def pipeline(self):
        return self.apipeline()


# ======================
# Smoke test (manual)
# ======================
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    logger = logging.getLogger(__name__)

    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        logger.warning("⚠️ REDIS_URL not set, skipping smoke test")
        sys.exit(0)

    async def async_smoke_test():
        """Async smoke test."""
        config = RedisConfig(url=redis_url)
        manager = AsyncRedisManager(config)

        test_stream = "test:smoke"
        test_group = "smoke_group"
        test_consumer = "smoke_consumer"

        try:
            logger.info("🧪 Running async Redis smoke test...")

            await manager.aconnect()
            logger.info("✅ Async connection established")

            pong = await manager.ping()
            assert pong, "Ping failed"
            logger.info("✅ Ping test passed")

            info = await manager.info()
            assert info, "Info failed"
            logger.info(f"✅ Info test passed: {info.get('redis_version', 'unknown')}")

            await manager.ensure_group(test_stream, test_group)
            logger.info("✅ Consumer group created")

            test_data = {
                "symbol": "BTC/USD",
                "side": "buy",
                "price": 45000.50,
                "volume": 0.1,
                "metadata": {"strategy": "scalp", "confidence": 0.85},
                "features": [1.2, 3.4, 5.6],
            }

            msg_id = await manager.xadd(test_stream, test_data)
            assert msg_id, "xadd failed"
            logger.info(f"✅ Message added: {msg_id}")

            messages = await manager.xreadgroup(
                test_group, test_consumer, {test_stream: ">"}, count=1, block_ms=1000
            )
            assert messages, "xreadgroup failed"
            logger.info("✅ Message read from stream")

            stream_name, stream_messages = messages[0]
            msg_id, fields = stream_messages[0]
            decoded = manager.decode_message(fields)

            assert decoded["symbol"] == "BTC/USD", "Message decode failed"
            assert decoded["metadata"]["strategy"] == "scalp", "Nested decode failed"
            logger.info("✅ Message decode test passed")

            ack_count = await manager.xack(test_stream, test_group, msg_id)
            assert ack_count == 1, "xack failed"
            logger.info("✅ Message acknowledged")

            batch_messages = [{"test": "batch1", "value": i} for i in range(5)]
            batch_ids = await manager.batch_xadd(test_stream, batch_messages)
            assert len(batch_ids) == 5, "Batch xadd failed"
            logger.info("✅ Batch operations test passed")

            test_channel = "test:pubsub"
            pub_result = await manager.publish(test_channel, {"test": "pubsub", "data": [1, 2, 3]})
            logger.info(f"✅ Publish test passed: {pub_result}")

            if hasattr(manager.client, "delete"):
                await manager.client.delete(test_stream)
            elif hasattr(manager.client, "unlink"):
                await manager.client.unlink(test_stream)

            await manager.aclose()
            logger.info("✅ Async smoke test completed successfully!")
            return True
        except Exception as e:
            logger.error(f"❌ Async smoke test failed: {e}")
            try:
                await manager.aclose()
            except Exception:
                pass
            return False

    def sync_smoke_test():
        """Sync smoke test."""
        config = RedisConfig(url=redis_url)
        manager = RedisManager(config)

        test_stream = "test:smoke_sync"
        test_group = "smoke_group_sync"
        test_consumer = "smoke_consumer_sync"

        try:
            logger.info("🧪 Running sync Redis smoke test...")

            manager.connect()
            logger.info("✅ Sync connection established")

            pong = manager.ping()
            assert pong, "Ping failed"
            logger.info("✅ Sync ping test passed")

            manager.ensure_group(test_stream, test_group)

            test_data = {"sync_test": True, "value": 42}
            msg_id = manager.xadd(test_stream, test_data)
            assert msg_id, "Sync xadd failed"
            logger.info("✅ Sync message operations passed")

            if hasattr(manager.client, "delete"):
                manager.client.delete(test_stream)
            elif hasattr(manager.client, "unlink"):
                manager.client.unlink(test_stream)

            manager.close()
            logger.info("✅ Sync smoke test completed successfully!")
            return True
        except Exception as e:
            logger.error(f"❌ Sync smoke test failed: {e}")
            try:
                manager.close()
            except Exception:
                pass
            return False

    try:
        sync_success = sync_smoke_test()
        async_success = asyncio.run(async_smoke_test())
        if sync_success and async_success:
            logger.info("🎉 ALL SMOKE TESTS PASSED - Redis manager ready for production!")
            sys.exit(0)
        else:
            logger.error("💥 Some smoke tests failed")
            sys.exit(1)
    except KeyboardInterrupt:
        logger.info("⏹️ Smoke test interrupted")
        sys.exit(1)
    except Exception as e:
        logger.error(f"💥 Smoke test error: {e}")
        sys.exit(1)
