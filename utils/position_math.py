# utils/position_math.py
from __future__ import annotations
from math import floor
from typing import Tuple

def round_to_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    return floor(value / step) * step

def round_amount(amount: float, amt_step: float) -> float:
    return round_to_step(amount, amt_step)

def round_price(price: float, px_step: float) -> float:
    return round_to_step(price, px_step)

def compute_amount_from_quote(quote_usd: float, price: float) -> float:
    return 0.0 if price <= 0 else quote_usd / price

def notional_usd(amount: float, price: float) -> float:
    return amount * price

def enforce_min_notional(
    amount: float, price: float, min_notional: float, amt_step: float
) -> Tuple[float, bool]:
    """Returns (new_amount, ok). If notional too small, tries to round up to next step; 
    if still too small, returns (0, False)."""
    n = notional_usd(amount, price)
    if n >= min_notional:
        return amount, True
    # round up by one step
    step_up = round_amount(amount + amt_step, amt_step)
    if notional_usd(step_up, price) >= min_notional:
        return step_up, True
    return 0.0, False
