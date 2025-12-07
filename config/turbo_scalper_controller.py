"""
Turbo Scalper Controller

Dynamic configuration controller for turbo scalper with:
- Conditional 5s bar enablement based on latency
- News override control (4-hour test windows)
- Real-time configuration updates via Redis
- Integration with soak test orchestrator

Author: Crypto AI Bot Team
Date: 2025-11-08
"""

import os
import time
import logging
from datetime import datetime
from typing import Dict, Optional, Callable
from dataclasses import dataclass, field
from pathlib import Path
import yaml

try:
    import redis.asyncio as redis
except ImportError:
    import redis

logger = logging.getLogger(__name__)


@dataclass
class TurboScalperConfig:
    """Turbo scalper dynamic configuration."""

    # Timeframe control
    timeframe_15s_enabled: bool = True
    timeframe_5s_enabled: bool = False  # Conditional on latency
    timeframe_5s_latency_threshold_ms: float = 50.0

    # News override control
    news_override_enabled: bool = False
    news_override_position_multiplier: float = 2.0
    news_override_disable_stops: bool = True

    # Scalping parameters
    max_trades_per_minute: int = 4
    max_trades_per_minute_turbo: int = 8  # When 5s enabled
    target_bps_15s: float = 17.0
    target_bps_5s: float = 15.0
    stop_bps: float = 18.5

    # Risk parameters
    base_risk_pct: float = 1.35
    max_portfolio_heat_pct: float = 65.0

    # Trading mode
    trading_mode: str = "paper"  # paper | live

    # Metadata
    last_updated: Optional[str] = None
    controlled_by: str = "manual"  # manual | soak_test | autotune


@dataclass
class LatencyMonitor:
    """Monitor latency for conditional 5s enablement."""

    samples: list = field(default_factory=list)
    max_samples: int = 100
    avg_latency_ms: float = 0.0
    max_latency_ms: float = 0.0

    def record(self, latency_ms: float):
        """Record latency sample."""
        self.samples.append(latency_ms)
        if len(self.samples) > self.max_samples:
            self.samples.pop(0)

        self.avg_latency_ms = sum(self.samples) / len(self.samples)
        self.max_latency_ms = max(self.samples)

    def should_enable_5s(self, threshold_ms: float) -> bool:
        """Check if 5s bars should be enabled."""
        if len(self.samples) < 10:  # Need enough samples
            return False

        return self.avg_latency_ms < threshold_ms


class TurboScalperController:
    """
    Dynamic controller for turbo scalper configuration.

    Features:
    - Conditional 5s bar enablement based on latency
    - News override control
    - Real-time updates via Redis
    - Change callbacks for hot-reload
    """

    def __init__(
        self,
        redis_url: Optional[str] = None,
        config_file: str = "config/turbo_mode.yaml"
    ):
        """
        Initialize turbo scalper controller.

        Args:
            redis_url: Redis connection URL (optional for offline mode)
            config_file: Path to turbo mode YAML config
        """
        self.config = TurboScalperConfig()
        self.latency_monitor = LatencyMonitor()
        self.config_file = Path(config_file)

        # Redis connection (optional)
        self.redis_url = redis_url or os.getenv('REDIS_URL')
        if not self.redis_url:
            logger.warning("[TurboScalperController] No REDIS_URL provided - Redis features disabled")
        self.redis = None

        # Change callbacks
        self.callbacks = []

        # State
        self._5s_enabled_time_start = None
        self._total_5s_enabled_seconds = 0

        logger.info("[TurboScalperController] Initialized")

    async def connect_redis(self):
        """Connect to Redis for live updates."""
        try:
            self.redis = await redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_timeout=10,
            )
            await self.redis.ping()
            logger.info("[TurboScalperController] Connected to Redis")
            return True
        except Exception as e:
            logger.warning(f"[TurboScalperController] Redis connection failed: {e}")
            return False

    def load_from_yaml(self):
        """Load configuration from YAML file."""
        if not self.config_file.exists():
            logger.warning(f"[TurboScalperController] Config file not found: {self.config_file}")
            return False

        try:
            with open(self.config_file, 'r') as f:
                yaml_config = yaml.safe_load(f)

            # Load scalper config
            scalper = yaml_config.get('scalper', {})
            self.config.timeframe_15s_enabled = scalper.get('timeframe_seconds', 15) >= 15
            self.config.max_trades_per_minute = scalper.get('max_trades_per_minute_base', 4)
            self.config.max_trades_per_minute_turbo = scalper.get('max_trades_per_minute', 8)

            # Load news override config
            news = yaml_config.get('news_catalyst', {})
            self.config.news_override_enabled = news.get('enabled', False)
            major_override = news.get('major_news_override', {})
            self.config.news_override_disable_stops = major_override.get('disable_stop_losses', True)
            self.config.news_override_position_multiplier = major_override.get('position_size_multiplier', 2.0)

            # Load risk parameters
            risk = yaml_config.get('risk', {})
            self.config.base_risk_pct = risk.get('risk_per_trade_pct', 1.5)
            self.config.max_portfolio_heat_pct = risk.get('max_portfolio_heat_pct', 80.0)

            # Trading mode
            self.config.trading_mode = yaml_config.get('mode', 'PAPER').lower()

            logger.info("[TurboScalperController] Configuration loaded from YAML")
            return True

        except Exception as e:
            logger.error(f"[TurboScalperController] Failed to load YAML: {e}")
            return False

    def update_latency(self, latency_ms: float):
        """
        Update latency sample and check if 5s bars should be toggled.

        Args:
            latency_ms: Current latency in milliseconds
        """
        self.latency_monitor.record(latency_ms)

        should_enable = self.latency_monitor.should_enable_5s(
            self.config.timeframe_5s_latency_threshold_ms
        )

        # Toggle 5s bars based on latency
        if should_enable and not self.config.timeframe_5s_enabled:
            self._enable_5s_bars()
        elif not should_enable and self.config.timeframe_5s_enabled:
            self._disable_5s_bars()

    def _enable_5s_bars(self):
        """Enable 5s bars (latency is low enough)."""
        self.config.timeframe_5s_enabled = True
        self._5s_enabled_time_start = time.time()

        logger.info(
            f"[5S ENABLED] Latency {self.latency_monitor.avg_latency_ms:.1f}ms < "
            f"{self.config.timeframe_5s_latency_threshold_ms}ms"
        )

        # Notify callbacks
        self._notify_change('5s_bars_enabled', True)

    def _disable_5s_bars(self):
        """Disable 5s bars (latency too high)."""
        # Track time 5s was enabled BEFORE disabling
        if self._5s_enabled_time_start:
            duration = time.time() - self._5s_enabled_time_start
            self._total_5s_enabled_seconds += duration
            self._5s_enabled_time_start = None

        self.config.timeframe_5s_enabled = False

        logger.info(
            f"[5S DISABLED] Latency {self.latency_monitor.avg_latency_ms:.1f}ms >= "
            f"{self.config.timeframe_5s_latency_threshold_ms}ms "
            f"(Total 5s time: {self._total_5s_enabled_seconds / 3600:.3f}h)"
        )

        # Notify callbacks
        self._notify_change('5s_bars_enabled', False)

    def enable_news_override(self):
        """Enable news override mode (4-hour test window)."""
        self.config.news_override_enabled = True
        self.config.last_updated = datetime.now().isoformat()

        logger.info("[NEWS OVERRIDE ENABLED] Position multiplier: 2.0x, Stops disabled")
        self._notify_change('news_override_enabled', True)

    def disable_news_override(self):
        """Disable news override mode."""
        self.config.news_override_enabled = False
        self.config.last_updated = datetime.now().isoformat()

        logger.info("[NEWS OVERRIDE DISABLED] Returning to normal parameters")
        self._notify_change('news_override_enabled', False)

    def register_callback(self, callback: Callable[[str, any], None]):
        """
        Register a callback for configuration changes.

        Args:
            callback: Function to call on config change (param_name, new_value)
        """
        self.callbacks.append(callback)
        logger.info(f"[TurboScalperController] Registered callback: {callback.__name__}")

    def _notify_change(self, param_name: str, new_value: any):
        """Notify all callbacks of a configuration change."""
        for callback in self.callbacks:
            try:
                callback(param_name, new_value)
            except Exception as e:
                logger.error(f"[TurboScalperController] Callback error: {e}")

    async def publish_config_update(self):
        """Publish current configuration to Redis."""
        if not self.redis:
            return False

        try:
            config_data = {
                'timeframe_15s_enabled': str(self.config.timeframe_15s_enabled),
                'timeframe_5s_enabled': str(self.config.timeframe_5s_enabled),
                'news_override_enabled': str(self.config.news_override_enabled),
                'max_trades_per_minute': str(self.config.max_trades_per_minute),
                'avg_latency_ms': str(self.latency_monitor.avg_latency_ms),
                'total_5s_enabled_hours': str(self._total_5s_enabled_seconds / 3600),
                'last_updated': datetime.now().isoformat(),
            }

            await self.redis.xadd('turbo:config_updates', config_data, maxlen=1000)
            return True

        except Exception as e:
            logger.error(f"[TurboScalperController] Failed to publish config: {e}")
            return False

    async def subscribe_to_soak_test(self):
        """Subscribe to soak test control stream."""
        if not self.redis:
            logger.warning("[TurboScalperController] No Redis connection for subscription")
            return

        stream_name = "soak:config_control"
        last_id = "0"

        logger.info("[TurboScalperController] Subscribing to soak test control stream")

        while True:
            try:
                messages = await self.redis.xread({stream_name: last_id}, count=10, block=1000)

                for stream, entries in messages:
                    for msg_id, data in entries:
                        last_id = msg_id
                        await self._process_soak_test_command(data)

            except Exception as e:
                logger.error(f"[TurboScalperController] Stream read error: {e}")
                await asyncio.sleep(1)

    async def _process_soak_test_command(self, data: Dict):
        """Process command from soak test."""
        command = data.get('command')

        if command == 'enable_news_override':
            self.enable_news_override()
        elif command == 'disable_news_override':
            self.disable_news_override()
        elif command == 'update_latency':
            latency_ms = float(data.get('latency_ms', 0))
            self.update_latency(latency_ms)

        await self.publish_config_update()

    def get_current_config(self) -> Dict:
        """Get current configuration as dictionary."""
        # Calculate total 5s time including current session
        total_5s_seconds = self._total_5s_enabled_seconds
        if self._5s_enabled_time_start:
            total_5s_seconds += (time.time() - self._5s_enabled_time_start)

        return {
            'timeframe_15s_enabled': self.config.timeframe_15s_enabled,
            'timeframe_5s_enabled': self.config.timeframe_5s_enabled,
            'timeframe_5s_latency_threshold_ms': self.config.timeframe_5s_latency_threshold_ms,
            'news_override_enabled': self.config.news_override_enabled,
            'news_override_position_multiplier': self.config.news_override_position_multiplier,
            'max_trades_per_minute': self.config.max_trades_per_minute if not self.config.timeframe_5s_enabled else self.config.max_trades_per_minute_turbo,
            'target_bps': self.config.target_bps_5s if self.config.timeframe_5s_enabled else self.config.target_bps_15s,
            'stop_bps': self.config.stop_bps,
            'base_risk_pct': self.config.base_risk_pct,
            'max_portfolio_heat_pct': self.config.max_portfolio_heat_pct,
            'trading_mode': self.config.trading_mode,
            'avg_latency_ms': self.latency_monitor.avg_latency_ms,
            'max_latency_ms': self.latency_monitor.max_latency_ms,
            'total_5s_enabled_hours': total_5s_seconds / 3600,
            'last_updated': self.config.last_updated,
            'controlled_by': self.config.controlled_by,
        }

    def get_status_summary(self) -> str:
        """Get human-readable status summary."""
        lines = []
        lines.append("="*60)
        lines.append("TURBO SCALPER CONFIGURATION STATUS")
        lines.append("="*60)
        lines.append(f"Trading Mode: {self.config.trading_mode.upper()}")
        lines.append(f"15s Bars: {'ENABLED' if self.config.timeframe_15s_enabled else 'DISABLED'}")
        lines.append(f"5s Bars: {'ENABLED' if self.config.timeframe_5s_enabled else 'DISABLED'} (conditional)")
        lines.append(f"  Latency: {self.latency_monitor.avg_latency_ms:.1f}ms (threshold: {self.config.timeframe_5s_latency_threshold_ms}ms)")
        lines.append(f"  5s Enabled Time: {self._total_5s_enabled_seconds / 3600:.1f}h")
        lines.append(f"News Override: {'ENABLED' if self.config.news_override_enabled else 'DISABLED'}")
        if self.config.news_override_enabled:
            lines.append(f"  Position Multiplier: {self.config.news_override_position_multiplier}x")
            lines.append(f"  Stops Disabled: {self.config.news_override_disable_stops}")
        lines.append(f"Max Trades/Min: {self.config.max_trades_per_minute if not self.config.timeframe_5s_enabled else self.config.max_trades_per_minute_turbo}")
        lines.append(f"Target BPS: {self.config.target_bps_5s if self.config.timeframe_5s_enabled else self.config.target_bps_15s:.1f}")
        lines.append(f"Stop BPS: {self.config.stop_bps:.1f}")
        lines.append(f"Base Risk: {self.config.base_risk_pct:.2f}%")
        lines.append(f"Max Heat: {self.config.max_portfolio_heat_pct:.1f}%")
        lines.append(f"Controlled By: {self.config.controlled_by}")
        lines.append(f"Last Updated: {self.config.last_updated or 'Never'}")
        lines.append("="*60)
        return "\n".join(lines)


# Singleton instance
_controller_instance = None


def get_turbo_controller() -> TurboScalperController:
    """Get singleton turbo scalper controller instance."""
    global _controller_instance
    if _controller_instance is None:
        _controller_instance = TurboScalperController()
        _controller_instance.load_from_yaml()
    return _controller_instance


# Example usage
if __name__ == '__main__':
    import asyncio

    async def main():
        # Initialize controller
        controller = TurboScalperController()
        controller.load_from_yaml()

        # Print initial status
        print(controller.get_status_summary())

        # Simulate latency updates
        print("\nSimulating latency updates...")

        # Low latency - should enable 5s
        for i in range(15):
            controller.update_latency(45.0 + i * 0.5)
        print(controller.get_status_summary())

        # High latency - should disable 5s
        for i in range(15):
            controller.update_latency(55.0 + i * 0.5)
        print(controller.get_status_summary())

        # Enable news override
        print("\nEnabling news override...")
        controller.enable_news_override()
        print(controller.get_status_summary())

        # Disable news override
        print("\nDisabling news override...")
        controller.disable_news_override()
        print(controller.get_status_summary())

    asyncio.run(main())
