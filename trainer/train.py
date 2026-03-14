"""
ML Training Pipeline Entry Point.

Trains XGBoost signal quality classifier from OHLCV data.
Designed to run offline on laptop — not on Fly.io.

Usage:
    python -m trainer.train --data-dir data/ --pair BTC/USD --output models/signal_scorer.joblib --validate
    python -m trainer.train --synthetic --validate
    python -m trainer.train --data-dir data/ --pair BTC/USD --validate-only
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from trainer.data_exporter import DataExporter, generate_synthetic_ohlcv, label_candles
from trainer.evaluation.walk_forward import WalkForwardConfig, run_walk_forward
from trainer.feature_builder import FeatureBuilder
from trainer.models.xgboost_signal import XGBoostSignalClassifier
from utils.logger import get_logger

logger = get_logger(__name__)


def _load_ohlcv_from_dir(data_dir: str, pair: str) -> np.ndarray:
    """Load OHLCV from CSV files in a data directory."""
    pair_slug = pair.replace("/", "_")
    candidates = list(Path(data_dir).glob(f"ohlcv_{pair_slug}*.csv"))
    if not candidates:
        logger.error("No OHLCV CSV files found for %s in %s", pair, data_dir)
        sys.exit(1)
    # Use most recently modified file
    csv_path = max(candidates, key=lambda p: p.stat().st_mtime)
    logger.info("Loading OHLCV from %s", csv_path)
    return DataExporter.load_ohlcv_csv(str(csv_path))


def main() -> None:
    parser = argparse.ArgumentParser(description="Train ML signal quality model")
    parser.add_argument("--data-dir", type=str, default="data/", help="Directory with OHLCV CSVs")
    parser.add_argument("--pair", type=str, default="BTC/USD", help="Trading pair to train on")
    parser.add_argument("--output", type=str, default="models/signal_scorer.joblib", help="Model output path")
    parser.add_argument("--synthetic", action="store_true", help="Use synthetic data for development")
    parser.add_argument("--validate", action="store_true", help="Run walk-forward validation")
    parser.add_argument("--validate-only", action="store_true", help="Only validate, don't export model")
    parser.add_argument("--candles", type=int, default=5000, help="Synthetic data candle count")
    args = parser.parse_args()

    # 1. Load data
    if args.synthetic:
        ohlcv = generate_synthetic_ohlcv(n_candles=args.candles)
        logger.info("Using synthetic data: %d candles", len(ohlcv))
    else:
        ohlcv = _load_ohlcv_from_dir(args.data_dir, args.pair)
        logger.info("Loaded %d candles for %s", len(ohlcv), args.pair)

    # 2. Build features
    fb = FeatureBuilder()
    features_df = fb.build_features(ohlcv)
    logger.info("Built %d feature rows, %d features", len(features_df), len(fb.FEATURE_NAMES))

    # 3. Label candles
    labels = label_candles(ohlcv)
    n_pos = int(np.sum(labels == 1))
    n_neg = int(np.sum(labels == 0))
    logger.info("Labels: %d profitable, %d unprofitable, %d unknown", n_pos, n_neg, int(np.sum(labels == -1)))

    # 4. Walk-forward validation
    if args.validate or args.validate_only:
        report = run_walk_forward(ohlcv, fb)
        logger.info("\n%s", report.summary())

        if not report.passed_gate:
            logger.error("GATE FAILED: %s", report.gate_reason)
            if args.validate_only:
                sys.exit(1)
            logger.warning("Proceeding with model export despite failed gate")

        if args.validate_only:
            sys.exit(0)

    # 5. Train final model on ALL data
    valid_mask = labels >= 0
    X = features_df[valid_mask].dropna()
    y = labels[valid_mask][: len(X)]

    if len(X) == 0:
        logger.error("No valid training samples after filtering")
        sys.exit(1)

    model = XGBoostSignalClassifier()
    metrics = model.train(X, y)
    logger.info("Final model metrics: %s", metrics)

    # 6. Export
    path = model.save(args.output)
    logger.info("Model saved to: %s", path)

    # 7. Feature importance
    importance = model.feature_importance()
    logger.info("Top 10 features:\n%s", importance.head(10).to_string())


if __name__ == "__main__":
    main()
