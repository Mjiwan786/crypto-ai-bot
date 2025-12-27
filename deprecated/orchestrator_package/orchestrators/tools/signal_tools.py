"""
Signal toolkit for crypto-ai-bot: feature computation, validation, filtering & publishing.

Flow: OHLCV+news → features → regime/sentiment enrich → validate → filter/throttle → dedup → Signal → publish

Handles TA features, anomaly detection, Redis streaming with MCP schemas.
Production-ready with graceful degradation when dependencies unavailable.
"""

from __future__ import annotations

import math
import re
import statistics
import time
from collections import deque
from typing import Any, Dict, List, Optional, Set, Tuple

from pydantic import BaseModel, Field, field_validator

# Import shim pattern for flexible deployment
try:
    from config.config_loader import get_config
except Exception:  # pragma: no cover
    from ...config.config_loader import get_config  # type: ignore

try:
    from mcp.schemas import VersionedBaseModel, Signal, OrderSide
except Exception:  # pragma: no cover
    from ...mcp.schemas import VersionedBaseModel, Signal, OrderSide  # type: ignore

try:
    from mcp.redis_manager import RedisManager
except Exception:  # pragma: no cover
    from ...mcp.redis_manager import RedisManager  # type: ignore

try:
    from mcp.marshaling import pack_stream_fields, stable_hash, serialize_event
except Exception:  # pragma: no cover
    from ...mcp.marshaling import pack_stream_fields, stable_hash, serialize_event  # type: ignore

try:
    from ai_engine.regime_detector.deep_ta_analyzer import compute_ta_bundle
    from ai_engine.regime_detector.sentiment_analyzer import SentimentSnapshot
    from ai_engine.regime_detector.macro_analyzer import MacroSnapshot
except Exception:  # pragma: no cover
    compute_ta_bundle = None  # type: ignore
    SentimentSnapshot = object  # type: ignore
    MacroSnapshot = object  # type: ignore

try:
    from utils.logger import get_logger
    from utils.timer import timer
except Exception:  # pragma: no cover
    from ...utils.logger import get_logger  # type: ignore
    from ...utils.timer import timer  # type: ignore


# Module logger
logger = get_logger(__name__)

# Constants
STREAM_RAW = "signals:raw"
STREAM_FILTERED = "signals:filtered"
STREAM_METRICS = "metrics:signals"
METRIC_KINDS = ["signal_raw", "signal_filtered", "signal_dropped", "signal_throttled"]

# Validation patterns
SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]+/[A-Z0-9]+$")
TIMEFRAME_PATTERN = re.compile(r"^\d+(s|m|h|d|w)$")


# Module exceptions
class SignalConfigError(Exception):
    """Signal configuration error."""
    pass


class SignalValidationError(Exception):
    """Signal validation error."""
    pass


# Typed models
class FeatureFrame(VersionedBaseModel):
    """Compact container for computed features."""
    type: str = "feature_frame"
    symbol: str = Field(description="Trading symbol")
    timeframe: str = Field(description="Timeframe")
    timestamp: float = Field(description="UTC epoch seconds")
    price: float = Field(description="Current price")
    bid: Optional[float] = Field(default=None, description="Bid price")
    ask: Optional[float] = Field(default=None, description="Ask price")
    mid: Optional[float] = Field(default=None, description="Mid price")

    # Technical indicators
    rsi: Optional[float] = Field(default=None, description="RSI")
    macd: Optional[float] = Field(default=None, description="MACD")
    macd_signal: Optional[float] = Field(default=None, description="MACD signal")
    bb_upper: Optional[float] = Field(default=None, description="Bollinger upper")
    bb_lower: Optional[float] = Field(default=None, description="Bollinger lower")
    atr: Optional[float] = Field(default=None, description="ATR")
    volatility: Optional[float] = Field(default=None, description="Volatility")
    mom: Optional[float] = Field(default=None, description="Momentum")
    ema_fast: Optional[float] = Field(default=None, description="Fast EMA")
    ema_slow: Optional[float] = Field(default=None, description="Slow EMA")
    returns_n: Optional[float] = Field(default=None, description="N-period returns")

    # Order flow features
    of_imbalance: Optional[float] = Field(default=None, description="Order flow imbalance")
    depth_ratio: Optional[float] = Field(default=None, description="Depth ratio")

    # Flexible extras
    extra: Dict[str, float] = Field(default_factory=dict, description="Additional features")

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, v: str) -> str:
        v = v.upper()
        if not SYMBOL_PATTERN.match(v):
            raise ValueError("Symbol must match BASE/QUOTE format (e.g., BTC/USD)")
        return v

    @field_validator("timeframe")
    @classmethod
    def validate_timeframe(cls, v: str) -> str:
        if not TIMEFRAME_PATTERN.match(v):
            raise ValueError("Timeframe must be like 15s, 1m, 1h, 1d, 1w")
        return v

    @field_validator(
        "price", "bid", "ask", "mid", "rsi", "macd", "macd_signal",
        "bb_upper", "bb_lower", "atr", "volatility", "mom",
        "ema_fast", "ema_slow", "returns_n", "of_imbalance", "depth_ratio"
    )
    @classmethod
    def validate_numeric(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not math.isfinite(v):
            raise ValueError("Numeric values must be finite")
        return v


class SignalPlan(VersionedBaseModel):
    """Pre-signal decision record."""
    type: str = "signal_plan"
    symbol: str = Field(description="Trading symbol")
    timeframe: str = Field(description="Timeframe")
    side: str = Field(description="Trade side", pattern="^(buy|sell)$")
    confidence: float = Field(ge=0.0, le=1.0, description="Signal confidence")
    features: Dict[str, float] = Field(description="Feature values")
    regime: Optional[str] = Field(default=None, description="Market regime")
    sentiment: Optional[float] = Field(default=None, description="Sentiment score")
    macro_score: Optional[float] = Field(default=None, description="Macro score")
    throttle_key: str = Field(description="Throttling key")
    idempotency_key: str = Field(description="Deduplication key")
    tags: Dict[str, str] = Field(default_factory=dict, description="Additional tags")

    def stable_id(self) -> str:
        """Generate stable hash ID."""
        data = {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "side": self.side,
            "confidence": round(self.confidence, 4),
            "features": dict(sorted(self.features.items())),
            "idempotency_key": self.idempotency_key,
        }
        return stable_hash(data)


class SignalFilters(BaseModel):
    """Runtime filtering thresholds."""
    min_confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    min_volume: Optional[float] = Field(default=None, ge=0.0)
    max_spread_bps: float = Field(default=10.0, ge=0.0)
    max_latency_ms: float = Field(default=500.0, ge=0.0)
    zscore_limit: float = Field(default=3.0, ge=0.0)
    throttle_s: int = Field(default=30, ge=0)
    dedup_ttl_s: int = Field(default=300, ge=0)
    allow_side: Set[str] = Field(default={"buy", "sell"})
    blocked_symbols: List[str] = Field(default_factory=list)
    required_features: List[str] = Field(default_factory=list)


# Feature computation utilities
def rsi(series: List[float], period: int = 14) -> float:
    """Calculate RSI (Relative Strength Index)."""
    if len(series) < period + 1:
        return 50.0

    deltas = [series[i] - series[i - 1] for i in range(1, len(series))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def ema(series: List[float], period: int) -> float:
    """Calculate Exponential Moving Average (last value)."""
    if not series:
        return 0.0
    alpha = 2.0 / (period + 1.0)
    ema_val = series[0]
    for price in series[1:]:
        ema_val = alpha * price + (1.0 - alpha) * ema_val
    return ema_val


def macd(series: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[float, float]:
    """Calculate MACD (fast EMA - slow EMA) and its signal line (EMA of MACD)."""
    if len(series) < slow + signal:
        return 0.0, 0.0

    # Build MACD history to compute the signal EMA over the last `signal` points.
    macd_hist: List[float] = []
    alpha_fast = 2.0 / (fast + 1.0)
    alpha_slow = 2.0 / (slow + 1.0)
    ema_fast_val = series[0]
    ema_slow_val = series[0]

    for price in series:
        ema_fast_val = alpha_fast * price + (1.0 - alpha_fast) * ema_fast_val
        ema_slow_val = alpha_slow * price + (1.0 - alpha_slow) * ema_slow_val
        macd_hist.append(ema_fast_val - ema_slow_val)

    macd_line = macd_hist[-1]
    signal_line = ema(macd_hist[-signal:], signal) if len(macd_hist) >= signal else macd_line
    return macd_line, signal_line


def bollinger(series: List[float], period: int = 20, std_mult: float = 2.0) -> Tuple[float, float, float]:
    """Calculate Bollinger Bands (upper, middle, lower)."""
    if len(series) < period:
        price = series[-1] if series else 0.0
        return price, price, price

    recent = series[-period:]
    mean = sum(recent) / len(recent)
    variance = sum((x - mean) ** 2 for x in recent) / len(recent)
    std_dev = math.sqrt(variance)

    upper = mean + (std_mult * std_dev)
    lower = mean - (std_mult * std_dev)
    return upper, mean, lower


def atr(high: List[float], low: List[float], close: List[float], period: int = 14) -> float:
    """Calculate Average True Range."""
    if len(high) < 2 or len(low) < 2 or len(close) < 2:
        return 0.0

    true_ranges: List[float] = []
    last = min(len(high), len(low), len(close))
    for i in range(1, last):
        tr = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )
        true_ranges.append(tr)

    if not true_ranges:
        return 0.0
    if len(true_ranges) < period:
        return sum(true_ranges) / len(true_ranges)
    return sum(true_ranges[-period:]) / period


def volatility_annualized(returns: List[float], periods_per_year: int) -> float:
    """Calculate annualized volatility."""
    if len(returns) < 2:
        return 0.0
    variance = statistics.variance(returns)
    return math.sqrt(variance * periods_per_year)


def zscore(value: float, mean: float, std: float, eps: float = 1e-12) -> float:
    """Calculate z-score with epsilon guard."""
    return (value - mean) / max(std, eps)


def compute_features_via_ai_engine(ohlcv: Dict[str, List[float]], extras: Dict[str, Any]) -> FeatureFrame:
    """Compute features using AI engine if available, otherwise fallback."""
    if compute_ta_bundle is None:
        logger.warning("AI engine not available, using fallback features")
        return _compute_features_fallback(ohlcv, extras)
    try:
        result = compute_ta_bundle(ohlcv, extras)
        return FeatureFrame(**result)
    except Exception as e:
        logger.warning(f"AI engine failed: {e}, using fallback")
        return _compute_features_fallback(ohlcv, extras)


def _compute_features_fallback(ohlcv: Dict[str, List[float]], extras: Dict[str, Any]) -> FeatureFrame:
    """Fallback feature computation using local functions."""
    close = ohlcv.get("close", [])
    high = ohlcv.get("high", [])
    low = ohlcv.get("low", [])

    if not close:
        raise SignalValidationError("No price data available")

    current_price = close[-1]

    # Calculate features
    rsi_val = rsi(close)
    macd_val, macd_sig = macd(close)
    bb_upper, _bb_mid, bb_lower = bollinger(close)
    atr_val = atr(high, low, close)
    ema_fast_val = ema(close, 12)
    ema_slow_val = ema(close, 26)

    # Returns & volatility
    returns_n = (close[-1] / close[-2] - 1.0) if len(close) >= 2 else 0.0
    returns = [(close[i] / close[i - 1] - 1.0) for i in range(1, len(close))]
    vol = volatility_annualized(returns, 365) if len(returns) >= 2 else 0.0

    bid = extras.get("bid")
    ask = extras.get("ask")
    mid = ((bid + ask) / 2.0) if (bid is not None and ask is not None) else None

    return FeatureFrame(
        symbol=extras.get("symbol", "UNKNOWN/USD"),
        timeframe=extras.get("timeframe", "1m"),
        timestamp=time.time(),
        price=current_price,
        bid=bid,
        ask=ask,
        mid=mid,
        rsi=rsi_val,
        macd=macd_val,
        macd_signal=macd_sig,
        bb_upper=bb_upper,
        bb_lower=bb_lower,
        atr=atr_val,
        volatility=vol,
        ema_fast=ema_fast_val,
        ema_slow=ema_slow_val,
        returns_n=returns_n,
        of_imbalance=extras.get("of_imbalance"),
        depth_ratio=extras.get("depth_ratio"),
        extra=extras.get("extra", {}),
    )


# Anomaly detection
class AnomalyDetector:
    """Simple rolling z-score anomaly detector."""

    def __init__(self, window: int = 100, zscore_limit: float = 3.0, min_obs: int = 10):
        self.window = window
        self.zscore_limit = zscore_limit
        self.min_obs = min_obs
        self.values = deque(maxlen=window)

    def fit_push(self, value: float) -> Dict[str, Any]:
        """Add value and return anomaly assessment."""
        self.values.append(value)

        if len(self.values) < self.min_obs:
            return {"is_anomaly": False, "z": 0.0, "mean": value, "std": 0.0}

        mean = statistics.mean(self.values)
        std = statistics.stdev(self.values) if len(self.values) > 1 else 0.0
        z = zscore(value, mean, std)
        is_anomaly = abs(z) > self.zscore_limit

        return {"is_anomaly": is_anomaly, "z": z, "mean": mean, "std": std}


# Redis streaming and throttling
class StreamPublisher:
    """Redis stream publisher with fallback & bounded streams."""

    def __init__(self, maxlen_raw: int = 10_000, maxlen_metrics: int = 10_000):
        self._redis: Optional[RedisManager] = None
        self._initialized = False
        self._maxlen_raw = maxlen_raw
        self._maxlen_metrics = maxlen_metrics

    async def _ensure_redis(self) -> None:
        """Lazy Redis initialization."""
        if self._initialized:
            return
        try:
            cfg = get_config()
            self._redis = await RedisManager.get_or_create(url=cfg.redis.url)
            logger.info("Redis stream publisher initialized")
        except Exception as e:
            logger.warning(f"Redis not available for streaming: {e}")
            self._redis = None
        finally:
            self._initialized = True

    @timer("publish_signal")
    async def publish_signal(self, stream: str, sig: Signal) -> str:
        """Publish signal to Redis stream."""
        await self._ensure_redis()

        if not self._redis:
            logger.debug("No Redis available, skipping signal publish")
            return "no-redis"

        try:
            data = serialize_event(sig)
            entry_id = await self._redis.client.xadd(
                stream, data, maxlen=self._maxlen_raw, approximate=True
            )
            logger.debug(f"Published signal to {stream}: {entry_id}")
            return str(entry_id)
        except Exception as e:
            logger.error(f"Failed to publish signal to {stream}: {e}")
            return "error"

    @timer("publish_metric")
    async def publish_metric(self, kind: str, fields: Dict[str, Any]) -> None:
        """Publish metric to Redis stream."""
        await self._ensure_redis()
        if not self._redis:
            return

        try:
            event = {
                "kind": kind,
                "timestamp": time.time(),
                **fields,
            }
            payload = pack_stream_fields(event)
            await self._redis.client.xadd(
                STREAM_METRICS, payload, maxlen=self._maxlen_metrics, approximate=True
            )
        except Exception as e:
            logger.error(f"Failed to publish metric {kind}: {e}")


class ThrottleDedupStore:
    """Redis-backed throttling and deduplication with in-memory fallback."""

    def __init__(self):
        self._redis: Optional[RedisManager] = None
        self._initialized = False
        self._memory_cache: Dict[str, bool] = {}
        self._memory_ttls: Dict[str, float] = {}

    async def _ensure_redis(self) -> None:
        """Lazy Redis initialization."""
        if self._initialized:
            return
        try:
            cfg = get_config()
            self._redis = await RedisManager.get_or_create(url=cfg.redis.url)
        except Exception as e:
            logger.warning(f"Redis not available for throttle/dedup: {e}")
            self._redis = None
        finally:
            self._initialized = True

    def _cleanup_memory(self) -> None:
        """Clean expired in-memory entries."""
        now = time.time()
        expired = [k for k, ttl in self._memory_ttls.items() if ttl < now]
        for key in expired:
            self._memory_cache.pop(key, None)
            self._memory_ttls.pop(key, None)

    async def is_throttled(self, key: str, throttle_s: int) -> bool:
        """Return True if throttled (already set within window)."""
        await self._ensure_redis()

        if self._redis:
            try:
                result = await self._redis.client.set(f"throttle:{key}", "1", ex=throttle_s, nx=True)
                return result is None  # None => key existed => throttled
            except Exception as e:
                logger.debug(f"Redis throttle check failed: {e}")

        # Fallback to memory
        self._cleanup_memory()
        mkey = f"throttle:{key}"
        if mkey in self._memory_cache:
            return True
        self._memory_cache[mkey] = True
        self._memory_ttls[mkey] = time.time() + throttle_s
        return False

    async def is_duplicate(self, key: str, ttl_s: int) -> bool:
        """Return True if duplicate (idempotency key within TTL)."""
        await self._ensure_redis()

        if self._redis:
            try:
                result = await self._redis.client.set(f"dedup:{key}", "1", ex=ttl_s, nx=True)
                return result is None  # None => key existed => duplicate
            except Exception as e:
                logger.debug(f"Redis dedup check failed: {e}")

        # Fallback to memory
        self._cleanup_memory()
        mkey = f"dedup:{key}"
        if mkey in self._memory_cache:
            return True
        self._memory_cache[mkey] = True
        self._memory_ttls[mkey] = time.time() + ttl_s
        return False


# Signal pipeline helpers
def validate_features(ff: FeatureFrame, filters: SignalFilters) -> Tuple[bool, List[str]]:
    """Validate features against filters and basic market sanity."""
    issues: List[str] = []

    # Required features present
    feature_dict = {
        "rsi": ff.rsi,
        "macd": ff.macd,
        "atr": ff.atr,
        "volatility": ff.volatility,
        "returns_n": ff.returns_n,
        **ff.extra,
    }
    for req_feature in filters.required_features:
        if feature_dict.get(req_feature) is None:
            issues.append(f"missing_feature_{req_feature}")

    # Spread check (bps over mid)
    if ff.bid is not None and ff.ask is not None:
        mid = (ff.bid + ff.ask) / 2.0
        if mid > 0.0:
            spread_bps = ((ff.ask - ff.bid) / mid) * 10_000.0
            if spread_bps > filters.max_spread_bps:
                issues.append("spread_too_wide")

    # Volume check
    if filters.min_volume is not None and ff.extra.get("volume", 0.0) < filters.min_volume:
        issues.append("insufficient_volume")

    return len(issues) == 0, issues


def enrich_with_regime_and_sentiment(
    ff: FeatureFrame,
    *,
    regime: Optional[str],
    sentiment: Optional[float],
    macro_score: Optional[float],
) -> Dict[str, Any]:
    """Enrich feature frame dict with regime and sentiment."""
    enriched = ff.model_dump()
    if regime:
        enriched["regime"] = regime
    if sentiment is not None:
        enriched["sentiment"] = sentiment
    if macro_score is not None:
        enriched["macro_score"] = macro_score
    return enriched


def plan_to_signal(plan: SignalPlan) -> Signal:
    """Convert SignalPlan to MCP Signal."""
    return Signal(
        strategy=plan.tags.get("strategy", "default"),
        symbol=plan.symbol,
        timeframe=plan.timeframe,
        side=OrderSide.BUY if plan.side == "buy" else OrderSide.SELL,
        confidence=plan.confidence,
        features=plan.features,
        risk=(
            {
                "regime": plan.regime,
                "sentiment": plan.sentiment,
                "macro_score": plan.macro_score,
            }
            if any([plan.regime, plan.sentiment, plan.macro_score])
            else None
        ),
        notes=f"Generated from plan {plan.stable_id()}",
    )


async def process_and_publish(
    plan: SignalPlan,
    ff: FeatureFrame,
    filters: SignalFilters,
    *,
    cfg=None,
    publisher: Optional[StreamPublisher] = None,
    store: Optional[ThrottleDedupStore] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Process signal plan through full pipeline and publish to Redis."""
    result: Dict[str, Any] = {
        "allowed": False,
        "reason": [],
        "raw_id": None,
        "filtered_id": None,
        "signal_id": plan.stable_id(),
        "stable_hash": stable_hash(plan.model_dump()),
    }

    if not cfg:
        cfg = get_config()

    if not publisher:
        publisher = StreamPublisher()

    if not store:
        store = ThrottleDedupStore()

    # Confidence
    if plan.confidence < filters.min_confidence:
        result["reason"].append("low_confidence")

    # Side
    if plan.side not in filters.allow_side:
        result["reason"].append("side_not_allowed")

    # Symbol blocker
    if not symbol_allowed(plan.symbol, filters):
        result["reason"].append("symbol_blocked")

    # Feature validation
    features_valid, feature_issues = validate_features(ff, filters)
    if not features_valid:
        result["reason"].extend(feature_issues)

    # Throttle
    if not dry_run:
        throttled = await store.is_throttled(plan.throttle_key, filters.throttle_s)
        if throttled:
            result["reason"].append("throttled")

    # Dedup
    if not dry_run:
        duplicate = await store.is_duplicate(plan.idempotency_key, filters.dedup_ttl_s)
        if duplicate:
            result["reason"].append("duplicate")

    # Publish raw always (unless pure blocking in dry-run=false AND we explicitly want drops only as metrics)
    if not result["reason"] or dry_run:
        signal = plan_to_signal(plan)

        if not dry_run:
            result["raw_id"] = await publisher.publish_signal(STREAM_RAW, signal)
            await publisher.publish_metric("signal_raw", {"count": 1})

        # If fully clean → filtered
        if not result["reason"]:
            result["allowed"] = True
            if not dry_run:
                result["filtered_id"] = await publisher.publish_signal(STREAM_FILTERED, signal)
                await publisher.publish_metric("signal_filtered", {"count": 1})
        else:
            if not dry_run:
                await publisher.publish_metric(
                    "signal_dropped", {"count": 1, "reasons": list(result["reason"])}
                )
    else:
        if not dry_run:
            await publisher.publish_metric(
                "signal_dropped", {"count": 1, "reasons": list(result["reason"])}
            )

    return result


# Backfill and window loading
class BackfillLoader:
    """Helper for loading and validating historical OHLCV data."""

    def __init__(self, ohlcv: Dict[str, List[float]]):
        self.ohlcv = self._validate_ohlcv(ohlcv)

    def _validate_ohlcv(self, ohlcv: Dict[str, List[float]]) -> Dict[str, List[float]]:
        """Validate OHLCV data structure."""
        required_keys = ["open", "high", "low", "close", "volume"]

        for key in required_keys:
            if key not in ohlcv:
                raise SignalValidationError(f"Missing OHLCV key: {key}")

        lengths = [len(ohlcv[key]) for key in required_keys]
        if len(set(lengths)) > 1:
            raise SignalValidationError("OHLCV arrays must have the same length")

        # Check finite & positive for prices, finite for volume
        for key in required_keys:
            for i, val in enumerate(ohlcv[key]):
                if not math.isfinite(val):
                    raise SignalValidationError(f"Invalid value in {key}[{i}]: {val}")
                if key in ["open", "high", "low", "close"] and val <= 0:
                    raise SignalValidationError(f"Price values must be positive in {key}[{i}]: {val}")
                if key == "volume" and val < 0:
                    raise SignalValidationError(f"Volume must be non-negative in volume[{i}]: {val}")

        return ohlcv

    def to_feature_frame(self, symbol: str, timeframe: str) -> FeatureFrame:
        """Convert OHLCV data to FeatureFrame using latest values."""
        if not self.ohlcv["close"]:
            raise SignalValidationError("No price data available")

        extras = {
            "symbol": symbol,
            "timeframe": timeframe,
            "extra": {"volume": self.ohlcv["volume"][-1] if self.ohlcv["volume"] else 0.0},
        }
        return compute_features_via_ai_engine(self.ohlcv, extras)


# Configuration helpers
_CFG_CACHE = None


def get_cached_config():
    """Get cached configuration."""
    global _CFG_CACHE
    if _CFG_CACHE is None:
        _CFG_CACHE = get_config()
    return _CFG_CACHE


def default_filters_from_cfg(cfg=None) -> SignalFilters:
    """Create default filters from configuration."""
    if not cfg:
        cfg = get_cached_config()

    try:
        return SignalFilters(
            min_confidence=getattr(cfg.signals, "min_confidence", 0.6),
            max_spread_bps=getattr(cfg.signals, "max_spread_bps", 10.0),
            throttle_s=getattr(cfg.signals, "throttle_s", 30),
            dedup_ttl_s=getattr(cfg.signals, "dedup_ttl_s", 300),
            required_features=getattr(cfg.signals, "required_features", []),
        )
    except AttributeError:
        logger.warning("Signal config not found, using defaults")
        return SignalFilters()


def symbol_allowed(symbol: str, filters: SignalFilters) -> bool:
    """Check if symbol is allowed by filters (blocklist regex)."""
    for pattern in filters.blocked_symbols:
        if re.search(pattern, symbol, re.IGNORECASE):
            return False
    return True


# Module exports
__all__ = [
    # Models
    "FeatureFrame",
    "SignalPlan",
    "SignalFilters",
    # Classes
    "AnomalyDetector",
    "StreamPublisher",
    "ThrottleDedupStore",
    "BackfillLoader",
    # Feature functions
    "rsi",
    "ema",
    "macd",
    "bollinger",
    "atr",
    "volatility_annualized",
    "zscore",
    # Pipeline
    "validate_features",
    "enrich_with_regime_and_sentiment",
    "plan_to_signal",
    "process_and_publish",
    # Config helpers
    "default_filters_from_cfg",
    "symbol_allowed",
    # Exceptions
    "SignalConfigError",
    "SignalValidationError",
]
