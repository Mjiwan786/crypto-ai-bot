"""
ExecutionGate - Deterministic Pre-Order Execution Control

The SINGLE CHOKE POINT for all order submission decisions.
This gate must be checked BEFORE any order reaches the exchange API.

Gate checks (in order):
1. EMERGENCY_STOP - blocks all orders immediately
2. LIVE_TRADING_ENABLED - must be true to execute
3. Dependency health - Redis, WebSocket connections
4. Risk limits - position size, daily loss, trade frequency
5. Mode confirmation - MODE=live + LIVE_TRADING_CONFIRMATION

When LIVE_TRADING_ENABLED=false:
- Signals continue to be generated
- Market data continues to be processed
- Orders are logged as "DRY-RUN" but NOT submitted

Usage:
    from protections.execution_gate import ExecutionGate, get_execution_gate

    gate = get_execution_gate()
    gate.log_preflight_status()  # At startup

    # Before EVERY order:
    result = gate.check(order_request)
    if not result.allowed:
        if result.dry_run:
            logger.info("DRY-RUN: would place %s", order_request)
        else:
            raise ExecutionBlocked(result.reason)
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Callable

logger = logging.getLogger(__name__)


# =============================================================================
# GATE RESULT
# =============================================================================

@dataclass
class GateResult:
    """Result of execution gate check."""
    allowed: bool
    reason: Optional[str] = None
    gate_name: Optional[str] = None  # Which gate blocked
    dry_run: bool = False  # True if order should be logged but not executed
    shadow_mode: bool = False  # True if simulating execution


# =============================================================================
# DEPENDENCY HEALTH
# =============================================================================

@dataclass
class DependencyHealth:
    """Health status of execution dependencies."""
    redis_healthy: bool = True
    websocket_healthy: bool = True
    exchange_api_healthy: bool = True
    last_check_time: float = field(default_factory=time.time)

    def all_healthy(self) -> bool:
        return self.redis_healthy and self.websocket_healthy and self.exchange_api_healthy

    def to_dict(self) -> Dict[str, Any]:
        return {
            "redis": self.redis_healthy,
            "websocket": self.websocket_healthy,
            "exchange_api": self.exchange_api_healthy,
            "all_healthy": self.all_healthy(),
        }


# =============================================================================
# EXECUTION GATE
# =============================================================================

class ExecutionGate:
    """
    Deterministic execution gate that controls all order submission.

    This is the SINGLE CHOKE POINT - no order can reach the exchange
    without passing through this gate.
    """

    def __init__(
        self,
        health_checker: Optional[Callable[[], DependencyHealth]] = None,
    ):
        """
        Initialize the execution gate.

        Args:
            health_checker: Optional callback to check dependency health.
                           If not provided, dependencies are assumed healthy.
        """
        self.logger = logging.getLogger(f"{__name__}.ExecutionGate")
        self._health_checker = health_checker
        self._last_health = DependencyHealth()
        self._startup_time = time.time()

        # Load configuration from environment
        self._reload_config()

    def _reload_config(self) -> None:
        """Reload configuration from environment variables."""
        self.live_enabled = os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true"
        self.emergency_stop = os.getenv("EMERGENCY_STOP", "false").lower() == "true"
        self.shadow_mode = os.getenv("SHADOW_EXECUTION", "false").lower() == "true"
        self.mode = os.getenv("MODE", "").strip()
        self.confirmation = os.getenv("LIVE_TRADING_CONFIRMATION", "").strip()

        # Risk limits
        self.max_position_size_usd = float(os.getenv("MAX_POSITION_SIZE_USD", "25"))
        self.max_daily_loss_usd = float(os.getenv("MAX_DAILY_LOSS_USD", "2"))
        self.max_trades_per_day = int(os.getenv("MAX_TRADES_PER_DAY", "8"))
        self.risk_per_trade_pct = float(os.getenv("RISK_PER_TRADE_PCT", "0.5"))
        self.cooldown_seconds = int(os.getenv("COOLDOWN_SECONDS_AFTER_LOSS", "300"))

    def check(
        self,
        position_size_usd: float = 0.0,
        daily_pnl: float = 0.0,
        trades_today: int = 0,
        is_exit: bool = False,
    ) -> GateResult:
        """
        Check if an order should be allowed through the gate.

        Args:
            position_size_usd: Size of the proposed position in USD
            daily_pnl: Current daily P&L in USD (negative = loss)
            trades_today: Number of trades executed today
            is_exit: True if this is an exit/close order

        Returns:
            GateResult with allowed status and reason if blocked
        """
        # Reload config to pick up any runtime changes
        self._reload_config()

        # =====================================================================
        # GATE 1: Emergency Stop (highest priority)
        # =====================================================================
        if self.emergency_stop:
            if is_exit:
                # Allow exits even during emergency to protect capital
                self.logger.warning("EMERGENCY_STOP active but allowing exit order")
            else:
                return GateResult(
                    allowed=False,
                    reason="EMERGENCY_STOP active - all new orders blocked",
                    gate_name="emergency_stop",
                )

        # =====================================================================
        # GATE 2: Live Trading Enabled (master switch)
        # =====================================================================
        if not self.live_enabled:
            return GateResult(
                allowed=False,
                reason="LIVE_TRADING_ENABLED=false - order blocked",
                gate_name="live_trading_enabled",
                dry_run=True,  # Signal that this is a dry-run block
            )

        # =====================================================================
        # GATE 3: Dependency Health
        # =====================================================================
        health = self._check_dependencies()
        if not health.all_healthy():
            unhealthy = []
            if not health.redis_healthy:
                unhealthy.append("redis")
            if not health.websocket_healthy:
                unhealthy.append("websocket")
            if not health.exchange_api_healthy:
                unhealthy.append("exchange_api")

            return GateResult(
                allowed=False,
                reason=f"Dependencies unhealthy: {', '.join(unhealthy)}",
                gate_name="dependency_health",
            )

        # =====================================================================
        # GATE 4: Risk Limits
        # =====================================================================

        # Position size limit
        if position_size_usd > self.max_position_size_usd:
            return GateResult(
                allowed=False,
                reason=f"Position too large: ${position_size_usd:.2f} > ${self.max_position_size_usd:.2f}",
                gate_name="max_position_size",
            )

        # Daily loss limit
        if daily_pnl < -self.max_daily_loss_usd:
            return GateResult(
                allowed=False,
                reason=f"Daily loss limit hit: ${abs(daily_pnl):.2f} > ${self.max_daily_loss_usd:.2f}",
                gate_name="max_daily_loss",
            )

        # Trade frequency limit
        if trades_today >= self.max_trades_per_day:
            return GateResult(
                allowed=False,
                reason=f"Max trades reached: {trades_today} >= {self.max_trades_per_day}",
                gate_name="max_trades_per_day",
            )

        # =====================================================================
        # GATE 5: Mode Confirmation (for live execution)
        # =====================================================================
        if self.mode != "live" or self.confirmation != "I-accept-the-risk":
            return GateResult(
                allowed=False,
                reason="Live trading not confirmed (MODE != 'live' or confirmation missing)",
                gate_name="mode_confirmation",
            )

        # =====================================================================
        # GATE 6: Shadow Mode (simulate but don't execute)
        # =====================================================================
        if self.shadow_mode:
            return GateResult(
                allowed=True,  # Allow through for simulation
                shadow_mode=True,
                reason="SHADOW_EXECUTION=true - order will be simulated",
            )

        # All gates passed
        return GateResult(allowed=True)

    def _check_dependencies(self) -> DependencyHealth:
        """Check health of execution dependencies."""
        if self._health_checker:
            try:
                self._last_health = self._health_checker()
            except Exception as e:
                self.logger.warning("Health check failed: %s", e)
                # On health check failure, assume unhealthy
                self._last_health = DependencyHealth(
                    redis_healthy=False,
                    websocket_healthy=False,
                    exchange_api_healthy=False,
                )
        return self._last_health

    def log_preflight_status(self) -> None:
        """
        Log non-sensitive preflight status at startup.

        Logs:
        - live_enabled (true/false)
        - emergency_stop (true/false)
        - shadow_mode (true/false)
        - risk rail values
        - dependency health flags
        """
        self._reload_config()
        health = self._check_dependencies()

        self.logger.info("=" * 60)
        self.logger.info("EXECUTION GATE PREFLIGHT STATUS")
        self.logger.info("=" * 60)

        # Execution mode
        if self.emergency_stop:
            self.logger.warning("EMERGENCY_STOP: ACTIVE - all orders blocked")
        else:
            self.logger.info("emergency_stop: false")

        if self.live_enabled:
            self.logger.warning("LIVE_TRADING_ENABLED: TRUE - real orders will execute")
        else:
            self.logger.info("live_trading_enabled: false (dry-run mode)")

        if self.shadow_mode:
            self.logger.info("shadow_execution: true (simulating orders)")
        else:
            self.logger.info("shadow_execution: false")

        self.logger.info("mode: %s", self.mode or "(not set)")

        # Risk limits
        self.logger.info("-" * 40)
        self.logger.info("RISK LIMITS:")
        self.logger.info("  max_position_size_usd: $%.2f", self.max_position_size_usd)
        self.logger.info("  max_daily_loss_usd: $%.2f", self.max_daily_loss_usd)
        self.logger.info("  max_trades_per_day: %d", self.max_trades_per_day)
        self.logger.info("  risk_per_trade_pct: %.2f%%", self.risk_per_trade_pct)
        self.logger.info("  cooldown_seconds: %d", self.cooldown_seconds)

        # Dependencies
        self.logger.info("-" * 40)
        self.logger.info("DEPENDENCIES:")
        self.logger.info("  redis_healthy: %s", health.redis_healthy)
        self.logger.info("  websocket_healthy: %s", health.websocket_healthy)
        self.logger.info("  exchange_api_healthy: %s", health.exchange_api_healthy)

        self.logger.info("=" * 60)

        # Summary
        if not self.live_enabled:
            self.logger.info("SYSTEM STATUS: DRY-RUN MODE (orders will be logged, not executed)")
        elif self.shadow_mode:
            self.logger.info("SYSTEM STATUS: SHADOW MODE (orders will be simulated)")
        elif self.emergency_stop:
            self.logger.warning("SYSTEM STATUS: EMERGENCY STOP ACTIVE")
        else:
            self.logger.warning("SYSTEM STATUS: LIVE EXECUTION ENABLED")

    def log_dry_run_order(self, order_info: Dict[str, Any]) -> None:
        """
        Log an order that would be placed in dry-run mode.

        Args:
            order_info: Dictionary with order details (symbol, side, size, price, etc.)
        """
        symbol = order_info.get("symbol", "UNKNOWN")
        side = order_info.get("side", "UNKNOWN")
        size = order_info.get("size", 0)
        price = order_info.get("price", 0)
        notional = float(size) * float(price) if price else 0

        self.logger.info(
            "DRY-RUN: would place %s %s %s @ %s (notional=$%.2f)",
            side,
            size,
            symbol,
            price,
            notional,
        )

    def get_status(self) -> Dict[str, Any]:
        """Get current gate status as a dictionary."""
        self._reload_config()
        health = self._check_dependencies()

        return {
            "live_trading_enabled": self.live_enabled,
            "emergency_stop": self.emergency_stop,
            "shadow_mode": self.shadow_mode,
            "mode": self.mode,
            "risk_limits": {
                "max_position_size_usd": self.max_position_size_usd,
                "max_daily_loss_usd": self.max_daily_loss_usd,
                "max_trades_per_day": self.max_trades_per_day,
                "risk_per_trade_pct": self.risk_per_trade_pct,
                "cooldown_seconds": self.cooldown_seconds,
            },
            "dependencies": health.to_dict(),
            "uptime_seconds": time.time() - self._startup_time,
        }


# =============================================================================
# SINGLETON ACCESS
# =============================================================================

_gate_instance: Optional[ExecutionGate] = None


def get_execution_gate(
    health_checker: Optional[Callable[[], DependencyHealth]] = None,
) -> ExecutionGate:
    """
    Get or create the singleton ExecutionGate instance.

    Args:
        health_checker: Optional callback for dependency health checks

    Returns:
        The global ExecutionGate instance
    """
    global _gate_instance
    if _gate_instance is None:
        _gate_instance = ExecutionGate(health_checker=health_checker)
    return _gate_instance


def reset_execution_gate() -> None:
    """Reset the singleton instance (for testing)."""
    global _gate_instance
    _gate_instance = None


__all__ = [
    "ExecutionGate",
    "GateResult",
    "DependencyHealth",
    "get_execution_gate",
    "reset_execution_gate",
]
