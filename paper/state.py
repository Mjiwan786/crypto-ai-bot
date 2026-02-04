"""
Account State Manager for Paper Trading.

Manages AccountState in Redis for paper trading:
- Load/save account state from Redis (paper namespace)
- Update state after trades (deterministic)
- Track daily/weekly PnL, trades, positions
- Reset on day rollover

Uses canonical AccountState from shared_contracts.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
import json
import logging

from shared_contracts import AccountState

logger = logging.getLogger(__name__)


# Redis key patterns for paper trading state
ACCOUNT_STATE_KEY = "paper:account:{account_id}:state"
ACCOUNT_POSITIONS_KEY = "paper:account:{account_id}:positions"
ACCOUNT_DAILY_STATS_KEY = "paper:account:{account_id}:daily:{date}"


@dataclass
class PositionSnapshot:
    """Snapshot of an open position."""

    position_id: str
    pair: str
    side: str  # "long" or "short"
    quantity: float
    entry_price: float
    entry_time: datetime
    stop_loss: float
    take_profit: float
    unrealized_pnl: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "position_id": self.position_id,
            "pair": self.pair,
            "side": self.side,
            "quantity": self.quantity,
            "entry_price": self.entry_price,
            "entry_time": self.entry_time.isoformat(),
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "unrealized_pnl": self.unrealized_pnl,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PositionSnapshot":
        """Create from dictionary."""
        return cls(
            position_id=data["position_id"],
            pair=data["pair"],
            side=data["side"],
            quantity=data["quantity"],
            entry_price=data["entry_price"],
            entry_time=datetime.fromisoformat(data["entry_time"]),
            stop_loss=data["stop_loss"],
            take_profit=data["take_profit"],
            unrealized_pnl=data.get("unrealized_pnl", 0.0),
        )


class AccountStateManager:
    """
    Manages paper trading account state in Redis.

    All state changes are persisted to Redis immediately.
    Supports deterministic updates for backtest parity.
    """

    def __init__(
        self,
        redis_client: Any,
        account_id: str,
        user_id: str,
        initial_equity: float = 10000.0,
    ):
        """
        Initialize account state manager.

        Args:
            redis_client: Async Redis client
            account_id: Account ID
            user_id: User ID
            initial_equity: Starting equity (USD)
        """
        self.redis = redis_client
        self.account_id = account_id
        self.user_id = user_id
        self.initial_equity = initial_equity

        # Current date for daily stat tracking
        self._current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _get_state_key(self) -> str:
        """Get Redis key for account state."""
        return ACCOUNT_STATE_KEY.format(account_id=self.account_id)

    def _get_positions_key(self) -> str:
        """Get Redis key for positions."""
        return ACCOUNT_POSITIONS_KEY.format(account_id=self.account_id)

    def _get_daily_stats_key(self, date_str: str | None = None) -> str:
        """Get Redis key for daily stats."""
        date = date_str or self._current_date
        return ACCOUNT_DAILY_STATS_KEY.format(account_id=self.account_id, date=date)

    async def load(self) -> AccountState:
        """
        Load account state from Redis.

        If no state exists, creates a new account with initial equity.

        Returns:
            AccountState snapshot
        """
        try:
            state_key = self._get_state_key()
            state_data = await self.redis.get(state_key)

            if state_data is None:
                # Create new account
                return await self._create_initial_state()

            data = json.loads(state_data)

            # Load positions
            positions_key = self._get_positions_key()
            positions_data = await self.redis.hgetall(positions_key)
            positions = []
            open_exposure = Decimal("0")

            for pos_id, pos_json in positions_data.items():
                if isinstance(pos_id, bytes):
                    pos_id = pos_id.decode()
                if isinstance(pos_json, bytes):
                    pos_json = pos_json.decode()
                pos = PositionSnapshot.from_dict(json.loads(pos_json))
                positions.append(pos.to_dict())
                open_exposure += Decimal(str(pos.quantity * pos.entry_price))

            # Handle day rollover
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if data.get("last_trade_date") != today:
                # Reset daily stats
                data["daily_pnl_usd"] = "0"
                data["trades_today"] = 0
                data["last_trade_date"] = today

            return AccountState(
                account_id=self.account_id,
                user_id=self.user_id,
                total_equity_usd=Decimal(data.get("total_equity_usd", str(self.initial_equity))),
                available_balance_usd=Decimal(data.get("available_balance_usd", str(self.initial_equity))),
                margin_used_usd=Decimal(data.get("margin_used_usd", "0")),
                daily_pnl_usd=Decimal(data.get("daily_pnl_usd", "0")),
                weekly_pnl_usd=Decimal(data.get("weekly_pnl_usd", "0")),
                drawdown_pct=float(data.get("drawdown_pct", 0.0)),
                open_positions_count=len(positions),
                open_positions_exposure_usd=open_exposure,
                open_positions=positions,
                trades_today=data.get("trades_today", 0),
                last_trade_at=datetime.fromisoformat(data["last_trade_at"]) if data.get("last_trade_at") else None,
                last_loss_at=datetime.fromisoformat(data["last_loss_at"]) if data.get("last_loss_at") else None,
                trading_enabled=data.get("trading_enabled", True),
                mode="paper",
            )

        except Exception as e:
            logger.error(f"Failed to load account state: {e}")
            # Return safe default on error
            return await self._create_initial_state()

    async def _create_initial_state(self) -> AccountState:
        """Create and save initial account state."""
        state = AccountState(
            account_id=self.account_id,
            user_id=self.user_id,
            total_equity_usd=Decimal(str(self.initial_equity)),
            available_balance_usd=Decimal(str(self.initial_equity)),
            mode="paper",
        )

        await self.save(state)
        return state

    async def save(self, state: AccountState) -> None:
        """
        Save account state to Redis.

        Args:
            state: AccountState to save
        """
        try:
            state_key = self._get_state_key()

            data = {
                "total_equity_usd": str(state.total_equity_usd),
                "available_balance_usd": str(state.available_balance_usd),
                "margin_used_usd": str(state.margin_used_usd),
                "daily_pnl_usd": str(state.daily_pnl_usd),
                "weekly_pnl_usd": str(state.weekly_pnl_usd),
                "drawdown_pct": state.drawdown_pct,
                "trades_today": state.trades_today,
                "last_trade_at": state.last_trade_at.isoformat() if state.last_trade_at else None,
                "last_loss_at": state.last_loss_at.isoformat() if state.last_loss_at else None,
                "trading_enabled": state.trading_enabled,
                "last_trade_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

            await self.redis.set(state_key, json.dumps(data))

        except Exception as e:
            logger.error(f"Failed to save account state: {e}")
            raise

    async def record_trade(
        self,
        pnl: float,
        fees: float,
        timestamp: datetime,
    ) -> AccountState:
        """
        Record a completed trade and update state.

        Args:
            pnl: Realized P&L from trade (positive or negative)
            fees: Trading fees paid
            timestamp: Trade timestamp

        Returns:
            Updated AccountState
        """
        state = await self.load()

        # Calculate new values
        net_pnl = pnl - fees
        new_equity = float(state.total_equity_usd) + net_pnl
        new_daily_pnl = float(state.daily_pnl_usd) + net_pnl
        new_weekly_pnl = float(state.weekly_pnl_usd) + net_pnl

        # Update drawdown
        peak_equity = max(self.initial_equity, new_equity)  # Simplified peak tracking
        drawdown = ((peak_equity - new_equity) / peak_equity) * 100 if peak_equity > 0 else 0

        # Create updated state (immutable, so create new)
        updated = AccountState(
            account_id=state.account_id,
            user_id=state.user_id,
            total_equity_usd=Decimal(str(new_equity)),
            available_balance_usd=Decimal(str(new_equity)),  # Simplified for paper
            margin_used_usd=state.margin_used_usd,
            daily_pnl_usd=Decimal(str(new_daily_pnl)),
            weekly_pnl_usd=Decimal(str(new_weekly_pnl)),
            drawdown_pct=drawdown,
            open_positions_count=state.open_positions_count,
            open_positions_exposure_usd=state.open_positions_exposure_usd,
            open_positions=state.open_positions,
            trades_today=state.trades_today + 1,
            last_trade_at=timestamp,
            last_loss_at=timestamp if net_pnl < 0 else state.last_loss_at,
            trading_enabled=state.trading_enabled,
            mode="paper",
        )

        await self.save(updated)

        logger.debug(
            f"Trade recorded: pnl=${net_pnl:.2f} equity=${new_equity:.2f} "
            f"trades_today={updated.trades_today}"
        )

        return updated

    async def open_position(self, position: PositionSnapshot) -> None:
        """
        Add an open position.

        Args:
            position: Position to open
        """
        positions_key = self._get_positions_key()
        await self.redis.hset(
            positions_key,
            position.position_id,
            json.dumps(position.to_dict()),
        )

    async def close_position(self, position_id: str) -> PositionSnapshot | None:
        """
        Close and remove a position.

        Args:
            position_id: Position ID to close

        Returns:
            Closed position or None if not found
        """
        positions_key = self._get_positions_key()
        pos_data = await self.redis.hget(positions_key, position_id)

        if pos_data is None:
            return None

        if isinstance(pos_data, bytes):
            pos_data = pos_data.decode()

        await self.redis.hdel(positions_key, position_id)

        return PositionSnapshot.from_dict(json.loads(pos_data))

    async def get_positions(self) -> list[PositionSnapshot]:
        """
        Get all open positions.

        Returns:
            List of open positions
        """
        positions_key = self._get_positions_key()
        positions_data = await self.redis.hgetall(positions_key)

        positions = []
        for pos_id, pos_json in positions_data.items():
            if isinstance(pos_json, bytes):
                pos_json = pos_json.decode()
            positions.append(PositionSnapshot.from_dict(json.loads(pos_json)))

        return positions

    async def disable_trading(self, reason: str = "Manual disable") -> None:
        """Disable trading for this account."""
        state = await self.load()

        # Create disabled state
        disabled = AccountState(
            account_id=state.account_id,
            user_id=state.user_id,
            total_equity_usd=state.total_equity_usd,
            available_balance_usd=state.available_balance_usd,
            margin_used_usd=state.margin_used_usd,
            daily_pnl_usd=state.daily_pnl_usd,
            weekly_pnl_usd=state.weekly_pnl_usd,
            drawdown_pct=state.drawdown_pct,
            open_positions_count=state.open_positions_count,
            open_positions_exposure_usd=state.open_positions_exposure_usd,
            open_positions=state.open_positions,
            trades_today=state.trades_today,
            last_trade_at=state.last_trade_at,
            last_loss_at=state.last_loss_at,
            trading_enabled=False,
            mode="paper",
        )

        await self.save(disabled)
        logger.warning(f"Trading disabled for account {self.account_id}: {reason}")

    async def enable_trading(self) -> None:
        """Enable trading for this account."""
        state = await self.load()

        enabled = AccountState(
            account_id=state.account_id,
            user_id=state.user_id,
            total_equity_usd=state.total_equity_usd,
            available_balance_usd=state.available_balance_usd,
            margin_used_usd=state.margin_used_usd,
            daily_pnl_usd=state.daily_pnl_usd,
            weekly_pnl_usd=state.weekly_pnl_usd,
            drawdown_pct=state.drawdown_pct,
            open_positions_count=state.open_positions_count,
            open_positions_exposure_usd=state.open_positions_exposure_usd,
            open_positions=state.open_positions,
            trades_today=state.trades_today,
            last_trade_at=state.last_trade_at,
            last_loss_at=state.last_loss_at,
            trading_enabled=True,
            mode="paper",
        )

        await self.save(enabled)
        logger.info(f"Trading enabled for account {self.account_id}")

    async def reset(self) -> AccountState:
        """
        Reset account to initial state.

        Returns:
            Fresh AccountState
        """
        # Clear positions
        positions_key = self._get_positions_key()
        await self.redis.delete(positions_key)

        # Clear state
        state_key = self._get_state_key()
        await self.redis.delete(state_key)

        # Create fresh state
        return await self._create_initial_state()
