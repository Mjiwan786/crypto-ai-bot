"""
mcp/context.py - Production application context for crypto-ai-bot agents

Provides centralized environment, namespacing, Redis access, schema-aware
publish/consume, policy snapshot caching, and safe DLQ on validation errors.

Compatible with Python 3.10+, Pydantic v2.x.
Supports both sync and async Redis clients for maximum compatibility.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from mcp.schemas import (
    VersionedBaseModel,
    Signal,
    OrderIntent,
    PolicyUpdate,
    MetricsTick,
    write_json_schemas,
)
from mcp.keys import BOT_ENV, stream
from mcp.redis_manager import RedisManager

# ---------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------

DEFAULT_STREAMS: Dict[str, str] = {
    "signals": "signals",
    "orders.intents": "orders:intents",
    "metrics": "metrics:ticks",
    "policy": "policy:updates",
    "rejections": "events:rejections",
}
DEFAULT_DLQ_STREAM = "events:dlq"

# ---------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------


def ensure_numeric_features(d: Dict[str, object]) -> Dict[str, float | int]:
    """
    Ensure feature values are numeric; coerce numeric strings; reject bools.
    """
    out: Dict[str, float | int] = {}
    for k, v in d.items():
        # bool is a subclass of int; reject explicitly
        if isinstance(v, bool):
            raise ValueError(f"Non-numeric value '{v}' for key '{k}'")
        if isinstance(v, (int, float)):
            out[k] = v
        elif isinstance(v, str):
            try:
                num = float(v)
            except ValueError as e:
                raise ValueError(f"Non-numeric value '{v}' for key '{k}'") from e
            out[k] = int(num) if num.is_integer() else num
        else:
            raise ValueError(f"Non-numeric type {type(v)} for key '{k}'")
    return out


def _decode_payload(payload: Union[str, bytes, bytearray]) -> str:
    if isinstance(payload, (bytes, bytearray)):
        return payload.decode("utf-8")
    if not isinstance(payload, str):
        raise ValueError("Event payload must be a JSON string")
    return payload


# ---------------------------------------------------------------------
# Redis compatibility shim
# ---------------------------------------------------------------------


class _RedisShim:
    """
    Accepts either a sync redis client or a redis.asyncio client.
    Calls and then awaits if the return is awaitable.
    """

    def __init__(self, client: Any) -> None:
        self._c = client

    @staticmethod
    def _is_awaitable(x: Any) -> bool:
        return inspect.isawaitable(x)

    async def _maybe_await(self, fn, *args, **kwargs):
        res = fn(*args, **kwargs)
        if self._is_awaitable(res):
            return await res
        return res

    async def xadd(self, stream_name: str, fields: Dict[str, Any]) -> str:
        return await self._maybe_await(getattr(self._c, "xadd"), stream_name, fields)

    async def xread(
        self,
        streams: Dict[str, str],
        *,
        count: Optional[int] = None,
        block: Optional[int] = None,
    ):
        # Expect redis-py style: XREAD {stream: last_id}
        return await self._maybe_await(
            getattr(self._c, "xread"),
            streams,
            count=count,
            block=block,
        )

    async def xrevrange(self, stream_name: str, *, count: Optional[int] = None):
        return await self._maybe_await(
            getattr(self._c, "xrevrange"), stream_name, count=count
        )

    async def close(self):
        # Prefer aclose(); fall back to close()
        for name in ("aclose", "close"):
            if hasattr(self._c, name):
                res = getattr(self._c, name)()
                if self._is_awaitable(res):
                    await res
                return


# ---------------------------------------------------------------------
# MCP Context
# ---------------------------------------------------------------------


class MCPContext:
    """
    Central application context for agents/services:
    - environment / namespacing
    - Redis streams with schema-aware publish/consume
    - policy snapshot cache
    - DLQ on validation errors
    - sync/async Redis client compatibility
    """

    def __init__(
        self,
        *,
        env: str,
        ns: str,
        redis: RedisManager,
        streams: Dict[str, str] | None = None,
        dlq_stream: str | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.env = env
        self.ns = ns

        # Accept either a manager with .client or a direct redis client
        client = getattr(redis, "client", redis)
        self._redis_raw = redis
        self.redis = _RedisShim(client)

        self.streams: Dict[str, str] = (streams or DEFAULT_STREAMS).copy()
        self.dlq_stream: str = dlq_stream or DEFAULT_DLQ_STREAM

        self.logger = logger or logging.getLogger("mcp.context")
        self._policy: PolicyUpdate | None = None
        self._closed = False

    # --------- lifecycle helpers ---------

    @classmethod
    def from_env(cls, **overrides: Any) -> "MCPContext":
        """
        Build context from environment; supports overriding pieces for tests.
        """
        env_val = BOT_ENV()
        if not env_val:
            env_val = os.getenv("ENVIRONMENT", "paper")

        env = overrides.pop("env", env_val)
        ns = overrides.pop("ns", "crypto-ai-bot")

        redis_mgr = overrides.pop("redis", None)
        if redis_mgr is None:
            if hasattr(RedisManager, "from_env") and callable(
                getattr(RedisManager, "from_env")
            ):
                redis_mgr = RedisManager.from_env()
            else:
                redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
                redis_mgr = RedisManager(url=redis_url)  # type: ignore[arg-type]

        return cls(env=env, ns=ns, redis=redis_mgr, **overrides)

    async def __aenter__(self) -> "MCPContext":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    # --------- naming / time ---------

    def now(self) -> float:
        return time.time()

    def stream_name(self, key: str) -> str:
        logical = self.streams.get(key, key)
        return stream(self.ns, self.env, logical)

    # --------- publish / DLQ ---------

    def _serialize_event(self, event: VersionedBaseModel) -> str:
        # Prefer custom .to_json if your VersionedBaseModel provides it; fallback to Pydantic v2
        if hasattr(event, "to_json") and callable(getattr(event, "to_json")):
            return event.to_json()  # type: ignore[no-any-return]
        return event.model_dump_json(by_alias=True)  # type: ignore[no-any-return]

    async def publish(self, key: str, event: VersionedBaseModel) -> str:
        """
        Validate & publish an event to a stream with a canonical envelope:
        {
          "type": "<event.type>",
          "schema_version": "<event.schema_version>",
          "ts": "<unix_ts>",
          "json": "<serialized model>"
        }
        """
        if self._closed:
            raise RuntimeError("MCPContext has been closed")
        if not isinstance(event, VersionedBaseModel):
            raise TypeError(f"publish() expects VersionedBaseModel, got {type(event)}")

        sname = self.stream_name(key)
        try:
            json_body = self._serialize_event(event)
            fields = {
                "type": getattr(event, "type", None),
                "schema_version": getattr(event, "schema_version", None),
                "ts": str(self.now()),
                "json": json_body,
            }
            msg_id = await self.redis.xadd(sname, fields)
            self.logger.debug(
                "mcp.publish",
                extra={
                    "key": key,
                    "stream": sname,
                    "event_type": fields["type"],
                    "schema_version": fields["schema_version"],
                    "msg_id": msg_id,
                },
            )
            return msg_id
        except Exception as exc:
            # DLQ envelope with original serialized form if possible
            try:
                original = json_body  # type: ignore[name-defined]
            except Exception:
                try:
                    original = self._serialize_event(event)
                except Exception:
                    original = repr(event)

            envelope = {
                "type": "dlq.event",
                "src": key,
                "err": str(exc),
                "ts": self.now(),
                "original_type": getattr(event, "type", "unknown"),
                "original": original,
            }
            try:
                dlq = stream(self.ns, self.env, self.dlq_stream)
                await self.redis.xadd(
                    dlq, {"ts": str(self.now()), "json": json.dumps(envelope)}
                )
                self.logger.warning("mcp.dlq.write", extra={"src": key, "err": str(exc)})
            except Exception as de:
                self.logger.error(f"DLQ write failed: {de}")
            raise

    # --------- reading helpers ---------

    async def peek_latest(self, key: str, count: int = 1) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Non-blocking: latest N items using XREVRANGE.
        Returns [(msg_id, fields_dict), ...].
        """
        if self._closed:
            raise RuntimeError("MCPContext has been closed")
        sname = self.stream_name(key)
        result = await self.redis.xrevrange(sname, count=count)
        # Normalize None → []
        return list(result or [])

    async def consume(
        self,
        key: str,
        last_id: str = "0-0",
        *,
        count: int = 1,
        block_ms: int = 5000,
    ) -> Tuple[List[Tuple[str, Dict[str, Any]]], str]:
        """
        Blocking: read new items strictly AFTER last_id using XREAD.
        Returns (messages, new_last_id) where messages = [(msg_id, fields), ...]
        """
        if self._closed:
            raise RuntimeError("MCPContext has been closed")

        sname = self.stream_name(key)
        res = await self.redis.xread({sname: last_id}, count=count, block=block_ms)

        messages: List[Tuple[str, Dict[str, Any]]] = []
        new_last = last_id

        # redis-py may return List[Tuple[str, List[Tuple[id, dict]]]] or Dict[str, List[...]]
        if res:
            it = res.items() if isinstance(res, dict) else res
            for _stream_name, pairs in it:
                for msg_id, fields in pairs:
                    messages.append((msg_id, fields))
                    new_last = msg_id

        return messages, new_last

    async def read_latest(
        self,
        key: str,
        count: int = 1,
        block_ms: Optional[int] = None,
    ) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Backward-compat shorthand for tests/tools.
        Non-blocking latest read (uses XREVRANGE).
        """
        _ = block_ms  # ignored by design
        return await self.peek_latest(key, count)

    # --------- parse / model helpers ---------

    def parse_event(
        self, payload_or_fields: Union[str, bytes, bytearray, Dict[str, Any]]
    ) -> VersionedBaseModel:
        """
        Parse a serialized event JSON string OR a Redis fields dict (with 'json'/'data').
        Enforces numeric-only features for Signal.
        """
        if isinstance(payload_or_fields, dict):
            raw = payload_or_fields.get("json") or payload_or_fields.get("data")
            if raw is None:
                raise ValueError("Fields dict missing 'json' or 'data' key")
            payload = _decode_payload(raw)
        else:
            payload = _decode_payload(payload_or_fields)

        data = json.loads(payload)
        etype = data.get("type")
        if not etype:
            raise ValueError("Missing 'type' field in event payload")

        mapping: Dict[str, type[VersionedBaseModel]] = {
            "signal": Signal,
            "order.intent": OrderIntent,
            "policy.update": PolicyUpdate,
            "metrics.tick": MetricsTick,
        }
        model_cls = mapping.get(etype)
        if not model_cls:
            raise ValueError(
                f"Unknown event type '{etype}' (available: {', '.join(mapping.keys())})"
            )

        obj = model_cls.model_validate(data)
        if isinstance(obj, Signal) and obj.features:
            # Coerce features to numeric (use model_copy to respect immutability)
            obj = obj.model_copy(
                update={"features": ensure_numeric_features(dict(obj.features))}
            )
        return obj

    # --------- policy cache / publish ---------

    def get_policy_snapshot(self) -> Optional[PolicyUpdate]:
        return self._policy

    def set_policy_snapshot(self, policy: PolicyUpdate) -> None:
        self._policy = PolicyUpdate.model_validate(policy)

    async def publish_policy_snapshot(self) -> Optional[str]:
        """
        Publish the cached policy snapshot to the 'policy' stream (if configured).
        Returns message id or None if no policy or stream disabled.
        """
        if self._policy and "policy" in self.streams:
            return await self.publish("policy", self._policy)
        return None

    # --------- schema export ---------

    def write_json_schemas(self, out_dir: str) -> Dict[str, str]:
        return write_json_schemas(out_dir)

    # --------- close ---------

    async def close(self) -> None:
        if not self._closed:
            try:
                await self.redis.close()
            except Exception as e:
                self.logger.error(f"Error closing Redis connection: {e}")
            finally:
                self._closed = True


# ---------------------------------------------------------------------
# Minimal Fake Redis (for self-test)
# ---------------------------------------------------------------------


class FakeRedisManager:
    """
    Minimal in-memory Redis stub compatible with _RedisShim.
    Implements xadd, xread({stream:last_id}), xrevrange(stream,count).
    """

    def __init__(self, *args, **kwargs):
        self._streams: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {}
        self._counter = 0

    # Sync on purpose; the shim will accept sync or async.
    def xadd(self, stream_name: str, fields: Dict[str, Any]) -> str:
        self._counter += 1
        msg_id = f"{int(time.time() * 1000)}-{self._counter}"
        self._streams.setdefault(stream_name, []).append((msg_id, fields))
        return msg_id

    def xread(
        self,
        streams: Dict[str, str],
        *,
        count: Optional[int] = None,
        block: Optional[int] = None,
    ) -> List[Tuple[str, List[Tuple[str, Dict[str, Any]]]]]:
        # Return items strictly after last_id for each stream
        out: List[Tuple[str, List[Tuple[str, Dict[str, Any]]]]] = []
        cap = count or 1
        for sname, last_id in streams.items():
            items = self._streams.get(sname, [])
            bucket: List[Tuple[str, Dict[str, Any]]] = []
            for mid, fields in items:
                if last_id == "0-0" or mid > last_id:
                    bucket.append((mid, fields))
                    if len(bucket) >= cap:
                        break
            if bucket:
                out.append((sname, bucket))
        return out

    def xrevrange(
        self, stream_name: str, *, count: Optional[int] = None
    ) -> List[Tuple[str, Dict[str, Any]]]:
        items = self._streams.get(stream_name, [])
        if count is None or count <= 0:
            return list(reversed(items))
        return list(reversed(items[-count:]))

    def close(self):
        pass


# ---------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------


async def _self_test() -> None:
    logging.basicConfig(level=logging.INFO)

    # 1) Context with fake redis
    fake = FakeRedisManager()
    ctx = MCPContext(env="test", ns="test-bot", redis=fake)

    # 2) Publish a Signal
    sig = Signal.example()
    mid = await ctx.publish("signals", sig)
    assert isinstance(mid, str)

    # 3) Peek latest and parse (pass fields dict directly)
    latest = await ctx.peek_latest("signals", count=1)
    assert latest, "no messages found"
    _, fields = latest[0]
    parsed = ctx.parse_event(fields)
    assert parsed.model_dump(mode="json") == sig.model_dump(mode="json")

    # 4) Consume since 0-0 (should see recent messages)
    msgs, last_id = await ctx.consume("signals", last_id="0-0", count=2, block_ms=10)
    assert msgs and last_id != "0-0"

    # 5) Numeric features enforcement
    sig2 = Signal(
        strategy="scalp",
        symbol="BTC/USD",
        timeframe="1m",
        side="buy",
        confidence=0.77,
        features={"rsi": "34.0", "momo": 0.001, "count": "5"},
    )
    mid2 = await ctx.publish("signals", sig2)
    assert isinstance(mid2, str)
    latest2 = await ctx.peek_latest("signals", count=1)
    parsed2 = ctx.parse_event(latest2[0][1])
    assert all(isinstance(v, (int, float)) for v in parsed2.features.values())

    # 6) Policy snapshot cache + publish
    pol = PolicyUpdate.example()
    ctx.set_policy_snapshot(pol)
    mid_pol = await ctx.publish_policy_snapshot()
    assert mid_pol is not None
    cache = ctx.get_policy_snapshot()
    assert cache and cache.model_dump(mode="json") == pol.model_dump(mode="json")

    # 7) Schema export
    with tempfile.TemporaryDirectory() as d:
        paths = ctx.write_json_schemas(d)
        assert paths and all(Path(p).exists() for p in paths.values())

    # 8) Close
    await ctx.close()
    print("MCPContext self-test PASSED")


def main() -> None:
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        asyncio.run(_self_test())
    else:
        print("Usage: python -m mcp.context --self-test")


if __name__ == "__main__":
    main()
