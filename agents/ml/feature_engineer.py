"""
Production feature engineering for high-frequency crypto trading.

Provides deterministic, vectorized, leak-proof feature engineering with comprehensive
technical indicators and market microstructure features for ML model training and inference.

Features:
- Deterministic, vectorized, leak-proof (left-aligned) feature computation
- Comprehensive technical indicators (RSI, ADX, ATR, volatility)
- Order book microstructure features
- Sentiment and news-based features
- Configurable feature windows and parameters
- Thread-safe operations with proper validation
- Support for multiple timeframes and symbols
- Production-grade error handling and logging

Key guarantees:
- No data leakage (left-aligned features)
- Deterministic results with fixed random seeds
- Comprehensive input validation
- Memory-efficient vectorized operations
- Thread-safe feature computation
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field, field_validator

# Internal toggle for optional extras (kept OFF to preserve exact public contract)

_ADVANCED_FEATURES = False


class FeatureEngineerConfig(BaseModel):
    symbol: str
    timeframe: str  # e.g., "15s", "1m"
    rsi_window: int = Field(default=14, gt=0)
    adx_window: int = Field(default=14, gt=0)
    atr_window: int = Field(default=14, gt=0)
    vol_window: int = Field(default=60, gt=0)
    ret_lags: List[int] = Field(default_factory=lambda: [1, 2, 3, 5])
    ob_depth_levels: int = Field(default=10, gt=0)
    sentiment_window: int = Field(default=60, gt=0)
    strict_checks: bool = True
    seed: int = 17

    @field_validator("symbol")
    @classmethod
    def _sym_nonempty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("symbol must be non-empty")
        return v

    @field_validator("timeframe")
    @classmethod
    def _tf_nonempty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("timeframe must be non-empty")
        return v

    @field_validator("ret_lags")
    @classmethod
    def _lags_valid(cls, v: List[int]) -> List[int]:
        if not v:
            raise ValueError("ret_lags must be non-empty")
        if any((not isinstance(x, int)) or x <= 0 for x in v):
            raise ValueError("ret_lags must contain positive integers")
        # Sorted unique for determinism
        return sorted(set(v))


class FeatureEngineer:
    """
    Deterministic, leak-proof feature engineering.
    Public contracts: registry(), compute(), sanity_summary().
    """

    REQUIRED_OHLCV = ["ts", "open", "high", "low", "close", "volume"]

    def __init__(self, cfg: FeatureEngineerConfig) -> None:
        self.cfg = cfg
        np.random.seed(cfg.seed)

        self._symbol_id = self._stable_id(cfg.symbol)
        self._tf_id = self._stable_id(cfg.timeframe)

        self._max_win = max(
            cfg.rsi_window,
            cfg.adx_window,
            cfg.atr_window,
            cfg.vol_window,
            cfg.sentiment_window,
            max(cfg.ret_lags),
        )

    def registry(self) -> Dict[str, Dict[str, Any]]:
        reg: Dict[str, Dict[str, Any]] = {}

        # Returns
        for k in self.cfg.ret_lags:
            reg[f"ret_{k}"] = {
                "formula": f"log(close[t-{k}] / close[t-{k}-1])",
                "window": k + 1,
                "dtype": "float",
            }

        # Momentum/Trend
        reg[f"rsi_{self.cfg.rsi_window}"] = {
            "formula": f"RSI({self.cfg.rsi_window}) left-aligned via EWM; uses close",
            "window": self.cfg.rsi_window,
            "dtype": "float",
        }
        reg[f"adx_{self.cfg.adx_window}"] = {
            "formula": f"ADX({self.cfg.adx_window}) left-aligned; uses high/low/close",
            "window": self.cfg.adx_window,
            "dtype": "float",
        }

        # Volatility
        reg[f"atr_{self.cfg.atr_window}"] = {
            "formula": f"ATR({self.cfg.atr_window}) left-aligned; EWM of TR",
            "window": self.cfg.atr_window,
            "dtype": "float",
        }
        reg[f"vol_realized_{self.cfg.vol_window}"] = {
            "formula": (
                f"std(log returns, {self.cfg.vol_window})*sqrt({self.cfg.vol_window}) "
                "left-aligned"
            ),
            "window": self.cfg.vol_window,
            "dtype": "float",
        }

        # Order-book (optional)
        reg["ob_imbalance"] = {
            "formula": "(Σ bid_sz - Σ ask_sz)/(Σ bid_sz + Σ ask_sz) left-aligned",
            "window": 1,
            "dtype": "float",
        }
        reg["ob_spread_bps"] = {
            "formula": "(best_ask-best_bid)/mid * 1e4 left-aligned",
            "window": 1,
            "dtype": "float",
        }
        reg["ob_depth_ratio"] = {
            "formula": "(Σ bid_sz)/(Σ ask_sz) left-aligned",
            "window": 1,
            "dtype": "float",
        }

        # Sentiment (optional)
        w = self.cfg.sentiment_window
        reg["sent_mean_ma"] = {
            "formula": f"MA(sent_mean, {w}) left-aligned",
            "window": w,
            "dtype": "float",
        }
        reg["sent_var_ma"] = {
            "formula": f"MA(sent_var, {w}) left-aligned",
            "window": w,
            "dtype": "float",
        }
        reg["news_count_ma"] = {
            "formula": f"MA(news_count, {w}) left-aligned",
            "window": w,
            "dtype": "float",
        }
        reg["social_count_ma"] = {
            "formula": f"MA(social_count, {w}) left-aligned",
            "window": w,
            "dtype": "float",
        }

        # Meta
        reg["symbol_id"] = {
            "formula": "deterministic id from cfg.symbol (sha256)",
            "window": None,
            "dtype": "int",
        }
        reg["tf_id"] = {
            "formula": "deterministic id from cfg.timeframe (sha256)",
            "window": None,
            "dtype": "int",
        }

        if _ADVANCED_FEATURES:
            # Reserved for optional advanced features (kept off by default)
            pass

        return reg

    def compute(
        self,
        df: pd.DataFrame,
        *,
        orderbook: Optional[pd.DataFrame] = None,
        sentiment: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        if not isinstance(df, pd.DataFrame) or df.empty:
            raise ValueError("df must be a non-empty DataFrame")
        self._validate_ohlcv(df, name="df")

        # Stable ascending sort by ts
        df = df.sort_values("ts", kind="mergesort").reset_index(drop=True)

        base = df[["ts", "open", "high", "low", "close", "volume"]].astype(
            {
                "open": "float64",
                "high": "float64",
                "low": "float64",
                "close": "float64",
                "volume": "float64",
            }  # noqa: E501
        )

        # 1) Log returns and lagged returns (left-aligned; no leakage)
        log_close = np.log(base["close"])
        one_bar_logret = log_close.diff()
        feats: Dict[str, pd.Series] = {}
        for k in self.cfg.ret_lags:
            feats[f"ret_{k}"] = log_close.shift(k) - log_close.shift(k + 1)

        # 2) RSI (left-aligned)
        feats[f"rsi_{self.cfg.rsi_window}"] = self._rsi(log_close, self.cfg.rsi_window).shift(
            1
        )  # noqa: E501

        # 3) ADX (left-aligned)
        feats[f"adx_{self.cfg.adx_window}"] = self._adx(
            base["high"], base["low"], base["close"], self.cfg.adx_window
        ).shift(1)

        # 4) ATR (left-aligned)
        feats[f"atr_{self.cfg.atr_window}"] = self._atr(
            base["high"], base["low"], base["close"], self.cfg.atr_window
        ).shift(1)

        # 5) Realized volatility (left-aligned)
        feats[f"vol_realized_{self.cfg.vol_window}"] = (
            one_bar_logret.rolling(self.cfg.vol_window, min_periods=self.cfg.vol_window)
            .std()
            .mul(np.sqrt(self.cfg.vol_window))
            .shift(1)
        )

        # 6) Order-book (optional)
        if isinstance(orderbook, pd.DataFrame) and not orderbook.empty:
            ob_feats = self._orderbook_features(orderbook, base["ts"])
            feats.update(ob_feats)

        # 7) Sentiment (optional)
        if isinstance(sentiment, pd.DataFrame) and not sentiment.empty:
            sent_feats = self._sentiment_features(sentiment, base["ts"])
            feats.update(sent_feats)

        # 8) Meta ids
        feats["symbol_id"] = pd.Series(self._symbol_id, index=base.index, dtype="int64")
        feats["tf_id"] = pd.Series(self._tf_id, index=base.index, dtype="int64")

        # 9) Assemble output
        out = pd.DataFrame({"ts": base["ts"].values})
        for name, series in feats.items():
            if series.dtype.kind == "i":
                out[name] = series.astype("int64")
            else:
                out[name] = series.astype("float64")

        # 10) Trim leading NaNs from rolling/shift to enforce leak-proof alignment.
        #     Ignore columns that are entirely NaN, so optional features with no valid data
        #     do not cause over-trimming. After trimming, drop any columns that remain all-NaN.
        feature_cols = [c for c in out.columns if c != "ts"]
        if feature_cols:
            valid_starts = []
            for c in feature_cols:
                idx = out[c].first_valid_index()
                if idx is not None:
                    valid_starts.append(int(idx))
            if valid_starts:
                first_valid = max(valid_starts)
                out = out.iloc[first_valid:].reset_index(drop=True)
                # Drop columns that are still entirely NaN after trimming
                drop_all_nan = [c for c in feature_cols if not out[c].notna().any()]
                if drop_all_nan:
                    out = out.drop(columns=drop_all_nan)
            else:
                # No feature ever becomes valid: return empty frame with only ts column
                return pd.DataFrame({"ts": pd.Series(dtype=out["ts"].dtype)})

        # 11) Ensure dtypes numeric (except ts)
        non_num = [
            c
            for c in out.columns
            if c != "ts" and not pd.api.types.is_numeric_dtype(out[c])  # noqa: E501
        ]
        if non_num:
            raise ValueError(f"Non-numeric feature columns found: {non_num}")

        return out

    @staticmethod
    def sanity_summary(df: pd.DataFrame) -> Dict[str, Any]:
        if not isinstance(df, pd.DataFrame) or df.empty:
            return {"rows": 0, "ts_min": None, "ts_max": None, "nulls_per_feature": {}}
        cols = [c for c in df.columns if c != "ts"]
        nulls = df[cols].isna().sum().to_dict() if cols else {}
        return {
            "rows": int(len(df)),
            "ts_min": df["ts"].min() if "ts" in df.columns else None,
            "ts_max": df["ts"].max() if "ts" in df.columns else None,
            "nulls_per_feature": nulls,
        }

    # ---------- Internal helpers ----------

    @staticmethod
    def _stable_id(text: str) -> int:
        h = hashlib.sha256(text.encode("utf-8")).digest()
        return int.from_bytes(h[:8], "big") % 2147483647

    def _validate_ohlcv(self, df: pd.DataFrame, *, name: str) -> None:
        missing = [c for c in self.REQUIRED_OHLCV if c not in df.columns]
        if missing:
            raise ValueError(f"{name} missing required columns: {missing}")
        if self.cfg.strict_checks:
            if not pd.Series(df["ts"]).is_monotonic_increasing:
                raise ValueError(f"{name} 'ts' must be monotonic increasing")
        price_cols = ["open", "high", "low", "close"]
        if (df[price_cols] <= 0).any(axis=None):
            raise ValueError(f"{name} has non-positive prices")
        if (df["volume"] < 0).any():
            raise ValueError(f"{name} has negative volume")

    @staticmethod
    def _atr(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        window: int,
    ) -> pd.Series:
        hl = (high - low).abs()
        hc = (high - close.shift(1)).abs()
        lc = (low - close.shift(1)).abs()
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1.0 / window, adjust=False).mean()
        return atr

    @staticmethod
    def _adx(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        window: int,
    ) -> pd.Series:
        up = high.diff()
        down = -low.diff()
        plus_dm = pd.Series(
            np.where((up > down) & (up > 0), up, 0.0),
            index=high.index,
            dtype="float64",
        )
        minus_dm = pd.Series(
            np.where((down > up) & (down > 0), down, 0.0),
            index=high.index,
            dtype="float64",
        )
        atr = FeatureEngineer._atr(high, low, close, window)
        plus_di = 100.0 * plus_dm.ewm(alpha=1.0 / window, adjust=False).mean() / (atr + 1e-12)
        minus_di = 100.0 * minus_dm.ewm(alpha=1.0 / window, adjust=False).mean() / (atr + 1e-12)
        dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-12)
        adx = dx.ewm(alpha=1.0 / window, adjust=False).mean()
        return adx

    @staticmethod
    def _rsi(log_close: pd.Series, window: int) -> pd.Series:
        delta = log_close.diff()
        up = delta.clip(lower=0.0)
        down = (-delta).clip(lower=0.0)
        avg_up = up.ewm(alpha=1.0 / window, adjust=False).mean()
        avg_down = down.ewm(alpha=1.0 / window, adjust=False).mean()
        rs = avg_up / (avg_down + 1e-12)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return rsi

    def _orderbook_features(
        self,
        orderbook: pd.DataFrame,
        ts_ref: pd.Series,
    ) -> Dict[str, pd.Series]:
        if "ts" not in orderbook.columns:
            return {}
        ob = orderbook.sort_values("ts", kind="mergesort").reset_index(drop=True)
        ob = ob.set_index("ts")
        ob = ob.reindex(ts_ref, method="ffill")

        bid_sz_cols = [f"bid_sz_{i}" for i in range(1, self.cfg.ob_depth_levels + 1)]
        ask_sz_cols = [f"ask_sz_{i}" for i in range(1, self.cfg.ob_depth_levels + 1)]
        bid_sz_cols = [c for c in bid_sz_cols if c in ob.columns]
        ask_sz_cols = [c for c in ask_sz_cols if c in ob.columns]

        feats: Dict[str, pd.Series] = {}
        if bid_sz_cols and ask_sz_cols:
            bid_sum = ob[bid_sz_cols].sum(axis=1)
            ask_sum = ob[ask_sz_cols].sum(axis=1)
            denom = (bid_sum + ask_sum).replace(0.0, np.nan)
            feats["ob_imbalance"] = ((bid_sum - ask_sum) / denom).shift(1).astype("float64")
            feats["ob_depth_ratio"] = ((bid_sum / (ask_sum.replace(0.0, np.nan))).shift(1)).astype(
                "float64"
            )

        if ("bid_px_1" in ob.columns) and ("ask_px_1" in ob.columns):
            best_bid = ob["bid_px_1"].astype("float64")
            best_ask = ob["ask_px_1"].astype("float64")
            mid = (best_bid + best_ask) / 2.0
            spread_bps = ((best_ask - best_bid) / mid.replace(0.0, np.nan)) * 1e4
            feats["ob_spread_bps"] = spread_bps.shift(1).astype("float64")

        return feats

    def _sentiment_features(
        self,
        sentiment: pd.DataFrame,
        ts_ref: pd.Series,
    ) -> Dict[str, pd.Series]:
        if "ts" not in sentiment.columns:
            return {}
        s = sentiment.sort_values("ts", kind="mergesort").reset_index(drop=True)
        s = s.set_index("ts")
        s = s.reindex(ts_ref, method="ffill")

        w = self.cfg.sentiment_window
        feats: Dict[str, pd.Series] = {}
        for col in ["sent_mean", "sent_var", "news_count", "social_count"]:
            if col in s.columns:
                ma = s[col].astype("float64").rolling(w, min_periods=w).mean().shift(1)
                feats[f"{col}_ma"] = ma
        return feats
