"""
Emergency kill switch system for immediate trading halt.

This module provides comprehensive kill switch capabilities for the scalping
system, offering multiple layers of emergency protection mechanisms to ensure
immediate trading halt when critical conditions are detected.

Features:
- Multiple kill switch types (manual, loss limits, drawdown, consecutive losses)
- Configurable severity levels (warning, critical, emergency)
- Automatic recovery and cooldown mechanisms
- Real-time monitoring and health checks
- Redis-based event broadcasting
- Emergency shutdown protocols
- Performance tracking and risk metrics

This module provides the core kill switch infrastructure for the scalping
system, enabling immediate protection against catastrophic losses and system failures.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from ..config_loader import KrakenScalpingConfig
from ..infra.redis_bus import RedisBus

logger = logging.getLogger(__name__)


class KillSwitchType(Enum):
    """Types of kill switches"""

    MANUAL = "manual"  # Manual emergency stop
    LOSS_LIMIT = "loss_limit"  # Daily/total loss exceeded
    DRAWDOWN = "drawdown"  # Maximum drawdown exceeded
    CONSECUTIVE_LOSSES = "consecutive_losses"  # Too many losses in a row
    API_FAILURE = "api_failure"  # Exchange API failures
    NETWORK_FAILURE = "network_failure"  # Network connectivity issues
    SYSTEM_ERROR = "system_error"  # Internal system errors
    MARKET_HALT = "market_halt"  # Exchange market halt
    VOLATILITY_SPIKE = "volatility_spike"  # Extreme volatility
    LIQUIDITY_CRISIS = "liquidity_crisis"  # Liquidity dried up
    REGULATORY = "regulatory"  # Regulatory halt signal


class KillSwitchSeverity(Enum):
    """Severity levels for kill switches"""

    WARNING = "warning"  # Reduce position size, increase caution
    CRITICAL = "critical"  # Stop new trades, monitor existing
    EMERGENCY = "emergency"  # Close all positions immediately


@dataclass
class KillSwitchEvent:
    """Kill switch activation event"""

    switch_type: KillSwitchType
    severity: KillSwitchSeverity
    reason: str
    trigger_value: Optional[float] = None
    threshold_value: Optional[float] = None
    timestamp: float = field(default_factory=time.time)
    source: str = "system"
    auto_recovery: bool = False
    recovery_delay_seconds: int = 0


@dataclass
class KillSwitchConfig:
    """Configuration for a kill switch"""

    enabled: bool = True
    threshold: Optional[float] = None
    severity: KillSwitchSeverity = KillSwitchSeverity.CRITICAL
    auto_recovery: bool = False
    recovery_delay_seconds: int = 300
    cooldown_seconds: int = 60
    max_triggers_per_hour: int = 3


class KillSwitch:
    """Individual kill switch implementation"""

    def __init__(
        self,
        switch_type: KillSwitchType,
        config: KillSwitchConfig,
        callback: Optional[Callable] = None,
    ):
        self.switch_type = switch_type
        self.config = config
        self.callback = callback

        # State
        self.is_active = False
        self.last_trigger_time = 0.0
        self.trigger_count = 0
        self.trigger_history: List[KillSwitchEvent] = []

        # Cooldown tracking
        self.last_cooldown_end = 0.0

        self.logger = logging.getLogger(f"{__name__}.{switch_type.value}")

    async def check_condition(
        self, value: Any = None, context: Dict = None
    ) -> Optional[KillSwitchEvent]:
        """
        Check if kill switch should be triggered.

        Returns KillSwitchEvent if triggered, None otherwise.
        """
        if not self.config.enabled:
            return None

        current_time = time.time()

        # Cooldown
        if (current_time - self.last_cooldown_end) < self.config.cooldown_seconds:
            return None

        # Rate limiting (per-hour)
        recent_triggers = sum(
            1 for event in self.trigger_history if current_time - event.timestamp <= 3600
        )
        if recent_triggers >= self.config.max_triggers_per_hour:
            self.logger.warning(f"Kill switch {self.switch_type.value} rate limited")
            return None

        should_trigger = await self._evaluate_condition(value, context or {})

        if should_trigger:
            event = KillSwitchEvent(
                switch_type=self.switch_type,
                severity=self.config.severity,
                reason=await self._get_trigger_reason(value, context or {}),
                trigger_value=float(value) if isinstance(value, (int, float)) else None,
                threshold_value=self.config.threshold,
                auto_recovery=self.config.auto_recovery,
                recovery_delay_seconds=self.config.recovery_delay_seconds,
            )
            await self._trigger(event)
            return event

        return None

    async def force_trigger(
        self, reason: str, severity: KillSwitchSeverity = None
    ) -> KillSwitchEvent:
        """Force trigger the kill switch"""
        event = KillSwitchEvent(
            switch_type=self.switch_type,
            severity=severity or self.config.severity,
            reason=f"Force triggered: {reason}",
            source="manual",
        )
        await self._trigger(event)
        return event

    async def reset(self) -> None:
        """Reset the kill switch"""
        self.is_active = False
        self.last_cooldown_end = time.time()
        self.logger.info(f"Kill switch {self.switch_type.value} reset")

    async def _evaluate_condition(self, value: Any, context: Dict) -> bool:
        """Evaluate the specific condition for this kill switch"""
        threshold = self.config.threshold
        if threshold is None:
            return False

        # Numeric comparison by default
        if isinstance(value, (int, float)):
            return float(value) >= float(threshold)

        # Allow context-driven conditions (optional extension)
        override = context.get("threshold")
        if isinstance(override, (int, float)):
            return float(value) >= float(override)
        return False

    async def _get_trigger_reason(self, value: Any, context: Dict) -> str:
        """Get human-readable trigger reason"""
        thr = context.get("threshold", self.config.threshold)
        if isinstance(thr, (int, float)) and isinstance(value, (int, float)):
            return f"{self.switch_type.value} threshold exceeded: {value} >= {thr}"
        return f"{self.switch_type.value} condition met"

    async def _trigger(self, event: KillSwitchEvent) -> None:
        """Trigger the kill switch"""
        self.is_active = True
        self.last_trigger_time = event.timestamp
        self.trigger_count += 1
        self.trigger_history.append(event)

        # Callback
        if self.callback:
            try:
                await self.callback(self, event)
            except Exception as e:
                self.logger.error(f"Error in kill switch callback: {e}")

        # Auto-recovery scheduling
        if event.auto_recovery and event.recovery_delay_seconds > 0:
            asyncio.create_task(self._auto_recover(event.recovery_delay_seconds))

        self.logger.critical(f"KILL SWITCH TRIGGERED: {event.switch_type.value} - {event.reason}")

    async def _auto_recover(self, delay_seconds: int) -> None:
        """Automatically recover after delay"""
        await asyncio.sleep(delay_seconds)
        if self.is_active:
            await self.reset()


class KillSwitchManager:
    """
    Manages multiple kill switches for comprehensive emergency protection.

    Coordinates different types of emergency stops and system halts.
    """

    def __init__(
        self, config: KrakenScalpingConfig, redis_bus: RedisBus, agent_id: str = "kraken_scalper"
    ):
        self.config = config
        self.redis_bus = redis_bus
        self.agent_id = agent_id
        self.logger = logging.getLogger(f"{__name__}.{agent_id}")

        # Portfolio base capital for % computations
        self.base_capital: float = getattr(config, "base_capital", 10_000.0)

        # Kill switches
        self.switches: Dict[KillSwitchType, KillSwitch] = {}
        self.active_switches: Set[KillSwitchType] = set()

        # System state
        self.system_halted = False
        self.halt_reason = ""
        self.halt_timestamp = 0.0
        self.emergency_mode = False

        # Callbacks for system-wide actions
        self.halt_callbacks: List[Callable] = []
        self.resume_callbacks: List[Callable] = []

        # Performance tracking
        self.cumulative_pnl = 0.0
        self.daily_pnl = 0.0
        self.consecutive_losses = 0
        self.max_drawdown = 0.0
        self.current_drawdown = 0.0

        # API / network tracking
        self.api_error_count = 0
        self.last_api_success = time.time()

        self._setup_switches()

        self.logger.info("KillSwitchManager initialized")

    async def start(self) -> None:
        """Start the kill switch system"""
        self.logger.info("Starting KillSwitchManager...")

        # Subscribe to system events
        await self._setup_monitoring()

        # Start monitoring loops
        asyncio.create_task(self._monitoring_loop())

        self.logger.info("KillSwitchManager started")

    async def stop(self) -> None:
        """Stop the kill switch system"""
        self.logger.info("KillSwitchManager stopped")

    async def manual_kill(
        self, reason: str, severity: KillSwitchSeverity = KillSwitchSeverity.EMERGENCY
    ) -> None:
        """Manually trigger emergency stop"""
        manual_switch = self.switches.get(KillSwitchType.MANUAL)
        if manual_switch:
            await manual_switch.force_trigger(reason, severity)
        else:
            await self._execute_system_halt(reason, severity)

    async def check_loss_limits(self, pnl: float) -> None:
        """Check loss limit kill switches.

        Expects `pnl` in base currency (USD). Converts to % of base capital.
        """
        self.daily_pnl = pnl

        loss_switch = self.switches.get(KillSwitchType.LOSS_LIMIT)
        if not loss_switch:
            return

        # Only consider losses; convert to percentage of base capital
        loss_pct = 0.0
        if self.base_capital > 0 and pnl < 0:
            loss_pct = (-pnl / self.base_capital) * 100.0

        if loss_pct > 0:
            await loss_switch.check_condition(loss_pct)

    async def check_drawdown(self, current_dd: float, max_dd: float) -> None:
        """Check drawdown kill switches

        Inputs expected as negative fractions (e.g., -0.05 for -5%), but code
        works with any sign by taking absolute values.
        """
        self.current_drawdown = current_dd
        self.max_drawdown = max_dd

        drawdown_switch = self.switches.get(KillSwitchType.DRAWDOWN)
        if drawdown_switch:
            dd_pct = abs(current_dd) * 100.0
            await drawdown_switch.check_condition(dd_pct)

    async def check_consecutive_losses(self, loss_count: int) -> None:
        """Check consecutive loss kill switches"""
        self.consecutive_losses = loss_count
        loss_switch = self.switches.get(KillSwitchType.CONSECUTIVE_LOSSES)
        if loss_switch:
            await loss_switch.check_condition(loss_count)

    async def report_api_error(self) -> None:
        """Report API error for monitoring"""
        self.api_error_count += 1

        api_switch = self.switches.get(KillSwitchType.API_FAILURE)
        if api_switch:
            await api_switch.check_condition(self.api_error_count)

    async def report_api_success(self) -> None:
        """Report successful API call"""
        self.last_api_success = time.time()
        self.api_error_count = max(0, self.api_error_count - 1)

    async def check_volatility(self, volatility: float) -> None:
        """Check volatility spike kill switches (volatility as fraction, e.g., 0.08 = 8%)"""
        vol_switch = self.switches.get(KillSwitchType.VOLATILITY_SPIKE)
        if vol_switch:
            vol_pct = volatility * 100.0
            await vol_switch.check_condition(vol_pct)

    async def check_liquidity(self, liquidity_ratio: float) -> None:
        """Check liquidity crisis kill switches (0..1, lower means worse liquidity)"""
        liquidity_switch = self.switches.get(KillSwitchType.LIQUIDITY_CRISIS)
        if liquidity_switch:
            # Here we intentionally pass the ratio, threshold also a ratio (e.g., 0.2).
            if liquidity_ratio <= (liquidity_switch.config.threshold or 0.0):
                await liquidity_switch.check_condition(liquidity_ratio)

    async def emergency_halt_all(self, reason: str) -> None:
        """Emergency halt everything immediately"""
        self.emergency_mode = True
        await self._execute_system_halt(reason, KillSwitchSeverity.EMERGENCY)

        # Trigger all emergency switches
        for switch in self.switches.values():
            if not switch.is_active:
                await switch.force_trigger(
                    f"Emergency halt: {reason}", KillSwitchSeverity.EMERGENCY
                )

    async def reset_all_switches(self) -> None:
        """Reset all kill switches"""
        for switch in self.switches.values():
            await switch.reset()

        self.active_switches.clear()
        self.system_halted = False
        self.emergency_mode = False

        self.logger.info("All kill switches reset")

    def is_system_halted(self) -> bool:
        """Check if system is halted"""
        return self.system_halted or len(self.active_switches) > 0

    def get_halt_reason(self) -> str:
        """Get reason for system halt"""
        if self.halt_reason:
            return self.halt_reason

        if self.active_switches:
            active_names = [switch.value for switch in self.active_switches]
            return f"Active kill switches: {', '.join(active_names)}"

        return "System operational"

    def get_system_status(self) -> Dict[str, Any]:
        """Get comprehensive system status"""
        return {
            "system_halted": self.system_halted,
            "emergency_mode": self.emergency_mode,
            "halt_reason": self.get_halt_reason(),
            "halt_timestamp": self.halt_timestamp,
            "active_switches": [switch.value for switch in self.active_switches],
            "switch_status": {
                switch_type.value: {
                    "active": switch.is_active,
                    "trigger_count": switch.trigger_count,
                    "last_trigger": switch.last_trigger_time,
                }
                for switch_type, switch in self.switches.items()
            },
            "performance_metrics": {
                "daily_pnl": self.daily_pnl,
                "current_drawdown": self.current_drawdown,
                "consecutive_losses": self.consecutive_losses,
                "api_error_count": self.api_error_count,
            },
        }

    def register_halt_callback(self, callback: Callable) -> None:
        """Register callback for system halt events"""
        self.halt_callbacks.append(callback)

    def register_resume_callback(self, callback: Callable) -> None:
        """Register callback for system resume events"""
        self.resume_callbacks.append(callback)

    # Private methods

    def _setup_switches(self) -> None:
        """Setup all kill switches with configuration"""

        # Manual kill switch
        manual_config = KillSwitchConfig(
            enabled=True, severity=KillSwitchSeverity.EMERGENCY, auto_recovery=False
        )
        self.switches[KillSwitchType.MANUAL] = KillSwitch(
            KillSwitchType.MANUAL, manual_config, self._handle_kill_switch
        )

        # Loss limit kill switch (threshold = % of base capital)
        loss_limit_config = KillSwitchConfig(
            enabled=True,
            threshold=abs(getattr(self.config.risk, "daily_stop_loss", -0.02)) * 100.0,
            severity=KillSwitchSeverity.CRITICAL,
            auto_recovery=False,
            recovery_delay_seconds=3600,  # 1 hour
        )
        self.switches[KillSwitchType.LOSS_LIMIT] = KillSwitch(
            KillSwitchType.LOSS_LIMIT, loss_limit_config, self._handle_kill_switch
        )

        # Drawdown kill switch (threshold in %)
        drawdown_config = KillSwitchConfig(
            enabled=True,
            threshold=abs(getattr(self.config.risk, "global_max_drawdown", -0.15)) * 100.0,
            severity=KillSwitchSeverity.EMERGENCY,
            auto_recovery=False,
        )
        self.switches[KillSwitchType.DRAWDOWN] = KillSwitch(
            KillSwitchType.DRAWDOWN, drawdown_config, self._handle_kill_switch
        )

        # Consecutive losses kill switch (count)
        consecutive_config = KillSwitchConfig(
            enabled=True,
            threshold=getattr(self.config.risk.circuit_breakers, "consecutive_losses", 5),
            severity=KillSwitchSeverity.WARNING,
            auto_recovery=True,
            recovery_delay_seconds=1800,  # 30 minutes
        )
        self.switches[KillSwitchType.CONSECUTIVE_LOSSES] = KillSwitch(
            KillSwitchType.CONSECUTIVE_LOSSES, consecutive_config, self._handle_kill_switch
        )

        # API failure kill switch (count of consecutive errors or growing errors)
        api_config = KillSwitchConfig(
            enabled=True,
            threshold=10,  # 10 errors trips
            severity=KillSwitchSeverity.CRITICAL,
            auto_recovery=True,
            recovery_delay_seconds=600,  # 10 minutes
        )
        self.switches[KillSwitchType.API_FAILURE] = KillSwitch(
            KillSwitchType.API_FAILURE, api_config, self._handle_kill_switch
        )

        # Network failure kill switch (seconds since last API success)
        network_config = KillSwitchConfig(
            enabled=True,
            threshold=600.0,  # 10 minutes without success
            severity=KillSwitchSeverity.CRITICAL,
            auto_recovery=True,
            recovery_delay_seconds=600,
        )
        self.switches[KillSwitchType.NETWORK_FAILURE] = KillSwitch(
            KillSwitchType.NETWORK_FAILURE, network_config, self._handle_kill_switch
        )

        # Volatility spike kill switch (vol %)
        volatility_config = KillSwitchConfig(
            enabled=True,
            threshold=8.0,  # 8% volatility
            severity=KillSwitchSeverity.WARNING,
            auto_recovery=True,
            recovery_delay_seconds=900,  # 15 minutes
        )
        self.switches[KillSwitchType.VOLATILITY_SPIKE] = KillSwitch(
            KillSwitchType.VOLATILITY_SPIKE, volatility_config, self._handle_kill_switch
        )

        # Liquidity crisis kill switch (ratio 0..1)
        liquidity_config = KillSwitchConfig(
            enabled=True,
            threshold=0.2,  # 20% of normal liquidity
            severity=KillSwitchSeverity.CRITICAL,
            auto_recovery=True,
            recovery_delay_seconds=1800,  # 30 minutes
        )
        self.switches[KillSwitchType.LIQUIDITY_CRISIS] = KillSwitch(
            KillSwitchType.LIQUIDITY_CRISIS, liquidity_config, self._handle_kill_switch
        )

    async def _setup_monitoring(self) -> None:
        """Setup monitoring subscriptions"""
        try:
            # Subscribe to performance updates
            await self.redis_bus.subscribe(
                f"performance:metrics:{self.agent_id}", self._handle_performance_update
            )

            # Subscribe to API error events
            await self.redis_bus.subscribe(f"api:error:{self.agent_id}", self._handle_api_error)

            # Subscribe to market data for volatility monitoring
            await self.redis_bus.subscribe(
                f"market:volatility:{self.agent_id}", self._handle_volatility_update
            )

        except Exception as e:
            self.logger.error(f"Error setting up monitoring: {e}")

    async def _monitoring_loop(self) -> None:
        """Main monitoring loop"""
        while True:
            try:
                await self._check_system_health()
                await self._cleanup_old_events()
                await asyncio.sleep(30)  # Check every 30 seconds
            except Exception as e:
                self.logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(60)

    async def _check_system_health(self) -> None:
        """Check overall system health"""
        current_time = time.time()

        # Network/API silence → trigger network failure
        network_switch = self.switches.get(KillSwitchType.NETWORK_FAILURE)
        if network_switch:
            silence_seconds = current_time - self.last_api_success
            await network_switch.check_condition(silence_seconds)

    async def _cleanup_old_events(self) -> None:
        """Clean up old kill switch events"""
        current_time = time.time()
        cutoff_time = current_time - 86400  # 24 hours

        for switch in self.switches.values():
            switch.trigger_history = [
                event for event in switch.trigger_history if event.timestamp > cutoff_time
            ]

    async def _handle_kill_switch(self, switch: KillSwitch, event: KillSwitchEvent) -> None:
        """Handle kill switch activation"""
        self.active_switches.add(event.switch_type)

        # Execute appropriate action based on severity
        if event.severity == KillSwitchSeverity.EMERGENCY:
            await self._execute_system_halt(event.reason, event.severity)
        elif event.severity == KillSwitchSeverity.CRITICAL:
            await self._execute_critical_action(event)
        else:  # WARNING
            await self._execute_warning_action(event)

        # Broadcast kill switch event
        await self.redis_bus.publish(
            f"killswitch:triggered:{self.agent_id}",
            {
                "switch_type": event.switch_type.value,
                "severity": event.severity.value,
                "reason": event.reason,
                "timestamp": event.timestamp,
            },
        )

    async def _execute_system_halt(self, reason: str, severity: KillSwitchSeverity) -> None:
        """Execute complete system halt"""
        if self.system_halted and self.halt_reason == reason:
            return  # already halted for this reason

        self.system_halted = True
        self.halt_reason = reason
        self.halt_timestamp = time.time()

        # Execute halt callbacks
        for callback in self.halt_callbacks:
            try:
                await callback(reason, severity)
            except Exception as e:
                self.logger.error(f"Error in halt callback: {e}")

        # Broadcast system halt
        await self.redis_bus.publish(
            f"system:halt:{self.agent_id}",
            {
                "reason": reason,
                "severity": severity.value,
                "timestamp": self.halt_timestamp,
                "emergency_mode": self.emergency_mode,
            },
        )

        self.logger.critical(f"SYSTEM HALTED: {reason}")

    async def _execute_critical_action(self, event: KillSwitchEvent) -> None:
        """Execute critical protection action"""
        # Stop new trades but don't force close positions
        await self.redis_bus.publish(
            f"trading:suspend:{self.agent_id}",
            {"reason": event.reason, "timestamp": event.timestamp},
        )
        self.logger.error(f"TRADING SUSPENDED: {event.reason}")

    async def _execute_warning_action(self, event: KillSwitchEvent) -> None:
        """Execute warning protection action"""
        # Reduce position sizes and increase caution
        await self.redis_bus.publish(
            f"trading:caution:{self.agent_id}",
            {"reason": event.reason, "timestamp": event.timestamp, "action": "reduce_size"},
        )
        self.logger.warning(f"TRADING CAUTION: {event.reason}")

    # Event handlers

    async def _handle_performance_update(self, data: Dict) -> None:
        """Handle performance metric updates"""
        try:
            # Update performance metrics
            if "total_pnl" in data:
                await self.check_loss_limits(data["total_pnl"])

            if "current_drawdown" in data:
                await self.check_drawdown(data["current_drawdown"], data.get("max_drawdown", 0.0))

            # Optionally: track consecutive losses if provided
            if "consecutive_losses" in data:
                await self.check_consecutive_losses(int(data["consecutive_losses"]))

        except Exception as e:
            self.logger.error(f"Error handling performance update: {e}")

    async def _handle_api_error(self, data: Dict) -> None:
        """Handle API error events"""
        try:
            await self.report_api_error()
        except Exception as e:
            self.logger.error(f"Error handling API error: {e}")

    async def _handle_volatility_update(self, data: Dict) -> None:
        """Handle volatility updates"""
        try:
            volatility = float(data.get("volatility", 0.0))
            await self.check_volatility(volatility)
        except Exception as e:
            self.logger.error(f"Error handling volatility update: {e}")


class EmergencyProtocol:
    """Emergency protocol for coordinated shutdown"""

    def __init__(self, kill_switch_manager: KillSwitchManager):
        self.ksm = kill_switch_manager
        self.logger = logging.getLogger(f"{__name__}.EmergencyProtocol")

    async def execute_emergency_shutdown(self, reason: str) -> None:
        """Execute full emergency shutdown protocol"""
        self.logger.critical(f"EXECUTING EMERGENCY SHUTDOWN: {reason}")

        # 1. Halt all trading immediately
        await self.ksm.emergency_halt_all(reason)

        # 2. Cancel all open orders
        await self._cancel_all_orders()

        # 3. Close all positions (if configured)
        await self._close_all_positions()

        # 4. Disconnect from exchange
        await self._disconnect_exchange()

        # 5. Send emergency notifications
        await self._send_emergency_notifications(reason)

    async def _cancel_all_orders(self) -> None:
        """Cancel all open orders"""
        try:
            await self.ksm.redis_bus.publish(
                f"orders:cancel_all:{self.ksm.agent_id}",
                {"reason": "emergency_shutdown", "timestamp": time.time()},
            )
        except Exception as e:
            self.logger.error(f"Error cancelling orders: {e}")

    async def _close_all_positions(self) -> None:
        """Close all open positions"""
        try:
            await self.ksm.redis_bus.publish(
                f"positions:close_all:{self.ksm.agent_id}",
                {"reason": "emergency_shutdown", "timestamp": time.time()},
            )
        except Exception as e:
            self.logger.error(f"Error closing positions: {e}")

    async def _disconnect_exchange(self) -> None:
        """Disconnect from exchange"""
        try:
            await self.ksm.redis_bus.publish(
                f"exchange:disconnect:{self.ksm.agent_id}",
                {"reason": "emergency_shutdown", "timestamp": time.time()},
            )
        except Exception as e:
            self.logger.error(f"Error disconnecting exchange: {e}")

    async def _send_emergency_notifications(self, reason: str) -> None:
        """Send emergency notifications"""
        try:
            await self.ksm.redis_bus.publish(
                f"alerts:emergency:{self.ksm.agent_id}",
                {
                    "type": "emergency_shutdown",
                    "reason": reason,
                    "timestamp": time.time(),
                    "severity": "CRITICAL",
                },
            )
        except Exception as e:
            self.logger.error(f"Error sending emergency notifications: {e}")
