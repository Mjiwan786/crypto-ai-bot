"""
Overnight Position Manager

Manages overnight positions with:
- Leverage proxy (larger notional on spot, NO margin)
- Trailing stop updates
- Position tracking
- Exit execution

Author: Crypto AI Bot Team
Date: 2025-11-08
"""

import os
import time
import logging
from typing import Dict, List, Optional
from decimal import Decimal
from dataclasses import dataclass, asdict


@dataclass
class OvernightPosition:
    """Overnight position tracking."""
    position_id: str
    symbol: str
    side: str  # "long" or "short"
    entry_price: Decimal
    entry_time: float
    quantity: Decimal
    notional_usd: Decimal
    target_price: Decimal
    stop_loss: Decimal
    trailing_stop_pct: Decimal
    highest_price: Decimal  # For long trailing
    lowest_price: Decimal   # For short trailing
    metadata: Dict


class OvernightPositionManager:
    """
    Manages overnight positions with leverage proxy.

    Leverage Proxy:
    - Uses LARGER NOTIONAL on spot (not margin)
    - Example: $10k equity -> $20k notional on spot
    - NO margin borrowing (avoid overnight fees)
    """

    def __init__(
        self,
        redis_manager=None,
        logger=None,
        spot_notional_multiplier: float = 2.0,
        max_notional_multiplier: float = 3.0,
    ):
        """
        Initialize position manager.

        Args:
            redis_manager: Redis client
            logger: Logger instance
            spot_notional_multiplier: Notional multiplier for spot (default: 2.0x)
            max_notional_multiplier: Maximum multiplier (default: 3.0x)
        """
        self.redis = redis_manager
        self.logger = logger or logging.getLogger(__name__)

        # Leverage proxy configuration
        self.spot_notional_multiplier = min(spot_notional_multiplier, max_notional_multiplier)
        self.max_notional_multiplier = max_notional_multiplier

        # Positions tracking
        self.positions: Dict[str, OvernightPosition] = {}

        # Configuration
        self.use_margin = os.getenv("OVERNIGHT_USE_MARGIN", "false").lower() == "true"

        if self.use_margin:
            self.logger.warning("⚠️  MARGIN ENABLED for overnight positions (NOT RECOMMENDED)")
        else:
            self.logger.info(
                f"Leverage proxy configured: {self.spot_notional_multiplier}x notional on spot "
                f"(no margin)"
            )

    def calculate_position_size(
        self,
        signal,
        equity_usd: Decimal,
        risk_per_trade_pct: Decimal = Decimal("1.0"),
    ) -> Decimal:
        """
        Calculate position size using leverage proxy.

        Leverage Proxy Method:
        1. Calculate base position size (risk-based)
        2. Apply notional multiplier
        3. Ensure within limits

        Args:
            signal: Overnight signal
            equity_usd: Current equity
            risk_per_trade_pct: Risk per trade (default: 1%)

        Returns:
            Position size in USD
        """
        # Calculate base position size from risk
        entry_price = signal.entry_price
        trailing_stop_pct = signal.trailing_stop_pct

        # Risk amount
        risk_usd = equity_usd * (risk_per_trade_pct / Decimal("100"))

        # Position size from risk (base)
        # risk = position_size * (trailing_stop_pct / 100)
        # position_size = risk / (trailing_stop_pct / 100)
        base_position_size = risk_usd / (trailing_stop_pct / Decimal("100"))

        # Apply leverage proxy (larger notional on spot)
        if not self.use_margin:
            # Multiply notional (spot only)
            multiplier = Decimal(str(self.spot_notional_multiplier))
            position_size = base_position_size * multiplier

            self.logger.info(
                f"Leverage proxy applied: ${base_position_size:.2f} -> ${position_size:.2f} "
                f"({self.spot_notional_multiplier}x notional on spot)"
            )
        else:
            # Use margin (not recommended for overnight)
            position_size = base_position_size
            self.logger.warning("Using margin for overnight position (not recommended)")

        return position_size

    def open_position(
        self,
        signal,
        position_size_usd: Decimal,
    ) -> OvernightPosition:
        """
        Open overnight position.

        Args:
            signal: Overnight signal
            position_size_usd: Position size in USD

        Returns:
            OvernightPosition
        """
        # Calculate quantity
        quantity = position_size_usd / signal.entry_price

        # Initial stop loss (entry price - trailing stop %)
        if signal.side == "long":
            stop_loss = signal.entry_price * (
                Decimal("1") - signal.trailing_stop_pct / Decimal("100")
            )
            highest_price = signal.entry_price
            lowest_price = Decimal("0")
        else:  # short
            stop_loss = signal.entry_price * (
                Decimal("1") + signal.trailing_stop_pct / Decimal("100")
            )
            highest_price = Decimal("0")
            lowest_price = signal.entry_price

        # Create position
        position = OvernightPosition(
            position_id=signal.signal_id,
            symbol=signal.symbol,
            side=signal.side,
            entry_price=signal.entry_price,
            entry_time=signal.timestamp,
            quantity=quantity,
            notional_usd=position_size_usd,
            target_price=signal.target_price,
            stop_loss=stop_loss,
            trailing_stop_pct=signal.trailing_stop_pct,
            highest_price=highest_price,
            lowest_price=lowest_price,
            metadata=signal.metadata,
        )

        # Store position
        self.positions[signal.symbol] = position

        self.logger.info(
            f"Position opened: {signal.symbol} {signal.side.upper()} "
            f"@ ${signal.entry_price:.2f}, "
            f"qty={quantity:.4f}, notional=${position_size_usd:.2f}, "
            f"stop=${stop_loss:.2f}, target=${signal.target_price:.2f}"
        )

        # Publish to Redis
        if self.redis:
            try:
                self.redis.publish_event("overnight:positions", {
                    "action": "open",
                    **asdict(position)
                })
            except Exception as e:
                self.logger.error(f"Error publishing position to Redis: {e}")

        return position

    def update_trailing_stop(
        self,
        symbol: str,
        current_price: Decimal,
    ) -> bool:
        """
        Update trailing stop for position.

        Args:
            symbol: Symbol
            current_price: Current price

        Returns:
            True if stop was updated
        """
        if symbol not in self.positions:
            return False

        position = self.positions[symbol]
        old_stop = position.stop_loss

        if position.side == "long":
            # Update highest price
            if current_price > position.highest_price:
                position.highest_price = current_price

                # Calculate new stop
                new_stop = current_price * (
                    Decimal("1") - position.trailing_stop_pct / Decimal("100")
                )

                # Only raise the stop (never lower)
                if new_stop > position.stop_loss:
                    position.stop_loss = new_stop

                    self.logger.info(
                        f"Trailing stop updated (long): {symbol} "
                        f"${old_stop:.2f} -> ${new_stop:.2f} "
                        f"(price: ${current_price:.2f})"
                    )
                    return True

        else:  # short
            # Update lowest price
            if position.lowest_price == 0 or current_price < position.lowest_price:
                position.lowest_price = current_price

                # Calculate new stop
                new_stop = current_price * (
                    Decimal("1") + position.trailing_stop_pct / Decimal("100")
                )

                # Only lower the stop (never raise)
                if position.stop_loss == 0 or new_stop < position.stop_loss:
                    position.stop_loss = new_stop

                    self.logger.info(
                        f"Trailing stop updated (short): {symbol} "
                        f"${old_stop:.2f} -> ${new_stop:.2f} "
                        f"(price: ${current_price:.2f})"
                    )
                    return True

        return False

    def check_exit(
        self,
        symbol: str,
        current_price: Decimal,
    ) -> tuple[bool, str]:
        """
        Check if position should exit.

        Args:
            symbol: Symbol
            current_price: Current price

        Returns:
            (should_exit, reason)
        """
        if symbol not in self.positions:
            return False, ""

        position = self.positions[symbol]

        # Check target reached
        if position.side == "long":
            if current_price >= position.target_price:
                return True, "target_reached"
        else:  # short
            if current_price <= position.target_price:
                return True, "target_reached"

        # Check stop loss
        if position.side == "long":
            if current_price <= position.stop_loss:
                return True, "trailing_stop"
        else:  # short
            if current_price >= position.stop_loss:
                return True, "trailing_stop"

        return False, ""

    def close_position(
        self,
        symbol: str,
        exit_price: Decimal,
        reason: str,
    ) -> Optional[Dict]:
        """
        Close position.

        Args:
            symbol: Symbol
            exit_price: Exit price
            reason: Exit reason

        Returns:
            Position summary or None
        """
        if symbol not in self.positions:
            return None

        position = self.positions[symbol]

        # Calculate P&L
        if position.side == "long":
            pnl_pct = float((exit_price - position.entry_price) / position.entry_price) * 100
        else:  # short
            pnl_pct = float((position.entry_price - exit_price) / position.entry_price) * 100

        pnl_usd = position.notional_usd * Decimal(str(pnl_pct / 100))

        # Create summary
        summary = {
            "position_id": position.position_id,
            "symbol": position.symbol,
            "side": position.side,
            "entry_price": float(position.entry_price),
            "exit_price": float(exit_price),
            "entry_time": position.entry_time,
            "exit_time": time.time(),
            "hold_time_hours": (time.time() - position.entry_time) / 3600,
            "quantity": float(position.quantity),
            "notional_usd": float(position.notional_usd),
            "pnl_usd": float(pnl_usd),
            "pnl_pct": pnl_pct,
            "exit_reason": reason,
            "target_reached": reason == "target_reached",
        }

        self.logger.info(
            f"Position closed: {symbol} {position.side.upper()} "
            f"entry=${position.entry_price:.2f}, exit=${exit_price:.2f}, "
            f"P&L={pnl_pct:+.2f}% (${pnl_usd:+.2f}), reason={reason}"
        )

        # Publish to Redis
        if self.redis:
            try:
                self.redis.publish_event("overnight:exits", summary)
            except Exception as e:
                self.logger.error(f"Error publishing exit to Redis: {e}")

        # Remove position
        del self.positions[symbol]

        return summary

    def get_position_count(self) -> int:
        """Get count of active positions."""
        return len(self.positions)

    def get_position(self, symbol: str) -> Optional[OvernightPosition]:
        """Get position by symbol."""
        return self.positions.get(symbol)

    def get_all_positions(self) -> List[OvernightPosition]:
        """Get all active positions."""
        return list(self.positions.values())


def create_overnight_position_manager(
    redis_manager=None,
    logger=None,
    spot_notional_multiplier: float = 2.0,
) -> OvernightPositionManager:
    """
    Create overnight position manager.

    Args:
        redis_manager: Redis client
        logger: Logger instance
        spot_notional_multiplier: Notional multiplier (default: 2.0x)

    Returns:
        OvernightPositionManager instance
    """
    return OvernightPositionManager(
        redis_manager=redis_manager,
        logger=logger,
        spot_notional_multiplier=spot_notional_multiplier,
    )
