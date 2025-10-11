"""
agents/risk/drawdown_protector.py

Production-grade drawdown protection module for crypto-ai-bot.
Enforces multi-layered risk limits with state machine logic.

PURE LOGIC MODULE:
- No environment reads, file/network/Redis I/O
- Pydantic v2 models only
- UTC-only time via epoch seconds
- Deterministic behavior with optional time provider injection
- O(1) performance per event

FUNCTIONALITY:
- Daily & rolling drawdown monitoring
- 4-state machine: NORMAL → WARN → SOFT_STOP → HARD_HALT
- Consecutive loss tracking with same-day breach rules
- Risk scaling via configurable bands
- Scope precedence: Portfolio → Strategy → Symbol
- Cooldown periods to prevent state thrashing
"""

from __future__ import annotations

import time
from collections import deque
from typing import Callable, Deque, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field


# ---- Policy / Config ----
class DrawdownBands(BaseModel):
    """Risk policy configuration with immutable settings."""

    model_config = ConfigDict(frozen=True)

    # Primary limits
    daily_stop_pct: float = Field(default=-0.02, description="Daily stop loss percentage")
    rolling_windows_pct: List[Tuple[int, float]] = Field(
        default_factory=lambda: [(3600, -0.01), (14400, -0.015)],
        description="Rolling window limits as (window_seconds, limit_pct)",
    )
    max_consecutive_losses: int = Field(default=3, description="Loss streak threshold")

    # Cooldown periods
    cooldown_after_soft_s: int = Field(default=600, description="Soft stop cooldown seconds")
    cooldown_after_hard_s: int = Field(default=1800, description="Hard halt cooldown seconds")

    # Risk scaling bands (drawdown_pct, size_multiplier)
    scale_bands: List[Tuple[float, float]] = Field(
        default_factory=lambda: [(-0.01, 0.75), (-0.02, 0.5), (-0.03, 0.25)],
        description="Progressive size reduction bands; ordered from mild→severe",
    )

    # Scope controls
    enable_per_strategy: bool = Field(default=True, description="Enable strategy-level monitoring")
    enable_per_symbol: bool = Field(default=True, description="Enable symbol-level monitoring")


# ---- State snapshots ----
class DrawdownScopeState(BaseModel):
    """State for a single scope (portfolio/strategy/symbol)."""

    model_config = ConfigDict(frozen=False)

    loss_streak: int = 0
    dd_daily_pct: float = 0.0
    dd_rolling_pct: float = 0.0
    size_multiplier: float = 1.0
    mode: Literal["normal", "warn", "soft_stop", "hard_halt"] = "normal"
    cooldown_ends_at_s: Optional[int] = None
    trigger_reason: Optional[str] = None


class DrawdownState(BaseModel):
    """Complete system state snapshot."""

    model_config = ConfigDict(frozen=False)

    portfolio: DrawdownScopeState
    per_strategy: Dict[str, DrawdownScopeState] = {}
    per_symbol: Dict[str, DrawdownScopeState] = {}


# ---- Events ----
class FillEvent(BaseModel):
    """Trade execution event."""

    ts_s: int = Field(description="UTC timestamp seconds")
    pnl_after_fees: float = Field(description="P&L including fees")
    strategy: str = Field(description="Strategy identifier")
    symbol: str = Field(description="Trading symbol")
    won: bool = Field(description="True if profitable trade")


class SnapshotEvent(BaseModel):
    """Equity snapshot event."""

    ts_s: int = Field(description="UTC timestamp seconds")
    equity_start_of_day_usd: float = Field(description="Start of day equity")
    equity_current_usd: float = Field(description="Current total equity")
    strategy_equity_usd: Optional[Dict[str, float]] = Field(
        default=None, description="Per-strategy equity breakdown"
    )
    symbol_equity_usd: Optional[Dict[str, float]] = Field(
        default=None, description="Per-symbol equity breakdown"
    )


# ---- Decisions ----
class GateDecision(BaseModel):
    """Trading gate decision."""

    allow_new_positions: bool = Field(description="Allow opening new positions")
    reduce_only: bool = Field(description="Only allow position reduction")
    halt_all: bool = Field(description="Halt all trading operations")
    size_multiplier: float = Field(description="Position size scaling factor")
    reason: Optional[str] = Field(default=None, description="Decision reason code")


# ---- Internal helpers ----
class _RollingWindow:
    """Efficient rolling window for drawdown calculation."""

    def __init__(self, window_seconds: int) -> None:
        self.window_seconds: int = window_seconds
        self.data: Deque[Tuple[int, float]] = deque()

    def update(self, ts_s: int, equity: float) -> None:
        """Add new data point and remove stale entries."""
        self.data.append((ts_s, equity))
        cutoff = ts_s - self.window_seconds
        while self.data and self.data[0][0] < cutoff:
            self.data.popleft()

    def get_drawdown_pct(self) -> float:
        """Calculate peak-to-current drawdown percentage."""
        if len(self.data) < 2:
            return 0.0
        peak_equity = max(e for _, e in self.data)
        current_equity = self.data[-1][1]
        if peak_equity <= 0:
            return 0.0
        return (current_equity - peak_equity) / peak_equity


# ---- Main class ----
class DrawdownProtector:
    """
    Production drawdown protection system with multi-scope monitoring.

    Features:
    - Portfolio, strategy, and symbol-level risk tracking
    - Progressive state machine: NORMAL → WARN → SOFT_STOP → HARD_HALT
    - Rolling window drawdown monitoring
    - Consecutive loss streak detection
    - Cooldown periods to prevent oscillation
    - Risk scaling via configurable bands
    """

    def __init__(
        self, policy: DrawdownBands, now_s_provider: Optional[Callable[[], int]] = None
    ) -> None:
        """
        Initialize drawdown protector.

        Args:
            policy: Risk policy configuration
            now_s_provider: Optional time provider for deterministic testing
        """
        self.policy = policy
        self._now_s_provider: Callable[[], int] = now_s_provider or (lambda: int(time.time()))
        self.state = DrawdownState(portfolio=DrawdownScopeState())

        # Day tracking
        self._equity_start_of_day_usd: float = 0.0
        self._current_day_utc: int = self._get_utc_day(self._now_s_provider())

        # Loss streak tracking
        self._hard_halt_breach_count: int = 0
        self._today_hard_halt_breaches: set[int] = set()

        # Rolling windows
        self._portfolio_windows: List[_RollingWindow] = []
        self._strategy_windows: Dict[str, List[_RollingWindow]] = {}
        self._symbol_windows: Dict[str, List[_RollingWindow]] = {}

        self._init_rolling_windows()

    def _init_rolling_windows(self) -> None:
        """Initialize rolling windows for portfolio scope."""
        self._portfolio_windows = [
            _RollingWindow(window_s) for window_s, _ in self.policy.rolling_windows_pct
        ]

    def _ensure_scope_exists(self, strategy: str, symbol: str) -> None:
        """Ensure strategy and symbol scopes exist if enabled; ignore empty ids to avoid phantom scopes."""
        if self.policy.enable_per_strategy and strategy:
            if strategy not in self.state.per_strategy:
                self.state.per_strategy[strategy] = DrawdownScopeState()
                self._strategy_windows[strategy] = [
                    _RollingWindow(window_s) for window_s, _ in self.policy.rolling_windows_pct
                ]

        if self.policy.enable_per_symbol and symbol:
            if symbol not in self.state.per_symbol:
                self.state.per_symbol[symbol] = DrawdownScopeState()
                self._symbol_windows[symbol] = [
                    _RollingWindow(window_s) for window_s, _ in self.policy.rolling_windows_pct
                ]

    @staticmethod
    def _get_utc_day(ts_s: int) -> int:
        """Convert timestamp to UTC day number."""
        return ts_s // 86400

    def _calculate_size_multiplier(self, dd_pct: float) -> float:
        """Calculate position size multiplier based on drawdown severity."""
        for threshold_pct, multiplier in reversed(self.policy.scale_bands):
            if dd_pct <= threshold_pct:
                return multiplier
        return 1.0

    def _update_scope_state(
        self,
        scope_state: DrawdownScopeState,
        windows: List[_RollingWindow],
        dd_daily_pct: float,
        ts_s: int,
    ) -> None:
        """Update state for a single scope (portfolio/strategy/symbol)."""
        # Update drawdown metrics
        scope_state.dd_daily_pct = dd_daily_pct
        rolling_dds: List[float] = [w.get_drawdown_pct() for w in windows]
        scope_state.dd_rolling_pct = min(rolling_dds) if rolling_dds else 0.0

        # Pair each window's DD with its configured limit (order preserved)
        rolling_breach: bool = (
            any(dd <= limit for dd, (_, limit) in zip(rolling_dds, self.policy.rolling_windows_pct))
            if rolling_dds
            else False
        )

        worst_dd = min(dd_daily_pct, scope_state.dd_rolling_pct)
        scope_state.size_multiplier = self._calculate_size_multiplier(worst_dd)

        # Check triggers
        loss_streak_breach = scope_state.loss_streak >= self.policy.max_consecutive_losses
        now_s = self._now_s_provider()
        scope_id = id(scope_state)

        # Cooldown state pinning - don't change mode during active cooldown
        if scope_state.cooldown_ends_at_s and now_s < scope_state.cooldown_ends_at_s:
            return

        # Clear expired cooldowns
        if scope_state.cooldown_ends_at_s and now_s >= scope_state.cooldown_ends_at_s:
            scope_state.cooldown_ends_at_s = None

        hard_halt_threshold = self.policy.daily_stop_pct * 1.5

        # Track hard halt triggers for same-day second breach rule
        second_loss_streak_breach_today = (
            loss_streak_breach and scope_id in self._today_hard_halt_breaches
        )

        # Store previous mode to detect transitions
        previous_mode = scope_state.mode

        # Hard halt: severe DD or second loss streak breach same day
        if worst_dd <= hard_halt_threshold or second_loss_streak_breach_today:
            # Allow transition from any mode to hard halt
            scope_state.mode = "hard_halt"
            if second_loss_streak_breach_today:
                scope_state.trigger_reason = "loss-streak-hard"
            else:
                scope_state.trigger_reason = "daily-stop-hit"

        # Soft stop: moderate DD, any rolling window breach, or first loss streak breach
        elif (
            worst_dd <= self.policy.daily_stop_pct
            or rolling_breach
            or (loss_streak_breach and scope_id not in self._today_hard_halt_breaches)
        ):
            # Allow transition to soft stop from any mode except hard halt
            if previous_mode != "hard_halt":
                scope_state.mode = "soft_stop"
                if worst_dd <= self.policy.daily_stop_pct:
                    scope_state.trigger_reason = "daily-stop-hit"
                elif rolling_breach:
                    scope_state.trigger_reason = "soft-stop-rolling-dd"
                elif loss_streak_breach:
                    scope_state.trigger_reason = "loss-streak-soft"
                else:
                    scope_state.trigger_reason = "soft-stop-triggered"

        # Warn: first scale band threshold
        elif self.policy.scale_bands and worst_dd <= self.policy.scale_bands[0][0]:
            if previous_mode == "normal":
                scope_state.mode = "warn"
                scope_state.trigger_reason = "warn-band-hit"

        elif previous_mode == "warn" and scope_state.dd_daily_pct > self.policy.scale_bands[0][0]:
            scope_state.mode = "normal"
            scope_state.trigger_reason = None

        # Track loss streak breaches for same-day rule
        if loss_streak_breach:
            self._today_hard_halt_breaches.add(scope_id)

    def reset(self, equity_start_of_day_usd: float, ts_s: int) -> None:
        """Reset system state with new starting equity."""
        self._equity_start_of_day_usd = equity_start_of_day_usd
        self._current_day_utc = self._get_utc_day(ts_s)
        self._hard_halt_breach_count = 0
        self._today_hard_halt_breaches.clear()
        self.state = DrawdownState(portfolio=DrawdownScopeState())
        self._strategy_windows.clear()
        self._symbol_windows.clear()
        self._init_rolling_windows()

        # Initialize portfolio windows with starting equity
        for w in self._portfolio_windows:
            w.update(ts_s, equity_start_of_day_usd)

    def on_day_rollover(self, equity_start_of_day_usd: float, ts_s: int) -> None:
        """Handle day rollover - reset daily metrics, preserve rolling windows."""
        self._equity_start_of_day_usd = equity_start_of_day_usd
        self._current_day_utc = self._get_utc_day(ts_s)
        self._hard_halt_breach_count = 0
        self._today_hard_halt_breaches.clear()

        # Reset daily metrics only
        self.state.portfolio.loss_streak = 0
        for s in self.state.per_strategy.values():
            s.loss_streak = 0
        for s in self.state.per_symbol.values():
            s.loss_streak = 0

    def ingest_fill(self, e: FillEvent) -> None:
        """Process trade fill event to update loss streaks."""
        self._ensure_scope_exists(e.strategy, e.symbol)

        # Handle day rollover if needed
        if self._get_utc_day(e.ts_s) != self._current_day_utc:
            self.on_day_rollover(self._equity_start_of_day_usd, e.ts_s)

        # Update loss streaks
        if e.won:
            # Reset streaks on winning trade
            self.state.portfolio.loss_streak = 0
            if e.strategy in self.state.per_strategy:
                self.state.per_strategy[e.strategy].loss_streak = 0
            if e.symbol in self.state.per_symbol:
                self.state.per_symbol[e.symbol].loss_streak = 0
        else:
            # Increment streaks on losing trade
            self.state.portfolio.loss_streak += 1
            if e.strategy in self.state.per_strategy:
                self.state.per_strategy[e.strategy].loss_streak += 1
            if e.symbol in self.state.per_symbol:
                self.state.per_symbol[e.symbol].loss_streak += 1

            # Track portfolio-level breach count for reasoning
            if self.state.portfolio.loss_streak >= self.policy.max_consecutive_losses:
                self._hard_halt_breach_count += 1

    def ingest_snapshot(self, e: SnapshotEvent) -> None:
        """Process equity snapshot to update drawdown states."""
        # Handle day rollover if needed
        if self._get_utc_day(e.ts_s) != self._current_day_utc:
            self.on_day_rollover(e.equity_start_of_day_usd, e.ts_s)

        # Update portfolio scope
        portfolio_dd = (
            (e.equity_current_usd - e.equity_start_of_day_usd) / e.equity_start_of_day_usd
            if e.equity_start_of_day_usd > 0
            else 0.0
        )
        for w in self._portfolio_windows:
            w.update(e.ts_s, e.equity_current_usd)
        self._update_scope_state(
            self.state.portfolio, self._portfolio_windows, portfolio_dd, e.ts_s
        )

        # Update strategy scopes
        if self.policy.enable_per_strategy and e.strategy_equity_usd:
            for strat, eq in e.strategy_equity_usd.items():
                self._ensure_scope_exists(strat, "")
                dd = (
                    (eq - self._equity_start_of_day_usd) / self._equity_start_of_day_usd
                    if self._equity_start_of_day_usd > 0
                    else 0.0
                )
                for w in self._strategy_windows[strat]:
                    w.update(e.ts_s, eq)
                self._update_scope_state(
                    self.state.per_strategy[strat], self._strategy_windows[strat], dd, e.ts_s
                )

        # Update symbol scopes
        if self.policy.enable_per_symbol and e.symbol_equity_usd:
            for sym, eq in e.symbol_equity_usd.items():
                self._ensure_scope_exists("", sym)
                dd = (
                    (eq - self._equity_start_of_day_usd) / self._equity_start_of_day_usd
                    if self._equity_start_of_day_usd > 0
                    else 0.0
                )
                for w in self._symbol_windows[sym]:
                    w.update(e.ts_s, eq)
                self._update_scope_state(
                    self.state.per_symbol[sym], self._symbol_windows[sym], dd, e.ts_s
                )

    def assess_can_open(self, strategy: str, symbol: str) -> GateDecision:
        """Assess if new positions can be opened for given strategy/symbol."""
        self._ensure_scope_exists(strategy, symbol)

        # Gather all applicable scopes
        scopes = [("portfolio", self.state.portfolio)]
        if strategy in self.state.per_strategy:
            scopes.append(("strategy", self.state.per_strategy[strategy]))
        if symbol in self.state.per_symbol:
            scopes.append(("symbol", self.state.per_symbol[symbol]))

        # Find most restrictive scope
        mode_order = {"normal": 0, "warn": 1, "soft_stop": 2, "hard_halt": 3}
        worst_scope_name, worst_mode = "portfolio", "normal"
        min_multiplier = 1.0

        for name, state in scopes:
            if mode_order[state.mode] > mode_order[worst_mode]:
                worst_scope_name, worst_mode = name, state.mode
            min_multiplier = min(min_multiplier, state.size_multiplier)

        scope = next(s for n, s in scopes if n == worst_scope_name)
        now_s = self._now_s_provider()

        # Start cooldown after first assessment if in stop mode
        if scope.mode in ("soft_stop", "hard_halt") and not scope.cooldown_ends_at_s:
            if scope.mode == "hard_halt":
                scope.cooldown_ends_at_s = now_s + self.policy.cooldown_after_hard_s
            elif scope.mode == "soft_stop":
                scope.cooldown_ends_at_s = now_s + self.policy.cooldown_after_soft_s

        # Generate decision based on worst mode
        if worst_mode == "hard_halt":
            reason = scope.trigger_reason or "hard-halt-triggered"
            if scope.cooldown_ends_at_s and now_s < scope.cooldown_ends_at_s:
                cooldown_age = now_s - (
                    scope.cooldown_ends_at_s - self.policy.cooldown_after_hard_s
                )
                if cooldown_age >= 1:  # Only show cooldown status after 1 second
                    reason = "cooldown-hard-active"

            return GateDecision(
                allow_new_positions=False,
                reduce_only=False,
                halt_all=True,
                size_multiplier=min_multiplier,
                reason=reason,
            )

        if worst_mode == "soft_stop":
            reason = scope.trigger_reason or "soft-stop-triggered"
            if scope.cooldown_ends_at_s and now_s < scope.cooldown_ends_at_s:
                cooldown_age = now_s - (
                    scope.cooldown_ends_at_s - self.policy.cooldown_after_soft_s
                )
                if cooldown_age >= 1:  # Only show cooldown status after 1 second
                    reason = "cooldown-soft-active"

            return GateDecision(
                allow_new_positions=False,
                reduce_only=True,
                halt_all=False,
                size_multiplier=min_multiplier,
                reason=reason,
            )

        if worst_mode == "warn":
            return GateDecision(
                allow_new_positions=True,
                reduce_only=False,
                halt_all=False,
                size_multiplier=min_multiplier,
                reason="warn-band-hit",
            )

        return GateDecision(
            allow_new_positions=True,
            reduce_only=False,
            halt_all=False,
            size_multiplier=min_multiplier,
            reason=None,
        )

    def current_state(self) -> DrawdownState:
        """Get deep copy of current system state."""
        return self.state.model_copy(deep=True)

    def apply_policy(self, policy: DrawdownBands) -> None:
        """Apply new risk policy configuration."""
        self.policy = policy

        # Reinitialize rolling windows with new configuration
        self._init_rolling_windows()
        self._strategy_windows.clear()
        self._symbol_windows.clear()

        # Recreate windows for existing scopes
        for strat in self.state.per_strategy:
            self._strategy_windows[strat] = [
                _RollingWindow(w) for w, _ in policy.rolling_windows_pct
            ]
        for sym in self.state.per_symbol:
            self._symbol_windows[sym] = [_RollingWindow(w) for w, _ in policy.rolling_windows_pct]
