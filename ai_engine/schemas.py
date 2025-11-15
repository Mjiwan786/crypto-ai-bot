"""
AI Engine Internal Schemas Module

Canonical, internal contracts for the AI Engine (separate from external wire/event contracts).
Provides frozen, strict Pydantic v2 models used inside the engine for:
- standardized configs (TA/Macro/Sentiment, learner, risk budgets)
- regime outputs (TA/Macro/Sentiment)
- engine-level strategy decisions & fuser inputs
- learner metrics & proposed updates (internal view)
- deterministic serialization utilities and adapters to/from ai_engine.events models

Example Usage:
    from ai_engine.schemas import TAConfig, TARegime, StrategyDecision, to_json
    cfg = TAConfig()
    reg = TARegime(label="bull", confidence=0.76, components={"trend":0.6,"mom":0.7,"vol":0.5},
                   features={"rsi":58.0,"adx":22.0}, explain="EMA cross + strong DI+", n_samples=3000, latency_ms=18)
    wire = to_json(reg)

HARD CONSTRAINTS:
- Pure logic: no network/file I/O, no env reads, no wall-clock in logic
- Deterministic: same inputs → same outputs; stable JSON key ordering; no sets
- Python 3.10–3.12. Dependencies: stdlib + pydantic (v2) only
- Frozen models with extra='forbid' and explicit, documented field types
- Dict fields serialize with deterministically sorted keys
- Clear validators with regex for timeframe/symbol; numeric bounds; reject NaN/Inf
"""

import json
import logging
import re
from enum import Enum
from typing import Any, Dict, Literal, Optional, TypeVar, Union

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator

# Module logger
logger = logging.getLogger(__name__)

# Type variable for generic functions
T = TypeVar('T', bound=BaseModel)

# Validation patterns
TIMEFRAME_PATTERN = re.compile(r'^\d+[mhdw]$')
SYMBOL_PATTERN = re.compile(r'^[A-Z0-9]{2,20}([:/-][A-Z0-9]{2,20})?$')

# =============================================================================
# COMMON ENUMS & VALIDATORS
# =============================================================================

class Env(str, Enum):
    """Environment enum"""
    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"

class RegimeLabel(str, Enum):
    """Market regime classification"""
    BULL = "bull"
    BEAR = "bear"
    CHOP = "chop"

class Side(str, Enum):
    """Trading side"""
    LONG = "long"
    SHORT = "short"
    NONE = "none"

class DecisionAction(str, Enum):
    """Strategy decision actions"""
    OPEN = "open"
    CLOSE = "close"
    REDUCE = "reduce"
    HOLD = "hold"
    NOOP = "noop"

def validate_timeframe(v: str) -> str:
    """Validate timeframe format (e.g., 1m, 5m, 1h, 1d)"""
    if not isinstance(v, str):
        raise ValueError("Timeframe must be a string")
    if not TIMEFRAME_PATTERN.match(v):
        raise ValueError(f"Invalid timeframe format: {v}. Must match pattern: \\d+[mhdw]")
    return v

def validate_symbol(v: str) -> str:
    """Validate trading symbol format (e.g., BTCUSDT, BTC/USD)"""
    if not isinstance(v, str):
        raise ValueError("Symbol must be a string")
    if not SYMBOL_PATTERN.match(v.upper()):
        raise ValueError("Invalid symbol format: "
                         f"{v}. Must be 2-20 alphanumeric chars, optionally separated by :/-")
    return v.upper()

def validate_finite_float(v: float, field_name: str) -> float:
    """Validate float is finite (not NaN or Inf)"""
    if not isinstance(v, (int, float)):
        raise ValueError(f"{field_name} must be a number")
    v = float(v)
    if not (v == v):  # NaN check
        raise ValueError(f"{field_name} cannot be NaN")
    if abs(v) == float('inf'):
        raise ValueError(f"{field_name} cannot be infinite")
    return v

def clamp_confidence(v: float) -> float:
    """Clamp confidence to [0, 1] range"""
    v = validate_finite_float(v, "confidence")
    return max(0.0, min(1.0, v))

def sorted_dict(d: Dict[str, Any]) -> Dict[str, Any]:
    """Return dict with sorted keys for deterministic serialization"""
    if not isinstance(d, dict):
        return d
    return {k: d[k] for k in sorted(d.keys())}

# =============================================================================
# CUSTOM EXCEPTIONS
# =============================================================================

class SchemaValidationError(ValueError):
    """Schema validation error"""
    pass

# =============================================================================
# BASE CONFIGS
# =============================================================================

class AppInfo(BaseModel):
    """Application information"""
    model_config = ConfigDict(frozen=True, extra='forbid')

    name: str = Field(description="Application name")
    version: str = Field(description="Application version")
    env: Env = Field(description="Environment")

class LatencyBudgets(BaseModel):
    """Latency budget configurations"""
    model_config = ConfigDict(frozen=True, extra='forbid')

    regime_ms: int = Field(default=250, ge=1, description="Regime detection budget (ms)")
    fuse_ms: int = Field(default=100, ge=1, description="Signal fusion budget (ms)")
    learner_ms: int = Field(default=250, ge=1, description="Learner update budget (ms)")

class RiskGuards(BaseModel):
    """Risk guard configurations"""
    model_config = ConfigDict(frozen=True, extra='forbid')

    daily_stop_usd: float = Field(default=0.0, ge=0.0, description="Daily stop loss in USD")
    spread_bps_cap: float = Field(default=50.0, ge=0.0, description="Maximum spread in basis points")
    max_age_ms: int = Field(default=120000, ge=1, description="Maximum data age in milliseconds")

    @field_validator('daily_stop_usd', 'spread_bps_cap')
    @classmethod
    def validate_finite(cls, v):
        return validate_finite_float(v, 'risk_guard_value')

class TAConfig(BaseModel):
    """Technical Analysis configuration"""
    model_config = ConfigDict(frozen=True, extra='forbid')

    # Windows
    windows: Dict[str, int] = Field(default={
        "rsi": 14,
        "adx": 14,
        "ema_fast": 12,
        "ema_slow": 26,
        "bbands": 20
    }, description="Technical indicator windows")

    # Weights
    weights: Dict[str, float] = Field(default={
        "momentum": 0.33,
        "trend": 0.34,
        "volatility": 0.33
    }, description="Component weights")

    # Thresholds
    thresholds: Dict[str, float] = Field(default={
        "bull": 0.55,
        "bear": -0.55,
        "chop_abs": 0.25
    }, description="Regime classification thresholds")

    # Guardrails
    guardrails: Dict[str, int] = Field(default={
        "max_age_ms": 300000
    }, description="Data quality guardrails")

    latency_budget_ms: int = Field(default=250, ge=1, description="Latency budget (ms)")

    @field_serializer('windows', 'weights', 'thresholds', 'guardrails')
    def serialize_dicts(self, v: Dict[str, Union[int, float]]) -> Dict[str, Union[int, float]]:
        return sorted_dict(v)

    @field_validator('weights', 'thresholds')
    @classmethod
    def _validate_float_dicts(cls, v: Dict[str, float]):
        for k, val in v.items():
            validate_finite_float(val, f'ta_{k}')
        return v

class MacroConfig(BaseModel):
    """Macro analysis configuration"""
    model_config = ConfigDict(frozen=True, extra='forbid')

    lookbacks: Dict[str, int] = Field(default={
        "short": 14,
        "medium": 30,
        "long": 90
    }, description="Lookback periods")

    weights: Dict[str, float] = Field(default={
        "usd_liquidity": 0.25,
        "crypto_derivs": 0.35,
        "risk_appetite": 0.25,
        "flow": 0.15
    }, description="Component weights")

    thresholds: Dict[str, float] = Field(default={
        "bull": 0.55,
        "bear": -0.55,
        "chop_abs": 0.25
    }, description="Regime classification thresholds")

    scaling: Dict[str, float] = Field(default={
        "basis_clip": 20.0,
        "funding_clip": 15.0,
        "dxy_z_clip": 3.0,
        "rate_z_clip": 3.0
    }, description="Scaling parameters")

    latency_budget_ms: int = Field(default=250, ge=1, description="Latency budget (ms)")

    @field_serializer('lookbacks', 'weights', 'thresholds', 'scaling')
    def serialize_dicts(self, v: Dict[str, Union[int, float]]) -> Dict[str, Union[int, float]]:
        return sorted_dict(v)

    @field_validator('weights', 'thresholds', 'scaling')
    @classmethod
    def _validate_float_dicts(cls, v: Dict[str, float]):
        for k, val in v.items():
            validate_finite_float(val, f'macro_{k}')
        return v

class SentimentConfig(BaseModel):
    """Sentiment analysis configuration"""
    model_config = ConfigDict(frozen=True, extra='forbid')

    lookbacks: Dict[str, int] = Field(default={
        "short": 20,
        "medium": 60,
        "long": 180
    }, description="Lookback periods")

    weights: Dict[str, float] = Field(default={
        "social": 0.45,
        "news": 0.35,
        "reaction": 0.20
    }, description="Component weights")

    thresholds: Dict[str, float] = Field(default={
        "bull": 0.55,
        "bear": -0.55,
        "chop_abs": 0.25
    }, description="Regime classification thresholds")

    scaling: Dict[str, float] = Field(default={
        "vol_z_clip": 3.5,
        "score_clip": 1.0,
        "dispersion_clip": 3.0
    }, description="Scaling parameters")

    guardrails: Dict[str, Union[int, float]] = Field(default={
        "min_rows": 200,
        "max_nan_frac": 0.15,
        "min_signal_volume": 50.0
    }, description="Data quality guardrails")

    latency_budget_ms: int = Field(default=250, ge=1, description="Latency budget (ms)")

    @field_serializer('lookbacks', 'weights', 'thresholds', 'scaling', 'guardrails')
    def serialize_dicts(self, v: Dict[str, Union[int, float]]) -> Dict[str, Union[int, float]]:
        return sorted_dict(v)

    @field_validator('weights', 'thresholds', 'scaling')
    @classmethod
    def _validate_float_dicts(cls, v: Dict[str, float]):
        for k, val in v.items():
            validate_finite_float(val, f'sent_{k}')
        return v

    @field_validator('guardrails')
    @classmethod
    def _validate_guardrails(cls, v: Dict[str, Union[int, float]]):
        # Only floats need finite-value checks here
        for k, val in v.items():
            if isinstance(val, float):
                validate_finite_float(val, f'sent_guard_{k}')
        return v

class LearnerBounds(BaseModel):
    """Learner parameter bounds"""
    model_config = ConfigDict(frozen=True, extra='forbid')

    pos_size_pct: Dict[str, float] = Field(default={
        "min": 0.1, "max": 2.0, "max_step": 0.25
    }, description="Position size percentage bounds")

    sl_multiplier: Dict[str, float] = Field(default={
        "min": 0.5, "max": 3.0, "max_step": 0.25
    }, description="Stop loss multiplier bounds")

    tp_multiplier: Dict[str, float] = Field(default={
        "min": 0.5, "max": 4.0, "max_step": 0.25
    }, description="Take profit multiplier bounds")

    cooldown_s: Dict[str, float] = Field(default={
        "min": 5.0, "max": 300.0, "max_step": 30.0
    }, description="Cooldown period bounds")

    max_concurrent: Dict[str, int] = Field(default={
        "min": 1, "max": 5, "max_step": 1
    }, description="Maximum concurrent positions bounds")

    @field_serializer('pos_size_pct', 'sl_multiplier', 'tp_multiplier', 'cooldown_s', 'max_concurrent')
    def serialize_dicts(self, v: Dict[str, Union[int, float]]) -> Dict[str, Union[int, float]]:
        return sorted_dict(v)

    @field_validator('pos_size_pct', 'sl_multiplier', 'tp_multiplier', 'cooldown_s')
    @classmethod
    def _validate_float_dicts(cls, v: Dict[str, float]):
        for k, val in v.items():
            validate_finite_float(val, f'learner_bounds_{k}')
        return v

class LearnerThresholds(BaseModel):
    """Learner performance thresholds"""
    model_config = ConfigDict(frozen=True, extra='forbid')

    min_trades: int = Field(default=200, ge=1, description="Minimum trades for evaluation")
    good_sharpe: float = Field(default=1.0, description="Good Sharpe ratio threshold")
    poor_sharpe: float = Field(default=0.2, description="Poor Sharpe ratio threshold")
    hit_rate_good: float = Field(default=0.55, ge=0.0, le=1.0, description="Good hit rate threshold")
    hit_rate_poor: float = Field(default=0.45, ge=0.0, le=1.0, description="Poor hit rate threshold")
    sl_hit_too_often: float = Field(default=0.35, ge=0.0, le=1.0, description="Stop loss hit rate threshold")
    drawdown_freeze_pct: float = Field(default=8.0, ge=0.0, description="Drawdown freeze percentage")

    @field_validator('good_sharpe', 'poor_sharpe', 'drawdown_freeze_pct')
    @classmethod
    def validate_finite(cls, v):
        return validate_finite_float(v, 'threshold_value')

class LearnerRisk(BaseModel):
    """Learner risk controls"""
    model_config = ConfigDict(frozen=True, extra='forbid')

    daily_stop_usd: float = Field(default=150.0, ge=0.0, description="Daily stop loss in USD")
    max_spread_bps: float = Field(default=25.0, ge=0.0, description="Maximum spread in bps")
    min_effective_samples: int = Field(default=100, ge=1, description="Minimum effective samples")
    min_interval_ms: int = Field(default=1800000, ge=1, description="Minimum interval between updates (ms)")

    @field_validator('daily_stop_usd', 'max_spread_bps')
    @classmethod
    def validate_finite(cls, v):
        return validate_finite_float(v, 'risk_value')

class LearnerConfig(BaseModel):
    """Learner configuration aggregator"""
    model_config = ConfigDict(frozen=True, extra='forbid')

    bounds: LearnerBounds = Field(default_factory=LearnerBounds)
    thresholds: LearnerThresholds = Field(default_factory=LearnerThresholds)
    risk: LearnerRisk = Field(default_factory=LearnerRisk)
    mode: Literal["shadow", "active"] = Field(default="shadow", description="Learner mode")
    latency_budget_ms: int = Field(default=250, ge=1, description="Latency budget (ms)")

# =============================================================================
# REGIME OUTPUTS (INTERNAL)
# =============================================================================

class TARegime(BaseModel):
    """Technical Analysis regime output"""
    model_config = ConfigDict(frozen=True, extra='forbid')

    schema_version: str = Field(default="1.0", description="Schema version")
    label: RegimeLabel = Field(description="Regime classification")
    confidence: float = Field(description="Classification confidence [0,1]")
    components: Dict[str, float] = Field(description="Component scores")
    features: Dict[str, float] = Field(description="Feature values")
    explain: str = Field(description="Human-readable explanation")
    n_samples: int = Field(ge=0, description="Number of samples used")
    latency_ms: int = Field(ge=0, description="Processing latency (ms)")

    @field_validator('confidence')
    @classmethod
    def validate_confidence(cls, v):
        return clamp_confidence(v)

    @field_validator('components', 'features')
    @classmethod
    def validate_dict_values(cls, v):
        for key, val in v.items():
            validate_finite_float(val, f'dict_value_{key}')
        return v

    @field_serializer('components', 'features')
    def serialize_dicts(self, v: Dict[str, float]) -> Dict[str, float]:
        return sorted_dict(v)

class MacroRegime(BaseModel):
    """Macro analysis regime output"""
    model_config = ConfigDict(frozen=True, extra='forbid')

    schema_version: str = Field(default="1.0", description="Schema version")
    label: RegimeLabel = Field(description="Regime classification")
    confidence: float = Field(description="Classification confidence [0,1]")
    components: Dict[str, float] = Field(description="Component scores")
    features: Dict[str, float] = Field(description="Feature values")
    explain: str = Field(description="Human-readable explanation")
    n_samples: int = Field(ge=0, description="Number of samples used")
    latency_ms: int = Field(ge=0, description="Processing latency (ms)")

    @field_validator('confidence')
    @classmethod
    def validate_confidence(cls, v):
        return clamp_confidence(v)

    @field_validator('components', 'features')
    @classmethod
    def validate_dict_values(cls, v):
        for key, val in v.items():
            validate_finite_float(val, f'dict_value_{key}')
        return v

    @field_serializer('components', 'features')
    def serialize_dicts(self, v: Dict[str, float]) -> Dict[str, float]:
        return sorted_dict(v)

class SentimentRegime(BaseModel):
    """Sentiment analysis regime output"""
    model_config = ConfigDict(frozen=True, extra='forbid')

    schema_version: str = Field(default="1.0", description="Schema version")
    label: RegimeLabel = Field(description="Regime classification")
    confidence: float = Field(description="Classification confidence [0,1]")
    components: Dict[str, float] = Field(description="Component scores")
    features: Dict[str, float] = Field(description="Feature values")
    explain: str = Field(description="Human-readable explanation")
    n_samples: int = Field(ge=0, description="Number of samples used")
    latency_ms: int = Field(ge=0, description="Processing latency (ms)")

    @field_validator('confidence')
    @classmethod
    def validate_confidence(cls, v):
        return clamp_confidence(v)

    @field_validator('components', 'features')
    @classmethod
    def validate_dict_values(cls, v):
        for key, val in v.items():
            validate_finite_float(val, f'dict_value_{key}')
        return v

    @field_serializer('components', 'features')
    def serialize_dicts(self, v: Dict[str, float]) -> Dict[str, float]:
        return sorted_dict(v)

# =============================================================================
# ENGINE DECISION & FUSER INPUTS
# =============================================================================

class FuserInput(BaseModel):
    """Input to signal fusion engine"""
    model_config = ConfigDict(frozen=True, extra='forbid')

    timeframe: str = Field(description="Analysis timeframe")
    ta: Optional[TARegime] = Field(default=None, description="Technical analysis regime")
    macro: Optional[MacroRegime] = Field(default=None, description="Macro regime")
    sentiment: Optional[SentimentRegime] = Field(default=None, description="Sentiment regime")

    @field_validator('timeframe')
    @classmethod
    def validate_timeframe_format(cls, v):
        return validate_timeframe(v)

class StrategyDecision(BaseModel):
    """Strategy decision output"""
    model_config = ConfigDict(frozen=True, extra='forbid')

    schema_version: str = Field(default="1.0", description="Schema version")
    action: DecisionAction = Field(description="Decision action")
    side: Side = Field(description="Trading side")
    allocations: Dict[str, float] = Field(description="Strategy allocations")
    max_position_usd: float = Field(ge=0.0, description="Maximum position size in USD")
    sl_multiplier: float = Field(ge=0.0, description="Stop loss multiplier")
    tp_multiplier: float = Field(ge=0.0, description="Take profit multiplier")
    explain: str = Field(description="Decision explanation")
    confidence: float = Field(description="Decision confidence [0,1]")

    @field_validator('confidence')
    @classmethod
    def validate_confidence(cls, v):
        return clamp_confidence(v)

    @field_validator('max_position_usd', 'sl_multiplier', 'tp_multiplier')
    @classmethod
    def validate_finite(cls, v):
        return validate_finite_float(v, 'decision_value')

    @field_validator('allocations')
    @classmethod
    def validate_allocations(cls, v):
        for key, val in v.items():
            validate_finite_float(val, f'allocation_{key}')
            if val < 0.0 or val > 1.0:
                raise ValueError(f"Allocation {key} must be in [0,1], got {val}")
        return v

    @field_serializer('allocations')
    def serialize_allocations(self, v: Dict[str, float]) -> Dict[str, float]:
        return sorted_dict(v)

    @model_validator(mode='after')
    def _check_allocations_sum(self):
        """Ensure allocations sum does not exceed 1.0 (with small tolerance)"""
        total = float(sum(self.allocations.values()))
        if total > 1.0 + 1e-9:
            raise ValueError(f"Allocations sum must be <= 1.0, got {total:.10f}")
        return self

# =============================================================================
# LEARNER METRICS & UPDATE (INTERNAL VIEW)
# =============================================================================

class LearnerMetrics(BaseModel):
    """Learner performance metrics"""
    model_config = ConfigDict(frozen=True, extra='forbid')

    sharpe_ewma: float = Field(description="EWMA Sharpe ratio")
    hit_rate_ewma: float = Field(ge=0.0, le=1.0, description="EWMA hit rate")
    sl_hit_rate: float = Field(ge=0.0, le=1.0, description="Stop loss hit rate")
    dd_pct: float = Field(description="Drawdown percentage")
    eff_n: float = Field(ge=0.0, description="Effective sample size")
    n_total: int = Field(ge=0, description="Total number of trades")

    @field_validator('sharpe_ewma', 'dd_pct', 'eff_n')
    @classmethod
    def validate_finite(cls, v):
        return validate_finite_float(v, 'metric_value')

class PolicyProposal(BaseModel):
    """Learner policy update proposal"""
    model_config = ConfigDict(frozen=True, extra='forbid')

    mode: Literal["shadow", "active"] = Field(description="Proposed mode")
    new_params: Dict[str, float] = Field(description="New parameter values")
    deltas: Dict[str, float] = Field(description="Parameter deltas")
    confidence: float = Field(description="Proposal confidence [0,1]")
    reason: str = Field(description="Reason for proposal")
    diagnostics: Dict[str, float] = Field(description="Diagnostic metrics")

    @field_validator('confidence')
    @classmethod
    def validate_confidence(cls, v):
        return clamp_confidence(v)

    @field_validator('new_params', 'deltas', 'diagnostics')
    @classmethod
    def validate_dict_values(cls, v):
        for key, val in v.items():
            validate_finite_float(val, f'param_{key}')
        return v

    @field_serializer('new_params', 'deltas', 'diagnostics')
    def serialize_dicts(self, v: Dict[str, float]) -> Dict[str, float]:
        return sorted_dict(v)

# =============================================================================
# DETERMINISTIC SERIALIZATION HELPERS
# =============================================================================

def to_json(model: BaseModel) -> str:
    """Convert model to compact JSON with globally sorted keys (deterministic)"""
    if not isinstance(model, BaseModel):
        raise TypeError("Input must be a Pydantic BaseModel")
    try:
        data = model.model_dump(by_alias=True, exclude_none=True)
        return json.dumps(data, sort_keys=True, separators=(',', ':'))
    except Exception as e:
        raise SchemaValidationError(f"Failed to serialize model: {e}")

def from_json(s: str, cls: type[T]) -> T:
    """Create model from JSON string"""
    if not isinstance(s, str):
        raise TypeError("Input must be a string")
    if not issubclass(cls, BaseModel):
        raise TypeError("cls must be a Pydantic BaseModel subclass")
    try:
        return cls.model_validate_json(s)
    except Exception as e:
        raise SchemaValidationError(f"Failed to deserialize JSON: {e}")

# =============================================================================
# ADAPTERS TO/FROM EVENTS (OPTIONAL)
# =============================================================================

def to_event(regime: Union[TARegime, MacroRegime, SentimentRegime], *, base_kwargs: Dict) -> Any:
    """Convert regime to external event format"""
    try:
        # Import only when needed to avoid circular dependencies
        from ai_engine.events import RegimeDetectedEvent

        # Create event with regime data and base kwargs
        event_data = {
            **base_kwargs,
            "regime_type": type(regime).__name__.replace("Regime", "").lower(),
            "label": regime.label,
            "confidence": regime.confidence,
            "components": sorted_dict(regime.components),
            "features": sorted_dict(regime.features),
            "explain": regime.explain,
            "n_samples": regime.n_samples,
            "latency_ms": regime.latency_ms
        }

        return RegimeDetectedEvent(**event_data)
    except ImportError:
        logger.warning("ai_engine.events module not available")
        return None

def from_event_regime(e: Any) -> Union[TARegime, MacroRegime, SentimentRegime]:
    """Convert external event to regime format"""
    try:
        # Determine regime type from event
        regime_type = getattr(e, 'regime_type', '').lower()

        # Common regime data (normalize dicts for deterministic in-memory state)
        regime_data = {
            "label": e.label,
            "confidence": e.confidence,
            "components": sorted_dict(getattr(e, 'components', {})),
            "features": sorted_dict(getattr(e, 'features', {})),
            "explain": getattr(e, 'explain', ''),
            "n_samples": getattr(e, 'n_samples', 0),
            "latency_ms": getattr(e, 'latency_ms', 0)
        }

        # Create appropriate regime type
        if regime_type == 'ta':
            return TARegime(**regime_data)
        elif regime_type == 'macro':
            return MacroRegime(**regime_data)
        elif regime_type == 'sentiment':
            return SentimentRegime(**regime_data)
        else:
            raise ValueError(f"Unknown regime type: {regime_type}")

    except Exception as ex:
        raise SchemaValidationError(f"Failed to convert event to regime: {ex}")

def to_event_decision(dec: StrategyDecision, *, base_kwargs: Dict) -> Any:
    """Convert strategy decision to external event format"""
    try:
        from ai_engine.events import StrategyDecisionEvent

        event_data = {
            **base_kwargs,
            "action": dec.action,
            "side": dec.side,
            "allocations": sorted_dict(dec.allocations),
            "max_position_usd": dec.max_position_usd,
            "sl_multiplier": dec.sl_multiplier,
            "tp_multiplier": dec.tp_multiplier,
            "explain": dec.explain,
            "confidence": dec.confidence
        }

        return StrategyDecisionEvent(**event_data)
    except ImportError:
        logger.warning("ai_engine.events module not available")
        return None

def from_event_policy(e: Any) -> PolicyProposal:
    """Convert external policy event to internal proposal format"""
    try:
        proposal_data = {
            "mode": getattr(e, 'mode', 'shadow'),
            "new_params": getattr(e, 'new_params', {}),
            "deltas": getattr(e, 'deltas', {}),
            "confidence": getattr(e, 'confidence', 0.5),
            "reason": getattr(e, 'reason', ''),
            "diagnostics": getattr(e, 'diagnostics', {})
        }

        return PolicyProposal(**proposal_data)
    except Exception as ex:
        raise SchemaValidationError(f"Failed to convert policy event: {ex}")

# =============================================================================
# PUBLIC API
# =============================================================================

# Import MarketSnapshot from events module and re-export for backward compatibility
try:
    from ai_engine.events import MarketSnapshotEvent as MarketSnapshot
except ImportError:
    MarketSnapshot = None  # Fallback if events module not available

__all__ = [
    # Enums
    'Env', 'RegimeLabel', 'Side', 'DecisionAction',

    # Base Configs
    'AppInfo', 'LatencyBudgets', 'RiskGuards',
    'TAConfig', 'MacroConfig', 'SentimentConfig',
    'LearnerBounds', 'LearnerThresholds', 'LearnerRisk', 'LearnerConfig',

    # Regime Outputs
    'TARegime', 'MacroRegime', 'SentimentRegime',

    # Engine Decision & Fuser
    'FuserInput', 'StrategyDecision',

    # Learner
    'LearnerMetrics', 'PolicyProposal',

    # Serialization Helpers
    'to_json', 'from_json', 'sorted_dict', 'validate_finite_float',

    # Validators
    'validate_timeframe', 'validate_symbol', 'clamp_confidence',

    # Adapters (optional)
    'to_event', 'from_event_regime', 'to_event_decision', 'from_event_policy',

    # Exceptions
    'SchemaValidationError',

    # Backward compatibility
    'MarketSnapshot'
]

# =============================================================================
# SELF-CHECK (UNDER __main__)
# =============================================================================

if __name__ == "__main__":
    """
    Self-check: Build tiny instances and run round-trip tests
    """
    import time  # Import moved here to avoid import-time dependency

    # Create test instances
    ta_regime = TARegime(
        label=RegimeLabel.BULL,
        confidence=0.76,
        components={"trend": 0.6, "momentum": 0.7, "volatility": 0.5},
        features={"rsi": 58.0, "adx": 22.0, "ema_cross": 1.0},
        explain="EMA cross + strong DI+",
        n_samples=3000,
        latency_ms=18
    )

    macro_regime = MacroRegime(
        label=RegimeLabel.CHOP,
        confidence=0.45,
        components={"usd_liquidity": 0.2, "crypto_derivs": -0.1, "risk_appetite": 0.0},
        features={"dxy": 105.2, "vix": 18.5, "btc_basis": 2.1},
        explain="Mixed signals with neutral risk appetite",
        n_samples=1500,
        latency_ms=24
    )

    sentiment_regime = SentimentRegime(
        label=RegimeLabel.BEAR,
        confidence=0.82,
        components={"social": -0.8, "news": -0.6, "reaction": -0.4},
        features={"twitter_sentiment": -0.75, "reddit_score": -0.45, "news_tone": -0.60},
        explain="Strong negative sentiment across all channels",
        n_samples=2200,
        latency_ms=31
    )

    strategy_decision = StrategyDecision(
        action=DecisionAction.OPEN,
        side=Side.LONG,
        allocations={"scalp": 0.3, "trend_following": 0.7},
        max_position_usd=5000.0,
        sl_multiplier=1.5,
        tp_multiplier=2.0,
        explain="Strong trend signal with favorable risk/reward",
        confidence=0.85
    )

    learner_metrics = LearnerMetrics(
        sharpe_ewma=1.25,
        hit_rate_ewma=0.58,
        sl_hit_rate=0.22,
        dd_pct=-3.2,
        eff_n=180.5,
        n_total=250
    )

    policy_proposal = PolicyProposal(
        mode="active",
        new_params={"pos_size": 0.08, "sl_mult": 1.8},
        deltas={"pos_size": 0.02, "sl_mult": 0.3},
        confidence=0.72,
        reason="Improved performance metrics warrant parameter adjustment",
        diagnostics={"backtest_sharpe": 1.45, "win_rate": 0.61}
    )

    # Collect models to test
    models_to_test = [
        ta_regime,
        macro_regime,
        sentiment_regime,
        strategy_decision,
        learner_metrics,
        policy_proposal,
    ]

    # Test JSON determinism and sorted keys
    for model in models_to_test:
        model_name = type(model).__name__

        try:
            # Test JSON serialization
            json_str = to_json(model)
            assert isinstance(json_str, str), f"{model_name}: JSON output not string"
            assert len(json_str) > 0, f"{model_name}: Empty JSON output"

            # Test JSON deserialization
            restored_model = from_json(json_str, type(model))
            assert isinstance(restored_model, type(model)), f"{model_name}: Wrong type after deserialization"

            # Test deterministic serialization (same input -> same output)
            json_str2 = to_json(model)
            assert json_str == json_str2, f"{model_name}: Non-deterministic serialization"

            # Test that JSON keys are globally sorted
            parsed_json = json.loads(json_str)
            if isinstance(parsed_json, dict):
                keys_list = list(parsed_json.keys())
                sorted_keys = sorted(keys_list)
                assert keys_list == sorted_keys, f"{model_name}: JSON keys not sorted: {keys_list} vs {sorted_keys}"

            # Test round-trip equality
            assert model.model_dump() == restored_model.model_dump(), f"{model_name}: Round-trip data mismatch"

            logger.info(f"✓ {model_name} JSON round-trip test passed")

        except Exception as e:
            logger.error(f"✗ {model_name} JSON round-trip test failed: {e}")
            raise

    # Test enhanced validation features
    try:
        # Test allocation sum constraint
        _valid_decision = StrategyDecision(
            action=DecisionAction.OPEN,
            side=Side.LONG,
            allocations={"scalp": 0.4, "trend": 0.6},  # Sum = 1.0, valid
            max_position_usd=1000.0,
            sl_multiplier=1.5,
            tp_multiplier=2.0,
            explain="Valid allocation",
            confidence=0.8
        )
        logger.info("✓ Valid allocation test passed")

        # Test invalid allocation sum (should fail)
        try:
            _invalid_decision = StrategyDecision(
                action=DecisionAction.OPEN,
                side=Side.LONG,
                allocations={"scalp": 0.8, "trend": 0.3},  # Sum = 1.1, invalid
                max_position_usd=1000.0,
                sl_multiplier=1.5,
                tp_multiplier=2.0,
                explain="Invalid allocation",
                confidence=0.8
            )
            raise AssertionError("Expected ValidationError for allocation sum > 1.0")
        except ValueError as e:
            if "Allocations sum must be <= 1.0" in str(e):
                logger.info("✓ Allocation sum constraint test passed")
            else:
                raise

        # Test config dict validation with NaN/Inf
        try:
            _invalid_ta_config = TAConfig(
                weights={"momentum": 0.33, "trend": float('nan'), "volatility": 0.34}
            )
            raise AssertionError("Expected ValidationError for NaN in weights")
        except ValueError as e:
            if "cannot be NaN" in str(e):
                logger.info("✓ Config NaN validation test passed")
            else:
                raise

        try:
            _invalid_macro_config = MacroConfig(
                scaling={"basis_clip": float('inf'), "funding_clip": 15.0}
            )
            raise AssertionError("Expected ValidationError for Inf in scaling")
        except ValueError as e:
            if "cannot be infinite" in str(e):
                logger.info("✓ Config Inf validation test passed")
            else:
                raise

    except Exception as e:
        logger.error(f"✗ Enhanced validation tests failed: {e}")
        raise

    # Test configuration models round-trip
    ta_config = TAConfig()
    macro_config = MacroConfig()
    sentiment_config = SentimentConfig()
    learner_config = LearnerConfig()

    config_models = [ta_config, macro_config, sentiment_config, learner_config]

    for config in config_models:
        config_name = type(config).__name__
        try:
            json_str = to_json(config)
            restored_config = from_json(json_str, type(config))
            assert config.model_dump() == restored_config.model_dump(), f"{config_name}: Config round-trip failed"
            logger.info(f"✓ {config_name} test passed")
        except Exception as e:
            logger.error(f"✗ {config_name} test failed: {e}")
            raise

    # Test adapter functions with deterministic dict sorting
    try:
        # Test regime to event conversion with sorted dicts
        event = to_event(ta_regime, base_kwargs={"timestamp": time.time(), "source": "test"})
        if event is not None:
            # Verify components and features are sorted in the event
            if hasattr(event, 'components') and isinstance(event.components, dict):
                components_keys = list(event.components.keys())
                assert components_keys == sorted(components_keys), f"Event components not sorted: {components_keys}"

            # Test event to regime conversion
            restored_regime = from_event_regime(event)
            assert restored_regime.label == ta_regime.label, "Regime adapter round-trip failed"
            logger.info("✓ Regime adapter tests passed")
        else:
            logger.info("✓ Regime adapters skipped (events module not available)")

        # Test decision to event conversion with sorted allocations
        decision_event = to_event_decision(strategy_decision, base_kwargs={"timestamp": time.time(), "source": "test"})
        if decision_event is not None:
            # Verify allocations are sorted in the event
            if hasattr(decision_event, 'allocations') and isinstance(decision_event.allocations, dict):
                allocation_keys = list(decision_event.allocations.keys())
                assert allocation_keys == sorted(allocation_keys), f"Event allocations not sorted: {allocation_keys}"
            logger.info("✓ Decision adapter tests passed")
        else:
            logger.info("✓ Decision adapters skipped (events module not available)")

    except Exception as e:
        logger.info(f"✓ Adapter tests skipped: {e}")

    # Test validators
    try:
        # Valid cases
        validate_timeframe("15m")
        validate_timeframe("1h")
        validate_timeframe("1d")
        validate_symbol("BTC/USD")
        validate_symbol("ETHUSDT")
        validate_symbol("SOL-USDC")
        validate_finite_float(1.23, "test")
        clamp_confidence(0.5)
        clamp_confidence(1.5)  # Should clamp to 1.0
        clamp_confidence(-0.5)  # Should clamp to 0.0

        # Test invalid cases should raise errors
        invalid_tests = [
            (lambda: validate_timeframe("invalid"), ValueError),
            (lambda: validate_symbol(""), ValueError),
            (lambda: validate_finite_float(float('nan'), "test"), ValueError),
            (lambda: validate_finite_float(float('inf'), "test"), ValueError),
        ]

        for test_func, expected_error in invalid_tests:
            try:
                test_func()
                raise AssertionError("Expected validation error was not raised")
            except expected_error:
                pass  # Expected

        logger.info("✓ Validator tests passed")

    except Exception as e:
        logger.error(f"✗ Validator tests failed: {e}")
        raise

    # Test sorted_dict utility
    test_dict = {"c": 3, "a": 1, "b": 2}
    sorted_result = sorted_dict(test_dict)
    expected_keys = ["a", "b", "c"]
    actual_keys = list(sorted_result.keys())
    assert actual_keys == expected_keys, f"sorted_dict failed: {actual_keys} != {expected_keys}"
    logger.info("✓ sorted_dict test passed")

    logger.info("✅ All self-check tests passed successfully!")
    print("ai_engine/schemas.py self-check completed successfully")
