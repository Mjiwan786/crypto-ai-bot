"""
Unit tests for RSI Bounce agent logic.

Tests:
- Template loading and validation
- Signal creation (LONG/SHORT with correct SL/TP)
- Bar freshness check
- Cooldown enforcement
- Daily limit enforcement
- Duplicate signal suppression
- Candle-close dedup (same candle skipped, new candle evaluated)
- Full evaluate flow with mock OHLCV data
- Explainability logging

Uses FakeRedis for async Redis operations (following test_bar_reaction_agent.py pattern).
"""

import logging
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest
import pytest_asyncio

try:
    from fakeredis.aioredis import FakeRedis as FakeAsyncRedis
except ImportError:
    FakeAsyncRedis = None

from agents.indicator.rsi_bounce import (
    RSIBounceAgent,
    _timeframe_to_seconds,
    load_template,
    ohlcv_stream_key,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def template_config():
    """Config dict matching the template schema (no YAML file needed)."""
    return {
        "pairs": ["BTC/USD"],
        "timeframe": "15m",
        "rsi_period": 14,
        "rsi_oversold": 30.0,
        "rsi_overbought": 70.0,
        "atr_period": 14,
        "sl_atr_multiplier": 1.5,
        "tp_atr_multiplier": 2.0,
        "position_size_usd": 100.0,
        "cooldown_minutes": 60,
        "max_signals_per_day": 10,
        "warmup_bars": 50,
        "bar_freshness_max_seconds": 120,
        "mode": "paper",
        "default_regime": "RANGING",
    }


@pytest_asyncio.fixture
async def redis_client():
    """Fake async Redis client for tests."""
    if FakeAsyncRedis is not None:
        client = FakeAsyncRedis(decode_responses=False)
    else:
        client = AsyncMock()
    yield client
    try:
        if hasattr(client, "flushall"):
            await client.flushall()
        if hasattr(client, "aclose"):
            await client.aclose()
    except Exception:
        pass


@pytest_asyncio.fixture
async def agent(template_config, redis_client):
    """Initialized RSIBounceAgent."""
    a = RSIBounceAgent()
    await a.initialize(template_config, redis_client)
    return a


# =============================================================================
# HELPERS - generate OHLCV numpy arrays
# =============================================================================

def _make_ohlcv_trending_down_then_up(n: int = 50):
    """Generate OHLCV that drops (RSI < 30) then bounces (RSI crosses above 30).

    Returns dict with numpy arrays.
    """
    closes = np.empty(n, dtype=np.float64)
    # Strong downtrend for first 35 bars
    for i in range(35):
        closes[i] = 100.0 - i * 0.8
    # Sharp bounce for remaining bars
    for i in range(35, n):
        closes[i] = closes[34] + (i - 34) * 1.5

    highs = closes + 0.5
    lows = closes - 0.5
    timestamps = np.array([time.time() - (n - i) * 900 for i in range(n)], dtype=np.float64)
    volumes = np.full(n, 100.0, dtype=np.float64)

    return {
        "timestamp": timestamps,
        "open": closes.copy(),
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    }


def _make_ohlcv_no_trigger(n: int = 50):
    """Generate OHLCV where RSI stays in the 40-60 range (no trigger)."""
    closes = np.empty(n, dtype=np.float64)
    for i in range(n):
        closes[i] = 100.0 + (1.0 if i % 2 == 0 else -1.0) * 0.5

    highs = closes + 0.3
    lows = closes - 0.3
    timestamps = np.array([time.time() - (n - i) * 900 for i in range(n)], dtype=np.float64)
    volumes = np.full(n, 100.0, dtype=np.float64)

    return {
        "timestamp": timestamps,
        "open": closes.copy(),
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    }


# =============================================================================
# TEMPLATE LOADING
# =============================================================================

class TestTemplateLoading:

    @pytest.mark.unit
    def test_load_default_template(self):
        cfg = load_template()
        assert "pairs" in cfg
        assert cfg["rsi_period"] == 14
        assert cfg["mode"] == "paper"

    @pytest.mark.unit
    def test_load_template_missing_file(self):
        with pytest.raises(FileNotFoundError):
            load_template("/nonexistent/path.yaml")


# =============================================================================
# STREAM KEY BUILDER
# =============================================================================

class TestOHLCVStreamKey:

    @pytest.mark.unit
    def test_key_format(self):
        key = ohlcv_stream_key("15m", "BTC/USD")
        assert key == "kraken:ohlc:15m:BTC-USD"

    @pytest.mark.unit
    def test_key_with_dash_pair(self):
        key = ohlcv_stream_key("5m", "ETH-USD")
        assert key == "kraken:ohlc:5m:ETH-USD"


# =============================================================================
# SIGNAL CREATION
# =============================================================================

class TestSignalCreation:

    @pytest.mark.unit
    def test_long_signal_sl_below_entry(self, agent):
        signal = agent._create_signal(
            pair="BTC/USD",
            side="LONG",
            entry_price=50000.0,
            atr_value=200.0,
            rsi_value=32.0,
            rsi_prev=28.0,
        )
        assert str(signal.side) == "LONG"
        assert signal.stop_loss < signal.entry_price
        assert signal.take_profit > signal.entry_price
        assert str(signal.strategy) == "MEAN_REVERSION"
        assert signal.strategy_label == "RSI Bounce"
        assert signal.mode == "paper"
        assert signal.rsi_14 == 32.0
        assert signal.atr_14 == 200.0

    @pytest.mark.unit
    def test_short_signal_sl_above_entry(self, agent):
        signal = agent._create_signal(
            pair="BTC/USD",
            side="SHORT",
            entry_price=50000.0,
            atr_value=200.0,
            rsi_value=68.0,
            rsi_prev=72.0,
        )
        assert str(signal.side) == "SHORT"
        assert signal.stop_loss > signal.entry_price
        assert signal.take_profit < signal.entry_price

    @pytest.mark.unit
    def test_sl_tp_match_atr_multipliers(self, agent):
        atr = 200.0
        entry = 50000.0
        signal = agent._create_signal(
            pair="BTC/USD",
            side="LONG",
            entry_price=entry,
            atr_value=atr,
            rsi_value=32.0,
            rsi_prev=28.0,
        )
        assert signal.stop_loss == pytest.approx(entry - 1.5 * atr)
        assert signal.take_profit == pytest.approx(entry + 2.0 * atr)

    @pytest.mark.unit
    def test_signal_includes_timeframe(self, agent):
        signal = agent._create_signal(
            pair="BTC/USD",
            side="LONG",
            entry_price=50000.0,
            atr_value=200.0,
            rsi_value=32.0,
            rsi_prev=28.0,
        )
        assert signal.timeframe == "15m"

    @pytest.mark.unit
    def test_signal_has_valid_confidence(self, agent):
        signal = agent._create_signal(
            pair="BTC/USD",
            side="LONG",
            entry_price=50000.0,
            atr_value=200.0,
            rsi_value=32.0,
            rsi_prev=28.0,
        )
        assert 0.55 <= signal.confidence <= 0.90


# =============================================================================
# BAR FRESHNESS
# =============================================================================

class TestBarFreshness:

    @pytest.mark.unit
    def test_fresh_bar_passes(self, agent):
        ts = np.array([time.time() - 60], dtype=np.float64)
        ok, _ = agent._check_bar_freshness(ts)
        assert ok is True

    @pytest.mark.unit
    def test_stale_bar_fails(self, agent):
        ts = np.array([time.time() - 300], dtype=np.float64)
        ok, reason = agent._check_bar_freshness(ts)
        assert ok is False
        assert "stale" in reason.lower()

    @pytest.mark.unit
    def test_empty_timestamps_fails(self, agent):
        ts = np.array([], dtype=np.float64)
        ok, _ = agent._check_bar_freshness(ts)
        assert ok is False


# =============================================================================
# COOLDOWN
# =============================================================================

class TestCooldown:

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_no_prior_cooldown_passes(self, agent):
        ok, _ = await agent._check_cooldown("BTC/USD")
        assert ok is True

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_recent_cooldown_fails(self, agent, redis_client):
        past = time.time() - 600  # 10 minutes ago (< 60 min cooldown)
        await redis_client.set(
            "rsi_bounce:cooldown:BTC/USD", str(past).encode()
        )
        ok, reason = await agent._check_cooldown("BTC/USD")
        assert ok is False
        assert "Cooldown" in reason

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_expired_cooldown_passes(self, agent, redis_client):
        past = time.time() - 4000  # ~67 minutes ago (> 60 min cooldown)
        await redis_client.set(
            "rsi_bounce:cooldown:BTC/USD", str(past).encode()
        )
        ok, _ = await agent._check_cooldown("BTC/USD")
        assert ok is True


# =============================================================================
# DAILY LIMIT
# =============================================================================

class TestDailyLimit:

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_under_limit_passes(self, agent, redis_client):
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        await redis_client.set(
            f"rsi_bounce:daily_count:BTC/USD:{today}".encode(),
            b"5",
        )
        ok, _ = await agent._check_daily_limit("BTC/USD")
        assert ok is True

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_at_limit_fails(self, agent, redis_client):
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        await redis_client.set(
            f"rsi_bounce:daily_count:BTC/USD:{today}".encode(),
            b"10",
        )
        ok, reason = await agent._check_daily_limit("BTC/USD")
        assert ok is False
        assert "Daily limit" in reason


# =============================================================================
# DUPLICATE SIGNAL SUPPRESSION
# =============================================================================

class TestDuplicate:

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_no_prior_signal_not_duplicate(self, agent):
        is_dup = await agent._check_duplicate("BTC/USD", "abc123")
        assert is_dup is False

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_same_id_is_duplicate(self, agent, redis_client):
        await redis_client.set(
            "rsi_bounce:last_signal_id:BTC/USD", b"abc123"
        )
        is_dup = await agent._check_duplicate("BTC/USD", "abc123")
        assert is_dup is True

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_different_id_not_duplicate(self, agent, redis_client):
        await redis_client.set(
            "rsi_bounce:last_signal_id:BTC/USD", b"abc123"
        )
        is_dup = await agent._check_duplicate("BTC/USD", "xyz789")
        assert is_dup is False


# =============================================================================
# CANDLE-CLOSE DEDUP
# =============================================================================

class TestCandleDedup:
    """evaluate_if_new_candle must process each candle exactly once."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_same_candle_skips_second_call(self, agent, redis_client):
        """Two calls with the same OHLCV stream -> second returns None immediately."""
        ohlcv = _make_ohlcv_no_trigger(50)

        # Write OHLCV to Redis stream
        stream_key = ohlcv_stream_key("15m", "BTC/USD")
        for i in range(len(ohlcv["close"])):
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

        # First call: evaluates (no trigger but processes the candle)
        result1 = await agent.evaluate_if_new_candle("BTC/USD")
        # No trigger in this data -> None
        assert result1 is None

        # Verify last_candle_ts was stored
        key = agent._last_candle_ts_key("BTC/USD")
        stored = await redis_client.get(key)
        assert stored is not None

        # Second call with same stream (no new bar): should skip
        result2 = await agent.evaluate_if_new_candle("BTC/USD")
        assert result2 is None

        # Confirm the stored timestamp did not change (no re-processing)
        stored_after = await redis_client.get(key)
        assert stored == stored_after

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_new_candle_triggers_evaluation(self, agent, redis_client):
        """Adding a newer bar after first call -> second call evaluates."""
        ohlcv = _make_ohlcv_no_trigger(50)

        stream_key = ohlcv_stream_key("15m", "BTC/USD")
        for i in range(len(ohlcv["close"])):
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

        # First call: evaluates
        await agent.evaluate_if_new_candle("BTC/USD")
        key = agent._last_candle_ts_key("BTC/USD")
        stored_first = await redis_client.get(key)

        # Add a newer bar (timestamp > any existing)
        new_ts = ohlcv["timestamp"][-1] + 900.0  # 15 min later
        await redis_client.xadd(
            stream_key,
            {
                b"time": str(new_ts).encode(),
                b"open": b"100.0",
                b"high": b"101.0",
                b"low": b"99.0",
                b"close": b"100.5",
                b"volume": b"50.0",
            },
        )

        # Second call: new candle detected -> evaluates again
        await agent.evaluate_if_new_candle("BTC/USD")
        stored_second = await redis_client.get(key)

        # Timestamp should have been updated
        assert float(stored_second) > float(stored_first)

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_no_bar_in_stream_returns_none(self, agent):
        """Empty stream -> evaluate_if_new_candle returns None without error."""
        result = await agent.evaluate_if_new_candle("BTC/USD")
        assert result is None

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_last_candle_ts_key_format(self, agent):
        """Redis key follows expected convention."""
        key = agent._last_candle_ts_key("BTC/USD")
        assert key == "rsi_bounce:last_candle_ts:BTC-USD:15m"


# =============================================================================
# HEARTBEAT LOG (INFO on every new candle, even SKIPPED)
# =============================================================================

class TestHeartbeatLog:

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_skipped_candle_emits_info(self, agent, redis_client, caplog):
        """New candle with no RSI cross -> exactly one INFO with EVALUATED | SKIPPED."""
        ohlcv = _make_ohlcv_no_trigger(50)
        stream_key = ohlcv_stream_key("15m", "BTC/USD")
        for i in range(len(ohlcv["close"])):
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

        with caplog.at_level(logging.INFO, logger="agents.indicator.rsi_bounce"):
            await agent.evaluate_if_new_candle("BTC/USD")

        info_records = [
            r for r in caplog.records
            if r.levelno == logging.INFO and "RSI Bounce" in r.message
        ]
        assert len(info_records) == 1
        assert "EVALUATED" in info_records[0].message
        assert "SKIPPED" in info_records[0].message

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_already_processed_candle_no_info(self, agent, redis_client, caplog):
        """Second call with same candle -> no INFO log at all."""
        ohlcv = _make_ohlcv_no_trigger(50)
        stream_key = ohlcv_stream_key("15m", "BTC/USD")
        for i in range(len(ohlcv["close"])):
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

        # First call: processes the candle
        await agent.evaluate_if_new_candle("BTC/USD")

        # Clear logs, then do second call
        caplog.clear()
        with caplog.at_level(logging.INFO, logger="agents.indicator.rsi_bounce"):
            await agent.evaluate_if_new_candle("BTC/USD")

        info_records = [
            r for r in caplog.records
            if r.levelno == logging.INFO and "RSI Bounce" in r.message
        ]
        assert len(info_records) == 0


# =============================================================================
# TIMEFRAME TTL
# =============================================================================

class TestTimeframeTTL:

    @pytest.mark.unit
    def test_timeframe_to_seconds_known_values(self):
        assert _timeframe_to_seconds("1m") == 60
        assert _timeframe_to_seconds("5m") == 300
        assert _timeframe_to_seconds("15m") == 900
        assert _timeframe_to_seconds("1h") == 3600
        assert _timeframe_to_seconds("4h") == 14400
        assert _timeframe_to_seconds("1d") == 86400

    @pytest.mark.unit
    def test_timeframe_to_seconds_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown timeframe"):
            _timeframe_to_seconds("2w")

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_ttl_floor_86400_for_15m(self, agent, redis_client):
        """15m -> max(86400, 10*900) = 86400."""
        await agent._set_last_processed_ts("BTC/USD", 1000.0)
        key = agent._last_candle_ts_key("BTC/USD")
        ttl = await redis_client.ttl(key)
        assert ttl == 86400

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_ttl_scales_for_daily(self, template_config, redis_client):
        """1d -> max(86400, 10*86400) = 864000."""
        cfg = {**template_config, "timeframe": "1d"}
        a = RSIBounceAgent()
        await a.initialize(cfg, redis_client)
        await a._set_last_processed_ts("BTC/USD", 1000.0)
        key = a._last_candle_ts_key("BTC/USD")
        ttl = await redis_client.ttl(key)
        assert ttl == 864000

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_ttl_scales_for_4h(self, template_config, redis_client):
        """4h -> max(86400, 10*14400) = 144000."""
        cfg = {**template_config, "timeframe": "4h"}
        a = RSIBounceAgent()
        await a.initialize(cfg, redis_client)
        await a._set_last_processed_ts("BTC/USD", 1000.0)
        key = a._last_candle_ts_key("BTC/USD")
        ttl = await redis_client.ttl(key)
        assert ttl == 144000


# =============================================================================
# METADATA
# =============================================================================

class TestMetadata:

    @pytest.mark.unit
    def test_agent_metadata(self):
        meta = RSIBounceAgent.get_metadata()
        assert meta.name == "rsi_bounce"
        assert meta.version == "1.0.0"
        assert "mean_reversion" in [c.value for c in meta.capabilities]

    @pytest.mark.unit
    def test_agent_initializes(self, agent):
        assert agent.is_initialized() is True
        assert agent.rsi_period == 14
        assert agent.mode == "paper"


# =============================================================================
# FULL EVALUATE (with mock OHLCV in Redis)
# =============================================================================

class TestEvaluatePair:

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_evaluate_returns_none_when_no_data(self, agent):
        """No OHLCV in stream -> returns None."""
        signal = await agent._evaluate_pair("BTC/USD")
        assert signal is None

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_evaluate_with_no_trigger_ohlcv(self, agent, redis_client):
        """OHLCV with RSI in mid-range -> no signal."""
        ohlcv = _make_ohlcv_no_trigger(50)

        # Write OHLCV to the expected stream
        stream_key = ohlcv_stream_key("15m", "BTC/USD")
        for i in range(len(ohlcv["close"])):
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

        signal = await agent._evaluate_pair("BTC/USD")
        assert signal is None
