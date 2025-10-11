"""
agents/scalper/monitoring/performance.py

Comprehensive performance monitoring for the scalping agent.
Tracks KPIs, execution quality, and system health metrics.
"""

from __future__ import annotations

import asyncio
import logging
import statistics
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..config_loader import KrakenScalpingConfig
from ..infra.redis_bus import RedisBus
from ..infra.state_manager import StateManager

# --------------------------- Data Structures --------------------------- #


@dataclass
class TradeMetrics:
    """Metrics for a single (completed or in-flight) trade."""

    trade_id: str
    timestamp: float
    symbol: str
    side: str  # "buy" or "sell"
    size: float
    entry_price: float
    exit_price: Optional[float] = None
    pnl: float = 0.0  # gross P&L in quote currency (e.g., USD)
    fees: float = 0.0
    slippage_bps: float = 0.0
    latency_ms: float = 0.0
    hold_time_seconds: float = 0.0
    win: bool = False

    @property
    def net_pnl(self) -> float:
        """Net P&L after fees."""
        return float(self.pnl) - float(self.fees)

    @property
    def is_closed(self) -> bool:
        return self.exit_price is not None

    @property
    def direction(self) -> int:
        """+1 for long, -1 for short."""
        if self.side.lower() == "buy":
            return 1
        if self.side.lower() == "sell":
            return -1
        return 0

    @property
    def return_bps(self) -> float:
        """
        Trade return in basis points, signed by direction.
        Uses entry/exit prices when available; if open, uses current P&L approximation from pnl/entry notionals.
        """
        if self.entry_price <= 0:
            return 0.0
        if self.exit_price is not None:
            pct = (self.exit_price - self.entry_price) / self.entry_price
            return pct * 10_000.0 * self.direction
        # Fallback if still open: approximate from pnl vs notional
        notional = abs(self.size) * self.entry_price
        if notional <= 0:
            return 0.0
        pct = (self.pnl - self.fees) / notional
        return pct * 10_000.0

    def close(self, exit_price: float, fees: float, slippage_bps: float, latency_ms: float) -> None:
        self.exit_price = float(exit_price)
        self.fees += float(fees)
        # P&L: sign by direction
        price_diff = (self.exit_price - self.entry_price) * self.direction
        self.pnl = float(self.size) * price_diff
        self.hold_time_seconds = max(0.0, time.time() - self.timestamp)
        self.win = self.pnl > 0.0
        # Track execution quality additively (allow accumulation across partials)
        # Use EMA-ish blend to stabilize if multiple fills recorded before close
        if slippage_bps is not None:
            if self.slippage_bps == 0.0:
                self.slippage_bps = float(slippage_bps)
            else:
                self.slippage_bps = 0.5 * float(slippage_bps) + 0.5 * self.slippage_bps
        if latency_ms is not None:
            if self.latency_ms == 0.0:
                self.latency_ms = float(latency_ms)
            else:
                self.latency_ms = 0.5 * float(latency_ms) + 0.5 * self.latency_ms


@dataclass
class RollingWindows:
    """Rolling windows for KPIs."""

    # Store last N completed trades
    trades: deque = field(default_factory=lambda: deque(maxlen=1000))
    # Equity snapshots: (timestamp, equity)
    equity_curve: deque = field(default_factory=lambda: deque(maxlen=5000))
    # Recent execution stats for quick medians
    slippage_bps: deque = field(default_factory=lambda: deque(maxlen=2000))
    latency_ms: deque = field(default_factory=lambda: deque(maxlen=2000))
    # Per-trade returns (bps) for Sharpe-like stats
    returns_bps: deque = field(default_factory=lambda: deque(maxlen=2000))
    # Timestamps for trade frequency
    trade_timestamps: deque = field(default_factory=lambda: deque(maxlen=5000))


# ------------------------------ Monitor ------------------------------- #


class PerformanceMonitor:
    """
    Centralized performance and execution-quality monitor.

    Features:
    - Tracks trade lifecycle and computes net/gross P&L, win-rate, profit factor, expectancy
    - Rolling Sharpe (per-trade), drawdown on equity curve
    - Execution quality: slippage, latency, fill speed proxy, trade frequency
    - Publishes compact snapshots to Redis
    """

    def __init__(
        self,
        config: KrakenScalpingConfig,
        state_manager: StateManager,
        redis_bus: RedisBus,
        agent_id: str = "kraken_scalper",
        *,
        base_capital_usd: Optional[float] = None,
        snapshot_interval_sec: Optional[int] = None,
    ):
        self.config = config
        self.state_manager = state_manager
        self.redis_bus = redis_bus
        self.agent_id = agent_id
        self.logger = logging.getLogger(f"{__name__}.{agent_id}")

        # Tunables
        self.base_capital = float(
            base_capital_usd
            if base_capital_usd is not None
            else getattr(config, "base_capital", 10_000.0)
        )
        self.snapshot_interval = int(snapshot_interval_sec or 15)

        # Stores
        self.windows = RollingWindows()
        self.open_trades: Dict[str, TradeMetrics] = {}
        self.completed_trades: Dict[str, TradeMetrics] = {}

        # Aggregates
        self.gross_pnl_total = 0.0
        self.net_pnl_total = 0.0
        self.fees_total = 0.0
        self.max_equity = self.base_capital
        self.min_equity = self.base_capital
        self.max_drawdown = 0.0  # negative fraction of peak (e.g., -0.08)

        # Runtime
        self._task: Optional[asyncio.Task] = None
        self._running = False

        # Seed equity curve with base capital
        now = time.time()
        self.windows.equity_curve.append((now, self.base_capital))

        self.logger.info("PerformanceMonitor initialized (base_capital=%.2f)", self.base_capital)

    # -------------------------- Lifecycle -------------------------- #

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        self.logger.info("PerformanceMonitor started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except asyncio.TimeoutError:
                self._task.cancel()
        self.logger.info("PerformanceMonitor stopped")

    # --------------------- Trade Recording API --------------------- #

    def record_trade_open(
        self,
        trade_id: str,
        symbol: str,
        side: str,
        size: float,
        entry_price: float,
        *,
        timestamp: Optional[float] = None,
        est_slippage_bps: float = 0.0,
        est_latency_ms: float = 0.0,
        fees: float = 0.0,
    ) -> None:
        """Register a newly-opened trade."""
        ts = float(timestamp or time.time())
        size = float(size)
        entry_price = float(entry_price)

        if size <= 0 or entry_price <= 0:
            self.logger.warning("Ignoring trade_open with non-positive size/price: %s", trade_id)
            return

        tm = TradeMetrics(
            trade_id=str(trade_id),
            timestamp=ts,
            symbol=symbol,
            side=side,
            size=size,
            entry_price=entry_price,
            pnl=0.0,
            fees=float(fees),
            slippage_bps=float(est_slippage_bps),
            latency_ms=float(est_latency_ms),
        )
        self.open_trades[tm.trade_id] = tm
        self.windows.trade_timestamps.append(ts)

    def record_trade_close(
        self,
        trade_id: str,
        exit_price: float,
        *,
        fees: float = 0.0,
        slippage_bps: Optional[float] = None,
        latency_ms: Optional[float] = None,
        close_timestamp: Optional[float] = None,
    ) -> Optional[TradeMetrics]:
        """Close an open trade, compute final metrics, and ingest into rolling windows."""
        if trade_id not in self.open_trades:
            self.logger.warning("record_trade_close: unknown trade_id %s", trade_id)
            return None

        tm = self.open_trades.pop(trade_id)
        tm.close(
            float(exit_price), float(fees), float(slippage_bps or 0.0), float(latency_ms or 0.0)
        )
        if close_timestamp:
            # Override hold time if caller has explicit end time
            tm.hold_time_seconds = max(0.0, float(close_timestamp) - tm.timestamp)

        # Totals
        self.fees_total += float(fees)
        self.gross_pnl_total += tm.pnl
        self.net_pnl_total += tm.net_pnl

        # Rolling windows & curves
        self.windows.trades.append(tm)
        if tm.slippage_bps != 0.0:
            self.windows.slippage_bps.append(tm.slippage_bps)
        if tm.latency_ms != 0.0:
            self.windows.latency_ms.append(tm.latency_ms)
        if tm.return_bps != 0.0:
            self.windows.returns_bps.append(tm.return_bps)

        # Update equity & DD
        last_equity = (
            self.windows.equity_curve[-1][1] if self.windows.equity_curve else self.base_capital
        )
        new_equity = last_equity + tm.net_pnl
        now = time.time()
        self.windows.equity_curve.append((now, new_equity))
        self.max_equity = max(self.max_equity, new_equity)
        self.min_equity = min(self.min_equity, new_equity)
        # drawdown as negative fraction from peak
        if self.max_equity > 0:
            dd = (new_equity - self.max_equity) / self.max_equity
            self.max_drawdown = min(self.max_drawdown, dd)

        # Archive in completed map
        self.completed_trades[tm.trade_id] = tm
        return tm

    def record_partial_fill_observation(
        self,
        trade_id: str,
        *,
        interim_slippage_bps: Optional[float] = None,
        interim_latency_ms: Optional[float] = None,
    ) -> None:
        """Optionally blend observed slippage/latency for an in-flight trade."""
        tm = self.open_trades.get(trade_id)
        if not tm:
            return
        if interim_slippage_bps is not None:
            tm.slippage_bps = 0.7 * tm.slippage_bps + 0.3 * float(interim_slippage_bps)
        if interim_latency_ms is not None:
            tm.latency_ms = 0.7 * tm.latency_ms + 0.3 * float(interim_latency_ms)

    # --------------------------- Snapshots --------------------------- #

    def get_snapshot(self) -> Dict[str, Any]:
        """Return a compact KPI snapshot for dashboards / logs."""
        kpis = self._compute_kpis()
        execq = self._compute_execution_quality()
        freq = self._compute_trade_frequency()

        snapshot = {
            "timestamp": time.time(),
            "base_capital": self.base_capital,
            "pnl": {
                "gross_total": self.gross_pnl_total,
                "net_total": self.net_pnl_total,
                "fees_total": self.fees_total,
                "open_trade_count": len(self.open_trades),
            },
            "performance": kpis,
            "execution_quality": execq,
            "trade_frequency": freq,
            "risk": {
                "max_drawdown": self.max_drawdown,  # negative fraction
                "equity": (
                    self.windows.equity_curve[-1][1]
                    if self.windows.equity_curve
                    else self.base_capital
                ),
            },
        }
        return snapshot

    # -------------------------- Background -------------------------- #

    async def _loop(self) -> None:
        """Periodic publisher for dashboards/alerting."""
        while self._running:
            try:
                snap = self.get_snapshot()
                await self.redis_bus.publish(f"perf:snapshot:{self.agent_id}", snap)
                await asyncio.sleep(self.snapshot_interval)
            except Exception as e:
                self.logger.error("PerformanceMonitor loop error: %s", e, exc_info=True)
                await asyncio.sleep(self.snapshot_interval)

    # --------------------------- Computations --------------------------- #

    def _compute_kpis(self) -> Dict[str, Any]:
        """Aggregate KPIs over rolling completed trades."""
        trades = list(self.windows.trades)
        n = len(trades)

        if n == 0:
            return {
                "win_rate": 0.0,
                "profit_factor": None,
                "expectancy_per_trade": 0.0,
                "avg_hold_time_sec": 0.0,
                "median_hold_time_sec": 0.0,
                "sharpe_per_trade": None,
                "avg_return_bps": 0.0,
                "std_return_bps": 0.0,
            }

        wins = [t for t in trades if t.net_pnl > 0]
        losses = [t for t in trades if t.net_pnl < 0]
        win_rate = len(wins) / n

        gross_win = sum(t.net_pnl for t in wins)
        gross_loss = -sum(t.net_pnl for t in losses)  # positive number
        profit_factor = (gross_win / gross_loss) if gross_loss > 0 else None

        expectancy = (gross_win - gross_loss) / n if n > 0 else 0.0

        holds = [t.hold_time_seconds for t in trades if t.hold_time_seconds > 0]
        avg_hold = (sum(holds) / len(holds)) if holds else 0.0
        median_hold = statistics.median(holds) if holds else 0.0

        # Sharpe-like per trade using returns_bps (~mean/std)
        rets = list(self.windows.returns_bps)
        if len(rets) >= 5:
            mu = statistics.fmean(rets)
            sd = statistics.pstdev(rets) if len(rets) > 1 else 0.0
            sharpe = (mu / sd) if sd > 0 else None
            avg_ret, std_ret = mu, sd
        else:
            sharpe = None
            avg_ret, std_ret = 0.0, 0.0

        return {
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "expectancy_per_trade": expectancy,
            "avg_hold_time_sec": avg_hold,
            "median_hold_time_sec": median_hold,
            "sharpe_per_trade": sharpe,
            "avg_return_bps": avg_ret,
            "std_return_bps": std_ret,
        }

    def _compute_execution_quality(self) -> Dict[str, Any]:
        """Aggregate execution quality metrics (slippage, latency)."""
        slipp = list(self.windows.slippage_bps)
        lat = list(self.windows.latency_ms)

        def _safe_avg(x: List[float]) -> float:
            return float(statistics.fmean(x)) if x else 0.0

        def _safe_med(x: List[float]) -> float:
            return float(statistics.median(x)) if x else 0.0

        return {
            "avg_slippage_bps": _safe_avg(slipp),
            "median_slippage_bps": _safe_med(slipp),
            "avg_latency_ms": _safe_avg(lat),
            "median_latency_ms": _safe_med(lat),
            "samples_slippage": len(slipp),
            "samples_latency": len(lat),
        }

    def _compute_trade_frequency(self) -> Dict[str, Any]:
        """Trades per minute/hour (rolling using timestamps deque)."""
        now = time.time()
        tss = list(self.windows.trade_timestamps)
        last_min = [t for t in tss if now - t <= 60]
        last_hour = [t for t in tss if now - t <= 3600]
        return {
            "trades_per_min": float(len(last_min)),
            "trades_per_hour": float(len(last_hour)),
            "total_completed_trades": float(len(self.windows.trades)),
        }

    # ----------------------------- Helpers ----------------------------- #

    def rebuild_from_state(self) -> None:
        """
        Optional: Rebuild equity curve & totals from completed_trades map.
        Useful after persistence reload. Call this once after hydration.
        """
        eq = self.base_capital
        self.windows.equity_curve.clear()
        self.windows.equity_curve.append((time.time(), eq))
        self.gross_pnl_total = 0.0
        self.net_pnl_total = 0.0
        self.fees_total = 0.0
        self.max_equity = eq
        self.min_equity = eq
        self.max_drawdown = 0.0

        for tm in sorted(self.completed_trades.values(), key=lambda t: t.timestamp):
            self.gross_pnl_total += tm.pnl
            self.net_pnl_total += tm.net_pnl
            self.fees_total += tm.fees
            eq += tm.net_pnl
            self.windows.trades.append(tm)
            if tm.slippage_bps != 0.0:
                self.windows.slippage_bps.append(tm.slippage_bps)
            if tm.latency_ms != 0.0:
                self.windows.latency_ms.append(tm.latency_ms)
            if tm.return_bps != 0.0:
                self.windows.returns_bps.append(tm.return_bps)
            self.windows.equity_curve.append((tm.timestamp, eq))
            self.max_equity = max(self.max_equity, eq)
            self.min_equity = min(self.min_equity, eq)
            if self.max_equity > 0:
                dd = (eq - self.max_equity) / self.max_equity
                self.max_drawdown = min(self.max_drawdown, dd)
