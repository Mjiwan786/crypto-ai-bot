"""
ai_engine/global_context.py

Production-ready deterministic global context layer for the AI Engine.
Provides frozen configurations, clock injection, TTL cache, rate limiting,
and event correlation with zero external dependencies.

Example usage:
    from ai_engine.global_context import (
        GlobalConfig, AppInfo, ClockConfig, CacheConfig, RateLimitConfig, RiskBudgets,
        EventMeta, DeterministicClock, TTLCache, TokenBucket, GlobalContext, make_correlation_id
    )

    app = AppInfo(name="crypto_ai_bot", version="1.0.0", env="staging")
    cfg = GlobalConfig(app=app, clock=ClockConfig(), cache=CacheConfig(), rate_limits={"signals": RateLimitConfig()}, risk=RiskBudgets())
    clock = DeterministicClock(now_ms=1700000000000, cfg=cfg.clock)
    ctx = GlobalContext(
        cfg=cfg,
        clock=clock,
        event_meta=EventMeta(source="ai_engine", correlation_id=make_correlation_id("seed"), partition_key="BTCUSDT"),
        cache=TTLCache(cfg.cache, clock),
        limiters={"signals": TokenBucket(cfg.rate_limits["signals"], clock)}
    )
    latency_ms, over = ctx.check_latency(start_ms=1700000000000)
"""

from __future__ import annotations

import contextvars
import hashlib
import logging
import math
from typing import Any, Dict, Generic, Literal, Optional, Tuple, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    # Config models
    "AppInfo", "ClockConfig", "CacheConfig", "RateLimitConfig", "RiskBudgets", "GlobalConfig",
    # Event metadata
    "EventMeta", "make_correlation_id",
    # Core components
    "DeterministicClock", "TTLCache", "TokenBucket", "GlobalContext",
    # Context vars
    "set_current", "get_current", "reset_current",
    # Exceptions
    "ClockNotSetError", "MonotonicViolationError", "CapacityExceededError", "ConfigError",
]

logger = logging.getLogger(__name__)

# Type variable for generic cache
T = TypeVar("T")


# =============================================================================
# Exceptions
# =============================================================================

class ClockNotSetError(ValueError):
    """Raised when DeterministicClock.now_ms is accessed without being set."""
    pass


class MonotonicViolationError(ValueError):
    """Raised when monotonic time enforcement fails."""
    pass


class CapacityExceededError(ValueError):
    """Raised when cache capacity is exceeded."""
    pass


class ConfigError(ValueError):
    """Raised for invalid configuration values."""
    pass


# =============================================================================
# Utilities
# =============================================================================

def _sha256_str(s: str) -> str:
    """Create deterministic SHA256 hash of string."""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _sorted_dict(d: Dict[str, Any]) -> Dict[str, Any]:
    """Return dict with sorted keys for deterministic serialization."""
    return {k: d[k] for k in sorted(d.keys())}


def _deep_sorted(obj: Any) -> Any:
    """Recursively sort dict keys and normalize nested structures deterministically."""
    if isinstance(obj, dict):
        return {k: _deep_sorted(obj[k]) for k in sorted(obj.keys())}
    if isinstance(obj, list):
        return [_deep_sorted(v) for v in obj]
    return obj


# =============================================================================
# Configuration Models
# =============================================================================

class AppInfo(BaseModel):
    """Application identification information."""
    name: str = Field(min_length=1, description="Application name")
    version: str = Field(min_length=1, description="Application version")
    env: Literal["dev", "staging", "prod"] = Field(description="Environment")

    model_config = ConfigDict(frozen=True, extra="forbid")


class ClockConfig(BaseModel):
    """Configuration for deterministic clock behavior."""
    enforce_monotonic: bool = Field(default=True, description="Enforce monotonic time progression")

    model_config = ConfigDict(frozen=True, extra="forbid")


class CacheConfig(BaseModel):
    """Configuration for TTL cache."""
    max_items: int = Field(default=1024, ge=1, description="Maximum cache items")
    default_ttl_ms: int = Field(default=60_000, ge=1, description="Default TTL in milliseconds")

    model_config = ConfigDict(frozen=True, extra="forbid")


class RateLimitConfig(BaseModel):
    """Configuration for token bucket rate limiter."""
    capacity: int = Field(default=10, ge=1, description="Token bucket capacity")
    refill_per_ms: float = Field(default=0.01, ge=0.0, description="Tokens refilled per millisecond")

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("capacity")
    @classmethod
    def _validate_capacity(cls, v: int) -> int:
        if not isinstance(v, int) or v <= 0:
            raise ValueError("capacity must be a positive integer")
        return v

    @field_validator("refill_per_ms")
    @classmethod
    def _validate_refill(cls, v: float) -> float:
        # ge=0.0 doesn't reject NaN/Inf; enforce finite and non-negative
        if not isinstance(v, (int, float)) or not math.isfinite(float(v)) or v < 0.0:
            raise ValueError("refill_per_ms must be a finite, non-negative number")
        return float(v)


class RiskBudgets(BaseModel):
    """Risk budget limits."""
    latency_budget_ms: int = Field(default=250, ge=0, description="Latency budget in milliseconds")
    daily_stop_usd: float = Field(default=0.0, ge=0.0, description="Daily stop loss in USD")
    spread_bps_cap: float = Field(default=50.0, ge=0.0, description="Maximum spread in basis points")

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("latency_budget_ms")
    @classmethod
    def _validate_latency_budget(cls, v: int) -> int:
        if not isinstance(v, int) or v < 0:
            raise ValueError("latency_budget_ms must be a non-negative integer")
        return v

    @field_validator("daily_stop_usd", "spread_bps_cap")
    @classmethod
    def _finite_non_negative(cls, v: float) -> float:
        if not isinstance(v, (int, float)) or not math.isfinite(float(v)) or v < 0.0:
            raise ValueError("risk budget values must be finite and non-negative")
        return float(v)


class GlobalConfig(BaseModel):
    """Global configuration aggregating all component configs."""
    app: AppInfo = Field(description="Application information")
    clock: ClockConfig = Field(default_factory=ClockConfig, description="Clock configuration")
    cache: CacheConfig = Field(default_factory=CacheConfig, description="Cache configuration")
    rate_limits: Dict[str, RateLimitConfig] = Field(default_factory=dict, description="Rate limit configs by name")
    risk: RiskBudgets = Field(default_factory=RiskBudgets, description="Risk budget limits")
    schema_version: str = Field(default="1.0", description="Configuration schema version")

    model_config = ConfigDict(frozen=True, extra="forbid")

    def model_dump(self, **kwargs) -> Dict[str, Any]:
        """Override to ensure deterministic dict ordering (deep)."""
        result = super().model_dump(**kwargs)
        # Deep-sort to stabilize nested mappings like rate_limits
        return _deep_sorted(result)


# =============================================================================
# Event Metadata & Correlation
# =============================================================================

class EventMeta(BaseModel):
    """Event metadata for correlation and partitioning."""
    source: str = Field(min_length=1, description="Event source identifier")
    correlation_id: str = Field(min_length=1, description="Correlation ID for tracing")
    partition_key: str = Field(min_length=1, description="Partitioning key")
    schema_version: str = Field(default="1.0", description="Event schema version")
    meta: Dict[str, str] = Field(default_factory=dict, description="Additional metadata")

    model_config = ConfigDict(frozen=True, extra="forbid")

    def to_event_kwargs(self) -> Dict[str, Any]:
        """Return dict suitable for event constructors."""
        return _sorted_dict({
            "source": self.source,
            "correlation_id": self.correlation_id,
            "partition_key": self.partition_key,
            "schema_version": self.schema_version,
            "meta": _sorted_dict(self.meta),
        })

    def model_dump(self, **kwargs) -> Dict[str, Any]:
        """Override to ensure deterministic dict ordering (deep)."""
        return _deep_sorted(super().model_dump(**kwargs))


def make_correlation_id(*parts: str) -> str:
    """Create deterministic correlation ID from string parts using SHA256."""
    if not parts:
        raise ValueError("At least one part required for correlation ID")
    combined = ":".join(str(p) for p in parts)
    return _sha256_str(combined)[:16]  # Use first 16 chars for brevity


# =============================================================================
# Deterministic Clock
# =============================================================================

class DeterministicClock:
    """Clock that returns injected time values for deterministic behavior."""
    __slots__ = ("_now_ms", "_cfg")

    def __init__(self, now_ms: Optional[int] = None, cfg: Optional[ClockConfig] = None):
        """Initialize clock with optional current time and config."""
        self._now_ms = now_ms
        self._cfg = cfg or ClockConfig()

    @property
    def cfg(self) -> ClockConfig:
        """Get clock configuration."""
        return self._cfg

    def now_ms(self) -> int:
        """Get current time in milliseconds. Raises ClockNotSetError if not set."""
        if self._now_ms is None:
            raise ClockNotSetError("Clock time not set - use set_now_ms() first")
        return self._now_ms

    def set_now_ms(self, now_ms: int) -> "DeterministicClock":
        """Return new clock with updated time (immutable pattern)."""
        if now_ms < 0:
            raise ValueError("Time cannot be negative")
        return DeterministicClock(now_ms=now_ms, cfg=self._cfg)

    def monotonic_guard(self, prev_ms: int, next_ms: int) -> int:
        """Check monotonic constraint if enabled. Return next_ms or raise."""
        if self._cfg.enforce_monotonic and next_ms < prev_ms:
            raise MonotonicViolationError(f"Monotonic violation: {next_ms} < {prev_ms}")
        return next_ms

    def __repr__(self) -> str:
        return f"DeterministicClock(now_ms={self._now_ms}, enforce_monotonic={self._cfg.enforce_monotonic})"


# =============================================================================
# TTL Cache
# =============================================================================

class TTLCache(Generic[T]):
    """In-memory TTL cache using deterministic clock."""
    __slots__ = ("_cfg", "_clock", "_data")

    def __init__(self, cfg: CacheConfig, clock: DeterministicClock):
        """Initialize cache with configuration and clock."""
        self._cfg = cfg
        self._clock = clock
        self._data: Dict[str, Tuple[T, int]] = {}  # key -> (value, expires_at_ms)

    def _evict_expired(self) -> None:
        """Remove expired entries."""
        now_ms = self._clock.now_ms()
        expired_keys = [key for key, (_, expires_at) in self._data.items() if expires_at <= now_ms]
        for key in expired_keys:
            del self._data[key]
            logger.debug(f"Evicted expired cache entry: {key}")

    def _enforce_capacity(self) -> None:
        """Ensure cache size doesn't exceed max_items."""
        if len(self._data) <= self._cfg.max_items:
            return

        # Sort by expires_at then by key for deterministic eviction
        sorted_items = sorted(self._data.items(), key=lambda x: (x[1][1], x[0]))  # (expires_at, key)

        excess = len(self._data) - self._cfg.max_items
        for key, _ in sorted_items[:excess]:
            del self._data[key]
            logger.debug(f"Evicted cache entry for capacity: {key}")

    def get(self, key: str) -> Tuple[bool, Optional[T]]:
        """Get value from cache. Returns (found, value)."""
        self._evict_expired()

        if key not in self._data:
            return False, None

        value, _ = self._data[key]
        return True, value

    def set(self, key: str, value: T, ttl_ms: Optional[int] = None) -> None:
        """Set value in cache with optional TTL override."""
        ttl = ttl_ms if ttl_ms is not None else self._cfg.default_ttl_ms
        if ttl <= 0:
            raise ValueError("TTL must be positive")

        expires_at = self._clock.now_ms() + ttl
        self._data[key] = (value, expires_at)

        self._enforce_capacity()
        logger.debug(f"Set cache entry: {key} (expires in {ttl}ms)")

    def delete(self, key: str) -> None:
        """Delete key from cache."""
        if key in self._data:
            del self._data[key]
            logger.debug(f"Deleted cache entry: {key}")

    def size(self) -> int:
        """Get current cache size after evicting expired entries."""
        self._evict_expired()
        return len(self._data)

    def size_approx(self) -> int:
        """Get current cache size without eviction (no side effects)."""
        return len(self._data)

    def clear(self) -> None:
        """Clear all cache entries."""
        self._data.clear()
        logger.debug("Cleared cache")


# =============================================================================
# Token Bucket Rate Limiter
# =============================================================================

class TokenBucket:
    """Token bucket rate limiter using deterministic clock."""
    __slots__ = ("_cfg", "_clock", "_tokens", "_last_refill_ms")

    def __init__(self, cfg: RateLimitConfig, clock: DeterministicClock):
        """Initialize token bucket with configuration and clock."""
        self._cfg = cfg
        self._clock = clock
        self._tokens = float(cfg.capacity)  # Start with full capacity
        self._last_refill_ms = clock.now_ms()

    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now_ms = self._clock.now_ms()
        elapsed_ms = now_ms - self._last_refill_ms

        if elapsed_ms > 0:
            tokens_to_add = elapsed_ms * self._cfg.refill_per_ms
            self._tokens = min(self._cfg.capacity, self._tokens + tokens_to_add)
            self._last_refill_ms = now_ms
            logger.debug(f"Refilled {tokens_to_add:.3f} tokens, now have {self._tokens:.3f}")

    def try_consume(self, n: float = 1.0) -> bool:
        """Try to consume n tokens (supports fractional). Returns True if successful."""
        if not isinstance(n, (int, float)) or not math.isfinite(float(n)):
            raise ValueError("Token consumption must be a finite number")
        n = float(n)
        if n <= 0.0:
            raise ValueError("Token consumption must be positive")
        if n > float(self._cfg.capacity):
            raise ValueError(f"Cannot consume {n} tokens, capacity is {self._cfg.capacity}")

        self._refill()

        if self._tokens >= n:
            self._tokens -= n
            logger.debug(f"Consumed {n} tokens, {self._tokens:.3f} remaining")
            return True

        logger.debug(f"Cannot consume {n} tokens, only {self._tokens:.3f} available")
        return False

    def available(self) -> float:
        """Get number of available tokens (may be fractional)."""
        self._refill()
        return self._tokens

    def __repr__(self) -> str:
        return f"TokenBucket(capacity={self._cfg.capacity}, tokens={self._tokens:.3f})"


# =============================================================================
# Global Context
# =============================================================================

class GlobalContext:
    """Immutable global context with clock, cache, rate limiters, and metadata."""
    __slots__ = ("_cfg", "_clock", "_event_meta", "_cache", "_limiters")

    def __init__(
        self,
        cfg: GlobalConfig,
        clock: DeterministicClock,
        event_meta: EventMeta,
        cache: TTLCache[Any],
        limiters: Dict[str, TokenBucket],
    ):
        """Initialize global context with all components."""
        self._cfg = cfg
        self._clock = clock
        self._event_meta = event_meta
        self._cache = cache
        self._limiters = limiters.copy()  # Defensive copy

    @property
    def cfg(self) -> GlobalConfig:
        """Get global configuration."""
        return self._cfg

    @property
    def clock(self) -> DeterministicClock:
        """Get deterministic clock."""
        return self._clock

    @property
    def event_meta(self) -> EventMeta:
        """Get event metadata."""
        return self._event_meta

    @property
    def cache(self) -> TTLCache[Any]:
        """Get TTL cache."""
        return self._cache

    @property
    def limiters(self) -> Dict[str, TokenBucket]:
        """Get rate limiters by name."""
        return self._limiters.copy()  # Defensive copy

    def child(
        self,
        *,
        cfg: Optional[GlobalConfig] = None,
        clock: Optional[DeterministicClock] = None,
        event_meta: Optional[EventMeta] = None,
        limiters: Optional[Dict[str, TokenBucket]] = None,
    ) -> "GlobalContext":
        """Create child context with optional overrides."""
        return GlobalContext(
            cfg=cfg or self._cfg,
            clock=clock or self._clock,
            event_meta=event_meta or self._event_meta,
            cache=self._cache,  # Cache is shared intentionally
            limiters=limiters or self._limiters,
        )

    def with_now_ms(self, now_ms: int) -> "GlobalContext":
        """Create new context with updated clock time."""
        new_clock = self._clock.set_now_ms(now_ms)
        return self.child(clock=new_clock)

    def check_latency(self, start_ms: int) -> Tuple[int, bool]:
        """Check latency against budget. Returns (latency_ms, over_budget)."""
        now_ms = self._clock.now_ms()
        latency_ms = now_ms - start_ms
        over_budget = latency_ms > self._cfg.risk.latency_budget_ms

        if over_budget:
            logger.debug(
                f"Latency {latency_ms}ms exceeds budget {self._cfg.risk.latency_budget_ms}ms"
            )

        return latency_ms, over_budget

    def to_event_kwargs(self) -> Dict[str, Any]:
        """Return event kwargs from event metadata."""
        return self._event_meta.to_event_kwargs()

    def __repr__(self) -> str:
        return (
            "GlobalContext("
            f"app={self._cfg.app.name}:{self._cfg.app.version}, "
            f"env={self._cfg.app.env}, "
            f"source={self._event_meta.source}, "
            f"cache_size={self._cache.size_approx()}, "
            f"limiters={sorted(self._limiters.keys())}"
            ")"
        )


# =============================================================================
# Context Variables (Optional)
# =============================================================================

_current_context: contextvars.ContextVar[Optional[GlobalContext]] = contextvars.ContextVar(
    "global_context", default=None
)


def set_current(ctx: GlobalContext) -> contextvars.Token:
    """Set current context. Returns token for reset_current()."""
    return _current_context.set(ctx)


def get_current() -> Optional[GlobalContext]:
    """Get current context or None if not set."""
    return _current_context.get()


def reset_current(token: contextvars.Token) -> None:
    """Reset context using token from set_current()."""
    _current_context.reset(token)


# =============================================================================
# Self-Check
# =============================================================================

if __name__ == "__main__":
    # Configure logging for self-check (no side effects at import)
    logging.basicConfig(level=logging.INFO, format="%(name)s - %(levelname)s - %(message)s")

    try:
        # Create test configuration
        app = AppInfo(name="crypto_ai_bot", version="1.0.0", env="staging")
        cfg = GlobalConfig(
            app=app,
            clock=ClockConfig(enforce_monotonic=True),
            cache=CacheConfig(max_items=100, default_ttl_ms=5000),
            rate_limits={"signals": RateLimitConfig(capacity=5, refill_per_ms=0.001)},
            risk=RiskBudgets(latency_budget_ms=100, daily_stop_usd=1000.0),
        )

        # Create components
        clock = DeterministicClock(now_ms=1700000000000, cfg=cfg.clock)
        cache = TTLCache(cfg.cache, clock)
        limiters = {"signals": TokenBucket(cfg.rate_limits["signals"], clock)}

        # Create context
        ctx = GlobalContext(
            cfg=cfg,
            clock=clock,
            event_meta=EventMeta(
                source="ai_engine",
                correlation_id=make_correlation_id("test", "seed"),
                partition_key="BTCUSDT",
            ),
            cache=cache,
            limiters=limiters,
        )

        # Test operations
        # Cache operations
        cache.set("test_key", "test_value", ttl_ms=1000)
        found, value = cache.get("test_key")
        assert found and value == "test_value"

        # Rate limiter operations
        success = limiters["signals"].try_consume(1)
        assert success

        # Context operations
        ctx2 = ctx.with_now_ms(1700000000100)
        latency_ms, over_budget = ctx2.check_latency(1700000000000)
        assert latency_ms == 100 and over_budget

        # Child context
        _child_ctx = ctx.child(
            event_meta=EventMeta(
                source="child",
                correlation_id=make_correlation_id("child"),
                partition_key="ETHUSDT",
            )
        )

        logger.info("Global context self-check completed successfully")

    except Exception as e:
        logger.error(f"Global context self-check failed: {e}")
        raise
