"""
Signals API Configuration
=========================

Centralized configuration for external signals-api service.
All HTTP calls to signals-api should use these values.

Usage:
    from config.signals_api_config import SIGNALS_API_BASE_URL, get_signals_api_url

    # Get base URL
    base = SIGNALS_API_BASE_URL  # https://signals-api-gateway.fly.dev

    # Build endpoint URLs
    health_url = get_signals_api_url("/health")
    signals_url = get_signals_api_url("/v1/signals")

Environment Variables:
    SIGNALS_API_BASE_URL - Override the default base URL
"""

import os

# Default to the canonical production gateway
DEFAULT_SIGNALS_API_BASE_URL = "https://signals-api-gateway.fly.dev"

# Read from environment, fallback to default
SIGNALS_API_BASE_URL: str = os.getenv(
    "SIGNALS_API_BASE_URL",
    DEFAULT_SIGNALS_API_BASE_URL
)


def get_signals_api_url(endpoint: str = "") -> str:
    """
    Build a full URL to the signals-api service.

    Args:
        endpoint: The API endpoint path (e.g., "/health", "/v1/signals")

    Returns:
        Full URL string (e.g., "https://signals-api-gateway.fly.dev/health")
    """
    base = SIGNALS_API_BASE_URL.rstrip("/")
    if endpoint and not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    return f"{base}{endpoint}"


# Convenience constants for common endpoints
SIGNALS_API_HEALTH_URL = get_signals_api_url("/health")
SIGNALS_API_SIGNALS_URL = get_signals_api_url("/v1/signals")
SIGNALS_API_METRICS_URL = get_signals_api_url("/metrics")
SIGNALS_API_PNL_URL = get_signals_api_url("/pnl")
