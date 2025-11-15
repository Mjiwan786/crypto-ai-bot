"""
Overnight Momentum Agent

Integrates overnight momentum strategy with the main trading system.
Handles signal generation, position management, and Redis publishing.

Author: Crypto AI Bot Team
Date: 2025-11-08
"""

import os
import time
import logging
from typing import Dict, List, Optional
from decimal import Decimal
from dataclasses import asdict

from strategies.overnight_momentum import (
    create_overnight_momentum_strategy,
    OvernightMomentumStrategy,
    OvernightSignal,
)
from strategies.overnight_position_manager import (
    create_overnight_position_manager,
    OvernightPositionManager,
)


class OvernightAgent:
    """
    Agent wrapper for overnight momentum strategy.

    Integrates with main trading system via:
    - Redis for signal publishing
    - Position tracking
    - Risk management
    """

    def __init__(
        self,
        redis_manager=None,
        logger=None,
        enabled: bool = None,
        backtest_only: bool = True,
        spot_notional_multiplier: float = 2.0,
        risk_per_trade_pct: float = 1.0,
    ):
        """
        Initialize overnight agent.

        Args:
            redis_manager: Redis client
            logger: Logger instance
            enabled: Enable strategy (default: from env)
            backtest_only: Backtest mode only (default: True)
            spot_notional_multiplier: Leverage proxy multiplier (default: 2.0)
            risk_per_trade_pct: Risk per trade percentage (default: 1.0)
        """
        self.redis = redis_manager
        self.logger = logger or logging.getLogger(__name__)

        # Feature flag
        if enabled is None:
            self.enabled = os.getenv("OVERNIGHT_MOMENTUM_ENABLED", "false").lower() == "true"
        else:
            self.enabled = enabled

        self.backtest_only = backtest_only
        self.risk_per_trade_pct = Decimal(str(risk_per_trade_pct))

        # Create strategy and position manager
        self.strategy = create_overnight_momentum_strategy(
            redis_manager=redis_manager,
            logger=logger,
            enabled=self.enabled,
            backtest_only=backtest_only,
        )

        self.position_manager = create_overnight_position_manager(
            redis_manager=redis_manager,
            logger=logger,
            spot_notional_multiplier=spot_notional_multiplier,
        )

        # State
        self.last_signal_time: Dict[str, float] = {}  # symbol -> timestamp
        self.signal_cooldown_seconds = 300  # 5 minutes between signals

        if not self.enabled:
            self.logger.info("OvernightAgent disabled")
        else:
            self.logger.info(
                f"OvernightAgent enabled: "
                f"backtest_only={backtest_only}, "
                f"leverage_proxy={spot_notional_multiplier}x"
            )

    def process_bar(
        self,
        symbol: str,
        current_price: Decimal,
        prices: List[Decimal],
        volumes: List[float],
        avg_24h_volume: float,
        equity_usd: Decimal,
        current_time: Optional[float] = None,
    ) -> Optional[Dict]:
        """
        Process new bar and generate signals.

        Args:
            symbol: Trading symbol
            current_price: Current price
            prices: Recent prices (20+ bars)
            volumes: Recent volumes
            avg_24h_volume: 24h average volume
            equity_usd: Current equity
            current_time: Current timestamp

        Returns:
            Action dictionary or None
        """
        if not self.enabled:
            return None

        if current_time is None:
            current_time = time.time()

        # Update trailing stops for active positions
        if self.position_manager.get_position(symbol):
            self.position_manager.update_trailing_stop(symbol, current_price)

            # Check for exit
            should_exit, exit_reason = self.position_manager.check_exit(
                symbol=symbol,
                current_price=current_price,
            )

            if should_exit:
                exit_summary = self.position_manager.close_position(
                    symbol=symbol,
                    exit_price=current_price,
                    reason=exit_reason,
                )

                if exit_summary:
                    self.logger.info(
                        f"Position exited: {symbol} {exit_summary['side'].upper()} "
                        f"P&L={exit_summary['pnl_pct']:+.2f}%, reason={exit_reason}"
                    )

                    # Publish exit to Redis
                    if self.redis:
                        try:
                            self.redis.publish_event("overnight:exits", exit_summary)
                        except Exception as e:
                            self.logger.error(f"Error publishing exit: {e}")

                    return {
                        "action": "exit",
                        "symbol": symbol,
                        "exit_price": float(current_price),
                        "exit_reason": exit_reason,
                        "pnl_pct": exit_summary['pnl_pct'],
                    }

        # Check for new signal (only if no active position)
        if not self.position_manager.get_position(symbol):
            # Check signal cooldown
            last_signal = self.last_signal_time.get(symbol, 0)
            if current_time - last_signal < self.signal_cooldown_seconds:
                return None

            # Generate signal
            signal = self.strategy.generate_signal(
                symbol=symbol,
                current_price=current_price,
                prices=prices,
                volumes=volumes,
                avg_24h_volume=avg_24h_volume,
                current_time=current_time,
            )

            if signal:
                # Calculate position size
                position_size_usd = self.position_manager.calculate_position_size(
                    signal=signal,
                    equity_usd=equity_usd,
                    risk_per_trade_pct=self.risk_per_trade_pct,
                )

                # Open position
                position = self.position_manager.open_position(
                    signal=signal,
                    position_size_usd=position_size_usd,
                )

                self.last_signal_time[symbol] = current_time

                self.logger.info(
                    f"Signal generated: {symbol} {signal.side.upper()} @ ${current_price:.2f}, "
                    f"size=${position_size_usd:.2f}, target=${signal.target_price:.2f}"
                )

                # Publish signal to Redis
                if self.redis:
                    try:
                        signal_data = {
                            "signal_id": signal.signal_id,
                            "symbol": signal.symbol,
                            "side": signal.side,
                            "entry_price": float(signal.entry_price),
                            "target_price": float(signal.target_price),
                            "trailing_stop_pct": float(signal.trailing_stop_pct),
                            "confidence": float(signal.confidence),
                            "position_size_usd": float(position_size_usd),
                            "timestamp": signal.timestamp,
                            "metadata": signal.metadata,
                        }
                        self.redis.publish_event("overnight:signals", signal_data)
                    except Exception as e:
                        self.logger.error(f"Error publishing signal: {e}")

                return {
                    "action": "entry",
                    "symbol": symbol,
                    "side": signal.side,
                    "entry_price": float(signal.entry_price),
                    "target_price": float(signal.target_price),
                    "position_size_usd": float(position_size_usd),
                    "stop_loss": float(position.stop_loss),
                }

        return None

    def get_active_positions(self) -> List[Dict]:
        """Get all active positions."""
        positions = self.position_manager.get_all_positions()
        return [asdict(pos) for pos in positions]

    def get_position_count(self) -> int:
        """Get count of active positions."""
        return self.position_manager.get_position_count()

    def force_close_all(self, current_prices: Dict[str, Decimal], reason: str = "manual_close") -> List[Dict]:
        """
        Force close all positions.

        Args:
            current_prices: Dict of symbol -> current_price
            reason: Close reason

        Returns:
            List of exit summaries
        """
        exits = []
        for position in self.position_manager.get_all_positions():
            symbol = position.symbol
            if symbol in current_prices:
                exit_summary = self.position_manager.close_position(
                    symbol=symbol,
                    exit_price=current_prices[symbol],
                    reason=reason,
                )

                if exit_summary:
                    exits.append(exit_summary)
                    self.logger.info(
                        f"Force closed: {symbol} {exit_summary['side'].upper()} "
                        f"P&L={exit_summary['pnl_pct']:+.2f}%, reason={reason}"
                    )

        return exits

    def get_status(self) -> Dict:
        """Get agent status."""
        return {
            "enabled": self.enabled,
            "backtest_only": self.backtest_only,
            "active_positions": self.get_position_count(),
            "max_positions": 1,
            "risk_per_trade_pct": float(self.risk_per_trade_pct),
            "strategy_config": {
                "target_swing_min": self.strategy.target_swing_min_pct,
                "target_swing_max": self.strategy.target_swing_max_pct,
                "trailing_stop": self.strategy.trailing_stop_pct,
                "volume_percentile_max": self.strategy.volume_percentile_max,
                "momentum_threshold": self.strategy.momentum_threshold,
            },
        }


def create_overnight_agent(
    redis_manager=None,
    logger=None,
    enabled: bool = None,
    backtest_only: bool = True,
    spot_notional_multiplier: float = 2.0,
    risk_per_trade_pct: float = 1.0,
) -> OvernightAgent:
    """
    Create overnight agent.

    Args:
        redis_manager: Redis client
        logger: Logger instance
        enabled: Enable strategy
        backtest_only: Backtest mode only
        spot_notional_multiplier: Leverage proxy multiplier
        risk_per_trade_pct: Risk per trade percentage

    Returns:
        OvernightAgent instance
    """
    return OvernightAgent(
        redis_manager=redis_manager,
        logger=logger,
        enabled=enabled,
        backtest_only=backtest_only,
        spot_notional_multiplier=spot_notional_multiplier,
        risk_per_trade_pct=risk_per_trade_pct,
    )
