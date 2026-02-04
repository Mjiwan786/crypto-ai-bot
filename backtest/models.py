"""
Backtest models - Configuration and result types.

All result types support full explainability by linking to canonical contracts.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from shared_contracts import Strategy, TradeIntent, ExecutionDecision, Trade


@dataclass(frozen=True)
class BacktestAssumptions:
    """Assumptions used in the backtest (for reproducibility)."""

    fees_bps: float = 10.0  # 10 bps = 0.1%
    slippage_bps: float = 5.0  # 5 bps = 0.05%
    starting_equity: float = 10000.0
    timeframe: str = "5m"
    pair: str = "BTC/USD"
    strategy_id: str = ""
    strategy_name: str = ""
    date_range_start: str = ""
    date_range_end: str = ""
    num_candles: int = 0


@dataclass(frozen=True)
class BacktestSummary:
    """Summary statistics from the backtest."""

    total_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    sharpe_ratio: float = 0.0
    num_trades: int = 0
    num_winners: int = 0
    num_losers: int = 0
    num_rejected: int = 0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    final_equity: float = 0.0


@dataclass
class EquityPoint:
    """Single point on the equity curve."""

    timestamp: datetime
    equity: float
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    drawdown_pct: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "equity": self.equity,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "drawdown_pct": self.drawdown_pct,
        }


@dataclass
class BacktestConfig:
    """Configuration for a backtest run."""

    strategy: Strategy
    pair: str = "BTC/USD"
    timeframe: str = "5m"
    starting_equity: float = 10000.0
    fees_bps: float = 10.0  # 10 bps = 0.1%
    slippage_bps: float = 5.0  # 5 bps = 0.05%

    # Risk limits
    max_position_size_usd: float = 1000.0
    max_trades_per_day: int = 10
    max_daily_loss_pct: float = 5.0  # 5% max daily loss

    # Position management
    exit_on_opposite_signal: bool = True

    def to_assumptions(self, num_candles: int, start_ts: str, end_ts: str) -> BacktestAssumptions:
        """Convert config to assumptions record."""
        return BacktestAssumptions(
            fees_bps=self.fees_bps,
            slippage_bps=self.slippage_bps,
            starting_equity=self.starting_equity,
            timeframe=self.timeframe,
            pair=self.pair,
            strategy_id=self.strategy.strategy_id,
            strategy_name=self.strategy.name,
            date_range_start=start_ts,
            date_range_end=end_ts,
            num_candles=num_candles,
        )


@dataclass
class BacktestResult:
    """
    Complete backtest result with full explainability.

    Contains:
    - trades: All executed trades with explainability chain
    - intents: All generated TradeIntents (including those rejected)
    - decisions: All ExecutionDecisions (approved and rejected)
    - equity_curve: Time series of equity
    - summary: Performance metrics
    - assumptions: Parameters used (for reproducibility)
    """

    trades: list[Trade] = field(default_factory=list)
    intents: list[TradeIntent] = field(default_factory=list)
    decisions: list[ExecutionDecision] = field(default_factory=list)
    equity_curve: list[EquityPoint] = field(default_factory=list)
    summary: BacktestSummary = field(default_factory=BacktestSummary)
    assumptions: BacktestAssumptions = field(default_factory=BacktestAssumptions)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "trades": [t.to_dict() for t in self.trades],
            "intents": [i.to_dict() for i in self.intents],
            "decisions": [d.to_dict() for d in self.decisions],
            "equity_curve": [e.to_dict() for e in self.equity_curve],
            "summary": {
                "total_return_pct": self.summary.total_return_pct,
                "max_drawdown_pct": self.summary.max_drawdown_pct,
                "win_rate": self.summary.win_rate,
                "profit_factor": self.summary.profit_factor,
                "expectancy": self.summary.expectancy,
                "sharpe_ratio": self.summary.sharpe_ratio,
                "num_trades": self.summary.num_trades,
                "num_winners": self.summary.num_winners,
                "num_losers": self.summary.num_losers,
                "num_rejected": self.summary.num_rejected,
                "avg_win": self.summary.avg_win,
                "avg_loss": self.summary.avg_loss,
                "largest_win": self.summary.largest_win,
                "largest_loss": self.summary.largest_loss,
                "final_equity": self.summary.final_equity,
            },
            "assumptions": {
                "fees_bps": self.assumptions.fees_bps,
                "slippage_bps": self.assumptions.slippage_bps,
                "starting_equity": self.assumptions.starting_equity,
                "timeframe": self.assumptions.timeframe,
                "pair": self.assumptions.pair,
                "strategy_id": self.assumptions.strategy_id,
                "strategy_name": self.assumptions.strategy_name,
                "date_range_start": self.assumptions.date_range_start,
                "date_range_end": self.assumptions.date_range_end,
                "num_candles": self.assumptions.num_candles,
            },
        }
