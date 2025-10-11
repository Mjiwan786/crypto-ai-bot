"""
Test suite for scalping signal generation and liquidity analysis.

This module provides comprehensive tests for signal generation, order book
analysis, and liquidity metrics used in the scalping trading system.

Features:
- Signal generator validation
- Order book analysis testing
- Liquidity metrics verification
- Edge case handling
- Performance validation
"""

from __future__ import annotations

import logging

import pytest
from crypto_ai_bot.scalper.data.market_store import MarketStore, TickRecord
from crypto_ai_bot.scalper.data.tick_processor import Features
from crypto_ai_bot.scalper.strategies.signal_generator import SignalGenerator

from agents.scalper.analysis.liquidity import (
    OrderBookLevel,
    OrderBookSnapshot,
    compose_liquidity_score,
    depth,
    imbalance_topk,
    liquidity_signal,
    mid_and_spread,
    normalize_scores,
    topk,
    validate_and_sort,
    vwap,
    weighted_mid,
)

logger = logging.getLogger(__name__)


def test_signal_generator_long_signal():
    gen = SignalGenerator(threshold=0.1)
    # create features with positive momentum and zero volatility
    features = Features(last_price=100, sma_short=110, sma_long=100, volatility=0)
    market = MarketStore(maxlen=10)
    # populate market with balanced buy/sell to get zero imbalance
    for _ in range(5):
        market.append(TickRecord(ts=0, price=100, volume=1, side="buy"))
        market.append(TickRecord(ts=0, price=100, volume=1, side="sell"))
    signal = gen.generate(features, market)
    assert signal.side == 1
    assert signal.strength > 0


def test_signal_generator_short_signal():
    gen = SignalGenerator(threshold=0.1)
    features = Features(last_price=100, sma_short=90, sma_long=100, volatility=0)
    market = MarketStore(maxlen=10)
    # skew to selling
    for _ in range(5):
        market.append(TickRecord(ts=0, price=100, volume=2, side="sell"))
        market.append(TickRecord(ts=0, price=100, volume=1, side="buy"))
    signal = gen.generate(features, market)
    assert signal.side == -1
    assert signal.strength < 0


# ===== LIQUIDITY ANALYSIS TESTS =====


def test_order_book_validation():
    """Test order book validation and sorting."""
    # Valid order book
    ob = OrderBookSnapshot(
        ts_ms=1000,
        bids=[
            OrderBookLevel(price=99.8, size=3),
            OrderBookLevel(price=100.0, size=2),
            OrderBookLevel(price=99.9, size=1),
        ],
        asks=[
            OrderBookLevel(price=100.2, size=2.5),
            OrderBookLevel(price=100.1, size=1.5),
            OrderBookLevel(price=100.3, size=1),
        ],
    )

    validated = validate_and_sort(ob)

    # Check sorting: bids desc, asks asc
    assert validated.bids[0].price == 100.0  # Highest bid first
    assert validated.bids[1].price == 99.9
    assert validated.bids[2].price == 99.8

    assert validated.asks[0].price == 100.1  # Lowest ask first
    assert validated.asks[1].price == 100.2
    assert validated.asks[2].price == 100.3


def test_order_book_validation_empty_sides():
    """Test validation raises error for empty sides."""
    # Empty bids
    ob = OrderBookSnapshot(ts_ms=1000, bids=[], asks=[OrderBookLevel(price=100.0, size=1.0)])
    with pytest.raises(
        ValueError, match="Order book must have at least one valid level on each side"
    ):
        validate_and_sort(ob)

    # Empty asks
    ob = OrderBookSnapshot(
        ts_ms=1000,
        bids=[OrderBookLevel(price=100.0, size=1.0)],
        asks=[],
    )
    with pytest.raises(
        ValueError, match="Order book must have at least one valid level on each side"
    ):
        validate_and_sort(ob)


def test_order_book_validation_zero_sizes():
    """Test validation drops zero-size levels."""
    ob = OrderBookSnapshot(
        ts_ms=1000,
        bids=[
            OrderBookLevel(price=100.0, size=2.0),
            OrderBookLevel(price=99.9, size=0.0),  # Should be dropped
        ],
        asks=[
            OrderBookLevel(price=100.1, size=1.5),
            OrderBookLevel(price=100.2, size=0.0),  # Should be dropped
        ],
    )

    validated = validate_and_sort(ob)
    assert len(validated.bids) == 1
    assert len(validated.asks) == 1
    assert validated.bids[0].price == 100.0
    assert validated.asks[0].price == 100.1


def test_topk():
    """Test top-k level selection."""
    levels = [
        OrderBookLevel(price=100.0, size=2.0),
        OrderBookLevel(price=99.9, size=1.0),
        OrderBookLevel(price=99.8, size=3.0),
    ]

    # Test k=2
    top2 = topk(levels, 2)
    assert len(top2) == 2
    assert top2[0].price == 100.0
    assert top2[1].price == 99.9

    # Test k=10 (more than available)
    top10 = topk(levels, 10)
    assert len(top10) == 3

    # Test k=0 (should clamp to 1)
    top1 = topk(levels, 0)
    assert len(top1) == 1


def test_mid_and_spread():
    """Test mid price and spread calculations."""
    # Normal case
    mid, spread_abs, spread_bps = mid_and_spread(100.0, 100.1)
    assert mid == pytest.approx(100.05, rel=1e-6)
    assert spread_abs == pytest.approx(0.1, rel=1e-6)
    assert spread_bps == pytest.approx(9.995, rel=1e-3)  # (0.1/100.05)*10000

    # Crossed book case
    mid, spread_abs, spread_bps = mid_and_spread(100.1, 100.0)
    assert mid == pytest.approx(100.05, rel=1e-6)
    assert spread_abs == pytest.approx(1e-9, rel=1e-6)  # Minimum spread
    assert spread_bps == pytest.approx(0.0, rel=1e-6)


def test_weighted_mid():
    """Test volume-weighted mid calculation."""
    ob = OrderBookSnapshot(
        ts_ms=1000,
        bids=[
            OrderBookLevel(price=100.0, size=2.0),
            OrderBookLevel(price=99.9, size=1.0),
        ],
        asks=[
            OrderBookLevel(price=100.1, size=1.5),
            OrderBookLevel(price=100.2, size=2.5),
        ],
    )

    wm = weighted_mid(ob, k=2)
    # Expected: (100.0*2 + 99.9*1 + 100.1*1.5 + 100.2*2.5) / (2+1+1.5+2.5)
    expected = (200.0 + 99.9 + 150.15 + 250.5) / 7.0
    assert wm == pytest.approx(expected, rel=1e-6)


def test_vwap():
    """Test VWAP calculation."""
    levels = [
        OrderBookLevel(price=100.0, size=2.0),
        OrderBookLevel(price=99.9, size=1.0),
        OrderBookLevel(price=99.8, size=3.0),
    ]

    vwap_price = vwap(levels)
    # Expected: (100.0*2 + 99.9*1 + 99.8*3) / (2+1+3) = 599.5 / 6
    expected = 599.5 / 6.0
    assert vwap_price == pytest.approx(expected, rel=1e-6)

    # Test empty levels
    assert vwap([]) == 0.0


def test_imbalance_topk():
    """Test order flow imbalance calculation."""
    bids = [
        OrderBookLevel(price=100.0, size=2.0),
        OrderBookLevel(price=99.9, size=1.0),
    ]
    asks = [
        OrderBookLevel(price=100.1, size=1.5),
        OrderBookLevel(price=100.2, size=2.5),
    ]

    imbalance = imbalance_topk(bids, asks, k=2)
    # Expected: (3.0 - 4.0) / 7.0 = -1/7 ≈ -0.143
    expected = (3.0 - 4.0) / 7.0
    assert imbalance == pytest.approx(expected, rel=1e-6)

    # Test all bids case
    imbalance_all_bids = imbalance_topk(bids, [], k=2)
    assert imbalance_all_bids == pytest.approx(1.0, rel=1e-6)

    # Test all asks case
    imbalance_all_asks = imbalance_topk([], asks, k=2)
    assert imbalance_all_asks == pytest.approx(-1.0, rel=1e-6)


def test_depth():
    """Test depth calculation."""
    levels = [
        OrderBookLevel(price=100.0, size=2.0),
        OrderBookLevel(price=99.9, size=1.0),
        OrderBookLevel(price=99.8, size=3.0),
    ]

    total_base, total_notional = depth(levels)
    assert total_base == pytest.approx(6.0, rel=1e-6)
    assert total_notional == pytest.approx(599.5, rel=1e-6)


def test_normalize_scores():
    """Test score normalization."""
    # Tight spread case
    tight_spread, depth_balance, imbalance = normalize_scores(
        spread_bps=0.5,  # Very tight
        depth_bid_notional=5000.0,
        depth_ask_notional=5000.0,  # Balanced
        imbalance=0.0,  # Neutral
    )

    assert tight_spread > 0.9  # Should be high for tight spread
    assert depth_balance > 0.5  # Should be decent for balanced depth
    assert imbalance == pytest.approx(0.5, rel=1e-6)  # Neutral imbalance

    # Wide spread case
    tight_spread_wide, _, _ = normalize_scores(
        spread_bps=25.0,  # Very wide
        depth_bid_notional=1000.0,
        depth_ask_notional=1000.0,
        imbalance=0.0,
    )
    assert tight_spread_wide < 0.1  # Should be low for wide spread


def test_compose_liquidity_score():
    """Test liquidity score composition."""
    overall, buy, sell = compose_liquidity_score(
        tight_spread_score=0.8, depth_balance_score=0.6, imbalance_score=0.3  # Bid-heavy
    )

    # All scores should be in [0,1]
    assert 0.0 <= overall <= 1.0
    assert 0.0 <= buy <= 1.0
    assert 0.0 <= sell <= 1.0

    # Buy score should be higher than sell for bid-heavy imbalance
    assert buy > sell


def test_liquidity_signal_happy_path():
    """Test complete liquidity signal generation - happy path."""
    ob = OrderBookSnapshot(
        ts_ms=1000,
        bids=[
            OrderBookLevel(price=100.0, size=2.0),
            OrderBookLevel(price=99.9, size=1.0),
            OrderBookLevel(price=99.8, size=3.0),
        ],
        asks=[
            OrderBookLevel(price=100.1, size=1.5),
            OrderBookLevel(price=100.2, size=2.5),
            OrderBookLevel(price=100.3, size=1.0),
        ],
    )

    signal = liquidity_signal(ob, k=3)

    # Check basic structure
    assert signal.ts_ms == 1000
    assert 0.0 <= signal.score_overall <= 1.0
    assert 0.0 <= signal.score_buy <= 1.0
    assert 0.0 <= signal.score_sell <= 1.0

    # Check features
    features = signal.features
    assert features.best_bid == 100.0
    assert features.best_ask == 100.1
    assert features.mid == pytest.approx(100.05, rel=1e-6)
    assert features.spread_abs == pytest.approx(0.1, rel=1e-6)
    assert features.k_used == 3

    # Check normalized scores
    assert 0.0 <= features.tight_spread_score <= 1.0
    assert 0.0 <= features.depth_balance_score <= 1.0
    assert 0.0 <= features.imbalance_score <= 1.0


def test_liquidity_signal_imbalance_extremes():
    """Test liquidity signal with extreme imbalances."""
    # Bid-heavy case
    ob_bid_heavy = OrderBookSnapshot(
        ts_ms=1000,
        bids=[
            OrderBookLevel(price=100.0, size=10.0),
            OrderBookLevel(price=99.9, size=5.0),
        ],
        asks=[
            OrderBookLevel(price=100.1, size=0.1),  # Tiny ask
        ],
    )

    signal_bid = liquidity_signal(ob_bid_heavy, k=2)
    assert signal_bid.score_buy > signal_bid.score_sell

    # Ask-heavy case
    ob_ask_heavy = OrderBookSnapshot(
        ts_ms=1000,
        bids=[
            OrderBookLevel(price=100.0, size=0.1),  # Tiny bid
        ],
        asks=[
            OrderBookLevel(price=100.1, size=10.0),
            OrderBookLevel(price=100.2, size=5.0),
        ],
    )

    signal_ask = liquidity_signal(ob_ask_heavy, k=2)
    assert signal_ask.score_sell > signal_ask.score_buy


def test_liquidity_signal_spread_monotonicity():
    """Test that tighter spreads produce higher scores."""
    # Tight spread book
    ob_tight = OrderBookSnapshot(
        ts_ms=1000,
        bids=[OrderBookLevel(price=100.0, size=2.0)],
        asks=[OrderBookLevel(price=100.1, size=1.5)],
    )

    # Wide spread book
    ob_wide = OrderBookSnapshot(
        ts_ms=1000,
        bids=[OrderBookLevel(price=100.0, size=2.0)],
        asks=[OrderBookLevel(price=100.5, size=1.5)],
    )

    signal_tight = liquidity_signal(ob_tight, k=1)
    signal_wide = liquidity_signal(ob_wide, k=1)

    assert signal_tight.score_overall > signal_wide.score_overall


def test_liquidity_signal_depth_monotonicity():
    """Test that deeper books produce higher scores."""
    # Shallow book
    ob_shallow = OrderBookSnapshot(
        ts_ms=1000,
        bids=[OrderBookLevel(price=100.0, size=1.0)],
        asks=[OrderBookLevel(price=100.1, size=1.0)],
    )

    # Deep book (3x size)
    ob_deep = OrderBookSnapshot(
        ts_ms=1000,
        bids=[OrderBookLevel(price=100.0, size=3.0)],
        asks=[OrderBookLevel(price=100.1, size=3.0)],
    )

    signal_shallow = liquidity_signal(ob_shallow, k=1)
    signal_deep = liquidity_signal(ob_deep, k=1)

    assert signal_deep.score_overall >= signal_shallow.score_overall


def test_liquidity_signal_k_clamping():
    """Test that k parameter is properly clamped."""
    ob = OrderBookSnapshot(
        ts_ms=1000,
        bids=[
            OrderBookLevel(price=100.0, size=2.0),
            OrderBookLevel(price=99.9, size=1.0),
        ],
        asks=[
            OrderBookLevel(price=100.1, size=1.5),
            OrderBookLevel(price=100.2, size=2.5),
        ],
    )

    # Request k=10 but only 2 levels available
    signal = liquidity_signal(ob, k=10)
    assert signal.features.k_used == 2

    # All aggregates should be consistent with k_used=2
    assert signal.features.depth_bid_base == pytest.approx(3.0, rel=1e-6)
    assert signal.features.depth_ask_base == pytest.approx(4.0, rel=1e-6)


def test_liquidity_signal_deterministic():
    """Test that same input produces same output."""
    ob = OrderBookSnapshot(
        ts_ms=1000,
        bids=[
            OrderBookLevel(price=100.0, size=2.0),
            OrderBookLevel(price=99.9, size=1.0),
        ],
        asks=[
            OrderBookLevel(price=100.1, size=1.5),
            OrderBookLevel(price=100.2, size=2.5),
        ],
    )

    signal1 = liquidity_signal(ob, k=2)
    signal2 = liquidity_signal(ob, k=2)

    # Should be identical
    assert signal1.score_overall == signal2.score_overall
    assert signal1.score_buy == signal2.score_buy
    assert signal1.score_sell == signal2.score_sell
    assert signal1.features.best_bid == signal2.features.best_bid
    assert signal1.features.best_ask == signal2.features.best_ask
