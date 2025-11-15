"""
Fetch Historical OHLCV Data from Kraken

Fetches real historical 1-minute OHLCV data from Kraken for backtesting.
Supports multiple pairs and lookback periods (180d, 365d).

Usage:
    python scripts/fetch_kraken_historical.py --lookback 180 --pairs BTC/USD,ETH/USD
    python scripts/fetch_kraken_historical.py --lookback 365 --pairs BTC/USD,ETH/USD --output data/historical/
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

import ccxt
import pandas as pd

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


class KrakenHistoricalFetcher:
    """Fetch historical OHLCV data from Kraken."""

    def __init__(self, output_dir: str = "data/historical"):
        """Initialize Kraken historical data fetcher.

        Args:
            output_dir: Directory to save historical data
        """
        self.exchange = ccxt.kraken(
            {
                "enableRateLimit": True,
                "timeout": 30000,
                "rateLimit": 1000,  # Kraken: 1 request per second for public endpoints
            }
        )
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Kraken fetcher initialized. Output: {self.output_dir}")

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1m",
        lookback_days: int = 180,
    ) -> pd.DataFrame:
        """Fetch OHLCV data for a symbol.

        Args:
            symbol: Trading pair (e.g., "BTC/USD")
            timeframe: Candle timeframe (1m, 5m, 15m, 1h, etc.)
            lookback_days: Number of days to fetch

        Returns:
            DataFrame with OHLCV data
        """
        logger.info(f"Fetching {symbol} {timeframe} data ({lookback_days}d lookback)...")

        # Calculate time range
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(days=lookback_days)

        # Convert to milliseconds
        since = int(start_time.timestamp() * 1000)
        end_ms = int(end_time.timestamp() * 1000)

        all_candles = []
        current_since = since

        # Fetch in batches (Kraken limit: 720 candles per request for 1m)
        batch_count = 0
        max_batches = 10000  # Safety limit

        while current_since < end_ms and batch_count < max_batches:
            try:
                logger.info(
                    f"  Batch {batch_count + 1}: Fetching from {datetime.fromtimestamp(current_since / 1000, timezone.utc)}"
                )

                # Fetch batch
                candles = self.exchange.fetch_ohlcv(
                    symbol=symbol,
                    timeframe=timeframe,
                    since=current_since,
                    limit=720,  # Kraken max for 1m
                )

                if not candles:
                    logger.warning(f"  No more candles returned. Stopping.")
                    break

                all_candles.extend(candles)
                batch_count += 1

                # Update since to last candle timestamp + 1ms
                current_since = candles[-1][0] + 1

                # Stop if we've reached end time
                if candles[-1][0] >= end_ms:
                    logger.info(f"  Reached end time. Stopping.")
                    break

                # Rate limiting (Kraken: ~1 req/sec)
                logger.info(f"  Fetched {len(candles)} candles. Sleeping 1.2s (rate limit)...")
                time.sleep(1.2)

            except Exception as e:
                logger.error(f"  Error fetching batch {batch_count + 1}: {e}")
                logger.info(f"  Sleeping 5s before retry...")
                time.sleep(5)
                continue

        # Convert to DataFrame
        df = pd.DataFrame(
            all_candles,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )

        # Convert timestamp to datetime
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)

        # Remove duplicates (can happen at batch boundaries)
        df = df.drop_duplicates(subset=["timestamp"], keep="first")

        # Sort by timestamp
        df = df.sort_values("timestamp").reset_index(drop=True)

        logger.info(
            f"[OK] Fetched {len(df):,} candles for {symbol} "
            f"from {df['timestamp'].min()} to {df['timestamp'].max()}"
        )

        return df

    def save_to_csv(
        self,
        df: pd.DataFrame,
        symbol: str,
        timeframe: str,
        lookback_days: int,
    ) -> Path:
        """Save DataFrame to CSV.

        Args:
            df: DataFrame with OHLCV data
            symbol: Trading pair
            timeframe: Candle timeframe
            lookback_days: Lookback period

        Returns:
            Path to saved CSV file
        """
        # Create filename
        symbol_clean = symbol.replace("/", "_")
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"{symbol_clean}_{timeframe}_{lookback_days}d_{timestamp}.csv"
        filepath = self.output_dir / filename

        # Save CSV
        df.to_csv(filepath, index=False)
        logger.info(f"[SAVED] Saved {len(df):,} rows to {filepath}")

        return filepath

    def fetch_and_save(
        self,
        symbol: str,
        timeframe: str = "1m",
        lookback_days: int = 180,
    ) -> Path:
        """Fetch and save OHLCV data.

        Args:
            symbol: Trading pair
            timeframe: Candle timeframe
            lookback_days: Lookback period

        Returns:
            Path to saved CSV file
        """
        df = self.fetch_ohlcv(symbol, timeframe, lookback_days)
        filepath = self.save_to_csv(df, symbol, timeframe, lookback_days)
        return filepath

    def validate_data(self, df: pd.DataFrame, symbol: str) -> bool:
        """Validate fetched data quality.

        Args:
            df: DataFrame to validate
            symbol: Trading pair

        Returns:
            True if data passes validation
        """
        logger.info(f"Validating data for {symbol}...")

        issues = []

        # Check for missing data
        if df.isnull().any().any():
            null_cols = df.columns[df.isnull().any()].tolist()
            issues.append(f"NULL values in columns: {null_cols}")

        # Check for zero/negative prices
        price_cols = ["open", "high", "low", "close"]
        for col in price_cols:
            if (df[col] <= 0).any():
                count = (df[col] <= 0).sum()
                issues.append(f"{count} zero/negative values in {col}")

        # Check for high < low
        if (df["high"] < df["low"]).any():
            count = (df["high"] < df["low"]).sum()
            issues.append(f"{count} candles with high < low")

        # Check for gaps in timestamps
        df_sorted = df.sort_values("timestamp").copy()
        if len(df_sorted) > 1:
            time_diff = pd.to_datetime(df_sorted["timestamp"]).diff()
            expected_diff = pd.Timedelta(minutes=1)  # Assuming 1m candles
            gaps = time_diff[time_diff > expected_diff * 2]  # Allow 2x for some tolerance
            if len(gaps) > 0:
                issues.append(f"{len(gaps)} time gaps detected")

        # Report results
        if issues:
            logger.warning(f"[WARNING] Data validation issues for {symbol}:")
            for issue in issues:
                logger.warning(f"  - {issue}")
            return False
        else:
            logger.info(f"[OK] Data validation passed for {symbol}")
            return True


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Fetch historical OHLCV data from Kraken"
    )
    parser.add_argument(
        "--lookback",
        type=int,
        default=180,
        help="Lookback period in days (default: 180)",
    )
    parser.add_argument(
        "--pairs",
        type=str,
        default="BTC/USD,ETH/USD",
        help="Comma-separated trading pairs (default: BTC/USD,ETH/USD)",
    )
    parser.add_argument(
        "--timeframe",
        type=str,
        default="1m",
        help="Candle timeframe (default: 1m)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/historical",
        help="Output directory (default: data/historical)",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate data quality after fetching",
    )

    args = parser.parse_args()

    # Parse pairs
    pairs = [p.strip() for p in args.pairs.split(",")]

    logger.info("=" * 70)
    logger.info("KRAKEN HISTORICAL DATA FETCHER")
    logger.info("=" * 70)
    logger.info(f"Pairs: {pairs}")
    logger.info(f"Timeframe: {args.timeframe}")
    logger.info(f"Lookback: {args.lookback} days")
    logger.info(f"Output: {args.output}")
    logger.info(f"Validate: {args.validate}")
    logger.info("=" * 70)

    # Initialize fetcher
    fetcher = KrakenHistoricalFetcher(output_dir=args.output)

    # Fetch data for each pair
    results = []
    for pair in pairs:
        try:
            logger.info(f"\n[PROCESSING] {pair}...")
            filepath = fetcher.fetch_and_save(
                symbol=pair,
                timeframe=args.timeframe,
                lookback_days=args.lookback,
            )

            # Validate if requested
            if args.validate:
                df = pd.read_csv(filepath)
                fetcher.validate_data(df, pair)

            results.append({"pair": pair, "status": "SUCCESS", "filepath": filepath})

        except Exception as e:
            logger.error(f"[FAILED] Failed to fetch {pair}: {e}")
            results.append({"pair": pair, "status": "FAILED", "error": str(e)})

    # Print summary
    logger.info("\n" + "=" * 70)
    logger.info("SUMMARY")
    logger.info("=" * 70)
    for result in results:
        if result["status"] == "SUCCESS":
            logger.info(f"[OK] {result['pair']}: {result['filepath']}")
        else:
            logger.error(f"[FAILED] {result['pair']}: {result['error']}")

    # Return exit code
    failed_count = sum(1 for r in results if r["status"] == "FAILED")
    if failed_count > 0:
        logger.error(f"\n[FAILED] {failed_count}/{len(results)} pairs failed")
        sys.exit(1)
    else:
        logger.info(f"\n[SUCCESS] All {len(results)} pairs fetched successfully!")
        sys.exit(0)


if __name__ == "__main__":
    main()
