"""
M1 - Paper Trading Criteria Validator

Validates paper trading performance against production rollout criteria:
- Performance: PF ≥ 1.30, Sharpe ≥ 1.0, MaxDD ≤ 6%, ≥ 60 trades
- Execution: Maker fill ratio ≥ 65%, spread skips < 25%
- Risk: No >3 loss streak without cooldown

Monitors paper trading for 7-14 days and generates go/no-go decision.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional, List, Dict, Tuple

import pandas as pd
import redis

logger = logging.getLogger(__name__)


@dataclass
class PaperTradingCriteria:
    """M1 - Paper trading validation criteria"""

    # Performance criteria
    min_profit_factor: float = 1.30
    min_sharpe_ratio: float = 1.0
    max_drawdown_pct: float = 6.0
    min_trades: int = 60

    # Execution quality criteria
    min_maker_fill_ratio: float = 0.65  # 65%
    max_spread_skip_ratio: float = 0.25  # 25%

    # Risk criteria
    max_consecutive_losses: int = 3
    cooldown_after_loss_streak_minutes: int = 30

    # Duration
    min_paper_days: int = 7
    max_paper_days: int = 14


@dataclass
class PaperTradingMetrics:
    """Aggregated paper trading metrics"""

    # Period
    start_date: datetime
    end_date: datetime
    days_elapsed: int

    # Performance
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    profit_factor: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown_pct: float
    total_return_pct: float
    cagr_pct: float

    # Execution quality
    total_signals: int
    maker_fills: int
    taker_fills: int
    maker_fill_ratio: float
    spread_skips: int
    spread_skip_ratio: float

    # Risk
    max_consecutive_losses: int
    current_loss_streak: int
    cooldown_violations: int  # Times traded during cooldown

    # Pass/fail
    performance_pass: bool
    execution_pass: bool
    risk_pass: bool
    overall_pass: bool


class LossStreakMonitor:
    """
    Monitors consecutive losses and enforces cooldown periods.

    Tracks loss streaks and prevents trading during cooldown after
    excessive consecutive losses.
    """

    def __init__(
        self,
        max_consecutive_losses: int = 3,
        cooldown_minutes: int = 30,
        redis_client: Optional[redis.Redis] = None,
    ):
        """
        Initialize loss streak monitor.

        Args:
            max_consecutive_losses: Max consecutive losses before cooldown
            cooldown_minutes: Cooldown duration in minutes
            redis_client: Optional Redis client for persistence
        """
        self.max_consecutive_losses = max_consecutive_losses
        self.cooldown_minutes = cooldown_minutes
        self.redis_client = redis_client

        # State
        self.current_streak = 0
        self.max_streak_seen = 0
        self.cooldown_until: Optional[datetime] = None
        self.cooldown_violations = 0

        logger.info(
            f"LossStreakMonitor: max_losses={max_consecutive_losses}, "
            f"cooldown={cooldown_minutes}min"
        )

    def record_trade_result(
        self,
        is_win: bool,
        timestamp: datetime,
    ) -> Tuple[bool, Optional[str]]:
        """
        Record trade result and check cooldown.

        Args:
            is_win: True if trade was profitable
            timestamp: Trade close timestamp

        Returns:
            Tuple of (allowed, reason) - False if in cooldown
        """
        # Check if in cooldown
        if self.is_in_cooldown(timestamp):
            self.cooldown_violations += 1
            return False, f"cooldown_until_{self.cooldown_until.strftime('%H:%M:%S')}"

        # Update streak
        if is_win:
            # Win resets streak
            self.current_streak = 0
        else:
            # Loss increments streak
            self.current_streak += 1
            self.max_streak_seen = max(self.max_streak_seen, self.current_streak)

            # Check if cooldown needed
            if self.current_streak >= self.max_consecutive_losses:
                self.cooldown_until = timestamp + timedelta(minutes=self.cooldown_minutes)
                logger.warning(
                    f"Loss streak {self.current_streak} reached, "
                    f"cooldown until {self.cooldown_until}"
                )

                # Publish to Redis
                if self.redis_client:
                    self._publish_cooldown_event(timestamp)

        return True, None

    def is_in_cooldown(self, timestamp: datetime) -> bool:
        """Check if currently in cooldown period"""
        if self.cooldown_until is None:
            return False

        return timestamp < self.cooldown_until

    def get_status(self, timestamp: datetime) -> Dict[str, any]:
        """Get current monitor status"""
        return {
            "current_streak": self.current_streak,
            "max_streak_seen": self.max_streak_seen,
            "in_cooldown": self.is_in_cooldown(timestamp),
            "cooldown_until": self.cooldown_until.isoformat() if self.cooldown_until else None,
            "cooldown_violations": self.cooldown_violations,
        }

    def _publish_cooldown_event(self, timestamp: datetime) -> None:
        """Publish cooldown event to Redis"""
        if not self.redis_client:
            return

        event = {
            "timestamp": timestamp.isoformat(),
            "event": "loss_streak_cooldown",
            "streak": str(self.current_streak),
            "cooldown_until": self.cooldown_until.isoformat(),
        }

        try:
            self.redis_client.xadd("metrics:paper_trading", event)
        except Exception as e:
            logger.error(f"Failed to publish cooldown event: {e}")


class PaperTradingValidator:
    """
    M1 - Paper trading validation engine.

    Monitors paper trading performance and execution quality over 7-14 days
    and validates against production rollout criteria.
    """

    def __init__(
        self,
        criteria: Optional[PaperTradingCriteria] = None,
        redis_client: Optional[redis.Redis] = None,
    ):
        """
        Initialize paper trading validator.

        Args:
            criteria: Validation criteria (uses defaults if None)
            redis_client: Redis client for metrics storage
        """
        self.criteria = criteria or PaperTradingCriteria()
        self.redis_client = redis_client

        # Loss streak monitor
        self.loss_monitor = LossStreakMonitor(
            max_consecutive_losses=self.criteria.max_consecutive_losses,
            cooldown_minutes=self.criteria.cooldown_after_loss_streak_minutes,
            redis_client=redis_client,
        )

        logger.info("PaperTradingValidator initialized with criteria:")
        logger.info(f"  Performance: PF≥{self.criteria.min_profit_factor}, "
                   f"Sharpe≥{self.criteria.min_sharpe_ratio}, "
                   f"MaxDD≤{self.criteria.max_drawdown_pct}%, "
                   f"Trades≥{self.criteria.min_trades}")
        logger.info(f"  Execution: MakerFill≥{self.criteria.min_maker_fill_ratio*100}%, "
                   f"SpreadSkip<{self.criteria.max_spread_skip_ratio*100}%")
        logger.info(f"  Risk: MaxLossStreak≤{self.criteria.max_consecutive_losses}, "
                   f"Cooldown={self.criteria.cooldown_after_loss_streak_minutes}min")

    def calculate_metrics_from_trades(
        self,
        trades_df: pd.DataFrame,
        signals_df: pd.DataFrame,
        start_date: datetime,
        end_date: datetime,
    ) -> PaperTradingMetrics:
        """
        Calculate paper trading metrics from trades and signals.

        Args:
            trades_df: DataFrame with closed trades (columns: entry_time, exit_time, pnl, pnl_pct, status, fill_type)
            signals_df: DataFrame with all signals (columns: timestamp, action, reason)
            start_date: Paper trading start date
            end_date: Paper trading end date (or now)

        Returns:
            PaperTradingMetrics with aggregated stats
        """
        # Period
        days_elapsed = (end_date - start_date).days

        # Performance metrics
        total_trades = len(trades_df)

        if total_trades == 0:
            # No trades yet
            return self._empty_metrics(start_date, end_date, days_elapsed)

        # Win/loss breakdown
        winning_trades = len(trades_df[trades_df["pnl"] > 0])
        losing_trades = len(trades_df[trades_df["pnl"] < 0])
        win_rate_pct = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0

        # Profit factor
        gross_profit = trades_df[trades_df["pnl"] > 0]["pnl"].sum()
        gross_loss = abs(trades_df[trades_df["pnl"] < 0]["pnl"].sum())
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0.0

        # Sharpe/Sortino (simplified - using trade returns)
        returns = trades_df["pnl_pct"].values
        sharpe_ratio = self._calculate_sharpe(returns)
        sortino_ratio = self._calculate_sortino(returns)

        # Max drawdown
        cumulative_pnl = trades_df["pnl"].cumsum()
        running_max = cumulative_pnl.expanding().max()
        drawdown = cumulative_pnl - running_max
        max_drawdown_pct = abs(drawdown.min() / trades_df.iloc[0].get("initial_capital", 10000) * 100)

        # Total return
        total_return_pct = cumulative_pnl.iloc[-1] / trades_df.iloc[0].get("initial_capital", 10000) * 100

        # CAGR (annualized)
        years = days_elapsed / 365.0
        cagr_pct = ((1 + total_return_pct/100) ** (1/years) - 1) * 100 if years > 0 else 0.0

        # Execution quality
        total_signals = len(signals_df)

        # Maker/taker fills
        maker_fills = len(trades_df[trades_df.get("fill_type", "maker") == "maker"])
        taker_fills = total_trades - maker_fills
        maker_fill_ratio = (maker_fills / total_trades) if total_trades > 0 else 0.0

        # Spread skips (signals that didn't become trades due to spread)
        spread_skips = len(signals_df[signals_df.get("reason", "") == "spread_too_wide"])
        spread_skip_ratio = (spread_skips / total_signals) if total_signals > 0 else 0.0

        # Risk metrics (loss streaks)
        self._update_loss_streaks(trades_df)

        max_consecutive_losses = self.loss_monitor.max_streak_seen
        current_loss_streak = self.loss_monitor.current_streak
        cooldown_violations = self.loss_monitor.cooldown_violations

        # Pass/fail checks
        performance_pass = (
            profit_factor >= self.criteria.min_profit_factor and
            sharpe_ratio >= self.criteria.min_sharpe_ratio and
            max_drawdown_pct <= self.criteria.max_drawdown_pct and
            total_trades >= self.criteria.min_trades
        )

        execution_pass = (
            maker_fill_ratio >= self.criteria.min_maker_fill_ratio and
            spread_skip_ratio <= self.criteria.max_spread_skip_ratio
        )

        risk_pass = (
            max_consecutive_losses <= self.criteria.max_consecutive_losses and
            cooldown_violations == 0
        )

        overall_pass = performance_pass and execution_pass and risk_pass

        return PaperTradingMetrics(
            start_date=start_date,
            end_date=end_date,
            days_elapsed=days_elapsed,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate_pct=win_rate_pct,
            profit_factor=profit_factor,
            sharpe_ratio=sharpe_ratio,
            sortino_ratio=sortino_ratio,
            max_drawdown_pct=max_drawdown_pct,
            total_return_pct=total_return_pct,
            cagr_pct=cagr_pct,
            total_signals=total_signals,
            maker_fills=maker_fills,
            taker_fills=taker_fills,
            maker_fill_ratio=maker_fill_ratio,
            spread_skips=spread_skips,
            spread_skip_ratio=spread_skip_ratio,
            max_consecutive_losses=max_consecutive_losses,
            current_loss_streak=current_loss_streak,
            cooldown_violations=cooldown_violations,
            performance_pass=performance_pass,
            execution_pass=execution_pass,
            risk_pass=risk_pass,
            overall_pass=overall_pass,
        )

    def _empty_metrics(
        self,
        start_date: datetime,
        end_date: datetime,
        days_elapsed: int,
    ) -> PaperTradingMetrics:
        """Return empty metrics when no trades"""
        return PaperTradingMetrics(
            start_date=start_date,
            end_date=end_date,
            days_elapsed=days_elapsed,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate_pct=0.0,
            profit_factor=0.0,
            sharpe_ratio=0.0,
            sortino_ratio=0.0,
            max_drawdown_pct=0.0,
            total_return_pct=0.0,
            cagr_pct=0.0,
            total_signals=0,
            maker_fills=0,
            taker_fills=0,
            maker_fill_ratio=0.0,
            spread_skips=0,
            spread_skip_ratio=0.0,
            max_consecutive_losses=0,
            current_loss_streak=0,
            cooldown_violations=0,
            performance_pass=False,
            execution_pass=False,
            risk_pass=False,
            overall_pass=False,
        )

    def _update_loss_streaks(self, trades_df: pd.DataFrame) -> None:
        """Update loss streak monitor from trades"""
        for _, trade in trades_df.iterrows():
            is_win = trade["pnl"] > 0
            exit_time = pd.to_datetime(trade["exit_time"])

            if exit_time.tzinfo is None:
                exit_time = exit_time.replace(tzinfo=timezone.utc)

            self.loss_monitor.record_trade_result(is_win, exit_time)

    def _calculate_sharpe(self, returns: np.ndarray) -> float:
        """Calculate Sharpe ratio from returns"""
        if len(returns) == 0:
            return 0.0

        mean_return = returns.mean()
        std_return = returns.std()

        if std_return == 0:
            return 0.0

        # Annualize (assuming daily trades)
        sharpe = (mean_return / std_return) * np.sqrt(252)
        return sharpe

    def _calculate_sortino(self, returns: np.ndarray) -> float:
        """Calculate Sortino ratio from returns"""
        if len(returns) == 0:
            return 0.0

        mean_return = returns.mean()
        downside_returns = returns[returns < 0]

        if len(downside_returns) == 0:
            return 0.0

        downside_std = downside_returns.std()

        if downside_std == 0:
            return 0.0

        # Annualize
        sortino = (mean_return / downside_std) * np.sqrt(252)
        return sortino

    def generate_validation_report(
        self,
        metrics: PaperTradingMetrics,
    ) -> str:
        """
        Generate human-readable validation report.

        Args:
            metrics: Paper trading metrics

        Returns:
            Formatted report string
        """
        report = []
        report.append("=" * 80)
        report.append("M1 - PAPER TRADING VALIDATION REPORT")
        report.append("=" * 80)
        report.append(f"Period: {metrics.start_date.strftime('%Y-%m-%d')} to {metrics.end_date.strftime('%Y-%m-%d')}")
        report.append(f"Duration: {metrics.days_elapsed} days (min: {self.criteria.min_paper_days})")
        report.append("")

        # Performance
        report.append("PERFORMANCE CRITERIA")
        report.append("-" * 80)
        report.append(self._format_criterion(
            "Profit Factor",
            metrics.profit_factor,
            self.criteria.min_profit_factor,
            ">=",
            metrics.profit_factor >= self.criteria.min_profit_factor
        ))
        report.append(self._format_criterion(
            "Sharpe Ratio",
            metrics.sharpe_ratio,
            self.criteria.min_sharpe_ratio,
            ">=",
            metrics.sharpe_ratio >= self.criteria.min_sharpe_ratio
        ))
        report.append(self._format_criterion(
            "Max Drawdown",
            metrics.max_drawdown_pct,
            self.criteria.max_drawdown_pct,
            "<=",
            metrics.max_drawdown_pct <= self.criteria.max_drawdown_pct,
            suffix="%"
        ))
        report.append(self._format_criterion(
            "Total Trades",
            metrics.total_trades,
            self.criteria.min_trades,
            ">=",
            metrics.total_trades >= self.criteria.min_trades
        ))
        report.append(f"  Win Rate: {metrics.win_rate_pct:.1f}%")
        report.append(f"  Total Return: {metrics.total_return_pct:+.2f}%")
        report.append(f"  CAGR: {metrics.cagr_pct:+.2f}%")
        report.append(f"  → Performance: {'PASS [OK]' if metrics.performance_pass else 'FAIL [X]'}")
        report.append("")

        # Execution quality
        report.append("EXECUTION QUALITY")
        report.append("-" * 80)
        report.append(self._format_criterion(
            "Maker Fill Ratio",
            metrics.maker_fill_ratio * 100,
            self.criteria.min_maker_fill_ratio * 100,
            ">=",
            metrics.maker_fill_ratio >= self.criteria.min_maker_fill_ratio,
            suffix="%"
        ))
        report.append(f"  Maker fills: {metrics.maker_fills}/{metrics.total_trades}")
        report.append(f"  Taker fills: {metrics.taker_fills}/{metrics.total_trades}")
        report.append(self._format_criterion(
            "Spread Skip Ratio",
            metrics.spread_skip_ratio * 100,
            self.criteria.max_spread_skip_ratio * 100,
            "<=",
            metrics.spread_skip_ratio <= self.criteria.max_spread_skip_ratio,
            suffix="%"
        ))
        report.append(f"  Spread skips: {metrics.spread_skips}/{metrics.total_signals}")
        report.append(f"  → Execution: {'PASS [OK]' if metrics.execution_pass else 'FAIL [X]'}")
        report.append("")

        # Risk
        report.append("RISK CONTROLS")
        report.append("-" * 80)
        report.append(self._format_criterion(
            "Max Loss Streak",
            metrics.max_consecutive_losses,
            self.criteria.max_consecutive_losses,
            "<=",
            metrics.max_consecutive_losses <= self.criteria.max_consecutive_losses
        ))
        report.append(f"  Current streak: {metrics.current_loss_streak}")
        report.append(self._format_criterion(
            "Cooldown Violations",
            metrics.cooldown_violations,
            0,
            "=",
            metrics.cooldown_violations == 0
        ))
        report.append(f"  → Risk: {'PASS [OK]' if metrics.risk_pass else 'FAIL [X]'}")
        report.append("")

        # Overall
        report.append("=" * 80)
        report.append("OVERALL VERDICT")
        report.append("=" * 80)

        if metrics.overall_pass and metrics.days_elapsed >= self.criteria.min_paper_days:
            report.append("[OK] ALL CRITERIA PASSED - READY FOR LIVE TRADING")
        elif metrics.overall_pass:
            report.append(f"[WAIT] All criteria passed but need {self.criteria.min_paper_days - metrics.days_elapsed} more days")
        else:
            report.append("[X] CRITERIA NOT MET - CONTINUE PAPER TRADING")
            if not metrics.performance_pass:
                report.append("  - Performance criteria failed")
            if not metrics.execution_pass:
                report.append("  - Execution quality failed")
            if not metrics.risk_pass:
                report.append("  - Risk controls failed")

        report.append("=" * 80)

        return "\n".join(report)

    def _format_criterion(
        self,
        name: str,
        value: float,
        threshold: float,
        operator: str,
        passed: bool,
        suffix: str = "",
    ) -> str:
        """Format single criterion line"""
        status = "PASS" if passed else "FAIL"
        return (
            f"  {name}: {value:.2f}{suffix} {operator} {threshold:.2f}{suffix} "
            f"→ {status}"
        )
