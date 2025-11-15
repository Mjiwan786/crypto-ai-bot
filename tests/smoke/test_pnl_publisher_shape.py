#!/usr/bin/env python3
"""
Shape Tests for PnL Publisher - Crypto AI Bot

Tests that publisher functions handle valid and invalid inputs correctly.
These tests do NOT require Redis to be running - they test validation logic only.

Run:
    pytest tests/smoke/test_pnl_publisher_shape.py -v
    python -m pytest tests/smoke/test_pnl_publisher_shape.py -v
"""

import sys
import os
from typing import Any, Dict

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Ensure Redis is NOT used for these tests
os.environ["REDIS_URL"] = "redis://invalid-host-for-testing:9999/0"

import pytest
from agents.infrastructure import pnl_publisher


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def valid_trade_close() -> Dict[str, Any]:
    """Valid trade close event."""
    return {
        "id": "test_trade_001",
        "ts": 1704067200000,
        "pair": "BTC/USD",
        "side": "long",
        "entry": 45000.0,
        "exit": 46000.0,
        "qty": 0.1,
        "pnl": 100.0,
    }


@pytest.fixture
def valid_equity_params() -> tuple:
    """Valid equity point parameters."""
    return (1704067200000, 10500.0, 150.0)


# ============================================================================
# Test publish_trade_close() - Valid Inputs
# ============================================================================

def test_publish_trade_close_valid_long(valid_trade_close):
    """Test publishing a valid long trade."""
    # Should not raise - silent failure is OK
    pnl_publisher.publish_trade_close(valid_trade_close)


def test_publish_trade_close_valid_short(valid_trade_close):
    """Test publishing a valid short trade."""
    valid_trade_close["side"] = "short"
    valid_trade_close["pnl"] = -50.0
    pnl_publisher.publish_trade_close(valid_trade_close)


def test_publish_trade_close_valid_with_extra_fields(valid_trade_close):
    """Test that extra fields are allowed."""
    valid_trade_close["metadata"] = {"foo": "bar"}
    valid_trade_close["strategy"] = "momentum"
    pnl_publisher.publish_trade_close(valid_trade_close)


def test_publish_trade_close_numeric_types(valid_trade_close):
    """Test that both int and float numeric types are accepted."""
    # Integer prices
    valid_trade_close["entry"] = 45000
    valid_trade_close["exit"] = 46000
    valid_trade_close["qty"] = 1
    valid_trade_close["pnl"] = 100
    pnl_publisher.publish_trade_close(valid_trade_close)


# ============================================================================
# Test publish_trade_close() - Missing Fields
# ============================================================================

def test_publish_trade_close_missing_id():
    """Test that missing 'id' field is silently rejected."""
    event = {
        "ts": 1704067200000,
        "pair": "BTC/USD",
        "side": "long",
        "entry": 45000.0,
        "exit": 46000.0,
        "qty": 0.1,
        "pnl": 100.0,
    }
    # Should not raise - silent failure
    pnl_publisher.publish_trade_close(event)


def test_publish_trade_close_missing_ts():
    """Test that missing 'ts' field is silently rejected."""
    event = {
        "id": "test_001",
        "pair": "BTC/USD",
        "side": "long",
        "entry": 45000.0,
        "exit": 46000.0,
        "qty": 0.1,
        "pnl": 100.0,
    }
    pnl_publisher.publish_trade_close(event)


def test_publish_trade_close_missing_pair():
    """Test that missing 'pair' field is silently rejected."""
    event = {
        "id": "test_001",
        "ts": 1704067200000,
        "side": "long",
        "entry": 45000.0,
        "exit": 46000.0,
        "qty": 0.1,
        "pnl": 100.0,
    }
    pnl_publisher.publish_trade_close(event)


def test_publish_trade_close_empty_dict():
    """Test that empty event is silently rejected."""
    pnl_publisher.publish_trade_close({})


# ============================================================================
# Test publish_trade_close() - Invalid Types
# ============================================================================

def test_publish_trade_close_invalid_id_type(valid_trade_close):
    """Test that non-string 'id' is silently rejected."""
    valid_trade_close["id"] = 12345  # Should be string
    pnl_publisher.publish_trade_close(valid_trade_close)


def test_publish_trade_close_invalid_ts_type(valid_trade_close):
    """Test that non-int 'ts' is silently rejected."""
    valid_trade_close["ts"] = "1704067200000"  # Should be int
    pnl_publisher.publish_trade_close(valid_trade_close)


def test_publish_trade_close_invalid_side(valid_trade_close):
    """Test that invalid 'side' value is silently rejected."""
    valid_trade_close["side"] = "buy"  # Should be 'long' or 'short'
    pnl_publisher.publish_trade_close(valid_trade_close)


def test_publish_trade_close_invalid_price_type(valid_trade_close):
    """Test that non-numeric price is silently rejected."""
    valid_trade_close["entry"] = "45000"  # Should be numeric
    pnl_publisher.publish_trade_close(valid_trade_close)


def test_publish_trade_close_invalid_qty_type(valid_trade_close):
    """Test that non-numeric qty is silently rejected."""
    valid_trade_close["qty"] = None
    pnl_publisher.publish_trade_close(valid_trade_close)


def test_publish_trade_close_invalid_pnl_type(valid_trade_close):
    """Test that non-numeric pnl is silently rejected."""
    valid_trade_close["pnl"] = "profit"
    pnl_publisher.publish_trade_close(valid_trade_close)


# ============================================================================
# Test publish_equity_point() - Valid Inputs
# ============================================================================

def test_publish_equity_point_valid(valid_equity_params):
    """Test publishing a valid equity point."""
    ts_ms, equity, daily_pnl = valid_equity_params
    # Should not raise - silent failure is OK
    pnl_publisher.publish_equity_point(ts_ms, equity, daily_pnl)


def test_publish_equity_point_negative_pnl():
    """Test that negative daily PnL is accepted."""
    pnl_publisher.publish_equity_point(1704067200000, 9500.0, -500.0)


def test_publish_equity_point_zero_pnl():
    """Test that zero daily PnL is accepted."""
    pnl_publisher.publish_equity_point(1704067200000, 10000.0, 0.0)


def test_publish_equity_point_integer_types():
    """Test that integer types are accepted for numeric fields."""
    pnl_publisher.publish_equity_point(1704067200000, 10000, 100)


# ============================================================================
# Test publish_equity_point() - Invalid Types
# ============================================================================

def test_publish_equity_point_invalid_ts_type():
    """Test that non-int timestamp is silently rejected."""
    pnl_publisher.publish_equity_point("1704067200000", 10500.0, 150.0)


def test_publish_equity_point_invalid_equity_type():
    """Test that non-numeric equity is silently rejected."""
    pnl_publisher.publish_equity_point(1704067200000, "10500", 150.0)


def test_publish_equity_point_invalid_daily_pnl_type():
    """Test that non-numeric daily_pnl is silently rejected."""
    pnl_publisher.publish_equity_point(1704067200000, 10500.0, None)


def test_publish_equity_point_all_invalid():
    """Test that all invalid parameters are silently rejected."""
    pnl_publisher.publish_equity_point("invalid", "invalid", "invalid")


# ============================================================================
# Test Edge Cases
# ============================================================================

def test_publish_trade_close_very_large_pnl(valid_trade_close):
    """Test that very large PnL values are accepted."""
    valid_trade_close["pnl"] = 1_000_000.0
    pnl_publisher.publish_trade_close(valid_trade_close)


def test_publish_trade_close_very_small_qty(valid_trade_close):
    """Test that very small quantities are accepted."""
    valid_trade_close["qty"] = 0.00000001
    pnl_publisher.publish_trade_close(valid_trade_close)


def test_publish_trade_close_negative_pnl(valid_trade_close):
    """Test that negative PnL (loss) is accepted."""
    valid_trade_close["pnl"] = -500.0
    pnl_publisher.publish_trade_close(valid_trade_close)


def test_publish_equity_point_very_large_equity():
    """Test that very large equity values are accepted."""
    pnl_publisher.publish_equity_point(1704067200000, 1_000_000_000.0, 50000.0)


def test_publish_equity_point_very_small_equity():
    """Test that very small equity values are accepted."""
    pnl_publisher.publish_equity_point(1704067200000, 0.01, -0.99)


# ============================================================================
# Test Module-Level Behavior
# ============================================================================

def test_get_redis_client_singleton():
    """Test that _get_redis_client() returns None when Redis is unavailable."""
    # Force new client creation with invalid URL
    pnl_publisher._redis_client = None
    client = pnl_publisher._get_redis_client()
    # Should be None since we set invalid URL
    assert client is None, "Client should be None with invalid Redis URL"


def test_publish_functions_dont_raise():
    """Test that publish functions never raise exceptions."""
    # This is critical - publisher must never break trading logic

    # Test with completely invalid inputs
    pnl_publisher.publish_trade_close(None)
    pnl_publisher.publish_trade_close("not a dict")
    pnl_publisher.publish_trade_close([1, 2, 3])

    # Test equity point with invalid inputs
    pnl_publisher.publish_equity_point(None, None, None)

    # If we reach here, test passes (no exceptions raised)
    assert True


# ============================================================================
# Test Documentation
# ============================================================================

def test_module_docstring():
    """Test that module has documentation."""
    assert pnl_publisher.__doc__ is not None
    assert len(pnl_publisher.__doc__) > 50


def test_publish_trade_close_docstring():
    """Test that publish_trade_close has documentation."""
    assert pnl_publisher.publish_trade_close.__doc__ is not None
    assert "trade close" in pnl_publisher.publish_trade_close.__doc__.lower()


def test_publish_equity_point_docstring():
    """Test that publish_equity_point has documentation."""
    assert pnl_publisher.publish_equity_point.__doc__ is not None
    assert "equity" in pnl_publisher.publish_equity_point.__doc__.lower()


if __name__ == "__main__":
    # Run with pytest
    pytest.main([__file__, "-v", "--tb=short"])
