"""
Per-exchange fee model for realistic paper trading P&L.

Instead of a single ROUND_TRIP_FEE_BPS constant, this provides
exchange-specific maker/taker fees so paper trading simulates
real-world costs for each supported exchange.

The default execution venue (for paper trading signal validation)
uses ROUND_TRIP_FEE_BPS env var, defaulting to 20 bps (Binance-level).
When live trading is enabled, fees come from the user's connected exchange.
"""

import logging
import os
from dataclasses import dataclass
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExchangeFees:
    """Fee structure for a single exchange."""
    name: str
    maker_bps: float      # maker fee in basis points
    taker_bps: float      # taker fee in basis points
    token_discount: float  # discount multiplier when using native token (1.0 = no discount)
    notes: str = ""


# Current fee schedules as of March 2026 (base tier, spot)
EXCHANGE_FEES: Dict[str, ExchangeFees] = {
    "bitfinex": ExchangeFees("Bitfinex", maker_bps=0.0, taker_bps=0.0, token_discount=1.0,
                             notes="Zero fees since Dec 2025"),
    "binance": ExchangeFees("Binance", maker_bps=10.0, taker_bps=10.0, token_discount=0.75,
                            notes="25% off with BNB; effective 7.5/7.5"),
    "okx": ExchangeFees("OKX", maker_bps=8.0, taker_bps=10.0, token_discount=0.60,
                        notes="Up to 40% off with OKB"),
    "kucoin": ExchangeFees("KuCoin", maker_bps=10.0, taker_bps=10.0, token_discount=0.80,
                           notes="20% off with KCS"),
    "gateio": ExchangeFees("Gate.io", maker_bps=10.0, taker_bps=10.0, token_discount=0.90,
                           notes="~10% off with GT"),
    "bybit": ExchangeFees("Bybit", maker_bps=10.0, taker_bps=10.0, token_discount=1.0,
                          notes="No token discount at base tier"),
    "kraken": ExchangeFees("Kraken", maker_bps=25.0, taker_bps=40.0, token_discount=1.0,
                           notes="No native token discount"),
    "coinbase": ExchangeFees("Coinbase", maker_bps=25.0, taker_bps=40.0, token_discount=1.0,
                             notes="Fees at $10K-$50K tier"),
}


def get_round_trip_fee_bps(exchange: Optional[str] = None, use_token_discount: bool = True) -> float:
    """
    Get round-trip (buy + sell) fee in basis points for an exchange.

    Args:
        exchange: Exchange name (e.g., 'binance'). If None, uses env var default.
        use_token_discount: Whether to apply native token discount.

    Returns:
        Round-trip fee in basis points.
    """
    # If no exchange specified, use the global default
    if exchange is None or exchange == "any":
        default = float(os.getenv("ROUND_TRIP_FEE_BPS", "20"))
        return default

    exchange_lower = exchange.lower().replace(" ", "").replace(".", "")
    fees = EXCHANGE_FEES.get(exchange_lower)

    if fees is None:
        logger.warning("Unknown exchange '%s', using default fee", exchange)
        return float(os.getenv("ROUND_TRIP_FEE_BPS", "20"))

    discount = fees.token_discount if use_token_discount else 1.0

    # Round-trip = maker + taker (assume maker buy, taker sell as common case)
    round_trip = (fees.maker_bps + fees.taker_bps) * discount

    return round_trip


def get_fee_for_venue(venue: Optional[str] = None) -> float:
    """
    Convenience function for the signal pipeline.
    Reads EXECUTION_VENUE env var if no venue specified.
    """
    if venue is None:
        venue = os.getenv("EXECUTION_VENUE", "any")
    return get_round_trip_fee_bps(venue)


# For backward compatibility: module-level constant reads from env
DEFAULT_ROUND_TRIP_FEE_BPS = float(os.getenv("ROUND_TRIP_FEE_BPS", "20"))
