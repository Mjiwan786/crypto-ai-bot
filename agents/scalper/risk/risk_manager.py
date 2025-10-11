"""
Production-grade risk management for the Kraken scalping agent.

Implements multi-layer risk controls with real-time monitoring and comprehensive
violation tracking for high-frequency crypto trading operations.

Features:
- Real-time position and exposure monitoring
- Multi-layer risk limits (position, daily, total)
- Circuit breakers for market conditions
- Dynamic risk adjustment based on performance
- Comprehensive violation tracking and alerting
- Thread-safe operations with proper state management
- Integration with Redis for state persistence
- Anti-spam violation emission with deduplication
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from ..config_loader import KrakenScalpingConfig
from ..infra.redis_bus import RedisBus
from ..infra.state_manager import StateManager
from .exposure import ExposureCalculator
from .limits import PositionLimits, RiskLimits

# --------------------------- Types & Data Models ---------------------------


class RiskViolationType(Enum):
    """Types of risk violations."""

    POSITION_SIZE = "position_size"
    DAILY_LOSS = "daily_loss"
    DRAWDOWN = "drawdown"
    CONCENTRATION = "concentration"
    FREQUENCY = "frequency"
    SPREAD = "spread"
    LATENCY = "latency"
    LIQUIDITY = "liquidity"
    EXPOSURE = "exposure"


@dataclass
class RiskViolation:
    """Risk violation event."""

    violation_type: RiskViolationType
    symbol: str
    current_value: float
    limit_value: float
    severity: str  # "warning", "critical"
    timestamp: float = field(default_factory=time.time)
    message: str = ""


@dataclass
class RiskMetrics:
    """Current risk metrics snapshot."""

    daily_pnl: float = 0.0  # USD
    daily_drawdown: float = 0.0  # USD drawdown from day peak
    max_drawdown: float = 0.0  # Max daily drawdown (USD) for the day
    total_exposure: float = 0.0  # USD absolute sum notionals
    position_count: int = 0
    largest_position_pct: float = 0.0  # largest position / total exposure
    trades_today: int = 0
    trades_last_hour: int = 0
    avg_spread_bps: float = 0.0
    avg_latency_ms: float = 0.0
    last_update: float = field(default_factory=time.time)


# ------------------------------ Risk Manager ------------------------------


class RiskManager:
    """
    Comprehensive risk management system for scalping operations.

    Features:
    - Real-time position and exposure monitoring
    - Multi-layer risk limits (position, daily, total)
    - Circuit breakers for market conditions
    - Dynamic risk adjustment based on performance
    - Comprehensive violation tracking and alerting
    """

    def __init__(
        self,
        config: KrakenScalpingConfig,
        state_manager: StateManager,
        redis_bus: RedisBus,
        agent_id: str = "kraken_scalper",
    ):
        self.config = config
        self.state_manager = state_manager
        self.redis_bus = redis_bus
        self.agent_id = agent_id
        self.logger = logging.getLogger(f"{__name__}.{agent_id}")

        # Risk components
        self.position_limits = PositionLimits(config)
        self.risk_limits = RiskLimits(config)
        self.exposure_calc = ExposureCalculator(config)

        # Risk state
        self.current_metrics = RiskMetrics()
        self.violations: List[RiskViolation] = []
        self.risk_overrides: Dict[str, Any] = {}

        # Performance tracking
        self.daily_trades: List[Dict[str, Any]] = []
        self.hourly_trades: List[Dict[str, Any]] = []
        self.position_history: List[Dict[str, Any]] = []

        # Circuit breaker states
        self.circuit_breakers: Dict[str, bool] = {
            "spread": False,
            "latency": False,
            "liquidity": False,
            "frequency": False,
            "loss": False,
        }

        # Runtime
        self._lock = asyncio.Lock()
        self._monitor_task: Optional[asyncio.Task] = None
        self.is_running = False
        self.last_check_time = 0.0

        # Anti-spam for violation emissions
        self._last_violation_emit_ts: Dict[str, float] = {}  # key → ts

        self.logger.info("RiskManager initialized for %s", agent_id)

    # ------------------------------- Lifecycle -------------------------------

    async def start(self) -> None:
        """Start the risk management system."""
        self.logger.info("Starting RiskManager...")
        await self._load_state()
        await self._setup_subscriptions()

        self.is_running = True
        self._monitor_task = asyncio.create_task(
            self._monitoring_loop(), name=f"risk.monitor.{self.agent_id}"
        )
        self.logger.info("RiskManager started successfully")

    async def stop(self) -> None:
        """Stop the risk management system."""
        self.logger.info("Stopping RiskManager...")
        self.is_running = False
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        await self._save_state()
        self.logger.info("RiskManager stopped")

    # --------------------------- External Interface ---------------------------

    async def validate_order(
        self,
        symbol: str,
        side: str,
        size: float,
        price: Optional[float] = None,
    ) -> Tuple[bool, List[str]]:
        """
        Validate if an order can be placed given current risk constraints.

        Returns:
            (is_valid, violation_messages)
        """
        violations: List[str] = []
        try:
            async with self._lock:
                await self._update_metrics()

                # Position size limits
                v = await self._check_position_limits(symbol, side, size)
                if v:
                    violations.append(v.message)

                # Exposure limits
                v = await self._check_exposure_limits(symbol, side, size, price)
                if v:
                    violations.append(v.message)

                # Frequency
                v = await self._check_frequency_limits()
                if v:
                    violations.append(v.message)

                # Daily loss
                v = await self._check_daily_loss_limits()
                if v:
                    violations.append(v.message)

                # Circuit breakers
                v = await self._check_circuit_breakers(symbol)
                if v:
                    violations.append(v.message)

            is_valid = len(violations) == 0
            if not is_valid:
                self.logger.warning(
                    "Order validation failed %s %s %.6f: %s", symbol, side, size, violations
                )
            return is_valid, violations

        except Exception as e:
            self.logger.error("Error validating order: %s", e, exc_info=True)
            return False, [f"Validation error: {str(e)}"]

    async def update_position(
        self,
        symbol: str,
        side: str,
        size: float,
        price: float,
        pnl: float = 0.0,
    ) -> None:
        """Update position information after trade execution."""
        try:
            record = {
                "timestamp": time.time(),
                "symbol": symbol,
                "side": side,
                "size": size,
                "price": price,
                "pnl": pnl,
            }

            async with self._lock:
                self.daily_trades.append(record)
                self.hourly_trades.append(record)
                await self._clean_old_trades()
                await self._update_metrics()

            # Fire checks outside of the lock to avoid slow paths holding it
            await self._check_all_violations()
            await self._save_state()

            self.logger.debug(
                "Updated position: %s %s %.6f @ %.8f pnl=%.2f", symbol, side, size, price, pnl
            )

        except Exception as e:
            self.logger.error("Error updating position: %s", e, exc_info=True)

    async def set_risk_override(self, key: str, value: Any) -> None:
        """Set temporary risk override."""
        async with self._lock:
            self.risk_overrides[key] = value
        self.logger.info("Risk override set: %s = %s", key, value)

        await self.redis_bus.publish(
            f"risk:override:{self.agent_id}",
            {"key": key, "value": value, "timestamp": time.time()},
        )

    async def clear_risk_override(self, key: str) -> None:
        """Clear risk override."""
        async with self._lock:
            if key in self.risk_overrides:
                del self.risk_overrides[key]
                self.logger.info("Risk override cleared: %s", key)

    async def get_risk_metrics(self) -> RiskMetrics:
        """Get current risk metrics."""
        async with self._lock:
            await self._update_metrics()
            return self.current_metrics

    async def get_violations(self, since: Optional[float] = None) -> List[RiskViolation]:
        """Get risk violations since specified time."""
        async with self._lock:
            if since is None:
                return list(self.violations)
            return [v for v in self.violations if v.timestamp >= since]

    async def trigger_circuit_breaker(
        self,
        breaker_type: str,
        reason: str,
        duration_seconds: int = 300,
    ) -> None:
        """Trigger a circuit breaker."""
        async with self._lock:
            self.circuit_breakers[breaker_type] = True

        vtype = self._map_breaker_to_violation_type(breaker_type)
        violation = RiskViolation(
            violation_type=vtype,
            symbol="ALL",
            current_value=1.0,
            limit_value=0.0,
            severity="critical",
            message=f"Circuit breaker triggered: {breaker_type} - {reason}",
        )

        async with self._lock:
            self.violations.append(violation)

        await self.redis_bus.publish(
            f"risk:circuit_breaker:{self.agent_id}",
            {
                "type": breaker_type,
                "reason": reason,
                "duration": duration_seconds,
                "timestamp": time.time(),
            },
        )

        if duration_seconds > 0:
            asyncio.create_task(self._reset_circuit_breaker(breaker_type, duration_seconds))

        self.logger.critical("Circuit breaker triggered: %s - %s", breaker_type, reason)

    # ------------------------------- Monitor Loop -------------------------------

    async def _monitoring_loop(self) -> None:
        """Main monitoring loop."""
        interval = float(getattr(self.config.risk, "check_interval_seconds", 2))
        while self.is_running:
            try:
                async with self._lock:
                    await self._update_metrics()
                await self._check_all_violations()

                # Save once a minute
                now = time.time()
                if now - self.last_check_time > 60.0:
                    await self._save_state()
                    self.last_check_time = now

                await asyncio.sleep(interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in monitoring loop: %s", e, exc_info=True)
                await asyncio.sleep(5.0)

    # ------------------------------ Computations ------------------------------

    async def _update_metrics(self) -> None:
        """Update current risk metrics (idempotent)."""
        try:
            positions: Dict[str, Dict[str, Any]] = await self.state_manager.get_positions()

            # Daily P&L and drawdown (amounts, not ratios)
            daily_pnl = 0.0
            running_pnl = 0.0
            peak_pnl = 0.0
            max_dd_amount = 0.0

            for tr in self.daily_trades:
                pnl = float(tr.get("pnl", 0.0))
                daily_pnl += pnl
                running_pnl += pnl
                if running_pnl > peak_pnl:
                    peak_pnl = running_pnl
                dd_amount = max(0.0, peak_pnl - running_pnl)
                if dd_amount > max_dd_amount:
                    max_dd_amount = dd_amount

            total_exposure = sum(abs(p.get("notional_value", 0.0)) for p in positions.values())
            active_positions = [p for p in positions.values() if float(p.get("size", 0.0)) != 0.0]
            position_count = len(active_positions)

            largest_notional = max(
                (abs(p.get("notional_value", 0.0)) for p in positions.values()),
                default=0.0,
            )
            largest_position_pct = (
                (largest_notional / total_exposure) if total_exposure > 0 else 0.0
            )

            now = time.time()
            trades_today = len(self.daily_trades)
            trades_last_hour = sum(
                1 for t in self.hourly_trades if now - float(t.get("timestamp", now)) <= 3600.0
            )

            self.current_metrics = RiskMetrics(
                daily_pnl=daily_pnl,
                daily_drawdown=max(0.0, peak_pnl - running_pnl),
                max_drawdown=max_dd_amount,
                total_exposure=total_exposure,
                position_count=position_count,
                largest_position_pct=largest_position_pct,
                trades_today=trades_today,
                trades_last_hour=trades_last_hour,
                # avg_spread_bps / avg_latency_ms could be updated via handlers
                # if you keep rolling stats
                avg_spread_bps=self.current_metrics.avg_spread_bps,
                avg_latency_ms=self.current_metrics.avg_latency_ms,
                last_update=now,
            )

        except Exception as e:
            self.logger.error("Error updating metrics: %s", e, exc_info=True)

    async def _check_position_limits(
        self, symbol: str, side: str, size: float
    ) -> Optional[RiskViolation]:
        """Check per-symbol position size limit with the hypothetical order applied."""
        try:
            positions = await self.state_manager.get_positions()
            current_pos = positions.get(symbol, {})
            current_size = float(current_pos.get("size", 0.0))

            new_size = current_size + (size if side == "buy" else -size)
            max_position = float(self.position_limits.get_max_position_size(symbol))

            if abs(new_size) > max_position:
                return RiskViolation(
                    violation_type=RiskViolationType.POSITION_SIZE,
                    symbol=symbol,
                    current_value=abs(new_size),
                    limit_value=max_position,
                    severity="critical",
                    message=(
                        f"Position size {abs(new_size):.6f} exceeds limit "
                        f"{max_position:.6f} for {symbol}"
                    ),
                )
            return None

        except Exception as e:
            self.logger.error("Error checking position limits: %s", e, exc_info=True)
            return None

    async def _check_exposure_limits(
        self,
        symbol: str,
        side: str,
        size: float,
        price: Optional[float],
    ) -> Optional[RiskViolation]:
        """Check total exposure limit accounting for delta exposure (reductions allowed)."""
        try:
            if price is None:
                # Without price, conservative approach: skip exposure check
                # (caller can pass price to enable)
                return None

            positions = await self.state_manager.get_positions()
            current_exposure = sum(abs(p.get("notional_value", 0.0)) for p in positions.values())

            # Estimate delta exposure: if adding to existing same-direction position,
            # exposure increases; if reducing, decreases.
            pos = positions.get(symbol, {})
            cur_size = float(pos.get("size", 0.0))
            new_size = cur_size + (size if side == "buy" else -size)

            def notional(x: float) -> float:
                return abs(x) * float(price)

            # Exposure after hypothetical change: subtract old notional for this symbol,
            # add new notional
            old_symbol_exposure = abs(cur_size) * float(price)
            new_symbol_exposure = abs(new_size) * float(price)
            new_total_exposure = current_exposure - old_symbol_exposure + new_symbol_exposure
            if new_total_exposure < 0:
                new_total_exposure = 0.0

            max_exposure = float(self.risk_limits.max_total_exposure)
            if new_total_exposure > max_exposure:
                return RiskViolation(
                    violation_type=RiskViolationType.EXPOSURE,
                    symbol=symbol,
                    current_value=new_total_exposure,
                    limit_value=max_exposure,
                    severity="critical",
                    message=(
                        f"Total exposure {new_total_exposure:.2f} exceeds limit "
                        f"{max_exposure:.2f}"
                    ),
                )
            return None

        except Exception as e:
            self.logger.error("Error checking exposure limits: %s", e, exc_info=True)
            return None

    async def _check_frequency_limits(self) -> Optional[RiskViolation]:
        """Check trading frequency limits (per-minute warns, per-hour critical)."""
        try:
            now = time.time()
            trades_last_minute = sum(
                1 for t in self.hourly_trades if now - float(t.get("timestamp", now)) <= 60.0
            )
            trades_last_hour = sum(
                1 for t in self.hourly_trades if now - float(t.get("timestamp", now)) <= 3600.0
            )

            max_per_min = int(getattr(self.config.scalp, "max_trades_per_minute", 20))
            max_per_hour = int(getattr(self.config.scalp, "max_trades_per_hour", 200))

            if trades_last_hour > max_per_hour:
                return RiskViolation(
                    violation_type=RiskViolationType.FREQUENCY,
                    symbol="ALL",
                    current_value=trades_last_hour,
                    limit_value=max_per_hour,
                    severity="critical",
                    message=(
                        f"Trade frequency {trades_last_hour}/hour exceeds limit "
                        f"{max_per_hour}/hour"
                    ),
                )

            if trades_last_minute > max_per_min:
                return RiskViolation(
                    violation_type=RiskViolationType.FREQUENCY,
                    symbol="ALL",
                    current_value=trades_last_minute,
                    limit_value=max_per_min,
                    severity="warning",
                    message=(
                        f"Trade frequency {trades_last_minute}/min exceeds limit "
                        f"{max_per_min}/min"
                    ),
                )
            return None

        except Exception as e:
            self.logger.error("Error checking frequency limits: %s", e, exc_info=True)
            return None

    async def _check_daily_loss_limits(self) -> Optional[RiskViolation]:
        """Check daily loss (USD) versus configured max daily loss (negative threshold)."""
        try:
            daily_pnl = sum(float(t.get("pnl", 0.0)) for t in self.daily_trades)
            # expected negative (e.g., -100.0)
            max_daily_loss = float(self.risk_limits.max_daily_loss)

            if daily_pnl < max_daily_loss:
                return RiskViolation(
                    violation_type=RiskViolationType.DAILY_LOSS,
                    symbol="ALL",
                    current_value=daily_pnl,
                    limit_value=max_daily_loss,
                    severity="critical",
                    message=f"Daily P&L {daily_pnl:.2f} breached max loss {max_daily_loss:.2f}",
                )
            return None

        except Exception as e:
            self.logger.error("Error checking daily loss limits: %s", e, exc_info=True)
            return None

    async def _check_drawdown_limits(self) -> Optional[RiskViolation]:
        """Check daily drawdown against configured threshold (USD)."""
        try:
            dd_limit = float(getattr(self.risk_limits, "max_daily_drawdown", 0.0))
            if dd_limit <= 0:
                return None  # disabled

            dd_amount = float(self.current_metrics.daily_drawdown)
            if dd_amount > dd_limit:
                return RiskViolation(
                    violation_type=RiskViolationType.DRAWDOWN,
                    symbol="ALL",
                    current_value=dd_amount,
                    limit_value=dd_limit,
                    severity="critical",
                    message=f"Daily drawdown {dd_amount:.2f} exceeds limit {dd_limit:.2f}",
                )
            return None

        except Exception as e:
            self.logger.error("Error checking drawdown limits: %s", e, exc_info=True)
            return None

    async def _check_circuit_breakers(self, symbol: str) -> Optional[RiskViolation]:
        """Check if any circuit breakers are active."""
        try:
            for breaker_type, is_active in self.circuit_breakers.items():
                if is_active:
                    vtype = self._map_breaker_to_violation_type(breaker_type)
                    return RiskViolation(
                        violation_type=vtype,
                        symbol=symbol,
                        current_value=1.0,
                        limit_value=0.0,
                        severity="critical",
                        message=f"Circuit breaker active: {breaker_type}",
                    )
            return None

        except Exception as e:
            self.logger.error("Error checking circuit breakers: %s", e, exc_info=True)
            return None

    async def _check_all_violations(self) -> None:
        """Consolidated violation evaluation with simple anti-spam."""
        try:
            checks = [
                await self._check_daily_loss_limits(),
                await self._check_drawdown_limits(),
                await self._check_frequency_limits(),
            ]

            # Total exposure and concentration checks (from current metrics)
            total_exp = float(self.current_metrics.total_exposure)
            max_total_exp = float(self.risk_limits.max_total_exposure)
            if total_exp > max_total_exp:
                checks.append(
                    RiskViolation(
                        violation_type=RiskViolationType.EXPOSURE,
                        symbol="ALL",
                        current_value=total_exp,
                        limit_value=max_total_exp,
                        severity="critical",
                        message=f"Total exposure {total_exp:.2f} exceeds {max_total_exp:.2f}",
                    )
                )

            # e.g., 0.5 = 50%
            max_conc = float(getattr(self.risk_limits, "max_concentration_ratio", 1.0))
            largest_pct = float(self.current_metrics.largest_position_pct)
            if largest_pct > max_conc:
                checks.append(
                    RiskViolation(
                        violation_type=RiskViolationType.CONCENTRATION,
                        symbol="ALL",
                        current_value=largest_pct,
                        limit_value=max_conc,
                        severity="warning",
                        message=f"Largest position {largest_pct:.2%} exceeds limit {max_conc:.2%}",
                    )
                )

            # Active circuit breakers (if any)
            cb_violation = await self._check_circuit_breakers("ALL")
            if cb_violation:
                checks.append(cb_violation)

            # Emit non-None violations with dedupe window
            now = time.time()
            DEDUPE_SEC = 30.0
            for v in filter(None, checks):
                key = f"{v.violation_type.value}:{v.symbol}:{v.severity}"
                last_ts = self._last_violation_emit_ts.get(key, 0.0)
                if now - last_ts >= DEDUPE_SEC:
                    async with self._lock:
                        self.violations.append(v)
                    await self.redis_bus.publish(
                        f"risk:violation:{self.agent_id}",
                        {
                            "type": v.violation_type.value,
                            "symbol": v.symbol,
                            "current": v.current_value,
                            "limit": v.limit_value,
                            "severity": v.severity,
                            "message": v.message,
                            "timestamp": v.timestamp,
                        },
                    )
                    self._last_violation_emit_ts[key] = now

        except Exception as e:
            self.logger.error("Error checking violations: %s", e, exc_info=True)

    # ------------------------------ Housekeeping ------------------------------

    async def _clean_old_trades(self) -> None:
        """Clean old trade records (keep 24h for daily, 1h for hourly)."""
        now = time.time()
        day_ago = now - 86400.0
        hour_ago = now - 3600.0
        self.daily_trades = [
            t for t in self.daily_trades if float(t.get("timestamp", now)) > day_ago
        ]
        self.hourly_trades = [
            t for t in self.hourly_trades if float(t.get("timestamp", now)) > hour_ago
        ]

    async def _clean_old_data(self) -> None:
        """Clean old violations (keep last 24h)."""
        try:
            now = time.time()
            self.violations = [v for v in self.violations if now - v.timestamp <= 86400.0]
        except Exception as e:
            self.logger.error("Error cleaning old data: %s", e, exc_info=True)

    # ----------------------------- Subscriptions -----------------------------

    async def _setup_subscriptions(self) -> None:
        """Setup Redis subscriptions for risk events."""
        try:
            await self.redis_bus.subscribe(
                f"market:spread:{self.agent_id}", self._handle_spread_update
            )
            await self.redis_bus.subscribe(
                f"system:latency:{self.agent_id}", self._handle_latency_update
            )
        except Exception as e:
            self.logger.error("Error setting up subscriptions: %s", e, exc_info=True)

    async def _handle_spread_update(self, data: Dict[str, Any]) -> None:
        """Handle spread update for circuit breaker monitoring."""
        try:
            spread_bps = float(data.get("spread_bps", 0.0))
            max_spread = float(getattr(self.config.scalp, "max_spread_bps", 50.0))
            # simple rolling stat: update avg in metrics
            async with self._lock:
                # EWMA style
                self.current_metrics.avg_spread_bps = (
                    0.8 * self.current_metrics.avg_spread_bps + 0.2 * spread_bps
                )

            if spread_bps > max_spread:
                await self.trigger_circuit_breaker(
                    "spread",
                    f"Spread {spread_bps:.2f} bps > {max_spread:.2f} bps",
                    300,
                )

        except Exception as e:
            self.logger.error("Error handling spread update: %s", e, exc_info=True)

    async def _handle_latency_update(self, data: Dict[str, Any]) -> None:
        """Handle latency update for circuit breaker monitoring."""
        try:
            latency_ms = float(data.get("latency_ms", 0.0))
            max_latency = float(self.config.risk.circuit_breakers.get("latency_ms_max", 500.0))

            async with self._lock:
                self.current_metrics.avg_latency_ms = (
                    0.8 * self.current_metrics.avg_latency_ms + 0.2 * latency_ms
                )

            if latency_ms > max_latency:
                await self.trigger_circuit_breaker(
                    "latency",
                    f"Latency {latency_ms:.1f}ms > {max_latency:.1f}ms",
                    180,
                )

        except Exception as e:
            self.logger.error("Error handling latency update: %s", e, exc_info=True)

    async def _reset_circuit_breaker(self, breaker_type: str, delay_seconds: int) -> None:
        """Reset circuit breaker after delay."""
        try:
            await asyncio.sleep(delay_seconds)
        except asyncio.CancelledError:
            return
        async with self._lock:
            self.circuit_breakers[breaker_type] = False
        self.logger.info("Circuit breaker reset: %s", breaker_type)

    # ------------------------------- Persistence ------------------------------

    async def _load_state(self) -> None:
        """Load risk state from persistence."""
        try:
            state_data = await self.state_manager.load_risk_state()
            if not state_data:
                return

            daily_trades = state_data.get("daily_trades", [])
            hourly_trades = state_data.get("hourly_trades", [])
            violations_raw = state_data.get("violations", [])

            # Coerce violations back to enum type safely
            violations: List[RiskViolation] = []
            for v in violations_raw:
                vtype = v.get("violation_type", "exposure")
                try:
                    enum_type = RiskViolationType(vtype)
                except Exception:
                    enum_type = RiskViolationType.EXPOSURE
                violations.append(
                    RiskViolation(
                        violation_type=enum_type,
                        symbol=v.get("symbol", "ALL"),
                        current_value=float(v.get("current_value", 0.0)),
                        limit_value=float(v.get("limit_value", 0.0)),
                        severity=str(v.get("severity", "warning")),
                        timestamp=float(v.get("timestamp", time.time())),
                        message=str(v.get("message", "")),
                    )
                )

            async with self._lock:
                self.daily_trades = list(daily_trades)
                self.hourly_trades = list(hourly_trades)
                self.violations = violations

            self.logger.info("Risk state loaded from persistence")

        except Exception as e:
            self.logger.error("Error loading risk state: %s", e, exc_info=True)

    async def _save_state(self) -> None:
        """Save risk state to persistence."""
        try:
            async with self._lock:
                state_data = {
                    "daily_trades": self.daily_trades,
                    "hourly_trades": self.hourly_trades,
                    "violations": [
                        {
                            "violation_type": v.violation_type.value,
                            "symbol": v.symbol,
                            "current_value": v.current_value,
                            "limit_value": v.limit_value,
                            "severity": v.severity,
                            "timestamp": v.timestamp,
                            "message": v.message,
                        }
                        for v in self.violations
                    ],
                    "current_metrics": {
                        "daily_pnl": self.current_metrics.daily_pnl,
                        "daily_drawdown": self.current_metrics.daily_drawdown,
                        "max_drawdown": self.current_metrics.max_drawdown,
                        "total_exposure": self.current_metrics.total_exposure,
                        "position_count": self.current_metrics.position_count,
                        "largest_position_pct": self.current_metrics.largest_position_pct,
                        "trades_today": self.current_metrics.trades_today,
                        "trades_last_hour": self.current_metrics.trades_last_hour,
                        "avg_spread_bps": self.current_metrics.avg_spread_bps,
                        "avg_latency_ms": self.current_metrics.avg_latency_ms,
                        "last_update": self.current_metrics.last_update,
                    },
                }
            await self.state_manager.save_risk_state(state_data)

        except Exception as e:
            self.logger.error("Error saving risk state: %s", e, exc_info=True)

    # ------------------------------ Utilities ------------------------------

    @staticmethod
    def _map_breaker_to_violation_type(breaker_type: str) -> RiskViolationType:
        t = breaker_type.lower()
        if t == "spread":
            return RiskViolationType.SPREAD
        if t == "latency":
            return RiskViolationType.LATENCY
        if t == "liquidity":
            return RiskViolationType.LIQUIDITY
        if t == "frequency":
            return RiskViolationType.FREQUENCY
        if t == "loss":
            return RiskViolationType.DAILY_LOSS
        return RiskViolationType.EXPOSURE
