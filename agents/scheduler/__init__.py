"""
Scheduler agents for crypto-ai-bot.

This package contains timing and scheduling agents for precise
event emission at bar boundaries.
"""

from agents.scheduler.bar_clock import (
    BarClock,
    ClockConfig,
    create_bar_clock,
    setup_signal_handlers,
)

__all__ = [
    "BarClock",
    "ClockConfig",
    "create_bar_clock",
    "setup_signal_handlers",
]
