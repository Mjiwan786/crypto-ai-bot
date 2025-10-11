"""
Circuit breaker system for scalping agent protection.

This module provides comprehensive circuit breaker capabilities for the scalping
system, implementing multiple layers of safety mechanisms to protect against
adverse market conditions and system failures.

Features:
- Multiple circuit breaker types (spread, latency, loss, frequency, API errors)
- Configurable thresholds and time windows
- Automatic recovery and half-open state testing
- Real-time monitoring and health checks
- Redis-based event broadcasting
- Callback system for custom actions
- System-wide halt and resume capabilities

This module provides the core circuit breaker infrastructure for the scalping
system, enabling robust protection against various failure modes and market risks.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..config_loader import KrakenScalpingConfig
from ..infra.redis_bus import RedisBus

logger = logging.getLogger(__name__)


class CircuitBreakerState(Enum):
    """Circuit breaker states"""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Circuit breaker triggered
    HALF_OPEN = "half_open"  # Testing recovery


class BreakerType(Enum):
    """Types of circuit breakers"""

    SPREAD = "spread"
    LATENCY = "latency"
    LOSS = "loss"
    FREQUENCY = "frequency"
    API_ERROR = "api_error"
    LIQUIDITY = "liquidity"
    VOLATILITY = "volatility"
    CONNECTIVITY = "connectivity"


@dataclass
class BreakerEvent:
    """Circuit breaker trigger event"""

    breaker_type: BreakerType
    trigger_value: float
    threshold_value: float
    timestamp: float = field(default_factory=time.time)
    message: str = ""
    severity: str = "warning"  # "warning", "critical"


@dataclass
class BreakerConfig:
    """Configuration for a circuit breaker"""

    threshold: float
    window_seconds: int = 60
    min_triggers: int = 1
    timeout_seconds: int = 300
    auto_reset: bool = True
    escalation_levels: List[float] = field(default_factory=list)


class CircuitBreaker:
    """Individual circuit breaker implementation (self-contained)."""

    def __init__(
        self,
        name: str,
        breaker_type: BreakerType,
        config: BreakerConfig,
        callback: Optional[Callable[[Any, BreakerEvent], Any]] = None,
    ):
        self.name = name
        self.breaker_type = breaker_type
        self.config = config
        self.callback = callback

        # State
        self.state = CircuitBreakerState.CLOSED
        self.trigger_count = 0
        self.last_trigger_time = 0.0
        self.open_time = 0.0

        # Histories
        self.trigger_history: List[BreakerEvent] = []
        self.value_history: List[Tuple[float, float]] = []  # (value, timestamp)

        self.logger = logging.getLogger(f"{__name__}.{name}")

    async def check_value(self, value: float) -> bool:
        """
        Feed a measurement into the breaker.
        Returns True if breaker is currently OPEN (i.e., protective action required).
        """
        now = time.time()
        self.value_history.append((float(value), now))
        self._cleanup_history(now)

        # Already open → maybe move to HALF_OPEN if timeout elapsed, but still "open" to callers
        if self.state == CircuitBreakerState.OPEN:
            if self.config.auto_reset and (now - self.open_time) >= self.config.timeout_seconds:
                await self._transition_to_half_open()
            return True

        # HALF_OPEN: if value stays below threshold during probe, we close; otherwise reopen.
        if self.state == CircuitBreakerState.HALF_OPEN:
            if not self._value_exceeds_threshold(value):
                await self._transition_to_closed()
                return False
            # Threshold still exceeded in HALF_OPEN → open again
            await self._handle_threshold_exceeded(value, now)
            return True

        # CLOSED: evaluate threshold/window logic
        if self._value_exceeds_threshold(value):
            triggered = await self._handle_threshold_exceeded(value, now)
            return triggered

        return False

    async def force_open(self, reason: str, duration_seconds: Optional[int] = None) -> None:
        """Force circuit breaker open."""
        await self._transition_to_open(reason, duration_seconds)

    async def force_close(self) -> None:
        """Force circuit breaker closed (clears trigger count)."""
        await self._transition_to_closed()

    def get_status(self) -> Dict[str, Any]:
        """Introspect breaker status."""
        return {
            "name": self.name,
            "type": self.breaker_type.value,
            "state": self.state.value,
            "trigger_count": self.trigger_count,
            "last_trigger_time": self.last_trigger_time,
            "threshold": self.config.threshold,
            "recent_values": self.value_history[-5:] if self.value_history else [],
            "open_time": self.open_time,
        }

    # ------------------------ Internals ------------------------

    def _value_exceeds_threshold(self, value: float) -> bool:
        """Simple threshold comparator (treat threshold as an upper bound)."""
        try:
            return float(value) > float(self.config.threshold)
        except Exception:
            return False

    async def _handle_threshold_exceeded(self, value: float, current_time: float) -> bool:
        """Count threshold breaches within the window and open if min_triggers met."""
        window_start = current_time - float(self.config.window_seconds)

        recent_triggers = 0
        for val, ts in self.value_history:
            if ts >= window_start and self._value_exceeds_threshold(val):
                recent_triggers += 1

        if recent_triggers >= int(self.config.min_triggers):
            severity = (
                "critical" if float(value) > float(self.config.threshold) * 2.0 else "warning"
            )
            event = BreakerEvent(
                breaker_type=self.breaker_type,
                trigger_value=float(value),
                threshold_value=float(self.config.threshold),
                timestamp=current_time,
                message=f"{self.name} triggered: {value} > {self.config.threshold}",
                severity=severity,
            )
            await self._trigger_breaker(event)
            return True

        return False

    async def _trigger_breaker(self, event: BreakerEvent) -> None:
        """Record and open the breaker, then invoke callback."""
        self.trigger_history.append(event)
        self.trigger_count += 1
        self.last_trigger_time = event.timestamp

        await self._transition_to_open(event.message)

        if self.callback:
            await self._invoke_callback(self.callback, event)

    async def _invoke_callback(
        self, cb: Callable[[Any, BreakerEvent], Any], event: BreakerEvent
    ) -> None:
        """Invoke sync or async callback safely."""
        try:
            if inspect.iscoroutinefunction(cb):
                await cb(self, event)
            else:
                cb(self, event)
        except Exception as e:
            self.logger.error(f"Error in breaker callback: {e}", exc_info=True)

    async def _transition_to_open(
        self, reason: str, duration_seconds: Optional[int] = None
    ) -> None:
        """Transition to OPEN and (optionally) schedule an auto-reset timer."""
        self.state = CircuitBreakerState.OPEN
        self.open_time = time.time()
        self.logger.warning(f"Circuit breaker {self.name} OPENED: {reason}")

        # Optional short-circuit timer separate from config.timeout_seconds
        if duration_seconds and duration_seconds > 0:
            asyncio.create_task(self._auto_reset(duration_seconds))

    async def _transition_to_half_open(self) -> None:
        """Transition to HALF_OPEN for probe requests."""
        if self.state != CircuitBreakerState.HALF_OPEN:
            self.state = CircuitBreakerState.HALF_OPEN
            self.logger.info(f"Circuit breaker {self.name} HALF-OPEN: testing recovery")

    async def _transition_to_closed(self) -> None:
        """Transition to CLOSED and reset counters."""
        self.state = CircuitBreakerState.CLOSED
        self.trigger_count = 0
        self.logger.info(f"Circuit breaker {self.name} CLOSED: normal operation resumed")

    async def _auto_reset(self, delay_seconds: int) -> None:
        """Move from OPEN to HALF_OPEN after a delay (if still OPEN)."""
        await asyncio.sleep(max(0, int(delay_seconds)))
        if self.state == CircuitBreakerState.OPEN:
            await self._transition_to_half_open()

    def _cleanup_history(self, current_time: float) -> None:
        """Trim old history entries to keep memory bounded."""
        cutoff = current_time - (float(self.config.window_seconds) * 2.0)

        # Keep recent values
        self.value_history = [(v, ts) for (v, ts) in self.value_history if ts >= cutoff]

        # Keep only last hour of triggers
        self.trigger_history = [
            ev for ev in self.trigger_history if (current_time - ev.timestamp) <= 3600.0
        ]


class CircuitBreakerManager:
    """
    Manages multiple circuit breakers for the scalping system.
    Coordinates different types of protection mechanisms.
    """

    def __init__(
        self,
        config: KrakenScalpingConfig,
        redis_bus: RedisBus,
        agent_id: str = "kraken_scalper",
    ):
        self.config = config
        self.redis_bus = redis_bus
        self.agent_id = agent_id
        self.logger = logging.getLogger(f"{__name__}.{agent_id}")

        # Circuit breakers
        self.breakers: Dict[BreakerType, CircuitBreaker] = {}
        self.global_breakers: List[CircuitBreaker] = []

        # System state
        self.system_halted = False
        self.halt_reason = ""
        self.halt_timestamp = 0.0

        # Callbacks registry
        self.callbacks: Dict[BreakerType, List[Callable[[BreakerEvent], Any]]] = {
            breaker_type: [] for breaker_type in BreakerType
        }

        self._setup_breakers()
        self.logger.info("CircuitBreakerManager initialized")

    async def start(self) -> None:
        """Start the circuit breaker system."""
        self.logger.info("Starting CircuitBreakerManager...")
        await self._setup_monitoring()
        asyncio.create_task(self._health_check_loop())
        self.logger.info("CircuitBreakerManager started")

    async def stop(self) -> None:
        """Stop the circuit breaker system."""
        self.logger.info("CircuitBreakerManager stopped")

    # ------------------------ Checkers ------------------------

    async def check_spread(self, spread_bps: float) -> bool:
        if BreakerType.SPREAD in self.breakers:
            return await self.breakers[BreakerType.SPREAD].check_value(spread_bps)
        return False

    async def check_latency(self, latency_ms: float) -> bool:
        if BreakerType.LATENCY in self.breakers:
            return await self.breakers[BreakerType.LATENCY].check_value(latency_ms)
        return False

    async def check_loss(self, loss_pct: float) -> bool:
        if BreakerType.LOSS in self.breakers:
            # Pass absolute % loss to compare with positive threshold
            return await self.breakers[BreakerType.LOSS].check_value(abs(loss_pct))
        return False

    async def check_frequency(self, trades_per_minute: float) -> bool:
        if BreakerType.FREQUENCY in self.breakers:
            return await self.breakers[BreakerType.FREQUENCY].check_value(trades_per_minute)
        return False

    async def check_api_errors(self, error_rate_pct: float) -> bool:
        if BreakerType.API_ERROR in self.breakers:
            return await self.breakers[BreakerType.API_ERROR].check_value(error_rate_pct)
        return False

    # ------------------------ System control ------------------------

    async def halt_system(self, reason: str, duration_seconds: int = 900) -> None:
        """Emergency halt of the entire system (broadcast + open all breakers)."""
        self.system_halted = True
        self.halt_reason = reason
        self.halt_timestamp = time.time()

        for breaker in self.breakers.values():
            await breaker.force_open(f"System halt: {reason}", duration_seconds)

        await self.redis_bus.publish(
            f"system:halt:{self.agent_id}",
            {"reason": reason, "duration_seconds": duration_seconds, "timestamp": time.time()},
        )

        self.logger.critical(f"SYSTEM HALTED: {reason}")

        if duration_seconds > 0:
            asyncio.create_task(self._auto_resume(duration_seconds))

    async def resume_system(self) -> None:
        """Resume system operations (close all breakers)."""
        if not self.system_halted:
            return

        self.system_halted = False
        self.halt_reason = ""

        for breaker in self.breakers.values():
            await breaker.force_close()

        await self.redis_bus.publish(f"system:resume:{self.agent_id}", {"timestamp": time.time()})
        self.logger.info("System operations resumed")

    def is_any_breaker_open(self) -> bool:
        """True if any breaker is OPEN or HALF_OPEN (i.e., constrained)."""
        return any(b.state != CircuitBreakerState.CLOSED for b in self.breakers.values())

    def get_system_status(self) -> Dict[str, Any]:
        """Get comprehensive system status snapshot."""
        return {
            "system_halted": self.system_halted,
            "halt_reason": self.halt_reason,
            "halt_timestamp": self.halt_timestamp,
            "breakers": {bt.value: br.get_status() for bt, br in self.breakers.items()},
            "any_breaker_open": self.is_any_breaker_open(),
        }

    def register_callback(
        self, breaker_type: BreakerType, callback: Callable[[BreakerEvent], Any]
    ) -> None:
        """Register a coroutine or function to receive breaker events."""
        self.callbacks[breaker_type].append(callback)

    # ------------------------ Setup & monitoring ------------------------

    def _setup_breakers(self) -> None:
        """Instantiate all circuit breakers from config."""
        # Spread circuit breaker
        spread_config = BreakerConfig(
            threshold=float(self.config.scalp.max_spread_bps),
            window_seconds=60,
            min_triggers=3,
            timeout_seconds=300,
        )
        self.breakers[BreakerType.SPREAD] = CircuitBreaker(
            "spread", BreakerType.SPREAD, spread_config, self._spread_callback
        )

        # Latency circuit breaker
        latency_config = BreakerConfig(
            threshold=float(getattr(self.config.risk.circuit_breakers, "latency_ms_max", 500)),
            window_seconds=30,
            min_triggers=2,
            timeout_seconds=180,
        )
        self.breakers[BreakerType.LATENCY] = CircuitBreaker(
            "latency", BreakerType.LATENCY, latency_config, self._latency_callback
        )

        # Loss circuit breaker (config is a negative fraction like -0.02 → use +2.0%)
        loss_pct_threshold = abs(float(self.config.risk.daily_stop_loss)) * 100.0
        loss_config = BreakerConfig(
            threshold=loss_pct_threshold,
            window_seconds=300,
            min_triggers=1,
            timeout_seconds=3600,
        )
        self.breakers[BreakerType.LOSS] = CircuitBreaker(
            "loss", BreakerType.LOSS, loss_config, self._loss_callback
        )

        # Frequency circuit breaker
        frequency_config = BreakerConfig(
            threshold=float(self.config.scalp.max_trades_per_minute),
            window_seconds=60,
            min_triggers=2,
            timeout_seconds=600,
        )
        self.breakers[BreakerType.FREQUENCY] = CircuitBreaker(
            "frequency", BreakerType.FREQUENCY, frequency_config, self._frequency_callback
        )

        # API error circuit breaker (percentage)
        api_error_config = BreakerConfig(
            threshold=10.0,  # 10% error rate
            window_seconds=120,
            min_triggers=5,
            timeout_seconds=900,
        )
        self.breakers[BreakerType.API_ERROR] = CircuitBreaker(
            "api_error", BreakerType.API_ERROR, api_error_config, self._api_error_callback
        )

    async def _setup_monitoring(self) -> None:
        """Subscribe to feeds that can trip breakers."""
        try:
            await self.redis_bus.subscribe(
                f"market:spread:{self.agent_id}", self._handle_spread_data
            )
            await self.redis_bus.subscribe(
                f"system:latency:{self.agent_id}", self._handle_latency_data
            )
            # You can add API error-rate channel subscription here if you emit one.
        except Exception as e:
            self.logger.error(f"Error setting up monitoring: {e}", exc_info=True)

    async def _health_check_loop(self) -> None:
        """Periodic health check loop."""
        while True:
            try:
                await self._perform_health_check()
                # Optional: publish summarized status for dashboards
                await self.redis_bus.publish(
                    f"system:circuit_status:{self.agent_id}",
                    self.get_system_status(),
                )
                await asyncio.sleep(30)  # every 30s
            except Exception as e:
                self.logger.error(f"Error in health check loop: {e}", exc_info=True)
                await asyncio.sleep(60)

    async def _perform_health_check(self) -> None:
        """Lightweight hook for custom checks; extend as needed."""
        # Example: if any breaker has triggered > N times in last hour, consider escalating
        # (left minimal to avoid changing behavior)
        return

    async def _auto_resume(self, delay_seconds: int) -> None:
        """Automatically resume system after delay."""
        await asyncio.sleep(max(0, int(delay_seconds)))
        if self.system_halted:
            await self.resume_system()

    # ------------------------ Breaker callbacks ------------------------

    async def _spread_callback(self, breaker: CircuitBreaker, event: BreakerEvent) -> None:
        self.logger.warning(
            f"Spread breaker triggered: {event.trigger_value:.2f} bps (>{event.threshold_value:.2f})"
        )
        for cb in self.callbacks[BreakerType.SPREAD]:
            try:
                if inspect.iscoroutinefunction(cb):
                    await cb(event)
                else:
                    cb(event)
            except Exception as e:
                self.logger.error(f"Error in spread callback: {e}", exc_info=True)

    async def _latency_callback(self, breaker: CircuitBreaker, event: BreakerEvent) -> None:
        self.logger.warning(
            f"Latency breaker triggered: {event.trigger_value:.1f} ms (>{event.threshold_value:.1f})"
        )
        for cb in self.callbacks[BreakerType.LATENCY]:
            try:
                if inspect.iscoroutinefunction(cb):
                    await cb(event)
                else:
                    cb(event)
            except Exception as e:
                self.logger.error(f"Error in latency callback: {e}", exc_info=True)

    async def _loss_callback(self, breaker: CircuitBreaker, event: BreakerEvent) -> None:
        self.logger.critical(
            f"Loss breaker triggered: {event.trigger_value:.2f}% (>{event.threshold_value:.2f}%)"
        )
        # Loss breaker halts the system for 1h by default
        await self.halt_system(f"Daily loss limit exceeded: {event.trigger_value:.2f}%", 3600)
        for cb in self.callbacks[BreakerType.LOSS]:
            try:
                if inspect.iscoroutinefunction(cb):
                    await cb(event)
                else:
                    cb(event)
            except Exception as e:
                self.logger.error(f"Error in loss callback: {e}", exc_info=True)

    async def _frequency_callback(self, breaker: CircuitBreaker, event: BreakerEvent) -> None:
        self.logger.warning(
            f"Frequency breaker triggered: {event.trigger_value:.1f} trades/min (>{event.threshold_value:.1f})"
        )
        for cb in self.callbacks[BreakerType.FREQUENCY]:
            try:
                if inspect.iscoroutinefunction(cb):
                    await cb(event)
                else:
                    cb(event)
            except Exception as e:
                self.logger.error(f"Error in frequency callback: {e}", exc_info=True)

    async def _api_error_callback(self, breaker: CircuitBreaker, event: BreakerEvent) -> None:
        self.logger.error(
            f"API error breaker triggered: {event.trigger_value:.1f}% (>{event.threshold_value:.1f}%)"
        )
        for cb in self.callbacks[BreakerType.API_ERROR]:
            try:
                if inspect.iscoroutinefunction(cb):
                    await cb(event)
                else:
                    cb(event)
            except Exception as e:
                self.logger.error(f"Error in API error callback: {e}", exc_info=True)

    # ------------------------ Data handlers ------------------------

    async def _handle_spread_data(self, data: Dict[str, Any]) -> None:
        """Handle incoming spread data."""
        try:
            spread_bps = float(data.get("spread_bps", 0.0))
            await self.check_spread(spread_bps)
        except Exception as e:
            self.logger.error(f"Error handling spread data: {e}", exc_info=True)

    async def _handle_latency_data(self, data: Dict[str, Any]) -> None:
        """Handle incoming latency data."""
        try:
            latency_ms = float(data.get("latency_ms", 0.0))
            await self.check_latency(latency_ms)
        except Exception as e:
            self.logger.error(f"Error handling latency data: {e}", exc_info=True)
