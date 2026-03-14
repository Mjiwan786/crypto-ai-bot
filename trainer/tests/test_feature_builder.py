"""Tests for trainer.feature_builder.FeatureBuilder."""
import numpy as np
import pytest

from trainer.feature_builder import FeatureBuilder


def _make_rising_ohlcv(n: int = 50, start: float = 100.0) -> np.ndarray:
    """Generate synthetic rising OHLCV data."""
    rng = np.random.RandomState(42)
    closes = start + np.cumsum(rng.randn(n) * 0.5 + 0.1)
    opens = closes - rng.rand(n) * 0.3
    highs = np.maximum(opens, closes) + rng.rand(n) * 0.5
    lows = np.minimum(opens, closes) - rng.rand(n) * 0.5
    volumes = rng.rand(n) * 1000 + 500
    return np.column_stack([opens, highs, lows, closes, volumes])


def _make_flat_ohlcv(n: int = 50, price: float = 100.0) -> np.ndarray:
    """Generate flat price OHLCV (all candles at same price)."""
    ohlcv = np.full((n, 5), price)
    ohlcv[:, 4] = 1000.0  # volume
    return ohlcv


class TestFeatureBuilder:
    def setup_method(self) -> None:
        self.fb = FeatureBuilder()

    def test_feature_names_count(self) -> None:
        assert len(self.fb.FEATURE_NAMES) == 30

    def test_feature_names_unique(self) -> None:
        assert len(set(self.fb.FEATURE_NAMES)) == 30

    def test_build_features_shape(self) -> None:
        ohlcv = _make_rising_ohlcv(50)
        df = self.fb.build_features(ohlcv)
        assert df.shape == (50, 30)
        assert list(df.columns) == self.fb.FEATURE_NAMES

    def test_build_features_non_nan_after_warmup(self) -> None:
        """After sufficient warmup (~26+ candles), all features should be non-NaN."""
        ohlcv = _make_rising_ohlcv(60)
        df = self.fb.build_features(ohlcv)
        # Row 30+ should have all features populated
        last_row = df.iloc[-1]
        nan_count = last_row.isna().sum()
        assert nan_count == 0, f"Last row has {nan_count} NaN features: {last_row[last_row.isna()].index.tolist()}"

    def test_build_single_returns_shape(self) -> None:
        ohlcv = _make_rising_ohlcv(50)
        result = self.fb.build_single(ohlcv)
        assert result is not None
        assert result.shape == (30,)

    def test_build_single_insufficient_data(self) -> None:
        ohlcv = _make_rising_ohlcv(10)
        result = self.fb.build_single(ohlcv)
        assert result is None

    def test_rsi_bounded(self) -> None:
        ohlcv = _make_rising_ohlcv(50)
        df = self.fb.build_features(ohlcv)
        rsi = df["rsi_14"].dropna()
        assert (rsi >= 0).all(), "RSI has values < 0"
        assert (rsi <= 100).all(), "RSI has values > 100"

    def test_bb_position_approximately_bounded(self) -> None:
        ohlcv = _make_rising_ohlcv(50)
        df = self.fb.build_features(ohlcv)
        bb = df["bb_position"].dropna()
        # Allow slight overshoot at extremes
        assert (bb >= -0.5).all(), f"bb_position min={bb.min()}"
        assert (bb <= 1.5).all(), f"bb_position max={bb.max()}"

    def test_volume_ratio_positive(self) -> None:
        ohlcv = _make_rising_ohlcv(50)
        df = self.fb.build_features(ohlcv)
        vr = df["volume_ratio"].dropna()
        assert (vr > 0).all(), "volume_ratio has non-positive values"

    def test_flat_price_no_crash(self) -> None:
        """Flat price data should not crash, features should be finite."""
        ohlcv = _make_flat_ohlcv(50)
        df = self.fb.build_features(ohlcv)
        assert df.shape == (50, 30)
        # Should not have inf values (NaN is ok for warmup)
        numeric = df.select_dtypes(include=[np.number])
        assert not np.isinf(numeric.values[~np.isnan(numeric.values)]).any()

    def test_consensus_votes_valid_values(self) -> None:
        """Consensus gate votes should be in {-1, 0, 1}."""
        ohlcv = _make_rising_ohlcv(60)
        df = self.fb.build_features(ohlcv)
        for col in ["momentum_vote", "trend_vote", "structure_vote"]:
            vals = df[col].dropna().unique()
            for v in vals:
                assert v in (-1.0, 0.0, 1.0), f"{col} has unexpected value {v}"
