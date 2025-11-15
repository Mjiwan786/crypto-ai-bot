"""
Tests for Synthetic OHLCV Bar Builder

Tests bucket boundary alignment, trade aggregation, quality filtering,
and latency requirements for sub-minute bars (5s, 15s, 30s).

Author: Crypto AI Bot Team
Date: 2025-11-08
"""

import asyncio
import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from utils.synthetic_bars import (
    OHLCV,
    SyntheticBarBuilder,
    Trade,
    create_bar_builder,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def mock_redis():
    """Mock Redis client for testing."""
    redis = AsyncMock()
    redis.xadd = AsyncMock()
    return redis


@pytest.fixture
def builder_15s():
    """15-second bar builder without Redis."""
    return SyntheticBarBuilder(
        timeframe_seconds=15,
        min_trades_per_bucket=1,
        symbol="BTC/USD",
    )


@pytest.fixture
def builder_5s():
    """5-second bar builder with strict quality requirements."""
    return SyntheticBarBuilder(
        timeframe_seconds=5,
        min_trades_per_bucket=3,  # Require at least 3 trades per 5s bucket
        symbol="BTC/USD",
        latency_budget_ms=50.0,
    )


# =============================================================================
# TEST: BUCKET BOUNDARY ALIGNMENT
# =============================================================================


def test_bucket_alignment_15s(builder_15s):
    """Test 15s bucket boundaries align to :00, :15, :30, :45 seconds."""
    # Test timestamp: 2025-01-01 12:00:17.500 (should align to 12:00:15)
    ts = 1735732817.500
    bucket_ts = builder_15s.get_bucket_timestamp(ts)

    # Should align to nearest 15s boundary below
    assert bucket_ts == 1735732815.0  # 12:00:15

    # Test edge cases
    assert builder_15s.get_bucket_timestamp(1735732800.0) == 1735732800.0  # Exactly :00
    assert builder_15s.get_bucket_timestamp(1735732814.999) == 1735732800.0  # Just before :15
    assert builder_15s.get_bucket_timestamp(1735732815.0) == 1735732815.0  # Exactly :15
    assert builder_15s.get_bucket_timestamp(1735732829.999) == 1735732815.0  # Just before :30


def test_bucket_alignment_5s(builder_5s):
    """Test 5s bucket boundaries align to :00, :05, :10, etc."""
    ts = 1735732817.500  # Should align to 12:00:15
    bucket_ts = builder_5s.get_bucket_timestamp(ts)
    assert bucket_ts == 1735732815.0

    # Test 5s boundaries
    assert builder_5s.get_bucket_timestamp(1735732800.0) == 1735732800.0  # :00
    assert builder_5s.get_bucket_timestamp(1735732804.999) == 1735732800.0  # :00-:05
    assert builder_5s.get_bucket_timestamp(1735732805.0) == 1735732805.0  # :05
    assert builder_5s.get_bucket_timestamp(1735732809.999) == 1735732805.0  # :05-:10
    assert builder_5s.get_bucket_timestamp(1735732810.0) == 1735732810.0  # :10


# =============================================================================
# TEST: OHLCV CALCULATION
# =============================================================================


@pytest.mark.asyncio
async def test_ohlcv_calculation_single_trade(builder_15s):
    """Test OHLCV bar creation from a single trade."""
    base_ts = time.time()
    base_ts = (base_ts // 15) * 15  # Align to 15s boundary

    trade = Trade(
        timestamp=base_ts + 1.0,
        price=Decimal("50000.00"),
        volume=Decimal("0.5"),
        side="buy",
    )

    # Add trade (won't complete bucket yet)
    bar = await builder_15s.add_trade(trade)
    assert bar is None  # Bucket not complete yet

    # Force close bucket
    bars = await builder_15s.force_close_all_buckets()
    assert len(bars) == 1

    bar = bars[0]
    assert bar.open == Decimal("50000.00")
    assert bar.high == Decimal("50000.00")
    assert bar.low == Decimal("50000.00")
    assert bar.close == Decimal("50000.00")
    assert bar.volume == Decimal("0.5")
    assert bar.trade_count == 1
    assert bar.vwap == Decimal("50000.00")


@pytest.mark.asyncio
async def test_ohlcv_calculation_multiple_trades(builder_15s):
    """Test OHLCV bar creation from multiple trades."""
    base_ts = time.time()
    base_ts = (base_ts // 15) * 15  # Align to 15s boundary

    trades = [
        Trade(base_ts + 0.1, Decimal("50000.00"), Decimal("0.1"), "buy"),
        Trade(base_ts + 2.0, Decimal("50100.00"), Decimal("0.2"), "buy"),  # High
        Trade(base_ts + 5.0, Decimal("49900.00"), Decimal("0.15"), "sell"),  # Low
        Trade(base_ts + 10.0, Decimal("50050.00"), Decimal("0.3"), "sell"),
    ]

    for trade in trades:
        await builder_15s.add_trade(trade)

    # Force close bucket
    bars = await builder_15s.force_close_all_buckets()
    assert len(bars) == 1

    bar = bars[0]
    assert bar.open == Decimal("50000.00")
    assert bar.high == Decimal("50100.00")
    assert bar.low == Decimal("49900.00")
    assert bar.close == Decimal("50050.00")
    assert bar.volume == Decimal("0.75")  # 0.1 + 0.2 + 0.15 + 0.3
    assert bar.trade_count == 4
    assert bar.buy_volume == Decimal("0.3")  # 0.1 + 0.2
    assert bar.sell_volume == Decimal("0.45")  # 0.15 + 0.3

    # VWAP should be volume-weighted average
    # (50000*0.1 + 50100*0.2 + 49900*0.15 + 50050*0.3) / 0.75
    expected_vwap = (
        Decimal("50000") * Decimal("0.1")
        + Decimal("50100") * Decimal("0.2")
        + Decimal("49900") * Decimal("0.15")
        + Decimal("50050") * Decimal("0.3")
    ) / Decimal("0.75")
    assert abs(bar.vwap - expected_vwap) < Decimal("0.01")


# =============================================================================
# TEST: QUALITY FILTERING
# =============================================================================


@pytest.mark.asyncio
async def test_quality_filter_min_trades(builder_5s):
    """Test that buckets with < min_trades are rejected."""
    base_ts = time.time()
    base_ts = (base_ts // 5) * 5  # Align to 5s boundary

    # Add only 2 trades (< min_trades_per_bucket=3)
    trades = [
        Trade(base_ts + 0.5, Decimal("50000.00"), Decimal("0.1"), "buy"),
        Trade(base_ts + 2.0, Decimal("50100.00"), Decimal("0.2"), "buy"),
    ]

    for trade in trades:
        await builder_5s.add_trade(trade)

    # Force close bucket
    bars = await builder_5s.force_close_all_buckets()

    # Should not create bar (< 3 trades)
    assert len(bars) == 0
    assert builder_5s.bars_created == 0


@pytest.mark.asyncio
async def test_quality_filter_passes(builder_5s):
    """Test that buckets with >= min_trades are accepted."""
    base_ts = time.time()
    base_ts = (base_ts // 5) * 5

    # Add exactly 3 trades (= min_trades_per_bucket)
    trades = [
        Trade(base_ts + 0.5, Decimal("50000.00"), Decimal("0.1"), "buy"),
        Trade(base_ts + 2.0, Decimal("50100.00"), Decimal("0.2"), "buy"),
        Trade(base_ts + 3.5, Decimal("50050.00"), Decimal("0.15"), "sell"),
    ]

    for trade in trades:
        await builder_5s.add_trade(trade)

    # Force close bucket
    bars = await builder_5s.force_close_all_buckets()

    # Should create bar (>= 3 trades)
    assert len(bars) == 1
    assert builder_5s.bars_created == 1
    assert bars[0].trade_count == 3


# =============================================================================
# TEST: BUCKET AUTO-CLOSE ON TIME BOUNDARY
# =============================================================================


@pytest.mark.asyncio
async def test_bucket_auto_close_on_boundary():
    """Test that buckets auto-close when a new trade crosses the boundary."""
    builder = SyntheticBarBuilder(timeframe_seconds=5, min_trades_per_bucket=1)

    # Get current bucket
    now = time.time()
    bucket_1_start = (now // 5) * 5

    # Add trade to first bucket
    trade1 = Trade(
        timestamp=bucket_1_start + 1.0,
        price=Decimal("50000.00"),
        volume=Decimal("0.1"),
        side="buy",
    )
    bar = await builder.add_trade(trade1)
    assert bar is None  # Bucket 1 not closed yet

    # Wait for bucket boundary to pass
    await asyncio.sleep(6)  # Ensure we're in next bucket

    # Add trade to second bucket (should trigger close of bucket 1)
    trade2 = Trade(
        timestamp=time.time(),
        price=Decimal("50100.00"),
        volume=Decimal("0.2"),
        side="buy",
    )
    bar = await builder.add_trade(trade2)

    # Bucket 1 should now be closed
    assert builder.bars_created >= 1


# =============================================================================
# TEST: REDIS PUBLISHING
# =============================================================================


@pytest.mark.asyncio
async def test_redis_publishing(mock_redis):
    """Test that bars are published to Redis stream."""
    builder = SyntheticBarBuilder(
        timeframe_seconds=15,
        min_trades_per_bucket=1,
        redis_client=mock_redis,
        redis_stream_key="kraken:ohlc:15s",
        symbol="BTC/USD",
    )

    base_ts = time.time()
    base_ts = (base_ts // 15) * 15

    trade = Trade(
        timestamp=base_ts + 1.0,
        price=Decimal("50000.00"),
        volume=Decimal("0.5"),
        side="buy",
    )

    await builder.add_trade(trade)
    await builder.force_close_all_buckets()

    # Check Redis was called
    assert mock_redis.xadd.called
    call_args = mock_redis.xadd.call_args

    # Verify stream key format
    assert call_args[0][0] == "kraken:ohlc:15s:BTC-USD"

    # Verify data structure
    data = call_args[0][1]
    assert "open" in data
    assert "high" in data
    assert "low" in data
    assert "close" in data
    assert "volume" in data
    assert "symbol" in data
    assert data["symbol"] == "BTC/USD"
    assert data["timeframe"] == "15s"


# =============================================================================
# TEST: LATENCY TRACKING
# =============================================================================


@pytest.mark.asyncio
async def test_latency_tracking():
    """Test that latency is tracked and budget violations are detected."""
    builder = SyntheticBarBuilder(
        timeframe_seconds=15,
        min_trades_per_bucket=1,
        latency_budget_ms=100.0,
    )

    base_ts = time.time()
    base_ts = (base_ts // 15) * 15

    # Add a trade
    trade = Trade(
        timestamp=base_ts + 1.0,
        price=Decimal("50000.00"),
        volume=Decimal("0.5"),
        side="buy",
    )

    await builder.add_trade(trade)

    # Check metrics
    metrics = builder.get_metrics()
    assert metrics["trades_processed"] == 1
    assert "avg_latency_ms" in metrics
    assert metrics["avg_latency_ms"] < builder.latency_budget_ms  # Should be fast


# =============================================================================
# TEST: FACTORY FUNCTION
# =============================================================================


def test_factory_function_15s():
    """Test create_bar_builder factory for 15s."""
    builder = create_bar_builder("15s", "BTC/USD")

    assert builder.timeframe_seconds == 15
    assert builder.min_trades_per_bucket == 1  # Default for 15s
    assert builder.latency_budget_ms == 100.0
    assert builder.symbol == "BTC/USD"


def test_factory_function_5s():
    """Test create_bar_builder factory for 5s."""
    builder = create_bar_builder("5s", "ETH/USD")

    assert builder.timeframe_seconds == 5
    assert builder.min_trades_per_bucket == 3  # Stricter for 5s
    assert builder.latency_budget_ms == 50.0  # Ultra-strict for 5s
    assert builder.symbol == "ETH/USD"


def test_factory_function_invalid_timeframe():
    """Test factory raises error for invalid timeframe."""
    with pytest.raises(ValueError, match="Only second-based timeframes supported"):
        create_bar_builder("1m", "BTC/USD")


# =============================================================================
# TEST: METRICS
# =============================================================================


@pytest.mark.asyncio
async def test_metrics_tracking():
    """Test that all metrics are tracked correctly."""
    builder = SyntheticBarBuilder(timeframe_seconds=5, min_trades_per_bucket=1)

    base_ts = time.time()
    base_ts = (base_ts // 5) * 5

    # Add 3 trades
    for i in range(3):
        trade = Trade(
            timestamp=base_ts + i,
            price=Decimal("50000.00"),
            volume=Decimal("0.1"),
            side="buy",
        )
        await builder.add_trade(trade)

    # Force close
    await builder.force_close_all_buckets()

    metrics = builder.get_metrics()

    assert metrics["trades_processed"] == 3
    assert metrics["bars_created"] == 1
    assert metrics["pending_buckets"] == 0
    assert "avg_latency_ms" in metrics


# =============================================================================
# TEST: CONCURRENT BUCKETS
# =============================================================================


@pytest.mark.asyncio
async def test_concurrent_buckets():
    """Test handling of trades spanning multiple buckets."""
    builder = SyntheticBarBuilder(timeframe_seconds=5, min_trades_per_bucket=1)

    base_ts = time.time()
    base_ts = (base_ts // 5) * 5

    # Add trades to bucket 1
    await builder.add_trade(
        Trade(base_ts + 1.0, Decimal("50000.00"), Decimal("0.1"), "buy")
    )
    await builder.add_trade(
        Trade(base_ts + 2.0, Decimal("50100.00"), Decimal("0.2"), "buy")
    )

    # Add trades to bucket 2
    await builder.add_trade(
        Trade(base_ts + 6.0, Decimal("50200.00"), Decimal("0.15"), "sell")
    )
    await builder.add_trade(
        Trade(base_ts + 7.0, Decimal("50250.00"), Decimal("0.3"), "sell")
    )

    # Should have 2 pending buckets
    assert len(builder.buckets) == 2

    # Force close all
    bars = await builder.force_close_all_buckets()
    assert len(bars) == 2

    # Verify each bar has correct trades
    assert bars[0].trade_count == 2
    assert bars[1].trade_count == 2


# =============================================================================
# BENCHMARK TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_latency_benchmark_15s():
    """Benchmark: 15s bar processing should be < 100ms."""
    builder = SyntheticBarBuilder(timeframe_seconds=15, latency_budget_ms=100.0)

    base_ts = time.time()
    base_ts = (base_ts // 15) * 15

    # Process 100 trades
    iterations = 100
    start = time.perf_counter()

    for i in range(iterations):
        trade = Trade(
            timestamp=base_ts + (i * 0.1),
            price=Decimal("50000.00"),
            volume=Decimal("0.1"),
            side="buy",
        )
        await builder.add_trade(trade)

    end = time.perf_counter()
    avg_time_ms = ((end - start) / iterations) * 1000

    # Should be very fast (< 1ms per trade)
    assert avg_time_ms < 1.0, f"Trade processing too slow: {avg_time_ms:.3f}ms"


@pytest.mark.asyncio
async def test_latency_benchmark_5s():
    """Benchmark: 5s bar processing should be < 50ms."""
    builder = SyntheticBarBuilder(timeframe_seconds=5, latency_budget_ms=50.0)

    base_ts = time.time()
    base_ts = (base_ts // 5) * 5

    # Process 100 trades
    iterations = 100
    start = time.perf_counter()

    for i in range(iterations):
        trade = Trade(
            timestamp=base_ts + (i * 0.05),
            price=Decimal("50000.00"),
            volume=Decimal("0.1"),
            side="buy",
        )
        await builder.add_trade(trade)

    end = time.perf_counter()
    avg_time_ms = ((end - start) / iterations) * 1000

    # Should be very fast (< 0.5ms per trade for 5s bars)
    assert avg_time_ms < 0.5, f"5s bar processing too slow: {avg_time_ms:.3f}ms"
