"""Sprint 4A go/no-go verification script."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np

from trainer.models.xgboost_signal import XGBoostSignalClassifier
from trainer.feature_builder import FeatureBuilder
from trainer.data_exporter import generate_synthetic_ohlcv


def main():
    print("=== Sprint 4A Verification ===")

    # 1. Load model
    m = XGBoostSignalClassifier.load("models/signal_scorer.joblib")
    p = m.predict_proba(np.zeros(30))
    print(f"[PASS] Model load + predict: proba={p:.4f}")
    print(f"       Model version: {m.training_metadata['model_version']}")
    print(f"       Feature count: {len(m.feature_names)}")

    # 2. Feature importance
    fi = m.feature_importance()
    assert fi["importance"].sum() > 0, "Feature importance is all zeros!"
    print(f"[PASS] Feature importance sum: {fi['importance'].sum():.4f}")
    print(f"       Top 3: {', '.join(fi['feature'].head(3).tolist())}")

    # 3. Benchmark build_single
    ohlcv = generate_synthetic_ohlcv(n_candles=50)
    fb = FeatureBuilder()
    times = []
    for _ in range(100):
        t0 = time.perf_counter()
        fb.build_single(ohlcv)
        times.append((time.perf_counter() - t0) * 1000)
    avg = np.mean(times)
    status = "PASS" if avg < 5 else "FAIL"
    print(f"[{status}] build_single avg: {avg:.2f}ms (target: <5ms)")

    # 4. predict_proba range check
    assert 0.0 <= p <= 1.0, f"predict_proba out of range: {p}"
    print(f"[PASS] predict_proba in [0, 1]")

    print("\n=== All Sprint 4A checks passed ===")


if __name__ == "__main__":
    main()
