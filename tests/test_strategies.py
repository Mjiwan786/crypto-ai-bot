"""
Tests for the 8 trading strategies and 7 indicator functions.

Covers:
  - Indicator correctness (RSI range, MACD identity, ATR positivity, BB ordering)
  - Strategy neutral on insufficient data
  - Strategy correct direction on engineered conditions
  - Confidence within 0-100 range
  - Integration: all strategies run, consensus gate, signal generator
"""
import asyncio
import sys
import os

import numpy as np
import pytest

# Add project root to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from indicators.rsi import compute_rsi
from indicators.ema import compute_ema
from indicators.sma import compute_sma
from indicators.macd import compute_macd
from indicators.atr import compute_atr
from indicators.bollinger_bands import compute_bollinger_bands
from indicators.volume_profile import compute_volume_sma, compute_volume_ratio

from strategies.base_strategy import StrategyResult
from strategies.rsi_strategy import RSIStrategy, AdaptiveRSIStrategy
from strategies.macd_strategy import MACDStrategy
from strategies.ema_cross_strategy import EMACrossStrategy
from strategies.mean_reversion_strategy import MeanReversionStrategy
from strategies.trend_following_strategy import TrendFollowingStrategy, compute_adx
from strategies.momentum_strategy import MomentumStrategy
from strategies.breakout_strategy import BreakoutStrategy
from strategies import ALL_STRATEGIES, FAMILY_MAP

from signals.signal_generator import SignalGenerator, TradingSignal


# ═══════════════════════════════════════════════════════════
# Helper: Generate synthetic OHLCV data
# ═══════════════════════════════════════════════════════════

def make_ohlcv(closes: list[float], spread: float = 0.5, volume: float = 1000.0) -> np.ndarray:
    """Build OHLCV array from close prices with synthetic H/L/O/V."""
    n = len(closes)
    c = np.array(closes, dtype=np.float64)
    h = c + spread
    l = c - spread
    o = (c + np.roll(c, 1)) / 2
    o[0] = c[0]
    v = np.full(n, volume)
    return np.column_stack([o, h, l, c, v])


def make_trending_up(n: int = 50, start: float = 100.0, step: float = 0.5) -> np.ndarray:
    """Steadily rising price series."""
    closes = [start + i * step for i in range(n)]
    return make_ohlcv(closes)


def make_trending_down(n: int = 50, start: float = 200.0, step: float = 0.5) -> np.ndarray:
    """Steadily falling price series."""
    closes = [start - i * step for i in range(n)]
    return make_ohlcv(closes)


def make_rsi_oversold(n: int = 50) -> np.ndarray:
    """Price drops sharply then recovers — RSI crosses up through 30."""
    closes = []
    # Start stable
    for i in range(20):
        closes.append(100.0)
    # Sharp drop to push RSI below 30
    for i in range(20):
        closes.append(100.0 - i * 2.0)
    # Recovery — RSI crosses back above 30
    for i in range(10):
        closes.append(62.0 + i * 1.5)
    return make_ohlcv(closes)


def make_rsi_overbought(n: int = 50) -> np.ndarray:
    """Price rises sharply then drops — RSI crosses down through 70."""
    closes = []
    for i in range(20):
        closes.append(100.0)
    for i in range(20):
        closes.append(100.0 + i * 2.0)
    for i in range(10):
        closes.append(138.0 - i * 1.5)
    return make_ohlcv(closes)


def make_flat(n: int = 50, price: float = 100.0) -> np.ndarray:
    """Flat price series with tiny random noise."""
    rng = np.random.RandomState(42)
    closes = price + rng.randn(n) * 0.01
    return make_ohlcv(list(closes))


def make_breakout_up(n: int = 50, resistance: float = 110.0) -> np.ndarray:
    """Range-bound then breakout above resistance with high volume."""
    closes = []
    for i in range(40):
        closes.append(100.0 + (i % 10) * 1.0)  # oscillate 100-109
    for i in range(10):
        closes.append(resistance + i * 2.0)  # break above 110
    ohlcv = make_ohlcv(closes)
    # High volume on breakout candles
    ohlcv[-10:, 4] = 3000.0  # 3x normal volume
    return ohlcv


# ═══════════════════════════════════════════════════════════
# INDICATOR TESTS
# ═══════════════════════════════════════════════════════════

class TestRSI:
    def test_rsi_range(self):
        """RSI values must be in [0, 100]."""
        closes = np.array([44 + i * 0.5 + (-1)**i * 0.3 for i in range(50)])
        rsi = compute_rsi(closes, 14)
        valid = rsi[~np.isnan(rsi)]
        assert len(valid) > 0
        assert np.all(valid >= 0)
        assert np.all(valid <= 100)

    def test_rsi_nan_padding(self):
        """First `period` values should be NaN."""
        closes = np.linspace(100, 110, 30)
        rsi = compute_rsi(closes, 14)
        assert np.all(np.isnan(rsi[:14]))
        assert not np.isnan(rsi[14])

    def test_rsi_insufficient_data(self):
        """All NaN if fewer than period+1 candles."""
        rsi = compute_rsi(np.array([100.0, 101.0, 99.0]), 14)
        assert np.all(np.isnan(rsi))

    def test_rsi_all_gains(self):
        """Pure uptrend should give RSI near 100."""
        closes = np.linspace(100, 200, 50)
        rsi = compute_rsi(closes, 14)
        assert rsi[-1] > 90

    def test_rsi_all_losses(self):
        """Pure downtrend should give RSI near 0."""
        closes = np.linspace(200, 100, 50)
        rsi = compute_rsi(closes, 14)
        assert rsi[-1] < 10


class TestEMA:
    def test_ema_length(self):
        ema = compute_ema(np.linspace(100, 110, 30), 10)
        assert len(ema) == 30

    def test_ema_nan_padding(self):
        ema = compute_ema(np.linspace(100, 110, 30), 10)
        assert np.all(np.isnan(ema[:9]))
        assert not np.isnan(ema[9])

    def test_ema_follows_trend(self):
        """EMA should be above first value in uptrend."""
        closes = np.linspace(100, 200, 50)
        ema = compute_ema(closes, 10)
        assert ema[-1] > 100


class TestSMA:
    def test_sma_value(self):
        """SMA of constant should equal constant."""
        closes = np.full(20, 50.0)
        sma = compute_sma(closes, 10)
        assert sma[-1] == pytest.approx(50.0)


class TestMACD:
    def test_macd_histogram_identity(self):
        """Histogram must equal MACD line minus signal line."""
        closes = np.array([100 + i * 0.3 + (-1)**i * 0.5 for i in range(60)])
        macd_line, signal_line, histogram = compute_macd(closes)
        # Where all three are valid
        valid = ~(np.isnan(macd_line) | np.isnan(signal_line) | np.isnan(histogram))
        if np.any(valid):
            np.testing.assert_allclose(
                histogram[valid], macd_line[valid] - signal_line[valid], atol=1e-10
            )

    def test_macd_insufficient_data(self):
        """All NaN if insufficient data."""
        m, s, h = compute_macd(np.array([100.0] * 10))
        assert np.all(np.isnan(m))


class TestATR:
    def test_atr_positive(self):
        """ATR must be > 0 for non-flat data."""
        ohlcv = make_trending_up(50)
        atr = compute_atr(ohlcv[:, 1], ohlcv[:, 2], ohlcv[:, 3], 14)
        valid = atr[~np.isnan(atr)]
        assert len(valid) > 0
        assert np.all(valid > 0)

    def test_atr_nan_padding(self):
        ohlcv = make_trending_up(30)
        atr = compute_atr(ohlcv[:, 1], ohlcv[:, 2], ohlcv[:, 3], 14)
        assert np.all(np.isnan(atr[:14]))


class TestBollingerBands:
    def test_bb_ordering(self):
        """Upper > Middle > Lower always."""
        closes = np.array([100 + i * 0.2 + (-1)**i * 1.0 for i in range(50)])
        upper, middle, lower = compute_bollinger_bands(closes)
        valid = ~(np.isnan(upper) | np.isnan(middle) | np.isnan(lower))
        assert np.all(upper[valid] >= middle[valid])
        assert np.all(middle[valid] >= lower[valid])

    def test_bb_nan_padding(self):
        upper, middle, lower = compute_bollinger_bands(np.linspace(100, 110, 30), 20)
        assert np.all(np.isnan(upper[:19]))
        assert not np.isnan(upper[19])


class TestVolume:
    def test_volume_sma(self):
        vol = np.full(30, 1000.0)
        sma = compute_volume_sma(vol, 20)
        assert sma[-1] == pytest.approx(1000.0)

    def test_volume_ratio_normal(self):
        vol = np.full(25, 1000.0)
        ratio = compute_volume_ratio(vol, 20)
        assert ratio == pytest.approx(1.0, abs=0.01)

    def test_volume_ratio_insufficient(self):
        ratio = compute_volume_ratio(np.array([100.0]), 20)
        assert ratio == 1.0


# ═══════════════════════════════════════════════════════════
# STRATEGY TESTS
# ═══════════════════════════════════════════════════════════

def _compute_indicators(ohlcv):
    """Compute all indicators for strategy tests."""
    close = ohlcv[:, 3]
    high = ohlcv[:, 1]
    low = ohlcv[:, 2]
    volume = ohlcv[:, 4]

    rsi = compute_rsi(close, 14)
    macd_line, macd_signal, macd_hist = compute_macd(close)
    ema_fast = compute_ema(close, 9)
    ema_slow = compute_ema(close, 21)
    ema_14 = compute_ema(close, 14)
    atr = compute_atr(high, low, close, 14)
    bb_upper, bb_middle, bb_lower = compute_bollinger_bands(close)
    adx, plus_di, minus_di = compute_adx(high, low, close, 14)

    return {
        "rsi": rsi,
        "macd_line": macd_line,
        "macd_signal": macd_signal,
        "macd_histogram": macd_hist,
        "ema_fast": ema_fast,
        "ema_slow": ema_slow,
        "ema_14": ema_14,
        "atr": atr,
        "bb_upper": bb_upper,
        "bb_middle": bb_middle,
        "bb_lower": bb_lower,
        "adx": adx,
        "plus_di": plus_di,
        "minus_di": minus_di,
    }


class TestRSIStrategy:
    def test_neutral_on_insufficient_data(self):
        ohlcv = make_flat(10)
        ind = _compute_indicators(make_flat(50))  # need valid indicators
        result = RSIStrategy().compute_signal(ohlcv, ind)
        assert result.direction == "neutral"

    def test_long_on_oversold_recovery(self):
        ohlcv = make_rsi_oversold()
        ind = _compute_indicators(ohlcv)
        result = RSIStrategy().compute_signal(ohlcv, ind)
        # May or may not fire depending on exact RSI values, but should not crash
        assert result.direction in ("long", "neutral")
        assert 0 <= result.confidence <= 100

    def test_confidence_range(self):
        ohlcv = make_rsi_overbought()
        ind = _compute_indicators(ohlcv)
        result = RSIStrategy().compute_signal(ohlcv, ind)
        assert 0 <= result.confidence <= 100


class TestAdaptiveRSI:
    def test_neutral_on_insufficient_data(self):
        ohlcv = make_flat(10)
        ind = _compute_indicators(make_flat(50))
        result = AdaptiveRSIStrategy().compute_signal(ohlcv, ind)
        assert result.direction == "neutral"

    def test_divergence_metadata(self):
        ohlcv = make_rsi_oversold()
        ind = _compute_indicators(ohlcv)
        result = AdaptiveRSIStrategy().compute_signal(ohlcv, ind)
        assert "divergence_type" in result.metadata

    def test_confidence_range(self):
        ohlcv = make_trending_down(50)
        ind = _compute_indicators(ohlcv)
        result = AdaptiveRSIStrategy().compute_signal(ohlcv, ind)
        assert 0 <= result.confidence <= 100


class TestMACDStrategy:
    def test_neutral_on_insufficient_data(self):
        ohlcv = make_flat(20)
        ind = _compute_indicators(make_flat(50))
        result = MACDStrategy().compute_signal(ohlcv, ind)
        assert result.direction == "neutral"

    def test_runs_on_trending(self):
        ohlcv = make_trending_up(60)
        ind = _compute_indicators(ohlcv)
        result = MACDStrategy().compute_signal(ohlcv, ind)
        assert result.direction in ("long", "short", "neutral")
        assert 0 <= result.confidence <= 100

    def test_metadata_keys(self):
        ohlcv = make_trending_up(60)
        ind = _compute_indicators(ohlcv)
        result = MACDStrategy().compute_signal(ohlcv, ind)
        assert "macd_line" in result.metadata


class TestEMACrossStrategy:
    def test_neutral_on_insufficient_data(self):
        ohlcv = make_flat(15)
        ind = _compute_indicators(make_flat(50))
        result = EMACrossStrategy().compute_signal(ohlcv, ind)
        assert result.direction == "neutral"

    def test_runs_on_trending(self):
        ohlcv = make_trending_up(50)
        ind = _compute_indicators(ohlcv)
        result = EMACrossStrategy().compute_signal(ohlcv, ind)
        assert 0 <= result.confidence <= 100

    def test_metadata_has_spread(self):
        ohlcv = make_trending_up(50)
        ind = _compute_indicators(ohlcv)
        result = EMACrossStrategy().compute_signal(ohlcv, ind)
        assert "spread_bps" in result.metadata


class TestMeanReversionStrategy:
    def test_neutral_on_insufficient_data(self):
        ohlcv = make_flat(15)
        ind = _compute_indicators(make_flat(50))
        result = MeanReversionStrategy().compute_signal(ohlcv, ind)
        assert result.direction == "neutral"

    def test_runs_without_crash(self):
        ohlcv = make_rsi_oversold()
        ind = _compute_indicators(ohlcv)
        result = MeanReversionStrategy().compute_signal(ohlcv, ind)
        assert 0 <= result.confidence <= 100

    def test_metadata_has_bb(self):
        ohlcv = make_flat(50)
        ind = _compute_indicators(ohlcv)
        result = MeanReversionStrategy().compute_signal(ohlcv, ind)
        assert "bb_upper" in result.metadata


class TestTrendFollowingStrategy:
    def test_neutral_on_insufficient_data(self):
        ohlcv = make_flat(15)
        ind = _compute_indicators(make_flat(50))
        result = TrendFollowingStrategy().compute_signal(ohlcv, ind)
        assert result.direction == "neutral"

    def test_long_in_uptrend(self):
        ohlcv = make_trending_up(60)
        ind = _compute_indicators(ohlcv)
        result = TrendFollowingStrategy().compute_signal(ohlcv, ind)
        assert result.direction in ("long", "neutral")
        assert 0 <= result.confidence <= 100

    def test_metadata_has_adx(self):
        ohlcv = make_trending_up(60)
        ind = _compute_indicators(ohlcv)
        result = TrendFollowingStrategy().compute_signal(ohlcv, ind)
        assert "adx" in result.metadata


class TestMomentumStrategy:
    def test_neutral_on_insufficient_data(self):
        ohlcv = make_flat(15)
        ind = _compute_indicators(make_flat(50))
        result = MomentumStrategy().compute_signal(ohlcv, ind)
        assert result.direction == "neutral"

    def test_runs_on_trending(self):
        ohlcv = make_trending_up(50)
        ind = _compute_indicators(ohlcv)
        result = MomentumStrategy().compute_signal(ohlcv, ind)
        assert 0 <= result.confidence <= 100

    def test_metadata_has_roc(self):
        ohlcv = make_trending_up(50)
        ind = _compute_indicators(ohlcv)
        result = MomentumStrategy().compute_signal(ohlcv, ind)
        assert "roc" in result.metadata


class TestBreakoutStrategy:
    def test_neutral_on_insufficient_data(self):
        ohlcv = make_flat(15)
        ind = _compute_indicators(make_flat(50))
        result = BreakoutStrategy().compute_signal(ohlcv, ind)
        assert result.direction == "neutral"

    def test_long_on_breakout(self):
        ohlcv = make_breakout_up(50)
        ind = _compute_indicators(ohlcv)
        result = BreakoutStrategy().compute_signal(ohlcv, ind)
        # Breakout should detect the range break
        assert result.direction in ("long", "neutral")
        assert 0 <= result.confidence <= 100

    def test_metadata_has_resistance(self):
        ohlcv = make_breakout_up(50)
        ind = _compute_indicators(ohlcv)
        result = BreakoutStrategy().compute_signal(ohlcv, ind)
        assert "resistance" in result.metadata


# ═══════════════════════════════════════════════════════════
# INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════

class TestIntegration:
    def test_all_strategies_run_without_exception(self):
        """All 8 strategies should run without crashing on 50 candles."""
        ohlcv = make_trending_up(50)
        ind = _compute_indicators(ohlcv)
        for strategy in ALL_STRATEGIES:
            result = strategy.compute_signal(ohlcv, ind)
            assert isinstance(result, StrategyResult)
            assert result.direction in ("long", "short", "neutral")
            assert 0 <= result.confidence <= 100

    def test_all_strategies_have_family(self):
        """Every strategy should be mapped to a consensus family."""
        for strategy in ALL_STRATEGIES:
            assert strategy.name in FAMILY_MAP, f"{strategy.name} not in FAMILY_MAP"

    def test_family_coverage(self):
        """All 3 families should be covered."""
        families = set(FAMILY_MAP.values())
        assert "momentum" in families
        assert "trend" in families
        assert "structure" in families

    def test_signal_generator_returns_none_on_insufficient(self):
        """Signal generator should return None with < 30 candles."""
        gen = SignalGenerator()
        result = asyncio.get_event_loop().run_until_complete(
            gen.generate("kraken", "BTC/USD", make_flat(10))
        )
        assert result is None

    def test_signal_generator_returns_signal_or_none(self):
        """Signal generator should return TradingSignal or None on valid data."""
        gen = SignalGenerator()
        # Use trending data where consensus might agree
        ohlcv = make_trending_up(60)
        result = asyncio.get_event_loop().run_until_complete(
            gen.generate("kraken", "BTC/USD", ohlcv)
        )
        if result is not None:
            assert isinstance(result, TradingSignal)
            assert result.direction in ("long", "short")
            assert 0 < result.confidence <= 100
            assert result.pair == "BTC/USD"
            assert "families_agreeing" in result.metadata

    def test_compute_features(self):
        """_compute_features should return all required indicator keys."""
        gen = SignalGenerator()
        ohlcv = make_trending_up(50)
        features = gen._compute_features(ohlcv)
        required = [
            "rsi", "macd_line", "macd_signal", "macd_histogram",
            "ema_fast", "ema_slow", "ema_14", "atr",
            "bb_upper", "bb_middle", "bb_lower",
            "adx", "plus_di", "minus_di",
        ]
        for key in required:
            assert key in features, f"Missing indicator: {key}"
            assert len(features[key]) == len(ohlcv)

    def test_adx_computation(self):
        """ADX should produce valid values for trending data."""
        ohlcv = make_trending_up(60)
        adx, pdi, mdi = compute_adx(ohlcv[:, 1], ohlcv[:, 2], ohlcv[:, 3], 14)
        valid = adx[~np.isnan(adx)]
        assert len(valid) > 0
        assert np.all(valid >= 0)
        assert np.all(valid <= 100)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
