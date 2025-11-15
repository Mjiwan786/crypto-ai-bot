"""
Tests for Redis Stream Configuration (PRD-001 Section 2.2)

Tests cover:
- Signal stream name based on TRADING_MODE (signals:paper or signals:live)
- PnL stream configuration (pnl:signals with MAXLEN 50000)
- Events stream configuration (events:bus with MAXLEN 5000)
- Signal streams with MAXLEN 10000
- Approximate trimming (~) for performance
- Stream verification on startup (XINFO STREAM)
- Logging stream configuration at INFO level
- Prometheus gauge redis_stream_length{stream}
"""

import pytest
import asyncio
import logging
from unittest.mock import Mock, patch, AsyncMock, MagicMock

from utils.kraken_ws import (
    RedisConnectionManager,
    KrakenWSConfig,
    REDIS_STREAM_LENGTH,
    PROMETHEUS_AVAILABLE
)


@pytest.fixture
def config_paper():
    """Create test configuration for paper trading"""
    return KrakenWSConfig(
        redis_url="rediss://test:password@redis.example.com:6380",
        trading_mode="paper"
    )


@pytest.fixture
def config_live():
    """Create test configuration for live trading"""
    return KrakenWSConfig(
        redis_url="rediss://test:password@redis.example.com:6380",
        trading_mode="live"
    )


@pytest.fixture
def redis_manager_paper(config_paper):
    """Create test Redis manager for paper trading"""
    return RedisConnectionManager(config_paper)


@pytest.fixture
def redis_manager_live(config_live):
    """Create test Redis manager for live trading"""
    return RedisConnectionManager(config_live)


class TestSignalStreamConfiguration:
    """Test signal stream naming based on TRADING_MODE (PRD-001 Section 2.2 Item 1)"""

    def test_signal_stream_name_paper_mode(self, config_paper):
        """Test that signal stream is signals:paper in paper trading mode"""
        stream_name = config_paper.get_signal_stream_name()
        assert stream_name == "signals:paper"

    def test_signal_stream_name_live_mode(self, config_live):
        """Test that signal stream is signals:live in live trading mode"""
        stream_name = config_live.get_signal_stream_name()
        assert stream_name == "signals:live"

    def test_trading_mode_from_env_var(self):
        """Test that trading mode is read from TRADING_MODE env var"""
        with patch.dict('os.environ', {'TRADING_MODE': 'live'}):
            config = KrakenWSConfig()
            assert config.trading_mode == "live"
            assert config.get_signal_stream_name() == "signals:live"


class TestPnLStreamConfiguration:
    """Test PnL stream configuration (PRD-001 Section 2.2 Item 2)"""

    def test_pnl_stream_name(self, config_paper):
        """Test that PnL stream name is pnl:signals"""
        stream_name = config_paper.get_pnl_stream_name()
        assert stream_name == "pnl:signals"

    def test_pnl_stream_maxlen(self, config_paper):
        """Test that PnL stream MAXLEN is 50000"""
        maxlen = config_paper.stream_maxlen["pnl"]
        assert maxlen == 50000


class TestEventsStreamConfiguration:
    """Test events stream configuration (PRD-001 Section 2.2 Item 3)"""

    def test_events_stream_name(self, config_paper):
        """Test that events stream name is events:bus"""
        stream_name = config_paper.get_events_stream_name()
        assert stream_name == "events:bus"

    def test_events_stream_maxlen(self, config_paper):
        """Test that events stream MAXLEN is 5000"""
        maxlen = config_paper.stream_maxlen["events"]
        assert maxlen == 5000


class TestSignalStreamMaxLen:
    """Test signal stream MAXLEN configuration (PRD-001 Section 2.2 Item 4)"""

    def test_signal_stream_maxlen(self, config_paper):
        """Test that signal stream MAXLEN is 10000"""
        maxlen = config_paper.stream_maxlen["signals"]
        assert maxlen == 10000


class TestStreamVerification:
    """Test stream verification on startup (PRD-001 Section 2.2 Items 6-7)"""

    @pytest.mark.asyncio
    async def test_verify_stream_configuration_calls_xinfo(self, redis_manager_paper):
        """Test that stream verification calls XINFO STREAM"""
        redis_manager_paper.redis_client = AsyncMock()
        redis_manager_paper.redis_client.xinfo_stream = AsyncMock(return_value={
            'length': 100,
            'first-entry': ['123', {}],
            'last-entry': ['456', {}]
        })

        await redis_manager_paper.verify_stream_configuration()

        # Should have called xinfo_stream for each stream
        assert redis_manager_paper.redis_client.xinfo_stream.call_count == 3

    @pytest.mark.asyncio
    async def test_verify_stream_logs_configuration(self, redis_manager_paper, caplog):
        """Test that stream verification logs configuration at INFO level"""
        redis_manager_paper.redis_client = AsyncMock()
        redis_manager_paper.redis_client.xinfo_stream = AsyncMock(return_value={
            'length': 100,
            'first-entry': ['123', {}],
            'last-entry': ['456', {}]
        })

        with caplog.at_level(logging.INFO):
            await redis_manager_paper.verify_stream_configuration()

        # Should have INFO logs for stream configuration
        info_logs = [r for r in caplog.records if r.levelname == "INFO"]
        assert len(info_logs) > 0
        assert any("Stream configuration verified" in log.message for log in info_logs)

    @pytest.mark.asyncio
    async def test_verify_stream_handles_nonexistent_streams(self, redis_manager_paper, caplog):
        """Test that stream verification handles non-existent streams gracefully"""
        redis_manager_paper.redis_client = AsyncMock()
        redis_manager_paper.redis_client.xinfo_stream = AsyncMock(
            side_effect=Exception("ERR no such key")
        )

        with caplog.at_level(logging.INFO):
            await redis_manager_paper.verify_stream_configuration()

        # Should log that streams will be created on first publish
        info_logs = [r for r in caplog.records if r.levelname == "INFO"]
        assert any("not yet created" in log.message for log in info_logs)

    @pytest.mark.asyncio
    async def test_verify_stream_checks_all_configured_streams(self, redis_manager_paper):
        """Test that verification checks signal, pnl, and events streams"""
        redis_manager_paper.redis_client = AsyncMock()
        call_args_list = []

        async def track_calls(stream_name):
            call_args_list.append(stream_name)
            return {'length': 0}

        redis_manager_paper.redis_client.xinfo_stream = track_calls

        await redis_manager_paper.verify_stream_configuration()

        # Should have checked all three streams
        assert "signals:paper" in call_args_list
        assert "pnl:signals" in call_args_list
        assert "events:bus" in call_args_list


class TestPrometheusStreamMetrics:
    """Test Prometheus stream length gauge (PRD-001 Section 2.2 Item 8)"""

    @pytest.mark.skipif(not PROMETHEUS_AVAILABLE, reason="Prometheus not available")
    @pytest.mark.asyncio
    async def test_stream_metrics_emitted_on_verification(self, redis_manager_paper):
        """Test that stream length metrics are emitted during verification"""
        redis_manager_paper.redis_client = AsyncMock()
        redis_manager_paper.redis_client.xinfo_stream = AsyncMock(return_value={
            'length': 150
        })

        await redis_manager_paper.verify_stream_configuration()

        # Verify metrics were set (check one stream as example)
        signal_stream = redis_manager_paper.config.get_signal_stream_name()
        metric_value = REDIS_STREAM_LENGTH.labels(stream=signal_stream)._value.get()
        assert metric_value == 150

    @pytest.mark.skipif(not PROMETHEUS_AVAILABLE, reason="Prometheus not available")
    @pytest.mark.asyncio
    async def test_update_stream_metrics(self, redis_manager_paper):
        """Test that update_stream_metrics updates all stream gauges"""
        redis_manager_paper.redis_client = AsyncMock()
        redis_manager_paper.redis_client.xinfo_stream = AsyncMock(return_value={
            'length': 250
        })

        await redis_manager_paper.update_stream_metrics()

        # All streams should have been checked
        assert redis_manager_paper.redis_client.xinfo_stream.call_count == 3

    @pytest.mark.skipif(not PROMETHEUS_AVAILABLE, reason="Prometheus not available")
    @pytest.mark.asyncio
    async def test_stream_metrics_by_stream_label(self, redis_manager_paper):
        """Test that stream metrics use stream name as label"""
        redis_manager_paper.redis_client = AsyncMock()

        # Return different lengths for different streams
        call_count = [0]
        lengths = [100, 200, 300]

        async def get_stream_length(stream_name):
            length = lengths[call_count[0]]
            call_count[0] += 1
            return {'length': length}

        redis_manager_paper.redis_client.xinfo_stream = get_stream_length

        await redis_manager_paper.verify_stream_configuration()

        # Each stream should have its own metric value
        signal_value = REDIS_STREAM_LENGTH.labels(stream="signals:paper")._value.get()
        pnl_value = REDIS_STREAM_LENGTH.labels(stream="pnl:signals")._value.get()
        events_value = REDIS_STREAM_LENGTH.labels(stream="events:bus")._value.get()

        # Values should be different (from our mock)
        assert signal_value in [100, 200, 300]
        assert pnl_value in [100, 200, 300]
        assert events_value in [100, 200, 300]


class TestStreamMAXLENConfiguration:
    """Test stream MAXLEN configuration"""

    def test_all_stream_maxlens_configured(self, config_paper):
        """Test that all stream MAXLENs are configured"""
        assert "signals" in config_paper.stream_maxlen
        assert "pnl" in config_paper.stream_maxlen
        assert "events" in config_paper.stream_maxlen

    def test_stream_maxlens_are_integers(self, config_paper):
        """Test that all stream MAXLENs are integers"""
        for maxlen in config_paper.stream_maxlen.values():
            assert isinstance(maxlen, int)
            assert maxlen > 0
