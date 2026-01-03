"""
RiskGuard - Unified Pre-Order Risk Validation

A single, deterministic, pure-logic module that validates all trades
BEFORE they reach the execution layer. No network calls.

This is the SINGLE CHOKE POINT for all order validation.

Config keys (with safe defaults):
- LIVE_TRADING_ENABLED: false (must explicitly enable)
- MAX_POSITION_SIZE_USD: 25 (safe for $100 capital)
- MAX_DAILY_LOSS_USD: 2 (conservative loss limit)
- MAX_TRADES_PER_DAY: 8 (prevents overtrading)
- RISK_PER_TRADE_PCT: 0.5 (0.5% = $0.50 on $100)
- EMERGENCY_STOP: false (true = halt all execution)
- COOLDOWN_SECONDS_AFTER_LOSS: 300 (5 min cooldown)

Usage:
    from protections.risk_guard import RiskGuard

    guard = RiskGuard()
    guard.log_active_limits()  # At startup

    # Before EVERY order:
    result = guard.check_order(
        position_size_usd=20.0,
        daily_pnl=-1.0,
        trades_today=3,
    )
    if not result.allowed:
        raise RiskViolation(result.reason)
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION (ENV VARS WITH SAFE DEFAULTS)
# =============================================================================

@dataclass(frozen=True)
class RiskConfig:
    """Immutable risk configuration loaded from environment."""

    # Master switch - must explicitly enable live trading
    live_trading_enabled: bool

    # Position limits
    max_position_size_usd: float

    # Loss limits
    max_daily_loss_usd: float
    risk_per_trade_pct: float

    # Trade frequency
    max_trades_per_day: int

    # Emergency controls
    emergency_stop: bool
    cooldown_seconds_after_loss: int

    @classmethod
    def from_env(cls) -> "RiskConfig":
        """
        Load configuration from environment variables with SAFE DEFAULTS.

        All defaults are conservative and designed for $100 capital safety.
        """
        return cls(
            live_trading_enabled=os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true",
            max_position_size_usd=float(os.getenv("MAX_POSITION_SIZE_USD", "25")),
            max_daily_loss_usd=float(os.getenv("MAX_DAILY_LOSS_USD", "2")),
            risk_per_trade_pct=float(os.getenv("RISK_PER_TRADE_PCT", "0.5")),
            max_trades_per_day=int(os.getenv("MAX_TRADES_PER_DAY", "8")),
            emergency_stop=os.getenv("EMERGENCY_STOP", "false").lower() == "true",
            cooldown_seconds_after_loss=int(os.getenv("COOLDOWN_SECONDS_AFTER_LOSS", "300")),
        )


# =============================================================================
# CHECK RESULT
# =============================================================================

@dataclass
class OrderCheckResult:
    """Result of order validation check."""
    allowed: bool
    reason: Optional[str] = None
    limit_hit: Optional[str] = None  # Which limit was hit


# =============================================================================
# RISK GUARD (SINGLE CHOKE POINT)
# =============================================================================

class RiskGuard:
    """
    Unified pre-order risk validation.

    Pure logic, deterministic, no network calls.
    Call this from a SINGLE choke point before placing any order.

    Features:
    - Emergency stop check (instant block)
    - Live trading enabled check
    - Max position size check
    - Max daily loss check
    - Max trades per day check
    - Cooldown after loss check
    - Startup logging (no secrets)

    Example:
        guard = RiskGuard()
        guard.log_active_limits()  # At startup

        # Before every order:
        result = guard.check_order(position_size_usd=20.0, daily_pnl=-1.0, trades_today=3)
        if not result.allowed:
            logger.error(f"Order blocked: {result.reason}")
            return
    """

    def __init__(self, config: Optional[RiskConfig] = None):
        """
        Initialize RiskGuard.

        Args:
            config: RiskConfig instance (default: load from env)
        """
        self.config = config or RiskConfig.from_env()
        self.logger = logging.getLogger(f"{__name__}.RiskGuard")

        # State tracking (in-memory, reset on restart)
        self._last_loss_time: float = 0.0
        self._connection_healthy: bool = True

        self.logger.info("RiskGuard initialized with safe defaults")

    # -------------------------------------------------------------------------
    # Main Check Method (SINGLE CHOKE POINT)
    # -------------------------------------------------------------------------

    def check_order(
        self,
        position_size_usd: float,
        daily_pnl: float = 0.0,
        trades_today: int = 0,
        is_exit: bool = False,
    ) -> OrderCheckResult:
        """
        Validate an order BEFORE it reaches execution.

        This is the SINGLE CHOKE POINT for all order validation.
        Call this before every order submission.

        Args:
            position_size_usd: Size of the order in USD
            daily_pnl: Today's P&L in USD (negative = loss)
            trades_today: Number of trades executed today
            is_exit: True if this is an exit/close order (less restrictive)

        Returns:
            OrderCheckResult with allowed/blocked status and reason
        """
        # 1. EMERGENCY STOP - highest priority, blocks everything except exits
        if self.config.emergency_stop:
            if is_exit:
                # Allow exits even during emergency
                self.logger.warning("Emergency stop active, allowing exit order")
                return OrderCheckResult(allowed=True)
            return OrderCheckResult(
                allowed=False,
                reason="EMERGENCY_STOP is active - all trading halted",
                limit_hit="emergency_stop",
            )

        # 2. CONNECTION HEALTH - block if unhealthy (but allow exits)
        if not self._connection_healthy:
            if is_exit:
                return OrderCheckResult(allowed=True)
            return OrderCheckResult(
                allowed=False,
                reason="Connection unhealthy - execution blocked",
                limit_hit="connection_health",
            )

        # 3. LIVE TRADING ENABLED - must be explicitly enabled
        if not self.config.live_trading_enabled:
            return OrderCheckResult(
                allowed=False,
                reason="LIVE_TRADING_ENABLED=false - enable to trade",
                limit_hit="live_trading_disabled",
            )

        # 4. COOLDOWN AFTER LOSS
        if self._last_loss_time > 0:
            elapsed = time.time() - self._last_loss_time
            if elapsed < self.config.cooldown_seconds_after_loss:
                remaining = int(self.config.cooldown_seconds_after_loss - elapsed)
                return OrderCheckResult(
                    allowed=False,
                    reason=f"Cooldown active: {remaining}s remaining after loss",
                    limit_hit="cooldown_after_loss",
                )

        # 5. MAX DAILY LOSS - check before allowing new entries
        if daily_pnl <= -self.config.max_daily_loss_usd:
            return OrderCheckResult(
                allowed=False,
                reason=f"Daily loss limit hit: ${abs(daily_pnl):.2f} >= ${self.config.max_daily_loss_usd:.2f}",
                limit_hit="max_daily_loss",
            )

        # 6. MAX TRADES PER DAY
        if trades_today >= self.config.max_trades_per_day:
            return OrderCheckResult(
                allowed=False,
                reason=f"Max trades/day hit: {trades_today} >= {self.config.max_trades_per_day}",
                limit_hit="max_trades_per_day",
            )

        # 7. MAX POSITION SIZE
        if position_size_usd > self.config.max_position_size_usd:
            return OrderCheckResult(
                allowed=False,
                reason=f"Position too large: ${position_size_usd:.2f} > ${self.config.max_position_size_usd:.2f}",
                limit_hit="max_position_size",
            )

        # All checks passed
        return OrderCheckResult(allowed=True)

    # -------------------------------------------------------------------------
    # State Updates
    # -------------------------------------------------------------------------

    def record_loss(self) -> None:
        """Record a loss to start cooldown timer."""
        self._last_loss_time = time.time()
        self.logger.info(
            f"Loss recorded, cooldown active for {self.config.cooldown_seconds_after_loss}s"
        )

    def clear_cooldown(self) -> None:
        """Clear cooldown timer (e.g., after successful trade)."""
        self._last_loss_time = 0.0

    def set_connection_health(self, healthy: bool) -> None:
        """
        Update connection health status.

        Call this when Redis/WS connection state changes.
        If unhealthy, execution is blocked (signals continue).
        """
        if self._connection_healthy != healthy:
            self._connection_healthy = healthy
            if healthy:
                self.logger.info("Connection healthy - execution enabled")
            else:
                self.logger.warning("Connection unhealthy - execution blocked")

    # -------------------------------------------------------------------------
    # Startup Logging
    # -------------------------------------------------------------------------

    def log_active_limits(self) -> None:
        """
        Log all active risk limits at startup.

        IMPORTANT: Logs ONLY config values, NO SECRETS.
        Call this once during engine initialization.
        """
        c = self.config

        # Single-line summary for quick visibility
        self.logger.info(
            "Risk rails active: max_pos=$%.0f, max_daily_loss=$%.0f, "
            "max_trades=%d, risk_per_trade=%.1f%%",
            c.max_position_size_usd,
            c.max_daily_loss_usd,
            c.max_trades_per_day,
            c.risk_per_trade_pct,
        )

        # Detailed breakdown
        self.logger.info("=" * 60)
        self.logger.info("RISK GUARD - ACTIVE LIMITS")
        self.logger.info("=" * 60)
        self.logger.info(f"LIVE_TRADING_ENABLED:       {c.live_trading_enabled}")
        self.logger.info(f"EMERGENCY_STOP:             {c.emergency_stop}")
        self.logger.info("-" * 40)
        self.logger.info(f"MAX_POSITION_SIZE_USD:      ${c.max_position_size_usd:.2f}")
        self.logger.info(f"MAX_DAILY_LOSS_USD:         ${c.max_daily_loss_usd:.2f}")
        self.logger.info(f"RISK_PER_TRADE_PCT:         {c.risk_per_trade_pct}%")
        self.logger.info(f"MAX_TRADES_PER_DAY:         {c.max_trades_per_day}")
        self.logger.info(f"COOLDOWN_SECONDS_AFTER_LOSS: {c.cooldown_seconds_after_loss}s")
        self.logger.info("=" * 60)

        if not c.live_trading_enabled:
            self.logger.warning(
                "LIVE_TRADING_ENABLED=false - set to 'true' to enable execution"
            )

        if c.emergency_stop:
            self.logger.critical("EMERGENCY_STOP=true - ALL TRADING HALTED")

    # -------------------------------------------------------------------------
    # Quick Checks (for use in tight loops)
    # -------------------------------------------------------------------------

    def is_emergency_stop(self) -> bool:
        """Quick check if emergency stop is active."""
        return self.config.emergency_stop

    def is_trading_enabled(self) -> bool:
        """Quick check if live trading is enabled."""
        return self.config.live_trading_enabled and not self.config.emergency_stop

    def get_max_position_size(self) -> float:
        """Get max position size in USD."""
        return self.config.max_position_size_usd


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

_risk_guard_instance: Optional[RiskGuard] = None


def get_risk_guard() -> RiskGuard:
    """
    Get the singleton RiskGuard instance.

    Use this to get a consistent RiskGuard across the application.
    """
    global _risk_guard_instance
    if _risk_guard_instance is None:
        _risk_guard_instance = RiskGuard()
    return _risk_guard_instance


# =============================================================================
# SELF-TEST
# =============================================================================

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    print("\n" + "=" * 60)
    print("RISK GUARD - SELF TEST")
    print("=" * 60)

    # Create guard with defaults
    guard = RiskGuard()

    print("\n1. Logging active limits:")
    guard.log_active_limits()

    print("\n2. Testing order checks:")

    # Test: Live trading disabled (default)
    result = guard.check_order(position_size_usd=20.0)
    print(f"   Live trading disabled: allowed={result.allowed}, reason={result.reason}")
    assert result.allowed is False
    assert result.limit_hit == "live_trading_disabled"

    # Override config for testing
    test_config = RiskConfig(
        live_trading_enabled=True,
        max_position_size_usd=25.0,
        max_daily_loss_usd=2.0,
        risk_per_trade_pct=0.5,
        max_trades_per_day=8,
        emergency_stop=False,
        cooldown_seconds_after_loss=300,
    )
    guard = RiskGuard(config=test_config)

    # Test: Valid order
    result = guard.check_order(position_size_usd=20.0, daily_pnl=0.0, trades_today=3)
    print(f"   Valid order: allowed={result.allowed}")
    assert result.allowed is True

    # Test: Oversized position
    result = guard.check_order(position_size_usd=30.0)
    print(f"   Oversized: allowed={result.allowed}, limit={result.limit_hit}")
    assert result.allowed is False
    assert result.limit_hit == "max_position_size"

    # Test: Max daily loss
    result = guard.check_order(position_size_usd=10.0, daily_pnl=-2.5)
    print(f"   Daily loss exceeded: allowed={result.allowed}, limit={result.limit_hit}")
    assert result.allowed is False
    assert result.limit_hit == "max_daily_loss"

    # Test: Max trades per day
    result = guard.check_order(position_size_usd=10.0, trades_today=8)
    print(f"   Max trades hit: allowed={result.allowed}, limit={result.limit_hit}")
    assert result.allowed is False
    assert result.limit_hit == "max_trades_per_day"

    # Test: Cooldown after loss
    guard.record_loss()
    result = guard.check_order(position_size_usd=10.0)
    print(f"   Cooldown active: allowed={result.allowed}, limit={result.limit_hit}")
    assert result.allowed is False
    assert result.limit_hit == "cooldown_after_loss"
    guard.clear_cooldown()

    # Test: Emergency stop
    emergency_config = RiskConfig(
        live_trading_enabled=True,
        max_position_size_usd=25.0,
        max_daily_loss_usd=2.0,
        risk_per_trade_pct=0.5,
        max_trades_per_day=8,
        emergency_stop=True,
        cooldown_seconds_after_loss=300,
    )
    guard = RiskGuard(config=emergency_config)

    result = guard.check_order(position_size_usd=10.0)
    print(f"   Emergency stop: allowed={result.allowed}, limit={result.limit_hit}")
    assert result.allowed is False
    assert result.limit_hit == "emergency_stop"

    # Test: Exit allowed during emergency
    result = guard.check_order(position_size_usd=10.0, is_exit=True)
    print(f"   Exit during emergency: allowed={result.allowed}")
    assert result.allowed is True

    # Test: Connection health
    guard = RiskGuard(config=test_config)
    guard.set_connection_health(False)
    result = guard.check_order(position_size_usd=10.0)
    print(f"   Unhealthy connection: allowed={result.allowed}, limit={result.limit_hit}")
    assert result.allowed is False
    assert result.limit_hit == "connection_health"

    print("\n" + "=" * 60)
    print("[PASS] ALL RISK GUARD TESTS PASSED")
    print("=" * 60)

    sys.exit(0)
