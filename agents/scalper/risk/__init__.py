"""
Risk management components for scalping operations.

This module provides comprehensive risk management for high-frequency trading:
- Real-time risk monitoring and violation detection
- Position limits and exposure management
- Dynamic risk adjustment based on market conditions
- Circuit breakers and emergency stop mechanisms
- Risk metrics calculation and reporting

NEW - Dynamic Position Sizing (2025-11-08):
- Adaptive position sizing based on equity, streak, volatility, and portfolio heat
- Production-safe with conservative caps (max 3x, min 0.1x)
- Runtime overrides via Redis/MCP for live tuning
- Full state persistence and metric publishing
"""

from __future__ import annotations

from .dynamic_sizing import (
    DynamicPositionSizer,
    DynamicSizingConfig,
    TradeOutcome,
    create_default_sizer,
    create_sizer_from_dict,
)
from .exposure import ExposureCalculator, ExposureMetrics, PositionExposure
from .limits import DynamicRiskAdjuster, PositionLimits, RiskLimits
from .risk_manager import RiskManager, RiskMetrics, RiskViolation
from .sizing_integration import DynamicSizingIntegration

__all__ = [
    # Existing risk management
    "RiskManager",
    "RiskViolation",
    "RiskMetrics",
    "PositionLimits",
    "RiskLimits",
    "DynamicRiskAdjuster",
    "ExposureCalculator",
    "ExposureMetrics",
    "PositionExposure",
    # NEW: Dynamic position sizing
    "DynamicPositionSizer",
    "DynamicSizingConfig",
    "TradeOutcome",
    "DynamicSizingIntegration",
    "create_default_sizer",
    "create_sizer_from_dict",
]
