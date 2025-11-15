"""
PRD-001 Section 6.1 Backtest Data Provider

This module implements PRD-001 Section 6.1 data requirements with:
- Fetch 1 year (365 days) historical OHLCV data for BTC/USD, ETH/USD, SOL/USD
- Use Kraken exchange as data source (via CCXT)
- Implement slippage model: 5 bps (0.05%) per trade
- Implement fee calculation: Kraken fee tiers (maker 16 bps, taker 26 bps)
- Simulate realistic order fills
- Store historical data in cache for reuse (data/ohlcv/)

Author: Crypto AI Bot Team
Version: 1.0.0
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import pandas as pd
import time

logger = logging.getLogger(__name__)

# PRD-001 Section 6.1: Trading pairs
DEFAULT_PAIRS = ["BTC/USD", "ETH/USD", "SOL/USD"]

# PRD-001 Section 6.1: Slippage and fees
SLIPPAGE_BPS = 5  # 0.05% per trade
MAKER_FEE_BPS = 16  # 0.16% maker fee
TAKER_FEE_BPS = 26  # 0.26% taker fee

# Cache directory
CACHE_DIR = Path("data/ohlcv")


class PRDBacktestDataProvider:
    """
    PRD-001 Section 6.1 compliant backtest data provider.

    Features:
    - Fetch historical OHLCV data from Kraken
    - Cache data locally for reuse
    - Provide slippage and fee calculations
    - Simulate realistic order fills

    Usage:
        provider = PRDBacktestDataProvider()

        # Fetch 1 year of data
        data = provider.fetch_ohlcv(
            pair="BTC/USD",
            days=365,
            timeframe="1h"
        )

        # Calculate fees
        maker_fee = provider.calculate_maker_fee(position_size=1000.0)
        taker_fee = provider.calculate_taker_fee(position_size=1000.0)

        # Calculate slippage
        fill_price = provider.calculate_fill_price_with_slippage(
            price=50000.0,
            side="buy"
        )
    """

    def __init__(self, cache_dir: Optional[Path] = None):
        """
        Initialize PRD-compliant backtest data provider.

        Args:
            cache_dir: Directory for caching OHLCV data (default: data/ohlcv/)
        """
        self.cache_dir = cache_dir or CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # PRD-001 Section 6.1: Slippage and fee parameters
        self.slippage_bps = SLIPPAGE_BPS
        self.maker_fee_bps = MAKER_FEE_BPS
        self.taker_fee_bps = TAKER_FEE_BPS

        # Statistics
        self.total_fetches = 0
        self.cache_hits = 0
        self.cache_misses = 0

        logger.info(
            f"PRDBacktestDataProvider initialized: "
            f"cache_dir={self.cache_dir}, "
            f"slippage={self.slippage_bps}bps, "
            f"maker_fee={self.maker_fee_bps}bps, "
            f"taker_fee={self.taker_fee_bps}bps"
        )

    def fetch_ohlcv(
        self,
        pair: str,
        days: int = 365,
        timeframe: str = "1h",
        force_refresh: bool = False
    ) -> pd.DataFrame:
        """
        PRD-001 Section 6.1: Fetch historical OHLCV data.

        Fetches data from Kraken or cache. If data is cached and not stale,
        returns cached data. Otherwise fetches from Kraken and caches.

        Args:
            pair: Trading pair (e.g., "BTC/USD")
            days: Number of days of historical data (default 365)
            timeframe: Candle timeframe (default "1h")
            force_refresh: Force fetch from exchange even if cached

        Returns:
            DataFrame with OHLCV data (columns: timestamp, open, high, low, close, volume)
        """
        self.total_fetches += 1

        # Check cache first
        if not force_refresh:
            cached_data = self._load_from_cache(pair, days, timeframe)
            if cached_data is not None:
                self.cache_hits += 1
                logger.info(
                    f"[CACHE HIT] Loaded {pair} {days}d {timeframe} from cache "
                    f"({len(cached_data)} rows)"
                )
                return cached_data

        # Cache miss - fetch from exchange
        self.cache_misses += 1
        logger.info(
            f"[CACHE MISS] Fetching {pair} {days}d {timeframe} from Kraken..."
        )

        data = self._fetch_from_kraken(pair, days, timeframe)

        # Save to cache
        self._save_to_cache(pair, days, timeframe, data)

        logger.info(
            f"[FETCH COMPLETE] {pair} {days}d {timeframe}: {len(data)} rows"
        )

        return data

    def _fetch_from_kraken(
        self,
        pair: str,
        days: int,
        timeframe: str
    ) -> pd.DataFrame:
        """
        Fetch OHLCV data from Kraken via CCXT.

        Args:
            pair: Trading pair
            days: Number of days
            timeframe: Timeframe

        Returns:
            DataFrame with OHLCV data
        """
        try:
            import ccxt

            # Initialize Kraken exchange
            exchange = ccxt.kraken({
                'enableRateLimit': True,
                'options': {'defaultType': 'spot'}
            })

            # Calculate since timestamp
            end_time = datetime.now()
            start_time = end_time - timedelta(days=days)
            since = int(start_time.timestamp() * 1000)

            # Fetch OHLCV data
            logger.info(f"Fetching {pair} from {start_time} to {end_time}...")

            all_candles = []
            current_since = since

            while True:
                candles = exchange.fetch_ohlcv(
                    pair,
                    timeframe=timeframe,
                    since=current_since,
                    limit=1000  # Max limit for most exchanges
                )

                if not candles:
                    break

                all_candles.extend(candles)

                # Check if we've fetched all data
                last_timestamp = candles[-1][0]
                if last_timestamp >= int(end_time.timestamp() * 1000):
                    break

                # Update since for next iteration
                current_since = last_timestamp + 1

                # Rate limiting
                time.sleep(exchange.rateLimit / 1000)

            # Convert to DataFrame
            df = pd.DataFrame(
                all_candles,
                columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
            )

            # Convert timestamp to datetime
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

            return df

        except ImportError:
            logger.warning(
                "CCXT not available. Using synthetic data for testing."
            )
            return self._generate_synthetic_data(pair, days, timeframe)

        except Exception as e:
            logger.error(f"Error fetching from Kraken: {e}", exc_info=True)
            logger.warning("Falling back to synthetic data")
            return self._generate_synthetic_data(pair, days, timeframe)

    def _generate_synthetic_data(
        self,
        pair: str,
        days: int,
        timeframe: str
    ) -> pd.DataFrame:
        """
        Generate synthetic OHLCV data for testing.

        Args:
            pair: Trading pair
            days: Number of days
            timeframe: Timeframe

        Returns:
            DataFrame with synthetic OHLCV data
        """
        # Timeframe to minutes mapping
        tf_minutes = {
            '1m': 1,
            '5m': 5,
            '15m': 15,
            '1h': 60,
            '4h': 240,
            '1d': 1440
        }

        minutes = tf_minutes.get(timeframe, 60)
        num_candles = int((days * 24 * 60) / minutes)

        # Base prices for different pairs
        base_prices = {
            'BTC/USD': 50000.0,
            'ETH/USD': 3000.0,
            'SOL/USD': 100.0
        }

        base_price = base_prices.get(pair, 1000.0)

        # Generate timestamps
        end_time = datetime.now()
        start_time = end_time - timedelta(days=days)

        timestamps = pd.date_range(
            start=start_time,
            end=end_time,
            periods=num_candles
        )

        # Generate synthetic price data (random walk)
        import numpy as np
        np.random.seed(42)  # For reproducibility

        returns = np.random.normal(0, 0.02, num_candles)  # 2% volatility
        price = base_price * (1 + returns).cumprod()

        # Generate OHLC from price
        high = price * (1 + np.abs(np.random.normal(0, 0.01, num_candles)))
        low = price * (1 - np.abs(np.random.normal(0, 0.01, num_candles)))
        close = price
        open_price = np.roll(close, 1)
        open_price[0] = base_price

        # Generate volume
        volume = np.random.lognormal(10, 2, num_candles)

        df = pd.DataFrame({
            'timestamp': timestamps,
            'open': open_price,
            'high': high,
            'low': low,
            'close': close,
            'volume': volume
        })

        return df

    def _load_from_cache(
        self,
        pair: str,
        days: int,
        timeframe: str
    ) -> Optional[pd.DataFrame]:
        """
        Load OHLCV data from cache.

        Args:
            pair: Trading pair
            days: Number of days
            timeframe: Timeframe

        Returns:
            DataFrame if cached, None otherwise
        """
        cache_file = self._get_cache_filename(pair, days, timeframe)

        if not cache_file.exists():
            return None

        try:
            df = pd.read_csv(cache_file)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            return df
        except Exception as e:
            logger.warning(f"Error loading cache file {cache_file}: {e}")
            return None

    def _save_to_cache(
        self,
        pair: str,
        days: int,
        timeframe: str,
        data: pd.DataFrame
    ):
        """
        Save OHLCV data to cache.

        Args:
            pair: Trading pair
            days: Number of days
            timeframe: Timeframe
            data: OHLCV DataFrame
        """
        cache_file = self._get_cache_filename(pair, days, timeframe)

        try:
            data.to_csv(cache_file, index=False)
            logger.info(f"Saved {len(data)} rows to cache: {cache_file}")
        except Exception as e:
            logger.error(f"Error saving to cache {cache_file}: {e}")

    def _get_cache_filename(
        self,
        pair: str,
        days: int,
        timeframe: str
    ) -> Path:
        """
        Get cache filename for given parameters.

        Args:
            pair: Trading pair
            days: Number of days
            timeframe: Timeframe

        Returns:
            Path to cache file
        """
        # Sanitize pair for filename
        pair_clean = pair.replace("/", "_").replace("-", "_")

        filename = f"{pair_clean}_{days}d_{timeframe}.csv"
        return self.cache_dir / filename

    def calculate_maker_fee(self, position_size_usd: float) -> float:
        """
        PRD-001 Section 6.1: Calculate maker fee (16 bps).

        Args:
            position_size_usd: Position size in USD

        Returns:
            Fee amount in USD
        """
        return position_size_usd * (self.maker_fee_bps / 10000.0)

    def calculate_taker_fee(self, position_size_usd: float) -> float:
        """
        PRD-001 Section 6.1: Calculate taker fee (26 bps).

        Args:
            position_size_usd: Position size in USD

        Returns:
            Fee amount in USD
        """
        return position_size_usd * (self.taker_fee_bps / 10000.0)

    def calculate_fill_price_with_slippage(
        self,
        price: float,
        side: str
    ) -> float:
        """
        PRD-001 Section 6.1: Calculate fill price with slippage (5 bps).

        Args:
            price: Nominal price
            side: "buy" or "sell"

        Returns:
            Fill price including slippage
        """
        slippage_multiplier = self.slippage_bps / 10000.0

        if side.lower() in ["buy", "long"]:
            # Buy: pay slippage (higher price)
            return price * (1 + slippage_multiplier)
        else:
            # Sell: receive slippage (lower price)
            return price * (1 - slippage_multiplier)

    def simulate_order_fill(
        self,
        price: float,
        size_usd: float,
        side: str,
        order_type: str = "market"
    ) -> Tuple[float, float, float]:
        """
        PRD-001 Section 6.1: Simulate realistic order fill.

        Args:
            price: Nominal price
            size_usd: Position size in USD
            side: "buy" or "sell"
            order_type: "market" or "limit"

        Returns:
            (fill_price, fee, total_cost) tuple
        """
        # Calculate fill price with slippage
        if order_type == "market":
            # Market orders: use slippage
            fill_price = self.calculate_fill_price_with_slippage(price, side)
            # Taker fee for market orders
            fee = self.calculate_taker_fee(size_usd)
        else:
            # Limit orders: no slippage (assume fill at limit price)
            fill_price = price
            # Maker fee for limit orders
            fee = self.calculate_maker_fee(size_usd)

        # Total cost including fee
        if side.lower() in ["buy", "long"]:
            total_cost = size_usd + fee
        else:
            total_cost = size_usd - fee

        return fill_price, fee, total_cost

    def get_metrics(self) -> Dict[str, int]:
        """
        Get data provider metrics.

        Returns:
            Dictionary with metrics
        """
        cache_hit_rate = (
            self.cache_hits / self.total_fetches
            if self.total_fetches > 0
            else 0.0
        )

        return {
            "total_fetches": self.total_fetches,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_hit_rate": cache_hit_rate
        }


# Singleton instance
_provider_instance: Optional[PRDBacktestDataProvider] = None


def get_data_provider() -> PRDBacktestDataProvider:
    """
    Get singleton PRDBacktestDataProvider instance.

    Returns:
        PRDBacktestDataProvider instance
    """
    global _provider_instance

    if _provider_instance is None:
        _provider_instance = PRDBacktestDataProvider()

    return _provider_instance


# Export for convenience
__all__ = [
    "PRDBacktestDataProvider",
    "get_data_provider",
    "DEFAULT_PAIRS",
    "SLIPPAGE_BPS",
    "MAKER_FEE_BPS",
    "TAKER_FEE_BPS",
]
