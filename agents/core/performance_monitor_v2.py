"""
Performance Monitor - Track P&L and metrics with snapshot DTO.

In-memory accumulators with no I/O dependencies.
Provides snapshot() DTO with win%, avg R, PnL.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from agents.core.types import ExecutionResult, Side

logger = logging.getLogger(__name__)


# ==============================================================================
# Performance Snapshot DTO
# ==============================================================================


@dataclass(frozen=True)
class PerformanceSnapshot:
    """Immutable performance snapshot DTO."""

    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float  # 0.0 to 1.0
    total_pnl: Decimal
    avg_win: Decimal
    avg_loss: Decimal
    avg_r: float  # Average R-multiple
    max_drawdown: Decimal
    sharpe_ratio: Optional[float] = None

    def to_dict(self) -> dict[str, float | int]:
        """Convert to dictionary for serialization."""
        return {
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": round(self.win_rate, 4),
            "total_pnl": float(self.total_pnl),
            "avg_win": float(self.avg_win),
            "avg_loss": float(self.avg_loss),
            "avg_r": round(self.avg_r, 2),
            "max_drawdown": float(self.max_drawdown),
            "sharpe_ratio": round(self.sharpe_ratio, 2) if self.sharpe_ratio else None,
        }


# ==============================================================================
# Performance Monitor
# ==============================================================================


class PerformanceMonitor:
    """Track trading performance with in-memory accumulators."""

    def __init__(self):
        """Initialize performance monitor."""
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0

        self.total_pnl = Decimal("0")
        self.wins: list[Decimal] = []
        self.losses: list[Decimal] = []
        self.pnl_history: list[Decimal] = []

        self.peak_equity = Decimal("0")
        self.max_drawdown = Decimal("0")

        logger.info("PerformanceMonitor initialized")

    def record(self, result: ExecutionResult, entry_price: Optional[Decimal] = None) -> None:
        """Record execution result and update metrics.

        Args:
            result: Execution result to record
            entry_price: Entry price for P&L calculation (optional)
        """
        if not result.success or not result.filled_quantity or not result.average_price:
            return  # Skip failed or unfilled orders

        self.total_trades += 1

        # Calculate P&L (simplified - assumes single position close)
        if entry_price and result.average_price:
            # For demonstration: assume closing a long position
            pnl = (result.average_price - entry_price) * result.filled_quantity - result.fee

            self.total_pnl += pnl
            self.pnl_history.append(pnl)

            # Track wins/losses
            if pnl > 0:
                self.winning_trades += 1
                self.wins.append(pnl)
            else:
                self.losing_trades += 1
                self.losses.append(abs(pnl))

            # Update drawdown
            if self.total_pnl > self.peak_equity:
                self.peak_equity = self.total_pnl
            else:
                current_dd = self.peak_equity - self.total_pnl
                if current_dd > self.max_drawdown:
                    self.max_drawdown = current_dd

            logger.debug(f"Recorded trade: PnL={float(pnl):.2f}, Total PnL={float(self.total_pnl):.2f}")

    def snapshot(self) -> PerformanceSnapshot:
        """Get current performance snapshot (immutable DTO).

        Returns:
            PerformanceSnapshot with current metrics
        """
        # Calculate metrics
        win_rate = self.winning_trades / max(self.total_trades, 1)

        avg_win = sum(self.wins) / len(self.wins) if self.wins else Decimal("0")
        avg_loss = sum(self.losses) / len(self.losses) if self.losses else Decimal("0")

        # Calculate average R-multiple
        # R = (Avg Win / Avg Loss) if avg_loss > 0
        if avg_loss > 0:
            avg_r = float(avg_win / avg_loss)
        elif avg_win > 0:
            avg_r = 999.0  # All wins, no losses
        else:
            avg_r = 0.0

        # Calculate Sharpe ratio (simplified)
        sharpe = None
        if len(self.pnl_history) > 1:
            import statistics

            mean_pnl = statistics.mean([float(p) for p in self.pnl_history])
            std_pnl = statistics.stdev([float(p) for p in self.pnl_history])
            if std_pnl > 0:
                sharpe = mean_pnl / std_pnl

        return PerformanceSnapshot(
            total_trades=self.total_trades,
            winning_trades=self.winning_trades,
            losing_trades=self.losing_trades,
            win_rate=win_rate,
            total_pnl=self.total_pnl,
            avg_win=avg_win,
            avg_loss=avg_loss,
            avg_r=avg_r,
            max_drawdown=self.max_drawdown,
            sharpe_ratio=sharpe,
        )

    def reset(self) -> None:
        """Reset all accumulators."""
        self.__init__()  # Re-initialize
        logger.info("PerformanceMonitor reset")


# ==============================================================================
# Exports
# ==============================================================================

__all__ = [
    "PerformanceMonitor",
    "PerformanceSnapshot",
]
