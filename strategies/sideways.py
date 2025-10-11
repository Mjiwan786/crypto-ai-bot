from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

try:
    import talib  # optional
    _HAS_TALIB = True
except Exception:
    _HAS_TALIB = False


# ---- Optional type to avoid hard dependency on your MCP module ----
@dataclass
class MarketContext:
    """Lightweight shim. Your real MCP context can pass in these fields."""
    regime_state: Optional[str] = None      # 'bull' | 'bear' | 'sideways'
    symbol: Optional[str] = None
    timeframe: Optional[str] = None


class SidewaysStrategy:
    """
    Range/grid strategy for sideways regimes.

    Config keys (all floats are fractions, not %):
      - grid_size: float                # e.g. 0.005 for 0.5% spacing
      - max_grid_levels: int            # number of levels on EACH side
      - position_size: float            # fraction of capital per grid order
      - volatility_cutoff: float        # e.g. 0.01 => 1% ATR/std-of-returns
      - base_confidence: float          # e.g. 0.6 (will be scaled by proximity)
      - stop_loss: float                # optional: distance from entry (fraction)
      - volatility_method: str          # 'atr' or 'std' (optional, default 'atr')
      - atr_period: int                 # optional (default 14)
      - std_window: int                 # optional (default 20)
    """

    def __init__(self) -> None:
        pass

    # ---------- Public API ----------
    def generate_signal(
        self,
        df: pd.DataFrame,
        context: MarketContext,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        self._validate_inputs(df, config)

        # Read config
        grid_size: float = float(config["grid_size"])
        max_levels: int = int(config["max_grid_levels"])
        pos_size: float = float(config["position_size"])
        vol_cutoff: float = float(config["volatility_cutoff"])
        base_conf: float = float(config.get("base_confidence", 0.5))
        stop_loss: Optional[float] = _safe_float(config.get("stop_loss"))
        vol_method: str = str(config.get("volatility_method", "atr")).lower()
        atr_period: int = int(config.get("atr_period", 14))
        std_window: int = int(config.get("std_window", 20))

        # Latest price
        price = float(df["close"].iloc[-1])

        # ---- Volatility check ----
        vol_value, vol_kind = self._compute_volatility(
            df, method=vol_method, atr_period=atr_period, std_window=std_window
        )
        # Normalize ATR to price (ATR %) or use std of returns directly:
        if vol_kind == "atr":
            vol_pct = vol_value / price if price > 0 else np.inf
        else:
            # std of returns is already a fraction; use it as-is
            vol_pct = vol_value

        grid_active = vol_pct <= vol_cutoff
        if not grid_active:
            return {
                "signal": "hold",
                "confidence": 0.0,
                "position_size": 0.0,
                "metadata": {
                    "reason": "volatility_above_cutoff",
                    "volatility": float(vol_pct),
                    "volatility_cutoff": float(vol_cutoff),
                    "volatility_method": vol_kind,
                    "grid_active": False,
                },
            }

        # Optional guard if RegimeRouter still calls us outside sideways
        regime = (context.regime_state or "").lower() if context else ""
        regime_penalty = 0.5 if (regime and regime != "sideways") else 1.0

        # ---- Build grid ----
        grid_levels = self._build_grid(price, grid_size, max_levels)
        lower_near, upper_near, idx_lower, idx_upper, d_lower, d_upper = \
            self._nearest_levels(price, grid_levels)

        # Decide signal by proximity to nearest side
        # Threshold = half grid step (derived from your grid_size -> not a new param)
        price_to_level_ratio_lower = (
            abs(price - lower_near) / (price * grid_size) if lower_near else np.inf
        )
        price_to_level_ratio_upper = (
            abs(price - upper_near) / (price * grid_size) if upper_near else np.inf
        )

        # Closer side wins
        near_side = None
        if price_to_level_ratio_lower < price_to_level_ratio_upper:
            near_side = "lower"
        elif price_to_level_ratio_upper < price_to_level_ratio_lower:
            near_side = "upper"

        # Proximity scaling in [0,1]; the closer you are, the higher the confidence.
        def prox_scale(dist_ratio: float) -> float:
            # dist_ratio measured in grid steps; 0 -> on level, 0.5 -> mid, 1+ -> far
            # Clip to [0,1]; at exactly on-level => 1.0; at one grid step => 0.0
            return float(np.clip(1.0 - dist_ratio, 0.0, 1.0))

        buy_conf = sell_conf = 0.0
        signal = "hold"

        if near_side == "lower" and lower_near is not None:
            dist_ratio = abs(price - lower_near) / (price * grid_size)
            buy_conf = base_conf * prox_scale(dist_ratio) * regime_penalty
            if buy_conf > 0:
                signal = "buy"

        elif near_side == "upper" and upper_near is not None:
            dist_ratio = abs(price - upper_near) / (price * grid_size)
            sell_conf = base_conf * prox_scale(dist_ratio) * regime_penalty
            if sell_conf > 0:
                signal = "sell"

        confidence = float(max(buy_conf, sell_conf))

        # If neither side is reasonably close, hold
        if confidence <= 0.0:
            signal = "hold"

        meta = {
            "symbol": getattr(context, "symbol", None),
            "timeframe": getattr(context, "timeframe", None),
            "regime_state": getattr(context, "regime_state", None),
            "grid_active": True,
            "grid_size": float(grid_size),
            "max_grid_levels": int(max_levels),
            "price": float(price),
            "volatility": float(vol_pct),
            "volatility_method": vol_kind,
            "grid_levels": grid_levels,
            "nearest_lower": float(lower_near) if lower_near else None,
            "nearest_upper": float(upper_near) if upper_near else None,
            "lower_index": int(idx_lower) if idx_lower is not None else None,
            "upper_index": int(idx_upper) if idx_upper is not None else None,
            "distance_to_lower": float(d_lower) if d_lower is not None else None,
            "distance_to_upper": float(d_upper) if d_upper is not None else None,
            "stop_loss": float(stop_loss) if stop_loss is not None else None,
        }

        return {
            "signal": signal,
            "confidence": confidence,
            "position_size": float(pos_size) if signal != "hold" else 0.0,
            "metadata": meta,
        }

    # ---------- Helpers ----------
    @staticmethod
    def _validate_inputs(df: pd.DataFrame, config: Dict[str, Any]) -> None:
        required = ["grid_size", "max_grid_levels", "position_size", "volatility_cutoff"]
        missing = [k for k in required if k not in config]
        if missing:
            raise ValueError(f"SidewaysStrategy config missing: {missing}")
        if not set(["close", "high", "low"]).issubset(df.columns):
            raise ValueError("DataFrame must contain ['high','low','close'] columns.")
        if len(df) < 5:
            raise ValueError("DataFrame too short; need at least 5 rows.")

    @staticmethod
    def _build_grid(price: float, grid_size: float, max_levels: int) -> Dict[str, list]:
        # Symmetric multiplicative grid (percentage steps) around current price
        uppers = [price * (1 + grid_size * i) for i in range(1, max_levels + 1)]
        lowers = [price * (1 - grid_size * i) for i in range(1, max_levels + 1)]
        return {"lower": lowers[::-1], "upper": uppers}  # lower farthest first for readability

    @staticmethod
    def _nearest_levels(price: float, grid: Dict[str, list]):
        lower_levels = grid["lower"]
        upper_levels = grid["upper"]

        lower_near = None
        idx_lower = None
        d_lower = None
        if lower_levels:
            diffs = [abs(price - lvl) for lvl in lower_levels]
            idx_lower = int(np.argmin(diffs))
            lower_near = lower_levels[idx_lower]
            d_lower = diffs[idx_lower]

        upper_near = None
        idx_upper = None
        d_upper = None
        if upper_levels:
            diffs = [abs(price - lvl) for lvl in upper_levels]
            idx_upper = int(np.argmin(diffs))
            upper_near = upper_levels[idx_upper]
            d_upper = diffs[idx_upper]

        return lower_near, upper_near, idx_lower, idx_upper, d_lower, d_upper

    @staticmethod
    def _compute_volatility(
        df: pd.DataFrame, method: str = "atr", atr_period: int = 14, std_window: int = 20
    ) -> tuple[float, str]:
        method = method.lower()
        if method == "atr":
            atr = _atr(df, period=atr_period)
            return float(atr), "atr"
        elif method == "std":
            std_ret = _std_of_returns(df, window=std_window)
            return float(std_ret), "std"
        else:
            # Fallback to ATR if unknown method
            atr = _atr(df, period=atr_period)
            return float(atr), "atr"

    # ---------- Optional: quick visual for debugging ----------
    @staticmethod
    def plot_grid(df: pd.DataFrame, grid: Dict[str, list], title: str = "Sideways Grid"):
        import matplotlib.pyplot as plt

        closes = df["close"].values
        x = np.arange(len(closes))
        plt.figure(figsize=(10, 5))
        plt.plot(x, closes, label="Close")
        for lvl in grid["lower"] + grid["upper"]:
            plt.plot([x[0], x[-1]], [lvl, lvl], linestyle="--", linewidth=0.8)
        plt.title(title)
        plt.xlabel("Bars")
        plt.ylabel("Price")
        plt.legend()
        plt.tight_layout()
        plt.show()


# ---------- Volatility helpers ----------
def _atr(df: pd.DataFrame, period: int = 14) -> float:
    """Return the *latest* ATR value (not series)."""
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values

    if _HAS_TALIB:
        atr_series = talib.ATR(high, low, close, timeperiod=period)
        return float(atr_series[-1])

    # pandas fallback
    prev_close = pd.Series(close).shift(1)
    tr = pd.concat([
        pd.Series(high) - pd.Series(low),
        (pd.Series(high) - prev_close).abs(),
        (pd.Series(low) - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(window=period, min_periods=period).mean().iloc[-1]
    return float(atr)

def _std_of_returns(df: pd.DataFrame, window: int = 20) -> float:
    """Std dev of log returns over window (latest value)."""
    close = df["close"].astype(float)
    rets = np.log(close / close.shift(1)).dropna()
    if len(rets) < max(5, window):
        return float(rets.std() if len(rets) > 1 else np.nan)
    return float(rets.rolling(window=window).std().iloc[-1])


def _safe_float(x: Any) -> Optional[float]:
    try:
        return float(x)
    except Exception:
        return None


# ---------- Standalone test ----------
if __name__ == "__main__":
    # Simulate a range-bound series around 100 with small noise
    np.random.seed(42)
    n = 300
    base = 100.0
    # gentle oscillation + noise
    t = np.arange(n)
    closes = base + 0.6 * np.sin(t / 6.0) + np.random.normal(0, 0.15, size=n)
    highs = closes + np.random.uniform(0.05, 0.25, size=n)
    lows = closes - np.random.uniform(0.05, 0.25, size=n)

    data = pd.DataFrame({"high": highs, "low": lows, "close": closes})

    cfg = {
        "grid_size": 0.005,           # 0.5%
        "max_grid_levels": 10,
        "position_size": 0.05,
        "volatility_cutoff": 0.01,    # 1%
        "base_confidence": 0.6,
        "stop_loss": 0.02,
        "volatility_method": "atr",   # 'atr' | 'std'
        "atr_period": 14,
        "std_window": 20,
    }

    ctx = MarketContext(regime_state="sideways", symbol="TEST/USDT", timeframe="1h")
    strat = SidewaysStrategy()
    signal = strat.generate_signal(data, ctx, cfg)
    print(signal)

    # Optional visual (uncomment to see)
    # grid_meta = signal["metadata"].get("grid_levels")
    # if grid_meta:
    #     strat.plot_grid(data.tail(150), grid_meta, title="Debug Grid (last 150 bars)")
