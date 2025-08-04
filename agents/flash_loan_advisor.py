"""
Flash Loan Advisor
===================

This module encapsulates logic for evaluating potential flash loan
arbitrage opportunities.  It demonstrates how to consume configuration
parameters at runtime to make decisions, rather than hard‑coding numbers.

The core function, :func:`should_execute_arb`, determines whether the bot
should attempt to execute a trade based on the expected profit, slippage
and a confidence score produced by your AI model.

Example:

    from agents.flash_loan_advisor import should_execute_arb

    opportunity = {
        "expected_profit": 0.025,
        "slippage": 0.0015
    }
    score = my_model.score(opportunity)
    if should_execute_arb(opportunity, score):
        execute_flash_loan(opportunity)

Note: This is a simplified example.  Real implementations would need to
consider network latency, gas costs, exchange liquidity and many other
factors.
"""

from __future__ import annotations

from typing import Dict

from config.config_loader import load_config

# Load configuration once at module import time.  Because the config is
# essentially static per run, it is safe to store in a module‑level variable.
cfg = load_config()


def should_execute_arb(opportunity: Dict[str, float], score: float) -> bool:
    """Decide whether to execute a flash loan arbitrage opportunity.

    Parameters
    ----------
    opportunity : dict
        A dictionary describing the trade.  It should contain at least the
        following keys:

        - ``expected_profit`` (float): The projected profit as a fraction of
          the borrowed amount (e.g. ``0.02`` for 2%).
        - ``slippage`` (float): The estimated slippage incurred when
          executing the trade, expressed as a fraction.

    score : float
        Confidence score returned by your AI model.  Should be between 0 and
        1, where higher values indicate greater confidence that the trade
        will be profitable.

    Returns
    -------
    bool
        ``True`` if the opportunity meets all configured thresholds and
        should be executed; ``False`` otherwise.
    """
    # Extract thresholds from configuration
    try:
        min_spread = cfg['flash_loan_system']['arbitrage']['min_spread']
        max_slippage = cfg['flash_loan_system']['arbitrage']['max_slippage']
        min_confidence = cfg['flash_loan_system']['ai_scoring']['min_confidence']
    except KeyError as exc:
        raise KeyError(f"Missing configuration key: {exc}") from exc

    expected_profit = float(opportunity.get('expected_profit', 0))
    slippage = float(opportunity.get('slippage', 0))

    return (
        expected_profit >= min_spread
        and slippage <= max_slippage
        and score >= min_confidence
    )