"""
mcp/schemas.py
Canonical, versioned event contracts for crypto-ai-bot agents.

- Immutable Pydantic v2 models
- Backward/forward compatibility (aliases, versioning)
- Deterministic, JSON-safe serialization for sets/dicts
- Exchange-aware guardrails (Kraken defaults)
- JSON Schema export (write_json_schemas)

All timestamps are UTC epoch seconds.
"""

from __future__ import annotations

import json
import time
import uuid
import re
from pathlib import Path
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Union, Literal, Annotated

from pydantic import (
    BaseModel,
    Field,
    ConfigDict,
    field_validator,
    model_validator,
    field_serializer,
    AliasChoices,
)

__all__ = [
    "OrderSide",
    "OrderType",
    "TimeInForce",
    "Signal",
    "OrderIntent",
    "PolicyUpdate",
    "MetricsTick",
    "export_json_schema",
    "write_json_schemas",
    "SIDE_MAP",
    "OTYPE_MAP",
]

# Kraken shorthand mappings (useful for adapters)
SIDE_MAP = {"b": "buy", "s": "sell"}
OTYPE_MAP = {"l": "limit", "m": "market"}

# Validation patterns
_SYMBOL_RE = re.compile(r"^[A-Z0-9]+/[A-Z0-9]+$", re.ASCII)
_TIMEFRAME_RE = re.compile(r"^\d+(s|m|h|d)$", re.ASCII)

# Type annotations for safer numeric constraints
NonNegFloat = Annotated[float, Field(ge=0.0)]
UnitFloat = Annotated[float, Field(ge=0.0, le=1.0)]


# --------------------------
# Base + shared infrastructure
# --------------------------
class VersionedBaseModel(BaseModel):
    """
    Base model with versioning, immutability, JSON helpers, and traceability.
    """
    schema_version: str = Field(default="1.0", description="Schema version for compatibility")
    type: str = Field(
        validation_alias=AliasChoices("type", "event_type"),
        description="Event type discriminator",
    )
    id: Optional[str] = Field(default=None, description="Event id (UUIDv4)")
    correlation_id: Optional[str] = Field(default=None, description="Trace id / flow id")

    model_config = ConfigDict(
        frozen=True,
        validate_assignment=False,
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
        use_enum_values=True,
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_and_seed_ids(cls, data: Any) -> Any:
        """
        - Accept legacy 'version' alias for 'schema_version'
        - Seed 'id' with UUIDv4 if absent
        """
        if not isinstance(data, dict):
            return data
        d = dict(data)
        if "version" in d and "schema_version" not in d:
            d["schema_version"] = d.pop("version")
        d.setdefault("id", str(uuid.uuid4()))
        return d

    # Convenience helpers
    def to_json(self) -> str:
        return self.model_dump_json(exclude_none=True, by_alias=True)

    @classmethod
    def from_json(cls, s: str) -> "VersionedBaseModel":
        return cls.model_validate_json(s)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(exclude_none=True, by_alias=True)


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class TimeInForce(str, Enum):
    GTC = "GTC"  # Good-Til-Cancel
    IOC = "IOC"  # Immediate-Or-Cancel (Kraken spot: not supported)
    FOK = "FOK"  # Fill-Or-Kill (Kraken spot: not supported)


# --------------------------
# Event: Signal
# --------------------------
class Signal(VersionedBaseModel):
    """
    Trade signal emitted by analysts/strategies.
    """
    type: Literal["signal"] = "signal"

    # Defaults align with current exchange usage; portable to others
    exchange: Optional[str] = Field(default="kraken", description="Target exchange")
    source: Optional[str] = Field(default="mcp", description="Producer/source identity")

    strategy: str = Field(description="Strategy name", examples=["scalp", "trend_following"])
    symbol: str = Field(description="Trading symbol", examples=["BTC/USD", "ETH/USD"])
    timeframe: str = Field(description="Timeframe", examples=["15s", "1m", "3m", "5m"])
    side: OrderSide = Field(description="Trade direction")
    confidence: UnitFloat = Field(description="Signal confidence 0..1")
    features: Optional[Dict[str, Union[float, int]]] = Field(
        default=None, description="Numeric feature values"
    )
    risk: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Risk parameters",
        examples=[{"sl_bps": 5, "tp_bps": [10, 20], "ttl_s": 120}],
    )
    notes: Optional[str] = Field(default=None, description="Optional notes")
    timestamp: float = Field(
        default_factory=lambda: float(time.time()), description="UTC epoch seconds"
    )

    @model_validator(mode="before")
    @classmethod
    def _aliases(cls, data: Any) -> Any:
        """
        Back-compat / external aliases:
        - pair -> symbol (Kraken WS, Redis streams)
        - interval -> timeframe (if some producer uses 'interval')
        """
        if not isinstance(data, dict):
            return data
        d = dict(data)
        if "pair" in d and "symbol" not in d:
            d["symbol"] = d.pop("pair")
        if "interval" in d and "timeframe" not in d:
            d["timeframe"] = d.pop("interval")
        return d

    @field_validator("symbol")
    @classmethod
    def _validate_symbol(cls, v: str) -> str:
        """Validate and normalize symbol format"""
        v = v.upper()
        if not _SYMBOL_RE.match(v):
            raise ValueError("symbol must look like BASE/QUOTE, e.g. BTC/USD")
        return v

    @field_validator("timeframe")
    @classmethod
    def _validate_timeframe(cls, v: str) -> str:
        """Validate timeframe format"""
        if not _TIMEFRAME_RE.match(v):
            raise ValueError("timeframe must be like 15s, 1m, 3m, 1h, 1d")
        return v

    @field_validator("risk")
    @classmethod
    def _validate_and_alias_risk(
        cls, v: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Accept aliases and validate limits:
        - stop_loss_bps -> sl_bps
        - target_bps -> tp_bps (normalize scalar to list)
        - constraints: sl_bps >= 1, tp_bps list length <= 6, each >= 1
        """
        if v is None:
            return v

        r = dict(v)

        # aliases
        if "stop_loss_bps" in r and "sl_bps" not in r:
            r["sl_bps"] = r.pop("stop_loss_bps")
        if "target_bps" in r and "tp_bps" not in r:
            tgt = r.pop("target_bps")
            r["tp_bps"] = [int(tgt)] if isinstance(tgt, (int, float)) else tgt

        # validate
        if "sl_bps" in r and r["sl_bps"] < 1:
            raise ValueError("sl_bps must be ≥ 1")

        if "tp_bps" in r:
            tp = r["tp_bps"]
            if not isinstance(tp, list):
                raise ValueError("tp_bps must be a list")
            if len(tp) > 6:
                raise ValueError("tp_bps cannot exceed 6 levels")
            if any(bps < 1 for bps in tp):
                raise ValueError("All tp_bps values must be ≥ 1")

        return r

    @classmethod
    def example(cls) -> "Signal":
        return cls(
            strategy="scalp",
            symbol="BTC/USD",
            timeframe="15s",
            side=OrderSide.BUY,
            confidence=0.85,
            features={"volume_ratio": 1.2, "book_imbalance": 0.7},
            risk={"sl_bps": 5, "tp_bps": [10, 15], "ttl_s": 120},
            notes="Strong book imbalance signal",
        )


# --------------------------
# Event: OrderIntent
# --------------------------
class OrderIntent(VersionedBaseModel):
    """
    Sized order request after risk/portfolio checks.
    """
    type: Literal["order.intent"] = "order.intent"

    exchange: Optional[str] = Field(default="kraken", description="Target exchange")
    symbol: str = Field(description="Trading symbol", examples=["BTC/USD"])
    side: OrderSide = Field(description="Trade direction")
    order_type: OrderType = Field(description="Order type")

    price: Optional[NonNegFloat] = Field(
        default=None, description="Price for limit orders (None for market)"
    )
    size_quote_usd: Annotated[float, Field(ge=1.0)] = Field(description="Order size in USD")
    reduce_only: bool = Field(default=False, description="Reduce-only flag")
    post_only: bool = Field(default=False, description="Post-only flag (limit-only)")
    tif: TimeInForce = Field(default=TimeInForce.GTC, description="Time in force")
    metadata: Optional[Dict[str, Union[str, int, float]]] = Field(
        default=None, description="Order metadata"
    )
    timestamp: float = Field(
        default_factory=lambda: float(time.time()), description="UTC epoch seconds"
    )

    @field_validator("symbol")
    @classmethod
    def _validate_symbol(cls, v: str) -> str:
        """Validate and normalize symbol format"""
        v = v.upper()
        if not _SYMBOL_RE.match(v):
            raise ValueError("symbol must look like BASE/QUOTE, e.g. BTC/USD")
        return v

    @field_validator("price")
    @classmethod
    def _price_guard(cls, v: Optional[float], info) -> Optional[float]:
        ot = (info.data or {}).get("order_type")
        if ot == OrderType.LIMIT and v is None:
            raise ValueError("Price is required for limit orders")
        if ot == OrderType.MARKET and v is not None:
            raise ValueError("Price must be None for market orders")
        return v

    @field_validator("post_only")
    @classmethod
    def _post_only_guard(cls, v: bool, info) -> bool:
        if v and (info.data or {}).get("order_type") != OrderType.LIMIT:
            raise ValueError("post_only is only available for limit orders")
        return v

    @field_validator("tif")
    @classmethod
    def _kraken_tif_guard(cls, v: TimeInForce, info) -> TimeInForce:
        """
        Kraken spot does not support IOC/FOK. We guard if exchange is explicitly Kraken.
        """
        ex = (info.data or {}).get("exchange")
        meta = (info.data or {}).get("metadata") or {}
        m_ex = (meta.get("exchange") or "").lower()
        target = (m_ex or (ex or "")).lower()
        if target == "kraken" and v != TimeInForce.GTC:
            raise ValueError("Kraken spot supports only GTC")
        return v

    @classmethod
    def example(cls) -> "OrderIntent":
        return cls(
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=45000.0,
            size_quote_usd=1000.0,
            reduce_only=False,
            post_only=True,
            tif=TimeInForce.GTC,
            metadata={"strategy": "scalp", "signal_id": "sig_123"},
        )


# --------------------------
# Event: PolicyUpdate
# --------------------------
class PolicyUpdate(VersionedBaseModel):
    """
    Runtime policy broadcast from MCP to agents.
    """
    type: Literal["policy.update"] = "policy.update"

    active_strategies: Set[str] = Field(description="Set of active strategies")
    allocations: Dict[str, float] = Field(
        description="Strategy allocations (sum ~= 1.0)",
        examples=[{"scalp": 0.4, "trend_following": 0.6}],
    )
    risk_overrides: Optional[Dict[str, Union[int, float, bool]]] = Field(
        default=None,
        description="Risk parameter overrides",
        examples=[{"daily_stop": -0.03, "max_spread_bps": 12}],
    )
    notes: Optional[str] = Field(default=None, description="Optional notes")
    timestamp: float = Field(
        default_factory=lambda: float(time.time()), description="UTC epoch seconds"
    )

    @field_serializer("active_strategies")
    def _serialize_active_strategies(self, v: Set[str]) -> List[str]:
        """Serialize set as sorted list for JSON-safe, deterministic output"""
        return sorted(v)

    @field_serializer("allocations")
    def _serialize_allocations(self, v: Dict[str, float]) -> Dict[str, float]:
        """Serialize dict with sorted keys for deterministic output"""
        return {k: v[k] for k in sorted(v.keys())}

    @field_validator("active_strategies")
    @classmethod
    def _non_empty(cls, v: Set[str]) -> Set[str]:
        if not v:
            raise ValueError("active_strategies cannot be empty")
        return v

    @field_validator("allocations")
    @classmethod
    def _allocations_sum_guard(cls, v: Dict[str, float]) -> Dict[str, float]:
        total = sum(v.values())
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Allocations must sum to ~1.0, got {total:.3f}")
        for name, alloc in v.items():
            if not 0 <= alloc <= 1:
                raise ValueError(f"Allocation for {name} must be in [0,1], got {alloc}")
        return v

    @field_validator("risk_overrides")
    @classmethod
    def _risk_overrides_guard(
        cls, v: Optional[Dict[str, Union[int, float, bool]]]
    ) -> Optional[Dict[str, Union[int, float, bool]]]:
        if v is None:
            return v
        if "max_spread_bps" in v and v["max_spread_bps"] < 0:
            raise ValueError("max_spread_bps must be ≥ 0")
        return v

    @classmethod
    def example(cls) -> "PolicyUpdate":
        return cls(
            active_strategies={"scalp", "trend_following"},
            allocations={"scalp": 0.4, "trend_following": 0.6},
            risk_overrides={"daily_stop": -0.03, "max_spread_bps": 5, "cooldown_after_loss_s": 90},
            notes="Increased scalp allocation due to favorable market conditions",
        )


# --------------------------
# Event: MetricsTick
# --------------------------
class MetricsTick(VersionedBaseModel):
    """
    Periodic metrics snapshot from agents to MCP.
    """
    type: Literal["metrics.tick"] = "metrics.tick"

    pnl: Dict[str, float] = Field(
        description="P&L metrics; must include realized/unrealized",
        examples=[{"realized": 150.25, "unrealized": -45.50, "fees": 12.75}],
    )
    slippage_bps_p50: NonNegFloat = Field(description="50th percentile slippage in bps")
    latency_ms_p95: NonNegFloat = Field(description="95th percentile latency in ms")
    win_rate_1h: UnitFloat = Field(description="1-hour win rate")
    drawdown_daily: float = Field(description="Daily drawdown (negative acceptable)")
    errors_rate: NonNegFloat = Field(description="Error rate")
    timestamp: float = Field(
        default_factory=lambda: float(time.time()), description="UTC epoch seconds"
    )

    @field_validator("pnl")
    @classmethod
    def _pnl_guard(cls, v: Dict[str, float]) -> Dict[str, float]:
        required = {"realized", "unrealized"}
        if not required.issubset(v):
            raise ValueError(f"pnl must include keys {required}, got {set(v)}")
        return v

    @classmethod
    def example(cls) -> "MetricsTick":
        return cls(
            pnl={"realized": 250.75, "unrealized": 120.50, "fees": 18.25},
            slippage_bps_p50=2.5,
            latency_ms_p95=85.2,
            win_rate_1h=0.62,
            drawdown_daily=-0.015,
            errors_rate=0.002,
        )


# --------------------------
# JSON Schema utilities
# --------------------------
def export_json_schema() -> Dict[str, Dict[str, Any]]:
    """
    Export JSON Schemas for all models. Keys are model names.
    """
    return {
        "Signal": Signal.model_json_schema(),
        "OrderIntent": OrderIntent.model_json_schema(),
        "PolicyUpdate": PolicyUpdate.model_json_schema(),
        "MetricsTick": MetricsTick.model_json_schema(),
    }


def write_json_schemas(out_dir: str = "mcp/schemas") -> Dict[str, str]:
    """
    Write JSON Schemas to disk (filenames: <model>.schema.json, lowercase).
    Returns map of model name to file path.
    """
    out: Dict[str, str] = {}
    p = Path(out_dir)
    p.mkdir(parents=True, exist_ok=True)
    artifacts = export_json_schema()
    for name, schema in artifacts.items():
        path = p / f"{name.lower()}.schema.json"
        path.write_text(json.dumps(schema, indent=2))
        out[name] = str(path)
    return out


# --------------------------
# Test helpers
# --------------------------
def _roundtrip_json(obj: VersionedBaseModel) -> bool:
    """
    Test JSON round-trip serialization.
    """
    try:
        back = type(obj).from_json(obj.to_json())
        return obj.model_dump(mode="json") == back.model_dump(mode="json")
    except Exception:
        return False


# --------------------------
# Smoke test (manual run)
# --------------------------
if __name__ == "__main__":
    models = [
        Signal.example(),
        OrderIntent.example(),
        PolicyUpdate.example(),
        MetricsTick.example(),
    ]
    for m in models:
        assert _roundtrip_json(m), f"Round-trip failed for {type(m).__name__}"
        print(f"✓ {type(m).__name__} round-trip test passed")

    paths = write_json_schemas("mcp/schemas")
    assert len(paths) == 4, f"Expected 4 schemas written, got {len(paths)}"
    print("✓ Schema export & write passed")
    print("All tests passed!")
