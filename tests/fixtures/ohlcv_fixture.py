"""
Deterministic OHLCV Fixture Data for Backtest Tests.

Provides synthetic price data with known patterns for testing:
- Trending up periods (bullish signals expected)
- Trending down periods (bearish signals expected)
- Ranging periods (may or may not trigger signals)
- Specific RSI/EMA conditions for signal triggering

No external downloads required - all data is generated deterministically.
"""

from datetime import datetime, timezone, timedelta
import math


def generate_ohlcv_fixture(
    num_bars: int = 300,
    start_price: float = 50000.0,
    start_time: datetime | None = None,
    timeframe_minutes: int = 5,
) -> list[dict]:
    """
    Generate deterministic OHLCV data with trading patterns.

    Args:
        num_bars: Number of bars to generate
        start_price: Starting price
        start_time: Start timestamp (default: 2024-01-01 00:00 UTC)
        timeframe_minutes: Bar timeframe in minutes

    Returns:
        List of OHLCV bar dictionaries
    """
    if start_time is None:
        start_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    bars = []
    price = start_price
    time_delta = timedelta(minutes=timeframe_minutes)

    for i in range(num_bars):
        timestamp = start_time + (time_delta * i)

        # Generate price movement based on phase
        # Phase 1 (0-100): Initial range/consolidation
        # Phase 2 (100-150): Downtrend (RSI oversold expected)
        # Phase 3 (150-200): Bounce and uptrend (bullish signals)
        # Phase 4 (200-250): Strong uptrend (RSI overbought expected)
        # Phase 5 (250-300): Reversal down (bearish signals)

        phase = i // 50
        phase_position = (i % 50) / 50  # 0-1 within phase

        if phase == 0:
            # Consolidation with slight volatility
            change_pct = 0.001 * math.sin(i * 0.5) + 0.0002 * (i % 7 - 3)
        elif phase == 1:
            # Downtrend
            change_pct = -0.003 - 0.002 * phase_position
        elif phase == 2:
            # Bounce and recovery
            if phase_position < 0.3:
                change_pct = -0.001  # Final drop
            else:
                change_pct = 0.004 * (phase_position - 0.3)  # Recovery
        elif phase == 3:
            # Strong uptrend
            change_pct = 0.003 + 0.001 * math.sin(i * 0.3)
        elif phase == 4:
            # Uptrend continuation then exhaustion
            if phase_position < 0.6:
                change_pct = 0.002
            else:
                change_pct = -0.002 * (phase_position - 0.6) * 5  # Reversal
        else:
            # Extended consolidation/slight decline
            change_pct = -0.001 * math.sin(i * 0.2)

        # Apply change
        price = price * (1 + change_pct)

        # Generate OHLC from price
        volatility = 0.002  # 0.2% intrabar volatility
        open_price = price * (1 + (i % 3 - 1) * volatility * 0.3)
        close_price = price
        high_price = max(open_price, close_price) * (1 + volatility * (0.5 + (i % 5) / 10))
        low_price = min(open_price, close_price) * (1 - volatility * (0.5 + (i % 7) / 14))

        # Volume varies with trend strength
        base_volume = 1000
        volume = base_volume * (1 + abs(change_pct) * 100)

        bars.append({
            "timestamp": timestamp.isoformat(),
            "open": round(open_price, 2),
            "high": round(high_price, 2),
            "low": round(low_price, 2),
            "close": round(close_price, 2),
            "volume": round(volume, 2),
        })

    return bars


def generate_ema_crossover_fixture(num_bars: int = 100) -> list[dict]:
    """
    Generate OHLCV data that will produce an EMA crossover.

    Creates a pattern where fast EMA crosses above slow EMA around bar 70.
    """
    start_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    time_delta = timedelta(minutes=5)
    bars = []

    base_price = 50000.0

    for i in range(num_bars):
        timestamp = start_time + (time_delta * i)

        # Create crossover pattern
        if i < 40:
            # Downtrend: fast EMA below slow
            price = base_price - i * 20
        elif i < 60:
            # Bottom formation
            price = base_price - 40 * 20 + (i - 40) * 5
        else:
            # Uptrend: fast EMA crosses above slow around bar 70
            price = base_price - 40 * 20 + 20 * 5 + (i - 60) * 40

        volatility = 0.001
        open_price = price * (1 - volatility)
        close_price = price
        high_price = price * (1 + volatility * 1.5)
        low_price = price * (1 - volatility * 1.5)

        bars.append({
            "timestamp": timestamp.isoformat(),
            "open": round(open_price, 2),
            "high": round(high_price, 2),
            "low": round(low_price, 2),
            "close": round(close_price, 2),
            "volume": 1000.0,
        })

    return bars


def generate_breakout_fixture(num_bars: int = 50) -> list[dict]:
    """
    Generate OHLCV data with a clear breakout pattern.

    Creates consolidation then breakout above resistance.
    """
    start_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    time_delta = timedelta(minutes=5)
    bars = []

    base_price = 50000.0
    resistance = 50200.0

    for i in range(num_bars):
        timestamp = start_time + (time_delta * i)

        if i < 30:
            # Consolidation below resistance
            price = base_price + (i % 5) * 20 - 40  # Oscillate around base
            high = min(price * 1.002, resistance - 10)  # Don't break resistance
        elif i < 35:
            # Building pressure
            price = resistance - 50 + (i - 30) * 10
            high = resistance - 5
        else:
            # Breakout!
            price = resistance + (i - 35) * 30
            high = price * 1.003

        volatility = 0.001
        open_price = price * (1 - volatility * 0.5)
        close_price = price
        low_price = price * (1 - volatility * 1.5)

        bars.append({
            "timestamp": timestamp.isoformat(),
            "open": round(open_price, 2),
            "high": round(high, 2),
            "low": round(low_price, 2),
            "close": round(close_price, 2),
            "volume": 1000.0 + (500.0 if i >= 35 else 0),  # Volume spike on breakout
        })

    return bars


def generate_no_signal_fixture(num_bars: int = 100) -> list[dict]:
    """
    Generate OHLCV data that should NOT produce any signals.

    Creates sideways price action with indicators in neutral zones.
    """
    start_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    time_delta = timedelta(minutes=5)
    bars = []

    base_price = 50000.0

    for i in range(num_bars):
        timestamp = start_time + (time_delta * i)

        # Sideways: oscillate around base price
        price = base_price + math.sin(i * 0.2) * 50

        volatility = 0.0005
        open_price = price * (1 - volatility)
        close_price = price
        high_price = price * (1 + volatility)
        low_price = price * (1 - volatility)

        bars.append({
            "timestamp": timestamp.isoformat(),
            "open": round(open_price, 2),
            "high": round(high_price, 2),
            "low": round(low_price, 2),
            "close": round(close_price, 2),
            "volume": 1000.0,
        })

    return bars


# Pre-generated fixture data for tests (deterministic)
OHLCV_FIXTURE_300_BARS = generate_ohlcv_fixture(300)
OHLCV_FIXTURE_EMA_CROSSOVER = generate_ema_crossover_fixture(100)
OHLCV_FIXTURE_BREAKOUT = generate_breakout_fixture(50)
OHLCV_FIXTURE_NO_SIGNAL = generate_no_signal_fixture(100)
