"""
Protection monitors for wiring external signals to circuit breakers.

This module provides trackers that monitor system health and trigger circuit breakers:
- API error streak tracking
- Latency P95 monitoring
- Loss streak integration with agents/risk

Key principles:
- Wire triggers, don't duplicate logic
- Integrate with agents/risk for decisions
- Maintain rolling windows for metrics
- Trigger circuit breakers on threshold breaches

Usage:
    from agents.scalper.protections.monitors import (
        APIErrorTracker, LatencyMonitor, LossStreakIntegrator
    )

    # Initialize monitors
    api_tracker = APIErrorTracker(circuit_breaker_manager)
    latency_monitor = LatencyMonitor(circuit_breaker_manager)
    loss_integrator = LossStreakIntegrator(
        circuit_breaker_manager,
        drawdown_protector
    )

    # Record events
    await api_tracker.record_call(success=True)
    await latency_monitor.record_latency(latency_ms=125.5)
    await loss_integrator.on_trade_close(pnl_after_fees=-10.0, ...)
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional, Tuple

from agents.risk.drawdown_protector import DrawdownProtector, FillEvent, SnapshotEvent

from .circuit_breakers import BreakerType, CircuitBreakerManager

logger = logging.getLogger(__name__)


# ======================== Data Models ========================


@dataclass
class APICallRecord:
    """Record of API call outcome"""

    timestamp: float
    success: bool
    error_type: Optional[str] = None
    latency_ms: Optional[float] = None


# ======================== API Error Tracker ========================


class APIErrorTracker:
    """
    Track API errors and trigger circuit breaker on error streak.

    Monitors:
    - Error rate over sliding window (last 2 minutes)
    - Consecutive error streaks
    - Error types and patterns

    Triggers circuit breaker when:
    - Error rate > threshold (e.g., 10%)
    - Consecutive errors > threshold (e.g., 5)
    - Specific error types (e.g., RateLimitError)
    """

    def __init__(
        self,
        breaker_manager: CircuitBreakerManager,
        window_seconds: int = 120,
        max_error_rate_pct: float = 10.0,
        consecutive_error_threshold: int = 5,
    ):
        """
        Initialize API error tracker.

        Args:
            breaker_manager: Circuit breaker manager to trigger
            window_seconds: Time window for error rate calculation
            max_error_rate_pct: Maximum acceptable error rate percentage
            consecutive_error_threshold: Max consecutive errors before triggering
        """
        self.breaker_manager = breaker_manager
        self.window_seconds = window_seconds
        self.max_error_rate_pct = max_error_rate_pct
        self.consecutive_error_threshold = consecutive_error_threshold

        # Rolling window of API calls
        self.call_history: Deque[APICallRecord] = deque(maxlen=1000)
        self.consecutive_errors = 0

        # Counters
        self.total_calls = 0
        self.total_errors = 0

        logger.info(
            f"APIErrorTracker initialized: window={window_seconds}s, "
            f"max_error_rate={max_error_rate_pct}%"
        )

    async def record_call(
        self,
        success: bool,
        error_type: Optional[str] = None,
        latency_ms: Optional[float] = None,
    ) -> None:
        """
        Record API call outcome.

        Args:
            success: Whether call succeeded
            error_type: Error type if failed (e.g., "RateLimitError")
            latency_ms: Call latency in milliseconds

        Example:
            >>> await tracker.record_call(success=False, error_type="RateLimitError")
        """
        now = time.time()

        # Record call
        record = APICallRecord(
            timestamp=now,
            success=success,
            error_type=error_type,
            latency_ms=latency_ms,
        )
        self.call_history.append(record)

        self.total_calls += 1
        if not success:
            self.total_errors += 1
            self.consecutive_errors += 1
        else:
            self.consecutive_errors = 0

        # Check triggers
        await self._check_error_rate(now)
        await self._check_consecutive_errors()

        # Check for critical errors
        if error_type in {"RateLimitError", "AuthenticationError"}:
            await self._handle_critical_error(error_type)

    async def _check_error_rate(self, current_time: float) -> None:
        """Check if error rate exceeds threshold"""
        # Clean old records
        cutoff = current_time - self.window_seconds
        recent_calls = [r for r in self.call_history if r.timestamp >= cutoff]

        if len(recent_calls) < 10:  # Min calls before checking
            return

        # Calculate error rate
        errors = sum(1 for r in recent_calls if not r.success)
        error_rate_pct = (errors / len(recent_calls)) * 100.0

        # Trigger circuit breaker if rate exceeded
        if error_rate_pct > self.max_error_rate_pct:
            logger.warning(
                f"API error rate high: {error_rate_pct:.1f}% "
                f"({errors}/{len(recent_calls)} errors in {self.window_seconds}s)"
            )
            await self.breaker_manager.check_api_errors(error_rate_pct)

    async def _check_consecutive_errors(self) -> None:
        """Check if consecutive errors exceed threshold"""
        if self.consecutive_errors >= self.consecutive_error_threshold:
            logger.error(
                f"Consecutive error threshold breached: {self.consecutive_errors} errors"
            )
            # Force open API error breaker
            if BreakerType.API_ERROR in self.breaker_manager.breakers:
                await self.breaker_manager.breakers[BreakerType.API_ERROR].force_open(
                    f"Consecutive error streak: {self.consecutive_errors}",
                    duration_seconds=300,  # 5 min cooldown
                )

    async def _handle_critical_error(self, error_type: str) -> None:
        """Handle critical error types that require immediate action"""
        if error_type == "RateLimitError":
            logger.critical(f"Rate limit error detected - forcing breaker open")
            # Longer cooldown for rate limits
            if BreakerType.API_ERROR in self.breaker_manager.breakers:
                await self.breaker_manager.breakers[BreakerType.API_ERROR].force_open(
                    "Rate limit error",
                    duration_seconds=900,  # 15 min cooldown
                )
        elif error_type == "AuthenticationError":
            logger.critical(f"Authentication error - halting system")
            await self.breaker_manager.halt_system(
                "Authentication failure",
                duration_seconds=3600,  # 1 hour halt
            )

    def get_stats(self) -> dict:
        """Get current error tracking statistics"""
        now = time.time()
        cutoff = now - self.window_seconds
        recent_calls = [r for r in self.call_history if r.timestamp >= cutoff]

        if not recent_calls:
            return {
                "total_calls": self.total_calls,
                "total_errors": self.total_errors,
                "window_calls": 0,
                "window_errors": 0,
                "error_rate_pct": 0.0,
                "consecutive_errors": self.consecutive_errors,
            }

        window_errors = sum(1 for r in recent_calls if not r.success)
        error_rate = (window_errors / len(recent_calls)) * 100.0

        return {
            "total_calls": self.total_calls,
            "total_errors": self.total_errors,
            "window_calls": len(recent_calls),
            "window_errors": window_errors,
            "error_rate_pct": error_rate,
            "consecutive_errors": self.consecutive_errors,
        }


# ======================== Latency Monitor ========================


class LatencyMonitor:
    """
    Monitor API latency and trigger breaker on P95 breach.

    Calculates percentile latencies over rolling window and triggers
    circuit breaker when P95 exceeds threshold.

    Triggers circuit breaker when:
    - P95 latency > threshold (e.g., 500ms)
    - P99 latency > critical threshold (e.g., 1000ms)
    """

    def __init__(
        self,
        breaker_manager: CircuitBreakerManager,
        p95_threshold_ms: float = 500.0,
        p99_threshold_ms: float = 1000.0,
        window_size: int = 100,
    ):
        """
        Initialize latency monitor.

        Args:
            breaker_manager: Circuit breaker manager to trigger
            p95_threshold_ms: P95 latency threshold in milliseconds
            p99_threshold_ms: P99 latency threshold in milliseconds
            window_size: Number of samples to keep for percentile calculation
        """
        self.breaker_manager = breaker_manager
        self.p95_threshold_ms = p95_threshold_ms
        self.p99_threshold_ms = p99_threshold_ms
        self.window_size = window_size

        # Rolling window of latency samples
        self.latency_samples: Deque[float] = deque(maxlen=window_size)

        logger.info(
            f"LatencyMonitor initialized: p95_threshold={p95_threshold_ms}ms, "
            f"p99_threshold={p99_threshold_ms}ms"
        )

    async def record_latency(self, latency_ms: float) -> None:
        """
        Record API call latency.

        Args:
            latency_ms: Latency in milliseconds

        Example:
            >>> await monitor.record_latency(latency_ms=125.5)
        """
        self.latency_samples.append(latency_ms)

        # Check thresholds once we have enough samples
        if len(self.latency_samples) >= min(20, self.window_size // 2):
            await self._check_percentiles()

    async def _check_percentiles(self) -> None:
        """Calculate percentiles and check thresholds"""
        p95 = self._calculate_percentile(95)
        p99 = self._calculate_percentile(99)

        # P99 critical breach - immediate halt
        if p99 > self.p99_threshold_ms:
            logger.critical(
                f"P99 latency critical: {p99:.1f}ms > {self.p99_threshold_ms}ms"
            )
            await self.breaker_manager.halt_system(
                f"P99 latency critical: {p99:.1f}ms",
                duration_seconds=600,  # 10 min halt
            )

        # P95 warning breach - trigger latency breaker
        elif p95 > self.p95_threshold_ms:
            logger.warning(
                f"P95 latency high: {p95:.1f}ms > {self.p95_threshold_ms}ms"
            )
            await self.breaker_manager.check_latency(p95)

    def _calculate_percentile(self, percentile: int) -> float:
        """
        Calculate percentile from samples.

        Args:
            percentile: Percentile to calculate (0-100)

        Returns:
            Percentile value in milliseconds
        """
        if not self.latency_samples:
            return 0.0

        sorted_samples = sorted(self.latency_samples)
        index = int(len(sorted_samples) * percentile / 100.0)
        index = min(index, len(sorted_samples) - 1)
        return sorted_samples[index]

    def get_stats(self) -> dict:
        """Get current latency statistics"""
        if not self.latency_samples:
            return {
                "count": 0,
                "mean": 0.0,
                "p50": 0.0,
                "p95": 0.0,
                "p99": 0.0,
                "max": 0.0,
            }

        sorted_samples = sorted(self.latency_samples)
        return {
            "count": len(sorted_samples),
            "mean": sum(sorted_samples) / len(sorted_samples),
            "p50": sorted_samples[len(sorted_samples) // 2],
            "p95": self._calculate_percentile(95),
            "p99": self._calculate_percentile(99),
            "max": sorted_samples[-1],
        }


# ======================== Loss Streak Integrator ========================


class LossStreakIntegrator:
    """
    Bridge between agents/risk drawdown protector and circuit breakers.

    Integrates loss streak detection from agents/risk/drawdown_protector with
    circuit breaker system. Avoids duplicating loss tracking logic.

    Flow:
    1. Trade closes → ingest into DrawdownProtector (agents/risk)
    2. DrawdownProtector updates loss streaks and drawdown state
    3. Check decision from DrawdownProtector
    4. Trigger circuit breakers if needed
    """

    def __init__(
        self,
        breaker_manager: CircuitBreakerManager,
        drawdown_protector: DrawdownProtector,
    ):
        """
        Initialize loss streak integrator.

        Args:
            breaker_manager: Circuit breaker manager to trigger
            drawdown_protector: Drawdown protector from agents/risk
        """
        self.breaker_manager = breaker_manager
        self.drawdown_protector = drawdown_protector

        logger.info("LossStreakIntegrator initialized")

    async def on_trade_close(
        self,
        pnl_after_fees: float,
        strategy: str,
        symbol: str,
        timestamp: Optional[int] = None,
    ) -> None:
        """
        Process trade close through integrated systems.

        Args:
            pnl_after_fees: Trade P&L after fees
            strategy: Strategy identifier
            symbol: Trading symbol
            timestamp: Optional timestamp (defaults to current time)

        Example:
            >>> await integrator.on_trade_close(
            ...     pnl_after_fees=-10.0,
            ...     strategy="scalper",
            ...     symbol="BTC/USD"
            ... )
        """
        ts_s = timestamp or int(time.time())

        # 1. Update agents/risk drawdown protector
        self.drawdown_protector.ingest_fill(
            FillEvent(
                ts_s=ts_s,
                pnl_after_fees=pnl_after_fees,
                strategy=strategy,
                symbol=symbol,
                won=pnl_after_fees > 0,
            )
        )

        # 2. Check decision from drawdown protector
        decision = self.drawdown_protector.assess_can_open(strategy, symbol)

        # 3. Trigger circuit breakers based on decision
        if decision.halt_all:
            # Hard halt - stop all trading
            logger.critical(
                f"Loss streak hard halt triggered: {decision.reason} "
                f"(strategy={strategy}, symbol={symbol})"
            )
            await self.breaker_manager.halt_system(
                f"Loss streak hard halt: {decision.reason}",
                duration_seconds=1800,  # 30 min halt
            )

        elif decision.reduce_only:
            # Soft stop - only allow position reduction
            logger.warning(
                f"Loss streak soft stop triggered: {decision.reason} "
                f"(strategy={strategy}, symbol={symbol})"
            )
            # Force open loss breaker with soft stop
            if BreakerType.LOSS in self.breaker_manager.breakers:
                await self.breaker_manager.breakers[BreakerType.LOSS].force_open(
                    f"Soft stop: {decision.reason}",
                    duration_seconds=600,  # 10 min cooldown
                )

        # 4. Also check loss percentage for circuit breaker
        if pnl_after_fees < 0:
            # Calculate loss percentage (rough estimate)
            loss_pct = abs(pnl_after_fees) / 100.0  # Normalize to percentage
            await self.breaker_manager.check_loss(loss_pct)

    async def on_equity_snapshot(
        self,
        equity_current: float,
        equity_start_of_day: float,
        strategy_equity: Optional[dict] = None,
        symbol_equity: Optional[dict] = None,
        timestamp: Optional[int] = None,
    ) -> None:
        """
        Process equity snapshot through drawdown protector.

        Args:
            equity_current: Current total equity
            equity_start_of_day: Starting equity for the day
            strategy_equity: Optional per-strategy equity breakdown
            symbol_equity: Optional per-symbol equity breakdown
            timestamp: Optional timestamp (defaults to current time)

        Example:
            >>> await integrator.on_equity_snapshot(
            ...     equity_current=9950.0,
            ...     equity_start_of_day=10000.0
            ... )
        """
        ts_s = timestamp or int(time.time())

        # Update agents/risk drawdown protector with snapshot
        self.drawdown_protector.ingest_snapshot(
            SnapshotEvent(
                ts_s=ts_s,
                equity_start_of_day_usd=equity_start_of_day,
                equity_current_usd=equity_current,
                strategy_equity_usd=strategy_equity,
                symbol_equity_usd=symbol_equity,
            )
        )

    def get_drawdown_state(self) -> dict:
        """Get current drawdown protection state"""
        state = self.drawdown_protector.current_state()
        return {
            "portfolio": {
                "mode": state.portfolio.mode,
                "loss_streak": state.portfolio.loss_streak,
                "dd_daily_pct": state.portfolio.dd_daily_pct,
                "dd_rolling_pct": state.portfolio.dd_rolling_pct,
                "size_multiplier": state.portfolio.size_multiplier,
            },
            "strategies": {
                strat: {
                    "mode": s.mode,
                    "loss_streak": s.loss_streak,
                }
                for strat, s in state.per_strategy.items()
            },
            "symbols": {
                sym: {
                    "mode": s.mode,
                    "loss_streak": s.loss_streak,
                }
                for sym, s in state.per_symbol.items()
            },
        }


# ======================== Export ========================

__all__ = [
    "APIErrorTracker",
    "LatencyMonitor",
    "LossStreakIntegrator",
    "APICallRecord",
]
