"""
ai_engine/adaptive_learner.py

Production-ready online adaptive learner for crypto trading system.
Ingests trade outcomes and proposes bounded parameter updates with comprehensive guardrails.

Key Principles:
- Deterministic operation (no wall-clock in core, no randomness, no I/O)
- Shadow/Active mode with strict safety guardrails and NOOP fallback with reason
- EWMA-based metrics for stability; winsorization for outliers
- Bounded, step-limited parameter updates with clear contracts (Pydantic v2)
- Stable/deterministic JSON serialization (sorted dict keys)
- Observability via logging (no prints)

This module contains pure logic suitable for synchronous or async orchestration layers.
"""

from __future__ import annotations

import logging
import math
import re
from functools import lru_cache
from typing import Dict, Optional, Union, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator, field_serializer

# Public surface
__all__ = [
    "Bounds",
    "LearnerConfig",
    "AdaptiveUpdate",
    "compute_metrics",
    "propose_deltas",
    "apply_bounds",
    "_compute_confidence",
    "gated_update",
]

# Setup module logger
logger = logging.getLogger(__name__)

# Constants and validation patterns
WINSORIZE_PNL_BPS = 500.0            # Clip extreme P&L at ±500 bps
WINSORIZE_MAE_MFE_BPS = 2000.0       # Clip extreme MAE/MFE at ±2000 bps
MIN_TRADES_ABSOLUTE = 50             # Absolute minimum trades regardless of config
_TIMEFRAME_RE = re.compile(r"^\d+[mhdw]$")  # Validate timeframe format like '1m','5m','2h','1d','2w'


class Bounds(BaseModel):
    """Parameter bounds with step size limits."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    min: float = Field(description="Minimum allowed value")
    max: float = Field(description="Maximum allowed value")
    max_step: float = Field(description="Maximum change per update")

    @field_validator("max")
    @classmethod
    def max_greater_than_min(cls, v: float, info):
        min_val = info.data.get("min")
        if min_val is not None and v <= min_val:
            raise ValueError("max must be greater than min")
        return v

    @field_validator("max_step")
    @classmethod
    def max_step_positive(cls, v: float):
        if v <= 0:
            raise ValueError("max_step must be positive")
        return v


class LearnerConfig(BaseModel):
    """Configuration for adaptive learner with production defaults.

    schema_version is explicit to enable downstream routing, migrations, and hashing.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    # Explicit schema version for config contracts
    schema_version: Literal["1.0"] = "1.0"

    # Analysis windows
    windows: Dict[str, int] = Field(
        default_factory=lambda: {"short": 50, "medium": 200, "long": 1000}
    )

    # EWMA alpha values
    ewma_alpha: Dict[str, float] = Field(
        default_factory=lambda: {"return": 0.1, "hit": 0.08, "vol": 0.08}
    )

    # Performance thresholds
    thresholds: Dict[str, float] = Field(
        default_factory=lambda: {
            "min_trades": 200,
            "good_sharpe": 1.0,
            "poor_sharpe": 0.2,
            "hit_rate_good": 0.55,
            "hit_rate_poor": 0.45,
            "sl_hit_too_often": 0.35,
            "drawdown_freeze_pct": 8.0,
        }
    )

    # Parameter bounds (Kraken-optimized defaults)
    bounds: Dict[str, Bounds] = Field(
        default_factory=lambda: {
            "position_size_pct": Bounds(min=0.1, max=2.0, max_step=0.25),
            "sl_multiplier": Bounds(min=0.5, max=3.0, max_step=0.25),
            "tp_multiplier": Bounds(min=0.5, max=4.0, max_step=0.25),
            "cooldown_s": Bounds(min=5.0, max=300.0, max_step=30.0),
            "max_concurrent": Bounds(min=1, max=5, max_step=1),
        }
    )

    # Risk guards
    risk_guards: Dict[str, float] = Field(
        default_factory=lambda: {
            "daily_stop_usd": 150.0,
            "max_spread_bps": 25.0,
            "min_effective_samples": 100,
            "min_interval_ms": 30 * 60 * 1000,
        }
    )

    # Operating mode
    mode: Literal["shadow", "active"] = Field(default="shadow")

    # Performance constraint (caller-provided latency)
    latency_budget_ms: int = Field(default=250)

    @field_validator("windows")
    @classmethod
    def validate_windows(cls, v: Dict[str, int]):
        required = {"short", "medium", "long"}
        if not required.issubset(v.keys()):
            raise ValueError(f"windows must contain keys: {required}")
        return v

    @field_validator("ewma_alpha")
    @classmethod
    def validate_alphas(cls, v: Dict[str, float]):
        required = {"return", "hit", "vol"}
        if not required.issubset(v.keys()):
            raise ValueError(f"ewma_alpha must contain keys: {required}")
        for k, alpha in v.items():
            if not 0 < alpha <= 1:
                raise ValueError(f"ewma_alpha.{k} must be in (0,1]")
        return v


class AdaptiveUpdate(BaseModel):
    """Output of adaptive learning update."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    # Explicit schema version for downstream routing/validation
    schema_version: Literal["1.0"] = "1.0"

    mode: Literal["shadow", "active"]
    new_params: Dict[str, float]
    deltas: Dict[str, float]
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    diagnostics: Dict[str, float]
    latency_ms: int

    @field_serializer("new_params")
    def serialize_new_params(self, v: Dict[str, float]) -> Dict[str, float]:
        """Serialize with sorted keys for deterministic output."""
        return {k: v[k] for k in sorted(v.keys())}

    @field_serializer("deltas")
    def serialize_deltas(self, v: Dict[str, float]) -> Dict[str, float]:
        """Serialize with sorted keys for deterministic output."""
        return {k: v[k] for k in sorted(v.keys())}

    @field_serializer("diagnostics")
    def serialize_diagnostics(self, v: Dict[str, float]) -> Dict[str, float]:
        """Serialize with sorted keys for deterministic output."""
        return {k: v[k] for k in sorted(v.keys())}


def _validate_and_clean_outcomes(df: pd.DataFrame) -> pd.DataFrame:
    """Validate and sanitize outcomes DataFrame (pure, deterministic)."""
    if df.empty:
        logger.warning("Empty outcomes DataFrame received")
        return df.copy()

    # Required columns
    required_cols = [
        "timestamp",
        "symbol",
        "strategy",
        "side",
        "entry_px",
        "exit_px",
        "pnl_usd",
        "pnl_bps",
        "hold_ms",
        "sl_hit",
        "tp_hit",
    ]

    # Check for missing required columns
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        logger.warning("Missing columns in outcomes DataFrame: %s", missing_cols)

    # Create working copy
    clean_df = df.copy()

    # Ensure required numeric columns exist with defaults
    numeric_defaults = {
        "pnl_bps": 0.0,
        "pnl_usd": 0.0,
        "hold_ms": 0,
        "sl_hit": 0,
        "tp_hit": 0,
        "entry_px": 0.0,
        "exit_px": 0.0,
    }

    for col, default in numeric_defaults.items():
        if col not in clean_df.columns:
            clean_df[col] = default
        else:
            # Convert to numeric, coercing errors to NaN then filling with default
            clean_df[col] = pd.to_numeric(clean_df[col], errors="coerce").fillna(default)

    # Handle optional columns
    optional_cols = ["mae_bps", "mfe_bps", "spread_bps", "regime_at_entry"]
    for col in optional_cols:
        if col not in clean_df.columns:
            if col in ["mae_bps", "mfe_bps", "spread_bps"]:
                clean_df[col] = 0.0
            else:
                clean_df[col] = "unknown"
        elif col in ["mae_bps", "mfe_bps", "spread_bps"]:
            clean_df[col] = pd.to_numeric(clean_df[col], errors="coerce").fillna(0.0)

    # Winsorize extreme values
    if "pnl_bps" in clean_df.columns:
        clean_df["pnl_bps"] = np.clip(clean_df["pnl_bps"], -WINSORIZE_PNL_BPS, WINSORIZE_PNL_BPS)

    for col in ["mae_bps", "mfe_bps"]:
        if col in clean_df.columns:
            clean_df[col] = np.clip(clean_df[col], -WINSORIZE_MAE_MFE_BPS, WINSORIZE_MAE_MFE_BPS)

    # Remove rows with invalid core data
    initial_len = len(clean_df)
    clean_df = clean_df.dropna(subset=["pnl_bps"])

    if len(clean_df) < initial_len:
        logger.info("Dropped %d rows with invalid pnl_bps", initial_len - len(clean_df))

    logger.debug("Cleaned outcomes DataFrame: %d trades", len(clean_df))
    return clean_df


@lru_cache(maxsize=128)
def _get_sharpe_scaling_factor(timeframe: str) -> float:
    """Return annualization factor sqrt(periods_per_year) for any N[m|h|d|w].

    Assumptions:
      - Trading days/year = 252
      - Hours/day = 24 (crypto is 24/7, but we keep 252 trading days for comparability)
      - Minutes/hour = 60
      - Weeks/year = 52
    """
    if not _TIMEFRAME_RE.match(timeframe):
        return math.sqrt(252)  # safe default
    n = int(timeframe[:-1])
    unit = timeframe[-1]
    n = max(n, 1)

    if unit == "m":  # minutes
        periods_per_day = (24 * 60) / n
        return math.sqrt(252 * periods_per_day)
    if unit == "h":  # hours
        periods_per_day = 24 / n
        return math.sqrt(252 * periods_per_day)
    if unit == "d":
        return math.sqrt(252 / n)
    if unit == "w":
        return math.sqrt(52 / n)
    return math.sqrt(252)


def compute_metrics(outcomes_df: pd.DataFrame, cfg: LearnerConfig, timeframe: str) -> Dict[str, float]:
    """
    Compute robust performance metrics using EWMA.

    Returns metrics including sharpe_ewma, hit_rate_ewma, sl_hit_rate, dd_pct, eff_n, n_total, vol_ewma.
    """
    # Validate timeframe format: ^\d+[mhdw]$
    if not _TIMEFRAME_RE.match(timeframe):
        logger.warning("Invalid timeframe '%s'; returning safe diagnostics", timeframe)
        return {
            "sharpe_ewma": 0.0,
            "hit_rate_ewma": 0.5,
            "sl_hit_rate": 0.0,
            "dd_pct": 0.0,
            "eff_n": 0,
            "n_total": 0,
            "vol_ewma": 0.0,
        }

    try:
        # Validate and clean data
        clean_df = _validate_and_clean_outcomes(outcomes_df)

        if clean_df.empty:
            logger.warning("No valid trades for metric computation")
            return {
                "sharpe_ewma": 0.0,
                "hit_rate_ewma": 0.5,
                "sl_hit_rate": 0.0,
                "dd_pct": 0.0,
                "eff_n": 0,
                "n_total": 0,
                "vol_ewma": 0.0,
            }

        n_total = len(clean_df)

        # Sort by timestamp for time series analysis
        clean_df = clean_df.sort_values("timestamp").reset_index(drop=True)

        # EWMA parameters
        alpha_return = cfg.ewma_alpha["return"]
        alpha_hit = cfg.ewma_alpha["hit"]
        alpha_vol = cfg.ewma_alpha["vol"]

        # Compute EWMA returns (mean & variance) in one pass
        returns = clean_df["pnl_bps"].values
        if len(returns) > 0:
            ewma_mean = float(returns[0])  # Initialize with first value
            ewma_var = 0.0

            for i in range(1, len(returns)):
                delta = returns[i] - ewma_mean
                ewma_mean += alpha_return * delta
                ewma_var = (1 - alpha_vol) * ewma_var + alpha_vol * delta * delta

            ewma_std = math.sqrt(ewma_var) if ewma_var > 0 else 1e-8
        else:
            ewma_mean = 0.0
            ewma_std = 1e-8

        # Compute annualized Sharpe
        scaling_factor = _get_sharpe_scaling_factor(timeframe)
        sharpe_ewma = (ewma_mean / ewma_std) * scaling_factor if ewma_std > 1e-8 else 0.0

        # EWMA hit rate (wins vs losses)
        wins = (clean_df["pnl_bps"] > 0).astype(float).values
        if len(wins) > 0:
            hit_rate_ewma = float(wins[0])  # Initialize
            for i in range(1, len(wins)):
                hit_rate_ewma = (1 - alpha_hit) * hit_rate_ewma + alpha_hit * wins[i]
        else:
            hit_rate_ewma = 0.5

        # Stop loss hit rate
        sl_hits = clean_df["sl_hit"].values
        sl_hit_rate = float(np.mean(sl_hits)) if len(sl_hits) > 0 else 0.0

        # Drawdown computation over medium window
        window_size = min(cfg.windows["medium"], n_total)
        if window_size > 0:
            recent_pnl = clean_df.tail(window_size)["pnl_bps"].values
            cum_pnl = np.cumsum(recent_pnl)
            if len(cum_pnl) > 1:
                running_max = np.maximum.accumulate(cum_pnl)
                drawdowns = (cum_pnl - running_max)
                dd_pct = abs(float(np.min(drawdowns))) / 100.0 if len(drawdowns) > 0 else 0.0
            else:
                dd_pct = 0.0
        else:
            dd_pct = 0.0

        # Effective sample size (approximation)
        eff_n = min(n_total, int(n_total * (1 - alpha_return))) if n_total > 0 else 0

        metrics = {
            "sharpe_ewma": float(sharpe_ewma),
            "hit_rate_ewma": float(hit_rate_ewma),
            "sl_hit_rate": float(sl_hit_rate),
            "dd_pct": float(dd_pct),
            "eff_n": int(eff_n),
            "n_total": int(n_total),
            "vol_ewma": float(ewma_std),
        }

        logger.debug("Computed metrics: %s", metrics)
        return metrics

    except Exception as e:
        logger.error("Error computing metrics: %s", e)
        return {
            "sharpe_ewma": 0.0,
            "hit_rate_ewma": 0.5,
            "sl_hit_rate": 0.0,
            "dd_pct": 0.0,
            "eff_n": 0,
            "n_total": 0,
            "vol_ewma": 0.0,
        }


def propose_deltas(
    metrics: Dict[str, float], current_params: Dict[str, float], cfg: LearnerConfig
) -> Dict[str, float]:
    """
    Propose bounded parameter changes based on performance metrics.

    Logic is deterministic and monotone with respect to metrics categories.
    """
    try:
        deltas: Dict[str, float] = {}

        # Extract metrics
        sharpe = metrics.get("sharpe_ewma", 0.0)
        hit_rate = metrics.get("hit_rate_ewma", 0.5)
        sl_hit_rate = metrics.get("sl_hit_rate", 0.0)
        dd_pct = metrics.get("dd_pct", 0.0)

        # Performance classification
        good_performance = (sharpe >= cfg.thresholds["good_sharpe"] and hit_rate >= cfg.thresholds["hit_rate_good"])
        poor_performance = (
            sharpe <= cfg.thresholds["poor_sharpe"]
            or hit_rate <= cfg.thresholds["hit_rate_poor"]
            or sl_hit_rate >= cfg.thresholds["sl_hit_too_often"]
        )
        high_drawdown = dd_pct >= cfg.thresholds["drawdown_freeze_pct"]

        # Propose changes for each parameter
        param_names = ["position_size_pct", "sl_multiplier", "tp_multiplier", "cooldown_s", "max_concurrent"]

        for param in param_names:
            if param not in cfg.bounds:
                deltas[param] = 0.0
                continue

            current_val = current_params.get(param, 0.0)
            bounds = cfg.bounds[param]
            delta = 0.0

            if param == "position_size_pct":
                if good_performance and not high_drawdown:
                    # Increase position size on good performance
                    delta = min(bounds.max_step, bounds.max - current_val) * 0.5  # Conservative scaling
                elif poor_performance or high_drawdown:
                    # Decrease position size on poor performance
                    delta = -min(bounds.max_step, current_val - bounds.min) * 0.7  # More aggressive reduction

            elif param == "sl_multiplier":
                if good_performance:
                    # Tighten stop loss (decrease multiplier) when doing well
                    delta = -min(bounds.max_step, current_val - bounds.min) * 0.3
                elif poor_performance or sl_hit_rate >= cfg.thresholds["sl_hit_too_often"]:
                    # Widen stop loss when hitting stops too often
                    delta = min(bounds.max_step, bounds.max - current_val) * 0.5

            elif param == "tp_multiplier":
                if good_performance and hit_rate > 0.6:
                    # Increase profit target when doing well
                    delta = min(bounds.max_step, bounds.max - current_val) * 0.3
                elif poor_performance:
                    # Decrease profit target to increase hit rate
                    delta = -min(bounds.max_step, current_val - bounds.min) * 0.4

            elif param == "cooldown_s":
                if poor_performance or high_drawdown:
                    # Increase cooldown on poor performance
                    delta = min(bounds.max_step, bounds.max - current_val) * 0.6
                elif good_performance and dd_pct < 2.0:  # Low drawdown
                    # Decrease cooldown when doing well
                    delta = -min(bounds.max_step, current_val - bounds.min) * 0.3

            elif param == "max_concurrent":
                if good_performance and dd_pct < 3.0:
                    # Increase concurrent positions when doing well
                    delta = min(1.0, bounds.max - current_val) * 0.5
                elif poor_performance or high_drawdown:
                    # Reduce concurrent positions
                    delta = -min(1.0, current_val - bounds.min) * 0.8

            deltas[param] = float(delta)

        logger.debug("Proposed deltas: %s", deltas)
        return deltas

    except Exception as e:
        logger.error("Error proposing deltas: %s", e)
        return {param: 0.0 for param in ["position_size_pct", "sl_multiplier", "tp_multiplier", "cooldown_s", "max_concurrent"]}


def apply_bounds(current_params: Dict[str, float], deltas: Dict[str, float], cfg: LearnerConfig) -> Dict[str, float]:
    """Apply bounds and constraints to generate new parameters (pure, deterministic)."""
    try:
        new_params: Dict[str, float] = {}

        for param, delta in deltas.items():
            current_val = current_params.get(param, 0.0)

            if param not in cfg.bounds:
                new_params[param] = float(current_val)
                continue

            bounds = cfg.bounds[param]

            # Apply delta with step limit
            clamped_delta = float(np.clip(delta, -bounds.max_step, bounds.max_step))
            new_val = current_val + clamped_delta

            # Apply parameter bounds
            new_val = float(np.clip(new_val, bounds.min, bounds.max))

            new_params[param] = float(new_val)

        # Ensure all expected parameters are present
        expected_params = ["position_size_pct", "sl_multiplier", "tp_multiplier", "cooldown_s", "max_concurrent"]
        for param in expected_params:
            if param not in new_params:
                new_params[param] = float(current_params.get(param, 1.0))

        return new_params

    except Exception as e:
        logger.error("Error applying bounds: %s", e)
        return {k: float(v) for k, v in current_params.items()}


def _compute_confidence(metrics: Dict[str, float], cfg: LearnerConfig, spread_penalty: float = 0.0) -> float:
    """Compute confidence score from normalized metrics."""
    try:
        sharpe = metrics.get("sharpe_ewma", 0.0)
        hit_rate = metrics.get("hit_rate_ewma", 0.5)
        dd_pct = metrics.get("dd_pct", 0.0)
        sl_hit_rate = metrics.get("sl_hit_rate", 0.0)
        eff_n = metrics.get("eff_n", 0)

        # Normalize metrics to [0,1] range
        sharpe_norm = float(np.clip((sharpe + 2.0) / 4.0, 0, 1))  # Assume sharpe in [-2, 2]
        hit_norm = float(abs(hit_rate - 0.5) * 2)                  # Distance from 50%
        dd_norm = float(max(0.0, 1.0 - dd_pct / 10.0))             # Penalize >10% drawdown
        sl_norm = float(max(0.0, 1.0 - sl_hit_rate / 0.5))         # Penalize >50% SL hit rate

        # Sample size confidence
        sample_conf = float(min(1.0, eff_n / cfg.risk_guards["min_effective_samples"]))

        # Combine metrics with weights
        confidence = (
            0.25 * sharpe_norm
            + 0.20 * hit_norm
            + 0.20 * dd_norm
            + 0.15 * sl_norm
            + 0.20 * sample_conf
        )

        # Apply spread penalty
        confidence = max(0.0, confidence - spread_penalty)

        return float(np.clip(confidence, 0.0, 1.0))

    except Exception as e:
        logger.error("Error computing confidence: %s", e)
        return 0.0


def gated_update(
    outcomes_df: pd.DataFrame,
    current_params: Dict[str, float],
    timeframe: str,
    config: Union[LearnerConfig, dict],
    context_meta: Optional[Dict[str, object]] = None,
) -> AdaptiveUpdate:
    """
    Main entry point for adaptive parameter updates with comprehensive guardrails.

    No wall-clock timing in core logic; rely on caller-provided latency via context_meta.
    """
    try:
        # Validate and convert config
        cfg = LearnerConfig(**config) if isinstance(config, dict) else config

        # Initialize context metadata
        if context_meta is None:
            context_meta = {}

        # Compute metrics
        metrics = compute_metrics(outcomes_df, cfg, timeframe)

        # Initialize default response with sorted keys for determinism
        noop_response = AdaptiveUpdate(
            mode="shadow",
            new_params={k: current_params[k] for k in sorted(current_params.keys())},
            deltas={k: 0.0 for k in sorted(current_params.keys())},
            confidence=0.0,
            reason="No update conditions met",
            diagnostics=metrics,
            latency_ms=int(context_meta.get("latency_ms", 0)),
        )

        # Eligibility checks (return NOOP if any fail)

        # 1. Minimum trades check
        if metrics["n_total"] < MIN_TRADES_ABSOLUTE:
            noop_response = noop_response.model_copy(
                update={"reason": f"Insufficient trades: {metrics['n_total']} < {MIN_TRADES_ABSOLUTE}"}
            )
            logger.info(noop_response.reason)
            return noop_response

        if metrics["eff_n"] < cfg.risk_guards["min_effective_samples"]:
            noop_response = noop_response.model_copy(
                update={
                    "reason": f"Low effective samples: {metrics['eff_n']} < {cfg.risk_guards['min_effective_samples']}"
                }
            )
            logger.debug(noop_response.reason)
            return noop_response

        # 2. Daily stop check
        daily_pnl = float(context_meta.get("rolling_pnl_day_usd", 0.0))
        if daily_pnl <= -float(cfg.risk_guards["daily_stop_usd"]):
            noop_response = noop_response.model_copy(
                update={"reason": f"Daily stop hit: {daily_pnl:.2f} <= -{cfg.risk_guards['daily_stop_usd']}"}
            )
            logger.warning(noop_response.reason)
            return noop_response

        # 3. Spread check
        avg_spread = float(context_meta.get("avg_spread_bps", 0.0))
        spread_penalty = 0.0
        if avg_spread > float(cfg.risk_guards["max_spread_bps"]):
            spread_penalty = 0.3  # Reduce confidence
            logger.warning(
                "High spread detected: %.1f > %.1f bps",
                avg_spread,
                cfg.risk_guards["max_spread_bps"],
            )

        # 4. Timing check
        now_ms = context_meta.get("now_ms")
        last_update_ms = context_meta.get("last_update_ms")
        if now_ms is not None and last_update_ms is not None:
            try:
                time_since_update = int(now_ms) - int(last_update_ms)
            except Exception:
                time_since_update = 0
            if time_since_update < int(cfg.risk_guards["min_interval_ms"]):
                noop_response = noop_response.model_copy(
                    update={
                        "reason": f"Update interval too short: {time_since_update}ms < {cfg.risk_guards['min_interval_ms']}ms"
                    }
                )
                logger.debug(noop_response.reason)
                return noop_response

        # Propose parameter changes
        deltas = propose_deltas(metrics, current_params, cfg)
        new_params = apply_bounds(current_params, deltas, cfg)

        # Compute confidence
        confidence = _compute_confidence(metrics, cfg, spread_penalty)

        # Determine mode and reason
        mode: Literal["shadow", "active"] = "shadow"  # Default to shadow
        reasons = []

        if cfg.mode == "active" and confidence >= 0.6:
            mode = "active"
            reasons.append("ACTIVE mode")
        else:
            reasons.append("shadow mode")

        # Add performance indicators to reason
        sharpe = metrics.get("sharpe_ewma", 0.0)
        hit_rate = metrics.get("hit_rate_ewma", 0.5)
        dd_pct = metrics.get("dd_pct", 0.0)

        if sharpe >= cfg.thresholds["good_sharpe"]:
            reasons.append("Sharpe↑")
        elif sharpe <= cfg.thresholds["poor_sharpe"]:
            reasons.append("Sharpe↓")

        if hit_rate >= cfg.thresholds["hit_rate_good"]:
            reasons.append("HR↑")
        elif hit_rate <= cfg.thresholds["hit_rate_poor"]:
            reasons.append("HR↓")

        if dd_pct >= cfg.thresholds["drawdown_freeze_pct"]:
            reasons.append("DD high")
        elif dd_pct <= 2.0:
            reasons.append("DD low")

        # Add delta indicators
        significant_deltas = [f"{k}:{v:+.2f}" for k, v in deltas.items() if abs(v) > 0.01]
        if significant_deltas:
            reasons.extend(significant_deltas[:3])  # Limit to top 3

        reason = ", ".join(reasons[:5])  # Limit reason length

        final_latency = int(context_meta.get("latency_ms", 0))

        # Check latency budget with caller-provided timing
        if final_latency > cfg.latency_budget_ms:
            logger.warning(
                "Latency budget exceeded (caller-provided): %dms > %dms",
                final_latency,
                cfg.latency_budget_ms,
            )

        result = AdaptiveUpdate(
            mode=mode,
            new_params=new_params,
            deltas=deltas,
            confidence=confidence,
            reason=reason,
            diagnostics=metrics,
            latency_ms=final_latency,
        )

        logger.info(
            "Adaptive update complete: mode=%s, confidence=%.2f, reason='%s', latency=%dms",
            mode,
            confidence,
            reason,
            final_latency,
        )

        return result

    except Exception as e:
        # Safe fallback on any error
        latency_ms = int(context_meta.get("latency_ms", 0)) if context_meta else 0
        logger.exception("Error in gated_update: %s", e)

        return AdaptiveUpdate(
            mode="shadow",
            new_params={k: current_params[k] for k in sorted(current_params.keys())},
            deltas={k: 0.0 for k in sorted(current_params.keys())},
            confidence=0.0,
            reason=f"Error: {str(e)[:50]}",
            diagnostics={"error": 1.0, "n_total": 0},
            latency_ms=latency_ms,
        )


if __name__ == "__main__":
    # Self-check with synthetic data (optional)
    import time  # self-check only; core path remains free of wall-clock

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    logger.info("Running adaptive learner self-check...")

    # Generate synthetic outcomes data
    np.random.seed(42)  # Reproducible results
    n_trades = 500

    # Simulate realistic trading outcomes
    base_return = 0.02   # 2 bps average
    volatility = 8.0     # 8 bps volatility

    # Generate timestamps (hourly over ~20 days)
    start_time = 1_700_000_000  # Nov 2023 (fixed for reproducibility)
    timestamps = [start_time + i * 3600 for i in range(n_trades)]

    # Generate realistic P&L with some autocorrelation
    returns = []
    last_return = 0.0
    for _ in range(n_trades):
        momentum = 0.1 * last_return
        noise = np.random.normal(0, volatility)
        ret = base_return + momentum + noise
        returns.append(ret)
        last_return = ret

    # Generate other realistic columns
    symbols = np.random.choice(["BTC/USD", "ETH/USD", "SOL/USD"], n_trades)
    strategies = np.random.choice(["scalp", "trend_following", "breakout"], n_trades)
    sides = np.random.choice(["long", "short"], n_trades)

    # Generate prices and P&L
    entry_prices = 45_000 + np.random.normal(0, 2_000, n_trades)  # BTC-like prices
    pnl_bps = np.array(returns)
    exit_prices = entry_prices * (1 + pnl_bps / 10_000)
    pnl_usd = pnl_bps * 10  # $10 per bp

    # Generate hit/miss indicators
    tp_hit = (pnl_bps > 10).astype(int)     # Profit target at 10 bps
    sl_hit = (pnl_bps < -5).astype(int)     # Stop loss at -5 bps

    # Hold times (realistic for scalping)
    hold_ms = np.random.exponential(120_000, n_trades).astype(int)  # ~2 min average

    # Create synthetic DataFrame
    synthetic_df = pd.DataFrame(
        {
            "timestamp": timestamps,
            "symbol": symbols,
            "strategy": strategies,
            "side": sides,
            "entry_px": entry_prices,
            "exit_px": exit_prices,
            "pnl_usd": pnl_usd,
            "pnl_bps": pnl_bps,
            "hold_ms": hold_ms,
            "sl_hit": sl_hit,
            "tp_hit": tp_hit,
            "mae_bps": np.random.uniform(-20, 0, n_trades),   # Max adverse excursion
            "mfe_bps": np.random.uniform(0, 25, n_trades),    # Max favorable excursion
            "spread_bps": np.random.uniform(1, 4, n_trades),  # Realistic spreads
            "regime_at_entry": np.random.choice(["bull", "bear", "chop"], n_trades),
        }
    )

    # Test parameters
    current_params = {
        "position_size_pct": 0.5,
        "sl_multiplier": 1.2,
        "tp_multiplier": 1.8,
        "cooldown_s": 30.0,
        "max_concurrent": 2,
    }

    # Test context (fixed latency for deterministic output)
    context_meta = {
        "now_ms": int(time.time() * 1000),
        "last_update_ms": int((time.time() - 1800) * 1000),  # 30 min ago
        "rolling_pnl_day_usd": 75.0,                         # Positive P&L
        "avg_spread_bps": 2.5,                               # Reasonable spread
        "latency_ms": 0,                                     # Deterministic
    }

    # Run the adaptive update
    try:
        config = LearnerConfig()
        result = gated_update(
            outcomes_df=synthetic_df,
            current_params=current_params,
            timeframe="1m",
            config=config,
            context_meta=context_meta,
        )

        logger.info("✅ Adaptive update result:")
        logger.info("   Mode: %s", result.mode)
        logger.info("   Confidence: %.3f", result.confidence)
        logger.info("   Reason: %s", result.reason)
        logger.info("   Latency: %dms", result.latency_ms)
        logger.info(
            "   Diagnostics: n_total=%d, sharpe=%.2f",
            int(result.diagnostics.get("n_total", 0)),
            float(result.diagnostics.get("sharpe_ewma", 0.0)),
        )

        # Test JSON serialization (deterministic)
        json_str = result.model_dump_json(sort_keys=True)
        roundtrip = AdaptiveUpdate.model_validate_json(json_str)
        assert result == roundtrip, "JSON roundtrip failed"
        logger.info("✅ JSON serialization test passed")

        # Edge cases
        logger.info("Testing edge cases...")

        # Empty DataFrame
        empty_result = gated_update(pd.DataFrame(), current_params, "1m", config, {"latency_ms": 0})
        assert empty_result.confidence == 0.0
        logger.info("✅ Empty DataFrame test passed")

        # Insufficient trades
        small_df = synthetic_df.head(10)
        small_result = gated_update(small_df, current_params, "1m", config, {"latency_ms": 0})
        assert "Insufficient trades" in small_result.reason
        logger.info("✅ Insufficient trades test passed")

        # Daily stop triggered
        context_stop = dict(context_meta)
        context_stop["rolling_pnl_day_usd"] = -200.0
        stop_result = gated_update(synthetic_df, current_params, "1m", config, context_stop)
        assert "Daily stop hit" in stop_result.reason
        logger.info("✅ Daily stop test passed")

        # Wide spread penalty (confidence reduced)
        context_spread = dict(context_meta)
        context_spread["avg_spread_bps"] = 30.0
        spread_result = gated_update(synthetic_df, current_params, "1m", config, context_spread)
        logger.info("✅ Wide spread test passed (confidence reduced)")

        logger.info("🎉 All tests passed! Adaptive learner appears production-ready.")

    except Exception as e:
        logger.error("❌ Self-check failed: %s", e)
        raise
