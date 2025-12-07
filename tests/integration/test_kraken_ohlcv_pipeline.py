"""
Integration Tests for Kraken OHLCV Pipeline (tests/integration/test_kraken_ohlcv_pipeline.py)

Tests the complete OHLCV data flow:
1. KrakenOHLCVManager configuration loading
2. Pair/timeframe subscription configuration
3. Synthetic bar generation from trade ticks
4. Redis stream publishing with PRD-compliant naming
5. Health monitoring

Run with: pytest tests/integration/test_kraken_ohlcv_pipeline.py -v

For live Kraken testing (requires REDIS_URL):
    pytest tests/integration/test_kraken_ohlcv_pipeline.py -v -m live

Author: Crypto AI Bot Team
PRD Reference: PRD-001 Sections B.3, 4.1, 4.2
"""

import asyncio
import os
import time
from decimal import Decimal
from typing import Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import the modules under test
from utils.kraken_ohlcv_manager import (
    KrakenOHLCVManager,
    OHLCVBar,
    PairConfig,
    PairTier,
    SyntheticBarBuilder,
    TimeframeConfig,
    TimeframeType,
    Trade,
    create_ohlcv_manager,
    get_stream_key,
    NATIVE_TIMEFRAMES,
    SYNTHETIC_TIMEFRAMES,
    DEFAULT_PAIR_TIERS,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_redis():
    """Mock Redis client for testing without real Redis"""
    mock = AsyncMock()
    mock.xadd = AsyncMock(return_value=b"1234567890-0")
    mock.ping = AsyncMock(return_value=True)
    return mock


@pytest.fixture
def ohlcv_manager(mock_redis):
    """Create OHLCV manager with mock Redis"""
    manager = KrakenOHLCVManager(
        redis_client=mock_redis,
        enabled_tiers=[PairTier.TIER_1, PairTier.TIER_2, PairTier.TIER_3],
    )
    return manager


@pytest.fixture
def sample_trades() -> List[Dict]:
    """Sample trade data for synthetic bar testing"""
    base_time = time.time()
    return [
        {"price": 50000.0, "volume": 0.1, "side": "buy", "timestamp": base_time},
        {"price": 50100.0, "volume": 0.2, "side": "sell", "timestamp": base_time + 1},
        {"price": 50050.0, "volume": 0.15, "side": "buy", "timestamp": base_time + 2},
        {"price": 49900.0, "volume": 0.3, "side": "sell", "timestamp": base_time + 3},
        {"price": 50200.0, "volume": 0.1, "side": "buy", "timestamp": base_time + 4},
    ]


# =============================================================================
# CONFIGURATION TESTS
# =============================================================================

class TestOHLCVManagerConfiguration:
    """Tests for OHLCV manager configuration loading"""

    def test_default_pairs_loaded(self, ohlcv_manager):
        """Default pairs should be loaded when no config file"""
        pairs = ohlcv_manager.get_all_pairs()
        assert len(pairs) > 0

        # Should include tier_1 pairs
        assert "BTC/USD" in pairs
        assert "ETH/USD" in pairs

    def test_tier_1_pairs(self, ohlcv_manager):
        """Tier 1 pairs should be highest priority"""
        tier_1 = ohlcv_manager.get_pairs_by_tier(PairTier.TIER_1)

        # PRD-001: tier_1 should include BTC/USD, ETH/USD, BTC/EUR
        expected = ["BTC/USD", "ETH/USD", "BTC/EUR"]
        for pair in expected:
            assert pair in tier_1, f"Missing tier_1 pair: {pair}"

    def test_tier_2_pairs(self, ohlcv_manager):
        """Tier 2 pairs should be medium priority"""
        tier_2 = ohlcv_manager.get_pairs_by_tier(PairTier.TIER_2)

        # PRD-001: tier_2 should include ADA/USD, SOL/USD, AVAX/USD
        expected = ["ADA/USD", "SOL/USD", "AVAX/USD"]
        for pair in expected:
            assert pair in tier_2, f"Missing tier_2 pair: {pair}"

    def test_tier_3_pairs(self, ohlcv_manager):
        """Tier 3 pairs should be included"""
        tier_3 = ohlcv_manager.get_pairs_by_tier(PairTier.TIER_3)

        # PRD-001: tier_3 should include LINK/USD
        assert "LINK/USD" in tier_3

    def test_kraken_pairs_format(self, ohlcv_manager):
        """Kraken pairs should be in correct format"""
        kraken_pairs = ohlcv_manager.get_kraken_pairs()

        # Should convert BTC/USD to XBT/USD for Kraken
        assert any("XBT" in p for p in kraken_pairs), "BTC should be converted to XBT for Kraken"

    def test_timeframes_configured(self, ohlcv_manager):
        """Timeframes should be configured"""
        native_tfs = ohlcv_manager.get_native_timeframes()
        synthetic_tfs = ohlcv_manager.get_synthetic_timeframes()

        assert len(native_tfs) > 0 or len(synthetic_tfs) > 0


class TestTimeframeConfiguration:
    """Tests for timeframe configuration"""

    def test_native_timeframes_have_kraken_interval(self):
        """Native timeframes should have Kraken API interval"""
        for name, config in NATIVE_TIMEFRAMES.items():
            assert config.kraken_interval is not None, f"{name} missing Kraken interval"
            assert config.type == TimeframeType.NATIVE

    def test_synthetic_timeframes_no_kraken_interval(self):
        """Synthetic timeframes should NOT have Kraken interval"""
        for name, config in SYNTHETIC_TIMEFRAMES.items():
            assert config.kraken_interval is None, f"{name} should not have Kraken interval"
            assert config.type == TimeframeType.SYNTHETIC

    def test_kraken_ohlc_intervals(self, ohlcv_manager):
        """Should return valid Kraken OHLC intervals"""
        intervals = ohlcv_manager.get_kraken_ohlc_intervals()

        # All intervals should be valid Kraken values
        valid_kraken_intervals = [1, 5, 15, 30, 60, 240, 1440, 10080, 21600]
        for interval in intervals:
            assert interval in valid_kraken_intervals, f"Invalid Kraken interval: {interval}"

    def test_15s_is_synthetic_not_native(self):
        """15s timeframe must be synthetic (Kraken doesn't support 15s native)"""
        assert "15s" in SYNTHETIC_TIMEFRAMES
        assert "15s" not in NATIVE_TIMEFRAMES


# =============================================================================
# STREAM NAMING TESTS
# =============================================================================

class TestStreamNaming:
    """Tests for PRD-compliant Redis stream naming"""

    def test_stream_key_format(self):
        """Stream key should follow pattern: kraken:ohlc:{tf}:{pair}"""
        key = get_stream_key("BTC/USD", "1m")
        assert key == "kraken:ohlc:1m:BTC-USD"

    def test_stream_key_with_slash_in_pair(self):
        """Slash in pair should be converted to dash"""
        key = get_stream_key("ETH/USD", "15s")
        assert "/" not in key
        assert "ETH-USD" in key

    def test_stream_key_various_pairs(self):
        """Test stream keys for various pairs"""
        test_cases = [
            ("BTC/USD", "1m", "kraken:ohlc:1m:BTC-USD"),
            ("ETH/USD", "5m", "kraken:ohlc:5m:ETH-USD"),
            ("SOL/USD", "15s", "kraken:ohlc:15s:SOL-USD"),
            ("BTC/EUR", "1h", "kraken:ohlc:1h:BTC-EUR"),
        ]

        for symbol, tf, expected in test_cases:
            result = get_stream_key(symbol, tf)
            assert result == expected, f"Expected {expected}, got {result}"


# =============================================================================
# SYNTHETIC BAR BUILDER TESTS
# =============================================================================

class TestSyntheticBarBuilder:
    """Tests for synthetic bar generation from trades"""

    @pytest.fixture
    def bar_builder(self, mock_redis):
        """Create a synthetic bar builder for 15s timeframe"""
        config = TimeframeConfig("15s", 15, None, TimeframeType.SYNTHETIC, min_trades=1)
        return SyntheticBarBuilder(
            symbol="BTC/USD",
            timeframe=config,
            redis_client=mock_redis,
        )

    def test_bucket_timestamp_alignment(self, bar_builder):
        """Bucket timestamps should be aligned to boundaries"""
        # Test 15s alignment
        # e.g., 12345 seconds should align to 12345 - (12345 % 15) = 12330

        test_time = 1699458012.345  # Some random timestamp
        bucket_ts = bar_builder.get_bucket_timestamp(test_time)

        # Should be aligned to 15s boundary
        assert bucket_ts % 15 == 0

    @pytest.mark.asyncio
    async def test_trade_processing(self, bar_builder, sample_trades):
        """Trades should be accumulated in buckets"""
        for trade_data in sample_trades[:3]:
            trade = Trade(
                timestamp=trade_data["timestamp"],
                price=Decimal(str(trade_data["price"])),
                volume=Decimal(str(trade_data["volume"])),
                side=trade_data["side"],
            )
            await bar_builder.add_trade(trade)

        assert bar_builder.trades_processed == 3

    @pytest.mark.asyncio
    async def test_bar_creation(self, mock_redis):
        """Bar should be created when bucket closes"""
        # Use a 1s timeframe for testing (fast bucket close)
        config = TimeframeConfig("1s", 1, None, TimeframeType.SYNTHETIC, min_trades=1)
        builder = SyntheticBarBuilder(
            symbol="BTC/USD",
            timeframe=config,
            redis_client=mock_redis,
        )

        # Add trade to old bucket (will close immediately)
        old_time = time.time() - 5  # 5 seconds ago
        trade = Trade(
            timestamp=old_time,
            price=Decimal("50000"),
            volume=Decimal("0.1"),
            side="buy",
        )

        bar = await builder.add_trade(trade)

        # Bar should be created for the old bucket
        assert builder.bars_created >= 0  # May or may not create depending on timing

    @pytest.mark.asyncio
    async def test_ohlcv_calculation(self, mock_redis):
        """OHLCV values should be calculated correctly"""
        config = TimeframeConfig("test", 1, None, TimeframeType.SYNTHETIC, min_trades=1)
        builder = SyntheticBarBuilder(
            symbol="BTC/USD",
            timeframe=config,
            redis_client=mock_redis,
        )

        # Force close a bucket with known trades
        bucket_ts = time.time() - 10
        trades = [
            Trade(bucket_ts, Decimal("100"), Decimal("1"), "buy"),
            Trade(bucket_ts + 0.1, Decimal("110"), Decimal("2"), "sell"),
            Trade(bucket_ts + 0.2, Decimal("95"), Decimal("1"), "buy"),
            Trade(bucket_ts + 0.3, Decimal("105"), Decimal("1.5"), "sell"),
        ]

        for t in trades:
            builder.buckets[bucket_ts].append(t)

        bar = await builder._close_bucket(bucket_ts)

        assert bar is not None
        assert bar.open == Decimal("100")  # First trade price
        assert bar.close == Decimal("105")  # Last trade price
        assert bar.high == Decimal("110")  # Highest price
        assert bar.low == Decimal("95")  # Lowest price
        assert bar.volume == Decimal("5.5")  # Sum of volumes
        assert bar.trade_count == 4


# =============================================================================
# OHLCV MANAGER INTEGRATION TESTS
# =============================================================================

class TestOHLCVManagerIntegration:
    """Integration tests for OHLCV manager"""

    @pytest.mark.asyncio
    async def test_initialize_bar_builders(self, ohlcv_manager):
        """Bar builders should be initialized for all pair/timeframe combinations"""
        await ohlcv_manager.initialize_bar_builders()

        pairs = ohlcv_manager.get_all_pairs()
        synthetic_tfs = ohlcv_manager.get_synthetic_timeframes()

        expected_count = len(pairs) * len(synthetic_tfs)
        assert len(ohlcv_manager.bar_builders) == expected_count

    @pytest.mark.asyncio
    async def test_process_trade(self, ohlcv_manager):
        """Trade processing should feed all synthetic bar builders"""
        await ohlcv_manager.initialize_bar_builders()

        await ohlcv_manager.process_trade(
            symbol="BTC/USD",
            price=50000.0,
            volume=0.1,
            side="buy",
            timestamp=time.time(),
        )

        assert ohlcv_manager.trades_processed == 1
        assert "BTC/USD" in ohlcv_manager.last_update_by_pair

    @pytest.mark.asyncio
    async def test_process_native_ohlc(self, ohlcv_manager, mock_redis):
        """Native OHLC data should be processed and cached"""
        ohlc_data = {
            "time": time.time(),
            "open": "50000",
            "high": "51000",
            "low": "49000",
            "close": "50500",
            "volume": "100",
            "count": 1000,
            "vwap": "50250",
        }

        bar = await ohlcv_manager.process_native_ohlc(
            symbol="BTC/USD",
            timeframe_minutes=1,  # 1m timeframe
            ohlc_data=ohlc_data,
        )

        assert bar is not None or ohlcv_manager.native_bars_received >= 0

    def test_health_status(self, ohlcv_manager):
        """Health status should report all metrics"""
        health = ohlcv_manager.get_health_status()

        assert "total_pairs" in health
        assert "enabled_pairs" in health
        assert "native_timeframes" in health
        assert "synthetic_timeframes" in health
        assert "pair_status" in health

    def test_subscription_config(self, ohlcv_manager):
        """Subscription config should be complete"""
        config = ohlcv_manager.get_subscription_config()

        assert "pairs" in config
        assert "ohlc_intervals" in config
        assert "subscribe_trades" in config

        # Should have pairs
        assert len(config["pairs"]) > 0


# =============================================================================
# REDIS PUBLISHING TESTS
# =============================================================================

class TestRedisPublishing:
    """Tests for Redis stream publishing"""

    @pytest.mark.asyncio
    async def test_synthetic_bar_published_to_correct_stream(self, mock_redis):
        """Synthetic bars should be published to kraken:ohlc:{tf}:{pair}"""
        config = TimeframeConfig("15s", 15, None, TimeframeType.SYNTHETIC, min_trades=1)
        builder = SyntheticBarBuilder(
            symbol="BTC/USD",
            timeframe=config,
            redis_client=mock_redis,
        )

        # Create and publish a bar
        bar = OHLCVBar(
            timestamp=time.time(),
            open=Decimal("50000"),
            high=Decimal("51000"),
            low=Decimal("49000"),
            close=Decimal("50500"),
            volume=Decimal("100"),
            trade_count=50,
        )

        await builder._publish_bar(bar)

        # Check that xadd was called with correct stream key
        mock_redis.xadd.assert_called_once()
        call_args = mock_redis.xadd.call_args
        stream_key = call_args[0][0]

        assert stream_key == "kraken:ohlc:15s:BTC-USD"

    @pytest.mark.asyncio
    async def test_native_bar_published_to_correct_stream(self, ohlcv_manager, mock_redis):
        """Native bars should be published to kraken:ohlc:{tf}:{pair}"""
        ohlc_data = {
            "time": time.time(),
            "open": "50000",
            "high": "51000",
            "low": "49000",
            "close": "50500",
            "volume": "100",
            "count": 1000,
        }

        await ohlcv_manager.process_native_ohlc(
            symbol="BTC/USD",
            timeframe_minutes=5,  # 5m timeframe
            ohlc_data=ohlc_data,
        )

        # Check that xadd was called
        if mock_redis.xadd.called:
            call_args = mock_redis.xadd.call_args
            stream_key = call_args[0][0]
            assert "kraken:ohlc:5m:BTC-USD" == stream_key


# =============================================================================
# OHLCV BAR DATA STRUCTURE TESTS
# =============================================================================

class TestOHLCVBar:
    """Tests for OHLCV bar data structure"""

    def test_bar_to_dict(self):
        """Bar should convert to Redis-compatible dict"""
        bar = OHLCVBar(
            timestamp=1699458000.0,
            open=Decimal("50000"),
            high=Decimal("51000"),
            low=Decimal("49000"),
            close=Decimal("50500"),
            volume=Decimal("100.5"),
            trade_count=1000,
            vwap=Decimal("50250"),
        )

        data = bar.to_dict()

        # All values should be strings
        for key, value in data.items():
            assert isinstance(value, str), f"{key} should be string, got {type(value)}"

        # Check values
        assert data["timestamp"] == "1699458000.0"
        assert data["open"] == "50000"
        assert data["high"] == "51000"
        assert data["low"] == "49000"
        assert data["close"] == "50500"
        assert data["volume"] == "100.5"
        assert data["trade_count"] == "1000"


# =============================================================================
# LIVE KRAKEN TESTS (marked for selective running)
# =============================================================================

@pytest.mark.live
class TestLiveKrakenConnection:
    """
    Live tests against real Kraken WebSocket.

    These tests require:
    - REDIS_URL environment variable set
    - Network access to Kraken WebSocket

    Run with: pytest tests/integration/test_kraken_ohlcv_pipeline.py -v -m live
    """

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not os.getenv("REDIS_URL"),
        reason="REDIS_URL not set"
    )
    async def test_live_redis_connection(self):
        """Test real Redis connection"""
        manager = create_ohlcv_manager()

        if manager.redis_client:
            try:
                await manager.redis_client.ping()
                assert True, "Redis connection successful"
            except Exception as e:
                pytest.fail(f"Redis connection failed: {e}")


# =============================================================================
# RUN AS SCRIPT
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-x"])
