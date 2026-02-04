"""
Tests for Engine Heartbeat Publisher (Phase 2 Step 2.3).

Verifies:
1. Heartbeat publishes effective limits to Redis
2. Heartbeat updates when limits change
3. Heartbeat shows error state when Redis fails
4. Heartbeat throttles correctly
"""

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from paper.heartbeat import (
    HeartbeatPublisher,
    EngineHeartbeat,
    EffectiveRiskLimitsSnapshot,
    ENGINE_STATUS_KEY,
    MIN_HEARTBEAT_INTERVAL_SECONDS,
)


@pytest.fixture
def mock_redis():
    """Create a mock Redis client."""
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=True)
    return redis


@pytest.fixture
def heartbeat_publisher(mock_redis):
    """Create a HeartbeatPublisher instance."""
    return HeartbeatPublisher(
        redis_client=mock_redis,
        account_id="test_account",
        bot_id="test_bot",
        min_interval_seconds=0.1,  # Short interval for testing
    )


@pytest.fixture
def sample_limits():
    """Sample effective limits snapshot."""
    return EffectiveRiskLimitsSnapshot(
        max_trades_per_day=10,
        max_position_size_usd=1000.0,
        max_daily_loss_pct=5.0,
    )


class TestEngineHeartbeat:
    """Test EngineHeartbeat data class."""

    def test_heartbeat_defaults(self):
        """Test heartbeat with minimal fields."""
        hb = EngineHeartbeat(account_id="test")
        assert hb.account_id == "test"
        assert hb.trading_enabled is True
        assert hb.block_reason is None
        assert hb.risk_limits_source == "default"
        assert hb.updated_at != ""

    def test_heartbeat_with_limits(self, sample_limits):
        """Test heartbeat with effective limits."""
        hb = EngineHeartbeat(
            account_id="test",
            effective_risk_limits=sample_limits,
            risk_limits_source="redis",
        )
        assert hb.effective_risk_limits == sample_limits
        assert hb.risk_limits_source == "redis"

    def test_heartbeat_blocked(self):
        """Test heartbeat in blocked state."""
        hb = EngineHeartbeat(
            account_id="test",
            trading_enabled=False,
            block_reason="GLOBAL_KILL",
            kill_switch_global=True,
        )
        assert hb.trading_enabled is False
        assert hb.block_reason == "GLOBAL_KILL"
        assert hb.kill_switch_global is True

    def test_heartbeat_to_dict(self, sample_limits):
        """Test heartbeat serialization."""
        hb = EngineHeartbeat(
            account_id="test",
            effective_risk_limits=sample_limits,
        )
        data = hb.to_dict()
        assert data["account_id"] == "test"
        assert data["effective_risk_limits"]["max_trades_per_day"] == 10
        assert data["effective_risk_limits"]["max_position_size_usd"] == 1000.0


class TestHeartbeatPublisher:
    """Test HeartbeatPublisher class."""

    @pytest.mark.asyncio
    async def test_publish_success(self, heartbeat_publisher, mock_redis, sample_limits):
        """Test successful heartbeat publish."""
        result = await heartbeat_publisher.publish(
            trading_enabled=True,
            block_reason=None,
            effective_limits=sample_limits,
            limits_source="redis",
            limits_refresh_ts=datetime.now(timezone.utc),
        )

        assert result is True
        mock_redis.set.assert_called_once()

        # Verify the key and payload
        call_args = mock_redis.set.call_args
        key = call_args[0][0]
        payload = json.loads(call_args[0][1])

        assert key == "paper:engine:status:test_account"
        assert payload["account_id"] == "test_account"
        assert payload["trading_enabled"] is True
        assert payload["risk_limits_source"] == "redis"
        assert payload["effective_risk_limits"]["max_trades_per_day"] == 10

    @pytest.mark.asyncio
    async def test_publish_blocked_state(self, heartbeat_publisher, mock_redis, sample_limits):
        """Test publishing blocked state."""
        result = await heartbeat_publisher.publish(
            trading_enabled=False,
            block_reason="ACCOUNT_KILL",
            effective_limits=sample_limits,
            limits_source="default",
            limits_refresh_ts=None,
            kill_switch_account=True,
        )

        assert result is True
        call_args = mock_redis.set.call_args
        payload = json.loads(call_args[0][1])

        assert payload["trading_enabled"] is False
        assert payload["block_reason"] == "ACCOUNT_KILL"
        assert payload["kill_switch_account"] is True

    @pytest.mark.asyncio
    async def test_publish_error_state(self, heartbeat_publisher, mock_redis):
        """Test publishing error state."""
        result = await heartbeat_publisher.publish(
            trading_enabled=False,
            block_reason="REDIS_ERROR",
            effective_limits=None,
            limits_source="error",
            limits_refresh_ts=None,
            last_error="Connection timeout",
        )

        assert result is True
        call_args = mock_redis.set.call_args
        payload = json.loads(call_args[0][1])

        assert payload["trading_enabled"] is False
        assert payload["block_reason"] == "REDIS_ERROR"
        assert payload["risk_limits_source"] == "error"
        assert payload["last_error"] == "Connection timeout"

    @pytest.mark.asyncio
    async def test_publish_throttling(self, mock_redis):
        """Test that publishes are throttled."""
        # Use longer interval for throttle test
        publisher = HeartbeatPublisher(
            redis_client=mock_redis,
            account_id="test",
            min_interval_seconds=10.0,  # 10 second throttle
        )

        limits = EffectiveRiskLimitsSnapshot(
            max_trades_per_day=10,
            max_position_size_usd=1000.0,
            max_daily_loss_pct=5.0,
        )

        # First publish should succeed
        result1 = await publisher.publish(
            trading_enabled=True,
            block_reason=None,
            effective_limits=limits,
            limits_source="redis",
            limits_refresh_ts=datetime.now(timezone.utc),
        )
        assert result1 is True

        # Immediate second publish should be throttled
        result2 = await publisher.publish(
            trading_enabled=True,
            block_reason=None,
            effective_limits=limits,
            limits_source="redis",
            limits_refresh_ts=datetime.now(timezone.utc),
        )
        assert result2 is False

        # Force should bypass throttle
        result3 = await publisher.publish(
            trading_enabled=True,
            block_reason=None,
            effective_limits=limits,
            limits_source="redis",
            limits_refresh_ts=datetime.now(timezone.utc),
            force=True,
        )
        assert result3 is True

    @pytest.mark.asyncio
    async def test_publish_stopped(self, heartbeat_publisher, mock_redis, sample_limits):
        """Test publishing stopped state."""
        # First publish to set last heartbeat
        await heartbeat_publisher.publish(
            trading_enabled=True,
            block_reason=None,
            effective_limits=sample_limits,
            limits_source="redis",
            limits_refresh_ts=datetime.now(timezone.utc),
        )

        # Now publish stopped
        result = await heartbeat_publisher.publish_stopped("Test shutdown")

        assert result is True
        call_args = mock_redis.set.call_args
        payload = json.loads(call_args[0][1])

        assert payload["trading_enabled"] is False
        assert "ENGINE_STOPPED" in payload["block_reason"]

    @pytest.mark.asyncio
    async def test_clear_heartbeat(self, heartbeat_publisher, mock_redis):
        """Test clearing heartbeat key."""
        result = await heartbeat_publisher.clear()

        assert result is True
        mock_redis.delete.assert_called_once_with("paper:engine:status:test_account")

    @pytest.mark.asyncio
    async def test_publish_redis_error_handling(self, mock_redis):
        """Test that Redis errors are handled gracefully."""
        mock_redis.set = AsyncMock(side_effect=Exception("Redis connection failed"))

        publisher = HeartbeatPublisher(
            redis_client=mock_redis,
            account_id="test",
        )

        limits = EffectiveRiskLimitsSnapshot(
            max_trades_per_day=10,
            max_position_size_usd=1000.0,
            max_daily_loss_pct=5.0,
        )

        # Should return False, not raise
        result = await publisher.publish(
            trading_enabled=True,
            block_reason=None,
            effective_limits=limits,
            limits_source="redis",
            limits_refresh_ts=datetime.now(timezone.utc),
        )

        assert result is False


class TestHeartbeatIntegration:
    """Integration tests for heartbeat with engine (mock-based)."""

    @pytest.mark.asyncio
    async def test_heartbeat_reflects_limit_changes(self, mock_redis):
        """Test that heartbeat updates when limits change."""
        publisher = HeartbeatPublisher(
            redis_client=mock_redis,
            account_id="test",
            min_interval_seconds=0,  # No throttle for test
        )

        # Initial limits
        limits1 = EffectiveRiskLimitsSnapshot(
            max_trades_per_day=10,
            max_position_size_usd=1000.0,
            max_daily_loss_pct=5.0,
        )

        await publisher.publish(
            trading_enabled=True,
            block_reason=None,
            effective_limits=limits1,
            limits_source="redis",
            limits_refresh_ts=datetime.now(timezone.utc),
            force=True,
        )

        first_payload = json.loads(mock_redis.set.call_args[0][1])
        assert first_payload["effective_risk_limits"]["max_position_size_usd"] == 1000.0

        # Updated limits (stricter)
        limits2 = EffectiveRiskLimitsSnapshot(
            max_trades_per_day=5,
            max_position_size_usd=500.0,
            max_daily_loss_pct=2.0,
        )

        await publisher.publish(
            trading_enabled=True,
            block_reason=None,
            effective_limits=limits2,
            limits_source="redis",
            limits_refresh_ts=datetime.now(timezone.utc),
            force=True,
        )

        second_payload = json.loads(mock_redis.set.call_args[0][1])
        assert second_payload["effective_risk_limits"]["max_position_size_usd"] == 500.0
        assert second_payload["effective_risk_limits"]["max_trades_per_day"] == 5
