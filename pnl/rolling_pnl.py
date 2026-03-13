"""
Rolling PnL Tracker with Redis Persistence (pnl/rolling_pnl.py)

Tracks real-time profit/loss for paper and live trading with Redis persistence.

FEATURES:
- Realized PnL (from fills/trades)
- Unrealized PnL (mark-to-market)
- Rolling equity curve
- Mode-aware Redis persistence with complete paper/live separation
- Per-pair position tracking
- Support for both paper and live modes

REDIS KEYS (MODE-AWARE):
- pnl:{mode}:summary (STRING): Latest PnL snapshot JSON
- pnl:{mode}:equity_curve (STREAM): Historical equity curve events
- pnl:{mode}:last_update_ts (STRING): Timestamp of last update

Example keys:
- Paper mode: pnl:paper:summary, pnl:paper:equity_curve, pnl:paper:last_update_ts
- Live mode: pnl:live:summary, pnl:live:equity_curve, pnl:live:last_update_ts

PNL CALCULATION:
- Realized PnL = Sum of (exit_price - entry_price) * quantity for closed positions
- Unrealized PnL = Sum of (current_price - avg_entry) * position_size for open positions
- Total PnL = Realized PnL + Unrealized PnL
- Equity = Initial Balance + Total PnL
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Literal

from pydantic import BaseModel, Field
import redis.asyncio as redis
import orjson

logger = logging.getLogger(__name__)


class Position(BaseModel):
    """
    Open position for a trading pair.

    Attributes:
        pair: Trading pair
        side: Position side (long or short)
        quantity: Position size
        avg_entry: Average entry price
        unrealized_pnl: Current unrealized PnL
        last_price: Last known market price
    """

    pair: str
    side: Literal["long", "short"]
    quantity: float = Field(gt=0.0)
    avg_entry: float = Field(gt=0.0)
    unrealized_pnl: float = 0.0
    last_price: Optional[float] = None


class PnLSummary(BaseModel):
    """
    PnL summary snapshot.

    Attributes:
        timestamp: Unix timestamp
        initial_balance: Starting balance
        realized_pnl: Total realized profit/loss
        unrealized_pnl: Total unrealized profit/loss
        total_pnl: Realized + Unrealized PnL
        equity: Current equity (initial_balance + total_pnl)
        positions: Open positions by pair
        num_trades: Total number of trades
        win_rate: Win rate (0.0 - 1.0)
        mode: Trading mode (paper or live)
    """

    timestamp: float
    timestamp_iso: str
    initial_balance: float
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    total_pnl: float = 0.0
    equity: float
    positions: Dict[str, Position] = {}
    num_trades: int = 0
    num_wins: int = 0
    num_losses: int = 0
    win_rate: float = 0.0
    mode: Literal["paper", "live"] = "paper"


class PnLTracker:
    """
    Rolling PnL tracker with Redis persistence.

    Tracks positions, calculates PnL, and publishes to Redis.
    """

    def __init__(
        self,
        redis_url: str,
        redis_cert_path: Optional[str] = None,
        initial_balance: float = 10000.0,
        mode: Literal["paper", "live"] = "paper",
    ):
        """
        Initialize PnL tracker.

        Args:
            redis_url: Redis connection URL
            redis_cert_path: Path to TLS certificate
            initial_balance: Initial account balance
            mode: Trading mode (paper or live)
        """
        self.redis_url = redis_url
        self.redis_cert_path = redis_cert_path
        self.initial_balance = initial_balance
        self.mode = mode

        self.redis_client: Optional[redis.Redis] = None

        # State
        self.positions: Dict[str, Position] = {}
        self.realized_pnl: float = 0.0
        self.num_trades: int = 0
        self.num_wins: int = 0
        self.num_losses: int = 0

    async def connect(self) -> bool:
        """
        Connect to Redis server.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            # Build connection parameters
            conn_params = {
                "socket_connect_timeout": 5,
                "socket_keepalive": True,
                "decode_responses": False,
            }

            # Add TLS certificate if using rediss://
            if self.redis_url.startswith("rediss://") and self.redis_cert_path:
                conn_params["ssl_ca_certs"] = self.redis_cert_path
                conn_params["ssl_cert_reqs"] = "required"

            # Create async Redis client
            self.redis_client = redis.from_url(self.redis_url, **conn_params)

            # Test connection
            await self.redis_client.ping()

            # Try to load existing state from Redis
            await self._load_state()

            logger.info(f"PnL tracker connected to Redis (mode={self.mode})")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            self.redis_client = None
            return False

    async def close(self) -> None:
        """Close Redis connection."""
        if self.redis_client:
            await self.redis_client.aclose()
            self.redis_client = None
            logger.info("PnL tracker disconnected from Redis")

    async def _load_state(self) -> None:
        """Load existing PnL state from Redis."""
        if not self.redis_client:
            return

        try:
            # Load summary from pnl:{mode}:summary (mode-aware)
            summary_key = f"pnl:{self.mode}:summary"
            summary_data = await self.redis_client.get(summary_key)
            if summary_data:
                summary_dict = orjson.loads(summary_data)
                summary = PnLSummary.model_validate(summary_dict)

                # Restore state
                self.positions = summary.positions
                self.realized_pnl = summary.realized_pnl
                self.num_trades = summary.num_trades
                self.num_wins = summary.num_wins
                self.num_losses = summary.num_losses

                logger.info(
                    f"Loaded PnL state from Redis ({summary_key}): equity=${summary.equity:.2f}, "
                    f"{len(self.positions)} open positions"
                )

        except Exception as e:
            logger.warning(f"Could not load PnL state from Redis: {e}")

    async def process_fill(
        self,
        pair: str,
        side: Literal["long", "short"],
        quantity: float,
        price: float,
        is_entry: bool = True,
    ) -> Dict[str, Any]:
        """
        Process a trade fill (entry or exit).

        Args:
            pair: Trading pair
            side: Trade side (long or short)
            quantity: Fill quantity
            price: Fill price
            is_entry: True if opening position, False if closing

        Returns:
            Dictionary with fill processing results
        """
        if not self.redis_client:
            raise ConnectionError("Not connected to Redis - call connect() first")

        result = {
            "pair": pair,
            "side": side,
            "quantity": quantity,
            "price": price,
            "is_entry": is_entry,
            "realized_pnl": 0.0,
            "position_closed": False,
        }

        if is_entry:
            # Opening a position
            if pair in self.positions:
                # Add to existing position (average entry price)
                pos = self.positions[pair]
                total_cost = pos.avg_entry * pos.quantity + price * quantity
                pos.quantity += quantity
                pos.avg_entry = total_cost / pos.quantity
            else:
                # New position
                self.positions[pair] = Position(
                    pair=pair,
                    side=side,
                    quantity=quantity,
                    avg_entry=price,
                    last_price=price,
                )

            logger.info(
                f"Opened/added to {side} position: {pair} {quantity} @ ${price}"
            )

        else:
            # Closing a position
            if pair not in self.positions:
                logger.warning(f"Attempted to close non-existent position: {pair}")
                return result

            pos = self.positions[pair]

            # Calculate realized PnL
            if pos.side == "long":
                pnl = (price - pos.avg_entry) * quantity
            else:  # short
                pnl = (pos.avg_entry - price) * quantity

            self.realized_pnl += pnl
            self.num_trades += 1

            if pnl > 0:
                self.num_wins += 1
            elif pnl < 0:
                self.num_losses += 1

            result["realized_pnl"] = pnl

            # Reduce position
            pos.quantity -= quantity

            if pos.quantity <= 1e-8:  # Close position (allow tiny rounding errors)
                del self.positions[pair]
                result["position_closed"] = True
                logger.info(
                    f"Closed {side} position: {pair} {quantity} @ ${price} | PnL: ${pnl:.2f}"
                )
            else:
                logger.info(
                    f"Reduced {side} position: {pair} {quantity} @ ${price} | PnL: ${pnl:.2f}"
                )

        # Publish updated PnL
        await self.publish()

        return result

    async def update_mtm(self, market_prices: Dict[str, float]) -> None:
        """
        Update mark-to-market unrealized PnL for open positions.

        Args:
            market_prices: Dictionary of {pair: current_price}
        """
        if not self.redis_client:
            raise ConnectionError("Not connected to Redis - call connect() first")

        # Update unrealized PnL for each position
        for pair, pos in self.positions.items():
            if pair in market_prices:
                current_price = market_prices[pair]
                pos.last_price = current_price

                # Calculate unrealized PnL
                if pos.side == "long":
                    pos.unrealized_pnl = (current_price - pos.avg_entry) * pos.quantity
                else:  # short
                    pos.unrealized_pnl = (pos.avg_entry - current_price) * pos.quantity

        # Publish updated PnL
        await self.publish()

    async def get_summary(self) -> PnLSummary:
        """
        Get current PnL summary.

        Returns:
            PnLSummary with current state
        """
        # Calculate total unrealized PnL
        unrealized_pnl = sum(pos.unrealized_pnl for pos in self.positions.values())

        # Calculate total PnL and equity
        total_pnl = self.realized_pnl + unrealized_pnl
        equity = self.initial_balance + total_pnl

        # Calculate win rate
        total_closed = self.num_wins + self.num_losses
        win_rate = self.num_wins / total_closed if total_closed > 0 else 0.0

        # Create summary
        now = time.time()
        return PnLSummary(
            timestamp=now,
            timestamp_iso=datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
            initial_balance=self.initial_balance,
            realized_pnl=self.realized_pnl,
            unrealized_pnl=unrealized_pnl,
            total_pnl=total_pnl,
            equity=equity,
            positions=self.positions.copy(),
            num_trades=self.num_trades,
            num_wins=self.num_wins,
            num_losses=self.num_losses,
            win_rate=win_rate,
            mode=self.mode,
        )

    async def publish(self) -> None:
        """
        Publish PnL summary to Redis with mode-aware stream names.

        Updates (mode-aware):
        - pnl:{mode}:summary (STRING): Latest PnL snapshot
        - pnl:{mode}:equity_curve (STREAM): Historical equity curve
        - pnl:{mode}:last_update_ts (STRING): Timestamp of last update

        Example streams:
        - Paper mode: pnl:paper:summary, pnl:paper:equity_curve
        - Live mode: pnl:live:summary, pnl:live:equity_curve
        """
        if not self.redis_client:
            raise ConnectionError("Not connected to Redis - call connect() first")

        try:
            # Get current summary
            summary = await self.get_summary()

            # Serialize to JSON
            summary_json = orjson.dumps(summary.model_dump())

            # Mode-aware stream keys
            summary_key = f"pnl:{self.mode}:summary"
            equity_key = f"pnl:{self.mode}:equity_curve"
            ts_key = f"pnl:{self.mode}:last_update_ts"

            # 1. Update pnl:{mode}:summary (STRING) + pnl:{mode}:latest (alias for signals-api fast path)
            await self.redis_client.set(summary_key, summary_json)
            await self.redis_client.set(f"pnl:{self.mode}:latest", summary_json)

            # 2. Add to pnl:{mode}:equity_curve (STREAM)
            equity_event = {
                "timestamp": str(summary.timestamp),
                "equity": str(summary.equity),
                "realized_pnl": str(summary.realized_pnl),
                "unrealized_pnl": str(summary.unrealized_pnl),
                "num_positions": str(len(summary.positions)),
                "mode": self.mode,  # Add mode for safety
            }
            await self.redis_client.xadd(
                equity_key,
                equity_event,
                maxlen=50000,  # Keep last 50k equity snapshots (increased from 10k)
                approximate=True,
            )

            # 3. Update pnl:{mode}:last_update_ts (STRING)
            await self.redis_client.set(ts_key, str(summary.timestamp))

            logger.debug(
                f"Published PnL to {equity_key}: equity=${summary.equity:.2f}, "
                f"realized=${summary.realized_pnl:.2f}, "
                f"unrealized=${summary.unrealized_pnl:.2f}"
            )

        except Exception as e:
            logger.error(f"Failed to publish PnL to Redis: {e}")
            raise

    async def reset(self, initial_balance: Optional[float] = None) -> None:
        """
        Reset PnL tracker state (use with caution!).

        Args:
            initial_balance: Optional new initial balance
        """
        if initial_balance is not None:
            self.initial_balance = initial_balance

        self.positions = {}
        self.realized_pnl = 0.0
        self.num_trades = 0
        self.num_wins = 0
        self.num_losses = 0

        # Publish reset state
        if self.redis_client:
            await self.publish()

        logger.info(f"PnL tracker reset (initial_balance=${self.initial_balance})")


# =============================================================================
# PUBLIC API
# =============================================================================

__all__ = [
    "PnLTracker",
    "PnLSummary",
    "Position",
]


# =============================================================================
# SELF-CHECK
# =============================================================================

if __name__ == "__main__":
    """Self-check: Validate PnL tracker functionality"""
    import asyncio
    from dotenv import load_dotenv
    import os

    load_dotenv(".env.prod")

    async def main():
        print("=" * 70)
        print(" " * 20 + "PNL TRACKER SELF-CHECK")
        print("=" * 70)

        # Test 1: Create tracker
        print("\nTest 1: Create PnL tracker")
        tracker = PnLTracker(
            redis_url=os.getenv("REDIS_URL"),
            redis_cert_path=os.getenv("REDIS_TLS_CERT_PATH"),
            initial_balance=10000.0,
            mode="paper",
        )
        print("  PASS")

        # Test 2: Connect to Redis
        print("\nTest 2: Connect to Redis")
        connected = await tracker.connect()
        if not connected:
            print("  FAIL: Could not connect to Redis")
            return
        print("  PASS")

        # Test 3: Reset tracker (clean slate)
        print("\nTest 3: Reset tracker")
        await tracker.reset()
        summary = await tracker.get_summary()
        assert summary.equity == 10000.0
        assert len(summary.positions) == 0
        print(f"  Initial equity: ${summary.equity:.2f}")
        print("  PASS")

        # Test 4: Open a long position
        print("\nTest 4: Open long position (BTC/USD 0.1 @ $50000)")
        await tracker.process_fill(
            pair="BTC/USD", side="long", quantity=0.1, price=50000.0, is_entry=True
        )
        summary = await tracker.get_summary()
        assert "BTC/USD" in summary.positions
        assert summary.positions["BTC/USD"].quantity == 0.1
        print(f"  Position opened: {summary.positions['BTC/USD']}")
        print("  PASS")

        # Test 5: Update mark-to-market (price up)
        print("\nTest 5: Update MTM (BTC @ $51000)")
        await tracker.update_mtm({"BTC/USD": 51000.0})
        summary = await tracker.get_summary()
        expected_unrealized = (51000.0 - 50000.0) * 0.1  # = $100
        assert abs(summary.unrealized_pnl - expected_unrealized) < 0.01
        print(f"  Unrealized PnL: ${summary.unrealized_pnl:.2f}")
        print(f"  Equity: ${summary.equity:.2f}")
        print("  PASS")

        # Test 6: Close position (realize profit)
        print("\nTest 6: Close position (BTC/USD 0.1 @ $51000)")
        result = await tracker.process_fill(
            pair="BTC/USD", side="long", quantity=0.1, price=51000.0, is_entry=False
        )
        summary = await tracker.get_summary()
        assert result["realized_pnl"] == 100.0
        assert result["position_closed"] is True
        assert len(summary.positions) == 0
        assert summary.realized_pnl == 100.0
        assert summary.num_trades == 1
        assert summary.num_wins == 1
        print(f"  Realized PnL: ${summary.realized_pnl:.2f}")
        print(f"  Equity: ${summary.equity:.2f}")
        print("  PASS")

        # Test 7: Win rate calculation
        print("\nTest 7: Win rate calculation")
        # Open and close a losing trade
        await tracker.process_fill(
            pair="ETH/USD", side="long", quantity=1.0, price=3000.0, is_entry=True
        )
        await tracker.process_fill(
            pair="ETH/USD", side="long", quantity=1.0, price=2900.0, is_entry=False
        )
        summary = await tracker.get_summary()
        assert summary.num_trades == 2
        assert summary.num_wins == 1
        assert summary.num_losses == 1
        assert summary.win_rate == 0.5
        print(f"  Win rate: {summary.win_rate * 100:.1f}%")
        print(f"  Equity: ${summary.equity:.2f}")
        print("  PASS")

        # Test 8: Verify Redis persistence
        print("\nTest 8: Verify Redis persistence")
        pnl_summary = await tracker.redis_client.get("pnl:summary")
        assert pnl_summary is not None
        pnl_data = orjson.loads(pnl_summary)
        assert "equity" in pnl_data
        print(f"  Redis pnl:summary found: equity=${pnl_data['equity']:.2f}")

        equity_len = await tracker.redis_client.xlen("pnl:equity_curve")
        assert equity_len > 0
        print(f"  Redis pnl:equity_curve length: {equity_len}")
        print("  PASS")

        # Cleanup
        await tracker.close()

        print("\n" + "=" * 70)
        print("[OK] All Self-Checks PASSED")
        print("=" * 70)

    asyncio.run(main())
