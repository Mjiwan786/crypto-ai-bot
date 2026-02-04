"""
Binance Market Data Reader (READ-ONLY)

Collects market data from Binance for cross-venue analysis:
- Order book snapshots (liquidity)
- Ticker data (spreads)
- Funding rates (perpetual futures)
- 24h volume statistics

NO ORDER PLACEMENT - Data collection only for arbitrage detection.

Author: Crypto AI Bot Team
Date: 2025-11-08
"""

import os
import time
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from decimal import Decimal

try:
    from binance.client import Client
    from binance.exceptions import BinanceAPIException
    BINANCE_AVAILABLE = True
except ImportError:
    BINANCE_AVAILABLE = False
    Client = None
    BinanceAPIException = Exception


@dataclass
class BinanceLiquiditySnapshot:
    """Liquidity snapshot from Binance order book."""
    symbol: str
    timestamp: float
    best_bid: float
    best_ask: float
    bid_volume: float  # Total BTC/ETH volume at top 10 levels
    ask_volume: float
    spread_bps: float
    bid_depth_usd: float  # USD value of bids in top 10 levels
    ask_depth_usd: float
    imbalance_ratio: float  # bid_volume / (bid_volume + ask_volume)


@dataclass
class BinanceFundingRate:
    """Funding rate data from Binance futures."""
    symbol: str
    timestamp: float
    funding_rate: float  # Current funding rate (as decimal, e.g., 0.0001 = 0.01%)
    next_funding_time: int  # Unix timestamp
    mark_price: float
    index_price: float
    funding_rate_8h_annualized: float  # Annualized rate (funding * 3 * 365)


@dataclass
class BinanceTicker:
    """24h ticker statistics from Binance."""
    symbol: str
    timestamp: float
    last_price: float
    volume_24h: float  # Base currency (BTC/ETH)
    quote_volume_24h: float  # USD
    price_change_24h_pct: float
    high_24h: float
    low_24h: float
    trades_count_24h: int


class BinanceReader:
    """
    Read-only Binance market data collector.

    Collects liquidity, funding rates, and ticker data for cross-venue analysis.
    Does NOT place orders or execute trades.
    """

    def __init__(
        self,
        redis_manager=None,
        logger=None,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
    ):
        """
        Initialize Binance reader.

        Args:
            redis_manager: Redis manager for publishing data
            logger: Logger instance
            api_key: Binance API key (optional, public data doesn't need it)
            api_secret: Binance API secret (optional)
        """
        self.redis = redis_manager
        self.logger = logger or logging.getLogger(__name__)

        # Symbol mapping: our format -> Binance format
        self.symbol_map = {
            "BTC/USD": "BTCUSDT",
            "ETH/USD": "ETHUSDT",
            "SOL/USD": "SOLUSDT",
            "ADA/USD": "ADAUSDT",
        }

        # Check if Binance SDK is available
        if not BINANCE_AVAILABLE:
            self.logger.warning(
                "Binance SDK not available. Install with: pip install python-binance"
            )
            self.client = None
            self.enabled = False
            return

        # Feature flag
        self.enabled = os.getenv("EXTERNAL_VENUE_READS", "").lower() == "binance"

        if not self.enabled:
            self.logger.info("Binance reader disabled (EXTERNAL_VENUE_READS != binance)")
            self.client = None
            return

        # Initialize Binance client
        try:
            self.client = Client(
                api_key=api_key or os.getenv("BINANCE_API_KEY", ""),
                api_secret=api_secret or os.getenv("BINANCE_API_SECRET", ""),
            )
            # Test connectivity
            self.client.ping()
            self.logger.info("Binance reader initialized successfully")
        except Exception as e:
            self.logger.error(f"Failed to initialize Binance client: {e}")
            self.client = None
            self.enabled = False

        # Cache for funding rates (update every 5 minutes)
        self.funding_cache: Dict[str, BinanceFundingRate] = {}
        self.funding_cache_ttl = 300  # 5 minutes
        self.last_funding_update = 0

    def get_liquidity_snapshot(
        self, symbol: str, depth_levels: int = 10
    ) -> Optional[BinanceLiquiditySnapshot]:
        """
        Get order book liquidity snapshot from Binance.

        Args:
            symbol: Symbol in our format (e.g., "BTC/USD")
            depth_levels: Number of order book levels to analyze

        Returns:
            BinanceLiquiditySnapshot or None if error
        """
        if not self.enabled or not self.client:
            return None

        binance_symbol = self.symbol_map.get(symbol)
        if not binance_symbol:
            self.logger.warning(f"Symbol {symbol} not mapped to Binance")
            return None

        try:
            # Get order book
            depth = self.client.get_order_book(symbol=binance_symbol, limit=depth_levels)

            # Parse bids and asks
            bids = depth["bids"]  # [[price, qty], ...]
            asks = depth["asks"]

            if not bids or not asks:
                return None

            best_bid = float(bids[0][0])
            best_ask = float(asks[0][0])

            # Calculate spread
            spread_bps = ((best_ask - best_bid) / best_bid) * 10000

            # Calculate volumes and depth
            bid_volume = sum(float(qty) for _, qty in bids)
            ask_volume = sum(float(qty) for _, qty in asks)

            bid_depth_usd = sum(float(price) * float(qty) for price, qty in bids)
            ask_depth_usd = sum(float(price) * float(qty) for price, qty in asks)

            # Liquidity imbalance ratio
            total_volume = bid_volume + ask_volume
            imbalance_ratio = bid_volume / total_volume if total_volume > 0 else 0.5

            snapshot = BinanceLiquiditySnapshot(
                symbol=symbol,
                timestamp=time.time(),
                best_bid=best_bid,
                best_ask=best_ask,
                bid_volume=bid_volume,
                ask_volume=ask_volume,
                spread_bps=spread_bps,
                bid_depth_usd=bid_depth_usd,
                ask_depth_usd=ask_depth_usd,
                imbalance_ratio=imbalance_ratio,
            )

            # Publish to Redis
            if self.redis:
                self._publish_liquidity(snapshot)

            return snapshot

        except BinanceAPIException as e:
            self.logger.error(f"Binance API error getting liquidity for {symbol}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Error getting Binance liquidity for {symbol}: {e}")
            return None

    def get_funding_rate(self, symbol: str) -> Optional[BinanceFundingRate]:
        """
        Get current funding rate from Binance futures.

        Args:
            symbol: Symbol in our format (e.g., "BTC/USD")

        Returns:
            BinanceFundingRate or None if error
        """
        if not self.enabled or not self.client:
            return None

        # Check cache
        current_time = time.time()
        if symbol in self.funding_cache:
            cached = self.funding_cache[symbol]
            if current_time - cached.timestamp < self.funding_cache_ttl:
                return cached

        binance_symbol = self.symbol_map.get(symbol)
        if not binance_symbol:
            return None

        try:
            # Get funding rate from futures
            funding_info = self.client.futures_funding_rate(
                symbol=binance_symbol, limit=1
            )

            if not funding_info:
                return None

            latest = funding_info[-1]

            # Get mark price and index price
            mark_price_info = self.client.futures_mark_price(symbol=binance_symbol)

            funding_rate = float(latest["fundingRate"])

            # Annualize funding rate (funding every 8 hours = 3x per day)
            funding_rate_annualized = funding_rate * 3 * 365

            rate = BinanceFundingRate(
                symbol=symbol,
                timestamp=current_time,
                funding_rate=funding_rate,
                next_funding_time=int(latest["fundingTime"]) // 1000,
                mark_price=float(mark_price_info["markPrice"]),
                index_price=float(mark_price_info["indexPrice"]),
                funding_rate_8h_annualized=funding_rate_annualized,
            )

            # Cache it
            self.funding_cache[symbol] = rate

            # Publish to Redis
            if self.redis:
                self._publish_funding_rate(rate)

            return rate

        except BinanceAPIException as e:
            self.logger.error(f"Binance API error getting funding rate for {symbol}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Error getting Binance funding rate for {symbol}: {e}")
            return None

    def get_ticker(self, symbol: str) -> Optional[BinanceTicker]:
        """
        Get 24h ticker statistics from Binance.

        Args:
            symbol: Symbol in our format (e.g., "BTC/USD")

        Returns:
            BinanceTicker or None if error
        """
        if not self.enabled or not self.client:
            return None

        binance_symbol = self.symbol_map.get(symbol)
        if not binance_symbol:
            return None

        try:
            ticker_data = self.client.get_ticker(symbol=binance_symbol)

            ticker = BinanceTicker(
                symbol=symbol,
                timestamp=time.time(),
                last_price=float(ticker_data["lastPrice"]),
                volume_24h=float(ticker_data["volume"]),
                quote_volume_24h=float(ticker_data["quoteVolume"]),
                price_change_24h_pct=float(ticker_data["priceChangePercent"]),
                high_24h=float(ticker_data["highPrice"]),
                low_24h=float(ticker_data["lowPrice"]),
                trades_count_24h=int(ticker_data["count"]),
            )

            # Publish to Redis
            if self.redis:
                self._publish_ticker(ticker)

            return ticker

        except BinanceAPIException as e:
            self.logger.error(f"Binance API error getting ticker for {symbol}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Error getting Binance ticker for {symbol}: {e}")
            return None

    def get_all_symbols_data(
        self, symbols: List[str]
    ) -> Dict[str, Dict]:
        """
        Get complete market data for all symbols.

        Args:
            symbols: List of symbols in our format

        Returns:
            Dict mapping symbol to data dict
        """
        if not self.enabled or not self.client:
            return {}

        results = {}

        for symbol in symbols:
            data = {}

            # Get liquidity snapshot
            liquidity = self.get_liquidity_snapshot(symbol)
            if liquidity:
                data["liquidity"] = liquidity

            # Get funding rate
            funding = self.get_funding_rate(symbol)
            if funding:
                data["funding"] = funding

            # Get ticker
            ticker = self.get_ticker(symbol)
            if ticker:
                data["ticker"] = ticker

            if data:
                results[symbol] = data

        return results

    def _publish_liquidity(self, snapshot: BinanceLiquiditySnapshot):
        """Publish liquidity snapshot to Redis."""
        if not self.redis:
            return

        try:
            data = {
                "venue": "binance",
                "symbol": snapshot.symbol,
                "timestamp": snapshot.timestamp,
                "best_bid": snapshot.best_bid,
                "best_ask": snapshot.best_ask,
                "bid_volume": snapshot.bid_volume,
                "ask_volume": snapshot.ask_volume,
                "spread_bps": snapshot.spread_bps,
                "bid_depth_usd": snapshot.bid_depth_usd,
                "ask_depth_usd": snapshot.ask_depth_usd,
                "imbalance_ratio": snapshot.imbalance_ratio,
            }

            self.redis.publish_event(
                f"binance:liquidity:{snapshot.symbol}",
                data
            )

        except Exception as e:
            self.logger.error(f"Error publishing liquidity snapshot: {e}")

    def _publish_funding_rate(self, rate: BinanceFundingRate):
        """Publish funding rate to Redis."""
        if not self.redis:
            return

        try:
            data = {
                "venue": "binance",
                "symbol": rate.symbol,
                "timestamp": rate.timestamp,
                "funding_rate": rate.funding_rate,
                "funding_rate_8h_annualized": rate.funding_rate_8h_annualized,
                "next_funding_time": rate.next_funding_time,
                "mark_price": rate.mark_price,
                "index_price": rate.index_price,
            }

            self.redis.publish_event(
                f"binance:funding:{rate.symbol}",
                data
            )

        except Exception as e:
            self.logger.error(f"Error publishing funding rate: {e}")

    def _publish_ticker(self, ticker: BinanceTicker):
        """Publish ticker to Redis."""
        if not self.redis:
            return

        try:
            data = {
                "venue": "binance",
                "symbol": ticker.symbol,
                "timestamp": ticker.timestamp,
                "last_price": ticker.last_price,
                "volume_24h": ticker.volume_24h,
                "quote_volume_24h": ticker.quote_volume_24h,
                "price_change_24h_pct": ticker.price_change_24h_pct,
                "high_24h": ticker.high_24h,
                "low_24h": ticker.low_24h,
                "trades_count_24h": ticker.trades_count_24h,
            }

            self.redis.publish_event(
                f"binance:ticker:{ticker.symbol}",
                data
            )

        except Exception as e:
            self.logger.error(f"Error publishing ticker: {e}")
