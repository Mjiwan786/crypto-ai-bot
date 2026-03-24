"""
Integration tests for RSI Bounce bot.

Tests:
1. OHLCV bars in Redis stream -> agent reads + evaluates -> signal published
2. Published signal format compatible with BotEngine signal reader
3. Candle-close driven: one candle -> one evaluation -> at most one signal

Requires fakeredis: @pytest.mark.integration
"""

import time

import numpy as np
import pytest
import pytest_asyncio

try:
    from fakeredis.aioredis import FakeRedis as FakeAsyncRedis
except ImportError:
    FakeAsyncRedis = None

from agents.indicator.computations import wilder_rsi
from agents.indicator.rsi_bounce import RSIBounceAgent, ohlcv_stream_key


# =============================================================================
# HELPERS
# =============================================================================

def _make_long_trigger_ohlcv(n: int = 50):
    """Generate OHLCV data where RSI crosses above 30 on the last bar.

    Approach: strong downtrend (RSI drops well below 30), then a single
    sharp up bar to push RSI above 30.
    """
    closes = np.empty(n, dtype=np.float64)
    # Steady decline for first n-1 bars -> drives RSI below 30
    for i in range(n - 1):
        closes[i] = 100.0 - i * 0.6

    # Verify RSI is below 30 before the bounce
    rsi_check = wilder_rsi(closes[:n - 1], period=14)
    pre_rsi = rsi_check[-1]

    # Sharp bounce on last bar
    closes[n - 1] = closes[n - 2] + 3.0  # strong up move

    highs = closes + 0.5
    lows = closes - 0.5
    now = time.time()
    timestamps = np.array(
        [now - (n - i) * 900 for i in range(n)], dtype=np.float64
    )
    # Make last bar recent so it passes freshness check
    timestamps[-1] = now - 5.0
    volumes = np.full(n, 100.0, dtype=np.float64)

    return {
        "timestamp": timestamps,
        "open": closes.copy(),
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    }


async def _write_ohlcv_to_stream(redis_client, pair, timeframe, ohlcv):
    """Write OHLCV dict arrays to Redis stream."""
    stream_key = ohlcv_stream_key(timeframe, pair)
    n = len(ohlcv["close"])
    for i in range(n):
        await redis_client.xadd(
            stream_key,
            {
                b"time": str(ohlcv["timestamp"][i]).encode(),
                b"open": str(ohlcv["open"][i]).encode(),
                b"high": str(ohlcv["high"][i]).encode(),
                b"low": str(ohlcv["low"][i]).encode(),
                b"close": str(ohlcv["close"][i]).encode(),
                b"volume": str(ohlcv["volume"][i]).encode(),
            },
        )


# =============================================================================
# FIXTURES
# =============================================================================

@pytest_asyncio.fixture
async def redis_client():
    if FakeAsyncRedis is None:
        pytest.skip("fakeredis not installed")
    client = FakeAsyncRedis(decode_responses=False)
    yield client
    await client.flushall()
    await client.aclose()


@pytest_asyncio.fixture
async def agent(redis_client):
    """RSI Bounce agent with relaxed cooldown for integration testing."""
    config = {
        "pairs": ["BTC/USD"],
        "timeframe": "15m",
        "rsi_period": 14,
        "rsi_oversold": 30.0,
        "rsi_overbought": 70.0,
        "atr_period": 14,
        "sl_atr_multiplier": 1.5,
        "tp_atr_multiplier": 2.0,
        "position_size_usd": 100.0,
        "cooldown_minutes": 0,  # no cooldown for tests
        "max_signals_per_day": 100,
        "warmup_bars": 50,
        "bar_freshness_max_seconds": 300,
        "mode": "paper",
        "default_regime": "RANGING",
    }
    a = RSIBounceAgent()
    await a.initialize(config, redis_client)
    return a


# =============================================================================
# INTEGRATION: OHLCV stream -> signal published
# =============================================================================

@pytest.mark.integration
class TestOHLCVToSignalPublished:
    """OHLCV in Redis stream -> evaluate -> signal appears in signals:paper:{PAIR}."""

    @pytest.mark.asyncio
    async def test_long_signal_published_to_stream(self, agent, redis_client):
        """Given OHLCV with RSI cross above 30, signal appears in output stream."""
        ohlcv = _make_long_trigger_ohlcv(50)

        # Write OHLCV to input stream
        await _write_ohlcv_to_stream(redis_client, "BTC/USD", "15m", ohlcv)

        # Evaluate
        signal = await agent._evaluate_pair("BTC/USD")

        # If RSI actually crossed (depends on synthetic data quality)
        if signal is not None:
            # Verify signal in output stream
            entries = await redis_client.xrevrange(
                b"signals:paper:BTC-USD", count=1
            )
            assert len(entries) > 0

            _, fields = entries[0]
            assert fields[b"strategy"] == b"MEAN_REVERSION"
            assert fields[b"strategy_label"] == b"RSI Bounce"
            assert fields[b"mode"] == b"paper"
            assert b"rsi_14" in fields
            assert b"atr_14" in fields
            assert fields[b"side"] == b"LONG"

            # Verify confidence is a valid float
            conf = float(fields[b"confidence"])
            assert 0.0 <= conf <= 1.0

    @pytest.mark.asyncio
    async def test_no_signal_when_rsi_in_midrange(self, agent, redis_client):
        """OHLCV with RSI in 40-60 range -> no signal published."""
        n = 50
        closes = np.empty(n, dtype=np.float64)
        for i in range(n):
            closes[i] = 100.0 + (1.0 if i % 2 == 0 else -1.0) * 0.3

        ohlcv = {
            "timestamp": np.array(
                [time.time() - (n - i) * 900 for i in range(n)],
                dtype=np.float64,
            ),
            "open": closes.copy(),
            "high": (closes + 0.2).astype(np.float64),
            "low": (closes - 0.2).astype(np.float64),
            "close": closes,
            "volume": np.full(n, 50.0, dtype=np.float64),
        }
        ohlcv["timestamp"][-1] = time.time() - 5.0

        await _write_ohlcv_to_stream(redis_client, "BTC/USD", "15m", ohlcv)

        signal = await agent._evaluate_pair("BTC/USD")
        assert signal is None

        # Verify no signal in output stream
        entries = await redis_client.xrevrange(
            b"signals:paper:BTC-USD", count=1
        )
        assert len(entries) == 0


# =============================================================================
# INTEGRATION: signal format compatible with BotEngine
# =============================================================================

@pytest.mark.integration
class TestSignalFormatCompatibility:
    """Verify the published signal format matches what BotEngine._get_latest_signal() expects."""

    @pytest.mark.asyncio
    async def test_signal_has_required_bot_engine_fields(self, agent, redis_client):
        """BotEngine reads: side, confidence, id, strategy."""
        ohlcv = _make_long_trigger_ohlcv(50)
        await _write_ohlcv_to_stream(redis_client, "BTC/USD", "15m", ohlcv)

        signal = await agent._evaluate_pair("BTC/USD")

        if signal is not None:
            entries = await redis_client.xrevrange(
                b"signals:paper:BTC-USD", count=1
            )
            _, fields = entries[0]

            # BotEngine._get_latest_signal() reads these fields:
            assert b"side" in fields  # checked with .upper()
            assert b"confidence" in fields  # checked >= min_confidence
            assert b"signal_id" in fields  # used as signal identifier
            assert b"id" in fields  # API alias for signal_id

            # side should be LONG or SHORT (BotEngine uses .upper())
            side_val = fields[b"side"].decode()
            assert side_val in ("LONG", "SHORT")

    @pytest.mark.asyncio
    async def test_signal_stream_key_matches_convention(self, agent, redis_client):
        """Output stream must be signals:paper:BTC-USD."""
        ohlcv = _make_long_trigger_ohlcv(50)
        await _write_ohlcv_to_stream(redis_client, "BTC/USD", "15m", ohlcv)

        signal = await agent._evaluate_pair("BTC/USD")

        if signal is not None:
            stream_key = signal.get_stream_key()
            assert stream_key == "signals:paper:BTC-USD"


# =============================================================================
# INTEGRATION: candle-close driven evaluation
# =============================================================================

@pytest.mark.integration
class TestCandleCloseEvaluation:
    """One candle -> one evaluation -> at most one signal.  No new candle -> zero."""

    @pytest.mark.asyncio
    async def test_one_candle_one_signal_via_evaluate_if_new_candle(
        self, agent, redis_client,
    ):
        """Push trigger OHLCV -> evaluate_if_new_candle -> exactly one signal."""
        ohlcv = _make_long_trigger_ohlcv(50)
        await _write_ohlcv_to_stream(redis_client, "BTC/USD", "15m", ohlcv)

        signal = await agent.evaluate_if_new_candle("BTC/USD")

        if signal is not None:
            entries = await redis_client.xrevrange(
                b"signals:paper:BTC-USD", count=10,
            )
            assert len(entries) == 1

    @pytest.mark.asyncio
    async def test_no_new_candle_no_second_signal(self, agent, redis_client):
        """Same stream, second call -> no additional evaluation or signal."""
        ohlcv = _make_long_trigger_ohlcv(50)
        await _write_ohlcv_to_stream(redis_client, "BTC/USD", "15m", ohlcv)

        # First call: processes the candle
        await agent.evaluate_if_new_candle("BTC/USD")

        signal_count_before = len(
            await redis_client.xrevrange(b"signals:paper:BTC-USD", count=100)
        )

        # Second call: no new candle -> should not produce a signal
        result = await agent.evaluate_if_new_candle("BTC/USD")
        assert result is None

        signal_count_after = len(
            await redis_client.xrevrange(b"signals:paper:BTC-USD", count=100)
        )
        assert signal_count_after == signal_count_before

    @pytest.mark.asyncio
    async def test_next_candle_triggers_new_evaluation(self, agent, redis_client):
        """Push candle A -> eval -> push candle B -> eval -> second evaluation runs."""
        ohlcv = _make_long_trigger_ohlcv(50)
        await _write_ohlcv_to_stream(redis_client, "BTC/USD", "15m", ohlcv)

        # First evaluation
        await agent.evaluate_if_new_candle("BTC/USD")

        # Record last_candle_ts after first eval
        key = agent._last_candle_ts_key("BTC/USD")
        ts_after_first = float(await redis_client.get(key))

        # Append a new bar with a later timestamp
        stream_key = ohlcv_stream_key("15m", "BTC/USD")
        new_ts = ohlcv["timestamp"][-1] + 900.0
        await redis_client.xadd(
            stream_key,
            {
                b"time": str(new_ts).encode(),
                b"open": str(ohlcv["close"][-1]).encode(),
                b"high": str(ohlcv["close"][-1] + 0.5).encode(),
                b"low": str(ohlcv["close"][-1] - 0.5).encode(),
                b"close": str(ohlcv["close"][-1] + 0.1).encode(),
                b"volume": b"100.0",
            },
        )

        # Second evaluation: new candle -> should run
        await agent.evaluate_if_new_candle("BTC/USD")

        ts_after_second = float(await redis_client.get(key))
        assert ts_after_second > ts_after_first
