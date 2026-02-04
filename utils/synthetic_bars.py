"""
Synthetic OHLCV Bar Builder for Sub-Minute Timeframes

Creates synthetic OHLCV bars from trade ticks using time-bucketing.
Optimized for 5s and 15s timeframes with strict latency requirements.

Features:
- Sub-second precision time bucketing
- Bucket boundary alignment (e.g., 15s bars at :00, :15, :30, :45)
- Quality filtering (minimum trades per bucket)
- Redis stream publishing
- Latency tracking and monitoring

Author: Crypto AI Bot Team
Date: 2025-11-08
"""

import asyncio
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Deque

import redis.asyncio as redis

logger = logging.getLogger(__name__)


@dataclass
class Trade:
    """Individual trade tick."""
    timestamp: float  # Unix timestamp with millisecond precision
    price: Decimal
    volume: Decimal
    side: str  # "buy" or "sell"
    trade_id: Optional[str] = None


@dataclass
class OHLCV:
    """OHLCV bar."""
    timestamp: float  # Bucket start time
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    trade_count: int = 0
    vwap: Optional[Decimal] = None
    buy_volume: Decimal = Decimal("0")
    sell_volume: Decimal = Decimal("0")

    def to_dict(self) -> dict:
        """Convert to dictionary for Redis/JSON serialization."""
        return {
            "timestamp": str(self.timestamp),
            "open": str(self.open),
            "high": str(self.high),
            "low": str(self.low),
            "close": str(self.close),
            "volume": str(self.volume),
            "trade_count": str(self.trade_count),
            "vwap": str(float(self.vwap)) if self.vwap else "0.0",
            "buy_volume": str(self.buy_volume),
            "sell_volume": str(self.sell_volume),
        }


class SyntheticBarBuilder:
    """
    Builds synthetic OHLCV bars from trade ticks using time-bucketing.

    Features:
    - Bucket boundary alignment (e.g., 15s bars start at :00, :15, :30, :45)
    - Quality filtering (minimum trades per bucket)
    - Latency tracking
    - Redis stream publishing
    """

    def __init__(
        self,
        timeframe_seconds: int,
        min_trades_per_bucket: int = 1,
        redis_client: Optional[redis.Redis] = None,
        redis_stream_key: Optional[str] = None,
        symbol: str = "BTC/USD",
        latency_budget_ms: float = 100.0,
    ):
        """
        Initialize synthetic bar builder.

        Args:
            timeframe_seconds: Bar interval in seconds (e.g., 5, 15, 30)
            min_trades_per_bucket: Minimum trades required to publish a bar
            redis_client: Optional Redis client for publishing bars
            redis_stream_key: Optional Redis stream key (e.g., "kraken:ohlc:15s")
            symbol: Trading pair symbol
            latency_budget_ms: Maximum allowed latency in milliseconds
        """
        self.timeframe_seconds = timeframe_seconds
        self.min_trades_per_bucket = min_trades_per_bucket
        self.redis_client = redis_client
        self.redis_stream_key = redis_stream_key
        self.symbol = symbol
        self.latency_budget_ms = latency_budget_ms

        # Trade accumulator: bucket_timestamp -> list of trades
        self.buckets: Dict[float, List[Trade]] = defaultdict(list)

        # Completed bars (for testing/verification)
        self.completed_bars: Deque[OHLCV] = deque(maxlen=1000)

        # Metrics
        self.bars_created = 0
        self.bars_published = 0
        self.trades_processed = 0
        self.latency_samples: Deque[float] = deque(maxlen=100)

        logger.info(
            f"SyntheticBarBuilder initialized: {timeframe_seconds}s bars for {symbol}, "
            f"min_trades={min_trades_per_bucket}, latency_budget={latency_budget_ms}ms"
        )

    def get_bucket_timestamp(self, timestamp: float) -> float:
        """
        Get bucket start timestamp for a given timestamp.

        Aligns to bucket boundaries (e.g., 15s bars at :00, :15, :30, :45).

        Args:
            timestamp: Unix timestamp (seconds with decimal precision)

        Returns:
            Bucket start timestamp (aligned to boundary)

        Examples:
            >>> builder = SyntheticBarBuilder(15)
            >>> builder.get_bucket_timestamp(1699458012.345)
            1699458000.0  # Aligned to :00 seconds
            >>> builder.get_bucket_timestamp(1699458017.123)
            1699458015.0  # Aligned to :15 seconds
        """
        return (timestamp // self.timeframe_seconds) * self.timeframe_seconds

    async def add_trade(self, trade: Trade) -> Optional[OHLCV]:
        """
        Add a trade to the appropriate bucket.

        If the trade completes a bucket (crosses boundary), the completed
        bucket is processed and published.

        Args:
            trade: Trade tick to add

        Returns:
            OHLCV bar if a bucket was completed, None otherwise
        """
        start_time = time.perf_counter()
        self.trades_processed += 1

        # Get bucket for this trade
        bucket_ts = self.get_bucket_timestamp(trade.timestamp)
        self.buckets[bucket_ts].append(trade)

        # Check if we should close any old buckets
        # (a new trade with timestamp > bucket_end triggers bucket close)
        completed_bar = None
        current_time = time.time()

        # Find buckets that are complete (current time > bucket_end)
        buckets_to_close = [
            ts for ts in list(self.buckets.keys())
            if current_time >= ts + self.timeframe_seconds
        ]

        for bucket_ts in buckets_to_close:
            bar = await self._close_bucket(bucket_ts)
            if bar:
                completed_bar = bar  # Return the most recent completed bar

        # Track latency
        latency_ms = (time.perf_counter() - start_time) * 1000
        self.latency_samples.append(latency_ms)

        if latency_ms > self.latency_budget_ms:
            logger.warning(
                f"Latency budget exceeded: {latency_ms:.2f}ms > {self.latency_budget_ms}ms"
            )

        return completed_bar

    async def _close_bucket(self, bucket_ts: float) -> Optional[OHLCV]:
        """
        Close a bucket and create an OHLCV bar.

        Args:
            bucket_ts: Bucket start timestamp

        Returns:
            OHLCV bar if bucket meets quality criteria, None otherwise
        """
        trades = self.buckets.pop(bucket_ts, [])

        if len(trades) < self.min_trades_per_bucket:
            logger.debug(
                f"Bucket {datetime.fromtimestamp(bucket_ts, tz=timezone.utc)} "
                f"has {len(trades)} trades (< {self.min_trades_per_bucket}), skipping"
            )
            return None

        # Build OHLCV bar
        bar = self._build_ohlcv(bucket_ts, trades)
        self.bars_created += 1
        self.completed_bars.append(bar)

        # Publish to Redis
        if self.redis_client and self.redis_stream_key:
            await self._publish_to_redis(bar)
            self.bars_published += 1

        logger.debug(
            f"Bar created: {datetime.fromtimestamp(bucket_ts, tz=timezone.utc)} "
            f"O:{bar.open} H:{bar.high} L:{bar.low} C:{bar.close} V:{bar.volume} "
            f"Trades:{bar.trade_count}"
        )

        return bar

    def _build_ohlcv(self, bucket_ts: float, trades: List[Trade]) -> OHLCV:
        """
        Build OHLCV bar from trades.

        Args:
            bucket_ts: Bucket start timestamp
            trades: List of trades in this bucket

        Returns:
            OHLCV bar
        """
        if not trades:
            raise ValueError("Cannot build OHLCV from empty trade list")

        # Sort trades by timestamp
        sorted_trades = sorted(trades, key=lambda t: t.timestamp)

        # OHLCV calculation
        open_price = sorted_trades[0].price
        close_price = sorted_trades[-1].price
        high_price = max(t.price for t in sorted_trades)
        low_price = min(t.price for t in sorted_trades)

        # Volume aggregation
        total_volume = sum(t.volume for t in sorted_trades)
        buy_volume = sum(t.volume for t in sorted_trades if t.side == "buy")
        sell_volume = sum(t.volume for t in sorted_trades if t.side == "sell")

        # VWAP calculation
        volume_weighted_sum = sum(t.price * t.volume for t in sorted_trades)
        vwap = volume_weighted_sum / total_volume if total_volume > 0 else close_price

        return OHLCV(
            timestamp=bucket_ts,
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
            volume=total_volume,
            trade_count=len(sorted_trades),
            vwap=vwap,
            buy_volume=buy_volume,
            sell_volume=sell_volume,
        )

    async def _publish_to_redis(self, bar: OHLCV) -> None:
        """
        Publish OHLCV bar to Redis stream.

        Args:
            bar: OHLCV bar to publish
        """
        try:
            if not self.redis_client or not self.redis_stream_key:
                return

            # Create Redis stream key with symbol
            # Format: kraken:ohlc:15s:BTC-USD
            stream_key = f"{self.redis_stream_key}:{self.symbol.replace('/', '-')}"

            # Prepare data
            data = bar.to_dict()
            data["symbol"] = self.symbol
            data["timeframe"] = f"{self.timeframe_seconds}s"

            # Publish to stream with MAXLEN to prevent unbounded growth
            await self.redis_client.xadd(
                stream_key,
                data,
                maxlen=10000,  # Keep last 10k bars
                approximate=True,
            )

            logger.debug(f"Published bar to Redis: {stream_key}")

        except Exception as e:
            logger.error(f"Error publishing bar to Redis: {e}", exc_info=True)

    async def force_close_all_buckets(self) -> List[OHLCV]:
        """
        Force close all pending buckets (for shutdown/testing).

        Returns:
            List of completed OHLCV bars
        """
        bars = []
        for bucket_ts in list(self.buckets.keys()):
            bar = await self._close_bucket(bucket_ts)
            if bar:
                bars.append(bar)
        return bars

    def get_metrics(self) -> dict:
        """Get current metrics."""
        avg_latency = (
            sum(self.latency_samples) / len(self.latency_samples)
            if self.latency_samples
            else 0.0
        )
        p95_latency = (
            sorted(self.latency_samples)[int(len(self.latency_samples) * 0.95)]
            if len(self.latency_samples) >= 20
            else 0.0
        )

        return {
            "trades_processed": self.trades_processed,
            "bars_created": self.bars_created,
            "bars_published": self.bars_published,
            "pending_buckets": len(self.buckets),
            "avg_latency_ms": avg_latency,
            "p95_latency_ms": p95_latency,
            "latency_budget_ms": self.latency_budget_ms,
        }


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def create_bar_builder(
    timeframe: str,
    symbol: str = "BTC/USD",
    redis_client: Optional[redis.Redis] = None,
    min_trades_per_bucket: Optional[int] = None,
) -> SyntheticBarBuilder:
    """
    Factory function to create a SyntheticBarBuilder from timeframe string.

    Args:
        timeframe: Timeframe string (e.g., "5s", "15s", "30s")
        symbol: Trading pair symbol
        redis_client: Optional Redis client
        min_trades_per_bucket: Optional minimum trades (defaults based on timeframe)

    Returns:
        Configured SyntheticBarBuilder

    Examples:
        >>> builder = create_bar_builder("15s", "BTC/USD")
        >>> builder.timeframe_seconds
        15
    """
    # Parse timeframe
    if not timeframe.endswith("s"):
        raise ValueError(f"Only second-based timeframes supported: {timeframe}")

    timeframe_seconds = int(timeframe[:-1])

    # Set defaults based on timeframe
    if min_trades_per_bucket is None:
        if timeframe_seconds == 5:
            min_trades_per_bucket = 3  # 5s requires more trades for quality
        elif timeframe_seconds == 15:
            min_trades_per_bucket = 1  # 15s can work with 1 trade
        else:
            min_trades_per_bucket = 1

    # Set latency budget based on timeframe
    if timeframe_seconds == 5:
        latency_budget_ms = 50.0  # Ultra-strict for 5s
    elif timeframe_seconds == 15:
        latency_budget_ms = 100.0  # Strict for 15s
    else:
        latency_budget_ms = 150.0  # Relaxed for 30s+

    # Redis stream key
    redis_stream_key = f"kraken:ohlc:{timeframe}" if redis_client else None

    return SyntheticBarBuilder(
        timeframe_seconds=timeframe_seconds,
        min_trades_per_bucket=min_trades_per_bucket,
        redis_client=redis_client,
        redis_stream_key=redis_stream_key,
        symbol=symbol,
        latency_budget_ms=latency_budget_ms,
    )
