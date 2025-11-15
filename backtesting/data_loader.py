"""
Historical data loader for backtesting.

Fetches OHLCV data from exchanges (Kraken, Binance, etc.) and prepares
it for backtesting simulations.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import ccxt

logger = logging.getLogger(__name__)


class DataLoader:
    """
    Load historical OHLCV data for backtesting.

    Supports multiple exchanges via CCXT library.
    """

    def __init__(self, exchange: str = "kraken"):
        """
        Initialize data loader.

        Args:
            exchange: Exchange name (kraken, binance, etc.)
        """
        self.exchange_name = exchange
        self.exchange = getattr(ccxt, exchange)()
        self.exchange.enableRateLimit = True

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start_date: str,
        end_date: str,
        limit: int = 1000,
    ) -> pd.DataFrame:
        """
        Fetch historical OHLCV data.

        Args:
            symbol: Trading pair (e.g., BTC/USD, ETH/USD)
            timeframe: Candle timeframe (1m, 5m, 1h, 1d)
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            limit: Max candles per request (exchange-dependent)

        Returns:
            DataFrame with columns: timestamp, open, high, low, close, volume

        Example:
            >>> loader = DataLoader("kraken")
            >>> df = loader.fetch_ohlcv(
            ...     "BTC/USD",
            ...     "1h",
            ...     "2023-01-01",
            ...     "2023-12-31"
            ... )
            >>> print(f"Loaded {len(df)} candles")
        """
        logger.info(
            f"Fetching {symbol} {timeframe} data from {start_date} to {end_date}"
        )

        # Convert dates to timestamps
        start_ts = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp() * 1000)
        end_ts = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp() * 1000)

        all_candles = []
        current_ts = start_ts

        # Fetch in chunks (exchanges have limits)
        while current_ts < end_ts:
            try:
                candles = self.exchange.fetch_ohlcv(
                    symbol,
                    timeframe,
                    since=current_ts,
                    limit=limit,
                )

                if not candles:
                    break

                all_candles.extend(candles)

                # Update timestamp for next batch
                current_ts = candles[-1][0] + 1

                logger.debug(
                    f"Fetched {len(candles)} candles, "
                    f"total: {len(all_candles)}, "
                    f"latest: {datetime.fromtimestamp(current_ts/1000)}"
                )

                # Stop if we've reached the end
                if current_ts >= end_ts:
                    break

            except Exception as e:
                logger.error(f"Error fetching data: {e}")
                break

        # Convert to DataFrame
        df = pd.DataFrame(
            all_candles,
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )

        # Convert timestamp to datetime
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")

        # Filter to exact date range
        df = df[
            (df["timestamp"] >= start_date) &
            (df["timestamp"] <= end_date)
        ]

        logger.info(
            f"Loaded {len(df)} candles for {symbol} "
            f"from {df['timestamp'].min()} to {df['timestamp'].max()}"
        )

        return df

    def fetch_multiple_symbols(
        self,
        symbols: list[str],
        timeframe: str,
        start_date: str,
        end_date: str,
    ) -> dict[str, pd.DataFrame]:
        """
        Fetch data for multiple symbols.

        Args:
            symbols: List of trading pairs
            timeframe: Candle timeframe
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            Dictionary mapping symbol to DataFrame
        """
        data = {}

        for symbol in symbols:
            try:
                df = self.fetch_ohlcv(symbol, timeframe, start_date, end_date)
                data[symbol] = df
            except Exception as e:
                logger.error(f"Failed to fetch {symbol}: {e}")

        return data


def prepare_backtest_data(
    df: pd.DataFrame,
    lookback_periods: int = 300,
) -> list[pd.DataFrame]:
    """
    Prepare rolling windows for backtesting.

    Each window contains `lookback_periods` candles for strategy calculation.

    Args:
        df: OHLCV DataFrame
        lookback_periods: Number of periods to look back for each decision

    Returns:
        List of DataFrames, one per timestep

    Example:
        >>> df = loader.fetch_ohlcv("BTC/USD", "1h", "2023-01-01", "2023-12-31")
        >>> windows = prepare_backtest_data(df, lookback_periods=300)
        >>> print(f"Generated {len(windows)} backtest timesteps")
    """
    if len(df) < lookback_periods:
        raise ValueError(
            f"Insufficient data: {len(df)} rows, need at least {lookback_periods}"
        )

    windows = []

    for i in range(lookback_periods, len(df)):
        window = df.iloc[i - lookback_periods : i].copy()
        windows.append(window)

    return windows


# =============================================================================
# SELF-CHECK
# =============================================================================

if __name__ == "__main__":
    """Self-check: Fetch sample data from Kraken"""
    import sys

    logging.basicConfig(level=logging.INFO)

    # Test data loader
    loader = DataLoader("kraken")

    # Fetch 7 days of BTC/USD 1h data
    end_date = datetime.now()
    start_date = end_date - timedelta(days=7)

    try:
        df = loader.fetch_ohlcv(
            "BTC/USD",
            "1h",
            start_date.strftime("%Y-%m-%d"),
            end_date.strftime("%Y-%m-%d"),
        )

        print(f"\nPASS Data Loader Self-Check:")
        print(f"  Fetched {len(df)} candles")
        print(f"  Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
        print(f"  Price range: ${df['close'].min():.2f} - ${df['close'].max():.2f}")
        print(f"\nFirst 3 rows:")
        print(df.head(3))

        # Test window preparation
        windows = prepare_backtest_data(df, lookback_periods=24)
        print(f"\nPrepared {len(windows)} backtest windows")

    except Exception as e:
        print(f"\nFAIL Data Loader Self-Check: {e}", file=sys.stderr)
        sys.exit(1)
