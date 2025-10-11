# base/trading_agent.py
"""
Abstract base class for all trading agents in the crypto-ai-bot system.
Provides core infrastructure for agent lifecycle, health monitoring, metrics,
and integration with the MCP system and Redis messaging bus.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union
from dataclasses import dataclass, field
from enum import Enum
from random import random

import psutil
from pydantic import BaseModel, Field, ConfigDict

# Internal imports
from mcp.schemas import MetricsTick
from utils.logger import get_logger
from config.loader import get_config


# --------------------------
# Agent enums and dataclasses
# --------------------------
class AgentState(str, Enum):
    CREATED = "created"
    INITIALIZING = "initializing"
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"
    SHUTTING_DOWN = "shutting_down"
    STOPPED = "stopped"


class AgentType(str, Enum):
    DATA_PROVIDER = "data_provider"
    STRATEGY = "strategy"
    EXECUTION = "execution"
    RISK_MANAGEMENT = "risk_management"
    PORTFOLIO = "portfolio"
    MONITORING = "monitoring"
    AI_ENGINE = "ai_engine"


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    CRITICAL = "critical"


@dataclass
class AgentMetrics:
    """Core agent performance metrics"""
    # Timing metrics
    uptime_seconds: float = 0.0
    last_heartbeat: float = 0.0
    avg_processing_time_ms: float = 0.0

    # Processing metrics
    messages_processed: int = 0
    messages_failed: int = 0
    errors_last_hour: int = 0  # can be maintained by external rolling window

    # Resource metrics
    memory_usage_mb: float = 0.0
    cpu_usage_percent: float = 0.0

    # Agent-specific metrics (override in subclasses)
    custom_metrics: Dict[str, Union[int, float, str]] = field(default_factory=dict)


class AgentConfig(BaseModel):
    """Base agent configuration (Pydantic v2)"""
    model_config = ConfigDict(use_enum_values=True, extra="ignore", frozen=False)

    agent_id: str
    agent_type: AgentType
    enabled: bool = True
    priority: int = 5  # 1=highest, 10=lowest

    # Resource limits
    max_memory_mb: int = 1024
    max_cpu_percent: float = 80.0

    # Health checks
    health_check_interval_seconds: int = 30
    heartbeat_timeout_seconds: int = 60
    max_consecutive_failures: int = 3

    # Retry/backoff
    retry_delays: List[float] = Field(default_factory=lambda: [1.0, 2.0, 4.0, 8.0])
    max_retry_attempts: int = 3
    jitter_fraction: float = 0.2  # +/-20% jitter

    # Logging
    log_level: str = "INFO"
    structured_logging: bool = True


# --------------------------
# TradingAgent base class
# --------------------------
class TradingAgent(ABC):
    """
    Abstract base class for all trading agents.

    Provides:
    - Lifecycle management (startup, shutdown, health checks)
    - Metrics collection and reporting
    - Error handling and retry logic
    - Integration hooks for MCP/Redis
    - Health monitoring and alerting
    """

    def __init__(
        self,
        agent_id: str,
        agent_type: AgentType = AgentType.STRATEGY,
        config: Optional[AgentConfig] = None,
    ):
        self.agent_id = agent_id
        self.agent_type = agent_type
        self.instance_id = str(uuid.uuid4())[:8]

        # State & health
        self.state = AgentState.CREATED
        self.health_status = HealthStatus.HEALTHY
        self._t0 = time.time()
        self.last_error: Optional[Exception] = None
        self.consecutive_failures = 0

        # Configuration
        self.config = config or AgentConfig(agent_id=agent_id, agent_type=agent_type)

        # Metrics & tasks
        self.metrics = AgentMetrics()
        self._update_metrics_task: Optional[asyncio.Task] = None
        self._health_check_task: Optional[asyncio.Task] = None
        self._tasks: List[asyncio.Task] = []

        # Message handling
        self.message_handlers: Dict[str, Callable[[Dict[str, Any]], Awaitable[None]]] = {}
        self.error_handlers: Dict[str, Callable[[str, Exception], Awaitable[None]]] = {}

        # Shutdown coordination
        self._shutdown_event = asyncio.Event()

        # Logger
        self.logger = get_logger(f"agent.{self.agent_id}")
        try:
            self.logger.setLevel(getattr(logging, self.config.log_level.upper()))
        except Exception:
            self.logger.setLevel(logging.INFO)

        # Global config (optional dependency)
        try:
            self.global_config = get_config()
        except Exception:  # keep agent robust if global config loader fails
            self.global_config = {}

        self.logger.info(
            f"Agent {self.agent_id} ({self.agent_type.value}) initialized (instance={self.instance_id})"
        )

    # ---- Abstracts (must implement) ----
    @abstractmethod
    async def startup(self) -> bool:
        """Initialize the agent and start processing. Return True if successful."""
        raise NotImplementedError

    @abstractmethod
    async def shutdown(self) -> None:
        """Gracefully shutdown the agent. Clean up resources, save state, cancel tasks."""
        raise NotImplementedError

    @abstractmethod
    async def get_health_status(self) -> Dict[str, Any]:
        """Return detailed health status for monitoring."""
        raise NotImplementedError

    # ---- Optional: override in subclasses ----
    async def get_metrics(self) -> MetricsTick:
        """Return MCP MetricsTick; override for agent-specific metrics."""
        return MetricsTick(
            pnl={"realized": 0.0, "unrealized": 0.0, "fees": 0.0},
            slippage_bps_p50=0.0,
            latency_ms_p95=self.metrics.avg_processing_time_ms,
            win_rate_1h=0.0,
            drawdown_daily=0.0,
            errors_rate=self._calculate_error_rate(),
        )

    async def handle_message(self, message_type: str, data: Dict[str, Any]) -> None:
        """Dispatch incoming messages to a registered async handler."""
        handler = self.message_handlers.get(message_type)
        if not handler:
            self.logger.debug(f"No handler for message type: {message_type}")
            return
        t0 = time.perf_counter()
        try:
            await handler(data)
            self._record_success()
        except Exception as e:
            await self._handle_error(f"Message handler error ({message_type}): {e}", e)
        finally:
            dt_ms = (time.perf_counter() - t0) * 1000.0
            # simple EMA for average processing time
            self.metrics.avg_processing_time_ms = (
                0.9 * self.metrics.avg_processing_time_ms + 0.1 * dt_ms
                if self.metrics.avg_processing_time_ms > 0.0
                else dt_ms
            )

    async def pause(self) -> None:
        if self.state == AgentState.ACTIVE:
            self.state = AgentState.PAUSED
            self.logger.info(f"Agent {self.agent_id} paused")

    async def resume(self) -> None:
        if self.state == AgentState.PAUSED:
            self.state = AgentState.ACTIVE
            self.logger.info(f"Agent {self.agent_id} resumed")

    # ---- Lifecycle orchestration ----
    async def start(self) -> bool:
        """Start the agent with lifecycle management."""
        try:
            self.logger.info(f"Starting agent {self.agent_id}")
            self.state = AgentState.INITIALIZING

            ok = await self.startup()
            if not ok:
                self.state = AgentState.ERROR
                self.logger.error(f"Agent {self.agent_id} startup failed")
                return False

            self.state = AgentState.ACTIVE
            await self._start_background_tasks()
            self.logger.info(f"Agent {self.agent_id} started successfully")
            return True

        except Exception as e:
            self.state = AgentState.ERROR
            await self._handle_error(f"Agent startup error: {e}", e)
            return False

    async def stop(self) -> None:
        """Stop the agent and clean up."""
        self.logger.info(f"Stopping agent {self.agent_id}")
        self.state = AgentState.SHUTTING_DOWN
        self._shutdown_event.set()

        # Cancel background tasks
        for task in list(self._tasks):
            if task and not task.done():
                task.cancel()
        # Drain cancellations
        for task in list(self._tasks):
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                self.logger.warning(f"Error during task cleanup: {e}")

        try:
            await self.shutdown()
        except Exception as e:
            await self._handle_error(f"Agent shutdown error: {e}", e)

        self.state = AgentState.STOPPED
        self.logger.info(f"Agent {self.agent_id} stopped")

    async def _start_background_tasks(self) -> None:
        """Kick off background metric & health loops."""
        self._update_metrics_task = asyncio.create_task(self._metrics_update_loop(), name=f"{self.agent_id}.metrics")
        self._health_check_task = asyncio.create_task(self._health_check_loop(), name=f"{self.agent_id}.health")
        self._tasks.extend([self._update_metrics_task, self._health_check_task])

    # ---- Background loops ----
    async def _metrics_update_loop(self) -> None:
        """Periodically update resource & heartbeat metrics."""
        while not self._shutdown_event.is_set():
            try:
                await self._update_metrics()
                await asyncio.sleep(10)  # every 10s
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Metrics update error: {e}")
                # soft backoff on error
                await asyncio.sleep(30)

    async def _health_check_loop(self) -> None:
        """Periodically compute health status and guardrails."""
        interval = max(5, int(self.config.health_check_interval_seconds))
        while not self._shutdown_event.is_set():
            try:
                await self._perform_health_check()
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Health check error: {e}")
                await asyncio.sleep(max(30, interval))

    # ---- Metrics & Health ----
    async def _update_metrics(self) -> None:
        """Update core metrics: uptime, heartbeat, RSS, CPU."""
        now = time.time()
        self.metrics.uptime_seconds = now - self._t0
        self.metrics.last_heartbeat = now

        try:
            proc = psutil.Process(os.getpid())
            self.metrics.memory_usage_mb = proc.memory_info().rss / (1024 * 1024)
            # psutil cpu_percent is the change since last call; call with interval=0 for non-blocking snapshot
            self.metrics.cpu_usage_percent = proc.cpu_percent(interval=0.0)
        except Exception as e:
            self.logger.debug(f"Failed to update resource metrics: {e}")

    async def _perform_health_check(self) -> None:
        """Aggregate agent-specific health data and apply thresholds."""
        try:
            _ = await self.get_health_status()  # subclasses may log/validate

            degraded = False
            if self.metrics.memory_usage_mb > self.config.max_memory_mb:
                degraded = True
                self.logger.warning(
                    f"High memory usage: {self.metrics.memory_usage_mb:.1f}MB "
                    f"(limit {self.config.max_memory_mb}MB)"
                )
            if self.metrics.cpu_usage_percent > self.config.max_cpu_percent:
                degraded = True
                self.logger.warning(
                    f"High CPU usage: {self.metrics.cpu_usage_percent:.1f}% "
                    f"(limit {self.config.max_cpu_percent}%)"
                )

            err_rate = self._calculate_error_rate()
            if err_rate > 0.10:
                self.health_status = HealthStatus.UNHEALTHY
            elif self.consecutive_failures >= self.config.max_consecutive_failures:
                self.health_status = HealthStatus.CRITICAL
            elif degraded or err_rate > 0.05:
                self.health_status = HealthStatus.DEGRADED
            else:
                self.health_status = HealthStatus.HEALTHY

            if self.health_status in (HealthStatus.UNHEALTHY, HealthStatus.CRITICAL):
                self.logger.error(
                    f"Agent {self.agent_id} health={self.health_status.value} "
                    f"(error_rate={err_rate:.2%}, failures={self.consecutive_failures})"
                )

        except Exception as e:
            self.health_status = HealthStatus.UNHEALTHY
            await self._handle_error(f"Health check failed: {e}", e)

    # ---- Error handling / retry ----
    async def _handle_error(self, message: str, exception: Exception) -> None:
        """Centralized error handling and circuit breaking."""
        self.last_error = exception
        self.consecutive_failures += 1
        self.metrics.messages_failed += 1
        self.metrics.errors_last_hour += 1

        self.logger.error(
            f"{message} (consecutive_failures={self.consecutive_failures})",
            extra={
                "agent_id": self.agent_id,
                "instance_id": self.instance_id,
                "error_type": type(exception).__name__,
                "consecutive_failures": self.consecutive_failures,
            },
            exc_info=exception,
        )

        if self.consecutive_failures >= self.config.max_consecutive_failures:
            await self._trigger_circuit_breaker(message, exception)

        for name, handler in list(self.error_handlers.items()):
            try:
                await handler(message, exception)
            except Exception as handler_err:
                self.logger.error(f"Error handler '{name}' failed: {handler_err}")

    async def _trigger_circuit_breaker(self, message: str, exception: Exception) -> None:
        """Pause the agent on repeated failures; hook for alerting."""
        self.logger.critical(f"Circuit breaker triggered for {self.agent_id}: {message}")
        await self.pause()
        # hook: emit alerts/metrics if desired

    def _record_success(self) -> None:
        self.consecutive_failures = 0
        self.metrics.messages_processed += 1

    def _calculate_error_rate(self) -> float:
        total = self.metrics.messages_processed + self.metrics.messages_failed
        return (self.metrics.messages_failed / total) if total > 0 else 0.0

    # ---- Utilities ----
    def register_message_handler(self, message_type: str, handler: Callable[[Dict[str, Any]], Awaitable[None]]) -> None:
        """Register an async handler for a message type."""
        self.message_handlers[message_type] = handler
        self.logger.debug(f"Registered handler for message type: {message_type}")

    def register_error_handler(self, name: str, handler: Callable[[str, Exception], Awaitable[None]]) -> None:
        """Register an async error handler callback."""
        self.error_handlers[name] = handler
        self.logger.debug(f"Registered error handler: {name}")

    async def execute_with_retry(
        self,
        operation: Union[Callable[..., Any], Awaitable[Any]],
        *args: Any,
        operation_name: str = "operation",
        **kwargs: Any,
    ) -> Any:
        """
        Execute an operation with bounded retries and jitter.
        Supports:
          - async function (call → await)
          - coroutine object (await directly)
          - sync function (call directly)
        """
        for attempt in range(self.config.max_retry_attempts + 1):
            try:
                if asyncio.iscoroutine(operation):
                    result = await operation
                elif asyncio.iscoroutinefunction(operation):
                    result = await operation(*args, **kwargs)
                else:
                    result = operation(*args, **kwargs)

                if attempt > 0:
                    self.logger.info(f"{operation_name} succeeded on attempt {attempt + 1}")
                self._record_success()
                return result

            except Exception as e:
                if attempt >= self.config.max_retry_attempts:
                    await self._handle_error(
                        f"{operation_name} failed after {attempt + 1} attempts", e
                    )
                    raise

                base_delay = self.config.retry_delays[min(attempt, len(self.config.retry_delays) - 1)]
                jitter = 1.0 + (self.config.jitter_fraction * (2 * random() - 1))  # +/- jitter_fraction
                delay = max(0.05, base_delay * jitter)

                self.logger.warning(
                    f"{operation_name} attempt {attempt + 1} failed: {e}. Retrying in {delay:.2f}s"
                )
                try:
                    await asyncio.sleep(delay)
                except asyncio.CancelledError:
                    # If stopping/shutting down, bubble up
                    raise

    def get_agent_info(self) -> Dict[str, Any]:
        """Return comprehensive agent info for diagnostics."""
        return {
            "agent_id": self.agent_id,
            "agent_type": self.agent_type.value,
            "instance_id": self.instance_id,
            "state": self.state.value,
            "health_status": self.health_status.value,
            "uptime_seconds": self.metrics.uptime_seconds,
            "start_time": datetime.fromtimestamp(self._t0, tz=timezone.utc).isoformat(),
            "messages_processed": self.metrics.messages_processed,
            "messages_failed": self.metrics.messages_failed,
            "consecutive_failures": self.consecutive_failures,
            "error_rate": self._calculate_error_rate(),
            "memory_usage_mb": self.metrics.memory_usage_mb,
            "cpu_usage_percent": self.metrics.cpu_usage_percent,
            "last_error": str(self.last_error) if self.last_error else None,
            "config": self.config.model_dump(),
        }

    def __str__(self) -> str:
        return f"{self.__class__.__name__}({self.agent_id})"

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"agent_id='{self.agent_id}', "
            f"state={self.state.value}, "
            f"health={self.health_status.value})"
        )


# --------------------------
# Specialized base classes
# --------------------------
class DataProviderAgent(TradingAgent):
    def __init__(self, agent_id: str, **kwargs: Any):
        super().__init__(agent_id, AgentType.DATA_PROVIDER, **kwargs)


class StrategyAgent(TradingAgent):
    def __init__(self, agent_id: str, **kwargs: Any):
        super().__init__(agent_id, AgentType.STRATEGY, **kwargs)


class ExecutionAgent(TradingAgent):
    def __init__(self, agent_id: str, **kwargs: Any):
        super().__init__(agent_id, AgentType.EXECUTION, **kwargs)


class RiskManagementAgent(TradingAgent):
    def __init__(self, agent_id: str, **kwargs: Any):
        super().__init__(agent_id, AgentType.RISK_MANAGEMENT, **kwargs)


class PortfolioAgent(TradingAgent):
    def __init__(self, agent_id: str, **kwargs: Any):
        super().__init__(agent_id, AgentType.PORTFOLIO, **kwargs)


class MonitoringAgent(TradingAgent):
    def __init__(self, agent_id: str, **kwargs: Any):
        super().__init__(agent_id, AgentType.MONITORING, **kwargs)


class AIEngineAgent(TradingAgent):
    def __init__(self, agent_id: str, **kwargs: Any):
        super().__init__(agent_id, AgentType.AI_ENGINE, **kwargs)
