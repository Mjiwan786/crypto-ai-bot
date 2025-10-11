"""
Protection and safety mechanisms for scalping operations.

This module provides safety and protection systems:
- Circuit breakers for market condition protection
- Kill switches for emergency stop functionality
- Risk-based position limits and controls
- Market condition monitoring and alerts
- Emergency response and recovery procedures
"""

from __future__ import annotations

from .circuit_breakers import BreakerEvent, BreakerType, CircuitBreaker, CircuitBreakerManager

__all__ = ["CircuitBreakerManager", "CircuitBreaker", "BreakerType", "BreakerEvent"]
