"""
Performance monitoring and metrics for scalping operations.

This module provides comprehensive monitoring capabilities:
- Real-time performance tracking and metrics collection
- Latency monitoring and optimization
- Trade execution quality analysis
- Performance attribution and risk metrics
- Alerting and notification systems
"""

from __future__ import annotations

from .performance import PerformanceMonitor, TradeMetrics

__all__ = ["PerformanceMonitor", "TradeMetrics"]
