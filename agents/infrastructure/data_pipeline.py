"""
agents/infrastructure/data_pipeline.py

Production-ready data ingress/egress pipeline for crypto-ai-bot.
Provides resilient, observable data pipeline with:
- Kraken WebSocket ingestion (trades, spreads, order book)
- Redis Streams publishing with sharding
- Circuit breakers and health monitoring
- Optional REST backfill (OHLCV)
- Graceful shutdown and error handling

Designed to run standalone or integrate with the multi-agent system.
"""

from __future__ import annotations

import asyncio
import base64
import gzip
import json
import logging
import os
import re
import time
import uuid
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

import aiohttp
import redis.asyncio as redis
import websockets
from pydantic import BaseModel, Field, field_validator

from agents.infrastructure.redis_client import create_data_pipeline_redis_client

# Import canonical trading pairs (single source of truth)
try:
    from config.trading_pairs import DEFAULT_TRADING_PAIRS_CSV
    CANONICAL_PAIRS_AVAILABLE = True
except ImportError:
    CANONICAL_PAIRS_AVAILABLE = False
    DEFAULT_TRADING_PAIRS_CSV = "BTC/USD,ETH/USD,SOL/USD,LINK/USD"
    logging.warning("canonical trading_pairs not available, using defaults")

# --------------------------------------------------------------------------------------
# Constants and stream naming
# --------------------------------------------------------------------------------------

STREAM_TRADE = "md:trades:{symbol}"
STREAM_SPREAD = "md:spread:{symbol}"
STREAM_BOOK = "md:book:{symbol}"
STREAM_CANDLES = "md:candles:{symbol}:{tf}"
STREAM_EVENTS = "events:bus"

# Symbol validation (e.g., "BTC/USD")
SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]{2,20}/[A-Z0-9]{2,20}$")

# Kraken pair mappings (WS wants pairs like "XBT/USD"; REST keys are like "XBTUSD")
KRAKEN_PAIRS: Dict[str, str] = {
    "BTC/USD": "XBT/USD",
    "ETH/USD": "ETH/USD",
    "SOL/USD": "SOL/USD",
    "ADA/USD": "ADA/USD",
}

ALLOWED_TIMEFRAMES = {"1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"}

__all__ = [
    "DataPipelineConfig",
    "DataPipeline",
    "normalize_trade",
    "normalize_spread",
    "calc_spread_bps",
    "PipelineDegraded",
]

# --------------------------------------------------------------------------------------
# Exceptions
# --------------------------------------------------------------------------------------


class PipelineDegraded(Exception):
    """Raised when pipeline is degraded and cannot continue."""


class CircuitBreakerOpen(Exception):
    """Raised when circuit breaker is open."""


# --------------------------------------------------------------------------------------
# Configuration (Pydantic v2)
# --------------------------------------------------------------------------------------


class DataPipelineConfig(BaseModel):
    """Configuration for data pipeline with environment variable defaults."""

    # Redis connection
    redis_url: str = Field(default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379"))

    # Trading pairs and timeframes - uses canonical config/trading_pairs.py
    pairs: List[str] = Field(
        default_factory=lambda: os.getenv("TRADING_PAIRS", DEFAULT_TRADING_PAIRS_CSV).split(",")
    )
    timeframes: List[str] = Field(
        default_factory=lambda: os.getenv("TIMEFRAMES", "1m,5m").split(",")
    )

    # Stream configuration
    stream_batch_size: int = Field(default=50, ge=1, le=1000)
    create_consumer_groups: bool = Field(default=True)

    # WebSocket settings
    ws_reconnect_max_retries: int = Field(default=10, ge=1, le=100)
    ws_ping_interval_s: int = Field(default=20, ge=5, le=120)

    # Backfill settings
    startup_backfill_enabled: bool = Field(default=True)
    startup_backfill_limit: int = Field(default=300, ge=10, le=5000)

    # Redis settings
    decode_responses: bool = Field(default=True)
    client_name: str = Field(default="crypto-ai-bot:datapipe")
    compression_enabled: bool = Field(default=True)
    log_level: str = Field(default=os.getenv("LOG_LEVEL", "INFO"))

    # Stream limits
    stream_maxlen: int = Field(default=10000, ge=100)

    # Circuit breaker settings
    max_consecutive_errors: int = Field(default=5, ge=1, le=50)
    circuit_breaker_cooldown: int = Field(default=60, ge=10, le=600)
    max_latency_ms: float = Field(default=200.0, ge=10, le=5000)

    @classmethod
    def from_env(cls) -> "DataPipelineConfig":
        """Create configuration from environment variables."""
        return cls()

    @field_validator("pairs", mode="before")
    @classmethod
    def validate_pairs(cls, v: Any) -> List[str]:
        """Validate trading pairs format."""
        if isinstance(v, str):
            v = [p.strip() for p in v.split(",") if p.strip()]
        if not isinstance(v, list) or not v:
            raise ValueError("pairs must be a non-empty list of 'BASE/QUOTE' symbols")
        for pair in v:
            if not SYMBOL_PATTERN.match(pair):
                raise ValueError(f"Invalid pair format: {pair}")
        return v

    @field_validator("timeframes", mode="before")
    @classmethod
    def validate_timeframes(cls, v: Any) -> List[str]:
        """Validate timeframe values (Kraken uses minutes-based intervals)."""
        if isinstance(v, str):
            v = [t.strip() for t in v.split(",") if t.strip()]
        if not isinstance(v, list) or not v:
            raise ValueError("timeframes must be a non-empty list")
        tf_set = set(v)
        bad = tf_set - ALLOWED_TIMEFRAMES
        if bad:
            raise ValueError(
                f"Unsupported timeframes: {sorted(bad)}; allowed={sorted(ALLOWED_TIMEFRAMES)}"
            )
        return v

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, v: str) -> str:
        """Validate Redis URL format."""
        if not (v.startswith("redis://") or v.startswith("rediss://")):
            raise ValueError("Redis URL must start with redis:// or rediss://")
        return v


# --------------------------------------------------------------------------------------
# Circuit Breaker
# --------------------------------------------------------------------------------------


class CircuitBreakerState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Simple circuit breaker for fault tolerance."""

    def __init__(self, name: str, failure_threshold: int = 5, timeout: int = 60):
        self.name = name
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self.state = CircuitBreakerState.CLOSED
        self.logger = logging.getLogger(f"CircuitBreaker.{name}")

    async def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Execute function through circuit breaker."""
        now = time.time()
        if self.state == CircuitBreakerState.OPEN:
            if self.last_failure_time is not None and now - self.last_failure_time > self.timeout:
                self.state = CircuitBreakerState.HALF_OPEN
                self.logger.info("Circuit %s entering HALF_OPEN", self.name)
            else:
                raise CircuitBreakerOpen(f"Circuit breaker {self.name} is OPEN")

        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            await self.on_success()
            return result
        except Exception:
            await self.on_failure()
            raise

    async def on_success(self) -> None:
        """Reset circuit breaker on success."""
        self.failure_count = 0
        if self.state == CircuitBreakerState.HALF_OPEN:
            self.state = CircuitBreakerState.CLOSED
            self.logger.info("Circuit %s reset to CLOSED", self.name)

    async def on_failure(self) -> None:
        """Handle failure."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitBreakerState.OPEN
            self.logger.error("Circuit %s OPENED after %d failures", self.name, self.failure_count)


# --------------------------------------------------------------------------------------
# Pure helper functions (testable without I/O)
# --------------------------------------------------------------------------------------


def normalize_symbol(symbol: str) -> str:
    """Normalize symbol format (BTC/USD style)."""
    symbol = symbol.upper().strip()
    if not SYMBOL_PATTERN.match(symbol):
        raise ValueError(f"Invalid symbol format: {symbol}")
    return symbol


def normalize_trade(raw: dict, symbol: str, now: float) -> dict:
    """
    Normalize trade data from Kraken format to canonical format.

    Args:
        raw: Raw trade data from Kraken (array or dict-like)
        symbol: Trading symbol
        now: Current timestamp

    Returns:
        Normalized trade dict
    """
    side_raw = raw.get("side", raw.get(3))
    side = "buy" if side_raw == "b" else "sell"
    return {
        "type": "md.trade",
        "schema_version": "1.0",
        "exchange": "kraken",
        "symbol": normalize_symbol(symbol),
        "price": float(raw.get("price", raw.get(0, 0.0))),
        "volume": float(raw.get("volume", raw.get(1, 0.0))),
        "side": side,
        "timestamp": float(raw.get("timestamp", raw.get(2, now))),
        "received_ts": now,
        "trade_id": raw.get("trade_id", str(uuid.uuid4())[:8]),
    }


def calc_spread_bps(bid: float, ask: float) -> float:
    """Calculate spread in basis points."""
    if bid <= 0 or ask <= 0 or ask <= bid:
        return 0.0
    mid = (bid + ask) / 2.0
    return ((ask - bid) / mid) * 10000.0


def normalize_spread(raw: dict, symbol: str, now: float) -> dict:
    """
    Normalize spread data from Kraken format.

    Args:
        raw: Raw spread data from Kraken (array or dict-like)
        symbol: Trading symbol
        now: Current timestamp
    """
    bid = float(raw.get("bid", raw.get(0, 0.0)))
    ask = float(raw.get("ask", raw.get(1, 0.0)))
    return {
        "type": "md.spread",
        "schema_version": "1.0",
        "exchange": "kraken",
        "symbol": normalize_symbol(symbol),
        "bid": bid,
        "ask": ask,
        "spread_bps": calc_spread_bps(bid, ask),
        "timestamp": float(raw.get("timestamp", raw.get(2, now))),
        "received_ts": now,
        "bid_volume": float(raw.get("bid_volume", raw.get(3, 0.0))),
        "ask_volume": float(raw.get("ask_volume", raw.get(4, 0.0))),
    }


def build_stream_key(template: str, symbol: str = "", timeframe: str = "") -> str:
    """Build Redis stream key from template."""
    key = template
    if "{symbol}" in key:
        key = key.replace("{symbol}", symbol.replace("/", "-"))
    if "{tf}" in key:
        key = key.replace("{tf}", timeframe)
    return key


# --------------------------------------------------------------------------------------
# Main Data Pipeline Class
# --------------------------------------------------------------------------------------


class DataPipeline:
    """
    Production-ready data pipeline for crypto trading system.

    Handles:
    - Kraken WebSocket connections (trade, spread, book, ohlc)
    - Redis Streams publishing with compression
    - Circuit breakers for resilience
    - Health monitoring and metrics
    - Graceful shutdown
    """

    def __init__(
        self,
        cfg: DataPipelineConfig,
        redis_client: redis.Redis,
        http: aiohttp.ClientSession,
        *,
        on_metric: Optional[Callable[[str, float, dict], None]] = None,
        on_event: Optional[Callable[[dict], None]] = None,
        clock: Callable[[], float] = lambda: time.time(),
        logger: Optional[logging.Logger] = None,
    ):
        self.cfg = cfg
        self.redis = redis_client
        self.http = http
        self.clock = clock
        self.logger = logger or logging.getLogger(__name__)

        # Callbacks
        self.on_metric = on_metric or self._default_metric_handler
        self.on_event = on_event or self._default_event_handler

        # State management
        self.running = False
        self.tasks: List[asyncio.Task] = []
        self.ws_connections: Dict[str, websockets.WebSocketClientProtocol] = {}

        # Circuit breakers
        self.circuit_breakers = {
            "ws_connection": CircuitBreaker(
                "ws_connection", cfg.max_consecutive_errors, cfg.circuit_breaker_cooldown
            ),
            "redis_publish": CircuitBreaker(
                "redis_publish", cfg.max_consecutive_errors, cfg.circuit_breaker_cooldown
            ),
        }

        # Metrics
        self.metrics: Dict[str, float] = {
            "ws_restarts": 0,
            "msgs_in": 0,
            "msgs_out": 0,
            "bytes_in": 0,
            "latency_ms_p95": 0,  # placeholder; implement rolling p95 if desired
            "errors_count": 0,  # counter; not a rate
            "backfill_candles": 0,
            "last_heartbeat": 0,
        }

        # Message buffers for batching
        self.message_buffers: Dict[str, List[dict]] = {}
        self.last_flush = self.clock()
        self._flush_lock = asyncio.Lock()

    # ------------------------------------------------------------------ Callbacks

    def _default_metric_handler(self, name: str, value: float, tags: dict) -> None:
        """Default metric handler - debug logs."""
        self.logger.debug("metric name=%s value=%s tags=%s", name, value, tags)

    def _default_event_handler(self, event: dict) -> None:
        """Default event handler - info logs."""
        self.logger.info("event type=%s", event.get("type", "unknown"))

    # ------------------------------------------------------------------ Lifecycle

    async def start(self) -> None:
        """Start the data pipeline."""
        if self.running:
            return

        if self.cfg.redis_url.startswith("redis://"):
            self.logger.warning(
                "Redis URL is not TLS (redis://). For production, prefer rediss:// "
                "with a verified CA."
            )

        self.logger.info("Starting data pipeline...")
        self.running = True

        try:
            # Create consumer groups
            if self.cfg.create_consumer_groups:
                await self._create_consumer_groups()

            # Start background tasks
            self.tasks.extend(
                [
                    asyncio.create_task(self._heartbeat_task(), name="heartbeat"),
                    asyncio.create_task(self._flush_task(), name="flush"),
                    asyncio.create_task(self._metrics_task(), name="metrics"),
                ]
            )

            # Start WebSocket connections
            for pair in self.cfg.pairs:
                task = asyncio.create_task(self._ws_connection_task(pair), name=f"ws:{pair}")
                self.tasks.append(task)

            # Optional startup backfill
            if self.cfg.startup_backfill_enabled:
                await self._startup_backfill()

            self.logger.info("Data pipeline started successfully")

        except Exception as e:
            self.logger.error("Failed to start data pipeline: %s", e, exc_info=True)
            await self.stop()
            raise

    async def stop(self) -> None:
        """Stop the data pipeline gracefully."""
        if not self.running:
            return

        self.logger.info("Stopping data pipeline...")
        self.running = False

        # Close WebSocket connections
        for ws in list(self.ws_connections.values()):
            try:
                if not ws.closed:
                    await ws.close()
            except Exception:
                pass
        self.ws_connections.clear()

        # Cancel all tasks
        for task in self.tasks:
            if not task.done():
                task.cancel()

        # Wait for tasks to complete
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()

        # Flush remaining messages
        await self._flush_all_buffers()

        # Close Redis connection
        try:
            await self.redis.aclose()
        except Exception:
            pass

        self.logger.info("Data pipeline stopped")

    async def run_forever(self) -> None:
        """Run pipeline until cancelled."""
        await self.start()
        try:
            while self.running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            self.logger.info("Data pipeline cancelled")
        finally:
            await self.stop()

    # ------------------------------------------------------------------ Redis groups

    async def _create_consumer_groups(self) -> None:
        """Create Redis consumer groups idempotently."""
        streams = [
            STREAM_TRADE,
            STREAM_SPREAD,
            STREAM_BOOK,
            STREAM_CANDLES,
            STREAM_EVENTS,
        ]

        for stream_template in streams:
            if "{symbol}" in stream_template:
                for pair in self.cfg.pairs:
                    if "{tf}" in stream_template:
                        for tf in self.cfg.timeframes:
                            stream_key = build_stream_key(stream_template, pair, tf)
                            await self._ensure_consumer_group(stream_key, f"{stream_key}_group")
                    else:
                        stream_key = build_stream_key(stream_template, pair)
                        await self._ensure_consumer_group(stream_key, f"{stream_key}_group")
            else:
                await self._ensure_consumer_group(stream_template, f"{stream_template}_group")

    async def _ensure_consumer_group(self, stream: str, group: str) -> None:
        """Create consumer group if it doesn't exist."""
        try:
            await self.redis.xgroup_create(stream, group, id="0", mkstream=True)
            self.logger.debug("Created consumer group %s for stream %s", group, stream)
        except Exception as e:
            if "BUSYGROUP" in str(e):
                # Group already exists
                pass
            else:
                self.logger.warning("Failed to create consumer group %s: %s", group, e)

    # ------------------------------------------------------------------ WebSockets

    async def _ws_connection_task(self, pair: str) -> None:
        """WebSocket connection task for a trading pair."""
        reconnect_delay = 1.0
        max_delay = 60.0

        while self.running:
            try:
                await self.circuit_breakers["ws_connection"].call(self._connect_ws, pair)
                reconnect_delay = 1.0  # reset after clean exit
            except Exception as e:
                self.metrics["ws_restarts"] += 1
                self.logger.error("WebSocket connection failed for %s: %s", pair, e)
                if not self.running:
                    break
                # Deterministic backoff (no randomness to keep determinism)
                delay = min(reconnect_delay + (reconnect_delay * 0.1), max_delay)
                self.logger.warning("Kraken WS retry for %s in %.1fs...", pair, delay)
                await asyncio.sleep(delay)
                reconnect_delay *= 2.0

    async def _connect_ws(self, pair: str) -> None:
        """Connect to Kraken WebSocket for a specific pair."""
        kraken_pair = KRAKEN_PAIRS.get(pair, pair)  # e.g., "XBT/USD"
        uri = "wss://ws.kraken.com"

        self.logger.info("Kraken WS connecting for %s (%s)", pair, kraken_pair)

        async with websockets.connect(
            uri, ping_interval=self.cfg.ws_ping_interval_s, close_timeout=10
        ) as ws:
            self.ws_connections[pair] = ws

            # Subscribe to channels
            subscriptions: List[Dict[str, Any]] = [
                {"event": "subscribe", "pair": [kraken_pair], "subscription": {"name": "trade"}},
                {"event": "subscribe", "pair": [kraken_pair], "subscription": {"name": "spread"}},
                {
                    "event": "subscribe",
                    "pair": [kraken_pair],
                    "subscription": {"name": "book", "depth": 10},
                },
            ]

            # Add OHLC subscriptions for each timeframe (minutes-based)
            for tf in self.cfg.timeframes:
                interval = self._timeframe_to_kraken_interval(tf)
                if interval is not None:
                    subscriptions.append(
                        {
                            "event": "subscribe",
                            "pair": [kraken_pair],
                            "subscription": {"name": "ohlc", "interval": interval},
                        }
                    )

            # Send subscriptions
            for sub in subscriptions:
                await ws.send(json.dumps(sub, separators=(",", ":")))
                await asyncio.sleep(0.1)  # gentle rate limit

            # Message processing loop
            async for message in ws:
                await self._handle_ws_message(pair, message)

            # Connection closed
            self.logger.info("Kraken WS disconnected for %s", pair)
            # Metrics instrumentation for disconnect
            try:
                from monitoring.metrics_exporter import inc_ingestor_disconnect

                inc_ingestor_disconnect(source="kraken_ws")
            except ImportError:
                pass  # Metrics not available

            # Discord alert for disconnect
            try:
                from monitoring.discord_alerts import send_system_alert

                send_system_alert(
                    "kraken",
                    f"WebSocket disconnected for {pair}",
                    "WARN",
                    pair=pair,
                    component="data_pipeline",
                )
            except ImportError:
                pass  # Discord alerts not available
            except Exception:
                pass  # Don't fail on Discord errors

    @staticmethod
    def _timeframe_to_kraken_interval(tf: str) -> Optional[int]:
        """Convert canonical timeframe to Kraken interval (minutes)."""
        mapping = {
            "1m": 1,
            "3m": 3,
            "5m": 5,
            "15m": 15,
            "30m": 30,
            "1h": 60,
            "4h": 240,
            "1d": 1440,
        }
        return mapping.get(tf)

    # ------------------------------------------------------------------ WS message routing

    async def _handle_ws_message(self, pair: str, message: str) -> None:
        """Handle WebSocket message from Kraken."""
        start_time = self.clock()

        try:
            self.metrics["msgs_in"] += 1
            self.metrics["bytes_in"] += len(message.encode("utf-8"))
            data = json.loads(message)

            # Control messages
            if isinstance(data, dict):
                ev = data.get("event")
                if ev == "heartbeat":
                    self.metrics["last_heartbeat"] = self.clock()
                    return
                if ev == "systemStatus":
                    await self._emit_event(
                        {
                            "type": "kraken.system_status",
                            "status": data.get("status"),
                            "timestamp": self.clock(),
                        }
                    )
                    return
                if ev == "subscriptionStatus":
                    self.logger.debug("Subscription status: %s", data)
                    return

            # Data messages are arrays
            if isinstance(data, list) and len(data) >= 4:
                # channel_id = data[0]  # unused
                payload = data[1]
                channel = data[2]
                # kraken_pair = data[3]  # unused here

                if isinstance(channel, str):
                    if channel.startswith("trade"):
                        await self._handle_trades(pair, payload)
                    elif channel.startswith("spread"):
                        await self._handle_spread(pair, payload)
                    elif channel.startswith("book"):
                        await self._handle_book(pair, payload)
                    elif channel.startswith("ohlc"):
                        timeframe = self._extract_timeframe_from_channel(channel)
                        await self._handle_ohlc(pair, payload, timeframe)

        except Exception as e:
            self.metrics["errors_count"] += 1
            self.logger.error("Error handling WebSocket message: %s", e, exc_info=True)
            # Continue processing
        finally:
            # Observe latency — emit event (do NOT route via a circuit breaker)
            latency_ms = (self.clock() - start_time) * 1000.0
            if latency_ms > self.cfg.max_latency_ms:
                await self._emit_event(
                    {
                        "type": "pipeline.high_latency",
                        "latency_ms": latency_ms,
                        "pair": pair,
                        "timestamp": self.clock(),
                    }
                )

    @staticmethod
    def _extract_timeframe_from_channel(channel: str) -> str:
        """Extract timeframe from Kraken OHLC channel name ("ohlc-{minutes}")."""
        if "-" in channel:
            interval = channel.split("-")[1]
            mapping = {
                "1": "1m",
                "3": "3m",
                "5": "5m",
                "15": "15m",
                "30": "30m",
                "60": "1h",
                "240": "4h",
                "1440": "1d",
            }
            return mapping.get(interval, "1m")
        return "1m"

    # ------------------------------------------------------------------ WS payload handlers

    async def _handle_trades(self, pair: str, trades: List[Any]) -> None:
        """Handle trade data."""
        now = self.clock()
        for trade_data in trades:
            try:
                normalized_trade = normalize_trade(
                    {
                        0: trade_data[0],
                        1: trade_data[1],
                        2: trade_data[2],
                        3: trade_data[3],
                        4: trade_data[4],
                    },
                    pair,
                    now,
                )
                stream_key = build_stream_key(STREAM_TRADE, pair)
                await self._buffer_message(stream_key, normalized_trade)
            except Exception as e:
                self.logger.error("Error processing trade: %s", e, exc_info=True)
        # Yield on bursts to avoid starving other tasks
        await asyncio.sleep(0)

    async def _handle_spread(self, pair: str, spread_data: List[Any]) -> None:
        """Handle spread data."""
        now = self.clock()
        try:
            normalized_spread = normalize_spread(
                {
                    0: spread_data[0],
                    1: spread_data[1],
                    2: spread_data[2],
                    3: spread_data[3],
                    4: spread_data[4],
                },
                pair,
                now,
            )
            stream_key = build_stream_key(STREAM_SPREAD, pair)
            await self._buffer_message(stream_key, normalized_spread)
        except Exception as e:
            self.logger.error("Error processing spread: %s", e, exc_info=True)

    async def _handle_book(self, pair: str, book_data: dict) -> None:
        """Handle order book data."""
        now = self.clock()
        try:
            bids = [[float(p), float(v), float(t)] for p, v, t in book_data.get("bs", [])]
            asks = [[float(p), float(v), float(t)] for p, v, t in book_data.get("as", [])]
            normalized_book = {
                "type": "md.book",
                "schema_version": "1.0",
                "exchange": "kraken",
                "symbol": normalize_symbol(pair),
                "bids": bids,
                "asks": asks,
                "timestamp": now,
                "received_ts": now,
                "checksum": book_data.get("c"),
            }
            stream_key = build_stream_key(STREAM_BOOK, pair)
            await self._buffer_message(stream_key, normalized_book)
        except Exception as e:
            self.logger.error("Error processing book: %s", e, exc_info=True)

    async def _handle_ohlc(self, pair: str, ohlc_data: List[Any], timeframe: str) -> None:
        """Handle OHLC/candle data."""
        now = self.clock()
        try:
            # Kraken OHLC array: [time, open, high, low, close, vwap, volume, count]
            if len(ohlc_data) < 7:
                return
            normalized_ohlc = {
                "type": "md.ohlcv",
                "schema_version": "1.0",
                "exchange": "kraken",
                "symbol": normalize_symbol(pair),
                "timeframe": timeframe,
                "time": float(
                    ohlc_data[1]
                ),  # note: some WS formats use index 0 as channel; here payload index[1] is time
                "open": float(ohlc_data[2]),
                "high": float(ohlc_data[3]),
                "low": float(ohlc_data[4]),
                "close": float(ohlc_data[5]),
                "volume": float(ohlc_data[6]),
                "timestamp": now,
                "received_ts": now,
            }
            stream_key = build_stream_key(STREAM_CANDLES, pair, timeframe)
            await self._buffer_message(stream_key, normalized_ohlc)
        except Exception as e:
            self.logger.error("Error processing OHLC: %s", e, exc_info=True)

    # ------------------------------------------------------------------ Buffering / Flushing

    async def _buffer_message(self, stream_key: str, message: dict) -> None:
        """Buffer message for batch publishing."""
        if stream_key not in self.message_buffers:
            self.message_buffers[stream_key] = []
        self.message_buffers[stream_key].append(message)
        # Flush if buffer is full
        if len(self.message_buffers[stream_key]) >= self.cfg.stream_batch_size:
            await self._flush_buffer(stream_key)

    async def _flush_buffer(self, stream_key: str) -> None:
        """Flush messages from buffer to Redis."""
        if stream_key not in self.message_buffers:
            return
        messages = self.message_buffers[stream_key]
        if not messages:
            return
        try:
            await self.circuit_breakers["redis_publish"].call(
                self._publish_messages, stream_key, messages
            )
            self.metrics["msgs_out"] += len(messages)
            self.message_buffers[stream_key] = []
        except Exception as e:
            self.logger.error("Error flushing buffer for %s: %s", stream_key, e, exc_info=True)
            # Keep messages in buffer for retry

    async def _publish_messages(self, stream_key: str, messages: List[dict]) -> None:
        """Publish messages to a Redis stream."""
        pipe = self.redis.pipeline(transaction=False)
        ts_now = str(self.clock())
        current_time = self.clock()

        for message in messages:
            if self.cfg.compression_enabled:
                raw = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
                payload = base64.b64encode(gzip.compress(raw)).decode("ascii")
                message_data = {"data": payload, "compressed": "true", "timestamp": ts_now}
            else:
                message_data = {
                    "data": json.dumps(message, separators=(",", ":"), ensure_ascii=False),
                    "compressed": "false",
                    "timestamp": ts_now,
                }
            pipe.xadd(stream_key, message_data, maxlen=self.cfg.stream_maxlen, approximate=True)

        await pipe.execute()

        # Track stream lag for SLO monitoring
        try:
            from monitoring.slo_metrics import record_consumer_lag

            # Calculate lag as time since last message timestamp
            if messages:
                last_message = messages[-1]
                message_ts = last_message.get("timestamp", current_time)
                if isinstance(message_ts, str):
                    message_ts = float(message_ts)
                lag_seconds = current_time - message_ts

                # Extract stream name and consumer info
                stream_name = (
                    stream_key.split(":")[0] + ":" + stream_key.split(":")[1]
                    if ":" in stream_key
                    else stream_key
                )
                consumer_name = "data_pipeline"

                await record_consumer_lag(
                    stream=stream_name,
                    consumer=consumer_name,
                    lag_seconds=lag_seconds,
                    redis_client=self.redis,
                )
        except ImportError:
            pass  # SLO metrics not available
        except Exception as e:
            self.logger.warning(f"Failed to record stream lag: {e}")

    async def _flush_all_buffers(self) -> None:
        """Flush all message buffers."""
        async with self._flush_lock:
            for stream_key in list(self.message_buffers.keys()):
                await self._flush_buffer(stream_key)

    async def _flush_task(self) -> None:
        """Periodic buffer flushing task."""
        while self.running:
            try:
                await asyncio.sleep(1)  # every second
                if self.clock() - self.last_flush >= 1:
                    await self._flush_all_buffers()
                    self.last_flush = self.clock()
            except Exception as e:
                self.logger.error("Error in flush task: %s", e, exc_info=True)

    # ------------------------------------------------------------------ Heartbeat & Metrics

    async def _heartbeat_task(self) -> None:
        """Heartbeat task for health monitoring."""
        while self.running:
            try:
                await asyncio.sleep(30)  # every 30 seconds
                await self._emit_event(
                    {
                        "type": "pipeline.heartbeat",
                        "timestamp": self.clock(),
                        "metrics": dict(self.metrics),
                        "circuit_breakers": {
                            name: cb.state.value for name, cb in self.circuit_breakers.items()
                        },
                    }
                )
            except Exception as e:
                self.logger.error("Error in heartbeat task: %s", e, exc_info=True)

    async def _metrics_task(self) -> None:
        """Metrics collection task."""
        while self.running:
            try:
                await asyncio.sleep(10)  # every 10 seconds
                for name, value in self.metrics.items():
                    self.on_metric(name, float(value), {"component": "data_pipeline"})
            except Exception as e:
                self.logger.error("Error in metrics task: %s", e, exc_info=True)

    async def _emit_event(self, event: dict) -> None:
        """Emit event to event bus and callback."""
        try:
            stream_data = {
                "data": json.dumps(event, separators=(",", ":"), ensure_ascii=False),
                "timestamp": str(self.clock()),
            }
            await self.redis.xadd(
                STREAM_EVENTS, stream_data, maxlen=self.cfg.stream_maxlen, approximate=True
            )
            self.on_event(event)
        except Exception as e:
            self.logger.error("Error emitting event: %s", e, exc_info=True)

    # ------------------------------------------------------------------ Backfill

    async def _startup_backfill(self) -> None:
        """Perform startup backfill for OHLCV data."""
        self.logger.info("Starting backfill...")
        for pair in self.cfg.pairs:
            for timeframe in self.cfg.timeframes:
                try:
                    count = await self.backfill_ohlcv(
                        pair, timeframe, self.cfg.startup_backfill_limit
                    )
                    self.metrics["backfill_candles"] += count
                    self.logger.info("Backfilled %d candles for %s %s", count, pair, timeframe)
                    await asyncio.sleep(0.5)  # gentle rate limiting
                except Exception as e:
                    self.logger.error(
                        "Backfill failed for %s %s: %s", pair, timeframe, e, exc_info=True
                    )
        self.logger.info("Backfill completed")

    async def backfill_ohlcv(self, symbol: str, timeframe: str, limit: int) -> int:
        """
        Backfill OHLCV data from Kraken REST API.

        Args:
            symbol: Trading symbol (e.g., "BTC/USD")
            timeframe: Timeframe (1m, 5m, 15m, 30m, 1h, 4h, 1d)
            limit: Maximum number of candles to ingest

        Returns:
            Number of candles backfilled
        """
        # Convert to Kraken formats
        ws_pair = KRAKEN_PAIRS.get(symbol, symbol)  # e.g., "XBT/USD"
        rest_pair = ws_pair.replace("/", "")  # e.g., "XBTUSD"

        interval_map = {
            "1m": 1,
            "5m": 5,
            "15m": 15,
            "30m": 30,
            "1h": 60,
            "4h": 240,
            "1d": 1440,
            "1w": 10080,
            "2w": 21600,
        }
        if timeframe not in interval_map:
            self.logger.warning("Unsupported timeframe for backfill: %s", timeframe)
            return 0
        interval = interval_map[timeframe]

        try:
            url = "https://api.kraken.com/0/public/OHLC"
            params = {"pair": rest_pair, "interval": interval}

            async with self.http.get(url, params=params) as response:
                if response.status != 200:
                    raise Exception(f"HTTP {response.status}")

                data = await response.json()
                if data.get("error"):
                    raise Exception(f"Kraken API error: {data['error']}")

                result = data.get("result", {})
                ohlc_data = result.get(rest_pair, [])
                if not ohlc_data:
                    return 0

                # Process and publish candles (slice on client side)
                count = 0
                stream_key = build_stream_key(STREAM_CANDLES, symbol, timeframe)

                for ohlc in ohlc_data[-limit:]:
                    # Expected order: [time, open, high, low, close, vwap, volume, count]
                    if len(ohlc) >= 7:
                        candle = {
                            "type": "md.ohlcv",
                            "schema_version": "1.0",
                            "exchange": "kraken",
                            "symbol": normalize_symbol(symbol),
                            "timeframe": timeframe,
                            "time": float(ohlc[0]),
                            "open": float(ohlc[1]),
                            "high": float(ohlc[2]),
                            "low": float(ohlc[3]),
                            "close": float(ohlc[4]),
                            "volume": float(ohlc[6]),
                            "timestamp": self.clock(),
                            "received_ts": self.clock(),
                            "backfill": True,
                        }
                        await self._buffer_message(stream_key, candle)
                        count += 1

                # Flush buffer
                await self._flush_buffer(stream_key)
                return count

        except Exception as e:
            self.logger.error("Backfill error for %s %s: %s", symbol, timeframe, e, exc_info=True)
            return 0


# --------------------------------------------------------------------------------------
# Main execution for standalone testing
# --------------------------------------------------------------------------------------


async def main() -> None:
    """Main function for standalone execution and testing."""
    import sys

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    logger = logging.getLogger(__name__)

    # Load configuration
    try:
        config = DataPipelineConfig.from_env()
        logger.info("Configuration loaded successfully")
        logger.info("Pairs: %s", config.pairs)
        logger.info("Timeframes: %s", config.timeframes)
        logger.info("Redis URL: %s", config.redis_url)
    except Exception as e:
        logger.error("Configuration error: %s", e)
        sys.exit(1)

    # Validate required environment variables
    required_vars = ["REDIS_URL"]
    missing = [var for var in required_vars if not os.getenv(var)]
    if missing:
        logger.error("Missing required environment variables: %s", missing)
        sys.exit(1)

    # Create Redis connection using Redis Cloud client
    try:
        redis_client = await create_data_pipeline_redis_client()
        await redis_client.ping()
        logger.info("Redis Cloud connection successful")
    except Exception as e:
        logger.error("Redis Cloud connection failed: %s", e)
        sys.exit(1)

    # Create HTTP session
    async with aiohttp.ClientSession() as http:
        # Metric and event handlers for testing
        def metric_handler(name: str, value: float, tags: dict) -> None:
            logger.info("METRIC: %s=%s %s", name, value, tags)

        def event_handler(event: dict) -> None:
            logger.info("EVENT: %s - %s", event.get("type", "unknown"), event)

        # Create and start pipeline
        pipeline = DataPipeline(
            config, redis_client, http, on_metric=metric_handler, on_event=event_handler
        )

        try:
            logger.info("Starting data pipeline for 30 seconds...")
            await pipeline.start()
            await asyncio.sleep(30)

            logger.info("Final metrics:")
            for name, value in pipeline.metrics.items():
                logger.info("  %s: %s", name, value)

            logger.info("Circuit breaker states:")
            for name, cb in pipeline.circuit_breakers.items():
                logger.info("  %s: %s", name, cb.state.value)

        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        finally:
            await pipeline.stop()
            try:
                await redis_client.aclose()
            except Exception:
                pass

    logger.info("Test completed successfully")


if __name__ == "__main__":
    """
    Smoke test that can be run standalone:

    python -m agents.infrastructure.data_pipeline

    Required environment variables:
    - REDIS_URL (e.g., redis://localhost:6379 or rediss://host:port with TLS)
    - TRADING_PAIRS (optional, defaults to BTC/USD,ETH/USD)
    - TIMEFRAMES (optional, defaults to 1m,5m) from {1m,3m,5m,15m,30m,1h,4h,1d}
    """
    import sys

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger = logging.getLogger(__name__)
        logger.info("Test interrupted by user")
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error("Test failed: %s", e)
        sys.exit(1)
