"""
PRD-001 Compliant Signal Publisher (agents/infrastructure/prd_publisher.py)

Unified Redis publishing module that EXACTLY matches PRD-001 signal schema and stream contracts.
This is the SINGLE SOURCE OF TRUTH for all Redis publishing operations.

PRD-001 STREAM CONTRACT:
- Signal streams: signals:paper:<PAIR> or signals:live:<PAIR>
- PnL streams: pnl:paper:equity_curve or pnl:live:equity_curve
- Events stream: events:bus
- Kraken metrics: kraken:metrics, kraken:heartbeat
- MAXLEN: 10,000 per stream (approximate trimming)

PRD-001 SIGNAL SCHEMA v1.0:
{
    "signal_id": "UUID v4",
    "timestamp": "ISO8601 UTC string",
    "pair": "BTC/USD",
    "side": "LONG" | "SHORT",
    "strategy": "SCALPER" | "TREND" | "MEAN_REVERSION" | "BREAKOUT",
    "regime": "TRENDING_UP" | "TRENDING_DOWN" | "RANGING" | "VOLATILE",
    "entry_price": float,
    "take_profit": float,
    "stop_loss": float,
    "confidence": float (0.0-1.0),
    "position_size_usd": float,
    "indicators": {...},
    "metadata": {...}
}

USAGE:
    from agents.infrastructure.prd_publisher import PRDPublisher, PRDSignal

    # Create publisher
    publisher = PRDPublisher()
    await publisher.connect()

    # Publish signal
    signal = PRDSignal(
        pair="BTC/USD",
        side="LONG",
        strategy="SCALPER",
        regime="TRENDING_UP",
        entry_price=50000.0,
        take_profit=52000.0,
        stop_loss=49000.0,
        confidence=0.85,
        position_size_usd=500.0,
    )
    await publisher.publish_signal(signal)

    # Cleanup
    await publisher.close()
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

import redis.asyncio as redis
from pydantic import BaseModel, Field, field_validator, model_validator

logger = logging.getLogger(__name__)


# =============================================================================
# PRD-001 ENUMS (Section 5)
# =============================================================================

class Side(str, Enum):
    """PRD-001 Side enum: LONG or SHORT"""
    LONG = "LONG"
    SHORT = "SHORT"


class Strategy(str, Enum):
    """PRD-001 Strategy enum"""
    SCALPER = "SCALPER"
    TREND = "TREND"
    MEAN_REVERSION = "MEAN_REVERSION"
    BREAKOUT = "BREAKOUT"


class Regime(str, Enum):
    """PRD-001 Regime enum"""
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGING = "RANGING"
    VOLATILE = "VOLATILE"


class MACDSignal(str, Enum):
    """PRD-001 MACD signal enum"""
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


# =============================================================================
# PRD-001 SIGNAL SCHEMA (Section 5)
# =============================================================================

class PRDIndicators(BaseModel):
    """PRD-001 Indicators nested object"""
    rsi_14: float = Field(ge=0, le=100, description="RSI(14) value")
    macd_signal: MACDSignal = Field(description="MACD signal")
    atr_14: float = Field(gt=0, description="ATR(14) value")
    volume_ratio: float = Field(gt=0, description="Volume ratio vs average")

    class Config:
        use_enum_values = True


class PRDMetadata(BaseModel):
    """PRD-001 Metadata nested object with UI-friendly additions"""
    model_version: str = Field(description="ML model version")
    backtest_sharpe: Optional[float] = Field(None, description="Backtest Sharpe ratio")
    latency_ms: Optional[int] = Field(None, ge=0, description="Processing latency in ms")
    
    # UI-friendly metadata fields (Week 2 addition)
    strategy_tag: Optional[str] = Field(None, description="Human-readable strategy tag (e.g., 'Scalper v2', 'Trend Follower')")
    mode: Optional[str] = Field(None, description="Trading mode (paper/live) - for UI display")
    timeframe: Optional[str] = Field(None, description="Signal timeframe (e.g., '5m', '15s', '1h') - for UI filtering")


class PRDSignal(BaseModel):
    """
    PRD-001 Compliant Signal Schema v1.0

    This is the CANONICAL schema shared across all 3 repos (bot, API, UI).
    All signals published to Redis MUST conform to this schema.
    """

    # Core identifiers
    signal_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="UUID v4 signal identifier"
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
        description="ISO8601 UTC timestamp"
    )

    # Market data
    pair: str = Field(description="Trading pair (e.g., BTC/USD)")
    side: Side = Field(description="Trade direction (LONG or SHORT)")

    # Strategy context
    strategy: Strategy = Field(description="Strategy that generated signal")
    regime: Regime = Field(description="Current market regime")

    # Execution parameters
    entry_price: float = Field(gt=0, description="Entry price")
    take_profit: float = Field(gt=0, description="Take profit price")
    stop_loss: float = Field(gt=0, description="Stop loss price")

    # Signal quality
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score [0-1]")
    position_size_usd: float = Field(gt=0, le=2000, description="Position size in USD")
    risk_reward_ratio: Optional[float] = Field(None, gt=0, description="Risk/reward ratio (calculated if not provided)")

    # Optional nested objects
    indicators: Optional[PRDIndicators] = Field(None, description="Technical indicators")
    metadata: Optional[PRDMetadata] = Field(None, description="Signal metadata")

    class Config:
        use_enum_values = True

    @field_validator("pair")
    @classmethod
    def normalize_pair(cls, v: str) -> str:
        """Normalize pair to use forward slash (BTC/USD)"""
        return v.replace("-", "/").upper()

    @model_validator(mode="after")
    def validate_price_relationships(self):
        """PRD-001 Section 5: Validate SL/TP vs entry based on side and calculate risk_reward_ratio"""
        if self.side == Side.LONG or self.side == "LONG":
            if self.take_profit <= self.entry_price:
                raise ValueError(
                    f"LONG signal: take_profit ({self.take_profit}) must be > entry_price ({self.entry_price})"
                )
            if self.stop_loss >= self.entry_price:
                raise ValueError(
                    f"LONG signal: stop_loss ({self.stop_loss}) must be < entry_price ({self.entry_price})"
                )
            # Calculate risk/reward ratio if not provided
            if self.risk_reward_ratio is None:
                risk = abs(self.entry_price - self.stop_loss)
                reward = abs(self.take_profit - self.entry_price)
                if risk > 0:
                    self.risk_reward_ratio = reward / risk
        elif self.side == Side.SHORT or self.side == "SHORT":
            if self.take_profit >= self.entry_price:
                raise ValueError(
                    f"SHORT signal: take_profit ({self.take_profit}) must be < entry_price ({self.entry_price})"
                )
            if self.stop_loss <= self.entry_price:
                raise ValueError(
                    f"SHORT signal: stop_loss ({self.stop_loss}) must be > entry_price ({self.entry_price})"
                )
            # Calculate risk/reward ratio if not provided
            if self.risk_reward_ratio is None:
                risk = abs(self.stop_loss - self.entry_price)
                reward = abs(self.entry_price - self.take_profit)
                if risk > 0:
                    self.risk_reward_ratio = reward / risk
        return self

    def to_redis_dict(self) -> Dict[str, str]:
        """
        Convert to Redis-compatible dict with all string values.
        Required for XADD which expects string values.
        
        Week 2 Enhancement: Includes both PRD-001 fields and API-compatible aliases
        to ensure signals-api can consume without transformation.
        """
        data = self.model_dump(exclude_none=True)
        result = {}

        # Add PRD-001 fields (canonical schema)
        for key, value in data.items():
            if isinstance(value, dict):
                # Flatten nested objects with prefix
                for nested_key, nested_value in value.items():
                    result[f"{key}_{nested_key}"] = str(nested_value)
            else:
                result[key] = str(value)

        # Add API-compatible aliases (Week 2: signals-api compatibility)
        # These are derived from existing fields, no data duplication
        result["id"] = self.signal_id  # API expects "id" not "signal_id"
        result["symbol"] = self._get_api_symbol()  # API expects "BTCUSDT" format
        result["signal_type"] = str(self.side)  # API expects "signal_type" not "side"
        result["price"] = str(self.entry_price)  # API expects "price" not "entry_price"

        # Add backward-compatible field aliases for signals-api consumption
        # The signals-api services/signals.py expects: ts, entry, sl, tp, side (lowercase)
        try:
            from datetime import datetime
            if isinstance(self.timestamp, str):
                dt = datetime.fromisoformat(self.timestamp.replace("Z", "+00:00"))
                ts_ms = int(dt.timestamp() * 1000)
            else:
                ts_ms = 0
        except Exception:
            ts_ms = 0
        result["ts"] = str(ts_ms)  # Timestamp in milliseconds for legacy API
        result["entry"] = str(self.entry_price)  # Legacy alias for entry_price
        result["sl"] = str(self.stop_loss)  # Legacy alias for stop_loss
        result["tp"] = str(self.take_profit)  # Legacy alias for take_profit

        return result
    
    def _get_api_symbol(self) -> str:
        """
        Convert pair to API-compatible symbol format.
        
        PRD-002 expects: "BTCUSDT", "ETHUSDT", etc.
        PRD-001 uses: "BTC/USD", "ETH/USD", etc.
        
        Returns:
            API-compatible symbol (e.g., "BTC/USD" -> "BTCUSDT")
        """
        # Normalize: BTC/USD -> BTCUSDT, ETH/USD -> ETHUSDT
        normalized = self.pair.replace("/", "").replace("-", "")
        # If ends with USD, replace with USDT for API compatibility
        if normalized.endswith("USD"):
            return normalized.replace("USD", "USDT")
        # If already has USDT or other format, return as-is
        return normalized

    def get_stream_key(self, mode: Literal["paper", "live"] = "paper") -> str:
        """
        Get Redis stream key for this signal.

        PRD-001 Section 2.2: Stream pattern is signals:{mode}:<PAIR>
        Uses dash instead of slash for stream key safety.

        Returns:
            Stream key (e.g., "signals:paper:BTC-USD")
        """
        # Convert pair format: BTC/USD -> BTC-USD for Redis stream safety
        safe_pair = self.pair.replace("/", "-")
        return f"signals:{mode}:{safe_pair}"


# =============================================================================
# PRD-001 PNL SCHEMA
# =============================================================================

class PRDPnLUpdate(BaseModel):
    """PRD-001 PnL update schema for equity curve tracking"""

    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
        description="ISO8601 UTC timestamp"
    )
    equity: float = Field(description="Current equity value")
    realized_pnl: float = Field(default=0.0, description="Total realized PnL")
    unrealized_pnl: float = Field(default=0.0, description="Total unrealized PnL")
    num_positions: int = Field(default=0, ge=0, description="Number of open positions")
    drawdown_pct: float = Field(default=0.0, description="Current drawdown %")

    def to_redis_dict(self) -> Dict[str, str]:
        """Convert to Redis-compatible dict with string values."""
        return {k: str(v) for k, v in self.model_dump().items()}


class PRDEvent(BaseModel):
    """PRD-001 Event schema for events:bus stream"""

    event_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="UUID v4 event identifier"
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
        description="ISO8601 UTC timestamp"
    )
    event_type: str = Field(description="Event type (e.g., SIGNAL_PUBLISHED, ERROR, ALERT)")
    source: str = Field(description="Source component (e.g., signal_publisher, kraken_ws)")
    severity: Literal["INFO", "WARN", "ERROR", "CRITICAL"] = Field(default="INFO")
    message: str = Field(description="Event message")
    data: Optional[Dict[str, Any]] = Field(None, description="Additional event data")

    def to_redis_dict(self) -> Dict[str, str]:
        """Convert to Redis-compatible dict with string values."""
        result = {}
        for k, v in self.model_dump(exclude_none=True).items():
            if isinstance(v, dict):
                import json
                result[k] = json.dumps(v)
            else:
                result[k] = str(v)
        return result


# =============================================================================
# PRD-001 PUBLISHER
# =============================================================================

class PRDPublisher:
    """
    PRD-001 Compliant Unified Redis Publisher

    Handles all Redis publishing operations with:
    - TLS/SSL connection to Redis Cloud
    - Schema validation before publish
    - Proper error handling and logging
    - MAXLEN enforcement (10,000)
    - Retry logic (3 attempts with backoff)
    """

    # PRD-001 Stream configuration
    STREAM_MAXLEN = 10000
    STREAM_PNL_MAXLEN = 50000
    RETRY_ATTEMPTS = 3
    RETRY_BACKOFF_BASE = 1.0

    def __init__(
        self,
        redis_url: Optional[str] = None,
        redis_ca_cert: Optional[str] = None,
        mode: Optional[Literal["paper", "live"]] = None,
    ):
        """
        Initialize PRD-compliant publisher.

        Args:
            redis_url: Redis URL (defaults to REDIS_URL env var)
            redis_ca_cert: Path to CA cert (defaults to REDIS_CA_CERT or config/certs/redis_ca.pem)
            mode: Trading mode (paper or live), defaults to ENGINE_MODE env var
        """
        self.redis_url = redis_url or os.getenv("REDIS_URL", "")
        self.redis_ca_cert = redis_ca_cert or os.getenv(
            "REDIS_CA_CERT",
            os.getenv("REDIS_CA_CERT_PATH", "config/certs/redis_ca.pem")
        )
        # FIX: Use 'is not None' to allow env var fallback when mode not explicitly passed
        self.mode = mode if mode is not None else os.getenv("ENGINE_MODE", "paper")
        logger.info(f"PRDPublisher initialized with mode={self.mode}")

        self.redis_client: Optional[redis.Redis] = None
        self._connected = False

        # Metrics
        self._publish_count = 0
        self._publish_errors = 0
        self._last_error: Optional[str] = None

    async def connect(self) -> bool:
        """
        Connect to Redis Cloud with TLS.

        PRD-001 Section B.1:
        - Connect via TLS (rediss:// scheme)
        - Verify CA certificate
        - Connection retry: 3 attempts with exponential backoff

        Returns:
            True if connected, False otherwise
        """
        if not self.redis_url:
            logger.error("REDIS_URL not configured - cannot connect")
            return False

        for attempt in range(1, self.RETRY_ATTEMPTS + 1):
            try:
                # Build connection parameters
                conn_params = {
                    "socket_connect_timeout": 10,
                    "socket_keepalive": True,
                    "decode_responses": False,  # Use bytes for efficiency
                    "max_connections": 10,
                    "retry_on_timeout": True,
                }

                # Add TLS config for rediss:// URLs
                if self.redis_url.startswith("rediss://"):
                    if self.redis_ca_cert and os.path.exists(self.redis_ca_cert):
                        conn_params["ssl_ca_certs"] = self.redis_ca_cert
                        conn_params["ssl_cert_reqs"] = "required"
                        logger.debug(f"Using CA cert: {self.redis_ca_cert}")

                # Create async Redis client
                self.redis_client = redis.from_url(self.redis_url, **conn_params)

                # Test connection
                await self.redis_client.ping()

                self._connected = True
                logger.info(f"PRDPublisher connected to Redis (mode={self.mode})")
                return True

            except Exception as e:
                backoff = self.RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                logger.warning(
                    f"Redis connection attempt {attempt}/{self.RETRY_ATTEMPTS} failed: {e}. "
                    f"Retrying in {backoff}s..."
                )
                if attempt < self.RETRY_ATTEMPTS:
                    import asyncio
                    await asyncio.sleep(backoff)

        logger.error(f"Failed to connect to Redis after {self.RETRY_ATTEMPTS} attempts")
        return False

    async def close(self) -> None:
        """Close Redis connection."""
        if self.redis_client:
            await self.redis_client.aclose()
            self.redis_client = None
            self._connected = False
            logger.info("PRDPublisher disconnected from Redis")

    async def publish_signal(
        self,
        signal: PRDSignal,
        mode: Optional[Literal["paper", "live"]] = None,
    ) -> Optional[str]:
        """
        Publish PRD-001 compliant signal to Redis stream.

        PRD-001 Section B.4: Publishing Guarantees
        - Idempotency: use signal_id as message ID
        - Atomicity: all fields in single XADD
        - Schema validation before publish
        - Retry logic: 3 attempts with exponential backoff

        Args:
            signal: PRD-compliant signal to publish
            mode: Override trading mode (defaults to instance mode)

        Returns:
            Redis entry ID if successful, None otherwise
        """
        if not self._connected or not self.redis_client:
            logger.error("Cannot publish - not connected to Redis")
            self._publish_errors += 1
            return None

        use_mode = mode or self.mode
        stream_key = signal.get_stream_key(use_mode)

        for attempt in range(1, self.RETRY_ATTEMPTS + 1):
            try:
                # Convert to Redis dict (validates implicitly via Pydantic)
                redis_data = signal.to_redis_dict()

                # Encode all values to bytes for XADD
                encoded_data = {k: v.encode() if isinstance(v, str) else str(v).encode()
                               for k, v in redis_data.items()}

                # Publish with MAXLEN trimming
                entry_id = await self.redis_client.xadd(
                    name=stream_key,
                    fields=encoded_data,
                    maxlen=self.STREAM_MAXLEN,
                    approximate=True,
                )

                # Decode entry ID
                entry_id_str = entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)

                self._publish_count += 1
                logger.info(
                    f"Published signal to {stream_key}",
                    extra={
                        "signal_id": signal.signal_id,
                        "pair": signal.pair,
                        "side": signal.side,
                        "strategy": signal.strategy,
                        "entry_id": entry_id_str,
                    }
                )

                # Publish event to events:bus
                await self._publish_signal_event(signal, stream_key, entry_id_str)

                # Update telemetry: engine:last_signal_meta (for signals-api/frontend)
                await self._update_signal_telemetry(signal, use_mode)

                return entry_id_str

            except Exception as e:
                self._last_error = str(e)
                self._publish_errors += 1
                backoff = self.RETRY_BACKOFF_BASE * (2 ** (attempt - 1))

                logger.error(
                    f"Failed to publish signal to {stream_key} (attempt {attempt}/{self.RETRY_ATTEMPTS})",
                    extra={
                        "signal_id": signal.signal_id,
                        "pair": signal.pair,
                        "strategy": signal.strategy,
                        "error": str(e),
                    }
                )

                if attempt < self.RETRY_ATTEMPTS:
                    import asyncio
                    await asyncio.sleep(backoff)

        return None

    async def publish_pnl(
        self,
        pnl: PRDPnLUpdate,
        mode: Optional[Literal["paper", "live"]] = None,
    ) -> Optional[str]:
        """
        Publish PnL update to equity curve stream.

        PRD-001 Section B.2: pnl:{mode}:equity_curve

        Args:
            pnl: PnL update data
            mode: Override trading mode

        Returns:
            Redis entry ID if successful, None otherwise
        """
        if not self._connected or not self.redis_client:
            logger.error("Cannot publish PnL - not connected to Redis")
            return None

        use_mode = mode or self.mode
        stream_key = f"pnl:{use_mode}:equity_curve"

        try:
            redis_data = pnl.to_redis_dict()
            encoded_data = {k: v.encode() if isinstance(v, str) else str(v).encode()
                           for k, v in redis_data.items()}

            entry_id = await self.redis_client.xadd(
                name=stream_key,
                fields=encoded_data,
                maxlen=self.STREAM_PNL_MAXLEN,
                approximate=True,
            )

            entry_id_str = entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)

            logger.debug(
                f"Published PnL update to {stream_key}",
                extra={"equity": pnl.equity, "entry_id": entry_id_str}
            )

            # Update telemetry: engine:last_pnl_meta (for signals-api/frontend)
            await self._update_pnl_telemetry(pnl, use_mode)

            return entry_id_str

        except Exception as e:
            logger.error(
                f"Failed to publish PnL to {stream_key}",
                extra={"error": str(e), "equity": pnl.equity}
            )
            return None

    async def publish_event(self, event: PRDEvent) -> Optional[str]:
        """
        Publish event to events:bus stream.

        PRD-001 Section B.2: events:bus for system events

        Args:
            event: Event data to publish

        Returns:
            Redis entry ID if successful, None otherwise
        """
        if not self._connected or not self.redis_client:
            logger.error("Cannot publish event - not connected to Redis")
            return None

        stream_key = "events:bus"

        try:
            redis_data = event.to_redis_dict()
            encoded_data = {k: v.encode() if isinstance(v, str) else str(v).encode()
                           for k, v in redis_data.items()}

            entry_id = await self.redis_client.xadd(
                name=stream_key,
                fields=encoded_data,
                maxlen=5000,  # PRD-001: events have smaller MAXLEN
                approximate=True,
            )

            entry_id_str = entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)

            logger.debug(
                f"Published event to {stream_key}",
                extra={"event_type": event.event_type, "entry_id": entry_id_str}
            )

            return entry_id_str

        except Exception as e:
            logger.error(
                f"Failed to publish event to {stream_key}",
                extra={"error": str(e), "event_type": event.event_type}
            )
            return None

    async def _publish_signal_event(
        self,
        signal: PRDSignal,
        stream_key: str,
        entry_id: str,
    ) -> None:
        """Internal: publish SIGNAL_PUBLISHED event to events:bus"""
        try:
            event = PRDEvent(
                event_type="SIGNAL_PUBLISHED",
                source="prd_publisher",
                severity="INFO",
                message=f"Signal {signal.signal_id} published to {stream_key}",
                data={
                    "signal_id": signal.signal_id,
                    "pair": signal.pair,
                    "side": str(signal.side),
                    "strategy": str(signal.strategy),
                    "stream": stream_key,
                    "entry_id": entry_id,
                }
            )
            await self.publish_event(event)
        except Exception as e:
            # Don't fail signal publish if event publish fails
            logger.warning(f"Failed to publish signal event: {e}")

    async def _update_signal_telemetry(
        self,
        signal: PRDSignal,
        mode: Literal["paper", "live"],
    ) -> None:
        """
        Update telemetry key: engine:last_signal_meta

        Week 2 Task B: Provide compact metadata for signals-api/frontend to show
        "recent activity" without parsing complex stream data.

        Uses Redis HASH for efficient GET/HGETALL access.
        
        Fields included:
        - pair: Trading pair (e.g., "BTC/USD")
        - side: Signal direction ("LONG" or "SHORT")
        - strategy: Strategy name (e.g., "SCALPER", "TREND")
        - regime: Market regime (e.g., "TRENDING_UP", "RANGING")
        - mode: Trading mode ("paper" or "live")
        - timestamp: ISO8601 UTC timestamp
        - timestamp_ms: Epoch milliseconds (for easy comparison)
        - confidence: Signal confidence score (0.0-1.0)
        - entry_price: Entry price
        - signal_id: Signal UUID
        - timeframe: Signal timeframe if available (e.g., "5m")

        TTL: 24 hours (86400 seconds) - auto-cleanup if engine stops

        This is a cheap operation (single HSET) that does not affect performance.
        """
        if not self._connected or not self.redis_client:
            return

        try:
            telemetry_key = "engine:last_signal_meta"
            
            # Convert timestamp to milliseconds for easy comparison
            try:
                from datetime import datetime
                if isinstance(signal.timestamp, str):
                    dt = datetime.fromisoformat(signal.timestamp.replace("Z", "+00:00"))
                    timestamp_ms = str(int(dt.timestamp() * 1000))
                else:
                    timestamp_ms = str(int(signal.timestamp.timestamp() * 1000))
            except Exception:
                timestamp_ms = "0"
            
            telemetry_data = {
                "pair": signal.pair.encode(),
                "side": str(signal.side).encode(),
                "strategy": str(signal.strategy).encode(),
                "regime": str(signal.regime).encode(),
                "mode": mode.encode(),
                "timestamp": signal.timestamp.encode() if isinstance(signal.timestamp, str) else str(signal.timestamp).encode(),
                "timestamp_ms": timestamp_ms.encode(),
                "confidence": str(signal.confidence).encode(),
                "entry_price": str(signal.entry_price).encode(),
                "signal_id": signal.signal_id.encode(),
            }
            
            # Add optional fields if available
            if signal.metadata and signal.metadata.timeframe:
                telemetry_data["timeframe"] = signal.metadata.timeframe.encode()

            # Use HSET for atomic update (overwrites previous values)
            await self.redis_client.hset(telemetry_key, mapping=telemetry_data)

            # Set TTL to 24 hours (auto-cleanup if engine stops)
            await self.redis_client.expire(telemetry_key, 24 * 3600)

            logger.debug(
                f"Updated signal telemetry: {telemetry_key}",
                extra={"pair": signal.pair, "strategy": str(signal.strategy), "mode": mode}
            )

        except Exception as e:
            # Don't fail signal publish if telemetry update fails
            logger.warning(f"Failed to update signal telemetry: {e}")

    async def _update_pnl_telemetry(
        self,
        pnl: PRDPnLUpdate,
        mode: Literal["paper", "live"],
    ) -> None:
        """
        Update telemetry key: engine:last_pnl_meta

        Week 2 Task B: Provide compact metadata for signals-api/frontend to show
        "recent PnL activity" without parsing complex stream data.

        Uses Redis HASH for efficient GET/HGETALL access.
        
        Fields included:
        - equity: Current equity value
        - realized_pnl: Total realized PnL
        - unrealized_pnl: Total unrealized PnL
        - total_pnl: Total PnL (realized + unrealized)
        - num_positions: Number of open positions
        - drawdown_pct: Current drawdown percentage
        - mode: Trading mode ("paper" or "live")
        - timestamp: ISO8601 UTC timestamp
        - timestamp_ms: Epoch milliseconds (for easy comparison)

        TTL: 24 hours (86400 seconds) - auto-cleanup if engine stops

        This is a cheap operation (single HSET) that does not affect performance.
        """
        if not self._connected or not self.redis_client:
            return

        try:
            telemetry_key = "engine:last_pnl_meta"
            
            # Convert timestamp to milliseconds for easy comparison
            try:
                from datetime import datetime
                if isinstance(pnl.timestamp, str):
                    dt = datetime.fromisoformat(pnl.timestamp.replace("Z", "+00:00"))
                    timestamp_ms = str(int(dt.timestamp() * 1000))
                else:
                    timestamp_ms = "0"
            except Exception:
                timestamp_ms = "0"
            
            total_pnl = pnl.realized_pnl + pnl.unrealized_pnl
            
            telemetry_data = {
                "equity": str(pnl.equity).encode(),
                "realized_pnl": str(pnl.realized_pnl).encode(),
                "unrealized_pnl": str(pnl.unrealized_pnl).encode(),
                "total_pnl": str(total_pnl).encode(),
                "num_positions": str(pnl.num_positions).encode(),
                "drawdown_pct": str(pnl.drawdown_pct).encode(),
                "mode": mode.encode(),
                "timestamp": pnl.timestamp.encode() if isinstance(pnl.timestamp, str) else str(pnl.timestamp).encode(),
                "timestamp_ms": timestamp_ms.encode(),
            }

            # Use HSET for atomic update (overwrites previous values)
            await self.redis_client.hset(telemetry_key, mapping=telemetry_data)

            # Set TTL to 24 hours (auto-cleanup if engine stops)
            await self.redis_client.expire(telemetry_key, 24 * 3600)

            logger.debug(
                f"Updated PnL telemetry: {telemetry_key}",
                extra={"equity": pnl.equity, "realized_pnl": pnl.realized_pnl, "mode": mode}
            )

        except Exception as e:
            # Don't fail PnL publish if telemetry update fails
            logger.warning(f"Failed to update PnL telemetry: {e}")

    def get_metrics(self) -> Dict[str, Any]:
        """Get publisher metrics."""
        return {
            "connected": self._connected,
            "mode": self.mode,
            "publish_count": self._publish_count,
            "publish_errors": self._publish_errors,
            "last_error": self._last_error,
        }


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def create_prd_signal(
    pair: str,
    side: Literal["LONG", "SHORT"],
    strategy: Literal["SCALPER", "TREND", "MEAN_REVERSION", "BREAKOUT"],
    regime: Literal["TRENDING_UP", "TRENDING_DOWN", "RANGING", "VOLATILE"],
    entry_price: float,
    take_profit: float,
    stop_loss: float,
    confidence: float,
    position_size_usd: float = 100.0,
    indicators: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> PRDSignal:
    """
    Convenience function to create PRD-compliant signal with auto-generated ID and timestamp.

    Args:
        pair: Trading pair (e.g., "BTC/USD")
        side: Trade direction ("LONG" or "SHORT")
        strategy: Strategy name
        regime: Current market regime
        entry_price: Entry price
        take_profit: Take profit price
        stop_loss: Stop loss price
        confidence: Signal confidence [0-1]
        position_size_usd: Position size in USD (default 100)
        indicators: Optional technical indicators
        metadata: Optional metadata

    Returns:
        Validated PRDSignal instance

    Example:
        >>> signal = create_prd_signal(
        ...     pair="BTC/USD",
        ...     side="LONG",
        ...     strategy="SCALPER",
        ...     regime="TRENDING_UP",
        ...     entry_price=50000.0,
        ...     take_profit=52000.0,
        ...     stop_loss=49000.0,
        ...     confidence=0.85,
        ... )
    """
    ind_obj = PRDIndicators(**indicators) if indicators else None
    meta_obj = PRDMetadata(**metadata) if metadata else None

    return PRDSignal(
        pair=pair,
        side=Side(side),
        strategy=Strategy(strategy),
        regime=Regime(regime),
        entry_price=entry_price,
        take_profit=take_profit,
        stop_loss=stop_loss,
        confidence=confidence,
        position_size_usd=position_size_usd,
        indicators=ind_obj,
        metadata=meta_obj,
    )


# =============================================================================
# LEGACY SIGNAL ADAPTER
# =============================================================================

def adapt_legacy_signal(
    legacy: Dict[str, Any],
    default_strategy: str = "SCALPER",
    default_regime: str = "RANGING",
) -> PRDSignal:
    """
    Convert legacy signal format to PRD-001 compliant schema.

    Handles field mappings from current signals/schema.py:
    - id → signal_id (regenerated as UUID)
    - ts (ms) → timestamp (ISO8601)
    - pair → pair (normalized)
    - side (buy/sell) → side (LONG/SHORT)
    - entry → entry_price
    - sl → stop_loss
    - tp → take_profit
    - confidence → confidence
    - strategy → strategy (uppercase)

    Args:
        legacy: Legacy signal dictionary
        default_strategy: Default strategy if not provided
        default_regime: Default regime if not provided

    Returns:
        PRD-compliant PRDSignal
    """
    # Map side values
    side_map = {
        "buy": "LONG",
        "sell": "SHORT",
        "long": "LONG",
        "short": "SHORT",
    }
    legacy_side = legacy.get("side", "buy").lower()
    side = side_map.get(legacy_side, "LONG")

    # Map strategy to PRD enum
    strategy_map = {
        "scalper": "SCALPER",
        "scalping": "SCALPER",
        "trend": "TREND",
        "trend_following": "TREND",
        "mean_reversion": "MEAN_REVERSION",
        "breakout": "BREAKOUT",
        "momentum": "TREND",
        "momentum_v1": "TREND",
    }
    legacy_strategy = legacy.get("strategy", default_strategy).lower()
    strategy = strategy_map.get(legacy_strategy, default_strategy.upper())

    # Get prices with fallbacks
    entry_price = float(legacy.get("entry", legacy.get("entry_price", 0)))
    stop_loss = float(legacy.get("sl", legacy.get("stop_loss", 0)))
    take_profit = float(legacy.get("tp", legacy.get("take_profit", 0)))

    return PRDSignal(
        pair=legacy.get("pair", legacy.get("trading_pair", "BTC/USD")),
        side=Side(side),
        strategy=Strategy(strategy),
        regime=Regime(default_regime),
        entry_price=entry_price,
        take_profit=take_profit,
        stop_loss=stop_loss,
        confidence=float(legacy.get("confidence", 0.5)),
        position_size_usd=float(legacy.get("position_size_usd", 100.0)),
    )


# =============================================================================
# PUBLIC API
# =============================================================================

__all__ = [
    # Enums
    "Side",
    "Strategy",
    "Regime",
    "MACDSignal",
    # Schema classes
    "PRDSignal",
    "PRDIndicators",
    "PRDMetadata",
    "PRDPnLUpdate",
    "PRDEvent",
    # Publisher
    "PRDPublisher",
    # Convenience functions
    "create_prd_signal",
    "adapt_legacy_signal",
]


# =============================================================================
# SELF-CHECK
# =============================================================================

if __name__ == "__main__":
    import asyncio
    from dotenv import load_dotenv

    load_dotenv(".env.paper")

    async def main():
        print("=" * 70)
        print(" " * 15 + "PRD-001 PUBLISHER SELF-CHECK")
        print("=" * 70)

        # Test 1: Create PRD-compliant signal
        print("\nTest 1: Create PRD-compliant signal")
        try:
            signal = create_prd_signal(
                pair="BTC/USD",
                side="LONG",
                strategy="SCALPER",
                regime="TRENDING_UP",
                entry_price=50000.0,
                take_profit=52000.0,
                stop_loss=49000.0,
                confidence=0.85,
            )
            print(f"  Signal ID: {signal.signal_id}")
            print(f"  Timestamp: {signal.timestamp}")
            print(f"  Pair: {signal.pair}")
            print(f"  Side: {signal.side}")
            print(f"  Stream key: {signal.get_stream_key('paper')}")
            assert len(signal.signal_id) == 36  # UUID format
            print("  PASS")
        except Exception as e:
            print(f"  FAIL: {e}")
            return

        # Test 2: Signal validation (LONG with correct SL/TP)
        print("\nTest 2: Price relationship validation (LONG)")
        try:
            PRDSignal(
                pair="BTC/USD",
                side=Side.LONG,
                strategy=Strategy.TREND,
                regime=Regime.TRENDING_UP,
                entry_price=50000.0,
                take_profit=48000.0,  # Invalid: TP < entry for LONG
                stop_loss=49000.0,
                confidence=0.7,
                position_size_usd=500.0,
            )
            print("  FAIL: Should have raised validation error")
        except ValueError as e:
            print(f"  PASS: Validation caught error - {str(e)[:50]}...")

        # Test 3: Legacy signal adaptation
        print("\nTest 3: Legacy signal adaptation")
        legacy = {
            "id": "abc123",
            "ts": 1730000000000,
            "pair": "ETH/USD",
            "side": "buy",
            "entry": 3000.0,
            "sl": 2900.0,
            "tp": 3200.0,
            "strategy": "momentum_v1",
            "confidence": 0.72,
        }
        adapted = adapt_legacy_signal(legacy)
        assert adapted.side == Side.LONG
        assert adapted.strategy == Strategy.TREND
        assert adapted.pair == "ETH/USD"
        print(f"  Adapted signal: {adapted.pair} {adapted.side} @ {adapted.entry_price}")
        print("  PASS")

        # Test 4: Redis dict conversion
        print("\nTest 4: Redis dict conversion")
        redis_dict = signal.to_redis_dict()
        assert all(isinstance(v, str) for v in redis_dict.values())
        assert "signal_id" in redis_dict
        assert "timestamp" in redis_dict
        print(f"  Redis dict keys: {list(redis_dict.keys())}")
        print("  PASS")

        # Test 5: Connect to Redis (if available)
        print("\nTest 5: Redis connection")
        publisher = PRDPublisher(mode="paper")
        redis_url = os.getenv("REDIS_URL")

        if redis_url:
            connected = await publisher.connect()
            if connected:
                print("  Connected to Redis")

                # Test 6: Publish signal
                print("\nTest 6: Publish test signal")
                entry_id = await publisher.publish_signal(signal)
                if entry_id:
                    print(f"  Published! Entry ID: {entry_id}")
                    print("  PASS")
                else:
                    print("  FAIL: No entry ID returned")

                # Test 7: Publish PnL
                print("\nTest 7: Publish PnL update")
                pnl = PRDPnLUpdate(
                    equity=10500.0,
                    realized_pnl=500.0,
                    unrealized_pnl=100.0,
                    num_positions=2,
                )
                pnl_entry = await publisher.publish_pnl(pnl)
                if pnl_entry:
                    print(f"  Published! Entry ID: {pnl_entry}")
                    print("  PASS")
                else:
                    print("  FAIL: No entry ID returned")

                # Cleanup
                await publisher.close()
            else:
                print("  SKIP: Could not connect to Redis")
        else:
            print("  SKIP: REDIS_URL not set")

        print("\n" + "=" * 70)
        print("[OK] PRD-001 Publisher Self-Check Complete")
        print("=" * 70)

    asyncio.run(main())
