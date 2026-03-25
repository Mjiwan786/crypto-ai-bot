#!/usr/bin/env python3
"""
Paper Trade Consumer — Sprint 2 (P0-C)

Subscribes to signals:paper:{PAIR} Redis streams via XREADGROUP,
opens/monitors/closes paper positions, publishes trades to
trades:paper:{PAIR} and PnL to pnl:paper:summary.

This is the MISSING LINK: signals publish to Redis but nothing consumed
them until now.

Runs as a SEPARATE Fly.io process (paper_trader in fly.toml).

Feature flag: PAPER_TRADER_ENABLED (default true)

Usage:
    python -u paper/paper_trader.py         # Production
    python -u paper/paper_trader.py --test  # Self-test with mock Redis
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp

# Ensure project root on sys.path
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Fix Windows console encoding
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from agents.infrastructure.redis_client import RedisCloudClient, RedisCloudConfig
from pnl.rolling_pnl import PnLTracker
from config.trading_pairs import DEFAULT_TRADING_PAIRS_CSV
from signals.exit_manager import ExitManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("paper_trader")

# ── Constants ────────────────────────────────────────────────────────
CONSUMER_GROUP = "paper-trader-group"
CONSUMER_NAME = "paper-trader-1"
from signals.fee_model import get_fee_for_venue

ROUND_TRIP_FEE_BPS = get_fee_for_venue()  # Per-exchange fee model (default 20 bps)
STALE_SIGNAL_SECONDS = 60
MONITOR_INTERVAL_S = 5
KRAKEN_API_URL = "https://api.kraken.com/0/public/Ticker"

KRAKEN_PAIR_MAP = {
    "BTC/USD": "XXBTZUSD", "ETH/USD": "XETHZUSD", "SOL/USD": "SOLUSD",
    "ADA/USD": "ADAUSD", "LINK/USD": "LINKUSD", "DOT/USD": "DOTUSD",
    "AVAX/USD": "AVAXUSD", "DOGE/USD": "XDGUSD", "XRP/USD": "XRPUSD",
    "MATIC/USD": "MATICUSD", "ALGO/USD": "ALGOUSD", "LTC/USD": "LTCUSD",
    "UNI/USD": "UNIUSD", "ATOM/USD": "ATOMUSD", "NEAR/USD": "NEARUSD",
    "ARB/USD": "ARBUSD",
}
PRICE_CACHE_TTL = 5.0


# ── Position ─────────────────────────────────────────────────────────
@dataclass
class OpenPosition:
    signal_id: str
    pair: str
    side: str           # "LONG" or "SHORT"
    entry_price: float
    stop_loss: float
    take_profit: float
    quantity: float
    open_time: float    # unix timestamp
    position_size_usd: float
    atr_value: float = 0.0
    highest_since_entry: float = 0.0
    lowest_since_entry: float = float("inf")
    confidence: float = 0.5


# ── Paper Trader ─────────────────────────────────────────────────────
class PaperTrader:
    """
    Async paper trade consumer.

    Lifecycle: init → connect() → run() → shutdown()
    """

    def __init__(
        self,
        redis_url: str = "",
        redis_ca_cert: str = "",
        trading_pairs: Optional[List[str]] = None,
        mode: str = "paper",
        initial_balance: float = 10000.0,
    ):
        self._redis_url = redis_url or os.getenv("REDIS_URL", "")
        self._redis_ca_cert = redis_ca_cert or os.getenv(
            "REDIS_CA_CERT",
            str(Path(__file__).parent.parent / "config" / "certs" / "redis_ca.pem"),
        )
        self._mode = mode
        self._pairs = trading_pairs or os.getenv(
            "TRADING_PAIRS", DEFAULT_TRADING_PAIRS_CSV
        ).split(",")

        self._redis: Optional[RedisCloudClient] = None
        self._pnl: Optional[PnLTracker] = None
        self._http: Optional[aiohttp.ClientSession] = None

        # Open positions: pair → OpenPosition (max 1 per pair)
        self._positions: Dict[str, OpenPosition] = {}

        # Price cache: pair → (price, timestamp)
        self._price_cache: Dict[str, tuple] = {}

        # Exit manager (Sprint 3B)
        self._exit_manager = ExitManager(fee_bps=ROUND_TRIP_FEE_BPS)

        # Pending opposing signals: pair → signal dict (for ExitManager evaluation)
        self._pending_flip_signals: Dict[str, Dict] = {}

        # State
        self._running = False
        self._shutdown_event = asyncio.Event()
        self._initial_balance = initial_balance

    # ── Connection ───────────────────────────────────────────────
    async def connect(self) -> None:
        """Connect to Redis and initialize PnL tracker."""
        logger.info("[PAPER_TRADER] Connecting to Redis...")
        config = RedisCloudConfig(
            url=self._redis_url,
            ca_cert_path=self._redis_ca_cert,
        )
        self._redis = RedisCloudClient(config)
        await self._redis.connect()
        logger.info("[PAPER_TRADER] Redis connected")

        # PnL tracker
        self._pnl = PnLTracker(
            redis_url=self._redis_url,
            redis_cert_path=self._redis_ca_cert,
            initial_balance=self._initial_balance,
            mode=self._mode,
        )
        await self._pnl.connect()
        logger.info("[PAPER_TRADER] PnL tracker connected")

        # Create consumer groups (idempotent)
        for pair in self._pairs:
            stream = f"signals:{self._mode}:{pair.replace('/', '-')}"
            try:
                await self._redis.client.xgroup_create(
                    stream, CONSUMER_GROUP, id="0", mkstream=True,
                )
                logger.info("[PAPER_TRADER] Created group %s on %s", CONSUMER_GROUP, stream)
            except Exception as e:
                if "BUSYGROUP" in str(e):
                    logger.debug("[PAPER_TRADER] Group %s already exists on %s", CONSUMER_GROUP, stream)
                else:
                    logger.warning("[PAPER_TRADER] xgroup_create error on %s: %s", stream, e)

        stream_list = ", ".join(
            f"signals:{self._mode}:{p.replace('/', '-')}" for p in self._pairs
        )
        logger.info("[PAPER_TRADER] Subscribed to %s", stream_list)

    async def disconnect(self) -> None:
        """Disconnect all components."""
        if self._http:
            await self._http.close()
            self._http = None
        if self._pnl:
            await self._pnl.close()
            self._pnl = None
        if self._redis:
            await self._redis.disconnect()
            self._redis = None
        logger.info("[PAPER_TRADER] Disconnected")

    # ── Price fetching ───────────────────────────────────────────
    async def _get_current_price(self, pair: str) -> Optional[float]:
        """
        Get current price. Try OHLCV stream first, fall back to REST.
        """
        # Try Redis OHLCV stream
        try:
            dash_pair = pair.replace("/", "-")
            entries = await self._redis.client.xrevrange(
                f"kraken:ohlc:1m:{dash_pair}", count=1,
            )
            if entries:
                _, fields = entries[0]
                close_val = fields.get("close") or fields.get(b"close")
                if close_val:
                    if isinstance(close_val, bytes):
                        close_val = close_val.decode()
                    return float(close_val)
        except Exception as e:
            logger.debug("[PAPER_TRADER] OHLCV read failed for %s: %s", pair, e)

        # Fall back to REST
        return await self._fetch_rest_price(pair)

    async def _fetch_rest_price(self, pair: str) -> Optional[float]:
        """Fetch price from Kraken REST API with caching."""
        now = time.time()
        if pair in self._price_cache:
            cached_price, cached_time = self._price_cache[pair]
            if now - cached_time < PRICE_CACHE_TTL:
                return cached_price

        kraken_pair = KRAKEN_PAIR_MAP.get(pair, pair.replace("/", ""))
        try:
            if not self._http:
                self._http = aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=10),
                )
            url = f"{KRAKEN_API_URL}?pair={kraken_pair}"
            async with self._http.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                if data.get("error"):
                    return None
                result = data.get("result", {})
                if not result:
                    return None
                pair_data = list(result.values())[0]
                price = float(pair_data["c"][0])
                self._price_cache[pair] = (price, now)
                return price
        except Exception as e:
            logger.warning("[PAPER_TRADER] REST price failed for %s: %s", pair, e)
            if pair in self._price_cache:
                return self._price_cache[pair][0]
            return None

    # ── Signal consumption ───────────────────────────────────────
    async def _consume_signals(self) -> None:
        """XREADGROUP loop: read new signals, open/flip positions."""
        streams = {
            f"signals:{self._mode}:{p.replace('/', '-')}": ">"
            for p in self._pairs
        }

        while self._running:
            try:
                results = await self._redis.client.xreadgroup(
                    CONSUMER_GROUP, CONSUMER_NAME,
                    streams,
                    count=10,
                    block=2000,  # 2s block, then loop to check _running
                )
                if not results:
                    continue

                for stream_key, messages in results:
                    if isinstance(stream_key, bytes):
                        stream_key = stream_key.decode()
                    for msg_id, fields in messages:
                        await self._process_signal(stream_key, msg_id, fields)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[PAPER_TRADER] consume error: %s", e, exc_info=True)
                await asyncio.sleep(2)

    async def _process_signal(
        self, stream_key: str, msg_id: Any, fields: Dict
    ) -> None:
        """Process a single signal from the stream."""
        try:
            # Decode fields
            decoded = {}
            for k, v in fields.items():
                key = k.decode() if isinstance(k, bytes) else k
                val = v.decode() if isinstance(v, bytes) else v
                decoded[key] = val

            # Parse signal — PRDPublisher stores as flat fields or JSON blob
            signal = self._parse_signal(decoded)
            if signal is None:
                await self._ack(stream_key, msg_id)
                return

            pair = signal["pair"]
            signal_id = signal.get("signal_id", str(uuid.uuid4()))

            # Staleness gate
            try:
                sig_ts = datetime.fromisoformat(signal["timestamp"]).timestamp()
            except (KeyError, ValueError):
                sig_ts = time.time()
            age_s = time.time() - sig_ts
            if age_s > STALE_SIGNAL_SECONDS:
                logger.info(
                    "[PAPER_TRADER] Skipping stale signal %s (%.1fs old)",
                    signal_id, age_s,
                )
                await self._ack(stream_key, msg_id)
                return

            side = signal["side"]  # "LONG" or "SHORT"

            # Position gate: close existing if different direction (signal flip)
            if pair in self._positions:
                existing = self._positions[pair]
                if existing.side != side:
                    conf = float(signal.get("confidence", 0.5))
                    if conf >= self._exit_manager.signal_flip_min_confidence:
                        price = await self._get_current_price(pair)
                        if price:
                            await self._close_position(pair, price, "signal_flip")
                    else:
                        logger.info(
                            "[PAPER_TRADER] %s: Ignoring weak signal flip (conf=%.2f < %.2f)",
                            pair, conf, self._exit_manager.signal_flip_min_confidence,
                        )
                        await self._ack(stream_key, msg_id)
                        return
                else:
                    # Same direction, already have position — skip
                    logger.debug(
                        "[PAPER_TRADER] Already have %s position on %s, skipping",
                        side, pair,
                    )
                    await self._ack(stream_key, msg_id)
                    return

            # Open new position
            entry_price = signal.get("entry_price")
            if not entry_price:
                entry_price = await self._get_current_price(pair)
            else:
                entry_price = float(entry_price)

            if not entry_price:
                logger.warning("[PAPER_TRADER] No price for %s, skipping signal", pair)
                await self._ack(stream_key, msg_id)
                return

            position_size_usd = float(signal.get("position_size_usd", 100.0))
            quantity = position_size_usd / entry_price

            # Extract ATR value for ExitManager (trailing stop + breakeven activation).
            # _parse_signal() already resolved indicators_atr_14 from the flat Redis
            # fields written by PRDPublisher.to_redis_dict() and stored it as atr_value.
            # Fall back to JSON-blob parsing for any legacy publishers that serialize
            # indicators as a JSON string in a single "indicators" field.
            atr_value = float(signal.get("atr_value", 0.0))
            if atr_value == 0.0:
                indicators_raw = signal.get("indicators", "")
                if isinstance(indicators_raw, str) and indicators_raw:
                    try:
                        ind = json.loads(indicators_raw)
                        atr_value = float(ind.get("atr_14", 0))
                    except (json.JSONDecodeError, TypeError, ValueError):
                        pass
                elif isinstance(indicators_raw, dict):
                    atr_value = float(indicators_raw.get("atr_14", 0))

            if atr_value == 0.0:
                logger.warning(
                    "[PAPER_TRADER] %s: atr_value=0 — trailing stop and breakeven "
                    "will be inactive for this position. Check that indicators_atr_14 "
                    "is present in the signal stream.",
                    pair,
                )
            else:
                logger.debug("[PAPER_TRADER] %s: atr_value=%.6f from signal", pair, atr_value)

            pos = OpenPosition(
                signal_id=signal_id,
                pair=pair,
                side=side,
                entry_price=entry_price,
                stop_loss=float(signal.get("stop_loss", 0)),
                take_profit=float(signal.get("take_profit", 0)),
                quantity=quantity,
                open_time=time.time(),
                position_size_usd=position_size_usd,
                atr_value=atr_value,
                highest_since_entry=entry_price,
                lowest_since_entry=entry_price,
                confidence=float(signal.get("confidence", 0.5)),
            )
            self._positions[pair] = pos

            # Record entry in PnL tracker
            if self._pnl:
                pnl_side = "long" if side == "LONG" else "short"
                await self._pnl.process_fill(
                    pair=pair, side=pnl_side, quantity=quantity,
                    price=entry_price, is_entry=True,
                )

            logger.info(
                "[PAPER_TRADER] OPENED %s %s @ $%.2f (qty=%.6f, TP=$%.2f, SL=$%.2f, ATR=%.6f)",
                pair, side, entry_price, quantity,
                pos.take_profit, pos.stop_loss, atr_value,
            )
            await self._ack(stream_key, msg_id)

        except Exception as e:
            logger.error("[PAPER_TRADER] process_signal error: %s", e, exc_info=True)
            await self._ack(stream_key, msg_id)

    def _parse_signal(self, fields: Dict[str, str]) -> Optional[Dict[str, Any]]:
        """Parse signal from Redis stream fields."""
        # PRDPublisher stores signals as individual flat fields
        if "pair" in fields and "side" in fields:
            # PRDPublisher.to_redis_dict() flattens nested objects with a prefix, so
            # indicators.atr_14 is stored as the flat field "indicators_atr_14" —
            # there is NO "indicators" JSON blob field in the stream.
            # Read the flat field directly; fall back to 0.0 if absent.
            atr_value_raw = fields.get("indicators_atr_14", "0")
            try:
                atr_value = float(atr_value_raw)
            except (TypeError, ValueError):
                atr_value = 0.0

            return {
                "signal_id": fields.get("signal_id", str(uuid.uuid4())),
                "pair": fields["pair"].replace("-", "/"),
                "side": fields["side"].upper(),
                "entry_price": fields.get("entry_price"),
                "take_profit": fields.get("take_profit"),
                "stop_loss": fields.get("stop_loss"),
                "confidence": fields.get("confidence", "0.5"),
                "position_size_usd": fields.get("position_size_usd", "100.0"),
                "timestamp": fields.get("timestamp", datetime.now(timezone.utc).isoformat()),
                "strategy": fields.get("strategy", "SCALPER"),
                "indicators": fields.get("indicators", ""),  # kept for legacy publishers
                "atr_value": atr_value,
            }

        # Some publishers store as a JSON blob in "data" field
        if "data" in fields:
            try:
                data = json.loads(fields["data"])
                if "pair" in data:
                    return data
            except (json.JSONDecodeError, TypeError):
                pass

        logger.debug("[PAPER_TRADER] Unparseable signal fields: %s", list(fields.keys()))
        return None

    async def _ack(self, stream_key: str, msg_id: Any) -> None:
        """ACK a message in the consumer group."""
        try:
            await self._redis.client.xack(stream_key, CONSUMER_GROUP, msg_id)
        except Exception as e:
            logger.debug("[PAPER_TRADER] xack error: %s", e)

    # ── Position monitoring ──────────────────────────────────────
    async def _monitor_positions(self) -> None:
        """Every 5s, evaluate open positions via ExitManager hierarchy."""
        while self._running:
            try:
                pairs_to_check = list(self._positions.keys())
                for pair in pairs_to_check:
                    if pair not in self._positions:
                        continue
                    pos = self._positions[pair]
                    price = await self._get_current_price(pair)
                    if price is None:
                        continue

                    # Update high/low watermarks
                    if price > pos.highest_since_entry:
                        pos.highest_since_entry = price
                    if price < pos.lowest_since_entry:
                        pos.lowest_since_entry = price

                    # Check for pending opposing signal
                    pending_signal = self._pending_flip_signals.pop(pair, None)

                    # Build position dict for ExitManager
                    pos_dict = {
                        "side": pos.side,
                        "entry_price": pos.entry_price,
                        "stop_loss": pos.stop_loss,
                        "take_profit": pos.take_profit,
                        "atr_value": pos.atr_value,
                        "open_time": pos.open_time,
                        "pair": pair,
                    }

                    exit_decision = self._exit_manager.evaluate_exit(
                        position=pos_dict,
                        current_price=price,
                        current_time=time.time(),
                        highest_since_entry=pos.highest_since_entry,
                        lowest_since_entry=pos.lowest_since_entry,
                        new_signal=pending_signal,
                    )

                    if exit_decision is not None:
                        await self._close_position(
                            pair, exit_decision["exit_price"], exit_decision["exit_reason"],
                        )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[PAPER_TRADER] monitor error: %s", e, exc_info=True)

            await asyncio.sleep(MONITOR_INTERVAL_S)

    async def _close_position(self, pair: str, exit_price: float, reason: str) -> None:
        """Close an open position and publish trade result."""
        if pair not in self._positions:
            return

        pos = self._positions.pop(pair)

        # Direction multiplier
        if pos.side == "LONG":
            raw_pnl = (exit_price - pos.entry_price) * pos.quantity
        else:
            raw_pnl = (pos.entry_price - exit_price) * pos.quantity

        # Fees: 52 bps round-trip on notional
        fees = pos.entry_price * pos.quantity * (ROUND_TRIP_FEE_BPS / 10000)
        realized_pnl = raw_pnl - fees

        duration_s = time.time() - pos.open_time
        pnl_pct = (realized_pnl / pos.position_size_usd) * 100 if pos.position_size_usd else 0

        # Format duration
        mins = int(duration_s // 60)
        secs = int(duration_s % 60)
        duration_str = f"{mins}m{secs:02d}s"

        pnl_sign = "+" if realized_pnl >= 0 else ""

        logger.info(
            "[PAPER_TRADER] CLOSED %s %s: entry=$%.2f exit=$%.2f "
            "pnl=%s$%.2f (%.2f%%) reason=%s duration=%s",
            pair, pos.side, pos.entry_price, exit_price,
            pnl_sign, realized_pnl, pnl_pct, reason, duration_str,
        )

        # Publish trade to trades:paper:{PAIR}
        trade_id = str(uuid.uuid4())
        trade_data = {
            "trade_id": trade_id,
            "signal_id": pos.signal_id,
            "pair": pair,
            "side": pos.side,
            "entry_price": str(pos.entry_price),
            "exit_price": str(exit_price),
            "quantity": str(pos.quantity),
            "realized_pnl": str(round(realized_pnl, 4)),
            "raw_pnl": str(round(raw_pnl, 4)),
            "fees": str(round(fees, 4)),
            "fee_bps": str(ROUND_TRIP_FEE_BPS),
            "exit_reason": reason,
            "duration_seconds": str(round(duration_s, 1)),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": self._mode,
        }

        try:
            dash_pair = pair.replace("/", "-")
            await self._redis.client.xadd(
                f"trades:{self._mode}:{dash_pair}",
                trade_data,
                maxlen=10000,
                approximate=True,
            )
        except Exception as e:
            logger.error("[PAPER_TRADER] Failed to publish trade: %s", e)

        # Update PnL tracker
        if self._pnl:
            try:
                pnl_side = "long" if pos.side == "LONG" else "short"
                await self._pnl.process_fill(
                    pair=pair, side=pnl_side, quantity=pos.quantity,
                    price=exit_price, is_entry=False,
                )
            except Exception as e:
                logger.error("[PAPER_TRADER] PnL update failed: %s", e)

    # ── Shutdown ─────────────────────────────────────────────────
    async def _shutdown_positions(self) -> None:
        """Close all open positions on shutdown."""
        pairs = list(self._positions.keys())
        if not pairs:
            return
        logger.info("[PAPER_TRADER] Closing %d open positions on shutdown...", len(pairs))
        for pair in pairs:
            price = await self._get_current_price(pair)
            if price:
                await self._close_position(pair, price, "shutdown")
            else:
                # Force close at entry price (no PnL impact minus fees)
                pos = self._positions.get(pair)
                if pos:
                    await self._close_position(pair, pos.entry_price, "shutdown")

    # ── Main run loop ────────────────────────────────────────────
    async def run(self) -> None:
        """Main entry: run signal consumer + position monitor concurrently."""
        self._running = True
        logger.info("[PAPER_TRADER] Starting paper trade consumer...")
        logger.info("[PAPER_TRADER] Pairs: %s", ", ".join(self._pairs))
        logger.info("[PAPER_TRADER] Fee: %d bps RT, Stale gate: %ds", ROUND_TRIP_FEE_BPS, STALE_SIGNAL_SECONDS)

        consumer_task = asyncio.create_task(self._consume_signals(), name="signal_consumer")
        monitor_task = asyncio.create_task(self._monitor_positions(), name="position_monitor")

        try:
            await self._shutdown_event.wait()
        except asyncio.CancelledError:
            pass
        finally:
            self._running = False
            consumer_task.cancel()
            monitor_task.cancel()
            try:
                await asyncio.gather(consumer_task, monitor_task, return_exceptions=True)
            except Exception:
                pass
            await self._shutdown_positions()
            logger.info("[PAPER_TRADER] Run loop stopped")

    def request_shutdown(self) -> None:
        """Request graceful shutdown (called from signal handler)."""
        logger.info("[PAPER_TRADER] Shutdown requested")
        self._running = False
        self._shutdown_event.set()


# ── Main entry point ─────────────────────────────────────────────────
async def main() -> None:
    import signal as signal_mod
    from dotenv import load_dotenv
    load_dotenv()

    enabled = os.getenv("PAPER_TRADER_ENABLED", "true").lower() == "true"
    if not enabled:
        logger.info("[PAPER_TRADER] Disabled via PAPER_TRADER_ENABLED=false, exiting")
        return

    redis_url = os.getenv("REDIS_URL", "")
    if not redis_url:
        logger.error("[PAPER_TRADER] REDIS_URL not set, exiting")
        sys.exit(1)

    trader = PaperTrader(redis_url=redis_url)

    # SIGTERM handler
    if sys.platform != "win32":
        loop = asyncio.get_running_loop()
        for sig in (signal_mod.SIGTERM, signal_mod.SIGINT):
            loop.add_signal_handler(sig, trader.request_shutdown)

    await trader.connect()
    try:
        await trader.run()
    finally:
        await trader.disconnect()


# ── Self-test ────────────────────────────────────────────────────────
async def run_self_test() -> None:
    """Self-test with mock Redis — validates core logic without real connections."""
    import types

    print("=" * 60)
    print("Paper Trader — Self-Test (mock Redis)")
    print("=" * 60)

    # ── Mock Redis ──────────────────────────────────
    class MockRedisInner:
        def __init__(self):
            self.data: Dict[str, str] = {}
            self.streams: Dict[str, list] = {}
            self.groups: Dict[str, bool] = {}
            self._xadd_log: list = []

        async def ping(self):
            return True

        async def set(self, key, value):
            self.data[key] = value

        async def get(self, key):
            return self.data.get(key)

        async def xgroup_create(self, stream, group, id="0", mkstream=False):
            self.groups[f"{stream}:{group}"] = True

        async def xreadgroup(self, group, consumer, streams, count=10, block=2000):
            # Return nothing by default — tests inject signals manually
            return []

        async def xack(self, stream, group, msg_id):
            pass

        async def xadd(self, stream, fields, maxlen=None, approximate=True):
            if stream not in self.streams:
                self.streams[stream] = []
            entry_id = f"mock-{len(self.streams[stream])}"
            self.streams[stream].append((entry_id, fields))
            self._xadd_log.append((stream, fields))
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

    # ── Build trader with mocks ────────────────────
    trader = PaperTrader.__new__(PaperTrader)
    mock_redis = MockRedisClient()
    trader._redis = mock_redis
    trader._pnl = None  # Skip PnL for mock test
    trader._http = None
    trader._positions = {}
    trader._price_cache = {}
    trader._running = True
    trader._shutdown_event = asyncio.Event()
    trader._mode = "paper"
    trader._pairs = ["BTC/USD"]
    trader._initial_balance = 10000.0
    trader._exit_manager = ExitManager(fee_bps=ROUND_TRIP_FEE_BPS)
    trader._pending_flip_signals = {}

    # ── Test 1: Parse signal ──────────────────────
    print("\nTest 1: Parse signal from flat fields")
    parsed = trader._parse_signal({
        "signal_id": "test-123",
        "pair": "BTC-USD",
        "side": "LONG",
        "entry_price": "68000.0",
        "take_profit": "69496.0",
        "stop_loss": "67490.0",
        "confidence": "0.65",
        "position_size_usd": "100.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "strategy": "SCALPER",
    })
    assert parsed is not None
    assert parsed["pair"] == "BTC/USD"
    assert parsed["side"] == "LONG"
    print("  PASS")

    # ── Test 2: Open position ─────────────────────
    print("\nTest 2: Process signal → open position")
    signal_fields = {
        "signal_id": "sig-001",
        "pair": "BTC-USD",
        "side": "LONG",
        "entry_price": "68000.0",
        "take_profit": "69496.0",
        "stop_loss": "67490.0",
        "confidence": "0.65",
        "position_size_usd": "100.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await trader._process_signal("signals:paper:BTC-USD", "1-0", signal_fields)
    assert "BTC/USD" in trader._positions
    pos = trader._positions["BTC/USD"]
    assert pos.side == "LONG"
    assert pos.entry_price == 68000.0
    assert abs(pos.quantity - 100.0 / 68000.0) < 1e-8
    print(f"  Position opened: {pos.side} {pos.pair} qty={pos.quantity:.8f}")
    print("  PASS")

    # ── Test 3: Close on TP hit ───────────────────
    print("\nTest 3: Close position on TP hit")
    tp_price = 69496.0
    await trader._close_position("BTC/USD", tp_price, "tp_hit")
    assert "BTC/USD" not in trader._positions

    # Verify trade published
    trade_stream = "trades:paper:BTC-USD"
    assert trade_stream in mock_redis._inner.streams
    trade_entry = mock_redis._inner.streams[trade_stream][-1]
    trade_fields = trade_entry[1]
    assert trade_fields["exit_reason"] == "tp_hit"
    assert trade_fields["side"] == "LONG"
    realized_pnl = float(trade_fields["realized_pnl"])
    fees = float(trade_fields["fees"])
    print(f"  PnL: ${realized_pnl:.4f}, Fees: ${fees:.4f}")
    print("  PASS")

    # ── Test 4: Fee calculation ───────────────────
    print("\nTest 4: Fee math verification")
    expected_qty = 100.0 / 68000.0
    expected_raw = (69496.0 - 68000.0) * expected_qty
    expected_fees = 68000.0 * expected_qty * (ROUND_TRIP_FEE_BPS / 10000)
    expected_net = expected_raw - expected_fees
    assert abs(realized_pnl - expected_net) < 0.01, f"PnL mismatch: {realized_pnl} vs {expected_net}"
    assert abs(fees - expected_fees) < 0.01, f"Fee mismatch: {fees} vs {expected_fees}"
    print(f"  Raw: ${expected_raw:.4f}, Fees: ${expected_fees:.4f}, Net: ${expected_net:.4f}")
    print("  PASS")

    # ── Test 5: Stale signal gate ─────────────────
    print("\nTest 5: Stale signal skipped")
    old_ts = datetime(2025, 1, 1, tzinfo=timezone.utc).isoformat()
    stale_fields = {
        "signal_id": "stale-001",
        "pair": "BTC-USD",
        "side": "LONG",
        "entry_price": "68000.0",
        "take_profit": "69496.0",
        "stop_loss": "67490.0",
        "timestamp": old_ts,
    }
    before_count = len(trader._positions)
    await trader._process_signal("signals:paper:BTC-USD", "2-0", stale_fields)
    assert len(trader._positions) == before_count  # Should not open
    print("  PASS")

    # ── Test 6: Signal flip ───────────────────────
    print("\nTest 6: Signal flip (LONG → SHORT)")
    # Open a LONG
    long_fields = {
        "signal_id": "sig-002",
        "pair": "BTC-USD",
        "side": "LONG",
        "entry_price": "68000.0",
        "take_profit": "69496.0",
        "stop_loss": "67490.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "position_size_usd": "100.0",
    }
    await trader._process_signal("signals:paper:BTC-USD", "3-0", long_fields)
    assert "BTC/USD" in trader._positions
    assert trader._positions["BTC/USD"].side == "LONG"

    # Inject a price for the flip close
    mock_redis._inner.streams["kraken:ohlc:1m:BTC-USD"] = [
        ("mock-0", {"close": "68200.0"}),
    ]

    # Now send SHORT signal with high confidence → should close LONG, open SHORT
    short_fields = {
        "signal_id": "sig-003",
        "pair": "BTC-USD",
        "side": "SHORT",
        "entry_price": "68200.0",
        "take_profit": "66700.0",
        "stop_loss": "68710.0",
        "confidence": "0.90",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "position_size_usd": "100.0",
    }
    await trader._process_signal("signals:paper:BTC-USD", "4-0", short_fields)
    assert "BTC/USD" in trader._positions
    assert trader._positions["BTC/USD"].side == "SHORT"
    print("  PASS")

    # ── Test 7: SHORT TP hit ──────────────────────
    print("\nTest 7: SHORT position TP hit")
    await trader._close_position("BTC/USD", 66700.0, "tp_hit")
    assert "BTC/USD" not in trader._positions
    # Check the trade was published
    trades = mock_redis._inner.streams.get("trades:paper:BTC-USD", [])
    last_trade = trades[-1][1]
    assert last_trade["side"] == "SHORT"
    assert float(last_trade["exit_price"]) == 66700.0
    short_pnl = float(last_trade["realized_pnl"])
    assert short_pnl > 0  # TP hit should be profitable
    print(f"  SHORT PnL: ${short_pnl:.4f}")
    print("  PASS")

    print("\n" + "=" * 60)
    print("ALL SELF-TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Paper Trade Consumer")
    parser.add_argument("--test", action="store_true", help="Run self-test with mock Redis")
    args = parser.parse_args()

    if args.test:
        asyncio.run(run_self_test())
    else:
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            logger.info("[PAPER_TRADER] Shutdown requested")
            sys.exit(0)
