"""Tests for agents.ml.feature_engineer (Sprint 4B replacement)."""
import numpy as np
import pandas as pd
import pytest

from agents.ml.feature_engineer import FeatureEngineer
from trainer.data_exporter import generate_synthetic_ohlcv


class TestFeatureEngineerV2:
    def setup_method(self) -> None:
        self.fe = FeatureEngineer()

    def test_from_ohlcv(self) -> None:
        ohlcv = generate_synthetic_ohlcv(n_candles=50)
        df = self.fe.from_ohlcv(ohlcv)
        assert isinstance(df, pd.DataFrame)
        assert df.shape == (50, 30)

    def test_from_ohlcv_single(self) -> None:
        ohlcv = generate_synthetic_ohlcv(n_candles=50)
        result = self.fe.from_ohlcv_single(ohlcv)
        assert result is not None
        assert result.shape == (30,)

    def test_from_ohlcv_single_insufficient(self) -> None:
        ohlcv = generate_synthetic_ohlcv(n_candles=10)
        assert self.fe.from_ohlcv_single(ohlcv) is None

    def test_feature_names(self) -> None:
        assert len(self.fe.feature_names) == 30

    def test_from_trade_logs(self) -> None:
        df = pd.DataFrame({
            "entry_price": [100.0, 200.0],
            "exit_price": [105.0, 195.0],
            "pnl": [5.0, -5.0],
            "quantity": [1.0, 1.0],
            "timestamp": ["2026-01-01", "2026-01-02"],
            "duration_sec": [300, 600],
        })
        result = self.fe.from_trade_logs(df)
        assert "pnl_pct" in result.columns
        assert "hour" in result.columns
        assert "duration_min" in result.columns
        assert "volatility" in result.columns
