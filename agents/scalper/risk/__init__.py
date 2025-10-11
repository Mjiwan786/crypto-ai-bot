"""
Risk management components for scalping operations.

This module provides comprehensive risk management for high-frequency trading:
- Real-time risk monitoring and violation detection
- Position limits and exposure management
- Dynamic risk adjustment based on market conditions
- Circuit breakers and emergency stop mechanisms
- Risk metrics calculation and reporting
"""

from __future__ import annotations

from .exposure import ExposureCalculator, ExposureMetrics, PositionExposure
from .limits import DynamicRiskAdjuster, PositionLimits, RiskLimits
from .risk_manager import RiskManager, RiskMetrics, RiskViolation

__all__ = [
    "RiskManager",
    "RiskViolation",
    "RiskMetrics",
    "PositionLimits",
    "RiskLimits",
    "DynamicRiskAdjuster",
    "ExposureCalculator",
    "ExposureMetrics",
    "PositionExposure",
]
