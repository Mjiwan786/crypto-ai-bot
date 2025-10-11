"""
=============================================================================
CRYPTO-AI-BOT: Kraken Rate Limits Manager (Production-Ready)
=============================================================================
- Async-safe token bucket (local) with optional distributed Redis bucket
- Safe Kraken defaults, env overrides, priority-aware admission
- Adaptive backoff with jitter + circuit breakers
- Explicit lifecycle (start/stop) for background monitoring
- redis.asyncio (no deprecated aioredis)
=============================================================================
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional, Callable

# Use redis>=4.2 (async API)
try:
    import redis.asyncio as redis_async
except Exception:  # pragma: no cover
    redis_async = None  # graceful degradation when Redis not available in tests

# =============================================================================
# CONFIGURATION & ENUMS
# =============================================================================

log = logging.getLogger(__name__)

class EndpointType(Enum):
    PUBLIC_REST = "public_rest"
    PRIVATE_REST = "private_rest"
    TRADING_REST = "trading_rest"
    WEBSOCKET_PUBLIC = "websocket_public"
    WEBSOCKET_PRIVATE = "websocket_private"
    HISTORICAL_DATA = "historical_data"
    ORDER_MANAGEMENT = "order_management"

class BackoffStrategy(Enum):
    LINEAR = "linear"
    EXPONENTIAL = "exponential"
    FIBONACCI = "fibonacci"
    JITTERED_EXPONENTIAL = "jittered_exponential"
    ADAPTIVE_ML = "adaptive_ml"

class AgentPriority(Enum):
    CRITICAL = 1
    HIGH = 2
    MEDIUM = 3
    LOW = 4

@dataclass(frozen=True)
class RateLimitConfig:
    requests_per_minute: int
    requests_per_second: float
    burst_capacity: int
    recovery_time: float  # seconds for dynamic recovery
    priority_weights: Dict[AgentPriority, float] = field(
        default_factory=lambda: {
            AgentPriority.CRITICAL: 0.45,
            AgentPriority.HIGH: 0.35,
            AgentPriority.MEDIUM: 0.15,
            AgentPriority.LOW: 0.05,
        }
    )

# =============================================================================
# KRAKEN SAFE DEFAULTS (Overridable via ENV)
# =============================================================================

DEFAULT_LIMITS: Dict[EndpointType, RateLimitConfig] = {
    # Kraken docs commonly suggest ~60 RPM per key for many endpoints; keep conservative.
    EndpointType.PUBLIC_REST: RateLimitConfig(
        requests_per_minute=60, requests_per_second=1.0, burst_capacity=5, recovery_time=20.0
    ),
    EndpointType.PRIVATE_REST: RateLimitConfig(
        requests_per_minute=60, requests_per_second=1.0, burst_capacity=4, recovery_time=30.0
    ),
    EndpointType.TRADING_REST: RateLimitConfig(
        requests_per_minute=60, requests_per_second=1.0, burst_capacity=3, recovery_time=45.0,
        priority_weights={
            AgentPriority.CRITICAL: 0.55,
            AgentPriority.HIGH: 0.35,
            AgentPriority.MEDIUM: 0.10,
            AgentPriority.LOW: 0.0,
        },
    ),
    # WS “rate limits” are mostly subscription/message throttles; keep generous but safe.
    EndpointType.WEBSOCKET_PUBLIC: RateLimitConfig(
        requests_per_minute=50, requests_per_second=1.0, burst_capacity=3, recovery_time=15.0
    ),
    EndpointType.WEBSOCKET_PRIVATE: RateLimitConfig(
        requests_per_minute=45, requests_per_second=0.8, burst_capacity=3, recovery_time=20.0
    ),
    # Bulk pulls should be slow and steady.
    EndpointType.HISTORICAL_DATA: RateLimitConfig(
        requests_per_minute=30, requests_per_second=0.5, burst_capacity=2, recovery_time=90.0
    ),
    # Internal order Mgmt (cancel/replace/status). Keep under 1–2 rps.
    EndpointType.ORDER_MANAGEMENT: RateLimitConfig(
        requests_per_minute=90, requests_per_second=1.5, burst_capacity=5, recovery_time=20.0
    ),
}

def _env_override(base: Dict[EndpointType, RateLimitConfig]) -> Dict[EndpointType, RateLimitConfig]:
    """Allow overrides via env: KRAKEN_RATE_LIMIT_<NAME>_{RPM|RPS|BURST}"""
    out: Dict[EndpointType, RateLimitConfig] = {}
    for et, cfg in base.items():
        prefix = f"KRAKEN_RATE_LIMIT_{et.value.upper()}"
        rpm = os.getenv(f"{prefix}_RPM")
        rps = os.getenv(f"{prefix}_RPS")
        burst = os.getenv(f"{prefix}_BURST")
        if any((rpm, rps, burst)):
            out[et] = RateLimitConfig(
                requests_per_minute=int(rpm) if rpm else cfg.requests_per_minute,
                requests_per_second=float(rps) if rps else cfg.requests_per_second,
                burst_capacity=int(burst) if burst else cfg.burst_capacity,
                recovery_time=cfg.recovery_time,
                priority_weights=cfg.priority_weights,
            )
        else:
            out[et] = cfg
    return out

KRAKEN_RATE_LIMITS: Dict[EndpointType, RateLimitConfig] = _env_override(DEFAULT_LIMITS)

# =============================================================================
# TOKEN BUCKET (LOCAL, ASYNC-SAFE)
# =============================================================================

class TokenBucket:
    """Async-safe token bucket with soft priority weighting & adaptive recovery."""
    __slots__ = (
        "config", "endpoint_type", "_lock", "_capacity", "_tokens", "_fill_rate",
        "_last", "_priority_tokens", "_violation_count", "_last_violation",
        "_adjust", "_stats"
    )

    def __init__(self, config: RateLimitConfig, endpoint_type: EndpointType):
        self.config = config
        self.endpoint_type = endpoint_type
        self._lock = asyncio.Lock()
        self._capacity = float(config.burst_capacity)
        self._tokens = float(config.burst_capacity)
        self._fill_rate = float(config.requests_per_second)
        self._last = time.monotonic()

        # priority token sub-buckets
        self._priority_tokens: Dict[AgentPriority, float] = {p: 0.0 for p in AgentPriority}

        # adaptive control
        self._violation_count = 0
        self._last_violation: Optional[float] = None
        self._adjust = 1.0  # dynamic multiplicative factor on fill rate

        # stats
        self._stats: Dict[str, Any] = dict(
            total_requests=0,
            denied_requests=0,
            average_wait_time=0.0,
            violations=0,
            efficiency_score=1.0,
        )

    def _refill_unlocked(self) -> None:
        now = time.monotonic()
        dt = max(0.0, now - self._last)
        self._last = now

        to_add = dt * self._fill_rate * self._adjust
        if to_add <= 0.0:
            return

        # main bucket
        self._tokens = min(self._capacity, self._tokens + to_add)

        # distribute to priority sub-buckets
        total_weight = sum(self.config.priority_weights.values()) or 1.0
        for prio, w in self.config.priority_weights.items():
            self._priority_tokens[prio] = min(
                self._capacity, self._priority_tokens[prio] + (to_add * (w / total_weight))
            )

    async def acquire(
        self,
        tokens: int = 1,
        priority: AgentPriority = AgentPriority.MEDIUM,
        timeout: Optional[float] = None,
        agent_id: Optional[str] = None,
    ) -> bool:
        start = time.monotonic()
        deadline = None if timeout is None else start + timeout

        while True:
            async with self._lock:
                self._refill_unlocked()

                available = self._tokens + self._priority_tokens.get(priority, 0.0)
                if available >= tokens:
                    # Drain priority first
                    prio_take = min(tokens, self._priority_tokens.get(priority, 0.0))
                    self._priority_tokens[priority] = max(0.0, self._priority_tokens[priority] - prio_take)
                    main_need = tokens - prio_take
                    self._tokens = max(0.0, self._tokens - main_need)

                    # stats
                    self._stats["total_requests"] += 1
                    wait = time.monotonic() - start
                    self._stats["average_wait_time"] = 0.1 * wait + 0.9 * self._stats["average_wait_time"]
                    self._stats["efficiency_score"] = 1.0 - (
                        self._stats["denied_requests"] / max(1, self._stats["total_requests"])
                    )
                    return True

            if deadline is not None and time.monotonic() >= deadline:
                async with self._lock:
                    self._stats["total_requests"] += 1
                    self._stats["denied_requests"] += 1
                    self._stats["efficiency_score"] = 1.0 - (
                        self._stats["denied_requests"] / max(1, self._stats["total_requests"])
                    )
                return False

            await asyncio.sleep(0.01)

    def report_violation(self) -> None:
        # Reduce adjust factor to slow refills; recover slowly later.
        self._violation_count += 1
        self._last_violation = time.monotonic()
        self._stats["violations"] += 1
        self._adjust = max(0.1, self._adjust * 0.8)

    def recover(self) -> None:
        if self._last_violation is None:
            # gentle drift toward 1.0
            self._adjust = min(1.0, self._adjust * 1.01)
            return
        if (time.monotonic() - self._last_violation) > self.config.recovery_time:
            self._adjust = min(1.0, self._adjust * 1.05)

    def status(self) -> Dict[str, Any]:
        # Non-locking snapshot for speed; slight race is fine for metrics.
        self._refill_unlocked()
        return dict(
            endpoint_type=self.endpoint_type.value,
            available_tokens=float(self._tokens),
            capacity=float(self._capacity),
            fill_rate=float(self._fill_rate),
            dynamic_adjustment=float(self._adjust),
            violation_count=int(self._violation_count),
            stats=self._stats.copy(),
            priority_tokens={k.name: float(v) for k, v in self._priority_tokens.items()},
        )

# =============================================================================
# OPTIONAL DISTRIBUTED TOKEN BUCKET (Redis Lua)
# =============================================================================

_LUA_BUCKET = """
-- KEYS[1]: tokens key
-- KEYS[2]: ts key
-- ARGV[1]: capacity
-- ARGV[2]: fill_rate (tokens per second)
-- ARGV[3]: now (ms)
-- ARGV[4]: tokens requested
local cap = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local need = tonumber(ARGV[4])

local tokens = tonumber(redis.call('GET', KEYS[1])) or cap
local ts = tonumber(redis.call('GET', KEYS[2])) or now

if now > ts then
  local delta = (now - ts) / 1000.0
  tokens = math.min(cap, tokens + delta * rate)
  ts = now
end

local allowed = 0
if tokens >= need then
  tokens = tokens - need
  allowed = 1
end

redis.call('SET', KEYS[1], tokens)
redis.call('SET', KEYS[2], ts)
redis.call('PEXPIRE', KEYS[1], 60000)
redis.call('PEXPIRE', KEYS[2], 60000)
return {allowed, tokens}
"""

class DistributedBucket:
    """Distributed token bucket using Redis Lua (atomic)."""
    def __init__(self, redis: redis_async.Redis, name: str, cfg: RateLimitConfig):
        self._r = redis
        self._name = name
        self._cfg = cfg
        self._script = self._r.register_script(_LUA_BUCKET)

    async def acquire(self, tokens: int = 1, timeout: Optional[float] = None) -> bool:
        start = time.monotonic()
        deadline = None if timeout is None else start + timeout

        while True:
            now_ms = int(time.time() * 1000)
            try:
                allowed, _ = await self._script(
                    keys=[f"rl:{self._name}:tokens", f"rl:{self._name}:ts"],
                    args=[self._cfg.burst_capacity, self._cfg.requests_per_second, now_ms, tokens],
                )
                if int(allowed) == 1:
                    return True
            except Exception as e:  # fallback to deny on Redis failure
                log.warning("Distributed bucket error for %s: %s", self._name, e)
                return False

            if deadline is not None and time.monotonic() >= deadline:
                return False
            await asyncio.sleep(0.01)

# =============================================================================
# BACKOFF MANAGER
# =============================================================================

class BackoffManager:
    def __init__(self):
        self._failures: Dict[EndpointType, int] = {}

    def record_failure(self, et: EndpointType) -> None:
        self._failures[et] = self._failures.get(et, 0) + 1

    def record_success(self, et: EndpointType) -> None:
        cur = self._failures.get(et, 0)
        if cur > 0:
            self._failures[et] = cur - 1

    async def wait(self, et: EndpointType, strategy: BackoffStrategy = BackoffStrategy.JITTERED_EXPONENTIAL) -> None:
        n = self._failures.get(et, 0)
        if strategy is BackoffStrategy.LINEAR:
            base = min(60.0, 1.0 + 2.0 * n)
        elif strategy is BackoffStrategy.EXPONENTIAL:
            base = min(60.0, 2.0 ** min(n, 6))
        elif strategy is BackoffStrategy.FIBONACCI:
            base = min(60.0, _fib(min(n + 1, 15)))
        elif strategy is BackoffStrategy.ADAPTIVE_ML:
            base = _adaptive_ml_seconds(n)
        else:  # JITTERED_EXPONENTIAL
            base = min(60.0, 2.0 ** min(n, 6))
        # jitter
        wait_s = max(0.1, base * random.uniform(0.8, 1.2))
        log.info("Rate backoff on %s: %.2fs (failures=%d)", et.value, wait_s, n)
        await asyncio.sleep(wait_s)

def _fib(n: int) -> float:
    if n <= 2:
        return 1.0
    a, b = 1.0, 1.0
    for _ in range(3, n + 1):
        a, b = b, a + b
    return b

def _adaptive_ml_seconds(failures: int) -> float:
    base = 2.0 ** min(failures, 4)
    hour = datetime.now().hour
    if 14 <= hour <= 20:   # peak hours
        base *= 1.4
    elif 2 <= hour <= 6:   # off hours
        base *= 0.8
    return min(60.0, base)

# =============================================================================
# RATE LIMIT MANAGER
# =============================================================================

class KrakenRateLimitManager:
    """
    Central manager. Supports local token buckets and (optional) distributed buckets per endpoint.
    Call start()/stop() to run background maintenance.
    """

    def __init__(self, redis_url: Optional[str] = None, use_distributed: Optional[bool] = None):
        self._limits = KRAKEN_RATE_LIMITS
        self._buckets_local: Dict[EndpointType, TokenBucket] = {
            et: TokenBucket(cfg, et) for et, cfg in self._limits.items()
        }
        self._buckets_dist: Dict[EndpointType, DistributedBucket] = {}
        self._redis_url = redis_url or os.getenv("REDIS_URL", "")
        self._use_distributed = (
            use_distributed
            if use_distributed is not None
            else os.getenv("DISTRIBUTED_RATE_LIMITS", "false").lower() == "true"
        )

        self._redis: Optional[redis_async.Redis] = None
        self._monitor_task: Optional[asyncio.Task] = None
        self._backoff = BackoffManager()

        # circuit breakers
        self._cb_threshold = int(os.getenv("RATE_LIMIT_CB_VIOLATIONS", "10"))
        self._cb_duration = float(os.getenv("RATE_LIMIT_CB_SECONDS", "300"))
        self._cb_until: Dict[EndpointType, float] = {}

        self._global = dict(
            total_requests=0,
            total_violations=0,
            circuit_breaks=0,
            uptime_start=time.monotonic(),
        )

    async def start(self) -> None:
        """Connect Redis (if enabled) and start background monitor."""
        if self._use_distributed and redis_async is None:
            log.warning("redis.asyncio not available; falling back to local buckets.")
            self._use_distributed = False

        if self._use_distributed and self._redis is None:
            try:
                self._redis = await redis_async.from_url(self._redis_url)  # type: ignore[attr-defined]
                # create distributed buckets
                for et, cfg in self._limits.items():
                    self._buckets_dist[et] = DistributedBucket(self._redis, f"kraken:{et.value}", cfg)
                log.info("Distributed rate limiting enabled via Redis.")
            except Exception as e:  # pragma: no cover
                log.warning("Failed to init Redis for rate limits: %s; using local buckets.", e)
                self._use_distributed = False

        if self._monitor_task is None:
            self._monitor_task = asyncio.create_task(self._monitor_loop(), name="kraken-rl-monitor")

    async def stop(self) -> None:
        """Stop background monitor and close Redis."""
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None

        if self._redis:
            try:
                await self._redis.aclose()  # type: ignore[attr-defined]
            except Exception:
                pass
            self._redis = None

    async def _monitor_loop(self) -> None:
        while True:
            try:
                # adaptive recovery
                for b in self._buckets_local.values():
                    b.recover()
                # circuit breaker housekeeping
                self._check_circuits()
                # metrics
                await self._publish_metrics()
                await asyncio.sleep(30.0)
            except asyncio.CancelledError:
                break
            except Exception as e:  # pragma: no cover
                log.error("rate-limit monitor error: %s", e)
                await asyncio.sleep(60.0)

    def _check_circuits(self) -> None:
        now = time.monotonic()
        for et, b in self._buckets_local.items():
            if et in self._cb_until and now >= self._cb_until[et]:
                del self._cb_until[et]
                # reset bucket violation count
                # (we don't expose a setter; just zero via status snapshot)
                b._violation_count = 0  # noqa: SLF001 (contained type)
                log.info("Circuit restored for %s", et.value)
            elif et not in self._cb_until and b._violation_count >= self._cb_threshold:
                self._cb_until[et] = now + self._cb_duration
                self._global["circuit_breaks"] += 1
                log.warning("Circuit opened for %s", et.value)

    async def _publish_metrics(self) -> None:
        if not self._redis:
            return
        try:
            buckets = {et.value: self._buckets_local[et].status() for et in self._limits.keys()}
            await self._redis.hset(
                "kraken:rate_limits",
                mapping={
                    "global": str(self._global),
                    "buckets": str(buckets),
                    "circuits": str({k.value: v for k, v in self._cb_until.items()}),
                    "ts": str(int(time.time())),
                },
            )
            await self._redis.expire("kraken:rate_limits", 3600)
        except Exception as e:  # pragma: no cover
            log.debug("metrics publish skipped: %s", e)

    def is_circuit_open(self, et: EndpointType) -> bool:
        return et in self._cb_until

    async def acquire(
        self,
        et: EndpointType,
        *,
        priority: AgentPriority = AgentPriority.MEDIUM,
        agent_id: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> bool:
        if self.is_circuit_open(et):
            log.warning("Circuit open for %s; deny.", et.value)
            return False

        success: bool
        if self._use_distributed and et in self._buckets_dist:
            success = await self._buckets_dist[et].acquire(1, timeout=timeout)
        else:
            success = await self._buckets_local[et].acquire(1, priority=priority, timeout=timeout, agent_id=agent_id)

        if success:
            self._global["total_requests"] += 1
            self._backoff.record_success(et)
        else:
            self._backoff.record_failure(et)
            await self._backoff.wait(et, BackoffStrategy.JITTERED_EXPONENTIAL)

        return success

    def report_api_error(self, et: EndpointType, status_code: int) -> None:
        if status_code == 429:
            self._global["total_violations"] += 1
            # always touch local bucket; distributed bucket refills are rate-based anyway
            self._buckets_local[et].report_violation()
            log.warning("Rate-limit violation on %s (429).", et.value)

    def status(self) -> Dict[str, Any]:
        return {
            "global": dict(self._global, uptime_seconds=time.monotonic() - self._global["uptime_start"]),
            "buckets": {et.value: self._buckets_local[et].status() for et in self._limits},
            "circuits": {et.value: until for et, until in self._cb_until.items()},
        }

# =============================================================================
# SINGLETON + HELPERS
# =============================================================================

_manager: Optional[KrakenRateLimitManager] = None
_manager_lock = asyncio.Lock()

async def get_rate_limit_manager() -> KrakenRateLimitManager:
    global _manager
    async with _manager_lock:
        if _manager is None:
            _manager = KrakenRateLimitManager()
            await _manager.start()
        return _manager

@asynccontextmanager
async def rate_guard(
    endpoint_type: EndpointType,
    *,
    priority: AgentPriority = AgentPriority.MEDIUM,
    agent_id: Optional[str] = None,
    timeout: Optional[float] = None,
    max_retries: int = 3,
):
    """
    Usage:
        async with rate_guard(EndpointType.TRADING_REST, priority=AgentPriority.HIGH):
            await client.add_order(...)
    """
    mgr = await get_rate_limit_manager()
    attempt = 0
    while True:
        acquired = await mgr.acquire(endpoint_type, priority=priority, agent_id=agent_id, timeout=timeout)
        if acquired:
            try:
                yield mgr
                return
            finally:
                # noop — token was consumed on acquire; nothing to release
                ...
        attempt += 1
        if attempt > max_retries:
            raise TimeoutError(f"rate_guard: could not acquire token for {endpoint_type.value} after {max_retries} retries.")
        await asyncio.sleep(0.2 * attempt)

def rate_limited(endpoint_type: EndpointType, *, priority: AgentPriority = AgentPriority.MEDIUM, max_retries: int = 3):
    """
    Decorator for async functions:
        @rate_limited(EndpointType.TRADING_REST, priority=AgentPriority.HIGH)
        async def place(...):
            ...
    """
    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        if not asyncio.iscoroutinefunction(fn):
            raise TypeError("rate_limited decorator requires an async function.")

        async def wrapper(*args, **kwargs):
            agent_id = kwargs.pop("agent_id", None) or f"{fn.__module__}.{fn.__name__}"
            async with rate_guard(endpoint_type, priority=priority, agent_id=agent_id, max_retries=max_retries):
                return await fn(*args, **kwargs)
        return wrapper
    return deco

# Convenience factories that return an async context manager (no await needed)
def rest_guard(kind: str = "public", **kwargs):
    mapping = {
        "public": EndpointType.PUBLIC_REST,
        "private": EndpointType.PRIVATE_REST,
        "trading": EndpointType.TRADING_REST,
        "historical": EndpointType.HISTORICAL_DATA,
        "orders": EndpointType.ORDER_MANAGEMENT,
    }
    return rate_guard(mapping.get(kind, EndpointType.PUBLIC_REST), **kwargs)

def ws_guard(*, private: bool = False, **kwargs):
    et = EndpointType.WEBSOCKET_PRIVATE if private else EndpointType.WEBSOCKET_PUBLIC
    return rate_guard(et, **kwargs)

# =============================================================================
# HEALTH CHECK
# =============================================================================

class RateLimitHealth:
    @staticmethod
    async def check() -> Dict[str, Any]:
        mgr = await get_rate_limit_manager()
        st = mgr.status()
        score = 1.0
        issues = []

        viol = st["global"]["total_violations"]
        req = st["global"]["total_requests"]
        if viol > 0 and (viol / max(1, req)) > 0.01:
            score -= 0.3
            issues.append(f"High violation rate: {viol}/{req}")

        if st["circuits"]:
            score -= 0.4
            issues.append(f"Circuits open: {list(st['circuits'].keys())}")

        for name, b in st["buckets"].items():
            eff = b["stats"]["efficiency_score"]
            if eff < 0.9:
                score -= 0.1
                issues.append(f"Low efficiency {name}: {eff:.2f}")

        return {
            "healthy": score >= 0.7,
            "health_score": round(score, 3),
            "issues": issues,
            "status": st,
            "timestamp": int(time.time()),
        }

# =============================================================================
# EXAMPLE (commented)
# =============================================================================

# async def example():
#     async with rest_guard("trading", priority=AgentPriority.HIGH, agent_id="scalper_1"):
#         await kraken_client.add_order(...)
#
# @rate_limited(EndpointType.PUBLIC_REST)
# async def fetch_markets():
#     return await kraken_client.get_markets()
