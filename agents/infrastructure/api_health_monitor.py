"""
agents/infrastructure/api_health_monitor.py

Production-ready API health monitor for external dependencies.
Lightweight, async, deterministic with circuit breakers and SLA tracking.

Key features:
- Circuit breaker state management
- Rolling SLA calculation (1m, 5m windows)
- Structured health events via callback
- Deterministic behavior (no random in logic; deterministic backoff)
- Optional aiohttp support (graceful degradation; module runs without it)
- Redis (TCP PING), HTTP, WebSocket, MCP/LLM endpoint monitoring

Core rules:
- PURE logic in models/serialization; no I/O in validation/serialization paths.
- All time comes from an injected now_ms() callable.
- Async safe: no blocking calls on the event loop.
- Deterministic outputs for identical inputs; sorted JSON serialization.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from typing import Any, Awaitable, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

try:
    import aiohttp

    AIOHTTP_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    aiohttp = None  # type: ignore[assignment]
    AIOHTTP_AVAILABLE = False

__version__ = "1.0.1"

# ============================================================================
# Core Types and Contracts
# ============================================================================

ServiceKind = Literal["http", "ws", "redis", "custom", "mcp", "llm"]
CircuitState = Literal["closed", "open", "half_open"]
HealthStatus = Literal["up", "degraded", "down", "unknown"]


class CheckSpec(BaseModel):
    """Health check specification (frozen; extra fields forbidden)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(description="Unique check name")
    kind: ServiceKind = Field(description="Service type")
    target: str = Field(description="URL, host:port, or identifier")
    interval_ms: int = Field(gt=0, description="Check interval in milliseconds")
    timeout_ms: int = Field(gt=0, description="Per-attempt timeout in milliseconds")
    retries: int = Field(ge=0, description="Retry attempts per cycle")
    open_after_failures: int = Field(gt=0, description="Circuit breaker failure threshold")
    half_open_after_ms: int = Field(gt=0, description="Circuit breaker cooldown period")
    degraded_threshold_ms: int = Field(gt=0, description="Latency threshold for degraded status")
    tags: dict[str, str] = Field(default_factory=dict, description="Additional metadata")

    @field_serializer("tags")
    def serialize_tags(self, v: dict[str, str]) -> dict[str, str]:
        """Serialize tags with sorted keys for determinism.

        Args:
            v: Tags dictionary to serialize

        Returns:
            Dictionary with sorted keys for deterministic serialization
        """
        return {k: v[k] for k in sorted(v.keys())}


class CheckResult(BaseModel):
    """Single health check result (frozen)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    kind: ServiceKind
    target: str
    ts_ms: int = Field(description="Timestamp in milliseconds")
    latency_ms: int | None = Field(default=None, description="Response latency")
    status: HealthStatus
    http_code: int | None = Field(default=None, description="HTTP status code if applicable")
    error: str | None = Field(default=None, description="Error description if failed")


class CircuitSnapshot(BaseModel):
    """Circuit breaker state snapshot (frozen)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    state: CircuitState
    fail_count: int
    opened_at_ms: int | None = Field(default=None, description="When circuit opened (ms)")


class HealthEvent(BaseModel):
    """Structured health event for emission (frozen)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(default="1.0")
    check: CheckResult
    circuit: CircuitSnapshot
    sla_1m: float = Field(ge=0.0, le=1.0, description="1-minute availability SLA")
    sla_5m: float = Field(ge=0.0, le=1.0, description="5-minute availability SLA")
    message: str = Field(description="Human-readable summary")


class MonitorConfig(BaseModel):
    """Monitor configuration (frozen)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(default="1.0")
    max_concurrency: int = Field(default=8, gt=0)
    deterministic_stagger_ms: int = Field(default=150, gt=0)
    emit_on_unchanged: bool = Field(
        default=False, description="Emit events even when status unchanged"
    )


# ============================================================================
# Utility Functions
# ============================================================================


def stable_hash(name: str) -> int:
    """Generate deterministic 64-bit hash from string.

    Args:
        name: String to hash

    Returns:
        Deterministic 64-bit hash value
    """
    return int(hashlib.md5(name.encode("utf-8"), usedforsecurity=False).hexdigest()[:16], 16)


def to_json(model: BaseModel) -> str:
    """Serialize Pydantic model deterministically with sorted keys (no None).

    Args:
        model: Pydantic model to serialize

    Returns:
        JSON string with sorted keys and no null values
    """
    import json as _json

    data = model.model_dump(exclude_none=True, by_alias=True)
    return _json.dumps(data, sort_keys=True, separators=(",", ":"))


# ============================================================================
# Core Engine Components
# ============================================================================


class CircuitBreaker:
    """Circuit breaker for individual health checks.

    Implements circuit breaker pattern with closed, open, and half-open states
    to prevent cascading failures and allow recovery.
    """

    def __init__(self, spec: CheckSpec) -> None:
        """Initialize circuit breaker.

        Args:
            spec: Health check specification with thresholds
        """
        self.spec = spec
        self.state: CircuitState = "closed"
        self.fail_count: int = 0
        self.opened_at_ms: int | None = None
        self.logger = logging.getLogger(f"{__name__}.CircuitBreaker.{spec.name}")

    def on_success(self, now_ms: int) -> None:
        """Handle successful check.

        Args:
            now_ms: Current timestamp in milliseconds

        Note:
            In half-open state, success closes the circuit.
            In closed state, resets failure count.
        """
        if self.state == "half_open":
            self.state = "closed"
            self.fail_count = 0
            self.opened_at_ms = None
            self.logger.info(f"Circuit breaker closed for {self.spec.name}")
        elif self.state == "closed":
            self.fail_count = 0

    def on_failure(self, now_ms: int) -> None:
        """Handle failed check.

        Args:
            now_ms: Current timestamp in milliseconds

        Semantics:
            - If already OPEN, ignore additional failures; wait for half-open window.
            - If HALF_OPEN, a failure re-opens and resets opened_at_ms.
            - If CLOSED, increment and transition to OPEN on threshold.
        """
        if self.state == "open":
            return  # do not inflate counters while open

        self.fail_count += 1

        if self.state == "closed" and self.fail_count >= self.spec.open_after_failures:
            self.state = "open"
            self.opened_at_ms = now_ms
            self.logger.error(
                f"Circuit breaker opened for {self.spec.name} after {self.fail_count} failures"
            )
        elif self.state == "half_open":
            # Failed probe, back to open
            self.state = "open"
            self.opened_at_ms = now_ms
            self.logger.warning(f"Circuit breaker reopened for {self.spec.name} after failed probe")

    def should_allow(self, now_ms: int) -> bool:
        """Check if request should be allowed.

        Args:
            now_ms: Current timestamp in milliseconds

        Returns:
            True if request should be allowed, False if circuit is open
        """
        if self.state == "closed":
            return True
        elif self.state == "open":
            if self.opened_at_ms is not None and (now_ms - self.opened_at_ms) >= self.spec.half_open_after_ms:
                self.state = "half_open"
                self.logger.info(f"Circuit breaker half-open for {self.spec.name}")
                return True
            return False
        else:  # half_open
            return True

    def snapshot(self) -> CircuitSnapshot:
        """Get current state snapshot.

        Returns:
            Immutable snapshot of current circuit breaker state
        """
        return CircuitSnapshot(
            name=self.spec.name,
            state=self.state,
            fail_count=self.fail_count,
            opened_at_ms=self.opened_at_ms,
        )


class SLATracker:
    """Rolling SLA calculation using fixed-size ring buffers (1s buckets)."""

    __slots__ = (
        "spec",
        "window_1m",
        "window_5m",
        "total_1m",
        "total_5m",
        "last_update_sec",
    )

    def __init__(self, spec: CheckSpec) -> None:
        """Initialize SLA tracker.

        Args:
            spec: Health check specification
        """
        self.spec = spec
        # success count per-second
        self.window_1m: list[int] = [0] * 60
        self.window_5m: list[int] = [0] * 300
        # total attempts per-second
        self.total_1m: list[int] = [0] * 60
        self.total_5m: list[int] = [0] * 300
        self.last_update_sec: int | None = None

    def _advance(self, now_sec: int) -> None:
        """Advance ring buffers, clearing buckets for elapsed seconds deterministically.

        Args:
            now_sec: Current timestamp in seconds
        """
        if self.last_update_sec is None:
            self.last_update_sec = now_sec
            return

        elapsed = now_sec - self.last_update_sec
        if elapsed <= 0:
            return

        # Cap clearing to the window sizes to avoid large loops after long pauses
        steps_1m = min(elapsed, 60)
        steps_5m = min(elapsed, 300)

        for s in range(1, steps_1m + 1):
            idx = (self.last_update_sec + s) % 60
            self.window_1m[idx] = 0
            self.total_1m[idx] = 0

        for s in range(1, steps_5m + 1):
            idx = (self.last_update_sec + s) % 300
            self.window_5m[idx] = 0
            self.total_5m[idx] = 0

        self.last_update_sec = now_sec

    def record(self, is_up: bool, now_ms: int) -> None:
        """Record availability measurement.

        Args:
            is_up: Whether the service is up
            now_ms: Current timestamp in milliseconds
        """
        now_sec = now_ms // 1000
        self._advance(now_sec)

        idx_1m = now_sec % 60
        idx_5m = now_sec % 300

        self.total_1m[idx_1m] += 1
        self.total_5m[idx_5m] += 1

        if is_up:
            self.window_1m[idx_1m] += 1
            self.window_5m[idx_5m] += 1

    def sla_1m(self) -> float:
        """Calculate 1-minute SLA.

        Returns:
            SLA ratio (0.0-1.0) for last minute, or 1.0 if no data
        """
        success_count = sum(self.window_1m)
        total_count = sum(self.total_1m)
        return success_count / total_count if total_count > 0 else 1.0

    def sla_5m(self) -> float:
        """Calculate 5-minute SLA.

        Returns:
            SLA ratio (0.0-1.0) for last 5 minutes, or 1.0 if no data
        """
        success_count = sum(self.window_5m)
        total_count = sum(self.total_5m)
        return success_count / total_count if total_count > 0 else 1.0


class CheckRunner:
    """Executes health checks with retries and circuit breaker integration."""

    def __init__(
        self,
        now_ms: Callable[[], int],
        session: Any | None = None,
        custom_fn: Callable[..., Awaitable[tuple[HealthStatus, int | None, str | None]]] | None = None,
    ) -> None:
        """Initialize check runner.

        Args:
            now_ms: Callable that returns current time in milliseconds
            session: Optional aiohttp session for HTTP checks
            custom_fn: Optional custom check function for custom/mcp/llm checks
        """
        self.now_ms = now_ms
        self.session = session
        self.custom_fn = custom_fn
        self.logger = logging.getLogger(f"{__name__}.CheckRunner")

    async def run_once(
        self, spec: CheckSpec, circuit: CircuitBreaker, sla: SLATracker
    ) -> CheckResult:
        """Execute a single check cycle with retries.

        Args:
            spec: Health check specification
            circuit: Circuit breaker for this check
            sla: SLA tracker for this check

        Returns:
            Check result with status and timing information
        """
        start_ms = self.now_ms()

        # Check circuit breaker
        if not circuit.should_allow(start_ms):
            result = CheckResult(
                name=spec.name,
                kind=spec.kind,
                target=spec.target,
                ts_ms=start_ms,
                status="down",
                error="Circuit breaker open",
            )
            # Do NOT mutate breaker while already open; only record SLA
            sla.record(False, start_ms)
            return result

        # Perform check with retries
        last_error = None
        for attempt in range(spec.retries + 1):
            try:
                if attempt > 0:
                    # Deterministic backoff delay: 100, 200, 400, ... with deterministic jitter
                    base_delay = 100 * (2 ** (attempt - 1))
                    jitter_factor = (stable_hash(f"{spec.name}:{attempt}") % 17) / 100.0
                    delay_ms = int(base_delay * (1 + jitter_factor))
                    await asyncio.sleep(delay_ms / 1000.0)

                status, latency_ms, error = await self._execute_check(spec)

                # Determine final status based on latency threshold
                if (
                    status == "up"
                    and latency_ms is not None
                    and latency_ms > spec.degraded_threshold_ms
                ):
                    status = "degraded"

                # Extract http_code if present in error string (set by _check_http)
                http_code_val: int | None = None
                if error is not None and error.startswith("HTTP "):
                    parts = error.split()
                    if len(parts) >= 2 and parts[1].isdigit():
                        http_code_val = int(parts[1])

                # Build result
                result = CheckResult(
                    name=spec.name,
                    kind=spec.kind,
                    target=spec.target,
                    ts_ms=self.now_ms(),
                    latency_ms=latency_ms,
                    status=status,
                    http_code=http_code_val,
                    error=error,
                )

                # Update circuit breaker and SLA
                is_success = status in ("up", "degraded")
                if is_success:
                    circuit.on_success(self.now_ms())
                else:
                    circuit.on_failure(self.now_ms())

                sla.record(is_success, self.now_ms())
                return result

            except Exception as e:  # pragma: no cover - exercised via integration tests
                last_error = str(e)
                self.logger.debug(f"Check {spec.name} attempt {attempt + 1} failed: {e}")

        # All attempts failed
        result = CheckResult(
            name=spec.name,
            kind=spec.kind,
            target=spec.target,
            ts_ms=self.now_ms(),
            status="down",
            error=last_error or "All attempts failed",
        )

        circuit.on_failure(self.now_ms())
        sla.record(False, self.now_ms())
        return result

    async def _execute_check(
        self, spec: CheckSpec
    ) -> tuple[HealthStatus, int | None, str | None]:
        """Execute specific check type.

        Args:
            spec: Health check specification

        Returns:
            Tuple of (status, latency_ms, error_message)
        """
        start_time = self.now_ms()

        try:
            if spec.kind == "http":
                return await self._check_http(spec, start_time)
            elif spec.kind == "ws":
                return await self._check_websocket(spec, start_time)
            elif spec.kind == "redis":
                return await self._check_redis(spec, start_time)
            elif spec.kind in ("custom", "mcp", "llm"):
                return await self._check_custom(spec, start_time)
            else:
                return "unknown", None, f"Unsupported check kind: {spec.kind}"

        except asyncio.TimeoutError:
            latency = self.now_ms() - start_time
            return "down", latency, "Timeout"
        except Exception as e:
            latency = self.now_ms() - start_time
            return "down", latency, str(e)

    async def _check_http(
        self, spec: CheckSpec, start_time: int
    ) -> tuple[HealthStatus, int | None, str | None]:
        """HTTP endpoint check (status code propagated via error string).

        Args:
            spec: Health check specification
            start_time: Check start timestamp in milliseconds

        Returns:
            Tuple of (status, latency_ms, error_message)
        """
        if not AIOHTTP_AVAILABLE:
            return "unknown", None, "aiohttp not available"

        if self.session is None:
            return "unknown", None, "HTTP session not provided"

        try:
            timeout = aiohttp.ClientTimeout(total=spec.timeout_ms / 1000.0)
            async with self.session.get(spec.target, timeout=timeout) as response:
                latency = self.now_ms() - start_time
                code = response.status

                if 200 <= code < 300:
                    return "up", latency, f"HTTP {code}"
                elif 400 <= code < 500:
                    return "degraded", latency, f"HTTP {code}"
                else:
                    return "down", latency, f"HTTP {code}"

        except Exception as e:
            latency = self.now_ms() - start_time
            return "down", latency, str(e)

    async def _check_websocket(
        self, spec: CheckSpec, start_time: int
    ) -> tuple[HealthStatus, int | None, str | None]:
        """WebSocket endpoint reachability via TCP connect (no handshake).

        Args:
            spec: Health check specification
            start_time: Check start timestamp in milliseconds

        Returns:
            Tuple of (status, latency_ms, error_message)
        """
        try:
            # Parse target for host and port
            if "://" in spec.target:
                from urllib.parse import urlparse

                parsed = urlparse(spec.target)
                host = parsed.hostname or "localhost"
                port = parsed.port or (443 if parsed.scheme == "wss" else 80)
            else:
                if ":" in spec.target:
                    host, port_str = spec.target.rsplit(":", 1)
                    port = int(port_str)
                else:
                    host = spec.target
                    port = 80

            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=spec.timeout_ms / 1000.0,
            )

            writer.close()
            await writer.wait_closed()

            latency = self.now_ms() - start_time
            return "up", latency, None

        except Exception as e:
            latency = self.now_ms() - start_time
            return "down", latency, str(e)

    async def _check_redis(
        self, spec: CheckSpec, start_time: int
    ) -> tuple[HealthStatus, int | None, str | None]:
        """Redis reachability via RESP PING over TCP (no TLS/auth).

        Args:
            spec: Health check specification
            start_time: Check start timestamp in milliseconds

        Returns:
            Tuple of (status, latency_ms, error_message)
        """
        try:
            if "://" in spec.target:
                # Simplified parsing for redis://... ; use defaults for this TCP probe
                host = "localhost"
                port = 6379
            elif ":" in spec.target:
                host, port_str = spec.target.rsplit(":", 1)
                port = int(port_str)
            else:
                host = spec.target
                port = 6379

            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=spec.timeout_ms / 1000.0,
            )

            # RESP PING
            writer.write(b"*1\r\n$4\r\nPING\r\n")
            await writer.drain()

            response = await asyncio.wait_for(reader.read(1024), timeout=spec.timeout_ms / 1000.0)

            writer.close()
            await writer.wait_closed()

            latency = self.now_ms() - start_time

            if b"+PONG" in response:
                return "up", latency, None
            return "degraded", latency, "Unexpected PING response"

        except Exception as e:
            latency = self.now_ms() - start_time
            return "down", latency, str(e)

    async def _check_custom(
        self, spec: CheckSpec, start_time: int
    ) -> tuple[HealthStatus, int | None, str | None]:
        """Custom check using injected function (async).

        Args:
            spec: Health check specification
            start_time: Check start timestamp in milliseconds

        Returns:
            Tuple of (status, latency_ms, error_message)
        """
        if self.custom_fn is None:
            return "unknown", None, "No custom function provided"

        try:
            status, latency_ms, error = await asyncio.wait_for(
                self.custom_fn(spec, spec.timeout_ms),
                timeout=spec.timeout_ms / 1000.0,
            )

            # Use provided latency or calculate our own
            if latency_ms is None:
                latency_ms = self.now_ms() - start_time

            return status, latency_ms, error

        except Exception as e:
            latency = self.now_ms() - start_time
            return "down", latency, str(e)


# ============================================================================
# Main Monitor Class
# ============================================================================


class APIHealthMonitor:
    """Main health monitoring coordinator."""

    def __init__(
        self,
        specs: list[CheckSpec],
        config: MonitorConfig,
        *,
        now_ms: Callable[[], int],
        emit: Callable[[HealthEvent], None],
        custom_fn: Callable[..., Awaitable[tuple[HealthStatus, int | None, str | None]]] | None = None,
    ) -> None:
        """Initialize API health monitor.

        Args:
            specs: List of health check specifications
            config: Monitor configuration
            now_ms: Callable that returns current time in milliseconds
            emit: Callback to emit health events
            custom_fn: Optional custom check function for custom/mcp/llm checks
        """
        self.specs = specs
        self.config = config
        self.now_ms = now_ms
        self.emit = emit
        self.custom_fn = custom_fn

        self.logger = logging.getLogger(f"{__name__}.APIHealthMonitor")
        self.running = False
        self.tasks: list[asyncio.Task[None]] = []
        self.session: Any | None = None

        # Per-check state
        self.circuit_breakers: dict[str, CircuitBreaker] = {}
        self.sla_trackers: dict[str, SLATracker] = {}
        self.last_events: dict[str, HealthEvent] = {}

        # Concurrency control (initialized in start)
        self._sem: asyncio.Semaphore | None = None

        # Initialize state for each check
        for spec in specs:
            self.circuit_breakers[spec.name] = CircuitBreaker(spec)
            self.sla_trackers[spec.name] = SLATracker(spec)

    async def start(self) -> None:
        """Start monitoring all checks.

        Returns:
            None

        Note:
            If already running, returns immediately without error.
        """
        if self.running:
            return

        self.running = True
        self.logger.info(f"Starting health monitor with {len(self.specs)} checks")

        # Create HTTP session if needed (per-request timeouts will be used)
        http_specs = [s for s in self.specs if s.kind == "http"]
        if http_specs and AIOHTTP_AVAILABLE:
            self.session = aiohttp.ClientSession()

        # Shared semaphore to enforce global max concurrency
        self._sem = asyncio.Semaphore(self.config.max_concurrency)

        # Start tasks with deterministic staggering
        for spec in self.specs:
            stagger_offset = (
                (stable_hash(spec.name) % 1000) * self.config.deterministic_stagger_ms // 1000
            )
            task = asyncio.create_task(self._monitor_loop(spec, stagger_offset))
            self.tasks.append(task)

        self.logger.info("Health monitor started")

    async def stop(self) -> None:
        """Stop monitoring and cleanup.

        Returns:
            None

        Note:
            If not running, returns immediately without error.
        """
        if not self.running:
            return

        self.logger.info("Stopping health monitor...")
        self.running = False

        for task in self.tasks:
            task.cancel()

        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)

        if self.session is not None:
            await self.session.close()
            self.session = None

        self.tasks.clear()
        self.logger.info("Health monitor stopped")

    async def _monitor_loop(self, spec: CheckSpec, stagger_ms: int) -> None:
        """Main monitoring loop for a single check.

        Args:
            spec: Health check specification
            stagger_ms: Initial delay in milliseconds for staggered startup
        """
        # Initial stagger delay
        if stagger_ms > 0:
            await asyncio.sleep(stagger_ms / 1000.0)

        runner = CheckRunner(self.now_ms, self.session, self.custom_fn)
        circuit = self.circuit_breakers[spec.name]
        sla_tracker = self.sla_trackers[spec.name]

        self.logger.debug(f"Started monitoring loop for {spec.name}")

        while self.running:
            loop_start_ms = self.now_ms()

            try:
                # Run health check under concurrency guard
                if self._sem is not None:
                    async with self._sem:
                        result = await runner.run_once(spec, circuit, sla_tracker)
                else:  # Fallback (shouldn't happen)
                    result = await runner.run_once(spec, circuit, sla_tracker)

                # Create health event (single snapshot used for message & event)
                snap = circuit.snapshot()
                event = HealthEvent(
                    check=result,
                    circuit=snap,
                    sla_1m=sla_tracker.sla_1m(),
                    sla_5m=sla_tracker.sla_5m(),
                    message=self._format_message(result, snap, sla_tracker),
                )

                # Emit event if changed or configured to emit always
                should_emit = (
                    self.config.emit_on_unchanged
                    or spec.name not in self.last_events
                    or self._event_changed(self.last_events[spec.name], event)
                )

                if should_emit:
                    try:
                        self.emit(event)
                    except Exception as e:  # pragma: no cover - emitter provided by caller
                        self.logger.error(f"Failed to emit event for {spec.name}: {e}")

                self.last_events[spec.name] = event

            except Exception as e:  # pragma: no cover - safety catch
                self.logger.error(f"Error in monitoring loop for {spec.name}: {e}")

            # Sleep until next interval
            elapsed_ms = self.now_ms() - loop_start_ms
            sleep_ms = max(0, spec.interval_ms - elapsed_ms)

            if sleep_ms > 0:
                await asyncio.sleep(sleep_ms / 1000.0)

    def _format_message(
        self, result: CheckResult, circuit: CircuitSnapshot, sla: SLATracker
    ) -> str:
        """Format human-readable status message (stable structure).

        Args:
            result: Check result
            circuit: Circuit breaker snapshot
            sla: SLA tracker

        Returns:
            Human-readable status message
        """
        status_emoji = {
            "up": "✓",
            "degraded": "⚠",
            "down": "✗",
            "unknown": "?",
        }

        parts = [f"{result.kind}", f"{status_emoji.get(result.status, '?')} {result.status}"]

        if result.http_code is not None:
            parts.append(f"{result.http_code}")

        if result.latency_ms is not None:
            parts.append(f"in {result.latency_ms}ms")

        circuit_emoji = {"closed": "○", "open": "●", "half_open": "◐"}
        parts.append(f"({circuit_emoji.get(circuit.state, '?')})")

        parts.append(f"sla1m={sla.sla_1m():.2f}")
        parts.append(f"sla5m={sla.sla_5m():.2f}")

        return " ".join(parts)

    def _event_changed(self, prev: HealthEvent, current: HealthEvent) -> bool:
        """Check if health event represents a significant change.

        Args:
            prev: Previous health event
            current: Current health event

        Returns:
            True if status or circuit state changed
        """
        return (prev.check.status != current.check.status) or (
            prev.circuit.state != current.circuit.state
        )


# ============================================================================
# Sync Helper Functions
# ============================================================================


def run_checks_once(
    specs: list[CheckSpec],
    now_ms: int,
    custom_fn: Callable[..., Awaitable[tuple[HealthStatus, int | None, str | None]]] | None = None,
) -> list[HealthEvent]:
    """Synchronous helper to run checks once (bounded to a single tick).

    Args:
        specs: List of health check specifications
        now_ms: Current timestamp in milliseconds
        custom_fn: Optional custom check function

    Returns:
        List of health events from check execution
    """

    async def _run_all() -> list[HealthEvent]:
        events: list[HealthEvent] = []

        # Create session if needed
        session: Any | None = None
        http_specs = [s for s in specs if s.kind == "http"]
        if http_specs and AIOHTTP_AVAILABLE:
            session = aiohttp.ClientSession()

        try:
            # Create runners and state
            runners: dict[str, CheckRunner] = {}
            circuits: dict[str, CircuitBreaker] = {}
            slas: dict[str, SLATracker] = {}

            for spec in specs:
                runners[spec.name] = CheckRunner(lambda: now_ms, session, custom_fn)
                circuits[spec.name] = CircuitBreaker(spec)
                slas[spec.name] = SLATracker(spec)

            # Run all checks concurrently
            tasks: list[tuple[str, asyncio.Task[CheckResult]]] = []
            for spec in specs:
                task = asyncio.create_task(
                    runners[spec.name].run_once(spec, circuits[spec.name], slas[spec.name])
                )
                tasks.append((spec.name, task))

            results: list[CheckResult | BaseException] = await asyncio.gather(
                *[task for _, task in tasks], return_exceptions=True
            )

            # Build events
            for (name, _), result in zip(tasks, results):
                if isinstance(result, BaseException):
                    spec = next(s for s in specs if s.name == name)
                    check_result = CheckResult(
                        name=name,
                        kind=spec.kind,
                        target=spec.target,
                        ts_ms=now_ms,
                        status="down",
                        error=str(result),
                    )
                else:
                    check_result = result

                event = HealthEvent(
                    check=check_result,
                    circuit=circuits[name].snapshot(),
                    sla_1m=slas[name].sla_1m(),
                    sla_5m=slas[name].sla_5m(),
                    message=f"{check_result.kind} {check_result.status}",
                )
                events.append(event)

        finally:
            if session is not None:
                await session.close()

        return events

    # Run in event loop
    try:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(_run_all())
    except RuntimeError:
        return asyncio.run(_run_all())


# ============================================================================
# Demo/Testing (optional)
# ============================================================================

if __name__ == "__main__":  # pragma: no cover - demo usage
    import json
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger = logging.getLogger(__name__)

    async def demo_custom_check(
        spec: CheckSpec, timeout_ms: int
    ) -> tuple[HealthStatus, int | None, str | None]:
        """Demo custom check that alternates up/down deterministically."""
        await asyncio.sleep(0.01)  # Simulate work

        # Deterministic alternating based on injected time (seconds)
        secs = demo_now_ms() // 1000
        hv = stable_hash(f"{spec.name}:{secs}")
        up = (hv % 2) == 0

        return (
            "up" if up else "down",
            50 if up else None,
            None if up else "Simulated failure",
        )

    def demo_emit(event: HealthEvent) -> None:
        """Demo event emitter (console)."""
        logger = logging.getLogger(__name__)
        logger.info("Event: %s", event.message)
        if event.check.status == "down":
            logger.error("   Error: %s", event.check.error)

    # Create demo time function (advancing counter for determinism)
    start_time = int(time.time() * 1000)
    _time_counter = 0

    def demo_now_ms() -> int:
        global _time_counter
        _time_counter += 1
        return start_time + (_time_counter * 100)  # Advance 100ms per call

    async def demo_main() -> None:
        """Demo with HTTP (if available) and custom checks."""
        logger.info("Starting API Health Monitor Demo")

        specs: list[CheckSpec] = []

        # HTTP checks if aiohttp available
        if AIOHTTP_AVAILABLE:
            specs.extend(
                [
                    CheckSpec(
                        name="example_ok",
                        kind="http",
                        target="https://example.com",
                        interval_ms=3000,
                        timeout_ms=2000,
                        retries=1,
                        open_after_failures=2,
                        half_open_after_ms=10000,
                        degraded_threshold_ms=1000,
                        tags={"env": "demo", "type": "external"},
                    ),
                    CheckSpec(
                        name="example_404",
                        kind="http",
                        target="https://example.com/nonexistent",
                        interval_ms=4000,
                        timeout_ms=2000,
                        retries=1,
                        open_after_failures=2,
                        half_open_after_ms=10000,
                        degraded_threshold_ms=1000,
                        tags={"env": "demo", "type": "external"},
                    ),
                ]
            )
        else:
            logger.warning("aiohttp not available, using custom checks only")

        # Custom checks (always available)
        specs.extend(
            [
                CheckSpec(
                    name="custom_service_a",
                    kind="custom",
                    target="service-a",
                    interval_ms=2000,
                    timeout_ms=1000,
                    retries=2,
                    open_after_failures=3,
                    half_open_after_ms=8000,
                    degraded_threshold_ms=500,
                    tags={"env": "demo", "type": "internal"},
                ),
                CheckSpec(
                    name="custom_service_b",
                    kind="custom",
                    target="service-b",
                    interval_ms=2500,
                    timeout_ms=1000,
                    retries=1,
                    open_after_failures=2,
                    half_open_after_ms=5000,
                    degraded_threshold_ms=300,
                    tags={"env": "demo", "type": "internal"},
                ),
            ]
        )

        # Redis check (TCP connection test)
        specs.append(
            CheckSpec(
                name="redis_local",
                kind="redis",
                target="localhost:6379",
                interval_ms=5000,
                timeout_ms=1000,
                retries=1,
                open_after_failures=3,
                half_open_after_ms=15000,
                degraded_threshold_ms=200,
                tags={"env": "demo", "type": "cache"},
            )
        )

        config = MonitorConfig(
            max_concurrency=4,
            deterministic_stagger_ms=200,
            emit_on_unchanged=True,  # For demo purposes
        )

        monitor = APIHealthMonitor(
            specs=specs,
            config=config,
            now_ms=demo_now_ms,
            emit=demo_emit,
            custom_fn=demo_custom_check,
        )

        try:
            await monitor.start()
            logger.info("Monitor running... (will stop in 30 seconds)")
            await asyncio.sleep(30)
        except KeyboardInterrupt:
            logger.info("Demo interrupted by user")
        finally:
            await monitor.stop()
            logger.info("Demo completed")

    def test_sync_helper() -> None:
        """Test the synchronous run_checks_once function."""
        logger.info("Testing sync helper function...")

        test_specs = [
            CheckSpec(
                name="sync_test_custom",
                kind="custom",
                target="test-target",
                interval_ms=1000,
                timeout_ms=500,
                retries=1,
                open_after_failures=2,
                half_open_after_ms=5000,
                degraded_threshold_ms=200,
                tags={"test": "sync"},
            )
        ]

        events = run_checks_once(test_specs, demo_now_ms(), demo_custom_check)
        logger.info("Sync test completed, got %d events:", len(events))
        for event in events:
            logger.info("  - %s", event.message)

    # Entry points
    if len(sys.argv) > 1:
        if sys.argv[1] == "sync":
            test_sync_helper()
        elif sys.argv[1] == "json-schema":
            schemas = {
                "CheckSpec": CheckSpec.model_json_schema(),
                "CheckResult": CheckResult.model_json_schema(),
                "CircuitSnapshot": CircuitSnapshot.model_json_schema(),
                "HealthEvent": HealthEvent.model_json_schema(),
                "MonitorConfig": MonitorConfig.model_json_schema(),
            }
            logger = logging.getLogger(__name__)
            logger.info(json.dumps(schemas, indent=2))
        else:
            logger = logging.getLogger(__name__)
            logger.info("Usage: python api_health_monitor.py [sync|json-schema]")
            logger.info("  sync: Test synchronous helper")
            logger.info("  json-schema: Export JSON schemas")
            logger.info("  (no args): Run full async demo")
    else:
        try:
            asyncio.run(demo_main())
        except KeyboardInterrupt:
            logger.info("Demo interrupted")
        except Exception as e:
            logger.error(f"Demo failed: {e}", exc_info=True)
