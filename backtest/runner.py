"""
Canonical Backtest Runner.

Runs bar-by-bar simulation using the same pipeline as paper trading:
    Strategy → TradeIntent → ExecutionDecision → Trade

All components use canonical contracts from shared_contracts.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
import logging
import math

from shared_contracts import (
    Strategy,
    TradeIntent,
    ExecutionDecision,
    Trade,
    MarketSnapshot,
    AccountState,
    TradeSide,
)

from strategies.indicator import evaluate_strategy
from backtest.models import (
    BacktestConfig,
    BacktestResult,
    BacktestSummary,
    EquityPoint,
)
from backtest.risk_evaluator import RiskEvaluator, RiskLimits
from backtest.simulator import ExecutionSimulator

logger = logging.getLogger(__name__)


@dataclass
class OHLCVBar:
    """Single OHLCV bar."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OHLCVBar":
        """Create from dictionary."""
        ts = data.get("timestamp") or data.get("ts") or data.get("time")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        elif isinstance(ts, (int, float)):
            ts = datetime.fromtimestamp(ts / 1000 if ts > 1e10 else ts, tz=timezone.utc)

        return cls(
            timestamp=ts,
            open=float(data.get("open") or data.get("o", 0)),
            high=float(data.get("high") or data.get("h", 0)),
            low=float(data.get("low") or data.get("l", 0)),
            close=float(data.get("close") or data.get("c", 0)),
            volume=float(data.get("volume") or data.get("v", 0)),
        )


@dataclass
class Position:
    """Active position in backtest."""

    trade: Trade
    intent: TradeIntent
    entry_price: float
    quantity: float
    side: TradeSide
    stop_loss: float
    take_profit: float
    entry_time: datetime


class BacktestRunner:
    """
    Canonical backtest runner using the trading pipeline.

    Uses the same components as paper trading:
    - Strategy evaluation via indicator registry
    - Risk evaluation producing ExecutionDecision
    - Execution simulation producing Trade
    """

    def __init__(self, config: BacktestConfig):
        """
        Initialize backtest runner.

        Args:
            config: Backtest configuration
        """
        self.config = config
        self.strategy = config.strategy

        # Initialize components
        self.risk_evaluator = RiskEvaluator(
            limits=RiskLimits(
                max_position_size_usd=config.max_position_size_usd,
                max_trades_per_day=config.max_trades_per_day,
                max_daily_loss_pct=config.max_daily_loss_pct,
            )
        )
        self.simulator = ExecutionSimulator(
            fees_bps=config.fees_bps,
            slippage_bps=config.slippage_bps,
        )

        # State
        self._reset_state()

    def _reset_state(self) -> None:
        """Reset backtest state."""
        self.equity = self.config.starting_equity
        self.realized_pnl = 0.0
        self.peak_equity = self.config.starting_equity
        self.max_drawdown = 0.0
        self.current_position: Position | None = None
        self.current_day: str = ""
        self.trades_today = 0
        self.daily_pnl = 0.0

        # Results
        self.trades: list[Trade] = []
        self.intents: list[TradeIntent] = []
        self.decisions: list[ExecutionDecision] = []
        self.equity_curve: list[EquityPoint] = []
        self.closed_pnls: list[float] = []

    def run(self, ohlcv_data: list[dict[str, Any]] | list[OHLCVBar]) -> BacktestResult:
        """
        Run backtest on OHLCV data.

        Args:
            ohlcv_data: List of OHLCV bars (dicts or OHLCVBar objects)

        Returns:
            BacktestResult with trades, intents, decisions, and metrics
        """
        self._reset_state()

        # Convert to OHLCVBar if needed
        bars = [
            bar if isinstance(bar, OHLCVBar) else OHLCVBar.from_dict(bar)
            for bar in ohlcv_data
        ]

        if not bars:
            return self._build_result(bars)

        logger.info(f"Starting backtest: {len(bars)} bars, strategy={self.strategy.name}")

        # Build historical closes for indicators
        closes: list[float] = []
        highs: list[float] = []
        lows: list[float] = []
        volumes: list[float] = []

        for i, bar in enumerate(bars):
            # Update historical data
            closes.append(bar.close)
            highs.append(bar.high)
            lows.append(bar.low)
            volumes.append(bar.volume)

            # Handle day rollover
            day_str = bar.timestamp.strftime("%Y-%m-%d")
            if day_str != self.current_day:
                self.current_day = day_str
                self.trades_today = 0
                self.daily_pnl = 0.0

            # Check SL/TP for existing position
            if self.current_position:
                exit_result = self._check_exit(bar)
                if exit_result:
                    self._close_position(exit_result[0], exit_result[1], bar.timestamp)

            # Skip first N bars to build indicator history
            min_bars = max(50, self.strategy.parameters.get("slow_ema_period", 26) + 10)
            if len(closes) < min_bars:
                self._record_equity(bar.timestamp)
                continue

            # Build MarketSnapshot
            snapshot = self._build_snapshot(bar, closes, highs, lows, volumes)

            # Evaluate strategy (MUST use Step 1 code)
            intent = evaluate_strategy(self.strategy, snapshot)

            if intent is not None:
                self.intents.append(intent)

                # Check if we should exit current position on opposite signal
                if self.current_position and self.config.exit_on_opposite_signal:
                    if intent.side != self.current_position.side:
                        self._close_position(bar.close, "signal_flip", bar.timestamp)

                # Only enter if no position
                if self.current_position is None:
                    self._process_intent(intent, bar.timestamp)

            # Record equity
            self._record_equity(bar.timestamp)

        # Close any remaining position at end
        if self.current_position and bars:
            self._close_position(bars[-1].close, "end_of_backtest", bars[-1].timestamp)

        return self._build_result(bars)

    def _build_snapshot(
        self,
        bar: OHLCVBar,
        closes: list[float],
        highs: list[float],
        lows: list[float],
        volumes: list[float],
    ) -> MarketSnapshot:
        """Build MarketSnapshot from bar and history."""
        # Estimate bid/ask from close
        spread_bps = 2.0  # Assume 2 bps spread
        mid = bar.close
        half_spread = mid * (spread_bps / 10000 / 2)

        return MarketSnapshot(
            pair=self.config.pair,
            bid=Decimal(str(mid - half_spread)),
            ask=Decimal(str(mid + half_spread)),
            last_price=Decimal(str(bar.close)),
            open=Decimal(str(bar.open)),
            high=Decimal(str(bar.high)),
            low=Decimal(str(bar.low)),
            close=Decimal(str(bar.close)),
            volume=Decimal(str(bar.volume)),
            spread_bps=spread_bps,
            indicators={
                "closes": closes.copy(),
                "highs": highs.copy(),
                "lows": lows.copy(),
                "volumes": volumes.copy(),
            },
            regime="unknown",
            volatility="normal",
            timestamp=bar.timestamp,
        )

    def _build_account_state(self) -> AccountState:
        """Build AccountState from current backtest state."""
        return AccountState(
            account_id="backtest",
            user_id="backtest",
            total_equity_usd=Decimal(str(self.equity)),
            available_balance_usd=Decimal(str(self.equity)),
            daily_pnl_usd=Decimal(str(self.daily_pnl)),
            trades_today=self.trades_today,
            drawdown_pct=self.max_drawdown,
            trading_enabled=True,
            mode="paper",
        )

    def _process_intent(self, intent: TradeIntent, timestamp: datetime) -> None:
        """Process a trade intent through risk and execution."""
        # Build account state
        account_state = self._build_account_state()

        # Evaluate risk
        decision = self.risk_evaluator.evaluate(intent, account_state)
        self.decisions.append(decision)

        if decision.is_rejected:
            logger.debug(
                f"Trade rejected: {decision.rejection_codes} - {decision.primary_rejection_reason}"
            )
            return

        # Execute trade
        trade = self.simulator.execute(
            intent=intent,
            decision=decision,
            strategy_name=self.strategy.name,
            execution_time=timestamp,
        )
        self.trades.append(trade)

        # Update state
        self.trades_today += 1

        # Open position
        self.current_position = Position(
            trade=trade,
            intent=intent,
            entry_price=float(trade.avg_fill_price),
            quantity=float(trade.total_filled_quantity),
            side=intent.side,
            stop_loss=float(intent.stop_loss),
            take_profit=float(intent.take_profit),
            entry_time=timestamp,
        )

        # Deduct fees from equity
        self.equity -= float(trade.total_fees)

        logger.debug(
            f"Opened {intent.side.value} position: entry={trade.avg_fill_price}, "
            f"size={trade.total_filled_quantity}, fee={trade.total_fees}"
        )

    def _check_exit(self, bar: OHLCVBar) -> tuple[float, str] | None:
        """Check if position should be exited on SL/TP."""
        if self.current_position is None:
            return None

        pos = self.current_position

        if pos.side == TradeSide.LONG:
            # Check stop loss (hit if low <= SL)
            if bar.low <= pos.stop_loss:
                return (pos.stop_loss, "stop_loss")
            # Check take profit (hit if high >= TP)
            if bar.high >= pos.take_profit:
                return (pos.take_profit, "take_profit")
        else:  # SHORT
            # Check stop loss (hit if high >= SL)
            if bar.high >= pos.stop_loss:
                return (pos.stop_loss, "stop_loss")
            # Check take profit (hit if low <= TP)
            if bar.low <= pos.take_profit:
                return (pos.take_profit, "take_profit")

        return None

    def _close_position(self, exit_price: float, reason: str, timestamp: datetime) -> None:
        """Close current position."""
        if self.current_position is None:
            return

        pos = self.current_position

        # Calculate P&L
        pnl, pnl_pct = self.simulator.calculate_pnl(pos.trade, exit_price, timestamp)

        # Update equity
        self.equity += pnl
        self.realized_pnl += pnl
        self.daily_pnl += pnl
        self.closed_pnls.append(pnl)

        # Update peak/drawdown
        if self.equity > self.peak_equity:
            self.peak_equity = self.equity
        current_dd = (self.peak_equity - self.equity) / self.peak_equity * 100
        if current_dd > self.max_drawdown:
            self.max_drawdown = current_dd

        logger.debug(
            f"Closed {pos.side.value} position: exit={exit_price:.2f}, "
            f"pnl=${pnl:.2f} ({pnl_pct:.2f}%), reason={reason}"
        )

        self.current_position = None

    def _record_equity(self, timestamp: datetime) -> None:
        """Record equity point."""
        unrealized = 0.0
        if self.current_position:
            # Would need current price to calculate, skip for now
            pass

        drawdown = (self.peak_equity - self.equity) / self.peak_equity * 100 if self.peak_equity > 0 else 0

        self.equity_curve.append(
            EquityPoint(
                timestamp=timestamp,
                equity=self.equity,
                realized_pnl=self.realized_pnl,
                unrealized_pnl=unrealized,
                drawdown_pct=drawdown,
            )
        )

    def _build_result(self, bars: list[OHLCVBar]) -> BacktestResult:
        """Build final backtest result with summary."""
        # Calculate summary statistics
        num_trades = len([t for t in self.trades])
        num_rejected = len([d for d in self.decisions if d.is_rejected])

        winners = [p for p in self.closed_pnls if p > 0]
        losers = [p for p in self.closed_pnls if p < 0]

        num_winners = len(winners)
        num_losers = len(losers)

        win_rate = num_winners / len(self.closed_pnls) * 100 if self.closed_pnls else 0
        avg_win = sum(winners) / len(winners) if winners else 0
        avg_loss = sum(losers) / len(losers) if losers else 0

        # Profit factor
        gross_profit = sum(winners) if winners else 0
        gross_loss = abs(sum(losers)) if losers else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

        # Expectancy
        expectancy = (win_rate / 100 * avg_win) + ((1 - win_rate / 100) * avg_loss) if self.closed_pnls else 0

        # Sharpe ratio (simplified, annualized)
        if len(self.closed_pnls) > 1:
            returns = self.closed_pnls
            mean_return = sum(returns) / len(returns)
            variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
            std_return = math.sqrt(variance) if variance > 0 else 0
            sharpe = (mean_return / std_return) * math.sqrt(252) if std_return > 0 else 0
        else:
            sharpe = 0

        # Total return
        total_return = ((self.equity - self.config.starting_equity) / self.config.starting_equity) * 100

        summary = BacktestSummary(
            total_return_pct=total_return,
            max_drawdown_pct=self.max_drawdown,
            win_rate=win_rate,
            profit_factor=profit_factor,
            expectancy=expectancy,
            sharpe_ratio=sharpe,
            num_trades=num_trades,
            num_winners=num_winners,
            num_losers=num_losers,
            num_rejected=num_rejected,
            avg_win=avg_win,
            avg_loss=avg_loss,
            largest_win=max(winners) if winners else 0,
            largest_loss=min(losers) if losers else 0,
            final_equity=self.equity,
        )

        # Build assumptions
        start_ts = bars[0].timestamp.isoformat() if bars else ""
        end_ts = bars[-1].timestamp.isoformat() if bars else ""
        assumptions = self.config.to_assumptions(len(bars), start_ts, end_ts)

        return BacktestResult(
            trades=self.trades,
            intents=self.intents,
            decisions=self.decisions,
            equity_curve=self.equity_curve,
            summary=summary,
            assumptions=assumptions,
        )
