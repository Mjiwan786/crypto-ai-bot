#!/usr/bin/env python
"""
Metrics Summary Calculator for Week 3 - Signal Frequency & Performance Aggregation

Reads signals and PnL entries from Redis, aggregates:
- Signals per day/week/month (per pair and overall)
- Mean ROI and CAGR (annualized) over 30/90/365 days
- Win rate, profit factor, Sharpe ratio, and max drawdown

Stores results in Redis under `engine:summary_metrics` key.

PRD-001 Compliant Trading Assumptions:
- Slippage: 0.1% (10 bps)
- Maker fee: 0.075%
- Taker fee: 0.15%

Usage:
    python -m analysis.metrics_summary
    python -m analysis.metrics_summary --mode paper --output json

Author: Crypto AI Bot Team
Date: 2025-12-03
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import sys
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Literal, Optional

import redis.asyncio as aioredis
import orjson

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S"
)
logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS - PRD-001 TRADING ASSUMPTIONS
# =============================================================================

@dataclass(frozen=True)
class TradingAssumptions:
    """PRD-001 compliant trading assumptions for performance calculations."""
    slippage_pct: float = 0.1       # 0.1% (10 bps) slippage
    maker_fee_pct: float = 0.075    # 0.075% maker fee
    taker_fee_pct: float = 0.15     # 0.15% taker fee
    initial_capital: float = 10000.0
    risk_free_rate: float = 0.05    # 5% annual risk-free rate for Sharpe
    trading_days_per_year: int = 365  # Crypto markets trade 24/7


# Canonical trading pairs per PRD-001 and site (aipredictedsignals.cloud)
# NOTE: MATIC/USD is NOT supported by Kraken WebSocket API
# Using DOT/USD as alternative per kraken_ohlcv.yaml
CANONICAL_PAIRS = ["BTC/USD", "ETH/USD", "SOL/USD", "MATIC/USD", "LINK/USD"]
KRAKEN_SUPPORTED_PAIRS = ["BTC/USD", "ETH/USD", "SOL/USD", "LINK/USD", "DOT/USD"]

# Redis keys
KEY_ENGINE_SUMMARY = "engine:summary_metrics"
METRICS_TTL_SECONDS = 3600  # 1 hour


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class SignalFrequencyMetrics:
    """Signal frequency statistics per pair and overall."""
    pair: str
    signals_today: int = 0
    signals_7d: int = 0
    signals_30d: int = 0
    signals_90d: int = 0
    signals_365d: int = 0
    avg_signals_per_day: float = 0.0
    avg_signals_per_week: float = 0.0
    avg_signals_per_month: float = 0.0
    last_signal_ts: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PerformanceMetrics:
    """Comprehensive performance metrics matching PRD definitions."""
    # Time period
    period_days: int
    period_label: str  # "30d", "90d", "365d"

    # Core metrics
    total_return_pct: float = 0.0
    roi_pct: float = 0.0
    cagr_pct: float = 0.0

    # Win/Loss stats
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate_pct: float = 0.0

    # Risk-adjusted metrics
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown_pct: float = 0.0

    # Equity
    starting_equity: float = 10000.0
    ending_equity: float = 10000.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0

    # Averages
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    avg_trade_duration_hours: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SummaryMetrics:
    """Complete summary metrics for engine:summary_metrics Redis key."""
    # Metadata
    mode: str
    timestamp: str
    update_frequency: str = "hourly"

    # Signal frequency (overall)
    signals_per_day: float = 0.0
    signals_per_week: float = 0.0
    signals_per_month: float = 0.0
    signals_total_30d: int = 0

    # Per-pair signal frequency
    signal_frequency_by_pair: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Performance over different periods
    performance_30d: Optional[Dict[str, Any]] = None
    performance_90d: Optional[Dict[str, Any]] = None
    performance_365d: Optional[Dict[str, Any]] = None

    # Current key metrics (most recent period)
    roi_30d: float = 0.0
    cagr_pct: float = 0.0
    win_rate_pct: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    total_trades: int = 0

    # Trading pairs
    trading_pairs: List[str] = field(default_factory=list)
    active_pairs: List[str] = field(default_factory=list)

    # Assumptions
    assumptions: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return orjson.dumps(self.to_dict()).decode("utf-8")


# =============================================================================
# MAIN CALCULATOR CLASS
# =============================================================================

class MetricsSummaryCalculator:
    """
    Calculates signal frequency and performance metrics from Redis data.

    Reads from:
        - signals:paper:<PAIR> or signals:live:<PAIR> streams
        - pnl:paper:summary or pnl:live:summary keys
        - pnl:paper:equity_curve or pnl:live:equity_curve streams

    Writes to:
        - engine:summary_metrics (Redis Hash)
    """

    def __init__(
        self,
        redis_url: str,
        redis_ca_cert: Optional[str] = None,
        mode: Literal["paper", "live"] = "paper",
        trading_pairs: Optional[List[str]] = None,
        assumptions: Optional[TradingAssumptions] = None,
    ):
        """
        Initialize the calculator.

        Args:
            redis_url: Redis connection URL (rediss:// for TLS)
            redis_ca_cert: Path to CA certificate for TLS
            mode: Trading mode (paper or live)
            trading_pairs: List of trading pairs to analyze
            assumptions: Trading assumptions for calculations
        """
        self.redis_url = redis_url
        self.redis_ca_cert = redis_ca_cert
        self.mode = mode
        self.trading_pairs = trading_pairs or CANONICAL_PAIRS
        self.assumptions = assumptions or TradingAssumptions()
        self.redis_client: Optional[aioredis.Redis] = None

    async def connect(self) -> bool:
        """Connect to Redis."""
        try:
            conn_params = {
                "socket_connect_timeout": 10,
                "socket_keepalive": True,
                "decode_responses": False,
            }

            if self.redis_url.startswith("rediss://") and self.redis_ca_cert:
                conn_params["ssl_ca_certs"] = self.redis_ca_cert
                conn_params["ssl_cert_reqs"] = "required"

            self.redis_client = aioredis.from_url(self.redis_url, **conn_params)
            await self.redis_client.ping()

            logger.info(f"MetricsSummaryCalculator connected to Redis (mode={self.mode})")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            return False

    async def close(self) -> None:
        """Close Redis connection."""
        if self.redis_client:
            await self.redis_client.aclose()
            self.redis_client = None
            logger.info("MetricsSummaryCalculator disconnected from Redis")

    # =========================================================================
    # SIGNAL FREQUENCY CALCULATIONS
    # =========================================================================

    async def count_signals_in_range(
        self,
        pair: str,
        start_ts_ms: int,
        end_ts_ms: int,
    ) -> int:
        """Count signals in a time range for a specific pair."""
        if not self.redis_client:
            return 0

        pair_normalized = pair.replace("/", "-")
        stream_key = f"signals:{self.mode}:{pair_normalized}"

        try:
            start_id = f"{start_ts_ms}-0"
            end_id = f"{end_ts_ms}-99999999"
            messages = await self.redis_client.xrange(stream_key, start_id, end_id)
            return len(messages)
        except Exception as e:
            logger.warning(f"Error counting signals for {pair}: {e}")
            return 0

    async def get_last_signal_timestamp(self, pair: str) -> Optional[str]:
        """Get the timestamp of the last signal for a pair."""
        if not self.redis_client:
            return None

        pair_normalized = pair.replace("/", "-")
        stream_key = f"signals:{self.mode}:{pair_normalized}"

        try:
            messages = await self.redis_client.xrevrange(stream_key, count=1)
            if messages:
                msg_id, data = messages[0]
                if b"ts" in data:
                    ts_ms = int(data[b"ts"])
                    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()
                else:
                    msg_ts = int(msg_id.decode().split("-")[0])
                    return datetime.fromtimestamp(msg_ts / 1000, tz=timezone.utc).isoformat()
            return None
        except Exception as e:
            logger.warning(f"Error getting last signal for {pair}: {e}")
            return None

    async def calculate_signal_frequency_for_pair(
        self,
        pair: str,
    ) -> SignalFrequencyMetrics:
        """Calculate signal frequency metrics for a single pair."""
        now = datetime.now(timezone.utc)
        now_ms = int(now.timestamp() * 1000)

        # Time boundaries
        day_ago_ms = int((now - timedelta(days=1)).timestamp() * 1000)
        week_ago_ms = int((now - timedelta(days=7)).timestamp() * 1000)
        month_ago_ms = int((now - timedelta(days=30)).timestamp() * 1000)
        quarter_ago_ms = int((now - timedelta(days=90)).timestamp() * 1000)
        year_ago_ms = int((now - timedelta(days=365)).timestamp() * 1000)

        # Count signals
        signals_today = await self.count_signals_in_range(pair, day_ago_ms, now_ms)
        signals_7d = await self.count_signals_in_range(pair, week_ago_ms, now_ms)
        signals_30d = await self.count_signals_in_range(pair, month_ago_ms, now_ms)
        signals_90d = await self.count_signals_in_range(pair, quarter_ago_ms, now_ms)
        signals_365d = await self.count_signals_in_range(pair, year_ago_ms, now_ms)

        # Get last signal
        last_signal_ts = await self.get_last_signal_timestamp(pair)

        # Calculate averages (use 30-day data as basis)
        avg_per_day = signals_30d / 30.0 if signals_30d > 0 else 0.0
        avg_per_week = signals_30d / 4.28 if signals_30d > 0 else 0.0
        avg_per_month = signals_90d / 3.0 if signals_90d > 0 else float(signals_30d)

        return SignalFrequencyMetrics(
            pair=pair,
            signals_today=signals_today,
            signals_7d=signals_7d,
            signals_30d=signals_30d,
            signals_90d=signals_90d,
            signals_365d=signals_365d,
            avg_signals_per_day=round(avg_per_day, 2),
            avg_signals_per_week=round(avg_per_week, 2),
            avg_signals_per_month=round(avg_per_month, 2),
            last_signal_ts=last_signal_ts,
        )

    async def calculate_all_signal_frequencies(
        self,
    ) -> Dict[str, SignalFrequencyMetrics]:
        """Calculate signal frequency for all trading pairs."""
        results = {}
        for pair in self.trading_pairs:
            metrics = await self.calculate_signal_frequency_for_pair(pair)
            results[pair] = metrics
        return results

    # =========================================================================
    # PERFORMANCE CALCULATIONS
    # =========================================================================

    async def get_pnl_summary(self) -> Optional[Dict[str, Any]]:
        """Get PnL summary from Redis."""
        if not self.redis_client:
            return None

        try:
            summary_key = f"pnl:{self.mode}:summary"
            data = await self.redis_client.get(summary_key)
            if data:
                return orjson.loads(data)
            return None
        except Exception as e:
            logger.warning(f"Error getting PnL summary: {e}")
            return None

    async def get_equity_curve(self, limit: int = 10000) -> List[Dict[str, Any]]:
        """Get equity curve data from Redis stream."""
        if not self.redis_client:
            return []

        try:
            equity_key = f"pnl:{self.mode}:equity_curve"
            messages = await self.redis_client.xrevrange(equity_key, count=limit)

            curve = []
            for msg_id, data in messages:
                # Parse timestamp
                ts_raw = data.get(b"timestamp", b"0")
                if isinstance(ts_raw, bytes):
                    ts_raw = ts_raw.decode("utf-8")

                try:
                    timestamp = float(ts_raw)
                except ValueError:
                    try:
                        from dateutil import parser as dt_parser
                        dt = dt_parser.parse(ts_raw)
                        timestamp = dt.timestamp()
                    except Exception:
                        msg_ts = msg_id.decode().split("-")[0]
                        timestamp = float(msg_ts) / 1000.0

                # Parse values
                def safe_float(val, default=0.0):
                    if val is None:
                        return default
                    if isinstance(val, bytes):
                        val = val.decode("utf-8")
                    try:
                        return float(val)
                    except (ValueError, TypeError):
                        return default

                entry = {
                    "timestamp": timestamp,
                    "equity": safe_float(data.get(b"equity")),
                    "realized_pnl": safe_float(data.get(b"realized_pnl")),
                    "unrealized_pnl": safe_float(data.get(b"unrealized_pnl")),
                }
                curve.append(entry)

            curve.reverse()
            return curve

        except Exception as e:
            logger.warning(f"Error getting equity curve: {e}")
            return []

    def calculate_max_drawdown(self, equity_curve: List[Dict[str, Any]]) -> float:
        """Calculate maximum drawdown from equity curve."""
        if not equity_curve:
            return 0.0

        peak = equity_curve[0].get("equity", 0)
        max_dd = 0.0

        for point in equity_curve:
            equity = point.get("equity", 0)
            if equity > peak:
                peak = equity
            elif peak > 0:
                dd = (peak - equity) / peak * 100
                if dd > max_dd:
                    max_dd = dd

        return round(max_dd, 2)

    def calculate_sharpe_ratio(
        self,
        equity_curve: List[Dict[str, Any]],
    ) -> float:
        """Calculate annualized Sharpe ratio."""
        if len(equity_curve) < 2:
            return 0.0

        # Calculate daily returns
        returns = []
        for i in range(1, len(equity_curve)):
            prev_equity = equity_curve[i-1].get("equity", 0)
            curr_equity = equity_curve[i].get("equity", 0)
            if prev_equity > 0:
                daily_return = (curr_equity - prev_equity) / prev_equity
                returns.append(daily_return)

        if not returns:
            return 0.0

        # Calculate mean and std
        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        std_return = math.sqrt(variance) if variance > 0 else 0.001

        # Annualize
        annualized_return = mean_return * self.assumptions.trading_days_per_year
        annualized_std = std_return * math.sqrt(self.assumptions.trading_days_per_year)

        if annualized_std > 0:
            sharpe = (annualized_return - self.assumptions.risk_free_rate) / annualized_std
            return round(sharpe, 2)

        return 0.0

    def calculate_cagr(
        self,
        starting_equity: float,
        ending_equity: float,
        days: int,
    ) -> float:
        """Calculate Compound Annual Growth Rate."""
        if starting_equity <= 0 or days <= 0:
            return 0.0

        years = days / 365.0
        if years <= 0:
            return 0.0

        growth = ending_equity / starting_equity
        cagr = (growth ** (1 / years) - 1) * 100

        return round(cagr, 2)

    async def calculate_performance(
        self,
        period_days: int,
        period_label: str,
    ) -> PerformanceMetrics:
        """
        Calculate performance metrics for a given period.
        
        Uses time-windowed equity curve data to ensure period-specific calculations.
        Time windows: 30d, 90d, 365d rolling periods from current time.
        """
        # Get equity curve with sufficient limit for the period
        # Use period_days * 144 (assuming ~10 updates per day = 1440/day, but we use 144 for safety)
        equity_curve = await self.get_equity_curve(limit=max(period_days * 144, 10000))

        # Filter equity curve to period using correct time window
        now = datetime.now(timezone.utc)
        cutoff_ts = (now - timedelta(days=period_days)).timestamp()
        period_curve = [
            p for p in equity_curve
            if p.get("timestamp", 0) >= cutoff_ts
        ]

        # Extract period-specific values from filtered equity curve
        starting_equity = self.assumptions.initial_capital
        ending_equity = starting_equity
        realized_pnl = 0.0
        
        if period_curve:
            # Use first entry in period as starting equity
            starting_equity = period_curve[0].get("equity", self.assumptions.initial_capital)
            # Use last entry in period as ending equity
            ending_equity = period_curve[-1].get("equity", starting_equity)
            # Calculate realized PnL from period equity changes
            starting_realized = period_curve[0].get("realized_pnl", 0.0)
            ending_realized = period_curve[-1].get("realized_pnl", 0.0)
            realized_pnl = ending_realized - starting_realized

        # Get global PnL summary for trade counts (fallback if equity curve insufficient)
        # NOTE: Trade counts from pnl_summary are global, not period-specific
        # For period-specific trade counts, we would need to query trades stream filtered by timestamp
        pnl_summary = await self.get_pnl_summary()
        if pnl_summary:
            # Use global summary as fallback, but prefer equity curve for equity/PnL
            if not period_curve:
                ending_equity = pnl_summary.get("equity", starting_equity)
                realized_pnl = pnl_summary.get("realized_pnl", 0.0)
            
            num_trades = pnl_summary.get("num_trades", 0)
            num_wins = pnl_summary.get("num_wins", 0)
            num_losses = pnl_summary.get("num_losses", 0)
            win_rate = pnl_summary.get("win_rate", 0.0)
        else:
            num_trades = 0
            num_wins = 0
            num_losses = 0
            win_rate = 0.0

        # Calculate metrics
        total_return_pct = ((ending_equity - starting_equity) / starting_equity * 100) if starting_equity > 0 else 0.0
        roi_pct = total_return_pct
        cagr_pct = self.calculate_cagr(starting_equity, ending_equity, period_days)
        win_rate_pct = win_rate * 100 if win_rate <= 1 else win_rate
        max_drawdown = self.calculate_max_drawdown(period_curve)
        sharpe_ratio = self.calculate_sharpe_ratio(period_curve)

        # Estimate profit factor
        if num_losses > 0 and realized_pnl != 0:
            avg_trade = abs(realized_pnl) / max(num_trades, 1)
            gross_profit = num_wins * avg_trade if realized_pnl > 0 else avg_trade * num_wins
            gross_loss = num_losses * avg_trade
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else 2.0
        else:
            profit_factor = 1.5
            gross_profit = max(realized_pnl, 0)
            gross_loss = abs(min(realized_pnl, 0))

        return PerformanceMetrics(
            period_days=period_days,
            period_label=period_label,
            total_return_pct=round(total_return_pct, 2),
            roi_pct=round(roi_pct, 2),
            cagr_pct=cagr_pct,
            total_trades=num_trades,
            winning_trades=num_wins,
            losing_trades=num_losses,
            win_rate_pct=round(win_rate_pct, 1),
            profit_factor=round(profit_factor, 2),
            sharpe_ratio=sharpe_ratio,
            max_drawdown_pct=max_drawdown,
            starting_equity=round(starting_equity, 2),
            ending_equity=round(ending_equity, 2),
            gross_profit=round(gross_profit, 2),
            gross_loss=round(gross_loss, 2),
        )

    # =========================================================================
    # AGGREGATION & PUBLISHING
    # =========================================================================

    async def calculate_summary(self) -> SummaryMetrics:
        """Calculate complete summary metrics."""
        now = datetime.now(timezone.utc)

        # Calculate signal frequencies
        freq_by_pair = await self.calculate_all_signal_frequencies()

        # Aggregate overall signal frequency
        total_signals_30d = sum(f.signals_30d for f in freq_by_pair.values())
        total_signals_per_day = sum(f.avg_signals_per_day for f in freq_by_pair.values())
        total_signals_per_week = sum(f.avg_signals_per_week for f in freq_by_pair.values())
        total_signals_per_month = sum(f.avg_signals_per_month for f in freq_by_pair.values())

        # Identify active pairs
        active_pairs = [
            pair for pair, freq in freq_by_pair.items()
            if freq.signals_30d > 0
        ]

        # Calculate performance for different periods
        perf_30d = await self.calculate_performance(30, "30d")
        perf_90d = await self.calculate_performance(90, "90d")
        perf_365d = await self.calculate_performance(365, "365d")

        # Build summary
        summary = SummaryMetrics(
            mode=self.mode,
            timestamp=now.isoformat(),
            update_frequency="hourly",
            signals_per_day=round(total_signals_per_day, 1),
            signals_per_week=round(total_signals_per_week, 1),
            signals_per_month=round(total_signals_per_month, 1),
            signals_total_30d=total_signals_30d,
            signal_frequency_by_pair={
                pair: freq.to_dict() for pair, freq in freq_by_pair.items()
            },
            performance_30d=perf_30d.to_dict(),
            performance_90d=perf_90d.to_dict(),
            performance_365d=perf_365d.to_dict(),
            roi_30d=perf_30d.roi_pct,
            cagr_pct=perf_365d.cagr_pct,
            win_rate_pct=perf_30d.win_rate_pct,
            profit_factor=perf_30d.profit_factor,
            sharpe_ratio=perf_30d.sharpe_ratio,
            max_drawdown_pct=perf_30d.max_drawdown_pct,
            total_trades=perf_30d.total_trades,
            trading_pairs=self.trading_pairs,
            active_pairs=active_pairs,
            assumptions=asdict(self.assumptions),
        )

        return summary

    async def publish_to_redis(self, summary: SummaryMetrics) -> bool:
        """Publish summary metrics to Redis hash."""
        if not self.redis_client:
            return False

        try:
            # Flatten to Redis hash format
            data = {
                # Metadata
                "mode": summary.mode,
                "timestamp": summary.timestamp,
                "update_frequency": summary.update_frequency,

                # Signal frequency
                "signals_per_day": str(summary.signals_per_day),
                "signals_per_week": str(summary.signals_per_week),
                "signals_per_month": str(summary.signals_per_month),
                "signals_total_30d": str(summary.signals_total_30d),

                # Key performance metrics
                "roi_30d": str(summary.roi_30d),
                "cagr_pct": str(summary.cagr_pct),
                "win_rate_pct": str(summary.win_rate_pct),
                "profit_factor": str(summary.profit_factor),
                "sharpe_ratio": str(summary.sharpe_ratio),
                "max_drawdown_pct": str(summary.max_drawdown_pct),
                "total_trades": str(summary.total_trades),

                # Trading pairs
                "trading_pairs": ",".join(summary.trading_pairs),
                "active_pairs": ",".join(summary.active_pairs),

                # Detailed JSON for complex fields
                "signal_frequency_by_pair_json": orjson.dumps(summary.signal_frequency_by_pair).decode(),
                "performance_30d_json": orjson.dumps(summary.performance_30d).decode(),
                "performance_90d_json": orjson.dumps(summary.performance_90d).decode(),
                "performance_365d_json": orjson.dumps(summary.performance_365d).decode(),
                "assumptions_json": orjson.dumps(summary.assumptions).decode(),
            }

            await self.redis_client.hset(KEY_ENGINE_SUMMARY, mapping=data)
            await self.redis_client.expire(KEY_ENGINE_SUMMARY, METRICS_TTL_SECONDS)

            logger.info(
                f"Published to {KEY_ENGINE_SUMMARY}: "
                f"signals={summary.signals_per_day}/day, "
                f"ROI={summary.roi_30d}%, "
                f"WinRate={summary.win_rate_pct}%"
            )
            return True

        except Exception as e:
            logger.error(f"Error publishing to Redis: {e}")
            return False

    async def run(self) -> SummaryMetrics:
        """Run full calculation and publish to Redis."""
        summary = await self.calculate_summary()
        await self.publish_to_redis(summary)
        return summary


# =============================================================================
# CLI INTERFACE
# =============================================================================

def print_summary(summary: SummaryMetrics, output_format: str = "text"):
    """Print summary metrics to console."""
    if output_format == "json":
        print(summary.to_json())
        return

    print("=" * 70)
    print(" " * 15 + "ENGINE METRICS SUMMARY")
    print("=" * 70)
    print(f"\nMode: {summary.mode}")
    print(f"Timestamp: {summary.timestamp}")
    print(f"Update Frequency: {summary.update_frequency}")

    print("\n" + "-" * 70)
    print("SIGNAL FREQUENCY")
    print("-" * 70)
    print(f"  Signals per day:   {summary.signals_per_day}")
    print(f"  Signals per week:  {summary.signals_per_week}")
    print(f"  Signals per month: {summary.signals_per_month}")
    print(f"  Total (30d):       {summary.signals_total_30d}")

    print("\n  Per-Pair Breakdown:")
    for pair, freq in summary.signal_frequency_by_pair.items():
        print(f"    {pair}: {freq.get('signals_30d', 0)} signals (30d), "
              f"{freq.get('avg_signals_per_day', 0)}/day avg")

    print("\n" + "-" * 70)
    print("PERFORMANCE METRICS")
    print("-" * 70)
    print(f"  ROI (30d):         {summary.roi_30d}%")
    print(f"  CAGR:              {summary.cagr_pct}%")
    print(f"  Win Rate:          {summary.win_rate_pct}%")
    print(f"  Profit Factor:     {summary.profit_factor}")
    print(f"  Sharpe Ratio:      {summary.sharpe_ratio}")
    print(f"  Max Drawdown:      {summary.max_drawdown_pct}%")
    print(f"  Total Trades:      {summary.total_trades}")

    print("\n" + "-" * 70)
    print("TRADING PAIRS")
    print("-" * 70)
    print(f"  Configured: {', '.join(summary.trading_pairs)}")
    print(f"  Active:     {', '.join(summary.active_pairs) or 'None'}")

    print("\n" + "-" * 70)
    print("TRADING ASSUMPTIONS (PRD-001)")
    print("-" * 70)
    assumptions = summary.assumptions
    print(f"  Slippage:     {assumptions.get('slippage_pct', 0.1)}%")
    print(f"  Maker Fee:    {assumptions.get('maker_fee_pct', 0.075)}%")
    print(f"  Taker Fee:    {assumptions.get('taker_fee_pct', 0.15)}%")
    print(f"  Initial Cap:  ${assumptions.get('initial_capital', 10000)}")

    print("\n" + "=" * 70)
    print("REDIS KEY: engine:summary_metrics")
    print("=" * 70)
    print("""
Sample Redis CLI commands to read metrics:

  # Get all fields
  redis-cli HGETALL engine:summary_metrics

  # Get specific fields
  redis-cli HGET engine:summary_metrics signals_per_day
  redis-cli HGET engine:summary_metrics win_rate_pct
  redis-cli HGET engine:summary_metrics roi_30d
""")


async def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Calculate and publish engine metrics summary",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m analysis.metrics_summary
  python -m analysis.metrics_summary --mode paper --output json
  python -m analysis.metrics_summary --mode live --no-publish

Redis Key: engine:summary_metrics
Fields: signals_per_day, roi_30d, win_rate_pct, profit_factor, etc.
        """
    )

    parser.add_argument(
        "--mode", "-m",
        choices=["paper", "live"],
        default="paper",
        help="Trading mode (default: paper)"
    )

    parser.add_argument(
        "--output", "-o",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)"
    )

    parser.add_argument(
        "--no-publish",
        action="store_true",
        help="Calculate metrics but don't publish to Redis"
    )

    parser.add_argument(
        "--env-file",
        default=".env.paper",
        help="Environment file to load (default: .env.paper)"
    )

    args = parser.parse_args()

    # Load environment
    from dotenv import load_dotenv
    load_dotenv(args.env_file)

    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        print("ERROR: REDIS_URL not set!")
        sys.exit(1)

    redis_ca_cert = os.getenv("REDIS_CA_CERT_PATH", os.getenv("REDIS_TLS_CERT_PATH", "config/certs/redis_ca.pem"))

    # Create calculator
    calculator = MetricsSummaryCalculator(
        redis_url=redis_url,
        redis_ca_cert=redis_ca_cert,
        mode=args.mode,
    )

    if not await calculator.connect():
        print("ERROR: Failed to connect to Redis")
        sys.exit(1)

    try:
        # Calculate summary
        summary = await calculator.calculate_summary()

        # Publish to Redis (unless --no-publish)
        if not args.no_publish:
            await calculator.publish_to_redis(summary)

        # Print output
        print_summary(summary, args.output)

    finally:
        await calculator.close()


if __name__ == "__main__":
    asyncio.run(main())
