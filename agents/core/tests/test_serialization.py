#!/usr/bin/env python3
"""
Unit tests for serialization utilities.

Tests json_dumps(), to_decimal_str(), ts_to_iso(), and serialize_for_redis()
with both orjson and standard json backends.
"""

from __future__ import annotations

import json
import pytest
from datetime import datetime, timezone
from decimal import Decimal

from agents.core.serialization import (
    json_dumps,
    decimal_to_str,
    to_decimal_str,
    ts_to_iso,
    serialize_for_redis,
    HAS_ORJSON,
)


class TestJsonDumps:
    """Test json_dumps() with orjson and json fallback."""

    def test_simple_dict(self):
        """Test serialization of simple dictionary."""
        data = {"name": "BTC/USD", "price": 50000}
        result = json_dumps(data)

        # Should be valid JSON
        parsed = json.loads(result)
        assert parsed == data

    def test_with_decimal(self):
        """Test serialization with Decimal values."""
        data = {"price": Decimal("50000.00")}
        result = json_dumps(data)

        parsed = json.loads(result)
        # Decimal should be converted to string without trailing zeros
        assert parsed == {"price": "50000"}

    def test_with_datetime(self):
        """Test serialization with datetime values."""
        dt = datetime(2025, 10, 11, 12, 30, 45, tzinfo=timezone.utc)
        data = {"timestamp": dt}
        result = json_dumps(data)

        parsed = json.loads(result)
        assert parsed == {"timestamp": "2025-10-11T12:30:45+00:00"}

    def test_compact_output(self):
        """Test compact JSON output (no indentation)."""
        data = {"a": 1, "b": 2}
        result = json_dumps(data)

        # Should not contain newlines
        assert "\n" not in result
        # Should be compact
        assert result in ['{"a":1,"b":2}', '{"b":2,"a":1}']  # Order may vary

    def test_indented_output(self):
        """Test indented JSON output."""
        data = {"a": 1, "b": 2}
        result = json_dumps(data, indent=2)

        # Should contain newlines
        assert "\n" in result
        # Should parse correctly
        parsed = json.loads(result)
        assert parsed == data

    def test_nested_structures(self):
        """Test serialization of nested structures."""
        data = {
            "signal": {
                "pair": "BTC/USD",
                "prices": [50000, 51000, 49000],
                "metadata": {"confidence": 0.85}
            }
        }
        result = json_dumps(data)

        parsed = json.loads(result)
        assert parsed == data

    def test_empty_dict(self):
        """Test serialization of empty dictionary."""
        result = json_dumps({})
        assert result == "{}"

    def test_empty_list(self):
        """Test serialization of empty list."""
        result = json_dumps([])
        assert result == "[]"

    @pytest.mark.skipif(not HAS_ORJSON, reason="orjson not available")
    def test_with_orjson_backend(self):
        """Test that orjson is being used when available."""
        data = {"test": "value"}
        result = json_dumps(data)

        # orjson should produce compact output
        assert result == '{"test":"value"}'


class TestDecimalToStr:
    """Test decimal_to_str() and to_decimal_str() helpers."""

    def test_decimal_with_trailing_zeros(self):
        """Test removal of trailing zeros."""
        assert decimal_to_str(Decimal("123.45000")) == "123.45"
        assert decimal_to_str(Decimal("100.00")) == "100"
        assert decimal_to_str(Decimal("0.00100")) == "0.001"

    def test_decimal_whole_number(self):
        """Test whole numbers without decimal point."""
        assert decimal_to_str(Decimal("100")) == "100"
        assert decimal_to_str(Decimal("50000")) == "50000"

    def test_decimal_small_numbers(self):
        """Test small decimal numbers."""
        assert decimal_to_str(Decimal("0.001")) == "0.001"
        assert decimal_to_str(Decimal("0.00001")) == "0.00001"

    def test_decimal_scientific_notation(self):
        """Test handling of scientific notation."""
        # Very large numbers
        assert decimal_to_str(Decimal("1E+10")) == "10000000000"

        # Very small numbers
        result = decimal_to_str(Decimal("1E-10"))
        assert "0.0000000001" in result

    def test_decimal_negative_numbers(self):
        """Test negative decimals."""
        assert decimal_to_str(Decimal("-123.45")) == "-123.45"
        assert decimal_to_str(Decimal("-100.00")) == "-100"

    def test_decimal_precision(self):
        """Test high-precision decimals."""
        assert decimal_to_str(Decimal("123.456789")) == "123.456789"

    def test_to_decimal_str_alias(self):
        """Test that to_decimal_str is an alias for decimal_to_str."""
        value = Decimal("123.45")
        assert to_decimal_str(value) == decimal_to_str(value)
        assert to_decimal_str is decimal_to_str

    def test_invalid_type_raises_error(self):
        """Test that non-Decimal types raise TypeError."""
        with pytest.raises(TypeError, match="Expected Decimal"):
            decimal_to_str(123.45)  # type: ignore

        with pytest.raises(TypeError, match="Expected Decimal"):
            decimal_to_str("123.45")  # type: ignore


class TestTsToIso:
    """Test ts_to_iso() datetime conversion."""

    def test_utc_datetime(self):
        """Test UTC datetime conversion."""
        dt = datetime(2025, 10, 11, 12, 30, 45, tzinfo=timezone.utc)
        result = ts_to_iso(dt)

        assert result == "2025-10-11T12:30:45+00:00"

    def test_naive_datetime_treated_as_utc(self):
        """Test that naive datetime is treated as UTC."""
        dt = datetime(2025, 10, 11, 12, 30, 45)
        result = ts_to_iso(dt)

        assert result == "2025-10-11T12:30:45+00:00"

    def test_datetime_with_microseconds(self):
        """Test datetime with microseconds."""
        dt = datetime(2025, 10, 11, 12, 30, 45, 123456, tzinfo=timezone.utc)
        result = ts_to_iso(dt)

        assert "2025-10-11T12:30:45.123456" in result

    def test_invalid_type_raises_error(self):
        """Test that non-datetime types raise TypeError."""
        with pytest.raises(TypeError, match="Expected datetime"):
            ts_to_iso(1234567890)  # type: ignore

        with pytest.raises(TypeError, match="Expected datetime"):
            ts_to_iso("2025-10-11")  # type: ignore


class TestSerializeForRedis:
    """Test serialize_for_redis() convenience function."""

    def test_simple_dict(self):
        """Test serialization of simple dictionary."""
        data = {"symbol": "BTC/USD", "price": 50000}
        result = serialize_for_redis(data)

        parsed = json.loads(result)
        assert parsed == data

    def test_with_decimal_and_datetime(self):
        """Test serialization with Decimal and datetime."""
        data = {
            "symbol": "BTC/USD",
            "price": Decimal("50000.00"),
            "timestamp": datetime(2025, 10, 11, 12, 0, 0, tzinfo=timezone.utc)
        }
        result = serialize_for_redis(data)

        parsed = json.loads(result)
        assert parsed == {
            "symbol": "BTC/USD",
            "price": "50000",
            "timestamp": "2025-10-11T12:00:00+00:00"
        }

    def test_nested_structures_with_special_types(self):
        """Test nested structures with Decimal and datetime."""
        data = {
            "signal": {
                "prices": {
                    "entry": Decimal("50000.00"),
                    "sl": Decimal("49000.00"),
                    "tp": Decimal("52000.00")
                },
                "timestamp": datetime(2025, 10, 11, tzinfo=timezone.utc)
            }
        }
        result = serialize_for_redis(data)

        parsed = json.loads(result)
        assert parsed == {
            "signal": {
                "prices": {
                    "entry": "50000",
                    "sl": "49000",
                    "tp": "52000"
                },
                "timestamp": "2025-10-11T00:00:00+00:00"
            }
        }

    def test_list_with_decimals(self):
        """Test list containing Decimal values."""
        data = {
            "prices": [Decimal("50000"), Decimal("51000"), Decimal("49000")]
        }
        result = serialize_for_redis(data)

        parsed = json.loads(result)
        assert parsed == {"prices": ["50000", "51000", "49000"]}

    def test_compact_output(self):
        """Test that output is compact (no indentation)."""
        data = {"a": 1, "b": 2}
        result = serialize_for_redis(data)

        # Should not contain extra whitespace
        assert "\n" not in result


class TestRoundTrip:
    """Test round-trip serialization and deserialization."""

    def test_signal_payload_roundtrip(self):
        """Test round-trip for signal payload."""
        data = {
            "id": "sig_001",
            "ts": 1234567890.123,
            "pair": "BTC/USD",
            "side": "buy",
            "entry": 50000.0,
            "sl": 49000.0,
            "tp": 52000.0,
            "strategy": "momentum",
            "confidence": 0.85
        }

        # Serialize
        json_str = json_dumps(data)

        # Deserialize
        parsed = json.loads(json_str)

        assert parsed == data

    def test_metrics_payload_roundtrip(self):
        """Test round-trip for metrics payload."""
        data = {
            "component": "kraken_api",
            "p50": 45.2,
            "p95": 128.7,
            "window_s": 60
        }

        # Serialize
        json_str = json_dumps(data)

        # Deserialize
        parsed = json.loads(json_str)

        assert parsed == data

    def test_health_payload_roundtrip(self):
        """Test round-trip for health payload."""
        data = {
            "ok": True,
            "checks": {
                "redis": True,
                "kraken": True,
                "postgres": True
            }
        }

        # Serialize
        json_str = json_dumps(data)

        # Deserialize
        parsed = json.loads(json_str)

        assert parsed == data


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_none_values(self):
        """Test handling of None values."""
        data = {"value": None}
        result = json_dumps(data)

        parsed = json.loads(result)
        assert parsed == {"value": None}

    def test_boolean_values(self):
        """Test handling of boolean values."""
        data = {"active": True, "disabled": False}
        result = json_dumps(data)

        parsed = json.loads(result)
        assert parsed == data

    def test_unicode_strings(self):
        """Test handling of unicode strings."""
        data = {"message": "Hello 世界 🚀"}
        result = json_dumps(data)

        parsed = json.loads(result)
        assert parsed == data

    def test_large_numbers(self):
        """Test handling of large numbers."""
        data = {"value": 9999999999999999}
        result = json_dumps(data)

        parsed = json.loads(result)
        assert parsed == data

    def test_empty_strings(self):
        """Test handling of empty strings."""
        data = {"empty": ""}
        result = json_dumps(data)

        parsed = json.loads(result)
        assert parsed == data


# Run tests with: pytest agents/core/tests/test_serialization.py -v
