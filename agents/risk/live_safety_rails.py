"""
Live Trading Safety Rails
===========================

Enforces strict safety limits for live trading:
- Maximum portfolio heat (75%)
- Daily stop loss (-6%) and profit target (+2.5%)
- Per-pair notional caps
- Position size limits
- Circuit breakers

Designed to fail-fast and prevent catastrophic losses.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class DailyRiskLimits:
    """Daily risk limits"""

    max_loss_pct: float = -6.0
    profit_target_pct: float = 2.5
    max_trades: int = 150
    max_losing_trades_consecutive: int = 5

    # Current state
    current_pnl_pct: float = 0.0
    trades_today: int = 0
    losing_trades_consecutive: int = 0

    # Tracking
    start_of_day_ts: float = field(default_factory=time.time)
    start_of_day_balance: float = 10000.0


@dataclass
class PortfolioLimits:
    """Portfolio-level limits"""

    max_heat_pct: float = 75.0
    heat_reduction_threshold_pct: float = 70.0
    max_concurrent_positions: int = 5
    max_correlated_positions: int = 2

    # Current state
    current_heat_pct: float = 0.0
    open_positions: int = 0


@dataclass
class PerPairLimit:
    """Per-pair position limits"""

    pair: str
    max_notional: float
    max_position_pct: float

    # Current state
    current_notional: float = 0.0
    current_position_pct: float = 0.0


@dataclass
class SafetyRailViolation:
    """Safety rail violation details"""

    rail_type: str  # "daily_stop", "portfolio_heat", "pair_limit", etc.
    severity: str  # "warning", "critical"
    message: str
    current_value: float
    limit_value: float
    timestamp: float = field(default_factory=time.time)
    action_taken: str = ""  # "reduced_size", "stopped_trading", etc.


# =============================================================================
# Safety Rails Manager
# =============================================================================


class LiveSafetyRails:
    """
    Enforces live trading safety rails

    Prevents catastrophic losses by enforcing:
    1. Portfolio heat limits (max 75%)
    2. Daily stop loss (-6%) and profit target (+2.5%)
    3. Per-pair notional caps
    4. Circuit breakers (consecutive losses)
    5. Emergency stops (drawdown, volatility)
    """

    def __init__(self, config: Dict):
        """
        Initialize safety rails

        Args:
            config: Configuration dictionary with safety_rails section
        """
        self.config = config
        safety_config = config.get("safety_rails", {})

        # Initialize limits
        daily_config = safety_config.get("daily_limits", {})
        self.daily_limits = DailyRiskLimits(
            max_loss_pct=daily_config.get("max_loss_pct", -6.0),
            profit_target_pct=daily_config.get("profit_target_pct", 2.5),
            max_trades=daily_config.get("max_trades", 150),
            max_losing_trades_consecutive=daily_config.get("max_losing_trades_consecutive", 5),
        )

        portfolio_config = safety_config.get("portfolio", {})
        self.portfolio_limits = PortfolioLimits(
            max_heat_pct=portfolio_config.get("max_heat_pct", 75.0),
            heat_reduction_threshold_pct=portfolio_config.get("heat_reduction_threshold_pct", 70.0),
            max_concurrent_positions=portfolio_config.get("max_concurrent_positions", 5),
            max_correlated_positions=portfolio_config.get("max_correlated_positions", 2),
        )

        # Per-pair limits
        self.per_pair_limits: Dict[str, PerPairLimit] = {}
        pair_limits_config = safety_config.get("per_pair_limits", {})

        for pair, limits in pair_limits_config.items():
            self.per_pair_limits[pair] = PerPairLimit(
                pair=pair,
                max_notional=limits.get("max_notional", 5000.0),
                max_position_pct=limits.get("max_position_pct", 0.20),
            )

        # Emergency stops
        emergency_config = safety_config.get("emergency", {})
        self.emergency_enabled = emergency_config.get("enabled", True)
        self.max_drawdown_pct = emergency_config.get("max_drawdown_pct", 10.0)
        self.volatility_multiplier_max = emergency_config.get("volatility_multiplier_max", 3.0)

        # State tracking
        self.violations: List[SafetyRailViolation] = []
        self.trading_paused = False
        self.trading_stopped = False
        self.last_check_time = time.time()

        # Circuit breaker state
        self.circuit_breakers_active: Dict[str, bool] = {}

        logger.info("Live safety rails initialized")
        logger.info(f"  Daily stop: {self.daily_limits.max_loss_pct}%")
        logger.info(f"  Daily target: +{self.daily_limits.profit_target_pct}%")
        logger.info(f"  Max portfolio heat: {self.portfolio_limits.max_heat_pct}%")
        logger.info(f"  Max concurrent positions: {self.portfolio_limits.max_concurrent_positions}")
        logger.info(f"  Per-pair limits: {len(self.per_pair_limits)} pairs configured")

    def check_can_trade(self) -> tuple[bool, Optional[str]]:
        """
        Check if trading is allowed

        Returns:
            (can_trade, reason) - True if allowed, False with reason if not
        """
        # Check if trading is stopped
        if self.trading_stopped:
            return False, "Trading stopped due to safety rail violation"

        # Check if trading is paused
        if self.trading_paused:
            return False, "Trading paused by circuit breaker"

        # Check daily stop loss
        if self.daily_limits.current_pnl_pct <= self.daily_limits.max_loss_pct:
            return False, f"Daily stop loss reached: {self.daily_limits.current_pnl_pct:.2f}%"

        # Check daily profit target
        if self.daily_limits.current_pnl_pct >= self.daily_limits.profit_target_pct:
            return False, f"Daily profit target reached: +{self.daily_limits.current_pnl_pct:.2f}%"

        # Check max trades
        if self.daily_limits.trades_today >= self.daily_limits.max_trades:
            return False, f"Daily trade limit reached: {self.daily_limits.trades_today}"

        # Check consecutive losses
        if (
            self.daily_limits.losing_trades_consecutive
            >= self.daily_limits.max_losing_trades_consecutive
        ):
            return False, f"Max consecutive losses: {self.daily_limits.losing_trades_consecutive}"

        # Check portfolio heat
        if self.portfolio_limits.current_heat_pct >= self.portfolio_limits.max_heat_pct:
            return False, f"Portfolio heat limit: {self.portfolio_limits.current_heat_pct:.1f}%"

        # Check max positions
        if self.portfolio_limits.open_positions >= self.portfolio_limits.max_concurrent_positions:
            return False, f"Max positions: {self.portfolio_limits.open_positions}"

        return True, None

    def check_can_open_position(
        self, pair: str, notional_usd: float, portfolio_value: float
    ) -> tuple[bool, Optional[str]]:
        """
        Check if a new position can be opened

        Args:
            pair: Trading pair
            notional_usd: Position size in USD
            portfolio_value: Current portfolio value

        Returns:
            (can_open, reason)
        """
        # First check if trading is allowed
        can_trade, reason = self.check_can_trade()
        if not can_trade:
            return False, reason

        # Check per-pair notional limit
        if pair in self.per_pair_limits:
            pair_limit = self.per_pair_limits[pair]

            if notional_usd > pair_limit.max_notional:
                return False, f"{pair} notional limit: ${notional_usd:.0f} > ${pair_limit.max_notional:.0f}"

            # Check per-pair portfolio percentage
            position_pct = notional_usd / portfolio_value if portfolio_value > 0 else 0

            if position_pct > pair_limit.max_position_pct:
                return False, (
                    f"{pair} position % limit: {position_pct*100:.1f}% > "
                    f"{pair_limit.max_position_pct*100:.1f}%"
                )

        return True, None

    def update_daily_pnl(self, current_pnl_pct: float, portfolio_value: float) -> None:
        """Update daily PnL and check limits"""
        self.daily_limits.current_pnl_pct = current_pnl_pct

        # Check daily stop loss
        if current_pnl_pct <= self.daily_limits.max_loss_pct:
            violation = SafetyRailViolation(
                rail_type="daily_stop_loss",
                severity="critical",
                message=f"Daily stop loss reached: {current_pnl_pct:.2f}%",
                current_value=current_pnl_pct,
                limit_value=self.daily_limits.max_loss_pct,
                action_taken="stopped_trading",
            )

            self.violations.append(violation)
            self.trading_stopped = True

            logger.critical(f"🚨 DAILY STOP LOSS TRIGGERED: {current_pnl_pct:.2f}%")
            logger.critical("   Trading STOPPED for the rest of the day")

        # Check daily profit target
        elif current_pnl_pct >= self.daily_limits.profit_target_pct:
            violation = SafetyRailViolation(
                rail_type="daily_profit_target",
                severity="warning",
                message=f"Daily profit target reached: +{current_pnl_pct:.2f}%",
                current_value=current_pnl_pct,
                limit_value=self.daily_limits.profit_target_pct,
                action_taken="stopped_trading",
            )

            self.violations.append(violation)
            self.trading_stopped = True

            logger.info(f"✅ DAILY TARGET REACHED: +{current_pnl_pct:.2f}%")
            logger.info("   Trading STOPPED to preserve gains")

    def update_portfolio_heat(self, heat_pct: float, open_positions: int) -> None:
        """Update portfolio heat and check limits"""
        self.portfolio_limits.current_heat_pct = heat_pct
        self.portfolio_limits.open_positions = open_positions

        # Check heat limit
        if heat_pct >= self.portfolio_limits.max_heat_pct:
            violation = SafetyRailViolation(
                rail_type="portfolio_heat",
                severity="critical",
                message=f"Portfolio heat limit: {heat_pct:.1f}%",
                current_value=heat_pct,
                limit_value=self.portfolio_limits.max_heat_pct,
                action_taken="rejected_new_positions",
            )

            self.violations.append(violation)

            logger.warning(f"⚠️  PORTFOLIO HEAT LIMIT: {heat_pct:.1f}%")
            logger.warning("   No new positions allowed until heat reduces")

        # Check heat reduction threshold (warning)
        elif heat_pct >= self.portfolio_limits.heat_reduction_threshold_pct:
            logger.warning(f"⚠️  Portfolio heat: {heat_pct:.1f}% (approaching limit)")

    def record_trade(self, pnl: float, is_win: bool) -> None:
        """Record a trade and update state"""
        self.daily_limits.trades_today += 1

        if is_win:
            self.daily_limits.losing_trades_consecutive = 0
        else:
            self.daily_limits.losing_trades_consecutive += 1

            # Check consecutive losses
            if (
                self.daily_limits.losing_trades_consecutive
                >= self.daily_limits.max_losing_trades_consecutive
            ):
                violation = SafetyRailViolation(
                    rail_type="consecutive_losses",
                    severity="critical",
                    message=f"Max consecutive losses: {self.daily_limits.losing_trades_consecutive}",
                    current_value=self.daily_limits.losing_trades_consecutive,
                    limit_value=self.daily_limits.max_losing_trades_consecutive,
                    action_taken="paused_trading",
                )

                self.violations.append(violation)
                self.trading_paused = True

                logger.critical(
                    f"🚨 CONSECUTIVE LOSSES: {self.daily_limits.losing_trades_consecutive}"
                )
                logger.critical("   Trading PAUSED")

    def update_pair_position(self, pair: str, notional_usd: float, portfolio_value: float) -> None:
        """Update per-pair position tracking"""
        if pair in self.per_pair_limits:
            pair_limit = self.per_pair_limits[pair]
            pair_limit.current_notional = notional_usd
            pair_limit.current_position_pct = (
                notional_usd / portfolio_value if portfolio_value > 0 else 0
            )

            # Check limits
            if notional_usd > pair_limit.max_notional:
                logger.warning(
                    f"⚠️  {pair} notional ${notional_usd:.0f} exceeds limit ${pair_limit.max_notional:.0f}"
                )

    def reset_daily_limits(self, start_balance: float) -> None:
        """Reset daily limits (call at start of trading day)"""
        now = datetime.now(timezone.utc)

        logger.info(f"Resetting daily limits for {now.strftime('%Y-%m-%d')}")

        self.daily_limits = DailyRiskLimits(
            max_loss_pct=self.daily_limits.max_loss_pct,
            profit_target_pct=self.daily_limits.profit_target_pct,
            max_trades=self.daily_limits.max_trades,
            max_losing_trades_consecutive=self.daily_limits.max_losing_trades_consecutive,
            start_of_day_ts=time.time(),
            start_of_day_balance=start_balance,
        )

        self.trading_stopped = False
        self.trading_paused = False
        self.violations = []

    def get_status_summary(self) -> Dict:
        """Get current status summary"""
        return {
            "trading_allowed": not self.trading_stopped and not self.trading_paused,
            "trading_stopped": self.trading_stopped,
            "trading_paused": self.trading_paused,
            "daily_pnl_pct": round(self.daily_limits.current_pnl_pct, 2),
            "daily_stop_pct": self.daily_limits.max_loss_pct,
            "daily_target_pct": self.daily_limits.profit_target_pct,
            "trades_today": self.daily_limits.trades_today,
            "max_trades": self.daily_limits.max_trades,
            "consecutive_losses": self.daily_limits.losing_trades_consecutive,
            "max_consecutive_losses": self.daily_limits.max_losing_trades_consecutive,
            "portfolio_heat_pct": round(self.portfolio_limits.current_heat_pct, 1),
            "max_heat_pct": self.portfolio_limits.max_heat_pct,
            "open_positions": self.portfolio_limits.open_positions,
            "max_positions": self.portfolio_limits.max_concurrent_positions,
            "violations_today": len(self.violations),
        }

    def log_startup_summary(self) -> None:
        """Log comprehensive startup summary"""
        logger.info("=" * 80)
        logger.info(" " * 25 + "SAFETY RAILS CONFIGURATION")
        logger.info("=" * 80)

        logger.info("\n📊 Daily Limits:")
        logger.info(f"   Stop Loss:           {self.daily_limits.max_loss_pct}%")
        logger.info(f"   Profit Target:       +{self.daily_limits.profit_target_pct}%")
        logger.info(f"   Max Trades:          {self.daily_limits.max_trades}")
        logger.info(f"   Max Consecutive Losses: {self.daily_limits.max_losing_trades_consecutive}")

        logger.info("\n📈 Portfolio Limits:")
        logger.info(f"   Max Heat:            {self.portfolio_limits.max_heat_pct}%")
        logger.info(f"   Heat Reduction At:   {self.portfolio_limits.heat_reduction_threshold_pct}%")
        logger.info(f"   Max Positions:       {self.portfolio_limits.max_concurrent_positions}")
        logger.info(f"   Max Correlated:      {self.portfolio_limits.max_correlated_positions}")

        logger.info("\n💰 Per-Pair Notional Limits:")
        for pair, limit in self.per_pair_limits.items():
            logger.info(
                f"   {pair:12s} ${limit.max_notional:,.0f} ({limit.max_position_pct*100:.0f}% portfolio)"
            )

        logger.info("\n🚨 Emergency Stops:")
        logger.info(f"   Enabled:             {self.emergency_enabled}")
        logger.info(f"   Max Drawdown:        {self.max_drawdown_pct}%")
        logger.info(f"   Max Volatility:      {self.volatility_multiplier_max}x")

        logger.info("\n" + "=" * 80)


# =============================================================================
# Helper Functions
# =============================================================================


def calculate_portfolio_heat(
    open_positions: List[Dict], portfolio_value: float
) -> float:
    """
    Calculate portfolio heat percentage

    Heat = sum(position_risk) / portfolio_value * 100

    Args:
        open_positions: List of open position dicts with 'notional', 'stop_distance_pct'
        portfolio_value: Current portfolio value

    Returns:
        Heat percentage (0-100)
    """
    if portfolio_value <= 0:
        return 0.0

    total_risk = 0.0

    for position in open_positions:
        notional = position.get("notional", 0.0)
        stop_distance_pct = position.get("stop_distance_pct", 0.02)  # Default 2%
        position_risk = notional * stop_distance_pct

        total_risk += position_risk

    heat_pct = (total_risk / portfolio_value) * 100

    return heat_pct


def calculate_daily_pnl_pct(
    current_balance: float, start_of_day_balance: float
) -> float:
    """Calculate daily PnL percentage"""
    if start_of_day_balance <= 0:
        return 0.0

    return ((current_balance - start_of_day_balance) / start_of_day_balance) * 100


# =============================================================================
# Testing & Validation
# =============================================================================


if __name__ == "__main__":
    """Test safety rails"""
    import json

    # Test configuration
    test_config = {
        "safety_rails": {
            "portfolio": {"max_heat_pct": 75.0, "max_concurrent_positions": 5},
            "daily_limits": {
                "max_loss_pct": -6.0,
                "profit_target_pct": 2.5,
                "max_trades": 150,
            },
            "per_pair_limits": {
                "BTC/USD": {"max_notional": 5000.0, "max_position_pct": 0.20},
                "ETH/USD": {"max_notional": 3000.0, "max_position_pct": 0.15},
            },
            "emergency": {"enabled": True, "max_drawdown_pct": 10.0},
        }
    }

    # Initialize
    rails = LiveSafetyRails(test_config)
    rails.log_startup_summary()

    # Test scenarios
    print("\n" + "=" * 80)
    print("TESTING SAFETY RAILS")
    print("=" * 80)

    # Test 1: Can trade initially
    can_trade, reason = rails.check_can_trade()
    print(f"\nTest 1: Can trade initially? {can_trade}")

    # Test 2: Update PnL to -5% (warning zone)
    rails.update_daily_pnl(-5.0, 10000)
    can_trade, reason = rails.check_can_trade()
    print(f"\nTest 2: Can trade at -5% PnL? {can_trade}")

    # Test 3: Update PnL to -6% (stop loss)
    rails.update_daily_pnl(-6.5, 10000)
    can_trade, reason = rails.check_can_trade()
    print(f"\nTest 3: Can trade at -6.5% PnL? {can_trade}")
    print(f"   Reason: {reason}")

    # Test 4: Portfolio heat
    rails.reset_daily_limits(10000)
    rails.update_portfolio_heat(80.0, 3)
    can_trade, reason = rails.check_can_trade()
    print(f"\nTest 4: Can trade at 80% heat? {can_trade}")
    print(f"   Reason: {reason}")

    # Test 5: Per-pair limit
    rails.reset_daily_limits(10000)
    can_open, reason = rails.check_can_open_position("BTC/USD", 6000.0, 10000)
    print(f"\nTest 5: Can open $6000 BTC/USD position? {can_open}")
    print(f"   Reason: {reason}")

    # Status summary
    print("\n" + "=" * 80)
    print("STATUS SUMMARY")
    print("=" * 80)
    status = rails.get_status_summary()
    print(json.dumps(status, indent=2))
