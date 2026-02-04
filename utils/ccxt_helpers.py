# utils/ccxt_helpers.py
from __future__ import annotations
import time
import random
from typing import Any, Dict
import ccxt

RETRIABLE = (
    ccxt.NetworkError, ccxt.DDoSProtection, ccxt.ExchangeNotAvailable, 
    ccxt.RateLimitExceeded
)

def get_symbol_meta(ex, symbol: str) -> Dict[str, Any]:
    m = ex.markets[symbol]
    px_step = (
        m.get("precision", {}).get("price") or 
        m.get("info", {}).get("tickSize") or 
        ex.price_to_precision(symbol, 1.0) and 
        ex.amount_to_precision(symbol, 1.0) and 
        m.get("limits", {}).get("price", {}).get("min", 0) or 0
    )
    amt_step = (
        m.get("precision", {}).get("amount") or 
        m.get("limits", {}).get("amount", {}).get("min", 0)
    )
    min_notional = (
        m.get("limits", {}).get("cost", {}).get("min", 0) or 
        m.get("info", {}).get("costMin", 0) or 0
    )
    return {"price_step": px_step or ex.precision["price"] if hasattr(ex, "precision") else 0.0,
            "amount_step": amt_step or 0.0,
            "min_notional": float(min_notional)}

def mk_client_order_id(prefix: str, seed: str) -> str:
    return f"{prefix}-{seed[:20]}"

def exp_backoff_sleep(attempt: int, base_ms: int = 100, cap_ms: int = 1600):
    dur = min(cap_ms, base_ms * (2 ** attempt))
    time.sleep((dur + random.randint(0, 100)) / 1000.0)

def is_retriable(e: Exception) -> bool:
    return isinstance(e, RETRIABLE)
