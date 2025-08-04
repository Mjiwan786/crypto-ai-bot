"""
Growth Tracker
--------------

Utility for tracking portfolio growth over time.  While this isn't part
of the trading core, it can be helpful to monitor how your account
balance evolves relative to capital injections and withdrawals.  The
function defined here prints a summary of your net growth.
"""

from __future__ import annotations


def log_growth(initial_balance: float, current_balance: float, injections: list[float]) -> None:
    """Print a summary of growth in the portfolio.

    Parameters
    ----------
    initial_balance : float
        The starting balance before any trading took place.
    current_balance : float
        The balance at the time of logging.
    injections : list of float
        Amounts of capital added over time.  Withdrawals should be represented
        as negative numbers in this list.

    Notes
    -----
    This function is designed for console use.  In practice you might
    instead record these metrics to a database or monitoring system.
    """
    total_injected = sum(injections)
    growth = current_balance - (initial_balance + total_injected)
    print(
        f"💹 Net Growth: ${growth:.2f} | Capital Injections: ${total_injected:.2f} "
        f"| Current Balance: ${current_balance:.2f}"
    )