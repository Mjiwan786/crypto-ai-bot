#!/usr/bin/env python3
"""
Spread Calculator for Market Data Streams

Calculates bid-ask spreads from orderbook data and publishes to Redis streams.
Used for maker-only execution filtering (skip entries if spread > cap).

Features:
- Real-time spread calculation from L1 orderbook (best bid/ask)
- Spread in basis points (bps) for easy comparison
- Redis stream publishing for consumption by execution agents
- Supports both live and backtest modes

Redis Stream Keys:
    - kraken:spread:{symbol} -> {ts, symbol, bid, ask, spread_bps}

Usage:
    from utils.spread_calculator import SpreadCalculator

    calc = SpreadCalculator(redis_url="rediss://...")

    # Calculate spread
    spread_bps = calc.calculate_spread(bid=50000.0, ask=50004.0)  # 0.8 bps

    # Publish to Redis
    calc.publish_spread("BTC/USD", bid=50000.0, ask=50004.0)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SpreadData:
    """Spread data snapshot"""

    symbol: str
    timestamp_ms: int
    bid: float
    ask: float
    spread_bps: float
    mid_price: float


class SpreadCalculator:
    """
    Real-time spread calculator for market data.

    Calculates bid-ask spreads and publishes to Redis for execution filtering.
    """

    def __init__(self, redis_client=None):
        """
        Initialize spread calculator.

        Args:
            redis_client: Optional Redis client (if None, operates without Redis)
        """
        self.redis_client = redis_client
        self.last_spreads: dict[str, SpreadData] = {}  # symbol -> last spread data

        logger.info(f"SpreadCalculator initialized [redis={'connected' if redis_client else 'disabled'}]")

    def calculate_spread(self, bid: float, ask: float) -> float:
        """
        Calculate spread in basis points.

        Args:
            bid: Best bid price
            ask: Best ask price

        Returns:
            Spread in basis points (bps)

        Example:
            bid=50000, ask=50004 -> spread = 0.8 bps
        """
        if bid <= 0 or ask <= 0:
            logger.warning(f"Invalid bid/ask: bid={bid}, ask={ask}")
            return 9999.0  # Invalid spread, will be rejected by filter

        mid_price = (bid + ask) / 2.0
        spread_abs = ask - bid

        if spread_abs < 0:
            logger.warning(f"Negative spread: bid={bid}, ask={ask}")
            return 9999.0

        spread_bps = (spread_abs / mid_price) * 10000
        return spread_bps

    def publish_spread(
        self, symbol: str, bid: float, ask: float, timestamp_ms: Optional[int] = None
    ) -> Optional[SpreadData]:
        """
        Calculate and publish spread to Redis stream.

        Args:
            symbol: Trading pair symbol
            bid: Best bid price
            ask: Best ask price
            timestamp_ms: Optional timestamp (defaults to now)

        Returns:
            SpreadData if successful, None otherwise
        """
        ts = timestamp_ms or int(time.time() * 1000)
        spread_bps = self.calculate_spread(bid, ask)
        mid_price = (bid + ask) / 2.0

        spread_data = SpreadData(
            symbol=symbol,
            timestamp_ms=ts,
            bid=bid,
            ask=ask,
            spread_bps=spread_bps,
            mid_price=mid_price,
        )

        # Cache last spread
        self.last_spreads[symbol] = spread_data

        # Publish to Redis if available
        if self.redis_client:
            try:
                stream_key = f"kraken:spread:{symbol}"
                payload = {
                    "ts": str(ts),
                    "symbol": symbol,
                    "bid": str(bid),
                    "ask": str(ask),
                    "spread_bps": f"{spread_bps:.2f}",
                    "mid_price": str(mid_price),
                }

                self.redis_client.xadd(stream_key, payload, maxlen=1000)

                logger.debug(
                    f"Published spread: {symbol} bid={bid:.2f} ask={ask:.2f} "
                    f"spread={spread_bps:.2f}bps"
                )

            except Exception as e:
                logger.error(f"Failed to publish spread to Redis: {e}")

        return spread_data

    def get_last_spread(self, symbol: str) -> Optional[SpreadData]:
        """
        Get last known spread for a symbol.

        Args:
            symbol: Trading pair symbol

        Returns:
            Last SpreadData or None if not available
        """
        return self.last_spreads.get(symbol)

    def get_spread_bps(self, symbol: str) -> float:
        """
        Get last known spread in bps for a symbol.

        Args:
            symbol: Trading pair symbol

        Returns:
            Spread in bps, or 9999.0 if not available (will be rejected)
        """
        spread_data = self.last_spreads.get(symbol)
        if spread_data:
            return spread_data.spread_bps
        return 9999.0  # Return high value to trigger rejection


def calculate_spread_from_orderbook(orderbook: dict) -> Optional[float]:
    """
    Calculate spread from orderbook snapshot.

    Args:
        orderbook: Orderbook dict with 'bids' and 'asks' lists

    Returns:
        Spread in basis points, or None if invalid

    Example:
        orderbook = {
            'bids': [[50000.0, 1.5], [49999.0, 2.0]],
            'asks': [[50004.0, 1.2], [50005.0, 1.8]]
        }
        spread_bps = calculate_spread_from_orderbook(orderbook)  # 0.8 bps
    """
    try:
        if not orderbook or 'bids' not in orderbook or 'asks' not in orderbook:
            return None

        bids = orderbook['bids']
        asks = orderbook['asks']

        if not bids or not asks:
            return None

        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])

        calc = SpreadCalculator()
        return calc.calculate_spread(best_bid, best_ask)

    except Exception as e:
        logger.error(f"Error calculating spread from orderbook: {e}")
        return None


# =============================================================================
# SELF-CHECK
# =============================================================================

if __name__ == "__main__":
    """Self-check: Test spread calculator"""
    import sys

    logging.basicConfig(level=logging.INFO)

    try:
        # Test 1: Basic spread calculation
        calc = SpreadCalculator()

        spread_bps = calc.calculate_spread(bid=50000.0, ask=50004.0)
        assert 0.79 < spread_bps < 0.81, f"Expected ~0.8 bps, got {spread_bps}"

        print("\nPASS Spread Calculator Self-Check:")
        print(f"  - Basic calculation: {spread_bps:.2f} bps OK")

        # Test 2: Wider spread
        spread_bps = calc.calculate_spread(bid=50000.0, ask=50050.0)
        assert 9.9 < spread_bps < 10.1, f"Expected ~10 bps, got {spread_bps}"
        print(f"  - Wide spread: {spread_bps:.2f} bps OK")

        # Test 3: Tight spread
        spread_bps = calc.calculate_spread(bid=50000.0, ask=50001.0)
        assert 0.19 < spread_bps < 0.21, f"Expected ~0.2 bps, got {spread_bps}"
        print(f"  - Tight spread: {spread_bps:.2f} bps OK")

        # Test 4: Invalid spread (negative)
        spread_bps = calc.calculate_spread(bid=50000.0, ask=49999.0)
        assert spread_bps == 9999.0, f"Expected 9999.0 for invalid, got {spread_bps}"
        print(f"  - Invalid spread: {spread_bps:.0f} bps (rejected) OK")

        # Test 5: Publish without Redis
        spread_data = calc.publish_spread("BTC/USD", bid=50000.0, ask=50004.0)
        assert spread_data is not None
        assert spread_data.symbol == "BTC/USD"
        assert 0.79 < spread_data.spread_bps < 0.81
        print(f"  - Publish (no Redis): {spread_data.spread_bps:.2f} bps OK")

        # Test 6: Get last spread
        last_spread = calc.get_last_spread("BTC/USD")
        assert last_spread is not None
        assert last_spread.bid == 50000.0
        print(f"  - Get last spread: {last_spread.spread_bps:.2f} bps OK")

        # Test 7: Orderbook spread calculation
        orderbook = {
            'bids': [[50000.0, 1.5], [49999.0, 2.0]],
            'asks': [[50004.0, 1.2], [50005.0, 1.8]]
        }
        spread_bps = calculate_spread_from_orderbook(orderbook)
        assert spread_bps is not None
        assert 0.79 < spread_bps < 0.81
        print(f"  - Orderbook spread: {spread_bps:.2f} bps OK")

        print("\nAll spread calculator tests passed!")

    except Exception as e:
        print(f"\nFAIL Spread Calculator Self-Check: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
