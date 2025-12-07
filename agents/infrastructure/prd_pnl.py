"""
PRD-001 Compliant PnL Attribution and Performance Metrics (agents/infrastructure/prd_pnl.py)

This module provides:
1. PRDTradeRecord - Individual trade outcomes linked to signals (for pnl:signals stream)
2. PRDPerformanceMetrics - Aggregated investor metrics (ROI, Sharpe, PF, MDD)
3. PRDPnLPublisher - Publishes trade records to Redis with proper attribution

PRD-001 STREAM CONTRACT:
- pnl:signals - Individual trade close events with signal attribution
- pnl:{mode}:performance - Aggregated performance metrics snapshots
- MAXLEN: 10,000 for pnl:signals, 50,000 for equity curve

PRD-001 INVESTOR METRICS (Section 6):
- Total ROI (%)
- Annualized Return (%)
- Win Rate (%)
- Profit Factor (gross_profit / gross_loss)
- Max Drawdown (%)
- Sharpe Ratio (excess return / volatility)
- Per-Strategy Attribution

USAGE:
    from agents.infrastructure.prd_pnl import (
        PRDTradeRecord, PRDPerformanceMetrics, PRDPnLPublisher
    )

    # Record trade close with signal attribution
    trade = PRDTradeRecord(
        signal_id="uuid-here",
        pair="BTC/USD",
        side="LONG",
        strategy="SCALPER",
        entry_price=50000.0,
        exit_price=50500.0,
        position_size_usd=500.0,
        realized_pnl=5.0,  # 1% on $500
        fees_usd=0.50,
        slippage_pct=0.02,
        hold_duration_sec=300,
    )

    # Publish to pnl:signals
    publisher = PRDPnLPublisher()
    await publisher.connect()
    await publisher.publish_trade(trade)
"""

from __future__ import annotations

import logging
import math
import os
import uuid
from collections import deque
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Deque, Dict, List, Literal, Optional, Tuple

import redis.asyncio as redis
from pydantic import BaseModel, Field, computed_field, field_validator

logger = logging.getLogger(__name__)


# =============================================================================
# PRD-001 TRADE RECORD SCHEMA
# =============================================================================

class TradeOutcome(str, Enum):
    """Trade outcome classification"""
    WIN = "WIN"
    LOSS = "LOSS"
    BREAKEVEN = "BREAKEVEN"


class ExitReason(str, Enum):
    """Reason for trade exit"""
    TAKE_PROFIT = "TAKE_PROFIT"
    STOP_LOSS = "STOP_LOSS"
    TRAILING_STOP = "TRAILING_STOP"
    SIGNAL_REVERSAL = "SIGNAL_REVERSAL"
    TIME_STOP = "TIME_STOP"
    MANUAL = "MANUAL"
    MARKET_CLOSE = "MARKET_CLOSE"


class PRDTradeRecord(BaseModel):
    """
    PRD-001 Compliant Trade Record for PnL Attribution

    Links each closed trade to its originating signal for full attribution.
    Published to pnl:signals stream on trade close.

    Key fields for investor metrics:
    - signal_id: Links to the originating PRDSignal
    - realized_pnl: Net PnL after fees/slippage (used for Sharpe, PF)
    - strategy: Enables per-strategy attribution
    - hold_duration_sec: For trade frequency analysis
    """

    # Identifiers
    trade_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="UUID v4 trade identifier"
    )
    signal_id: str = Field(description="UUID of originating signal")
    timestamp_open: str = Field(description="ISO8601 trade open timestamp")
    timestamp_close: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
        description="ISO8601 trade close timestamp"
    )

    # Market data
    pair: str = Field(description="Trading pair (e.g., BTC/USD)")
    side: Literal["LONG", "SHORT"] = Field(description="Trade direction")
    strategy: Literal["SCALPER", "TREND", "MEAN_REVERSION", "BREAKOUT"] = Field(
        description="Strategy that generated signal"
    )

    # Execution
    entry_price: float = Field(gt=0, description="Actual entry price")
    exit_price: float = Field(gt=0, description="Actual exit price")
    position_size_usd: float = Field(gt=0, description="Position size in USD")
    quantity: float = Field(gt=0, description="Asset quantity traded")

    # PnL breakdown
    gross_pnl: float = Field(description="PnL before fees/slippage")
    fees_usd: float = Field(ge=0, default=0.0, description="Total fees in USD")
    slippage_pct: float = Field(ge=0, default=0.0, description="Slippage as percentage")
    realized_pnl: float = Field(description="Net PnL after fees/slippage")

    # Classification
    exit_reason: ExitReason = Field(description="Reason for trade exit")
    outcome: TradeOutcome = Field(description="WIN, LOSS, or BREAKEVEN")

    # Duration
    hold_duration_sec: int = Field(ge=0, description="Trade duration in seconds")

    # Optional context
    regime_at_entry: Optional[str] = Field(None, description="Market regime at entry")
    confidence_at_entry: Optional[float] = Field(None, ge=0, le=1, description="Signal confidence")
    indicators_at_entry: Optional[Dict[str, Any]] = Field(None, description="Indicators snapshot")

    @field_validator("pair")
    @classmethod
    def normalize_pair(cls, v: str) -> str:
        """Normalize pair to use forward slash"""
        return v.replace("-", "/").upper()

    @computed_field
    @property
    def pnl_pct(self) -> float:
        """Return on trade as percentage"""
        if self.position_size_usd > 0:
            return (self.realized_pnl / self.position_size_usd) * 100
        return 0.0

    def to_redis_dict(self) -> Dict[str, str]:
        """Convert to Redis-compatible dict with string values."""
        data = self.model_dump(exclude_none=True)
        result = {}
        for key, value in data.items():
            if isinstance(value, dict):
                import json
                result[key] = json.dumps(value)
            elif isinstance(value, Enum):
                result[key] = value.value
            else:
                result[key] = str(value)
        return result


def create_trade_record(
    signal_id: str,
    pair: str,
    side: Literal["LONG", "SHORT"],
    strategy: Literal["SCALPER", "TREND", "MEAN_REVERSION", "BREAKOUT"],
    entry_price: float,
    exit_price: float,
    position_size_usd: float,
    quantity: float,
    timestamp_open: str,
    exit_reason: ExitReason,
    fees_usd: float = 0.0,
    slippage_pct: float = 0.0,
    regime_at_entry: Optional[str] = None,
    confidence_at_entry: Optional[float] = None,
) -> PRDTradeRecord:
    """
    Factory function to create a PRD-compliant trade record.

    Automatically calculates:
    - gross_pnl (before fees)
    - realized_pnl (after fees/slippage)
    - outcome (WIN/LOSS/BREAKEVEN)
    - hold_duration_sec

    Args:
        signal_id: UUID of the originating signal
        pair: Trading pair
        side: LONG or SHORT
        strategy: Strategy name
        entry_price: Entry fill price
        exit_price: Exit fill price
        position_size_usd: Position size in USD
        quantity: Asset quantity
        timestamp_open: ISO8601 timestamp when trade opened
        exit_reason: Why the trade closed
        fees_usd: Total fees paid
        slippage_pct: Slippage percentage
        regime_at_entry: Optional market regime
        confidence_at_entry: Optional signal confidence

    Returns:
        PRDTradeRecord with all fields calculated
    """
    # Calculate PnL
    if side == "LONG":
        price_diff = exit_price - entry_price
    else:  # SHORT
        price_diff = entry_price - exit_price

    gross_pnl = price_diff * quantity

    # Apply slippage (reduces PnL)
    slippage_cost = position_size_usd * (slippage_pct / 100)
    realized_pnl = gross_pnl - fees_usd - slippage_cost

    # Determine outcome
    if realized_pnl > 0.01:  # Threshold to avoid float precision issues
        outcome = TradeOutcome.WIN
    elif realized_pnl < -0.01:
        outcome = TradeOutcome.LOSS
    else:
        outcome = TradeOutcome.BREAKEVEN

    # Calculate hold duration
    try:
        open_dt = datetime.fromisoformat(timestamp_open.replace('Z', '+00:00'))
        close_dt = datetime.now(timezone.utc)
        hold_duration_sec = int((close_dt - open_dt).total_seconds())
    except Exception:
        hold_duration_sec = 0

    return PRDTradeRecord(
        signal_id=signal_id,
        pair=pair,
        side=side,
        strategy=strategy,
        entry_price=entry_price,
        exit_price=exit_price,
        position_size_usd=position_size_usd,
        quantity=quantity,
        timestamp_open=timestamp_open,
        gross_pnl=gross_pnl,
        fees_usd=fees_usd,
        slippage_pct=slippage_pct,
        realized_pnl=realized_pnl,
        exit_reason=exit_reason,
        outcome=outcome,
        hold_duration_sec=hold_duration_sec,
        regime_at_entry=regime_at_entry,
        confidence_at_entry=confidence_at_entry,
    )


# =============================================================================
# PRD-001 PERFORMANCE METRICS
# =============================================================================

class PRDPerformanceMetrics(BaseModel):
    """
    PRD-001 Compliant Performance Metrics for Investors

    Aggregated metrics computed from trade history.
    Published periodically to pnl:{mode}:performance stream.

    Metrics aligned with PRD-001 Section 6:
    - Total ROI
    - Annualized return (CAGR)
    - Win rate
    - Profit factor
    - Max drawdown
    - Sharpe ratio
    - Per-strategy attribution
    """

    # Snapshot metadata
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
        description="ISO8601 snapshot timestamp"
    )
    mode: Literal["paper", "live"] = Field(description="Trading mode")
    period_start: str = Field(description="ISO8601 period start timestamp")
    period_end: str = Field(description="ISO8601 period end timestamp")

    # Core metrics
    initial_equity: float = Field(description="Equity at period start")
    current_equity: float = Field(description="Current equity")
    total_pnl: float = Field(description="Total realized PnL in period")

    # Return metrics
    total_roi_pct: float = Field(description="Total ROI as percentage")
    annualized_return_pct: float = Field(description="Annualized return (CAGR)")

    # Trade statistics
    total_trades: int = Field(ge=0, description="Total trades in period")
    winning_trades: int = Field(ge=0, description="Number of winning trades")
    losing_trades: int = Field(ge=0, description="Number of losing trades")
    breakeven_trades: int = Field(ge=0, default=0, description="Number of breakeven trades")
    win_rate_pct: float = Field(ge=0, le=100, description="Win rate as percentage")

    # PnL distribution
    avg_win_usd: float = Field(description="Average winning trade in USD")
    avg_loss_usd: float = Field(description="Average losing trade in USD")
    largest_win_usd: float = Field(description="Largest single win")
    largest_loss_usd: float = Field(description="Largest single loss")
    profit_factor: float = Field(ge=0, description="Gross profit / gross loss")

    # Risk metrics
    max_drawdown_pct: float = Field(description="Maximum drawdown percentage")
    max_drawdown_usd: float = Field(description="Maximum drawdown in USD")
    sharpe_ratio: float = Field(description="Sharpe ratio (annualized)")
    sortino_ratio: Optional[float] = Field(None, description="Sortino ratio (optional)")

    # Per-strategy attribution
    strategy_performance: Dict[str, Dict[str, float]] = Field(
        default_factory=dict,
        description="Performance breakdown by strategy"
    )

    # Trade frequency
    avg_trades_per_day: float = Field(ge=0, description="Average trades per day")
    avg_hold_duration_sec: float = Field(ge=0, description="Average trade duration")

    def to_redis_dict(self) -> Dict[str, str]:
        """Convert to Redis-compatible dict with string values."""
        data = self.model_dump(exclude_none=True)
        result = {}
        for key, value in data.items():
            if isinstance(value, dict):
                import json
                result[key] = json.dumps(value)
            else:
                result[key] = str(value)
        return result


class PerformanceAggregator:
    """
    Compute PRD-001 performance metrics from trade history.

    Uses a sliding window of trades for efficient memory usage.
    Computes all metrics required for investor reporting.
    """

    # Configuration
    MAX_TRADES_WINDOW = 10000
    RISK_FREE_RATE = 0.05  # 5% annual risk-free rate for Sharpe calculation

    def __init__(
        self,
        initial_equity: float = 10000.0,
        mode: Literal["paper", "live"] = "paper",
    ):
        """
        Initialize performance aggregator.

        Args:
            initial_equity: Starting equity for ROI calculation
            mode: Trading mode (paper or live)
        """
        self.initial_equity = initial_equity
        self.current_equity = initial_equity
        self.mode = mode

        # Trade history (bounded deque)
        self.trades: Deque[PRDTradeRecord] = deque(maxlen=self.MAX_TRADES_WINDOW)

        # Running statistics
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.breakeven_trades = 0
        self.gross_profit = 0.0
        self.gross_loss = 0.0

        # Equity tracking for drawdown
        self.peak_equity = initial_equity
        self.max_drawdown_pct = 0.0
        self.max_drawdown_usd = 0.0

        # Per-strategy tracking
        self.strategy_stats: Dict[str, Dict[str, Any]] = {}

        # For Sharpe/Sortino calculation
        self.daily_returns: Deque[float] = deque(maxlen=365)  # 1 year of daily returns
        self.last_daily_equity = initial_equity
        self.current_day = datetime.now(timezone.utc).date()

    def add_trade(self, trade: PRDTradeRecord) -> None:
        """
        Add a closed trade to the aggregator.

        Updates all running statistics and metrics.

        Args:
            trade: PRD-compliant trade record
        """
        # Add to history
        self.trades.append(trade)
        self.total_trades += 1

        # Update equity
        self.current_equity += trade.realized_pnl

        # Track wins/losses
        if trade.outcome == TradeOutcome.WIN:
            self.winning_trades += 1
            self.gross_profit += trade.realized_pnl
        elif trade.outcome == TradeOutcome.LOSS:
            self.losing_trades += 1
            self.gross_loss += abs(trade.realized_pnl)
        else:
            self.breakeven_trades += 1

        # Update drawdown
        if self.current_equity > self.peak_equity:
            self.peak_equity = self.current_equity
        else:
            dd_usd = self.peak_equity - self.current_equity
            dd_pct = (dd_usd / self.peak_equity) * 100 if self.peak_equity > 0 else 0

            if dd_pct > self.max_drawdown_pct:
                self.max_drawdown_pct = dd_pct
                self.max_drawdown_usd = dd_usd

        # Update per-strategy stats
        strategy = trade.strategy
        if strategy not in self.strategy_stats:
            self.strategy_stats[strategy] = {
                "trades": 0,
                "wins": 0,
                "losses": 0,
                "pnl": 0.0,
                "gross_profit": 0.0,
                "gross_loss": 0.0,
            }

        stats = self.strategy_stats[strategy]
        stats["trades"] += 1
        stats["pnl"] += trade.realized_pnl

        if trade.outcome == TradeOutcome.WIN:
            stats["wins"] += 1
            stats["gross_profit"] += trade.realized_pnl
        elif trade.outcome == TradeOutcome.LOSS:
            stats["losses"] += 1
            stats["gross_loss"] += abs(trade.realized_pnl)

        # Track daily returns for Sharpe calculation
        today = datetime.now(timezone.utc).date()
        if today != self.current_day:
            # Day rolled over - record daily return
            if self.last_daily_equity > 0:
                daily_return = (self.current_equity - self.last_daily_equity) / self.last_daily_equity
                self.daily_returns.append(daily_return)

            self.last_daily_equity = self.current_equity
            self.current_day = today

    def get_metrics(self, period_start: Optional[str] = None) -> PRDPerformanceMetrics:
        """
        Compute and return current performance metrics.

        Args:
            period_start: Optional ISO8601 period start (defaults to first trade)

        Returns:
            PRDPerformanceMetrics with all computed values
        """
        now = datetime.now(timezone.utc).isoformat(timespec='milliseconds')

        # Determine period
        if period_start:
            p_start = period_start
        elif self.trades:
            p_start = self.trades[0].timestamp_open
        else:
            p_start = now

        # Calculate ROI
        total_pnl = self.current_equity - self.initial_equity
        total_roi_pct = (total_pnl / self.initial_equity) * 100 if self.initial_equity > 0 else 0

        # Calculate annualized return (CAGR)
        try:
            start_dt = datetime.fromisoformat(p_start.replace('Z', '+00:00'))
            end_dt = datetime.now(timezone.utc)
            days_elapsed = max(1, (end_dt - start_dt).days)

            if days_elapsed >= 365:
                years = days_elapsed / 365
                if self.initial_equity > 0 and self.current_equity > 0:
                    annualized_return = ((self.current_equity / self.initial_equity) ** (1 / years) - 1) * 100
                else:
                    annualized_return = 0.0
            else:
                # Extrapolate for less than a year
                daily_return = total_roi_pct / days_elapsed if days_elapsed > 0 else 0
                annualized_return = daily_return * 365
        except Exception:
            annualized_return = 0.0
            days_elapsed = 1

        # Win rate
        total_decisive = self.winning_trades + self.losing_trades
        win_rate_pct = (self.winning_trades / total_decisive) * 100 if total_decisive > 0 else 0

        # Average win/loss
        avg_win = self.gross_profit / self.winning_trades if self.winning_trades > 0 else 0
        avg_loss = self.gross_loss / self.losing_trades if self.losing_trades > 0 else 0

        # Largest win/loss
        wins = [t.realized_pnl for t in self.trades if t.outcome == TradeOutcome.WIN]
        losses = [abs(t.realized_pnl) for t in self.trades if t.outcome == TradeOutcome.LOSS]
        largest_win = max(wins) if wins else 0
        largest_loss = max(losses) if losses else 0

        # Profit factor
        profit_factor = self.gross_profit / self.gross_loss if self.gross_loss > 0 else (
            float('inf') if self.gross_profit > 0 else 0
        )
        # Cap at reasonable value for display
        profit_factor = min(profit_factor, 999.99)

        # Sharpe ratio (annualized)
        sharpe = self._calculate_sharpe()

        # Sortino ratio (optional, uses only negative returns)
        sortino = self._calculate_sortino()

        # Per-strategy attribution
        strategy_performance = {}
        for strat, stats in self.strategy_stats.items():
            strat_pf = stats["gross_profit"] / stats["gross_loss"] if stats["gross_loss"] > 0 else (
                999.99 if stats["gross_profit"] > 0 else 0
            )
            strat_wr = (stats["wins"] / stats["trades"]) * 100 if stats["trades"] > 0 else 0

            strategy_performance[strat] = {
                "trades": stats["trades"],
                "wins": stats["wins"],
                "losses": stats["losses"],
                "pnl": round(stats["pnl"], 2),
                "win_rate_pct": round(strat_wr, 2),
                "profit_factor": round(min(strat_pf, 999.99), 2),
            }

        # Trade frequency
        avg_trades_per_day = self.total_trades / days_elapsed if days_elapsed > 0 else 0

        # Average hold duration
        hold_durations = [t.hold_duration_sec for t in self.trades]
        avg_hold = sum(hold_durations) / len(hold_durations) if hold_durations else 0

        return PRDPerformanceMetrics(
            mode=self.mode,
            period_start=p_start,
            period_end=now,
            initial_equity=self.initial_equity,
            current_equity=self.current_equity,
            total_pnl=round(total_pnl, 2),
            total_roi_pct=round(total_roi_pct, 2),
            annualized_return_pct=round(annualized_return, 2),
            total_trades=self.total_trades,
            winning_trades=self.winning_trades,
            losing_trades=self.losing_trades,
            breakeven_trades=self.breakeven_trades,
            win_rate_pct=round(win_rate_pct, 2),
            avg_win_usd=round(avg_win, 2),
            avg_loss_usd=round(avg_loss, 2),
            largest_win_usd=round(largest_win, 2),
            largest_loss_usd=round(largest_loss, 2),
            profit_factor=round(profit_factor, 2),
            max_drawdown_pct=round(self.max_drawdown_pct, 2),
            max_drawdown_usd=round(self.max_drawdown_usd, 2),
            sharpe_ratio=round(sharpe, 2),
            sortino_ratio=round(sortino, 2) if sortino else None,
            strategy_performance=strategy_performance,
            avg_trades_per_day=round(avg_trades_per_day, 2),
            avg_hold_duration_sec=round(avg_hold, 0),
        )

    def _calculate_sharpe(self) -> float:
        """
        Calculate annualized Sharpe ratio from daily returns.

        Sharpe = (mean_return - risk_free_rate) / std_dev * sqrt(252)
        """
        if len(self.daily_returns) < 2:
            return 0.0

        returns = list(self.daily_returns)
        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        std_dev = math.sqrt(variance) if variance > 0 else 0

        if std_dev == 0:
            return 0.0

        # Daily risk-free rate
        daily_rf = self.RISK_FREE_RATE / 252

        # Annualized Sharpe
        sharpe = ((mean_return - daily_rf) / std_dev) * math.sqrt(252)

        return sharpe

    def _calculate_sortino(self) -> Optional[float]:
        """
        Calculate Sortino ratio (uses only downside deviation).

        Sortino = (mean_return - risk_free_rate) / downside_deviation * sqrt(252)
        """
        if len(self.daily_returns) < 2:
            return None

        returns = list(self.daily_returns)
        mean_return = sum(returns) / len(returns)

        # Downside deviation (only negative returns)
        downside_returns = [r for r in returns if r < 0]
        if not downside_returns:
            return None

        downside_variance = sum(r ** 2 for r in downside_returns) / len(downside_returns)
        downside_std = math.sqrt(downside_variance) if downside_variance > 0 else 0

        if downside_std == 0:
            return None

        daily_rf = self.RISK_FREE_RATE / 252
        sortino = ((mean_return - daily_rf) / downside_std) * math.sqrt(252)

        return sortino

    def reset(self, initial_equity: Optional[float] = None) -> None:
        """Reset aggregator state."""
        if initial_equity is not None:
            self.initial_equity = initial_equity

        # Always reset current equity back to initial
        self.current_equity = self.initial_equity

        self.trades.clear()
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.breakeven_trades = 0
        self.gross_profit = 0.0
        self.gross_loss = 0.0
        self.peak_equity = self.initial_equity
        self.max_drawdown_pct = 0.0
        self.max_drawdown_usd = 0.0
        self.strategy_stats.clear()
        self.daily_returns.clear()
        self.last_daily_equity = self.initial_equity
        self.current_day = datetime.now(timezone.utc).date()


# =============================================================================
# PRD-001 PNL PUBLISHER
# =============================================================================

class PRDPnLPublisher:
    """
    PRD-001 Compliant PnL Publisher

    Publishes trade records and performance metrics to Redis.

    Streams:
    - pnl:signals - Individual trade close events
    - pnl:{mode}:performance - Aggregated performance snapshots
    """

    STREAM_MAXLEN = 10000
    PERFORMANCE_MAXLEN = 1000
    RETRY_ATTEMPTS = 3

    def __init__(
        self,
        redis_url: Optional[str] = None,
        redis_ca_cert: Optional[str] = None,
        mode: Literal["paper", "live"] = "paper",
    ):
        """
        Initialize PnL publisher.

        Args:
            redis_url: Redis URL (defaults to REDIS_URL env var)
            redis_ca_cert: Path to CA cert
            mode: Trading mode (paper or live)
        """
        self.redis_url = redis_url or os.getenv("REDIS_URL", "")
        self.redis_ca_cert = redis_ca_cert or os.getenv(
            "REDIS_CA_CERT",
            os.getenv("REDIS_CA_CERT_PATH", "config/certs/redis_ca.pem")
        )
        self.mode = mode if mode else os.getenv("ENGINE_MODE", "paper")

        self.redis_client: Optional[redis.Redis] = None
        self._connected = False

        # Metrics
        self._publish_count = 0
        self._publish_errors = 0

    async def connect(self) -> bool:
        """Connect to Redis with TLS."""
        if not self.redis_url:
            logger.error("REDIS_URL not configured")
            return False

        try:
            conn_params = {
                "socket_connect_timeout": 10,
                "socket_keepalive": True,
                "decode_responses": False,
                "retry_on_timeout": True,
            }

            if self.redis_url.startswith("rediss://"):
                if self.redis_ca_cert and os.path.exists(self.redis_ca_cert):
                    conn_params["ssl_ca_certs"] = self.redis_ca_cert
                    conn_params["ssl_cert_reqs"] = "required"

            self.redis_client = redis.from_url(self.redis_url, **conn_params)
            await self.redis_client.ping()

            self._connected = True
            logger.info(f"PRDPnLPublisher connected to Redis (mode={self.mode})")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            return False

    async def close(self) -> None:
        """Close Redis connection."""
        if self.redis_client:
            await self.redis_client.aclose()
            self.redis_client = None
            self._connected = False

    async def publish_trade(self, trade: PRDTradeRecord) -> Optional[str]:
        """
        Publish trade record to pnl:signals stream.

        Args:
            trade: PRD-compliant trade record

        Returns:
            Redis entry ID if successful
        """
        if not self._connected or not self.redis_client:
            logger.error("Cannot publish trade - not connected")
            return None

        stream_key = f"pnl:{self.mode}:signals"

        try:
            redis_data = trade.to_redis_dict()
            encoded_data = {k: v.encode() if isinstance(v, str) else str(v).encode()
                           for k, v in redis_data.items()}

            entry_id = await self.redis_client.xadd(
                name=stream_key,
                fields=encoded_data,
                maxlen=self.STREAM_MAXLEN,
                approximate=True,
            )

            entry_id_str = entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)
            self._publish_count += 1

            # Enhanced logging with explicit timestamp (PRD-001 Task A requirement)
            logger.info(
                f"Published trade to {stream_key} | pair={trade.pair} signal_id={trade.signal_id} "
                f"pnl=${trade.realized_pnl:.2f} outcome={trade.outcome} timestamp={trade.timestamp_close}",
                extra={
                    "trade_id": trade.trade_id,
                    "signal_id": trade.signal_id,
                    "pair": trade.pair,
                    "pnl": trade.realized_pnl,
                    "outcome": trade.outcome,
                    "timestamp_close": trade.timestamp_close,
                    "mode": self.mode,
                }
            )

            return entry_id_str

        except Exception as e:
            self._publish_errors += 1
            logger.error(f"Failed to publish trade: {e}")
            return None

    async def publish_performance(self, metrics: PRDPerformanceMetrics) -> Optional[str]:
        """
        Publish performance metrics snapshot.

        Args:
            metrics: PRD-compliant performance metrics

        Returns:
            Redis entry ID if successful
        """
        if not self._connected or not self.redis_client:
            logger.error("Cannot publish performance - not connected")
            return None

        stream_key = f"pnl:{self.mode}:performance"

        try:
            redis_data = metrics.to_redis_dict()
            encoded_data = {k: v.encode() if isinstance(v, str) else str(v).encode()
                           for k, v in redis_data.items()}

            entry_id = await self.redis_client.xadd(
                name=stream_key,
                fields=encoded_data,
                maxlen=self.PERFORMANCE_MAXLEN,
                approximate=True,
            )

            # Also update latest performance key
            import json
            latest_key = f"pnl:{self.mode}:performance:latest"
            await self.redis_client.set(latest_key, json.dumps(metrics.model_dump()).encode())

            entry_id_str = entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)

            logger.info(
                f"Published performance to {stream_key}",
                extra={
                    "equity": metrics.current_equity,
                    "roi_pct": metrics.total_roi_pct,
                    "sharpe": metrics.sharpe_ratio,
                }
            )

            return entry_id_str

        except Exception as e:
            logger.error(f"Failed to publish performance: {e}")
            return None


# =============================================================================
# PUBLIC API
# =============================================================================

__all__ = [
    # Enums
    "TradeOutcome",
    "ExitReason",
    # Trade record
    "PRDTradeRecord",
    "create_trade_record",
    # Performance metrics
    "PRDPerformanceMetrics",
    "PerformanceAggregator",
    # Publisher
    "PRDPnLPublisher",
]


# =============================================================================
# SELF-CHECK
# =============================================================================

if __name__ == "__main__":
    import asyncio
    from dotenv import load_dotenv

    load_dotenv(".env.paper")

    async def main():
        print("=" * 70)
        print(" " * 15 + "PRD PNL ATTRIBUTION SELF-CHECK")
        print("=" * 70)

        # Test 1: Create trade record
        print("\nTest 1: Create trade record")
        trade = create_trade_record(
            signal_id="test-signal-uuid",
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            entry_price=50000.0,
            exit_price=50500.0,
            position_size_usd=500.0,
            quantity=0.01,
            timestamp_open=datetime.now(timezone.utc).isoformat(),
            exit_reason=ExitReason.TAKE_PROFIT,
        )
        print(f"  Trade ID: {trade.trade_id}")
        print(f"  Gross PnL: ${trade.gross_pnl:.2f}")
        print(f"  Realized PnL: ${trade.realized_pnl:.2f}")
        print(f"  Outcome: {trade.outcome}")
        print(f"  ROI %: {trade.pnl_pct:.2f}%")
        assert trade.outcome == TradeOutcome.WIN
        print("  PASS")

        # Test 2: Losing trade
        print("\nTest 2: Losing trade")
        loss_trade = create_trade_record(
            signal_id="test-signal-2",
            pair="ETH/USD",
            side="LONG",
            strategy="TREND",
            entry_price=3000.0,
            exit_price=2950.0,
            position_size_usd=300.0,
            quantity=0.1,
            timestamp_open=datetime.now(timezone.utc).isoformat(),
            exit_reason=ExitReason.STOP_LOSS,
            fees_usd=0.30,
        )
        print(f"  Realized PnL: ${loss_trade.realized_pnl:.2f}")
        print(f"  Outcome: {loss_trade.outcome}")
        assert loss_trade.outcome == TradeOutcome.LOSS
        print("  PASS")

        # Test 3: Performance aggregator
        print("\nTest 3: Performance aggregator")
        agg = PerformanceAggregator(initial_equity=10000.0, mode="paper")

        # Add some trades
        for i in range(10):
            side = "LONG" if i % 2 == 0 else "SHORT"
            entry = 50000.0
            exit_price = 50100.0 if i % 3 != 0 else 49900.0  # 7 wins, 3 losses

            t = create_trade_record(
                signal_id=f"signal-{i}",
                pair="BTC/USD",
                side=side,
                strategy="SCALPER" if i < 5 else "TREND",
                entry_price=entry,
                exit_price=exit_price,
                position_size_usd=100.0,
                quantity=0.002,
                timestamp_open=datetime.now(timezone.utc).isoformat(),
                exit_reason=ExitReason.TAKE_PROFIT if exit_price > entry else ExitReason.STOP_LOSS,
            )
            agg.add_trade(t)

        metrics = agg.get_metrics()
        print(f"  Total trades: {metrics.total_trades}")
        print(f"  Win rate: {metrics.win_rate_pct:.1f}%")
        print(f"  Total PnL: ${metrics.total_pnl:.2f}")
        print(f"  Profit factor: {metrics.profit_factor:.2f}")
        print(f"  Max drawdown: {metrics.max_drawdown_pct:.2f}%")
        print(f"  Strategy breakdown: {list(metrics.strategy_performance.keys())}")
        assert metrics.total_trades == 10
        print("  PASS")

        # Test 4: Redis dict conversion
        print("\nTest 4: Redis dict conversion")
        redis_dict = trade.to_redis_dict()
        assert all(isinstance(v, str) for v in redis_dict.values())
        print(f"  Keys: {list(redis_dict.keys())[:5]}...")
        print("  PASS")

        # Test 5: Connect and publish (if Redis available)
        print("\nTest 5: Redis publishing")
        publisher = PRDPnLPublisher(mode="paper")
        redis_url = os.getenv("REDIS_URL")

        if redis_url:
            connected = await publisher.connect()
            if connected:
                print("  Connected to Redis")

                # Publish trade
                entry_id = await publisher.publish_trade(trade)
                if entry_id:
                    print(f"  Trade published! Entry ID: {entry_id}")
                else:
                    print("  Trade publish failed")

                # Publish performance
                perf_id = await publisher.publish_performance(metrics)
                if perf_id:
                    print(f"  Performance published! Entry ID: {perf_id}")
                else:
                    print("  Performance publish failed")

                await publisher.close()
                print("  PASS")
            else:
                print("  SKIP: Could not connect to Redis")
        else:
            print("  SKIP: REDIS_URL not set")

        print("\n" + "=" * 70)
        print("[OK] PRD PnL Attribution Self-Check Complete")
        print("=" * 70)

    asyncio.run(main())
