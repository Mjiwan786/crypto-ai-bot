"""
Infrastructure components for scalping operations.

This module provides essential infrastructure services:
- State management with persistence and recovery
- Redis message bus for inter-component communication
- Health monitoring and diagnostics
- Metrics collection and reporting
- Configuration management and settings
"""

from __future__ import annotations

from .redis_bus import RedisBus
from .state_manager import StateManager

__all__ = ["StateManager", "RedisBus"]
