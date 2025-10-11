"""
ai_engine/regime_detector/sentiment_analyzer.py

Production-ready sentiment/flow regime component for Crypto AI Bot.
Ingests pre-aggregated numeric sentiment signals and outputs bull/bear/chop regime
assessments with confidence, explainability, and strict validation.

Author: Crypto AI Bot Team
Version: 1.0.0
Python: 3.10-3.12
Dependencies: numpy, pandas, pydantic

Notes:
- This module expects pre-aggregated numeric inputs that are language-normalized
  and calibrated (e.g., VADER vs transformer) by upstream sentiment processors.
  Multilingual bias and source calibration must be handled upstream.
- Deterministic timing: pass t_start_ms/t_end_ms via context_meta; no wall clock usage.
- Outputs use deterministic key ordering for JSON serialization.
"""

from __future__ import annotations

import hashlib
import json
import logging
from functools import lru_cache
from statistics import mean
from typing import Any, Dict, Literal, Optional, Union

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

__all__ = [
    "SentimentConfig",
    "SentimentRegime",
    "compute_sentiment_features",
    "score_components",
    "detect_sentiment_regime",
]

# Configure logging
logger = logging.getLogger(__name__)


class SentimentConfig(BaseModel):
    """Configuration for sentiment regime detection with Kraken-optimized defaults."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_assignment=True)
    # Contract versioning for downstream services
    schema_version: Literal["1.0"] = Field(
        default="1.0", description="Schema version for SentimentConfig"
    )

    # Lookback windows for rolling calculations
    lookbacks: Dict[str, int] = Field(
        default_factory=lambda: {"short": 20, "medium": 60, "long": 180},
        description="Lookback periods for short/medium/long term analysis",
    )

    # Component weights (must sum to ~1.0)
    weights: Dict[str, float] = Field(
        default_factory=lambda: {"social": 0.45, "news": 0.35, "reaction": 0.20},
        description="Weights for social/news/reaction components",
    )

    # Decision thresholds
    thresholds: Dict[str, float] = Field(
        default_factory=lambda: {"bull": 0.55, "bear": -0.55, "chop_abs": 0.25},
        description="Thresholds for bull/bear/chop classification",
    )

    # Data quality guardrails
    guardrails: Dict[str, Union[int, float]] = Field(
        default_factory=lambda: {
            "min_rows": 200,
            "max_nan_frac": 0.15,
            "min_signal_volume": 50.0,
        },
        description="Data quality requirements",
    )

    # Scaling and clipping parameters
    scaling: Dict[str, float] = Field(
        default_factory=lambda: {
            "vol_z_clip": 3.5,
            "score_clip": 1.0,
            "dispersion_clip": 3.0,
        },
        description="Scaling and clipping parameters",
    )

    # Performance budget
    latency_budget_ms: int = Field(default=250, ge=50, le=2000)

    @field_validator("weights")
    @classmethod
    def validate_weights_sum(cls, v: Dict[str, float]) -> Dict[str, float]:
        total = sum(v.values())
        if abs(total - 1.0) > 0.02:
            raise ValueError(f"Weights must sum to ~1.0, got {total:.3f}")
        return v

    @field_validator("thresholds")
    @classmethod
    def validate_thresholds(cls, v: Dict[str, float]) -> Dict[str, float]:
        if v.get("bull", 0) <= v.get("chop_abs", 0):
            raise ValueError("Bull threshold must be > chop_abs threshold")
        if v.get("bear", 0) >= -v.get("chop_abs", 0):
            raise ValueError("Bear threshold must be < -chop_abs threshold")
        return v


class SentimentRegime(BaseModel):
    """Sentiment regime assessment output with deterministic serialization."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Contract versioning for downstream services
    schema_version: Literal["1.0"] = Field(
        default="1.0", description="Schema version for SentimentRegime"
    )

    label: Literal["bull", "bear", "chop"] = Field(description="Regime classification")
    confidence: float = Field(ge=0.0, le=1.0, description="Classification confidence")
    components: Dict[str, float] = Field(
        description="Component scores in [-1,1]"
    )
    features: Dict[str, float] = Field(
        description="Feature values for logging/learning"
    )
    explain: str = Field(description="Single-line explanation of top drivers")
    latency_ms: int = Field(ge=0, description="Processing latency in milliseconds")
    n_samples: int = Field(ge=0, description="Number of samples processed")

    @field_serializer("components", "features")
    def serialize_dicts_sorted(self, v: Dict[str, float]) -> Dict[str, float]:
        """Ensure deterministic JSON ordering by sorting keys."""
        return {k: v[k] for k in sorted(v.keys())}


@lru_cache(maxsize=32)
def _validate_timeframe(timeframe: str) -> str:
    """Validate timeframe format with caching for performance."""
    import re

    if not re.match(r"^\d+[mhdw]$", timeframe):
        raise ValueError(
            f"Invalid timeframe format: {timeframe}. Must match pattern like '5m', '1h', '1d'"
        )
    return timeframe


def _safe_clip(arr: pd.Series, lower: float, upper: float) -> pd.Series:
    """Safely clip array values with NaN handling."""
    return arr.clip(lower=lower, upper=upper)


def _safe_zscore(series: pd.Series, window: int, clip_val: float = 3.0) -> pd.Series:
    """Compute rolling z-score with clipping and NaN handling."""
    if len(series) < window:
        return pd.Series(0.0, index=series.index)

    rolling_mean = series.rolling(window=window, min_periods=max(1, window // 2)).mean()
    rolling_std = series.rolling(window=window, min_periods=max(1, window // 2)).std()

    # Avoid division by zero
    rolling_std = rolling_std.where(rolling_std > 1e-8, 1e-8)

    zscore = (series - rolling_mean) / rolling_std
    return _safe_clip(zscore, -clip_val, clip_val)


def _soft_tanh_scale(x: Union[float, pd.Series], scale: float = 1.0) -> Union[float, pd.Series]:
    """Apply soft tanh scaling to bound values in [-1, 1]."""
    return np.tanh(x * scale)


def compute_sentiment_features(df: pd.DataFrame, cfg: SentimentConfig) -> Dict[str, pd.Series]:
    """
    Compute sentiment features from raw input data with vectorized operations.

    Args:
        df: Input DataFrame with sentiment columns
        cfg: Configuration object

    Returns:
        Dictionary of computed feature series
    """
    features: Dict[str, pd.Series] = {}
    n_rows = len(df)

    if n_rows < cfg.guardrails["min_rows"]:
        logger.warning(
            "Insufficient data: %d rows < %d required",
            n_rows,
            cfg.guardrails["min_rows"],
        )

    # Sentiment score normalization (soft clip to [-1,1])
    for col in ["tw_score", "rd_score", "news_score"]:
        if col in df.columns:
            raw_series = df[col].fillna(0.0)
            features[f"{col}_s"] = _safe_clip(
                raw_series, -cfg.scaling["score_clip"], cfg.scaling["score_clip"]
            )
        else:
            features[f"{col}_s"] = pd.Series(0.0, index=df.index)

    # Volume z-scores with clipping
    for col in ["tw_volume", "rd_volume", "news_volume"]:
        base_name = col.replace("_volume", "_vol")
        if col in df.columns:
            raw_series = df[col].fillna(0.0)
            # Ensure non-negative volumes
            raw_series = raw_series.clip(lower=0.0)
            features[f"{base_name}_z"] = _safe_zscore(
                raw_series, cfg.lookbacks["medium"], cfg.scaling["vol_z_clip"]
            )
        else:
            features[f"{base_name}_z"] = pd.Series(0.0, index=df.index)

    # News dispersion (uncertainty penalty)
    if "news_dispersion" in df.columns:
        disp_series = df["news_dispersion"].fillna(0.0).clip(lower=0.0)
        features["news_dispersion_s"] = _safe_clip(
            disp_series, 0.0, cfg.scaling["dispersion_clip"]
        )
    else:
        features["news_dispersion_s"] = pd.Series(0.0, index=df.index)

    # Return reaction features (price-sentiment alignment)
    for col in ["ret_5m", "ret_1h"]:
        if col in df.columns:
            ret_series = df[col].fillna(0.0)
            # Scale returns to [-1,1] using tanh
            features[f"{col}_s"] = _soft_tanh_scale(ret_series, scale=20.0)  # ~5% -> ~1.0
        else:
            features[f"{col}_s"] = pd.Series(0.0, index=df.index)

    # Mention counts (simple normalization)
    for col in ["mentions_btc", "mentions_eth"]:
        if col in df.columns:
            mentions_series = df[col].fillna(0.0).clip(lower=0.0)
            # Log-scale normalization for mentions
            features[f"{col}_norm"] = np.log1p(mentions_series) / np.log1p(1000.0)  # Cap at ~1000 mentions
            features[f"{col}_norm"] = features[f"{col}_norm"].clip(0.0, 1.0)
        else:
            features[f"{col}_norm"] = pd.Series(0.0, index=df.index)

    logger.debug("Computed %d features for %d samples", len(features), n_rows)
    return features


def score_components(feat: Dict[str, pd.Series], cfg: SentimentConfig) -> Dict[str, pd.Series]:
    """
    Score individual sentiment components from features.

    Args:
        feat: Feature dictionary from compute_sentiment_features
        cfg: Configuration object

    Returns:
        Dictionary of component scores in [-1,1]
    """
    components: Dict[str, pd.Series] = {}

    # Get reference index from features - use first available feature
    reference_index = None
    for series in feat.values():
        if len(series) > 0:
            reference_index = series.index
            break

    if reference_index is None:
        # Fallback to empty series if no features available
        reference_index = pd.Index([])

    # Social component (weighted combination of Twitter + Reddit)
    tw_score = feat.get("tw_score_s", pd.Series(0.0, index=reference_index))
    rd_score = feat.get("rd_score_s", pd.Series(0.0, index=reference_index))
    tw_vol_z = feat.get("tw_vol_z", pd.Series(0.0, index=reference_index))
    rd_vol_z = feat.get("rd_vol_z", pd.Series(0.0, index=reference_index))

    # Volume weighting (positive z-scores increase weight)
    tw_weight = (1.0 + tw_vol_z.clip(0, 2.0) / 2.0) / 2.0  # Range: [0.5, 1.0]
    rd_weight = (1.0 + rd_vol_z.clip(0, 2.0) / 2.0) / 2.0  # Range: [0.5, 1.0]

    # Weighted combination
    total_weight = tw_weight + rd_weight
    social_score = (tw_score * tw_weight + rd_score * rd_weight) / total_weight.where(
        total_weight > 0, 1.0
    )
    components["social"] = _soft_tanh_scale(social_score, scale=1.0)

    # News component (score adjusted by volume and dispersion)
    news_score = feat.get("news_score_s", pd.Series(0.0, index=reference_index))
    news_vol_z = feat.get("news_vol_z", pd.Series(0.0, index=reference_index))
    news_disp = feat.get("news_dispersion_s", pd.Series(0.0, index=reference_index))

    # Volume boost (positive z-score increases effectiveness)
    volume_multiplier = 1.0 + news_vol_z.clip(0, 2.0) / 4.0  # Range: [1.0, 1.5]

    # Dispersion penalty (higher dispersion reduces effectiveness)
    dispersion_penalty = 1.0 / (1.0 + news_disp / 2.0)  # Range: [0.33, 1.0]

    news_effective = news_score * volume_multiplier * dispersion_penalty
    components["news"] = _soft_tanh_scale(news_effective, scale=1.0)

    # Reaction component (price momentum alignment)
    ret_5m_s = feat.get("ret_5m_s", pd.Series(0.0, index=reference_index))
    ret_1h_s = feat.get("ret_1h_s", pd.Series(0.0, index=reference_index))

    # Weighted combination favoring shorter-term moves
    reaction_score = 0.6 * ret_5m_s + 0.4 * ret_1h_s
    components["reaction"] = _soft_tanh_scale(reaction_score, scale=1.0)

    logger.debug("Computed %d component scores", len(components))
    return components


def _calculate_component_confidence(
    components: Dict[str, pd.Series], feat: Dict[str, pd.Series]
) -> Dict[str, float]:
    """Calculate confidence for each component based on data quality and consistency."""
    confidence: Dict[str, float] = {}

    for comp_name, comp_series in components.items():
        if len(comp_series) == 0:
            confidence[comp_name] = 0.0
            continue

        # Base confidence from data availability
        valid_ratio = float(comp_series.notna().sum()) / float(len(comp_series))
        base_conf = min(valid_ratio, 1.0)

        # Reduce confidence for extreme values (may indicate data issues)
        extreme_ratio = float((comp_series.abs() > 0.9).sum()) / float(len(comp_series))
        extreme_penalty = max(0.0, 1.0 - extreme_ratio * 2.0)

        # Component-specific adjustments
        if comp_name == "social":
            # Check volume support
            tw_vol = feat.get("tw_vol_z", pd.Series(0.0))
            rd_vol = feat.get("rd_vol_z", pd.Series(0.0))
            avg_vol_support = float((tw_vol + rd_vol).abs().mean()) if len(tw_vol) else 0.0
            vol_boost = min(avg_vol_support / 2.0, 0.2)
            base_conf += vol_boost

        elif comp_name == "news":
            # Penalize high dispersion
            news_disp = feat.get("news_dispersion_s", pd.Series(0.0))
            avg_dispersion = float(news_disp.mean()) if len(news_disp) else 0.0
            disp_penalty = max(0.0, avg_dispersion / 3.0)
            base_conf -= disp_penalty

        elif comp_name == "reaction":
            # Boost confidence if price moves align with sentiment
            rc_std = float(comp_series.abs().std()) if len(comp_series) else 1.0
            reaction_consistency = 1.0 - rc_std
            base_conf *= max(0.5, reaction_consistency)

        # Ensure no NaN values propagate
        base_conf = float(np.nan_to_num(base_conf, nan=0.0, posinf=1.0, neginf=0.0))
        confidence[comp_name] = max(0.0, min(1.0, base_conf * extreme_penalty))

    return confidence


def _generate_explanation(
    label: str,
    sentiment_score: float,
    components: Dict[str, float],
    component_conf: Dict[str, float],
) -> str:
    """Generate concise explanation of the sentiment regime decision."""
    # Find top contributing components (deterministic tie-breaker by name)
    comp_contrib = {k: abs(v) * component_conf.get(k, 0.5) for k, v in components.items()}
    top_components = sorted(comp_contrib.items(), key=lambda x: (-x[1], x[0]))[:2]

    # Build explanation
    regime_desc = {
        "bull": "bullish sentiment",
        "bear": "bearish sentiment",
        "chop": "neutral/choppy sentiment",
    }

    if not top_components:
        return f"{regime_desc[label]} (score: {sentiment_score:.2f}) - insufficient data"

    driver_parts = []
    for comp_name, _ in top_components:
        comp_score = components[comp_name]
        direction = "positive" if comp_score > 0 else "negative"
        driver_parts.append(f"{direction} {comp_name}")

    drivers_str = " + ".join(driver_parts)
    return f"{regime_desc[label]} (score: {sentiment_score:.2f}) driven by {drivers_str}"


def detect_sentiment_regime(
    df: pd.DataFrame,
    timeframe: str,
    config: Union[SentimentConfig, Dict[str, Any]],
    context_meta: Optional[Dict[str, Any]] = None,
) -> SentimentRegime:
    """
    Main entry point for sentiment regime detection.

    Args:
        df: DataFrame with sentiment data columns (expects pre-aggregated,
            language-normalized numeric signals from upstream processors)
        timeframe: Trading timeframe (e.g., "5m", "1h")
        config: Configuration object or dict
        context_meta: Optional context metadata with t_start_ms/t_end_ms for deterministic timing

    Returns:
        SentimentRegime result with label, confidence, and explanations
    """
    # Deterministic timing: rely on provided context; default to 0
    context_meta = context_meta or {}
    t_start_ms = int(context_meta.get("t_start_ms", 0))
    t_end_ms_hint = int(context_meta.get("t_end_ms", 0))

    try:
        # Validate inputs
        _validate_timeframe(timeframe)

        if isinstance(config, dict):
            config = SentimentConfig(**config)

        # Validate DataFrame
        if df.empty:
            logger.warning("Empty DataFrame provided")
            return SentimentRegime(
                label="chop",
                confidence=0.0,
                components={"social": 0.0, "news": 0.0, "reaction": 0.0},
                features={},
                explain="No data available",
                latency_ms=(t_end_ms_hint - t_start_ms) if (t_end_ms_hint and t_start_ms) else 0,
                n_samples=0,
            )

        n_samples = len(df)

        # Data quality checks
        nan_ratio = df.isnull().sum().sum() / (len(df) * len(df.columns))
        if nan_ratio > config.guardrails["max_nan_frac"]:
            logger.warning(
                "High NaN ratio: %.2f%% > %.2f%%",
                100.0 * nan_ratio,
                100.0 * float(config.guardrails["max_nan_frac"]),
            )

        # Compute features
        features = compute_sentiment_features(df, config)

        # Score components
        components = score_components(features, config)

        # Aggregate sentiment score
        component_values: Dict[str, float] = {}
        for name in ["social", "news", "reaction"]:
            if name in components and len(components[name]) > 0:
                component_values[name] = float(components[name].iloc[-1])  # Most recent value
            else:
                component_values[name] = 0.0

        sentiment_score = (
            config.weights["social"] * component_values["social"]
            + config.weights["news"] * component_values["news"]
            + config.weights["reaction"] * component_values["reaction"]
        )

        # Ensure score is in [-1, 1]
        sentiment_score = float(np.clip(sentiment_score, -1.0, 1.0))

        # Determine regime label
        if sentiment_score >= config.thresholds["bull"]:
            label: Literal["bull", "bear", "chop"] = "bull"
        elif sentiment_score <= config.thresholds["bear"]:
            label = "bear"
        else:
            label = "chop"

        # Calculate confidence
        component_confidences = _calculate_component_confidence(components, features)
        base_confidence = mean(component_confidences.values()) if component_confidences else 0.0

        # Sample size adjustment
        sample_ratio = min(1.0, n_samples / float(config.guardrails["min_rows"]))
        base_confidence *= sample_ratio

        # Volume signal strength check
        total_volume = 0.0
        for col in ["tw_volume", "rd_volume", "news_volume"]:
            if col in df.columns:
                total_volume += float(df[col].fillna(0.0).iloc[-1]) if len(df) > 0 else 0.0

        if total_volume < float(config.guardrails["min_signal_volume"]):
            base_confidence *= 0.7  # Reduce confidence for low volume

        # Spread penalty from context
        spread_bps_mean = float(context_meta.get("spread_bps_mean", 0.0))
        if spread_bps_mean > 20.0:  # Very high spread
            base_confidence *= 0.9  # Small confidence haircut

        confidence = float(np.clip(base_confidence, 0.0, 1.0))

        # Generate explanation
        explain = _generate_explanation(
            label, sentiment_score, component_values, component_confidences
        )

        # Prepare feature subset for output (stable, small set)
        output_features: Dict[str, float] = {}
        feature_keys = [
            "tw_score_s",
            "rd_score_s",
            "news_score_s",
            "news_dispersion_s",
            "tw_vol_z",
            "rd_vol_z",
            "news_vol_z",
            "ret_5m_s",
            "ret_1h_s",
        ]
        for key in feature_keys:
            if key in features and len(features[key]) > 0:
                output_features[key] = float(features[key].iloc[-1])
            else:
                output_features[key] = 0.0

        # Deterministic latency from context
        latency_ms = (t_end_ms_hint - t_start_ms) if (t_end_ms_hint and t_start_ms) else 0

        # Performance warning
        if latency_ms > config.latency_budget_ms:
            logger.warning(
                "Sentiment analysis exceeded latency budget: %dms > %dms",
                latency_ms,
                config.latency_budget_ms,
            )

        # Stable hash for replay/audit
        audit_payload = {
            "schema_version": "1.0",
            "label": label,
            "confidence": confidence,
            "score": sentiment_score,
            "components": {k: component_values[k] for k in sorted(component_values)},
            "features": {k: output_features[k] for k in sorted(output_features)},
            "n": n_samples,
            "latency_ms": latency_ms,
            "timeframe": timeframe,
        }
        audit_json = json.dumps(audit_payload, sort_keys=True, separators=(",", ":"))
        audit_hash = hashlib.sha256(audit_json.encode("utf-8")).hexdigest()

        # Log results with stable ordering
        logger.info(
            "Sentiment regime: %s (conf=%.2f, score=%.2f, n=%d, latency=%dms, hash=%s) - %s",
            label,
            confidence,
            sentiment_score,
            n_samples,
            latency_ms,
            audit_hash,
            explain,
        )

        logger.debug(
            "Component scores: %s",
            {k: component_values[k] for k in sorted(component_values)},
        )
        logger.debug(
            "Last feature values: %s",
            {k: output_features[k] for k in sorted(output_features)},
        )

        return SentimentRegime(
            label=label,
            confidence=confidence,
            components=component_values,
            features=output_features,
            explain=explain,
            latency_ms=latency_ms,
            n_samples=n_samples,
        )

    except Exception as e:  # pragma: no cover - fail-safe
        latency_ms = (t_end_ms_hint - t_start_ms) if (t_end_ms_hint and t_start_ms) else 0
        error_msg = f"Sentiment analysis error: {str(e)}"
        logger.exception(error_msg)

        # Return safe NOOP result
        return SentimentRegime(
            label="chop",
            confidence=0.0,
            components={"social": 0.0, "news": 0.0, "reaction": 0.0},
            features={},
            explain=f"Error: {str(e)[:50]}...",
            latency_ms=latency_ms,
            n_samples=len(df) if df is not None else 0,
        )


# Self-check for development/testing
if __name__ == "__main__":
    import sys

    # Configure basic logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    logger.info("Running sentiment analyzer self-check...")

    try:
        # Create synthetic test data
        np.random.seed(42)
        n_rows = 300

        test_data = pd.DataFrame(
            {
                "tw_score": np.random.normal(0.1, 0.3, n_rows).clip(-1, 1),
                "tw_volume": np.random.exponential(100, n_rows),
                "rd_score": np.random.normal(0.05, 0.25, n_rows).clip(-1, 1),
                "rd_volume": np.random.exponential(80, n_rows),
                "news_score": np.random.normal(0.15, 0.2, n_rows).clip(-1, 1),
                "news_volume": np.random.exponential(50, n_rows),
                "news_dispersion": np.random.exponential(1.5, n_rows),
                "ret_5m": np.random.normal(0.0, 0.02, n_rows),
                "ret_1h": np.random.normal(0.0, 0.05, n_rows),
                "mentions_btc": np.random.poisson(150, n_rows),
                "mentions_eth": np.random.poisson(100, n_rows),
            }
        )

        # Add timestamp index
        test_data.index = pd.date_range("2025-01-01", periods=n_rows, freq="5T")

        # Test with default configuration
        config = SentimentConfig()

        # Run sentiment detection with deterministic timing
        result = detect_sentiment_regime(
            df=test_data, timeframe="5m", config=config, context_meta={"spread_bps_mean": 8.5, "t_start_ms": 1000, "t_end_ms": 1150}
        )

        # Validate result
        assert result.label in ["bull", "bear", "chop"]
        assert 0.0 <= result.confidence <= 1.0
        assert len(result.components) == 3
        assert all(k in result.components for k in ["social", "news", "reaction"])
        assert all(-1.0 <= v <= 1.0 for v in result.components.values())
        assert result.latency_ms == 150
        assert result.n_samples == n_rows

        logger.info(
            "✓ Self-check passed! Result: %s (confidence=%.2f, latency=%dms, features=%d)",
            result.label,
            result.confidence,
            result.latency_ms,
            len(result.features),
        )

        # Test JSON serialization round-trip
        json_str = result.model_dump_json()
        result_copy = SentimentRegime.model_validate_json(json_str)
        assert result == result_copy
        logger.info("✓ JSON serialization test passed!")

        # Test empty DataFrame handling (deterministic latency stays 0)
        empty_result = detect_sentiment_regime(df=pd.DataFrame(), timeframe="1m", config=config, context_meta={"t_start_ms": 0, "t_end_ms": 0})
        assert empty_result.label == "chop"
        assert empty_result.confidence == 0.0
        assert empty_result.latency_ms == 0
        logger.info("✓ Empty DataFrame handling test passed!")

        sys.exit(0)

    except Exception as e:
        logger.error("❌ Self-check failed: %s", e)
        sys.exit(1)
