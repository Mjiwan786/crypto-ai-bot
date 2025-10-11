"""
Configuration management for crypto-ai-bot.

This package provides unified configuration loading from YAML files with
environment-specific overrides and stream registry management.

**Quick Start:**
    from config import load_system_config, get_stream

    # Load system configuration for specific environment
    config = load_system_config(environment="paper")

    # Get Redis stream keys
    signal_stream = get_stream("signals", symbol="BTC/USDT")

**Available Functions:**
- load_system_config() - Load unified system configuration
- get_config_loader() - Get singleton config loader instance
- get_agent_config() - Get agent-specific configuration
- get_stream() - Get Redis stream key with formatting
- get_all_streams() - Get all registered stream keys
- load_streams() - Load stream definitions from YAML
"""

from __future__ import annotations

from .unified_config_loader import (
    load_system_config,
    get_config_loader,
    get_agent_config,
    SystemConfig,
    UnifiedConfigLoader,
)

from .stream_registry import (
    load_streams,
    get_stream,
    get_all_streams,
    reset_registry,
)

__all__ = [
    # Configuration loading
    "load_system_config",
    "get_config_loader",
    "get_agent_config",
    "SystemConfig",
    "UnifiedConfigLoader",
    # Stream registry
    "load_streams",
    "get_stream",
    "get_all_streams",
    "reset_registry",
]
