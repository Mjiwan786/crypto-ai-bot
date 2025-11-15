#!/usr/bin/env python3
"""
Protection Mode - Automatic Capital Preservation System

Activates when:
1. Equity ≥ protection_equity_threshold (default: $18k)
2. Win streak ≥ protection_win_streak_threshold (default: 5 consecutive wins)

Protection Mode adjustments:
- Position sizes: Halved (risk_multiplier: 0.5)
- Stop losses: Tightened (sl_multiplier: 0.7)
- Max trades/min: Reduced (rate_multiplier: 0.5)
- Take profits: Optional tighter targets (tp_multiplier: 0.8)

Manual override available via:
- YAML config: protection_mode.force_enabled: true/false
- Runtime Redis: SET protection:mode:override "enabled" or "disabled"
- API endpoint: POST /protection-mode/override
"""

import asyncio
import logging
from typing import Dict, Optional, Any, List
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from enum import Enum

try:
    import redis.asyncio as aioredis
except ImportError:
    aioredis = None


logger = logging.getLogger(__name__)


class ProtectionModeStatus(str, Enum):
    """Protection mode status"""
    DISABLED = "disabled"
    ENABLED = "enabled"
    FORCE_ENABLED = "force_enabled"
    FORCE_DISABLED = "force_disabled"


class ProtectionModeTrigger(str, Enum):
    """What triggered protection mode"""
    NONE = "none"
    EQUITY_THRESHOLD = "equity_threshold"
    WIN_STREAK = "win_streak"
    MANUAL_OVERRIDE = "manual_override"


@dataclass
class ProtectionModeConfig:
    """Protection mode configuration"""
    # Enable/disable
    enabled: bool = True
    force_enabled: Optional[bool] = None  # Manual override (True/False/None)

    # Activation triggers
    equity_threshold_usd: float = 18000.0  # Activate when equity ≥ $18k
    win_streak_threshold: int = 5  # Activate after 5 consecutive wins

    # Protection adjustments (multipliers applied to normal settings)
    risk_multiplier: float = 0.5  # Halve position sizes
    sl_multiplier: float = 0.7  # Tighten stop losses to 70% of normal
    tp_multiplier: float = 1.0  # Keep take profits same (or 0.8 to tighten)
    rate_multiplier: float = 0.5  # Reduce max trades/min to 50%

    # Deactivation criteria
    deactivate_on_loss: bool = False  # Stay in protection mode even after loss
    deactivate_below_equity: Optional[float] = None  # e.g., $17k to re-enable aggression

    # Alerts
    alert_on_activation: bool = True
    alert_on_deactivation: bool = True


@dataclass
class ProtectionModeState:
    """Current protection mode state"""
    status: ProtectionModeStatus
    trigger: ProtectionModeTrigger
    activated_at: Optional[datetime] = None
    current_equity: float = 0.0
    current_win_streak: int = 0
    trades_since_activation: int = 0
    pnl_since_activation: float = 0.0

    # Adjustments being applied
    risk_multiplier: float = 1.0
    sl_multiplier: float = 1.0
    tp_multiplier: float = 1.0
    rate_multiplier: float = 1.0


class ProtectionModeManager:
    """Manages protection mode activation, deactivation, and adjustments"""

    def __init__(
        self,
        config: ProtectionModeConfig,
        redis_client: Optional[aioredis.Redis] = None,
        starting_equity: float = 10000.0
    ):
        self.config = config
        self.redis_client = redis_client
        self.starting_equity = starting_equity

        # Current state
        self.state = ProtectionModeState(
            status=ProtectionModeStatus.DISABLED,
            trigger=ProtectionModeTrigger.NONE
        )

        # Trade history for win streak tracking
        self.recent_trades: List[Dict] = []

        logger.info(f"Protection Mode initialized: equity_threshold=${config.equity_threshold_usd:,.0f}, win_streak={config.win_streak_threshold}")

    async def check_and_update(
        self,
        current_equity: float,
        recent_trades: Optional[List[Dict]] = None
    ) -> ProtectionModeState:
        """
        Check conditions and update protection mode state

        Args:
            current_equity: Current account equity
            recent_trades: List of recent closed trades (for win streak)

        Returns:
            Updated protection mode state
        """
        # Update current metrics
        self.state.current_equity = current_equity

        if recent_trades:
            self.recent_trades = recent_trades
            self.state.current_win_streak = self._calculate_win_streak()

        # Check for manual override first
        override_status = await self._check_override()

        if override_status == "force_enabled":
            if self.state.status != ProtectionModeStatus.FORCE_ENABLED:
                await self._activate(ProtectionModeTrigger.MANUAL_OVERRIDE)
                self.state.status = ProtectionModeStatus.FORCE_ENABLED
                logger.warning("🛡️  Protection Mode FORCE ENABLED via manual override")

        elif override_status == "force_disabled":
            if self.state.status != ProtectionModeStatus.FORCE_DISABLED:
                await self._deactivate()
                self.state.status = ProtectionModeStatus.FORCE_DISABLED
                logger.warning("⚠️  Protection Mode FORCE DISABLED via manual override")

        else:
            # Normal automatic logic (no override)
            if not self.config.enabled:
                if self.state.status == ProtectionModeStatus.ENABLED:
                    await self._deactivate()
                return self.state

            # Check activation conditions
            should_activate = False
            trigger = ProtectionModeTrigger.NONE

            # Condition 1: Equity threshold
            if current_equity >= self.config.equity_threshold_usd:
                should_activate = True
                trigger = ProtectionModeTrigger.EQUITY_THRESHOLD

            # Condition 2: Win streak threshold
            if self.state.current_win_streak >= self.config.win_streak_threshold:
                should_activate = True
                if trigger == ProtectionModeTrigger.NONE:
                    trigger = ProtectionModeTrigger.WIN_STREAK

            # Activate or deactivate
            if should_activate and self.state.status == ProtectionModeStatus.DISABLED:
                await self._activate(trigger)

            # Check deactivation conditions
            elif self.state.status == ProtectionModeStatus.ENABLED:
                should_deactivate = False

                # Deactivate if equity drops below threshold
                if self.config.deactivate_below_equity:
                    if current_equity < self.config.deactivate_below_equity:
                        should_deactivate = True
                        logger.info(f"Protection Mode: Equity ${current_equity:,.2f} < ${self.config.deactivate_below_equity:,.2f}, deactivating")

                # Deactivate on loss
                if self.config.deactivate_on_loss and self.state.current_win_streak == 0:
                    should_deactivate = True
                    logger.info("Protection Mode: Win streak broken, deactivating")

                if should_deactivate:
                    await self._deactivate()

        # Publish state to Redis
        await self._publish_state()

        return self.state

    async def _activate(self, trigger: ProtectionModeTrigger):
        """Activate protection mode"""
        self.state.status = ProtectionModeStatus.ENABLED
        self.state.trigger = trigger
        self.state.activated_at = datetime.utcnow()
        self.state.trades_since_activation = 0
        self.state.pnl_since_activation = 0.0

        # Apply multipliers
        self.state.risk_multiplier = self.config.risk_multiplier
        self.state.sl_multiplier = self.config.sl_multiplier
        self.state.tp_multiplier = self.config.tp_multiplier
        self.state.rate_multiplier = self.config.rate_multiplier

        logger.warning(
            f"🛡️  PROTECTION MODE ACTIVATED | "
            f"Trigger: {trigger.value} | "
            f"Equity: ${self.state.current_equity:,.2f} | "
            f"Win Streak: {self.state.current_win_streak} | "
            f"Adjustments: Risk×{self.state.risk_multiplier}, SL×{self.state.sl_multiplier}, Rate×{self.state.rate_multiplier}"
        )

        if self.config.alert_on_activation:
            await self._send_alert("ACTIVATED", trigger)

    async def _deactivate(self):
        """Deactivate protection mode"""
        was_active = self.state.status in [ProtectionModeStatus.ENABLED, ProtectionModeStatus.FORCE_ENABLED]

        self.state.status = ProtectionModeStatus.DISABLED
        self.state.trigger = ProtectionModeTrigger.NONE

        # Reset multipliers to 1.0 (normal)
        self.state.risk_multiplier = 1.0
        self.state.sl_multiplier = 1.0
        self.state.tp_multiplier = 1.0
        self.state.rate_multiplier = 1.0

        if was_active:
            logger.warning(
                f"⚔️  PROTECTION MODE DEACTIVATED | "
                f"Equity: ${self.state.current_equity:,.2f} | "
                f"Trades: {self.state.trades_since_activation} | "
                f"P&L: ${self.state.pnl_since_activation:+.2f}"
            )

            if self.config.alert_on_deactivation:
                await self._send_alert("DEACTIVATED", ProtectionModeTrigger.NONE)

    def _calculate_win_streak(self) -> int:
        """Calculate current consecutive win streak"""
        if not self.recent_trades:
            return 0

        # Sort by close time (most recent first)
        sorted_trades = sorted(
            self.recent_trades,
            key=lambda t: t.get('closed_at', t.get('timestamp', '')),
            reverse=True
        )

        win_streak = 0
        for trade in sorted_trades:
            pnl = trade.get('pnl_usd', 0.0)

            if pnl > 0:
                win_streak += 1
            else:
                # Streak broken
                break

        return win_streak

    async def _check_override(self) -> Optional[str]:
        """
        Check for manual override in Redis

        Returns:
            "force_enabled", "force_disabled", or None
        """
        # Check YAML override first
        if self.config.force_enabled is True:
            return "force_enabled"
        elif self.config.force_enabled is False:
            return "force_disabled"

        # Check Redis override
        if not self.redis_client:
            return None

        try:
            override = await self.redis_client.get("protection:mode:override")
            if override:
                if override.lower() in ["enabled", "force_enabled", "on", "true"]:
                    return "force_enabled"
                elif override.lower() in ["disabled", "force_disabled", "off", "false"]:
                    return "force_disabled"
        except Exception as e:
            logger.error(f"Failed to check Redis override: {e}")

        return None

    async def _publish_state(self):
        """Publish current state to Redis"""
        if not self.redis_client:
            return

        try:
            # Publish state hash
            state_dict = {
                'status': self.state.status.value,
                'trigger': self.state.trigger.value,
                'activated_at': self.state.activated_at.isoformat() if self.state.activated_at else '',
                'current_equity': self.state.current_equity,
                'current_win_streak': self.state.current_win_streak,
                'trades_since_activation': self.state.trades_since_activation,
                'pnl_since_activation': self.state.pnl_since_activation,
                'risk_multiplier': self.state.risk_multiplier,
                'sl_multiplier': self.state.sl_multiplier,
                'tp_multiplier': self.state.tp_multiplier,
                'rate_multiplier': self.state.rate_multiplier,
            }

            await self.redis_client.hset('protection:mode:state', mapping=state_dict)

            # Publish event to stream
            await self.redis_client.xadd(
                'protection:mode:events',
                state_dict,
                maxlen=1000
            )

        except Exception as e:
            logger.error(f"Failed to publish protection mode state: {e}")

    async def _send_alert(self, action: str, trigger: ProtectionModeTrigger):
        """Send alert to configured channels"""
        alert = {
            'timestamp': datetime.utcnow().isoformat(),
            'action': action,
            'trigger': trigger.value,
            'equity': self.state.current_equity,
            'win_streak': self.state.current_win_streak,
            'adjustments': {
                'risk_multiplier': self.state.risk_multiplier,
                'sl_multiplier': self.state.sl_multiplier,
                'tp_multiplier': self.state.tp_multiplier,
                'rate_multiplier': self.state.rate_multiplier,
            }
        }

        if not self.redis_client:
            return

        try:
            # Publish to alerts stream
            await self.redis_client.xadd(
                'metrics:alerts',
                {
                    'type': 'protection_mode',
                    'action': action,
                    'message': f"Protection Mode {action}: {trigger.value}",
                    'data': str(alert)
                },
                maxlen=1000
            )
        except Exception as e:
            logger.error(f"Failed to send protection mode alert: {e}")

    def get_adjusted_params(self, base_params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply protection mode adjustments to strategy parameters

        Args:
            base_params: Original strategy parameters

        Returns:
            Adjusted parameters with protection mode multipliers applied
        """
        if self.state.status not in [ProtectionModeStatus.ENABLED, ProtectionModeStatus.FORCE_ENABLED]:
            return base_params

        adjusted = base_params.copy()

        # Adjust risk per trade (position size)
        if 'risk_per_trade_pct' in adjusted:
            original = adjusted['risk_per_trade_pct']
            adjusted['risk_per_trade_pct'] = original * self.state.risk_multiplier
            logger.debug(f"Protection Mode: risk_per_trade {original}% → {adjusted['risk_per_trade_pct']}%")

        # Adjust stop loss (tighten)
        if 'sl_atr' in adjusted:
            original = adjusted['sl_atr']
            adjusted['sl_atr'] = original * self.state.sl_multiplier
            logger.debug(f"Protection Mode: sl_atr {original} → {adjusted['sl_atr']}")

        if 'stop_loss_bps' in adjusted:
            original = adjusted['stop_loss_bps']
            adjusted['stop_loss_bps'] = original * self.state.sl_multiplier
            logger.debug(f"Protection Mode: stop_loss_bps {original} → {adjusted['stop_loss_bps']}")

        # Adjust take profit (optional tightening)
        if self.state.tp_multiplier != 1.0:
            if 'tp1_atr' in adjusted:
                adjusted['tp1_atr'] *= self.state.tp_multiplier
            if 'tp2_atr' in adjusted:
                adjusted['tp2_atr'] *= self.state.tp_multiplier
            if 'target_bps' in adjusted:
                adjusted['target_bps'] *= self.state.tp_multiplier

        # Adjust rate limits
        if 'max_trades_per_minute' in adjusted:
            original = adjusted['max_trades_per_minute']
            adjusted['max_trades_per_minute'] = max(1, int(original * self.state.rate_multiplier))
            logger.debug(f"Protection Mode: max_trades_per_minute {original} → {adjusted['max_trades_per_minute']}")

        if 'max_trades_per_hour' in adjusted:
            original = adjusted['max_trades_per_hour']
            adjusted['max_trades_per_hour'] = max(1, int(original * self.state.rate_multiplier))

        return adjusted

    def is_active(self) -> bool:
        """Check if protection mode is currently active"""
        return self.state.status in [ProtectionModeStatus.ENABLED, ProtectionModeStatus.FORCE_ENABLED]

    def record_trade(self, trade: Dict):
        """Record a trade for tracking P&L and updating win streak"""
        if self.is_active():
            self.state.trades_since_activation += 1
            self.state.pnl_since_activation += trade.get('pnl_usd', 0.0)

        # Add to recent trades for win streak calculation
        self.recent_trades.insert(0, trade)

        # Keep only last 20 trades
        self.recent_trades = self.recent_trades[:20]

        # Recalculate win streak
        self.state.current_win_streak = self._calculate_win_streak()


def create_protection_mode_from_config(
    config_dict: Dict,
    redis_client: Optional[aioredis.Redis] = None,
    starting_equity: float = 10000.0
) -> ProtectionModeManager:
    """
    Create ProtectionModeManager from config dictionary

    Args:
        config_dict: Config section for protection_mode
        redis_client: Optional Redis client for state publishing
        starting_equity: Starting account equity

    Returns:
        Configured ProtectionModeManager instance
    """
    pm_config = ProtectionModeConfig(
        enabled=config_dict.get('enabled', True),
        force_enabled=config_dict.get('force_enabled'),
        equity_threshold_usd=config_dict.get('equity_threshold_usd', 18000.0),
        win_streak_threshold=config_dict.get('win_streak_threshold', 5),
        risk_multiplier=config_dict.get('risk_multiplier', 0.5),
        sl_multiplier=config_dict.get('sl_multiplier', 0.7),
        tp_multiplier=config_dict.get('tp_multiplier', 1.0),
        rate_multiplier=config_dict.get('rate_multiplier', 0.5),
        deactivate_on_loss=config_dict.get('deactivate_on_loss', False),
        deactivate_below_equity=config_dict.get('deactivate_below_equity'),
        alert_on_activation=config_dict.get('alert_on_activation', True),
        alert_on_deactivation=config_dict.get('alert_on_deactivation', True),
    )

    return ProtectionModeManager(
        config=pm_config,
        redis_client=redis_client,
        starting_equity=starting_equity
    )
