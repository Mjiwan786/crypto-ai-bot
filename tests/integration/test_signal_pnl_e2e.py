"""
E2E Integration Test: Signal Generation → Trade Execution → PnL Attribution

This test simulates the complete flow:
1. Generate a PRD-compliant signal
2. Simulate trade execution (entry → exit)
3. Create PRDTradeRecord with signal attribution
4. Publish to Redis streams
5. Verify PnL streams are populated

Run: pytest tests/integration/test_signal_pnl_e2e.py -v -m redis
"""

import asyncio
import os
from datetime import datetime, timezone, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
import redis.asyncio as redis

from dotenv import load_dotenv
load_dotenv(".env.paper")

from agents.infrastructure.prd_publisher import (
    PRDPublisher,
    PRDSignal,
    Side,
    Strategy,
    Regime,
    PRDIndicators,
    PRDMetadata,
    MACDSignal,
)
from agents.infrastructure.prd_pnl import (
    PRDPnLPublisher,
    PRDTradeRecord,
    TradeOutcome,
    ExitReason,
    create_trade_record,
    PerformanceAggregator,
)


# =============================================================================
# SKIP CONDITION
# =============================================================================

def redis_available() -> bool:
    """Check if Redis is available for integration tests."""
    return bool(os.getenv("REDIS_URL"))


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
async def signal_publisher(redis_url, redis_ca_cert):
    """Create and connect a PRDPublisher for signals."""
    pub = PRDPublisher(
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
async def pnl_publisher(redis_url, redis_ca_cert):
    """Create and connect a PRDPnLPublisher for trades."""
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


# =============================================================================
# E2E TESTS - SIGNAL → TRADE → PNL FLOW
# =============================================================================

@pytest.mark.redis
@pytest.mark.asyncio
@skip_no_redis
class TestSignalPnLE2E:
    """E2E tests for complete signal → PnL flow."""

    async def test_signal_to_trade_attribution(
        self,
        signal_publisher,
        pnl_publisher,
        redis_client
    ):
        """Test complete flow: signal → trade → PnL with attribution."""
        # Step 1: Generate and publish a signal
        signal_id = str(uuid4())
        signal = PRDSignal(
            signal_id=signal_id,
            pair="BTC/USD",
            side=Side.LONG,
            strategy=Strategy.SCALPER,
            regime=Regime.TRENDING_UP,
            entry_price=50000.0,
            take_profit=50500.0,
            stop_loss=49500.0,
            confidence=0.75,
            position_size_usd=500.0,
            indicators=PRDIndicators(
                rsi_14=65.0,
                macd_signal=MACDSignal.BULLISH,
                atr_14=425.0,
                volume_ratio=1.2
            ),
            metadata=PRDMetadata(
                model_version="v2.1.0",
                backtest_sharpe=1.85,
                latency_ms=127
            )
        )

        signal_entry_id = await signal_publisher.publish_signal(signal)
        assert signal_entry_id is not None

        # Verify signal in Redis
        signal_stream = f"signals:paper:{signal.pair}"
        signal_result = await redis_client.xrevrange(signal_stream, count=1)
        assert len(signal_result) > 0

        # Step 2: Simulate trade execution (entry → exit)
        entry_time = datetime.now(timezone.utc) - timedelta(minutes=5)
        exit_time = datetime.now(timezone.utc)
        entry_price = 50000.0
        exit_price = 50400.0  # Partial profit
        quantity = 0.01  # 0.01 BTC
        fees_usd = 0.25
        slippage_pct = 0.01

        # Step 3: Create trade record with signal attribution
        trade = create_trade_record(
            signal_id=signal_id,  # Link to signal
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            entry_price=entry_price,
            exit_price=exit_price,
            position_size_usd=500.0,
            quantity=quantity,
            timestamp_open=entry_time.isoformat(),
            exit_reason=ExitReason.TAKE_PROFIT,
            fees_usd=fees_usd,
            slippage_pct=slippage_pct,
            regime_at_entry="TRENDING_UP",
            confidence_at_entry=0.75,
        )

        # Step 4: Publish trade to PnL stream
        trade_entry_id = await pnl_publisher.publish_trade(trade)
        assert trade_entry_id is not None

        # Step 5: Verify trade in Redis
        pnl_stream = "pnl:paper:signals"
        pnl_result = await redis_client.xrevrange(pnl_stream, count=1)
        assert len(pnl_result) > 0

        _, pnl_fields = pnl_result[0]
        assert pnl_fields[b"signal_id"].decode() == signal_id
        assert pnl_fields[b"pair"].decode() == "BTC/USD"
        assert pnl_fields[b"outcome"].decode() == "WIN"

        # Step 6: Verify PnL calculation
        realized_pnl = float(pnl_fields[b"realized_pnl"].decode())
        # Expected: (50400 - 50000) * 0.01 - 0.25 - (500 * 0.01 / 100) = 4.0 - 0.25 - 0.05 = 3.7
        assert realized_pnl > 0
        assert realized_pnl == pytest.approx(3.7, abs=0.5)

    async def test_multiple_signals_to_trades(
        self,
        signal_publisher,
        pnl_publisher,
        redis_client
    ):
        """Test multiple signals generating multiple trades."""
        signals = []
        trades = []

        # Generate 3 signals
        for i in range(3):
            signal_id = str(uuid4())
            signal = PRDSignal(
                signal_id=signal_id,
                pair="BTC/USD" if i % 2 == 0 else "ETH/USD",
                side=Side.LONG if i % 2 == 0 else Side.SHORT,
                strategy=Strategy.SCALPER if i < 2 else Strategy.TREND,
                regime=Regime.TRENDING_UP,
                entry_price=50000.0 if i % 2 == 0 else 3000.0,
                take_profit=50500.0 if i % 2 == 0 else 2950.0,
                stop_loss=49500.0 if i % 2 == 0 else 3050.0,
                confidence=0.7 + (i * 0.05),
                position_size_usd=100.0 * (i + 1),
            )
            signals.append((signal_id, signal))

            # Publish signal
            await signal_publisher.publish_signal(signal)

            # Simulate trade
            entry_time = datetime.now(timezone.utc) - timedelta(minutes=10 - i)
            exit_price = 50100.0 if i % 2 == 0 else 2980.0
            
            trade = create_trade_record(
                signal_id=signal_id,
                pair=signal.pair,
                side=signal.side.value,
                strategy=signal.strategy.value,
                entry_price=signal.entry_price,
                exit_price=exit_price,
                position_size_usd=signal.position_size_usd,
                quantity=0.002,
                timestamp_open=entry_time.isoformat(),
                exit_reason=ExitReason.TAKE_PROFIT if i % 2 == 0 else ExitReason.STOP_LOSS,
            )
            trades.append(trade)

            # Publish trade
            await pnl_publisher.publish_trade(trade)

        # Verify all trades in Redis
        pnl_stream = "pnl:paper:signals"
        pnl_result = await redis_client.xrevrange(pnl_stream, count=3)
        assert len(pnl_result) >= 3

        # Verify signal attribution
        signal_ids_in_redis = set()
        for _, fields in pnl_result[:3]:
            signal_id = fields[b"signal_id"].decode()
            signal_ids_in_redis.add(signal_id)

        expected_signal_ids = {sid for sid, _ in signals}
        assert signal_ids_in_redis == expected_signal_ids

    async def test_performance_aggregator_with_trades(
        self,
        pnl_publisher,
        redis_client
    ):
        """Test PerformanceAggregator computes metrics from trades."""
        aggregator = PerformanceAggregator(initial_equity=10000.0, mode="paper")

        # Add 10 trades with known outcomes
        for i in range(10):
            signal_id = str(uuid4())
            entry_price = 50000.0
            exit_price = 50100.0 if i % 3 != 0 else 49900.0  # 7 wins, 3 losses
            
            trade = create_trade_record(
                signal_id=signal_id,
                pair="BTC/USD",
                side="LONG",
                strategy="SCALPER" if i < 5 else "TREND",
                entry_price=entry_price,
                exit_price=exit_price,
                position_size_usd=100.0,
                quantity=0.002,
                timestamp_open=(datetime.now(timezone.utc) - timedelta(hours=i)).isoformat(),
                exit_reason=ExitReason.TAKE_PROFIT if i % 3 != 0 else ExitReason.STOP_LOSS,
            )
            aggregator.add_trade(trade)

        # Get metrics
        metrics = aggregator.get_metrics()

        # Verify metrics
        assert metrics.total_trades == 10
        assert metrics.winning_trades == 7
        assert metrics.losing_trades == 3
        assert metrics.win_rate_pct == pytest.approx(70.0, abs=5.0)
        assert metrics.total_pnl > 0
        assert "SCALPER" in metrics.strategy_performance
        assert "TREND" in metrics.strategy_performance

        # Publish metrics
        perf_entry_id = await pnl_publisher.publish_performance(metrics)
        assert perf_entry_id is not None

        # Verify in Redis
        perf_stream = "pnl:paper:performance"
        perf_result = await redis_client.xrevrange(perf_stream, count=1)
        assert len(perf_result) > 0

        _, perf_fields = perf_result[0]
        total_trades = int(perf_fields[b"total_trades"].decode())
        assert total_trades == 10

    async def test_signal_trade_pnl_consistency(
        self,
        signal_publisher,
        pnl_publisher,
        redis_client
    ):
        """Test signal and trade data consistency."""
        signal_id = str(uuid4())
        
        # Create signal
        signal = PRDSignal(
            signal_id=signal_id,
            pair="BTC/USD",
            side=Side.LONG,
            strategy=Strategy.SCALPER,
            regime=Regime.TRENDING_UP,
            entry_price=50000.0,
            take_profit=50500.0,
            stop_loss=49500.0,
            confidence=0.8,
            position_size_usd=1000.0,
        )
        await signal_publisher.publish_signal(signal)

        # Create trade with same signal_id
        trade = create_trade_record(
            signal_id=signal_id,
            pair=signal.pair,
            side=signal.side.value,
            strategy=signal.strategy.value,
            entry_price=signal.entry_price,
            exit_price=50400.0,
            position_size_usd=signal.position_size_usd,
            quantity=0.02,
            timestamp_open=datetime.now(timezone.utc).isoformat(),
            exit_reason=ExitReason.TAKE_PROFIT,
            confidence_at_entry=signal.confidence,
            regime_at_entry=signal.regime.value,
        )
        await pnl_publisher.publish_trade(trade)

        # Verify consistency
        pnl_stream = "pnl:paper:signals"
        pnl_result = await redis_client.xrevrange(pnl_stream, count=1)
        _, pnl_fields = pnl_result[0]

        assert pnl_fields[b"signal_id"].decode() == signal_id
        assert pnl_fields[b"pair"].decode() == signal.pair
        assert pnl_fields[b"strategy"].decode() == signal.strategy.value
        assert float(pnl_fields[b"entry_price"].decode()) == signal.entry_price
        assert float(pnl_fields[b"confidence_at_entry"].decode()) == signal.confidence


# =============================================================================
# SELF-CHECK
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "redis"])









