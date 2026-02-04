"""
Dynamic Risk Limits Provider for Paper Trading.

Fetches risk limits from Redis with caching:
- paper:risk:account:{account_id}
- paper:risk:bot:{bot_id} (optional, more specific)

Merges limits (most restrictive wins) with engine defaults as floor.
Handles Redis failures by blocking execution (fail-safe).

TTL-based caching prevents excessive Redis reads while ensuring
changes take effect within bounded delay.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
import asyncio
import json
import logging

from backtest.risk_evaluator import RiskLimits

logger = logging.getLogger(__name__)


# Redis key patterns (must match signals-api paper_controls.py)
RISK_LIMITS_ACCOUNT_KEY = "paper:risk:account:{account_id}"
RISK_LIMITS_BOT_KEY = "paper:risk:bot:{bot_id}"

# Event stream for publishing control errors
CONTROLS_EVENT_STREAM = "events:paper:controls"

# Cache TTL in seconds (15s balances responsiveness with Redis load)
DEFAULT_CACHE_TTL_SECONDS = 15

# Redis read timeout in seconds
REDIS_READ_TIMEOUT_SECONDS = 2.0


@dataclass
class RiskLimitsMeta:
    """Metadata about a risk limits fetch."""

    enforcement_state: Literal["ok", "stale", "error"]
    fetched_at: datetime
    source_keys: list[str]
    error_message: str | None = None
    error_class: str | None = None  # timeout, connection, invalid_payload
    cache_hit: bool = False


@dataclass
class EffectiveRiskLimits:
    """Effective risk limits with metadata for explainability."""

    limits: RiskLimits
    meta: RiskLimitsMeta

    @property
    def can_trade(self) -> bool:
        """Check if trading is allowed based on enforcement state."""
        return self.meta.enforcement_state == "ok"


@dataclass
class CachedLimits:
    """Cached risk limits with expiry tracking."""

    limits: RiskLimits
    fetched_at: datetime
    source_keys: list[str]

    def is_expired(self, ttl_seconds: float) -> bool:
        """Check if cache has expired."""
        age = (datetime.now(timezone.utc) - self.fetched_at).total_seconds()
        return age > ttl_seconds


class RiskLimitsProvider:
    """
    Provides dynamic risk limits from Redis with caching.

    Features:
    - TTL-based caching (default 15 seconds)
    - Merge logic: most restrictive of bot/account/defaults wins per field
    - Fail-safe: Redis errors block trading (never allow silent execution)
    - Publishes error events to controls stream for visibility

    Usage:
        provider = RiskLimitsProvider(redis, defaults=RiskLimits(...))
        result = await provider.get_effective_limits("account_1", "bot_1")
        if not result.can_trade:
            # Reject with RISK_LIMITS_UNAVAILABLE
            pass
    """

    def __init__(
        self,
        redis_client: Any,
        defaults: RiskLimits,
        cache_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
    ):
        """
        Initialize risk limits provider.

        Args:
            redis_client: Async Redis client
            defaults: Default/floor risk limits from engine config
            cache_ttl_seconds: How long to cache fetched limits (default 15s)
        """
        self.redis = redis_client
        self.defaults = defaults
        self.cache_ttl_seconds = cache_ttl_seconds

        # Cache: keyed by (account_id, bot_id) tuple
        self._cache: dict[tuple[str, str], CachedLimits] = {}

    async def get_effective_limits(
        self,
        account_id: str,
        bot_id: str,
    ) -> EffectiveRiskLimits:
        """
        Get effective risk limits for account/bot.

        Returns cached limits if within TTL, otherwise fetches from Redis.
        On any error, returns limits with enforcement_state="error".

        Args:
            account_id: Account ID
            bot_id: Bot ID

        Returns:
            EffectiveRiskLimits with limits and metadata
        """
        cache_key = (account_id, bot_id)
        now = datetime.now(timezone.utc)

        # Check cache
        cached = self._cache.get(cache_key)
        if cached is not None and not cached.is_expired(self.cache_ttl_seconds):
            return EffectiveRiskLimits(
                limits=cached.limits,
                meta=RiskLimitsMeta(
                    enforcement_state="ok",
                    fetched_at=cached.fetched_at,
                    source_keys=cached.source_keys,
                    cache_hit=True,
                ),
            )

        # Fetch from Redis
        try:
            limits, source_keys = await self._fetch_and_merge(account_id, bot_id)

            # Update cache
            self._cache[cache_key] = CachedLimits(
                limits=limits,
                fetched_at=now,
                source_keys=source_keys,
            )

            return EffectiveRiskLimits(
                limits=limits,
                meta=RiskLimitsMeta(
                    enforcement_state="ok",
                    fetched_at=now,
                    source_keys=source_keys,
                    cache_hit=False,
                ),
            )

        except asyncio.TimeoutError:
            logger.error(
                f"Redis timeout fetching risk limits for account={account_id} bot={bot_id}",
                extra={"account_id": account_id, "bot_id": bot_id, "error": "timeout"},
            )
            await self._publish_error_event(
                account_id, bot_id, "timeout", "Redis read timeout"
            )
            return self._error_result(now, "timeout", "Redis read timeout")

        except ConnectionError as e:
            logger.error(
                f"Redis connection error fetching risk limits: {e}",
                extra={"account_id": account_id, "bot_id": bot_id, "error": str(e)},
            )
            await self._publish_error_event(
                account_id, bot_id, "connection", str(e)
            )
            return self._error_result(now, "connection", str(e))

        except json.JSONDecodeError as e:
            logger.error(
                f"Invalid JSON in risk limits: {e}",
                extra={"account_id": account_id, "bot_id": bot_id, "error": str(e)},
            )
            await self._publish_error_event(
                account_id, bot_id, "invalid_payload", f"JSON decode error: {e}"
            )
            return self._error_result(now, "invalid_payload", f"JSON decode error: {e}")

        except ValueError as e:
            # Validation error (out of bounds, missing fields, etc.)
            logger.error(
                f"Invalid risk limits payload: {e}",
                extra={"account_id": account_id, "bot_id": bot_id, "error": str(e)},
            )
            await self._publish_error_event(
                account_id, bot_id, "invalid_payload", str(e)
            )
            return self._error_result(now, "invalid_payload", str(e))

        except Exception as e:
            logger.error(
                f"Unexpected error fetching risk limits: {e}",
                extra={"account_id": account_id, "bot_id": bot_id, "error": str(e)},
            )
            await self._publish_error_event(
                account_id, bot_id, "unknown", str(e)
            )
            return self._error_result(now, "unknown", str(e))

    async def _fetch_and_merge(
        self,
        account_id: str,
        bot_id: str,
    ) -> tuple[RiskLimits, list[str]]:
        """
        Fetch limits from Redis and merge with defaults.

        Merge logic: most restrictive value wins per field.
        Defaults serve as the safety floor (never less restrictive).

        Args:
            account_id: Account ID
            bot_id: Bot ID

        Returns:
            (merged RiskLimits, list of source keys read)
        """
        account_key = RISK_LIMITS_ACCOUNT_KEY.format(account_id=account_id)
        bot_key = RISK_LIMITS_BOT_KEY.format(bot_id=bot_id)
        source_keys = []

        # Fetch with timeout
        async def fetch_with_timeout():
            account_data = await self.redis.get(account_key)
            bot_data = await self.redis.get(bot_key)
            return account_data, bot_data

        account_data, bot_data = await asyncio.wait_for(
            fetch_with_timeout(),
            timeout=REDIS_READ_TIMEOUT_SECONDS,
        )

        # Parse account limits
        account_limits = None
        if account_data is not None:
            source_keys.append(account_key)
            if isinstance(account_data, bytes):
                account_data = account_data.decode()
            account_limits = self._parse_limits(account_data, account_key)

        # Parse bot limits
        bot_limits = None
        if bot_data is not None:
            source_keys.append(bot_key)
            if isinstance(bot_data, bytes):
                bot_data = bot_data.decode()
            bot_limits = self._parse_limits(bot_data, bot_key)

        # Merge: most restrictive wins
        merged = self._merge_limits(account_limits, bot_limits)

        return merged, source_keys

    def _parse_limits(self, raw_json: str, key: str) -> RiskLimits:
        """
        Parse and validate risk limits JSON.

        Expected format (from signals-api):
        {
            "max_trades_per_day": int,
            "max_position_size_usd": float,
            "max_daily_loss_pct": float,
            ...
        }

        Args:
            raw_json: Raw JSON string from Redis
            key: Redis key (for error messages)

        Returns:
            Validated RiskLimits

        Raises:
            json.JSONDecodeError: If JSON is invalid
            ValueError: If values are out of bounds
        """
        data = json.loads(raw_json)

        # Extract and validate fields
        max_position_size_usd = data.get("max_position_size_usd")
        max_trades_per_day = data.get("max_trades_per_day")
        max_daily_loss_pct = data.get("max_daily_loss_pct")

        # Validate bounds
        if max_position_size_usd is not None:
            if not isinstance(max_position_size_usd, (int, float)):
                raise ValueError(f"{key}: max_position_size_usd must be numeric")
            if max_position_size_usd < 0:
                raise ValueError(f"{key}: max_position_size_usd cannot be negative")

        if max_trades_per_day is not None:
            if not isinstance(max_trades_per_day, int):
                # Allow float if it's a whole number
                if isinstance(max_trades_per_day, float) and max_trades_per_day.is_integer():
                    max_trades_per_day = int(max_trades_per_day)
                else:
                    raise ValueError(f"{key}: max_trades_per_day must be integer")
            if max_trades_per_day < 0:
                raise ValueError(f"{key}: max_trades_per_day cannot be negative")

        if max_daily_loss_pct is not None:
            if not isinstance(max_daily_loss_pct, (int, float)):
                raise ValueError(f"{key}: max_daily_loss_pct must be numeric")
            if max_daily_loss_pct < 0 or max_daily_loss_pct > 100:
                raise ValueError(f"{key}: max_daily_loss_pct must be 0-100")

        return RiskLimits(
            max_position_size_usd=max_position_size_usd if max_position_size_usd is not None else self.defaults.max_position_size_usd,
            max_trades_per_day=max_trades_per_day if max_trades_per_day is not None else self.defaults.max_trades_per_day,
            max_daily_loss_pct=max_daily_loss_pct if max_daily_loss_pct is not None else self.defaults.max_daily_loss_pct,
        )

    def _merge_limits(
        self,
        account_limits: RiskLimits | None,
        bot_limits: RiskLimits | None,
    ) -> RiskLimits:
        """
        Merge limits: most restrictive value wins per field.

        Priority: bot (most specific) > account > defaults (floor)

        "Most restrictive" means:
        - max_position_size_usd: LOWER is more restrictive
        - max_trades_per_day: LOWER is more restrictive
        - max_daily_loss_pct: LOWER is more restrictive

        Args:
            account_limits: Account-level limits (or None)
            bot_limits: Bot-level limits (or None)

        Returns:
            Merged RiskLimits (most restrictive per field)
        """
        # Start with defaults
        max_position_size_usd = self.defaults.max_position_size_usd
        max_trades_per_day = self.defaults.max_trades_per_day
        max_daily_loss_pct = self.defaults.max_daily_loss_pct

        # Apply account limits (more restrictive only)
        if account_limits is not None:
            max_position_size_usd = min(max_position_size_usd, account_limits.max_position_size_usd)
            max_trades_per_day = min(max_trades_per_day, account_limits.max_trades_per_day)
            max_daily_loss_pct = min(max_daily_loss_pct, account_limits.max_daily_loss_pct)

        # Apply bot limits (more restrictive only)
        if bot_limits is not None:
            max_position_size_usd = min(max_position_size_usd, bot_limits.max_position_size_usd)
            max_trades_per_day = min(max_trades_per_day, bot_limits.max_trades_per_day)
            max_daily_loss_pct = min(max_daily_loss_pct, bot_limits.max_daily_loss_pct)

        return RiskLimits(
            max_position_size_usd=max_position_size_usd,
            max_trades_per_day=max_trades_per_day,
            max_daily_loss_pct=max_daily_loss_pct,
        )

    def _error_result(
        self,
        now: datetime,
        error_class: str,
        error_message: str,
    ) -> EffectiveRiskLimits:
        """
        Create an error result that blocks trading.

        Uses defaults as limits but marks enforcement_state as error.
        """
        return EffectiveRiskLimits(
            limits=self.defaults,
            meta=RiskLimitsMeta(
                enforcement_state="error",
                fetched_at=now,
                source_keys=[],
                error_message=error_message,
                error_class=error_class,
                cache_hit=False,
            ),
        )

    async def _publish_error_event(
        self,
        account_id: str,
        bot_id: str,
        error_class: str,
        error_message: str,
    ) -> None:
        """
        Publish a controls fetch error event for visibility.

        Args:
            account_id: Account ID
            bot_id: Bot ID
            error_class: Error class (timeout, connection, invalid_payload)
            error_message: Detailed error message
        """
        try:
            payload = {
                "event_type": "risk_limits_fetch_error",
                "account_id": account_id,
                "bot_id": bot_id,
                "error_class": error_class,
                "error_message": error_message,
                "action_taken": "trading_blocked",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            await self.redis.xadd(
                name=CONTROLS_EVENT_STREAM,
                fields={"json": json.dumps(payload).encode()},
                maxlen=5000,
                approximate=True,
            )

            logger.warning(
                f"Published risk_limits_fetch_error event: {error_class}",
                extra={
                    "account_id": account_id,
                    "bot_id": bot_id,
                    "error_class": error_class,
                },
            )

        except Exception as e:
            # Don't fail if event publishing fails - error is already logged
            logger.error(f"Failed to publish error event: {e}")

    def invalidate_cache(self, account_id: str, bot_id: str) -> None:
        """
        Invalidate cached limits for a specific account/bot.

        Call this when limits are known to have changed.

        Args:
            account_id: Account ID
            bot_id: Bot ID
        """
        cache_key = (account_id, bot_id)
        if cache_key in self._cache:
            del self._cache[cache_key]
            logger.debug(f"Invalidated risk limits cache for {account_id}/{bot_id}")

    def clear_cache(self) -> None:
        """Clear all cached limits."""
        self._cache.clear()
        logger.debug("Cleared all risk limits cache")
