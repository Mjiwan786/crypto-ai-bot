"""
Redis Telemetry for signals-api/frontend - Week 2 Task B

This module provides lightweight Redis telemetry keys that signals-api and
signals-site can use for quick status checks without scanning streams.

Telemetry Keys:
    engine:last_signal_meta     Hash with last signal metadata
    engine:last_pnl_meta        Hash with last PnL metadata
    engine:status               Hash with engine status

Design Principles:
    - Use HASHES for O(1) read with HGETALL
    - Non-blocking updates (fire-and-forget)
    - TTL on keys to auto-expire stale data
    - Minimal overhead on signal publishing

Usage in crypto-ai-bot:
    from monitoring.telemetry import EngineTelemetry

    telemetry = EngineTelemetry(redis_client)

    # On signal publish
    telemetry.update_last_signal(pair="BTC/USD", side="LONG", ...)

    # On PnL update
    telemetry.update_last_pnl(equity=10500.0, realized_pnl=500.0, ...)

Usage in signals-api:
    # Simple HGETALL to get last signal info
    last_signal = await redis.hgetall("engine:last_signal_meta")
    # Returns: {pair: "BTC/USD", side: "LONG", strategy: "SCALPER", ...}

    # Check if engine is alive (key expires if engine stops publishing)
    status = await redis.hgetall("engine:status")
    # Returns: {status: "running", last_heartbeat: "2025-11-29T...", uptime_seconds: "3600"}

Redis CLI inspection commands (safe - no secrets):
    HGETALL engine:last_signal_meta
    HGETALL engine:last_pnl_meta
    HGETALL engine:status
    TTL engine:last_signal_meta
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional, Union

logger = logging.getLogger(__name__)

# =============================================================================
# TELEMETRY KEY CONFIGURATION
# =============================================================================

# Redis key names
KEY_LAST_SIGNAL_META = os.getenv("TELEMETRY_KEY_SIGNAL", "engine:last_signal_meta")
KEY_LAST_PNL_META = os.getenv("TELEMETRY_KEY_PNL", "engine:last_pnl_meta")
KEY_ENGINE_STATUS = os.getenv("TELEMETRY_KEY_STATUS", "engine:status")

# TTL for telemetry keys (stale data auto-expires)
DEFAULT_TTL_SECONDS = int(os.getenv("TELEMETRY_TTL_SECONDS", "300"))  # 5 minutes


# =============================================================================
# TELEMETRY CLASS
# =============================================================================

class EngineTelemetry:
    """
    Engine Telemetry for signals-api/frontend.

    Provides lightweight Redis hashes that can be read with simple HGETALL
    commands for status pages, health checks, and "last activity" displays.

    Thread-safe and async-compatible.
    """

    def __init__(
        self,
        redis_client: Any,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        enabled: bool = True,
    ):
        """
        Initialize telemetry.

        Args:
            redis_client: Redis client (sync or async)
            ttl_seconds: TTL for telemetry keys (default: 300s / 5 min)
            enabled: Enable telemetry (default: True)
        """
        self.redis = redis_client
        self.ttl_seconds = ttl_seconds
        self.enabled = enabled
        self.start_time = time.time()

        # Detect if client is async
        self._is_async = self._detect_async_client()

        if self.enabled:
            logger.info(
                f"EngineTelemetry initialized (async={self._is_async}, ttl={ttl_seconds}s)"
            )

    def _detect_async_client(self) -> bool:
        """Detect if redis_client is async."""
        if self.redis is None:
            return False
        client_module = type(self.redis).__module__
        return 'asyncio' in client_module or 'aioredis' in client_module

    def _get_iso_timestamp(self) -> str:
        """Get current UTC timestamp in ISO format."""
        return datetime.now(timezone.utc).isoformat(timespec='milliseconds')

    def _get_epoch_ms(self) -> int:
        """Get current time as epoch milliseconds."""
        return int(time.time() * 1000)

    # =========================================================================
    # LAST SIGNAL METADATA
    # =========================================================================

    async def update_last_signal_async(
        self,
        pair: str,
        side: Literal["LONG", "SHORT", "buy", "sell"],
        strategy: str,
        confidence: float,
        entry_price: float,
        mode: Literal["paper", "live"] = "paper",
        timeframe: Optional[str] = None,
        signal_id: Optional[str] = None,
    ) -> bool:
        """
        Update last signal metadata (async version).

        Args:
            pair: Trading pair (e.g., "BTC/USD")
            side: Signal side (LONG/SHORT or buy/sell)
            strategy: Strategy name
            confidence: Signal confidence [0-1]
            entry_price: Entry price
            mode: Trading mode (paper/live)
            timeframe: Signal timeframe (e.g., "5m")
            signal_id: Optional signal ID

        Returns:
            True if update succeeded, False otherwise
        """
        if not self.enabled:
            return True

        try:
            data = {
                "pair": pair,
                "side": side.upper() if side in ("buy", "sell") else side,
                "strategy": strategy,
                "confidence": str(confidence),
                "entry_price": str(entry_price),
                "mode": mode,
                "timestamp": self._get_iso_timestamp(),
                "timestamp_ms": str(self._get_epoch_ms()),
            }

            if timeframe:
                data["timeframe"] = timeframe
            if signal_id:
                data["signal_id"] = signal_id

            # Update hash and set TTL
            await self.redis.hset(KEY_LAST_SIGNAL_META, mapping=data)
            await self.redis.expire(KEY_LAST_SIGNAL_META, self.ttl_seconds)

            logger.debug(f"Updated {KEY_LAST_SIGNAL_META}: {pair} {side} {strategy}")
            return True

        except Exception as e:
            logger.warning(f"Failed to update last signal telemetry: {e}")
            return False

    def update_last_signal_sync(
        self,
        pair: str,
        side: Literal["LONG", "SHORT", "buy", "sell"],
        strategy: str,
        confidence: float,
        entry_price: float,
        mode: Literal["paper", "live"] = "paper",
        timeframe: Optional[str] = None,
        signal_id: Optional[str] = None,
    ) -> bool:
        """
        Update last signal metadata (sync version).
        """
        if not self.enabled:
            return True

        try:
            data = {
                "pair": pair,
                "side": side.upper() if side in ("buy", "sell") else side,
                "strategy": strategy,
                "confidence": str(confidence),
                "entry_price": str(entry_price),
                "mode": mode,
                "timestamp": self._get_iso_timestamp(),
                "timestamp_ms": str(self._get_epoch_ms()),
            }

            if timeframe:
                data["timeframe"] = timeframe
            if signal_id:
                data["signal_id"] = signal_id

            # Update hash and set TTL
            self.redis.hset(KEY_LAST_SIGNAL_META, mapping=data)
            self.redis.expire(KEY_LAST_SIGNAL_META, self.ttl_seconds)

            logger.debug(f"Updated {KEY_LAST_SIGNAL_META}: {pair} {side} {strategy}")
            return True

        except Exception as e:
            logger.warning(f"Failed to update last signal telemetry: {e}")
            return False

    def update_last_signal(self, **kwargs) -> Union[bool, Any]:
        """
        Update last signal metadata (auto-detect sync/async).

        See update_last_signal_async for parameters.
        """
        if self._is_async:
            return self.update_last_signal_async(**kwargs)
        else:
            return self.update_last_signal_sync(**kwargs)

    # =========================================================================
    # LAST PNL METADATA
    # =========================================================================

    async def update_last_pnl_async(
        self,
        equity: float,
        realized_pnl: float = 0.0,
        unrealized_pnl: float = 0.0,
        num_positions: int = 0,
        drawdown_pct: float = 0.0,
        mode: Literal["paper", "live"] = "paper",
        win_rate: Optional[float] = None,
        total_trades: Optional[int] = None,
    ) -> bool:
        """
        Update last PnL metadata (async version).

        Args:
            equity: Current equity value
            realized_pnl: Realized PnL
            unrealized_pnl: Unrealized PnL
            num_positions: Number of open positions
            drawdown_pct: Current drawdown %
            mode: Trading mode (paper/live)
            win_rate: Optional win rate
            total_trades: Optional total trades count

        Returns:
            True if update succeeded, False otherwise
        """
        if not self.enabled:
            return True

        try:
            data = {
                "equity": str(equity),
                "realized_pnl": str(realized_pnl),
                "unrealized_pnl": str(unrealized_pnl),
                "total_pnl": str(realized_pnl + unrealized_pnl),
                "num_positions": str(num_positions),
                "drawdown_pct": str(drawdown_pct),
                "mode": mode,
                "timestamp": self._get_iso_timestamp(),
                "timestamp_ms": str(self._get_epoch_ms()),
            }

            if win_rate is not None:
                data["win_rate"] = str(win_rate)
            if total_trades is not None:
                data["total_trades"] = str(total_trades)

            # Update hash and set TTL
            await self.redis.hset(KEY_LAST_PNL_META, mapping=data)
            await self.redis.expire(KEY_LAST_PNL_META, self.ttl_seconds)

            logger.debug(f"Updated {KEY_LAST_PNL_META}: equity={equity}")
            return True

        except Exception as e:
            logger.warning(f"Failed to update last PnL telemetry: {e}")
            return False

    def update_last_pnl_sync(
        self,
        equity: float,
        realized_pnl: float = 0.0,
        unrealized_pnl: float = 0.0,
        num_positions: int = 0,
        drawdown_pct: float = 0.0,
        mode: Literal["paper", "live"] = "paper",
        win_rate: Optional[float] = None,
        total_trades: Optional[int] = None,
    ) -> bool:
        """
        Update last PnL metadata (sync version).
        """
        if not self.enabled:
            return True

        try:
            data = {
                "equity": str(equity),
                "realized_pnl": str(realized_pnl),
                "unrealized_pnl": str(unrealized_pnl),
                "total_pnl": str(realized_pnl + unrealized_pnl),
                "num_positions": str(num_positions),
                "drawdown_pct": str(drawdown_pct),
                "mode": mode,
                "timestamp": self._get_iso_timestamp(),
                "timestamp_ms": str(self._get_epoch_ms()),
            }

            if win_rate is not None:
                data["win_rate"] = str(win_rate)
            if total_trades is not None:
                data["total_trades"] = str(total_trades)

            # Update hash and set TTL
            self.redis.hset(KEY_LAST_PNL_META, mapping=data)
            self.redis.expire(KEY_LAST_PNL_META, self.ttl_seconds)

            logger.debug(f"Updated {KEY_LAST_PNL_META}: equity={equity}")
            return True

        except Exception as e:
            logger.warning(f"Failed to update last PnL telemetry: {e}")
            return False

    def update_last_pnl(self, **kwargs) -> Union[bool, Any]:
        """
        Update last PnL metadata (auto-detect sync/async).

        See update_last_pnl_async for parameters.
        """
        if self._is_async:
            return self.update_last_pnl_async(**kwargs)
        else:
            return self.update_last_pnl_sync(**kwargs)

    # =========================================================================
    # ENGINE STATUS
    # =========================================================================

    async def update_engine_status_async(
        self,
        status: Literal["running", "starting", "stopping", "error"] = "running",
        mode: Literal["paper", "live"] = "paper",
        version: Optional[str] = None,
        pairs: Optional[list] = None,
    ) -> bool:
        """
        Update engine status (async version).

        Args:
            status: Engine status
            mode: Trading mode
            version: Engine version
            pairs: Active trading pairs

        Returns:
            True if update succeeded, False otherwise
        """
        if not self.enabled:
            return True

        try:
            uptime = int(time.time() - self.start_time)

            data = {
                "status": status,
                "mode": mode,
                "last_heartbeat": self._get_iso_timestamp(),
                "last_heartbeat_ms": str(self._get_epoch_ms()),
                "uptime_seconds": str(uptime),
            }

            if version:
                data["version"] = version
            if pairs:
                data["active_pairs"] = ",".join(pairs)

            # Update hash and set TTL
            await self.redis.hset(KEY_ENGINE_STATUS, mapping=data)
            await self.redis.expire(KEY_ENGINE_STATUS, self.ttl_seconds)

            return True

        except Exception as e:
            logger.warning(f"Failed to update engine status telemetry: {e}")
            return False

    def update_engine_status_sync(
        self,
        status: Literal["running", "starting", "stopping", "error"] = "running",
        mode: Literal["paper", "live"] = "paper",
        version: Optional[str] = None,
        pairs: Optional[list] = None,
    ) -> bool:
        """
        Update engine status (sync version).
        """
        if not self.enabled:
            return True

        try:
            uptime = int(time.time() - self.start_time)

            data = {
                "status": status,
                "mode": mode,
                "last_heartbeat": self._get_iso_timestamp(),
                "last_heartbeat_ms": str(self._get_epoch_ms()),
                "uptime_seconds": str(uptime),
            }

            if version:
                data["version"] = version
            if pairs:
                data["active_pairs"] = ",".join(pairs)

            # Update hash and set TTL
            self.redis.hset(KEY_ENGINE_STATUS, mapping=data)
            self.redis.expire(KEY_ENGINE_STATUS, self.ttl_seconds)

            return True

        except Exception as e:
            logger.warning(f"Failed to update engine status telemetry: {e}")
            return False

    def update_engine_status(self, **kwargs) -> Union[bool, Any]:
        """
        Update engine status (auto-detect sync/async).

        See update_engine_status_async for parameters.
        """
        if self._is_async:
            return self.update_engine_status_async(**kwargs)
        else:
            return self.update_engine_status_sync(**kwargs)


# =============================================================================
# GLOBAL INSTANCE
# =============================================================================

_global_telemetry: Optional[EngineTelemetry] = None


def get_telemetry(redis_client: Optional[Any] = None) -> Optional[EngineTelemetry]:
    """
    Get or create global telemetry instance.

    Args:
        redis_client: Redis client (required on first call)

    Returns:
        EngineTelemetry instance or None if redis_client not provided
    """
    global _global_telemetry

    if _global_telemetry is None and redis_client is not None:
        _global_telemetry = EngineTelemetry(redis_client)

    return _global_telemetry


def set_telemetry(telemetry: EngineTelemetry) -> None:
    """Set global telemetry instance."""
    global _global_telemetry
    _global_telemetry = telemetry


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def update_signal_telemetry(
    pair: str,
    side: str,
    strategy: str,
    confidence: float,
    entry_price: float,
    **kwargs
) -> Union[bool, Any]:
    """
    Convenience function to update signal telemetry.

    Requires telemetry to be initialized via get_telemetry(redis_client) first.
    """
    if _global_telemetry is None:
        logger.warning("Telemetry not initialized, call get_telemetry(redis_client) first")
        return False

    return _global_telemetry.update_last_signal(
        pair=pair,
        side=side,
        strategy=strategy,
        confidence=confidence,
        entry_price=entry_price,
        **kwargs
    )


def update_pnl_telemetry(equity: float, **kwargs) -> Union[bool, Any]:
    """
    Convenience function to update PnL telemetry.

    Requires telemetry to be initialized via get_telemetry(redis_client) first.
    """
    if _global_telemetry is None:
        logger.warning("Telemetry not initialized, call get_telemetry(redis_client) first")
        return False

    return _global_telemetry.update_last_pnl(equity=equity, **kwargs)


def update_status_telemetry(**kwargs) -> Union[bool, Any]:
    """
    Convenience function to update engine status telemetry.

    Requires telemetry to be initialized via get_telemetry(redis_client) first.
    """
    if _global_telemetry is None:
        logger.warning("Telemetry not initialized, call get_telemetry(redis_client) first")
        return False

    return _global_telemetry.update_engine_status(**kwargs)


# =============================================================================
# PUBLIC API
# =============================================================================

__all__ = [
    # Keys
    "KEY_LAST_SIGNAL_META",
    "KEY_LAST_PNL_META",
    "KEY_ENGINE_STATUS",
    # Class
    "EngineTelemetry",
    # Global functions
    "get_telemetry",
    "set_telemetry",
    "update_signal_telemetry",
    "update_pnl_telemetry",
    "update_status_telemetry",
]
