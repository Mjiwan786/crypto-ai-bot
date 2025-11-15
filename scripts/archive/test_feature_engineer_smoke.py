from __future__ import annotations

"""
⚠️ SAFETY: No live trading unless MODE=live and confirmation set.
Smoke test for ML feature engineer component.
"""

import logging
import os
import sys
import time

import numpy as np
import pandas as pd

# Add project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from agents.ml.feature_engineer import FeatureEngineer, FeatureEngineerConfig

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def make_ohlcv(n=1000, start_ts=1_700_000_000_000, dt_ms=60_000, seed=7):
    rng = np.random.default_rng(seed)
    ts = np.arange(start_ts, start_ts + n * dt_ms, dt_ms, dtype=np.int64)
    # simulate prices
    ret = rng.normal(0, 0.0008, size=n).astype(np.float64)
    price = 20000.0 * np.exp(ret.cumsum())
    close = price
    high = close * (1 + rng.uniform(0.0, 0.002, size=n))
    low = close * (1 - rng.uniform(0.0, 0.002, size=n))
    open_ = np.r_[close[0], close[:-1]]
    volume = rng.uniform(1, 50, size=n)
    df = pd.DataFrame(
        {"ts": ts, "open": open_, "high": high, "low": low, "close": close, "volume": volume}
    )
    return df


def make_orderbook(df, depth=10, seed=11):
    rng = np.random.default_rng(seed)
    mid = (df["high"].values + df["low"].values) / 2.0
    bid_px_1 = mid * (1 - 0.0002)
    ask_px_1 = mid * (1 + 0.0002)
    ob = {"ts": df["ts"].values, "bid_px_1": bid_px_1, "ask_px_1": ask_px_1}
    for i in range(1, depth + 1):
        ob[f"bid_sz_{i}"] = rng.uniform(1, 10, size=len(df))
        ob[f"ask_sz_{i}"] = rng.uniform(1, 10, size=len(df))
    return pd.DataFrame(ob)


def make_sentiment(df, seed=13):
    rng = np.random.default_rng(seed)
    s = pd.DataFrame(
        {
            "ts": df["ts"].values,
            "sent_mean": rng.normal(0, 0.3, size=len(df)),
            "sent_var": rng.uniform(0.1, 1.0, size=len(df)),
            "news_count": rng.integers(0, 8, size=len(df)).astype(np.float64),
            "social_count": rng.integers(5, 50, size=len(df)).astype(np.float64),
        }
    )
    return s


def debug_features_before_trim(fe, ohlcv, orderbook, sentiment):
    """Debug version that shows features before trimming"""
    # Manually run through the compute logic to see intermediate results
    df = ohlcv.sort_values("ts", kind="mergesort").reset_index(drop=True)
    base = df[["ts", "open", "high", "low", "close", "volume"]].astype(
        {"open": "float64", "high": "float64", "low": "float64", "close": "float64", "volume": "float64"}
    )

    log_close = np.log(base["close"])
    feats = {}

    # Check individual features
    for k in fe.cfg.ret_lags:
        ret_feat = log_close.shift(k) - log_close.shift(k + 1)
        logger.info(f"ret_{k}: first_valid={ret_feat.first_valid_index()}, last_valid={ret_feat.last_valid_index()}")
        feats[f"ret_{k}"] = ret_feat

    # RSI
    rsi = fe._rsi(log_close, fe.cfg.rsi_window).shift(1)
    logger.info(f"rsi: first_valid={rsi.first_valid_index()}, last_valid={rsi.last_valid_index()}")

    # Vol
    one_bar_logret = log_close.diff()
    vol = (
        one_bar_logret.rolling(fe.cfg.vol_window, min_periods=fe.cfg.vol_window)
        .std()
        .mul(np.sqrt(fe.cfg.vol_window))
        .shift(1)
    )
    logger.info(f"vol: first_valid={vol.first_valid_index()}, last_valid={vol.last_valid_index()}")

    logger.info(f"Max window: {fe._max_win}")
    logger.info(f"Input data length: {len(df)}")


def run_smoke_test() -> int:
    """Run the feature engineer smoke test."""
    # Use more data and smaller windows for testing
    ohlcv = make_ohlcv(n=200)  # Smaller dataset
    orderbook = make_orderbook(ohlcv, depth=10)
    sentiment = make_sentiment(ohlcv)

    # Use smaller windows that won't consume all data
    cfg = FeatureEngineerConfig(
        symbol="BTC/USDT",
        timeframe="1m",
        rsi_window=10,        # Smaller window
        adx_window=10,        # Smaller window
        atr_window=10,        # Smaller window
        vol_window=20,        # Much smaller window
        ret_lags=[1, 2, 3],   # Fewer lags
        ob_depth_levels=5,    # Smaller depth
        sentiment_window=15,  # Much smaller window
        strict_checks=True,
        seed=17,
    )

    fe = FeatureEngineer(cfg)

    logger.info("=== DEBUG INFO ===")
    debug_features_before_trim(fe, ohlcv, orderbook, sentiment)
    logger.info("==================")

    t0 = time.perf_counter()
    feats = fe.compute(ohlcv, orderbook=orderbook, sentiment=sentiment)
    dt_ms = (time.perf_counter() - t0) * 1000.0

    logger.info(f"Result rows: {len(feats)}")
    logger.info(f"Latency: {dt_ms:.2f} ms for {len(ohlcv)} input rows")

    if len(feats) > 0:
        logger.info("\nFirst 5 rows of features:")
        logger.info(f"\n{feats.head()}")
        logger.info(f"\nFeature columns: {list(feats.columns)}")

        # Check for NaNs
        logger.info("\nNaN counts per column:")
        for col in feats.columns:
            if col != 'ts':
                nan_count = feats[col].isna().sum()
                logger.info(f"  {col}: {nan_count} NaNs")
        return 0
    else:
        logger.error("No features generated - all rows trimmed due to NaNs")
        return 1


def main() -> int:
    """Main entry point."""
    try:
        return run_smoke_test()
    except Exception as e:
        logger.error(f"Feature engineer smoke test failed: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
