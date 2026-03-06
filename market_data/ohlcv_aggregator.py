"""
OHLCV Aggregator with Feed Health Tracking
============================================

Builds OHLCV candles from raw price ticks and tracks per-exchange
feed freshness. Stale feeds are detected and reported so downstream
signal generation can skip corrupted data.

Redis keys published:
    ohlc:{tf_seconds}:{exchange}:{pair}   per-exchange candle
    ohlc:{tf_seconds}:any:{pair}          cross-exchange aggregate
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Candle:
    """In-progress OHLCV candle."""

    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    tick_count: int = 0
    period_start: float = 0.0  # unix timestamp of period start


class OHLCVAggregator:
    """
    Builds OHLCV candles from price ticks and tracks feed freshness.

    Usage:
        agg = OHLCVAggregator(timeframes=[60, 300])
        agg.process_tick("kraken", "BTC/USD", price=68000.0, volume=0.5)
        assert not agg.is_feed_stale("kraken", "BTC/USD", timeframe_s=60)
    """

    def __init__(
        self,
        timeframes: Optional[List[int]] = None,
        maxlen: int = 500,
        staleness_multiplier: float = 2.5,
        redis_client: Any = None,
    ) -> None:
        self._timeframes = timeframes or [15, 60, 300]
        self._maxlen = maxlen
        self._staleness_multiplier = float(
            os.getenv("FEED_STALENESS_MULTIPLIER", str(staleness_multiplier))
        )
        self._enabled = os.getenv("FEED_STALENESS_ENABLED", "true").lower() == "true"
        self._redis = redis_client

        # Per-exchange feed health: "{exchange}:{pair}" -> last tick time
        self._last_tick_time: Dict[str, float] = {}

        # Active candles: "{exchange}:{pair}:{tf}" -> Candle
        self._active_candles: Dict[str, Candle] = {}

        # Completed candle count for metrics
        self._candles_published: int = 0
        self._ticks_processed: int = 0

    # -- Tick ingestion -------------------------------------------------------

    def process_tick(
        self,
        exchange: str,
        pair: str,
        price: float,
        volume: float = 0.0,
        timestamp: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Ingest a price tick and update all timeframe candles.

        Args:
            exchange: Exchange ID (e.g. "kraken")
            pair: Trading pair (e.g. "BTC/USD")
            price: Current price
            volume: Trade volume (default 0)
            timestamp: Unix timestamp (default: now)

        Returns:
            List of completed candle dicts (period closed), empty if none completed.
        """
        ts = timestamp or time.time()
        feed_key = f"{exchange}:{pair}"
        self._last_tick_time[feed_key] = ts
        self._ticks_processed += 1

        completed: List[Dict[str, Any]] = []

        for tf in self._timeframes:
            candle_key = f"{exchange}:{pair}:{tf}"
            period_start = (int(ts) // tf) * tf

            candle = self._active_candles.get(candle_key)

            if candle is None or candle.period_start != period_start:
                # New period — emit previous candle if exists
                if candle is not None and candle.tick_count > 0:
                    completed_candle = {
                        "exchange": exchange,
                        "pair": pair,
                        "timeframe_s": tf,
                        "period_start": candle.period_start,
                        "open": candle.open,
                        "high": candle.high,
                        "low": candle.low,
                        "close": candle.close,
                        "volume": candle.volume,
                        "tick_count": candle.tick_count,
                    }
                    completed.append(completed_candle)
                    self._candles_published += 1

                # Start new candle
                self._active_candles[candle_key] = Candle(
                    open=price,
                    high=price,
                    low=price,
                    close=price,
                    volume=volume,
                    tick_count=1,
                    period_start=period_start,
                )
            else:
                # Update existing candle
                candle.high = max(candle.high, price)
                candle.low = min(candle.low, price)
                candle.close = price
                candle.volume += volume
                candle.tick_count += 1

        return completed

    # -- Feed health ----------------------------------------------------------

    def is_feed_stale(
        self, exchange: str, pair: str, timeframe_s: int = 60
    ) -> bool:
        """
        Check if a feed is stale (no tick received within staleness window).

        Args:
            exchange: Exchange ID
            pair: Trading pair
            timeframe_s: Reference timeframe in seconds

        Returns:
            True if feed is stale (last tick older than timeframe_s * multiplier)
        """
        if not self._enabled:
            return False

        feed_key = f"{exchange}:{pair}"
        last_tick = self._last_tick_time.get(feed_key, 0)
        threshold = timeframe_s * self._staleness_multiplier
        return (time.time() - last_tick) > threshold

    def get_stale_feeds(self, timeframe_s: int = 60) -> List[str]:
        """
        Get list of feed keys currently stale.

        Returns:
            List of "{exchange}:{pair}" strings that are stale.
        """
        stale: List[str] = []
        for feed_key in self._last_tick_time:
            parts = feed_key.split(":", 1)
            if len(parts) == 2:
                exchange, pair = parts
                if self.is_feed_stale(exchange, pair, timeframe_s):
                    stale.append(feed_key)
        return stale

    def get_feed_health_summary(
        self, timeframe_s: int = 60
    ) -> Dict[str, Dict[str, Any]]:
        """
        Get health summary for all tracked feeds.

        Returns:
            Dict mapping feed_key to {last_tick_age_s, is_stale, timeframe_s}
        """
        now = time.time()
        summary: Dict[str, Dict[str, Any]] = {}
        for feed_key, last_tick in self._last_tick_time.items():
            age = now - last_tick
            parts = feed_key.split(":", 1)
            exchange = parts[0] if parts else ""
            pair = parts[1] if len(parts) > 1 else ""
            summary[feed_key] = {
                "last_tick_age_s": round(age, 1),
                "is_stale": self.is_feed_stale(exchange, pair, timeframe_s),
                "timeframe_s": timeframe_s,
            }
        return summary

    def get_metrics(self) -> Dict[str, Any]:
        """Get aggregator metrics for ops endpoints."""
        return {
            "ticks_processed": self._ticks_processed,
            "candles_published": self._candles_published,
            "active_candles": len(self._active_candles),
            "tracked_feeds": len(self._last_tick_time),
            "stale_feeds": len(self.get_stale_feeds()),
            "staleness_multiplier": self._staleness_multiplier,
            "enabled": self._enabled,
        }


# Module-level singleton
_aggregator: Optional[OHLCVAggregator] = None


def get_aggregator() -> OHLCVAggregator:
    """Get or create the module-level OHLCVAggregator singleton."""
    global _aggregator
    if _aggregator is None:
        timeframes_env = os.getenv("OHLCV_AGGREGATOR_TIMEFRAMES", "15,60,300")
        timeframes = [int(t) for t in timeframes_env.split(",")]
        maxlen = int(os.getenv("OHLCV_AGGREGATOR_MAXLEN", "500"))
        _aggregator = OHLCVAggregator(timeframes=timeframes, maxlen=maxlen)
    return _aggregator
