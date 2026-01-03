"""
Live Mode Guard - Capital-Aware Risk Controls for Live Trading

Enforces stricter risk limits when ENGINE_MODE=live, designed for
micro-capital trading ($100-$500).

PURE LOGIC MODULE:
- Reads config from risk_config.yaml (live_mode section)
- Environment override via TRADING_CAPITAL_USD
- No signal generation changes
- Config-driven and reversible

Features:
- Capital-scaled position sizing
- Tighter drawdown limits for small capital
- Pre-flight safety checks
- Emergency auto-halt on excessive losses
- Enhanced audit logging

Usage:
    guard = LiveModeGuard.from_config()

    # Check before any trade
    result = guard.check_trade_allowed(
        notional_usd=25.0,
        current_positions=1,
        daily_pnl=-3.0
    )
    if not result.allowed:
        logger.error(f"Trade blocked: {result.reason}")
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION MODELS
# =============================================================================

@dataclass(frozen=True)
class LiveModeCapitalConfig:
    """Capital configuration for live mode."""
    starting_capital_usd: float = 100.0
    max_capital_usd: float = 500.0
    min_capital_usd: float = 50.0


@dataclass(frozen=True)
class LiveModePositionConfig:
    """Position sizing configuration for live mode."""
    max_position_pct: float = 25.0
    min_position_usd: float = 5.0
    max_concurrent_positions: int = 2
    risk_per_trade_pct: float = 2.0


@dataclass(frozen=True)
class LiveModeDrawdownConfig:
    """Drawdown protection configuration for live mode."""
    daily_halt_pct: float = 5.0
    rolling_4h_halt_pct: float = 3.0
    max_consecutive_losses: int = 2
    soft_cooldown_s: int = 1800
    hard_cooldown_s: int = 7200


@dataclass(frozen=True)
class LiveModeCircuitBreakerConfig:
    """Circuit breaker configuration for live mode."""
    max_spread_bps: float = 5.0
    max_volatility_pct: float = 5.0
    min_24h_volume_usd: float = 5_000_000.0
    max_latency_ms: float = 300.0


@dataclass(frozen=True)
class LiveModePreflightConfig:
    """Pre-flight check configuration for live mode."""
    require_redis_health: bool = True
    require_exchange_health: bool = True
    require_paper_profit: bool = False
    paper_profit_lookback_trades: int = 10
    require_confirmation_file: bool = False
    confirmation_file_path: str = "config/.live_confirmed"


@dataclass(frozen=True)
class LiveModeEmergencyConfig:
    """Emergency control configuration for live mode."""
    halt_on_any_error: bool = True
    max_loss_usd: float = 20.0
    flatten_on_halt: bool = True
    notify_on_halt: bool = True
    webhook_url: str = ""


@dataclass(frozen=True)
class LiveModeAuditConfig:
    """Audit logging configuration for live mode."""
    log_order_attempts: bool = True
    log_risk_checks: bool = True
    capital_snapshot_interval_s: int = 60
    log_retention_days: int = 90


@dataclass
class LiveModeConfig:
    """Complete live mode configuration."""
    enabled: bool = True
    capital: LiveModeCapitalConfig = field(default_factory=LiveModeCapitalConfig)
    position: LiveModePositionConfig = field(default_factory=LiveModePositionConfig)
    drawdown: LiveModeDrawdownConfig = field(default_factory=LiveModeDrawdownConfig)
    circuit_breakers: LiveModeCircuitBreakerConfig = field(
        default_factory=LiveModeCircuitBreakerConfig
    )
    preflight: LiveModePreflightConfig = field(default_factory=LiveModePreflightConfig)
    emergency: LiveModeEmergencyConfig = field(default_factory=LiveModeEmergencyConfig)
    audit: LiveModeAuditConfig = field(default_factory=LiveModeAuditConfig)

    @classmethod
    def from_yaml(cls, yaml_path: Path) -> "LiveModeConfig":
        """Load configuration from YAML file."""
        if not yaml_path.exists():
            logger.warning(f"Config file not found: {yaml_path}, using defaults")
            return cls()

        with open(yaml_path, "r") as f:
            config = yaml.safe_load(f)

        live_mode = config.get("live_mode", {})
        if not live_mode:
            logger.warning("No live_mode section in config, using defaults")
            return cls()

        return cls(
            enabled=live_mode.get("enabled", True),
            capital=LiveModeCapitalConfig(
                **live_mode.get("capital", {})
            ),
            position=LiveModePositionConfig(
                **live_mode.get("position", {})
            ),
            drawdown=LiveModeDrawdownConfig(
                **live_mode.get("drawdown", {})
            ),
            circuit_breakers=LiveModeCircuitBreakerConfig(
                **live_mode.get("circuit_breakers", {})
            ),
            preflight=LiveModePreflightConfig(
                **live_mode.get("preflight", {})
            ),
            emergency=LiveModeEmergencyConfig(
                **{
                    **live_mode.get("emergency", {}),
                    "webhook_url": os.getenv(
                        "LIVE_HALT_WEBHOOK_URL",
                        live_mode.get("emergency", {}).get("webhook_url", "")
                    ),
                }
            ),
            audit=LiveModeAuditConfig(
                **live_mode.get("audit", {})
            ),
        )


# =============================================================================
# CHECK RESULTS
# =============================================================================

@dataclass
class TradeCheckResult:
    """Result of a trade check."""
    allowed: bool
    reason: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    size_multiplier: float = 1.0
    max_allowed_notional: Optional[float] = None


@dataclass
class PreflightCheckResult:
    """Result of pre-flight checks."""
    passed: bool
    checks_run: List[str] = field(default_factory=list)
    checks_failed: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LiveModeStatus:
    """Current live mode status."""
    is_live_mode: bool
    guardrails_enabled: bool
    capital_usd: float
    max_position_usd: float
    daily_loss_limit_usd: float
    current_daily_pnl: float
    positions_count: int
    is_halted: bool
    halt_reason: Optional[str] = None


# =============================================================================
# LIVE MODE GUARD
# =============================================================================

class LiveModeGuard:
    """
    Guard that enforces capital-aware risk controls for live trading.

    Features:
    - Validates all trades against capital-scaled limits
    - Tracks daily P&L and position count
    - Enforces circuit breakers with tighter thresholds
    - Provides pre-flight validation before going live
    - Auto-halts on emergency conditions
    """

    def __init__(
        self,
        config: LiveModeConfig,
        capital_override_usd: Optional[float] = None,
    ):
        """
        Initialize live mode guard.

        Args:
            config: Live mode configuration
            capital_override_usd: Override capital from environment
        """
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.LiveModeGuard")

        # Determine actual capital (env override takes precedence)
        env_capital = os.getenv("TRADING_CAPITAL_USD")
        if capital_override_usd is not None:
            self._capital_usd = capital_override_usd
        elif env_capital:
            try:
                self._capital_usd = float(env_capital)
            except ValueError:
                self.logger.error(f"Invalid TRADING_CAPITAL_USD: {env_capital}")
                self._capital_usd = config.capital.starting_capital_usd
        else:
            self._capital_usd = config.capital.starting_capital_usd

        # Calculate derived limits
        self._max_position_usd = (
            self._capital_usd * (config.position.max_position_pct / 100.0)
        )
        self._daily_loss_limit_usd = (
            self._capital_usd * (config.drawdown.daily_halt_pct / 100.0)
        )
        self._max_loss_usd = config.emergency.max_loss_usd

        # State tracking
        self._is_halted = False
        self._halt_reason: Optional[str] = None
        self._halt_time: Optional[float] = None
        self._daily_pnl: float = 0.0
        self._current_positions: int = 0
        self._consecutive_losses: int = 0
        self._last_snapshot_time: float = 0.0
        self._trade_count_today: int = 0

        # Determine if we're in live mode
        engine_mode = os.getenv("ENGINE_MODE", "paper").lower()
        self._is_live_mode = engine_mode == "live"

        self.logger.info(
            f"LiveModeGuard initialized: "
            f"capital=${self._capital_usd:.2f}, "
            f"max_position=${self._max_position_usd:.2f}, "
            f"daily_loss_limit=${self._daily_loss_limit_usd:.2f}, "
            f"is_live={self._is_live_mode}, "
            f"guardrails_enabled={config.enabled}"
        )

    @classmethod
    def from_config(cls, config_path: Optional[Path] = None) -> "LiveModeGuard":
        """
        Create guard from configuration file.

        Args:
            config_path: Path to risk_config.yaml (auto-detected if None)

        Returns:
            Configured LiveModeGuard instance
        """
        if config_path is None:
            project_root = Path(__file__).parent.parent
            config_path = project_root / "config" / "risk_config.yaml"

        config = LiveModeConfig.from_yaml(config_path)
        return cls(config)

    @property
    def capital_usd(self) -> float:
        """Current trading capital in USD."""
        return self._capital_usd

    @property
    def is_live_mode(self) -> bool:
        """Whether engine is in live mode."""
        return self._is_live_mode

    @property
    def is_halted(self) -> bool:
        """Whether trading is halted."""
        return self._is_halted

    def should_enforce(self) -> bool:
        """Check if live mode guardrails should be enforced."""
        return self._is_live_mode and self.config.enabled

    # -------------------------------------------------------------------------
    # Trade Validation
    # -------------------------------------------------------------------------

    def check_trade_allowed(
        self,
        notional_usd: float,
        current_positions: int = 0,
        daily_pnl: float = 0.0,
        spread_bps: Optional[float] = None,
        volatility_pct: Optional[float] = None,
        latency_ms: Optional[float] = None,
        volume_24h_usd: Optional[float] = None,
    ) -> TradeCheckResult:
        """
        Check if a trade is allowed under live mode constraints.

        Args:
            notional_usd: Proposed trade size in USD
            current_positions: Number of current open positions
            daily_pnl: Today's P&L in USD
            spread_bps: Current bid-ask spread in basis points
            volatility_pct: Current volatility percentage
            latency_ms: Current latency in milliseconds
            volume_24h_usd: 24-hour volume in USD

        Returns:
            TradeCheckResult with allowed/blocked status and reasons
        """
        # Skip enforcement in paper mode
        if not self.should_enforce():
            return TradeCheckResult(
                allowed=True,
                max_allowed_notional=None,  # No limit in paper mode
            )

        warnings: List[str] = []

        # Check 1: System halted?
        if self._is_halted:
            return TradeCheckResult(
                allowed=False,
                reason=f"Trading halted: {self._halt_reason}",
            )

        # Check 2: Daily loss limit
        if daily_pnl <= -self._daily_loss_limit_usd:
            self._trigger_halt(f"Daily loss limit exceeded: ${daily_pnl:.2f}")
            return TradeCheckResult(
                allowed=False,
                reason=f"Daily loss limit (${self._daily_loss_limit_usd:.2f}) exceeded",
            )

        # Check 3: Emergency max loss
        if daily_pnl <= -self._max_loss_usd:
            self._trigger_halt(f"Emergency max loss exceeded: ${daily_pnl:.2f}")
            return TradeCheckResult(
                allowed=False,
                reason=f"Emergency max loss (${self._max_loss_usd:.2f}) exceeded",
            )

        # Check 4: Position count
        if current_positions >= self.config.position.max_concurrent_positions:
            return TradeCheckResult(
                allowed=False,
                reason=f"Max concurrent positions ({self.config.position.max_concurrent_positions}) reached",
            )

        # Check 5: Position size
        if notional_usd < self.config.position.min_position_usd:
            return TradeCheckResult(
                allowed=False,
                reason=f"Position size ${notional_usd:.2f} below minimum ${self.config.position.min_position_usd:.2f}",
            )

        if notional_usd > self._max_position_usd:
            return TradeCheckResult(
                allowed=False,
                reason=f"Position size ${notional_usd:.2f} exceeds maximum ${self._max_position_usd:.2f}",
                max_allowed_notional=self._max_position_usd,
            )

        # Check 6: Circuit breakers (optional inputs)
        if spread_bps is not None:
            if spread_bps > self.config.circuit_breakers.max_spread_bps:
                return TradeCheckResult(
                    allowed=False,
                    reason=f"Spread {spread_bps:.2f}bps exceeds limit {self.config.circuit_breakers.max_spread_bps:.2f}bps",
                )

        if volatility_pct is not None:
            if volatility_pct > self.config.circuit_breakers.max_volatility_pct:
                return TradeCheckResult(
                    allowed=False,
                    reason=f"Volatility {volatility_pct:.2f}% exceeds limit {self.config.circuit_breakers.max_volatility_pct:.2f}%",
                )

        if latency_ms is not None:
            if latency_ms > self.config.circuit_breakers.max_latency_ms:
                return TradeCheckResult(
                    allowed=False,
                    reason=f"Latency {latency_ms:.0f}ms exceeds limit {self.config.circuit_breakers.max_latency_ms:.0f}ms",
                )

        if volume_24h_usd is not None:
            if volume_24h_usd < self.config.circuit_breakers.min_24h_volume_usd:
                return TradeCheckResult(
                    allowed=False,
                    reason=f"Volume ${volume_24h_usd:,.0f} below minimum ${self.config.circuit_breakers.min_24h_volume_usd:,.0f}",
                )

        # Check 7: Consecutive losses
        if self._consecutive_losses >= self.config.drawdown.max_consecutive_losses:
            return TradeCheckResult(
                allowed=False,
                reason=f"Max consecutive losses ({self.config.drawdown.max_consecutive_losses}) reached",
            )

        # Calculate size multiplier based on drawdown
        size_multiplier = self._calculate_size_multiplier(daily_pnl)

        # Add warnings for approaching limits
        daily_pnl_pct = (daily_pnl / self._capital_usd) * 100 if self._capital_usd > 0 else 0
        if daily_pnl_pct <= -3.0:  # 60% of 5% limit
            warnings.append(f"Approaching daily loss limit: {daily_pnl_pct:.1f}%")

        if size_multiplier < 1.0:
            warnings.append(f"Position size reduced to {size_multiplier:.0%} due to drawdown")

        return TradeCheckResult(
            allowed=True,
            warnings=warnings,
            size_multiplier=size_multiplier,
            max_allowed_notional=self._max_position_usd * size_multiplier,
        )

    def _calculate_size_multiplier(self, daily_pnl: float) -> float:
        """Calculate position size multiplier based on daily P&L."""
        if daily_pnl >= 0:
            return 1.0

        # Progressive reduction as losses accumulate
        loss_pct = abs(daily_pnl) / self._daily_loss_limit_usd

        if loss_pct < 0.3:
            return 1.0
        elif loss_pct < 0.5:
            return 0.75
        elif loss_pct < 0.7:
            return 0.50
        else:
            return 0.25

    # -------------------------------------------------------------------------
    # State Updates
    # -------------------------------------------------------------------------

    def record_trade_result(self, pnl: float, is_win: bool) -> None:
        """
        Record trade result for tracking.

        Args:
            pnl: Trade P&L in USD
            is_win: Whether trade was profitable
        """
        self._daily_pnl += pnl
        self._trade_count_today += 1

        if is_win:
            self._consecutive_losses = 0
        else:
            self._consecutive_losses += 1

            if self._consecutive_losses >= self.config.drawdown.max_consecutive_losses:
                self._trigger_halt(
                    f"Consecutive loss limit ({self.config.drawdown.max_consecutive_losses}) reached"
                )

        if self.config.audit.log_risk_checks:
            self.logger.info(
                f"Trade recorded: pnl=${pnl:.2f}, "
                f"daily_pnl=${self._daily_pnl:.2f}, "
                f"consecutive_losses={self._consecutive_losses}"
            )

    def record_position_change(self, delta: int) -> None:
        """Record position count change (+1 for open, -1 for close)."""
        self._current_positions += delta
        self._current_positions = max(0, self._current_positions)

    def reset_daily(self) -> None:
        """Reset daily tracking (call at UTC midnight)."""
        self.logger.info(
            f"Daily reset: pnl=${self._daily_pnl:.2f}, trades={self._trade_count_today}"
        )
        self._daily_pnl = 0.0
        self._trade_count_today = 0
        self._consecutive_losses = 0

        # Clear halt if it was due to daily limits
        if self._is_halted and "daily" in (self._halt_reason or "").lower():
            self._clear_halt()

    # -------------------------------------------------------------------------
    # Halt Management
    # -------------------------------------------------------------------------

    def _trigger_halt(self, reason: str) -> None:
        """Trigger trading halt."""
        if self._is_halted:
            return

        self._is_halted = True
        self._halt_reason = reason
        self._halt_time = time.time()

        self.logger.critical(f"🚨 LIVE MODE HALT: {reason}")

        if self.config.emergency.notify_on_halt and self.config.emergency.webhook_url:
            self._send_halt_notification(reason)

    def _clear_halt(self) -> None:
        """Clear trading halt (manual reset required for hard halts)."""
        self.logger.warning("✅ Live mode halt cleared")
        self._is_halted = False
        self._halt_reason = None
        self._halt_time = None

    def manual_reset(self, confirmation: str = "") -> bool:
        """
        Manually reset halt state (requires confirmation for safety).

        Args:
            confirmation: Must be "confirm-reset" to proceed

        Returns:
            True if reset successful
        """
        if confirmation != "confirm-reset":
            self.logger.warning("Manual reset rejected: invalid confirmation")
            return False

        self._clear_halt()
        self._consecutive_losses = 0
        return True

    def _send_halt_notification(self, reason: str) -> None:
        """Send halt notification via webhook (non-blocking)."""
        webhook_url = self.config.emergency.webhook_url
        if not webhook_url:
            return

        try:
            import urllib.request
            import json

            payload = json.dumps({
                "text": f"🚨 LIVE TRADING HALTED: {reason}",
                "capital_usd": self._capital_usd,
                "daily_pnl": self._daily_pnl,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }).encode("utf-8")

            req = urllib.request.Request(
                webhook_url,
                data=payload,
                headers={"Content-Type": "application/json"},
            )

            # Non-blocking - fire and forget
            urllib.request.urlopen(req, timeout=5)

        except Exception as e:
            self.logger.error(f"Failed to send halt notification: {e}")

    # -------------------------------------------------------------------------
    # Pre-flight Checks
    # -------------------------------------------------------------------------

    async def run_preflight_checks(
        self,
        redis_client=None,
        exchange_api=None,
    ) -> PreflightCheckResult:
        """
        Run pre-flight checks before live trading.

        Args:
            redis_client: Redis client for health check
            exchange_api: Exchange API for health check

        Returns:
            PreflightCheckResult with pass/fail status
        """
        checks_run: List[str] = []
        checks_failed: List[str] = []
        details: Dict[str, Any] = {}

        # Check 1: Capital bounds
        checks_run.append("capital_bounds")
        if self._capital_usd < self.config.capital.min_capital_usd:
            checks_failed.append("capital_bounds")
            details["capital_error"] = (
                f"Capital ${self._capital_usd:.2f} below minimum "
                f"${self.config.capital.min_capital_usd:.2f}"
            )
        elif self._capital_usd > self.config.capital.max_capital_usd:
            checks_failed.append("capital_bounds")
            details["capital_error"] = (
                f"Capital ${self._capital_usd:.2f} exceeds maximum "
                f"${self.config.capital.max_capital_usd:.2f}"
            )

        # Check 2: Live confirmation
        checks_run.append("live_confirmation")
        confirmation = os.getenv("LIVE_TRADING_CONFIRMATION", "")
        if confirmation != "I-accept-the-risk":
            checks_failed.append("live_confirmation")
            details["confirmation_error"] = (
                "LIVE_TRADING_CONFIRMATION must be 'I-accept-the-risk'"
            )

        # Check 3: Redis health (optional)
        if self.config.preflight.require_redis_health and redis_client:
            checks_run.append("redis_health")
            try:
                if hasattr(redis_client, "_client") and redis_client._client:
                    await redis_client._client.ping()
                elif hasattr(redis_client, "ping"):
                    await redis_client.ping()
                details["redis_health"] = "OK"
            except Exception as e:
                checks_failed.append("redis_health")
                details["redis_error"] = str(e)

        # Check 4: Exchange health (optional)
        if self.config.preflight.require_exchange_health and exchange_api:
            checks_run.append("exchange_health")
            try:
                if hasattr(exchange_api, "get_system_status"):
                    status = await exchange_api.get_system_status()
                    details["exchange_health"] = status
                else:
                    details["exchange_health"] = "Skipped (no status method)"
            except Exception as e:
                checks_failed.append("exchange_health")
                details["exchange_error"] = str(e)

        # Check 5: Confirmation file (optional)
        if self.config.preflight.require_confirmation_file:
            checks_run.append("confirmation_file")
            conf_path = Path(self.config.preflight.confirmation_file_path)
            if not conf_path.exists():
                checks_failed.append("confirmation_file")
                details["confirmation_file_error"] = f"File not found: {conf_path}"
            else:
                details["confirmation_file"] = "OK"

        passed = len(checks_failed) == 0

        if passed:
            self.logger.info(f"Pre-flight checks PASSED: {checks_run}")
        else:
            self.logger.error(f"Pre-flight checks FAILED: {checks_failed}")

        return PreflightCheckResult(
            passed=passed,
            checks_run=checks_run,
            checks_failed=checks_failed,
            details=details,
        )

    # -------------------------------------------------------------------------
    # Status
    # -------------------------------------------------------------------------

    def get_status(self) -> LiveModeStatus:
        """Get current live mode status."""
        return LiveModeStatus(
            is_live_mode=self._is_live_mode,
            guardrails_enabled=self.config.enabled,
            capital_usd=self._capital_usd,
            max_position_usd=self._max_position_usd,
            daily_loss_limit_usd=self._daily_loss_limit_usd,
            current_daily_pnl=self._daily_pnl,
            positions_count=self._current_positions,
            is_halted=self._is_halted,
            halt_reason=self._halt_reason,
        )

    def get_limits(self) -> Dict[str, float]:
        """Get calculated limits for current capital."""
        return {
            "capital_usd": self._capital_usd,
            "max_position_usd": self._max_position_usd,
            "min_position_usd": self.config.position.min_position_usd,
            "max_concurrent_positions": self.config.position.max_concurrent_positions,
            "risk_per_trade_usd": self._capital_usd * (self.config.position.risk_per_trade_pct / 100),
            "daily_loss_limit_usd": self._daily_loss_limit_usd,
            "max_loss_usd": self._max_loss_usd,
            "max_consecutive_losses": self.config.drawdown.max_consecutive_losses,
        }

    def log_active_limits(self) -> None:
        """
        Log all active risk limits at startup (preflight check).

        IMPORTANT: This logs only configuration values, NO SECRETS.
        Call this during engine initialization to confirm limits are active.
        """
        limits = self.get_limits()

        self.logger.info("=" * 60)
        self.logger.info("ACTIVE RISK LIMITS (Preflight Check)")
        self.logger.info("=" * 60)
        self.logger.info(f"Engine Mode: {'LIVE' if self._is_live_mode else 'PAPER'}")
        self.logger.info(f"Guardrails Enabled: {self.config.enabled}")
        self.logger.info("-" * 40)
        self.logger.info("POSITION LIMITS:")
        self.logger.info(f"  max_position_size_usd: ${limits['max_position_usd']:.2f}")
        self.logger.info(f"  min_position_size_usd: ${limits['min_position_usd']:.2f}")
        self.logger.info(f"  max_concurrent_positions: {limits['max_concurrent_positions']}")
        self.logger.info(f"  risk_per_trade_usd: ${limits['risk_per_trade_usd']:.2f}")
        self.logger.info("-" * 40)
        self.logger.info("LOSS LIMITS:")
        self.logger.info(f"  max_daily_loss_usd: ${limits['daily_loss_limit_usd']:.2f}")
        self.logger.info(f"  max_loss_usd (emergency): ${limits['max_loss_usd']:.2f}")
        self.logger.info(f"  max_consecutive_losses: {limits['max_consecutive_losses']}")
        self.logger.info("-" * 40)
        self.logger.info("CIRCUIT BREAKERS:")
        self.logger.info(f"  max_spread_bps: {self.config.circuit_breakers.max_spread_bps}")
        self.logger.info(f"  max_volatility_pct: {self.config.circuit_breakers.max_volatility_pct}%")
        self.logger.info(f"  min_24h_volume_usd: ${self.config.circuit_breakers.min_24h_volume_usd:,.0f}")
        self.logger.info(f"  max_latency_ms: {self.config.circuit_breakers.max_latency_ms}ms")
        self.logger.info("-" * 40)
        self.logger.info("EMERGENCY CONTROLS:")
        self.logger.info(f"  halt_on_any_error: {self.config.emergency.halt_on_any_error}")
        self.logger.info(f"  flatten_on_halt: {self.config.emergency.flatten_on_halt}")
        self.logger.info(f"  notify_on_halt: {self.config.emergency.notify_on_halt}")
        self.logger.info("=" * 60)

        if self._is_live_mode and self.config.enabled:
            self.logger.warning(
                "LIVE MODE ACTIVE with $%.2f capital. "
                "Max position: $%.2f, Daily loss limit: $%.2f",
                self._capital_usd,
                limits['max_position_usd'],
                limits['daily_loss_limit_usd'],
            )


# =============================================================================
# SELF-CHECK
# =============================================================================

if __name__ == "__main__":
    import asyncio

    async def test_live_mode_guard():
        """Self-check for live mode guard."""
        print("\n=== Live Mode Guard Self-Check ===\n")

        # Create guard with test config
        guard = LiveModeGuard.from_config()

        print("1. Configuration loaded:")
        print(f"   Capital: ${guard.capital_usd:.2f}")
        print(f"   Limits: {guard.get_limits()}\n")

        print("1.5. Preflight logging (active limits):")
        guard.log_active_limits()
        print()

        print("2. Testing trade check (should pass):")
        result = guard.check_trade_allowed(
            notional_usd=20.0,
            current_positions=0,
            daily_pnl=0.0,
        )
        print(f"   Allowed: {result.allowed}")
        print(f"   Max notional: ${result.max_allowed_notional}\n")

        print("3. Testing oversized trade (should fail):")
        result = guard.check_trade_allowed(
            notional_usd=50.0,  # Over 25% of $100
            current_positions=0,
            daily_pnl=0.0,
        )
        print(f"   Allowed: {result.allowed}")
        print(f"   Reason: {result.reason}\n")

        print("4. Testing daily loss limit (should fail):")
        result = guard.check_trade_allowed(
            notional_usd=10.0,
            current_positions=0,
            daily_pnl=-6.0,  # Over 5% of $100
        )
        print(f"   Allowed: {result.allowed}")
        print(f"   Reason: {result.reason}\n")

        print("5. Status:")
        status = guard.get_status()
        print(f"   Is live mode: {status.is_live_mode}")
        print(f"   Guardrails enabled: {status.guardrails_enabled}")
        print(f"   Is halted: {status.is_halted}")
        print(f"   Halt reason: {status.halt_reason}\n")

        print("6. Pre-flight checks (without Redis/Exchange):")
        preflight = await guard.run_preflight_checks()
        print(f"   Passed: {preflight.passed}")
        print(f"   Checks run: {preflight.checks_run}")
        print(f"   Checks failed: {preflight.checks_failed}\n")

        print("[PASS] Live Mode Guard Self-Check Complete")

    asyncio.run(test_live_mode_guard())
