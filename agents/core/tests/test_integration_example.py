#!/usr/bin/env python3
"""
Integration example demonstrating serialization and contracts together.

This file shows how to use serialization utilities with contract validation
in realistic scenarios.
"""

from __future__ import annotations

import pytest
import json
import time
from decimal import Decimal
from datetime import datetime, timezone

from agents.core.serialization import (
    json_dumps,
    to_decimal_str,
    serialize_for_redis,
)
from agents.core.contracts import (
    SignalPayload,
    MetricsLatencyPayload,
    HealthStatusPayload,
    validate_signal_payload,
    validate_metrics_latency_payload,
    validate_health_status_payload,
)

try:
    from pydantic import ValidationError
    HAS_PYDANTIC = True
except ImportError:
    HAS_PYDANTIC = False
    ValidationError = Exception  # type: ignore


pytestmark = pytest.mark.skipif(not HAS_PYDANTIC, reason="Pydantic not available")


class TestSignalPublishingWorkflow:
    """Test complete signal publishing workflow."""

    def test_create_validate_serialize_signal(self):
        """Test creating, validating, and serializing a trading signal."""
        # Step 1: Create signal with validation
        signal = SignalPayload(
            id="momentum_001",
            ts=time.time(),
            pair="BTC/USD",
            side="buy",
            entry=50000.0,
            sl=49000.0,
            tp=52000.0,
            strategy="momentum",
            confidence=0.85
        )

        # Step 2: Convert to dict
        signal_dict = signal.model_dump()

        # Step 3: Serialize for Redis
        redis_payload = serialize_for_redis(signal_dict)

        # Step 4: Verify it's valid JSON
        parsed = json.loads(redis_payload)
        assert parsed["pair"] == "BTC/USD"
        assert parsed["side"] == "buy"

        # Step 5: Simulate Redis round-trip
        # (In real code, this would be r.xadd() and r.xread())
        received_dict = json.loads(redis_payload)

        # Step 6: Validate received payload
        received_signal = validate_signal_payload(received_dict)
        assert received_signal.id == signal.id
        assert received_signal.pair == signal.pair

    def test_signal_with_decimal_prices(self):
        """Test signal with Decimal prices (common in trading systems)."""
        # Many trading systems use Decimal for precision
        entry_price = Decimal("50000.12345")
        sl_price = Decimal("49000.00")
        tp_price = Decimal("52000.50")

        # Create signal (will convert to float internally)
        signal = SignalPayload(
            id="sig_001",
            ts=time.time(),
            pair="BTC/USD",
            side="buy",
            entry=float(entry_price),
            sl=float(sl_price),
            tp=float(tp_price),
            strategy="test",
            confidence=0.85
        )

        # Serialize
        payload = serialize_for_redis(signal.model_dump())

        # Verify
        parsed = json.loads(payload)
        assert parsed["entry"] == 50000.12345

    def test_invalid_signal_rejected(self):
        """Test that invalid signals are rejected with clear errors."""
        # Invalid: SL above entry for buy signal
        with pytest.raises(ValueError) as exc_info:
            SignalPayload(
                id="sig_001",
                ts=time.time(),
                pair="BTC/USD",
                side="buy",
                entry=50000.0,
                sl=51000.0,  # Invalid
                tp=52000.0,
                strategy="test",
                confidence=0.85
            )

        error_msg = str(exc_info.value).lower()
        assert "stop loss" in error_msg
        assert "below entry" in error_msg


class TestMetricsPublishingWorkflow:
    """Test complete metrics publishing workflow."""

    def test_create_validate_serialize_metrics(self):
        """Test creating, validating, and serializing latency metrics."""
        # Step 1: Create metrics with validation
        metrics = MetricsLatencyPayload(
            component="kraken_api",
            p50=45.2,
            p95=128.7,
            window_s=60
        )

        # Step 2: Convert to dict
        metrics_dict = metrics.model_dump()

        # Step 3: Serialize for Redis
        redis_payload = serialize_for_redis(metrics_dict)

        # Step 4: Verify it's valid JSON
        parsed = json.loads(redis_payload)
        assert parsed["component"] == "kraken_api"
        assert parsed["p50"] == 45.2

        # Step 5: Simulate Redis round-trip
        received_dict = json.loads(redis_payload)

        # Step 6: Validate received payload
        received_metrics = validate_metrics_latency_payload(received_dict)
        assert received_metrics.component == metrics.component
        assert received_metrics.p50 == metrics.p50

    def test_invalid_metrics_rejected(self):
        """Test that invalid metrics are rejected."""
        # Invalid: p95 < p50
        with pytest.raises(ValueError) as exc_info:
            MetricsLatencyPayload(
                component="test",
                p50=100.0,
                p95=50.0,  # Invalid
                window_s=60
            )

        error_msg = str(exc_info.value).lower()
        assert "p95" in error_msg
        assert "p50" in error_msg


class TestHealthCheckWorkflow:
    """Test complete health check workflow."""

    def test_create_validate_serialize_health(self):
        """Test creating, validating, and serializing health status."""
        # Step 1: Create health status with validation
        health = HealthStatusPayload(
            ok=True,
            checks={
                "redis": True,
                "kraken": True,
                "postgres": True
            }
        )

        # Step 2: Convert to dict
        health_dict = health.model_dump()

        # Step 3: Serialize for Redis
        redis_payload = serialize_for_redis(health_dict)

        # Step 4: Verify it's valid JSON
        parsed = json.loads(redis_payload)
        assert parsed["ok"] is True
        assert parsed["checks"]["redis"] is True

        # Step 5: Simulate Redis round-trip
        received_dict = json.loads(redis_payload)

        # Step 6: Validate received payload
        received_health = validate_health_status_payload(received_dict)
        assert received_health.ok == health.ok
        assert received_health.checks == health.checks

    def test_unhealthy_status(self):
        """Test health status with failed checks."""
        health = HealthStatusPayload(
            ok=False,
            checks={
                "redis": True,
                "kraken": False,  # Failed
                "postgres": True
            }
        )

        # Serialize and deserialize
        payload = serialize_for_redis(health.model_dump())
        parsed = json.loads(payload)

        # Verify
        assert parsed["ok"] is False
        assert parsed["checks"]["kraken"] is False


class TestCompletePublishConsumeWorkflow:
    """Test complete publish-consume workflow simulation."""

    def test_signal_publish_consume_simulation(self):
        """Simulate complete signal publish-consume workflow."""
        # === PUBLISHER SIDE ===

        # Create signal
        signal = SignalPayload(
            id=f"momentum_{int(time.time())}",
            ts=time.time(),
            pair="BTC/USD",
            side="buy",
            entry=50000.0,
            sl=49000.0,
            tp=52000.0,
            strategy="momentum_v2",
            confidence=0.85
        )

        # Validate (automatic in __init__)
        assert signal.pair == "BTC/USD"

        # Serialize for Redis
        redis_payload = serialize_for_redis(signal.model_dump())

        # Simulate Redis XADD
        # In real code: r.xadd("signals:paper", {"payload": redis_payload})
        stream_message = {
            "id": "1697000000000-0",
            "payload": redis_payload
        }

        # === CONSUMER SIDE ===

        # Simulate Redis XREAD
        # In real code: messages = r.xread({"signals:paper": "0-0"})
        received_payload = stream_message["payload"]

        # Deserialize
        payload_dict = json.loads(received_payload)

        # Validate
        received_signal = validate_signal_payload(payload_dict)

        # Verify integrity
        assert received_signal.id == signal.id
        assert received_signal.pair == signal.pair
        assert received_signal.side == signal.side
        assert received_signal.entry == signal.entry
        assert received_signal.strategy == signal.strategy

    def test_multiple_messages_workflow(self):
        """Test publishing and consuming multiple messages."""
        # === PUBLISHER SIDE ===

        messages = []

        # Signal 1: BTC buy
        signal1 = SignalPayload(
            id="sig_001",
            ts=time.time(),
            pair="BTC/USD",
            side="buy",
            entry=50000.0,
            sl=49000.0,
            tp=52000.0,
            strategy="momentum",
            confidence=0.85
        )
        messages.append(serialize_for_redis(signal1.model_dump()))

        # Signal 2: ETH sell
        signal2 = SignalPayload(
            id="sig_002",
            ts=time.time(),
            pair="ETH/USDT",
            side="sell",
            entry=1800.0,
            sl=1850.0,
            tp=1750.0,
            strategy="mean_reversion",
            confidence=0.75
        )
        messages.append(serialize_for_redis(signal2.model_dump()))

        # === CONSUMER SIDE ===

        received_signals = []
        for payload in messages:
            payload_dict = json.loads(payload)
            signal = validate_signal_payload(payload_dict)
            received_signals.append(signal)

        # Verify
        assert len(received_signals) == 2
        assert received_signals[0].pair == "BTC/USD"
        assert received_signals[1].pair == "ETH/USDT"


class TestErrorHandlingWorkflow:
    """Test error handling in realistic scenarios."""

    def test_consumer_handles_invalid_payload(self):
        """Test that consumer gracefully handles invalid payloads."""
        # Simulate invalid payload from Redis
        invalid_payloads = [
            # Missing required field
            {
                "id": "sig_001",
                "ts": time.time(),
                "pair": "BTC/USD",
                "side": "buy",
                # Missing entry, sl, tp
                "strategy": "test",
                "confidence": 0.8
            },
            # Invalid side value
            {
                "id": "sig_002",
                "ts": time.time(),
                "pair": "BTC/USD",
                "side": "long",  # Invalid
                "entry": 50000.0,
                "sl": 49000.0,
                "tp": 52000.0,
                "strategy": "test",
                "confidence": 0.8
            },
        ]

        for invalid_payload in invalid_payloads:
            with pytest.raises(ValidationError):
                validate_signal_payload(invalid_payload)

    def test_consumer_skips_invalid_continues(self):
        """Test that consumer can skip invalid messages and continue."""
        # Mix of valid and invalid payloads
        payloads = [
            # Valid
            {
                "id": "sig_001",
                "ts": time.time(),
                "pair": "BTC/USD",
                "side": "buy",
                "entry": 50000.0,
                "sl": 49000.0,
                "tp": 52000.0,
                "strategy": "test",
                "confidence": 0.8
            },
            # Invalid: missing fields
            {"id": "sig_002", "ts": time.time()},
            # Valid
            {
                "id": "sig_003",
                "ts": time.time(),
                "pair": "ETH/USDT",
                "side": "sell",
                "entry": 1800.0,
                "sl": 1850.0,
                "tp": 1750.0,
                "strategy": "test",
                "confidence": 0.75
            },
        ]

        # Process with error handling
        valid_signals = []
        errors = []

        for payload in payloads:
            try:
                signal = validate_signal_payload(payload)
                valid_signals.append(signal)
            except Exception as e:
                errors.append(str(e))

        # Verify: 2 valid signals, 1 error
        assert len(valid_signals) == 2
        assert len(errors) == 1
        assert valid_signals[0].pair == "BTC/USD"
        assert valid_signals[1].pair == "ETH/USDT"


# Run tests with: pytest agents/core/tests/test_integration_example.py -v
