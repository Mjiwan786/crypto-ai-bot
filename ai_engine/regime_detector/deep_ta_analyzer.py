"""
ai_engine/regime_detector/deep_ta_analyzer.py

Production-grade technical analysis regime detector for crypto AI bot.
Analyzes OHLCV data and microstructure features to classify market regimes
as bull/bear/chop with confidence scores and detailed component analysis.

Algorithm:
- Extracts 4 feature families: trend, momentum, volatility regime, microstructure
- Combines using weighted scoring to composite TA score [-1,1]
- Maps to bull/bear/chop labels with confidence based on data quality
- Optimized for speed (O(N)), deterministic, no side effects

Author: Crypto AI Bot Team
"""

import logging
import re
from typing import Dict, Literal, Optional, Union

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field, field_validator, ConfigDict, field_serializer

# Optional TA-Lib import with fallback
try:
    import talib  # type: ignore
    HAS_TALIB = True
except ImportError:
    HAS_TALIB = False

logger = logging.getLogger(__name__)

# Type aliases
RegimeLabel = Literal["bull", "bear", "chop"]

# Deterministic timeframe parsing
TIMEFRAME_RE = re.compile(r"(?P<num>\d+)(?P<unit>[mhdw])$")


class TAConfig(BaseModel):
    """Configuration for technical analysis regime detection."""

    # Prevent runtime mutation & unknown keys
    model_config = ConfigDict(frozen=True, extra="forbid")

    lookbacks: Dict[str, int] = Field(
        default_factory=lambda: {
            "momentum": 20,
            "trend": 50,
            "vol": 30,
            "micro": 14,
        }
    )

    thresholds: Dict[str, float] = Field(
        default_factory=lambda: {"bull": 0.55, "bear": -0.55, "chop_abs": 0.25}
    )

    weights: Dict[str, float] = Field(
        default_factory=lambda: {
            "trend": 0.45,
            "momentum": 0.30,
            "vol_regime": 0.15,
            "microstructure": 0.10,
        }
    )

    guardrails: Dict[str, Union[int, float]] = Field(
        default_factory=lambda: {
            "min_rows": 200,
            "max_age_ms": 15 * 60 * 1000,  # 15 minutes
            "max_nan_frac": 0.05,
        }
    )

    latency_budget_ms: int = Field(default=250)

    @field_validator("weights")
    @classmethod
    def validate_weights_sum(cls, v: Dict[str, float]) -> Dict[str, float]:
        total = sum(v.values())
        if not (0.95 <= total <= 1.05):
            raise ValueError(f"Weights must sum to ~1.0, got {total:.3f}")
        return v

    @field_validator("thresholds")
    @classmethod
    def validate_thresholds(cls, v: Dict[str, float]) -> Dict[str, float]:
        if v["bull"] <= v["chop_abs"] or v["bear"] >= -v["chop_abs"]:
            raise ValueError(
                "Invalid threshold ordering: bear < -chop_abs < chop_abs < bull"
            )
        return v


class TARegime(BaseModel):
    """Technical analysis regime detection result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(default="1.0", description="Schema version for compatibility")
    label: RegimeLabel
    confidence: float = Field(ge=0.0, le=1.0)
    components: Dict[str, float] = Field(description="Component scores [-1,1]")
    features: Dict[str, float] = Field(description="Raw feature values")
    explain: str = Field(description="Single-line reasoning")
    latency_ms: int = Field(ge=0)
    n_samples: int = Field(ge=0)

    # Deterministic JSON: sort keys
    @field_serializer("components", "features", mode="plain")
    def _sort_keys(self, v: Dict[str, float]) -> Dict[str, float]:
        return {k: v[k] for k in sorted(v)}


class TAAnalyzer:
    """Core technical analysis engine with vectorized operations."""

    def __init__(self) -> None:
        pass

    def _indicator_ema(self, series: pd.Series, period: int) -> pd.Series:
        """Exponential moving average with fallback."""
        if HAS_TALIB:
            return pd.Series(
                talib.EMA(series.values, timeperiod=period), index=series.index
            )
        else:
            return series.ewm(span=period, adjust=False).mean()

    def _indicator_rsi(self, series: pd.Series, period: int = 14) -> pd.Series:
        """RSI with fallback implementation."""
        if HAS_TALIB:
            return pd.Series(
                talib.RSI(series.values, timeperiod=period), index=series.index
            )
        else:
            delta = series.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
            rs = gain / loss.replace(0, np.inf)
            return 100 - (100 / (1 + rs))

    def _indicator_adx(
        self, high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
    ) -> pd.Series:
        """ADX with fallback implementation."""
        if HAS_TALIB:
            return pd.Series(
                talib.ADX(high.values, low.values, close.values, timeperiod=period),
                index=close.index,
            )
        else:
            # Wilder's DI/ADX (deterministic, vectorized, safe divisions)
            tr = np.maximum.reduce(
                [
                    (high - low),
                    (high - close.shift()).abs(),
                    (low - close.shift()).abs(),
                ]
            )
            up_move = high.diff().clip(lower=0)
            down_move = (-low.diff()).clip(lower=0)
            dm_plus = np.where(up_move > down_move, up_move, 0.0)
            dm_minus = np.where(down_move > up_move, down_move, 0.0)

            tr_s = pd.Series(tr, index=close.index).ewm(
                alpha=1 / period, adjust=False
            ).mean()
            dmp_s = pd.Series(dm_plus, index=close.index).ewm(
                alpha=1 / period, adjust=False
            ).mean()
            dmm_s = pd.Series(dm_minus, index=close.index).ewm(
                alpha=1 / period, adjust=False
            ).mean()

            di_p = 100 * (dmp_s / tr_s).replace([np.inf, -np.inf], np.nan)
            di_m = 100 * (dmm_s / tr_s).replace([np.inf, -np.inf], np.nan)
            dx = 100 * (di_p - di_m).abs() / (di_p + di_m).replace(0, np.nan)
            return dx.ewm(alpha=1 / period, adjust=False).mean()

    def _indicator_roc(self, series: pd.Series, period: int) -> pd.Series:
        """Rate of change."""
        return ((series / series.shift(period)) - 1) * 100

    def _indicator_bbands(
        self, series: pd.Series, period: int = 20, std_dev: float = 2.0
    ) -> Dict[str, pd.Series]:
        """Bollinger Bands."""
        if HAS_TALIB:
            upper, middle, lower = talib.BBANDS(
                series.values, timeperiod=period, nbdevup=std_dev, nbdevdn=std_dev
            )
            return {
                "upper": pd.Series(upper, index=series.index),
                "middle": pd.Series(middle, index=series.index),
                "lower": pd.Series(lower, index=series.index),
            }
        else:
            sma = series.rolling(period).mean()
            std = series.rolling(period).std()
            return {
                "upper": sma + (std * std_dev),
                "middle": sma,
                "lower": sma - (std * std_dev),
            }

    def _indicator_logret_vol(
        self, series: pd.Series, period: int, minutes_per_bar: int
    ) -> pd.Series:
        """Realized volatility from log returns with proper timeframe scaling."""
        log_returns = np.log(series / series.shift(1))
        scale = np.sqrt(252 * (1440 / max(1, int(minutes_per_bar))))
        return log_returns.rolling(period).std() * scale

    def _z_score_to_regime(self, series: pd.Series, window: int = 50) -> pd.Series:
        """Convert series to z-score and soft-clip; fully vectorized."""
        mean = series.rolling(window, min_periods=window).mean()
        std = series.rolling(window, min_periods=window).std().replace(0, np.nan)
        z = (series - mean) / std
        z = z.clip(lower=-10, upper=10)
        return pd.Series(np.tanh(z / 3.0), index=series.index).fillna(0.0)

    def compute_features(
        self, df: pd.DataFrame, cfg: "TAConfig", minutes_per_bar: int = 1
    ) -> Dict[str, pd.Series]:
        """
        Extract all technical analysis features vectorized.

        Args:
            df: OHLCV DataFrame
            cfg: TAConfig configuration
            minutes_per_bar: Minutes per bar for volatility scaling

        Returns:
            Dictionary of normalized feature series aligned to df.index.
        """
        # Create working copy to avoid mutation
        data = df.copy()

        # Ensure required columns
        required_cols = ["open", "high", "low", "close", "volume"]
        missing_cols = [col for col in required_cols if col not in data.columns]
        if missing_cols:
            raise ValueError(f"Missing required columns: {missing_cols}")

        # Convert to float and handle infinite values
        for col in required_cols:
            data[col] = (
                pd.to_numeric(data[col], errors="coerce")
                .replace([np.inf, -np.inf], np.nan)
            )

        features: Dict[str, pd.Series] = {}

        # === TREND FEATURES ===
        ema_trend = self._indicator_ema(data["close"], cfg.lookbacks["trend"])
        price_vs_ema = (data["close"] / ema_trend - 1).fillna(0)

        # Trend slope (normalized)
        ema_slope = ema_trend.diff(5) / ema_trend.shift(5)
        trend_slope_norm = self._z_score_to_regime(ema_slope, 30)

        # ADX for trend strength
        adx = self._indicator_adx(
            data["high"], data["low"], data["close"], cfg.lookbacks["micro"]
        )
        adx_norm = (adx / 50.0).clip(0, 1).fillna(0)  # Normalize ADX to [0,1]

        # Combine trend features
        trend_score = (trend_slope_norm + (price_vs_ema * 2).clip(-1, 1)) / 2
        trend_score = trend_score * adx_norm  # Weight by trend strength

        features["trend"] = trend_score.fillna(0)

        # === MOMENTUM FEATURES ===
        roc = self._indicator_roc(data["close"], cfg.lookbacks["momentum"])
        roc_norm = self._z_score_to_regime(roc, cfg.lookbacks["momentum"])

        rsi = self._indicator_rsi(data["close"], cfg.lookbacks["micro"])
        rsi_norm = ((rsi - 50) / 50).clip(-1, 1).fillna(0)  # RSI to [-1,1]

        momentum_score = (roc_norm + rsi_norm) / 2
        features["momentum"] = momentum_score.fillna(0)

        # === VOLATILITY REGIME ===
        realized_vol = self._indicator_logret_vol(
            data["close"], cfg.lookbacks["vol"], minutes_per_bar
        )
        # Deterministic tie-handling for percentiles
        vol_percentile = (
            realized_vol.rolling(cfg.lookbacks["vol"] * 2)
            .rank(pct=True, method="first")
            .fillna(0.5)
        )

        # Bollinger band width as volatility measure
        bbands = self._indicator_bbands(data["close"], cfg.lookbacks["vol"])
        bb_width = ((bbands["upper"] - bbands["lower"]) / bbands["middle"]).fillna(0)
        bb_width_pct = (
            bb_width.rolling(cfg.lookbacks["vol"])
            .rank(pct=True, method="first")
            .fillna(0.5)
        )

        # High vol periods discount trending (favor chop)
        vol_regime_score = (vol_percentile + bb_width_pct) / 2
        vol_regime_score = (0.5 - vol_regime_score) * 2  # Invert: high vol = negative score

        features["vol_regime"] = vol_regime_score.fillna(0)

        # === MICROSTRUCTURE ===
        # Intrabar pressure
        bar_range = (data["high"] - data["low"]).replace(0, np.finfo(float).eps)
        intrabar_pressure = (data["close"] - data["open"]) / bar_range
        intrabar_norm = self._z_score_to_regime(
            intrabar_pressure, cfg.lookbacks["micro"]
        )

        # Wick analysis
        upper_wick = (data["high"] - np.maximum(data["open"], data["close"])) / bar_range
        lower_wick = (np.minimum(data["open"], data["close"]) - data["low"]) / bar_range
        wick_imbalance = (lower_wick - upper_wick).fillna(
            0
        )  # Positive = more lower wicks (bullish)
        wick_norm = self._z_score_to_regime(wick_imbalance, cfg.lookbacks["micro"])

        # Volume-weighted pressure (simplified)
        volume_pressure = (data["volume"] * intrabar_pressure).rolling(
            cfg.lookbacks["micro"]
        ).sum()
        volume_pressure_norm = self._z_score_to_regime(
            volume_pressure, cfg.lookbacks["micro"]
        )

        micro_score = (intrabar_norm + wick_norm + volume_pressure_norm) / 3
        features["microstructure"] = micro_score.fillna(0)

        return features


def detect_ta_regime(
    df: pd.DataFrame,
    timeframe: str,
    config: Union[TAConfig, dict],
    context_meta: Optional[dict] = None,
) -> TARegime:
    """
    Main entry point for TA regime detection.

    Args:
        df: OHLCV DataFrame with timestamp, open, high, low, close, volume
        timeframe: Timeframe string (for metadata and scaling)
        config: TAConfig or dict with configuration parameters
        context_meta: Optional context with now_ms, spread_bps_mean

    Returns:
        TARegime with label, confidence, components, and diagnostics
    """
    # No wall-clock usage in pure logic layer
    try:
        # Validate and convert config
        if isinstance(config, dict):
            config = TAConfig(**config)

        context_meta = context_meta or {}

        # Validate timeframe and derive deterministic bar interval (no wall-clock)
        _tf_match = TIMEFRAME_RE.fullmatch(timeframe)
        if not _tf_match:
            raise ValueError(f"Invalid timeframe: {timeframe!r}")
        _num = int(_tf_match.group("num"))
        _unit = _tf_match.group("unit")
        _unit_to_min = {"m": 1, "h": 60, "d": 1440, "w": 10080}
        _bar_minutes = _num * _unit_to_min[_unit]

        # Deterministic 'now_ms'
        if "now_ms" in context_meta:
            now_ms = int(context_meta["now_ms"])
        elif "timestamp" in df.columns:
            _last_ts = pd.Timestamp(df["timestamp"].iloc[-1])
            now_ms = int(_last_ts.value // 1_000_000) + (_bar_minutes * 60_000)
        else:
            now_ms = None

        spread_bps_mean = float(context_meta.get("spread_bps_mean", 0.0))

        # Input validation
        if df is None or len(df) == 0:
            return TARegime(
                label="chop",
                confidence=0.0,
                components={},
                features={},
                explain="empty_data",
                latency_ms=0,
                n_samples=0,
            )

        # Sort deterministically by timestamp if present
        if "timestamp" in df.columns:
            data = df.copy()
            data["timestamp"] = pd.to_datetime(data["timestamp"], utc=False)
            data = data.sort_values("timestamp").reset_index(drop=True)
        else:
            data = df

        n_samples = len(data)
        if n_samples < config.guardrails["min_rows"]:
            return TARegime(
                label="chop",
                confidence=0.0,
                components={},
                features={},
                explain=f"insufficient_data_{n_samples}<{config.guardrails['min_rows']}",
                latency_ms=0,
                n_samples=n_samples,
            )

        # Check data freshness (only if now_ms is available)
        if "timestamp" in data.columns and now_ms is not None:
            last_timestamp = data["timestamp"].iloc[-1]
            last_ms = int(pd.Timestamp(last_timestamp).value // 1_000_000)
            age_ms = now_ms - last_ms
            is_stale = age_ms > config.guardrails["max_age_ms"]
        else:
            age_ms = 0
            is_stale = False

        # Infer minutes per bar deterministically from timestamps (fallback=_bar_minutes)
        if "timestamp" in data.columns:
            _dt = pd.to_datetime(data["timestamp"])
            _secs = _dt.diff().dt.total_seconds().dropna()
            if not _secs.empty:
                # Deterministic rounding: floor(x/60 + 0.5)
                minutes_per_bar = max(
                    1, int(np.floor((_secs.median() / 60.0) + 0.5))
                )
            else:
                minutes_per_bar = _bar_minutes
        else:
            minutes_per_bar = _bar_minutes

        # Extract features
        analyzer = TAAnalyzer()
        features = analyzer.compute_features(data, config, minutes_per_bar)

        # Compute component scores (latest values)
        components: Dict[str, float] = {}
        latest_features: Dict[str, float] = {}

        # Precompute diagnostics once (avoid duplicate O(N) work) and cast to JSON-safe floats
        try:
            ema_50_last = float(analyzer._indicator_ema(data["close"], 50).iloc[-1])
        except Exception:
            ema_50_last = float("nan")
        try:
            rsi_14_last = float(analyzer._indicator_rsi(data["close"], 14).iloc[-1])
        except Exception:
            rsi_14_last = float("nan")

        for component in ("trend", "momentum", "vol_regime", "microstructure"):
            if component in features:
                series = features[component]
                latest_val = float(series.iloc[-1]) if len(series) > 0 else 0.0
                components[component] = latest_val
                latest_features[f"{component}_score"] = latest_val

                # Additional feature diagnostics
                if component == "trend":
                    latest_features["ema_50"] = ema_50_last
                elif component == "momentum":
                    latest_features["rsi_14"] = rsi_14_last

        # Weighted composite score (fixed component order)
        ta_score = 0.0
        for comp_name in ("trend", "momentum", "vol_regime", "microstructure"):
            ta_score += config.weights.get(comp_name, 0.0) * components.get(
                comp_name, 0.0
            )
        ta_score = float(np.clip(ta_score, -1.0, 1.0))

        # Determine regime label
        if abs(ta_score) < config.thresholds["chop_abs"]:
            label: RegimeLabel = "chop"
        elif ta_score >= config.thresholds["bull"]:
            label = "bull"
        elif ta_score <= config.thresholds["bear"]:
            label = "bear"
        else:
            label = "chop"

        # Calculate confidence
        base_confidence = min(1.0, n_samples / config.guardrails["min_rows"])

        # Penalize high spreads
        spread_penalty = min(0.3, max(0.0, (spread_bps_mean - 20.0) / 100.0))

        # Penalize staleness (only if now_ms was provided)
        staleness_penalty = 0.2 if is_stale else 0.0

        # Data quality penalty: compute from raw inputs over deterministic window
        required_cols = ["open", "high", "low", "close", "volume"]
        window_n = max(int(max(config.lookbacks.values())), 1)
        tail = data[required_cols].tail(window_n)
        nan_fraction = float(tail.isna().mean().mean())
        quality_penalty = min(0.3, nan_fraction * 3.0)

        confidence = base_confidence * (
            1.0 - spread_penalty - staleness_penalty - quality_penalty
        )
        confidence = max(0.0, min(1.0, confidence))

        # Circuit breaker: if confidence too low or spread too high, default to chop
        if confidence < 0.3 or spread_bps_mean > 50.0:
            label = "chop"
            confidence = max(0.1, confidence)  # Minimum confidence for chop

        # Create explanation with detailed reasoning
        explain_parts = [f"{label}", f"score={ta_score:.2f}", f"conf={confidence:.2f}"]

        if is_stale:
            explain_parts.append("stale")
        if spread_bps_mean > 20.0:
            explain_parts.append(f"wide_spread_{spread_bps_mean:.1f}bps")
        if nan_fraction > float(config.guardrails.get("max_nan_frac", 1.0)):
            explain_parts.append(f"nan>{float(config.guardrails['max_nan_frac']):.2f}")
        if confidence < 0.3:
            explain_parts.append("low_conf")
        if nan_fraction > 0.1:
            explain_parts.append("data_quality_issues")

        explain = "|".join(explain_parts)

        # Store additional features for learning (JSON-safe types)
        latest_features.update(
            {
                "ta_score": float(ta_score),
                "spread_bps_mean": float(spread_bps_mean),
                "age_ms": int(age_ms),
                "nan_fraction": float(nan_fraction),
            }
        )

        result = TARegime(
            label=label,
            confidence=float(confidence),
            components=components,
            features=latest_features,
            explain=explain,
            latency_ms=0,  # No wall-clock timing in pure logic layer
            n_samples=n_samples,
        )

        # Logging
        logger.info(
            f"TA regime: {label} (conf={confidence:.3f}, score={ta_score:.3f}, "
            f"n={n_samples}) - {explain}"
        )

        if logger.isEnabledFor(logging.DEBUG):
            comp_str = ", ".join(f"{k}={components[k]:.3f}" for k in sorted(components))
            logger.debug(f"TA components: {comp_str}")

        return result

    except Exception:
        logger.exception("TA regime detection failed")

        return TARegime(
            label="chop",
            confidence=0.0,
            components={},
            features={"error": "exception_occurred"},
            explain="error_Exception",
            latency_ms=0,
            n_samples=len(df) if df is not None else 0,
        )


def compute_features(
    df: pd.DataFrame, cfg: TAConfig, timeframe: str = "1m"
) -> Dict[str, pd.Series]:
    """
    Standalone feature computation function.

    Args:
        df: OHLCV DataFrame
        cfg: TAConfig configuration
        timeframe: Timeframe string for proper volatility scaling

    Returns:
        Dictionary of computed feature series
    """
    # Parse timeframe to get minutes per bar
    _tf_match = TIMEFRAME_RE.fullmatch(timeframe)
    if not _tf_match:
        minutes_per_bar = 1  # Default fallback
    else:
        _num = int(_tf_match.group("num"))
        _unit = _tf_match.group("unit")
        _unit_to_min = {"m": 1, "h": 60, "d": 1440, "w": 10080}
        minutes_per_bar = _num * _unit_to_min[_unit]

    analyzer = TAAnalyzer()
    return analyzer.compute_features(df, cfg, minutes_per_bar)


if __name__ == "__main__":
    # Lightweight self-check for CI/testing
    import warnings

    warnings.filterwarnings("ignore")
    logging.basicConfig(level=logging.INFO)

    # Generate synthetic OHLCV data
    np.random.seed(42)
    n_bars = 300

    # Create realistic price series with trend + noise
    trend = np.linspace(100, 110, n_bars)
    noise = np.random.normal(0, 2, n_bars)
    close = trend + noise

    # Generate OHLC from close
    open_prices = np.roll(close, 1)
    open_prices[0] = close[0]

    high = np.maximum(open_prices, close) + np.random.exponential(0.5, n_bars)
    low = np.minimum(open_prices, close) - np.random.exponential(0.5, n_bars)
    volume = np.random.lognormal(10, 1, n_bars)

    # Create DataFrame
    test_df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=n_bars, freq="1min"),
            "open": open_prices,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )

    # Run detection
    config = TAConfig()
    result = detect_ta_regime(test_df, "1m", config)

    logger.info(
        "Self-check: %s (conf=%.3f, %d samples) | %s",
        result.label,
        result.confidence,
        result.n_samples,
        result.explain,
    )
