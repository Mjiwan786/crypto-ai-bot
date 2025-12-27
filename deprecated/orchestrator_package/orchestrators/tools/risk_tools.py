"""
orchestrator_package/orchestrators/tools/risk_tools.py

Risk & compliance toolkit for crypto-ai-bot. Provides deterministic, unit-testable
utilities for exposure limits, drawdown protection, daily stops, per-symbol caps,
leverage/position caps, volatility/ATR guards, VaR/CVaR estimation, Kelly-fraction
sizing caps, spread/slippage guards, compliance checks, and kill-switches.

Risk Pipeline:
  signal/plan → pre-trade checks → caps/limits → compliance → approve/block → post-trade updates

Integrates with MCP (schemas, marshaling), Redis (state & counters), and emits
lightweight metric events for Prometheus/Grafana. No external network or exchange
SDKs required to import.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from pydantic import Field, field_validator, model_validator

# Import shim pattern for dual-location support
try:
    from config.config_loader import get_config
except Exception:  # pragma: no cover
    from ...config.config_loader import get_config  # type: ignore

try:
    from mcp.schemas import VersionedBaseModel, Signal, OrderIntent
except Exception:  # pragma: no cover
    from ...mcp.schemas import VersionedBaseModel, Signal, OrderIntent  # type: ignore

try:
    from mcp.redis_manager import RedisManager
except Exception:  # pragma: no cover
    from ...mcp.redis_manager import RedisManager  # type: ignore

try:
    from mcp.marshaling import stable_hash, pack_stream_fields
except Exception:  # pragma: no cover
    from ...mcp.marshaling import stable_hash, pack_stream_fields  # type: ignore

try:
    from utils.logger import get_logger
    from utils.timer import timer
except Exception:  # pragma: no cover
    from ...utils.logger import get_logger  # type: ignore
    from ...utils.timer import timer  # type: ignore


# ----------------------------------------------------------------------------------------------------------------------
# Constants & Logging
# ----------------------------------------------------------------------------------------------------------------------

STREAM_KEYS = {
    "metrics": "metrics:ticks",
    "risk_events": "risk:events",
}

METRIC_KINDS = {
    "risk_check": "risk_check",
    "risk_block": "risk_block",
    "risk_update": "risk_update",
}

REASON_CODES = {
    "killswitch": "killswitch_engaged",
    "daily_stop": "daily_stop_hit",
    "compliance": "compliance_violation",
    "spread": "spread_exceeded",
    "slippage": "slippage_exceeded",
    "min_notional": "min_notional_violation",
    "max_notional": "max_notional_violation",
    "max_leverage": "max_leverage_violation",
    "exposure_cap": "exposure_cap_exceeded",
    "var_limit": "var_limit_exceeded",
    "atr_limit": "atr_volatility_exceeded",
    "kelly_limit": "kelly_fraction_exceeded",
    "equity_invalid": "equity_non_positive",
    "price_invalid": "price_non_positive",
}

SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]+/[A-Z0-9]+$")
TIMEFRAME_PATTERN = re.compile(r"^\d+(s|m|h|d|w)$")

logger = get_logger("risk_tools")


# ----------------------------------------------------------------------------------------------------------------------
# Exceptions
# ----------------------------------------------------------------------------------------------------------------------

class RiskConfigError(Exception):
    """Risk configuration validation error"""
    pass


class RiskEvaluationError(Exception):
    """Risk evaluation runtime error"""
    pass


# ----------------------------------------------------------------------------------------------------------------------
# Typed Models
# ----------------------------------------------------------------------------------------------------------------------

class RiskContext(VersionedBaseModel):
    """Runtime inputs required for risk checks"""
    type: str = "risk.context"

    symbol: str = Field(description="Trading symbol")
    timeframe: str = Field(description="Signal timeframe")

    price: float = Field(ge=0, description="Current/reference price")
    bid: Optional[float] = Field(default=None, ge=0, description="Current bid")
    ask: Optional[float] = Field(default=None, ge=0, description="Current ask")
    mark_price: Optional[float] = Field(default=None, ge=0, description="Mark price")

    balance_quote: float = Field(ge=0, description="Quote currency balance")
    balance_base: float = Field(ge=0, description="Base currency balance")

    position_size: float = Field(default=0.0, description="Current position size")
    realized_pnl: float = Field(default=0.0, description="Realized P&L")
    unrealized_pnl: float = Field(default=0.0, description="Unrealized P&L")

    volatility_pct: Optional[float] = Field(default=None, ge=0, description="Annualized volatility %")
    atr: Optional[float] = Field(default=None, ge=0, description="Average True Range")
    recent_returns: List[float] = Field(default_factory=list, description="Recent returns for VaR")

    equity: float = Field(ge=0, description="Total account equity")
    leverage: Optional[float] = Field(default=None, ge=0, description="Current leverage")

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, v: str) -> str:
        v = v.upper()
        if not SYMBOL_PATTERN.match(v):
            raise ValueError("Symbol must match BASE/QUOTE format")
        return v

    @field_validator("timeframe")
    @classmethod
    def validate_timeframe(cls, v: str) -> str:
        if not TIMEFRAME_PATTERN.match(v):
            raise ValueError("Timeframe must match format like 1m, 5m, 1h, 1w")
        return v


class RiskDecision(VersionedBaseModel):
    """Risk evaluation decision with reasons and applied caps"""
    type: str = "risk.decision"

    allowed: bool = Field(description="Whether trade is allowed")
    reasons: List[str] = Field(default_factory=list, description="Blocking reasons if not allowed")
    limits: Dict[str, float] = Field(default_factory=dict, description="Active risk limits")
    caps_applied: Dict[str, float] = Field(default_factory=dict, description="Size/exposure caps applied")
    advice: Optional[Dict[str, str]] = Field(default=None, description="Advisory guidance")
    policy_ref: Optional[str] = Field(default=None, description="Policy reference")
    decision_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique decision ID")

    @model_validator(mode="after")
    def validate_consistency(self):
        if not self.allowed and not self.reasons:
            raise ValueError("If not allowed, must provide at least one reason")
        return self

    def stable_id(self) -> str:
        """Generate stable hash for decision"""
        data = {
            "allowed": self.allowed,
            "reasons": sorted(self.reasons),
            "limits": dict(sorted(self.limits.items())),
            "caps_applied": dict(sorted(self.caps_applied.items())),
        }
        return stable_hash(data)


class ExposureCaps(VersionedBaseModel):
    """Risk cap configuration snapshot"""
    type: str = "exposure.caps"

    max_position_pct: float = Field(ge=0, le=1, description="Max position size as % of equity")
    max_portfolio_exposure_pct: float = Field(ge=0, le=1, description="Max total portfolio exposure %")
    max_symbol_exposure_pct: float = Field(ge=0, le=1, description="Max exposure per symbol %")
    max_leverage: float = Field(ge=1, description="Maximum leverage allowed")
    min_notional: float = Field(ge=0, description="Minimum order notional")
    max_notional_per_order: float = Field(ge=0, description="Maximum order notional")
    daily_stop_pct: float = Field(ge=-1.0, le=0.0, description="Daily stop loss as fraction of equity (negative, e.g. -0.03)")
    per_trade_risk_pct: float = Field(ge=0, le=1, description="Max risk per trade %")
    spread_bps_max: float = Field(ge=0, description="Maximum spread in bps")
    slippage_bps_max: float = Field(ge=0, description="Maximum slippage in bps")
    atr_volatility_max_pct: float = Field(ge=0, description="Max ATR as % of price")
    var_confidence_level: float = Field(ge=0.9, le=0.999, description="VaR confidence level")
    kelly_cap_multiplier: float = Field(ge=0, le=1, description="Kelly fraction cap multiplier")


class ComplianceRules(VersionedBaseModel):
    """Compliance rules configuration"""
    type: str = "compliance.rules"

    allowed_symbols: List[str] = Field(default_factory=list, description="Symbol whitelist patterns")
    blocked_symbols: List[str] = Field(default_factory=list, description="Symbol blacklist patterns")
    allowed_regions: List[str] = Field(default_factory=list, description="Allowed trading regions")
    blocked_regions: List[str] = Field(default_factory=list, description="Blocked trading regions")
    max_leverage_by_symbol: Dict[str, float] = Field(default_factory=dict, description="Symbol-specific leverage limits")
    restricted_hours_utc: List[Tuple[int, int]] = Field(default_factory=list, description="Restricted trading hours (start, end) - inclusive")
    require_manual_approval: List[str] = Field(default_factory=list, description="Symbols requiring manual approval")


# ----------------------------------------------------------------------------------------------------------------------
# Pure Calculator Functions (with accurate Gaussian VaR/CVaR)
# ----------------------------------------------------------------------------------------------------------------------

def _phi(z: float) -> float:
    """Standard normal PDF"""
    return (1.0 / math.sqrt(2 * math.pi)) * math.exp(-0.5 * z * z)


def _norm_inv_cdf(p: float) -> float:
    """Acklam's rational approximation for normal inverse CDF"""
    if not 0.0 < p < 1.0:
        raise ValueError("p must be in (0,1)")

    a = [-39.6968302866538, 220.946098424521, -275.928510446969,
         138.357751867269, -30.6647980661472, 2.50662827745924]
    b = [-54.4760987982241, 161.585836858041, -155.698979859887,
         66.8013118877197, -13.2806815528857]
    c = [-0.00778489400243029, -0.322396458041136, -2.40075827716184,
         -2.54973253934373, 4.37466414146497, 2.93816398269878]
    d = [0.00778469570904146, 0.32246712907004, 2.445134137143, 3.75440866190742]

    plow = 0.02425
    phigh = 1 - plow

    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
                 ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)

    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
           (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    """Calculate Average True Range"""
    if len(highs) < period or len(lows) < period or len(closes) < period:
        raise ValueError(f"Need at least {period} periods for ATR calculation")

    if not all(math.isfinite(x) and x > 0 for x in highs + lows + closes):
        raise ValueError("All price values must be finite and positive")

    true_ranges = []
    for i in range(1, len(closes)):
        tr1 = highs[i] - lows[i]
        tr2 = abs(highs[i] - closes[i - 1])
        tr3 = abs(lows[i] - closes[i - 1])
        true_ranges.append(max(tr1, tr2, tr3))

    if len(true_ranges) < period:
        return sum(true_ranges) / len(true_ranges)

    return sum(true_ranges[-period:]) / period


def annualized_vol(returns: List[float], periods_per_year: int) -> float:
    """Calculate annualized volatility from returns"""
    if len(returns) < 2:
        return 0.0

    if not all(math.isfinite(r) for r in returns):
        raise ValueError("All returns must be finite")

    mean_return = sum(returns) / len(returns)
    variance = sum((r - mean_return) ** 2 for r in returns) / (len(returns) - 1)
    return math.sqrt(variance * periods_per_year)


def var_gaussian(returns: List[float], confidence_level: float = 0.99) -> float:
    """Calculate Value at Risk using Gaussian assumption with proper inverse CDF"""
    if len(returns) < 2:
        return 0.0
    if not 0.5 < confidence_level < 0.9999:
        raise ValueError("Confidence level must be in (0.5, 0.9999)")

    mu = sum(returns) / len(returns)
    var = sum((r - mu) ** 2 for r in returns) / (len(returns) - 1)
    sigma = math.sqrt(var)
    z = _norm_inv_cdf(confidence_level)

    return abs(mu - z * sigma)


def cvar_gaussian(returns: List[float], confidence_level: float = 0.99) -> float:
    """Calculate Conditional Value at Risk (Expected Shortfall) for Gaussian"""
    if len(returns) < 2:
        return 0.0

    mu = sum(returns) / len(returns)
    var = sum((r - mu) ** 2 for r in returns) / (len(returns) - 1)
    sigma = math.sqrt(var)
    z = _norm_inv_cdf(confidence_level)

    # Expected shortfall for loss tail
    return abs(mu - sigma * (_phi(z) / (1.0 - confidence_level)))


def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float, cap: float = 0.2) -> float:
    """Calculate Kelly fraction with cap"""
    if not (0 <= win_rate <= 1):
        raise ValueError("Win rate must be between 0 and 1")

    if avg_win <= 0 or avg_loss <= 0:
        raise ValueError("Average win and loss must be positive")

    if not (0 <= cap <= 1):
        raise ValueError("Cap must be between 0 and 1")

    # Kelly formula: f = (bp - q) / b
    # where b = avg_win/avg_loss, p = win_rate, q = 1 - win_rate
    b = avg_win / avg_loss
    p = win_rate
    q = 1 - win_rate

    kelly = (b * p - q) / b
    return max(0, min(kelly, cap))


def spread_bps(bid: float, ask: float) -> float:
    """Calculate spread in basis points"""
    if bid <= 0 or ask <= 0:
        raise ValueError("Bid and ask must be positive")

    if ask < bid:
        raise ValueError("Ask must be >= bid")

    mid = (bid + ask) / 2
    return ((ask - bid) / mid) * 10000


def slippage_price(side: str, ref_price: float, slippage_bps: float) -> float:
    """Calculate price after slippage"""
    if ref_price <= 0:
        raise ValueError("Reference price must be positive")

    if slippage_bps < 0:
        raise ValueError("Slippage must be non-negative")

    multiplier = 1 + (slippage_bps / 10000)

    side_l = side.lower()
    if side_l in ("buy", "long"):
        return ref_price * multiplier
    if side_l in ("sell", "short"):
        return ref_price / multiplier
    raise ValueError("Side must be 'buy' or 'sell'")


def notional(size: float, price: float) -> float:
    """Calculate notional value"""
    if price <= 0:
        raise ValueError("Price must be positive")
    return abs(size) * price


def position_pct(notional_value: float, equity: float) -> float:
    """Calculate position as percentage of equity"""
    if equity <= 0:
        raise ValueError("Equity must be positive")
    return abs(notional_value) / equity


# ----------------------------------------------------------------------------------------------------------------------
# Emitters
# ----------------------------------------------------------------------------------------------------------------------

async def emit_metric(kind: str, payload: Dict[str, Any], *, redis: Optional[RedisManager] = None) -> None:
    """Emit metric event to metrics stream"""
    try:
        event = {
            "kind": kind,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **payload,
        }
        if not redis:
            return
        await redis.client.xadd(
            STREAM_KEYS["metrics"],
            pack_stream_fields(event),
            maxlen=10000,
            approximate=True,
        )
    except Exception as e:
        logger.warning(f"emit_metric failed: {e}")


async def emit_risk_event(event: Dict[str, Any], *, redis: Optional[RedisManager] = None) -> None:
    """Emit risk event to risk events stream"""
    try:
        if not redis:
            return
        await redis.client.xadd(
            STREAM_KEYS["risk_events"],
            pack_stream_fields(event),
            maxlen=5000,
            approximate=True,
        )
    except Exception as e:
        logger.warning(f"emit_risk_event failed: {e}")


# ----------------------------------------------------------------------------------------------------------------------
# Redis-backed State Store
# ----------------------------------------------------------------------------------------------------------------------

class RiskStateStore:
    """Redis-backed risk state with in-memory fallback"""

    def __init__(self, redis_manager: Optional[RedisManager] = None, use_memory: bool = False):
        self.redis = redis_manager
        self.use_memory = use_memory or redis_manager is None
        self._memory_store: Dict[str, Any] = {}
        self._lock = asyncio.Lock()
        self.logger = logger

    # Redis helper methods
    async def _get(self, key: str) -> Optional[str]:
        """Get string value from Redis (decoded)"""
        if not self.redis:
            return None
        val = await self.redis.client.get(key)
        if val is None:
            return None
        if isinstance(val, bytes):
            val = val.decode()
        return val

    async def _set(self, key: str, value: str, ex: Optional[int] = None) -> None:
        """Set string value in Redis"""
        if self.redis:
            await self.redis.client.set(key, value, ex=ex)

    async def _incrbyfloat(self, key: str, delta: float) -> float:
        """Increment float value in Redis"""
        if self.redis:
            return float(await self.redis.client.incrbyfloat(key, float(delta)))
        return 0.0

    async def _expire(self, key: str, seconds: int) -> None:
        """Set expiration on Redis key"""
        if self.redis:
            await self.redis.client.expire(key, seconds)

    async def get_drawdown(self, symbol: Optional[str] = None) -> float:
        """Get current drawdown percentage"""
        key = f"risk:drawdown:{symbol}" if symbol else "risk:drawdown:global"

        if self.use_memory:
            async with self._lock:
                return float(self._memory_store.get(key, 0.0))

        try:
            value = await self._get(key)
            return float(value) if value is not None else 0.0
        except Exception as e:
            self.logger.warning(f"Redis get_drawdown failed: {e}")
            return 0.0

    async def update_pnl(self, symbol: str, realized_delta: float, equity: float) -> Dict[str, Any]:
        """Update P&L and return snapshot"""
        utc_day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        daily_key = f"risk:daily_pnl:{symbol}:{utc_day}"
        drawdown_key = f"risk:drawdown:{symbol}"

        snapshot = {
            "symbol": symbol,
            "realized_delta": realized_delta,
            "equity": equity,
            "timestamp": time.time(),
        }

        if self.use_memory:
            async with self._lock:
                current_daily = float(self._memory_store.get(daily_key, 0.0))
                new_daily = current_daily + realized_delta
                self._memory_store[daily_key] = new_daily

                drawdown_pct = new_daily / equity if equity > 0 else 0.0
                self._memory_store[drawdown_key] = drawdown_pct

                snapshot.update({
                    "daily_pnl": new_daily,
                    "daily_drawdown_pct": drawdown_pct,
                })
                return snapshot

        try:
            # Update daily PnL using float increment
            new_daily = await self._incrbyfloat(daily_key, float(realized_delta))
            await self._expire(daily_key, 86400)  # 24 hours

            # Calculate and store drawdown
            drawdown_pct = new_daily / equity if equity > 0 else 0.0
            await self._set(drawdown_key, str(drawdown_pct), ex=86400)

            snapshot.update({
                "daily_pnl": new_daily,
                "daily_drawdown_pct": drawdown_pct,
            })

        except Exception as e:
            self.logger.warning(f"Redis update_pnl failed: {e}")
            snapshot.update({
                "daily_pnl": realized_delta,
                "daily_drawdown_pct": realized_delta / equity if equity > 0 else 0.0,
            })

        return snapshot

    async def get_exposure(self, symbol: Optional[str] = None) -> float:
        """Get current exposure"""
        key = f"risk:exposure:{symbol}" if symbol else "risk:exposure:total"

        if self.use_memory:
            async with self._lock:
                return float(self._memory_store.get(key, 0.0))

        try:
            value = await self._get(key)
            return float(value) if value is not None else 0.0
        except Exception as e:
            self.logger.warning(f"Redis get_exposure failed: {e}")
            return 0.0

    async def bump_order(self, symbol: str, notional_value: float) -> None:
        """Increment order exposure for rate limiting window"""
        key = f"risk:orders:{symbol}:{int(time.time() // 60)}"  # Per minute window

        if self.use_memory:
            async with self._lock:
                current = float(self._memory_store.get(key, 0.0))
                self._memory_store[key] = current + abs(notional_value)
                return

        try:
            await self._incrbyfloat(key, float(abs(notional_value)))
            await self._expire(key, 120)  # 2 minutes
        except Exception as e:
            self.logger.warning(f"Redis bump_order failed: {e}")

    async def is_killswitch_engaged(self) -> bool:
        """Check if global kill switch is engaged"""
        key = "risk:killswitch"

        if self.use_memory:
            async with self._lock:
                return bool(self._memory_store.get(key, False))

        try:
            value = await self._get(key)
            return value == "true" if value is not None else False
        except Exception as e:
            self.logger.warning(f"Redis killswitch check failed: {e}")
            return False

    async def set_killswitch(self, engaged: bool) -> None:
        """Set global kill switch state"""
        key = "risk:killswitch"
        value = "true" if engaged else "false"

        if self.use_memory:
            async with self._lock:
                self._memory_store[key] = engaged
                return

        try:
            await self._set(key, value, ex=3600)  # 1 hour expiry
        except Exception as e:
            self.logger.warning(f"Redis set_killswitch failed: {e}")

    async def get_daily_stop_state(self) -> Dict[str, Any]:
        """Get daily stop loss state"""
        utc_day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key = f"risk:daily_stop:{utc_day}"

        default_state = {"hit": False, "pnl": 0.0, "timestamp": None}

        if self.use_memory:
            async with self._lock:
                return dict(self._memory_store.get(key, default_state.copy()))

        try:
            value = await self._get(key)
            if value:
                return json.loads(value)
            return default_state
        except Exception as e:
            self.logger.warning(f"Redis get_daily_stop_state failed: {e}")
            return default_state


# ----------------------------------------------------------------------------------------------------------------------
# Risk Engines
# ----------------------------------------------------------------------------------------------------------------------

class PreTradeRisk:
    """Pre-trade risk evaluation engine"""

    def __init__(self, cfg: Any, store: RiskStateStore):
        self.cfg = cfg
        self.store = store
        self.logger = logger

    @timer("pretrade_risk_evaluate")
    async def evaluate(
        self,
        *,
        signal: Optional[Signal] = None,
        intent: Optional[OrderIntent] = None,
        ctx: RiskContext,
        caps: ExposureCaps,
        rules: ComplianceRules,
    ) -> RiskDecision:
        """Evaluate pre-trade risk checks"""

        reasons: List[str] = []
        caps_applied: Dict[str, float] = {}
        limits: Dict[str, float] = {}

        # Extract order details
        symbol = ctx.symbol
        side = intent.side.value if intent else (signal.side.value if signal else "buy")
        order_notional = float(intent.size_quote_usd) if intent else 0.0

        try:
            # Pre-flight input validation
            if ctx.equity <= 0:
                reasons.append(REASON_CODES["equity_invalid"])
            if (ctx.price or 0) <= 0:
                reasons.append(REASON_CODES["price_invalid"])

            # 1. Global kill switch
            if await self.store.is_killswitch_engaged():
                reasons.append(REASON_CODES["killswitch"])

            # 2. Daily stop check
            daily_drawdown = await self.store.get_drawdown()
            limits["daily_drawdown"] = daily_drawdown
            if daily_drawdown <= caps.daily_stop_pct:
                reasons.append(REASON_CODES["daily_stop"])

            # 3. Compliance checks
            compliance_ok, compliance_reasons = self._check_compliance(symbol, rules)
            if not compliance_ok:
                reasons.extend([f"{REASON_CODES['compliance']}:{r}" for r in compliance_reasons])

            # 4. Spread/slippage checks
            if ctx.bid and ctx.ask:
                current_spread_bps = spread_bps(float(ctx.bid), float(ctx.ask))
                limits["spread_bps"] = current_spread_bps
                if current_spread_bps > caps.spread_bps_max:
                    reasons.append(REASON_CODES["spread"])

            # 5. Notional limits
            if order_notional > 0:
                limits["order_notional"] = order_notional
                if order_notional < caps.min_notional:
                    reasons.append(REASON_CODES["min_notional"])
                elif order_notional > caps.max_notional_per_order:
                    reasons.append(REASON_CODES["max_notional"])

            # 6. Leverage check
            if ctx.leverage and ctx.leverage > caps.max_leverage:
                reasons.append(REASON_CODES["max_leverage"])
                limits["leverage"] = float(ctx.leverage)

            # 7. Exposure checks
            current_exposure = await self.store.get_exposure(symbol)
            position_exposure_pct = position_pct(order_notional, ctx.equity) if ctx.equity > 0 else 0.0

            limits["position_exposure_pct"] = position_exposure_pct
            limits["current_exposure"] = current_exposure

            if position_exposure_pct > caps.max_position_pct:
                # Cap the position size (advisory)
                max_allowed = ctx.equity * caps.max_position_pct
                caps_applied["size_capped_to"] = max_allowed
                if position_exposure_pct > caps.max_symbol_exposure_pct:
                    reasons.append(REASON_CODES["exposure_cap"])

            # 8. ATR/Volatility check
            if ctx.atr and ctx.price:
                atr_pct = (float(ctx.atr) / float(ctx.price)) * 100.0
                limits["atr_volatility_pct"] = atr_pct
                if atr_pct > caps.atr_volatility_max_pct:
                    reasons.append(REASON_CODES["atr_limit"])

            # 9. VaR check
            if len(ctx.recent_returns) >= 10:
                var_estimate = var_gaussian(ctx.recent_returns, caps.var_confidence_level)
                risk_pct = var_estimate * 100.0
                limits["var_risk_pct"] = risk_pct
                if risk_pct > caps.per_trade_risk_pct * 100.0:
                    reasons.append(REASON_CODES["var_limit"])

            # 10. Kelly fraction – placeholder (requires strategy performance inputs)

            decision = RiskDecision(
                allowed=len(reasons) == 0,
                reasons=reasons,
                limits=limits,
                caps_applied=caps_applied,
                policy_ref=f"caps_v{getattr(caps, 'schema_version', '1')}",
            )

            # Emit metric
            await emit_metric(
                METRIC_KINDS["risk_check" if decision.allowed else "risk_block"],
                {
                    "symbol": symbol,
                    "side": side,
                    "allowed": decision.allowed,
                    "reasons_count": len(reasons),
                    "decision_id": decision.decision_id,
                },
                redis=self.store.redis,
            )

            return decision

        except Exception as e:
            self.logger.error(f"Risk evaluation failed: {e}")
            return RiskDecision(
                allowed=False,
                reasons=["evaluation_error"],
                limits={"error": str(e)},
            )

    def _check_compliance(self, symbol: str, rules: ComplianceRules) -> Tuple[bool, List[str]]:
        """Check compliance rules"""
        reasons: List[str] = []

        # Symbol whitelist/blacklist
        if rules.allowed_symbols:
            allowed = any(re.match(pattern, symbol) for pattern in rules.allowed_symbols)
            if not allowed:
                reasons.append("symbol_not_whitelisted")

        if rules.blocked_symbols:
            blocked = any(re.match(pattern, symbol) for pattern in rules.blocked_symbols)
            if blocked:
                reasons.append("symbol_blacklisted")

        # Time restrictions (inclusive)
        if rules.restricted_hours_utc:
            current_hour = datetime.now(timezone.utc).hour
            for start, end in rules.restricted_hours_utc:
                if start <= current_hour <= end:
                    reasons.append("restricted_trading_hours")
                    break

        # Manual approval required
        if rules.require_manual_approval:
            if any(re.match(pattern, symbol) for pattern in rules.require_manual_approval):
                reasons.append("manual_approval_required")

        return len(reasons) == 0, reasons


class PostTradeRisk:
    """Post-trade risk update engine"""

    def __init__(self, cfg: Any, store: RiskStateStore):
        self.cfg = cfg
        self.store = store
        self.logger = logger

    @timer("posttrade_risk_update")
    async def update_after_fill(
        self,
        *,
        symbol: str,
        realized_pnl_delta: float,
        equity: float,
    ) -> Dict[str, Any]:
        """Update risk state after trade execution"""

        try:
            # Update PnL and get snapshot
            snapshot = await self.store.update_pnl(symbol, realized_pnl_delta, equity)

            # Check if daily stop should be triggered
            daily_drawdown_pct = snapshot.get("daily_drawdown_pct", 0.0)

            # Get caps from config
            caps = get_caps_from_cfg(self.cfg)

            if daily_drawdown_pct <= caps.daily_stop_pct:
                self.logger.warning(f"Daily stop triggered: {daily_drawdown_pct:.2%}")
                await self.store.set_killswitch(True)
                snapshot["daily_stop_triggered"] = True

            # Emit metric
            await emit_metric(
                METRIC_KINDS["risk_update"],
                {
                    "symbol": symbol,
                    "realized_pnl_delta": realized_pnl_delta,
                    "daily_drawdown_pct": daily_drawdown_pct,
                    "equity": equity,
                },
                redis=self.store.redis,
            )

            return snapshot

        except Exception as e:
            self.logger.error(f"Post-trade update failed: {e}")
            return {"error": str(e), "symbol": symbol, "timestamp": time.time()}


class ComplianceEngine:
    """Compliance checking engine"""

    def __init__(self, rules: ComplianceRules):
        self.rules = rules

    def check(
        self,
        symbol: str,
        now_utc: datetime,
        leverage: Optional[float] = None,
    ) -> Tuple[bool, List[str]]:
        """Check compliance for symbol, time, and leverage"""
        reasons: List[str] = []

        # Symbol checks
        if self.rules.allowed_symbols and not any(re.match(p, symbol) for p in self.rules.allowed_symbols):
            reasons.append("symbol_not_allowed")
        if self.rules.blocked_symbols and any(re.match(p, symbol) for p in self.rules.blocked_symbols):
            reasons.append("symbol_blocked")

        # Time window checks (inclusive bounds)
        current_hour = now_utc.hour
        for start_hour, end_hour in self.rules.restricted_hours_utc:
            if start_hour <= current_hour <= end_hour:
                reasons.append("trading_hours_restricted")
                break

        # Leverage checks
        if leverage is not None:
            max_lev = self.rules.max_leverage_by_symbol.get(symbol)
            if max_lev is not None and leverage > max_lev:
                reasons.append("leverage_exceeds_symbol_limit")

        allowed = len(reasons) == 0
        return allowed, reasons


# ----------------------------------------------------------------------------------------------------------------------
# Configuration helpers
# ----------------------------------------------------------------------------------------------------------------------

_cfg_cache = None


def get_caps_from_cfg(cfg=None) -> ExposureCaps:
    """Extract exposure caps from config"""
    global _cfg_cache
    if cfg is None:
        if _cfg_cache is None:
            _cfg_cache = get_config()
        cfg = _cfg_cache

    risk_cfg = getattr(cfg, "risk", cfg)
    cb = getattr(risk_cfg, "circuit_breakers", None)

    return ExposureCaps(
        max_position_pct=getattr(risk_cfg, "per_symbol_max_exposure", 0.25),
        max_portfolio_exposure_pct=getattr(risk_cfg, "max_portfolio_exposure", 0.8),
        max_symbol_exposure_pct=getattr(risk_cfg, "per_symbol_max_exposure", 0.25),
        max_leverage=getattr(risk_cfg, "max_leverage", 3.0),
        min_notional=getattr(risk_cfg, "min_notional", 10.0),
        max_notional_per_order=getattr(risk_cfg, "max_notional_per_order", 10000.0),
        daily_stop_pct=getattr(risk_cfg, "daily_stop_loss", -0.03),
        per_trade_risk_pct=getattr(risk_cfg, "per_trade_risk", 0.01),
        spread_bps_max=getattr(cb, "spread_bps_max", 10.0),
        slippage_bps_max=getattr(risk_cfg, "max_slippage_bps", 8.0),
        atr_volatility_max_pct=getattr(risk_cfg, "atr_volatility_max_pct", 5.0),
        var_confidence_level=getattr(risk_cfg, "var_confidence_level", 0.95),
        kelly_cap_multiplier=getattr(risk_cfg, "kelly_cap_multiplier", 0.25),
    )


def get_rules_from_cfg(cfg=None) -> ComplianceRules:
    """Extract compliance rules from config"""
    global _cfg_cache
    if cfg is None:
        if _cfg_cache is None:
            _cfg_cache = get_config()
        cfg = _cfg_cache

    return ComplianceRules(
        allowed_symbols=getattr(cfg, "allowed_symbols", []),
        blocked_symbols=getattr(cfg, "blocked_symbols", []),
        allowed_regions=getattr(cfg, "allowed_regions", []),
        blocked_regions=getattr(cfg, "blocked_regions", []),
        max_leverage_by_symbol=getattr(cfg, "max_leverage_by_symbol", {}),
        restricted_hours_utc=getattr(cfg, "restricted_hours_utc", []),
        require_manual_approval=getattr(cfg, "require_manual_approval", []),
    )


# ----------------------------------------------------------------------------------------------------------------------
# Public API helpers
# ----------------------------------------------------------------------------------------------------------------------

async def pretrade_check(
    signal: Optional[Signal] = None,
    intent: Optional[OrderIntent] = None,
    ctx: RiskContext = None,
    *,
    cfg=None,
    store: Optional[RiskStateStore] = None,
) -> RiskDecision:
    """Convenience function for pre-trade risk check"""
    if cfg is None:
        cfg = get_config()

    if store is None:
        redis_manager = await RedisManager.get_or_create(url=cfg.redis.url) if hasattr(cfg, "redis") else None
        store = RiskStateStore(redis_manager)

    caps = get_caps_from_cfg(cfg)
    rules = get_rules_from_cfg(cfg)

    engine = PreTradeRisk(cfg, store)
    return await engine.evaluate(
        signal=signal,
        intent=intent,
        ctx=ctx,
        caps=caps,
        rules=rules,
    )


async def posttrade_update(
    symbol: str,
    realized_pnl_delta: float,
    equity: float,
    *,
    cfg=None,
    store: Optional[RiskStateStore] = None,
) -> Dict[str, Any]:
    """Convenience function for post-trade risk update"""
    if cfg is None:
        cfg = get_config()

    if store is None:
        redis_manager = await RedisManager.get_or_create(url=cfg.redis.url) if hasattr(cfg, "redis") else None
        store = RiskStateStore(redis_manager)

    engine = PostTradeRisk(cfg, store)
    return await engine.update_after_fill(
        symbol=symbol,
        realized_pnl_delta=realized_pnl_delta,
        equity=equity,
    )


async def engage_killswitch(
    flag: bool,
    *,
    cfg=None,
    store: Optional[RiskStateStore] = None,
) -> None:
    """Convenience function to engage/disengage kill switch"""
    if cfg is None:
        cfg = get_config()

    if store is None:
        redis_manager = await RedisManager.get_or_create(url=cfg.redis.url) if hasattr(cfg, "redis") else None
        store = RiskStateStore(redis_manager)

    await store.set_killswitch(flag)

    # Emit event
    await emit_risk_event(
        {
            "event": "killswitch_changed",
            "engaged": flag,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        redis=store.redis,
    )


# ----------------------------------------------------------------------------------------------------------------------
# Module exports
# ----------------------------------------------------------------------------------------------------------------------

__all__ = [
    # Models
    "RiskContext",
    "RiskDecision",
    "ExposureCaps",
    "ComplianceRules",

    # Engines & Store
    "PreTradeRisk",
    "PostTradeRisk",
    "ComplianceEngine",
    "RiskStateStore",

    # Calculators
    "atr",
    "annualized_vol",
    "var_gaussian",
    "cvar_gaussian",
    "kelly_fraction",
    "spread_bps",
    "slippage_price",
    "notional",
    "position_pct",

    # Helpers
    "get_caps_from_cfg",
    "get_rules_from_cfg",
    "pretrade_check",
    "posttrade_update",
    "engage_killswitch",

    # Emitters
    "emit_metric",
    "emit_risk_event",

    # Exceptions
    "RiskConfigError",
    "RiskEvaluationError",
]
