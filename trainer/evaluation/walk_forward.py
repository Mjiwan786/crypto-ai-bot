"""
Walk-forward validation for ML signal quality model.

Rolling window backtesting that validates model generalization. Includes a
purge gap between training and validation windows to prevent label leakage
from the lookahead labeling strategy.

Go/no-go gate criteria:
  - Mean accuracy  >= 0.55 (better than random)
  - Mean AUC       >= 0.58
  - Mean PF        >= 1.1  (net profitable after fees)
  - At least 3 folds completed
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class WalkForwardConfig:
    """Walk-forward validation configuration."""

    train_window: int = 3000  # candles for training (~2 days at 1-min)
    val_window: int = 500  # candles for validation (~8 hours)
    step_size: int = 500  # roll forward by this many candles
    min_trades_per_window: int = 20  # skip windows with too few labels
    purge_gap: int = 15  # must match lookahead_candles in labeler


@dataclass
class WalkForwardResult:
    """Result of one walk-forward fold."""

    fold: int
    train_size: int
    val_size: int
    accuracy: float
    precision: float
    recall: float
    f1: float
    auc: float
    profit_factor: float
    n_trades: int
    feature_importance: pd.DataFrame = field(repr=False)


@dataclass
class WalkForwardReport:
    """Aggregate walk-forward results."""

    folds: List[WalkForwardResult]
    mean_accuracy: float
    mean_auc: float
    mean_profit_factor: float
    std_accuracy: float
    passed_gate: bool
    gate_reason: str

    def summary(self) -> str:
        """Human-readable summary."""
        return (
            f"Walk-Forward Report: {len(self.folds)} folds\n"
            f"  Mean Accuracy:      {self.mean_accuracy:.4f} (std: {self.std_accuracy:.4f})\n"
            f"  Mean AUC:           {self.mean_auc:.4f}\n"
            f"  Mean Profit Factor: {self.mean_profit_factor:.4f}\n"
            f"  Gate: {'PASSED' if self.passed_gate else 'FAILED'} -- {self.gate_reason}"
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for JSON export."""
        return {
            "n_folds": len(self.folds),
            "mean_accuracy": self.mean_accuracy,
            "mean_auc": self.mean_auc,
            "mean_profit_factor": self.mean_profit_factor,
            "std_accuracy": self.std_accuracy,
            "passed_gate": self.passed_gate,
            "gate_reason": self.gate_reason,
            "folds": [
                {
                    "fold": f.fold,
                    "train_size": f.train_size,
                    "val_size": f.val_size,
                    "accuracy": f.accuracy,
                    "precision": f.precision,
                    "recall": f.recall,
                    "f1": f.f1,
                    "auc": f.auc,
                    "profit_factor": f.profit_factor,
                    "n_trades": f.n_trades,
                }
                for f in self.folds
            ],
        }


def _empty_report(reason: str) -> WalkForwardReport:
    return WalkForwardReport(
        folds=[],
        mean_accuracy=0.0,
        mean_auc=0.0,
        mean_profit_factor=0.0,
        std_accuracy=0.0,
        passed_gate=False,
        gate_reason=reason,
    )


def run_walk_forward(
    ohlcv: np.ndarray,
    feature_builder,
    config: WalkForwardConfig | None = None,
    model_config=None,
) -> WalkForwardReport:
    """
    Execute walk-forward validation.

    For each fold:
      1. Build features from training window.
      2. Label candles with lookahead.
      3. Train XGBoost on training window.
      4. Evaluate on validation window (after purge gap).
      5. Simulate trades when model confidence > 0.60.
      6. Calculate profit factor on simulated trades.
    """
    from trainer.data_exporter import label_candles
    from trainer.models.xgboost_signal import XGBoostSignalClassifier, XGBoostSignalConfig

    if config is None:
        config = WalkForwardConfig()
    if model_config is None:
        model_config = XGBoostSignalConfig()

    total = len(ohlcv)
    min_req = config.train_window + config.purge_gap + config.val_window

    if total < min_req:
        return _empty_report(f"Insufficient data: {total} < {min_req} required")

    # Pre-compute features and labels for entire dataset
    all_features = feature_builder.build_features(ohlcv)
    all_labels = label_candles(ohlcv)

    folds: List[WalkForwardResult] = []
    fold_idx = 0
    start = 0

    while start + min_req <= total:
        train_end = start + config.train_window
        val_start = train_end + config.purge_gap
        val_end = min(val_start + config.val_window, total)

        train_feat = all_features.iloc[start:train_end]
        train_lbl = all_labels[start:train_end]
        val_feat = all_features.iloc[val_start:val_end]
        val_lbl = all_labels[val_start:val_end]

        # Filter NaN rows and unknown labels (-1)
        train_ok = (train_lbl >= 0) & (~train_feat.isna().any(axis=1).values)
        val_ok = (val_lbl >= 0) & (~val_feat.isna().any(axis=1).values)

        X_train = train_feat[train_ok]
        y_train = train_lbl[train_ok]
        X_val = val_feat[val_ok]
        y_val = val_lbl[val_ok]

        if len(X_train) < config.min_trades_per_window or len(X_val) < 10:
            start += config.step_size
            continue

        # Train
        model = XGBoostSignalClassifier(config=model_config)
        model.train(X_train, y_train)

        # Predict on validation
        X_val_scaled = model.scaler.transform(X_val)
        y_pred = model.classifier.predict(X_val_scaled)
        y_proba = model.classifier.predict_proba(X_val_scaled)[:, 1]

        acc = float(accuracy_score(y_val, y_pred))
        prec = float(precision_score(y_val, y_pred, zero_division=0))
        rec = float(recall_score(y_val, y_pred, zero_division=0))
        f1_val = float(f1_score(y_val, y_pred, zero_division=0))
        try:
            auc = float(roc_auc_score(y_val, y_proba))
        except ValueError:
            auc = 0.5

        # Simulate trades — only when confidence > 0.60
        trade_mask = y_proba > 0.60
        n_trades = int(trade_mask.sum())

        if n_trades > 0:
            traded_labels = y_val[trade_mask]
            wins = int(np.sum(traded_labels == 1))
            losses = int(np.sum(traded_labels == 0))
            # PF = gross_wins / gross_losses  (TP=100 bps, SL=75 bps per label)
            profit_factor = float(wins * 100.0 / (losses * 75.0)) if losses > 0 else (float("inf") if wins > 0 else 0.0)
        else:
            profit_factor = 0.0

        importance = model.feature_importance()
        folds.append(
            WalkForwardResult(
                fold=fold_idx,
                train_size=len(X_train),
                val_size=len(X_val),
                accuracy=acc,
                precision=prec,
                recall=rec,
                f1=f1_val,
                auc=auc,
                profit_factor=profit_factor,
                n_trades=n_trades,
                feature_importance=importance,
            )
        )
        logger.info(
            "Fold %d: acc=%.4f auc=%.4f pf=%.4f trades=%d",
            fold_idx, acc, auc, profit_factor, n_trades,
        )
        fold_idx += 1
        start += config.step_size

    if not folds:
        return _empty_report("No valid folds completed")

    accs = [f.accuracy for f in folds]
    aucs = [f.auc for f in folds]
    pfs = [f.profit_factor for f in folds if f.profit_factor != float("inf")]

    mean_acc = float(np.mean(accs))
    mean_auc = float(np.mean(aucs))
    mean_pf = float(np.mean(pfs)) if pfs else 0.0
    std_acc = float(np.std(accs))

    # Go/no-go gate
    reasons: List[str] = []
    if len(folds) < 3:
        reasons.append(f"Only {len(folds)} folds (need >= 3)")
    if mean_acc < 0.55:
        reasons.append(f"Accuracy {mean_acc:.4f} < 0.55")
    if mean_auc < 0.58:
        reasons.append(f"AUC {mean_auc:.4f} < 0.58")
    if mean_pf < 1.1:
        reasons.append(f"Profit factor {mean_pf:.4f} < 1.1")

    passed = len(reasons) == 0
    gate_reason = "; ".join(reasons) if reasons else "All criteria met"

    return WalkForwardReport(
        folds=folds,
        mean_accuracy=mean_acc,
        mean_auc=mean_auc,
        mean_profit_factor=mean_pf,
        std_accuracy=std_acc,
        passed_gate=passed,
        gate_reason=gate_reason,
    )
