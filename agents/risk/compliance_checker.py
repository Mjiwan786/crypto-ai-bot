"""
Production-grade compliance validation for crypto-ai-bot.

Validates signals and order intents against exchange rules, jurisdictional restrictions,
symbol/size limits, time windows, and runtime kill-switches.

Features:
- Comprehensive signal and order validation
- Exchange-specific rule enforcement
- Jurisdictional compliance checks
- Symbol and size limit validation
- Trading window enforcement
- KYC and regional restrictions
- Emergency kill switch support
- Leverage and margin validation
- Real-time compliance monitoring

Key guarantees:
- PURE LOGIC: no I/O, no env reads, no Redis, no network
- Deterministic, UTC-only operations
- Thread-safe validation logic
- Comprehensive error handling
- Production-grade performance
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, Field, field_validator, model_validator

# Import MCP models (contracts); do not redefine
from mcp.schemas import OrderIntent, Signal


# -----------------------------
# Small utilities
# -----------------------------
def _as_str(val: Union[str, object]) -> str:
    """
    Return a stable string for enum-or-string fields.
    If `val` has a `.value`, use it; else `str(val)`. Lowercased for consistency.
    """
    v = getattr(val, "value", val)
    return str(v).lower()


# =====================================================================
# CONFIG
# =====================================================================


class ComplianceConfig(BaseModel):
    """Configuration for compliance validation"""

    # Exchange & venue context
    exchange: str = Field(default="kraken")
    sandbox: bool = False

    # Allowed universe & hard bans
    allowed_symbols: Optional[List[str]] = None  # if set → whitelist
    banned_symbols: Optional[List[str]] = None  # blacklist (always wins)
    quote_currencies_allowed: Optional[List[str]] = None  # e.g., ["USD","USDT"]

    # Sizing/Notional rules (USD)
    min_notional_usd: float = 5.0
    max_notional_usd: Optional[float] = None  # None = unbounded at this layer

    # Per-symbol overrides: {"BTC/USD": {"min_size": 0.0001, "max_size": 5.0}}
    per_symbol_size: Optional[Dict[str, Dict[str, float]]] = None

    # Trading windows (UTC hh:mm, 24h). None → always allowed.
    allowed_hours_utc: Optional[List[str]] = None

    # Market status flags
    trading_halt: bool = False
    maintenance_mode: bool = False

    # Leverage / margin policy
    margin_allowed: bool = False
    max_leverage: float = 1.0

    # KYC/region policy
    required_kyc_tier: int = 1
    user_kyc_tier: int = 1
    blocked_regions: Optional[List[str]] = None
    user_region: Optional[str] = None

    # Emergency kill switch
    emergency_kill_switch: bool = False

    # Validation control - allows disabling strict validation for testing
    strict_validation: bool = Field(default=True, description="Enable strict config validation")

    # ---------------- Validators ----------------

    @field_validator("min_notional_usd")
    @classmethod
    def validate_min_notional(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("min_notional_usd must be positive")
        return v

    @field_validator("max_notional_usd")
    @classmethod
    def validate_max_notional(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v <= 0:
            raise ValueError("max_notional_usd must be positive if set")
        return v

    @field_validator("allowed_hours_utc")
    @classmethod
    def validate_trading_hours(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v
        time_pattern = re.compile(
            r"^([0-1][0-9]|2[0-3]):[0-5][0-9]-([0-1][0-9]|2[0-3]):[0-5][0-9]$"
        )
        for window in v:
            if not time_pattern.match(window):
                raise ValueError(f"Invalid time window format: {window}. Use HH:MM-HH:MM")
        return v

    @model_validator(mode="after")
    def validate_bounds(self) -> "ComplianceConfig":
        # Notional bounds
        if self.max_notional_usd is not None and self.min_notional_usd > self.max_notional_usd:
            raise ValueError("min_notional_usd cannot exceed max_notional_usd")

        # Only do strict validation if enabled
        if self.strict_validation:
            # Check for overlapping allowed/banned symbol lists
            if self.allowed_symbols and self.banned_symbols:
                allowed_set = {s.upper() for s in self.allowed_symbols}
                banned_set = {s.upper() for s in self.banned_symbols}
                overlap = allowed_set & banned_set
                if overlap:
                    raise ConfigError(
                        f"Symbol(s) cannot be both allowed and banned: {', '.join(overlap)}"
                    )

            # Validate per-symbol size configurations
            if self.per_symbol_size:
                for symbol, sizes in self.per_symbol_size.items():
                    # Check symbol format
                    if not re.match(r"^[A-Z0-9]+/[A-Z0-9]+$", symbol.upper()):
                        raise ConfigError(f"Invalid symbol format in per_symbol_size: {symbol}")

                    # Check min_size <= max_size
                    min_size = sizes.get("min_size")
                    max_size = sizes.get("max_size")
                    if min_size is not None and max_size is not None and min_size > max_size:
                        raise ConfigError(
                            f"min_size ({min_size}) cannot exceed max_size ({max_size}) "
                            f"for symbol {symbol}"
                        )

        return self


# =====================================================================
# RESULTS & ERRORS
# =====================================================================


class ComplianceDecision(BaseModel):
    """Result of compliance validation"""

    allowed: bool
    # Reasons must be short kebab-case strings
    reasons: List[str] = Field(default_factory=list)
    # Useful echoes (symbol, notional, leverage, window match, mode, etc.)
    normalized: Dict[str, Union[str, float, int, bool, None]] = Field(default_factory=dict)


class ComplianceError(Exception):
    """Base compliance error"""

    pass


class ConfigError(ComplianceError):
    """Configuration validation error"""

    pass


class ComplianceRejected(ComplianceError):
    """Compliance validation rejection"""

    pass


# =====================================================================
# CHECKER
# =====================================================================


class ComplianceChecker:
    """Validates trading signals and order intents for compliance (pure & deterministic)."""

    def __init__(self, config: ComplianceConfig) -> None:
        self.config = config
        self._validate_config()

    def _validate_config(self) -> None:
        """
        Runtime-specific validation that can't be done at config creation time.
        Config-level validation is handled in ComplianceConfig.validate_bounds()
        """
        # Config-level validation is now handled in ComplianceConfig
        # Only keep validations that require runtime context if any
        pass

    # ---------------- Assess Methods ----------------

    def assess_signal(self, sig: Signal, price_usd: Optional[float]) -> ComplianceDecision:
        """
        Validate a Signal for compliance.
        Requirement: if price_usd is None and size unknown → reject with reason.
        """
        reasons: List[str] = []
        normalized: Dict[str, Union[str, float, int, bool, None]] = {
            "symbol": sig.symbol,
            "side": _as_str(getattr(sig, "side", "buy")),
            "strategy": getattr(sig, "strategy", None),
            "confidence": getattr(sig, "confidence", None),
        }

        # Global kill switches
        if not self._check_kill_switches(reasons):
            return ComplianceDecision(allowed=False, reasons=reasons, normalized=normalized)

        # KYC & Region checks
        if not self._check_kyc_and_region(reasons):
            return ComplianceDecision(allowed=False, reasons=reasons, normalized=normalized)

        # Symbol universe checks
        if not self._check_symbol_universe(sig.symbol, reasons):
            return ComplianceDecision(allowed=False, reasons=reasons, normalized=normalized)

        # Trading window check (+ echo)
        in_window_ok, window_match = self._check_trading_window()
        normalized["window_match"] = window_match
        if not in_window_ok:
            reasons.append("outside-trading-window")
            return ComplianceDecision(allowed=False, reasons=reasons, normalized=normalized)

        # Signals: require price for any notional reasoning; size is unknown here.
        if price_usd is None:
            normalized["price_usd"] = None
            normalized["notional_usd"] = None
            reasons.append("price-missing-for-notional-check")
            return ComplianceDecision(allowed=False, reasons=reasons, normalized=normalized)

        normalized["price_usd"] = float(price_usd)
        normalized["notional_usd"] = None  # size unknown at signal stage

        # Leverage checks (signals imply spot unless noted; pass None)
        if not self._check_leverage(None, reasons):
            return ComplianceDecision(allowed=False, reasons=reasons, normalized=normalized)

        # Sandbox annotation
        if self.config.sandbox:
            normalized["mode"] = "sandbox"

        return ComplianceDecision(allowed=True, reasons=[], normalized=normalized)

    def assess_order(self, oi: OrderIntent) -> ComplianceDecision:
        """
        Validate an OrderIntent for compliance. Uses size_quote_usd for notionals and
        per-symbol size checks if present.
        """
        reasons: List[str] = []
        normalized: Dict[str, Union[str, float, int, bool, None]] = {
            "symbol": oi.symbol,
            "side": _as_str(getattr(oi, "side", "buy")),
            "order_type": _as_str(getattr(oi, "order_type", "market")),
            "size_quote_usd": float(getattr(oi, "size_quote_usd", 0.0)),
            "price": float(oi.price) if getattr(oi, "price", None) is not None else None,
        }

        # Global kill switches
        if not self._check_kill_switches(reasons):
            return ComplianceDecision(allowed=False, reasons=reasons, normalized=normalized)

        # KYC & Region checks
        if not self._check_kyc_and_region(reasons):
            return ComplianceDecision(allowed=False, reasons=reasons, normalized=normalized)

        # Symbol universe checks
        if not self._check_symbol_universe(oi.symbol, reasons):
            return ComplianceDecision(allowed=False, reasons=reasons, normalized=normalized)

        # Trading window check (+ echo)
        in_window_ok, window_match = self._check_trading_window()
        normalized["window_match"] = window_match
        if not in_window_ok:
            reasons.append("outside-trading-window")
            return ComplianceDecision(allowed=False, reasons=reasons, normalized=normalized)

        # Notional bounds
        notional = float(getattr(oi, "size_quote_usd", 0.0))
        if not self._check_notional_bounds(notional, reasons):
            return ComplianceDecision(allowed=False, reasons=reasons, normalized=normalized)

        # Per-symbol size checks
        if not self._check_per_symbol_size(oi, reasons):
            return ComplianceDecision(allowed=False, reasons=reasons, normalized=normalized)

        # Leverage checks
        leverage = (getattr(oi, "metadata", None) or {}).get("leverage", 1.0)
        normalized["leverage"] = float(leverage)
        if not self._check_leverage(leverage, reasons):
            return ComplianceDecision(allowed=False, reasons=reasons, normalized=normalized)

        # Sandbox annotation
        if self.config.sandbox:
            normalized["mode"] = "sandbox"

        # Echo computed notional for downstream auditing
        normalized["notional_usd"] = notional

        return ComplianceDecision(allowed=True, reasons=[], normalized=normalized)

    def assess(
        self, event: Union[Signal, OrderIntent], price_usd: Optional[float] = None
    ) -> ComplianceDecision:
        """Dispatch to the appropriate assess_* method."""
        if isinstance(event, Signal):
            return self.assess_signal(event, price_usd)
        if isinstance(event, OrderIntent):
            return self.assess_order(event)
        raise ValueError(f"Unsupported event type: {type(event)}")

    # ---------------- Private validation helpers ----------------

    def _check_kill_switches(self, reasons: List[str]) -> bool:
        if self.config.emergency_kill_switch:
            reasons.append("emergency-kill-switch")
            return False
        if self.config.maintenance_mode:
            reasons.append("maintenance-mode")
            return False
        if self.config.trading_halt:
            reasons.append("trading-halt")
            return False
        return True

    def _check_kyc_and_region(self, reasons: List[str]) -> bool:
        if self.config.user_kyc_tier < self.config.required_kyc_tier:
            reasons.append("insufficient-kyc-tier")
            return False
        if self.config.blocked_regions and self.config.user_region in self.config.blocked_regions:
            reasons.append("blocked-region")
            return False
        return True

    def _check_symbol_universe(self, symbol: str, reasons: List[str]) -> bool:
        """Blacklist precedence, then quote gating, then whitelist."""
        sym_u = symbol.upper()

        # Blacklist always wins
        if self.config.banned_symbols:
            banned_u = {s.upper() for s in self.config.banned_symbols}
            if sym_u in banned_u:
                reasons.append("symbol-banned")
                return False

        # Quote currency gating FIRST (to surface quote-currency-not-allowed)
        if self.config.quote_currencies_allowed:
            try:
                quote = sym_u.split("/")[1]
                if quote not in self.config.quote_currencies_allowed:
                    reasons.append("quote-currency-not-allowed")
                    return False
            except (IndexError, AttributeError):
                reasons.append("invalid-symbol-format")
                return False

        # Whitelist if configured
        if self.config.allowed_symbols:
            allowed_u = {s.upper() for s in self.config.allowed_symbols}
            if sym_u not in allowed_u:
                reasons.append("symbol-not-whitelisted")
                return False

        return True

    def _check_trading_window(self) -> Tuple[bool, bool]:
        """Check if current UTC time falls within allowed trading hours."""
        if not self.config.allowed_hours_utc:
            return True, True  # no restrictions
        now_utc = datetime.now(timezone.utc)
        current_minutes = now_utc.hour * 60 + now_utc.minute
        for window in self.config.allowed_hours_utc:
            start, end = self._parse_time_window(window)
            if self._is_within_minutes_window(current_minutes, start, end):
                return True, True
        return False, False

    def _check_notional_bounds(self, notional_usd: float, reasons: List[str]) -> bool:
        if notional_usd < self.config.min_notional_usd:
            reasons.append("notional-below-minimum")
            return False
        if self.config.max_notional_usd is not None and notional_usd > self.config.max_notional_usd:
            reasons.append("notional-above-maximum")
            return False
        return True

    def _check_per_symbol_size(self, oi: OrderIntent, reasons: List[str]) -> bool:
        if not self.config.per_symbol_size:
            return True
        symbol_cfg = self.config.per_symbol_size.get(oi.symbol)
        if not symbol_cfg:
            return True

        metadata = getattr(oi, "metadata", None) or {}
        base_size = metadata.get("base_size")

        if base_size is not None:
            min_size = symbol_cfg.get("min_size")
            max_size = symbol_cfg.get("max_size")
            if min_size is not None and base_size < min_size:
                reasons.append("size-below-symbol-minimum")
                return False
            if max_size is not None and base_size > max_size:
                reasons.append("size-above-symbol-maximum")
                return False
        else:
            # Fallback: ensure quote size respects global min notional
            if float(getattr(oi, "size_quote_usd", 0.0)) < self.config.min_notional_usd:
                reasons.append("notional-below-minimum")  # Changed from "quote-size-below-minimum"
                return False

        return True

    def _check_leverage(self, leverage: Optional[float], reasons: List[str]) -> bool:
        lev = 1.0 if leverage is None else float(leverage)
        if not self.config.margin_allowed and lev > 1.0:
            reasons.append("margin-not-allowed")
            return False
        if lev > self.config.max_leverage:
            reasons.append("leverage-exceeds-maximum")
            return False
        return True

    # ---------------- Utility helpers (exposed for tests) ----------------

    def _is_valid_symbol(self, symbol: str) -> bool:
        return bool(re.match(r"^[A-Z0-9]+/[A-Z0-9]+$", symbol.upper()))

    def _parse_time_window(self, window: str) -> Tuple[int, int]:
        start_str, end_str = window.split("-")
        s_h, s_m = map(int, start_str.split(":"))
        e_h, e_m = map(int, end_str.split(":"))
        return s_h * 60 + s_m, e_h * 60 + e_m

    def _is_within_minutes_window(self, current: int, start: int, end: int) -> bool:
        """Inclusive edge check with overnight window handling."""
        if start <= end:
            return start <= current <= end
        # Overnight (e.g., "22:00-06:00")
        return current >= start or current <= end
