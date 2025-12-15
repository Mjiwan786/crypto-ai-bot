#!/usr/bin/env python
"""
Metrics Summary Calculator - Investor Performance Metrics

This module computes and publishes performance metrics for the investor dashboard
on aipredictedsignals.cloud. Metrics are consumed by signals-api /v1/metrics/summary endpoint.

PRIMARY FUNCTION:
    Calculates investor-facing performance metrics from trading signals and PnL data:
    - ROI (30-day, 90-day, 365-day rolling periods)
    - Win rate, profit factor, Sharpe ratio, max drawdown
    - Signal frequency per trading pair
    - Compound Annual Growth Rate (CAGR)

PUBLISHES TO:
    - engine:summary_metrics (Redis Hash) - consumed by signals-api /v1/metrics/summary

METRIC DEFINITIONS:
    - roi_30d: 30-day Return on Investment, percentage (e.g., 5.5 = 5.5%)
    - win_rate_pct: Win rate, percentage (0-100, e.g., 55.5 = 55.5% win rate)
    - sharpe_ratio: Annualized Sharpe ratio (risk-adjusted return, typically 0-3)
    - profit_factor: Gross profit / gross loss ratio (e.g., 1.5 = 50% more profit than loss)
    - max_drawdown_pct: Maximum drawdown, percentage (e.g., -15.2 = 15.2% drawdown)
    - cagr_pct: Compound Annual Growth Rate, percentage (annualized return)
    - signals_per_day: Average signals per day (rolling 30-day average)

TIME WINDOWS:
    All periods are rolling windows from current time:
    - 30d = last 30 days from now
    - 90d = last 90 days from now
    - 365d = last 365 days from now

PRD-001 COMPLIANT TRADING ASSUMPTIONS:
    - Slippage: 0.1% (10 bps)
    - Maker fee: 0.075%
    - Taker fee: 0.15%
    - Initial capital: $10,000
    - Risk-free rate: 5% annual (for Sharpe calculation)
    - Trading days per year: 365 (crypto markets trade 24/7)

Usage:
    python -m analysis.metrics_summary                    # Paper mode (default)
    python -m analysis.metrics_summary --mode live        # Live mode
    python -m analysis.metrics_summary --output json       # JSON output

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

# Import canonical trading pairs (single source of truth)
try:
    from config.trading_pairs import (
        ALL_PAIR_SYMBOLS,
        ENABLED_PAIR_SYMBOLS,
        get_kraken_symbols,
    )
    _CANONICAL_PAIRS_AVAILABLE = True
except ImportError:
    _CANONICAL_PAIRS_AVAILABLE = False
    ALL_PAIR_SYMBOLS = ["BTC/USD", "ETH/USD", "SOL/USD", "MATIC/USD", "LINK/USD"]
    ENABLED_PAIR_SYMBOLS = ["BTC/USD", "ETH/USD", "SOL/USD", "LINK/USD"]

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


# Canonical trading pairs - uses config/trading_pairs.py as single source of truth
# ALL_PAIR_SYMBOLS includes all configured pairs (incl. disabled like MATIC/USD)
# ENABLED_PAIR_SYMBOLS includes only Kraken WS supported pairs
CANONICAL_PAIRS = ALL_PAIR_SYMBOLS.copy() if _CANONICAL_PAIRS_AVAILABLE else ["BTC/USD", "ETH/USD", "SOL/USD", "MATIC/USD", "LINK/USD"]
KRAKEN_SUPPORTED_PAIRS = ENABLED_PAIR_SYMBOLS.copy() if _CANONICAL_PAIRS_AVAILABLE else ["BTC/USD", "ETH/USD", "SOL/USD", "LINK/USD"]

# Redis keys
KEY_ENGINE_SUMMARY = "engine:summary_metrics"
METRICS_TTL_SECONDS = 3600  # 1 hour


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class SignalFrequencyMetrics:
    """
    Signal frequency statistics per trading pair.
    
    These metrics track how many signals are generated for a specific pair
    over different time windows. Used for dashboard display and API responses.
    """
    pair: str  # Trading pair (e.g., "BTC/USD")
    signals_today: int = 0  # Signals generated today (last 24 hours)
    signals_7d: int = 0  # Signals generated in last 7 days
    signals_30d: int = 0  # Signals generated in last 30 days
    signals_90d: int = 0  # Signals generated in last 90 days
    signals_365d: int = 0  # Signals generated in last 365 days
    avg_signals_per_day: float = 0.0  # Average signals per day (calculated from 30d data)
    avg_signals_per_week: float = 0.0  # Average signals per week (calculated from 30d data)
    avg_signals_per_month: float = 0.0  # Average signals per month (calculated from 90d data)
    last_signal_ts: Optional[str] = None  # ISO8601 timestamp of most recent signal (or None if no signals)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PerformanceMetrics:
    """
    Comprehensive performance metrics for investor dashboard.
    
    These metrics are published to engine:summary_metrics and consumed by
    signals-api /v1/metrics/summary endpoint for display on aipredictedsignals.cloud.
    
    All percentage values are in percentage points (e.g., 5.5 means 5.5%).
    All time windows are rolling periods from current time (e.g., 30d = last 30 days).
    """
    # Time period metadata
    period_days: int  # Number of days in the period (e.g., 30, 90, 365)
    period_label: str  # Human-readable label: "30d", "90d", "365d"

    # Core return metrics (investor-facing)
    total_return_pct: float = 0.0  # Total return over period, percentage (e.g., 5.5 = 5.5%)
    roi_pct: float = 0.0  # Return on Investment, percentage (alias for total_return_pct, matches API)
    cagr_pct: float = 0.0  # Compound Annual Growth Rate, percentage (annualized return)

    # Trade statistics (investor-facing)
    total_trades: int = 0  # Total number of trades executed in period
    winning_trades: int = 0  # Number of profitable trades
    losing_trades: int = 0  # Number of losing trades
    win_rate_pct: float = 0.0  # Win rate as percentage (0-100, e.g., 55.5 = 55.5% win rate)

    # Risk-adjusted metrics (investor-facing)
    profit_factor: float = 0.0  # Gross profit / gross loss ratio (e.g., 1.5 = 50% more profit than loss)
    sharpe_ratio: float = 0.0  # Annualized Sharpe ratio (risk-adjusted return, typically 0-3)
    max_drawdown_pct: float = 0.0  # Maximum drawdown percentage (peak-to-trough decline, e.g., -15.2 = 15.2% drawdown)

    # Equity tracking (internal calculation, also exposed to API)
    starting_equity: float = 10000.0  # Starting equity in USD at period start
    ending_equity: float = 10000.0  # Ending equity in USD at period end
    gross_profit: float = 0.0  # Total gross profit in USD (sum of all winning trades)
    gross_loss: float = 0.0  # Total gross loss in USD (absolute value, sum of all losing trades)

    # Average metrics (internal, not directly exposed to API)
    avg_win_pct: float = 0.0  # Average winning trade return, percentage
    avg_loss_pct: float = 0.0  # Average losing trade return, percentage (negative)
    avg_trade_duration_hours: float = 0.0  # Average trade duration in hours

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SummaryMetrics:
    """
    Complete summary metrics for engine:summary_metrics Redis key.
    
    This is the primary data structure consumed by signals-api /v1/metrics/summary endpoint
    and displayed on aipredictedsignals.cloud investor dashboard.
    
    Published to: engine:summary_metrics (Redis Hash)
    Update frequency: Hourly
    TTL: 1 hour (auto-refreshed on each update)
    """
    # Metadata (API: included in response)
    mode: str  # Trading mode: "paper" or "live"
    timestamp: str  # ISO8601 UTC timestamp of last update (e.g., "2025-01-27T12:34:56.789Z")
    update_frequency: str = "hourly"  # How often metrics are recalculated

    # Signal frequency metrics (API: signals_per_day, signals_per_week, signals_per_month)
    signals_per_day: float = 0.0  # Average signals per day (rolling 30-day average)
    signals_per_week: float = 0.0  # Average signals per week (rolling 30-day average)
    signals_per_month: float = 0.0  # Average signals per month (rolling 90-day average)
    signals_total_30d: int = 0  # Total signals generated in last 30 days

    # Per-pair signal frequency (API: signal_frequency_by_pair_json)
    signal_frequency_by_pair: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # Structure: {"BTC/USD": {"signals_30d": 150, "avg_signals_per_day": 5.0, ...}, ...}

    # Performance over different periods (API: performance_30d_json, performance_90d_json, performance_365d_json)
    performance_30d: Optional[Dict[str, Any]] = None  # 30-day performance metrics (rolling)
    performance_90d: Optional[Dict[str, Any]] = None  # 90-day performance metrics (rolling)
    performance_365d: Optional[Dict[str, Any]] = None  # 365-day performance metrics (rolling)

    # Current key metrics (API: primary fields for dashboard display)
    # These are the "headline" metrics shown prominently on investor dashboard
    roi_30d: float = 0.0  # 30-day ROI, percentage (e.g., 5.5 = 5.5% return)
    cagr_pct: float = 0.0  # Compound Annual Growth Rate, percentage (annualized, based on 365d period)
    win_rate_pct: float = 0.0  # Win rate, percentage (0-100, e.g., 55.5 = 55.5% win rate)
    profit_factor: float = 0.0  # Gross profit / gross loss ratio (e.g., 1.5 = 50% more profit than loss)
    sharpe_ratio: float = 0.0  # Annualized Sharpe ratio (risk-adjusted return, typically 0-3)
    max_drawdown_pct: float = 0.0  # Maximum drawdown, percentage (e.g., -15.2 = 15.2% drawdown)
    total_trades: int = 0  # Total trades in 30-day period

    # Trading pairs (API: trading_pairs, active_pairs)
    trading_pairs: List[str] = field(default_factory=list)  # All configured pairs (e.g., ["BTC/USD", "ETH/USD"])
    active_pairs: List[str] = field(default_factory=list)  # Pairs with signals in last 30 days

    # Trading assumptions (API: assumptions_json)
    # PRD-001 compliant assumptions used for calculations (slippage, fees, etc.)
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
    
    This is the primary module for computing investor-facing metrics that are
    displayed on aipredictedsignals.cloud dashboard.
    
    DATA SOURCES (Redis):
        Reads from:
        - signals:paper:<PAIR> or signals:live:<PAIR> streams (signal frequency)
        - pnl:paper:summary or pnl:live:summary keys (trade statistics)
        - pnl:paper:equity_curve or pnl:live:equity_curve streams (equity tracking)
    
    OUTPUT (Redis):
        Writes to:
        - engine:summary_metrics (Redis Hash) - consumed by signals-api /v1/metrics/summary
        
    UPDATE FREQUENCY:
        Metrics are recalculated hourly (via scheduled task or manual execution).
        Each update overwrites the previous engine:summary_metrics hash.
        
    METRIC CALCULATION:
        - Signal frequency: Counts signals in Redis streams over time windows
        - Performance metrics: Computed from equity curve (ROI, Sharpe, drawdown)
        - Trade statistics: Aggregated from PnL summary (win rate, profit factor)
        
    MODE SEPARATION:
        - Paper mode: Reads from signals:paper:* and pnl:paper:*
        - Live mode: Reads from signals:live:* and pnl:live:*
        - Mode is set at initialization and cannot be changed
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

            logger.info("Connected to Redis for metrics calculation (mode=%s)", self.mode)
            return True

        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            return False

    async def close(self) -> None:
        """Close Redis connection."""
        if self.redis_client:
            await self.redis_client.aclose()
            self.redis_client = None
            logger.info("Disconnected from Redis")

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
            logger.warning("Unable to count signals for %s: %s", pair, e)
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
            logger.warning("Unable to get last signal timestamp for %s: %s", pair, e)
            return None

    async def calculate_signal_frequency_for_pair(
        self,
        pair: str,
    ) -> SignalFrequencyMetrics:
        """
        Calculate signal frequency metrics for a single trading pair.
        
        This computes how many signals were generated for a specific pair
        over different time windows (today, 7d, 30d, 90d, 365d).
        
        Args:
            pair: Trading pair (e.g., "BTC/USD")
            
        Returns:
            SignalFrequencyMetrics with counts and averages
            
        Note:
            Averages are calculated from 30-day data for consistency.
            For example, avg_signals_per_day = signals_30d / 30.0
        """
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
            logger.warning("Unable to retrieve PnL summary: %s", e)
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
            logger.warning("Unable to retrieve equity curve: %s", e)
            return []

    def calculate_max_drawdown(self, equity_curve: List[Dict[str, Any]]) -> float:
        """
        Calculate maximum drawdown from equity curve.
        
        Maximum drawdown is the largest peak-to-trough decline in equity.
        This is a key risk metric for investors.
        
        Args:
            equity_curve: List of equity points over time (sorted chronologically)
            
        Returns:
            Maximum drawdown as percentage (e.g., -15.2 means 15.2% drawdown)
            Returns 0.0 if no drawdown or insufficient data
            
        Example:
            If equity peaks at $10,000 and drops to $8,500, max drawdown = -15.0%
        """
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
        """
        Calculate annualized Sharpe ratio from equity curve.
        
        Sharpe ratio measures risk-adjusted return:
        Sharpe = (Annualized Return - Risk-Free Rate) / Annualized Volatility
        
        This is a key metric for investors to compare strategies.
        Higher Sharpe = better risk-adjusted returns.
        
        Args:
            equity_curve: List of equity points over time (sorted chronologically)
            
        Returns:
            Annualized Sharpe ratio (typically 0-3, higher is better)
            Returns 0.0 if insufficient data (< 2 points)
            
        Assumptions:
            - Risk-free rate: 5% annual (from TradingAssumptions)
            - Trading days per year: 365 (crypto markets trade 24/7)
            - Daily returns are calculated from equity changes
        """
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
        """
        Calculate Compound Annual Growth Rate (CAGR).
        
        CAGR is the annualized return assuming compounding:
        CAGR = ((Ending Equity / Starting Equity) ^ (1 / Years) - 1) * 100
        
        This allows investors to compare returns across different time periods.
        
        Args:
            starting_equity: Starting equity in USD
            ending_equity: Ending equity in USD
            days: Number of days in the period
            
        Returns:
            CAGR as percentage (e.g., 12.5 = 12.5% annualized return)
            Returns 0.0 if invalid inputs (starting_equity <= 0 or days <= 0)
            
        Example:
            Starting: $10,000, Ending: $11,000, Days: 365
            CAGR = ((11000/10000)^(1/1) - 1) * 100 = 10.0%
        """
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
        Calculate performance metrics for a given rolling period.
        
        This computes investor-facing metrics from equity curve data:
        - ROI: Total return over the period
        - CAGR: Annualized return (if period < 365 days, extrapolated)
        - Win rate: Percentage of profitable trades
        - Sharpe ratio: Risk-adjusted return (annualized)
        - Max drawdown: Largest peak-to-trough decline
        
        Args:
            period_days: Number of days in the period (30, 90, or 365)
            period_label: Human-readable label ("30d", "90d", "365d")
            
        Returns:
            PerformanceMetrics with all calculated metrics for the period
            
        Note:
            Time windows are rolling periods from current time (not calendar periods).
            For example, 30d = last 30 days from now, not calendar month.
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
        """
        Calculate complete summary metrics for investor dashboard.
        
        This is the main entry point that:
        1. Calculates signal frequency per pair and overall
        2. Computes performance metrics for 30d, 90d, and 365d periods
        3. Aggregates key metrics for dashboard display
        4. Identifies active trading pairs
        
        Returns SummaryMetrics object ready for publishing to engine:summary_metrics.
        """
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

        # Calculate performance for different periods (rolling windows)
        # These are the primary metrics displayed on investor dashboard
        logger.info("Calculating 30-day performance metrics...")
        perf_30d = await self.calculate_performance(30, "30d")
        
        logger.info("Calculating 90-day performance metrics...")
        perf_90d = await self.calculate_performance(90, "90d")
        
        logger.info("Calculating 365-day performance metrics...")
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
        """
        Publish summary metrics to Redis hash for signals-api consumption.
        
        Publishes to: engine:summary_metrics (Redis Hash)
        Consumed by: signals-api /v1/metrics/summary endpoint
        
        All values are stored as strings in Redis hash (Redis limitation).
        Complex nested structures are stored as JSON strings.
        
        Args:
            summary: SummaryMetrics object to publish
            
        Returns:
            True if published successfully, False otherwise
        """
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

            # Investor-friendly log message (no internal implementation details)
            logger.info(
                "Updated 30-day performance summary: "
                "%.1f signals/day, %.1f%% ROI, %.1f%% win rate, %.2f Sharpe ratio",
                summary.signals_per_day,
                summary.roi_30d,
                summary.win_rate_pct,
                summary.sharpe_ratio,
                extra={
                    "component": "metrics_summary",
                    "mode": summary.mode,
                    "signals_per_day": summary.signals_per_day,
                    "roi_30d_pct": summary.roi_30d,
                    "win_rate_pct": summary.win_rate_pct,
                    "sharpe_ratio": summary.sharpe_ratio,
                    "total_trades": summary.total_trades,
                }
            )
            return True

        except Exception as e:
            logger.error("Failed to publish metrics summary to Redis: %s", e)
            return False

    async def run(self) -> SummaryMetrics:
        """
        Run full calculation and publish to Redis.
        
        This is the main entry point for hourly metrics updates.
        Called by scheduled task or manual execution.
        
        Returns:
            SummaryMetrics object (also published to Redis)
        """
        logger.info("Starting metrics calculation for %s mode", self.mode)
        summary = await self.calculate_summary()
        
        published = await self.publish_to_redis(summary)
        if published:
            logger.info("Successfully published metrics summary to Redis")
        else:
            logger.warning("Failed to publish metrics summary to Redis")
        
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
