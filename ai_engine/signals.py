# ai_engine/signals.py
"""
Deterministic “trading signal brain” for Crypto AI Bot.

- Pure logic (no I/O, no wall-clock in decision paths)
- Pydantic v2 contracts (frozen, extra='forbid')
- Deterministic serialization (sorted dict keys)
- Risk-aware fusion of TA / Macro / Sentiment with market hygiene filters
- Explainable outputs + stable decision hash

Example:
    from ai_engine.signals import (
        make_signal, signals_for_universe,
        FusionConfig, RiskFiltersConfig, RegimeBundle, HygieneSnapshot
    )

    # Minimal regime-like objects (duck-typed; only label+confidence+components used)
    ta = type("Reg", (), {"label":"bull","confidence":0.8,"components":{"trend":0.6,"mom":0.5}})
    mc = type("Reg", (), {"label":"bull","confidence":0.6,"components":{"liquidity":0.3,"risk":0.2}})
    se = type("Reg", (), {"label":"chop","confidence":0.4,"components":{"news":0.1,"social":-0.05}})

    hyg = HygieneSnapshot(spread_bps=8.0, est_vol_1h=0.9, data_age_ms=1500, liquidity_flag="ok")

    sig = make_signal(
        symbol="BTCUSDT", timeframe="1m",
        regimes=RegimeBundle(ta=ta, macro=mc, sentiment=se),
        hyg=hyg, fcfg=FusionConfig(), rcfg=RiskFiltersConfig()
    )
    print(sig.side, round(sig.score, 3), round(sig.confidence, 3), sig.filters_applied)
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from statistics import mean
from typing import Any, Dict, List, Literal, Mapping, Optional, Tuple, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

logger = logging.getLogger(__name__)

# -----------------------------
# Regexes & types
# -----------------------------

_TIMEFRAME_RE = re.compile(r"^\d+[mhdw]$")
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,20}([:/-][A-Z0-9]{2,20})?$")

Side = Literal["long", "short", "none"]
RegimeLabel = Literal["bull", "bear", "chop"]

T = TypeVar("T")


# -----------------------------
# Config models (Pydantic v2)
# -----------------------------

class FusionConfig(BaseModel):
    """Weights and thresholds for regime fusion."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    weights: Dict[str, float] = Field(default_factory=lambda: {"ta": 0.40, "macro": 0.35, "sentiment": 0.25})
    hygiene_weight: float = 0.15
    thresholds: Dict[str, float] = Field(default_factory=lambda: {"long": 0.35, "short": -0.35, "chop_abs": 0.15})
    softclip_k: float = 3.0

    @field_validator("hygiene_weight")
    @classmethod
    def _check_hw(cls, v: float) -> float:
        return _finite(v, "hygiene_weight")

    @field_validator("softclip_k")
    @classmethod
    def _check_k(cls, v: float) -> float:
        v = _finite(v, "softclip_k")
        if v <= 0:
            raise ValueError("softclip_k must be > 0")
        return v

    @field_validator("thresholds")
    @classmethod
    def _check_thresholds(cls, v: Mapping[str, float]) -> Mapping[str, float]:
        for k in ("long", "short", "chop_abs"):
            if k not in v:
                raise ValueError(f"thresholds missing key: {k}")
            _finite(float(v[k]), f"thresholds.{k}")
        if not (-1.0 <= v["short"] < 0 < v["long"] <= 1.0):
            raise ValueError("thresholds must satisfy: short∈[-1,0), long∈(0,1], and short<0<long")
        ca = float(v["chop_abs"])
        if not (0 <= ca < min(v["long"], -v["short"])):
            raise ValueError("thresholds.chop_abs must be >=0 and < min(long, -short)")
        return dict(v)

    @field_validator("weights")
    @classmethod
    def _check_weights(cls, v: Mapping[str, float]) -> Mapping[str, float]:
        # Only allow keys in {'ta','macro','sentiment'}
        allowed = {"ta", "macro", "sentiment"}
        for k in v:
            if k not in allowed:
                raise ValueError(f"weights: unexpected key {k!r}")
            _finite(float(v[k]), f"weights.{k}")
        # All non-negative
        if any(float(v[k]) < 0 for k in v):
            raise ValueError("weights must be non-negative")
        if sum(v.values()) == 0:
            raise ValueError("weights sum must be > 0")
        return dict(v)


class RiskFiltersConfig(BaseModel):
    """Market hygiene and trade gating rules."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_spread_bps: float = 25.0
    max_data_age_ms: int = 120_000
    max_vol_cap: float = 0.0  # 0 disables
    liquidity_rules: Dict[str, float] = Field(default_factory=lambda: {"thin": -0.15, "bad": -0.35})
    min_component_conf: float = 0.15
    min_conf_to_trade: float = 0.50
    confidence_floor_chop: float = 0.15

    @field_validator("max_spread_bps", "max_vol_cap", "min_component_conf", "min_conf_to_trade", "confidence_floor_chop")
    @classmethod
    def _finite_float(cls, v: float, info) -> float:
        return _finite(v, info.field_name)

    @field_validator("max_data_age_ms")
    @classmethod
    def _finite_int(cls, v: int) -> int:
        if v < 0:
            raise ValueError("max_data_age_ms must be >= 0")
        return int(v)

    @field_validator("liquidity_rules")
    @classmethod
    def _check_liq_rules(cls, v: Mapping[str, float]) -> Mapping[str, float]:
        out = {}
        for k, val in v.items():
            if k not in {"ok", "thin", "bad"}:
                raise ValueError("liquidity_rules keys must be in {'ok','thin','bad'}")
            out[k] = _finite(float(val), f"liquidity_rules.{k}")
            if val > 0:
                raise ValueError("liquidity_rules penalties must be <= 0")
        return out


class HygieneSnapshot(BaseModel):
    """Per-symbol market hygiene inputs."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    spread_bps: float = 0.0
    est_vol_1h: float = 0.0
    data_age_ms: int = 0
    liquidity_flag: Literal["ok", "thin", "bad"] = "ok"

    @field_validator("spread_bps", "est_vol_1h")
    @classmethod
    def _finite_nonneg(cls, v: float, info) -> float:
        v = _finite(v, info.field_name)
        if v < 0:
            raise ValueError(f"{info.field_name} must be >= 0")
        return v

    @field_validator("data_age_ms")
    @classmethod
    def _nonneg_age(cls, v: int) -> int:
        if v < 0:
            raise ValueError("data_age_ms must be >= 0")
        return int(v)


class RegimeBundle(BaseModel):
    """
    Bundle of regime-like objects. Duck-typed:
    expects attributes `.label` ('bull'|'bear'|'chop'), `.confidence` (0..1),
    and optionally `.components` (dict[str,float]).
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    ta: Optional[Any] = None
    macro: Optional[Any] = None
    sentiment: Optional[Any] = None


class Signal(BaseModel):
    """Final fused signal with explainability and deterministic hash."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    timeframe: str
    score: float
    side: Side
    confidence: float
    components: Dict[str, float]
    filters_applied: List[str] = Field(default_factory=list)
    explain: str = ""
    decision_hash: str = ""

    @field_validator("symbol")
    @classmethod
    def _symbol_ok(cls, v: str) -> str:
        if not _SYMBOL_RE.fullmatch(v or ""):
            raise ValueError(f"invalid symbol: {v!r}")
        return v

    @field_validator("timeframe")
    @classmethod
    def _tf_ok(cls, v: str) -> str:
        if not _TIMEFRAME_RE.fullmatch(v or ""):
            raise ValueError(f"invalid timeframe: {v!r}")
        return v

    @field_validator("score")
    @classmethod
    def _score_bounds(cls, v: float) -> float:
        return max(-1.0, min(1.0, _finite(v, "score")))

    @field_validator("confidence")
    @classmethod
    def _conf_bounds(cls, v: float) -> float:
        v = _finite(v, "confidence")
        return 0.0 if v < 0 else (1.0 if v > 1 else v)

    @field_validator("components")
    @classmethod
    def _components_ok(cls, v: Mapping[str, float]) -> Dict[str, float]:
        out = {}
        for k, val in v.items():
            out[str(k)] = max(-1.0, min(1.0, _finite(float(val), f"components.{k}")))
        return _sorted_dict(out)

    @field_serializer("components", mode="plain")
    def _ser_components(self, v: Mapping[str, float]) -> Mapping[str, float]:
        return _sorted_dict(dict(v))


class SignalSet(BaseModel):
    """Deterministic set of signals keyed by symbol."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    signals: Dict[str, Signal] = Field(default_factory=dict)

    @field_serializer("signals", mode="plain")
    def _ser_signals(self, v: Mapping[str, Signal]) -> Mapping[str, Signal]:
        # sort by key for deterministic JSON
        return {k: v[k] for k in sorted(v)}


# -----------------------------
# Public API functions
# -----------------------------

def map_label_to_score(label: RegimeLabel) -> float:
    """Map a regime label to base score."""
    if label == "bull":
        return 1.0
    if label == "bear":
        return -1.0
    return 0.0


def fuse_regimes(regimes: RegimeBundle, cfg: FusionConfig) -> Tuple[float, Dict[str, float]]:
    """
    Fuse TA/Macro/Sentiment into a score in [-1,1] (without hygiene),
    and return per-component scores (ta/macro/sentiment) in [-1,1].
    """
    per: Dict[str, float] = {"ta": 0.0, "macro": 0.0, "sentiment": 0.0}
    present: List[str] = []
    confs: Dict[str, float] = {}

    for key in ("ta", "macro", "sentiment"):
        reg = getattr(regimes, key)
        if reg is None:
            continue
        try:
            label = str(getattr(reg, "label"))
            conf = float(getattr(reg, "confidence"))
            _ = _finite(conf, f"{key}.confidence")
            if label not in ("bull", "bear", "chop"):
                raise ValueError(f"{key}.label must be one of 'bull','bear','chop'")
            comps = getattr(reg, "components", {}) or {}
            comp_vals: List[float] = []
            for ck, cv in getattr(comps, "items", lambda: [])():
                comp_vals.append(max(-1.0, min(1.0, _finite(float(cv), f"{key}.components.{ck}"))))
            if comp_vals:
                raw = mean(comp_vals)
            else:
                raw = map_label_to_score(label)
            s = _tanh_clip(raw, cfg.softclip_k) * max(0.0, min(1.0, conf))
            per[key] = max(-1.0, min(1.0, s))
            present.append(key)
            confs[key] = conf
        except Exception as e:
            logger.debug("Skipping regime %s due to parse/validation error: %s", key, e)

    # Re-normalize weights across present regimes
    if not present:
        return 0.0, per

    w_sum = sum(cfg.weights.get(k, 0.0) for k in present)
    if w_sum <= 0:
        # fallback: equal weights
        norm = {k: 1.0 / len(present) for k in present}
    else:
        norm = {k: cfg.weights.get(k, 0.0) / w_sum for k in present}

    fused = sum(norm[k] * per[k] for k in present)
    fused = _tanh_clip(fused, cfg.softclip_k)
    return fused, per


def apply_hygiene(hyg: HygieneSnapshot, cfg: RiskFiltersConfig) -> Tuple[float, List[str]]:
    """
    Compute a deterministic hygiene penalty (<=0) and list of filters applied.
    Returns:
        (penalty_total <= 0, filters_applied)
    """
    filters: List[str] = []
    total_penalty = 0.0

    # Spread
    if hyg.spread_bps > cfg.max_spread_bps:
        # proportional penalty capped at -0.6
        over = (hyg.spread_bps - cfg.max_spread_bps) / max(cfg.max_spread_bps, 1e-9)
        penalty = -min(0.6, max(0.0, over))
        total_penalty += penalty
        filters.append("spread_cap")

    # Staleness
    if hyg.data_age_ms > cfg.max_data_age_ms:
        over = (hyg.data_age_ms - cfg.max_data_age_ms) / max(cfg.max_data_age_ms, 1)
        penalty = -min(0.5, max(0.0, over))
        total_penalty += penalty
        filters.append("stale_data")

    # Vol cap
    if cfg.max_vol_cap > 0 and hyg.est_vol_1h > cfg.max_vol_cap:
        over = (hyg.est_vol_1h - cfg.max_vol_cap) / max(cfg.max_vol_cap, 1e-9)
        penalty = -min(0.4, max(0.0, over))
        total_penalty += penalty
        filters.append("vol_cap")

    # Liquidity
    liq_pen = cfg.liquidity_rules.get(hyg.liquidity_flag, 0.0)
    if liq_pen < 0:
        total_penalty += liq_pen
        filters.append(f"liquidity_{hyg.liquidity_flag}")

    # Bound: penalty_total ∈ [-1, 0]
    total_penalty = max(-1.0, min(0.0, total_penalty))
    return total_penalty, filters


def label_side(score: float, thresholds: Mapping[str, float]) -> Side:
    """Assign side from fused score and thresholds."""
    score = _finite(score, "score")
    ca = float(thresholds.get("chop_abs", 0.15))
    lo = float(thresholds.get("short", -0.35))
    hi = float(thresholds.get("long", 0.35))

    if abs(score) < ca:
        return "none"
    if score >= hi:
        return "long"
    if score <= lo:
        return "short"
    return "none"


def make_signal(
    symbol: str,
    timeframe: str,
    regimes: RegimeBundle,
    hyg: HygieneSnapshot,
    fcfg: FusionConfig,
    rcfg: RiskFiltersConfig,
) -> Signal:
    """
    Build a deterministic Signal from regimes + hygiene.
    On unexpected error, returns a safe 'none' signal with confidence 0 and logs the exception.
    """
    try:
        # Pre-validate symbol/timeframe (Signal model will validate again)
        if not _SYMBOL_RE.fullmatch(symbol or ""):
            raise ValueError(f"invalid symbol: {symbol!r}")
        if not _TIMEFRAME_RE.fullmatch(timeframe or ""):
            raise ValueError(f"invalid timeframe: {timeframe!r}")

        fused_no_hyg, per = fuse_regimes(regimes, fcfg)

        penalty, filters = apply_hygiene(hyg, rcfg)
        hygiene_score = max(-1.0, min(0.0, -abs(penalty)))  # purely negative or zero

        fused_final = _tanh_clip(fused_no_hyg + fcfg.hygiene_weight * hygiene_score, fcfg.softclip_k)

        # Base confidence from available regimes
        present = [getattr(regimes, k) for k in ("ta", "macro", "sentiment") if getattr(regimes, k) is not None]
        if present:
            confs = []
            for k in ("ta", "macro", "sentiment"):
                r = getattr(regimes, k)
                if r is None:
                    continue
                try:
                    confs.append(max(0.0, min(1.0, _finite(float(getattr(r, "confidence")), f"{k}.confidence"))))
                except Exception:
                    pass
            base_conf = mean(confs) if confs else rcfg.confidence_floor_chop
        else:
            base_conf = rcfg.confidence_floor_chop

        # Missing regime penalty
        base_conf *= (len(present) / 3.0) if present else 0.5

        # Low component confidence haircut
        low_conf = False
        for k in ("ta", "macro", "sentiment"):
            r = getattr(regimes, k)
            if r is None:
                continue
            try:
                if float(getattr(r, "confidence")) < rcfg.min_component_conf:
                    low_conf = True
                    break
            except Exception:
                pass
        if low_conf:
            base_conf *= 0.8

        # Hygiene penalty reduces confidence (penalty <= 0)
        base_conf *= max(0.0, 1.0 + 0.5 * penalty)  # penalty is negative; reduces factor

        # Clamp
        confidence = 0.0 if base_conf < 0 else (1.0 if base_conf > 1 else base_conf)

        # Side decision; enforce min_conf_to_trade
        side = label_side(fused_final, fcfg.thresholds)
        if confidence < rcfg.min_conf_to_trade:
            side = "none"
            if "low_confidence" not in filters:
                filters.append("low_confidence")

        # Build components dict (include hygiene)
        components = _sorted_dict({
            "ta": per.get("ta", 0.0),
            "macro": per.get("macro", 0.0),
            "sentiment": per.get("sentiment", 0.0),
            "hygiene": hygiene_score,
        })

        explain = _compose_explain(fused_final, components, filters)

        sig = Signal(
            symbol=symbol,
            timeframe=timeframe,
            score=fused_final,
            side=side,
            confidence=confidence,
            components=components,
            filters_applied=list(dict.fromkeys(filters)),  # preserve order, dedupe
            explain=explain,
            decision_hash="",  # set next
        )

        # Deterministic decision hash (exclude the hash field itself)
        sig = sig.model_copy(update={"decision_hash": _sha256_sorted(sig, exclude_keys={"decision_hash"})})
        logger.info(
            "Signal %s %s: side=%s score=%.3f conf=%.3f filters=%s | %s",
            symbol, timeframe, sig.side, sig.score, sig.confidence, ",".join(sig.filters_applied), sig.explain
        )
        logger.debug("Components %s: %s", symbol, sig.components)
        return sig
    except Exception:
        logger.exception("make_signal failed; returning safe NOOP")
        # Return safe NOOP
        fallback = Signal(
            symbol=symbol if _SYMBOL_RE.fullmatch(symbol or "") else "UNKNOWN",
            timeframe=timeframe if _TIMEFRAME_RE.fullmatch(timeframe or "") else "1m",
            score=0.0,
            side="none",
            confidence=0.0,
            components={"ta": 0.0, "macro": 0.0, "sentiment": 0.0, "hygiene": 0.0},
            filters_applied=["error"],
            explain="error",
            decision_hash="",
        )
        return fallback.model_copy(update={"decision_hash": _sha256_sorted(fallback, exclude_keys={"decision_hash"})})


def signals_for_universe(
    inputs: Dict[str, Tuple[RegimeBundle, HygieneSnapshot]],
    timeframe: str,
    fcfg: FusionConfig,
    rcfg: RiskFiltersConfig,
) -> SignalSet:
    """
    Build signals for a dict of symbol -> (RegimeBundle, HygieneSnapshot).
    Deterministic order by symbol key.
    """
    out: Dict[str, Signal] = {}
    for sym in sorted(inputs):
        bundles, hyg = inputs[sym]
        out[sym] = make_signal(sym, timeframe, bundles, hyg, fcfg, rcfg)
    return SignalSet(signals=out)


# -----------------------------
# Internal helpers
# -----------------------------

def _tanh_clip(x: float, k: float) -> float:
    """Smoothly clip to [-1,1] using tanh with scale k (>0)."""
    x = _finite(x, "clip.x")
    k = _finite(k, "clip.k")
    if k <= 0:
        raise ValueError("softclip scale k must be > 0")
    y = math.tanh(x / k)
    # bound (just in case of numerical oddities)
    return -1.0 if y < -1.0 else (1.0 if y > 1.0 else y)


def _finite(x: float, name: str) -> float:
    """Ensure x is a finite float."""
    try:
        xf = float(x)
    except Exception as e:
        raise ValueError(f"{name} not a float-like value: {x!r}") from e
    if not math.isfinite(xf):
        raise ValueError(f"{name} must be finite, got {xf!r}")
    return xf


def _sorted_dict(d: Mapping[str, T]) -> Dict[str, T]:
    """Deterministically sort dict by keys."""
    return {k: d[k] for k in sorted(d)}


def _sha256_sorted(obj: Any, exclude_keys: set[str] | None = None) -> str:
    """
    Deterministic SHA256 over JSON of a model or dict, with sorted keys.
    Excludes keys in `exclude_keys`.
    """
    if exclude_keys is None:
        exclude_keys = set()
    if isinstance(obj, BaseModel):
        data = obj.model_dump()
    elif isinstance(obj, dict):
        data = dict(obj)
    else:
        # try getattr path for models
        data = json.loads(json.dumps(obj, default=lambda o: getattr(o, "__dict__", str(o))))
    # Exclude keys
    for k in exclude_keys:
        if k in data:
            del data[k]
    # Sort inner dicts as well for stability
    def _sort_any(v: Any) -> Any:
        if isinstance(v, dict):
            return {k: _sort_any(v[k]) for k in sorted(v)}
        if isinstance(v, list):
            return [_sort_any(x) for x in v]
        return v

    stable = _sort_any(data)
    s = json.dumps(stable, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _compose_explain(score: float, components: Mapping[str, float], filters: List[str]) -> str:
    """Create a concise one-liner explanation."""
    # Top drivers by absolute magnitude among ta/macro/sentiment
    drivers = [(k, abs(v)) for k, v in components.items() if k in ("ta", "macro", "sentiment")]
    drivers.sort(key=lambda kv: kv[1], reverse=True)
    top = [k for k, _ in drivers[:2]]
    filt = ",".join(filters) if filters else "none"
    side = "long" if score > 0 else ("short" if score < 0 else "none")
    return f"{side} bias; drivers={'+'.join(top) if top else 'n/a'}; filters={filt}"


# -----------------------------
# Self-check
# -----------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Synthetic regimes (duck-typed)
    TA = type("Reg", (), {})
    MAC = type("Reg", (), {})
    SE = type("Reg", (), {})

    ta = TA(); ta.label = "bull"; ta.confidence = 0.8; ta.components = {"trend": 0.6, "mom": 0.5}
    mc = MAC(); mc.label = "bull"; mc.confidence = 0.6; mc.components = {"liquidity": 0.3, "risk": 0.2}
    se = SE(); se.label = "chop"; se.confidence = 0.4; se.components = {"news": 0.1, "social": -0.05}

    hyg_ok = HygieneSnapshot(spread_bps=8.0, est_vol_1h=0.9, data_age_ms=1500, liquidity_flag="ok")
    hyg_bad = HygieneSnapshot(spread_bps=40.0, est_vol_1h=1.2, data_age_ms=240000, liquidity_flag="thin")

    fcfg = FusionConfig()
    rcfg = RiskFiltersConfig()

    rbundle = RegimeBundle(ta=ta, macro=mc, sentiment=se)

    s1 = make_signal("BTCUSDT", "1m", rbundle, hyg_ok, fcfg, rcfg)
    s2 = make_signal("ETHUSDT", "1m", rbundle, hyg_bad, fcfg, rcfg)

    uni = {"BTCUSDT": (rbundle, hyg_ok), "ETHUSDT": (rbundle, hyg_bad)}
    ss = signals_for_universe(uni, "1m", fcfg, rcfg)
    logger.info("Universe signals: %s", ",".join(f"{k}:{v.side}" for k, v in ss.signals.items()))
