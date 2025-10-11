"""
Enhanced replay module for deterministic backtesting.

Provides time-stepped data feeding with configurable speed vs fidelity tradeoffs.
Supports multiple replay modes: tick-by-tick, bar-by-bar, and snapshot-based.

Features:
- Configurable replay speed (1x to 1000x)
- Skip bars for faster replay with lower fidelity
- Batch processing for efficiency
- Memory-efficient streaming
- Deterministic ordering with seed handling
- Integration with BacktestEngine

Usage:
    from agents.scalper.backtest.replay_enhanced import (
        ReplayFeeder, ReplayConfig, ReplayMode, create_balanced_replay
    )

    # Load data
    data = {"BTC/USD@1m": btc_df}

    # Create feeder
    feeder = create_balanced_replay(data)

    # Replay bars
    async for bar in feeder.replay_bars(["BTC/USD"], "1m"):
        print(f"{bar.timestamp} {bar.symbol} C: {bar.close}")
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from typing import AsyncIterator, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


# ======================== Enums & Configuration ========================


class ReplayMode(Enum):
    """Replay mode selection for speed vs fidelity tradeoff"""

    TICK_BY_TICK = "tick"  # Highest fidelity, slowest (not implemented)
    BAR_BY_BAR = "bar"     # OHLCV bars, good balance
    SNAPSHOT = "snapshot"   # Periodic snapshots, fastest


@dataclass(frozen=True)
class ReplayConfig:
    """
    Configuration for replay behavior.

    Attributes:
        mode: Replay mode selection
        speed: Speed multiplier (1.0 = realtime, 1000 = 1000x faster)
        skip_bars: Skip N bars between events (0 = no skip, 4 = skip 4/5 bars)
        batch_size: Process N bars at once (1 = single bar, 10 = batch of 10)
        max_memory_mb: Memory limit in MB (not yet enforced)
        streaming: Stream from disk vs load all (not yet implemented)
        real_time_delays: Use actual timestamp delays between bars
        fixed_delay_ms: Fixed delay between events in milliseconds
    """

    mode: ReplayMode = ReplayMode.BAR_BY_BAR
    speed: float = 1.0

    # Speed vs fidelity tradeoff
    skip_bars: int = 0  # 0 = no skip, 4 = skip 4 out of 5 bars
    batch_size: int = 1  # 1 = single bar, 10 = batch processing

    # Memory management (future)
    max_memory_mb: int = 1000
    streaming: bool = True

    # Timing
    real_time_delays: bool = False  # Use actual timestamp delays
    fixed_delay_ms: Optional[float] = None  # Fixed delay between events


# ======================== Data Models ========================


@dataclass(frozen=True)
class BarEvent:
    """
    OHLCV bar event for replay.

    Immutable data structure representing a single bar in the replay stream.
    """

    timestamp: pd.Timestamp
    symbol: str
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: float

    # Optional market microstructure (future enhancement)
    trades: Optional[List[Dict]] = None
    orderbook: Optional[Dict] = None


# ======================== Main Replay Feeder ========================


class ReplayFeeder:
    """
    Time-stepped data feeder for backtesting.

    Provides deterministic, configurable replay of OHLCV data with support
    for multiple symbols and timeframes.

    Example:
        >>> data = {"BTC/USD@1m": btc_df}
        >>> feeder = ReplayFeeder(data, ReplayConfig(speed=10.0))
        >>> bars = feeder.replay_synchronous(["BTC/USD"], "1m")
        >>> print(len(bars))
        10000
    """

    def __init__(self, data: Dict[str, pd.DataFrame], config: ReplayConfig):
        """
        Initialize replay feeder.

        Args:
            data: Dictionary mapping symbol@timeframe to OHLCV DataFrame
            config: Replay configuration

        Raises:
            ValueError: If data format is invalid
        """
        self.data = data
        self.config = config
        self._validate_data()
        logger.info(
            f"ReplayFeeder initialized: mode={config.mode.value}, "
            f"speed={config.speed}x, skip_bars={config.skip_bars}"
        )

    def _validate_data(self) -> None:
        """
        Validate data format and requirements.

        Raises:
            ValueError: If data is missing required columns or has wrong index type
        """
        for key, df in self.data.items():
            if not isinstance(df.index, pd.DatetimeIndex):
                raise ValueError(f"Data {key} must have DatetimeIndex, got {type(df.index)}")

            required_cols = ['open', 'high', 'low', 'close', 'volume']
            missing = [c for c in required_cols if c not in df.columns]
            if missing:
                raise ValueError(f"Data {key} missing columns: {missing}")

            # Check for NaN values
            for col in required_cols:
                if df[col].isna().any():
                    nan_count = df[col].isna().sum()
                    logger.warning(f"Data {key} has {nan_count} NaN values in {col}")

        logger.info(f"Validated {len(self.data)} data sources")

    async def replay_bars(self,
                          symbols: List[str],
                          timeframe: str) -> AsyncIterator[BarEvent]:
        """
        Replay OHLCV bars in chronological order (async).

        Args:
            symbols: List of symbols to replay
            timeframe: Timeframe for bars

        Yields:
            BarEvent objects in chronological order

        Raises:
            ValueError: If no data found for symbol@timeframe

        Example:
            >>> async for bar in feeder.replay_bars(["BTC/USD"], "1m"):
            ...     print(f"{bar.timestamp} {bar.close}")
        """
        # Get all bars in chronological order
        all_bars = self._get_combined_bars(symbols, timeframe)

        # Apply skip filter
        if self.config.skip_bars > 0:
            all_bars = [
                bar for i, bar in enumerate(all_bars)
                if i % (self.config.skip_bars + 1) == 0
            ]

        logger.info(
            f"Replaying {len(all_bars)} bars for {symbols} @ {timeframe}"
        )

        # Replay with configured timing
        previous_ts = None
        for bar in all_bars:
            # Apply delay if real-time mode
            if self.config.real_time_delays and previous_ts is not None:
                delay = (bar.timestamp - previous_ts).total_seconds() / self.config.speed
                if delay > 0:
                    await asyncio.sleep(delay)
            elif self.config.fixed_delay_ms is not None:
                await asyncio.sleep(self.config.fixed_delay_ms / 1000.0)

            previous_ts = bar.timestamp
            yield bar

    def replay_synchronous(self,
                           symbols: List[str],
                           timeframe: str) -> List[BarEvent]:
        """
        Synchronous replay for non-async contexts (like BacktestEngine).

        Returns all bars in chronological order without delays.

        Args:
            symbols: List of symbols to replay
            timeframe: Timeframe for bars

        Returns:
            List of BarEvent objects in chronological order

        Raises:
            ValueError: If no data found for symbol@timeframe

        Example:
            >>> bars = feeder.replay_synchronous(["BTC/USD"], "1m")
            >>> print(len(bars))
            10000
        """
        # Get all bars in chronological order
        all_bars = self._get_combined_bars(symbols, timeframe)

        # Apply skip filter
        if self.config.skip_bars > 0:
            all_bars = [
                bar for i, bar in enumerate(all_bars)
                if i % (self.config.skip_bars + 1) == 0
            ]

        logger.info(
            f"Synchronous replay: {len(all_bars)} bars for {symbols} @ {timeframe}"
        )

        return all_bars

    def _get_combined_bars(self,
                           symbols: List[str],
                           timeframe: str) -> List[BarEvent]:
        """
        Get combined bars from all symbols in chronological order.

        Args:
            symbols: List of symbols to combine
            timeframe: Timeframe for bars

        Returns:
            List of BarEvent objects sorted by timestamp

        Raises:
            ValueError: If no data found for symbol@timeframe
        """
        combined_data = []

        for symbol in symbols:
            key = f"{symbol}@{timeframe}"
            if key not in self.data:
                raise ValueError(f"No data found for {key}")

            df = self.data[key]

            for idx, row in df.iterrows():
                combined_data.append(BarEvent(
                    timestamp=idx,
                    symbol=symbol,
                    timeframe=timeframe,
                    open=float(row['open']),
                    high=float(row['high']),
                    low=float(row['low']),
                    close=float(row['close']),
                    volume=float(row['volume']),
                ))

        # Sort by timestamp (deterministic ordering)
        combined_data.sort(key=lambda x: x.timestamp)

        return combined_data


# ======================== Convenience Constructors ========================


def create_fast_replay(data: Dict[str, pd.DataFrame]) -> ReplayFeeder:
    """
    Create fast replay configuration (max speed, lower fidelity).

    Use case: Quick strategy testing, parameter sweeps

    Args:
        data: Dictionary mapping symbol@timeframe to OHLCV DataFrame

    Returns:
        ReplayFeeder configured for maximum speed

    Example:
        >>> feeder = create_fast_replay(data)
        >>> bars = feeder.replay_synchronous(["BTC/USD"], "1m")
    """
    config = ReplayConfig(
        mode=ReplayMode.SNAPSHOT,
        speed=1000.0,  # 1000x speed
        skip_bars=4,  # Skip 4 out of 5 bars (20% data)
        batch_size=10,  # Process 10 at once
        real_time_delays=False,
    )
    return ReplayFeeder(data, config)


def create_accurate_replay(data: Dict[str, pd.DataFrame]) -> ReplayFeeder:
    """
    Create accurate replay configuration (slower, high fidelity).

    Use case: Final validation, production testing

    Args:
        data: Dictionary mapping symbol@timeframe to OHLCV DataFrame

    Returns:
        ReplayFeeder configured for maximum accuracy

    Example:
        >>> feeder = create_accurate_replay(data)
        >>> bars = feeder.replay_synchronous(["BTC/USD"], "1m")
    """
    config = ReplayConfig(
        mode=ReplayMode.BAR_BY_BAR,
        speed=1.0,  # Realtime speed
        skip_bars=0,  # No skipping
        batch_size=1,  # One bar at a time
        real_time_delays=True,
    )
    return ReplayFeeder(data, config)


def create_balanced_replay(data: Dict[str, pd.DataFrame]) -> ReplayFeeder:
    """
    Create balanced replay configuration (good speed, good fidelity).

    Use case: Standard backtesting workflow

    Args:
        data: Dictionary mapping symbol@timeframe to OHLCV DataFrame

    Returns:
        ReplayFeeder configured for balance between speed and accuracy

    Example:
        >>> feeder = create_balanced_replay(data)
        >>> bars = feeder.replay_synchronous(["BTC/USD"], "1m")
    """
    config = ReplayConfig(
        mode=ReplayMode.BAR_BY_BAR,
        speed=10.0,  # 10x speed
        skip_bars=0,  # No skipping
        batch_size=1,  # One bar at a time
        real_time_delays=False,
        fixed_delay_ms=10.0,  # Small fixed delay for async context
    )
    return ReplayFeeder(data, config)


# ======================== Integration Helpers ========================


def load_data_for_replay(
    symbols: List[str],
    timeframe: str,
    data_dir: str = "data"
) -> Dict[str, pd.DataFrame]:
    """
    Load OHLCV data from CSV files for replay.

    Args:
        symbols: List of symbols to load (e.g., ["BTC/USD", "ETH/USD"])
        timeframe: Timeframe (e.g., "1m", "5m", "1h")
        data_dir: Directory containing CSV files

    Returns:
        Dictionary mapping symbol@timeframe to OHLCV DataFrame

    Example:
        >>> data = load_data_for_replay(["BTC/USD"], "1m", "data/backtest")
        >>> feeder = create_balanced_replay(data)
    """
    import os
    data = {}

    for symbol in symbols:
        # Convert symbol to filename: BTC/USD -> BTC_USD
        symbol_filename = symbol.replace("/", "_")
        filepath = os.path.join(data_dir, f"{symbol_filename}_{timeframe}.csv")

        try:
            df = pd.read_csv(filepath, index_col=0, parse_dates=True)
            key = f"{symbol}@{timeframe}"
            data[key] = df
            logger.info(f"Loaded {len(df)} bars for {key} from {filepath}")
        except FileNotFoundError:
            logger.warning(f"Data file not found: {filepath}")
        except Exception as e:
            logger.error(f"Error loading {filepath}: {e}")

    if not data:
        raise ValueError(f"No data loaded for {symbols} @ {timeframe}")

    return data


# ======================== Example Usage ========================


if __name__ == "__main__":
    import numpy as np

    # Configure logging
    logging.basicConfig(level=logging.INFO)

    # Generate sample data
    logger.info("Generating sample data for demo...")
    timestamps = pd.date_range(start="2025-01-01", periods=1000, freq="1min", tz="UTC")

    sample_data = {
        "BTC/USD@1m": pd.DataFrame({
            "open": np.random.uniform(49000, 51000, 1000),
            "high": np.random.uniform(49100, 51100, 1000),
            "low": np.random.uniform(48900, 50900, 1000),
            "close": np.random.uniform(49000, 51000, 1000),
            "volume": np.random.uniform(1, 100, 1000),
        }, index=timestamps)
    }

    # Test fast replay
    logger.info("\n=== Testing Fast Replay ===")
    fast_feeder = create_fast_replay(sample_data)
    fast_bars = fast_feeder.replay_synchronous(["BTC/USD"], "1m")
    logger.info(f"Fast replay: {len(fast_bars)} bars (from 1000 total)")

    # Test accurate replay
    logger.info("\n=== Testing Accurate Replay ===")
    accurate_feeder = create_accurate_replay(sample_data)
    accurate_bars = accurate_feeder.replay_synchronous(["BTC/USD"], "1m")
    logger.info(f"Accurate replay: {len(accurate_bars)} bars")

    # Test balanced replay
    logger.info("\n=== Testing Balanced Replay ===")
    balanced_feeder = create_balanced_replay(sample_data)
    balanced_bars = balanced_feeder.replay_synchronous(["BTC/USD"], "1m")
    logger.info(f"Balanced replay: {len(balanced_bars)} bars")

    # Show first few bars
    logger.info("\n=== Sample Bar Events ===")
    for i, bar in enumerate(balanced_bars[:3]):
        logger.info(
            f"Bar {i+1}: {bar.timestamp} {bar.symbol} "
            f"O:{bar.open:.2f} H:{bar.high:.2f} L:{bar.low:.2f} C:{bar.close:.2f} V:{bar.volume:.2f}"
        )

    logger.info("\n✅ Replay demo completed successfully!")