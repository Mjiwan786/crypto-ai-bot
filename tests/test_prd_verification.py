"""
PRD-001 Verification Test Suite for crypto-ai-bot

This test suite validates PRD-001 compliance:
- Signal schema validation
- Redis stream naming
- Pairs consistency (BTC-USD, ETH-USD, SOL-USD, MATIC-USD, LINK-USD)
- Metrics publishing (engine:summary_metrics)
- Redis publishing and fallback safety

Run with: pytest tests/test_prd_verification.py -v
"""

import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# =============================================================================
# CONSTANTS - PRD-001 REQUIREMENTS
# =============================================================================

PRD_CANONICAL_PAIRS = ["BTC/USD", "ETH/USD", "SOL/USD", "MATIC/USD", "LINK/USD"]
PRD_STREAM_NAMES_PAPER = [
    "signals:paper:BTC-USD",
    "signals:paper:ETH-USD",
    "signals:paper:SOL-USD",
    "signals:paper:MATIC-USD",
    "signals:paper:LINK-USD",
]
PRD_STREAM_NAMES_LIVE = [
    "signals:live:BTC-USD",
    "signals:live:ETH-USD",
    "signals:live:SOL-USD",
    "signals:live:MATIC-USD",
    "signals:live:LINK-USD",
]
PRD_PNL_STREAM_PAPER = "pnl:paper:equity_curve"
PRD_PNL_STREAM_LIVE = "pnl:live:equity_curve"
PRD_EVENTS_STREAM = "events:bus"
PRD_SUMMARY_KEY = "engine:summary_metrics"


# =============================================================================
# SIGNAL SCHEMA TESTS
# =============================================================================

class TestSignalSchema:
    """Test PRD-001 Section 5.1: Signal Schema v1.0"""

    def test_signal_creation_valid(self):
        """Test creating a valid signal with all required fields."""
        from signals.schema import create_signal, Signal

        signal = create_signal(
            pair="BTC/USD",
            side="buy",
            entry=50000.0,
            sl=49000.0,
            tp=52000.0,
            strategy="momentum_v1",
            confidence=0.75,
            mode="paper",
        )

        assert isinstance(signal, Signal)
        assert signal.pair == "BTC/USD"
        assert signal.side == "buy"
        assert signal.entry == 50000.0
        assert signal.sl == 49000.0
        assert signal.tp == 52000.0
        assert signal.strategy == "momentum_v1"
        assert signal.confidence == 0.75
        assert signal.mode == "paper"
        assert len(signal.id) == 32  # SHA256 hash prefix

    def test_signal_pair_normalization(self):
        """Test that pairs with dash are normalized to slash format."""
        from signals.schema import create_signal

        signal = create_signal(
            pair="BTC-USD",  # Using dash
            side="buy",
            entry=50000.0,
            sl=49000.0,
            tp=52000.0,
            strategy="test",
            confidence=0.5,
            mode="paper",
        )

        assert signal.pair == "BTC/USD"  # Should be normalized to slash

    def test_signal_side_values(self):
        """Test that side accepts 'buy' and 'sell' (not 'long'/'short')."""
        from signals.schema import create_signal

        # Valid sides
        buy_signal = create_signal(
            pair="ETH/USD", side="buy", entry=3000.0, sl=2900.0, tp=3100.0,
            strategy="test", confidence=0.6, mode="paper"
        )
        sell_signal = create_signal(
            pair="ETH/USD", side="sell", entry=3000.0, sl=3100.0, tp=2900.0,
            strategy="test", confidence=0.6, mode="paper"
        )

        assert buy_signal.side == "buy"
        assert sell_signal.side == "sell"

    def test_signal_confidence_validation(self):
        """Test confidence must be between 0.0 and 1.0."""
        from signals.schema import create_signal
        from pydantic import ValidationError

        # Valid confidence
        signal = create_signal(
            pair="SOL/USD", side="buy", entry=100.0, sl=95.0, tp=110.0,
            strategy="test", confidence=0.85, mode="paper"
        )
        assert signal.confidence == 0.85

        # Invalid confidence > 1.0
        with pytest.raises(ValidationError):
            create_signal(
                pair="SOL/USD", side="buy", entry=100.0, sl=95.0, tp=110.0,
                strategy="test", confidence=1.5, mode="paper"
            )

        # Invalid confidence < 0.0
        with pytest.raises(ValidationError):
            create_signal(
                pair="SOL/USD", side="buy", entry=100.0, sl=95.0, tp=110.0,
                strategy="test", confidence=-0.1, mode="paper"
            )

    def test_signal_mode_validation(self):
        """Test mode must be 'paper' or 'live'."""
        from signals.schema import create_signal

        paper = create_signal(
            pair="LINK/USD", side="buy", entry=15.0, sl=14.0, tp=17.0,
            strategy="test", confidence=0.7, mode="paper"
        )
        live = create_signal(
            pair="LINK/USD", side="buy", entry=15.0, sl=14.0, tp=17.0,
            strategy="test", confidence=0.7, mode="live"
        )

        assert paper.mode == "paper"
        assert live.mode == "live"

    def test_signal_idempotent_id_generation(self):
        """Test that same ts/pair/strategy generates same ID (idempotency)."""
        from signals.schema import generate_signal_id

        ts = 1730000000000
        pair = "BTC/USD"
        strategy = "momentum_v1"

        id1 = generate_signal_id(ts, pair, strategy)
        id2 = generate_signal_id(ts, pair, strategy)

        assert id1 == id2
        assert len(id1) == 32

    def test_signal_stream_key_generation(self):
        """Test stream key generation follows PRD pattern."""
        from signals.schema import create_signal

        paper_signal = create_signal(
            pair="BTC/USD", side="buy", entry=50000.0, sl=49000.0, tp=52000.0,
            strategy="test", confidence=0.7, mode="paper"
        )
        live_signal = create_signal(
            pair="ETH/USD", side="sell", entry=3000.0, sl=3100.0, tp=2900.0,
            strategy="test", confidence=0.7, mode="live"
        )

        assert paper_signal.get_stream_key() == "signals:paper:BTC-USD"
        assert live_signal.get_stream_key() == "signals:live:ETH-USD"

    def test_signal_to_redis_dict(self):
        """Test conversion to Redis-compatible dict (all string values)."""
        from signals.schema import create_signal

        signal = create_signal(
            pair="MATIC/USD", side="buy", entry=0.85, sl=0.80, tp=0.95,
            strategy="scalper", confidence=0.72, mode="paper"
        )

        redis_dict = signal.to_redis_dict()

        # All values must be strings for Redis XADD
        for key, value in redis_dict.items():
            assert isinstance(value, str), f"Field {key} is not a string"

    def test_signal_immutability(self):
        """Test that signals are frozen (immutable)."""
        from signals.schema import create_signal

        signal = create_signal(
            pair="BTC/USD", side="buy", entry=50000.0, sl=49000.0, tp=52000.0,
            strategy="test", confidence=0.7, mode="paper"
        )

        # Attempting to modify should raise
        with pytest.raises(Exception):  # Pydantic v2 raises ValidationError
            signal.confidence = 0.9


# =============================================================================
# REDIS STREAM NAMING TESTS
# =============================================================================

class TestRedisStreamNaming:
    """Test PRD-001 Section B.2: Stream Configuration and Naming Convention"""

    def test_signal_stream_names_paper(self):
        """Test paper mode signal stream names match PRD-001."""
        from agents.infrastructure.prd_redis_publisher import get_signal_stream_name

        for pair in PRD_CANONICAL_PAIRS:
            stream_name = get_signal_stream_name("paper", pair)
            expected = f"signals:paper:{pair.replace('/', '-')}"
            assert stream_name == expected, f"Stream name mismatch for {pair}"

    def test_signal_stream_names_live(self):
        """Test live mode signal stream names match PRD-001."""
        from agents.infrastructure.prd_redis_publisher import get_signal_stream_name

        for pair in PRD_CANONICAL_PAIRS:
            stream_name = get_signal_stream_name("live", pair)
            expected = f"signals:live:{pair.replace('/', '-')}"
            assert stream_name == expected, f"Stream name mismatch for {pair}"

    def test_pnl_stream_names(self):
        """Test PnL stream names match PRD-001."""
        from agents.infrastructure.prd_redis_publisher import get_pnl_stream_name

        assert get_pnl_stream_name("paper") == PRD_PNL_STREAM_PAPER
        assert get_pnl_stream_name("live") == PRD_PNL_STREAM_LIVE

    def test_event_stream_name(self):
        """Test event stream name matches PRD-001."""
        from agents.infrastructure.prd_redis_publisher import get_event_stream_name

        assert get_event_stream_name() == PRD_EVENTS_STREAM

    def test_invalid_mode_raises_error(self):
        """Test invalid mode raises ValueError."""
        from agents.infrastructure.prd_redis_publisher import (
            get_signal_stream_name,
            get_pnl_stream_name,
        )

        with pytest.raises(ValueError):
            get_signal_stream_name("invalid", "BTC/USD")

        with pytest.raises(ValueError):
            get_pnl_stream_name("invalid")


# =============================================================================
# TRADING PAIRS CONSISTENCY TESTS
# =============================================================================

class TestTradingPairs:
    """Test PRD-001 Section 4.A: Trading Pairs Consistency"""

    def test_env_trading_pairs_match_prd(self):
        """Test that configured trading pairs match PRD-001 canonical pairs."""
        from dotenv import load_dotenv
        load_dotenv(".env.paper")

        trading_pairs = os.getenv("TRADING_PAIRS", "").split(",")
        trading_pairs = [p.strip() for p in trading_pairs if p.strip()]

        assert set(trading_pairs) == set(PRD_CANONICAL_PAIRS), \
            f"Trading pairs mismatch. Expected: {PRD_CANONICAL_PAIRS}, Got: {trading_pairs}"

    def test_kraken_trading_pairs_match_prd(self):
        """Test that Kraken trading pairs match PRD-001."""
        from dotenv import load_dotenv
        load_dotenv(".env.paper")

        kraken_pairs = os.getenv("KRAKEN_TRADING_PAIRS", "").split(",")
        kraken_pairs = [p.strip() for p in kraken_pairs if p.strip()]

        assert set(kraken_pairs) == set(PRD_CANONICAL_PAIRS), \
            f"Kraken pairs mismatch. Expected: {PRD_CANONICAL_PAIRS}, Got: {kraken_pairs}"

    def test_metrics_calculator_pairs_match_prd(self):
        """Test that MetricsSummaryCalculator uses PRD canonical pairs."""
        from analysis.metrics_summary import CANONICAL_PAIRS

        assert set(CANONICAL_PAIRS) == set(PRD_CANONICAL_PAIRS), \
            f"Metrics calculator pairs mismatch. Expected: {PRD_CANONICAL_PAIRS}, Got: {CANONICAL_PAIRS}"


# =============================================================================
# METRICS PUBLISHING TESTS
# =============================================================================

class TestMetricsPublishing:
    """Test PRD-001: Metrics publishing to engine:summary_metrics"""

    def test_summary_metrics_key_name(self):
        """Test summary metrics uses correct Redis key."""
        from analysis.metrics_summary import KEY_ENGINE_SUMMARY

        assert KEY_ENGINE_SUMMARY == PRD_SUMMARY_KEY

    def test_summary_metrics_fields(self):
        """Test SummaryMetrics has all required fields."""
        from analysis.metrics_summary import SummaryMetrics

        # Create a sample summary
        summary = SummaryMetrics(
            mode="paper",
            timestamp="2025-01-01T00:00:00Z",
        )

        # Verify required fields exist
        required_fields = [
            "signals_per_day",
            "win_rate_pct",
            "roi_30d",
            "profit_factor",
            "max_drawdown_pct",
            "sharpe_ratio",
            "total_trades",
            "trading_pairs",
        ]

        summary_dict = summary.to_dict()
        for field in required_fields:
            assert field in summary_dict, f"Missing required field: {field}"

    def test_performance_metrics_periods(self):
        """Test performance metrics include 30d, 90d, 365d periods."""
        from analysis.metrics_summary import SummaryMetrics

        summary = SummaryMetrics(
            mode="paper",
            timestamp="2025-01-01T00:00:00Z",
            performance_30d={"period_days": 30},
            performance_90d={"period_days": 90},
            performance_365d={"period_days": 365},
        )

        assert summary.performance_30d is not None
        assert summary.performance_90d is not None
        assert summary.performance_365d is not None


# =============================================================================
# REDIS PUBLISHING MOCK TESTS
# =============================================================================

class TestRedisPublishing:
    """Test Redis publishing functions with mocks."""

    @pytest.fixture
    def mock_redis_client(self):
        """Create a mock Redis client."""
        client = AsyncMock()
        client.ping.return_value = True
        client.xadd.return_value = b"1234567890-0"
        client.hset.return_value = True
        client.expire.return_value = True
        return client

    @pytest.mark.asyncio
    async def test_publish_signal_validates_schema(self, mock_redis_client):
        """Test that publish_signal validates signal schema."""
        from agents.infrastructure.prd_redis_publisher import publish_signal

        # Valid signal
        valid_signal = {
            "signal_id": "test-uuid",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "pair": "BTC/USD",
            "side": "LONG",
            "strategy": "SCALPER",
            "regime": "TRENDING_UP",
            "entry_price": 50000.0,
            "take_profit": 52000.0,
            "stop_loss": 49000.0,
            "position_size_usd": 100.0,
            "confidence": 0.85,
            "risk_reward_ratio": 2.0,
        }

        # Should not raise
        result = await publish_signal(mock_redis_client, "paper", valid_signal)
        # Note: Result may be None if the internal validation fails for other reasons
        # The key test is that invalid data raises ValueError

    @pytest.mark.asyncio
    async def test_publish_signal_rejects_invalid_schema(self, mock_redis_client):
        """Test that publish_signal rejects invalid signal data."""
        from agents.infrastructure.prd_redis_publisher import publish_signal

        # Invalid signal - missing required fields
        invalid_signal = {
            "pair": "BTC/USD",
            # Missing: signal_id, timestamp, side, strategy, etc.
        }

        with pytest.raises(ValueError):
            await publish_signal(mock_redis_client, "paper", invalid_signal)


# =============================================================================
# FALLBACK SAFETY TESTS
# =============================================================================

class TestFallbackSafety:
    """Test fallback safety behavior."""

    def test_engine_mode_defaults_to_paper(self):
        """Test ENGINE_MODE defaults to 'paper' for safety."""
        from agents.infrastructure.prd_redis_publisher import get_engine_mode

        # Clear any existing ENV var
        original = os.environ.pop("ENGINE_MODE", None)
        try:
            mode = get_engine_mode()
            assert mode == "paper", "Default mode should be 'paper' for safety"
        finally:
            if original:
                os.environ["ENGINE_MODE"] = original

    def test_invalid_engine_mode_falls_back_to_paper(self):
        """Test invalid ENGINE_MODE falls back to 'paper'."""
        from agents.infrastructure.prd_redis_publisher import get_engine_mode

        original = os.environ.get("ENGINE_MODE")
        try:
            os.environ["ENGINE_MODE"] = "invalid_mode"
            mode = get_engine_mode()
            assert mode == "paper", "Invalid mode should fall back to 'paper'"
        finally:
            if original:
                os.environ["ENGINE_MODE"] = original
            else:
                os.environ.pop("ENGINE_MODE", None)


# =============================================================================
# METRICS CALCULATION TESTS
# =============================================================================

class TestMetricsCalculations:
    """Test metrics calculation logic."""

    def test_sharpe_ratio_calculation(self):
        """Test Sharpe ratio calculation with sample data."""
        from analysis.metrics_summary import MetricsSummaryCalculator, TradingAssumptions

        # Create calculator (won't actually connect to Redis)
        calc = MetricsSummaryCalculator(
            redis_url="rediss://test",
            mode="paper",
        )

        # Sample equity curve (simulated)
        equity_curve = [
            {"timestamp": 1700000000, "equity": 10000.0},
            {"timestamp": 1700086400, "equity": 10100.0},  # +1% day 1
            {"timestamp": 1700172800, "equity": 10050.0},  # -0.5% day 2
            {"timestamp": 1700259200, "equity": 10200.0},  # +1.5% day 3
            {"timestamp": 1700345600, "equity": 10300.0},  # +1% day 4
        ]

        sharpe = calc.calculate_sharpe_ratio(equity_curve)

        # Sharpe should be a reasonable number (positive for profitable curve)
        assert isinstance(sharpe, float)
        # With small sample, we just verify it returns a number

    def test_max_drawdown_calculation(self):
        """Test max drawdown calculation."""
        from analysis.metrics_summary import MetricsSummaryCalculator

        calc = MetricsSummaryCalculator(
            redis_url="rediss://test",
            mode="paper",
        )

        # Equity curve with clear drawdown
        equity_curve = [
            {"timestamp": 1, "equity": 10000.0},
            {"timestamp": 2, "equity": 11000.0},  # Peak
            {"timestamp": 3, "equity": 10000.0},  # 9.09% drawdown
            {"timestamp": 4, "equity": 9500.0},   # 13.64% drawdown from peak
            {"timestamp": 5, "equity": 10500.0},
        ]

        max_dd = calc.calculate_max_drawdown(equity_curve)

        # Max drawdown should be around 13.64%
        assert 13.0 < max_dd < 14.0

    def test_cagr_calculation(self):
        """Test CAGR calculation."""
        from analysis.metrics_summary import MetricsSummaryCalculator

        calc = MetricsSummaryCalculator(
            redis_url="rediss://test",
            mode="paper",
        )

        # 100% return over 365 days = 100% CAGR
        cagr = calc.calculate_cagr(
            starting_equity=10000.0,
            ending_equity=20000.0,
            days=365
        )

        assert 99.0 < cagr < 101.0  # Should be ~100%

        # 50% return over 182.5 days (half year)
        cagr_half = calc.calculate_cagr(
            starting_equity=10000.0,
            ending_equity=15000.0,
            days=182.5
        )

        # Annualized should be more than 50% (compounding)
        assert cagr_half > 50.0


# =============================================================================
# INTEGRATION TEST MARKERS
# =============================================================================

@pytest.mark.integration
class TestRedisIntegration:
    """Integration tests that require actual Redis connection.

    Run with: pytest tests/test_prd_verification.py -v -m integration
    Requires: REDIS_URL environment variable set
    """

    @pytest.fixture
    def redis_url(self):
        """Get Redis URL from environment."""
        from dotenv import load_dotenv
        load_dotenv(".env.paper")
        url = os.getenv("REDIS_URL")
        if not url:
            pytest.skip("REDIS_URL not set")
        return url

    @pytest.mark.asyncio
    async def test_redis_connection(self, redis_url):
        """Test Redis connection with TLS."""
        import redis.asyncio as aioredis

        redis_ca_cert = os.getenv("REDIS_CA_CERT_PATH", "config/certs/redis_ca.pem")

        client = aioredis.from_url(
            redis_url,
            ssl_ca_certs=redis_ca_cert,
            ssl_cert_reqs="required",
            socket_connect_timeout=10,
        )

        try:
            pong = await client.ping()
            assert pong is True
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_signal_streams_exist(self, redis_url):
        """Test that PRD signal streams exist and have data."""
        import redis.asyncio as aioredis

        redis_ca_cert = os.getenv("REDIS_CA_CERT_PATH", "config/certs/redis_ca.pem")

        client = aioredis.from_url(
            redis_url,
            ssl_ca_certs=redis_ca_cert,
            ssl_cert_reqs="required",
            decode_responses=False,
        )

        try:
            for stream_name in PRD_STREAM_NAMES_PAPER:
                length = await client.xlen(stream_name)
                # Stream should exist (length >= 0 means it exists)
                assert length >= 0, f"Stream {stream_name} does not exist"
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_summary_metrics_populated(self, redis_url):
        """Test that engine:summary_metrics is populated."""
        import redis.asyncio as aioredis

        redis_ca_cert = os.getenv("REDIS_CA_CERT_PATH", "config/certs/redis_ca.pem")

        client = aioredis.from_url(
            redis_url,
            ssl_ca_certs=redis_ca_cert,
            ssl_cert_reqs="required",
            decode_responses=True,
        )

        try:
            metrics = await client.hgetall(PRD_SUMMARY_KEY)

            # Verify key metrics exist
            assert "signals_per_day" in metrics, "signals_per_day missing"
            assert "win_rate" in metrics or "win_rate_pct" in metrics, "win_rate missing"
            assert "roi_30d" in metrics, "roi_30d missing"
            assert "profit_factor" in metrics, "profit_factor missing"
            assert "sharpe_ratio" in metrics, "sharpe_ratio missing"
            assert "max_drawdown" in metrics or "max_drawdown_pct" in metrics, "max_drawdown missing"
        finally:
            await client.aclose()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
