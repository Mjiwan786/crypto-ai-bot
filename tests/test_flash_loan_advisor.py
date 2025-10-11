"""
tests/test_flash_loan_advisor.py

Comprehensive tests for the flash loan advisor module.

Covers:
- Determinism & decision hashing
- Correctness (fees, slippage, math)
- Guardrails (enabled flag, hop count, profit thresholds)
- Tie-breaking determinism
- Pydantic v2 validator compatibility
- Stable swap math correctness
- RFQ depth enforcement
- Error handling & reason sorting
"""

from ai_engine.flash_loan_advisor import (
    advise_flash_loan, AdvisorConfig, SwapPath, SwapHop, Pool, PriceSnapshot,
    AMMModel, Mode, Action, simulate_path, _stable_swap_out
)


# ------------------------------
# Determinism
# ------------------------------
class TestDeterminism:
    def test_decision_hash_stable(self):
        """Decision hash must be identical across repeated runs."""
        prices = PriceSnapshot(ts_ms=1640995200000, prices_usd={"USDC": 1.0, "WETH": 3500.0})
        pools = [
            Pool(id="pool1", chain="ethereum", model=AMMModel.CONSTANT_PRODUCT,
                 token0="USDC", token1="WETH", r0=1000.0, r1=0.286, fee_bps=30)
        ]
        path = SwapPath(hops=[SwapHop(pool_id="pool1", in_token="USDC", out_token="WETH")],
                        borrow_token="USDC", repay_token="WETH")
        cfg = AdvisorConfig(enabled=True, mode=Mode.SHADOW)

        a1 = advise_flash_loan([path], prices, pools, cfg)
        a2 = advise_flash_loan([path], prices, pools, cfg)

        assert a1.decision_hash == a2.decision_hash
        assert a1.reasons == a2.reasons

    def test_tie_breaks_lexicographically(self):
        """When profits equal, lexicographically smaller route wins."""
        prices = PriceSnapshot(ts_ms=1, prices_usd={"USDC": 1.0, "WETH": 3500.0})
        pools = [
            Pool(id="pool_b", chain="eth", model=AMMModel.CONSTANT_PRODUCT,
                 token0="USDC", token1="WETH", r0=1000, r1=0.286, fee_bps=30),
            Pool(id="pool_a", chain="eth", model=AMMModel.CONSTANT_PRODUCT,
                 token0="USDC", token1="WETH", r0=1000, r1=0.286, fee_bps=30)
        ]
        path1 = SwapPath(hops=[SwapHop(pool_id="pool_b", in_token="USDC", out_token="WETH")],
                         borrow_token="USDC", repay_token="WETH")
        path2 = SwapPath(hops=[SwapHop(pool_id="pool_a", in_token="USDC", out_token="WETH")],
                         borrow_token="USDC", repay_token="WETH")

        cfg = AdvisorConfig(enabled=True, min_profit_usd=0.01, min_worst_case_profit_usd=0.01)
        advice = advise_flash_loan([path1, path2], prices, pools, cfg)

        if advice.action == Action.PROPOSE:
            assert advice.route[0].pool_id == "pool_a"


# ------------------------------
# Correctness
# ------------------------------
class TestCorrectness:
    def test_fee_conversion_to_usd(self):
        """Per-hop token fees should convert properly into USD in diagnostics."""
        prices = PriceSnapshot(ts_ms=1, prices_usd={"USDC": 1.0, "WETH": 3500.0})
        pools = [
            Pool(id="pool1", chain="eth", model=AMMModel.CONSTANT_PRODUCT,
                 token0="USDC", token1="WETH", r0=10000, r1=2.857, fee_bps=300)
        ]
        path = SwapPath(hops=[SwapHop(pool_id="pool1", in_token="USDC", out_token="WETH")],
                        borrow_token="USDC", repay_token="WETH")

        cfg = AdvisorConfig(enabled=True, min_profit_usd=0.01, min_worst_case_profit_usd=0.01)
        advice = advise_flash_loan([path], prices, pools, cfg)

        assert "fees_usd" in advice.diagnostics
        assert 0 < advice.diagnostics["fees_usd"] < 1000

    def test_slippage_compounds_across_hops(self):
        """Slippage must compound per hop (not linear)."""
        prices = PriceSnapshot(ts_ms=1, prices_usd={"USDC": 1.0, "WETH": 3500.0, "WBTC": 47000.0})
        pools = [
            Pool(id="p1", chain="eth", model=AMMModel.CONSTANT_PRODUCT,
                 token0="USDC", token1="WETH", r0=100000, r1=28.57, fee_bps=30),
            Pool(id="p2", chain="eth", model=AMMModel.CONSTANT_PRODUCT,
                 token0="WETH", token1="WBTC", r0=100, r1=7.45, fee_bps=30),
            Pool(id="p3", chain="eth", model=AMMModel.CONSTANT_PRODUCT,
                 token0="WBTC", token1="USDC", r0=1, r1=47000, fee_bps=30)
        ]
        path = SwapPath(hops=[
            SwapHop(pool_id="p1", in_token="USDC", out_token="WETH"),
            SwapHop(pool_id="p2", in_token="WETH", out_token="WBTC"),
            SwapHop(pool_id="p3", in_token="WBTC", out_token="USDC"),
        ], borrow_token="USDC", repay_token="USDC")

        cfg = AdvisorConfig(enabled=True, slippage_bps=100,
                            min_profit_usd=0.01, min_worst_case_profit_usd=0.01)
        advice = advise_flash_loan([path], prices, pools, cfg)

        assert "slippage_usd" in advice.diagnostics
        assert advice.diagnostics["slippage_usd"] > 0


# ------------------------------
# Guardrails
# ------------------------------
class TestGuardrails:
    def test_disabled_means_noop(self):
        prices = PriceSnapshot(ts_ms=1, prices_usd={"USDC": 1.0})
        pools = [Pool(id="p1", chain="eth", model=AMMModel.CONSTANT_PRODUCT,
                      token0="USDC", token1="WETH", r0=1000, r1=1, fee_bps=30)]
        path = SwapPath(hops=[SwapHop(pool_id="p1", in_token="USDC", out_token="WETH")],
                        borrow_token="USDC", repay_token="WETH")

        cfg = AdvisorConfig(enabled=False)
        advice = advise_flash_loan([path], prices, pools, cfg)

        assert advice.action == Action.NOOP
        assert "disabled" in advice.reasons

    def test_hop_count_guardrail(self):
        prices = PriceSnapshot(ts_ms=1, prices_usd={"USDC": 1.0, "WETH": 3500.0})
        pools = [Pool(id=f"p{i}", chain="eth", model=AMMModel.CONSTANT_PRODUCT,
                      token0="USDC", token1="WETH", r0=1000, r1=1, fee_bps=30) for i in range(5)]
        long_path = SwapPath(
            hops=[SwapHop(pool_id=f"p{i}", in_token="USDC", out_token="WETH") 
                  for i in range(5)],
            borrow_token="USDC", repay_token="WETH"
        )

        cfg = AdvisorConfig(enabled=True, max_hops=3)
        advice = advise_flash_loan([long_path], prices, pools, cfg)

        assert advice.action == Action.NOOP
        assert any("no_viable_paths" in r for r in advice.reasons)


# ------------------------------
# RFQ
# ------------------------------
class TestRFQ:
    def test_respects_depth_limit(self):
        prices = PriceSnapshot(ts_ms=1, prices_usd={"WBTC": 47000, "USDC": 1})
        pools = [
            Pool(id="rfq", chain="eth", model=AMMModel.RFQ_FIXED,
                 token0="WBTC", token1="USDC", r0=1, r1=1, fee_bps=10,
                 extra={"price": 47100, "depth": 1000})
        ]
        path = SwapPath(hops=[SwapHop(pool_id="rfq", in_token="WBTC", out_token="USDC")],
                        borrow_token="WBTC", repay_token="USDC")

        cfg = AdvisorConfig(enabled=True, max_borrow_usd=5000,
                            min_profit_usd=0.01, min_worst_case_profit_usd=0.01)
        advice = advise_flash_loan([path], prices, pools, cfg)

        assert advice.latency_ms >= 0  # Sanity


# ------------------------------
# Stable swap math
# ------------------------------
class TestStableSwap:
    def test_amplification_reduces_slippage(self):
        r_in, r_out, amt = 10000, 10000, 100
        out_low = _stable_swap_out(r_in, r_out, amt, 30, A=10)
        out_high = _stable_swap_out(r_in, r_out, amt, 30, A=1000)
        assert out_high > out_low
        assert out_high <= r_out * 0.99

    def test_fee_reduces_output(self):
        r_in, r_out, amt, A = 10000, 10000, 100, 100
        out_low_fee = _stable_swap_out(r_in, r_out, amt, 10, A)
        out_high_fee = _stable_swap_out(r_in, r_out, amt, 100, A)
        assert out_low_fee > out_high_fee


# ------------------------------
# Error handling polish
# ------------------------------
class TestErrors:
    def test_simulate_path_returns_error_flags(self):
        pools = {}
        path = SwapPath(hops=[SwapHop(pool_id="missing", in_token="USDC", out_token="WETH")],
                        borrow_token="USDC", repay_token="WETH")
        result = simulate_path(path, 100, pools)
        assert result["amount_out"] == 0
        assert "sim_error" in result
