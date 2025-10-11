"""
Risk management components for trading agents.

This module provides comprehensive risk management capabilities:
- Portfolio balancing and exposure management
- Drawdown protection and circuit breakers
- Compliance checking and regulatory adherence
- Risk routing and decision making
- Real-time risk monitoring and alerting
"""

from __future__ import annotations

# Explicit exports for clean public API
__all__ = [
    # Primary risk management modules
    "risk_router",
    "drawdown_protector",
    "portfolio_balancer",
    "compliance_checker",
]
