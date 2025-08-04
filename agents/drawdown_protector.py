"""
Drawdown Protector
------------------

Risk management is critical in automated trading.  This module contains
utilities for monitoring portfolio drawdown and triggering protective
actions (such as reducing position sizes or pausing trading) when
predefined limits are breached.

At present the implementation is minimal.  It simply tracks the highest
and lowest portfolio values observed and exposes a method to check
whether the maximum drawdown has exceeded the limit configured in
``agent_settings.yaml``.  You should extend this with weekly loss limits,
cool‑off timers and other protective measures.
"""

from __future__ import annotations

from typing import Optional

from config.config_loader import load_config


cfg = load_config()


class DrawdownProtector:
    """Monitor portfolio drawdown and enforce limits."""

    def __init__(self) -> None:
        self._peak: Optional[float] = None
        self._trough: Optional[float] = None
        # Extract configured drawdown limit (negative value)
        try:
            self._max_drawdown_limit = cfg['risk']['portfolio']['max_drawdown']
        except KeyError:
            # Default to -20% if not specified
            self._max_drawdown_limit = -0.2

    def update(self, portfolio_value: float) -> None:
        """Update internal state with the latest portfolio value."""
        if self._peak is None or portfolio_value > self._peak:
            self._peak = portfolio_value
        if self._trough is None or portfolio_value < self._trough:
            self._trough = portfolio_value

    def current_drawdown(self) -> float:
        """Calculate the current drawdown as a fraction."""
        if self._peak is None or self._trough is None:
            return 0.0
        return (self._trough - self._peak) / self._peak

    def is_limit_breached(self) -> bool:
        """Return True if the drawdown limit has been exceeded."""
        drawdown = self.current_drawdown()
        return drawdown <= self._max_drawdown_limit