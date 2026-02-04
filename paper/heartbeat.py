"""
Engine Heartbeat Publisher for Paper Trading.

Phase 2 Step 2.3: Publishes engine status including effective risk limits
so API/UI can distinguish between "saved" and "enforced" state.

Redis key: paper:engine:status:{account_id}
TTL: 60 seconds (expires if engine crashes/stops)

The heartbeat contains:
- What limits the engine is ACTUALLY enforcing
- Source of limits (redis | default | error)
- Last refresh timestamp
- Block reasons if trading is disabled
- Kill switch effective state
"""

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Literal, Optional

logger = logging.getLogger(__name__)

# Redis key pattern for engine status heartbeat
ENGINE_STATUS_KEY = "paper:engine:status:{account_id}"

# Heartbeat TTL in seconds (longer than cache TTL, expires if engine dies)
ENGINE_STATUS_TTL_SECONDS = 60

# Minimum interval between heartbeats (throttle)
MIN_HEARTBEAT_INTERVAL_SECONDS = 5.0


@dataclass
class EffectiveRiskLimitsSnapshot:
    """Snapshot of what limits the engine is currently enforcing."""

    max_trades_per_day: int
    max_position_size_usd: float
    max_daily_loss_pct: float


@dataclass
class EngineHeartbeat:
    """
    Engine heartbeat containing effective enforcement state.

    This is what the engine is ACTUALLY enforcing right now,
    which may differ from what was just saved via API.
    """

    # Identity
    account_id: str
    bot_id: Optional[str] = None

    # Effective trading state
    trading_enabled: bool = True
    block_reason: Optional[str] = None  # GLOBAL_KILL, ACCOUNT_KILL, BOT_KILL, REDIS_ERROR

    # Effective risk limits (what engine is enforcing)
    effective_risk_limits: Optional[EffectiveRiskLimitsSnapshot] = None

    # Source of limits
    risk_limits_source: Literal["redis", "default", "error"] = "default"
    risk_limits_last_refresh_ts: Optional[str] = None
    cache_ttl_seconds: int = 15

    # Error tracking
    last_error: Optional[str] = None
    last_error_ts: Optional[str] = None

    # Kill switch state
    kill_switch_global: bool = False
    kill_switch_account: bool = False
    kill_switch_bot: bool = False

    # Heartbeat metadata
    updated_at: str = ""
    engine_version: str = "1.0.0"

    def __post_init__(self):
        if not self.updated_at:
            self.updated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        """Convert to dictionary for Redis storage."""
        data = asdict(self)
        # Convert nested dataclass to dict
        if self.effective_risk_limits:
            data["effective_risk_limits"] = asdict(self.effective_risk_limits)
        return data


class HeartbeatPublisher:
    """
    Publishes engine status heartbeats to Redis.

    Throttles to avoid excessive Redis writes while ensuring
    status updates are visible to API/UI within bounded delay.
    """

    def __init__(
        self,
        redis_client: Any,
        account_id: str,
        bot_id: Optional[str] = None,
        min_interval_seconds: float = MIN_HEARTBEAT_INTERVAL_SECONDS,
        status_ttl_seconds: int = ENGINE_STATUS_TTL_SECONDS,
    ):
        """
        Initialize heartbeat publisher.

        Args:
            redis_client: Async Redis client
            account_id: Account ID for this engine
            bot_id: Optional bot ID
            min_interval_seconds: Minimum seconds between heartbeats
            status_ttl_seconds: TTL for the status key
        """
        self.redis = redis_client
        self.account_id = account_id
        self.bot_id = bot_id
        self.min_interval_seconds = min_interval_seconds
        self.status_ttl_seconds = status_ttl_seconds

        self._last_publish_ts: Optional[datetime] = None
        self._last_heartbeat: Optional[EngineHeartbeat] = None

    def _should_publish(self, force: bool = False) -> bool:
        """Check if enough time has passed since last publish."""
        if force:
            return True
        if self._last_publish_ts is None:
            return True

        elapsed = (datetime.now(timezone.utc) - self._last_publish_ts).total_seconds()
        return elapsed >= self.min_interval_seconds

    async def publish(
        self,
        trading_enabled: bool,
        block_reason: Optional[str],
        effective_limits: Optional[EffectiveRiskLimitsSnapshot],
        limits_source: Literal["redis", "default", "error"],
        limits_refresh_ts: Optional[datetime],
        last_error: Optional[str] = None,
        kill_switch_global: bool = False,
        kill_switch_account: bool = False,
        kill_switch_bot: bool = False,
        force: bool = False,
    ) -> bool:
        """
        Publish engine heartbeat to Redis.

        Args:
            trading_enabled: Whether engine is allowing trades
            block_reason: Reason if blocked (GLOBAL_KILL, ACCOUNT_KILL, etc.)
            effective_limits: Current risk limits being enforced
            limits_source: Where limits came from (redis, default, error)
            limits_refresh_ts: When limits were last refreshed from Redis
            last_error: Last error message if any
            kill_switch_global: Global kill switch state
            kill_switch_account: Account kill switch state
            kill_switch_bot: Bot kill switch state
            force: Force publish even if throttle hasn't elapsed

        Returns:
            True if published, False if throttled
        """
        if not self._should_publish(force):
            return False

        now = datetime.now(timezone.utc)

        heartbeat = EngineHeartbeat(
            account_id=self.account_id,
            bot_id=self.bot_id,
            trading_enabled=trading_enabled,
            block_reason=block_reason,
            effective_risk_limits=effective_limits,
            risk_limits_source=limits_source,
            risk_limits_last_refresh_ts=limits_refresh_ts.isoformat() if limits_refresh_ts else None,
            cache_ttl_seconds=15,
            last_error=last_error,
            last_error_ts=now.isoformat() if last_error else None,
            kill_switch_global=kill_switch_global,
            kill_switch_account=kill_switch_account,
            kill_switch_bot=kill_switch_bot,
            updated_at=now.isoformat(),
        )

        try:
            key = ENGINE_STATUS_KEY.format(account_id=self.account_id)
            payload = json.dumps(heartbeat.to_dict())

            # Set with TTL so key expires if engine crashes
            await self.redis.set(key, payload, ex=self.status_ttl_seconds)

            self._last_publish_ts = now
            self._last_heartbeat = heartbeat

            logger.debug(
                f"Published engine heartbeat: account={self.account_id} "
                f"trading_enabled={trading_enabled} source={limits_source}",
                extra={
                    "account_id": self.account_id,
                    "trading_enabled": trading_enabled,
                    "limits_source": limits_source,
                    "block_reason": block_reason,
                },
            )

            return True

        except Exception as e:
            logger.error(
                f"Failed to publish engine heartbeat: {e}",
                extra={
                    "account_id": self.account_id,
                    "error": str(e),
                },
            )
            return False

    async def publish_stopped(self, reason: str) -> bool:
        """
        Publish a final heartbeat indicating engine has stopped.

        Args:
            reason: Reason for stopping

        Returns:
            True if published successfully
        """
        return await self.publish(
            trading_enabled=False,
            block_reason=f"ENGINE_STOPPED:{reason}",
            effective_limits=self._last_heartbeat.effective_risk_limits if self._last_heartbeat else None,
            limits_source="default",
            limits_refresh_ts=None,
            last_error=None,
            force=True,
        )

    async def clear(self) -> bool:
        """
        Clear the heartbeat key (on graceful shutdown).

        Returns:
            True if cleared successfully
        """
        try:
            key = ENGINE_STATUS_KEY.format(account_id=self.account_id)
            await self.redis.delete(key)
            logger.info(f"Cleared engine heartbeat: account={self.account_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to clear engine heartbeat: {e}")
            return False
