"""
Top-level package for core AI engine components.

This package contains modules responsible for maintaining a shared context
across the system, selecting the appropriate trading strategy based on the
current market regime, evaluating arbitrage opportunities and learning from
experience over time.
"""

__all__ = [
    "global_context",
    "strategy_selector",
    "flash_loan_advisor",
    "adaptive_learner",
    "regime_detector",
]