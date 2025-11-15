#!/usr/bin/env python3
"""
Unit Tests for Signal Schema Validation
========================================

Tests:
- Valid signal payloads
- Invalid signal payloads (validation errors)
- Freshness/lag calculators
- Clock drift detection
"""

import pytest
import time
from signals.scalper_schema import ScalperSignal


class TestSignalSchemaValidation:
    """Test signal schema validation"""

    def test_valid_signal_creation(self):
        """Test creating a valid signal"""
        now_ms = int(time.time() * 1000)

        signal = ScalperSignal(
            ts_exchange=now_ms - 100,
            ts_server=now_ms - 50,
            symbol="BTC/USD",
            timeframe="15s",
            side="long",
            confidence=0.85,
            entry=45000.0,
            stop=44500.0,
            tp=46000.0,
            model="test_model_v1",
            trace_id="test-trace-001",
        )

        assert signal.symbol == "BTC/USD"
        assert signal.side == "long"
        assert signal.confidence == 0.85
        assert signal.entry == 45000.0

    def test_invalid_confidence_too_low(self):
        """Test that confidence < 0 raises validation error"""
        now_ms = int(time.time() * 1000)

        with pytest.raises(ValueError):
            ScalperSignal(
                ts_exchange=now_ms,
                ts_server=now_ms,
                symbol="BTC/USD",
                timeframe="15s",
                side="long",
                confidence=-0.1,  # Invalid: < 0
                entry=45000.0,
                stop=44500.0,
                tp=46000.0,
                model="test_model",
                trace_id="test-001",
            )

    def test_invalid_confidence_too_high(self):
        """Test that confidence > 1 raises validation error"""
        now_ms = int(time.time() * 1000)

        with pytest.raises(ValueError):
            ScalperSignal(
                ts_exchange=now_ms,
                ts_server=now_ms,
                symbol="BTC/USD",
                timeframe="15s",
                side="long",
                confidence=1.5,  # Invalid: > 1
                entry=45000.0,
                stop=44500.0,
                tp=46000.0,
                model="test_model",
                trace_id="test-001",
            )

    def test_invalid_side(self):
        """Test that invalid side raises validation error"""
        now_ms = int(time.time() * 1000)

        with pytest.raises(ValueError):
            ScalperSignal(
                ts_exchange=now_ms,
                ts_server=now_ms,
                symbol="BTC/USD",
                timeframe="15s",
                side="sideways",  # Invalid: must be "long" or "short"
                confidence=0.8,
                entry=45000.0,
                stop=44500.0,
                tp=46000.0,
                model="test_model",
                trace_id="test-001",
            )

    def test_invalid_negative_price(self):
        """Test that negative prices raise validation error"""
        now_ms = int(time.time() * 1000)

        with pytest.raises(ValueError):
            ScalperSignal(
                ts_exchange=now_ms,
                ts_server=now_ms,
                symbol="BTC/USD",
                timeframe="15s",
                side="long",
                confidence=0.8,
                entry=-45000.0,  # Invalid: negative price
                stop=44500.0,
                tp=46000.0,
                model="test_model",
                trace_id="test-001",
            )

    def test_missing_required_field(self):
        """Test that missing required fields raise validation error"""
        now_ms = int(time.time() * 1000)

        with pytest.raises(TypeError):
            ScalperSignal(
                ts_exchange=now_ms,
                ts_server=now_ms,
                symbol="BTC/USD",
                timeframe="15s",
                side="long",
                confidence=0.8,
                # Missing required field: entry
                stop=44500.0,
                tp=46000.0,
                model="test_model",
                trace_id="test-001",
            )


class TestFreshnessCalculators:
    """Test freshness and lag calculation methods"""

    def test_calculate_freshness_metrics(self):
        """Test freshness metrics calculation"""
        now_ms = int(time.time() * 1000)
        ts_exchange = now_ms - 100  # 100ms ago
        ts_server = now_ms - 50  # 50ms ago

        signal = ScalperSignal(
            ts_exchange=ts_exchange,
            ts_server=ts_server,
            symbol="BTC/USD",
            timeframe="15s",
            side="long",
            confidence=0.8,
            entry=45000.0,
            stop=44500.0,
            tp=46000.0,
            model="test_model",
            trace_id="test-001",
        )

        # Calculate freshness with explicit now
        metrics = signal.calculate_freshness_metrics(now_server_ms=now_ms)

        assert "event_age_ms" in metrics
        assert "ingest_lag_ms" in metrics
        assert "exchange_server_delta_ms" in metrics

        # Event age should be approximately 100ms
        assert 95 <= metrics["event_age_ms"] <= 105

        # Ingest lag should be approximately 50ms
        assert 45 <= metrics["ingest_lag_ms"] <= 55

        # Delta should be approximately 50ms
        assert 45 <= metrics["exchange_server_delta_ms"] <= 55

    def test_calculate_freshness_metrics_auto_now(self):
        """Test freshness metrics with automatic now timestamp"""
        now_ms = int(time.time() * 1000)

        signal = ScalperSignal(
            ts_exchange=now_ms - 200,
            ts_server=now_ms - 100,
            symbol="BTC/USD",
            timeframe="15s",
            side="long",
            confidence=0.8,
            entry=45000.0,
            stop=44500.0,
            tp=46000.0,
            model="test_model",
            trace_id="test-001",
        )

        # Calculate without explicit now (uses current time)
        metrics = signal.calculate_freshness_metrics()

        # Event age should be at least 200ms
        assert metrics["event_age_ms"] >= 200

        # Ingest lag should be at least 100ms
        assert metrics["ingest_lag_ms"] >= 100

    def test_check_clock_drift_no_drift(self):
        """Test clock drift detection when there's no drift"""
        now_ms = int(time.time() * 1000)

        signal = ScalperSignal(
            ts_exchange=now_ms - 100,
            ts_server=now_ms - 50,  # Only 50ms difference
            symbol="BTC/USD",
            timeframe="15s",
            side="long",
            confidence=0.8,
            entry=45000.0,
            stop=44500.0,
            tp=46000.0,
            model="test_model",
            trace_id="test-001",
        )

        has_drift, message = signal.check_clock_drift(threshold_ms=2000)

        assert has_drift is False
        assert message is None

    def test_check_clock_drift_with_drift(self):
        """Test clock drift detection when drift exceeds threshold"""
        now_ms = int(time.time() * 1000)

        signal = ScalperSignal(
            ts_exchange=now_ms - 3000,  # 3 seconds ago
            ts_server=now_ms,  # Now (3000ms drift)
            symbol="BTC/USD",
            timeframe="15s",
            side="long",
            confidence=0.8,
            entry=45000.0,
            stop=44500.0,
            tp=46000.0,
            model="test_model",
            trace_id="test-001",
        )

        has_drift, message = signal.check_clock_drift(threshold_ms=2000)

        assert has_drift is True
        assert message is not None
        assert "drift" in message.lower()
        assert "3000" in message

    def test_check_clock_drift_exchange_ahead(self):
        """Test clock drift when exchange timestamp is ahead"""
        now_ms = int(time.time() * 1000)

        signal = ScalperSignal(
            ts_exchange=now_ms + 3000,  # 3 seconds in future
            ts_server=now_ms,
            symbol="BTC/USD",
            timeframe="15s",
            side="long",
            confidence=0.8,
            entry=45000.0,
            stop=44500.0,
            tp=46000.0,
            model="test_model",
            trace_id="test-001",
        )

        has_drift, message = signal.check_clock_drift(threshold_ms=2000)

        assert has_drift is True
        assert "ahead" in message.lower()


class TestSignalSerialization:
    """Test signal JSON serialization"""

    def test_to_json_str(self):
        """Test signal to JSON string conversion"""
        now_ms = int(time.time() * 1000)

        signal = ScalperSignal(
            ts_exchange=now_ms - 100,
            ts_server=now_ms - 50,
            symbol="BTC/USD",
            timeframe="15s",
            side="long",
            confidence=0.85,
            entry=45000.0,
            stop=44500.0,
            tp=46000.0,
            model="test_model_v1",
            trace_id="test-trace-001",
        )

        json_str = signal.to_json_str()

        assert isinstance(json_str, str)
        assert "BTC/USD" in json_str
        assert "long" in json_str
        assert "0.85" in json_str
        assert "test-trace-001" in json_str

    def test_get_stream_key(self):
        """Test stream key generation"""
        signal = ScalperSignal(
            ts_exchange=int(time.time() * 1000),
            ts_server=int(time.time() * 1000),
            symbol="BTC/USD",
            timeframe="15s",
            side="long",
            confidence=0.8,
            entry=45000.0,
            stop=44500.0,
            tp=46000.0,
            model="test_model",
            trace_id="test-001",
        )

        stream_key = signal.get_stream_key()

        # Should be in format: signals:paper:{symbol}:{timeframe}
        assert "signals:paper:" in stream_key
        assert "BTC_USD" in stream_key or "BTC/USD" in stream_key
        assert "15s" in stream_key


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
