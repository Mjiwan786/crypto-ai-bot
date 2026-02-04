"""
Test fixtures for indicator strategy tests.

Provides deterministic MarketSnapshot fixtures for testing strategy evaluators.
No external data downloads required.
"""

from datetime import datetime, timezone
from decimal import Decimal

from shared_contracts import MarketSnapshot


def create_market_snapshot(
    pair: str = "BTC/USD",
    bid: float = 50000.0,
    ask: float = 50010.0,
    last_price: float = 50005.0,
    closes: list[float] | None = None,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    volumes: list[float] | None = None,
    indicators: dict | None = None,
    regime: str = "trending_up",
    volatility: str = "normal",
) -> MarketSnapshot:
    """Create a deterministic MarketSnapshot for testing."""
    ind = indicators or {}

    if closes:
        ind["closes"] = closes
    if highs:
        ind["highs"] = highs
    if lows:
        ind["lows"] = lows
    if volumes:
        ind["volumes"] = volumes

    return MarketSnapshot(
        pair=pair,
        bid=Decimal(str(bid)),
        ask=Decimal(str(ask)),
        last_price=Decimal(str(last_price)),
        spread_bps=(ask - bid) / ((ask + bid) / 2) * 10000,
        indicators=ind,
        regime=regime,
        volatility=volatility,
    )


# ============================================================================
# RSI FIXTURES - Oversold/Overbought conditions
# ============================================================================

def rsi_oversold_crossover_snapshot() -> MarketSnapshot:
    """
    MarketSnapshot where RSI crosses UP through 30 (oversold -> signal).

    RSI sequence: [28, 27, 26, 25, 28, 31]  (crosses up through 30)
    This requires closes that produce this RSI pattern.
    """
    # Closes that produce RSI crossing up through 30
    # Start with downtrend (low RSI), then slight uptick
    closes = [
        50500, 50400, 50300, 50200, 50100,  # Strong downtrend
        50000, 49900, 49800, 49700, 49600,  # Continued selling
        49500, 49450, 49400, 49380, 49370,  # Slowing decline
        49400, 49500,  # Small bounce - RSI crosses up
    ]

    return create_market_snapshot(
        pair="BTC/USD",
        last_price=49500,
        bid=49495,
        ask=49505,
        closes=closes,
        indicators={
            "closes": closes,
            "ema_50": 50000,  # Price below EMA (trend filter will fail for long with trend)
        },
        regime="ranging",
    )


def rsi_overbought_crossover_snapshot() -> MarketSnapshot:
    """
    MarketSnapshot where RSI crosses DOWN through 70 (overbought -> signal).

    RSI high then crossing down.
    """
    # Closes that produce RSI crossing down through 70
    closes = [
        49500, 49600, 49700, 49800, 49900,  # Strong uptrend
        50000, 50100, 50200, 50300, 50400,  # Continued buying
        50500, 50550, 50600, 50620, 50630,  # Slowing advance
        50600, 50500,  # Small pullback - RSI crosses down
    ]

    return create_market_snapshot(
        pair="BTC/USD",
        last_price=50500,
        bid=50495,
        ask=50505,
        closes=closes,
        indicators={
            "closes": closes,
            "ema_50": 50000,  # Price above EMA
        },
        regime="trending_up",
    )


def rsi_neutral_snapshot() -> MarketSnapshot:
    """MarketSnapshot with RSI in neutral zone (40-60), no signal expected."""
    # Closes that produce RSI around 50
    closes = [
        50000, 50050, 50000, 50050, 50000,
        50050, 50000, 50050, 50000, 50050,
        50000, 50050, 50000, 50050, 50000,
        50050, 50000,
    ]

    return create_market_snapshot(
        pair="BTC/USD",
        last_price=50000,
        bid=49995,
        ask=50005,
        closes=closes,
        regime="ranging",
    )


# ============================================================================
# EMA FIXTURES - Crossover conditions
# ============================================================================

def ema_bullish_crossover_snapshot() -> MarketSnapshot:
    """
    MarketSnapshot where fast EMA crosses above slow EMA.

    Trend starts down, then reverses with fast EMA crossing above slow.
    """
    # Create a clear bullish crossover pattern
    # Downtrend -> bottom -> uptrend (fast crosses slow)
    closes = [
        51000, 50900, 50800, 50700, 50600,  # Down
        50500, 50400, 50350, 50300, 50280,  # Continued down, slowing
        50260, 50250, 50240, 50230, 50220,  # Bottom forming
        50210, 50200, 50190, 50180, 50175,  # Flat bottom
        50180, 50200, 50230, 50270, 50320,  # Reversal begins
        50380, 50450, 50530, 50620, 50720,  # Strong reversal - crossover
    ]

    return create_market_snapshot(
        pair="ETH/USD",
        last_price=50720,
        bid=50715,
        ask=50725,
        closes=closes,
        regime="trending_up",
    )


def ema_bearish_crossover_snapshot() -> MarketSnapshot:
    """
    MarketSnapshot where fast EMA crosses below slow EMA.
    """
    # Uptrend -> top -> downtrend (fast crosses below slow)
    closes = [
        49000, 49100, 49200, 49300, 49400,  # Up
        49500, 49600, 49650, 49700, 49720,  # Continued up, slowing
        49740, 49750, 49760, 49770, 49780,  # Top forming
        49790, 49800, 49810, 49820, 49825,  # Flat top
        49820, 49800, 49770, 49730, 49680,  # Reversal begins
        49620, 49550, 49470, 49380, 49280,  # Strong reversal - crossover
    ]

    return create_market_snapshot(
        pair="ETH/USD",
        last_price=49280,
        bid=49275,
        ask=49285,
        closes=closes,
        regime="trending_down",
    )


def ema_no_crossover_snapshot() -> MarketSnapshot:
    """MarketSnapshot with no EMA crossover (trending, EMAs parallel)."""
    # Steady uptrend, EMAs parallel, no crossover
    closes = [
        48000, 48100, 48200, 48300, 48400,
        48500, 48600, 48700, 48800, 48900,
        49000, 49100, 49200, 49300, 49400,
        49500, 49600, 49700, 49800, 49900,
        50000, 50100, 50200, 50300, 50400,
        50500, 50600, 50700, 50800, 50900,
    ]

    return create_market_snapshot(
        pair="ETH/USD",
        last_price=50900,
        bid=50895,
        ask=50905,
        closes=closes,
        regime="trending_up",
    )


# ============================================================================
# MACD FIXTURES - Crossover conditions
# ============================================================================

def macd_bullish_crossover_snapshot() -> MarketSnapshot:
    """
    MarketSnapshot where MACD line crosses above signal line.

    Requires enough data for MACD calculation (26 + 9 = 35 bars minimum).
    """
    # Create pattern that produces MACD bullish crossover
    # Strong downtrend -> consolidation -> reversal
    closes = [
        52000, 51900, 51800, 51700, 51600,  # 5 - downtrend
        51500, 51400, 51300, 51200, 51100,  # 10
        51000, 50900, 50800, 50700, 50600,  # 15
        50500, 50450, 50400, 50350, 50300,  # 20 - slowing
        50280, 50260, 50250, 50240, 50230,  # 25 - base forming
        50220, 50210, 50200, 50195, 50190,  # 30 - flat
        50200, 50220, 50250, 50290, 50340,  # 35 - bounce
        50400, 50480, 50580, 50700, 50840,  # 40 - strong reversal
    ]

    return create_market_snapshot(
        pair="BTC/USD",
        last_price=50840,
        bid=50835,
        ask=50845,
        closes=closes,
        regime="ranging",
    )


def macd_bearish_crossover_snapshot() -> MarketSnapshot:
    """
    MarketSnapshot where MACD line crosses below signal line.
    """
    # Strong uptrend -> consolidation -> reversal down
    closes = [
        48000, 48100, 48200, 48300, 48400,  # 5 - uptrend
        48500, 48600, 48700, 48800, 48900,  # 10
        49000, 49100, 49200, 49300, 49400,  # 15
        49500, 49550, 49600, 49650, 49700,  # 20 - slowing
        49720, 49740, 49750, 49760, 49770,  # 25 - top forming
        49780, 49790, 49800, 49805, 49810,  # 30 - flat
        49800, 49780, 49750, 49710, 49660,  # 35 - roll over
        49600, 49520, 49420, 49300, 49160,  # 40 - strong down
    ]

    return create_market_snapshot(
        pair="BTC/USD",
        last_price=49160,
        bid=49155,
        ask=49165,
        closes=closes,
        regime="ranging",
    )


def macd_no_crossover_snapshot() -> MarketSnapshot:
    """MarketSnapshot with no MACD crossover."""
    # Steady trend, no MACD crossover
    closes = [
        48000 + i * 50 for i in range(45)  # Steady uptrend
    ]

    return create_market_snapshot(
        pair="BTC/USD",
        last_price=50200,
        bid=50195,
        ask=50205,
        closes=closes,
        regime="trending_up",
    )


# ============================================================================
# BREAKOUT FIXTURES - HH/LL conditions
# ============================================================================

def breakout_bullish_snapshot() -> MarketSnapshot:
    """
    MarketSnapshot with price breaking above 20-bar high.
    """
    # Range, then breakout to new high
    highs = [
        50100, 50150, 50200, 50180, 50160,  # 5
        50140, 50120, 50100, 50080, 50060,  # 10 - declining highs
        50080, 50100, 50120, 50140, 50160,  # 15 - base forming
        50180, 50200, 50220, 50200, 50180,  # 20 - consolidation (HH = 50220)
        50400,  # 21 - BREAKOUT above HH
    ]

    lows = [
        49900, 49850, 49800, 49820, 49840,
        49860, 49880, 49900, 49920, 49940,
        49920, 49900, 49880, 49860, 49840,
        49820, 49800, 49780, 49800, 49820,
        50100,  # Breakout bar
    ]

    closes = [
        50000, 50000, 50000, 50000, 50000,
        50000, 50000, 50000, 50000, 50000,
        50000, 50000, 50000, 50000, 50000,
        50000, 50000, 50000, 50000, 50000,
        50350,  # Close near high on breakout
    ]

    volumes = [
        1000, 1000, 1000, 1000, 1000,
        1000, 1000, 1000, 1000, 1000,
        1000, 1000, 1000, 1000, 1000,
        1000, 1000, 1000, 1000, 1000,
        2500,  # High volume on breakout
    ]

    return create_market_snapshot(
        pair="BTC/USD",
        last_price=50350,
        bid=50345,
        ask=50355,
        highs=highs,
        lows=lows,
        closes=closes,
        volumes=volumes,
        regime="ranging",
    )


def breakout_bearish_snapshot() -> MarketSnapshot:
    """
    MarketSnapshot with price breaking below 20-bar low.
    """
    # Range, then breakdown to new low
    highs = [
        50100, 50080, 50060, 50080, 50100,
        50120, 50140, 50160, 50180, 50200,
        50180, 50160, 50140, 50120, 50100,
        50080, 50060, 50040, 50060, 50080,
        49700,  # Breakdown bar
    ]

    lows = [
        49900, 49920, 49940, 49920, 49900,
        49880, 49860, 49840, 49820, 49800,  # LL = 49800
        49820, 49840, 49860, 49880, 49900,
        49920, 49940, 49960, 49940, 49920,
        49500,  # BREAKDOWN below LL
    ]

    closes = [
        50000, 50000, 50000, 50000, 50000,
        50000, 50000, 50000, 50000, 50000,
        50000, 50000, 50000, 50000, 50000,
        50000, 50000, 50000, 50000, 50000,
        49600,  # Close near low on breakdown
    ]

    volumes = [
        1000, 1000, 1000, 1000, 1000,
        1000, 1000, 1000, 1000, 1000,
        1000, 1000, 1000, 1000, 1000,
        1000, 1000, 1000, 1000, 1000,
        2500,  # High volume on breakdown
    ]

    return create_market_snapshot(
        pair="BTC/USD",
        last_price=49600,
        bid=49595,
        ask=49605,
        highs=highs,
        lows=lows,
        closes=closes,
        volumes=volumes,
        regime="ranging",
    )


def breakout_no_signal_snapshot() -> MarketSnapshot:
    """MarketSnapshot with no breakout (price within range)."""
    # Tight range, no breakout
    highs = [50100] * 21
    lows = [49900] * 21
    closes = [50000] * 21

    return create_market_snapshot(
        pair="BTC/USD",
        last_price=50000,
        bid=49995,
        ask=50005,
        highs=highs,
        lows=lows,
        closes=closes,
        regime="ranging",
    )


# ============================================================================
# INSUFFICIENT DATA FIXTURES
# ============================================================================

def insufficient_data_snapshot() -> MarketSnapshot:
    """MarketSnapshot with insufficient historical data."""
    return create_market_snapshot(
        pair="BTC/USD",
        last_price=50000,
        bid=49995,
        ask=50005,
        closes=[50000, 50010, 50005],  # Only 3 bars
        regime="unknown",
    )
