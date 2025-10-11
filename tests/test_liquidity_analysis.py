import math
import pytest

from agents.scalper.analysis.liquidity import (
    OrderBookLevel,
    OrderBookSnapshot,
    liquidity_ratio,
    calculate_book_imbalance,
    calculate_market_impact,
    calculate_weighted_spread,
    calculate_liquidity_score,
    analyze_liquidity,
    should_scalp_market,
)

# Minimal TickRecord stub if your real one isn't available in test context.
class TickRecord:
    def __init__(self, price: float, volume: float):
        self.price = price
        self.volume = volume


def _mk_ob(
    bid_levels, ask_levels, ts=0.0, sym="X/USDT", sort=True
) -> OrderBookSnapshot:
    bids = [OrderBookLevel(*b) for b in bid_levels]
    asks = [OrderBookLevel(*a) for a in ask_levels]
    if sort:
        bids.sort(key=lambda l: l.price, reverse=True)
        asks.sort(key=lambda l: l.price)
    return OrderBookSnapshot(timestamp=ts, symbol=sym, bids=bids, asks=asks)


def test_liquidity_ratio_basic():
    ticks = [TickRecord(100.0, 2.0), TickRecord(101.0, 4.0), TickRecord(100.5, 0.0)]
    assert liquidity_ratio(ticks) == pytest.approx((2.0 + 4.0 + 0.0) / 3.0)

    assert liquidity_ratio([]) == 0.0


def test_imbalance_symmetric():
    ob = _mk_ob(
        bid_levels=[(99.0, 10.0, 2), (98.5, 5.0, 1)],
        ask_levels=[(101.0, 10.0, 2), (101.5, 5.0, 1)],
    )
    imb = calculate_book_imbalance(ob.bids, ob.asks, levels=2)
    assert imb == pytest.approx(0.5, abs=1e-9)


def test_imbalance_buy_pressure():
    ob = _mk_ob(
        bid_levels=[(99.0, 20.0, 2), (98.5, 10.0, 1)],
        ask_levels=[(101.0, 5.0, 2), (101.5, 5.0, 1)],
    )
    imb = calculate_book_imbalance(ob.bids, ob.asks, levels=2)
    assert 0.5 < imb < 1.0


def test_weighted_spread_and_mid():
    ob = _mk_ob(
        bid_levels=[(100.0, 10.0, 2), (99.9, 10.0, 2), (99.8, 10.0, 2)],
        ask_levels=[(100.2, 10.0, 2), (100.3, 10.0, 2), (100.4, 10.0, 2)],
    )
    assert ob.mid_price == pytest.approx((100.0 + 100.2) / 2.0)
    ws = calculate_weighted_spread(ob, levels=3)
    assert 0.0 <= ws < 30.0  # bps


def test_market_impact_finite_when_depth_sufficient():
    ob = _mk_ob(
        bid_levels=[(100.0, 20.0, 2), (99.8, 20.0, 2), (99.6, 20.0, 2)],
        ask_levels=[(100.2, 20.0, 2), (100.4, 20.0, 2), (100.6, 20.0, 2)],
    )
    impact = calculate_market_impact(ob, trade_size_usd=1_000.0, side="buy")
    assert math.isfinite(impact)
    assert impact >= 0.0


def test_market_impact_inf_when_insufficient_depth():
    ob = _mk_ob(
        bid_levels=[(100.0, 0.1, 1)],
        ask_levels=[(100.2, 0.1, 1)],
    )
    # Trade too large for available depth
    impact = calculate_market_impact(ob, trade_size_usd=10_000.0, side="buy")
    assert impact == float("inf")


def test_liquidity_score_monotonicity_on_spread():
    tight = _mk_ob(
        bid_levels=[(100.0, 50.0, 5)],
        ask_levels=[(100.02, 50.0, 5)],
    )
    wide = _mk_ob(
        bid_levels=[(100.0, 50.0, 5)],
        ask_levels=[(100.50, 50.0, 5)],
    )
    recent_vol = 500_000.0
    s_tight = calculate_liquidity_score(tight, recent_vol)
    s_wide = calculate_liquidity_score(wide, recent_vol)
    assert s_tight > s_wide


def test_analyze_liquidity_and_gate():
    ob = _mk_ob(
        bid_levels=[(100.0, 100.0, 10), (99.9, 80.0, 8), (99.8, 60.0, 6)],
        ask_levels=[(100.02, 100.0, 10), (100.1, 80.0, 8), (100.2, 60.0, 6)],
    )
    ticks = [TickRecord(100.05, 5_000.0) for _ in range(10)]  # robust recent flow
    cfg = {
        "SCALP_TYPICAL_SIZE_USD": 10_000.0,
        "SCALP_MIN_LIQUIDITY_USD": 200_000.0,
        "SCALP_MAX_SPREAD_BPS": 6.0,
        "SCALP_BOOK_IMBALANCE_MIN": 0.35,
        "SCALP_MIN_BOOK_DEPTH_LEVELS": 2,
        "SCALP_MAX_SLIPPAGE_BPS": 10.0,
        "SCALP_MIN_SUITABILITY_SCORE": 0.4,
    }

    metrics = analyze_liquidity(ob, ticks, cfg)
    assert metrics.total_liquidity_usd > 0.0
    assert math.isfinite(metrics.spread_bps)
    assert 0.0 <= metrics.book_imbalance <= 1.0
    assert metrics.book_depth_levels >= 1
    assert metrics.liquidity_score >= 0.0
    assert 0.0 <= metrics.scalping_suitability <= 1.0

    ok, reason = should_scalp_market(metrics, cfg)
    assert isinstance(ok, bool) and isinstance(reason, str)


def test_should_scalp_hard_fails():
    # Extremely wide spread + low depth should fail quickly
    ob = _mk_ob(
        bid_levels=[(100.0, 1.0, 1)],
        ask_levels=[(101.5, 1.0, 1)],
    )
    ticks = [TickRecord(100.0, 1.0)]
    cfg = {
        "SCALP_MIN_LIQUIDITY_USD": 1_000_000.0,
        "SCALP_MAX_SPREAD_BPS": 5.0,
        "SCALP_BOOK_IMBALANCE_MIN": 0.5,
        "SCALP_MIN_BOOK_DEPTH_LEVELS": 5,
        "SCALP_MAX_SLIPPAGE_BPS": 4.0,
        "SCALP_MIN_SUITABILITY_SCORE": 0.7,
    }
    metrics = analyze_liquidity(ob, ticks, cfg)
    ok, reason = should_scalp_market(metrics, cfg)
    assert ok is False
    assert isinstance(reason, str) and len(reason) > 0
