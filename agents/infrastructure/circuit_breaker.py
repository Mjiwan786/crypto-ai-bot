"""
Circuit Breaker Pattern for Agent Failure Isolation

Prevents individual agent failures from cascading and crashing the entire system.

Features:
- Per-agent failure tracking with configurable thresholds
- Automatic circuit opening after N consecutive failures
- Auto-recovery with cooldown period
- Prometheus metrics for monitoring
- Half-open state for testing recovery

States:
- CLOSED: Normal operation, agent called directly
- OPEN: Agent disabled due to failures, returns empty result
- HALF_OPEN: Testing if agent has recovered

PRD-001 Compliance:
- Section 4.4: Agent failure isolation
- Section 8.2: Prometheus metrics for failures

Author: Reliability & QA Team
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import Callable, Any, Dict, Optional, TypeVar, ParamSpec

# Prometheus metrics
try:
    from prometheus_client import Counter, Gauge, Histogram

    CIRCUIT_BREAKER_STATE = Gauge(
        'agent_circuit_breaker_state',
        'Circuit breaker state (0=closed, 1=open, 2=half_open)',
        ['agent']
    )

    CIRCUIT_BREAKER_FAILURES = Counter(
        'agent_circuit_breaker_failures_total',
        'Total agent failures tracked by circuit breaker',
        ['agent', 'error_type']
    )

    CIRCUIT_BREAKER_TRIGGERS = Counter(
        'agent_circuit_breaker_triggered_total',
        'Total circuit breaker trips',
        ['agent', 'reason']
    )

    CIRCUIT_BREAKER_RECOVERIES = Counter(
        'agent_circuit_breaker_recovered_total',
        'Total circuit breaker recoveries',
        ['agent']
    )

    AGENT_CALL_DURATION = Histogram(
        'agent_call_duration_seconds',
        'Agent call duration in seconds',
        ['agent', 'outcome']
    )

    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    CIRCUIT_BREAKER_STATE = None
    CIRCUIT_BREAKER_FAILURES = None
    CIRCUIT_BREAKER_TRIGGERS = None
    CIRCUIT_BREAKER_RECOVERIES = None
    AGENT_CALL_DURATION = None

logger = logging.getLogger(__name__)

P = ParamSpec('P')
T = TypeVar('T')


class CircuitState(str, Enum):
    """Circuit breaker states"""
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Circuit tripped, agent disabled
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior"""

    # Failure thresholds
    failure_threshold: int = 5  # Open circuit after N consecutive failures
    half_open_max_calls: int = 3  # Test N calls in half-open state

    # Time windows
    cooldown_seconds: int = 300  # 5 minutes cooldown before half-open
    timeout_seconds: float = 30.0  # Max execution time before timeout

    # Success criteria
    success_threshold: int = 2  # N successful calls to close circuit from half-open

    # Metrics
    rolling_window_size: int = 100  # Track success rate over N calls

    # Degradation
    min_success_rate: float = 0.8  # Mark degraded if success rate < 80%


@dataclass
class CircuitBreakerState:
    """Internal state of a circuit breaker"""

    agent_name: str
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    half_open_calls: int = 0
    last_failure_time: float = 0.0
    last_state_change: float = field(default_factory=time.time)

    # Rolling window for success rate
    recent_results: list[bool] = field(default_factory=list)  # True=success, False=failure

    # Error tracking
    last_error: Optional[str] = None
    error_types: Dict[str, int] = field(default_factory=dict)


class CircuitBreaker:
    """
    Circuit breaker for agent failure isolation.

    Usage:
        # As a decorator
        @circuit_breaker(agent_name="my_agent")
        async def my_agent_function():
            # ... agent logic ...
            pass

        # Or manually
        breaker = CircuitBreaker(agent_name="my_agent")
        result = await breaker.call(my_agent_function, *args, **kwargs)
    """

    def __init__(
        self,
        agent_name: str,
        config: Optional[CircuitBreakerConfig] = None
    ):
        """
        Initialize circuit breaker for an agent.

        Args:
            agent_name: Unique identifier for the agent
            config: Circuit breaker configuration (uses defaults if None)
        """
        self.agent_name = agent_name
        self.config = config or CircuitBreakerConfig()
        self.state = CircuitBreakerState(agent_name=agent_name)
        self.logger = logging.getLogger(f"CircuitBreaker.{agent_name}")

        # Initialize Prometheus gauge
        if PROMETHEUS_AVAILABLE and CIRCUIT_BREAKER_STATE:
            CIRCUIT_BREAKER_STATE.labels(agent=agent_name).set(0)  # CLOSED = 0

    def _update_prometheus_state(self):
        """Update Prometheus gauge with current state"""
        if not PROMETHEUS_AVAILABLE or not CIRCUIT_BREAKER_STATE:
            return

        state_value = {
            CircuitState.CLOSED: 0,
            CircuitState.OPEN: 1,
            CircuitState.HALF_OPEN: 2
        }[self.state.state]

        CIRCUIT_BREAKER_STATE.labels(agent=self.agent_name).set(state_value)

    def _transition_to(self, new_state: CircuitState, reason: str):
        """Transition circuit breaker to new state"""
        old_state = self.state.state

        if old_state == new_state:
            return

        self.state.state = new_state
        self.state.last_state_change = time.time()

        self.logger.warning(
            f"Circuit breaker state transition: {old_state} → {new_state}",
            extra={
                "agent": self.agent_name,
                "old_state": old_state,
                "new_state": new_state,
                "reason": reason,
                "failure_count": self.state.failure_count
            }
        )

        # Update Prometheus
        self._update_prometheus_state()

        # Emit trigger metric if opening
        if new_state == CircuitState.OPEN and PROMETHEUS_AVAILABLE and CIRCUIT_BREAKER_TRIGGERS:
            CIRCUIT_BREAKER_TRIGGERS.labels(agent=self.agent_name, reason=reason).inc()

    def _record_success(self):
        """Record successful call"""
        self.state.success_count += 1
        self.state.failure_count = 0  # Reset consecutive failures
        self.state.recent_results.append(True)

        # Trim rolling window
        if len(self.state.recent_results) > self.config.rolling_window_size:
            self.state.recent_results.pop(0)

        # Handle state transitions
        if self.state.state == CircuitState.HALF_OPEN:
            self.state.half_open_calls += 1

            if self.state.half_open_calls >= self.config.success_threshold:
                self._transition_to(CircuitState.CLOSED, "Recovered after successful tests")

                if PROMETHEUS_AVAILABLE and CIRCUIT_BREAKER_RECOVERIES:
                    CIRCUIT_BREAKER_RECOVERIES.labels(agent=self.agent_name).inc()

    def _record_failure(self, error: Exception):
        """Record failed call"""
        self.state.failure_count += 1
        self.state.success_count = 0  # Reset consecutive successes
        self.state.last_failure_time = time.time()
        self.state.last_error = str(error)
        self.state.recent_results.append(False)

        # Track error type
        error_type = type(error).__name__
        self.state.error_types[error_type] = self.state.error_types.get(error_type, 0) + 1

        # Trim rolling window
        if len(self.state.recent_results) > self.config.rolling_window_size:
            self.state.recent_results.pop(0)

        # Emit Prometheus metric
        if PROMETHEUS_AVAILABLE and CIRCUIT_BREAKER_FAILURES:
            CIRCUIT_BREAKER_FAILURES.labels(agent=self.agent_name, error_type=error_type).inc()

        # Handle state transitions
        if self.state.state == CircuitState.CLOSED:
            if self.state.failure_count >= self.config.failure_threshold:
                self._transition_to(
                    CircuitState.OPEN,
                    f"Failure threshold reached ({self.config.failure_threshold})"
                )

        elif self.state.state == CircuitState.HALF_OPEN:
            # Failure during testing - reopen circuit
            self._transition_to(CircuitState.OPEN, "Failed during half-open test")
            self.state.half_open_calls = 0

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset"""
        if self.state.state != CircuitState.OPEN:
            return False

        time_since_failure = time.time() - self.state.last_failure_time
        return time_since_failure >= self.config.cooldown_seconds

    async def call(self, func: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> Optional[T]:
        """
        Execute function with circuit breaker protection.

        Args:
            func: Function to call
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func

        Returns:
            Function result if successful, None if circuit is open

        Raises:
            Exception: Re-raises exceptions in CLOSED state after recording
        """
        # Check if circuit should transition to half-open
        if self._should_attempt_reset():
            self._transition_to(CircuitState.HALF_OPEN, "Cooldown period elapsed, testing recovery")
            self.state.half_open_calls = 0

        # Reject call if circuit is open
        if self.state.state == CircuitState.OPEN:
            self.logger.warning(
                f"Circuit breaker OPEN - rejecting call to {self.agent_name}",
                extra={
                    "agent": self.agent_name,
                    "failure_count": self.state.failure_count,
                    "last_error": self.state.last_error
                }
            )
            return None

        # Execute with timeout and error handling
        start_time = time.time()

        try:
            # Call the function (async or sync)
            import asyncio
            import inspect

            if inspect.iscoroutinefunction(func):
                result = await asyncio.wait_for(
                    func(*args, **kwargs),
                    timeout=self.config.timeout_seconds
                )
            else:
                result = func(*args, **kwargs)

            # Record success
            duration = time.time() - start_time
            self._record_success()

            if PROMETHEUS_AVAILABLE and AGENT_CALL_DURATION:
                AGENT_CALL_DURATION.labels(agent=self.agent_name, outcome="success").observe(duration)

            return result

        except asyncio.TimeoutError as e:
            duration = time.time() - start_time
            self.logger.error(
                f"Agent call timeout after {duration:.2f}s",
                extra={"agent": self.agent_name, "timeout": self.config.timeout_seconds}
            )
            self._record_failure(e)

            if PROMETHEUS_AVAILABLE and AGENT_CALL_DURATION:
                AGENT_CALL_DURATION.labels(agent=self.agent_name, outcome="timeout").observe(duration)

            raise

        except Exception as e:
            duration = time.time() - start_time
            self.logger.error(
                f"Agent call failed: {e}",
                extra={
                    "agent": self.agent_name,
                    "error_type": type(e).__name__,
                    "error_message": str(e)
                },
                exc_info=True
            )
            self._record_failure(e)

            if PROMETHEUS_AVAILABLE and AGENT_CALL_DURATION:
                AGENT_CALL_DURATION.labels(agent=self.agent_name, outcome="failure").observe(duration)

            raise

    def get_health_status(self) -> Dict[str, Any]:
        """
        Get current health status of circuit breaker.

        Returns:
            Health status dictionary
        """
        # Calculate success rate
        if len(self.state.recent_results) > 0:
            success_rate = sum(self.state.recent_results) / len(self.state.recent_results)
        else:
            success_rate = 1.0

        # Determine health
        if self.state.state == CircuitState.OPEN:
            health = "unhealthy"
        elif success_rate < self.config.min_success_rate:
            health = "degraded"
        else:
            health = "healthy"

        return {
            "agent": self.agent_name,
            "health": health,
            "state": self.state.state,
            "success_rate": round(success_rate, 3),
            "failure_count": self.state.failure_count,
            "success_count": self.state.success_count,
            "last_error": self.state.last_error,
            "error_types": self.state.error_types,
            "time_in_state_seconds": round(time.time() - self.state.last_state_change, 2)
        }

    def reset(self):
        """Manually reset circuit breaker to CLOSED state"""
        self.logger.info(f"Manually resetting circuit breaker for {self.agent_name}")
        self._transition_to(CircuitState.CLOSED, "Manual reset")
        self.state.failure_count = 0
        self.state.success_count = 0
        self.state.half_open_calls = 0


# Global registry of circuit breakers
_circuit_breakers: Dict[str, CircuitBreaker] = {}


def get_circuit_breaker(agent_name: str, config: Optional[CircuitBreakerConfig] = None) -> CircuitBreaker:
    """
    Get or create circuit breaker for an agent.

    Args:
        agent_name: Unique agent identifier
        config: Circuit breaker configuration (only used for new breakers)

    Returns:
        CircuitBreaker instance for the agent
    """
    if agent_name not in _circuit_breakers:
        _circuit_breakers[agent_name] = CircuitBreaker(agent_name, config)

    return _circuit_breakers[agent_name]


def circuit_breaker(
    agent_name: str,
    config: Optional[CircuitBreakerConfig] = None
):
    """
    Decorator to add circuit breaker protection to agent functions.

    Args:
        agent_name: Unique agent identifier
        config: Optional circuit breaker configuration

    Example:
        @circuit_breaker(agent_name="scalper")
        async def generate_signals(market_data):
            # ... agent logic ...
            pass
    """
    breaker = get_circuit_breaker(agent_name, config)

    def decorator(func: Callable[P, T]) -> Callable[P, Optional[T]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> Optional[T]:
            return await breaker.call(func, *args, **kwargs)

        return wrapper

    return decorator


def get_all_breaker_health() -> Dict[str, Dict[str, Any]]:
    """
    Get health status of all circuit breakers.

    Returns:
        Dictionary mapping agent names to health status
    """
    return {
        name: breaker.get_health_status()
        for name, breaker in _circuit_breakers.items()
    }


__all__ = [
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitState",
    "circuit_breaker",
    "get_circuit_breaker",
    "get_all_breaker_health",
]
