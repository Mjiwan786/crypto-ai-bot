"""
Comprehensive Safety Gates for J1-J3 Requirements

J1: Environment Switches
- MODE=PAPER|LIVE routing with ACTIVE_SIGNALS alias
- LIVE_TRADING_CONFIRMATION="I-accept-the-risk" requirement
- KRAKEN_EMERGENCY_STOP immediate halt

J2: Pair Whitelists & Notional Caps
- Per-pair min/max notional from kraken.yaml
- Whitelist enforcement (block unlisted pairs)
- Dynamic cap loading from config

J3: Circuit Breakers
- Spread/latency circuit trips pause entries for N seconds
- Publishes status events to Redis
- Auto-recovery after pause duration
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Any
import yaml
from pathlib import Path

import redis

logger = logging.getLogger(__name__)


# =============================================================================
# J1: ENVIRONMENT SWITCHES
# =============================================================================


class TradingMode(str, Enum):
    """Trading mode"""
    PAPER = "PAPER"
    LIVE = "LIVE"


@dataclass
class ModeConfig:
    """MODE configuration result"""
    mode: TradingMode
    is_paper: bool
    is_live: bool
    confirmation_valid: bool
    active_signal_stream: str
    can_trade_live: bool
    errors: List[str]


class ModeSwitch:
    """
    J1: MODE=PAPER|LIVE environment switch.

    Features:
    - Routes signals to signals:paper or signals:live based on MODE
    - Requires LIVE_TRADING_CONFIRMATION for live trading
    - Sets ACTIVE_SIGNALS Redis alias for downstream routing
    """

    CONFIRMATION_PHRASE = "I-accept-the-risk"

    def __init__(self, redis_client: Optional[redis.Redis] = None):
        """
        Initialize mode switch.

        Args:
            redis_client: Redis client for ACTIVE_SIGNALS alias
        """
        self.redis = redis_client
        self.logger = logging.getLogger(f"{__name__}.ModeSwitch")

    def get_mode_config(self) -> ModeConfig:
        """
        Get current MODE configuration from environment.

        Returns:
            ModeConfig with all mode details
        """
        mode_str = os.getenv("MODE", "PAPER").upper()
        mode = TradingMode.LIVE if mode_str == "LIVE" else TradingMode.PAPER

        is_paper = (mode == TradingMode.PAPER)
        is_live = (mode == TradingMode.LIVE)

        # Check LIVE confirmation
        confirmation = os.getenv("LIVE_TRADING_CONFIRMATION", "")
        confirmation_valid = (confirmation == self.CONFIRMATION_PHRASE)

        errors = []

        # Determine active signal stream
        if is_live:
            active_signal_stream = "signals:live"
            if not confirmation_valid:
                errors.append(
                    f"LIVE mode requires LIVE_TRADING_CONFIRMATION="
                    f"'{self.CONFIRMATION_PHRASE}'. "
                    f"Current: '{confirmation if confirmation else '(not set)'}'"
                )
        else:
            active_signal_stream = "signals:paper"

        # Can trade live?
        can_trade_live = (is_live and confirmation_valid)

        # Set Redis alias if available
        if self.redis:
            try:
                self.redis.set("ACTIVE_SIGNALS", active_signal_stream)
                self.logger.info(f"ACTIVE_SIGNALS → {active_signal_stream}")
            except Exception as e:
                self.logger.error(f"Failed to set ACTIVE_SIGNALS: {e}")
                errors.append(f"Redis error: {e}")

        return ModeConfig(
            mode=mode,
            is_paper=is_paper,
            is_live=is_live,
            confirmation_valid=confirmation_valid,
            active_signal_stream=active_signal_stream,
            can_trade_live=can_trade_live,
            errors=errors
        )

    def check_can_enter_live_trade(self) -> tuple[bool, str]:
        """
        Check if live trading is allowed (for entries).

        Returns:
            Tuple of (allowed, error_message)
        """
        config = self.get_mode_config()

        if not config.is_live:
            return False, f"MODE={config.mode.value}, not LIVE"

        if not config.confirmation_valid:
            return False, config.errors[0] if config.errors else "Missing confirmation"

        return True, ""


# =============================================================================
# J1: EMERGENCY KILL SWITCH
# =============================================================================


@dataclass
class EmergencyStopStatus:
    """Emergency stop status"""
    is_active: bool
    source: str  # "env" or "redis"
    reason: str
    activated_at: Optional[datetime]
    can_enter: bool
    can_exit: bool


class EmergencyKillSwitch:
    """
    J1: KRAKEN_EMERGENCY_STOP kill switch.

    Features:
    - Checks both KRAKEN_EMERGENCY_STOP env var and Redis key
    - Immediately rejects new entries when active
    - Allows exits to close positions
    - Publishes emergency events to Redis
    """

    ENV_VAR = "KRAKEN_EMERGENCY_STOP"
    REDIS_KEY = "kraken:emergency:kill_switch"
    STATUS_STREAM = "kraken:status"
    METRICS_STREAM = "metrics:emergency"

    def __init__(self, redis_client: Optional[redis.Redis] = None):
        """
        Initialize emergency kill switch.

        Args:
            redis_client: Redis client for kill switch coordination
        """
        self.redis = redis_client
        self.logger = logging.getLogger(f"{__name__}.EmergencyKillSwitch")
        self._last_status_check = 0.0
        self._cache_ttl = 1.0  # Cache status for 1 second

    def get_status(self) -> EmergencyStopStatus:
        """
        Get emergency stop status.

        Returns:
            EmergencyStopStatus with all details
        """
        # Check environment variable
        env_value = os.getenv(self.ENV_VAR, "false").lower()
        env_active = env_value in ("true", "1", "yes")

        if env_active:
            return EmergencyStopStatus(
                is_active=True,
                source="env",
                reason=f"{self.ENV_VAR}={env_value}",
                activated_at=None,
                can_enter=False,
                can_exit=True
            )

        # Check Redis key
        if self.redis:
            try:
                redis_value = self.redis.get(self.REDIS_KEY)
                if redis_value:
                    value_str = redis_value.decode() if isinstance(redis_value, bytes) else redis_value

                    # Try to extract timestamp if available
                    activated_at = None
                    if "activated at" in value_str.lower():
                        # Extract ISO timestamp if present
                        try:
                            parts = value_str.split("activated at")
                            if len(parts) > 1:
                                ts_str = parts[1].strip().rstrip(")")
                                activated_at = datetime.fromisoformat(ts_str)
                        except:
                            pass

                    return EmergencyStopStatus(
                        is_active=True,
                        source="redis",
                        reason=value_str,
                        activated_at=activated_at,
                        can_enter=False,
                        can_exit=True
                    )
            except Exception as e:
                self.logger.error(f"Error checking Redis kill switch: {e}")

        # Not active
        return EmergencyStopStatus(
            is_active=False,
            source="none",
            reason="",
            activated_at=None,
            can_enter=True,
            can_exit=True
        )

    def is_active(self) -> bool:
        """Quick check if emergency stop is active"""
        return self.get_status().is_active

    def activate(self, reason: str = "Manual activation", ttl_seconds: Optional[int] = 3600):
        """
        Activate emergency kill switch.

        Args:
            reason: Reason for activation
            ttl_seconds: TTL for Redis key (default: 1 hour)
        """
        timestamp = datetime.utcnow().isoformat()
        message = f"{reason} (activated at {timestamp})"

        if self.redis:
            try:
                if ttl_seconds:
                    self.redis.setex(self.REDIS_KEY, ttl_seconds, message)
                else:
                    self.redis.set(self.REDIS_KEY, message)

                # Publish emergency event
                event = {
                    "event": "emergency_stop_activated",
                    "reason": reason,
                    "timestamp": timestamp,
                    "ttl_seconds": ttl_seconds or 0
                }

                self.redis.xadd(self.STATUS_STREAM, {"status": "emergency_stop", **event})
                self.redis.xadd(self.METRICS_STREAM, event)

                self.logger.critical(f"🚨 EMERGENCY STOP ACTIVATED: {reason}")
            except Exception as e:
                self.logger.error(f"Failed to activate emergency stop in Redis: {e}")
        else:
            self.logger.warning("Redis not available, emergency stop not persisted")

    def deactivate(self):
        """Deactivate emergency kill switch"""
        if self.redis:
            try:
                self.redis.delete(self.REDIS_KEY)

                event = {
                    "event": "emergency_stop_deactivated",
                    "timestamp": datetime.utcnow().isoformat()
                }

                self.redis.xadd(self.STATUS_STREAM, {"status": "emergency_stop_cleared", **event})
                self.redis.xadd(self.METRICS_STREAM, event)

                self.logger.warning("✅ Emergency stop deactivated")
            except Exception as e:
                self.logger.error(f"Failed to deactivate emergency stop: {e}")


# =============================================================================
# J2: PAIR WHITELISTS & NOTIONAL CAPS
# =============================================================================


@dataclass
class PairLimits:
    """Per-pair trading limits"""
    pair: str
    min_notional: float
    max_notional: float
    is_whitelisted: bool
    precision: Optional[Dict[str, Any]] = None


class PairWhitelistEnforcer:
    """
    J2: Pair whitelist and notional cap enforcement.

    Features:
    - Loads limits from config/exchange_configs/kraken.yaml
    - Enforces min/max notional per pair
    - Blocks unlisted pairs
    - Supports dynamic whitelist from environment
    """

    def __init__(
        self,
        config_path: Optional[Path] = None,
        whitelist_override: Optional[List[str]] = None,
        notional_caps_override: Optional[Dict[str, float]] = None
    ):
        """
        Initialize pair whitelist enforcer.

        Args:
            config_path: Path to kraken.yaml (auto-detected if None)
            whitelist_override: Override whitelist from environment
            notional_caps_override: Override notional caps from environment
        """
        self.logger = logging.getLogger(f"{__name__}.PairWhitelistEnforcer")

        # Auto-detect config path
        if config_path is None:
            project_root = Path(__file__).parent.parent
            config_path = project_root / "config" / "exchange_configs" / "kraken.yaml"

        self.config_path = config_path
        self.limits: Dict[str, PairLimits] = {}

        # Load limits from YAML
        self._load_limits_from_yaml()

        # Apply overrides from environment
        self._apply_environment_overrides(whitelist_override, notional_caps_override)

        self.logger.info(f"Pair enforcer initialized: {len(self.limits)} pairs configured")

    def _load_limits_from_yaml(self):
        """Load pair limits from kraken.yaml"""
        if not self.config_path.exists():
            self.logger.warning(f"Config file not found: {self.config_path}")
            return

        try:
            with open(self.config_path, "r") as f:
                config = yaml.safe_load(f)

            trading_specs = config.get("trading_specs", {})
            precision = trading_specs.get("precision", {})

            # Load from trading_specs.precision
            for pair, spec in precision.items():
                min_notional = spec.get("min_notional", 5.0)
                # Max notional from risk_guards or default
                max_notional = config.get("risk_guards", {}).get("position_limits", {}).get(
                    "max_position_usd", {}
                ).get(pair, 50000.0)

                self.limits[pair] = PairLimits(
                    pair=pair,
                    min_notional=min_notional,
                    max_notional=max_notional,
                    is_whitelisted=True,  # All configured pairs are whitelisted
                    precision=spec
                )

            self.logger.info(f"Loaded limits for {len(self.limits)} pairs from {self.config_path.name}")

        except Exception as e:
            self.logger.error(f"Error loading limits from YAML: {e}")

    def _apply_environment_overrides(
        self,
        whitelist_override: Optional[List[str]],
        notional_caps_override: Optional[Dict[str, float]]
    ):
        """Apply environment variable overrides"""
        # Apply whitelist from env: TRADING_PAIR_WHITELIST
        env_whitelist = os.getenv("TRADING_PAIR_WHITELIST", "")
        if env_whitelist:
            whitelist_pairs = [p.strip() for p in env_whitelist.split(",") if p.strip()]
            self.logger.info(f"Applying whitelist from env: {whitelist_pairs}")

            # Mark all as not whitelisted, then whitelist specified
            for pair in self.limits:
                self.limits[pair].is_whitelisted = (pair in whitelist_pairs)

        elif whitelist_override:
            self.logger.info(f"Applying whitelist override: {whitelist_override}")
            for pair in self.limits:
                self.limits[pair].is_whitelisted = (pair in whitelist_override)

        # Apply notional caps from env: NOTIONAL_CAPS=XBTUSD:10000,ETHUSD:5000
        env_caps = os.getenv("NOTIONAL_CAPS", "")
        if env_caps:
            try:
                caps_dict = {}
                for item in env_caps.split(","):
                    if ":" in item:
                        pair, cap = item.split(":")
                        caps_dict[pair.strip()] = float(cap.strip())

                self.logger.info(f"Applying notional caps from env: {caps_dict}")

                for pair, cap in caps_dict.items():
                    if pair in self.limits:
                        self.limits[pair].max_notional = cap

            except Exception as e:
                self.logger.error(f"Error parsing NOTIONAL_CAPS: {e}")

        elif notional_caps_override:
            self.logger.info(f"Applying notional caps override: {notional_caps_override}")
            for pair, cap in notional_caps_override.items():
                if pair in self.limits:
                    self.limits[pair].max_notional = cap

    def is_pair_allowed(self, pair: str) -> bool:
        """
        Check if pair is whitelisted.

        Args:
            pair: Trading pair (e.g., 'XBTUSD')

        Returns:
            True if pair is allowed, False otherwise
        """
        if pair not in self.limits:
            self.logger.warning(f"Pair '{pair}' not configured in limits")
            return False

        return self.limits[pair].is_whitelisted

    def check_notional(self, pair: str, notional_usd: float) -> tuple[bool, str]:
        """
        Check if notional is within min/max limits.

        Args:
            pair: Trading pair
            notional_usd: Order notional in USD

        Returns:
            Tuple of (valid, error_message)
        """
        if pair not in self.limits:
            return False, f"Pair '{pair}' not configured"

        limits = self.limits[pair]

        if not limits.is_whitelisted:
            return False, f"Pair '{pair}' not in whitelist"

        if notional_usd < limits.min_notional:
            return False, f"Notional ${notional_usd:.2f} below min ${limits.min_notional:.2f} for {pair}"

        if notional_usd > limits.max_notional:
            return False, f"Notional ${notional_usd:.2f} exceeds max ${limits.max_notional:.2f} for {pair}"

        return True, ""

    def get_limits(self, pair: str) -> Optional[PairLimits]:
        """Get limits for a specific pair"""
        return self.limits.get(pair)

    def get_all_whitelisted_pairs(self) -> List[str]:
        """Get list of all whitelisted pairs"""
        return [pair for pair, limits in self.limits.items() if limits.is_whitelisted]


# =============================================================================
# J3: CIRCUIT BREAKERS
# =============================================================================


@dataclass
class CircuitBreakerStatus:
    """Circuit breaker status"""
    breaker_type: str  # "spread", "latency", "rate_limit", etc.
    is_tripped: bool
    trip_time: Optional[datetime]
    resume_time: Optional[datetime]
    pause_duration_seconds: int
    reason: str
    can_trade: bool


class CircuitBreaker:
    """
    J3: Circuit breaker with pause mechanism.

    Features:
    - Pauses entries for N seconds when triggered
    - Publishes status events to Redis
    - Auto-recovery after pause duration
    - Supports multiple breaker types (spread, latency, etc.)
    """

    def __init__(
        self,
        redis_client: Optional[redis.Redis] = None,
        spread_threshold_bps: float = 50.0,
        latency_threshold_ms: float = 1000.0,
        default_pause_seconds: int = 60
    ):
        """
        Initialize circuit breaker.

        Args:
            redis_client: Redis client for status events
            spread_threshold_bps: Spread threshold in bps
            latency_threshold_ms: Latency threshold in ms
            default_pause_seconds: Default pause duration
        """
        self.redis = redis_client
        self.spread_threshold_bps = spread_threshold_bps
        self.latency_threshold_ms = latency_threshold_ms
        self.default_pause_seconds = default_pause_seconds

        self.logger = logging.getLogger(f"{__name__}.CircuitBreaker")

        # Track active breakers
        self.breakers: Dict[str, CircuitBreakerStatus] = {}

        self.logger.info(
            f"CircuitBreaker initialized: spread={spread_threshold_bps}bps, "
            f"latency={latency_threshold_ms}ms, pause={default_pause_seconds}s"
        )

    def check_spread(self, pair: str, spread_bps: float) -> tuple[bool, Optional[str]]:
        """
        Check if spread exceeds threshold.

        Args:
            pair: Trading pair
            spread_bps: Measured spread in bps

        Returns:
            Tuple of (can_trade, error_message)
        """
        breaker_key = f"spread_{pair}"

        # Check if breaker is already tripped
        if breaker_key in self.breakers:
            status = self.breakers[breaker_key]
            if status.is_tripped and status.resume_time:
                if datetime.utcnow() < status.resume_time:
                    remaining = (status.resume_time - datetime.utcnow()).total_seconds()
                    return False, f"Spread breaker active for {pair} (resumes in {remaining:.0f}s)"
                else:
                    # Breaker expired, clear it
                    self._clear_breaker(breaker_key)

        # Check threshold
        if spread_bps > self.spread_threshold_bps:
            self._trip_breaker(
                breaker_key=breaker_key,
                breaker_type="spread",
                pair=pair,
                reason=f"Spread {spread_bps:.2f}bps > threshold {self.spread_threshold_bps:.2f}bps",
                details={"spread_bps": spread_bps, "threshold_bps": self.spread_threshold_bps},
                pause_seconds=self.default_pause_seconds
            )
            return False, f"Spread circuit tripped for {pair}: {spread_bps:.2f}bps"

        return True, None

    def check_latency(self, pair: str, latency_ms: float) -> tuple[bool, Optional[str]]:
        """
        Check if latency exceeds threshold.

        Args:
            pair: Trading pair
            latency_ms: Measured latency in ms

        Returns:
            Tuple of (can_trade, error_message)
        """
        breaker_key = f"latency_{pair}"

        # Check if breaker is already tripped
        if breaker_key in self.breakers:
            status = self.breakers[breaker_key]
            if status.is_tripped and status.resume_time:
                if datetime.utcnow() < status.resume_time:
                    remaining = (status.resume_time - datetime.utcnow()).total_seconds()
                    return False, f"Latency breaker active for {pair} (resumes in {remaining:.0f}s)"
                else:
                    self._clear_breaker(breaker_key)

        # Check threshold
        if latency_ms > self.latency_threshold_ms:
            self._trip_breaker(
                breaker_key=breaker_key,
                breaker_type="latency",
                pair=pair,
                reason=f"Latency {latency_ms:.0f}ms > threshold {self.latency_threshold_ms:.0f}ms",
                details={"latency_ms": latency_ms, "threshold_ms": self.latency_threshold_ms},
                pause_seconds=self.default_pause_seconds
            )
            return False, f"Latency circuit tripped for {pair}: {latency_ms:.0f}ms"

        return True, None

    def _trip_breaker(
        self,
        breaker_key: str,
        breaker_type: str,
        pair: str,
        reason: str,
        details: Dict[str, Any],
        pause_seconds: int
    ):
        """
        Trip circuit breaker and pause entries.

        Args:
            breaker_key: Unique breaker key
            breaker_type: Type of breaker
            pair: Trading pair
            reason: Trip reason
            details: Additional details
            pause_seconds: Pause duration in seconds
        """
        now = datetime.utcnow()
        resume_time = now + timedelta(seconds=pause_seconds)

        status = CircuitBreakerStatus(
            breaker_type=breaker_type,
            is_tripped=True,
            trip_time=now,
            resume_time=resume_time,
            pause_duration_seconds=pause_seconds,
            reason=reason,
            can_trade=False
        )

        self.breakers[breaker_key] = status

        # Publish event to Redis
        if self.redis:
            event = {
                "event": "circuit_breaker_tripped",
                "breaker_type": breaker_type,
                "pair": pair,
                "reason": reason,
                "timestamp": now.isoformat(),
                "resume_time": resume_time.isoformat(),
                "pause_seconds": pause_seconds,
                **details
            }

            try:
                self.redis.xadd("metrics:circuit_breakers", event)
                self.redis.xadd("kraken:status", {"status": "circuit_breaker", **event})
            except Exception as e:
                self.logger.error(f"Failed to publish circuit breaker event: {e}")

        self.logger.error(f"⚠️ Circuit breaker tripped: {breaker_type} on {pair} - {reason}")

    def _clear_breaker(self, breaker_key: str):
        """Clear tripped breaker"""
        if breaker_key in self.breakers:
            status = self.breakers[breaker_key]

            # Publish recovery event
            if self.redis:
                event = {
                    "event": "circuit_breaker_cleared",
                    "breaker_type": status.breaker_type,
                    "timestamp": datetime.utcnow().isoformat(),
                    "was_tripped_at": status.trip_time.isoformat() if status.trip_time else None
                }

                try:
                    self.redis.xadd("metrics:circuit_breakers", event)
                    self.redis.xadd("kraken:status", {"status": "circuit_breaker_cleared", **event})
                except Exception as e:
                    self.logger.error(f"Failed to publish circuit breaker clear event: {e}")

            self.logger.info(f"✅ Circuit breaker cleared: {breaker_key}")
            del self.breakers[breaker_key]

    def get_status(self, breaker_key: str) -> Optional[CircuitBreakerStatus]:
        """Get status of specific breaker"""
        return self.breakers.get(breaker_key)

    def get_all_active(self) -> Dict[str, CircuitBreakerStatus]:
        """Get all active breakers"""
        return {k: v for k, v in self.breakers.items() if v.is_tripped}


# =============================================================================
# INTEGRATED SAFETY CONTROLLER
# =============================================================================


@dataclass
class SafetyCheckResult:
    """Comprehensive safety check result"""
    can_trade: bool
    mode: TradingMode
    is_emergency_stop: bool
    is_pair_allowed: bool
    is_notional_valid: bool
    are_circuits_clear: bool
    errors: List[str]
    warnings: List[str]


class SafetyController:
    """
    Integrated safety controller for J1-J3.

    Combines:
    - J1: MODE switch + LIVE confirmation + emergency stop
    - J2: Pair whitelist + notional caps
    - J3: Circuit breakers with pause
    """

    def __init__(self, redis_client: Optional[redis.Redis] = None, config_path: Optional[Path] = None):
        """
        Initialize safety controller.

        Args:
            redis_client: Redis client
            config_path: Path to kraken.yaml
        """
        self.mode_switch = ModeSwitch(redis_client)
        self.emergency_stop = EmergencyKillSwitch(redis_client)
        self.pair_enforcer = PairWhitelistEnforcer(config_path)
        self.circuit_breaker = CircuitBreaker(redis_client)

        self.logger = logging.getLogger(f"{__name__}.SafetyController")
        self.logger.info("SafetyController initialized (J1-J3 complete)")

    def check_can_enter_trade(
        self,
        pair: str,
        notional_usd: float,
        spread_bps: Optional[float] = None,
        latency_ms: Optional[float] = None
    ) -> SafetyCheckResult:
        """
        Comprehensive safety check before entering trade.

        Args:
            pair: Trading pair
            notional_usd: Order notional in USD
            spread_bps: Current spread in bps (optional)
            latency_ms: Current latency in ms (optional)

        Returns:
            SafetyCheckResult with all check results
        """
        errors = []
        warnings = []

        # J1: Check MODE
        mode_config = self.mode_switch.get_mode_config()
        if mode_config.errors:
            errors.extend(mode_config.errors)

        # J1: Check emergency stop
        emergency_status = self.emergency_stop.get_status()
        if emergency_status.is_active:
            errors.append(f"Emergency stop active ({emergency_status.source}): {emergency_status.reason}")

        # J2: Check pair whitelist
        pair_allowed = self.pair_enforcer.is_pair_allowed(pair)
        if not pair_allowed:
            errors.append(f"Pair '{pair}' not in whitelist")

        # J2: Check notional limits
        notional_valid, notional_error = self.pair_enforcer.check_notional(pair, notional_usd)
        if not notional_valid:
            errors.append(notional_error)

        # J3: Check circuit breakers
        circuits_clear = True

        if spread_bps is not None:
            spread_ok, spread_error = self.circuit_breaker.check_spread(pair, spread_bps)
            if not spread_ok:
                errors.append(spread_error)
                circuits_clear = False

        if latency_ms is not None:
            latency_ok, latency_error = self.circuit_breaker.check_latency(pair, latency_ms)
            if not latency_ok:
                errors.append(latency_error)
                circuits_clear = False

        # Warnings
        if mode_config.is_live:
            warnings.append("LIVE trading mode - real money at risk")

        can_trade = (len(errors) == 0)

        return SafetyCheckResult(
            can_trade=can_trade,
            mode=mode_config.mode,
            is_emergency_stop=emergency_status.is_active,
            is_pair_allowed=pair_allowed,
            is_notional_valid=notional_valid,
            are_circuits_clear=circuits_clear,
            errors=errors,
            warnings=warnings
        )

    def check_can_exit_trade(self, pair: str) -> SafetyCheckResult:
        """
        Check if exits are allowed (always true except in extreme cases).

        Args:
            pair: Trading pair

        Returns:
            SafetyCheckResult (exits always allowed)
        """
        mode_config = self.mode_switch.get_mode_config()

        return SafetyCheckResult(
            can_trade=True,  # Exits always allowed
            mode=mode_config.mode,
            is_emergency_stop=False,
            is_pair_allowed=True,
            is_notional_valid=True,
            are_circuits_clear=True,
            errors=[],
            warnings=["Exit operations are always allowed"]
        )
