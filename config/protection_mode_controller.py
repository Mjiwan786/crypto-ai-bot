"""
Protection Mode Controller

Automatic risk reduction when:
- Equity >= $18,000 (protect profits)
- Win streak >= threshold (prevent overconfidence)

Protection Mode Effects:
- Halve position sizes (0.5x multiplier)
- Tighten stops (reduce by 30%)
- Reduce max trades/min (50% reduction)

Features:
- Manual YAML toggle
- Runtime override via Redis
- Auto-switching based on equity/streak
- Change callbacks for hot-reload

Author: Crypto AI Bot Team
Date: 2025-11-08
"""

import os
import time
import logging
from datetime import datetime
from typing import Dict, Optional, Callable
from dataclasses import dataclass
from pathlib import Path
import yaml

try:
    import redis.asyncio as redis
except ImportError:
    import redis

logger = logging.getLogger(__name__)


@dataclass
class ProtectionModeConfig:
    """Protection mode configuration."""

    # Mode state
    enabled: bool = False
    auto_enable: bool = True  # Auto-enable based on triggers
    manual_override: bool = False  # Manual override (ignores triggers)

    # Triggers
    equity_threshold_usd: float = 18000.0
    win_streak_threshold: int = 5

    # Protection parameters
    position_size_multiplier: float = 0.5  # Halve sizes
    stop_loss_tightening_pct: float = 0.3  # 30% tighter stops
    max_trades_per_minute_reduction_pct: float = 0.5  # 50% reduction

    # State tracking
    current_equity_usd: float = 0.0
    current_win_streak: int = 0
    entered_at: Optional[str] = None
    trigger_reason: Optional[str] = None

    # Metadata
    last_updated: Optional[str] = None
    controlled_by: str = "auto"  # auto | manual


class ProtectionModeController:
    """
    Protection Mode Controller

    Automatically reduces risk when equity or win streak reaches thresholds.
    Supports manual override and runtime configuration via Redis.
    """

    def __init__(
        self,
        redis_url: Optional[str] = None,
        config_file: str = "config/protection_mode.yaml"
    ):
        """
        Initialize protection mode controller.

        Args:
            redis_url: Redis connection URL (optional for offline mode)
            config_file: Path to main config YAML
        """
        self.config = ProtectionModeConfig()
        self.config_file = Path(config_file)

        # Redis connection (optional)
        self.redis_url = redis_url or os.getenv(
            'REDIS_URL',
            'rediss://default:Salam78614**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818'
        )
        self.redis = None

        # Change callbacks
        self.callbacks = []

        # Statistics
        self.total_time_in_protection_seconds = 0
        self._protection_start_time = None

        logger.info("[ProtectionMode] Controller initialized")

    async def connect_redis(self):
        """Connect to Redis for live updates."""
        try:
            self.redis = await redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_timeout=10,
            )
            await self.redis.ping()
            logger.info("[ProtectionMode] Connected to Redis")
            return True
        except Exception as e:
            logger.warning(f"[ProtectionMode] Redis connection failed: {e}")
            return False

    def load_from_yaml(self):
        """Load configuration from YAML file."""
        if not self.config_file.exists():
            logger.warning(f"[ProtectionMode] Config file not found: {self.config_file}")
            return False

        try:
            with open(self.config_file, 'r') as f:
                yaml_config = yaml.safe_load(f)

            # Load protection mode config
            protection = yaml_config.get('protection_mode', {})

            if not protection:
                logger.info("[ProtectionMode] No protection_mode section in YAML, using defaults")
                return True

            self.config.enabled = protection.get('enabled', False)
            self.config.auto_enable = protection.get('auto_enable', True)
            self.config.manual_override = protection.get('manual_override', False)

            triggers = protection.get('triggers', {})
            self.config.equity_threshold_usd = triggers.get('equity_threshold_usd', 18000.0)
            self.config.win_streak_threshold = triggers.get('win_streak_threshold', 5)

            params = protection.get('parameters', {})
            self.config.position_size_multiplier = params.get('position_size_multiplier', 0.5)
            self.config.stop_loss_tightening_pct = params.get('stop_loss_tightening_pct', 0.3)
            self.config.max_trades_per_minute_reduction_pct = params.get(
                'max_trades_per_minute_reduction_pct', 0.5
            )

            logger.info("[ProtectionMode] Configuration loaded from YAML")
            return True

        except Exception as e:
            logger.error(f"[ProtectionMode] Failed to load YAML: {e}")
            return False

    def update_equity(self, equity_usd: float):
        """
        Update current equity and check if protection mode should be triggered.

        Args:
            equity_usd: Current account equity in USD
        """
        self.config.current_equity_usd = equity_usd

        # Check if protection mode should be auto-enabled
        if self.config.auto_enable and not self.config.manual_override:
            if equity_usd >= self.config.equity_threshold_usd:
                if not self.config.enabled:
                    self._enable_protection_mode(f"Equity ${equity_usd:.2f} >= ${self.config.equity_threshold_usd:.2f}")
            else:
                # Auto-disable if equity drops below threshold (with 5% hysteresis)
                hysteresis_threshold = self.config.equity_threshold_usd * 0.95
                if self.config.enabled and equity_usd < hysteresis_threshold:
                    if self.config.trigger_reason and 'Equity' in self.config.trigger_reason:
                        self._disable_protection_mode(f"Equity ${equity_usd:.2f} < ${hysteresis_threshold:.2f} (hysteresis)")

    def update_win_streak(self, win_streak: int):
        """
        Update current win streak and check if protection mode should be triggered.

        Args:
            win_streak: Current consecutive wins
        """
        self.config.current_win_streak = win_streak

        # Check if protection mode should be auto-enabled
        if self.config.auto_enable and not self.config.manual_override:
            if win_streak >= self.config.win_streak_threshold:
                if not self.config.enabled:
                    self._enable_protection_mode(f"Win streak {win_streak} >= {self.config.win_streak_threshold}")
            else:
                # Auto-disable if streak breaks (only if triggered by streak)
                if self.config.enabled and win_streak == 0:
                    if self.config.trigger_reason and 'streak' in self.config.trigger_reason.lower():
                        self._disable_protection_mode(f"Win streak broken (reset to {win_streak})")

    def _enable_protection_mode(self, reason: str):
        """Enable protection mode."""
        self.config.enabled = True
        self.config.entered_at = datetime.now().isoformat()
        self.config.trigger_reason = reason
        self.config.last_updated = datetime.now().isoformat()
        self._protection_start_time = time.time()

        logger.warning(f"[PROTECTION MODE ENABLED] {reason}")
        logger.warning(f"  Position Size: 0.5x (halved)")
        logger.warning(f"  Stops: -30% tighter")
        logger.warning(f"  Max Trades/Min: -50%")

        # Notify callbacks
        self._notify_change('protection_mode_enabled', True)

    def _disable_protection_mode(self, reason: str):
        """Disable protection mode."""
        # Track time in protection
        if self._protection_start_time:
            duration = time.time() - self._protection_start_time
            self.total_time_in_protection_seconds += duration
            self._protection_start_time = None

        self.config.enabled = False
        self.config.last_updated = datetime.now().isoformat()

        logger.info(f"[PROTECTION MODE DISABLED] {reason}")
        logger.info(f"  Returning to normal risk parameters")

        # Notify callbacks
        self._notify_change('protection_mode_enabled', False)

    def enable_manual_override(self):
        """Manually enable protection mode (ignores triggers)."""
        self.config.manual_override = True
        self.config.controlled_by = "manual"

        if not self.config.enabled:
            self._enable_protection_mode("Manual override")

        logger.info("[PROTECTION MODE] Manual override enabled")

    def disable_manual_override(self):
        """Disable manual override (return to auto mode)."""
        was_enabled = self.config.enabled

        self.config.manual_override = False
        self.config.controlled_by = "auto"

        logger.info("[PROTECTION MODE] Manual override disabled, returning to auto mode")

        # Disable protection mode first if it was only enabled due to manual override
        if was_enabled:
            self._disable_protection_mode("Manual override disabled")

        # Re-check triggers to see if it should auto-enable
        self.update_equity(self.config.current_equity_usd)
        self.update_win_streak(self.config.current_win_streak)

    def force_enable(self):
        """Force enable protection mode (manual trigger)."""
        if not self.config.enabled:
            self._enable_protection_mode("Manual force enable")

    def force_disable(self):
        """Force disable protection mode (manual trigger)."""
        if self.config.enabled:
            self._disable_protection_mode("Manual force disable")

    def register_callback(self, callback: Callable[[str, any], None]):
        """
        Register a callback for configuration changes.

        Args:
            callback: Function to call on config change (param_name, new_value)
        """
        self.callbacks.append(callback)
        logger.info(f"[ProtectionMode] Registered callback: {callback.__name__}")

    def _notify_change(self, param_name: str, new_value: any):
        """Notify all callbacks of a configuration change."""
        for callback in self.callbacks:
            try:
                callback(param_name, new_value)
            except Exception as e:
                logger.error(f"[ProtectionMode] Callback error: {e}")

    async def publish_status_update(self):
        """Publish current status to Redis."""
        if not self.redis:
            return False

        try:
            # Calculate total protection time including current session
            total_protection_seconds = self.total_time_in_protection_seconds
            if self._protection_start_time:
                total_protection_seconds += (time.time() - self._protection_start_time)

            status_data = {
                'enabled': str(self.config.enabled),
                'auto_enable': str(self.config.auto_enable),
                'manual_override': str(self.config.manual_override),
                'current_equity_usd': str(self.config.current_equity_usd),
                'equity_threshold_usd': str(self.config.equity_threshold_usd),
                'current_win_streak': str(self.config.current_win_streak),
                'win_streak_threshold': str(self.config.win_streak_threshold),
                'trigger_reason': self.config.trigger_reason or '',
                'entered_at': self.config.entered_at or '',
                'total_protection_hours': str(total_protection_seconds / 3600),
                'position_size_multiplier': str(self.config.position_size_multiplier),
                'last_updated': datetime.now().isoformat(),
            }

            await self.redis.xadd('protection:status', status_data, maxlen=1000)
            return True

        except Exception as e:
            logger.error(f"[ProtectionMode] Failed to publish status: {e}")
            return False

    async def subscribe_to_commands(self):
        """Subscribe to protection mode command stream."""
        if not self.redis:
            logger.warning("[ProtectionMode] No Redis connection for subscription")
            return

        stream_name = "protection:commands"
        last_id = "0"

        logger.info("[ProtectionMode] Subscribing to command stream")

        while True:
            try:
                messages = await self.redis.xread({stream_name: last_id}, count=10, block=1000)

                for stream, entries in messages:
                    for msg_id, data in entries:
                        last_id = msg_id
                        await self._process_command(data)

            except Exception as e:
                logger.error(f"[ProtectionMode] Stream read error: {e}")
                await asyncio.sleep(1)

    async def _process_command(self, data: Dict):
        """Process command from Redis."""
        command = data.get('command')

        if command == 'enable':
            self.force_enable()
        elif command == 'disable':
            self.force_disable()
        elif command == 'enable_manual_override':
            self.enable_manual_override()
        elif command == 'disable_manual_override':
            self.disable_manual_override()
        elif command == 'update_equity':
            equity = float(data.get('equity_usd', 0))
            self.update_equity(equity)
        elif command == 'update_win_streak':
            streak = int(data.get('win_streak', 0))
            self.update_win_streak(streak)

        await self.publish_status_update()

    def get_adjusted_parameters(self, base_params: Dict) -> Dict:
        """
        Get adjusted parameters based on protection mode state.

        Args:
            base_params: Base trading parameters

        Returns:
            Adjusted parameters with protection mode applied
        """
        if not self.config.enabled:
            return base_params

        adjusted = base_params.copy()

        # Halve position size
        if 'position_size_usd' in adjusted:
            adjusted['position_size_usd'] *= self.config.position_size_multiplier
        if 'base_risk_pct' in adjusted:
            adjusted['base_risk_pct'] *= self.config.position_size_multiplier

        # Tighten stops (reduce stop distance by 30%)
        if 'stop_loss_bps' in adjusted:
            adjusted['stop_loss_bps'] *= (1 - self.config.stop_loss_tightening_pct)
        if 'stop_loss_pct' in adjusted:
            adjusted['stop_loss_pct'] *= (1 - self.config.stop_loss_tightening_pct)

        # Reduce max trades per minute
        if 'max_trades_per_minute' in adjusted:
            adjusted['max_trades_per_minute'] = int(
                adjusted['max_trades_per_minute'] * (1 - self.config.max_trades_per_minute_reduction_pct)
            )

        return adjusted

    def get_current_config(self) -> Dict:
        """Get current configuration as dictionary."""
        # Calculate total protection time including current session
        total_protection_seconds = self.total_time_in_protection_seconds
        if self._protection_start_time:
            total_protection_seconds += (time.time() - self._protection_start_time)

        return {
            'enabled': self.config.enabled,
            'auto_enable': self.config.auto_enable,
            'manual_override': self.config.manual_override,
            'equity_threshold_usd': self.config.equity_threshold_usd,
            'win_streak_threshold': self.config.win_streak_threshold,
            'current_equity_usd': self.config.current_equity_usd,
            'current_win_streak': self.config.current_win_streak,
            'position_size_multiplier': self.config.position_size_multiplier,
            'stop_loss_tightening_pct': self.config.stop_loss_tightening_pct,
            'max_trades_per_minute_reduction_pct': self.config.max_trades_per_minute_reduction_pct,
            'trigger_reason': self.config.trigger_reason,
            'entered_at': self.config.entered_at,
            'total_protection_hours': total_protection_seconds / 3600,
            'last_updated': self.config.last_updated,
            'controlled_by': self.config.controlled_by,
        }

    def get_status_summary(self) -> str:
        """Get human-readable status summary."""
        lines = []
        lines.append("="*60)
        lines.append("PROTECTION MODE STATUS")
        lines.append("="*60)

        status = "[ACTIVE]" if self.config.enabled else "[INACTIVE]"
        lines.append(f"Status: {status}")

        if self.config.enabled:
            lines.append(f"  Trigger: {self.config.trigger_reason}")
            lines.append(f"  Entered: {self.config.entered_at}")
            lines.append(f"  Position Size: {self.config.position_size_multiplier}x")
            lines.append(f"  Stops: {self.config.stop_loss_tightening_pct * 100:.0f}% tighter")
            lines.append(f"  Max Trades/Min: {self.config.max_trades_per_minute_reduction_pct * 100:.0f}% reduced")

        lines.append(f"\nCurrent State:")
        lines.append(f"  Equity: ${self.config.current_equity_usd:.2f} (threshold: ${self.config.equity_threshold_usd:.2f})")
        lines.append(f"  Win Streak: {self.config.current_win_streak} (threshold: {self.config.win_streak_threshold})")

        lines.append(f"\nConfiguration:")
        lines.append(f"  Auto Enable: {'Yes' if self.config.auto_enable else 'No'}")
        lines.append(f"  Manual Override: {'Yes' if self.config.manual_override else 'No'}")
        lines.append(f"  Controlled By: {self.config.controlled_by}")

        total_hours = self.total_time_in_protection_seconds / 3600
        if self._protection_start_time:
            total_hours += (time.time() - self._protection_start_time) / 3600
        lines.append(f"\nTotal Time in Protection: {total_hours:.2f} hours")

        lines.append("="*60)
        return "\n".join(lines)


# Singleton instance
_protection_controller_instance = None


def get_protection_controller() -> ProtectionModeController:
    """Get singleton protection mode controller instance."""
    global _protection_controller_instance
    if _protection_controller_instance is None:
        _protection_controller_instance = ProtectionModeController()
        _protection_controller_instance.load_from_yaml()
    return _protection_controller_instance


# Example usage
if __name__ == '__main__':
    # Initialize controller
    controller = ProtectionModeController()
    controller.load_from_yaml()

    print(controller.get_status_summary())

    # Simulate equity increase
    print("\nSimulating equity increase to $20,000...")
    controller.update_equity(20000.0)
    print(controller.get_status_summary())

    # Simulate win streak
    print("\nSimulating 6-win streak...")
    controller.update_win_streak(6)
    print(controller.get_status_summary())

    # Test parameter adjustment
    base_params = {
        'position_size_usd': 1000.0,
        'base_risk_pct': 1.5,
        'stop_loss_bps': 20.0,
        'max_trades_per_minute': 8,
    }

    print("\nBase Parameters:")
    for k, v in base_params.items():
        print(f"  {k}: {v}")

    adjusted = controller.get_adjusted_parameters(base_params)
    print("\nProtection Mode Adjusted Parameters:")
    for k, v in adjusted.items():
        print(f"  {k}: {v}")
