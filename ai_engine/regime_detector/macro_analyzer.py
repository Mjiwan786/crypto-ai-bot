"""
ai_engine/regime_detector/macro_analyzer.py

Production-ready macro/derivatives regime component for Crypto AI Bot.
Ingests precomputed local inputs covering USD liquidity, BTC derivatives,
and crypto-specific macro factors. Outputs macro-based regime assessment
with explainability and strict guardrails.

Core Methodology:
1. USD Liquidity: DXY inverse (z-scored), Treasury yield pressure
2. Crypto Derivatives: Funding rates, futures basis, open interest trends
3. Risk Appetite: VIX inverse, BTC dominance changes
4. Flow Analysis: Stablecoin market cap and inflow patterns

Example Usage:
    >>> import pandas as pd
    >>> from ai_engine.regime_detector.macro_analyzer import detect_macro_regime, MacroConfig
    >>>
    >>> config = MacroConfig()
    >>> df = pd.DataFrame({...})
    >>> regime = detect_macro_regime(df, "1h", config, context_meta={"t_start_ms": 0, "t_end_ms": 0})
    >>> regime.label, regime.confidence
"""

from __future__ import annotations

import logging
import re
import statistics
from functools import lru_cache
from typing import Dict, Literal, Optional, Union

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field, ConfigDict, field_serializer, field_validator

logger = logging.getLogger(__name__)

# Type aliases for clarity
RegimeLabel = Literal["bull", "bear", "chop"]


class MacroConfig(BaseModel):
    """Configuration for macro regime detection with validation."""

    # Contracts: frozen, forbid extras
    model_config = ConfigDict(frozen=True, extra="forbid")

    # Explicit schema version for contracts
    schema_version: Literal["1.0"] = Field(
        default="1.0", description="Schema version for MacroConfig"
    )

    lookbacks: Dict[str, int] = Field(
        default={
            "short": 14,
            "medium": 30,
            "long": 90,
        },
        description="Lookback periods for different time horizons",
    )

    weights: Dict[str, float] = Field(
        default={
            "usd_liquidity": 0.25,
            "crypto_derivs": 0.35,
            "risk_appetite": 0.25,
            "flow": 0.15,
        },
        description="Component weights for final macro score",
    )

    thresholds: Dict[str, float] = Field(
        default={"bull": 0.55, "bear": -0.55, "chop_abs": 0.25},
        description="Regime classification thresholds",
    )

    guardrails: Dict[str, Union[int, float]] = Field(
        default={"min_rows": 200, "max_nan_frac": 0.10},
        description="Data quality guardrails",
    )

    latency_budget_ms: int = Field(
        default=250, description="Maximum allowed processing time in milliseconds"
    )

    scaling: Dict[str, float] = Field(
        default={
            "basis_clip": 20.0,
            "funding_clip": 15.0,
            "dxy_z_clip": 3.0,
            "rate_z_clip": 3.0,
        },
        description="Clipping values for robust normalization",
    )

    @field_validator("weights")
    @classmethod
    def validate_weights_sum(cls, v: Dict[str, float]) -> Dict[str, float]:
        """Ensure weights sum to approximately 1.0."""
        total = sum(v.values())
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Weights must sum to ~1.0, got {total:.3f}")
        return v

    @field_validator("thresholds")
    @classmethod
    def validate_thresholds(cls, v: Dict[str, float]) -> Dict[str, float]:
        """Validate threshold logic."""
        if v["bull"] <= v["chop_abs"]:
            raise ValueError("Bull threshold must be > chop_abs threshold")
        if v["bear"] >= -v["chop_abs"]:
            raise ValueError("Bear threshold must be < -chop_abs threshold")
        return v

    @field_validator("lookbacks")
    @classmethod
    def validate_lookbacks(cls, v: Dict[str, int]) -> Dict[str, int]:
        """Ensure lookback periods are positive and ordered."""
        required_keys = {"short", "medium", "long"}
        missing = required_keys - v.keys()
        if missing:
            raise ValueError(f"Missing required lookback keys: {missing}")
        if not (0 < v["short"] < v["medium"] < v["long"]):
            raise ValueError("Lookbacks must satisfy: 0 < short < medium < long")
        return v


class MacroRegime(BaseModel):
    """Macro regime detection output with explainability."""

    # Contracts: frozen, forbid extras
    model_config = ConfigDict(frozen=True, extra="forbid")

    # Explicit schema version for contracts
    schema_version: Literal["1.0"] = Field(
        default="1.0", description="Schema version for MacroRegime"
    )

    label: RegimeLabel = Field(description="Detected regime classification")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score [0,1]")
    components: Dict[str, float] = Field(description="Component scores [-1,1]")
    features: Dict[str, float] = Field(description="Latest computed indicators")
    explain: str = Field(description="Single-line reason summary")
    latency_ms: int = Field(ge=0, description="Processing time in milliseconds")
    n_samples: int = Field(ge=0, description="Number of data points analyzed")

    @field_serializer("components", "features")
    def serialize_dicts(self, value: Dict[str, float]) -> Dict[str, float]:
        """Ensure deterministic serialization by sorting keys."""
        return {k: value[k] for k in sorted(value.keys())}


@lru_cache(maxsize=1)
def _validate_timeframe(timeframe: str) -> bool:
    """Validate timeframe format with caching."""
    pattern = r"^\d+[mhdw]$"
    return bool(re.match(pattern, timeframe.lower()))


def _timeframe_scales(timeframe: str) -> Dict[str, float]:
    """
    Compute timeframe-aware scaling factors.
    - funding_scale: relative to 8 hours (positive funding over longer TF should weigh more)
    - basis_scale: relative to 1 year (annualized basis scaled by TF length in days)
    """
    m = re.match(r"^(\d+)([mhdw])$", timeframe.lower())
    if not m:
        return {"funding_scale": 1.0, "basis_scale": 1.0}
    n, unit = int(m.group(1)), m.group(2)
    minutes = {"m": 1, "h": 60, "d": 60 * 24, "w": 60 * 24 * 7}[unit] * n
    hours = minutes / 60.0
    days = hours / 24.0
    return {"funding_scale": hours / 8.0, "basis_scale": days / 365.0}


def _z(series: pd.Series, window: int, clip: float) -> pd.Series:
    """Compute robust z-scores with rolling statistics and clipping (vectorized)."""
    if len(series) < 2:
        return pd.Series(0.0, index=series.index)

    w = min(window, len(series))
    rolling_mean = series.rolling(window=w, min_periods=1).mean()
    rolling_std = series.rolling(window=w, min_periods=1).std()

    # Handle zero/near-zero standard deviation
    rolling_std = rolling_std.fillna(1.0)
    rolling_std = rolling_std.where(rolling_std > 1e-8, 1.0)

    z_scores = (series - rolling_mean) / rolling_std
    return z_scores.clip(-clip, clip)


def _tanh_clip(z_series: pd.Series) -> pd.Series:
    """Vectorized tanh normalization to clip z-scores to [-1, 1] range."""
    arr = z_series.to_numpy(copy=False)
    out = np.tanh(np.where(np.isnan(arr), 0.0, arr))
    return pd.Series(out, index=z_series.index)


def _safe_log_transform(series: pd.Series, min_val: float = 1e-9) -> pd.Series:
    """Safe logarithmic transformation with minimum value protection."""
    return np.log(series.clip(lower=min_val))


def _compute_component_confidence(data: Dict[str, pd.Series]) -> float:
    """Compute confidence based on data availability within component."""
    if not data:
        return 0.0
    total_points = 0
    valid_points = 0
    for s in data.values():
        if not s.empty:
            total_points += len(s)
            valid_points += s.notna().sum()
    if total_points == 0:
        return 0.0
    return float(valid_points / total_points)


def compute_macro_features(
    df: pd.DataFrame, cfg: MacroConfig, timeframe: Optional[str] = None
) -> Dict[str, pd.Series]:
    """
    Compute macro indicators from input DataFrame (vectorized, O(N)).

    Returns:
        dict[str, pd.Series]: key->feature series (aligned to df.index)
    """
    features: Dict[str, pd.Series] = {}

    # Ensure time index when timestamp column exists (pure transformation only)
    if "timestamp" in df.columns and not isinstance(df.index, pd.DatetimeIndex):
        if np.issubdtype(df["timestamp"].dtype, np.integer):
            df.index = pd.to_datetime(df["timestamp"], unit="ms")
        else:
            df.index = pd.to_datetime(df["timestamp"])

    # USD Liquidity components
    if "dxy" in df.columns:
        features["dxy_z"] = _z(df["dxy"], cfg.lookbacks["medium"], cfg.scaling["dxy_z_clip"])

    if "us10y" in df.columns:
        features["us10y_z"] = _z(df["us10y"], cfg.lookbacks["medium"], cfg.scaling["rate_z_clip"])

    if "move_index" in df.columns:
        features["move_z"] = _z(df["move_index"], cfg.lookbacks["short"], 2.5)

    # Crypto Derivatives components
    if "funding_8h" in df.columns:
        # Annualized %; clip then normalize to [-1,1]-ish
        funding_clipped = df["funding_8h"].clip(
            -cfg.scaling["funding_clip"], cfg.scaling["funding_clip"]
        )
        features["funding_scaled"] = funding_clipped / cfg.scaling["funding_clip"]

    if "futures_basis_annual" in df.columns:
        # Annualized %; clip then normalize
        basis_clipped = df["futures_basis_annual"].clip(
            -cfg.scaling["basis_clip"], cfg.scaling["basis_clip"]
        )
        features["basis_scaled"] = basis_clipped / cfg.scaling["basis_clip"]

    if "open_interest_usd" in df.columns:
        oi_pct_change = df["open_interest_usd"].pct_change(periods=cfg.lookbacks["short"])
        features["oi_roc_z"] = _z(oi_pct_change, cfg.lookbacks["medium"], 2.0)

    if "oi_change_24h" in df.columns:
        features["oi_change_scaled"] = (df["oi_change_24h"] / 50.0).clip(-5.0, 5.0)

    # Risk Appetite components
    if "btc_dominance" in df.columns:
        dom_change = df["btc_dominance"].pct_change(periods=cfg.lookbacks["short"])
        features["dom_change_z"] = _z(dom_change, cfg.lookbacks["medium"], 2.0)

    if "vix" in df.columns:
        features["vix_z"] = _z(df["vix"], cfg.lookbacks["short"], 2.5)

    # Flow components
    if "stablecoin_mcap" in df.columns:
        mcap_log = _safe_log_transform(df["stablecoin_mcap"])
        # Long horizon change; keep as pct_change on log (monotone to log-return)
        mcap_growth = mcap_log.pct_change(periods=cfg.lookbacks["long"])
        features["stable_mcap_growth_z"] = _z(mcap_growth, cfg.lookbacks["medium"], 2.0)

    if "stablecoin_inflow_7d" in df.columns:
        inflow_scaled = (df["stablecoin_inflow_7d"] / 1e9).clip(-5, 5)
        features["stable_inflow_scaled"] = inflow_scaled

    # Timeframe-aware scaling (funding/basis)
    if timeframe and _validate_timeframe(timeframe):
        scales = _timeframe_scales(timeframe)
        if "funding_scaled" in features:
            features["funding_scaled"] = features["funding_scaled"] * scales["funding_scale"]
        if "basis_scaled" in features:
            features["basis_scaled"] = features["basis_scaled"] * scales["basis_scale"]

    return features


def score_components(feat: Dict[str, pd.Series], cfg: MacroConfig) -> Dict[str, pd.Series]:
    """
    Score individual component families from computed features.

    Returns:
        dict[str, pd.Series]: component score series in [-1, 1]
    """
    components: Dict[str, pd.Series] = {}

    # USD Liquidity: negative DXY (stronger USD = less liquidity), negative rates, negative MOVE
    usd_liq_parts = []
    usd_liq_data: Dict[str, pd.Series] = {}

    if "dxy_z" in feat:
        dxy_contrib = _tanh_clip(-feat["dxy_z"])  # Negative: stronger USD = less liquidity
        usd_liq_parts.append(dxy_contrib * 0.6)  # 60% weight to DXY
        usd_liq_data["dxy"] = feat["dxy_z"]

    if "us10y_z" in feat:
        rate_contrib = _tanh_clip(-feat["us10y_z"])  # Negative: higher rates = less risk-on
        weight = 0.4 if usd_liq_parts else 0.7
        usd_liq_parts.append(rate_contrib * weight)
        usd_liq_data["rates"] = feat["us10y_z"]

    if "move_z" in feat:
        move_contrib = _tanh_clip(-feat["move_z"])  # Negative: higher vol = less liquidity
        weight = 0.1 if len(usd_liq_parts) >= 2 else 0.3
        usd_liq_parts.append(move_contrib * weight)
        usd_liq_data["move"] = feat["move_z"]

    if usd_liq_parts:
        components["usd_liquidity"] = sum(usd_liq_parts)
    else:
        ref_series = next(iter(feat.values())) if feat else pd.Series([0.0])
        components["usd_liquidity"] = pd.Series(0.0, index=ref_series.index)

    # Crypto Derivatives: positive funding, positive basis, positive OI trends
    crypto_deriv_parts = []
    crypto_deriv_data: Dict[str, pd.Series] = {}

    if "funding_scaled" in feat:
        funding_contrib = _tanh_clip(feat["funding_scaled"] * 2.0)  # Amplify for sensitivity
        crypto_deriv_parts.append(funding_contrib * 0.4)  # 40% weight to funding
        crypto_deriv_data["funding"] = feat["funding_scaled"]

    if "basis_scaled" in feat:
        basis_contrib = _tanh_clip(feat["basis_scaled"] * 1.5)
        weight = 0.35 if crypto_deriv_parts else 0.5
        crypto_deriv_parts.append(basis_contrib * weight)
        crypto_deriv_data["basis"] = feat["basis_scaled"]

    if "oi_roc_z" in feat:
        oi_contrib = _tanh_clip(feat["oi_roc_z"])
        weight = 0.15 if len(crypto_deriv_parts) >= 2 else 0.3
        crypto_deriv_parts.append(oi_contrib * weight)
        crypto_deriv_data["oi_roc"] = feat["oi_roc_z"]

    if "oi_change_scaled" in feat:
        oi_change_contrib = _tanh_clip(feat["oi_change_scaled"])
        weight = 0.1 if len(crypto_deriv_parts) >= 2 else 0.2
        crypto_deriv_parts.append(oi_change_contrib * weight)
        crypto_deriv_data["oi_change"] = feat["oi_change_scaled"]

    if crypto_deriv_parts:
        components["crypto_derivs"] = sum(crypto_deriv_parts)
    else:
        ref_series = next(iter(feat.values())) if feat else pd.Series([0.0])
        components["crypto_derivs"] = pd.Series(0.0, index=ref_series.index)

    # Risk Appetite: negative VIX, modest positive BTC dominance change
    risk_app_parts = []
    risk_app_data: Dict[str, pd.Series] = {}

    if "vix_z" in feat:
        vix_contrib = _tanh_clip(-feat["vix_z"])  # Negative: lower VIX = higher risk appetite
        risk_app_parts.append(vix_contrib * 0.7)  # 70% weight to VIX
        risk_app_data["vix"] = feat["vix_z"]

    if "dom_change_z" in feat:
        dom_contrib = _tanh_clip(feat["dom_change_z"] * 0.5)  # Reduced sensitivity
        weight = 0.3 if risk_app_parts else 0.6
        risk_app_parts.append(dom_contrib * weight)
        risk_app_data["btc_dom"] = feat["dom_change_z"]

    if risk_app_parts:
        components["risk_appetite"] = sum(risk_app_parts)
    else:
        ref_series = next(iter(feat.values())) if feat else pd.Series([0.0])
        components["risk_appetite"] = pd.Series(0.0, index=ref_series.index)

    # Flow: positive stablecoin growth and inflows
    flow_parts = []
    flow_data: Dict[str, pd.Series] = {}

    if "stable_mcap_growth_z" in feat:
        mcap_contrib = _tanh_clip(feat["stable_mcap_growth_z"])
        flow_parts.append(mcap_contrib * 0.6)  # 60% weight to market cap growth
        flow_data["mcap_growth"] = feat["stable_mcap_growth_z"]

    if "stable_inflow_scaled" in feat:
        inflow_contrib = _tanh_clip(feat["stable_inflow_scaled"])
        weight = 0.4 if flow_parts else 0.8
        flow_parts.append(inflow_contrib * weight)
        flow_data["inflows"] = feat["stable_inflow_scaled"]

    if flow_parts:
        components["flow"] = sum(flow_parts)
    else:
        ref_series = next(iter(feat.values())) if feat else pd.Series([0.0])
        components["flow"] = pd.Series(0.0, index=ref_series.index)

    # Stash per-component raw data for confidence computation
    components["_component_data"] = {
        "usd_liquidity": usd_liq_data,
        "crypto_derivs": crypto_deriv_data,
        "risk_appetite": risk_app_data,
        "flow": flow_data,
    }

    return components


def detect_macro_regime(
    df: pd.DataFrame,
    timeframe: str,
    config: Union[MacroConfig, dict],
    context_meta: Optional[dict] = None,
) -> MacroRegime:
    """
    Detect macro regime from input DataFrame (pure, deterministic).

    Args:
        df: Input data with macro indicators.
        timeframe: Timeframe string (e.g., "1h", "5m"). Must match ^\\d+[mhdw]$.
        config: MacroConfig instance or dict of its fields.
        context_meta: Optional dict with deterministic timing metadata:
            - t_start_ms: int (analysis start)
            - t_end_ms: int (analysis end)
            - spread_bps_mean: Optional[float] (confidence haircut when wide)

    Returns:
        MacroRegime: classification, confidence, components, features, explain, latency, n_samples
    """
    if not _validate_timeframe(timeframe):
        raise ValueError(f"Invalid timeframe format: {timeframe}")

    cfg = config if isinstance(config, MacroConfig) else MacroConfig(**config)
    context_meta = context_meta or {}
    t_start_ms = int(context_meta.get("t_start_ms", 0))
    t_end_ms_hint = int(context_meta.get("t_end_ms", 0))

    logger.debug(
        "Starting macro regime detection for %s rows, timeframe %s",
        len(df),
        timeframe,
    )

    try:
        # Data quality checks (informational; do not break determinism)
        n_rows = len(df)
        if n_rows < cfg.guardrails["min_rows"]:
            logger.warning(
                "Insufficient data: %s < %s min rows", n_rows, cfg.guardrails["min_rows"]
            )

        nan_fraction = (
            float(df.isnull().sum().sum()) / float(len(df) * max(len(df.columns), 1))
            if n_rows > 0
            else 1.0
        )
        if nan_fraction > cfg.guardrails["max_nan_frac"]:
            logger.warning(
                "High NaN fraction: %.2f > %.2f",
                nan_fraction,
                cfg.guardrails["max_nan_frac"],
            )

        # Compute features (vectorized) with timeframe-aware scaling inside
        features = compute_macro_features(df, cfg, timeframe)
        logger.debug("Computed %d macro features", len(features))

        # Score components over time series
        component_scores = score_components(features, cfg)

        # Extract latest values for final aggregation
        latest_components: Dict[str, float] = {}
        component_confidences: Dict[str, float] = {}

        for comp_name, comp_series in component_scores.items():
            if comp_name.startswith("_"):  # Skip metadata stash
                continue

            if not comp_series.empty:
                last_valid_idx = comp_series.last_valid_index()
                latest_components[comp_name] = (
                    float(comp_series.loc[last_valid_idx]) if last_valid_idx is not None else 0.0
                )
                comp_meta = component_scores.get("_component_data", {})
                if comp_name in comp_meta:
                    component_confidences[comp_name] = _compute_component_confidence(
                        comp_meta[comp_name]
                    )
                else:
                    component_confidences[comp_name] = float(comp_series.notna().mean())
            else:
                latest_components[comp_name] = 0.0
                component_confidences[comp_name] = 0.0

        # Aggregate macro score using weights (deterministic)
        macro_score = 0.0
        total_weight = 0.0
        for comp_name, weight in cfg.weights.items():
            if comp_name in latest_components:
                macro_score += latest_components[comp_name] * weight
                total_weight += weight

        if total_weight > 0 and abs(total_weight - 1.0) > 1e-6:
            macro_score = macro_score / total_weight

        # Determine regime label with NOOP fallback path
        thresholds = cfg.thresholds
        if abs(macro_score) < thresholds["chop_abs"]:
            label: RegimeLabel = "chop"
        elif macro_score >= thresholds["bull"]:
            label = "bull"
        elif macro_score <= thresholds["bear"]:
            label = "bear"
        else:
            label = "bull" if macro_score > 0 else "bear"

        # Confidence calculation with graceful degradation
        base_confidence = (
            statistics.mean(component_confidences.values()) if component_confidences else 0.5
        )
        data_quality_factor = min(1.0, n_rows / float(cfg.guardrails["min_rows"]))
        spread_factor = 1.0
        if "spread_bps_mean" in context_meta:
            spread_bps = float(context_meta["spread_bps_mean"])
            if spread_bps > 20.0:
                spread_factor = max(0.8, 1.0 - (spread_bps - 20.0) / 200.0)

        confidence = max(0.0, min(1.0, base_confidence * data_quality_factor * spread_factor))

        # Latest feature snapshot (deterministic order handled by serializer)
        latest_features: Dict[str, float] = {}
        for feat_name, feat_series in features.items():
            if not feat_series.empty:
                last_valid_idx = feat_series.last_valid_index()
                latest_features[feat_name] = (
                    float(feat_series.loc[last_valid_idx]) if last_valid_idx is not None else 0.0
                )
            else:
                latest_features[feat_name] = 0.0

        # Explainability (single line)
        if latest_components:
            dominant_component = max(latest_components.items(), key=lambda x: abs(x[1]))[0]
            dominant_value = latest_components[dominant_component]
        else:
            dominant_component, dominant_value = "none", 0.0
        explain = f"{label.upper()} regime (score={macro_score:.2f}) driven by {dominant_component}({dominant_value:+.2f})"

        # Deterministic latency (context-derived only)
        latency_ms = t_end_ms_hint - t_start_ms if (t_end_ms_hint and t_start_ms) else 0
        if latency_ms > cfg.latency_budget_ms:
            logger.warning(
                "Latency budget exceeded: %sms > %sms", latency_ms, cfg.latency_budget_ms
            )

        # Debug component details
        for comp_name, comp_value in latest_components.items():
            logger.debug(
                "Component %s: %.3f (conf: %.2f)",
                comp_name,
                comp_value,
                component_confidences.get(comp_name, 0.0),
            )

        return MacroRegime(
            label=label,
            confidence=confidence,
            components=latest_components,
            features=latest_features,
            explain=explain,
            latency_ms=latency_ms,
            n_samples=n_rows,
        )

    except Exception as e:  # pragma: no cover - fail-safe path
        latency_ms = t_end_ms_hint - t_start_ms if (t_end_ms_hint and t_start_ms) else 0
        logger.exception("Macro regime detection failed after %sms: %s", latency_ms, e)
        # Safe fallback (NOOP/chop)
        return MacroRegime(
            label="chop",
            confidence=0.0,
            components={
                "usd_liquidity": 0.0,
                "crypto_derivs": 0.0,
                "risk_appetite": 0.0,
                "flow": 0.0,
            },
            features={},
            explain=f"Error in macro analysis: {str(e)[:50]}",
            latency_ms=latency_ms,
            n_samples=len(df) if not df.empty else 0,
        )
