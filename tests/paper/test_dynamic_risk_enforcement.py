"""
Tests for Phase 2 Step 2.2: Dynamic Risk Enforcement.

Tests verify:
1. Cached limits refresh applies without restart
2. Bot limits override account limits (most restrictive wins)
3. Redis failure blocks trading (RISK_LIMITS_UNAVAILABLE)
4. Invalid payload blocks trading
"""

import asyncio
import json
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from backtest.risk_evaluator import RiskLimits
from paper.risk_limits_provider import (
    RiskLimitsProvider,
    EffectiveRiskLimits,
    RiskLimitsMeta,
    CachedLimits,
    RISK_LIMITS_ACCOUNT_KEY,
    RISK_LIMITS_BOT_KEY,
)


class FakeRedis:
    """Fake Redis client for testing."""

    def __init__(self):
        self.data: dict[str, str] = {}
        self.should_timeout = False
        self.should_raise_connection_error = False
        self.xadd_calls: list[dict] = []

    async def get(self, key: str) -> bytes | None:
        if self.should_timeout:
            raise asyncio.TimeoutError("Simulated timeout")
        if self.should_raise_connection_error:
            raise ConnectionError("Simulated connection error")
        value = self.data.get(key)
        return value.encode() if value else None

    async def set(self, key: str, value: str) -> None:
        self.data[key] = value

    async def xadd(self, name: str, fields: dict, **kwargs) -> bytes:
        self.xadd_calls.append({"name": name, "fields": fields, **kwargs})
        return b"1234567890-0"

    def set_limits(self, account_id: str = None, bot_id: str = None, limits: dict = None):
        """Helper to set limits in fake Redis."""
        if account_id and limits:
            key = RISK_LIMITS_ACCOUNT_KEY.format(account_id=account_id)
            self.data[key] = json.dumps(limits)
        if bot_id and limits:
            key = RISK_LIMITS_BOT_KEY.format(bot_id=bot_id)
            self.data[key] = json.dumps(limits)


@pytest.fixture
def fake_redis():
    return FakeRedis()


@pytest.fixture
def default_limits():
    return RiskLimits(
        max_position_size_usd=1000.0,
        max_trades_per_day=10,
        max_daily_loss_pct=5.0,
    )


@pytest.fixture
def provider(fake_redis, default_limits):
    return RiskLimitsProvider(
        redis_client=fake_redis,
        defaults=default_limits,
        cache_ttl_seconds=1.0,  # Short TTL for testing
    )


class TestRiskLimitsProvider:
    """Tests for RiskLimitsProvider."""

    @pytest.mark.asyncio
    async def test_returns_defaults_when_no_redis_limits(self, provider, default_limits):
        """When Redis has no limits, should return defaults."""
        result = await provider.get_effective_limits("account_1", "bot_1")

        assert result.can_trade is True
        assert result.limits == default_limits
        assert result.meta.enforcement_state == "ok"
        assert result.meta.source_keys == []

    @pytest.mark.asyncio
    async def test_returns_account_limits_from_redis(self, provider, fake_redis):
        """Should fetch and apply account limits from Redis."""
        fake_redis.set_limits(
            account_id="account_1",
            limits={
                "max_position_size_usd": 500.0,
                "max_trades_per_day": 5,
                "max_daily_loss_pct": 3.0,
            },
        )

        result = await provider.get_effective_limits("account_1", "bot_1")

        assert result.can_trade is True
        assert result.limits.max_position_size_usd == 500.0
        assert result.limits.max_trades_per_day == 5
        assert result.limits.max_daily_loss_pct == 3.0
        assert "paper:risk:account:account_1" in result.meta.source_keys

    @pytest.mark.asyncio
    async def test_bot_limits_override_account_more_restrictive(self, provider, fake_redis):
        """Bot limits should override account limits when more restrictive."""
        # Account allows 500 USD, bot limits to 200 USD
        fake_redis.set_limits(
            account_id="account_1",
            limits={
                "max_position_size_usd": 500.0,
                "max_trades_per_day": 10,
                "max_daily_loss_pct": 5.0,
            },
        )
        fake_redis.set_limits(
            bot_id="bot_1",
            limits={
                "max_position_size_usd": 200.0,  # More restrictive
                "max_trades_per_day": 3,  # More restrictive
                "max_daily_loss_pct": 2.0,  # More restrictive
            },
        )

        result = await provider.get_effective_limits("account_1", "bot_1")

        # Bot limits win (more restrictive)
        assert result.limits.max_position_size_usd == 200.0
        assert result.limits.max_trades_per_day == 3
        assert result.limits.max_daily_loss_pct == 2.0
        assert "paper:risk:account:account_1" in result.meta.source_keys
        assert "paper:risk:bot:bot_1" in result.meta.source_keys

    @pytest.mark.asyncio
    async def test_account_limits_override_bot_more_restrictive(self, provider, fake_redis):
        """When account is more restrictive, it should win."""
        # Account limits to 100 USD, bot allows 500 USD
        fake_redis.set_limits(
            account_id="account_1",
            limits={
                "max_position_size_usd": 100.0,  # More restrictive
                "max_trades_per_day": 2,  # More restrictive
                "max_daily_loss_pct": 1.0,  # More restrictive
            },
        )
        fake_redis.set_limits(
            bot_id="bot_1",
            limits={
                "max_position_size_usd": 500.0,
                "max_trades_per_day": 10,
                "max_daily_loss_pct": 5.0,
            },
        )

        result = await provider.get_effective_limits("account_1", "bot_1")

        # Account limits win (more restrictive)
        assert result.limits.max_position_size_usd == 100.0
        assert result.limits.max_trades_per_day == 2
        assert result.limits.max_daily_loss_pct == 1.0

    @pytest.mark.asyncio
    async def test_defaults_as_safety_floor(self, provider, fake_redis, default_limits):
        """Defaults should serve as floor even if Redis limits are less restrictive."""
        # Redis allows 2000 USD, but defaults only allow 1000
        fake_redis.set_limits(
            account_id="account_1",
            limits={
                "max_position_size_usd": 2000.0,  # Less restrictive than default
                "max_trades_per_day": 20,  # Less restrictive than default
                "max_daily_loss_pct": 10.0,  # Less restrictive than default
            },
        )

        result = await provider.get_effective_limits("account_1", "bot_1")

        # Defaults win (more restrictive)
        assert result.limits.max_position_size_usd == default_limits.max_position_size_usd
        assert result.limits.max_trades_per_day == default_limits.max_trades_per_day
        assert result.limits.max_daily_loss_pct == default_limits.max_daily_loss_pct


class TestCaching:
    """Tests for caching behavior."""

    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached_limits(self, provider, fake_redis):
        """Second call within TTL should return cached result."""
        fake_redis.set_limits(
            account_id="account_1",
            limits={"max_position_size_usd": 500.0},
        )

        # First call - fetches from Redis
        result1 = await provider.get_effective_limits("account_1", "bot_1")
        assert result1.meta.cache_hit is False

        # Second call - should use cache
        result2 = await provider.get_effective_limits("account_1", "bot_1")
        assert result2.meta.cache_hit is True
        assert result2.limits == result1.limits

    @pytest.mark.asyncio
    async def test_limits_refresh_applies_without_restart(self, provider, fake_redis):
        """Changed limits should take effect after cache expires."""
        # Initial limits
        fake_redis.set_limits(
            account_id="account_1",
            limits={"max_position_size_usd": 500.0},
        )

        result1 = await provider.get_effective_limits("account_1", "bot_1")
        assert result1.limits.max_position_size_usd == 500.0

        # Change limits in Redis
        fake_redis.set_limits(
            account_id="account_1",
            limits={"max_position_size_usd": 100.0},  # Changed!
        )

        # Wait for cache to expire (TTL is 1 second in test)
        await asyncio.sleep(1.1)

        # Should fetch new limits
        result2 = await provider.get_effective_limits("account_1", "bot_1")
        assert result2.limits.max_position_size_usd == 100.0
        assert result2.meta.cache_hit is False

    @pytest.mark.asyncio
    async def test_invalidate_cache_forces_refresh(self, provider, fake_redis):
        """Invalidating cache should force next call to fetch from Redis."""
        fake_redis.set_limits(
            account_id="account_1",
            limits={"max_position_size_usd": 500.0},
        )

        # First call populates cache
        await provider.get_effective_limits("account_1", "bot_1")

        # Change limits
        fake_redis.set_limits(
            account_id="account_1",
            limits={"max_position_size_usd": 100.0},
        )

        # Invalidate cache
        provider.invalidate_cache("account_1", "bot_1")

        # Should fetch new limits immediately
        result = await provider.get_effective_limits("account_1", "bot_1")
        assert result.limits.max_position_size_usd == 100.0
        assert result.meta.cache_hit is False


class TestRedisFailure:
    """Tests for Redis failure handling."""

    @pytest.mark.asyncio
    async def test_redis_timeout_blocks_trading(self, provider, fake_redis):
        """Redis timeout should block trading with error state."""
        fake_redis.should_timeout = True

        result = await provider.get_effective_limits("account_1", "bot_1")

        assert result.can_trade is False
        assert result.meta.enforcement_state == "error"
        assert result.meta.error_class == "timeout"
        assert "timeout" in result.meta.error_message.lower()

    @pytest.mark.asyncio
    async def test_redis_connection_error_blocks_trading(self, provider, fake_redis):
        """Redis connection error should block trading."""
        fake_redis.should_raise_connection_error = True

        result = await provider.get_effective_limits("account_1", "bot_1")

        assert result.can_trade is False
        assert result.meta.enforcement_state == "error"
        assert result.meta.error_class == "connection"

    @pytest.mark.asyncio
    async def test_error_event_published_on_failure(self, provider, fake_redis):
        """Error event should be published when Redis fails."""
        fake_redis.should_timeout = True

        await provider.get_effective_limits("account_1", "bot_1")

        # Check that error event was published
        assert len(fake_redis.xadd_calls) == 1
        call = fake_redis.xadd_calls[0]
        assert call["name"] == "events:paper:controls"

        payload = json.loads(call["fields"]["json"])
        assert payload["event_type"] == "risk_limits_fetch_error"
        assert payload["account_id"] == "account_1"
        assert payload["bot_id"] == "bot_1"
        assert payload["error_class"] == "timeout"
        assert payload["action_taken"] == "trading_blocked"


class TestInvalidPayload:
    """Tests for invalid Redis payload handling."""

    @pytest.mark.asyncio
    async def test_invalid_json_blocks_trading(self, provider, fake_redis):
        """Invalid JSON should block trading."""
        key = RISK_LIMITS_ACCOUNT_KEY.format(account_id="account_1")
        fake_redis.data[key] = "not valid json {{"

        result = await provider.get_effective_limits("account_1", "bot_1")

        assert result.can_trade is False
        assert result.meta.enforcement_state == "error"
        assert result.meta.error_class == "invalid_payload"

    @pytest.mark.asyncio
    async def test_negative_position_size_blocks_trading(self, provider, fake_redis):
        """Negative max_position_size_usd should block trading."""
        fake_redis.set_limits(
            account_id="account_1",
            limits={"max_position_size_usd": -100.0},  # Invalid!
        )

        result = await provider.get_effective_limits("account_1", "bot_1")

        assert result.can_trade is False
        assert result.meta.enforcement_state == "error"
        assert result.meta.error_class == "invalid_payload"

    @pytest.mark.asyncio
    async def test_invalid_daily_loss_pct_blocks_trading(self, provider, fake_redis):
        """Daily loss percent > 100 should block trading."""
        fake_redis.set_limits(
            account_id="account_1",
            limits={"max_daily_loss_pct": 150.0},  # Invalid - over 100%
        )

        result = await provider.get_effective_limits("account_1", "bot_1")

        assert result.can_trade is False
        assert result.meta.enforcement_state == "error"
        assert result.meta.error_class == "invalid_payload"

    @pytest.mark.asyncio
    async def test_non_numeric_value_blocks_trading(self, provider, fake_redis):
        """Non-numeric values should block trading."""
        fake_redis.set_limits(
            account_id="account_1",
            limits={"max_position_size_usd": "not a number"},
        )

        result = await provider.get_effective_limits("account_1", "bot_1")

        assert result.can_trade is False
        assert result.meta.enforcement_state == "error"
        assert result.meta.error_class == "invalid_payload"


class TestMergeLogic:
    """Tests for limit merge logic edge cases."""

    @pytest.mark.asyncio
    async def test_partial_bot_limits_merge_with_account(self, provider, fake_redis):
        """Bot with only some fields should merge with account for others."""
        fake_redis.set_limits(
            account_id="account_1",
            limits={
                "max_position_size_usd": 500.0,
                "max_trades_per_day": 10,
                "max_daily_loss_pct": 5.0,
            },
        )
        # Bot only sets position size
        fake_redis.set_limits(
            bot_id="bot_1",
            limits={
                "max_position_size_usd": 200.0,  # Override
                # Other fields not set - should use account values
            },
        )

        result = await provider.get_effective_limits("account_1", "bot_1")

        # Bot overrides position size
        assert result.limits.max_position_size_usd == 200.0
        # Account values used for others (as they're parsed with defaults)
        assert result.limits.max_trades_per_day == 10
        assert result.limits.max_daily_loss_pct == 5.0

    @pytest.mark.asyncio
    async def test_mixed_restrictiveness(self, provider, fake_redis):
        """Each field should pick the most restrictive value independently."""
        fake_redis.set_limits(
            account_id="account_1",
            limits={
                "max_position_size_usd": 100.0,  # Account more restrictive
                "max_trades_per_day": 20,  # Account less restrictive
                "max_daily_loss_pct": 1.0,  # Account more restrictive
            },
        )
        fake_redis.set_limits(
            bot_id="bot_1",
            limits={
                "max_position_size_usd": 500.0,  # Bot less restrictive
                "max_trades_per_day": 5,  # Bot more restrictive
                "max_daily_loss_pct": 10.0,  # Bot less restrictive
            },
        )

        result = await provider.get_effective_limits("account_1", "bot_1")

        # Most restrictive per field
        assert result.limits.max_position_size_usd == 100.0  # Account
        assert result.limits.max_trades_per_day == 5  # Bot
        assert result.limits.max_daily_loss_pct == 1.0  # Account
