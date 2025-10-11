"""
SLO (Service Level Objective) definitions and thresholds for crypto-ai-bot.

This module provides a single source of truth for SLO thresholds and helper functions
for monitoring and alerting. SLOs define the expected performance characteristics
of the system and are used to trigger alerts when thresholds are breached.

Burn-in Window:
- SLOs are evaluated over a configurable time window (default: 72 hours)
- This window allows for system stabilization and reduces false positives
- Override via SLO_WINDOW_HOURS environment variable

Environment Detection:
- Uses merged configuration to determine if running in staging environment
- Staging environment has different thresholds and more lenient monitoring
"""

import os
from typing import Dict, Any
from config.loader import get_config

# =============================================================================
# SLO Thresholds (Staging Defaults)
# =============================================================================

# P95 publish latency should be under 500ms for real-time trading
P95_PUBLISH_LATENCY_MS = 500

# Stream lag should be minimal - consumers must keep up with producers
MAX_STREAM_LAG_SEC = 1  # "≈0" means consumers keep up

# Uptime target of 99.5% (allows for ~3.6 hours downtime per month)
UPTIME_TARGET = 0.995  # 99.5%

# Duplicate rate should be very low for data integrity
MAX_DUP_RATE = 0.001  # < 0.1%


# =============================================================================
# Helper Functions
# =============================================================================

def window_hours() -> int:
    """
    Get the SLO evaluation window in hours.
    
    Returns:
        int: Number of hours for SLO evaluation window (default: 72)
    """
    return int(os.getenv("SLO_WINDOW_HOURS", 72))


def is_staging() -> bool:
    """
    Determine if the system is running in staging environment.
    
    Uses the merged configuration system to check the environment setting.
    Staging environment typically has more lenient thresholds and different
    monitoring behavior.
    
    Returns:
        bool: True if running in staging environment, False otherwise
    """
    try:
        config = get_config()
        return config.meta.environment == "staging"
    except Exception:
        # Fallback to environment variable if config loading fails
        return os.getenv("ENVIRONMENT", "").lower() in ["staging", "stage"]


def slo_dict() -> Dict[str, Any]:
    """
    Get all SLO thresholds as a dictionary for display and monitoring.
    
    Returns:
        Dict[str, Any]: Dictionary containing all SLO thresholds and metadata
    """
    return {
        "thresholds": {
            "p95_publish_latency_ms": P95_PUBLISH_LATENCY_MS,
            "max_stream_lag_sec": MAX_STREAM_LAG_SEC,
            "uptime_target": UPTIME_TARGET,
            "max_dup_rate": MAX_DUP_RATE,
        },
        "window_hours": window_hours(),
        "is_staging": is_staging(),
        "environment": "staging" if is_staging() else "production",
        "description": {
            "p95_publish_latency_ms": "95th percentile publish latency in milliseconds",
            "max_stream_lag_sec": "Maximum acceptable stream lag in seconds",
            "uptime_target": "Target uptime as a decimal (0.995 = 99.5%)",
            "max_dup_rate": "Maximum acceptable duplicate rate as decimal (0.001 = 0.1%)",
            "window_hours": "SLO evaluation window in hours",
        }
    }


# =============================================================================
# Environment-Specific Overrides
# =============================================================================

def get_staging_thresholds() -> Dict[str, Any]:
    """
    Get SLO thresholds adjusted for staging environment.
    
    Staging typically has more lenient thresholds to reduce false positives
    during development and testing.
    
    Returns:
        Dict[str, Any]: Staging-specific SLO thresholds
    """
    if not is_staging():
        return slo_dict()["thresholds"]
    
    # Staging overrides - more lenient thresholds
    return {
        "p95_publish_latency_ms": P95_PUBLISH_LATENCY_MS * 2,  # 1000ms
        "max_stream_lag_sec": MAX_STREAM_LAG_SEC * 5,  # 5 seconds
        "uptime_target": 0.99,  # 99% (more lenient)
        "max_dup_rate": MAX_DUP_RATE * 2,  # 0.2%
    }


def get_effective_thresholds() -> Dict[str, Any]:
    """
    Get the effective SLO thresholds based on current environment.
    
    Returns:
        Dict[str, Any]: Environment-appropriate SLO thresholds
    """
    if is_staging():
        return get_staging_thresholds()
    return slo_dict()["thresholds"]


# =============================================================================
# Validation Helpers
# =============================================================================

def validate_slo_thresholds(thresholds: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate SLO threshold values for reasonableness.
    
    Args:
        thresholds: Dictionary of threshold values to validate
        
    Returns:
        Dict[str, Any]: Validation results with any issues found
    """
    issues = []
    warnings = []
    
    # Validate latency threshold
    if thresholds.get("p95_publish_latency_ms", 0) > 2000:
        issues.append("P95 publish latency > 2000ms is too high for real-time trading")
    elif thresholds.get("p95_publish_latency_ms", 0) > 1000:
        warnings.append("P95 publish latency > 1000ms may impact trading performance")
    
    # Validate stream lag
    if thresholds.get("max_stream_lag_sec", 0) > 10:
        issues.append("Max stream lag > 10s indicates serious performance issues")
    elif thresholds.get("max_stream_lag_sec", 0) > 5:
        warnings.append("Max stream lag > 5s may cause stale data issues")
    
    # Validate uptime target
    uptime = thresholds.get("uptime_target", 0)
    if uptime < 0.95:
        issues.append("Uptime target < 95% is too low for production")
    elif uptime < 0.99:
        warnings.append("Uptime target < 99% may not meet SLA requirements")
    
    # Validate duplicate rate
    dup_rate = thresholds.get("max_dup_rate", 0)
    if dup_rate > 0.01:
        issues.append("Max duplicate rate > 1% indicates data integrity issues")
    elif dup_rate > 0.005:
        warnings.append("Max duplicate rate > 0.5% may indicate data quality problems")
    
    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "warnings": warnings,
        "thresholds": thresholds
    }


# =============================================================================
# Module-level convenience
# =============================================================================

def get_slo_summary() -> str:
    """
    Get a human-readable summary of current SLO configuration.
    
    Returns:
        str: Formatted summary of SLO thresholds and environment
    """
    slo_data = slo_dict()
    env = "staging" if is_staging() else "production"
    
    return f"""
SLO Configuration Summary:
Environment: {env}
Window: {slo_data['window_hours']} hours

Thresholds:
  P95 Publish Latency: {slo_data['thresholds']['p95_publish_latency_ms']}ms
  Max Stream Lag: {slo_data['thresholds']['max_stream_lag_sec']}s
  Uptime Target: {slo_data['thresholds']['uptime_target']:.1%}
  Max Duplicate Rate: {slo_data['thresholds']['max_dup_rate']:.3%}
""".strip()


if __name__ == "__main__":
    # Allow testing in REPL
    print(get_slo_summary())
    print("\nEffective thresholds:", get_effective_thresholds())
    print("\nValidation:", validate_slo_thresholds(get_effective_thresholds()))

