"""
ML Predictors for Confidence Gate (ml/predictors.py)

Lightweight ensemble of deterministic ML models for filtering low-edge trades.
Per PRD §7 and Step 7:
- BasePredictor interface (deterministic seed, .fit(), .predict_proba())
- LogitPredictor (logistic regression on simple features)
- TreePredictor (decision tree on simple features)
- EnsemblePredictor (mean vote)

Features: returns, RSI, ADX, slope (all computed from OHLCV)

Constraints:
- Deterministic (fixed seed)
- Lightweight (< 250 LOC)
- No external data calls
- Config-driven toggle
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, List

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier


class BasePredictor(ABC):
    """
    Base predictor interface for ensemble confidence gate.

    Attributes:
        seed: Random seed for determinism
    """

    def __init__(self, seed: int = 42):
        """
        Initialize base predictor.

        Args:
            seed: Random seed for reproducible predictions
        """
        self.seed = seed
        self.feature_names_ = ["returns", "rsi", "adx", "slope"]

    @abstractmethod
    def fit(self, ctx: dict) -> None:
        """
        Fit predictor to market context (deterministic initialization).

        Args:
            ctx: Market context dict with ohlcv_df, current_price, timeframe
        """
        pass

    @abstractmethod
    def predict_proba(self, ctx: dict) -> float:
        """
        Predict probability of upward movement.

        Args:
            ctx: Market context dict with ohlcv_df, current_price, timeframe

        Returns:
            Probability in [0, 1] that price will move up
        """
        pass

    def _compute_features(self, ctx: dict) -> np.ndarray:
        """
        Compute simple features from OHLCV data.

        Features:
        - returns: Recent price momentum (log returns)
        - rsi: RSI indicator
        - adx: ADX trend strength
        - slope: Linear regression slope

        Args:
            ctx: Market context with ohlcv_df

        Returns:
            Feature array [returns, rsi, adx, slope]
        """
        df = ctx["ohlcv_df"]

        # Returns (10-period log return)
        returns = float(np.log(df["close"].iloc[-1] / df["close"].iloc[-11])) if len(df) >= 11 else 0.0

        # RSI (14-period)
        rsi = self._compute_rsi(df, period=14)

        # ADX (14-period) - simplified version
        adx = self._compute_adx(df, period=14)

        # Slope (linear regression on last 10 closes)
        slope = self._compute_slope(df["close"], period=10)

        return np.array([returns, rsi, adx, slope])

    def _compute_rsi(self, df: pd.DataFrame, period: int = 14) -> float:
        """Compute RSI indicator"""
        if len(df) < period + 1:
            return 50.0  # Neutral

        closes = df["close"].values
        deltas = np.diff(closes)

        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return float(rsi)

    def _compute_adx(self, df: pd.DataFrame, period: int = 14) -> float:
        """Compute simplified ADX (trend strength)"""
        if len(df) < period + 1:
            return 20.0  # Neutral

        high = df["high"].values
        low = df["low"].values
        close = df["close"].values

        # True Range
        tr = []
        for i in range(1, len(df)):
            h_l = high[i] - low[i]
            h_pc = abs(high[i] - close[i-1])
            l_pc = abs(low[i] - close[i-1])
            tr.append(max(h_l, h_pc, l_pc))

        # Average TR
        atr = float(np.mean(tr[-period:])) if tr else 0.0

        # Simplified ADX (ATR as proxy for trend strength)
        adx = min(100.0, (atr / close[-1]) * 1000.0) if close[-1] > 0 else 20.0
        return float(adx)

    def _compute_slope(self, series: pd.Series, period: int = 10) -> float:
        """Compute linear regression slope"""
        if len(series) < period:
            return 0.0

        y = series.values[-period:]
        x = np.arange(period)

        # Linear regression: y = mx + b
        m = (period * np.sum(x * y) - np.sum(x) * np.sum(y)) / (period * np.sum(x**2) - np.sum(x)**2)
        return float(m)


class LogitPredictor(BasePredictor):
    """
    Logistic regression predictor on simple features.

    Uses LogisticRegression from sklearn with deterministic seed.
    """

    def __init__(self, seed: int = 42):
        super().__init__(seed)
        self.model = LogisticRegression(random_state=seed, max_iter=100)
        self._fitted = False

    def fit(self, ctx: dict) -> None:
        """
        Fit logistic regression (deterministic initialization).

        Args:
            ctx: Market context dict
        """
        # Generate synthetic training data (deterministic)
        np.random.seed(self.seed)
        X = np.random.randn(100, 4)  # 100 samples, 4 features
        y = (X[:, 0] + X[:, 1] > 0).astype(int)  # Simple rule

        self.model.fit(X, y)
        self._fitted = True

    def predict_proba(self, ctx: dict) -> float:
        """
        Predict probability of upward movement.

        Args:
            ctx: Market context dict

        Returns:
            Probability in [0, 1]
        """
        if not self._fitted:
            self.fit(ctx)

        features = self._compute_features(ctx).reshape(1, -1)
        prob_up = float(self.model.predict_proba(features)[0, 1])
        return prob_up


class TreePredictor(BasePredictor):
    """
    Decision tree predictor on simple features.

    Uses DecisionTreeClassifier from sklearn with deterministic seed.
    """

    def __init__(self, seed: int = 42):
        super().__init__(seed)
        self.model = DecisionTreeClassifier(random_state=seed, max_depth=3)
        self._fitted = False

    def fit(self, ctx: dict) -> None:
        """
        Fit decision tree (deterministic initialization).

        Args:
            ctx: Market context dict
        """
        # Generate synthetic training data (deterministic)
        np.random.seed(self.seed)
        X = np.random.randn(100, 4)  # 100 samples, 4 features
        y = (X[:, 0] + X[:, 2] > 0).astype(int)  # Simple rule

        self.model.fit(X, y)
        self._fitted = True

    def predict_proba(self, ctx: dict) -> float:
        """
        Predict probability of upward movement.

        Args:
            ctx: Market context dict

        Returns:
            Probability in [0, 1]
        """
        if not self._fitted:
            self.fit(ctx)

        features = self._compute_features(ctx).reshape(1, -1)
        prob_up = float(self.model.predict_proba(features)[0, 1])
        return prob_up


class EnsemblePredictor(BasePredictor):
    """
    Ensemble predictor (mean vote of multiple models).

    Aggregates predictions from multiple base predictors.
    """

    def __init__(self, models: List[BasePredictor], seed: int = 42):
        """
        Initialize ensemble.

        Args:
            models: List of base predictors
            seed: Random seed

        Raises:
            ValueError: If models list is empty
        """
        super().__init__(seed)
        if not models:
            raise ValueError("models list cannot be empty")
        self.models = models

    def fit(self, ctx: dict) -> None:
        """
        Fit all constituent models.

        Args:
            ctx: Market context dict
        """
        for model in self.models:
            model.fit(ctx)

    def predict_proba(self, ctx: dict) -> float:
        """
        Predict probability (mean of model predictions).

        Args:
            ctx: Market context dict

        Returns:
            Mean probability in [0, 1]
        """
        probs = [model.predict_proba(ctx) for model in self.models]
        return float(np.mean(probs))
