"""
Tests for OHLCV Aggregator feed health tracking.
"""

import time
from unittest.mock import patch

import pytest

from market_data.ohlcv_aggregator import OHLCVAggregator


class TestOHLCVAggregator:
    """Test OHLCV candle bucketing and feed health."""

    def test_process_tick_creates_candle(self) -> None:
        agg = OHLCVAggregator(timeframes=[60])
        completed = agg.process_tick("kraken", "BTC/USD", price=68000.0, volume=1.0)
        # First tick in period — no completed candle yet
        assert completed == []
        assert agg._ticks_processed == 1

    def test_process_tick_updates_ohlcv(self) -> None:
        agg = OHLCVAggregator(timeframes=[60])
        now = time.time()
        period_start = (int(now) // 60) * 60

        agg.process_tick("kraken", "BTC/USD", price=100.0, timestamp=period_start + 1)
        agg.process_tick("kraken", "BTC/USD", price=110.0, timestamp=period_start + 2)
        agg.process_tick("kraken", "BTC/USD", price=95.0, timestamp=period_start + 3)
        agg.process_tick("kraken", "BTC/USD", price=105.0, timestamp=period_start + 4)

        candle = agg._active_candles["kraken:BTC/USD:60"]
        assert candle.open == 100.0
        assert candle.high == 110.0
        assert candle.low == 95.0
        assert candle.close == 105.0
        assert candle.tick_count == 4

    def test_period_close_emits_completed_candle(self) -> None:
        agg = OHLCVAggregator(timeframes=[60])
        period_start = 1000 * 60  # aligned to 60s boundary

        # Tick in period 1
        agg.process_tick("kraken", "BTC/USD", price=100.0, timestamp=period_start + 5)

        # Tick in period 2 — should close period 1
        completed = agg.process_tick(
            "kraken", "BTC/USD", price=105.0, timestamp=period_start + 65
        )
        assert len(completed) == 1
        assert completed[0]["open"] == 100.0
        assert completed[0]["close"] == 100.0
        assert completed[0]["exchange"] == "kraken"
        assert completed[0]["pair"] == "BTC/USD"
        assert completed[0]["timeframe_s"] == 60

    def test_is_feed_stale_false_after_tick(self) -> None:
        agg = OHLCVAggregator(timeframes=[60], staleness_multiplier=2.5)
        agg.process_tick("kraken", "BTC/USD", price=68000.0)
        assert not agg.is_feed_stale("kraken", "BTC/USD", timeframe_s=60)

    def test_is_feed_stale_true_after_timeout(self) -> None:
        agg = OHLCVAggregator(timeframes=[60], staleness_multiplier=2.5)
        # Set last tick to 3x the timeframe ago (> 2.5x threshold)
        agg._last_tick_time["kraken:BTC/USD"] = time.time() - (60 * 3)
        assert agg.is_feed_stale("kraken", "BTC/USD", timeframe_s=60)

    def test_is_feed_stale_unknown_feed(self) -> None:
        agg = OHLCVAggregator(timeframes=[60])
        # No tick ever received — last_tick defaults to 0
        assert agg.is_feed_stale("unknown", "BTC/USD", timeframe_s=60)

    def test_get_stale_feeds(self) -> None:
        agg = OHLCVAggregator(timeframes=[60], staleness_multiplier=2.5)

        # Fresh feed
        agg.process_tick("kraken", "BTC/USD", price=68000.0)
        # Stale feed
        agg._last_tick_time["binance:ETH/USD"] = time.time() - 200

        stale = agg.get_stale_feeds(timeframe_s=60)
        assert "binance:ETH/USD" in stale
        assert "kraken:BTC/USD" not in stale

    def test_get_feed_health_summary(self) -> None:
        agg = OHLCVAggregator(timeframes=[60], staleness_multiplier=2.5)
        agg.process_tick("kraken", "BTC/USD", price=68000.0)

        summary = agg.get_feed_health_summary(timeframe_s=60)
        assert "kraken:BTC/USD" in summary
        assert summary["kraken:BTC/USD"]["is_stale"] is False
        assert summary["kraken:BTC/USD"]["last_tick_age_s"] < 5.0

    def test_staleness_disabled(self) -> None:
        agg = OHLCVAggregator(timeframes=[60])
        agg._enabled = False
        # Even with no ticks, disabled means not stale
        assert not agg.is_feed_stale("kraken", "BTC/USD", timeframe_s=60)

    def test_get_metrics(self) -> None:
        agg = OHLCVAggregator(timeframes=[60])
        agg.process_tick("kraken", "BTC/USD", price=100.0)

        metrics = agg.get_metrics()
        assert metrics["ticks_processed"] == 1
        assert metrics["tracked_feeds"] == 1
        assert metrics["enabled"] is True

    def test_multiple_timeframes(self) -> None:
        agg = OHLCVAggregator(timeframes=[15, 60, 300])
        agg.process_tick("kraken", "BTC/USD", price=100.0)

        # Should create candles for all 3 timeframes
        assert "kraken:BTC/USD:15" in agg._active_candles
        assert "kraken:BTC/USD:60" in agg._active_candles
        assert "kraken:BTC/USD:300" in agg._active_candles
