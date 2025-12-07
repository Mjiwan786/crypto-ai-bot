"""
Tests for Engine Telemetry - Week 2 Task B

Verifies telemetry keys are correctly updated and readable.
"""

import pytest
from unittest.mock import Mock, MagicMock
from monitoring.telemetry import (
    EngineTelemetry,
    KEY_LAST_SIGNAL_META,
    KEY_LAST_PNL_META,
    KEY_ENGINE_STATUS,
)


class TestEngineTelemetry:
    """Test EngineTelemetry class"""

    def setup_method(self):
        """Set up mock Redis client"""
        self.mock_redis = Mock()
        self.mock_redis.hset = Mock(return_value=True)
        self.mock_redis.expire = Mock(return_value=True)
        self.telemetry = EngineTelemetry(self.mock_redis, ttl_seconds=300)

    def test_update_last_signal_sync(self):
        """Test updating last signal metadata"""
        result = self.telemetry.update_last_signal_sync(
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            confidence=0.87,
            entry_price=90850.0,
            mode="paper",
            timeframe="5m",
            signal_id="test-123",
        )

        assert result is True
        self.mock_redis.hset.assert_called_once()
        self.mock_redis.expire.assert_called_once()

        # Verify key name
        call_args = self.mock_redis.hset.call_args
        assert call_args[0][0] == KEY_LAST_SIGNAL_META

        # Verify data fields
        data = call_args[1]["mapping"]
        assert data["pair"] == "BTC/USD"
        assert data["side"] == "LONG"
        assert data["strategy"] == "SCALPER"
        assert data["confidence"] == "0.87"
        assert data["entry_price"] == "90850.0"
        assert data["mode"] == "paper"
        assert data["timeframe"] == "5m"
        assert data["signal_id"] == "test-123"
        assert "timestamp" in data
        assert "timestamp_ms" in data

    def test_update_last_signal_normalizes_side(self):
        """Test that side is normalized to uppercase"""
        self.telemetry.update_last_signal_sync(
            pair="BTC/USD",
            side="buy",  # lowercase
            strategy="SCALPER",
            confidence=0.87,
            entry_price=90850.0,
        )

        call_args = self.mock_redis.hset.call_args
        data = call_args[1]["mapping"]
        assert data["side"] == "BUY"  # Should be uppercased

    def test_update_last_pnl_sync(self):
        """Test updating last PnL metadata"""
        result = self.telemetry.update_last_pnl_sync(
            equity=10500.0,
            realized_pnl=500.0,
            unrealized_pnl=100.0,
            num_positions=2,
            drawdown_pct=-2.5,
            mode="paper",
            win_rate=0.64,
            total_trades=142,
        )

        assert result is True
        self.mock_redis.hset.assert_called_once()
        self.mock_redis.expire.assert_called_once()

        # Verify key name
        call_args = self.mock_redis.hset.call_args
        assert call_args[0][0] == KEY_LAST_PNL_META

        # Verify data fields
        data = call_args[1]["mapping"]
        assert data["equity"] == "10500.0"
        assert data["realized_pnl"] == "500.0"
        assert data["unrealized_pnl"] == "100.0"
        assert data["total_pnl"] == "600.0"  # Auto-calculated
        assert data["num_positions"] == "2"
        assert data["drawdown_pct"] == "-2.5"
        assert data["mode"] == "paper"
        assert data["win_rate"] == "0.64"
        assert data["total_trades"] == "142"

    def test_update_engine_status_sync(self):
        """Test updating engine status"""
        result = self.telemetry.update_engine_status_sync(
            status="running",
            mode="paper",
            version="1.0.0",
            pairs=["BTC/USD", "ETH/USD"],
        )

        assert result is True
        self.mock_redis.hset.assert_called_once()
        self.mock_redis.expire.assert_called_once()

        # Verify key name
        call_args = self.mock_redis.hset.call_args
        assert call_args[0][0] == KEY_ENGINE_STATUS

        # Verify data fields
        data = call_args[1]["mapping"]
        assert data["status"] == "running"
        assert data["mode"] == "paper"
        assert data["version"] == "1.0.0"
        assert data["active_pairs"] == "BTC/USD,ETH/USD"
        assert "last_heartbeat" in data
        assert "uptime_seconds" in data

    def test_ttl_is_set(self):
        """Test that TTL is set on telemetry keys"""
        self.telemetry.update_last_signal_sync(
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            confidence=0.87,
            entry_price=90850.0,
        )

        # Verify expire was called with correct TTL
        expire_call = self.mock_redis.expire.call_args
        assert expire_call[0][0] == KEY_LAST_SIGNAL_META
        assert expire_call[0][1] == 300  # TTL seconds

    def test_disabled_telemetry_does_nothing(self):
        """Test that disabled telemetry doesn't call Redis"""
        disabled_telemetry = EngineTelemetry(self.mock_redis, enabled=False)

        result = disabled_telemetry.update_last_signal_sync(
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            confidence=0.87,
            entry_price=90850.0,
        )

        assert result is True  # Still returns True
        self.mock_redis.hset.assert_not_called()  # But doesn't call Redis

    def test_handles_redis_error_gracefully(self):
        """Test that Redis errors are handled gracefully"""
        self.mock_redis.hset.side_effect = Exception("Redis connection error")

        result = self.telemetry.update_last_signal_sync(
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            confidence=0.87,
            entry_price=90850.0,
        )

        assert result is False  # Returns False on error


class TestTelemetryKeyNames:
    """Test telemetry key name constants"""

    def test_key_names_are_correct(self):
        """Verify key names match documentation"""
        assert KEY_LAST_SIGNAL_META == "engine:last_signal_meta"
        assert KEY_LAST_PNL_META == "engine:last_pnl_meta"
        assert KEY_ENGINE_STATUS == "engine:status"


class TestTelemetryFieldStructure:
    """Test telemetry field structures match signals-api expectations"""

    def setup_method(self):
        """Set up mock Redis client"""
        self.mock_redis = Mock()
        self.mock_redis.hset = Mock(return_value=True)
        self.mock_redis.expire = Mock(return_value=True)
        self.telemetry = EngineTelemetry(self.mock_redis)

    def test_signal_meta_has_api_required_fields(self):
        """Verify signal metadata has all fields needed by signals-api"""
        self.telemetry.update_last_signal_sync(
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            confidence=0.87,
            entry_price=90850.0,
            mode="paper",
        )

        call_args = self.mock_redis.hset.call_args
        data = call_args[1]["mapping"]

        # Required fields for signals-api /metrics/system-health
        required_fields = [
            "pair",
            "side",
            "strategy",
            "confidence",
            "entry_price",
            "mode",
            "timestamp",
            "timestamp_ms",
        ]

        for field in required_fields:
            assert field in data, f"Missing required field: {field}"

    def test_pnl_meta_has_api_required_fields(self):
        """Verify PnL metadata has all fields needed by signals-api"""
        self.telemetry.update_last_pnl_sync(
            equity=10500.0,
            realized_pnl=500.0,
            unrealized_pnl=100.0,
            num_positions=2,
            mode="paper",
        )

        call_args = self.mock_redis.hset.call_args
        data = call_args[1]["mapping"]

        # Required fields for signals-api PnL display
        required_fields = [
            "equity",
            "realized_pnl",
            "unrealized_pnl",
            "total_pnl",
            "num_positions",
            "mode",
            "timestamp",
        ]

        for field in required_fields:
            assert field in data, f"Missing required field: {field}"

    def test_engine_status_has_api_required_fields(self):
        """Verify engine status has all fields needed by signals-api"""
        self.telemetry.update_engine_status_sync(
            status="running",
            mode="paper",
        )

        call_args = self.mock_redis.hset.call_args
        data = call_args[1]["mapping"]

        # Required fields for signals-api health check
        required_fields = [
            "status",
            "mode",
            "last_heartbeat",
            "uptime_seconds",
        ]

        for field in required_fields:
            assert field in data, f"Missing required field: {field}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
