# agents/scalper/infra/redis_bus.py
#
# Production-grade Redis message bus for inter-agent communication.
# - Supports Streams (consumer groups), Pub/Sub, simple queues, and request/response (RPC)
# - Rediss/TLS (Redis Cloud) ready: ssl, certifi CA, hostname checking
# - Config-driven: decode_responses, pool sizes, timeouts, health checks, retry-on-timeout
# - Optional payload compression (gzip+base64) behind size threshold
# - Backpressure-friendly stream trimming, consumer group bootstrap
# - Robust pub/sub loop (single shared pubsub, proper subscribe/unsubscribe)
# - Safer byte<->str handling depending on decode_responses
# - Metrics & health
#
# Expected redis_config keys (all optional):
#   url, db, ssl, ssl_cert_reqs, ssl_ca_certs, ssl_check_hostname,
#   decode_responses, client_name,
#   connection_pool_size, socket_timeout, socket_connect_timeout,
#   health_check_interval, retry_on_timeout,
#   stream_max_len, stream_batch_size,
#   pipeline_threshold,
#   compression_enabled, compression_threshold_kb
#
# NOTE: Do not hardcode credentials here; pass the `url` from env (rediss://...)
#

import asyncio
import base64
import json
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Optional, Tuple, Union

import redis.asyncio as redis
from pydantic import BaseModel, Field

from utils.logger import get_logger


class MessageType(str, Enum):
    MARKET_DATA = "market_data"
    SIGNAL = "signal"
    ORDER = "order"
    EXECUTION = "execution"
    RISK = "risk"
    HEALTH = "health"
    CONTROL = "control"
    METRICS = "metrics"


class DeliveryMode(str, Enum):
    STREAM = "stream"
    PUBSUB = "pubsub"
    QUEUE = "queue"
    REQUEST_RESPONSE = "rpc"


@dataclass
class StreamConfig:
    name: str
    consumer_group: str
    consumer_name: str
    max_pending: int = 1000
    max_len: int = 10000
    batch_size: int = 10
    block_time_ms: int = 1000
    trim_strategy: str = "MAXLEN"  # kept for future MINID support
    approximate_trim: bool = True


@dataclass
class MessageMetrics:
    messages_sent: int = 0
    messages_received: int = 0
    messages_failed: int = 0
    bytes_sent: int = 0
    bytes_received: int = 0
    avg_send_latency_ms: float = 0.0
    avg_receive_latency_ms: float = 0.0
    active_streams: int = 0
    active_subscriptions: int = 0
    connection_failures: int = 0
    last_activity_time: Optional[float] = None


class Message(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: MessageType
    source: str
    destination: Optional[str] = None
    timestamp: float = Field(default_factory=time.time)
    correlation_id: Optional[str] = None
    reply_to: Optional[str] = None
    expiry: Optional[float] = None
    data: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def is_expired(self) -> bool:
        return self.expiry is not None and time.time() > self.expiry

    def _encode_payload(
        self, payload: Dict[str, Any], compress: bool
    ) -> Tuple[str, Dict[str, Any]]:
        """Return (data_str, meta_update) with optional gzip+base64 compression."""
        raw = json.dumps(payload).encode("utf-8")
        if not compress:
            return raw.decode("utf-8"), {}
        import gzip

        packed = gzip.compress(raw)
        b64 = base64.b64encode(packed).decode("ascii")
        return b64, {"encoding": "gzip+base64"}

    @staticmethod
    def _decode_payload(data_str: str, meta: Dict[str, Any]) -> Dict[str, Any]:
        """Decode possibly-compressed payload string back to dict."""
        encoding = (meta or {}).get("encoding")
        if encoding == "gzip+base64":
            import gzip

            raw = gzip.decompress(base64.b64decode(data_str.encode("ascii")))
            return json.loads(raw.decode("utf-8"))
        # plain JSON string
        return json.loads(data_str or "{}")

    def to_redis_format(self, compress: bool = False) -> Dict[str, str]:
        data_str, meta_update = self._encode_payload(self.data, compress)
        meta = {**self.metadata, **meta_update} if meta_update else self.metadata
        return {
            "id": self.id,
            "type": self.type.value,
            "source": self.source,
            "destination": self.destination or "",
            "timestamp": str(self.timestamp),
            "correlation_id": self.correlation_id or "",
            "reply_to": self.reply_to or "",
            "expiry": str(self.expiry) if self.expiry else "",
            "data": data_str,
            "metadata": json.dumps(meta),
        }

    @classmethod
    def from_redis_format(cls, redis_data: Dict[str, str]) -> "Message":
        meta_obj = json.loads(redis_data.get("metadata", "{}") or "{}")
        # data may be plain JSON string or gzip+base64
        data_obj = cls._decode_payload(redis_data.get("data", "{}"), meta_obj)
        expiry = redis_data.get("expiry")
        return cls(
            id=redis_data.get("id", str(uuid.uuid4())),
            type=MessageType(redis_data["type"]),
            source=redis_data["source"],
            destination=redis_data.get("destination") or None,
            timestamp=float(redis_data.get("timestamp", time.time())),
            correlation_id=redis_data.get("correlation_id") or None,
            reply_to=redis_data.get("reply_to") or None,
            expiry=float(expiry) if expiry else None,
            data=data_obj,
            metadata=meta_obj,
        )


class RedisBus:
    """
    High-performance Redis message bus for trading agent communication.
    """

    def __init__(
        self,
        redis_config: Dict[str, Any],
        agent_id: str,
        default_ttl_seconds: int = 3600,
        max_retries: int = 3,
        retry_delay_ms: int = 1000,
    ):
        self.agent_id = agent_id
        self.default_ttl_seconds = default_ttl_seconds
        self.max_retries = max_retries
        self.retry_delay_ms = retry_delay_ms

        self.redis_config = dict(redis_config or {})
        self.client: Optional[redis.Redis] = None
        self.pubsub_client: Optional[redis.Redis] = None
        self.connection_pool: Optional[redis.ConnectionPool] = None
        self.pubsub = None  # single shared pubsub (fixes prior bug)

        self.message_handlers: Dict[str, Callable] = {}
        self.stream_configs: Dict[str, StreamConfig] = {}
        self.active_consumers: Dict[str, asyncio.Task] = {}
        self.pubsub_subscriptions: Dict[str, Callable] = {}

        self.metrics = MessageMetrics()
        self.metrics_lock = asyncio.Lock()

        self.running = False
        self.shutdown_event = asyncio.Event()

        self.logger = get_logger(f"redis_bus.{agent_id}")

    # -------------------------
    # Connection / initialization
    # -------------------------
    async def initialize(self) -> bool:
        try:
            self.logger.info(f"[{self.agent_id}] Initializing Redis message bus")

            url = self.redis_config.get("url")
            if not url:
                raise ValueError("redis_config['url'] is required (e.g., rediss://...)")

            # TLS/cert options
            ssl = bool(self.redis_config.get("ssl", url.startswith("rediss://")))
            ssl_cert_reqs = self.redis_config.get("ssl_cert_reqs", "required") if ssl else None
            ssl_check_hostname = (
                bool(self.redis_config.get("ssl_check_hostname", True)) if ssl else None
            )
            ssl_ca_certs = None
            if ssl:
                if self.redis_config.get("ssl_ca_certs"):
                    ssl_ca_certs = self.redis_config["ssl_ca_certs"]
                elif self.redis_config.get("ssl_ca_cert_use_certifi", True):
                    try:
                        import certifi  # type: ignore

                        ssl_ca_certs = certifi.where()
                    except Exception:
                        pass  # fall back to system store

            decode_responses = bool(self.redis_config.get("decode_responses", False))

            # Build connection pool
            self.connection_pool = redis.ConnectionPool.from_url(
                url,
                max_connections=int(self.redis_config.get("connection_pool_size", 20)),
                socket_timeout=float(self.redis_config.get("socket_timeout", 30)),
                socket_connect_timeout=float(
                    self.redis_config.get("socket_connect_timeout", 30)
                ),
                health_check_interval=int(self.redis_config.get("health_check_interval", 30)),
                retry_on_timeout=bool(self.redis_config.get("retry_on_timeout", True)),
                client_name=self.redis_config.get("client_name", f"bus:{self.agent_id}"),
                decode_responses=decode_responses,
                ssl=ssl,
                ssl_cert_reqs=ssl_cert_reqs,
                ssl_ca_certs=ssl_ca_certs,
                ssl_check_hostname=ssl_check_hostname,
            )

            self.client = redis.Redis(connection_pool=self.connection_pool)
            self.pubsub_client = redis.Redis(connection_pool=self.connection_pool)

            # Test both clients
            await self.client.ping()
            await self.pubsub_client.ping()

            # Create a single shared pubsub instance (FIX: earlier code created/discarded)
            self.pubsub = self.pubsub_client.pubsub()

            self.running = True
            self.logger.info("Redis message bus initialized successfully")
            return True

        except Exception as e:
            self.metrics.connection_failures += 1
            self.logger.error(f"Failed to initialize Redis message bus: {e}")
            return False

    # -------------------------
    # Helpers (encoding, sizes)
    # -------------------------
    def _should_compress(self, payload_len_bytes: int) -> bool:
        if not self.redis_config.get("compression_enabled", False):
            return False
        threshold_kb = int(self.redis_config.get("compression_threshold_kb", 0))
        return payload_len_bytes >= (threshold_kb * 1024)

    def _as_bytes_len(self, v: Union[str, bytes]) -> int:
        return len(v if isinstance(v, bytes) else v.encode("utf-8"))

    def _b2s(self, b: Union[str, bytes]) -> str:
        # respect decode_responses: if already str, return; else decode utf-8
        return b if isinstance(b, str) else b.decode("utf-8")

    # -------------------------
    # Sending
    # -------------------------
    async def send_message(
        self,
        stream_name: str,
        message: Message,
        delivery_mode: DeliveryMode = DeliveryMode.STREAM,
    ) -> bool:
        if not self.running or not self.client:
            self.logger.error("Redis bus not initialized")
            return False

        start_time = time.perf_counter()

        try:
            if message.is_expired():
                self.logger.debug(f"[{self.agent_id}][{message.correlation_id}] Message {message.id} expired, not sending")
                return False

            success = False
            message_size = 0

            if delivery_mode == DeliveryMode.STREAM:
                success, message_size = await self._send_stream_message(stream_name, message)
            elif delivery_mode == DeliveryMode.PUBSUB:
                success, message_size = await self._send_pubsub_message(stream_name, message)
            elif delivery_mode == DeliveryMode.QUEUE:
                success, message_size = await self._send_queue_message(stream_name, message)
            elif delivery_mode == DeliveryMode.REQUEST_RESPONSE:
                success, message_size = await self._send_rpc_message(stream_name, message)
            else:
                raise ValueError(f"Unsupported delivery mode: {delivery_mode}")

            send_time = (time.perf_counter() - start_time) * 1000.0
            await self._update_send_metrics(message_size, send_time, success)

            if success:
                self.logger.debug(f"[{self.agent_id}][{message.correlation_id}] Message sent to {stream_name}: {message.id}")
            else:
                self.logger.warning(f"[{self.agent_id}][{message.correlation_id}] Failed to send message to {stream_name}: {message.id}")

            return success

        except Exception as e:
            await self._update_send_metrics(0, 0.0, False)
            self.logger.error(f"Error sending message: {e}")
            return False

    async def _send_stream_message(self, stream_name: str, message: Message) -> Tuple[bool, int]:
        try:
            # compress only 'data' field, leave metadata readable for routing/ops
            # decide based on data size
            raw_payload = json.dumps(message.data).encode("utf-8")
            compress = self._should_compress(len(raw_payload))
            redis_data = message.to_redis_format(compress=compress)
            message_size = sum(self._as_bytes_len(str(v)) for v in redis_data.values())

            # enforce stream maxlen if provided in global config or stream config
            maxlen = None
            approximate = True
            stream_cfg = self.stream_configs.get(stream_name)
            if stream_cfg:
                maxlen = stream_cfg.max_len
                approximate = stream_cfg.approximate_trim
            elif "stream_max_len" in self.redis_config:
                maxlen = int(self.redis_config["stream_max_len"])
                approximate = True

            if maxlen:
                await self.client.xadd(
                    stream_name, redis_data, maxlen=maxlen, approximate=approximate
                )
            else:
                await self.client.xadd(stream_name, redis_data)

            return True, message_size
        except Exception as e:
            self.logger.error(f"Failed to send stream message: {e}")
            return False, 0

    async def _send_pubsub_message(self, channel: str, message: Message) -> Tuple[bool, int]:
        try:
            raw = message.model_dump_json().encode("utf-8")
            compress = self._should_compress(len(raw))
            if compress:
                import gzip

                payload = base64.b64encode(gzip.compress(raw)).decode("ascii")
                out = json.dumps({"encoding": "gzip+base64", "payload": payload})
            else:
                out = message.model_dump_json()

            message_size = self._as_bytes_len(out)
            await self.client.publish(channel, out)
            return True, message_size
        except Exception as e:
            self.logger.error(f"Failed to send pub/sub message: {e}")
            return False, 0

    async def _send_queue_message(self, queue_name: str, message: Message) -> Tuple[bool, int]:
        try:
            body = message.model_dump_json()
            message_size = self._as_bytes_len(body)
            await self.client.lpush(queue_name, body)
            return True, message_size
        except Exception as e:
            self.logger.error(f"Failed to send queue message: {e}")
            return False, 0

    async def _send_rpc_message(self, request_channel: str, message: Message) -> Tuple[bool, int]:
        try:
            reply_channel = f"{request_channel}:reply:{message.id}"
            message.reply_to = reply_channel
            body = message.model_dump_json()
            message_size = self._as_bytes_len(body)
            await self.client.publish(request_channel, body)
            return True, message_size
        except Exception as e:
            self.logger.error(f"Failed to send RPC message: {e}")
            return False, 0

    # -------------------------
    # Streams (consume)
    # -------------------------
    async def subscribe_stream(
        self,
        stream_name: str,
        handler: Callable[[Dict[str, Any]], Union[None, asyncio.Future]],
        consumer_group: str,
        consumer_name: str,
        **kwargs,
    ) -> bool:
        try:
            cfg = StreamConfig(
                name=stream_name,
                consumer_group=consumer_group,
                consumer_name=consumer_name,
                max_pending=kwargs.get("max_pending", 1000),
                max_len=kwargs.get("max_len", int(self.redis_config.get("stream_max_len", 10000))),
                batch_size=kwargs.get(
                    "batch_size", int(self.redis_config.get("stream_batch_size", 10))
                ),
                block_time_ms=kwargs.get("block_time_ms", 1000),
            )

            self.stream_configs[stream_name] = cfg
            self.message_handlers[stream_name] = handler

            # Ensure group exists
            try:
                await self.client.xgroup_create(stream_name, consumer_group, id="0", mkstream=True)
                self.logger.info(
                    f"Created consumer group {consumer_group} for stream {stream_name}"
                )
            except redis.ResponseError as e:
                if "BUSYGROUP" not in str(e):
                    raise

            task = asyncio.create_task(self._stream_consumer_loop(cfg))
            self.active_consumers[stream_name] = task

            async with self.metrics_lock:
                self.metrics.active_streams += 1

            self.logger.info(f"Subscribed to stream {stream_name} as {consumer_name}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to subscribe to stream {stream_name}: {e}")
            return False

    async def _stream_consumer_loop(self, config: StreamConfig):
        while self.running and not self.shutdown_event.is_set():
            try:
                # read pending (non-blocking)
                pending = await self.client.xreadgroup(
                    config.consumer_group,
                    config.consumer_name,
                    {config.name: "0"},
                    count=config.batch_size,
                    block=0,
                )
                if pending:
                    for stream_name, messages in pending:
                        stream_name = self._b2s(stream_name)
                        for message_id, fields in messages:
                            await self._process_stream_message(
                                config, stream_name, self._b2s(message_id), fields
                            )

                # read new messages (blocking up to block_time_ms)
                new_messages = await self.client.xreadgroup(
                    config.consumer_group,
                    config.consumer_name,
                    {config.name: ">"},
                    count=config.batch_size,
                    block=config.block_time_ms,
                )
                if new_messages:
                    for stream_name, messages in new_messages:
                        stream_name = self._b2s(stream_name)
                        for message_id, fields in messages:
                            await self._process_stream_message(
                                config, stream_name, self._b2s(message_id), fields
                            )

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Stream consumer error for {config.name}: {e}")
                await asyncio.sleep(self.retry_delay_ms / 1000.0)

    async def _process_stream_message(
        self,
        config: StreamConfig,
        stream_name: str,
        message_id: str,
        fields: Dict[Union[str, bytes], Union[str, bytes]],
    ):
        start_time = time.perf_counter()
        try:
            # Normalize fields to str
            string_fields: Dict[str, str] = {self._b2s(k): self._b2s(v) for k, v in fields.items()}

            msg = Message.from_redis_format(string_fields)

            if msg.is_expired():
                await self.client.xack(config.name, config.consumer_group, message_id)
                return

            handler = self.message_handlers.get(stream_name)
            if handler:
                if asyncio.iscoroutinefunction(handler):
                    await handler(msg.data)
                else:
                    handler(msg.data)

                await self.client.xack(config.name, config.consumer_group, message_id)

                receive_time = (time.perf_counter() - start_time) * 1000.0
                message_size = sum(self._as_bytes_len(v) for v in string_fields.values())
                await self._update_receive_metrics(message_size, receive_time, True)

        except Exception as e:
            self.logger.error(f"Error processing stream message {message_id}: {e}")
            await self._update_receive_metrics(0, 0.0, False)

    # -------------------------
    # Pub/Sub
    # -------------------------
    async def subscribe_channel(
        self, channel: str, handler: Callable[[Dict[str, Any]], Union[None, asyncio.Future]]
    ) -> bool:
        """Subscribes to a channel (using one shared PubSub)."""
        try:
            if not self.pubsub:
                self.pubsub = self.pubsub_client.pubsub()

            self.pubsub_subscriptions[channel] = handler
            await self.pubsub.subscribe(channel)

            if not hasattr(self, "_pubsub_task") or self._pubsub_task.done():
                self._pubsub_task = asyncio.create_task(self._pubsub_consumer_loop())

            async with self.metrics_lock:
                self.metrics.active_subscriptions += 1

            self.logger.info(f"Subscribed to pub/sub channel {channel}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to subscribe to channel {channel}: {e}")
            return False

    async def unsubscribe_channel(self, channel: str) -> None:
        """Unsubscribes from a channel and removes its handler."""
        try:
            if self.pubsub and channel in self.pubsub_subscriptions:
                await self.pubsub.unsubscribe(channel)
                self.pubsub_subscriptions.pop(channel, None)
                async with self.metrics_lock:
                    self.metrics.active_subscriptions = max(
                        0, self.metrics.active_subscriptions - 1
                    )
        except Exception as e:
            self.logger.warning(f"Failed to unsubscribe {channel}: {e}")

    async def _pubsub_consumer_loop(self):
        """Single consumer loop for all subscribed channels (FIX: earlier code double-opened pubsub)."""
        if not self.pubsub:
            self.pubsub = self.pubsub_client.pubsub()

        while self.running and not self.shutdown_event.is_set():
            try:
                message = await self.pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if not message:
                    continue

                channel_b = message.get("channel")
                data_b = message.get("data")
                if channel_b is None or data_b is None:
                    continue

                channel = self._b2s(channel_b)
                data_str = self._b2s(data_b)

                # Support optional gzip+base64 envelope for pub/sub
                try:
                    obj = json.loads(data_str)
                    if isinstance(obj, dict) and obj.get("encoding") == "gzip+base64":
                        import gzip

                        raw = gzip.decompress(base64.b64decode(obj["payload"].encode("ascii")))
                        payload = json.loads(raw.decode("utf-8"))
                    else:
                        payload = obj
                except Exception:
                    # fallback: maybe publisher sent plain JSON string
                    try:
                        payload = json.loads(data_str)
                    except Exception:
                        payload = {"raw": data_str}

                handler = self.pubsub_subscriptions.get(channel)
                if handler:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(payload)
                    else:
                        handler(payload)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in pub/sub consumer loop: {e}")
                await asyncio.sleep(1.0)

        # Close on exit
        try:
            if self.pubsub:
                await self.pubsub.aclose()
        except Exception:
            pass

    # -------------------------
    # RPC
    # -------------------------
    async def request_response(
        self,
        request_channel: str,
        request_data: Dict[str, Any],
        timeout_seconds: float = 30.0,
    ) -> Optional[Dict[str, Any]]:
        try:
            request_message = Message(
                type=MessageType.CONTROL,
                source=self.agent_id,
                data=request_data,
                correlation_id=str(uuid.uuid4()),
                expiry=time.time() + timeout_seconds,
            )

            reply_channel = f"{request_channel}:reply:{request_message.id}"
            request_message.reply_to = reply_channel

            # Future + temp subscription
            response_future: asyncio.Future = asyncio.get_running_loop().create_future()

            async def _handler(data):
                if not response_future.done():
                    response_future.set_result(data)

            ok = await self.subscribe_channel(reply_channel, _handler)
            if not ok:
                return None

            sent = await self.send_message(request_channel, request_message, DeliveryMode.PUBSUB)
            if not sent:
                await self.unsubscribe_channel(reply_channel)
                return None

            try:
                resp = await asyncio.wait_for(response_future, timeout=timeout_seconds)
                return resp
            except asyncio.TimeoutError:
                self.logger.warning(f"RPC request timeout for {request_channel}")
                return None
            finally:
                await self.unsubscribe_channel(reply_channel)

        except Exception as e:
            self.logger.error(f"Error in request/response: {e}")
            return None

    # -------------------------
    # Admin / metrics / health
    # -------------------------
    async def get_stream_info(self, stream_name: str) -> Optional[Dict[str, Any]]:
        try:
            info = await self.client.xinfo_stream(stream_name)

            # note: redis returns bytes or str depending on decode_responses
            def _norm(v):
                return self._b2s(v) if isinstance(v, (bytes, bytearray)) else v

            return {
                "length": info.get("length"),
                "first_entry": [_norm(x) for x in info.get("first-entry", [])],
                "last_entry": [_norm(x) for x in info.get("last-entry", [])],
                "consumer_groups": info.get("groups"),
            }
        except Exception as e:
            self.logger.error(f"Failed to get stream info for {stream_name}: {e}")
            return None

    async def trim_stream(self, stream_name: str, max_len: int) -> bool:
        try:
            await self.client.xtrim(stream_name, maxlen=max_len, approximate=True)
            self.logger.info(f"Trimmed stream {stream_name} to ~{max_len} messages")
            return True
        except Exception as e:
            self.logger.error(f"Failed to trim stream {stream_name}: {e}")
            return False

    async def get_metrics(self) -> MessageMetrics:
        async with self.metrics_lock:
            # shallow copy
            return MessageMetrics(**self.metrics.__dict__)

    async def get_health_status(self) -> Dict[str, Any]:
        try:
            ping_start = time.perf_counter()
            await self.client.ping()
            ping_time = (time.perf_counter() - ping_start) * 1000.0
            m = await self.get_metrics()
            return {
                "status": "healthy" if ping_time < 100 else "degraded",
                "ping_time_ms": ping_time,
                "active_streams": m.active_streams,
                "active_subscriptions": m.active_subscriptions,
                "total_messages_sent": m.messages_sent,
                "total_messages_received": m.messages_received,
                "error_rate": m.messages_failed / max(m.messages_sent + m.messages_received, 1),
                "last_activity": m.last_activity_time,
            }
        except Exception as e:
            return {"status": "unhealthy", "error": str(e), "ping_time_ms": None}

    async def _update_send_metrics(self, message_size: int, latency_ms: float, success: bool):
        async with self.metrics_lock:
            if success:
                self.metrics.messages_sent += 1
                self.metrics.bytes_sent += message_size
                n = self.metrics.messages_sent
                self.metrics.avg_send_latency_ms = (
                    latency_ms
                    if n == 1
                    else ((self.metrics.avg_send_latency_ms * (n - 1) + latency_ms) / n)
                )
            else:
                self.metrics.messages_failed += 1
            self.metrics.last_activity_time = time.time()

    async def _update_receive_metrics(self, message_size: int, latency_ms: float, success: bool):
        async with self.metrics_lock:
            if success:
                self.metrics.messages_received += 1
                self.metrics.bytes_received += message_size
                n = self.metrics.messages_received
                self.metrics.avg_receive_latency_ms = (
                    latency_ms
                    if n == 1
                    else ((self.metrics.avg_receive_latency_ms * (n - 1) + latency_ms) / n)
                )
            else:
                self.metrics.messages_failed += 1
            self.metrics.last_activity_time = time.time()

    # -------------------------
    # Shutdown
    # -------------------------
    async def close(self):
        try:
            self.logger.info("Shutting down Redis message bus")
            self.running = False
            self.shutdown_event.set()

            # Cancel stream consumers
            for task in list(self.active_consumers.values()):
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
            self.active_consumers.clear()

            # Close pubsub
            if hasattr(self, "_pubsub_task") and self._pubsub_task and not self._pubsub_task.done():
                self._pubsub_task.cancel()
                try:
                    await self._pubsub_task
                except asyncio.CancelledError:
                    pass
            # Try to unsubscribe all (best-effort)
            if self.pubsub:
                try:
                    if self.pubsub_subscriptions:
                        await self.pubsub.unsubscribe(*list(self.pubsub_subscriptions.keys()))
                    await self.pubsub.aclose()
                except Exception:
                    pass
            self.pubsub_subscriptions.clear()

            # Close Redis connections/pool
            if self.client:
                await self.client.aclose()
            if self.pubsub_client:
                await self.pubsub_client.aclose()
            if self.connection_pool:
                await self.connection_pool.aclose()

            self.logger.info("Redis message bus shutdown complete")
        except Exception as e:
            self.logger.error(f"Error during Redis bus shutdown: {e}")


# Convenience factory
async def create_redis_bus(redis_config: Dict[str, Any], agent_id: str, **kwargs) -> RedisBus:
    bus = RedisBus(redis_config, agent_id, **kwargs)
    ok = await bus.initialize()
    if not ok:
        raise RuntimeError("Failed to initialize RedisBus")
    return bus


__all__ = [
    "RedisBus",
    "Message",
    "StreamConfig",
    "MessageMetrics",
    "MessageType",
    "DeliveryMode",
    "create_redis_bus",
]
