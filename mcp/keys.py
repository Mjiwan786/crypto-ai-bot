"""
mcp/keys.py - Production-grade Redis key management for crypto-ai-bot

Provides safe, consistent namespacing and key validation for Redis streams/channels.
Integrates with MCP brain and trading agents with environment awareness.

Usage:
    from mcp.keys import BOT_ENV, ns_key, channel, stream

    # Environment-aware keys (prefer the callable for compatibility)
    signal_stream = stream("crypto-ai-bot", BOT_ENV(), "signals")
    # -> "paper:crypto-ai-bot:signals"

    # Namespace keys
    config_key = ns_key("crypto-ai-bot", "config", "scalping")
    # -> "crypto-ai-bot:config:scalping"

    # Pub/sub channels
    alert_channel = channel("crypto-ai-bot", BOT_ENV(), "alerts")
    # -> "paper:crypto-ai-bot:alerts"
"""

from __future__ import annotations

import os
import re
import logging
from typing import List, Set, Dict

__all__ = [
    "BOT_ENV",             # callable that returns the normalized env
    "BOT_ENV_VALUE",       # normalized env captured at import time
    "VALID_ENVS",
    "env_from_os",
    "ensure_env",
    "sanitize_part",
    "sanitize_ns",
    "ns_key",
    "channel",
    "stream",
    "DEFAULT_NAMESPACE",
    "DEFAULT_STREAMS",
]

# ---------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------

logger = logging.getLogger("mcp.keys")

# ---------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------

VALID_ENVS: Set[str] = {"dev", "test", "paper", "live"}

DEFAULT_NAMESPACE: str = "crypto-ai-bot"

DEFAULT_STREAMS: Dict[str, str] = {
    "signals": "signals",
    "orders.intents": "orders:intents",
    "metrics": "metrics:ticks",
    "policy": "policy:updates",
    "rejections": "events:rejections",
    "dlq": "events:dlq",
}

# ---------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------

_ALLOWED = re.compile(r"[^a-z0-9:_-]")  # anything not allowed

def _coerce_chars(value: str) -> str:
    """Replace invalid characters with '-', allow only [a-z0-9:_-]."""
    return _ALLOWED.sub("-", value)

def _collapse_separators(value: str) -> str:
    """Collapse multiple consecutive separators to single."""
    # Collapse ::: and --- runs
    value = re.sub(r":{2,}", ":", value)
    value = re.sub(r"-{2,}", "-", value)
    return value

def _validate_non_empty(label: str, value: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"Empty {label} after sanitization")

def _join(*parts: str) -> str:
    """Join parts with colons, ignoring empties, and normalize separators."""
    filtered: List[str] = [p for p in parts if p and p.strip()]
    if not filtered:
        raise ValueError("No valid segments provided to _join")
    result = ":".join(filtered)
    result = _collapse_separators(result)
    result = result.strip(":- ")
    if not result:
        raise ValueError("Result is empty after joining and cleanup")
    return result

# ---------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------

def env_from_os(var_name: str = "BOT_ENV", default: str = "paper") -> str:
    """
    Get environment name from OS environment variable (default 'BOT_ENV').

    Returns a raw string (not validated). Use ensure_env() to validate/normalize.
    """
    return os.getenv(var_name, default)

def ensure_env(env: str) -> str:
    """
    Validate and normalize environment name (lowercased).
    Raises ValueError if not in VALID_ENVS.
    """
    if not env or not isinstance(env, str):
        raise ValueError(f"Environment must be a non-empty string, got: {repr(env)}")
    normalized = env.lower().strip()
    if normalized not in VALID_ENVS:
        raise ValueError(f"Invalid environment '{env}'. Must be one of: {sorted(VALID_ENVS)}")
    return normalized

def sanitize_part(part: str) -> str:
    """
    Sanitize a key part for Redis compatibility.

    - lowercase + trim
    - spaces -> '-'
    - keep only [a-z0-9:_-], others -> '-'
    - collapse repeated ':' and '-'
    - strip leading/trailing ':' and '-'
    """
    if not isinstance(part, str):
        raise ValueError(f"Part must be a string, got: {type(part).__name__}")
    original = part
    result = part.lower().strip()
    result = result.replace(" ", "-")
    result = _coerce_chars(result)
    result = _collapse_separators(result)
    result = result.strip(":- ")
    _validate_non_empty("part", result)
    if logger.isEnabledFor(logging.DEBUG) and result != original:
        logger.debug("Sanitized %r -> %r", original, result)
    return result

def sanitize_ns(ns: str) -> str:
    """Sanitize namespace (same rules as sanitize_part)."""
    return sanitize_part(ns)

def ns_key(ns: str, *parts: str) -> str:
    """
    Build a namespaced key: "<ns>:<p1>:<p2>:..."
    All parts are sanitized. Requires at least one part.
    """
    if not parts:
        raise ValueError("At least one part must be provided beyond namespace")
    clean_ns = sanitize_ns(ns)
    clean_parts = []
    for i, part in enumerate(parts):
        try:
            clean_parts.append(sanitize_part(part))
        except ValueError as e:
            raise ValueError(f"Part {i+1} ('{part}'): {e}")
    return _join(clean_ns, *clean_parts)

def channel(ns: str, env: str, name: str) -> str:
    """
    Build a pub/sub channel name: "<env>:<ns>:<name>"
    """
    clean_env = ensure_env(env)
    clean_ns = sanitize_ns(ns)
    clean_name = sanitize_part(name)
    return _join(clean_env, clean_ns, clean_name)

def stream(ns: str, env: str, name: str) -> str:
    """
    Build a Redis stream name: "<env>:<ns>:<name>"
    (Same format as channel for consistency.)
    """
    return channel(ns, env, name)

# ---------------------------------------------------------------------
# Environment accessor (compat-safe)
# ---------------------------------------------------------------------

# Capture the environment at import time:
BOT_ENV_VALUE: str = ensure_env(env_from_os())

def BOT_ENV() -> str:
    """
    Returns the normalized environment selected by OS env (cached at import).
    This callable preserves compatibility with existing code that uses BOT_ENV().
    """
    return BOT_ENV_VALUE

# ---------------------------------------------------------------------
# Self-test (manual)
# ---------------------------------------------------------------------

def _run_self_test() -> None:
    """Run self-test to validate functionality."""
    print("Running mcp.keys self-test...")

    # Test 1: Environment resolution
    test_env = ensure_env(env_from_os())  # avoid assuming anything about the machine
    expected_stream = f"{test_env}:{DEFAULT_NAMESPACE}:signals"
    actual_stream = stream(DEFAULT_NAMESPACE, test_env, "signals")
    assert actual_stream == expected_stream, f"Expected {expected_stream}, got {actual_stream}"

    # Test 2: Sanitization basics
    assert sanitize_part(" BTC/USD  ") == "btc-usd"
    assert sanitize_part("Orders:Intents") == "orders:intents"

    # Test 3: Invalid environment
    try:
        ensure_env("invalid")
        raise AssertionError("ensure_env('invalid') should have raised")
    except ValueError:
        pass

    # Test 4: ns_key
    assert ns_key("crypto-ai-bot", "signals") == "crypto-ai-bot:signals"

    # Test 5: channel/stream parity
    ch = channel("crypto-ai-bot", "paper", "signals")
    st = stream("crypto-ai-bot", "paper", "signals")
    assert ch == st

    # Test 6: empty segments rejected
    for bad in ("", "   "):
        try:
            sanitize_part(bad)
            raise AssertionError("sanitize_part should have raised for empty/blank")
        except ValueError:
            pass

    print("mcp.keys self-test PASSED")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        _run_self_test()
        sys.exit(0)
    print("mcp.keys module loaded")
    print(f"BOT_ENV(): {BOT_ENV()}")
    print(f"Valid environments: {sorted(VALID_ENVS)}")
    print(f"Default namespace: {DEFAULT_NAMESPACE}")
    print("Run with --self-test to validate functionality")
