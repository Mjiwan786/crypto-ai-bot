"""
Tests for mcp.schemas models. Production-ready for Python 3.10 + Pydantic v2.
"""
import time
import pytest
from mcp.schemas import Signal, OrderIntent, PolicyUpdate, MetricsTick, PolicyAllocations

def test_signal_validation_errors():
    # Happy path: use .example() for valid signal
    valid_signal = Signal.example()
    assert isinstance(valid_signal, Signal)
    # Missing required field
    with pytest.raises(ValueError):
        Signal(symbol="BTCUSD", side="buy", timestamp=None)
    # Invalid side
    with pytest.raises(ValueError):
        Signal(symbol="BTCUSD", side="invalid", timestamp=time.time())

def test_order_intent_validation_errors():
    # Happy path: valid limit and market
    valid_limit = OrderIntent(
        symbol="BTCUSD", side="buy", type="limit", price=50000, 
        size_quote_usd=1000, timestamp=time.time()
    )
    valid_market = OrderIntent(
        symbol="BTCUSD", side="sell", type="market", size_quote_usd=1000, timestamp=time.time()
    )
    assert valid_limit.model_dump(mode="json") != {}
    assert valid_market.model_dump(mode="json") != {}
    # Invalid price
    with pytest.raises(ValueError):
        OrderIntent(
            symbol="BTCUSD", side="buy", type="limit", price=0, 
            size_quote_usd=1000, timestamp=time.time()
        )
    # Invalid size
    with pytest.raises(ValueError):
        OrderIntent(
            symbol="BTCUSD", side="buy", type="market", 
            size_quote_usd=0.5, timestamp=time.time()
        )
    # Invalid post_only
    with pytest.raises(ValueError):
        OrderIntent(
            symbol="BTCUSD", side="buy", type="limit", price=50000, 
            size_quote_usd=1000, post_only="notabool", timestamp=time.time()
        )

def test_policy_update_validation_errors():
    # Happy path
    valid_policy = PolicyUpdate.example()
    assert isinstance(valid_policy, PolicyUpdate)
    # Missing allocations
    with pytest.raises(ValueError):
        PolicyUpdate(allocations=None, timestamp=time.time())
    # Invalid allocations type
    with pytest.raises(ValueError):
        PolicyUpdate(allocations="notadict", timestamp=time.time())
    # Missing timestamp
    with pytest.raises(ValueError):
        PolicyUpdate(allocations={"BTC": 1.0})
    # Invalid version
    with pytest.raises(ValueError):
        PolicyUpdate(allocations={"BTC": 1.0}, version=123, timestamp=time.time())

def test_metrics_tick_validation_errors():
    # Happy path
    valid_metrics = MetricsTick.example()
    assert isinstance(valid_metrics, MetricsTick)
    # Missing pnl keys
    with pytest.raises(ValueError, match="pnl must include keys"):
        MetricsTick(pnl={}, timestamp=time.time())
    # Negative win_rate
    with pytest.raises(ValueError):
        MetricsTick(pnl={"BTC": 1.0}, win_rate=-0.1, timestamp=time.time())
    # Out-of-range slippage
    with pytest.raises(ValueError):
        MetricsTick(pnl={"BTC": 1.0}, slippage=2.0, timestamp=time.time())
    # Negative latency
    with pytest.raises(ValueError):
        MetricsTick(pnl={"BTC": 1.0}, latency_ms=-5, timestamp=time.time())
    # Negative errors_rate
    with pytest.raises(ValueError):
        MetricsTick(pnl={"BTC": 1.0}, errors_rate=-0.1, timestamp=time.time())

import math



def test_policy_allocations_table():
    # Parametrized table for allocations
    table = [
        ({"BTC": 1.0}, True),
        ({"BTC": 0.995, "ETH": 0.005}, True),
        ({"BTC": 1.005}, True),
        ({"BTC": 0.98}, False),
        ({"BTC": 1.02}, False),
    ]
    for allocs, should_pass in table:
        if should_pass:
            obj = PolicyAllocations(allocations=allocs)
            total = sum(obj.allocations.values())
            assert math.isclose(total, 1.0, abs_tol=0.01)
        else:
            with pytest.raises(ValueError):
                PolicyAllocations(allocations=allocs)

def test_immutability():
    sig = Signal.example()
    with pytest.raises((TypeError, AttributeError)):
        sig.symbol = "ETHUSD"

def test_json_schema_export():
    # Check schema export for all models
    models = [Signal, OrderIntent, PolicyUpdate, MetricsTick]
    for model in models:
        schema = model.model_json_schema()
        assert "title" in schema or "$schema" in schema

def test_performance_sanity():
    # 200 iterations of serialize/parse
    s = Signal.example()
    start = time.time()
    for _ in range(200):
        dumped = s.model_dump(mode="json")
        loaded = Signal(**dumped)
        assert loaded.model_dump(mode="json") == s.model_dump(mode="json")
    elapsed = time.time() - start
    assert elapsed < 0.7

def test_backward_compat_version_alias():
    # Ensure version aliasing works
    s = Signal(symbol="BTCUSD", side="buy", timestamp=time.time(), version="v1")
    assert s.version == "v1"
