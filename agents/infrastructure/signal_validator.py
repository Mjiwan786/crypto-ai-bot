"""
PRD-001 Section 5.2 Schema Validation

This module implements PRD-001 Section 5.2 schema validation with:
- Validate every signal with TradingSignal.model_validate() before Redis publish
- Catch Pydantic ValidationError and log at ERROR level with field details
- Emit Prometheus counter signal_schema_errors_total{field, error_type} on validation failures
- Reject invalid signals (do not publish to Redis)

Author: Crypto AI Bot Team
Version: 1.0.0
"""

from __future__ import annotations

import logging
from typing import Dict, Any, Optional, Tuple
from pydantic import ValidationError

from models.prd_signal_schema import TradingSignal

# PRD-001 Section 5.2: Prometheus metrics
try:
    from prometheus_client import Counter
    SIGNAL_SCHEMA_ERRORS = Counter(
        'signal_schema_errors_total',
        'Total signal schema validation errors by field and error type',
        ['field', 'error_type']
    )
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    SIGNAL_SCHEMA_ERRORS = None

logger = logging.getLogger(__name__)


class SignalValidator:
    """
    PRD-001 Section 5.2 compliant signal validator.

    Features:
    - Validate signals against TradingSignal schema before Redis publish
    - Log validation errors at ERROR level
    - Emit Prometheus metrics for validation failures
    - Reject invalid signals

    Usage:
        validator = SignalValidator()

        # Validate signal before publishing
        is_valid, validated_signal = validator.validate_signal(signal_dict)

        if is_valid:
            # Publish to Redis
            await redis_client.xadd("signals", validated_signal.model_dump())
        else:
            # Signal was rejected due to validation failure
            pass
    """

    def __init__(self):
        """Initialize PRD-compliant signal validator."""
        self.total_validations = 0
        self.total_failures = 0

        logger.info("SignalValidator initialized (PRD-001 Section 5.2)")

    def validate_signal(
        self,
        signal_dict: Dict[str, Any]
    ) -> Tuple[bool, Optional[TradingSignal]]:
        """
        PRD-001 Section 5.2: Validate signal with TradingSignal.model_validate().

        Steps:
        1. Validate signal with Pydantic TradingSignal model
        2. If validation fails:
           - Log at ERROR level with field details
           - Emit Prometheus counter
           - Return (False, None) to reject signal
        3. If validation passes:
           - Return (True, validated_signal)

        Args:
            signal_dict: Signal dictionary to validate

        Returns:
            (is_valid, validated_signal) tuple
            - is_valid: True if signal passes validation, False otherwise
            - validated_signal: TradingSignal instance if valid, None otherwise
        """
        self.total_validations += 1

        try:
            # PRD-001 Section 5.2: Validate with TradingSignal.model_validate()
            validated_signal = TradingSignal.model_validate(signal_dict)

            logger.debug(
                f"[SCHEMA VALIDATION PASS] Signal {validated_signal.signal_id} "
                f"({validated_signal.trading_pair} {validated_signal.side})"
            )

            return True, validated_signal

        except ValidationError as e:
            # PRD-001 Section 5.2: Validation failed
            self.total_failures += 1

            # PRD-001 Section 5.2: Log at ERROR level with field details
            error_details = self._extract_error_details(e)
            logger.error(
                f"[SCHEMA VALIDATION FAILED] Signal validation failed: {error_details}"
            )

            # PRD-001 Section 5.2: Emit Prometheus counter
            self._emit_prometheus_metrics(e)

            # PRD-001 Section 5.2: Reject invalid signal
            return False, None

        except Exception as e:
            # Unexpected error during validation
            self.total_failures += 1

            logger.error(
                f"[SCHEMA VALIDATION ERROR] Unexpected error during validation: {e}",
                exc_info=True
            )

            # Emit generic error metric
            if PROMETHEUS_AVAILABLE and SIGNAL_SCHEMA_ERRORS:
                SIGNAL_SCHEMA_ERRORS.labels(
                    field="unknown",
                    error_type="unexpected_error"
                ).inc()

            return False, None

    def _extract_error_details(self, validation_error: ValidationError) -> str:
        """
        Extract detailed error information from Pydantic ValidationError.

        Args:
            validation_error: Pydantic ValidationError

        Returns:
            Human-readable error details string
        """
        errors = validation_error.errors()
        error_lines = []

        for error in errors:
            field = ".".join(str(loc) for loc in error.get("loc", []))
            error_type = error.get("type", "unknown")
            msg = error.get("msg", "validation failed")

            error_lines.append(f"  - Field '{field}': {msg} (type: {error_type})")

        return "\n".join(error_lines)

    def _emit_prometheus_metrics(self, validation_error: ValidationError):
        """
        PRD-001 Section 5.2: Emit Prometheus counter for validation failures.

        Args:
            validation_error: Pydantic ValidationError
        """
        if not PROMETHEUS_AVAILABLE or not SIGNAL_SCHEMA_ERRORS:
            return

        errors = validation_error.errors()

        for error in errors:
            field = ".".join(str(loc) for loc in error.get("loc", []))
            error_type = error.get("type", "unknown")

            SIGNAL_SCHEMA_ERRORS.labels(
                field=field,
                error_type=error_type
            ).inc()

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get validator metrics.

        Returns:
            Dictionary with validation metrics
        """
        failure_rate = (
            self.total_failures / self.total_validations
            if self.total_validations > 0
            else 0.0
        )

        return {
            "total_validations": self.total_validations,
            "total_failures": self.total_failures,
            "failure_rate": failure_rate
        }

    def reset_stats(self):
        """Reset statistics counters."""
        self.total_validations = 0
        self.total_failures = 0
        logger.info("SignalValidator statistics reset")


# Singleton instance for convenience
_validator_instance: Optional[SignalValidator] = None


def get_signal_validator() -> SignalValidator:
    """
    Get singleton SignalValidator instance.

    Returns:
        SignalValidator instance
    """
    global _validator_instance

    if _validator_instance is None:
        _validator_instance = SignalValidator()

    return _validator_instance


def validate_signal_for_redis(signal_dict: Dict[str, Any]) -> Tuple[bool, Optional[TradingSignal]]:
    """
    Convenience function to validate signal before Redis publish.

    PRD-001 Section 5.2: This function should be called before every signal publish
    to Redis to ensure schema compliance.

    Args:
        signal_dict: Signal dictionary to validate

    Returns:
        (is_valid, validated_signal) tuple

    Example:
        >>> signal = {"signal_id": "test-001", ...}
        >>> is_valid, validated = validate_signal_for_redis(signal)
        >>> if is_valid:
        ...     await redis_client.xadd("signals", validated.model_dump())
    """
    validator = get_signal_validator()
    return validator.validate_signal(signal_dict)


# Export for convenience
__all__ = [
    "SignalValidator",
    "get_signal_validator",
    "validate_signal_for_redis",
]
