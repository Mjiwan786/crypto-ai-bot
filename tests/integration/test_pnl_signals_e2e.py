"""
E2E Integration Tests for PRD-001 PnL Signals Stream

Tests the complete flow from trade record creation to Redis publishing
and verification. Requires live Redis connection.

Run: pytest tests/integration/test_pnl_signals_e2e.py -v -m redis
"""

import asyncio
import os
from datetime import datetime, timezone

import pytest
import pytest_asyncio
import redis.asyncio as redis

# Load environment variables from .env.paper
from dotenv import load_dotenv
load_dotenv(".env.paper")

from agents.infrastructure.prd_pnl import (
    PRDTradeRecord,
    PRDPerformanceMetrics,
    PerformanceAggregator,
    PRDPnLPublisher,
    TradeOutcome,
    ExitReason,
    create_trade_record,
)


# =============================================================================
# SKIP CONDITION
# =============================================================================

def redis_available() -> bool:
    """Check if Redis is available for integration tests."""
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        return False
    return True


skip_no_redis = pytest.mark.skipif(
    not redis_available(),
    reason="REDIS_URL not set - skipping Redis integration tests"
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def redis_url():
    """Get Redis URL from environment."""
    return os.getenv("REDIS_URL")


@pytest.fixture
def redis_ca_cert():
    """Get Redis CA cert path from environment."""
    return os.getenv(
        "REDIS_CA_CERT",
        os.getenv("REDIS_CA_CERT_PATH", "config/certs/redis_ca.pem")
    )


@pytest_asyncio.fixture
async def publisher(redis_url, redis_ca_cert):
    """Create and connect a PRDPnLPublisher."""
    pub = PRDPnLPublisher(
        redis_url=redis_url,
        redis_ca_cert=redis_ca_cert,
        mode="paper"
    )
    connected = await pub.connect()
    if not connected:
        pytest.skip("Could not connect to Redis")
    yield pub
    await pub.close()


@pytest_asyncio.fixture
async def redis_client(redis_url, redis_ca_cert):
    """Create a raw Redis client for verification."""
    conn_params = {
        "socket_connect_timeout": 10,
        "decode_responses": False,
    }

    if redis_url.startswith("rediss://"):
        if redis_ca_cert and os.path.exists(redis_ca_cert):
            conn_params["ssl_ca_certs"] = redis_ca_cert
            conn_params["ssl_cert_reqs"] = "required"

    client = redis.from_url(redis_url, **conn_params)
    try:
        await client.ping()
    except Exception as e:
        pytest.skip(f"Could not connect to Redis: {e}")

    yield client
    await client.aclose()


@pytest.fixture
def sample_trade():
    """Create a sample trade record for testing."""
    return create_trade_record(
        signal_id="e2e-test-signal-001",
        pair="BTC/USD",
        side="LONG",
        strategy="SCALPER",
        entry_price=50000.0,
        exit_price=50500.0,
        position_size_usd=500.0,
        quantity=0.01,
        timestamp_open=datetime.now(timezone.utc).isoformat(),
        exit_reason=ExitReason.TAKE_PROFIT,
        fees_usd=0.25,
        slippage_pct=0.01,
    )


# =============================================================================
# E2E TESTS - TRADE RECORDS
# =============================================================================

@pytest.mark.redis
@pytest.mark.asyncio
@skip_no_redis
class TestPnLSignalsE2E:
    """E2E tests for pnl:signals stream."""

    async def test_publish_trade_to_redis(self, publisher, redis_client, sample_trade):
        """Test publishing a trade record to Redis."""
        # Publish trade
        entry_id = await publisher.publish_trade(sample_trade)

        assert entry_id is not None
        assert len(entry_id) > 0

        # Verify in Redis
        stream_key = "pnl:paper:signals"
        result = await redis_client.xrevrange(stream_key, count=1)

        assert len(result) > 0
        entry_id_from_redis, fields = result[0]

        # Verify key fields
        assert b"trade_id" in fields
        assert b"signal_id" in fields
        assert b"pair" in fields
        assert b"realized_pnl" in fields

        # Verify values
        assert fields[b"signal_id"].decode() == "e2e-test-signal-001"
        assert fields[b"pair"].decode() == "BTC/USD"

    async def test_publish_multiple_trades(self, publisher, redis_client):
        """Test publishing multiple trades."""
        trades = []
        for i in range(5):
            trade = create_trade_record(
                signal_id=f"e2e-multi-{i}",
                pair="ETH/USD" if i % 2 == 0 else "BTC/USD",
                side="LONG" if i % 2 == 0 else "SHORT",
                strategy="SCALPER",
                entry_price=3000.0,
                exit_price=3050.0 if i % 3 != 0 else 2950.0,
                position_size_usd=100.0,
                quantity=0.033,
                timestamp_open=datetime.now(timezone.utc).isoformat(),
                exit_reason=ExitReason.TAKE_PROFIT if i % 3 != 0 else ExitReason.STOP_LOSS,
            )
            trades.append(trade)

        # Publish all trades
        entry_ids = []
        for trade in trades:
            entry_id = await publisher.publish_trade(trade)
            assert entry_id is not None
            entry_ids.append(entry_id)

        # Verify count
        assert len(entry_ids) == 5

        # Verify in Redis
        stream_key = "pnl:paper:signals"
        result = await redis_client.xrevrange(stream_key, count=5)
        assert len(result) >= 5

    async def test_trade_fields_complete(self, publisher, redis_client, sample_trade):
        """Test all required fields are present in Redis."""
        await publisher.publish_trade(sample_trade)

        stream_key = "pnl:paper:signals"
        result = await redis_client.xrevrange(stream_key, count=1)
        _, fields = result[0]

        required_fields = [
            b"trade_id",
            b"signal_id",
            b"timestamp_open",
            b"timestamp_close",
            b"pair",
            b"side",
            b"strategy",
            b"entry_price",
            b"exit_price",
            b"position_size_usd",
            b"quantity",
            b"gross_pnl",
            b"realized_pnl",
            b"exit_reason",
            b"outcome",
            b"hold_duration_sec",
        ]

        for field in required_fields:
            assert field in fields, f"Missing required field: {field.decode()}"

    async def test_pnl_values_correct(self, publisher, redis_client):
        """Test PnL values are calculated correctly."""
        # Create a trade with known values
        trade = create_trade_record(
            signal_id="pnl-value-test",
            pair="BTC/USD",
            side="LONG",
            strategy="TREND",
            entry_price=50000.0,
            exit_price=51000.0,  # +$1000/BTC
            position_size_usd=1000.0,
            quantity=0.02,  # 0.02 BTC
            timestamp_open=datetime.now(timezone.utc).isoformat(),
            exit_reason=ExitReason.TAKE_PROFIT,
        )
        # Expected PnL: 0.02 * $1000 = $20

        await publisher.publish_trade(trade)

        stream_key = "pnl:paper:signals"
        result = await redis_client.xrevrange(stream_key, count=1)
        _, fields = result[0]

        gross_pnl = float(fields[b"gross_pnl"].decode())
        realized_pnl = float(fields[b"realized_pnl"].decode())

        assert abs(gross_pnl - 20.0) < 0.1
        assert abs(realized_pnl - 20.0) < 0.1

    async def test_win_loss_outcome(self, publisher, redis_client):
        """Test WIN and LOSS outcomes are set correctly."""
        # Create a winning trade
        win_trade = create_trade_record(
            signal_id="win-outcome-test",
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            entry_price=50000.0,
            exit_price=50500.0,
            position_size_usd=500.0,
            quantity=0.01,
            timestamp_open=datetime.now(timezone.utc).isoformat(),
            exit_reason=ExitReason.TAKE_PROFIT,
        )

        await publisher.publish_trade(win_trade)

        stream_key = "pnl:paper:signals"
        result = await redis_client.xrevrange(stream_key, count=1)
        _, fields = result[0]

        assert fields[b"outcome"].decode() == "WIN"

        # Create a losing trade
        loss_trade = create_trade_record(
            signal_id="loss-outcome-test",
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            entry_price=50000.0,
            exit_price=49500.0,
            position_size_usd=500.0,
            quantity=0.01,
            timestamp_open=datetime.now(timezone.utc).isoformat(),
            exit_reason=ExitReason.STOP_LOSS,
        )

        await publisher.publish_trade(loss_trade)

        result = await redis_client.xrevrange(stream_key, count=1)
        _, fields = result[0]

        assert fields[b"outcome"].decode() == "LOSS"


# =============================================================================
# E2E TESTS - PERFORMANCE METRICS
# =============================================================================

@pytest.mark.redis
@pytest.mark.asyncio
@skip_no_redis
class TestPerformanceMetricsE2E:
    """E2E tests for pnl:performance stream."""

    async def test_publish_performance_metrics(self, publisher, redis_client):
        """Test publishing performance metrics snapshot."""
        # Create aggregator with some trades
        agg = PerformanceAggregator(initial_equity=10000.0, mode="paper")

        for i in range(10):
            trade = create_trade_record(
                signal_id=f"perf-test-{i}",
                pair="BTC/USD",
                side="LONG",
                strategy="SCALPER" if i < 5 else "TREND",
                entry_price=50000.0,
                exit_price=50100.0 if i % 3 != 0 else 49900.0,
                position_size_usd=100.0,
                quantity=0.002,
                timestamp_open=datetime.now(timezone.utc).isoformat(),
                exit_reason=ExitReason.TAKE_PROFIT if i % 3 != 0 else ExitReason.STOP_LOSS,
            )
            agg.add_trade(trade)

        metrics = agg.get_metrics()

        # Publish
        entry_id = await publisher.publish_performance(metrics)
        assert entry_id is not None

        # Verify in stream
        stream_key = "pnl:paper:performance"
        result = await redis_client.xrevrange(stream_key, count=1)
        assert len(result) > 0

        _, fields = result[0]
        assert b"total_trades" in fields
        assert b"win_rate_pct" in fields
        assert b"profit_factor" in fields
        assert b"sharpe_ratio" in fields

        # Verify values
        total_trades = int(fields[b"total_trades"].decode())
        assert total_trades == 10

    async def test_performance_latest_key(self, publisher, redis_client):
        """Test performance latest key is updated."""
        agg = PerformanceAggregator(initial_equity=10000.0, mode="paper")

        # Add a trade
        trade = create_trade_record(
            signal_id="latest-test",
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            entry_price=50000.0,
            exit_price=50100.0,
            position_size_usd=100.0,
            quantity=0.002,
            timestamp_open=datetime.now(timezone.utc).isoformat(),
            exit_reason=ExitReason.TAKE_PROFIT,
        )
        agg.add_trade(trade)

        metrics = agg.get_metrics()
        await publisher.publish_performance(metrics)

        # Check latest key
        latest_key = "pnl:paper:performance:latest"
        latest_data = await redis_client.get(latest_key)

        assert latest_data is not None

        import json
        parsed = json.loads(latest_data.decode())

        assert "total_trades" in parsed
        assert "win_rate_pct" in parsed
        assert "strategy_performance" in parsed

    async def test_strategy_attribution_in_redis(self, publisher, redis_client):
        """Test per-strategy attribution is published."""
        agg = PerformanceAggregator(initial_equity=10000.0, mode="paper")

        strategies = ["SCALPER", "TREND", "MEAN_REVERSION", "BREAKOUT"]

        for strategy in strategies:
            trade = create_trade_record(
                signal_id=f"strat-{strategy}",
                pair="BTC/USD",
                side="LONG",
                strategy=strategy,
                entry_price=50000.0,
                exit_price=50100.0,
                position_size_usd=100.0,
                quantity=0.002,
                timestamp_open=datetime.now(timezone.utc).isoformat(),
                exit_reason=ExitReason.TAKE_PROFIT,
            )
            agg.add_trade(trade)

        metrics = agg.get_metrics()
        await publisher.publish_performance(metrics)

        # Check latest
        latest_key = "pnl:paper:performance:latest"
        latest_data = await redis_client.get(latest_key)

        import json
        parsed = json.loads(latest_data.decode())

        assert "strategy_performance" in parsed
        strat_perf = parsed["strategy_performance"]

        for strategy in strategies:
            assert strategy in strat_perf
            assert strat_perf[strategy]["trades"] == 1


# =============================================================================
# E2E TESTS - STREAM BEHAVIOR
# =============================================================================

@pytest.mark.redis
@pytest.mark.asyncio
@skip_no_redis
class TestStreamBehaviorE2E:
    """E2E tests for Redis stream behavior."""

    async def test_stream_maxlen_respected(self, publisher, redis_client):
        """Test MAXLEN is applied to stream."""
        stream_key = "pnl:paper:signals"

        # Get initial length
        initial_len = await redis_client.xlen(stream_key)

        # Publish 100 trades
        for i in range(100):
            trade = create_trade_record(
                signal_id=f"maxlen-test-{i}",
                pair="BTC/USD",
                side="LONG",
                strategy="SCALPER",
                entry_price=50000.0,
                exit_price=50050.0,
                position_size_usd=100.0,
                quantity=0.002,
                timestamp_open=datetime.now(timezone.utc).isoformat(),
                exit_reason=ExitReason.TAKE_PROFIT,
            )
            await publisher.publish_trade(trade)

        final_len = await redis_client.xlen(stream_key)

        # Stream should not exceed MAXLEN (10000) + initial
        assert final_len <= 10000 + initial_len

    async def test_stream_order_preserved(self, publisher, redis_client):
        """Test entries are in order."""
        stream_key = "pnl:paper:signals"

        # Publish 5 trades in sequence
        signal_ids = []
        for i in range(5):
            sig_id = f"order-test-{i}"
            signal_ids.append(sig_id)

            trade = create_trade_record(
                signal_id=sig_id,
                pair="BTC/USD",
                side="LONG",
                strategy="SCALPER",
                entry_price=50000.0,
                exit_price=50050.0,
                position_size_usd=100.0,
                quantity=0.002,
                timestamp_open=datetime.now(timezone.utc).isoformat(),
                exit_reason=ExitReason.TAKE_PROFIT,
            )
            await publisher.publish_trade(trade)
            await asyncio.sleep(0.01)  # Small delay for ordering

        # Read back in reverse order (xrevrange)
        result = await redis_client.xrevrange(stream_key, count=5)

        # Most recent should be last signal_id
        _, latest_fields = result[0]
        assert latest_fields[b"signal_id"].decode() == signal_ids[-1]

    async def test_reconnect_after_publish(self, redis_url, redis_ca_cert):
        """Test publisher can reconnect and continue."""
        pub = PRDPnLPublisher(
            redis_url=redis_url,
            redis_ca_cert=redis_ca_cert,
            mode="paper"
        )

        connected = await pub.connect()
        if not connected:
            pytest.skip("Could not connect to Redis")

        # Publish a trade
        trade1 = create_trade_record(
            signal_id="reconnect-1",
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            entry_price=50000.0,
            exit_price=50050.0,
            position_size_usd=100.0,
            quantity=0.002,
            timestamp_open=datetime.now(timezone.utc).isoformat(),
            exit_reason=ExitReason.TAKE_PROFIT,
        )
        entry1 = await pub.publish_trade(trade1)
        assert entry1 is not None

        # Close connection
        await pub.close()

        # Reconnect
        connected = await pub.connect()
        assert connected

        # Publish another trade
        trade2 = create_trade_record(
            signal_id="reconnect-2",
            pair="ETH/USD",
            side="SHORT",
            strategy="TREND",
            entry_price=3000.0,
            exit_price=2950.0,
            position_size_usd=100.0,
            quantity=0.033,
            timestamp_open=datetime.now(timezone.utc).isoformat(),
            exit_reason=ExitReason.TAKE_PROFIT,
        )
        entry2 = await pub.publish_trade(trade2)
        assert entry2 is not None

        await pub.close()


# =============================================================================
# SELF-CHECK
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "redis"])
