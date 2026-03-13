"""Tests for paper/paper_trader.py"""
import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Dict

import pytest

from paper.paper_trader import (
    PaperTrader,
    OpenPosition,
    ROUND_TRIP_FEE_BPS,
    CONSUMER_GROUP,
)
from signals.exit_manager import ExitManager


# ── Mock Redis ───────────────────────────────────────────────────────

class MockRedisInner:
    def __init__(self):
        self.data: Dict[str, str] = {}
        self.streams: Dict[str, list] = {}

    async def ping(self):
        return True

    async def set(self, key, value):
        self.data[key] = value

    async def get(self, key):
        return self.data.get(key)

    async def xgroup_create(self, stream, group, id="0", mkstream=False):
        pass

    async def xreadgroup(self, group, consumer, streams, count=10, block=2000):
        return []

    async def xack(self, stream, group, msg_id):
        pass

    async def xadd(self, stream, fields, maxlen=None, approximate=True):
        if stream not in self.streams:
            self.streams[stream] = []
        entry_id = f"mock-{len(self.streams[stream])}"
        self.streams[stream].append((entry_id, fields))
        return entry_id

    async def xrevrange(self, key, count=1):
        entries = self.streams.get(key, [])
        if entries:
            return list(reversed(entries[-count:]))
        return []

    async def xlen(self, key):
        return len(self.streams.get(key, []))

    async def aclose(self):
        pass


class MockRedisClient:
    def __init__(self):
        self._inner = MockRedisInner()
        self._is_connected = True

    @property
    def client(self):
        return self._inner

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    def is_connected(self):
        return True


def _make_trader() -> tuple:
    """Create a PaperTrader with mock Redis, returns (trader, mock)."""
    trader = PaperTrader.__new__(PaperTrader)
    mock = MockRedisClient()
    trader._redis = mock
    trader._pnl = None
    trader._http = None
    trader._positions = {}
    trader._price_cache = {}
    trader._running = True
    trader._shutdown_event = asyncio.Event()
    trader._mode = "paper"
    trader._pairs = ["BTC/USD"]
    trader._initial_balance = 10000.0
    trader._exit_manager = ExitManager(fee_bps=52.0)
    trader._pending_flip_signals = {}
    return trader, mock


def _signal_fields(
    pair: str = "BTC-USD",
    side: str = "LONG",
    entry: float = 68000.0,
    tp: float = 69496.0,
    sl: float = 67490.0,
    size: float = 100.0,
    ts: str = "",
    confidence: float = 0.85,
) -> dict:
    if not ts:
        ts = datetime.now(timezone.utc).isoformat()
    return {
        "signal_id": str(uuid.uuid4()),
        "pair": pair,
        "side": side,
        "entry_price": str(entry),
        "take_profit": str(tp),
        "stop_loss": str(sl),
        "position_size_usd": str(size),
        "confidence": str(confidence),
        "timestamp": ts,
    }


# ── Tests ────────────────────────────────────────────────────────────

class TestSignalParsing:
    def test_parse_flat_fields(self):
        trader, _ = _make_trader()
        fields = _signal_fields()
        parsed = trader._parse_signal(fields)
        assert parsed is not None
        assert parsed["pair"] == "BTC/USD"
        assert parsed["side"] == "LONG"

    def test_parse_json_blob(self):
        trader, _ = _make_trader()
        data = {"pair": "ETH/USD", "side": "SHORT", "entry_price": "3000.0",
                "timestamp": datetime.now(timezone.utc).isoformat()}
        fields = {"data": json.dumps(data)}
        parsed = trader._parse_signal(fields)
        assert parsed is not None
        assert parsed["pair"] == "ETH/USD"

    def test_parse_garbage_returns_none(self):
        trader, _ = _make_trader()
        assert trader._parse_signal({"random": "data"}) is None


class TestPositionOpening:
    def test_open_long(self):
        trader, mock = _make_trader()
        fields = _signal_fields(side="LONG", entry=68000.0, size=100.0)
        asyncio.run(trader._process_signal("signals:paper:BTC-USD", "1-0", fields))
        assert "BTC/USD" in trader._positions
        pos = trader._positions["BTC/USD"]
        assert pos.side == "LONG"
        assert pos.entry_price == 68000.0
        assert abs(pos.quantity - 100.0 / 68000.0) < 1e-10

    def test_open_short(self):
        trader, mock = _make_trader()
        fields = _signal_fields(side="SHORT", entry=68000.0, size=200.0)
        asyncio.run(trader._process_signal("signals:paper:BTC-USD", "1-0", fields))
        pos = trader._positions["BTC/USD"]
        assert pos.side == "SHORT"
        assert abs(pos.quantity - 200.0 / 68000.0) < 1e-10

    def test_skip_duplicate_direction(self):
        trader, mock = _make_trader()
        fields1 = _signal_fields(side="LONG")
        fields2 = _signal_fields(side="LONG")
        asyncio.run(trader._process_signal("signals:paper:BTC-USD", "1-0", fields1))
        asyncio.run(trader._process_signal("signals:paper:BTC-USD", "2-0", fields2))
        # Should still only have 1 position
        assert len(trader._positions) == 1


class TestPositionClosing:
    def test_close_long_tp(self):
        trader, mock = _make_trader()
        fields = _signal_fields(entry=68000.0, tp=69496.0, sl=67490.0, size=100.0)
        asyncio.run(trader._process_signal("signals:paper:BTC-USD", "1-0", fields))
        asyncio.run(trader._close_position("BTC/USD", 69496.0, "tp_hit"))
        assert "BTC/USD" not in trader._positions
        # Check trade published
        trades = mock._inner.streams.get("trades:paper:BTC-USD", [])
        assert len(trades) == 1
        assert trades[0][1]["exit_reason"] == "tp_hit"

    def test_close_short_tp(self):
        trader, mock = _make_trader()
        fields = _signal_fields(side="SHORT", entry=68000.0, tp=66500.0, sl=68710.0, size=100.0)
        asyncio.run(trader._process_signal("signals:paper:BTC-USD", "1-0", fields))
        asyncio.run(trader._close_position("BTC/USD", 66500.0, "tp_hit"))
        trades = mock._inner.streams.get("trades:paper:BTC-USD", [])
        pnl = float(trades[0][1]["realized_pnl"])
        assert pnl > 0  # Profitable trade

    def test_close_long_sl(self):
        trader, mock = _make_trader()
        fields = _signal_fields(entry=68000.0, tp=69496.0, sl=67490.0, size=100.0)
        asyncio.run(trader._process_signal("signals:paper:BTC-USD", "1-0", fields))
        asyncio.run(trader._close_position("BTC/USD", 67490.0, "sl_hit"))
        trades = mock._inner.streams.get("trades:paper:BTC-USD", [])
        pnl = float(trades[0][1]["realized_pnl"])
        assert pnl < 0  # Losing trade


class TestFeeCalculation:
    def test_52bps_round_trip(self):
        """Verify 52 bps round-trip fee is correctly applied."""
        trader, mock = _make_trader()
        entry = 68000.0
        size = 100.0
        tp = 69496.0  # 220 bps up

        fields = _signal_fields(entry=entry, tp=tp, sl=67490.0, size=size)
        asyncio.run(trader._process_signal("signals:paper:BTC-USD", "1-0", fields))
        asyncio.run(trader._close_position("BTC/USD", tp, "tp_hit"))

        trades = mock._inner.streams["trades:paper:BTC-USD"]
        t = trades[0][1]
        qty = size / entry
        expected_raw = (tp - entry) * qty
        expected_fees = entry * qty * (ROUND_TRIP_FEE_BPS / 10000)
        expected_net = expected_raw - expected_fees

        actual_pnl = float(t["realized_pnl"])
        actual_fees = float(t["fees"])

        assert abs(actual_fees - expected_fees) < 0.001
        assert abs(actual_pnl - expected_net) < 0.001
        assert int(t["fee_bps"]) == ROUND_TRIP_FEE_BPS


class TestStaleSignalGate:
    def test_stale_signal_skipped(self):
        trader, mock = _make_trader()
        old_ts = datetime(2025, 1, 1, tzinfo=timezone.utc).isoformat()
        fields = _signal_fields(ts=old_ts)
        asyncio.run(trader._process_signal("signals:paper:BTC-USD", "1-0", fields))
        assert len(trader._positions) == 0

    def test_fresh_signal_accepted(self):
        trader, mock = _make_trader()
        fields = _signal_fields()  # current timestamp
        asyncio.run(trader._process_signal("signals:paper:BTC-USD", "1-0", fields))
        assert len(trader._positions) == 1


class TestSignalFlip:
    def test_long_to_short_flip(self):
        trader, mock = _make_trader()
        # Inject price for close
        mock._inner.streams["kraken:ohlc:1m:BTC-USD"] = [
            ("mock-0", {"close": "68200.0"}),
        ]
        # Open LONG
        asyncio.run(trader._process_signal(
            "signals:paper:BTC-USD", "1-0",
            _signal_fields(side="LONG", entry=68000.0),
        ))
        assert trader._positions["BTC/USD"].side == "LONG"
        # Flip to SHORT
        asyncio.run(trader._process_signal(
            "signals:paper:BTC-USD", "2-0",
            _signal_fields(side="SHORT", entry=68200.0),
        ))
        assert trader._positions["BTC/USD"].side == "SHORT"
        # LONG should have been closed
        trades = mock._inner.streams.get("trades:paper:BTC-USD", [])
        assert len(trades) >= 1
        assert trades[0][1]["exit_reason"] == "signal_flip"


class TestShutdown:
    def test_shutdown_closes_positions(self):
        trader, mock = _make_trader()
        mock._inner.streams["kraken:ohlc:1m:BTC-USD"] = [
            ("mock-0", {"close": "68500.0"}),
        ]
        fields = _signal_fields(entry=68000.0)
        asyncio.run(trader._process_signal("signals:paper:BTC-USD", "1-0", fields))
        assert len(trader._positions) == 1
        asyncio.run(trader._shutdown_positions())
        assert len(trader._positions) == 0
        trades = mock._inner.streams.get("trades:paper:BTC-USD", [])
        assert trades[-1][1]["exit_reason"] == "shutdown"
