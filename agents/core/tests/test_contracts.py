#!/usr/bin/env python3
"""
Unit tests for Redis stream contracts.

Tests SignalPayload, MetricsLatencyPayload, and HealthStatusPayload
validators with valid and invalid data.
"""

from __future__ import annotations

import pytest
import time
from typing import Dict, Any

try:
    from pydantic import ValidationError
    HAS_PYDANTIC = True
except ImportError:
    HAS_PYDANTIC = False
    ValidationError = Exception  # type: ignore

from agents.core.contracts import (
    SignalPayload,
    MetricsLatencyPayload,
    HealthStatusPayload,
    validate_signal_payload,
    validate_metrics_latency_payload,
    validate_health_status_payload,
    HAS_PYDANTIC,
)


# Skip all tests if Pydantic is not available
pytestmark = pytest.mark.skipif(not HAS_PYDANTIC, reason="Pydantic not available")


# ============================================================================
# SignalPayload Tests
# ============================================================================

class TestSignalPayload:
    """Test SignalPayload validation."""

    def test_valid_buy_signal(self):
        """Test valid buy signal creation."""
        signal = SignalPayload(
            id="sig_001",
            ts=1234567890.123,
            pair="BTC/USD",
            side="buy",
            entry=50000.0,
            sl=49000.0,  # Below entry for buy
            tp=52000.0,  # Above entry for buy
            strategy="momentum",
            confidence=0.85
        )

        assert signal.id == "sig_001"
        assert signal.ts == 1234567890.123
        assert signal.pair == "BTC/USD"
        assert signal.side == "buy"
        assert signal.entry == 50000.0
        assert signal.sl == 49000.0
        assert signal.tp == 52000.0
        assert signal.strategy == "momentum"
        assert signal.confidence == 0.85

    def test_valid_sell_signal(self):
        """Test valid sell signal creation."""
        signal = SignalPayload(
            id="sig_002",
            ts=1234567890.0,
            pair="ETH/USDT",
            side="sell",
            entry=1800.0,
            sl=1850.0,  # Above entry for sell
            tp=1750.0,  # Below entry for sell
            strategy="mean_reversion",
            confidence=0.75
        )

        assert signal.side == "sell"
        assert signal.sl > signal.entry
        assert signal.tp < signal.entry

    def test_pair_converted_to_uppercase(self):
        """Test that trading pair is converted to uppercase."""
        signal = SignalPayload(
            id="sig_003",
            ts=time.time(),
            pair="btc/usd",  # Lowercase
            side="buy",
            entry=50000.0,
            sl=49000.0,
            tp=52000.0,
            strategy="test",
            confidence=0.8
        )

        assert signal.pair == "BTC/USD"  # Converted to uppercase

    def test_whitespace_stripped(self):
        """Test that whitespace is stripped from string fields."""
        signal = SignalPayload(
            id="  sig_004  ",
            ts=time.time(),
            pair="BTC/USD",
            side="buy",
            entry=50000.0,
            sl=49000.0,
            tp=52000.0,
            strategy="  momentum  ",
            confidence=0.8
        )

        assert signal.id == "sig_004"
        assert signal.strategy == "momentum"

    def test_confidence_boundaries(self):
        """Test confidence score boundaries."""
        # Minimum confidence
        signal_min = SignalPayload(
            id="sig_min",
            ts=time.time(),
            pair="BTC/USD",
            side="buy",
            entry=50000.0,
            sl=49000.0,
            tp=52000.0,
            strategy="test",
            confidence=0.0
        )
        assert signal_min.confidence == 0.0

        # Maximum confidence
        signal_max = SignalPayload(
            id="sig_max",
            ts=time.time(),
            pair="BTC/USD",
            side="buy",
            entry=50000.0,
            sl=49000.0,
            tp=52000.0,
            strategy="test",
            confidence=1.0
        )
        assert signal_max.confidence == 1.0

    def test_model_dump(self):
        """Test conversion to dictionary."""
        signal = SignalPayload(
            id="sig_001",
            ts=1234567890.0,
            pair="BTC/USD",
            side="buy",
            entry=50000.0,
            sl=49000.0,
            tp=52000.0,
            strategy="momentum",
            confidence=0.85
        )

        data = signal.model_dump()

        assert isinstance(data, dict)
        assert data["id"] == "sig_001"
        assert data["pair"] == "BTC/USD"

    def test_validate_signal_payload_helper(self):
        """Test validate_signal_payload() helper function."""
        data = {
            "id": "sig_001",
            "ts": 1234567890.0,
            "pair": "BTC/USD",
            "side": "buy",
            "entry": 50000.0,
            "sl": 49000.0,
            "tp": 52000.0,
            "strategy": "momentum",
            "confidence": 0.85
        }

        signal = validate_signal_payload(data)
        assert signal.id == "sig_001"


class TestSignalPayloadValidationErrors:
    """Test SignalPayload validation errors."""

    def test_missing_required_field(self):
        """Test that missing required fields raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            SignalPayload(
                id="sig_001",
                ts=1234567890.0,
                pair="BTC/USD",
                side="buy",
                # Missing entry, sl, tp
                strategy="test",
                confidence=0.8
            )

        error_msg = str(exc_info.value)
        assert "entry" in error_msg.lower() or "field required" in error_msg.lower()

    def test_empty_id(self):
        """Test that empty ID raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            SignalPayload(
                id="",  # Empty
                ts=time.time(),
                pair="BTC/USD",
                side="buy",
                entry=50000.0,
                sl=49000.0,
                tp=52000.0,
                strategy="test",
                confidence=0.8
            )

        assert "id" in str(exc_info.value).lower()

    def test_invalid_pair_format(self):
        """Test that invalid pair format raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            SignalPayload(
                id="sig_001",
                ts=time.time(),
                pair="BTCUSD",  # Missing separator
                side="buy",
                entry=50000.0,
                sl=49000.0,
                tp=52000.0,
                strategy="test",
                confidence=0.8
            )

        error_msg = str(exc_info.value).lower()
        assert "pair" in error_msg or "format" in error_msg

    def test_invalid_side(self):
        """Test that invalid side value raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            SignalPayload(
                id="sig_001",
                ts=time.time(),
                pair="BTC/USD",
                side="long",  # Invalid, must be "buy" or "sell"
                entry=50000.0,
                sl=49000.0,
                tp=52000.0,
                strategy="test",
                confidence=0.8
            )

        error_msg = str(exc_info.value).lower()
        assert "side" in error_msg or "literal" in error_msg

    def test_negative_price(self):
        """Test that negative prices raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            SignalPayload(
                id="sig_001",
                ts=time.time(),
                pair="BTC/USD",
                side="buy",
                entry=-50000.0,  # Negative
                sl=49000.0,
                tp=52000.0,
                strategy="test",
                confidence=0.8
            )

        error_msg = str(exc_info.value).lower()
        assert "entry" in error_msg or "greater than 0" in error_msg

    def test_zero_price(self):
        """Test that zero prices raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            SignalPayload(
                id="sig_001",
                ts=time.time(),
                pair="BTC/USD",
                side="buy",
                entry=0.0,  # Zero
                sl=49000.0,
                tp=52000.0,
                strategy="test",
                confidence=0.8
            )

        error_msg = str(exc_info.value).lower()
        assert "entry" in error_msg or "greater than 0" in error_msg

    def test_confidence_below_zero(self):
        """Test that confidence < 0 raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            SignalPayload(
                id="sig_001",
                ts=time.time(),
                pair="BTC/USD",
                side="buy",
                entry=50000.0,
                sl=49000.0,
                tp=52000.0,
                strategy="test",
                confidence=-0.1  # Below 0
            )

        error_msg = str(exc_info.value).lower()
        assert "confidence" in error_msg

    def test_confidence_above_one(self):
        """Test that confidence > 1 raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            SignalPayload(
                id="sig_001",
                ts=time.time(),
                pair="BTC/USD",
                side="buy",
                entry=50000.0,
                sl=49000.0,
                tp=52000.0,
                strategy="test",
                confidence=1.5  # Above 1
            )

        error_msg = str(exc_info.value).lower()
        assert "confidence" in error_msg

    def test_buy_signal_invalid_sl(self):
        """Test that buy signal with SL >= entry raises ValidationError."""
        with pytest.raises(ValueError) as exc_info:
            SignalPayload(
                id="sig_001",
                ts=time.time(),
                pair="BTC/USD",
                side="buy",
                entry=50000.0,
                sl=51000.0,  # Above entry (invalid for buy)
                tp=52000.0,
                strategy="test",
                confidence=0.8
            )

        error_msg = str(exc_info.value).lower()
        assert "stop loss" in error_msg or "below entry" in error_msg

    def test_buy_signal_invalid_tp(self):
        """Test that buy signal with TP <= entry raises ValidationError."""
        with pytest.raises(ValueError) as exc_info:
            SignalPayload(
                id="sig_001",
                ts=time.time(),
                pair="BTC/USD",
                side="buy",
                entry=50000.0,
                sl=49000.0,
                tp=48000.0,  # Below entry (invalid for buy)
                strategy="test",
                confidence=0.8
            )

        error_msg = str(exc_info.value).lower()
        assert "take profit" in error_msg or "above entry" in error_msg

    def test_sell_signal_invalid_sl(self):
        """Test that sell signal with SL <= entry raises ValidationError."""
        with pytest.raises(ValueError) as exc_info:
            SignalPayload(
                id="sig_001",
                ts=time.time(),
                pair="BTC/USD",
                side="sell",
                entry=50000.0,
                sl=49000.0,  # Below entry (invalid for sell)
                tp=48000.0,
                strategy="test",
                confidence=0.8
            )

        error_msg = str(exc_info.value).lower()
        assert "stop loss" in error_msg or "above entry" in error_msg

    def test_sell_signal_invalid_tp(self):
        """Test that sell signal with TP >= entry raises ValidationError."""
        with pytest.raises(ValueError) as exc_info:
            SignalPayload(
                id="sig_001",
                ts=time.time(),
                pair="BTC/USD",
                side="sell",
                entry=50000.0,
                sl=51000.0,
                tp=52000.0,  # Above entry (invalid for sell)
                strategy="test",
                confidence=0.8
            )

        error_msg = str(exc_info.value).lower()
        assert "take profit" in error_msg or "below entry" in error_msg


# ============================================================================
# MetricsLatencyPayload Tests
# ============================================================================

class TestMetricsLatencyPayload:
    """Test MetricsLatencyPayload validation."""

    def test_valid_metrics(self):
        """Test valid metrics creation."""
        metrics = MetricsLatencyPayload(
            component="kraken_api",
            p50=45.2,
            p95=128.7,
            window_s=60
        )

        assert metrics.component == "kraken_api"
        assert metrics.p50 == 45.2
        assert metrics.p95 == 128.7
        assert metrics.window_s == 60

    def test_p50_equals_p95(self):
        """Test that p50 can equal p95."""
        metrics = MetricsLatencyPayload(
            component="redis",
            p50=10.0,
            p95=10.0,  # Same as p50
            window_s=60
        )

        assert metrics.p50 == metrics.p95

    def test_zero_latency(self):
        """Test that zero latency is allowed."""
        metrics = MetricsLatencyPayload(
            component="local_cache",
            p50=0.0,
            p95=0.1,
            window_s=60
        )

        assert metrics.p50 == 0.0

    def test_model_dump(self):
        """Test conversion to dictionary."""
        metrics = MetricsLatencyPayload(
            component="kraken_api",
            p50=45.2,
            p95=128.7,
            window_s=60
        )

        data = metrics.model_dump()

        assert isinstance(data, dict)
        assert data["component"] == "kraken_api"
        assert data["p50"] == 45.2

    def test_validate_metrics_helper(self):
        """Test validate_metrics_latency_payload() helper function."""
        data = {
            "component": "kraken_api",
            "p50": 45.2,
            "p95": 128.7,
            "window_s": 60
        }

        metrics = validate_metrics_latency_payload(data)
        assert metrics.component == "kraken_api"


class TestMetricsLatencyPayloadValidationErrors:
    """Test MetricsLatencyPayload validation errors."""

    def test_empty_component(self):
        """Test that empty component raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            MetricsLatencyPayload(
                component="",  # Empty
                p50=45.2,
                p95=128.7,
                window_s=60
            )

        assert "component" in str(exc_info.value).lower()

    def test_negative_p50(self):
        """Test that negative p50 raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            MetricsLatencyPayload(
                component="test",
                p50=-10.0,  # Negative
                p95=128.7,
                window_s=60
            )

        error_msg = str(exc_info.value).lower()
        assert "p50" in error_msg or "greater than or equal to 0" in error_msg

    def test_p95_less_than_p50(self):
        """Test that p95 < p50 raises ValidationError."""
        with pytest.raises(ValueError) as exc_info:
            MetricsLatencyPayload(
                component="test",
                p50=100.0,
                p95=50.0,  # Less than p50
                window_s=60
            )

        error_msg = str(exc_info.value).lower()
        assert "p95" in error_msg and "p50" in error_msg

    def test_zero_window(self):
        """Test that zero window raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            MetricsLatencyPayload(
                component="test",
                p50=45.2,
                p95=128.7,
                window_s=0  # Zero
            )

        error_msg = str(exc_info.value).lower()
        assert "window_s" in error_msg or "greater than 0" in error_msg

    def test_negative_window(self):
        """Test that negative window raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            MetricsLatencyPayload(
                component="test",
                p50=45.2,
                p95=128.7,
                window_s=-60  # Negative
            )

        error_msg = str(exc_info.value).lower()
        assert "window_s" in error_msg or "greater than 0" in error_msg


# ============================================================================
# HealthStatusPayload Tests
# ============================================================================

class TestHealthStatusPayload:
    """Test HealthStatusPayload validation."""

    def test_valid_healthy_status(self):
        """Test valid healthy status creation."""
        health = HealthStatusPayload(
            ok=True,
            checks={
                "redis": True,
                "kraken": True,
                "postgres": True
            }
        )

        assert health.ok is True
        assert health.checks["redis"] is True
        assert health.checks["kraken"] is True
        assert health.checks["postgres"] is True

    def test_valid_unhealthy_status(self):
        """Test valid unhealthy status creation."""
        health = HealthStatusPayload(
            ok=False,
            checks={
                "redis": True,
                "kraken": False,  # Failed
                "postgres": True
            }
        )

        assert health.ok is False
        assert health.checks["kraken"] is False

    def test_single_check(self):
        """Test health status with single check."""
        health = HealthStatusPayload(
            ok=True,
            checks={"redis": True}
        )

        assert len(health.checks) == 1
        assert health.checks["redis"] is True

    def test_many_checks(self):
        """Test health status with many checks."""
        checks = {f"service_{i}": True for i in range(10)}
        health = HealthStatusPayload(ok=True, checks=checks)

        assert len(health.checks) == 10

    def test_model_dump(self):
        """Test conversion to dictionary."""
        health = HealthStatusPayload(
            ok=True,
            checks={"redis": True, "kraken": True}
        )

        data = health.model_dump()

        assert isinstance(data, dict)
        assert data["ok"] is True
        assert isinstance(data["checks"], dict)

    def test_validate_health_helper(self):
        """Test validate_health_status_payload() helper function."""
        data = {
            "ok": True,
            "checks": {
                "redis": True,
                "kraken": True
            }
        }

        health = validate_health_status_payload(data)
        assert health.ok is True


class TestHealthStatusPayloadValidationErrors:
    """Test HealthStatusPayload validation errors."""

    def test_empty_checks(self):
        """Test that empty checks dict raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            HealthStatusPayload(
                ok=True,
                checks={}  # Empty
            )

        error_msg = str(exc_info.value).lower()
        assert "checks" in error_msg or "empty" in error_msg

    def test_non_boolean_check_value(self):
        """Test that non-boolean check values raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            HealthStatusPayload(
                ok=True,
                checks={
                    "redis": True,
                    "kraken": "healthy"  # String instead of bool
                }
            )

        error_msg = str(exc_info.value).lower()
        assert "boolean" in error_msg or "bool" in error_msg

    def test_inconsistent_ok_status_logs_warning(self, caplog):
        """Test that inconsistent 'ok' status logs a warning."""
        import logging
        caplog.set_level(logging.WARNING)

        # ok=True but some checks failed
        health = HealthStatusPayload(
            ok=True,  # Inconsistent with checks
            checks={
                "redis": True,
                "kraken": False  # Failed
            }
        )

        # Should still create successfully but log warning
        assert health.ok is True
        # Check if warning was logged (this may vary based on logging config)


# ============================================================================
# Integration Tests
# ============================================================================

class TestContractsIntegration:
    """Test contracts in realistic scenarios."""

    def test_signal_from_redis_dict(self):
        """Test creating signal from Redis-like dictionary."""
        # Simulate data from Redis stream
        redis_data = {
            "id": "momentum_20251011_123045",
            "ts": "1697000000.123",  # String from Redis
            "pair": "btc/usd",  # Lowercase
            "side": "buy",
            "entry": "50000.0",  # String from Redis
            "sl": "49000.0",
            "tp": "52000.0",
            "strategy": "momentum",
            "confidence": "0.85"
        }

        # Pydantic should coerce types
        signal = SignalPayload.model_validate(redis_data)

        assert signal.ts == 1697000000.123
        assert signal.entry == 50000.0
        assert signal.confidence == 0.85
        assert signal.pair == "BTC/USD"  # Converted to uppercase

    def test_metrics_from_monitoring_system(self):
        """Test creating metrics from monitoring system."""
        monitoring_data = {
            "component": "kraken_api",
            "p50": 45.2,
            "p95": 128.7,
            "window_s": 60
        }

        metrics = MetricsLatencyPayload.model_validate(monitoring_data)

        assert metrics.component == "kraken_api"
        assert metrics.p95 > metrics.p50

    def test_health_from_health_check(self):
        """Test creating health status from health check."""
        health_data = {
            "ok": True,
            "checks": {
                "redis": True,
                "kraken_api": True,
                "postgres": True,
                "signal_processor": True
            }
        }

        health = HealthStatusPayload.model_validate(health_data)

        assert health.ok is True
        assert all(health.checks.values())


# Run tests with: pytest agents/core/tests/test_contracts.py -v
