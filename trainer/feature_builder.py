"""
Feature engineering for ML signal quality classifier.

Builds a 30-feature vector from OHLCV data for each candle. Features are
grouped into technical indicators, derived/contextual metrics, and consensus
gate simulations. The consensus gate features reuse the exact same logic as
signals/consensus_gate.py to ensure training/inference parity.

Input format: numpy array shape (N, 5) = [open, high, low, close, volume]
Output: pandas DataFrame with 35 columns or single numpy vector (35,).
"""
from __future__ import annotations

from typing import List, Optional

import numpy as np
import pandas as pd

from utils.logger import get_logger

# Import consensus gate evaluators directly for feature parity.
# These are module-level functions; Python doesn't enforce _ privacy.
from signals.consensus_gate import _evaluate_momentum, _evaluate_trend, _evaluate_structure
from signals.squeeze_momentum import compute_squeeze_features

logger = get_logger(__name__)


class FeatureBuilder:
    """Builds ML feature vectors from OHLCV data."""

    FEATURE_NAMES: List[str] = [
        # Group 1 — Technical Analysis (20)
        "rsi_14",
        "roc_10",
        "ema_9",
        "ema_21",
        "ema_spread",
        "ema_slope",
        "sma_20",
        "bb_position",
        "bb_width",
        "macd_line",
        "macd_signal",
        "macd_histogram",
        "atr_14",
        "atr_14_pct",
        "volume_ratio",
        "volume_sma_ratio",
        "obv_slope",
        "body_ratio",
        "upper_shadow_ratio",
        "lower_shadow_ratio",
        # Group 2 — Derived/Contextual (7)
        "price_change_1",
        "price_change_5",
        "price_change_10",
        "volatility_10",
        "volatility_20",
        "high_low_range_pct",
        "close_vs_high",
        # Group 3 — Consensus Gate Derived (3)
        "momentum_vote",
        "trend_vote",
        "structure_vote",
        # Group 4 — Squeeze Momentum (5) — Phase 1 ML features
        "squeeze_on",
        "squeeze_duration",
        "squeeze_momentum",
        "squeeze_direction",
        "squeeze_acceleration",
    ]

    def build_features(self, ohlcv: np.ndarray) -> pd.DataFrame:
        """
        Compute features for ALL candles in the OHLCV array.

        Args:
            ohlcv: numpy array shape (N, 5) = [open, high, low, close, volume]

        Returns:
            DataFrame with shape (N, 30). Early rows contain NaN where
            lookback is insufficient. Caller should dropna().
        """
        n = len(ohlcv)
        opens = ohlcv[:, 0]
        highs = ohlcv[:, 1]
        lows = ohlcv[:, 2]
        closes = ohlcv[:, 3]
        volumes = ohlcv[:, 4]

        result = np.full((n, 35), np.nan, dtype=np.float64)

        # Pre-compute rolling arrays
        ema9 = self._ema_series(closes, 9)
        ema21 = self._ema_series(closes, 21)
        sma20 = self._sma_series(closes, 20)
        ema12 = self._ema_series(closes, 12)
        ema26 = self._ema_series(closes, 26)
        macd_raw = ema12 - ema26
        macd_sig = self._ema_series(macd_raw, 9)

        # OBV
        obv = self._obv_series(closes, volumes)

        # Pre-compute squeeze features for entire series
        squeeze_on_arr = np.full(n, np.nan)
        squeeze_dur_arr = np.full(n, np.nan)
        squeeze_mom_arr = np.full(n, np.nan)
        squeeze_dir_arr = np.full(n, np.nan)
        squeeze_acc_arr = np.full(n, np.nan)

        min_squeeze_bars = 25  # min_bars for squeeze computation
        for si in range(min_squeeze_bars, n + 1):
            sf = compute_squeeze_features(ohlcv[:si])
            if sf is not None:
                idx = si - 1
                squeeze_on_arr[idx] = 1.0 if sf["squeeze_on"] else 0.0
                squeeze_dur_arr[idx] = float(sf["squeeze_duration"])
                squeeze_mom_arr[idx] = sf["squeeze_momentum"]
                squeeze_dir_arr[idx] = float(sf["squeeze_momentum_direction"])
                squeeze_acc_arr[idx] = sf["squeeze_momentum_acceleration"]

        for i in range(n):
            row = np.full(35, np.nan)

            # --- Group 1: Technical Analysis ---
            # RSI 14 (needs 15 data points)
            if i >= 14:
                row[0] = self._rsi(closes[: i + 1], 14)

            # ROC 10
            if i >= 10:
                row[1] = (closes[i] - closes[i - 10]) / closes[i - 10] * 100

            # EMA 9/21 (normalized as % distance from close)
            if i >= 8:
                row[2] = (ema9[i] - closes[i]) / closes[i] * 100
            if i >= 20:
                row[3] = (ema21[i] - closes[i]) / closes[i] * 100

            # EMA spread
            if i >= 20:
                if ema21[i] != 0:
                    row[4] = (ema9[i] - ema21[i]) / ema21[i] * 100

            # EMA slope (last 3 candles)
            if i >= 10:
                if ema9[i - 2] != 0:
                    row[5] = (ema9[i] - ema9[i - 2]) / ema9[i - 2] * 100

            # SMA 20
            if i >= 19:
                row[6] = (sma20[i] - closes[i]) / closes[i] * 100

            # Bollinger Bands
            if i >= 19:
                std20 = np.std(closes[i - 19: i + 1])
                if std20 > 0:
                    upper = sma20[i] + 2 * std20
                    lower = sma20[i] - 2 * std20
                    bb_w = upper - lower
                    if bb_w > 0:
                        row[7] = (closes[i] - lower) / bb_w  # bb_position
                        row[8] = bb_w / sma20[i] * 100 if sma20[i] != 0 else 0  # bb_width

            # MACD (EMA26 valid at i=25, MACD signal EMA9 valid at i=33)
            if i >= 25 and not np.isnan(macd_raw[i]):
                row[9] = macd_raw[i]
            if i >= 33 and not np.isnan(macd_sig[i]):
                row[10] = macd_sig[i]
                row[11] = macd_raw[i] - macd_sig[i]

            # ATR 14
            if i >= 14:
                row[12] = self._atr(highs[: i + 1], lows[: i + 1], closes[: i + 1], 14)
                if closes[i] != 0:
                    row[13] = row[12] / closes[i] * 100

            # Volume ratio (current / avg of prev 20)
            if i >= 20:
                avg_vol = np.mean(volumes[i - 20: i])
                row[14] = volumes[i] / avg_vol if avg_vol > 0 else 1.0

            # Volume SMA ratio (current / SMA(vol, 10))
            if i >= 10:
                vol_sma = np.mean(volumes[i - 10: i])
                row[15] = volumes[i] / vol_sma if vol_sma > 0 else 1.0

            # OBV slope
            if i >= 10:
                obv_segment = obv[i - 10: i + 1]
                if obv_segment[0] != 0:
                    row[16] = (obv_segment[-1] - obv_segment[0]) / abs(obv_segment[0]) * 100
                else:
                    row[16] = 0.0

            # Candle patterns
            candle_range = highs[i] - lows[i]
            if candle_range > 0:
                row[17] = abs(closes[i] - opens[i]) / candle_range  # body_ratio
                row[18] = (highs[i] - max(opens[i], closes[i])) / candle_range  # upper_shadow
                row[19] = (min(opens[i], closes[i]) - lows[i]) / candle_range  # lower_shadow
            else:
                row[17] = 0.0
                row[18] = 0.0
                row[19] = 0.0

            # --- Group 2: Derived/Contextual ---
            if i >= 1:
                row[20] = (closes[i] - closes[i - 1]) / closes[i - 1] * 100
            if i >= 5:
                row[21] = (closes[i] - closes[i - 5]) / closes[i - 5] * 100
            if i >= 10:
                row[22] = (closes[i] - closes[i - 10]) / closes[i - 10] * 100

            # Volatility
            if i >= 10:
                rets = np.diff(closes[i - 10: i + 1]) / closes[i - 10: i]
                row[23] = np.std(rets)
            if i >= 20:
                rets20 = np.diff(closes[i - 20: i + 1]) / closes[i - 20: i]
                row[24] = np.std(rets20)

            # High/low range
            if closes[i] != 0:
                row[25] = (highs[i] - lows[i]) / closes[i] * 100
            if candle_range > 0:
                row[26] = (closes[i] - lows[i]) / candle_range
            else:
                row[26] = 0.5

            # --- Group 3: Consensus Gate Derived ---
            if i >= 25:
                slice_closes = closes[: i + 1]
                slice_highs = highs[: i + 1]
                slice_lows = lows[: i + 1]

                mv = _evaluate_momentum(slice_closes)
                row[27] = self._vote_to_numeric(mv)

                tv = _evaluate_trend(slice_closes)
                row[28] = self._vote_to_numeric(tv)

                sv = _evaluate_structure(slice_closes, slice_highs, slice_lows)
                row[29] = self._vote_to_numeric(sv)

            # --- Group 4: Squeeze Momentum ---
            row[30] = squeeze_on_arr[i]
            row[31] = squeeze_dur_arr[i]
            row[32] = squeeze_mom_arr[i]
            row[33] = squeeze_dir_arr[i]
            row[34] = squeeze_acc_arr[i]

            result[i] = row

        return pd.DataFrame(result, columns=self.FEATURE_NAMES)

    def build_single(self, ohlcv: np.ndarray) -> Optional[np.ndarray]:
        """
        Compute feature vector for the LAST candle only.
        Used by ml_scorer.py for real-time inference (Sprint 4B).

        Optimized path: computes only the features needed for the final
        candle rather than iterating over all N candles.

        Args:
            ohlcv: numpy array shape (N, 5) — needs at least 30 candles.

        Returns:
            1D numpy array of shape (35,) or None if insufficient data.
        """
        if ohlcv is None or len(ohlcv) < 30:
            return None

        n = len(ohlcv)
        i = n - 1
        opens = ohlcv[:, 0]
        highs = ohlcv[:, 1]
        lows = ohlcv[:, 2]
        closes = ohlcv[:, 3]
        volumes = ohlcv[:, 4]

        row = np.full(35, np.nan)

        # RSI 14
        row[0] = self._rsi(closes, 14)

        # ROC 10
        row[1] = (closes[i] - closes[i - 10]) / closes[i - 10] * 100

        # EMA 9/21
        ema9_val = self._ema_last(closes, 9)
        ema21_val = self._ema_last(closes, 21)
        if ema9_val is not None:
            row[2] = (ema9_val - closes[i]) / closes[i] * 100
        if ema21_val is not None:
            row[3] = (ema21_val - closes[i]) / closes[i] * 100

        # EMA spread
        if ema9_val is not None and ema21_val is not None and ema21_val != 0:
            row[4] = (ema9_val - ema21_val) / ema21_val * 100

        # EMA slope (last 3 candles)
        ema9_prev = self._ema_last(closes[:-2], 9)
        if ema9_val is not None and ema9_prev is not None and ema9_prev != 0:
            row[5] = (ema9_val - ema9_prev) / ema9_prev * 100

        # SMA 20
        sma20_val = float(np.mean(closes[-20:]))
        row[6] = (sma20_val - closes[i]) / closes[i] * 100

        # Bollinger Bands
        std20 = float(np.std(closes[-20:]))
        if std20 > 0:
            upper = sma20_val + 2 * std20
            lower = sma20_val - 2 * std20
            bb_w = upper - lower
            if bb_w > 0:
                row[7] = (closes[i] - lower) / bb_w
                row[8] = bb_w / sma20_val * 100 if sma20_val != 0 else 0

        # MACD
        ema12_val = self._ema_last(closes, 12)
        ema26_val = self._ema_last(closes, 26)
        if ema12_val is not None and ema26_val is not None:
            macd_line = ema12_val - ema26_val
            row[9] = macd_line
            # MACD signal needs EMA9 of MACD series — compute full for accuracy
            ema12_s = self._ema_series(closes, 12)
            ema26_s = self._ema_series(closes, 26)
            macd_s = ema12_s - ema26_s
            macd_sig_s = self._ema_series(macd_s, 9)
            if not np.isnan(macd_sig_s[i]):
                row[10] = macd_sig_s[i]
                row[11] = macd_line - macd_sig_s[i]

        # ATR 14
        atr_val = self._atr(highs, lows, closes, 14)
        row[12] = atr_val
        if closes[i] != 0:
            row[13] = atr_val / closes[i] * 100

        # Volume ratio
        avg_vol = float(np.mean(volumes[i - 20: i]))
        row[14] = volumes[i] / avg_vol if avg_vol > 0 else 1.0

        # Volume SMA ratio
        vol_sma = float(np.mean(volumes[i - 10: i]))
        row[15] = volumes[i] / vol_sma if vol_sma > 0 else 1.0

        # OBV slope
        obv = self._obv_series(closes, volumes)
        obv_seg = obv[i - 10: i + 1]
        row[16] = (obv_seg[-1] - obv_seg[0]) / abs(obv_seg[0]) * 100 if obv_seg[0] != 0 else 0.0

        # Candle patterns
        candle_range = highs[i] - lows[i]
        if candle_range > 0:
            row[17] = abs(closes[i] - opens[i]) / candle_range
            row[18] = (highs[i] - max(opens[i], closes[i])) / candle_range
            row[19] = (min(opens[i], closes[i]) - lows[i]) / candle_range
        else:
            row[17] = row[18] = row[19] = 0.0

        # Derived
        row[20] = (closes[i] - closes[i - 1]) / closes[i - 1] * 100
        row[21] = (closes[i] - closes[i - 5]) / closes[i - 5] * 100
        row[22] = (closes[i] - closes[i - 10]) / closes[i - 10] * 100

        rets10 = np.diff(closes[i - 10: i + 1]) / closes[i - 10: i]
        row[23] = float(np.std(rets10))
        rets20 = np.diff(closes[i - 20: i + 1]) / closes[i - 20: i]
        row[24] = float(np.std(rets20))

        row[25] = (highs[i] - lows[i]) / closes[i] * 100 if closes[i] != 0 else 0
        row[26] = (closes[i] - lows[i]) / candle_range if candle_range > 0 else 0.5

        # Consensus gate votes
        mv = _evaluate_momentum(closes)
        row[27] = self._vote_to_numeric(mv)
        tv = _evaluate_trend(closes)
        row[28] = self._vote_to_numeric(tv)
        sv = _evaluate_structure(closes, highs, lows)
        row[29] = self._vote_to_numeric(sv)

        # Squeeze Momentum features
        sf = compute_squeeze_features(ohlcv)
        if sf is not None:
            row[30] = 1.0 if sf["squeeze_on"] else 0.0
            row[31] = float(sf["squeeze_duration"])
            row[32] = sf["squeeze_momentum"]
            row[33] = float(sf["squeeze_momentum_direction"])
            row[34] = sf["squeeze_momentum_acceleration"]

        if np.isnan(row).all():
            return None
        return row

    @staticmethod
    def _ema_last(data: np.ndarray, period: int) -> Optional[float]:
        """Compute EMA of the last value in data."""
        if len(data) < period:
            return None
        k = 2.0 / (period + 1)
        ema = float(np.mean(data[:period]))
        for j in range(period, len(data)):
            ema = float(data[j]) * k + ema * (1 - k)
        return ema

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _vote_to_numeric(vote) -> float:
        """Convert a StrategyVote to numeric: 1=long, -1=short, 0=abstain."""
        if vote is None:
            return 0.0
        if vote.direction == "long":
            return 1.0
        if vote.direction == "short":
            return -1.0
        return 0.0

    @staticmethod
    def _rsi(closes: np.ndarray, period: int = 14) -> float:
        """Wilder-smoothed RSI."""
        if len(closes) < period + 1:
            return np.nan
        deltas = np.diff(closes[-(period + 1):])
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)
        avg_gain = np.mean(gains)
        avg_loss = max(np.mean(losses), 1e-10)
        rs = avg_gain / avg_loss
        return 100.0 - 100.0 / (1.0 + rs)

    @staticmethod
    def _ema_series(data: np.ndarray, period: int) -> np.ndarray:
        """Compute EMA for entire series. Seeds with SMA of first valid `period` values."""
        result = np.full_like(data, np.nan, dtype=np.float64)
        if len(data) < period:
            return result
        k = 2.0 / (period + 1)
        # Find first index where we have `period` consecutive non-NaN values
        valid = ~np.isnan(data)
        start = -1
        count = 0
        for idx in range(len(data)):
            if valid[idx]:
                count += 1
                if count >= period:
                    start = idx - period + 1
                    break
            else:
                count = 0
        if start < 0:
            return result
        seed_idx = start + period - 1
        result[seed_idx] = np.mean(data[start: start + period])
        for i in range(seed_idx + 1, len(data)):
            if np.isnan(data[i]):
                continue
            result[i] = data[i] * k + result[i - 1] * (1 - k)
        return result

    @staticmethod
    def _sma_series(data: np.ndarray, period: int) -> np.ndarray:
        """Compute SMA for entire series."""
        result = np.full_like(data, np.nan, dtype=np.float64)
        if len(data) < period:
            return result
        cumsum = np.cumsum(data)
        result[period - 1:] = (cumsum[period - 1:] - np.concatenate([[0], cumsum[:-period]])) / period
        return result

    @staticmethod
    def _obv_series(closes: np.ndarray, volumes: np.ndarray) -> np.ndarray:
        """On-Balance Volume."""
        direction = np.sign(np.diff(closes))
        direction = np.concatenate([[0], direction])
        return np.cumsum(direction * volumes)

    @staticmethod
    def _atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
        """Average True Range (simple average, not Wilder)."""
        if len(closes) < period + 1:
            return np.nan
        h = highs[-(period + 1):]
        l = lows[-(period + 1):]
        c = closes[-(period + 1):]
        tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
        return float(np.mean(tr))
