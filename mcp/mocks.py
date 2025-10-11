"""
mcp/mocks.py - Production Test Utilities

High-quality in-memory test doubles for unit and integration tests.
Provides Redis-like stream bus (with optional blocking reads), controllable fake
clock, schema helpers, and context managers for environment/time patching.

Designed for crypto-ai-bot with MCP brain and Kraken trading integration.
"""

from __future__ import annotations

import os
import time
import logging
import threading
from contextlib import contextmanager
from collections import defaultdict, deque
from typing import (
    Callable,
    Deque,
    Dict,
    List,
    Mapping,
    Optional,
    Tuple,
    Union,
)

# Import canonical models and marshaling helpers
try:
    from mcp.schemas import (
        VersionedBaseModel,
        Signal,
        OrderIntent,
        PolicyUpdate,
        MetricsTick,
    )
    from mcp.marshaling import (
        serialize_event,
        deserialize_event,
        FIELD_JSON,
    )
    from mcp.errors import MCPError, SerializationError
except Exception:  # pragma: no cover - lightweight fallback for isolated tests
    class VersionedBaseModel:
        def to_json(self) -> str:  # type: ignore
            return '{"type":"mock","mock":true}'

        @classmethod
        def example(cls):  # type: ignore
            return cls()

        def model_dump(self, mode: str = "json"):  # type: ignore
            return {"type": "mock", "mock": True}

    class Signal(VersionedBaseModel): ...
    class OrderIntent(VersionedBaseModel): ...
    class PolicyUpdate(VersionedBaseModel): ...
    class MetricsTick(VersionedBaseModel): ...

    def serialize_event(event):  # type: ignore
        return event.to_json() if hasattr(event, "to_json") else '{"mock":true}'

    def deserialize_event(data):  # type: ignore
        return {"type": "mock", "data": data}

    FIELD_JSON = "json"  # type: ignore

    class MCPError(Exception): ...
    class SerializationError(MCPError): ...


__all__ = [
    "FakeClock",
    "patch_time",
    "patch_environ",
    "InMemoryStreamBus",
    "InMemoryPubSub",
    "FakeRedisManager",
    "emit_event_json",
    "read_event_json",
    "EventCollector",
    "FakeMarketFeed",
    "example_policy",
]

logger = logging.getLogger("mcp.mocks")


# -----------------------------------------------------------------------------
# Clock & Patchers
# -----------------------------------------------------------------------------
class FakeClock:
    """
    Monotonic-ish wall clock for tests. Thread-safe, controllable time source.
    """

    def __init__(self, start: Optional[float] = None) -> None:
        self._current_time = float(start if start is not None else 1_700_000_000.0)
        self._lock = threading.Lock()

    def now(self) -> float:
        with self._lock:
            return self._current_time

    def sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        with self._lock:
            self._current_time += float(seconds)

    def set(self, ts: float) -> None:
        with self._lock:
            self._current_time = float(ts)


@contextmanager
def patch_time(clock: FakeClock):
    """
    Monkey-patch time.time() to use clock.now() for the duration; restore on exit.
    """
    original = time.time
    time.time = clock.now  # type: ignore[assignment]
    try:
        yield
    finally:
        time.time = original


@contextmanager
def patch_environ(overrides: Mapping[str, str]):
    """
    Temporarily set os.environ keys; restore previous env after block.
    """
    original_values: Dict[str, str] = {}
    keys_to_delete: List[str] = []
    for k, v in overrides.items():
        if k in os.environ:
            original_values[k] = os.environ[k]
        else:
            keys_to_delete.append(k)
        os.environ[k] = v
    try:
        yield
    finally:
        for k, v in original_values.items():
            os.environ[k] = v
        for k in keys_to_delete:
            if k in os.environ:
                del os.environ[k]


# -----------------------------------------------------------------------------
# In-memory Redis Streams (with optional blocking xread)
# -----------------------------------------------------------------------------
class InMemoryStreamBus:
    """
    Minimal Redis Streams-like bus in-memory.

    - Message IDs are "millis-seq" strings, where millis = int(clock.now()*1000),
      and seq increments per stream per millis.
    - XADD stores field values as bytes (Redis-compatible).
    - XREAD supports optional blocking (block ms) until any target stream gets new data.
    - XRANGE / XREVRANGE supported for convenience in tests.
    - Clear streams to avoid cross-test contamination.
    """

    def __init__(self, clock: Optional[FakeClock] = None) -> None:
        self._clock = clock or FakeClock()
        self._streams: Dict[str, Deque[Tuple[str, Dict[bytes, bytes]]]] = defaultdict(deque)
        self._sequences: Dict[Tuple[str, int], int] = {}  # (stream, millis) -> seq
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)  # for blocking reads

    # --------------------------
    # Internal helpers
    # --------------------------
    def _generate_id(self, stream: str) -> str:
        millis = int(self._clock.now() * 1000)
        key = (stream, millis)
        seq = self._sequences.get(key, 0)
        self._sequences[key] = seq + 1
        return f"{millis}-{seq}"

    @staticmethod
    def _to_bytes_fields(fields: Mapping[str, Union[str, bytes]]) -> Dict[bytes, bytes]:
        out: Dict[bytes, bytes] = {}
        for k, v in fields.items():
            kb = k if isinstance(k, bytes) else k.encode("utf-8")
            vb = v if isinstance(v, (bytes, bytearray)) else str(v).encode("utf-8")
            out[kb] = bytes(vb)
        return out

    @staticmethod
    def _parse_id(mid: str) -> Tuple[int, int]:
        ts, seq = mid.split("-", 1)
        return int(ts), int(seq)

    def _compare_ids(self, id1: str, id2: str) -> int:
        # Returns -1 if id1 < id2, 0 if equal, 1 if id1 > id2
        if id2 in ("0-0", "0"):
            return 1
        if id2 == "$":
            return -1
        try:
            ts1, s1 = self._parse_id(id1)
            ts2, s2 = self._parse_id(id2)
            if ts1 != ts2:
                return 1 if ts1 > ts2 else -1
            return (s1 > s2) - (s1 < s2)
        except Exception:
            return (id1 > id2) - (id1 < id2)

    def _id_in_range(self, mid: str, start: str, end: str) -> bool:
        if start != "0-0" and self._compare_ids(mid, start) < 0:
            return False
        if end != "+" and self._compare_ids(mid, end) > 0:
            return False
        return True

    # --------------------------
    # Stream ops
    # --------------------------
    def xadd(self, stream: str, fields: Mapping[str, Union[str, bytes]]) -> str:
        if not stream.strip():
            raise ValueError("Stream name cannot be empty")
        with self._lock:
            msg_id = self._generate_id(stream)
            self._streams[stream].append((msg_id, self._to_bytes_fields(fields)))
            # Wake any xread waiting
            self._cv.notify_all()
            return msg_id

    def xread(
        self,
        streams: Mapping[str, str],
        count: Optional[int] = None,
        block: Optional[int] = None,
    ) -> List[Tuple[str, List[Tuple[str, Dict[bytes, bytes]]]]]:
        """
        Read new items strictly after last_id for each stream.
        - block: milliseconds to wait for new data if none present. If None/0, non-blocking.
        Return: [(stream, [(msg_id, {b"f": b"v"}), ...]), ...]
        """
        deadline = None if not block or block <= 0 else (time.time() + block / 1000.0)

        with self._lock:
            while True:
                result: List[Tuple[str, List[Tuple[str, Dict[bytes, bytes]]]]] = []
                for stream_name, last_id in streams.items():
                    if last_id == "$":
                        # '$' asks for only future entries; we don't return history
                        continue
                    bucket: List[Tuple[str, Dict[bytes, bytes]]] = []
                    for mid, fields in self._streams.get(stream_name, ()):
                        if self._compare_ids(mid, last_id) > 0:
                            bucket.append((mid, fields))
                            if count is not None and len(bucket) >= count:
                                break
                    if bucket:
                        result.append((stream_name, bucket))
                if result or deadline is None:
                    return result
                # still empty; wait until timeout or notify
                remaining = deadline - time.time()
                if remaining <= 0:
                    return []
                self._cv.wait(timeout=remaining)

    def xrange(
        self,
        stream: str,
        start: str = "0-0",
        end: str = "+",
        count: Optional[int] = None,
    ) -> List[Tuple[str, Dict[bytes, bytes]]]:
        if not stream.strip():
            raise ValueError("Stream name cannot be empty")
        out: List[Tuple[str, Dict[bytes, bytes]]] = []
        with self._lock:
            for mid, fields in self._streams.get(stream, ()):
                if self._id_in_range(mid, start, end):
                    out.append((mid, fields))
                    if count is not None and len(out) >= count:
                        break
        return out

    def xrevrange(
        self,
        stream: str,
        end: str = "+",
        start: str = "-",
        count: Optional[int] = None,
    ) -> List[Tuple[str, Dict[bytes, bytes]]]:
        if not stream.strip():
            raise ValueError("Stream name cannot be empty")
        out: List[Tuple[str, Dict[bytes, bytes]]] = []
        with self._lock:
            data = self._streams.get(stream, ())
            # Normalize to concrete bounds for reverse direction
            norm_start = "0-0" if start == "-" else start
            norm_end = "9999999999999-0" if end == "+" else end
            for mid, fields in reversed(data):
                if self._id_in_range(mid, norm_start, norm_end):
                    out.append((mid, fields))
                    if count is not None and len(out) >= count:
                        break
        return out

    def xlen(self, stream: str) -> int:
        with self._lock:
            return len(self._streams.get(stream, ()))

    def xtrim(self, stream: str, maxlen: int) -> int:
        if maxlen < 0:
            raise ValueError("maxlen must be >= 0")
        removed = 0
        with self._lock:
            dq = self._streams.get(stream)
            if dq is None:
                return 0
            while len(dq) > maxlen:
                dq.popleft()
                removed += 1
        return removed

    def clear(self, stream: Optional[str] = None) -> None:
        with self._lock:
            if stream is None:
                self._streams.clear()
                self._sequences.clear()
                return
            if stream in self._streams:
                self._streams[stream].clear()
                # drop sequence keys for that stream
                for k in [k for k in self._sequences.keys() if k[0] == stream]:
                    del self._sequences[k]

    def streams(self) -> List[str]:
        with self._lock:
            return list(self._streams.keys())


# -----------------------------------------------------------------------------
# In-memory Pub/Sub
# -----------------------------------------------------------------------------
class InMemoryPubSub:
    """Simple in-memory pub/sub system."""

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[Callable[[str, str], None]]] = defaultdict(list)
        self._lock = threading.Lock()

    def publish(self, channel: str, message: str) -> int:
        if not channel.strip():
            raise ValueError("Channel name cannot be empty")
        with self._lock:
            callbacks = list(self._subscribers.get(channel, ()))
        for cb in callbacks:
            try:
                cb(channel, message)
            except Exception as e:
                logger.error("Error in pubsub callback for %s: %s", channel, e)
        return len(callbacks)

    def subscribe(self, channel: str, callback: Callable[[str, str], None]) -> None:
        if not channel.strip():
            raise ValueError("Channel name cannot be empty")
        with self._lock:
            self._subscribers[channel].append(callback)

    def unsubscribe(self, channel: str, callback: Callable[[str, str], None]) -> None:
        with self._lock:
            lst = self._subscribers.get(channel)
            if not lst:
                return
            try:
                lst.remove(callback)
            except ValueError:
                pass
            if not lst:
                del self._subscribers[channel]


# -----------------------------------------------------------------------------
# Fake RedisManager facade (streams + pubsub)
# -----------------------------------------------------------------------------
class FakeRedisManager:
    """
    Drop-in testing stub mimicking RedisManager stream/pubsub surface.
    Backed by InMemoryStreamBus and InMemoryPubSub.
    """

    def __init__(
        self,
        bus: Optional[InMemoryStreamBus] = None,
        pubsub: Optional[InMemoryPubSub] = None,
    ) -> None:
        self._bus = bus or InMemoryStreamBus()
        self._pubsub = pubsub or InMemoryPubSub()

    @classmethod
    def with_clock(cls, clock: FakeClock) -> "FakeRedisManager":
        return cls(bus=InMemoryStreamBus(clock))

    # Streams
    def xadd(self, stream: str, fields: Mapping[str, Union[str, bytes]]) -> str:
        return self._bus.xadd(stream, fields)

    def xread(
        self,
        streams: Mapping[str, str],
        count: Optional[int] = None,
        block: Optional[int] = None,
    ):
        return self._bus.xread(streams, count=count, block=block)

    def xrange(
        self,
        stream: str,
        start: str = "0-0",
        end: str = "+",
        count: Optional[int] = None,
    ):
        return self._bus.xrange(stream, start=start, end=end, count=count)

    def xrevrange(
        self,
        stream: str,
        end: str = "+",
        start: str = "-",
        count: Optional[int] = None,
    ):
        return self._bus.xrevrange(stream, end=end, start=start, count=count)

    def xlen(self, stream: str) -> int:
        return self._bus.xlen(stream)

    def xtrim(self, stream: str, maxlen: int) -> int:
        return self._bus.xtrim(stream, maxlen)

    def clear(self, stream: Optional[str] = None) -> None:
        self._bus.clear(stream)

    # Pub/Sub
    def publish(self, channel: str, message: str) -> int:
        return self._pubsub.publish(channel, message)

    def subscribe(self, channel: str, callback: Callable[[str, str], None]) -> None:
        self._pubsub.subscribe(channel, callback)

    def unsubscribe(self, channel: str, callback: Callable[[str, str], None]) -> None:
        self._pubsub.unsubscribe(channel, callback)


# -----------------------------------------------------------------------------
# Schema-aware helpers
# -----------------------------------------------------------------------------
def emit_event_json(
    bus: InMemoryStreamBus, stream_name: str, event: VersionedBaseModel, *, field: str = FIELD_JSON
) -> str:
    """
    Serialize with canonical serializer, push via XADD({field: json}), return msg id.
    """
    try:
        json_data = serialize_event(event)
        return bus.xadd(stream_name, {field: json_data})
    except Exception as e:
        raise SerializationError(f"Failed to emit event: {e}") from e


def read_event_json(
    bus: InMemoryStreamBus, stream_name: str, last_id: str = "0-0", *, field: str = FIELD_JSON
) -> List[Tuple[str, VersionedBaseModel]]:
    """
    XRANGE(start=last_id) → decode field → mcp.marshaling.deserialize_event.
    Tolerates both bytes and str field names for seamless testing.
    """
    try:
        messages = bus.xrange(stream_name, start=last_id)
        want_key_b = field.encode("utf-8")
        out: List[Tuple[str, VersionedBaseModel]] = []
        for mid, fields in messages:
            if want_key_b in fields:
                raw = fields[want_key_b]
            elif field in fields:  # rare: direct str usage
                raw = fields[field]  # type: ignore[index]
            else:
                continue
            json_data = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
            try:
                out.append((mid, deserialize_event(json_data)))
            except Exception as e:
                logger.warning("Failed to deserialize event %s: %s", mid, e)
        return out
    except Exception as e:
        raise SerializationError(f"Failed to read events: {e}") from e


class EventCollector:
    """
    Helper to capture events from a stream with value-equality to schemas.
    """

    def __init__(self, bus: InMemoryStreamBus, stream_name: str, *, field: str = FIELD_JSON) -> None:
        self._bus = bus
        self._stream_name = stream_name
        self._field = field
        self._last_id = "0-0"

    def read_all(self) -> List[VersionedBaseModel]:
        events_with_ids = read_event_json(self._bus, self._stream_name, self._last_id, field=self._field)
        if events_with_ids:
            self._last_id = events_with_ids[-1][0]
        return [e for _, e in events_with_ids]

    def last_id(self) -> str:
        return self._last_id


# -----------------------------------------------------------------------------
# Deterministic market snapshot generator
# -----------------------------------------------------------------------------
class FakeMarketFeed:
    """Deterministic generator for snapshots/ticks to drive SignalAnalyst tests."""

    def __init__(self, clock: FakeClock) -> None:
        self._clock = clock

    def snapshot(
        self,
        symbol: str,
        *,
        bid: float,
        ask: float,
        volume: float = 0.0,
        spread_bps: Optional[float] = None,
    ) -> Dict[str, float]:
        if bid <= 0 or ask <= 0:
            raise ValueError("Bid and ask must be positive")
        if ask <= bid:
            raise ValueError("Ask must be greater than bid")
        if spread_bps is None:
            spread_bps = ((ask - bid) / bid) * 10_000.0
        return {
            "symbol": symbol,
            "bid": float(bid),
            "ask": float(ask),
            "volume": float(volume),
            "spread_bps": float(spread_bps),
            "mid_price": float((bid + ask) / 2.0),
            "timestamp": float(self._clock.now()),
        }


# -----------------------------------------------------------------------------
# Policy helper (deterministic)
# -----------------------------------------------------------------------------
def example_policy() -> PolicyUpdate:
    """
    Returns PolicyUpdate.example() with deterministic timestamp (1700000000.0).
    Stays as a proper PolicyUpdate instance (never a dict).
    """
    p = PolicyUpdate.example()
    try:
        pd = p.model_dump(mode="json")  # ensure sets → lists for safe JSON
    except Exception:
        pd = p.model_dump()
    pd["timestamp"] = 1_700_000_000.0
    return PolicyUpdate(**pd)


# -----------------------------------------------------------------------------
# Self-test
# -----------------------------------------------------------------------------
def _run_self_test() -> None:
    print("Running mcp.mocks self-test...")

    # FakeClock & patch_time
    c = FakeClock(1_700_000_000.0)
    assert c.now() == 1_700_000_000.0
    c.sleep(1.0)
    assert c.now() == 1_700_000_001.0
    with patch_time(c):
        assert time.time() == 1_700_000_001.0  # type: ignore[comparison-overlap]
        c.sleep(0.5)
        assert time.time() == 1_700_000_001.5  # type: ignore[comparison-overlap]
    assert time.time() != c.now()

    # Streams: basic ops
    bus = InMemoryStreamBus(c)
    msg1 = bus.xadd("s", {"f": "v1"})
    msg2 = bus.xadd("s", {"f": "v2"})
    assert bus.xlen("s") == 2
    xs = bus.xrange("s")
    assert [m for m, _ in xs] == [msg1, msg2]
    rs = bus.xrevrange("s")
    assert [m for m, _ in rs] == [msg2, msg1]

    # Streams: xread non-blocking
    got = bus.xread({"s": "0-0"})
    assert len(got) == 1 and len(got[0][1]) == 2

    # Streams: xread blocking
    def delayed():
        time.sleep(0.05)
        bus.xadd("s2", {"f": "a"})

    t = threading.Thread(target=delayed, daemon=True)
    t.start()
    got2 = bus.xread({"s2": "0-0"}, block=500)
    assert got2 and got2[0][0] == "s2" and len(got2[0][1]) == 1
    t.join()

    # Trimming and clear
    bus.xtrim("s", 1)
    assert bus.xlen("s") == 1
    bus.clear("s")
    assert bus.xlen("s") == 0
    bus.clear()

    # Schema helpers
    with patch_time(c):
        sig = Signal.example()
        mid = emit_event_json(bus, "sig:stream", sig)
        assert isinstance(mid, str)
        events = read_event_json(bus, "sig:stream", "0-0")
        assert events and isinstance(events[0][1], Signal)

    # Market feed
    feed = FakeMarketFeed(c)
    snap = feed.snapshot("BTC/USD", bid=100.0, ask=100.1)
    assert snap["symbol"] == "BTC/USD" and snap["spread_bps"] > 0.0

    # Policy helper
    pol = example_policy()
    assert isinstance(pol, PolicyUpdate)

    # PubSub
    pub = InMemoryPubSub()
    seen: List[Tuple[str, str]] = []

    def cb(ch: str, msg: str):
        seen.append((ch, msg))

    pub.subscribe("ch", cb)
    assert pub.publish("ch", "hello") == 1
    assert seen == [("ch", "hello")]
    pub.unsubscribe("ch", cb)
    assert pub.publish("ch", "bye") == 0

    # FakeRedisManager facade
    mgr = FakeRedisManager.with_clock(c)
    mid2 = mgr.xadd("mgr", {"a": "b"})
    assert isinstance(mid2, str) and mgr.xlen("mgr") == 1
    rev = mgr.xrevrange("mgr")
    assert len(rev) == 1
    mgr.clear("mgr")
    assert mgr.xlen("mgr") == 0

    print("mcp.mocks self-test PASSED")


if __name__ == "__main__":
    import sys

    if "--self-test" in sys.argv:
        try:
            _run_self_test()
            raise SystemExit(0)
        except Exception as e:
            print(f"Self-test FAILED: {e}")
            raise SystemExit(1)
    print("mcp.mocks - Production Test Utilities")
    print("Usage: python -m mcp.mocks --self-test")
