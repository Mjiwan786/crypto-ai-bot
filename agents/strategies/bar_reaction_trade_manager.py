"""
Bar Reaction 5M Trade Manager

Implements risk & trade management for bar_reaction_5m strategy:
- G1: ATR-based stops (SL, TP1, TP2, Break-Even, Trailing)
- G2: Stacking & caps (concurrent limits, drawdown gates)
- G3: Comprehensive position lifecycle management

Features:
- SL = sl_atr * ATR
- TP1 = tp1_atr * ATR (close 50%)
- TP2 = tp2_atr * ATR (trail trail_atr * ATR)
- Move to breakeven at unrealized >= break_even_at_r * SL
- Max concurrent per pair enforcement
- Global drawdown gates (day, rolling, consecutive losses)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

import redis.asyncio as redis

logger = logging.getLogger(__name__)


def as_decimal(x: float | str | Decimal) -> Decimal:
    """Convert to Decimal for precise calculations."""
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


@dataclass
class TradeConfig:
    """Configuration for ATR-based trade management."""

    # G1: ATR-based stops
    sl_atr: float = 0.6           # Stop loss: 0.6x ATR
    tp1_atr: float = 1.0          # Take profit 1: 1.0x ATR (close 50%)
    tp2_atr: float = 1.8          # Take profit 2: 1.8x ATR (trail remainder)
    trail_atr: float = 0.8        # Trailing stop distance: 0.8x ATR
    break_even_at_r: float = 0.5  # Move to BE at 0.5R unrealized profit

    # TP1 partial close
    tp1_close_pct: float = 0.5    # Close 50% at TP1

    # G2: Concurrent limits
    max_concurrent_per_pair: int = 1  # Max one concurrent per pair

    # G2: Global drawdown gates
    day_max_drawdown_pct: float = 5.0          # 5% max daily drawdown
    rolling_max_drawdown_pct: float = 10.0     # 10% max rolling drawdown
    max_consecutive_losses: int = 3             # 3 losses → cooldown
    cooldown_after_losses_seconds: int = 3600   # 1 hour cooldown

    # Redis keys
    redis_prefix: str = "bar_reaction_trade"

    # Backtest mode
    backtest_mode: bool = False


@dataclass
class Position:
    """Active trade position with ATR-based management."""

    # Identity
    position_id: str
    signal_id: str
    pair: str
    side: str  # 'long' or 'short'

    # Entry
    entry_price: Decimal
    quantity: Decimal
    entry_time: int  # milliseconds

    # ATR-based levels
    atr: Decimal
    sl: Decimal           # Initial stop loss
    tp1: Decimal          # First target (partial close)
    tp2: Decimal          # Second target (final)
    current_sl: Decimal   # Current stop (may move to BE or trail)

    # State
    status: str = "open"  # open, tp1_hit, closed
    tp1_hit: bool = False
    breakeven_set: bool = False
    trailing: bool = False

    # Quantities
    original_quantity: Decimal = field(default_factory=lambda: Decimal("0"))
    remaining_quantity: Decimal = field(default_factory=lambda: Decimal("0"))

    # P&L tracking
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")

    # Config
    config: TradeConfig = field(default_factory=TradeConfig)

    def __post_init__(self):
        """Initialize derived fields."""
        if self.original_quantity == Decimal("0"):
            self.original_quantity = self.quantity
        if self.remaining_quantity == Decimal("0"):
            self.remaining_quantity = self.quantity


@dataclass
class TradeUpdate:
    """Update result from trade management logic."""

    action: str  # 'none', 'move_be', 'tp1_close', 'tp2_close', 'sl_hit', 'trail_update'
    new_sl: Optional[Decimal] = None
    close_quantity: Optional[Decimal] = None
    realized_pnl: Optional[Decimal] = None
    message: str = ""


@dataclass
class DrawdownState:
    """Global drawdown tracking state."""

    daily_pnl: Decimal = Decimal("0")
    daily_start_equity: Decimal = Decimal("100000")  # Starting equity
    rolling_pnl: Decimal = Decimal("0")
    rolling_start_equity: Decimal = Decimal("100000")
    consecutive_losses: int = 0
    last_loss_time: Optional[int] = None  # milliseconds
    cooldown_until: Optional[int] = None  # milliseconds


class BarReactionTradeManager:
    """
    Trade manager for bar_reaction_5m strategy.

    Implements ATR-based risk management with break-even, trailing stops,
    and global drawdown gates.
    """

    def __init__(
        self,
        config: TradeConfig,
        redis_client: redis.Redis,
    ):
        """
        Initialize trade manager.

        Args:
            config: Trade management configuration
            redis_client: Async Redis client
        """
        self.config = config
        self.redis = redis_client

        # Position tracking
        self.active_positions: Dict[str, Position] = {}
        self.positions_by_pair: Dict[str, List[str]] = {}  # pair -> [position_ids]

        # Drawdown state
        self.drawdown_state = DrawdownState()

        # Statistics
        self.stats = {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "breakeven_moves": 0,
            "tp1_hits": 0,
            "tp2_hits": 0,
            "sl_hits": 0,
            "trail_updates": 0,
            "concurrent_limit_rejections": 0,
            "drawdown_rejections": 0,
            "total_realized_pnl": 0.0,
        }

        logger.info(
            f"BarReactionTradeManager initialized [max_concurrent={config.max_concurrent_per_pair}, "
            f"day_dd={config.day_max_drawdown_pct}%, rolling_dd={config.rolling_max_drawdown_pct}%, "
            f"max_losses={config.max_consecutive_losses}]"
        )

    async def can_open_position(self, pair: str) -> tuple[bool, Optional[str]]:
        """
        G2: Check if new position can be opened.

        Checks:
        1. Concurrent limit per pair
        2. Day max drawdown
        3. Rolling max drawdown
        4. Consecutive losses cooldown

        Args:
            pair: Trading pair

        Returns:
            (can_open, rejection_reason)
        """
        # Check concurrent limit
        current_count = len(self.positions_by_pair.get(pair, []))
        if current_count >= self.config.max_concurrent_per_pair:
            self.stats["concurrent_limit_rejections"] += 1
            return False, f"Concurrent limit reached ({current_count}/{self.config.max_concurrent_per_pair})"

        # Check day drawdown
        day_dd_pct = self._calculate_drawdown_pct(
            self.drawdown_state.daily_pnl,
            self.drawdown_state.daily_start_equity
        )
        if day_dd_pct > self.config.day_max_drawdown_pct:
            self.stats["drawdown_rejections"] += 1
            return False, f"Day drawdown limit ({day_dd_pct:.2f}% > {self.config.day_max_drawdown_pct}%)"

        # Check rolling drawdown
        rolling_dd_pct = self._calculate_drawdown_pct(
            self.drawdown_state.rolling_pnl,
            self.drawdown_state.rolling_start_equity
        )
        if rolling_dd_pct > self.config.rolling_max_drawdown_pct:
            self.stats["drawdown_rejections"] += 1
            return False, f"Rolling drawdown limit ({rolling_dd_pct:.2f}% > {self.config.rolling_max_drawdown_pct}%)"

        # Check consecutive losses cooldown
        if self.drawdown_state.cooldown_until:
            now_ms = int(time.time() * 1000)
            if now_ms < self.drawdown_state.cooldown_until:
                remaining_s = (self.drawdown_state.cooldown_until - now_ms) / 1000
                return False, f"Cooldown after {self.config.max_consecutive_losses} losses ({remaining_s:.0f}s remaining)"

        return True, None

    def _calculate_drawdown_pct(self, pnl: Decimal, start_equity: Decimal) -> float:
        """Calculate drawdown percentage."""
        if start_equity <= 0:
            return 0.0

        # Drawdown is negative PnL relative to starting equity
        if pnl >= 0:
            return 0.0  # No drawdown if profitable

        dd_pct = abs(float(pnl) / float(start_equity)) * 100
        return dd_pct

    async def open_position(
        self,
        signal: Dict[str, Any],
        entry_price: Decimal,
        quantity: Decimal,
        atr: Decimal,
    ) -> Position:
        """
        G1: Open new position with ATR-based levels.

        Calculates:
        - SL = entry ± sl_atr * ATR
        - TP1 = entry ± tp1_atr * ATR
        - TP2 = entry ± tp2_atr * ATR

        Args:
            signal: Signal dictionary
            entry_price: Entry price
            quantity: Position size
            atr: Current ATR value

        Returns:
            Position object
        """
        pair = signal["pair"]
        side = signal["side"]

        # Calculate ATR-based levels
        if side in ("long", "buy"):
            sl = entry_price - (atr * as_decimal(self.config.sl_atr))
            tp1 = entry_price + (atr * as_decimal(self.config.tp1_atr))
            tp2 = entry_price + (atr * as_decimal(self.config.tp2_atr))
        else:  # short/sell
            sl = entry_price + (atr * as_decimal(self.config.sl_atr))
            tp1 = entry_price - (atr * as_decimal(self.config.tp1_atr))
            tp2 = entry_price - (atr * as_decimal(self.config.tp2_atr))

        # Create position
        position_id = f"pos_{pair.replace('/', '')}_{int(time.time() * 1000)}"
        position = Position(
            position_id=position_id,
            signal_id=signal.get("id", "unknown"),
            pair=pair,
            side=side,
            entry_price=entry_price,
            quantity=quantity,
            entry_time=int(time.time() * 1000),
            atr=atr,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            current_sl=sl,
            config=self.config,
        )

        # Track position
        self.active_positions[position_id] = position
        if pair not in self.positions_by_pair:
            self.positions_by_pair[pair] = []
        self.positions_by_pair[pair].append(position_id)

        # Update stats
        self.stats["total_trades"] += 1

        # Persist to Redis
        await self._persist_position(position)

        logger.info(
            f"Opened position {position_id[:8]} {pair} {side} @ {float(entry_price):.2f} "
            f"[SL={float(sl):.2f}, TP1={float(tp1):.2f}, TP2={float(tp2):.2f}]"
        )

        return position

    async def update_position(
        self,
        position_id: str,
        current_price: Decimal,
    ) -> TradeUpdate:
        """
        G1: Update position with current price.

        Checks (in order):
        1. Stop loss hit
        2. TP2 hit (if TP1 already hit)
        3. TP1 hit (partial close)
        4. Break-even move (if unrealized >= 0.5R)
        5. Trailing stop update (if TP1 hit and not at TP2)

        Args:
            position_id: Position ID
            current_price: Current market price

        Returns:
            TradeUpdate with action taken
        """
        if position_id not in self.active_positions:
            return TradeUpdate(action="none", message="Position not found")

        position = self.active_positions[position_id]

        # Calculate unrealized PnL
        position.unrealized_pnl = self._calculate_unrealized_pnl(position, current_price)

        # Check stop loss hit
        if self._check_sl_hit(position, current_price):
            return await self._handle_sl_hit(position, current_price)

        # Check TP1 hit first (takes priority over BE)
        if not position.tp1_hit and self._check_tp1_hit(position, current_price):
            return await self._handle_tp1_hit(position, current_price)

        # Check TP2 hit (if TP1 already hit)
        if position.tp1_hit and self._check_tp2_hit(position, current_price):
            return await self._handle_tp2_hit(position, current_price)

        # Check break-even move (only if TP1 not hit yet)
        if not position.tp1_hit and not position.breakeven_set and self._check_breakeven_threshold(position):
            return await self._handle_breakeven_move(position)

        # Check trailing stop update (if TP1 hit)
        if position.tp1_hit and not position.trailing:
            position.trailing = True
            return await self._handle_trail_start(position, current_price)

        # Update trailing stop
        if position.trailing:
            trail_update = await self._handle_trail_update(position, current_price)
            if trail_update.action != "none":
                return trail_update

        return TradeUpdate(action="none")

    def _calculate_unrealized_pnl(self, position: Position, current_price: Decimal) -> Decimal:
        """Calculate unrealized PnL."""
        if position.side in ("long", "buy"):
            pnl_per_unit = current_price - position.entry_price
        else:
            pnl_per_unit = position.entry_price - current_price

        unrealized = pnl_per_unit * position.remaining_quantity
        return unrealized

    def _check_sl_hit(self, position: Position, current_price: Decimal) -> bool:
        """Check if stop loss hit."""
        if position.side in ("long", "buy"):
            return current_price <= position.current_sl
        else:
            return current_price >= position.current_sl

    def _check_tp1_hit(self, position: Position, current_price: Decimal) -> bool:
        """Check if TP1 hit."""
        if position.side in ("long", "buy"):
            return current_price >= position.tp1
        else:
            return current_price <= position.tp1

    def _check_tp2_hit(self, position: Position, current_price: Decimal) -> bool:
        """Check if TP2 hit."""
        if position.side in ("long", "buy"):
            return current_price >= position.tp2
        else:
            return current_price <= position.tp2

    def _check_breakeven_threshold(self, position: Position) -> bool:
        """G1: Check if unrealized profit >= break_even_at_r * SL distance.

        Note: Compares profit per unit, not total dollar PnL.
        """
        sl_distance = abs(position.entry_price - position.sl)
        breakeven_threshold = sl_distance * as_decimal(self.config.break_even_at_r)

        # Calculate profit per unit (not total PnL)
        # This is independent of position size
        if position.remaining_quantity == 0:
            return False

        profit_per_unit = position.unrealized_pnl / position.remaining_quantity

        return profit_per_unit >= breakeven_threshold

    async def _handle_sl_hit(self, position: Position, current_price: Decimal) -> TradeUpdate:
        """Handle stop loss hit."""
        realized_pnl = self._calculate_unrealized_pnl(position, current_price)

        # Close position
        await self._close_position(position, realized_pnl, "sl_hit")

        self.stats["sl_hits"] += 1

        logger.info(
            f"SL hit {position.position_id[:8]} @ {float(current_price):.2f} "
            f"[PnL=${float(realized_pnl):.2f}]"
        )

        return TradeUpdate(
            action="sl_hit",
            close_quantity=position.remaining_quantity,
            realized_pnl=realized_pnl,
            message=f"Stop loss hit @ {float(current_price):.2f}"
        )

    async def _handle_tp1_hit(self, position: Position, current_price: Decimal) -> TradeUpdate:
        """G1: Handle TP1 hit - close 50% of position."""
        # Calculate partial close quantity
        close_qty = position.remaining_quantity * as_decimal(self.config.tp1_close_pct)

        # Calculate realized PnL on partial close
        if position.side in ("long", "buy"):
            pnl_per_unit = current_price - position.entry_price
        else:
            pnl_per_unit = position.entry_price - current_price

        partial_pnl = pnl_per_unit * close_qty

        # Update position
        position.tp1_hit = True
        position.trailing = True  # Start trailing after TP1
        position.remaining_quantity -= close_qty
        position.realized_pnl += partial_pnl

        # Update drawdown state
        await self._update_drawdown_state(partial_pnl, is_win=(partial_pnl > 0))

        # Persist
        await self._persist_position(position)

        self.stats["tp1_hits"] += 1
        self.stats["total_realized_pnl"] += float(partial_pnl)

        logger.info(
            f"TP1 hit {position.position_id[:8]} @ {float(current_price):.2f} "
            f"[Closed {float(close_qty):.4f}, PnL=${float(partial_pnl):.2f}]"
        )

        return TradeUpdate(
            action="tp1_close",
            close_quantity=close_qty,
            realized_pnl=partial_pnl,
            message=f"TP1 hit, closed {self.config.tp1_close_pct*100}% @ {float(current_price):.2f}"
        )

    async def _handle_tp2_hit(self, position: Position, current_price: Decimal) -> TradeUpdate:
        """Handle TP2 hit - close remaining position."""
        realized_pnl = self._calculate_unrealized_pnl(position, current_price)

        # Close position
        await self._close_position(position, realized_pnl, "tp2_hit")

        self.stats["tp2_hits"] += 1

        logger.info(
            f"TP2 hit {position.position_id[:8]} @ {float(current_price):.2f} "
            f"[PnL=${float(realized_pnl):.2f}]"
        )

        return TradeUpdate(
            action="tp2_close",
            close_quantity=position.remaining_quantity,
            realized_pnl=realized_pnl,
            message=f"TP2 hit @ {float(current_price):.2f}"
        )

    async def _handle_breakeven_move(self, position: Position) -> TradeUpdate:
        """G1: Move stop to break-even."""
        old_sl = position.current_sl
        position.current_sl = position.entry_price
        position.breakeven_set = True

        # Persist
        await self._persist_position(position)

        self.stats["breakeven_moves"] += 1

        logger.info(
            f"Moved to BE {position.position_id[:8]} "
            f"[SL: {float(old_sl):.2f} -> {float(position.entry_price):.2f}]"
        )

        return TradeUpdate(
            action="move_be",
            new_sl=position.entry_price,
            message=f"Moved stop to break-even @ {float(position.entry_price):.2f}"
        )

    async def _handle_trail_start(self, position: Position, current_price: Decimal) -> TradeUpdate:
        """Start trailing after TP1 hit."""
        logger.info(f"Started trailing {position.position_id[:8]}")
        return TradeUpdate(action="trail_start", message="Trailing started")

    async def _handle_trail_update(self, position: Position, current_price: Decimal) -> TradeUpdate:
        """G1: Update trailing stop (trail_atr * ATR from current price)."""
        # Calculate new trailing stop
        trail_distance = position.atr * as_decimal(self.config.trail_atr)

        if position.side in ("long", "buy"):
            new_trail_sl = current_price - trail_distance
            # Only move up (never down for longs)
            if new_trail_sl > position.current_sl:
                old_sl = position.current_sl
                position.current_sl = new_trail_sl

                # Persist
                await self._persist_position(position)

                self.stats["trail_updates"] += 1

                logger.debug(
                    f"Trail update {position.position_id[:8]} "
                    f"[SL: {float(old_sl):.2f} -> {float(new_trail_sl):.2f}]"
                )

                return TradeUpdate(
                    action="trail_update",
                    new_sl=new_trail_sl,
                    message=f"Trailing stop updated to {float(new_trail_sl):.2f}"
                )
        else:  # short
            new_trail_sl = current_price + trail_distance
            # Only move down (never up for shorts)
            if new_trail_sl < position.current_sl:
                old_sl = position.current_sl
                position.current_sl = new_trail_sl

                # Persist
                await self._persist_position(position)

                self.stats["trail_updates"] += 1

                logger.debug(
                    f"Trail update {position.position_id[:8]} "
                    f"[SL: {float(old_sl):.2f} -> {float(new_trail_sl):.2f}]"
                )

                return TradeUpdate(
                    action="trail_update",
                    new_sl=new_trail_sl,
                    message=f"Trailing stop updated to {float(new_trail_sl):.2f}"
                )

        return TradeUpdate(action="none")

    async def _close_position(
        self,
        position: Position,
        final_pnl: Decimal,
        reason: str,
    ) -> None:
        """Close position and update state."""
        # Update position
        position.status = "closed"
        position.realized_pnl += final_pnl

        # Update drawdown state
        is_win = final_pnl > 0
        await self._update_drawdown_state(final_pnl, is_win)

        # Update stats
        if is_win:
            self.stats["winning_trades"] += 1
        else:
            self.stats["losing_trades"] += 1

        self.stats["total_realized_pnl"] += float(final_pnl)

        # Remove from active tracking
        pair = position.pair
        if position.position_id in self.active_positions:
            del self.active_positions[position.position_id]

        if pair in self.positions_by_pair:
            if position.position_id in self.positions_by_pair[pair]:
                self.positions_by_pair[pair].remove(position.position_id)

        # Persist final state
        await self._persist_position(position)

    async def _update_drawdown_state(self, pnl: Decimal, is_win: bool) -> None:
        """G2: Update global drawdown state and consecutive losses."""
        # Update daily PnL
        self.drawdown_state.daily_pnl += pnl

        # Update rolling PnL
        self.drawdown_state.rolling_pnl += pnl

        # Update consecutive losses
        if is_win:
            # Reset on win
            self.drawdown_state.consecutive_losses = 0
            self.drawdown_state.cooldown_until = None
        else:
            # Increment on loss
            self.drawdown_state.consecutive_losses += 1
            self.drawdown_state.last_loss_time = int(time.time() * 1000)

            # G2: Trigger cooldown after max_consecutive_losses
            if self.drawdown_state.consecutive_losses >= self.config.max_consecutive_losses:
                cooldown_ms = self.config.cooldown_after_losses_seconds * 1000
                self.drawdown_state.cooldown_until = int(time.time() * 1000) + cooldown_ms

                logger.warning(
                    f"Cooldown triggered after {self.config.max_consecutive_losses} consecutive losses "
                    f"({self.config.cooldown_after_losses_seconds}s)"
                )

    async def _persist_position(self, position: Position) -> None:
        """Persist position to Redis."""
        key = f"{self.config.redis_prefix}:position:{position.position_id}"

        position_dict = {
            "position_id": position.position_id,
            "signal_id": position.signal_id,
            "pair": position.pair,
            "side": position.side,
            "entry_price": str(position.entry_price),
            "quantity": str(position.quantity),
            "entry_time": str(position.entry_time),
            "sl": str(position.sl),
            "tp1": str(position.tp1),
            "tp2": str(position.tp2),
            "current_sl": str(position.current_sl),
            "status": position.status,
            "tp1_hit": "1" if position.tp1_hit else "0",
            "breakeven_set": "1" if position.breakeven_set else "0",
            "trailing": "1" if position.trailing else "0",
            "remaining_quantity": str(position.remaining_quantity),
            "realized_pnl": str(position.realized_pnl),
        }

        await self.redis.hset(key, mapping=position_dict)
        await self.redis.expire(key, 86400)  # 24h TTL

    def get_stats(self) -> Dict[str, Any]:
        """Get trade management statistics."""
        total_closed = self.stats["winning_trades"] + self.stats["losing_trades"]
        win_rate = (self.stats["winning_trades"] / max(total_closed, 1)) * 100

        return {
            "total_trades": self.stats["total_trades"],
            "active_positions": len(self.active_positions),
            "winning_trades": self.stats["winning_trades"],
            "losing_trades": self.stats["losing_trades"],
            "win_rate_pct": round(win_rate, 1),
            "breakeven_moves": self.stats["breakeven_moves"],
            "tp1_hits": self.stats["tp1_hits"],
            "tp2_hits": self.stats["tp2_hits"],
            "sl_hits": self.stats["sl_hits"],
            "trail_updates": self.stats["trail_updates"],
            "concurrent_limit_rejections": self.stats["concurrent_limit_rejections"],
            "drawdown_rejections": self.stats["drawdown_rejections"],
            "total_realized_pnl": round(self.stats["total_realized_pnl"], 2),
            "daily_pnl": float(self.drawdown_state.daily_pnl),
            "rolling_pnl": float(self.drawdown_state.rolling_pnl),
            "consecutive_losses": self.drawdown_state.consecutive_losses,
            "in_cooldown": self.drawdown_state.cooldown_until is not None,
            "config": {
                "sl_atr": self.config.sl_atr,
                "tp1_atr": self.config.tp1_atr,
                "tp2_atr": self.config.tp2_atr,
                "trail_atr": self.config.trail_atr,
                "break_even_at_r": self.config.break_even_at_r,
                "max_concurrent_per_pair": self.config.max_concurrent_per_pair,
                "day_max_drawdown_pct": self.config.day_max_drawdown_pct,
                "rolling_max_drawdown_pct": self.config.rolling_max_drawdown_pct,
                "max_consecutive_losses": self.config.max_consecutive_losses,
            },
        }

    def reset_daily_state(self) -> None:
        """Reset daily drawdown tracking (call at start of day)."""
        self.drawdown_state.daily_pnl = Decimal("0")
        self.drawdown_state.daily_start_equity = (
            self.drawdown_state.daily_start_equity + self.drawdown_state.daily_pnl
        )
        logger.info("Daily drawdown state reset")
