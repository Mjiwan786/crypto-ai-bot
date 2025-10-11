#!/usr/bin/env python3
"""
Canonical Redis stream contracts with Pydantic v2 validators.

This module defines the standard message schemas for Redis streams used
throughout the trading system. All publishers and consumers must use these
contracts to ensure data consistency and type safety.

**Redis Streams:**
- `signals:paper` - Paper trading signals
- `signals:live` - Live trading signals
- `metrics:latency` - System latency metrics
- `status:health` - Component health checks

**Features:**
- Pydantic v2 validators for type safety
- Clear error messages for invalid payloads
- Automatic type coercion where safe
- Comprehensive documentation for each field

**Usage:**
    from agents.core.contracts import SignalPayload, MetricsLatencyPayload, HealthStatusPayload

    # Create and validate signal payload
    signal = SignalPayload(
        id="sig_001",
        ts=1234567890.123,
        pair="BTC/USD",
        side="buy",
        entry=50000.0,
        sl=49000.0,
        tp=52000.0,
        strategy="momentum",
        confidence=0.85
    )

    # Validate from dict (e.g., from Redis)
    data = redis.xread("signals:paper")
    signal = SignalPayload.model_validate(data)

    # Convert to dict for Redis
    payload_dict = signal.model_dump()
"""

from __future__ import annotations

from typing import Any, Dict, Literal
from datetime import datetime

try:
    from pydantic import BaseModel, Field, field_validator, ConfigDict
    HAS_PYDANTIC = True
except ImportError:
    HAS_PYDANTIC = False
    # Fallback for when Pydantic is not available
    class BaseModel:  # type: ignore
        pass

    def Field(*args, **kwargs):  # type: ignore
        return None

    def field_validator(*args, **kwargs):  # type: ignore
        def decorator(func):
            return func
        return decorator

    def ConfigDict(**kwargs):  # type: ignore
        return {}


# ============================================================================
# Signal Contracts (signals:paper and signals:live)
# ============================================================================

class SignalPayload(BaseModel):
    """
    Canonical payload for Redis streams: signals:paper and signals:live.

    Represents a trading signal with entry/exit parameters and metadata.
    All fields are required and validated for type safety.

    **Stream Usage:**
    - `signals:paper` - Paper trading mode (no real execution)
    - `signals:live` - Live trading mode (real execution)

    **Field Constraints:**
    - id: Non-empty string identifier (e.g., "sig_001", "momentum_20251011_123045")
    - ts: Unix timestamp (seconds since epoch, can include fractional seconds)
    - pair: Trading pair in "BASE/QUOTE" format (e.g., "BTC/USD", "ETH/USDT")
    - side: Either "buy" or "sell" (lowercase)
    - entry: Entry price (positive float)
    - sl: Stop loss price (positive float, must be below entry for buy, above for sell)
    - tp: Take profit price (positive float, must be above entry for buy, below for sell)
    - strategy: Strategy name (non-empty string)
    - confidence: Confidence score between 0.0 and 1.0 inclusive

    **Examples:**
        >>> signal = SignalPayload(
        ...     id="momentum_001",
        ...     ts=1234567890.123,
        ...     pair="BTC/USD",
        ...     side="buy",
        ...     entry=50000.0,
        ...     sl=49000.0,
        ...     tp=52000.0,
        ...     strategy="momentum",
        ...     confidence=0.85
        ... )
        >>> signal.pair
        'BTC/USD'
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        frozen=False,
    )

    id: str = Field(
        ...,
        description="Unique signal identifier",
        min_length=1,
        examples=["sig_001", "momentum_20251011_123045"]
    )

    ts: float = Field(
        ...,
        description="Unix timestamp (seconds since epoch, with optional fractional seconds)",
        gt=0,
        examples=[1234567890.123, 1697000000.0]
    )

    pair: str = Field(
        ...,
        description="Trading pair in BASE/QUOTE format (e.g., 'BTC/USD', 'ETH/USDT')",
        min_length=3,
        examples=["BTC/USD", "ETH/USDT", "XRP/EUR"]
    )

    side: Literal["buy", "sell"] = Field(
        ...,
        description="Trade direction: 'buy' or 'sell' (lowercase only)",
        examples=["buy", "sell"]
    )

    entry: float = Field(
        ...,
        description="Entry price (must be positive)",
        gt=0,
        examples=[50000.0, 1800.5, 0.25]
    )

    sl: float = Field(
        ...,
        description="Stop loss price (must be positive)",
        gt=0,
        examples=[49000.0, 1750.0, 0.20]
    )

    tp: float = Field(
        ...,
        description="Take profit price (must be positive)",
        gt=0,
        examples=[52000.0, 1900.0, 0.30]
    )

    strategy: str = Field(
        ...,
        description="Strategy name that generated this signal",
        min_length=1,
        examples=["momentum", "mean_reversion", "breakout", "ml_ensemble"]
    )

    confidence: float = Field(
        ...,
        description="Confidence score (0.0 to 1.0 inclusive)",
        ge=0.0,
        le=1.0,
        examples=[0.85, 0.92, 0.75]
    )

    @field_validator("pair")
    @classmethod
    def validate_pair_format(cls, v: str) -> str:
        """Validate trading pair format is BASE/QUOTE with uppercase."""
        if not v:
            raise ValueError("Trading pair cannot be empty")

        # Convert to uppercase for consistency
        v = v.upper()

        if "/" not in v:
            raise ValueError(
                f"Trading pair must be in BASE/QUOTE format (e.g., 'BTC/USD'), got: {v}"
            )

        parts = v.split("/")
        if len(parts) != 2:
            raise ValueError(
                f"Trading pair must have exactly one '/' separator, got: {v}"
            )

        base, quote = parts
        if not base or not quote:
            raise ValueError(
                f"Both base and quote must be non-empty, got: {v}"
            )

        return v

    @field_validator("sl", "tp")
    @classmethod
    def validate_price_levels(cls, v: float, info) -> float:
        """Validate stop loss and take profit prices are sensible."""
        if v <= 0:
            raise ValueError(f"{info.field_name} must be positive, got: {v}")

        # Additional validation after all fields are set (done in model_validator)
        return v

    def validate_price_relationships(self) -> None:
        """
        Validate price relationships between entry, SL, and TP.

        For buy signals:
        - SL must be below entry
        - TP must be above entry

        For sell signals:
        - SL must be above entry
        - TP must be below entry

        Raises:
            ValueError: If price relationships are invalid
        """
        if self.side == "buy":
            if self.sl >= self.entry:
                raise ValueError(
                    f"Buy signal: stop loss ({self.sl}) must be below entry ({self.entry})"
                )
            if self.tp <= self.entry:
                raise ValueError(
                    f"Buy signal: take profit ({self.tp}) must be above entry ({self.entry})"
                )
        elif self.side == "sell":
            if self.sl <= self.entry:
                raise ValueError(
                    f"Sell signal: stop loss ({self.sl}) must be above entry ({self.entry})"
                )
            if self.tp >= self.entry:
                raise ValueError(
                    f"Sell signal: take profit ({self.tp}) must be below entry ({self.entry})"
                )

    def model_post_init(self, __context: Any) -> None:
        """Run additional validation after model initialization."""
        # Validate price relationships
        self.validate_price_relationships()


# ============================================================================
# Metrics Contracts (metrics:latency)
# ============================================================================

class MetricsLatencyPayload(BaseModel):
    """
    Canonical payload for Redis stream: metrics:latency.

    Represents latency metrics for a specific component over a time window.
    Used for monitoring and alerting on system performance.

    **Stream Usage:**
    - `metrics:latency` - Latency measurements for all system components

    **Field Constraints:**
    - component: Non-empty component identifier (e.g., "redis", "kraken_api", "signal_processor")
    - p50: 50th percentile latency in milliseconds (non-negative)
    - p95: 95th percentile latency in milliseconds (non-negative, must be >= p50)
    - window_s: Time window in seconds over which metrics were collected (positive)

    **Examples:**
        >>> metrics = MetricsLatencyPayload(
        ...     component="kraken_api",
        ...     p50=45.2,
        ...     p95=128.7,
        ...     window_s=60
        ... )
        >>> metrics.component
        'kraken_api'
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        frozen=False,
    )

    component: str = Field(
        ...,
        description="Component name (e.g., 'redis', 'kraken', 'signal_processor')",
        min_length=1,
        examples=["redis", "kraken_api", "signal_processor", "execution_agent"]
    )

    p50: float = Field(
        ...,
        description="50th percentile latency in milliseconds",
        ge=0,
        examples=[12.5, 45.2, 0.8]
    )

    p95: float = Field(
        ...,
        description="95th percentile latency in milliseconds",
        ge=0,
        examples=[25.0, 128.7, 2.3]
    )

    window_s: int = Field(
        ...,
        description="Time window in seconds over which metrics were collected",
        gt=0,
        examples=[60, 300, 3600]
    )

    @field_validator("p95")
    @classmethod
    def validate_p95_greater_than_p50(cls, v: float, info) -> float:
        """Validate that p95 >= p50 (if p50 is available)."""
        # Note: This validation only works if p50 is already set
        # Full validation happens in model_post_init
        return v

    def model_post_init(self, __context: Any) -> None:
        """Run additional validation after model initialization."""
        if self.p95 < self.p50:
            raise ValueError(
                f"p95 ({self.p95}ms) must be >= p50 ({self.p50}ms)"
            )


# ============================================================================
# Health Status Contracts (status:health)
# ============================================================================

class HealthStatusPayload(BaseModel):
    """
    Canonical payload for Redis stream: status:health.

    Represents overall system health status with individual component checks.
    Used for monitoring, alerting, and dashboards.

    **Stream Usage:**
    - `status:health` - System health checks from all components

    **Field Constraints:**
    - ok: Boolean indicating overall health status
    - checks: Dictionary mapping component names to their health status (True/False)
           Must include at least one component (e.g., "redis", "kraken")

    **Examples:**
        >>> health = HealthStatusPayload(
        ...     ok=True,
        ...     checks={
        ...         "redis": True,
        ...         "kraken": True,
        ...         "postgres": True
        ...     }
        ... )
        >>> health.ok
        True

        >>> # Failed health check
        >>> health_failed = HealthStatusPayload(
        ...     ok=False,
        ...     checks={
        ...         "redis": True,
        ...         "kraken": False,  # API down
        ...         "postgres": True
        ...     }
        ... )
        >>> health_failed.checks["kraken"]
        False
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        frozen=False,
    )

    ok: bool = Field(
        ...,
        description="Overall health status (True if all checks pass, False otherwise)",
        examples=[True, False]
    )

    checks: Dict[str, bool] = Field(
        ...,
        description="Component health checks mapping component name to status",
        min_length=1,
        examples=[
            {"redis": True, "kraken": True, "postgres": True},
            {"redis": True, "kraken": False, "postgres": True}
        ]
    )

    @field_validator("checks")
    @classmethod
    def validate_checks_not_empty(cls, v: Dict[str, bool]) -> Dict[str, bool]:
        """Validate that checks dictionary is not empty."""
        if not v:
            raise ValueError("Health checks dictionary cannot be empty")

        # Validate all component names are non-empty strings
        for component_name in v.keys():
            if not component_name or not isinstance(component_name, str):
                raise ValueError(
                    f"Component names must be non-empty strings, got: {component_name}"
                )

        # Validate all values are booleans
        for component_name, status in v.items():
            if not isinstance(status, bool):
                raise ValueError(
                    f"Component status must be boolean, got {type(status).__name__} for {component_name}"
                )

        return v

    def model_post_init(self, __context: Any) -> None:
        """Run additional validation after model initialization."""
        # Validate that 'ok' matches the actual check results
        all_checks_pass = all(self.checks.values())

        if self.ok and not all_checks_pass:
            # Warning: ok=True but some checks failed
            # This is allowed but logged as a warning
            import logging
            logger = logging.getLogger(__name__)
            failed_checks = [name for name, status in self.checks.items() if not status]
            logger.warning(
                f"Health status marked as 'ok=True' but some checks failed: {failed_checks}"
            )


# ============================================================================
# Validation Utilities
# ============================================================================

def validate_signal_payload(data: Dict[str, Any]) -> SignalPayload:
    """
    Validate signal payload from dict.

    Args:
        data: Raw payload dictionary

    Returns:
        Validated SignalPayload instance

    Raises:
        ValidationError: If payload is invalid with clear error message

    Examples:
        >>> data = {
        ...     "id": "sig_001",
        ...     "ts": 1234567890.0,
        ...     "pair": "BTC/USD",
        ...     "side": "buy",
        ...     "entry": 50000.0,
        ...     "sl": 49000.0,
        ...     "tp": 52000.0,
        ...     "strategy": "momentum",
        ...     "confidence": 0.85
        ... }
        >>> signal = validate_signal_payload(data)
        >>> signal.pair
        'BTC/USD'
    """
    return SignalPayload.model_validate(data)


def validate_metrics_latency_payload(data: Dict[str, Any]) -> MetricsLatencyPayload:
    """
    Validate metrics latency payload from dict.

    Args:
        data: Raw payload dictionary

    Returns:
        Validated MetricsLatencyPayload instance

    Raises:
        ValidationError: If payload is invalid with clear error message

    Examples:
        >>> data = {
        ...     "component": "kraken_api",
        ...     "p50": 45.2,
        ...     "p95": 128.7,
        ...     "window_s": 60
        ... }
        >>> metrics = validate_metrics_latency_payload(data)
        >>> metrics.component
        'kraken_api'
    """
    return MetricsLatencyPayload.model_validate(data)


def validate_health_status_payload(data: Dict[str, Any]) -> HealthStatusPayload:
    """
    Validate health status payload from dict.

    Args:
        data: Raw payload dictionary

    Returns:
        Validated HealthStatusPayload instance

    Raises:
        ValidationError: If payload is invalid with clear error message

    Examples:
        >>> data = {
        ...     "ok": True,
        ...     "checks": {
        ...         "redis": True,
        ...         "kraken": True
        ...     }
        ... }
        >>> health = validate_health_status_payload(data)
        >>> health.ok
        True
    """
    return HealthStatusPayload.model_validate(data)


# ============================================================================
# Export public API
# ============================================================================

__all__ = [
    "SignalPayload",
    "MetricsLatencyPayload",
    "HealthStatusPayload",
    "validate_signal_payload",
    "validate_metrics_latency_payload",
    "validate_health_status_payload",
    "HAS_PYDANTIC",
]
