"""
Configuration files local to the scalper package.

At runtime the global config loader reads from `crypto_ai_bot/config/settings.yaml`
but individual components may override or extend those settings by
providing additional YAML files in this directory. The included
`settings.yaml` mirrors the global settings for convenience while
`kraken_config.yaml` contains exchange specific parameters.

This module provides:
- Scalper-specific configuration overrides
- Exchange-specific parameter definitions
- Default settings and fallback configurations
- Configuration validation and schema enforcement
"""

from __future__ import annotations
