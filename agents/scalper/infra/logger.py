"""
Advanced logging infrastructure for high-frequency scalping operations.

Provides structured logging, performance tracking, and audit trails with
comprehensive features for production trading systems.

Features:
- Structured JSON logging with context correlation
- Performance tracking and metrics collection
- Audit trail for compliance and debugging
- Async-safe logging via queue-based architecture
- Custom log levels for trading operations
- Log filtering and sampling capabilities
- Rotating file handlers with configurable retention
- Thread-safe operations with proper resource cleanup

This module provides the core logging infrastructure for the scalping system,
enabling comprehensive observability and debugging capabilities.
"""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import sys
import threading
import time
import traceback
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.core.log_keys import (
    K_ACTION_TAKEN,
    K_BREACH_AMOUNT,
    K_CATEGORY,
    K_COMPONENT,
    K_CONFIG,
    K_CURRENT_VALUE,
    K_DURATION_MS,
    K_EVENT_TYPE,
    K_LIMIT,
    K_NOTIONAL,
    K_OPERATION,
    K_ORDER_ID,
    K_PAIR,
    K_PRICE,
    K_RISK_DATA,
    K_RISK_TYPE,
    K_SIDE,
    K_SIZE,
    K_SYSTEM_DATA,
    K_TIMESTAMP_MS,
    K_TRADE_DATA,
    K_VERSION,
)

# Setup module logger
logger = logging.getLogger(__name__)

# =========================
# Custom levels and enums
# =========================


class LogLevel(Enum):
    """Custom log levels for trading operations"""

    TRACE = 5
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    CRITICAL = 50
    TRADE = 25  # Custom level for trade events
    PERFORMANCE = 15  # Custom level for performance metrics


class LogCategory(Enum):
    """Log categories for filtering and analysis"""

    SYSTEM = "system"
    TRADING = "trading"
    MARKET_DATA = "market_data"
    EXECUTION = "execution"
    RISK = "risk"
    PERFORMANCE = "performance"
    HEALTH = "health"
    AUDIT = "audit"
    DEBUG = "debug"


@dataclass
class LogContext:
    """Log context for correlation and tracing"""

    request_id: Optional[str] = None
    session_id: Optional[str] = None
    trade_id: Optional[str] = None
    strategy: Optional[str] = None
    pair: Optional[str] = None
    component: Optional[str] = None

    def to_dict(self) -> Dict[str, str]:
        try:
            return {k: v for k, v in asdict(self).items() if v is not None}
        except Exception:
            return {}


# Context variables for thread-/task-local storage
log_context: ContextVar[LogContext] = ContextVar("log_context", default=LogContext())


# =========================
# Structured JSON formatter
# =========================


class StructuredFormatter(logging.Formatter):
    """JSON formatter for structured logging"""

    _EXCLUDE_KEYS = {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "getMessage",
    }

    def __init__(self, include_context: bool = True):
        super().__init__()
        self.include_context = include_context

    def format(self, record: logging.LogRecord) -> str:
        # Base entry
        log_entry: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Context, if any
        if self.include_context:
            try:
                ctx = log_context.get()
                if ctx:
                    log_entry["context"] = ctx.to_dict()
            except Exception:
                pass

        # Extra fields (anything extra put into record.__dict__)
        for key, value in record.__dict__.items():
            if key not in self._EXCLUDE_KEYS:
                # Do not overwrite keys we've already set
                if key in log_entry:
                    key = f"extra_{key}"
                log_entry[key] = value

        # Exception info
        if record.exc_info:
            try:
                etype = record.exc_info[0].__name__ if record.exc_info[0] else None
                emsg = str(record.exc_info[1]) if record.exc_info[1] else None
                etb = traceback.format_exception(*record.exc_info)
            except Exception:
                etype, emsg, etb = None, None, None
            log_entry["exception"] = {"type": etype, "message": emsg, "traceback": etb}

        # Ensure JSON serializable
        return json.dumps(log_entry, default=str)


# =========================
# Performance tracker
# =========================


class PerformanceTracker:
    """Track performance metrics for logging"""

    def __init__(self):
        self.metrics: Dict[str, Dict[str, Any]] = {}
        self.lock = threading.Lock()

    def track_execution_time(self, operation: str, duration_ms: float):
        with self.lock:
            metric = self.metrics.setdefault(
                operation,
                {
                    "count": 0,
                    "total_time": 0.0,
                    "min_time": float("inf"),
                    "max_time": 0.0,
                    "recent_times": [],  # last N for percentiles
                },
            )
            metric["count"] += 1
            metric["total_time"] += duration_ms
            metric["min_time"] = min(metric["min_time"], duration_ms)
            metric["max_time"] = max(metric["max_time"], duration_ms)
            metric["recent_times"].append(duration_ms)
            if len(metric["recent_times"]) > 200:  # keep a bit more history
                metric["recent_times"].pop(0)

    @staticmethod
    def _percentile(sorted_vals: List[float], pct: float) -> float:
        if not sorted_vals:
            return 0.0
        n = len(sorted_vals)
        # nearest-rank method with bounds
        idx = max(0, min(n - 1, int(round((pct / 100.0) * (n - 1)))))
        return sorted_vals[idx]

    def get_stats(self, operation: str) -> Dict[str, float]:
        with self.lock:
            if operation not in self.metrics:
                return {}
            m = self.metrics[operation]
            count = max(1, m["count"])
            stats = {
                "count": m["count"],
                "avg_time_ms": m["total_time"] / count,
                "min_time_ms": 0.0 if m["min_time"] == float("inf") else m["min_time"],
                "max_time_ms": m["max_time"],
            }
            if m["recent_times"]:
                s = sorted(m["recent_times"])
                stats["p50_time_ms"] = self._percentile(s, 50)
                stats["p95_time_ms"] = self._percentile(s, 95)
                stats["p99_time_ms"] = self._percentile(s, 99)
            return stats


# =========================
# Audit logger
# =========================


class AuditLogger:
    """Separate audit logger for compliance and debugging"""

    def __init__(self, audit_file: Path):
        self.logger = logging.getLogger("audit")
        self.logger.setLevel(logging.INFO)
        self._handler_path = audit_file
        self._handler: Optional[RotatingFileHandler] = None
        self._ensure_handler()

    def _ensure_handler(self):
        # Avoid duplicate handlers on reconfigure
        # Remove existing audit handlers we created
        for h in list(self.logger.handlers):
            if isinstance(h, RotatingFileHandler) and getattr(h, "_is_scalper_audit", False):
                self.logger.removeHandler(h)
                try:
                    h.close()
                except Exception:
                    pass

        handler = RotatingFileHandler(
            str(self._handler_path), maxBytes=100 * 1024 * 1024, backupCount=10  # 100MB
        )
        handler._is_scalper_audit = True  # mark ours
        handler.setFormatter(StructuredFormatter(include_context=True))
        self.logger.addHandler(handler)
        self.logger.propagate = False
        self._handler = handler

    def log_trade_event(self, event_type: str, trade_data: Dict[str, Any]):
        """Log trading events for audit trail"""
        self.logger.info(
            f"Trade event: {event_type}",
            extra={
                K_CATEGORY: LogCategory.AUDIT.value,
                K_EVENT_TYPE: event_type,
                K_TRADE_DATA: trade_data,
                K_TIMESTAMP_MS: int(time.time() * 1000),
            },
        )

    def log_risk_event(self, event_type: str, risk_data: Dict[str, Any]):
        """Log risk management events"""
        self.logger.warning(
            f"Risk event: {event_type}",
            extra={
                K_CATEGORY: LogCategory.AUDIT.value,
                K_EVENT_TYPE: event_type,
                K_RISK_DATA: risk_data,
                K_TIMESTAMP_MS: int(time.time() * 1000),
            },
        )

    def log_system_event(self, event_type: str, system_data: Dict[str, Any]):
        """Log system events"""
        self.logger.info(
            f"System event: {event_type}",
            extra={
                K_CATEGORY: LogCategory.AUDIT.value,
                K_EVENT_TYPE: event_type,
                K_SYSTEM_DATA: system_data,
                K_TIMESTAMP_MS: int(time.time() * 1000),
            },
        )


# =========================
# Logger singleton
# =========================


class ScalperLogger:
    """
    Main logger class for scalping operations.

    Features:
    - Structured JSON logging
    - Performance tracking
    - Context correlation
    - Async-safe logging via queue
    - Audit trail
    - Log filtering and sampling
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return

        self._initialized = True
        self.performance_tracker = PerformanceTracker()
        # Placeholder; set in configure()
        self.audit_logger: Optional[AuditLogger] = None

        self.loggers: Dict[str, logging.Logger] = {}
        self.queue_listener: Optional[QueueListener] = None
        self._handlers: List[logging.Handler] = []
        self._queue_handler: Optional[QueueHandler] = None
        self._log_queue: Optional[queue.Queue] = None
        self._log_dir: Path = Path("logs")
        self._configured_level = logging.DEBUG

        # Register custom level names and helper methods
        logging.addLevelName(LogLevel.TRACE.value, "TRACE")
        logging.addLevelName(LogLevel.TRADE.value, "TRADE")
        logging.addLevelName(LogLevel.PERFORMANCE.value, "PERFORMANCE")
        self._install_logger_helpers()

        # Default configuration
        self.configure()

    # --- public API ---

    def configure(
        self,
        log_level: str = "INFO",
        enable_console: bool = True,
        enable_files: bool = True,
        log_dir: Optional[str] = "logs",
    ):
        """(Re)configure logging sinks and levels safely."""
        # Stop previous listener & close handlers
        self._teardown_handlers()

        # Level
        self._configured_level = getattr(logging, log_level.upper(), logging.INFO)

        # Directory
        self._log_dir = Path(log_dir or "logs")
        if enable_files:
            self._log_dir.mkdir(parents=True, exist_ok=True)

        # Queue plumbing
        self._log_queue = queue.Queue(-1)
        self._queue_handler = QueueHandler(self._log_queue)

        # Build sinks
        handlers: List[logging.Handler] = []

        if enable_console:
            console = logging.StreamHandler(sys.stdout)
            console.setFormatter(StructuredFormatter())
            console.setLevel(self._configured_level)
            handlers.append(console)

        if enable_files:
            main_file = RotatingFileHandler(
                str(self._log_dir / "scalper.log"), maxBytes=50 * 1024 * 1024, backupCount=10
            )
            main_file.setFormatter(StructuredFormatter())
            main_file.setLevel(self._configured_level)
            handlers.append(main_file)

            err_file = RotatingFileHandler(
                str(self._log_dir / "scalper_errors.log"), maxBytes=10 * 1024 * 1024, backupCount=5
            )
            err_file.setLevel(logging.ERROR)
            err_file.setFormatter(StructuredFormatter())
            handlers.append(err_file)

            perf_file = RotatingFileHandler(
                str(self._log_dir / "scalper_performance.log"),
                maxBytes=20 * 1024 * 1024,
                backupCount=5,
            )
            perf_file.setLevel(LogLevel.PERFORMANCE.value)
            perf_file.setFormatter(StructuredFormatter())
            handlers.append(perf_file)

        # Start listener
        if handlers:
            self.queue_listener = QueueListener(
                self._log_queue, *handlers, respect_handler_level=True
            )
            self.queue_listener.start()
            self._handlers = handlers

        # Attach queue handler to root
        root_logger = logging.getLogger()
        # Clear existing non-queue handlers to avoid double emission
        for h in list(root_logger.handlers):
            root_logger.removeHandler(h)
        if self._queue_handler:
            root_logger.addHandler(self._queue_handler)

        # Set root level
        root_logger.setLevel(self._configured_level)

        # Rebuild audit logger (file in same dir if files enabled)
        audit_path = self._log_dir / "audit.log" if enable_files else Path("audit.log")
        self.audit_logger = AuditLogger(audit_path)

        # Ensure previously created component loggers respect level
        for lg in self.loggers.values():
            lg.setLevel(self._configured_level)

    def get_logger(self, name: str) -> logging.Logger:
        """Get or create a logger with the given name"""
        if name not in self.loggers:
            logger = logging.getLogger(f"scalper.{name}")
            logger.setLevel(self._configured_level)
            # Do not attach handlers directly; use propagate to root queue handler
            logger.propagate = True
            self.loggers[name] = logger
        return self.loggers[name]

    def set_context(self, **kwargs):
        """Set logging context for current thread/task"""
        current_context = log_context.get(LogContext())
        context_dict = asdict(current_context)
        context_dict.update(kwargs)
        log_context.set(LogContext(**context_dict))

    def clear_context(self):
        """Clear logging context"""
        log_context.set(LogContext())

    def log_trade(self, logger_name: str, message: str, **kwargs):
        """Log trade-specific events"""
        logger = self.get_logger(logger_name)
        logger.log(
            LogLevel.TRADE.value, message, extra={K_CATEGORY: LogCategory.TRADING.value, **kwargs}
        )
        if K_TRADE_DATA in kwargs and self.audit_logger:
            self.audit_logger.log_trade_event(message, kwargs[K_TRADE_DATA])

    def log_performance(self, logger_name: str, operation: str, duration_ms: float, **kwargs):
        """Log performance metrics"""
        logger = self.get_logger(logger_name)
        self.performance_tracker.track_execution_time(operation, duration_ms)
        logger.log(
            LogLevel.PERFORMANCE.value,
            f"Performance: {operation} took {duration_ms:.2f}ms",
            extra={
                K_CATEGORY: LogCategory.PERFORMANCE.value,
                K_OPERATION: operation,
                K_DURATION_MS: duration_ms,
                **kwargs,
            },
        )

    def log_market_data(self, logger_name: str, message: str, **kwargs):
        """Log market data events"""
        logger = self.get_logger(logger_name)
        logger.debug(message, extra={K_CATEGORY: LogCategory.MARKET_DATA.value, **kwargs})

    def log_execution(self, logger_name: str, message: str, **kwargs):
        """Log execution events"""
        logger = self.get_logger(logger_name)
        logger.info(message, extra={K_CATEGORY: LogCategory.EXECUTION.value, **kwargs})

    def log_risk(self, logger_name: str, message: str, level: str = "warning", **kwargs):
        """Log risk management events"""
        logger = self.get_logger(logger_name)
        log_level = getattr(logging, level.upper(), logging.WARNING)
        logger.log(log_level, message, extra={K_CATEGORY: LogCategory.RISK.value, **kwargs})
        if log_level >= logging.WARNING and K_RISK_DATA in kwargs and self.audit_logger:
            self.audit_logger.log_risk_event(message, kwargs[K_RISK_DATA])

    def get_performance_stats(self, operation: str = None) -> Dict[str, Any]:
        """Get performance statistics"""
        if operation:
            return self.performance_tracker.get_stats(operation)
        return {
            op: self.performance_tracker.get_stats(op)
            for op in self.performance_tracker.metrics.keys()
        }

    def shutdown(self):
        """Shutdown the logging system cleanly"""
        # Stop listener
        if self.queue_listener:
            try:
                self.queue_listener.stop()
            except Exception:
                pass
            self.queue_listener = None
        # Remove queue handler from root
        root_logger = logging.getLogger()
        if self._queue_handler:
            try:
                root_logger.removeHandler(self._queue_handler)
            except Exception:
                pass
        # Close our handlers
        for h in self._handlers:
            try:
                h.flush()
                h.close()
            except Exception:
                pass
        self._handlers.clear()

    # --- internals ---

    def _teardown_handlers(self):
        """Internal: stop listener and close handlers when reconfiguring."""
        if self.queue_listener:
            try:
                self.queue_listener.stop()
            except Exception:
                pass
            self.queue_listener = None
        for h in self._handlers:
            try:
                h.flush()
                h.close()
            except Exception:
                pass
        self._handlers.clear()

    @staticmethod
    def _install_logger_helpers():
        """Add helper methods for custom levels to logging.Logger."""

        def trace(self: logging.Logger, msg, *args, **kwargs):
            if self.isEnabledFor(LogLevel.TRACE.value):
                self._log(LogLevel.TRACE.value, msg, args, **kwargs)

        def trade(self: logging.Logger, msg, *args, **kwargs):
            if self.isEnabledFor(LogLevel.TRADE.value):
                self._log(LogLevel.TRADE.value, msg, args, **kwargs)

        def performance(self: logging.Logger, msg, *args, **kwargs):
            if self.isEnabledFor(LogLevel.PERFORMANCE.value):
                self._log(LogLevel.PERFORMANCE.value, msg, args, **kwargs)

        if not hasattr(logging.Logger, "trace"):
            logging.Logger.trace = trace  # type: ignore[attr-defined]
        if not hasattr(logging.Logger, "trade"):
            logging.Logger.trade = trade  # type: ignore[attr-defined]
        if not hasattr(logging.Logger, "performance"):
            logging.Logger.performance = performance  # type: ignore[attr-defined]


# =========================
# Context manager & decorator
# =========================


class LogPerformance:
    """Context manager for automatic performance logging"""

    def __init__(self, logger_name: str, operation: str, **kwargs):
        self.logger_name = logger_name
        self.operation = operation
        self.kwargs = kwargs
        self.scalper_logger = ScalperLogger()
        self.start_time = None

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time is not None:
            duration_ms = (time.time() - self.start_time) * 1000.0
            self.scalper_logger.log_performance(
                self.logger_name, self.operation, duration_ms, **self.kwargs
            )


def log_performance(logger_name: str, operation: str = None):
    """Decorator for automatic performance logging"""

    def decorator(func):
        op_name = operation or f"{func.__module__}.{func.__qualname__}"

        if asyncio.iscoroutinefunction(func):

            async def async_wrapper(*args, **kwargs):
                with LogPerformance(logger_name, op_name):
                    return await func(*args, **kwargs)

            return async_wrapper
        else:

            def sync_wrapper(*args, **kwargs):
                with LogPerformance(logger_name, op_name):
                    return func(*args, **kwargs)

            return sync_wrapper

    return decorator


# =========================
# Convenience helpers
# =========================


def setup_scalper_logging(
    log_level: str = "INFO",
    enable_console: bool = True,
    enable_files: bool = True,
    log_dir: Optional[str] = "logs",
) -> ScalperLogger:
    """
    Setup scalper logging with default configuration or reconfigure existing singleton.
    """
    logger = ScalperLogger()
    logger.configure(
        log_level=log_level,
        enable_console=enable_console,
        enable_files=enable_files,
        log_dir=log_dir,
    )
    return logger


def log_trade_execution(
    pair: str, side: str, size: float, price: float, order_id: str = None, **kwargs
):
    """Log trade execution with standard format"""
    logger = ScalperLogger()
    logger.set_context(pair=pair, trade_id=order_id)

    trade_data = {
        K_PAIR: pair,
        K_SIDE: side,
        K_SIZE: size,
        K_PRICE: price,
        K_NOTIONAL: size * price,
        K_ORDER_ID: order_id,
        **kwargs,
    }

    logger.log_trade(
        "execution",
        f"Trade executed: {side.upper()} {size} {pair} @ {price}",
        trade_data=trade_data,
    )


def log_risk_breach(risk_type: str, current_value: float, limit: float, action: str, **kwargs):
    """Log risk limit breach with standard format"""
    logger = ScalperLogger()

    risk_data = {
        K_RISK_TYPE: risk_type,
        K_CURRENT_VALUE: current_value,
        K_LIMIT: limit,
        K_BREACH_AMOUNT: current_value - limit,
        K_ACTION_TAKEN: action,
        **kwargs,
    }

    logger.log_risk(
        "risk_manager",
        f"Risk breach: {risk_type} = {current_value} > {limit}, action: {action}",
        level="error",
        risk_data=risk_data,
    )


def log_system_startup(component: str, version: str = None, config: Dict = None):
    """Log system component startup"""
    logger = ScalperLogger()
    logger.set_context(component=component)

    system_data = {
        K_COMPONENT: component,
        K_VERSION: version,
        "startup_time": datetime.now(timezone.utc).isoformat(),
        K_CONFIG: config or {},
    }

    if logger.audit_logger:
        logger.audit_logger.log_system_event(f"Component startup: {component}", system_data)


# =========================
# Example usage (manual run)
# =========================

if __name__ == "__main__":
    scalper_logger = setup_scalper_logging(
        "DEBUG", enable_console=True, enable_files=True, log_dir="logs"
    )

    execution_logger = scalper_logger.get_logger("execution")
    market_data_logger = scalper_logger.get_logger("market_data")

    scalper_logger.set_context(session_id="session_123", strategy="kraken_scalp", pair="BTC/USD")

    execution_logger.info("Starting execution engine")

    log_trade_execution(
        pair="BTC/USD",
        side="buy",
        size=0.1,
        price=45000.0,
        order_id="order_456",
        strategy="kraken_scalp",
    )

    with LogPerformance("market_data", "process_book_update"):
        time.sleep(0.001)  # Simulate processing

    log_risk_breach(
        risk_type="daily_loss",
        current_value=-0.025,
        limit=-0.02,
        action="halt_trading",
        pair="BTC/USD",
    )

    log_system_startup(
        component="kraken_scalper", version="1.0.0", config={"target_bps": 10, "stop_loss_bps": 5}
    )

    stats = scalper_logger.get_performance_stats("process_book_update")
    logger.info("Performance stats: %s", stats)

    scalper_logger.shutdown()


# =========================
# Simple factory function (unified interface)
# =========================


def get_logger(name: str, level: Optional[str] = None) -> logging.Logger:
    """
    Simple factory function for getting loggers (unified interface).

    This provides a simplified interface compatible with utils.logger.get_logger()
    while using the advanced structured logging infrastructure.

    Args:
        name: Logger name (typically __name__)
        level: Optional level override (DEBUG, INFO, WARNING, ERROR, CRITICAL)

    Returns:
        Configured logger instance with structured JSON logging

    Example:
        ```python
        from agents.scalper.infra.logger import get_logger

        logger = get_logger(__name__)
        logger.info("Application started")

        # With level override
        debug_logger = get_logger(__name__, "DEBUG")
        debug_logger.debug("Detailed debug information")
        ```
    """
    scalper_logger = ScalperLogger()
    logger_instance = scalper_logger.get_logger(name)

    # Apply level override if provided
    if level:
        logger_instance.setLevel(getattr(logging, level.upper(), logging.INFO))

    return logger_instance


__all__ = [
    # Main logger class
    "ScalperLogger",
    "LoggerFactory",  # Alias for compatibility

    # Simple factory (unified interface)
    "get_logger",

    # Setup functions
    "setup_scalper_logging",

    # Structured logging components
    "StructuredFormatter",
    "LogLevel",
    "LogCategory",
    "LogContext",

    # Performance tracking
    "PerformanceTracker",
    "LogPerformance",
    "log_performance",

    # Audit logging
    "AuditLogger",

    # Convenience helpers
    "log_trade_execution",
    "log_risk_breach",
    "log_system_startup",

    # Context management
    "log_context",
]

# Alias for compatibility with utils.logger
LoggerFactory = ScalperLogger
