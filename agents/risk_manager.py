"""
Top-Level Risk Manager Module (agents/risk_manager.py)

Production-grade risk manager coordinating position sizing, portfolio caps, leverage limits,
and drawdown breakers per PRD §6 & §8.

HARD REQUIREMENTS:
- Pure logic: No I/O, no env reads beyond config initialization
- Deterministic outputs: Same inputs → same outputs
- Position sizing: 1-2% per-trade risk via SL distance
- Portfolio caps: ≤4% total concurrent risk
- Leverage limits: Default 2-3x, max 5x per symbol
- Drawdown breakers: Pause or drop to 0.5x risk on daily/rolling DD thresholds
- Integrates with: RegimeTick (STEP 2), SignalSpec (STEP 3), existing agents/risk modules

INTERFACES:
- size_position(signal, equity, volatility) -> PositionSize
- check_portfolio_risk(positions, equity) -> RiskCheckResult
- apply_drawdown_breakers(equity_curve) -> DrawdownState

SOURCE: PRD.md §6 (Strategy Stack), §8 (Risk & Leverage Policy)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)

# =============================================================================
# SIGNAL/POSITION TYPES (simplified to avoid circular imports)
# =============================================================================

# We define minimal signal input type to avoid importing strategies.api
# In production use, RiskManager accepts strategies.api.SignalSpec
@dataclass(frozen=True)
class SignalInput:
    """Simplified signal input (compatible with strategies.api.SignalSpec)"""
    signal_id: str
    symbol: str
    side: str
    entry_price: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    confidence: Decimal

# =============================================================================
# CONFIGURATION MODELS
# =============================================================================


class RiskConfig(BaseModel):
    """Risk manager configuration with immutable defaults per PRD §8."""

    model_config = ConfigDict(frozen=True, extra='forbid')

    # Per-trade risk
    per_trade_risk_pct_min: float = Field(
        default=0.01,
        ge=0.0,
        le=1.0,
        description="Minimum per-trade risk (1% of equity)",
    )
    per_trade_risk_pct_max: float = Field(
        default=0.02,
        ge=0.0,
        le=1.0,
        description="Maximum per-trade risk (2% of equity)",
    )

    # Portfolio exposure caps
    max_portfolio_risk_pct: float = Field(
        default=0.04,
        ge=0.0,
        le=1.0,
        description="Max concurrent portfolio risk (4% of equity)",
    )
    max_concurrent_positions: int = Field(
        default=3, ge=1, description="Maximum concurrent positions"
    )

    # Leverage limits (PRD §8: default 2-3x, max 5x)
    default_leverage: float = Field(default=2.0, ge=1.0, description="Default leverage")
    max_leverage_default: float = Field(
        default=5.0, ge=1.0, description="Default max leverage"
    )

    # Per-symbol leverage overrides (loaded from exchange config)
    leverage_caps: Dict[str, float] = Field(
        default_factory=dict, description="Per-symbol leverage caps"
    )

    # Risk/Reward ratio filter (STEP 5)
    min_rr_ratio: float = Field(
        default=1.6,
        ge=0.0,
        description="Minimum risk/reward ratio (TP distance / SL distance)",
    )

    # Drawdown breakers (STEP 5: 10% → halve, 15-20% → pause)
    dd_soft_threshold_pct: float = Field(
        default=-0.10, description="Soft DD threshold (-10%) → halve risk"
    )
    dd_hard_threshold_pct: float = Field(
        default=-0.15, description="Hard DD threshold (-15%) → pause trading"
    )
    dd_halt_threshold_pct: float = Field(
        default=-0.20, description="Full halt threshold (-20%) → extended pause"
    )
    dd_rolling_window_bars: int = Field(
        default=20, ge=1, description="Rolling DD window (bars)"
    )

    # Drawdown risk reduction
    dd_risk_multiplier_soft: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Risk multiplier on soft DD breach (50%)",
    )
    dd_pause_bars: int = Field(
        default=10, ge=0, description="Pause bars on hard DD breach"
    )

    # Minimum position size filter
    min_position_usd: float = Field(default=10.0, ge=0.0, description="Min position USD")

    @field_validator("per_trade_risk_pct_max")
    @classmethod
    def validate_risk_pct_max_gte_min(cls, v, info):
        """Validate max risk >= min risk"""
        if "per_trade_risk_pct_min" in info.data:
            if v < info.data["per_trade_risk_pct_min"]:
                raise ValueError(
                    f"per_trade_risk_pct_max ({v}) must be >= per_trade_risk_pct_min ({info.data['per_trade_risk_pct_min']})"
                )
        return v


# =============================================================================
# OUTPUT MODELS
# =============================================================================


@dataclass(frozen=True)
class PositionSize:
    """
    Position sizing result with risk-adjusted parameters.

    Attributes:
        signal_id: Reference to originating signal
        symbol: Trading symbol
        side: Trade direction ('long' or 'short')
        size: Position size in base currency (Decimal)
        notional_usd: Position value in USD (Decimal)
        entry_price: Entry price (Decimal)
        stop_loss: Stop loss price (Decimal)
        take_profit: Take profit price (Decimal)
        expected_risk_usd: Expected risk in USD (entry to SL)
        risk_pct: Risk as percentage of equity
        leverage: Applied leverage
        allowed: Whether position is allowed (passed all gates)
        rejection_reasons: List of rejection reasons if not allowed
    """

    signal_id: str
    symbol: str
    side: str
    size: Decimal
    notional_usd: Decimal
    entry_price: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    expected_risk_usd: Decimal
    risk_pct: Decimal
    leverage: Decimal
    allowed: bool
    rejection_reasons: List[str]


@dataclass(frozen=True)
class RiskCheckResult:
    """
    Portfolio-level risk check result.

    Attributes:
        passed: Whether portfolio risk is within limits
        total_risk_pct: Total concurrent risk as % of equity
        position_count: Number of concurrent positions
        violations: List of violated constraints
    """

    passed: bool
    total_risk_pct: Decimal
    position_count: int
    violations: List[str]


@dataclass(frozen=True)
class DrawdownState:
    """
    Drawdown breaker state.

    Attributes:
        daily_dd_pct: Current daily drawdown percentage
        rolling_dd_pct: Current rolling drawdown percentage
        mode: Current mode ('normal', 'soft_stop', 'hard_halt')
        risk_multiplier: Risk size multiplier (1.0 = normal, 0.5 = soft, 0.0 = halt)
        pause_remaining: Remaining pause bars (0 = not paused)
        trigger_reason: Reason for current state
    """

    daily_dd_pct: float
    rolling_dd_pct: float
    mode: str  # 'normal', 'soft_stop', 'hard_halt'
    risk_multiplier: float
    pause_remaining: int
    trigger_reason: Optional[str]


# =============================================================================
# RISK MANAGER
# =============================================================================


class RiskManager:
    """
    Top-level risk manager coordinating position sizing, portfolio caps, and drawdown breakers.

    Flow:
        1. size_position(signal) -> PositionSize (per-trade risk 1-2%)
        2. check_portfolio_risk(positions) -> RiskCheckResult (≤4% total)
        3. apply_drawdown_breakers(equity_curve) -> DrawdownState (pause/reduce on DD)

    All methods are deterministic and pure (no I/O).
    """

    def __init__(self, config: Optional[RiskConfig] = None):
        """
        Initialize risk manager with configuration.

        Args:
            config: Risk configuration (uses defaults if None)
        """
        self.config = config or RiskConfig()
        self._drawdown_state = DrawdownState(
            daily_dd_pct=0.0,
            rolling_dd_pct=0.0,
            mode="normal",
            risk_multiplier=1.0,
            pause_remaining=0,
            trigger_reason=None,
        )

        # Metrics tracking
        self._metrics = {
            "total_sized": 0,
            "total_rejected": 0,
            "rejected_min_size": 0,
            "rejected_leverage": 0,
            "rejected_portfolio_risk": 0,
            "rejected_drawdown": 0,
        }

    def size_position(
        self,
        signal: SignalInput,
        equity_usd: Decimal,
        volatility: Optional[Decimal] = None,
    ) -> PositionSize:
        """
        Size position based on signal with 1-2% per-trade risk via SL distance.

        Logic (PRD §8):
            1. Compute SL distance percentage
            2. Target risk = equity * (1-2%)
            3. Position size = target_risk / SL_distance
            4. Apply leverage caps (default 2-3x, max 5x per symbol)
            5. Apply drawdown multiplier if active
            6. Reject if below min_position_usd

        Args:
            signal: Trading signal to size
            equity_usd: Current account equity in USD
            volatility: Optional current volatility for vol targeting (not used yet)

        Returns:
            PositionSize with sizing details and allow/reject decision
        """
        self._metrics["total_sized"] += 1
        rejection_reasons = []

        # Check drawdown breaker first
        if self._drawdown_state.mode == "hard_halt":
            self._metrics["rejected_drawdown"] += 1
            self._metrics["total_rejected"] += 1
            return PositionSize(
                signal_id=signal.signal_id,
                symbol=signal.symbol,
                side=signal.side,
                size=Decimal("0"),
                notional_usd=Decimal("0"),
                entry_price=signal.entry_price,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                expected_risk_usd=Decimal("0"),
                risk_pct=Decimal("0"),
                leverage=Decimal("1"),
                allowed=False,
                rejection_reasons=["drawdown_hard_halt"],
            )

        # 1. Compute SL distance and TP distance for RR calculation
        entry = float(signal.entry_price)
        sl = float(signal.stop_loss)
        tp = float(signal.take_profit)

        sl_distance_pct = abs(entry - sl) / entry
        tp_distance_pct = abs(tp - entry) / entry

        # 1a. Check Risk/Reward ratio (STEP 5: min RR ≥ 1.6)
        if sl_distance_pct > 0:
            rr_ratio = tp_distance_pct / sl_distance_pct
            if rr_ratio < self.config.min_rr_ratio:
                self._metrics["total_rejected"] += 1
                return PositionSize(
                    signal_id=signal.signal_id,
                    symbol=signal.symbol,
                    side=signal.side,
                    size=Decimal("0"),
                    notional_usd=Decimal("0"),
                    entry_price=signal.entry_price,
                    stop_loss=signal.stop_loss,
                    take_profit=signal.take_profit,
                    expected_risk_usd=Decimal("0"),
                    risk_pct=Decimal("0"),
                    leverage=Decimal("1"),
                    allowed=False,
                    rejection_reasons=[f"low_risk_reward_ratio: {rr_ratio:.2f} < {self.config.min_rr_ratio:.2f}"],
                )

        # 2. Target risk (1-2% of equity, adjusted by DD multiplier)
        base_risk_pct = self.config.per_trade_risk_pct_max
        adjusted_risk_pct = base_risk_pct * self._drawdown_state.risk_multiplier

        target_risk_usd = float(equity_usd) * adjusted_risk_pct

        # 3. Position size (USD)
        notional_usd_raw = target_risk_usd / sl_distance_pct if sl_distance_pct > 0 else 0.0

        # 4. Apply leverage cap
        symbol_leverage_cap = self.config.leverage_caps.get(
            signal.symbol, self.config.max_leverage_default
        )
        max_leverage = min(symbol_leverage_cap, self.config.max_leverage_default)

        # Use default leverage (2-3x), capped by max
        leverage = min(self.config.default_leverage, max_leverage)

        # Notional after leverage
        notional_usd = notional_usd_raw

        # 5. Check minimum position size
        if notional_usd < self.config.min_position_usd:
            self._metrics["rejected_min_size"] += 1
            rejection_reasons.append("below_min_position_usd")

        # 6. Compute base size (depends on entry price)
        base_size = notional_usd / entry if entry > 0 else 0.0

        # Expected risk (with SL)
        expected_risk_usd = notional_usd * sl_distance_pct
        actual_risk_pct = expected_risk_usd / float(equity_usd) if float(equity_usd) > 0 else 0.0

        # 7. STRICT: Reject if risk exceeds 2% (STEP 5)
        if actual_risk_pct > self.config.per_trade_risk_pct_max:
            rejection_reasons.append(
                f"risk_exceeds_max: {actual_risk_pct:.2%} > {self.config.per_trade_risk_pct_max:.2%}"
            )

        allowed = len(rejection_reasons) == 0

        # Update total rejected counter
        if not allowed:
            self._metrics["total_rejected"] += 1

        return PositionSize(
            signal_id=signal.signal_id,
            symbol=signal.symbol,
            side=signal.side,
            size=Decimal(str(base_size)),
            notional_usd=Decimal(str(notional_usd)),
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            expected_risk_usd=Decimal(str(expected_risk_usd)),
            risk_pct=Decimal(str(actual_risk_pct)),
            leverage=Decimal(str(leverage)),
            allowed=allowed,
            rejection_reasons=rejection_reasons,
        )

    def check_portfolio_risk(
        self, positions: List[PositionSize], equity_usd: Decimal
    ) -> RiskCheckResult:
        """
        Check if portfolio-level risk is within limits (≤4% concurrent risk).

        Constraints (PRD §8):
            - Total concurrent risk ≤ 4% of equity
            - Max concurrent positions ≤ config.max_concurrent_positions

        Args:
            positions: List of current/proposed positions
            equity_usd: Current account equity

        Returns:
            RiskCheckResult with pass/fail and violations
        """
        violations = []

        # Total risk
        total_risk_usd = sum(float(p.expected_risk_usd) for p in positions if p.allowed)
        total_risk_pct = (
            total_risk_usd / float(equity_usd) if float(equity_usd) > 0 else 0.0
        )

        # Check total risk cap
        if total_risk_pct > self.config.max_portfolio_risk_pct:
            violations.append(
                f"portfolio_risk_exceeded: {total_risk_pct:.2%} > {self.config.max_portfolio_risk_pct:.2%}"
            )
            self._metrics["rejected_portfolio_risk"] += 1

        # Check position count
        allowed_positions = [p for p in positions if p.allowed]
        if len(allowed_positions) > self.config.max_concurrent_positions:
            violations.append(
                f"max_positions_exceeded: {len(allowed_positions)} > {self.config.max_concurrent_positions}"
            )

        passed = len(violations) == 0

        return RiskCheckResult(
            passed=passed,
            total_risk_pct=Decimal(str(total_risk_pct)),
            position_count=len(allowed_positions),
            violations=violations,
        )

    def update_drawdown_state(
        self, equity_curve: List[Decimal], current_bar: int
    ) -> DrawdownState:
        """
        Update drawdown breaker state based on equity curve.

        Logic (PRD §8):
            - Daily DD < -2%: Soft stop (0.5x risk)
            - Rolling DD (20 bars) < -5%: Hard halt (pause for 10 bars)
            - Auto-recover when DD improves

        Args:
            equity_curve: List of equity values (USD)
            current_bar: Current bar index

        Returns:
            Updated DrawdownState
        """
        if len(equity_curve) < 2:
            # Not enough data
            return self._drawdown_state

        current_equity = float(equity_curve[-1])

        # Daily DD (compare to previous bar)
        if len(equity_curve) >= 2:
            prev_equity = float(equity_curve[-2])
            daily_dd_pct = (
                (current_equity - prev_equity) / prev_equity if prev_equity > 0 else 0.0
            )
        else:
            daily_dd_pct = 0.0

        # Rolling DD (compare to peak in window)
        window_size = min(self.config.dd_rolling_window_bars, len(equity_curve))
        window = equity_curve[-window_size:]
        peak_equity = float(max(window))
        rolling_dd_pct = (
            (current_equity - peak_equity) / peak_equity if peak_equity > 0 else 0.0
        )

        # Determine mode (STEP 5: 3-tier thresholds)
        mode = "normal"
        risk_multiplier = 1.0
        pause_remaining = max(0, self._drawdown_state.pause_remaining - 1)
        trigger_reason = None

        # Check thresholds in order of severity (worst to best)
        # -20% or worse → Full halt (extended pause)
        if rolling_dd_pct <= self.config.dd_halt_threshold_pct:
            mode = "hard_halt"
            risk_multiplier = 0.0
            pause_remaining = self.config.dd_pause_bars * 2  # Extended pause
            trigger_reason = f"halt_dd={rolling_dd_pct:.2%} <= {self.config.dd_halt_threshold_pct:.2%}"
        # -15% to -20% → Hard halt (pause trading)
        elif rolling_dd_pct <= self.config.dd_hard_threshold_pct:
            mode = "hard_halt"
            risk_multiplier = 0.0
            pause_remaining = self.config.dd_pause_bars
            trigger_reason = f"hard_dd={rolling_dd_pct:.2%} <= {self.config.dd_hard_threshold_pct:.2%}"
        # -10% to -15% → Soft stop (halve risk)
        elif rolling_dd_pct <= self.config.dd_soft_threshold_pct:
            mode = "soft_stop"
            risk_multiplier = self.config.dd_risk_multiplier_soft  # 0.5x
            trigger_reason = f"soft_dd={rolling_dd_pct:.2%} <= {self.config.dd_soft_threshold_pct:.2%}"
        # Check if still in pause cooldown
        elif pause_remaining > 0:
            mode = "hard_halt"
            risk_multiplier = 0.0
            trigger_reason = f"cooldown_remaining={pause_remaining} bars"
        else:
            # Normal mode
            mode = "normal"
            risk_multiplier = 1.0

        self._drawdown_state = DrawdownState(
            daily_dd_pct=daily_dd_pct,
            rolling_dd_pct=rolling_dd_pct,
            mode=mode,
            risk_multiplier=risk_multiplier,
            pause_remaining=pause_remaining,
            trigger_reason=trigger_reason,
        )

        return self._drawdown_state

    def get_drawdown_state(self) -> DrawdownState:
        """Get current drawdown breaker state."""
        return self._drawdown_state

    def get_max_leverage(self, symbol: str) -> float:
        """
        Get maximum leverage for symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Max leverage (float)
        """
        return self.config.leverage_caps.get(symbol, self.config.max_leverage_default)

    def get_metrics(self) -> Dict[str, int]:
        """Get risk manager metrics."""
        return self._metrics.copy()

    def reset_metrics(self) -> None:
        """Reset metrics counters."""
        self._metrics = {
            "total_sized": 0,
            "total_rejected": 0,
            "rejected_min_size": 0,
            "rejected_leverage": 0,
            "rejected_portfolio_risk": 0,
            "rejected_drawdown": 0,
        }


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def create_risk_manager(
    per_trade_risk_pct: float = 0.02,
    max_portfolio_risk_pct: float = 0.04,
    max_leverage: float = 5.0,
    leverage_caps: Optional[Dict[str, float]] = None,
) -> RiskManager:
    """
    Create risk manager with common configuration.

    Args:
        per_trade_risk_pct: Per-trade risk percentage (default 2%)
        max_portfolio_risk_pct: Max portfolio risk (default 4%)
        max_leverage: Default max leverage (default 5x)
        leverage_caps: Per-symbol leverage overrides

    Returns:
        Configured RiskManager instance

    Example:
        >>> rm = create_risk_manager(
        ...     per_trade_risk_pct=0.015,
        ...     leverage_caps={"BTC/USD": 5.0, "ETH/USD": 3.0}
        ... )
    """
    config = RiskConfig(
        per_trade_risk_pct_max=per_trade_risk_pct,
        max_portfolio_risk_pct=max_portfolio_risk_pct,
        max_leverage_default=max_leverage,
        leverage_caps=leverage_caps or {},
    )
    return RiskManager(config=config)


# =============================================================================
# PUBLIC API
# =============================================================================

__all__ = [
    "RiskConfig",
    "PositionSize",
    "RiskCheckResult",
    "DrawdownState",
    "RiskManager",
    "create_risk_manager",
]


# =============================================================================
# SELF-CHECK
# =============================================================================

if __name__ == "__main__":
    """Self-check: Validate risk manager functionality"""

    print("=== Risk Manager Self-Check ===\n")

    # Create test signal
    test_signal = SignalInput(
        signal_id="test_001",
        symbol="BTC/USD",
        side="long",
        entry_price=Decimal("50000.00"),
        stop_loss=Decimal("49000.00"),  # 2% SL
        take_profit=Decimal("52000.00"),
        confidence=Decimal("0.75"),
    )

    # Test 1: Basic position sizing
    print("Test 1: Basic position sizing")
    rm = create_risk_manager(per_trade_risk_pct=0.02, max_leverage=5.0)
    equity = Decimal("10000.00")

    position = rm.size_position(test_signal, equity)
    print(f"  Signal: {test_signal.symbol} {test_signal.side} @ {test_signal.entry_price}")
    print(f"  SL distance: 2.0%")
    print(f"  Position size: {position.size:.8f} BTC")
    print(f"  Notional: ${position.notional_usd:.2f}")
    print(f"  Risk: ${position.expected_risk_usd:.2f} ({float(position.risk_pct):.2%})")
    print(f"  Leverage: {position.leverage}x")
    print(f"  Allowed: {position.allowed}")
    assert position.allowed, "Position should be allowed"
    assert float(position.risk_pct) <= 0.02, "Risk should be <=2%"
    print("  PASS\n")

    # Test 2: Portfolio risk check
    print("Test 2: Portfolio risk check")
    positions = [position]
    risk_check = rm.check_portfolio_risk(positions, equity)
    print(f"  Total risk: {float(risk_check.total_risk_pct):.2%}")
    print(f"  Positions: {risk_check.position_count}")
    print(f"  Passed: {risk_check.passed}")
    assert risk_check.passed, "Portfolio risk should pass"
    print("  PASS\n")

    # Test 3: Drawdown breaker (normal state)
    print("Test 3: Drawdown state (normal)")
    equity_curve = [Decimal("10000"), Decimal("10100"), Decimal("10200")]
    dd_state = rm.update_drawdown_state(equity_curve, current_bar=2)
    print(f"  Daily DD: {dd_state.daily_dd_pct:.2%}")
    print(f"  Rolling DD: {dd_state.rolling_dd_pct:.2%}")
    print(f"  Mode: {dd_state.mode}")
    print(f"  Risk multiplier: {dd_state.risk_multiplier}")
    assert dd_state.mode == "normal", "Should be in normal mode"
    assert dd_state.risk_multiplier == 1.0, "Risk multiplier should be 1.0"
    print("  PASS\n")

    # Test 4: Drawdown breaker (soft stop)
    print("Test 4: Drawdown breaker (soft stop)")
    equity_curve_soft = [Decimal("10000"), Decimal("9750")]  # -2.5% daily DD
    dd_state_soft = rm.update_drawdown_state(equity_curve_soft, current_bar=1)
    print(f"  Daily DD: {dd_state_soft.daily_dd_pct:.2%}")
    print(f"  Mode: {dd_state_soft.mode}")
    print(f"  Risk multiplier: {dd_state_soft.risk_multiplier}")
    assert dd_state_soft.mode == "soft_stop", "Should trigger soft stop"
    assert dd_state_soft.risk_multiplier == 0.5, "Risk multiplier should be 0.5"
    print("  PASS\n")

    # Test 5: Leverage caps
    print("Test 5: Per-symbol leverage caps")
    rm_capped = create_risk_manager(leverage_caps={"BTC/USD": 3.0, "ETH/USD": 2.0})
    btc_cap = rm_capped.get_max_leverage("BTC/USD")
    eth_cap = rm_capped.get_max_leverage("ETH/USD")
    default_cap = rm_capped.get_max_leverage("UNKNOWN/USD")
    print(f"  BTC/USD max leverage: {btc_cap}x")
    print(f"  ETH/USD max leverage: {eth_cap}x")
    print(f"  Default max leverage: {default_cap}x")
    assert btc_cap == 3.0, "BTC cap should be 3x"
    assert eth_cap == 2.0, "ETH cap should be 2x"
    assert default_cap == 5.0, "Default cap should be 5x"
    print("  PASS\n")

    # Test 6: Metrics tracking
    print("Test 6: Metrics tracking")
    metrics = rm.get_metrics()
    print(f"  Total sized: {metrics['total_sized']}")
    print(f"  Total rejected: {metrics['total_rejected']}")
    assert metrics["total_sized"] > 0, "Should have sized at least one position"
    print("  PASS\n")

    print("=== All Self-Checks PASSED ===")
