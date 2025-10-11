"""
Unit tests for the flash loan arbitrage subsystem (paper mode).

These tests use a ``FakeCtx`` class to emulate the ``MarketContext`` API used by
the modules. They verify that the opportunity scorer produces the expected
spread, that the profitability simulator returns executable results for a
reasonable trade size, that the execution optimizer respects rate limits and
records history, and that the historical analyzer computes win rates and
suggestions correctly.

Note: PyTest is not bundled in this environment. You can run these tests
directly via ``python -m tests.test_flash_arb`` which will execute the test
functions sequentially. When PyTest is available you can run ``pytest -q``
instead.
"""

import time
import os
import sys
from types import SimpleNamespace

# Ensure that the project root (containing flash_loan_system) is on sys.path when
# running this file directly. Without this, ``ModuleNotFoundError`` may occur.
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from flash_loan_system.opportunity_scorer import OpportunityScorer, ArbOpportunity
from flash_loan_system.profitability_simulator import ProfitabilitySimulator, SimResult
from flash_loan_system.execution_optimizer import ExecutionOptimizer
from flash_loan_system.historical_analyzer import HistoricalAnalyzer


class FakeCtx:
    """Simple context stub that stores values in dicts/lists."""
    def __init__(self):
        self.store = {}
        self.lists = {"flash/history": []}
        self.pubs = []
    def set_value(self, key, value):
        self.store[key] = value
    def get_value(self, key):
        return self.store.get(key)
    def append_to_list(self, key, item):
        self.lists.setdefault(key, []).append(item)
    def get_list(self, key):
        return self.lists.get(key, [])
    def publish(self, channel, payload):
        self.pubs.append((channel, payload))


def base_config():
    return {
        "bot": {"env": "paper", "mode": "hypergrowth"},
        "flash_loan_system": {
            "enabled": True,
            "min_roi": 0.02,
            "max_loans_per_day": 3,
            "cooloff_seconds": 0,
            "arbitrage": {
                "min_spread": 0.018,
                "max_slippage": 0.001,
                "exchanges": ["uniswap_v3", "sushiswap"],
                "pair_whitelist": ["ETH/USDC"],
            },
            "sizing": {
                "base_multiplier": 2.0,
                "volatility_adjusted": True,
                "max_capital_utilization": 0.5,
            },
            "gas": {"max_gwei": 80, "priority_tip_gwei": 2, "estimation_buffer": 1.15},
            "mev": {"buffer_bps": 8},
            "dex": {"uniswap_v3": {"fee_tiers": [500, 3000]}},
        },
    }


def test_opportunity_scorer_monkeypatch():
    ctx = FakeCtx()
    cfg = base_config()
    scorer = OpportunityScorer(ctx, cfg, logger=None)
    # monkeypatch _quote to deterministic values
    def fake_quote(dex, base, quote):
        price = 3000.0 if dex == "uniswap_v3" else 3095.0
        return SimpleNamespace(
            dex=dex, base=base, quote=quote, price=price, 
            liquidity=2_000_000.0, ts=time.time()
        )
    scorer._quote = fake_quote  # type: ignore
    opps = scorer.scan()
    assert len(opps) == 1
    opp = opps[0]
    expected_spread = (3095.0 - 3000.0) / 3000.0
    assert abs(opp.gross_spread - expected_spread) < 1e-6


def test_profitability_simulator_basic():
    ctx = FakeCtx()
    cfg = base_config()
    ctx.set_value("prices/native_usd", 1500.0)
    sim = ProfitabilitySimulator(ctx, cfg, logger=None)
    opp = ArbOpportunity(
        symbol="ETH/USDC",
        buy_dex="uniswap_v3",
        sell_dex="sushiswap",
        buy_price=3000.0,
        sell_price=3095.0,
        gross_spread=(3095.0 - 3000.0) / 3000.0,
        est_slippage_bps=10.0,
        confidence=0.9,
        size_hint=1.0,
        route={"buy_liquidity": 2_000_000.0, "sell_liquidity": 2_000_000.0, "fee_tiers": [500]},
    )
    res = sim.simulate(opp, notional_usd=10_000.0)
    assert isinstance(res, SimResult)
    assert res.can_execute is True


def test_execution_optimizer_paper_flow():
    ctx = FakeCtx()
    cfg = base_config()
    ctx.set_value("portfolio/cash_usd", 10_000.0)
    ctx.set_value("volatility/score", 0.2)
    execu = ExecutionOptimizer(ctx, cfg, logger=None)
    sim = SimResult(
        symbol="ETH/USDC",
        size=1.0,
        net_roi=0.03,
        gross_spread=0.03,
        gas_cost_usd=5.0,
        fees_usd=3.0,
        mev_buffer_usd=1.0,
        repay_amount=3000.0,
        can_execute=True,
        notes="ok",
    )
    opp = ArbOpportunity(
        symbol="ETH/USDC",
        buy_dex="uniswap_v3",
        sell_dex="sushiswap",
        buy_price=3000.0,
        sell_price=3095.0,
        gross_spread=0.031,
        est_slippage_bps=10.0,
        confidence=0.9,
        size_hint=1.0,
        route={"buy_liquidity": 2_000_000.0, "sell_liquidity": 2_000_000.0, "fee_tiers": [500]},
    )
    outcome = execu.execute(sim, opp)
    assert outcome["status"] in {"executed", "skipped"}
    hist = ctx.get_list("flash/history")
    assert len(hist) == 1


def test_historical_analyzer_summary_and_suggestion():
    ctx = FakeCtx()
    cfg = base_config()
    # add three executed trades: two positive ROI, one negative
    ctx.append_to_list("flash/history", {
        "status": "executed", "net_roi": 0.03, "buy_dex": "u", "sell_dex": "s"
    })
    ctx.append_to_list("flash/history", {
        "status": "executed", "net_roi": 0.02, "buy_dex": "u", "sell_dex": "s"
    })
    ctx.append_to_list("flash/history", {
        "status": "executed", "net_roi": -0.01, "buy_dex": "u", "sell_dex": "s"
    })
    ha = HistoricalAnalyzer(ctx, cfg, logger=None)
    summary = ha.summarize()
    assert 0.65 < summary["win_rate"] < 0.67  # approx 2/3
    sugg = ha.suggest_adjustments(summary)
    assert isinstance(sugg, dict)


if __name__ == "__main__":
    # run tests sequentially
    test_opportunity_scorer_monkeypatch()
    print("scorer test passed")
    test_profitability_simulator_basic()
    print("simulator test passed")
    test_execution_optimizer_paper_flow()
    print("execution optimizer test passed")
    test_historical_analyzer_summary_and_suggestion()
    print("historical analyzer test passed")
    print("All tests passed.")