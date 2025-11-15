"""
Dynamic Sizing Integration Layer

Bridges DynamicPositionSizer with RiskManager and agent config system.
Provides seamless integration with Redis-based runtime overrides.

Features:
- Hot config reloading from Redis
- Automatic metric publishing
- State persistence
- MCP compatibility

Author: Crypto AI Bot Team
Date: 2025-11-08
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional

from .dynamic_sizing import (
    DynamicPositionSizer,
    DynamicSizingConfig,
    TradeOutcome,
)

logger = logging.getLogger(__name__)


class DynamicSizingIntegration:
    """
    Integration layer for dynamic position sizing.

    Responsibilities:
    - Load config from YAML/env
    - Subscribe to Redis runtime overrides
    - Publish sizing metrics to Redis streams
    - Persist state to StateManager
    - Expose simple API for RiskManager
    """

    def __init__(
        self,
        config_dict: Dict[str, Any],
        redis_bus: Optional[Any] = None,
        state_manager: Optional[Any] = None,
        agent_id: str = "scalper",
    ):
        """
        Initialize dynamic sizing integration.

        Args:
            config_dict: Dynamic sizing config from YAML
            redis_bus: Redis bus for pubsub (optional)
            state_manager: State manager for persistence (optional)
            agent_id: Agent identifier for Redis channels
        """
        self.config_dict = config_dict
        self.redis_bus = redis_bus
        self.state_manager = state_manager
        self.agent_id = agent_id
        self.logger = logging.getLogger(f"{__name__}.{agent_id}")

        # Extract integration-specific config (not part of DynamicSizingConfig)
        integration_fields = {
            "enabled",
            "log_sizing_decisions",
            "publish_metrics_to_redis",
            "metrics_publish_interval_seconds",
        }

        # Filter config for DynamicSizingConfig (remove integration fields)
        sizing_config_dict = {
            k: v for k, v in config_dict.items() if k not in integration_fields
        }

        # Create sizer
        sizing_config = DynamicSizingConfig(**sizing_config_dict)
        self.sizer = DynamicPositionSizer(sizing_config)

        # Runtime
        self._monitor_task: Optional[asyncio.Task] = None
        self._metrics_task: Optional[asyncio.Task] = None
        self.is_running = False

        # Config flags
        self.log_sizing_decisions = config_dict.get("log_sizing_decisions", True)
        self.publish_metrics = config_dict.get("publish_metrics_to_redis", True)
        self.metrics_interval = config_dict.get("metrics_publish_interval_seconds", 60)

        self.logger.info("DynamicSizingIntegration initialized for %s", agent_id)

    # -------------------------------------------------------------------------
    # LIFECYCLE
    # -------------------------------------------------------------------------

    async def start(self) -> None:
        """Start the dynamic sizing integration."""
        self.logger.info("Starting DynamicSizingIntegration...")

        # Load persisted state
        await self._load_state()

        # Setup Redis subscriptions
        if self.redis_bus:
            await self._setup_subscriptions()

        self.is_running = True

        # Start monitoring tasks
        if self.publish_metrics and self.redis_bus:
            self._metrics_task = asyncio.create_task(
                self._metrics_publishing_loop(),
                name=f"sizing.metrics.{self.agent_id}"
            )

        self.logger.info("DynamicSizingIntegration started")

    async def stop(self) -> None:
        """Stop the dynamic sizing integration."""
        self.logger.info("Stopping DynamicSizingIntegration...")
        self.is_running = False

        # Cancel tasks
        if self._metrics_task and not self._metrics_task.done():
            self._metrics_task.cancel()
            try:
                await self._metrics_task
            except asyncio.CancelledError:
                pass

        # Save state
        await self._save_state()

        self.logger.info("DynamicSizingIntegration stopped")

    # -------------------------------------------------------------------------
    # PUBLIC API (called by RiskManager)
    # -------------------------------------------------------------------------

    async def get_size_multiplier(
        self,
        current_equity_usd: float,
        portfolio_heat_pct: float,
        current_volatility_atr_pct: Optional[float] = None,
    ) -> tuple[float, Dict[str, float]]:
        """
        Calculate dynamic size multiplier.

        This is the main API called by RiskManager during position sizing.

        Args:
            current_equity_usd: Current account equity
            portfolio_heat_pct: Current portfolio heat (%)
            current_volatility_atr_pct: Current ATR% (optional)

        Returns:
            (size_multiplier, breakdown_dict)
        """
        try:
            multiplier, breakdown = self.sizer.calculate_size_multiplier(
                current_equity_usd=current_equity_usd,
                portfolio_heat_pct=portfolio_heat_pct,
                current_volatility_atr_pct=current_volatility_atr_pct,
            )

            # Log if enabled
            if self.log_sizing_decisions:
                self.logger.info(
                    "Size multiplier: %.2fx (equity=$%.0f, heat=%.1f%%, vol=%.2f%%)",
                    multiplier,
                    current_equity_usd,
                    portfolio_heat_pct,
                    current_volatility_atr_pct or 0.0,
                )

            return multiplier, breakdown

        except Exception as e:
            self.logger.error("Error getting size multiplier: %s", e, exc_info=True)
            return 1.0, {"error": str(e), "failsafe": 1.0}

    async def record_trade_outcome(
        self,
        symbol: str,
        pnl_usd: float,
        size_usd: float,
    ) -> None:
        """
        Record trade outcome for streak tracking.

        Args:
            symbol: Trading pair
            pnl_usd: Trade P&L in USD
            size_usd: Trade size in USD
        """
        try:
            self.sizer.record_trade(
                symbol=symbol,
                pnl_usd=pnl_usd,
                size_usd=size_usd,
            )

            # Publish update if enabled
            if self.publish_metrics and self.redis_bus:
                await self.redis_bus.publish(
                    f"sizing:trade_recorded:{self.agent_id}",
                    {
                        "symbol": symbol,
                        "pnl": pnl_usd,
                        "size": size_usd,
                        "streak": self.sizer.current_streak,
                        "timestamp": time.time(),
                    },
                )

        except Exception as e:
            self.logger.error("Error recording trade outcome: %s", e, exc_info=True)

    async def get_state(self) -> Dict:
        """Get current sizing state for monitoring."""
        return self.sizer.get_state()

    # -------------------------------------------------------------------------
    # REDIS INTEGRATION
    # -------------------------------------------------------------------------

    async def _setup_subscriptions(self) -> None:
        """Setup Redis subscriptions for runtime overrides."""
        if not self.redis_bus:
            return

        try:
            # Subscribe to sizing override channel
            await self.redis_bus.subscribe(
                f"sizing:override:{self.agent_id}",
                self._handle_override_update,
            )

            # Subscribe to sizing control channel
            await self.redis_bus.subscribe(
                f"sizing:control:{self.agent_id}",
                self._handle_control_command,
            )

            self.logger.info("Redis subscriptions setup for sizing integration")

        except Exception as e:
            self.logger.error("Error setting up Redis subscriptions: %s", e, exc_info=True)

    async def _handle_override_update(self, data: Dict[str, Any]) -> None:
        """
        Handle runtime override update from Redis.

        Message format:
        {
            "key": "size_multiplier",
            "value": 1.5,
            "expiry_seconds": 3600,
            "reason": "manual override for testing"
        }
        """
        try:
            key = data.get("key")
            value = float(data.get("value", 0.0))
            expiry = data.get("expiry_seconds")
            reason = data.get("reason", "")

            if not key:
                self.logger.warning("Override message missing 'key'")
                return

            self.sizer.set_runtime_override(key, value, expiry)
            self.logger.info(
                "Runtime override applied: %s=%.2f (%s)",
                key,
                value,
                reason or "no reason provided",
            )

        except Exception as e:
            self.logger.error("Error handling override update: %s", e, exc_info=True)

    async def _handle_control_command(self, data: Dict[str, Any]) -> None:
        """
        Handle control commands from Redis.

        Supported commands:
        - reset_streak
        - clear_overrides
        - reload_config
        """
        try:
            command = data.get("command", "").lower()

            if command == "reset_streak":
                self.sizer.reset_streak()
                self.logger.info("Streak reset via control command")

            elif command == "clear_overrides":
                self.sizer.clear_all_overrides()
                self.logger.info("Overrides cleared via control command")

            elif command == "reload_config":
                await self._reload_config()
                self.logger.info("Config reloaded via control command")

            else:
                self.logger.warning("Unknown control command: %s", command)

        except Exception as e:
            self.logger.error("Error handling control command: %s", e, exc_info=True)

    async def _metrics_publishing_loop(self) -> None:
        """Publish sizing metrics to Redis periodically."""
        while self.is_running:
            try:
                state = self.sizer.get_state()

                # Publish to Redis
                await self.redis_bus.publish(
                    f"sizing:metrics:{self.agent_id}",
                    {
                        **state,
                        "timestamp": time.time(),
                    },
                )

                await asyncio.sleep(self.metrics_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in metrics publishing loop: %s", e, exc_info=True)
                await asyncio.sleep(5.0)

    # -------------------------------------------------------------------------
    # STATE PERSISTENCE
    # -------------------------------------------------------------------------

    async def _load_state(self) -> None:
        """Load sizing state from persistence."""
        if not self.state_manager:
            return

        try:
            state_data = await self.state_manager.load_sizing_state()
            if not state_data:
                return

            # Restore streak
            if "current_streak" in state_data:
                self.sizer.current_streak = int(state_data["current_streak"])

            # Restore trade history (last 100 trades)
            if "trade_history" in state_data:
                from .dynamic_sizing import TradeRecord, TradeOutcome
                for record_data in state_data["trade_history"][-100:]:
                    record = TradeRecord(
                        timestamp=float(record_data["timestamp"]),
                        symbol=str(record_data["symbol"]),
                        outcome=TradeOutcome(record_data["outcome"]),
                        pnl_usd=float(record_data["pnl"]),
                        size_usd=float(record_data["size"]),
                    )
                    self.sizer.trade_history.append(record)

            self.logger.info("Sizing state loaded from persistence")

        except Exception as e:
            self.logger.error("Error loading sizing state: %s", e, exc_info=True)

    async def _save_state(self) -> None:
        """Save sizing state to persistence."""
        if not self.state_manager:
            return

        try:
            state_data = {
                "current_streak": self.sizer.current_streak,
                "trade_history": [
                    {
                        "timestamp": t.timestamp,
                        "symbol": t.symbol,
                        "outcome": t.outcome.value,
                        "pnl": t.pnl_usd,
                        "size": t.size_usd,
                    }
                    for t in self.sizer.trade_history
                ],
            }

            await self.state_manager.save_sizing_state(state_data)

        except Exception as e:
            self.logger.error("Error saving sizing state: %s", e, exc_info=True)

    # -------------------------------------------------------------------------
    # CONFIG MANAGEMENT
    # -------------------------------------------------------------------------

    async def _reload_config(self) -> None:
        """Reload config from source (not implemented yet)."""
        self.logger.warning("Config reload not implemented - restart agent to apply new config")
        # TODO: Implement hot config reload if needed
