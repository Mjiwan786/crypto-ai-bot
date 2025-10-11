"""
Configuration management for trading agents.

This module provides unified configuration loading and management:
- Agent configuration loading and validation (Pydantic v2)
- Settings management with environment overrides
- Configuration merging and inheritance
- Stream registry and configuration schemas
- Agent integration and settings coordination
- Re-exports from both agents.config and config modules

Usage:
    >>> from agents.config import load_agent_settings, Settings
    >>> settings = load_agent_settings()
    >>> print(settings.mode)  # 'paper' or 'live'

    >>> # For scalper-specific config
    >>> from agents.config import load_scalper_config
    >>> scalper_cfg = load_scalper_config()
"""

from __future__ import annotations

# ======================== Core Agent Config (Pydantic v2) ========================
# Import from agents.config.config_loader (Pydantic v2 models)
from agents.config.config_loader import (
    # Pydantic Models
    Settings,
    RedisSettings,
    KrakenSettings,
    RiskSettings,
    ScalperSettings,
    # Loader functions
    load_agent_settings,
    # Legacy compatibility
    SimpleConfig,
    get_config,
    reload_config,
    ConfigLoader,
)

# ======================== Scalper Config ========================
# Re-export scalper config for convenience
try:
    from agents.scalper.config_loader import (
        KrakenScalpingConfig,
        load_scalper_config,
        ScalpingPairConfig,
        ScalpingRiskConfig,
        ScalpingExecutionConfig,
        ScalpingMarketConfig,
    )
    _SCALPER_AVAILABLE = True
except ImportError:
    _SCALPER_AVAILABLE = False
    # Provide stubs if scalper config not available
    KrakenScalpingConfig = None  # type: ignore
    load_scalper_config = None  # type: ignore

# ======================== Public API ========================

__all__ = [
    # Primary configuration interface (Pydantic v2)
    "Settings",
    "load_agent_settings",

    # Pydantic models
    "RedisSettings",
    "KrakenSettings",
    "RiskSettings",
    "ScalperSettings",

    # Legacy compatibility (dict-based)
    "SimpleConfig",
    "get_config",
    "reload_config",
    "ConfigLoader",

    # Scalper config (if available)
    "KrakenScalpingConfig",
    "load_scalper_config",
    "ScalpingPairConfig",
    "ScalpingRiskConfig",
    "ScalpingExecutionConfig",
    "ScalpingMarketConfig",
]
