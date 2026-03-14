"""Tests for trainer.data_exporter (labeler, synthetic generator, CSV I/O)."""
import os
import tempfile

import numpy as np
import pytest

from trainer.data_exporter import DataExporter, generate_synthetic_ohlcv, label_candles


class TestGenerateSyntheticOHLCV:
    def test_default_shape(self) -> None:
        ohlcv = generate_synthetic_ohlcv()
        assert ohlcv.shape == (5000, 5)

    def test_custom_candles(self) -> None:
        ohlcv = generate_synthetic_ohlcv(n_candles=200)
        assert ohlcv.shape == (200, 5)

    def test_valid_ohlcv_structure(self) -> None:
        """high >= max(open, close) and low <= min(open, close)."""
        ohlcv = generate_synthetic_ohlcv(n_candles=1000)
        opens, highs, lows, closes = ohlcv[:, 0], ohlcv[:, 1], ohlcv[:, 2], ohlcv[:, 3]
        assert (highs >= np.maximum(opens, closes) - 1e-10).all(), "Highs below max(open,close)"
        assert (lows <= np.minimum(opens, closes) + 1e-10).all(), "Lows above min(open,close)"

    def test_positive_volumes(self) -> None:
        ohlcv = generate_synthetic_ohlcv()
        assert (ohlcv[:, 4] > 0).all()

    def test_deterministic_with_seed(self) -> None:
        a = generate_synthetic_ohlcv(seed=99)
        b = generate_synthetic_ohlcv(seed=99)
        np.testing.assert_array_equal(a, b)


class TestLabelCandles:
    def setup_method(self) -> None:
        self.ohlcv = generate_synthetic_ohlcv(n_candles=500, seed=42)

    def test_output_length(self) -> None:
        labels = label_candles(self.ohlcv)
        assert len(labels) == 500

    def test_label_values(self) -> None:
        labels = label_candles(self.ohlcv)
        unique = set(np.unique(labels))
        assert unique.issubset({-1, 0, 1})

    def test_last_rows_unknown(self) -> None:
        lookahead = 15
        labels = label_candles(self.ohlcv, lookahead_candles=lookahead)
        assert (labels[-lookahead:] == -1).all()

    def test_strong_uptrend_has_winners(self) -> None:
        """A strong uptrend should produce at least some profitable labels."""
        n = 200
        closes = 100.0 + np.arange(n) * 0.5  # strong uptrend
        opens = closes - 0.1
        highs = closes + 0.3
        lows = closes - 0.3
        volumes = np.ones(n) * 1000
        ohlcv = np.column_stack([opens, highs, lows, closes, volumes])
        labels = label_candles(ohlcv, tp_bps=100, sl_bps=75, fee_bps=52)
        valid = labels[labels >= 0]
        assert np.sum(valid == 1) > 0, "Strong uptrend produced no winners"

    def test_fee_floor_respected(self) -> None:
        """A +40 bps move with 52 bps fees should be labeled 0 (loss)."""
        n = 50
        entry = 10000.0
        # Create scenario: price moves up exactly 40 bps then stays
        closes = np.full(n, entry)
        closes[1:20] = entry * 1.004  # +40 bps
        opens = closes.copy()
        highs = closes * 1.001
        lows = closes * 0.999
        volumes = np.ones(n) * 1000
        ohlcv = np.column_stack([opens, highs, lows, closes, volumes])
        labels = label_candles(ohlcv, tp_bps=100, sl_bps=75, fee_bps=52)
        # Candle 0 should be labeled 0 because max move (+40 bps) < fee floor (52 bps)
        assert labels[0] == 0, f"Expected label=0 (loss after fees), got {labels[0]}"


class TestCSVRoundtrip:
    def test_ohlcv_csv_roundtrip(self) -> None:
        ohlcv = generate_synthetic_ohlcv(n_candles=100)
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
            tmp_path = f.name
        try:
            import pandas as pd

            df = pd.DataFrame(ohlcv, columns=["open", "high", "low", "close", "volume"])
            df.insert(0, "timestamp", range(len(df)))
            df.to_csv(tmp_path, index=False)
            loaded = DataExporter.load_ohlcv_csv(tmp_path)
            assert loaded.shape == (100, 5)
            np.testing.assert_allclose(loaded, ohlcv, rtol=1e-10)
        finally:
            os.unlink(tmp_path)
