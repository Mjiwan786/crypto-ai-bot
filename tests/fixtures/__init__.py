"""Test fixtures for crypto-ai-bot tests."""

from tests.fixtures.ohlcv_fixture import (
    generate_ohlcv_fixture,
    generate_ema_crossover_fixture,
    generate_breakout_fixture,
    generate_no_signal_fixture,
    OHLCV_FIXTURE_300_BARS,
    OHLCV_FIXTURE_EMA_CROSSOVER,
    OHLCV_FIXTURE_BREAKOUT,
    OHLCV_FIXTURE_NO_SIGNAL,
)
from tests.fixtures.indicator_fixtures import (
    create_market_snapshot,
    rsi_oversold_crossover_snapshot,
    rsi_overbought_crossover_snapshot,
    rsi_neutral_snapshot,
    ema_bullish_crossover_snapshot,
    ema_bearish_crossover_snapshot,
    ema_no_crossover_snapshot,
    macd_bullish_crossover_snapshot,
    macd_bearish_crossover_snapshot,
    macd_no_crossover_snapshot,
    breakout_bullish_snapshot,
    breakout_bearish_snapshot,
    breakout_no_signal_snapshot,
    insufficient_data_snapshot,
)

__all__ = [
    # OHLCV fixtures
    "generate_ohlcv_fixture",
    "generate_ema_crossover_fixture",
    "generate_breakout_fixture",
    "generate_no_signal_fixture",
    "OHLCV_FIXTURE_300_BARS",
    "OHLCV_FIXTURE_EMA_CROSSOVER",
    "OHLCV_FIXTURE_BREAKOUT",
    "OHLCV_FIXTURE_NO_SIGNAL",
    # MarketSnapshot fixtures
    "create_market_snapshot",
    "rsi_oversold_crossover_snapshot",
    "rsi_overbought_crossover_snapshot",
    "rsi_neutral_snapshot",
    "ema_bullish_crossover_snapshot",
    "ema_bearish_crossover_snapshot",
    "ema_no_crossover_snapshot",
    "macd_bullish_crossover_snapshot",
    "macd_bearish_crossover_snapshot",
    "macd_no_crossover_snapshot",
    "breakout_bullish_snapshot",
    "breakout_bearish_snapshot",
    "breakout_no_signal_snapshot",
    "insufficient_data_snapshot",
]
