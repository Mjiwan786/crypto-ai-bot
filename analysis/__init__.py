"""
Analysis module for crypto-ai-bot.

Provides metrics aggregation, signal frequency analysis, and performance calculations.
"""

from analysis.metrics_summary import (
    MetricsSummaryCalculator,
    SignalFrequencyMetrics,
    PerformanceMetrics,
    TradingAssumptions,
)

__all__ = [
    "MetricsSummaryCalculator",
    "SignalFrequencyMetrics",
    "PerformanceMetrics",
    "TradingAssumptions",
]
