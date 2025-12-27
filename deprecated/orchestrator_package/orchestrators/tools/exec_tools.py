# orchestrator_package/orchestrators/tools/exec_tools.py
"""
Production-ready execution utilities for crypto-ai-bot orchestrators and agents.
Provides ExchangePort protocol, order construction/execution helpers, risk/price checks,
idempotency & dedup, Redis-backed persistence, and test seams.

Call flow:
Signal → OrderPlan → OrderIntent → send_intent → exchange.create_order → ack → fills
        ↓
     PriceGuards/RiskChecks → IdempotencyStore → Redis streams
"""

from __future__ import annotations

import asyncio
import time
import uuid
import re
from typing import Protocol, Any, Dict, List, Optional
from collections import OrderedDict
from decimal import Decimal, ROUND_HALF_UP

from pydantic import Field, field_validator

# Import shim for flexible placement
try:
    from config.config_loader import get_config
except Exception:  # pragma: no cover
    from ...config.config_loader import get_config  # type: ignore

try:
    from mcp.schemas import (
        OrderIntent,
        Signal,
        MetricsTick,
        VersionedBaseModel,
        OrderType,
    )
except Exception:  # pragma: no cover
    from ...mcp.schemas import (  # type: ignore
        OrderIntent,
        Signal,
        MetricsTick,
        VersionedBaseModel,
        OrderType,
    )

# Redis managers are optional; we duck-type on .client (async redis-py)
try:
    from mcp.redis_manager import RedisManager, AsyncRedisManager  # noqa: F401
except Exception:  # pragma: no cover
    RedisManager = object  # type: ignore
    AsyncRedisManager = object  # type: ignore

try:
    from mcp.marshaling import stable_hash, pack_stream_fields
except Exception:  # pragma: no cover
    from ...mcp.marshaling import stable_hash, pack_stream_fields  # type: ignore

try:
    from mcp.errors import MCPError
except Exception:  # pragma: no cover
    from ...mcp.errors import MCPError  # type: ignore

try:
    from utils.logger import get_logger
except Exception:  # pragma: no cover
    from ...utils.logger import get_logger  # type: ignore

try:
    from utils.timer import timer
except Exception:  # pragma: no cover
    from ...utils.timer import timer  # type: ignore

try:
    from utils.retry import retry
except Exception:  # pragma: no cover
    from ...utils.retry import retry  # type: ignore

# Optional: execution agent
try:
    from agents.core.execution_agent import ExecutionAgent  # noqa: F401
    HAS_EXECUTION_AGENT = True
except Exception:
    HAS_EXECUTION_AGENT = False

logger = get_logger(__name__)

# --------------------------
# Config helpers & patterns
# --------------------------

_config_cache = None


def _get_cached_config() -> Dict[str, Any]:
    """Cache & return dict-like config."""
    global _config_cache
    if _config_cache is None:
        try:
            cfg = get_config()
            # normalize to dict for consistent access
            _config_cache = dict(cfg) if isinstance(cfg, dict) else getattr(cfg, "__dict__", {}) or {}
        except Exception as e:
            logger.warning(f"Failed to load config, using defaults: {e}")
            _config_cache = {}
    return _config_cache


def _dg(cfg: Dict[str, Any], path: str, default: Any = None) -> Any:
    """Deep-get helper for dict configs: _dg(cfg, 'trading.entries.min_volume_usd', 5.0)."""
    cur: Any = cfg
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur


# Validation patterns
_SYMBOL_RE = re.compile(r"^[A-Z0-9]+/[A-Z0-9]+$", re.ASCII)
_TIMEFRAME_RE = re.compile(r"^\d+(s|m|h|d)$", re.ASCII)


# --------------------------
# Exceptions
# --------------------------

class ExecutionError(MCPError):
    """Base execution error."""


class RiskCheckError(ExecutionError):
    """Risk check failed."""


class PriceGuardError(ExecutionError):
    """Price guard violation."""


class IdempotencyError(ExecutionError):
    """Idempotency violation."""


# --------------------------
# Protocols & Adapters
# --------------------------

class ExchangePort(Protocol):
    """Test seam for exchange operations."""

    async def get_orderbook(self, symbol: str) -> dict: ...
    async def get_position(self, symbol: str) -> dict | None: ...
    async def get_balance(self, asset: str) -> dict: ...

    async def create_order(
        self,
        *,
        symbol: str,
        side: str,
        type: str,
        amount: float,
        price: float | None = None,
        params: dict | None = None,
    ) -> dict: ...

    async def fetch_order(self, order_id: str, symbol: str) -> dict: ...
    async def cancel_order(self, order_id: str, symbol: str) -> dict: ...


class NullExchange:
    """No-op exchange for testing."""

    async def get_orderbook(self, symbol: str) -> dict:
        return {"bids": [[45000.0, 1.0]], "asks": [[45001.0, 1.0]]}

    async def get_position(self, symbol: str) -> dict | None:
        return None

    async def get_balance(self, asset: str) -> dict:
        return {"free": 1000.0, "used": 0.0, "total": 1000.0}

    async def create_order(
        self,
        *,
        symbol: str,
        side: str,
        type: str,
        amount: float,
        price: float | None = None,
        params: dict | None = None,
    ) -> dict:
        return {
            "id": f"sim_{int(time.time() * 1000)}",
            "symbol": symbol,
            "side": side,
            "amount": amount,
            "price": price,
            "status": "closed",
            "filled": amount,
        }

    async def fetch_order(self, order_id: str, symbol: str) -> dict:
        return {"id": order_id, "symbol": symbol, "status": "closed", "filled": 1.0}

    async def cancel_order(self, order_id: str, symbol: str) -> dict:
        return {"id": order_id, "status": "canceled"}


class DelegatingExchange:
    """Adapter that delegates to execution agent when available."""
    def __init__(self, agent: Any = None):
        self.agent = agent
        self.fallback = NullExchange()

    async def get_orderbook(self, symbol: str) -> dict:
        if self.agent and hasattr(self.agent, "get_orderbook"):
            try:
                return await self.agent.get_orderbook(symbol)
            except Exception as e:
                logger.warning(f"Agent orderbook fetch failed: {e}")
        return await self.fallback.get_orderbook(symbol)

    async def get_position(self, symbol: str) -> dict | None:
        if self.agent and hasattr(self.agent, "get_position"):
            try:
                return await self.agent.get_position(symbol)
            except Exception:
                pass
        return await self.fallback.get_position(symbol)

    async def get_balance(self, asset: str) -> dict:
        if self.agent and hasattr(self.agent, "get_balance"):
            try:
                return await self.agent.get_balance(asset)
            except Exception as e:
                logger.warning(f"Agent balance fetch failed: {e}")
        return await self.fallback.get_balance(asset)

    async def create_order(
        self,
        *,
        symbol: str,
        side: str,
        type: str,
        amount: float,
        price: float | None = None,
        params: dict | None = None,
    ) -> dict:
        if self.agent and hasattr(self.agent, "create_order"):
            try:
                return await self.agent.create_order(
                    symbol=symbol, side=side, type=type, amount=amount, price=price, params=params
                )
            except Exception as e:
                logger.error(f"Agent order creation failed: {e}")
                raise
        return await self.fallback.create_order(
            symbol=symbol, side=side, type=type, amount=amount, price=price, params=params
        )

    async def fetch_order(self, order_id: str, symbol: str) -> dict:
        if self.agent and hasattr(self.agent, "fetch_order"):
            try:
                return await self.agent.fetch_order(order_id, symbol)
            except Exception:
                pass
        return await self.fallback.fetch_order(order_id, symbol)

    async def cancel_order(self, order_id: str, symbol: str) -> dict:
        if self.agent and hasattr(self.agent, "cancel_order"):
            try:
                return await self.agent.cancel_order(order_id, symbol)
            except Exception:
                pass
        return await self.fallback.cancel_order(order_id, symbol)


# --------------------------
# Order planning model
# --------------------------

class OrderPlan(VersionedBaseModel):
    """Derived from Signal + config for order construction."""

    type: str = Field(default="order.plan", description="Event type")
    symbol: str = Field(description="Trading symbol")
    side: str = Field(description="Order side: buy/sell")
    timeframe: str = Field(description="Timeframe context")
    amount: float = Field(gt=0.0, description="Order amount")  # strictly positive
    limit_price: Optional[float] = Field(default=None, ge=0.0, description="Limit price")
    time_in_force: str = Field(default="GTC", description="Time in force")
    reduce_only: bool = Field(default=False, description="Reduce only flag")
    leverage: Optional[float] = Field(default=None, ge=1.0, description="Leverage")
    slippage_bps_max: float = Field(default=10.0, ge=0.0, le=1000.0, description="Max slippage in bps")
    spread_bps_max: float = Field(default=5.0, ge=0.0, le=1000.0, description="Max spread in bps")
    notional_min: float = Field(default=5.0, ge=0.0, description="Minimum notional value")
    idempotency_key: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Idempotency key")
    tags: Dict[str, str] = Field(default_factory=dict, description="Additional tags")

    @field_validator("side")
    @classmethod
    def validate_side(cls, v: str) -> str:
        v_lower = v.lower()
        if v_lower not in {"buy", "sell"}:
            raise ValueError(f"side must be 'buy' or 'sell', got '{v}'")
        return v_lower

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, v: str) -> str:
        v = v.upper()
        if not _SYMBOL_RE.match(v):
            raise ValueError(f"symbol must match BASE/QUOTE format, got '{v}'")
        return v

    @field_validator("timeframe")
    @classmethod
    def validate_timeframe(cls, v: str) -> str:
        if not _TIMEFRAME_RE.match(v):
            raise ValueError(r"timeframe must match \d+(s|m|h|d) format")
        return v

    def stable_id(self) -> str:
        """Generate stable ID for deduplication."""
        return stable_hash(
            {
                "symbol": self.symbol,
                "side": self.side,
                "amount": self.amount,
                "idempotency_key": self.idempotency_key,
            }
        )


# --------------------------
# Utility classes
# --------------------------

class PositionSizer:
    """Position sizing with deterministic rounding."""

    def __init__(self, decimals: int = 8):
        self.decimals = decimals

    def size_from_config(
        self,
        balance: float,
        price: float,
        risk_pct: float,
        min_notional: float,
    ) -> float:
        """Calculate position size from config parameters."""
        cfg = _get_cached_config()
        max_position_pct = float(_dg(cfg, "trading.position_sizing.max_position", 0.25))

        # Calculate risk-based size
        risk_amount = balance * float(risk_pct)
        max_amount = balance * max_position_pct

        target_amount = min(risk_amount, max_amount)

        # Convert to size in units of base
        size = target_amount / max(price, 1e-12)

        # Ensure minimum notional
        min_size = float(min_notional) / max(price, 1e-12)
        size = max(size, min_size)

        q = Decimal("0." + "0" * (self.decimals - 1) + "1")
        return float(Decimal(str(size)).quantize(q, rounding=ROUND_HALF_UP))


class PriceGuards:
    """Price and spread validation utilities."""

    @staticmethod
    def compute_spread_bps(bid: float, ask: float) -> float:
        if bid <= 0 or ask <= 0 or ask <= bid:
            return float("inf")
        return ((ask - bid) / bid) * 10000.0

    @staticmethod
    def within_spread(bps: float, max_bps: float) -> bool:
        return bps <= max_bps

    @staticmethod
    def apply_slippage(price: float, bps: float, side: str) -> float:
        multiplier = 1 + (bps / 10000.0)
        return price * multiplier if side.lower() == "buy" else price / multiplier


class RiskChecks:
    """Risk validation utilities."""

    @staticmethod
    def check_min_notional(size: float, price: float, min_notional: float) -> bool:
        return (size * price) >= float(min_notional)

    @staticmethod
    def check_drawdown_limits(cfg_state: Any, symbol: str) -> bool:
        # TODO: Wire to Redis counters / risk service
        return True

    @staticmethod
    def check_compliance(symbol: str, region_rules: List[str]) -> bool:
        cfg = _get_cached_config()
        restricted_symbols = set(_dg(cfg, "security.restricted_symbols", []))
        return symbol not in restricted_symbols


# --------------------------
# Idempotency store
# --------------------------

class IdempotencyStore:
    """
    Redis-backed idempotency store with in-memory fallback.

    Duck-types an async redis client: expects `redis.client` that has async `exists`/`setex`.
    """

    def __init__(self, redis_manager: Optional[Any] = None):
        self.redis_manager = redis_manager
        self._memory_cache: OrderedDict[str, float] = OrderedDict()
        self._max_cache_size = 1000

    async def _redis_call(self, fn: str, *args, **kwargs) -> Any:
        if not self.redis_manager:
            raise RuntimeError("no redis")
        client = getattr(self.redis_manager, "client", None) or self.redis_manager
        method = getattr(client, fn, None)
        if method is None:
            raise AttributeError(f"redis client missing method {fn}")
        result = method(*args, **kwargs)
        if asyncio.iscoroutine(result):
            return await result
        return result

    async def seen(self, key: str, ttl_s: int = 900) -> bool:
        """Check if key has been seen before."""
        # Redis path
        if self.redis_manager:
            try:
                exists = await self._redis_call("exists", f"idempotent:{key}")
                return bool(exists)
            except Exception as e:
                logger.warning(f"Redis idempotency check failed, using memory: {e}")

        # Fallback memory path
        now = time.time()
        t = self._memory_cache.get(key)
        if t and (now - t) < ttl_s:
            return True
        if t:
            del self._memory_cache[key]
        return False

    async def mark(self, key: str, ttl_s: int = 900) -> None:
        """Mark key as seen."""
        if self.redis_manager:
            try:
                await self._redis_call("setex", f"idempotent:{key}", int(ttl_s), "1")
                return
            except Exception as e:
                logger.warning(f"Redis idempotency mark failed, using memory: {e}")

        now = time.time()
        self._memory_cache[key] = now
        while len(self._memory_cache) > self._max_cache_size:
            self._memory_cache.popitem(last=False)


# --------------------------
# Main execution functions
# --------------------------

async def build_order_intent(
    signal: Signal,
    cfg: Dict[str, Any] | Any,
    exchange: ExchangePort,
    *,
    overrides: Optional[Dict[str, Any]] = None,
) -> OrderIntent:
    """
    Build OrderIntent from Signal with risk checks and sizing.

    Raises PriceGuardError / RiskCheckError instead of returning a zero-sized intent.
    """
    overrides = overrides or {}

    # Get orderbook for pricing
    with timer() as t:
        orderbook = await exchange.get_orderbook(signal.symbol)
    logger.debug(f"Orderbook fetch took {t.elapsed:.3f}s for {signal.symbol}")

    if not orderbook.get("bids") or not orderbook.get("asks"):
        raise PriceGuardError(f"Empty orderbook for {signal.symbol}")

    bid = float(orderbook["bids"][0][0])
    ask = float(orderbook["asks"][0][0])

    # Spread guard
    spread_bps = PriceGuards.compute_spread_bps(bid, ask)
    cfg_d = _get_cached_config()
    max_spread_bps = float(overrides.get("spread_bps_max", _dg(cfg_d, "trading.spread_bps_max", 5.0)))
    if not PriceGuards.within_spread(spread_bps, max_spread_bps):
        allow_market = bool(_dg(cfg_d, "trading.allow_market_on_wide_spread", False))
        if not allow_market:
            raise PriceGuardError(f"Spread {spread_bps:.2f} bps exceeds limit {max_spread_bps:.2f} bps")

    # Balance for sizing (use quote asset, e.g. USD from BTC/USD)
    quote_asset = signal.symbol.split("/")[1]
    balance_info = await exchange.get_balance(quote_asset)
    available_quote = float(balance_info.get("free", 0.0))

    # Position size (in USD quote); risk settings from cfg
    risk_pct = float(_dg(cfg_d, "risk.per_trade_risk", 0.003))
    min_notional = float(_dg(cfg_d, "trading.entries.min_volume_usd", 5.0))
    price_for_sizing = ask if signal.side.value == "buy" else bid

    sizer = PositionSizer()
    size_usd = sizer.size_from_config(available_quote, price_for_sizing, risk_pct, min_notional)

    # Risk checks
    base_units = size_usd / max(price_for_sizing, 1e-12)
    if not RiskChecks.check_min_notional(base_units, price_for_sizing, min_notional):
        raise RiskCheckError(f"Position size below minimum notional: {min_notional}")

    if not RiskChecks.check_drawdown_limits(cfg, signal.symbol):
        raise RiskCheckError(f"Drawdown limits exceeded for {signal.symbol}")

    # Set price with slippage
    slippage_bps = float(overrides.get("slippage_bps_max", _dg(cfg_d, "trading.slippage_bps_max", 3.0)))
    limit_price = PriceGuards.apply_slippage(price_for_sizing, slippage_bps, signal.side.value)

    # Build intent (limit, post-only by default for Kraken spot portability)
    intent = OrderIntent(
        symbol=signal.symbol,
        side=signal.side,  # Enum -> OK (use_enum_values=True in schemas)
        order_type=OrderType.LIMIT,
        price=limit_price,
        size_quote_usd=size_usd,
        post_only=True,
        metadata={
            "signal_id": signal.id,
            "strategy": signal.strategy,
            "confidence": signal.confidence,
            "spread_bps": spread_bps,
            "slippage_bps": slippage_bps,
            "plan_stable_id": stable_hash(signal.model_dump(mode="json")),
            "timestamp": time.time(),
        },
    )
    return intent


async def _redis_xadd_async(redis_mgr: Optional[Any], stream: str, fields: Dict[str, Any]) -> None:
    """Duck-typed helper to XADD into Redis if available."""
    if not redis_mgr:
        return
    client = getattr(redis_mgr, "client", None) or redis_mgr
    xadd = getattr(client, "xadd", None)
    if xadd is None:
        logger.debug("Redis client has no xadd; skipping publish")
        return
    packed = pack_stream_fields(fields)
    res = xadd(stream, packed)
    if asyncio.iscoroutine(res):
        await res


@retry(max_attempts=3, backoff_factor=1.5, jitter=True)
async def send_intent(
    intent: OrderIntent,
    exchange: ExchangePort,
    *,
    redis: Optional[Any] = None,
    dry_run: bool = False,
    ack_timeout_s: float = 5.0,
) -> dict:
    """
    Send OrderIntent to exchange with Redis tracking.

    - Publishes to streams orders:intent and orders:ack when redis is provided.
    - Uses duck-typed async redis client (.client with async methods).
    """
    if dry_run:
        return {
            "status": "simulated",
            "order_id": f"sim_{stable_hash(intent.model_dump(mode='json'))}",
            "intent_id": intent.id,
            "timestamp": time.time(),
        }

    # Publish intent to Redis (best-effort)
    await _redis_xadd_async(
        redis,
        "orders:intent",
        {
            "intent_id": intent.id,
            "symbol": intent.symbol,
            "side": intent.side.value if hasattr(intent.side, "value") else str(intent.side),
            "amount_usd": str(intent.size_quote_usd),
            "price": "" if intent.price is None else str(intent.price),
            "timestamp": str(time.time()),
        },
    )

    # Create exchange order
    with timer() as t:
        # amount in base units; guard price if missing (market)
        px = intent.price or max(1e-12, float(intent.metadata.get("last_mid", 0.0)) or 1.0)
        amount = float(intent.size_quote_usd) / px
        result = await exchange.create_order(
            symbol=intent.symbol,
            side=intent.side.value if hasattr(intent.side, "value") else str(intent.side),
            type=intent.order_type.value if hasattr(intent.order_type, "value") else str(intent.order_type),
            amount=amount,
            price=intent.price,
            params={"postOnly": intent.post_only, "reduceOnly": intent.reduce_only},
        )

    logger.info(f"Order created in {t.elapsed:.3f}s: {result.get('id')} for {intent.symbol}")

    # Wait for ack with timeout (best-effort)
    order_id = result.get("id")
    if order_id:
        try:
            with timer() as ack_timer:
                while ack_timer.elapsed < ack_timeout_s:
                    order_status = await exchange.fetch_order(order_id, intent.symbol)
                    st = (order_status or {}).get("status", "").lower()
                    if st in {"closed", "canceled", "rejected"}:
                        break
                    await asyncio.sleep(0.1)
        except Exception as e:
            logger.warning(f"Order ack check failed: {e}")

    # Publish ack to Redis (best-effort)
    if order_id:
        await _redis_xadd_async(
            redis,
            "orders:ack",
            {
                "order_id": order_id,
                "intent_id": intent.id,
                "status": result.get("status", "unknown"),
                "filled": str(result.get("filled", 0)),
                "timestamp": str(time.time()),
            },
        )

    return {
        "status": "sent",
        "order_id": order_id,
        "intent_id": intent.id,
        "exchange_result": result,
        "execution_time_s": t.elapsed,
    }


async def cancel_open(
    exchange: ExchangePort,
    symbol: str,
    *,
    stale_after_s: int = 60,
) -> int:
    """
    Cancel stale open orders for symbol.

    NOTE: Placeholder. Implement when order listing is available in ExchangePort.
    """
    logger.info(f"cancel_open called for {symbol} (stale_after_s={stale_after_s})")
    return 0


def emit_metric(
    kind: str,
    fields: Dict[str, Any],
    *,
    redis: Optional[Any] = None,
) -> None:
    """
    Emit metric tick to Redis stream.

    Safe in sync contexts: if there is no running event loop, it schedules
    an internal thread to run the async publisher.
    """
    try:
        required_fields = {
            "pnl": fields.get("pnl", {"realized": 0.0, "unrealized": 0.0}),
            "slippage_bps_p50": fields.get("slippage_bps_p50", 0.0),
            "latency_ms_p95": fields.get("latency_ms_p95", 0.0),
            "win_rate_1h": fields.get("win_rate_1h", 0.5),
            "drawdown_daily": fields.get("drawdown_daily", 0.0),
            "errors_rate": fields.get("errors_rate", 0.0),
        }
        metric = MetricsTick(**required_fields)

        async def _emit_async():
            await _redis_xadd_async(redis, "metrics:ticks", pack_stream_fields(metric.model_dump()))

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_emit_async())
        except RuntimeError:
            # No running loop: run in a fire-and-forget thread
            def _runner():
                asyncio.run(_emit_async())

            import threading

            threading.Thread(target=_runner, daemon=True).start()

    except Exception as e:
        logger.error(f"Failed to emit metric {kind}: {e}")


# Module exports
__all__ = [
    "ExchangePort",
    "NullExchange",
    "DelegatingExchange",
    "OrderPlan",
    "PositionSizer",
    "PriceGuards",
    "RiskChecks",
    "IdempotencyStore",
    "build_order_intent",
    "send_intent",
    "cancel_open",
    "emit_metric",
    "ExecutionError",
    "RiskCheckError",
    "PriceGuardError",
    "IdempotencyError",
]
