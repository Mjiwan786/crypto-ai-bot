"""
Risk Manager with Event Guard Integration

Extends the base RiskManager with event guard functionality:
- Pre-event blackout periods (60s before major events)
- Post-event momentum allowance (10s after, 1.3x size)
- Symbol-specific allowlists for exchange listings
- Audit logging for all event-related decisions

Usage:
    from agents.risk.risk_manager_with_events import RiskManagerWithEvents

    risk_manager = RiskManagerWithEvents(
        redis_manager=redis,
        logger=logger,
    )

    # Check if entry is allowed (includes event guard)
    decision = risk_manager.check_entry_allowed(symbol="BTC/USD")

    # Size position (applies event-based multipliers)
    position = risk_manager.size_position_with_events(
        signal=signal,
        equity_usd=equity,
    )

Author: Crypto AI Bot Team
Date: 2025-11-08
"""

import logging
from typing import Optional
from decimal import Decimal

from agents.risk_manager import RiskManager, RiskConfig, SignalInput, PositionSize
from agents.risk.event_guard import EventGuard, EventGuardDecision, create_event_guard


class RiskManagerWithEvents:
    """
    Risk manager with integrated event guard.

    Combines:
    - Base risk management (position sizing, portfolio caps, drawdowns)
    - Event guard (pre-event blackouts, post-event momentum)
    """

    def __init__(
        self,
        risk_config: Optional[RiskConfig] = None,
        event_guard: Optional[EventGuard] = None,
        redis_manager=None,
        logger=None,
    ):
        """
        Initialize risk manager with event guard.

        Args:
            risk_config: Risk configuration
            event_guard: EventGuard instance (created if None)
            redis_manager: Redis client
            logger: Logger instance
        """
        self.logger = logger or logging.getLogger(__name__)

        # Base risk manager
        self.risk_manager = RiskManager(config=risk_config)

        # Event guard
        if event_guard is None:
            event_guard = create_event_guard(
                redis_manager=redis_manager,
                logger=self.logger,
            )
        self.event_guard = event_guard

        self.logger.info(
            f"RiskManagerWithEvents initialized: "
            f"event_guard_enabled={self.event_guard.enabled}"
        )

    def check_entry_allowed(
        self,
        symbol: str,
        current_time: Optional[float] = None,
    ) -> EventGuardDecision:
        """
        Check if new entry is allowed for symbol (event guard only).

        This is a pre-check before sizing. If entry is not allowed,
        position sizing should be skipped entirely.

        Args:
            symbol: Trading symbol
            current_time: Current timestamp (default: now)

        Returns:
            EventGuardDecision with allowed status
        """
        return self.event_guard.check_entry_allowed(
            symbol=symbol,
            current_time=current_time,
        )

    def size_position_with_events(
        self,
        signal: SignalInput,
        equity_usd: Decimal,
        volatility: Optional[Decimal] = None,
        current_time: Optional[float] = None,
    ) -> PositionSize:
        """
        Size position with event guard integration.

        Flow:
            1. Check event guard (blackout/momentum)
            2. If blackout: reject immediately
            3. If momentum window: apply size multiplier (≤1.3x)
            4. Call base risk manager for sizing
            5. Apply momentum multiplier to final size

        Args:
            signal: Trading signal
            equity_usd: Current account equity
            volatility: Optional volatility for targeting
            current_time: Current timestamp (default: now)

        Returns:
            PositionSize with event-adjusted sizing
        """
        # Check event guard
        event_decision = self.event_guard.check_entry_allowed(
            symbol=signal.symbol,
            current_time=current_time,
        )

        # If entry blocked by event guard, reject immediately
        if not event_decision.allowed:
            # Return rejected position
            return PositionSize(
                position_size_usd=Decimal("0"),
                notional_usd=Decimal("0"),
                leverage=Decimal("0"),
                risk_usd=Decimal("0"),
                allowed=False,
                rejection_reasons=[f"Event guard: {event_decision.reason}"],
                sl_distance_pct=Decimal("0"),
                rr_ratio=Decimal("0"),
            )

        # Get base position size from risk manager
        base_position = self.risk_manager.size_position(
            signal=signal,
            equity_usd=equity_usd,
            volatility=volatility,
        )

        # If base position rejected, return as is
        if not base_position.allowed:
            return base_position

        # Apply momentum multiplier if in momentum window
        if event_decision.momentum_multiplier > 1.0:
            # Scale position size
            multiplier = Decimal(str(event_decision.momentum_multiplier))

            adjusted_position = PositionSize(
                position_size_usd=base_position.position_size_usd * multiplier,
                notional_usd=base_position.notional_usd * multiplier,
                leverage=base_position.leverage,  # Keep same leverage
                risk_usd=base_position.risk_usd * multiplier,
                allowed=True,
                rejection_reasons=[],
                sl_distance_pct=base_position.sl_distance_pct,
                rr_ratio=base_position.rr_ratio,
            )

            self.logger.info(
                f"Applied momentum multiplier {event_decision.momentum_multiplier}x: "
                f"${base_position.position_size_usd:.2f} → ${adjusted_position.position_size_usd:.2f} "
                f"({event_decision.reason})"
            )

            return adjusted_position

        # Normal trading - return base position
        return base_position

    def get_event_guard_status(self) -> dict:
        """
        Get event guard status.

        Returns:
            Event guard status dictionary
        """
        return self.event_guard.get_status()

    def get_upcoming_events(self, hours: int = 24):
        """
        Get upcoming events.

        Args:
            hours: Lookahead window in hours

        Returns:
            List of upcoming events
        """
        return self.event_guard.get_upcoming_events(hours=hours)

    # ========================================
    # Delegate to base risk manager
    # ========================================

    def check_portfolio_risk(self, positions, equity_usd):
        """Delegate to base risk manager."""
        return self.risk_manager.check_portfolio_risk(positions, equity_usd)

    def apply_drawdown_breakers(self, equity_curve, current_equity):
        """Delegate to base risk manager."""
        return self.risk_manager.apply_drawdown_breakers(equity_curve, current_equity)

    def get_drawdown_state(self):
        """Get current drawdown state."""
        return self.risk_manager._drawdown_state

    def get_metrics(self):
        """Get risk manager metrics."""
        return self.risk_manager._metrics

    def get_config(self):
        """Get risk configuration."""
        return self.risk_manager.config


def create_risk_manager_with_events(
    risk_config: Optional[RiskConfig] = None,
    event_guard: Optional[EventGuard] = None,
    redis_manager=None,
    logger=None,
) -> RiskManagerWithEvents:
    """
    Create risk manager with event guard.

    Args:
        risk_config: Risk configuration
        event_guard: EventGuard instance (created if None)
        redis_manager: Redis client
        logger: Logger instance

    Returns:
        RiskManagerWithEvents instance
    """
    return RiskManagerWithEvents(
        risk_config=risk_config,
        event_guard=event_guard,
        redis_manager=redis_manager,
        logger=logger,
    )
