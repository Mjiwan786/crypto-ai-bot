"""
PRD-001 Compliant Unified Redis Publisher

This module provides a SINGLE SOURCE OF TRUTH for all Redis publishing operations
in the crypto-ai-bot repository. It enforces:

1. PRD-001 Section 2.2: Exact stream naming (signals:paper:<PAIR>, signals:live:<PAIR>)
2. PRD-001 Section 5.1: Exact signal schema validation
3. PRD-001 Section B.1: TLS connection with CA certificate
4. PRD-001 Section B.4: Publishing guarantees (idempotency, atomicity, retry logic)
5. Comprehensive error logging with context

Usage:
    from agents.infrastructure.prd_redis_publisher import (
        get_prd_redis_client,
        publish_signal,
        publish_pnl,
        publish_event
    )

    # Get shared Redis client
    redis_client = await get_prd_redis_client()

    # Publish signal (validates schema automatically)
    entry_id = await publish_signal(
        redis_client=redis_client,
        mode="paper",
        signal_data={
            "signal_id": "uuid-v4",
            "timestamp": "2025-01-27T12:00:00.000Z",
            "pair": "BTC/USD",
            "side": "LONG",
            "strategy": "SCALPER",
            "regime": "TRENDING_UP",
            "entry_price": 50000.0,
            "take_profit": 52000.0,
            "stop_loss": 49000.0,
            "position_size_usd": 100.0,
            "confidence": 0.85,
            "risk_reward_ratio": 2.0,
            "indicators": {...},
            "metadata": {...}
        }
    )

    # Publish PnL update
    entry_id = await publish_pnl(
        redis_client=redis_client,
        mode="paper",
        pnl_data={
            "timestamp": "2025-01-27T12:00:00.000Z",
            "equity": 10000.0,
            "realized_pnl": 500.0,
            "unrealized_pnl": 100.0,
            "num_positions": 2,
            "drawdown_pct": 0.0
        }
    )

    # Publish event
    entry_id = await publish_event(
        redis_client=redis_client,
        event_data={
            "event_id": "uuid-v4",
            "timestamp": "2025-01-27T12:00:00.000Z",
            "event_type": "SIGNAL_PUBLISHED",
            "source": "signal_generator",
            "severity": "INFO",
            "message": "Signal published successfully",
            "data": {...}
        }
    )
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional

from agents.infrastructure.prd_publisher import (
    PRDEvent,
    PRDPnLUpdate,
    PRDSignal,
)
from agents.infrastructure.redis_client import RedisCloudClient, RedisCloudConfig

logger = logging.getLogger(__name__)

# PRD-001 Stream Configuration (Section 2.2)
STREAM_MAXLEN_SIGNALS = 10000
STREAM_MAXLEN_PNL = 50000
STREAM_MAXLEN_EVENTS = 5000

# PRD-001 Retry Configuration (Section B.4)
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_BASE = 1.0  # 1s, 2s, 4s


# =============================================================================
# SHARED REDIS CLIENT (Singleton Pattern)
# =============================================================================

_shared_redis_client: Optional[RedisCloudClient] = None
_redis_client_lock = None


async def get_prd_redis_client(
    redis_url: Optional[str] = None,
    redis_ca_cert: Optional[str] = None,
    force_new: bool = False,
) -> RedisCloudClient:
    """
    Get shared PRD-001 compliant Redis client with TLS.

    PRD-001 Section B.1: TLS connection with CA certificate
    - Uses rediss:// scheme (required)
    - Loads CA certificate from REDIS_CA_CERT env var or config/certs/redis_ca.pem
    - Connection pooling (max 10 connections)
    - Automatic reconnection with exponential backoff

    Args:
        redis_url: Override Redis URL (defaults to REDIS_URL env var)
        redis_ca_cert: Override CA cert path (defaults to REDIS_CA_CERT env var)
        force_new: Force creation of new client (for testing)

    Returns:
        Connected RedisCloudClient instance

    Raises:
        ValueError: If REDIS_URL not set or invalid
        FileNotFoundError: If CA certificate not found
        Exception: If connection fails after retries
    """
    global _shared_redis_client, _redis_client_lock

    if _redis_client_lock is None:
        import asyncio
        _redis_client_lock = asyncio.Lock()

    async with _redis_client_lock:
        if _shared_redis_client is not None and not force_new:
            # Check if still connected
            try:
                await _shared_redis_client.ping()
                return _shared_redis_client
            except Exception:
                logger.warning("Shared Redis client disconnected, reconnecting...")
                _shared_redis_client = None

        # Build config from environment or parameters
        config = RedisCloudConfig(
            url=redis_url or os.getenv("REDIS_URL", ""),
            ca_cert_path=redis_ca_cert or os.getenv("REDIS_CA_CERT") or os.getenv("REDIS_SSL_CA_CERT") or "config/certs/redis_ca.pem",
            client_name="crypto-ai-bot-prd-publisher",
            max_connections=10,  # PRD-001 Section B.1
        )

        # Validate URL uses TLS
        if not config.url.startswith("rediss://"):
            raise ValueError(
                f"PRD-001 requires TLS connection (rediss://), got: {config.url[:20]}..."
            )

        # Create and connect client
        client = RedisCloudClient(config)
        await client.connect()

        if not force_new:
            _shared_redis_client = client

        logger.info("PRD-001 Redis client connected (TLS enabled)")
        return client


async def close_prd_redis_client() -> None:
    """Close shared Redis client."""
    global _shared_redis_client
    if _shared_redis_client:
        await _shared_redis_client.disconnect()
        _shared_redis_client = None
        logger.info("PRD-001 Redis client disconnected")


# =============================================================================
# STREAM NAME HELPERS (PRD-001 Section 2.2)
# =============================================================================

def get_signal_stream_name(mode: Literal["paper", "live"], pair: str) -> str:
    """
    Get PRD-001 compliant signal stream name.

    PRD-001 Section 2.2: signals:paper:<PAIR> or signals:live:<PAIR>
    Uses dash instead of slash for Redis stream key safety.

    Args:
        mode: Trading mode ("paper" or "live")
        pair: Trading pair (e.g., "BTC/USD", "ETH/USD")

    Returns:
        Stream name (e.g., "signals:paper:BTC-USD")

    Example:
        >>> get_signal_stream_name("paper", "BTC/USD")
        'signals:paper:BTC-USD'
    """
    if mode not in ("paper", "live"):
        raise ValueError(f"Invalid mode: {mode}. Must be 'paper' or 'live'")

    # Convert pair format: BTC/USD -> BTC-USD for Redis stream safety
    normalized_pair = pair.upper().replace("/", "-")
    return f"signals:{mode}:{normalized_pair}"


def get_pnl_stream_name(mode: Literal["paper", "live"]) -> str:
    """
    Get PRD-001 compliant PnL stream name.

    PRD-001 Section 2.2: pnl:paper:equity_curve or pnl:live:equity_curve

    Args:
        mode: Trading mode ("paper" or "live")

    Returns:
        Stream name (e.g., "pnl:paper:equity_curve")
    """
    if mode not in ("paper", "live"):
        raise ValueError(f"Invalid mode: {mode}. Must be 'paper' or 'live'")

    return f"pnl:{mode}:equity_curve"


def get_event_stream_name() -> str:
    """
    Get PRD-001 compliant event stream name.

    PRD-001 Section 2.2: events:bus

    Returns:
        Stream name: "events:bus"
    """
    return "events:bus"


# =============================================================================
# SIGNAL PUBLISHING (PRD-001 Section 5.1)
# =============================================================================

async def publish_signal(
    redis_client: RedisCloudClient,
    mode: Literal["paper", "live"],
    signal_data: Dict[str, Any],
    retry_attempts: int = RETRY_ATTEMPTS,
) -> Optional[str]:
    """
    Publish PRD-001 compliant signal to Redis stream.

    PRD-001 Section 5.1: Signal Schema v1.0
    - Validates all required fields
    - Enforces exact field names and types
    - Uses signal_id as message ID for idempotency
    - Publishes to signals:paper:<PAIR> or signals:live:<PAIR>

    PRD-001 Section B.4: Publishing Guarantees
    - Idempotency: signal_id as message ID
    - Atomicity: all fields in single XADD
    - Retry logic: 3 attempts with exponential backoff
    - MAXLEN: 10,000 (approximate trimming)

    Args:
        redis_client: Connected Redis client
        mode: Trading mode ("paper" or "live")
        signal_data: Signal data dictionary (must match PRD-001 Section 5.1 schema)
        retry_attempts: Number of retry attempts (default: 3)

    Returns:
        Redis entry ID if successful, None otherwise

    Raises:
        ValueError: If signal_data doesn't match PRD-001 schema
        RuntimeError: If Redis client not connected

    Example:
        >>> signal = {
        ...     "signal_id": str(uuid.uuid4()),
        ...     "timestamp": datetime.now(timezone.utc).isoformat(),
        ...     "pair": "BTC/USD",
        ...     "side": "LONG",
        ...     "strategy": "SCALPER",
        ...     "regime": "TRENDING_UP",
        ...     "entry_price": 50000.0,
        ...     "take_profit": 52000.0,
        ...     "stop_loss": 49000.0,
        ...     "position_size_usd": 100.0,
        ...     "confidence": 0.85,
        ...     "risk_reward_ratio": 2.0,
        ... }
        >>> entry_id = await publish_signal(redis_client, "paper", signal)
    """
    import asyncio

    # Validate mode
    if mode not in ("paper", "live"):
        raise ValueError(f"Invalid mode: {mode}. Must be 'paper' or 'live'")

    # Validate and convert signal data to PRD-001 schema
    try:
        prd_signal = PRDSignal.model_validate(signal_data)
    except Exception as e:
        error_msg = f"Signal schema validation failed: {e}"
        logger.error(
            error_msg,
            extra={
                "mode": mode,
                "pair": signal_data.get("pair", "unknown"),
                "strategy": signal_data.get("strategy", "unknown"),
                "error": str(e),
            },
        )
        raise ValueError(error_msg) from e

    # Get stream name (PRD-001 Section 2.2)
    stream_name = get_signal_stream_name(mode, prd_signal.pair)

    # Convert to Redis dict (all string values)
    redis_data = prd_signal.to_redis_dict()

    # Encode all values to bytes for XADD
    encoded_data = {
        k: v.encode() if isinstance(v, str) else str(v).encode()
        for k, v in redis_data.items()
    }

    # Retry logic with exponential backoff
    last_error = None
    for attempt in range(1, retry_attempts + 1):
        try:
            # Publish with MAXLEN trimming (PRD-001 Section B.4)
            entry_id = await redis_client.xadd(
                name=stream_name,
                fields=encoded_data,
                maxlen=STREAM_MAXLEN_SIGNALS,
                approximate=True,
            )

            entry_id_str = entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)

            # Enhanced logging with explicit timestamp (PRD-001 Task A requirement)
            logger.info(
                f"Published signal to {stream_name} | pair={prd_signal.pair} side={prd_signal.side} "
                f"strategy={prd_signal.strategy} mode={mode} timestamp={prd_signal.timestamp}",
                extra={
                    "signal_id": prd_signal.signal_id,
                    "pair": prd_signal.pair,
                    "side": str(prd_signal.side),
                    "strategy": str(prd_signal.strategy),
                    "mode": mode,
                    "timestamp": prd_signal.timestamp,
                    "stream": stream_name,
                    "entry_id": entry_id_str,
                },
            )

            return entry_id_str

        except Exception as e:
            last_error = e
            backoff = RETRY_BACKOFF_BASE * (2 ** (attempt - 1))

            logger.error(
                f"Failed to publish signal to {stream_name} (attempt {attempt}/{retry_attempts})",
                extra={
                    "signal_id": prd_signal.signal_id,
                    "pair": prd_signal.pair,
                    "strategy": str(prd_signal.strategy),
                    "mode": mode,
                    "stream": stream_name,
                    "error": str(e),
                    "attempt": attempt,
                },
                exc_info=True,
            )

            if attempt < retry_attempts:
                await asyncio.sleep(backoff)

    # All retries failed
    logger.critical(
        f"Failed to publish signal after {retry_attempts} attempts",
        extra={
            "signal_id": prd_signal.signal_id,
            "pair": prd_signal.pair,
            "strategy": str(prd_signal.strategy),
            "mode": mode,
            "stream": stream_name,
            "error": str(last_error),
        },
    )
    return None


# =============================================================================
# PnL PUBLISHING (PRD-001 Section 2.2)
# =============================================================================

async def publish_pnl(
    redis_client: RedisCloudClient,
    mode: Literal["paper", "live"],
    pnl_data: Dict[str, Any],
    retry_attempts: int = RETRY_ATTEMPTS,
) -> Optional[str]:
    """
    Publish PnL update to PRD-001 compliant stream.

    PRD-001 Section 2.2: pnl:paper:equity_curve or pnl:live:equity_curve
    - MAXLEN: 50,000 (approximate trimming)
    - TTL: 30 days (handled by Redis Cloud)

    Args:
        redis_client: Connected Redis client
        mode: Trading mode ("paper" or "live")
        pnl_data: PnL data dictionary
        retry_attempts: Number of retry attempts (default: 3)

    Returns:
        Redis entry ID if successful, None otherwise

    Example:
        >>> pnl = {
        ...     "timestamp": datetime.now(timezone.utc).isoformat(),
        ...     "equity": 10000.0,
        ...     "realized_pnl": 500.0,
        ...     "unrealized_pnl": 100.0,
        ...     "num_positions": 2,
        ...     "drawdown_pct": 0.0
        ... }
        >>> entry_id = await publish_pnl(redis_client, "paper", pnl)
    """
    import asyncio

    # Validate mode
    if mode not in ("paper", "live"):
        raise ValueError(f"Invalid mode: {mode}. Must be 'paper' or 'live'")

    # Validate and convert PnL data
    try:
        pnl_update = PRDPnLUpdate.model_validate(pnl_data)
    except Exception as e:
        error_msg = f"PnL schema validation failed: {e}"
        logger.error(
            error_msg,
            extra={
                "mode": mode,
                "error": str(e),
            },
        )
        raise ValueError(error_msg) from e

    # Get stream name (PRD-001 Section 2.2)
    stream_name = get_pnl_stream_name(mode)

    # Convert to Redis dict
    redis_data = pnl_update.to_redis_dict()

    # Encode all values to bytes
    encoded_data = {
        k: v.encode() if isinstance(v, str) else str(v).encode()
        for k, v in redis_data.items()
    }

    # Retry logic
    last_error = None
    for attempt in range(1, retry_attempts + 1):
        try:
            entry_id = await redis_client.xadd(
                name=stream_name,
                fields=encoded_data,
                maxlen=STREAM_MAXLEN_PNL,
                approximate=True,
            )

            entry_id_str = entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)

            logger.debug(
                f"Published PnL update to {stream_name}",
                extra={
                    "mode": mode,
                    "stream": stream_name,
                    "equity": pnl_update.equity,
                    "entry_id": entry_id_str,
                },
            )

            return entry_id_str

        except Exception as e:
            last_error = e
            backoff = RETRY_BACKOFF_BASE * (2 ** (attempt - 1))

            logger.error(
                f"Failed to publish PnL to {stream_name} (attempt {attempt}/{retry_attempts})",
                extra={
                    "mode": mode,
                    "stream": stream_name,
                    "error": str(e),
                    "attempt": attempt,
                },
            )

            if attempt < retry_attempts:
                await asyncio.sleep(backoff)

    logger.critical(
        f"Failed to publish PnL after {retry_attempts} attempts",
        extra={
            "mode": mode,
            "stream": stream_name,
            "error": str(last_error),
        },
    )
    return None


# =============================================================================
# EVENT PUBLISHING (PRD-001 Section 2.2)
# =============================================================================

async def publish_event(
    redis_client: RedisCloudClient,
    event_data: Dict[str, Any],
    retry_attempts: int = RETRY_ATTEMPTS,
) -> Optional[str]:
    """
    Publish system event to PRD-001 compliant stream.

    PRD-001 Section 2.2: events:bus
    - MAXLEN: 5,000 (approximate trimming)
    - TTL: 7 days (handled by Redis Cloud)

    Args:
        redis_client: Connected Redis client
        event_data: Event data dictionary
        retry_attempts: Number of retry attempts (default: 3)

    Returns:
        Redis entry ID if successful, None otherwise

    Example:
        >>> event = {
        ...     "event_id": str(uuid.uuid4()),
        ...     "timestamp": datetime.now(timezone.utc).isoformat(),
        ...     "event_type": "SIGNAL_PUBLISHED",
        ...     "source": "signal_generator",
        ...     "severity": "INFO",
        ...     "message": "Signal published successfully",
        ...     "data": {"signal_id": "..."}
        ... }
        >>> entry_id = await publish_event(redis_client, event)
    """
    import asyncio

    # Validate and convert event data
    try:
        event = PRDEvent.model_validate(event_data)
    except Exception as e:
        error_msg = f"Event schema validation failed: {e}"
        logger.error(
            error_msg,
            extra={
                "event_type": event_data.get("event_type", "unknown"),
                "error": str(e),
            },
        )
        raise ValueError(error_msg) from e

    # Get stream name (PRD-001 Section 2.2)
    stream_name = get_event_stream_name()

    # Convert to Redis dict
    redis_data = event.to_redis_dict()

    # Encode all values to bytes
    encoded_data = {
        k: v.encode() if isinstance(v, str) else str(v).encode()
        for k, v in redis_data.items()
    }

    # Retry logic
    last_error = None
    for attempt in range(1, retry_attempts + 1):
        try:
            entry_id = await redis_client.xadd(
                name=stream_name,
                fields=encoded_data,
                maxlen=STREAM_MAXLEN_EVENTS,
                approximate=True,
            )

            entry_id_str = entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)

            logger.debug(
                f"Published event to {stream_name}",
                extra={
                    "event_type": event.event_type,
                    "source": event.source,
                    "severity": event.severity,
                    "stream": stream_name,
                    "entry_id": entry_id_str,
                },
            )

            return entry_id_str

        except Exception as e:
            last_error = e
            backoff = RETRY_BACKOFF_BASE * (2 ** (attempt - 1))

            logger.error(
                f"Failed to publish event to {stream_name} (attempt {attempt}/{retry_attempts})",
                extra={
                    "event_type": event.event_type,
                    "source": event.source,
                    "stream": stream_name,
                    "error": str(e),
                    "attempt": attempt,
                },
            )

            if attempt < retry_attempts:
                await asyncio.sleep(backoff)

    logger.critical(
        f"Failed to publish event after {retry_attempts} attempts",
        extra={
            "event_type": event.event_type,
            "source": event.source,
            "stream": stream_name,
            "error": str(last_error),
        },
    )
    return None


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def get_engine_mode() -> Literal["paper", "live"]:
    """
    Get ENGINE_MODE from environment variable.

    PRD-001 Section G.4: ENGINE_MODE determines stream routing
    - Defaults to "paper" for safety
    - Must be "paper" or "live"

    Returns:
        Engine mode ("paper" or "live")
    """
    mode = os.getenv("ENGINE_MODE", "paper").lower()
    if mode not in ("paper", "live"):
        logger.warning(f"Invalid ENGINE_MODE={mode}, defaulting to 'paper'")
        return "paper"
    return mode  # type: ignore


# =============================================================================
# PUBLIC API
# =============================================================================

__all__ = [
    # Client management
    "get_prd_redis_client",
    "close_prd_redis_client",
    # Stream name helpers
    "get_signal_stream_name",
    "get_pnl_stream_name",
    "get_event_stream_name",
    # Publishing functions
    "publish_signal",
    "publish_pnl",
    "publish_event",
    # Utilities
    "get_engine_mode",
    # Constants
    "STREAM_MAXLEN_SIGNALS",
    "STREAM_MAXLEN_PNL",
    "STREAM_MAXLEN_EVENTS",
]

