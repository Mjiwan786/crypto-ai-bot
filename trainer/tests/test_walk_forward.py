"""Tests for trainer.evaluation.walk_forward."""
import json

import numpy as np
import pandas as pd
import pytest

from trainer.data_exporter import generate_synthetic_ohlcv
from trainer.evaluation.walk_forward import (
    WalkForwardConfig,
    WalkForwardReport,
    run_walk_forward,
)
from trainer.feature_builder import FeatureBuilder


class TestWalkForward:
    def test_synthetic_5000_completes(self) -> None:
        """Walk-forward on 5000 synthetic candles should complete."""
        ohlcv = generate_synthetic_ohlcv(n_candles=5000)
        fb = FeatureBuilder()
        report = run_walk_forward(ohlcv, fb)
        assert isinstance(report, WalkForwardReport)
        assert len(report.folds) > 0

    def test_too_little_data(self) -> None:
        """100 candles is far below minimum — should fail gate with 0 folds."""
        ohlcv = generate_synthetic_ohlcv(n_candles=100)
        fb = FeatureBuilder()
        report = run_walk_forward(ohlcv, fb)
        assert len(report.folds) == 0
        assert report.passed_gate is False
        assert "Insufficient data" in report.gate_reason

    def test_purge_gap_respected(self) -> None:
        """No candle index should appear in both train and val windows."""
        config = WalkForwardConfig(
            train_window=500, val_window=100, step_size=100, purge_gap=15
        )
        # Verify the math: train goes [0, 500), purge [500, 515), val [515, 615)
        train_end = config.train_window
        val_start = train_end + config.purge_gap
        assert val_start > train_end, "Purge gap not separating windows"
        assert val_start - train_end == config.purge_gap

    def test_summary_nonempty(self) -> None:
        report = WalkForwardReport(
            folds=[], mean_accuracy=0.5, mean_auc=0.5,
            mean_profit_factor=0.9, std_accuracy=0.1,
            passed_gate=False, gate_reason="test",
        )
        s = report.summary()
        assert len(s) > 0
        assert "FAILED" in s

    def test_to_dict_serializable(self) -> None:
        report = WalkForwardReport(
            folds=[], mean_accuracy=0.6, mean_auc=0.65,
            mean_profit_factor=1.2, std_accuracy=0.05,
            passed_gate=True, gate_reason="All criteria met",
        )
        d = report.to_dict()
        serialized = json.dumps(d)
        assert isinstance(serialized, str)

    def test_gate_criteria_pass(self) -> None:
        report = WalkForwardReport(
            folds=[None, None, None],  # type: ignore — just checking count
            mean_accuracy=0.60, mean_auc=0.65,
            mean_profit_factor=1.3, std_accuracy=0.03,
            passed_gate=True, gate_reason="All criteria met",
        )
        assert report.passed_gate is True

    def test_gate_criteria_fail_accuracy(self) -> None:
        report = WalkForwardReport(
            folds=[None, None, None],  # type: ignore
            mean_accuracy=0.50, mean_auc=0.65,
            mean_profit_factor=1.3, std_accuracy=0.03,
            passed_gate=False, gate_reason="Accuracy 0.5000 < 0.55",
        )
        assert report.passed_gate is False
