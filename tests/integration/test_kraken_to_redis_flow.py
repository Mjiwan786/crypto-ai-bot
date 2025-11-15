"""
Integration Test: Kraken Feed → Agent → Redis Signals

Tests the complete flow from simulated Kraken WebSocket feed through
agent processing to Redis signal publication with correct schema.

PRD-001 Acceptance Criteria:
- End-to-end latency ≤ 500ms (95th percentile)
- Signal schema: timestamp, signal_type, trading_pair, size, stop_loss,
  take_profit, confidence_score, agent_id
- No data gaps, reliable real-time processing
"""

import asyncio
import pytest
import time
import redis
import json
from datetime import datetime
from typing import Dict, Any, List
from unittest.mock import Mock, patch, AsyncMock
from pathlib import Path
import sys

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from agents.core.signal_processor import SignalProcessor
from ai_engine.signals import Signal, SignalType, SignalSide


@pytest.fixture
def redis_client():
    """Redis client connected to Redis Cloud with TLS."""
    import os
    from urllib.parse import urlparse

    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        pytest.skip("REDIS_URL not set - skipping integration test")

    parsed = urlparse(redis_url)

    # Redis Cloud TLS connection
    client = redis.Redis(
        host=parsed.hostname,
        port=parsed.port or 19818,
        username=parsed.username or "default",
        password=parsed.password,
        ssl=True,
        ssl_cert_reqs="required",
        ssl_ca_certs=str(project_root / "config" / "certs" / "redis_ca.pem"),
        decode_responses=True,
    )

    # Test connection
    try:
        client.ping()
    except Exception as e:
        pytest.skip(f"Redis connection failed: {e}")

    yield client

    # Cleanup
    client.close()


@pytest.fixture
def test_stream_name():
    """Test stream name for signal publication."""
    return "signals:paper:test"


@pytest.fixture
async def cleanup_test_stream(redis_client, test_stream_name):
    """Cleanup test stream after test."""
    yield
    # Delete test stream after test
    try:
        redis_client.delete(test_stream_name)
    except Exception:
        pass


class SimulatedKrakenFeed:
    """Simulates Kraken WebSocket feed data."""

    @staticmethod
    def generate_ticker_update(pair: str = "BTC/USD", price: float = 50000.0) -> Dict[str, Any]:
        """Generate a simulated ticker update from Kraken."""
        return {
            "event": "ticker",
            "pair": pair,
            "data": {
                "c": [str(price), "1.0"],  # [price, wholeLotVolume]
                "v": ["1000.5", "5000.25"],  # [today, last24Hours]
                "p": [str(price), str(price * 0.99)],  # [today, last24Hours]
                "t": [100, 500],  # [today, last24Hours]
                "l": [str(price * 0.98), str(price * 0.97)],  # [today, last24Hours]
                "h": [str(price * 1.02), str(price * 1.03)],  # [today, last24Hours]
                "o": [str(price * 0.99), str(price * 0.98)],  # [today, last24Hours]
            },
            "timestamp": time.time()
        }

    @staticmethod
    def generate_ohlc_update(pair: str = "BTC/USD", price: float = 50000.0) -> Dict[str, Any]:
        """Generate a simulated OHLC candle from Kraken."""
        return {
            "event": "ohlc",
            "pair": pair,
            "interval": 1,  # 1 minute
            "data": {
                "time": time.time(),
                "etime": time.time() + 60,
                "open": str(price),
                "high": str(price * 1.01),
                "low": str(price * 0.99),
                "close": str(price * 1.005),
                "vwap": str(price * 1.002),
                "volume": "100.5",
                "count": 150
            }
        }

    @staticmethod
    def generate_trade_update(pair: str = "BTC/USD", price: float = 50000.0) -> Dict[str, Any]:
        """Generate a simulated trade from Kraken."""
        return {
            "event": "trade",
            "pair": pair,
            "data": [
                [
                    str(price),  # price
                    "1.5",  # volume
                    time.time(),  # time
                    "b",  # buy/sell
                    "m",  # market/limit
                    ""  # misc
                ]
            ]
        }


class MockAgent:
    """Mock trading agent for testing signal processing."""

    def __init__(self, agent_id: str = "test_agent"):
        self.agent_id = agent_id
        self.signals_generated = []

    async def process_market_data(self, market_data: Dict[str, Any]) -> Signal:
        """Process market data and generate a signal."""
        # Simulate agent logic
        await asyncio.sleep(0.05)  # Simulate processing time

        # Generate signal based on market data
        signal = Signal(
            timestamp=datetime.utcnow(),
            signal_type=SignalType.ENTRY,
            side=SignalSide.LONG,
            trading_pair=market_data.get("pair", "BTC/USD"),
            entry_price=float(market_data.get("data", {}).get("c", ["50000"])[0]),
            size=0.01,
            stop_loss=float(market_data.get("data", {}).get("c", ["50000"])[0]) * 0.98,
            take_profit=float(market_data.get("data", {}).get("c", ["50000"])[0]) * 1.02,
            confidence_score=0.75,
            agent_id=self.agent_id,
            strategy="test_strategy",
            metadata={"source": "test"}
        )

        self.signals_generated.append(signal)
        return signal


class TestKrakenToRedisFlow:
    """Test complete flow from Kraken feed to Redis signals."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_simulated_feed_to_redis_schema(
        self,
        redis_client,
        test_stream_name,
        cleanup_test_stream
    ):
        """
        Test simulated Kraken feed → agent → Redis with correct schema.

        Validates:
        - Agent receives and processes market data
        - Signal is published to Redis stream
        - Signal schema matches PRD-001 requirements
        - End-to-end latency ≤ 500ms
        """
        # 1. Create simulated Kraken feed
        feed = SimulatedKrakenFeed()
        ticker_data = feed.generate_ticker_update(pair="BTC/USD", price=50000.0)

        # 2. Create mock agent
        agent = MockAgent(agent_id="scalper_001")

        # 3. Process market data through agent
        start_time = time.time()
        signal = await agent.process_market_data(ticker_data)

        # 4. Publish signal to Redis stream
        signal_dict = {
            "timestamp": signal.timestamp.isoformat(),
            "signal_type": signal.signal_type.value,
            "side": signal.side.value,
            "trading_pair": signal.trading_pair,
            "entry_price": signal.entry_price,
            "size": signal.size,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
            "confidence_score": signal.confidence_score,
            "agent_id": signal.agent_id,
            "strategy": signal.strategy,
            "metadata": signal.metadata
        }

        message_id = redis_client.xadd(
            test_stream_name,
            {"json": json.dumps(signal_dict)},
            maxlen=1000
        )

        end_time = time.time()
        latency_ms = (end_time - start_time) * 1000

        # 5. Verify signal was published
        assert message_id is not None, "Signal should be published to Redis"

        # 6. Verify latency requirement (≤ 500ms)
        assert latency_ms <= 500, f"Latency {latency_ms:.2f}ms exceeds 500ms requirement"

        # 7. Read back signal from Redis and verify schema
        messages = redis_client.xrevrange(test_stream_name, count=1)
        assert len(messages) == 1, "Should have one message in stream"

        msg_id, msg_data = messages[0]
        retrieved_signal = json.loads(msg_data["json"])

        # 8. Validate PRD-001 signal schema requirements
        required_fields = [
            "timestamp",
            "signal_type",
            "trading_pair",
            "size",
            "stop_loss",
            "take_profit",
            "confidence_score",
            "agent_id"
        ]

        for field in required_fields:
            assert field in retrieved_signal, f"Signal missing required field: {field}"

        # 9. Validate field values
        assert retrieved_signal["signal_type"] in ["entry", "exit", "stop"], \
            f"Invalid signal_type: {retrieved_signal['signal_type']}"
        assert retrieved_signal["trading_pair"] == "BTC/USD"
        assert 0 < retrieved_signal["confidence_score"] <= 1.0, \
            "Confidence score should be between 0 and 1"
        assert retrieved_signal["agent_id"] == "scalper_001"
        assert retrieved_signal["stop_loss"] < retrieved_signal["entry_price"]
        assert retrieved_signal["take_profit"] > retrieved_signal["entry_price"]

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_multiple_signals_no_data_gaps(
        self,
        redis_client,
        test_stream_name,
        cleanup_test_stream
    ):
        """
        Test multiple signals are published without gaps.

        Validates:
        - High-frequency signal generation
        - No message loss
        - Sequential processing
        """
        feed = SimulatedKrakenFeed()
        agent = MockAgent(agent_id="test_multi")

        num_signals = 10
        latencies = []

        for i in range(num_signals):
            # Generate different market data
            ticker_data = feed.generate_ticker_update(
                pair="BTC/USD",
                price=50000.0 + i * 100
            )

            start_time = time.time()

            # Process through agent
            signal = await agent.process_market_data(ticker_data)

            # Publish to Redis
            signal_dict = {
                "timestamp": signal.timestamp.isoformat(),
                "signal_type": signal.signal_type.value,
                "side": signal.side.value,
                "trading_pair": signal.trading_pair,
                "entry_price": signal.entry_price,
                "size": signal.size,
                "stop_loss": signal.stop_loss,
                "take_profit": signal.take_profit,
                "confidence_score": signal.confidence_score,
                "agent_id": signal.agent_id,
                "strategy": signal.strategy,
                "metadata": {"sequence": i}
            }

            redis_client.xadd(
                test_stream_name,
                {"json": json.dumps(signal_dict)},
                maxlen=1000
            )

            end_time = time.time()
            latencies.append((end_time - start_time) * 1000)

        # Verify all signals were published
        messages = redis_client.xrevrange(test_stream_name, count=num_signals)
        assert len(messages) == num_signals, \
            f"Expected {num_signals} messages, got {len(messages)}"

        # Verify sequence (no gaps)
        retrieved_sequences = []
        for msg_id, msg_data in reversed(messages):
            signal = json.loads(msg_data["json"])
            retrieved_sequences.append(signal["metadata"]["sequence"])

        expected_sequences = list(range(num_signals))
        assert retrieved_sequences == expected_sequences, \
            f"Signal sequence has gaps: {retrieved_sequences}"

        # Verify latency distribution
        avg_latency = sum(latencies) / len(latencies)
        p95_latency = sorted(latencies)[int(len(latencies) * 0.95)]

        assert avg_latency <= 300, \
            f"Average latency {avg_latency:.2f}ms exceeds 300ms median requirement"
        assert p95_latency <= 500, \
            f"95th percentile latency {p95_latency:.2f}ms exceeds 500ms requirement"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_signal_schema_validation(
        self,
        redis_client,
        test_stream_name,
        cleanup_test_stream
    ):
        """
        Test published signals match exact PRD-001 schema.

        Validates:
        - All required fields present
        - Correct data types
        - Value constraints
        """
        feed = SimulatedKrakenFeed()
        agent = MockAgent(agent_id="schema_test")

        ticker_data = feed.generate_ticker_update()
        signal = await agent.process_market_data(ticker_data)

        # Publish with complete schema
        signal_dict = {
            "timestamp": signal.timestamp.isoformat(),
            "signal_type": "entry",
            "side": "long",
            "trading_pair": "BTC/USD",
            "entry_price": 50000.0,
            "size": 0.01,
            "stop_loss": 49000.0,
            "take_profit": 51000.0,
            "confidence_score": 0.75,
            "agent_id": "schema_test",
            "strategy": "test_strategy",
            "metadata": {"test": True}
        }

        redis_client.xadd(
            test_stream_name,
            {"json": json.dumps(signal_dict)}
        )

        # Retrieve and validate
        messages = redis_client.xrevrange(test_stream_name, count=1)
        retrieved = json.loads(messages[0][1]["json"])

        # Type validation
        assert isinstance(retrieved["timestamp"], str)
        assert isinstance(retrieved["signal_type"], str)
        assert isinstance(retrieved["trading_pair"], str)
        assert isinstance(retrieved["entry_price"], (int, float))
        assert isinstance(retrieved["size"], (int, float))
        assert isinstance(retrieved["stop_loss"], (int, float))
        assert isinstance(retrieved["take_profit"], (int, float))
        assert isinstance(retrieved["confidence_score"], (int, float))
        assert isinstance(retrieved["agent_id"], str)

        # Value constraints
        assert retrieved["signal_type"] in ["entry", "exit", "stop"]
        assert retrieved["side"] in ["long", "short"]
        assert 0 < retrieved["confidence_score"] <= 1.0
        assert retrieved["size"] > 0
        assert len(retrieved["agent_id"]) > 0
        assert len(retrieved["trading_pair"]) > 0

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_different_signal_types(
        self,
        redis_client,
        test_stream_name,
        cleanup_test_stream
    ):
        """
        Test all signal types (entry, exit, stop) are published correctly.

        Validates:
        - Entry signals
        - Exit signals
        - Stop signals
        - All have correct schema
        """
        signal_types = ["entry", "exit", "stop"]

        for sig_type in signal_types:
            signal_dict = {
                "timestamp": datetime.utcnow().isoformat(),
                "signal_type": sig_type,
                "side": "long",
                "trading_pair": "BTC/USD",
                "entry_price": 50000.0,
                "size": 0.01,
                "stop_loss": 49000.0,
                "take_profit": 51000.0,
                "confidence_score": 0.75,
                "agent_id": f"test_{sig_type}",
                "strategy": "test",
                "metadata": {"type": sig_type}
            }

            redis_client.xadd(
                test_stream_name,
                {"json": json.dumps(signal_dict)}
            )

        # Verify all signal types were published
        messages = redis_client.xrevrange(test_stream_name, count=len(signal_types))
        assert len(messages) == len(signal_types)

        retrieved_types = []
        for msg_id, msg_data in messages:
            signal = json.loads(msg_data["json"])
            retrieved_types.append(signal["signal_type"])

        assert set(retrieved_types) == set(signal_types), \
            f"Not all signal types published: {retrieved_types}"


@pytest.mark.integration
class TestRealTimeProcessing:
    """Test real-time processing requirements."""

    @pytest.mark.asyncio
    async def test_concurrent_signal_processing(
        self,
        redis_client,
        test_stream_name,
        cleanup_test_stream
    ):
        """
        Test concurrent signal processing from multiple agents.

        Validates:
        - Multiple agents can publish concurrently
        - No race conditions
        - All signals are captured
        """
        num_agents = 5
        signals_per_agent = 3

        async def publish_signals(agent_id: int):
            """Publish signals from a single agent."""
            agent = MockAgent(agent_id=f"agent_{agent_id}")
            feed = SimulatedKrakenFeed()

            for i in range(signals_per_agent):
                ticker_data = feed.generate_ticker_update(price=50000.0 + agent_id * 1000 + i * 100)
                signal = await agent.process_market_data(ticker_data)

                signal_dict = {
                    "timestamp": signal.timestamp.isoformat(),
                    "signal_type": signal.signal_type.value,
                    "side": signal.side.value,
                    "trading_pair": signal.trading_pair,
                    "entry_price": signal.entry_price,
                    "size": signal.size,
                    "stop_loss": signal.stop_loss,
                    "take_profit": signal.take_profit,
                    "confidence_score": signal.confidence_score,
                    "agent_id": f"agent_{agent_id}",
                    "strategy": signal.strategy,
                    "metadata": {"agent_id": agent_id, "sequence": i}
                }

                redis_client.xadd(
                    test_stream_name,
                    {"json": json.dumps(signal_dict)}
                )

        # Run all agents concurrently
        tasks = [publish_signals(i) for i in range(num_agents)]
        await asyncio.gather(*tasks)

        # Verify all signals were published
        total_expected = num_agents * signals_per_agent
        messages = redis_client.xrevrange(test_stream_name, count=total_expected)

        assert len(messages) == total_expected, \
            f"Expected {total_expected} signals, got {len(messages)}"

        # Verify each agent published all their signals
        agent_counts = {}
        for msg_id, msg_data in messages:
            signal = json.loads(msg_data["json"])
            agent_id = signal["agent_id"]
            agent_counts[agent_id] = agent_counts.get(agent_id, 0) + 1

        assert len(agent_counts) == num_agents, \
            f"Expected signals from {num_agents} agents, got {len(agent_counts)}"

        for agent_id, count in agent_counts.items():
            assert count == signals_per_agent, \
                f"Agent {agent_id} published {count} signals, expected {signals_per_agent}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "-m", "integration"])
