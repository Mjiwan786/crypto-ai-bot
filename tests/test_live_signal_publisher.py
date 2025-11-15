#!/usr/bin/env python3
"""
Tests for Live Signal Publisher
================================

Comprehensive test suite for live_signal_publisher.py covering:
- Configuration validation
- Signal generation
- Schema validation
- Redis publishing
- Metrics tracking
- Heartbeat functionality
- Health endpoint
- Mode toggling (paper/live)

"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from live_signal_publisher import (
    LiveSignalPublisher,
    PublisherConfig,
    PublisherMetrics,
)
from signals.schema import Signal, create_signal


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def paper_config():
    """Paper mode configuration for testing"""
    return PublisherConfig(
        mode="paper",
        trading_pairs=["BTC/USD", "ETH/USD"],
        max_signals_per_second=10.0,
        redis_url="rediss://test:test@localhost:6380",
        redis_ca_cert="/tmp/fake_cert.pem",
        live_trading_confirmation="",  # Not needed for paper
    )


@pytest.fixture
def live_config():
    """Live mode configuration for testing"""
    return PublisherConfig(
        mode="live",
        trading_pairs=["BTC/USD"],
        max_signals_per_second=5.0,
        redis_url="rediss://test:test@localhost:6380",
        redis_ca_cert="/tmp/fake_cert.pem",
        live_trading_confirmation="I confirm live trading",
    )


@pytest.fixture
def mock_redis_client():
    """Mock Redis client"""
    client = AsyncMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.xadd = AsyncMock(return_value=b"1730000000000-0")
    client.ping = AsyncMock(return_value=True)
    return client


@pytest.fixture
def mock_signal_publisher():
    """Mock SignalPublisher"""
    publisher = AsyncMock()
    publisher.connect = AsyncMock()
    publisher.close = AsyncMock()
    publisher.publish = AsyncMock(return_value="1730000000000-0")
    return publisher


# =============================================================================
# Configuration Tests
# =============================================================================


class TestPublisherConfig:
    """Test configuration validation"""

    def test_valid_paper_config(self, paper_config):
        """Test valid paper mode configuration"""
        paper_config.validate()  # Should not raise

    def test_valid_live_config(self, live_config):
        """Test valid live mode configuration"""
        live_config.validate()  # Should not raise

    def test_invalid_mode(self):
        """Test invalid trading mode"""
        config = PublisherConfig(
            mode="invalid",
            redis_url="rediss://test:test@localhost:6380",
        )

        with pytest.raises(ValueError, match="Invalid mode"):
            config.validate()

    def test_live_mode_without_confirmation(self):
        """Test live mode requires confirmation"""
        config = PublisherConfig(
            mode="live",
            redis_url="rediss://test:test@localhost:6380",
            live_trading_confirmation="",  # Missing confirmation
        )

        with pytest.raises(ValueError, match="Live trading requires"):
            config.validate()

    def test_missing_redis_url(self):
        """Test missing Redis URL"""
        config = PublisherConfig(
            mode="paper",
            redis_url="",  # Missing
        )

        with pytest.raises(ValueError, match="REDIS_URL"):
            config.validate()

    def test_non_tls_redis_url(self):
        """Test non-TLS Redis URL rejected"""
        config = PublisherConfig(
            mode="paper",
            redis_url="redis://test:test@localhost:6379",  # Not rediss://
        )

        with pytest.raises(ValueError, match="must use TLS"):
            config.validate()

    def test_invalid_pair_format(self):
        """Test invalid pair format"""
        config = PublisherConfig(
            mode="paper",
            trading_pairs=["BTCUSD"],  # Missing slash
            redis_url="rediss://test:test@localhost:6380",
        )

        with pytest.raises(ValueError, match="Invalid pair format"):
            config.validate()

    def test_empty_trading_pairs(self):
        """Test empty trading pairs list"""
        config = PublisherConfig(
            mode="paper",
            trading_pairs=[],  # Empty
            redis_url="rediss://test:test@localhost:6380",
        )

        with pytest.raises(ValueError, match="At least one trading pair"):
            config.validate()


# =============================================================================
# Metrics Tests
# =============================================================================


class TestPublisherMetrics:
    """Test metrics tracking"""

    def test_initial_metrics(self):
        """Test initial metrics state"""
        metrics = PublisherMetrics()

        assert metrics.total_published == 0
        assert metrics.total_errors == 0
        assert len(metrics.signals_by_pair) == 0
        assert len(metrics.signals_by_mode) == 0
        assert metrics.get_freshness_seconds() == float('inf')

    def test_record_signal(self):
        """Test recording signal publication"""
        metrics = PublisherMetrics()

        metrics.record_signal(
            pair="BTC/USD",
            mode="paper",
            gen_latency_ms=10.5,
            redis_latency_ms=5.2,
        )

        assert metrics.total_published == 1
        assert metrics.signals_by_pair["BTC/USD"] == 1
        assert metrics.signals_by_mode["paper"] == 1
        assert len(metrics.signal_generation_latencies) == 1
        assert len(metrics.redis_publish_latencies) == 1

    def test_record_error(self):
        """Test recording errors"""
        metrics = PublisherMetrics()

        metrics.record_error()
        metrics.record_error()

        assert metrics.total_errors == 2

    def test_freshness_tracking(self):
        """Test freshness calculation"""
        metrics = PublisherMetrics()

        # No signals published yet
        assert metrics.get_freshness_seconds() == float('inf')

        # Publish a signal
        metrics.record_signal("BTC/USD", "paper", 10.0, 5.0)

        # Freshness should be near 0
        freshness = metrics.get_freshness_seconds()
        assert freshness < 1.0  # Less than 1 second

        # Simulate time passing
        time.sleep(0.1)
        freshness = metrics.get_freshness_seconds()
        assert freshness >= 0.1

    def test_latency_stats(self):
        """Test latency statistics calculation"""
        metrics = PublisherMetrics()

        # Add some latency samples
        for i in range(100):
            metrics.record_signal(
                "BTC/USD",
                "paper",
                gen_latency_ms=float(i),  # 0-99ms
                redis_latency_ms=float(i) / 2,  # 0-49.5ms
            )

        stats = metrics.get_latency_stats()

        assert stats["gen_p50"] >= 40  # Around 50th value
        assert stats["gen_p95"] >= 90  # Around 95th value
        assert stats["redis_p50"] >= 20  # Half of gen_p50

    def test_latency_window_limit(self):
        """Test latency samples are limited to last 1000"""
        metrics = PublisherMetrics()

        # Add 1500 samples
        for i in range(1500):
            metrics.record_signal("BTC/USD", "paper", float(i), float(i))

        # Should only keep last 1000
        assert len(metrics.signal_generation_latencies) == 1000
        assert len(metrics.redis_publish_latencies) == 1000

        # Should have kept the most recent
        assert metrics.signal_generation_latencies[-1] == 1499.0

    def test_to_dict(self):
        """Test metrics serialization"""
        metrics = PublisherMetrics()

        metrics.record_signal("BTC/USD", "paper", 10.0, 5.0)
        metrics.record_signal("ETH/USD", "live", 15.0, 7.0)
        metrics.record_error()

        data = metrics.to_dict()

        assert data["total_published"] == 2
        assert data["total_errors"] == 1
        assert data["signals_by_pair"]["BTC/USD"] == 1
        assert data["signals_by_pair"]["ETH/USD"] == 1
        assert data["signals_by_mode"]["paper"] == 1
        assert data["signals_by_mode"]["live"] == 1
        assert "latency_ms" in data
        assert "freshness_seconds" in data


# =============================================================================
# Publisher Tests
# =============================================================================


class TestLiveSignalPublisher:
    """Test LiveSignalPublisher functionality"""

    @pytest.mark.asyncio
    async def test_signal_generation(self, paper_config):
        """Test signal generation"""
        publisher = LiveSignalPublisher(paper_config)

        signal = await publisher.generate_signal("BTC/USD")

        assert signal is not None
        assert signal.pair == "BTC/USD"
        assert signal.mode == "paper"
        assert signal.side in ["long", "short"]
        assert signal.entry > 0
        assert signal.sl > 0
        assert signal.tp > 0
        assert 0 <= signal.confidence <= 1
        assert signal.strategy == paper_config.strategy_name

    @pytest.mark.asyncio
    async def test_signal_schema_validation(self, paper_config):
        """Test generated signals pass schema validation"""
        publisher = LiveSignalPublisher(paper_config)

        for pair in paper_config.trading_pairs:
            signal = await publisher.generate_signal(pair)

            # Should not raise validation error
            Signal.model_validate(signal.model_dump())

    @pytest.mark.asyncio
    async def test_signal_stream_key(self, paper_config):
        """Test signals generate correct stream keys"""
        publisher = LiveSignalPublisher(paper_config)

        signal = await publisher.generate_signal("BTC/USD")

        expected_key = "signals:paper:BTC-USD"
        assert signal.get_stream_key() == expected_key

    @pytest.mark.asyncio
    async def test_live_mode_signal_stream_key(self, live_config):
        """Test live mode signals use correct stream key"""
        publisher = LiveSignalPublisher(live_config)

        signal = await publisher.generate_signal("BTC/USD")

        expected_key = "signals:live:BTC-USD"
        assert signal.get_stream_key() == expected_key

    @pytest.mark.asyncio
    @patch("live_signal_publisher.RedisCloudClient")
    @patch("live_signal_publisher.SignalPublisher")
    async def test_connect(self, mock_publisher_class, mock_client_class, paper_config):
        """Test Redis connection"""
        # Setup mocks
        mock_client = AsyncMock()
        mock_client.connect = AsyncMock()
        mock_client_class.return_value = mock_client

        mock_publisher = AsyncMock()
        mock_publisher.connect = AsyncMock()
        mock_publisher_class.return_value = mock_publisher

        # Test
        publisher = LiveSignalPublisher(paper_config)
        await publisher.connect()

        # Verify connections
        mock_client.connect.assert_called_once()
        mock_publisher.connect.assert_called_once()

    @pytest.mark.asyncio
    @patch("live_signal_publisher.SignalPublisher")
    async def test_publish_signal(self, mock_publisher_class, paper_config):
        """Test signal publishing"""
        # Setup mock
        mock_publisher = AsyncMock()
        mock_publisher.connect = AsyncMock()
        mock_publisher.publish = AsyncMock(return_value="1730000000000-0")
        mock_publisher_class.return_value = mock_publisher

        # Create publisher
        publisher = LiveSignalPublisher(paper_config)
        publisher.signal_publisher = mock_publisher

        # Generate and publish signal
        signal = await publisher.generate_signal("BTC/USD")
        await publisher.publish_signal(signal)

        # Verify
        mock_publisher.publish.assert_called_once_with(signal)
        assert publisher.metrics.total_published == 1
        assert publisher.metrics.signals_by_pair["BTC/USD"] == 1

    @pytest.mark.asyncio
    @patch("live_signal_publisher.RedisCloudClient")
    async def test_publish_heartbeat(self, mock_client_class, paper_config):
        """Test heartbeat publishing"""
        # Setup mock
        mock_client = AsyncMock()
        mock_client.xadd = AsyncMock(return_value=b"1730000000000-0")
        mock_client_class.return_value = mock_client

        # Create publisher
        publisher = LiveSignalPublisher(paper_config)
        publisher.redis_client = mock_client

        # Publish heartbeat
        await publisher.publish_heartbeat()

        # Verify
        mock_client.xadd.assert_called_once()
        call_args = mock_client.xadd.call_args

        assert call_args[0][0] == "ops:heartbeat"  # Stream name
        assert "json" in call_args[0][1]  # Has JSON payload

        # Verify heartbeat content
        heartbeat_json = call_args[0][1]["json"]
        heartbeat = json.loads(heartbeat_json)

        assert heartbeat["service"] == "live_signal_publisher"
        assert heartbeat["mode"] == "paper"
        assert "ts" in heartbeat
        assert "published" in heartbeat

    @pytest.mark.asyncio
    @patch("live_signal_publisher.RedisCloudClient")
    async def test_publish_metrics(self, mock_client_class, paper_config):
        """Test metrics publishing"""
        # Setup mock
        mock_client = AsyncMock()
        mock_client.xadd = AsyncMock(return_value=b"1730000000000-0")
        mock_client_class.return_value = mock_client

        # Create publisher
        publisher = LiveSignalPublisher(paper_config)
        publisher.redis_client = mock_client

        # Add some metrics
        publisher.metrics.record_signal("BTC/USD", "paper", 10.0, 5.0)

        # Publish metrics
        await publisher.publish_metrics()

        # Verify
        mock_client.xadd.assert_called_once()
        call_args = mock_client.xadd.call_args

        assert call_args[0][0] == "metrics:publisher"  # Stream name

    def test_health_status_healthy(self, paper_config):
        """Test health status when publishing normally"""
        publisher = LiveSignalPublisher(paper_config)

        # Simulate recent publish
        publisher.metrics.last_signal_time = time.time()

        health = publisher.get_health_status()

        assert health["status"] == "healthy"
        assert health["mode"] == "paper"
        assert "metrics" in health

    def test_health_status_degraded(self, paper_config):
        """Test health status when no recent publishes"""
        publisher = LiveSignalPublisher(paper_config)

        # Simulate old publish (>30s ago)
        publisher.metrics.last_signal_time = time.time() - 35

        health = publisher.get_health_status()

        assert health["status"] == "degraded"
        assert "No signal published" in health["reason"]


# =============================================================================
# Integration Tests
# =============================================================================


class TestPublisherIntegration:
    """Integration tests (require Redis)"""

    @pytest.mark.skipif(
        os.getenv("REDIS_URL", "") == "",
        reason="Requires REDIS_URL environment variable",
    )
    @pytest.mark.asyncio
    async def test_full_publish_cycle(self):
        """Test complete publish cycle with real Redis"""
        from dotenv import load_dotenv

        load_dotenv(project_root / ".env.paper")

        config = PublisherConfig(
            mode="paper",
            trading_pairs=["BTC/USD"],
            redis_url=os.getenv("REDIS_URL"),
            redis_ca_cert=os.getenv("REDIS_CA_CERT"),
        )

        config.validate()

        publisher = LiveSignalPublisher(config)

        try:
            # Connect
            await publisher.connect()

            # Generate signal
            signal = await publisher.generate_signal("BTC/USD")

            # Publish signal
            await publisher.publish_signal(signal)

            # Verify metrics
            assert publisher.metrics.total_published == 1

            # Publish heartbeat
            await publisher.publish_heartbeat()

            # Publish metrics
            await publisher.publish_metrics()

        finally:
            await publisher.disconnect()


# =============================================================================
# Run Tests
# =============================================================================


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
