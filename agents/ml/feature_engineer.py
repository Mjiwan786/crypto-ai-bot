"""
Feature engineering for ML models.

Wraps trainer.feature_builder.FeatureBuilder with convenience methods
for building features from trade logs and OHLCV arrays. This is the
agents/ml/ interface; the core logic lives in trainer/feature_builder.py.
"""
from __future__ import annotations

import logging
from typing import List, Optional

import numpy as np
import pandas as pd

from trainer.feature_builder import FeatureBuilder

logger = logging.getLogger(__name__)


class FeatureEngineer:
    """ML feature engineering interface for agents."""

    def __init__(self) -> None:
        self._builder = FeatureBuilder()

    @property
    def feature_names(self) -> List[str]:
        """Return the canonical list of 30 feature names."""
        return self._builder.FEATURE_NAMES

    def from_ohlcv(self, ohlcv: np.ndarray) -> pd.DataFrame:
        """Build features from OHLCV array. Returns DataFrame with 30 features."""
        return self._builder.build_features(ohlcv)

    def from_ohlcv_single(self, ohlcv: np.ndarray) -> Optional[np.ndarray]:
        """Build feature vector for the last candle. Returns shape (30,) or None."""
        return self._builder.build_single(ohlcv)

    def from_trade_logs(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Build features from trade log DataFrame.

        Expects columns: entry_price, exit_price, pnl, quantity, timestamp, duration_sec.
        Returns DataFrame with derived trade-level features.
        """
        result = df.copy()
        result["pnl_pct"] = df["pnl"] / (df["entry_price"] * df["quantity"] + 1e-9)
        result["hour"] = pd.to_datetime(df["timestamp"]).dt.hour
        result["duration_min"] = df["duration_sec"] / 60.0
        result["volatility"] = np.abs(df["entry_price"] - df["exit_price"]) / df["entry_price"]
        return result

    def from_market_opportunity(self, opp, timestamp=None) -> pd.DataFrame:
        """Legacy interface for MarketOpportunity objects."""
        from datetime import datetime

        ts = timestamp or datetime.utcnow()
        return pd.DataFrame([{
            "entry_price": getattr(opp, "entry_price", 1.0),
            "exit_price": getattr(opp, "exit_price", 1.01),
            "pnl_pct": 0.01,
            "duration_min": 5.0,
            "hour": ts.hour,
            "volatility": 0.002,
        }])
