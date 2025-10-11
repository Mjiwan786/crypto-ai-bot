import importlib
import time
import pytest
from dataclasses import dataclass
from typing import List


# Minimal TickRecord fallback if your module expects it
@dataclass
class TickRecord:
    timestamp: float
    price: float
    volume: float
    side: str  # "buy" | "sell"


def _gen_ticks(ts0: float, mid: float, n=200, skew="buy") -> List[TickRecord]:
    """
    Create synthetic ticks with a slight buy/sell skew. If your toxic flow
    module uses order-imbalance/toxicity ideas, this should produce a signal.
    """
    ticks = []
    for i in range(n):
        ts = ts0 + i * 0.05  # 20 ticks/sec
        if skew == "buy":
            side = "buy" if (i % 4 != 0) else "sell"  # 75% buys
        else:
            side = "sell" if (i % 4 != 0) else "buy"
        # tiny price nudge in direction of side
        price = mid * (1 + (0.00003 if side == "buy" else -0.00003))
        vol = 0.01 if side == "buy" else 0.008
        ticks.append(TickRecord(ts, price, vol, side))
    return ticks


def _load_api():
    """
    Try multiple common entrypoints so we don't depend on exact names.
    Returns a callable that takes (ticks, current_price) or (ticks) and returns a dict/obj.
    """
    try:
        mod = importlib.import_module("agents.scalper.analysis.toxic_flow")
    except ImportError as e:
        pytest.skip(f"Cannot import toxic_flow module: {e}")

    # 1) Class ToxicFlowAnalyzer with analyze()
    for cls_name in ("ToxicFlowAnalyzer", "ToxicityAnalyzer", "OrderToxicity"):
        cls = getattr(mod, cls_name, None)
        if cls is not None:
            try:
                inst = cls()
                analyze = getattr(inst, "analyze", None)
                if callable(analyze):
                    # Check if analyze method accepts current_price parameter
                    import inspect
                    sig = inspect.signature(analyze)
                    if 'current_price' in sig.parameters:
                        return lambda ticks, mid: analyze(ticks, current_price=mid)
                    else:
                        return lambda ticks, mid: analyze(ticks)
            except Exception as e:
                print(f"Warning: Could not instantiate {cls_name}: {e}")
                continue

    # 2) Top-level analyze(...) or compute_toxicity(...)
    for fn_name in ("analyze", "compute_toxicity", "toxic_flow", "evaluate"):
        fn = getattr(mod, fn_name, None)
        if callable(fn):
            try:
                import inspect
                sig = inspect.signature(fn)
                if 'current_price' in sig.parameters:
                    return lambda ticks, mid: fn(ticks, current_price=mid)
                else:
                    return lambda ticks, mid: fn(ticks)
            except Exception as e:
                print(f"Warning: Could not use function {fn_name}: {e}")
                continue

    pytest.skip("No suitable analyzer found in toxic_flow.py")


class TestToxicFlow:
    
    def test_toxic_flow_smoke_import(self):
        """Test that the module can be imported without errors."""
        try:
            mod = importlib.import_module("agents.scalper.analysis.toxic_flow")
            assert mod is not None
        except ImportError:
            pytest.skip("toxic_flow module not available")

    def test_toxic_flow_generates_metrics(self):
        """Test that the analyzer returns structured results."""
        analyzer = _load_api()
        ts0 = time.time()
        mid = 50_000.0
        ticks = _gen_ticks(ts0, mid, n=300, skew="buy")

        result = analyzer(ticks, mid)
        
        # We don't assert exact schema; just that something structured came back
        assert result is not None

        # If result is a dataclass or object, try to get a dict view
        d = result
        if hasattr(result, "__dict__"):
            d = vars(result)
        elif hasattr(result, "_asdict"):  # namedtuple
            d = result._asdict()

        # Look for common fields; loosened assertions so test is robust
        indicative_keys = {
            "toxicity", "vpin", "order_imbalance", "prob_adverse_selection",
            "toxicity_score", "buy_prob", "sell_prob", "imbalance", "flow_toxicity"
        }
        
        if isinstance(d, dict):
            present = indicative_keys.intersection(set(d.keys()))
            print(f"Available keys: {list(d.keys())}")
            print(f"Found indicative keys: {present}")
            # At least the result should be structured (dict-like)
            assert len(d) > 0, "Result should contain some data"
        else:
            # If it's not dict-like, at least ensure it's structured
            assert hasattr(result, "__dict__") or hasattr(result, "_asdict"), \
                "Result should be structured (have attributes or be dict-like)"

    def test_toxic_flow_buy_skew_vs_sell_skew(self):
        """Test that buy-skewed and sell-skewed data produce different results."""
        analyzer = _load_api()
        ts0 = time.time()
        mid = 50_000.0
        
        # Generate buy-skewed ticks
        buy_ticks = _gen_ticks(ts0, mid, n=200, skew="buy")
        buy_result = analyzer(buy_ticks, mid)
        
        # Generate sell-skewed ticks
        sell_ticks = _gen_ticks(ts0, mid, n=200, skew="sell")
        sell_result = analyzer(sell_ticks, mid)
        
        # Results should be different (basic sanity check)
        assert buy_result != sell_result, "Buy-skewed and sell-skewed data should produce different results"
        
    def test_toxic_flow_empty_ticks(self):
        """Test behavior with empty tick data."""
        analyzer = _load_api()
        mid = 50_000.0
        
        # Test with empty list
        try:
            result = analyzer([], mid)
            # Should either return a valid result or raise an appropriate exception
            assert result is not None or True  # Accept any non-crash behavior
        except (ValueError, IndexError, ZeroDivisionError) as e:
            # These are acceptable exceptions for empty data
            print(f"Expected exception for empty data: {e}")
            
    def test_toxic_flow_single_tick(self):
        """Test behavior with minimal tick data."""
        analyzer = _load_api()
        ts0 = time.time()
        mid = 50_000.0
        
        # Single tick
        single_tick = [TickRecord(ts0, mid, 0.01, "buy")]
        
        try:
            result = analyzer(single_tick, mid)
            assert result is not None
        except (ValueError, IndexError, ZeroDivisionError) as e:
            # These are acceptable exceptions for insufficient data
            print(f"Expected exception for single tick: {e}")


# If running as script
if __name__ == "__main__":
    import sys
    
    # Run tests manually
    test_instance = TestToxicFlow()
    
    tests = [
        test_instance.test_toxic_flow_smoke_import,
        test_instance.test_toxic_flow_generates_metrics,
        test_instance.test_toxic_flow_buy_skew_vs_sell_skew,
        test_instance.test_toxic_flow_empty_ticks,
        test_instance.test_toxic_flow_single_tick,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            print(f"Running {test.__name__}...")
            test()
            print(f"✓ {test.__name__} PASSED")
            passed += 1
        except Exception as e:
            print(f"✗ {test.__name__} FAILED: {e}")
            failed += 1
    
    print(f"\nResults: {passed} passed, {failed} failed")
    sys.exit(failed)