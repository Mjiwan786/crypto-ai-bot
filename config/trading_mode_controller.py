"""
Trading Mode Controller - Paper/Live Switching with Safety Guards

Controls the transition from PAPER to LIVE trading mode with multi-layer safety checks.
Enforces LIVE_TRADING_CONFIRMATION, emergency kill-switch, and pair whitelisting.

Redis Key:
    - ACTIVE_SIGNALS alias: Points to either 'signals:paper' or 'signals:live'
    - kraken:emergency:kill_switch: Emergency stop flag

Environment Variables:
    - TRADING_MODE: PAPER | LIVE
    - LIVE_TRADING_CONFIRMATION: Must equal "I-accept-the-risk" for LIVE mode
    - KRAKEN_EMERGENCY_STOP: Set to "true" to halt all new entries immediately
"""

import os
import logging
from enum import Enum
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime
import redis


logger = logging.getLogger(__name__)


class TradingMode(str, Enum):
    """Trading mode enum"""
    PAPER = "PAPER"
    LIVE = "LIVE"


class EmergencyStatus(str, Enum):
    """Emergency stop status"""
    ACTIVE = "ACTIVE"
    STOPPED = "STOPPED"
    HALTED = "HALTED"


@dataclass
class TradingModeConfig:
    """Trading mode configuration"""
    mode: TradingMode
    confirmation_required: bool
    confirmation_phrase: str = "I-accept-the-risk"
    emergency_stop_env: str = "KRAKEN_EMERGENCY_STOP"
    redis_emergency_key: str = "kraken:emergency:kill_switch"
    active_signals_alias: str = "ACTIVE_SIGNALS"
    signals_paper_stream: str = "signals:paper"
    signals_live_stream: str = "signals:live"


@dataclass
class SafetyCheckResult:
    """Result of safety checks"""
    passed: bool
    mode: TradingMode
    emergency_stop_active: bool
    confirmation_valid: bool
    pair_allowed: bool
    notional_within_cap: bool
    errors: List[str]
    warnings: List[str]


class TradingModeController:
    """
    Controls trading mode transitions and enforces safety checks.

    Features:
        - Paper/Live mode switching via Redis alias
        - LIVE mode requires explicit confirmation
        - Emergency kill-switch support
        - Pair whitelist enforcement
        - Notional cap enforcement per pair
        - Circuit breaker integration
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        config: Optional[TradingModeConfig] = None,
        pair_whitelist: Optional[List[str]] = None,
        notional_caps: Optional[Dict[str, float]] = None
    ):
        """
        Initialize trading mode controller.

        Args:
            redis_client: Redis client instance
            config: Trading mode configuration (auto-loaded from env if None)
            pair_whitelist: List of allowed trading pairs (e.g., ['XBTUSD', 'ETHUSD'])
            notional_caps: Notional caps per pair in USD (e.g., {'XBTUSD': 10000.0})
        """
        self.redis = redis_client
        self.config = config or self._load_config_from_env()
        self.pair_whitelist = pair_whitelist or []
        self.notional_caps = notional_caps or {}

        # Initialize Redis alias on startup
        self._initialize_mode()

        logger.info(
            f"TradingModeController initialized: mode={self.config.mode}, "
            f"pairs={len(self.pair_whitelist)}, caps={len(self.notional_caps)}"
        )

    def _load_config_from_env(self) -> TradingModeConfig:
        """Load configuration from environment variables"""
        mode_str = os.getenv("TRADING_MODE", "PAPER").upper()
        mode = TradingMode.PAPER if mode_str == "PAPER" else TradingMode.LIVE

        return TradingModeConfig(
            mode=mode,
            confirmation_required=(mode == TradingMode.LIVE),
        )

    def _initialize_mode(self):
        """Initialize ACTIVE_SIGNALS Redis alias based on current mode"""
        target_stream = (
            self.config.signals_live_stream
            if self.config.mode == TradingMode.LIVE
            else self.config.signals_paper_stream
        )

        # Set the alias (we use a simple string key, not Redis ALIAS)
        # Agents will read ACTIVE_SIGNALS to know which stream to publish to
        self.redis.set(self.config.active_signals_alias, target_stream)

        logger.info(f"ACTIVE_SIGNALS → {target_stream}")

    def get_current_mode(self) -> TradingMode:
        """Get current trading mode"""
        return self.config.mode

    def get_active_signal_stream(self) -> str:
        """Get the active signal stream name from Redis"""
        stream = self.redis.get(self.config.active_signals_alias)
        if stream:
            return stream.decode() if isinstance(stream, bytes) else stream
        return self.config.signals_paper_stream

    def is_emergency_stop_active(self) -> bool:
        """
        Check if emergency stop is active.

        Checks both:
            1. Environment variable KRAKEN_EMERGENCY_STOP
            2. Redis key kraken:emergency:kill_switch

        Returns:
            True if emergency stop is active, False otherwise
        """
        # Check environment variable
        env_stop = os.getenv(self.config.emergency_stop_env, "false").lower()
        if env_stop in ("true", "1", "yes"):
            return True

        # Check Redis flag
        redis_stop = self.redis.get(self.config.redis_emergency_key)
        if redis_stop:
            value = redis_stop.decode() if isinstance(redis_stop, bytes) else redis_stop
            return value.lower() in ("true", "1", "active")

        return False

    def activate_emergency_stop(self, reason: str = "Manual trigger"):
        """
        Activate emergency kill-switch.

        Sets Redis flag and publishes emergency event to metrics stream.

        Args:
            reason: Reason for activation
        """
        # Set Redis flag
        self.redis.set(self.config.redis_emergency_key, "true")

        # Publish emergency event
        event = {
            "event": "emergency_stop_activated",
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat(),
            "mode": self.config.mode.value
        }

        self.redis.xadd("metrics:emergency", event)
        self.redis.xadd("kraken:status", {"status": "emergency_stop", **event})

        logger.critical(f"EMERGENCY STOP ACTIVATED: {reason}")

    def deactivate_emergency_stop(self):
        """Deactivate emergency kill-switch"""
        self.redis.delete(self.config.redis_emergency_key)

        event = {
            "event": "emergency_stop_deactivated",
            "timestamp": datetime.utcnow().isoformat(),
            "mode": self.config.mode.value
        }

        self.redis.xadd("metrics:emergency", event)
        self.redis.xadd("kraken:status", {"status": "emergency_stop_cleared", **event})

        logger.warning("Emergency stop deactivated")

    def is_live_confirmation_valid(self) -> bool:
        """
        Check if LIVE trading confirmation is valid.

        Returns:
            True if confirmation is valid or mode is PAPER, False otherwise
        """
        if self.config.mode == TradingMode.PAPER:
            return True

        confirmation = os.getenv("LIVE_TRADING_CONFIRMATION", "")
        return confirmation == self.config.confirmation_phrase

    def is_pair_allowed(self, pair: str) -> bool:
        """
        Check if trading pair is in whitelist.

        Args:
            pair: Trading pair (e.g., 'XBTUSD')

        Returns:
            True if pair is allowed or whitelist is empty, False otherwise
        """
        if not self.pair_whitelist:
            return True

        return pair in self.pair_whitelist

    def is_notional_within_cap(self, pair: str, notional_usd: float) -> bool:
        """
        Check if order notional is within pair cap.

        Args:
            pair: Trading pair
            notional_usd: Order notional in USD

        Returns:
            True if within cap or no cap defined, False otherwise
        """
        if pair not in self.notional_caps:
            return True

        cap = self.notional_caps[pair]
        return notional_usd <= cap

    def check_can_trade(
        self,
        pair: str,
        notional_usd: float,
        operation: str = "entry"
    ) -> SafetyCheckResult:
        """
        Comprehensive safety check before allowing trade.

        Args:
            pair: Trading pair
            notional_usd: Order notional in USD
            operation: 'entry' or 'exit' (exits always allowed during emergency)

        Returns:
            SafetyCheckResult with all check results
        """
        errors = []
        warnings = []

        # Check 1: Emergency stop
        emergency_active = self.is_emergency_stop_active()
        if emergency_active and operation == "entry":
            errors.append("Emergency stop is active - no new entries allowed")

        # Check 2: LIVE confirmation
        confirmation_valid = self.is_live_confirmation_valid()
        if not confirmation_valid:
            errors.append(
                f"LIVE mode requires LIVE_TRADING_CONFIRMATION='{self.config.confirmation_phrase}'"
            )

        # Check 3: Pair whitelist
        pair_allowed = self.is_pair_allowed(pair)
        if not pair_allowed:
            errors.append(f"Pair '{pair}' not in whitelist: {self.pair_whitelist}")

        # Check 4: Notional cap
        notional_ok = self.is_notional_within_cap(pair, notional_usd)
        if not notional_ok:
            cap = self.notional_caps.get(pair, 0)
            errors.append(
                f"Order notional ${notional_usd:.2f} exceeds cap ${cap:.2f} for {pair}"
            )

        # Warnings
        if self.config.mode == TradingMode.LIVE and not warnings:
            warnings.append("LIVE trading mode - real money at risk")

        passed = len(errors) == 0

        return SafetyCheckResult(
            passed=passed,
            mode=self.config.mode,
            emergency_stop_active=emergency_active,
            confirmation_valid=confirmation_valid,
            pair_allowed=pair_allowed,
            notional_within_cap=notional_ok,
            errors=errors,
            warnings=warnings
        )

    def switch_mode(self, new_mode: TradingMode) -> bool:
        """
        Switch trading mode (PAPER ↔ LIVE).

        Args:
            new_mode: Target mode

        Returns:
            True if switch successful, False otherwise
        """
        if new_mode == self.config.mode:
            logger.info(f"Already in {new_mode} mode")
            return True

        # Validate LIVE mode requirements
        if new_mode == TradingMode.LIVE:
            if not self.is_live_confirmation_valid():
                logger.error(
                    f"Cannot switch to LIVE: missing confirmation "
                    f"'{self.config.confirmation_phrase}'"
                )
                return False

        old_mode = self.config.mode
        self.config.mode = new_mode
        self.config.confirmation_required = (new_mode == TradingMode.LIVE)

        # Update Redis alias
        self._initialize_mode()

        # Publish mode change event
        event = {
            "event": "trading_mode_changed",
            "old_mode": old_mode.value,
            "new_mode": new_mode.value,
            "timestamp": datetime.utcnow().isoformat()
        }

        self.redis.xadd("metrics:mode_changes", event)
        self.redis.xadd("kraken:status", {"status": "mode_change", **event})

        logger.warning(f"Trading mode switched: {old_mode} → {new_mode}")
        return True

    def get_status(self) -> Dict[str, Any]:
        """Get current controller status"""
        return {
            "mode": self.config.mode.value,
            "active_signal_stream": self.get_active_signal_stream(),
            "emergency_stop_active": self.is_emergency_stop_active(),
            "live_confirmation_valid": self.is_live_confirmation_valid(),
            "pair_whitelist": self.pair_whitelist,
            "notional_caps": self.notional_caps,
            "timestamp": datetime.utcnow().isoformat()
        }


class CircuitBreakerMonitor:
    """
    Monitors circuit breaker conditions and publishes status events.

    Monitors:
        - Latency spikes
        - Spread widening
        - Rate limit violations
        - WebSocket disconnections
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        mode_controller: TradingModeController,
        latency_threshold_ms: float = 1000.0,
        spread_threshold_bps: float = 50.0
    ):
        """
        Initialize circuit breaker monitor.

        Args:
            redis_client: Redis client
            mode_controller: Trading mode controller
            latency_threshold_ms: Latency threshold in milliseconds
            spread_threshold_bps: Spread threshold in basis points
        """
        self.redis = redis_client
        self.mode_controller = mode_controller
        self.latency_threshold_ms = latency_threshold_ms
        self.spread_threshold_bps = spread_threshold_bps

        logger.info(
            f"CircuitBreakerMonitor initialized: "
            f"latency_threshold={latency_threshold_ms}ms, "
            f"spread_threshold={spread_threshold_bps}bps"
        )

    def check_latency(self, latency_ms: float, pair: str) -> bool:
        """
        Check if latency exceeds threshold.

        Args:
            latency_ms: Measured latency in milliseconds
            pair: Trading pair

        Returns:
            True if latency is acceptable, False if breaker should trip
        """
        if latency_ms > self.latency_threshold_ms:
            self._trip_breaker("latency", pair, {
                "latency_ms": latency_ms,
                "threshold_ms": self.latency_threshold_ms
            })
            return False

        return True

    def check_spread(self, spread_bps: float, pair: str) -> bool:
        """
        Check if spread exceeds threshold.

        Args:
            spread_bps: Measured spread in basis points
            pair: Trading pair

        Returns:
            True if spread is acceptable, False if breaker should trip
        """
        if spread_bps > self.spread_threshold_bps:
            self._trip_breaker("spread", pair, {
                "spread_bps": spread_bps,
                "threshold_bps": self.spread_threshold_bps
            })
            return False

        return True

    def report_rate_limit_violation(self, pair: str, details: Dict[str, Any]):
        """Report rate limit violation"""
        self._trip_breaker("rate_limit", pair, details)

    def report_websocket_disconnect(self, pair: str, details: Dict[str, Any]):
        """Report WebSocket disconnection"""
        self._trip_breaker("websocket_disconnect", pair, details)

    def _trip_breaker(self, breaker_type: str, pair: str, details: Dict[str, Any]):
        """
        Trip circuit breaker and publish events.

        Args:
            breaker_type: Type of breaker (latency, spread, rate_limit, etc.)
            pair: Trading pair
            details: Additional details
        """
        event = {
            "event": "circuit_breaker_tripped",
            "breaker_type": breaker_type,
            "pair": pair,
            "timestamp": datetime.utcnow().isoformat(),
            "mode": self.mode_controller.get_current_mode().value,
            **details
        }

        # Publish to multiple streams for visibility
        self.redis.xadd("metrics:circuit_breakers", event)
        self.redis.xadd("kraken:status", {"status": "circuit_breaker", **event})

        logger.error(
            f"Circuit breaker tripped: {breaker_type} on {pair} - {details}"
        )

        # Auto-activate emergency stop on critical breakers
        if breaker_type in ("rate_limit", "websocket_disconnect"):
            logger.critical(f"Auto-activating emergency stop due to {breaker_type}")
            self.mode_controller.activate_emergency_stop(
                f"Auto-stop: {breaker_type} on {pair}"
            )
