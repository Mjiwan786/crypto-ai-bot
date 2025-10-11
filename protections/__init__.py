"""
Global Protection Systems for Crypto AI Bot

This module provides system-wide protections including:
- Emergency kill switches with Redis control
- Live trading guards
- Paper mode safety checks
"""

from .kill_switches import GlobalKillSwitch, check_live_trading_allowed

__all__ = ["GlobalKillSwitch", "check_live_trading_allowed"]
