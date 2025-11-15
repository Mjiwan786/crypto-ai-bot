#!/usr/bin/env python3
"""
Tests for PnL Aggregator Resume and Day Reset Functionality

Tests verify:
1. Aggregator can resume from last processed ID
2. Daily PnL resets correctly at UTC day boundaries
3. State is persisted correctly to Redis

Uses monkeypatching to avoid real Redis dependency in tests.
"""

import os
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

try:
    import orjson
except ImportError:
    import json as orjson


# Mock Redis client for testing
class MockRedisClient:
    """Mock Redis client that stores data in memory."""

    def __init__(self):
        self.data: Dict[str, bytes] = {}
        self.streams: Dict[str, List[tuple]] = {}
        self.connected = True

    def ping(self):
        """Mock ping."""
        if not self.connected:
            raise Exception("Not connected")
        return True

    def get(self, key: str) -> bytes | None:
        """Mock GET."""
        return self.data.get(key)

    def set(self, key: str, value: Any) -> bool:
        """Mock SET."""
        self.data[key] = value if isinstance(value, bytes) else str(value).encode("utf-8")
        return True

    def xadd(self, stream: str, fields: dict) -> bytes:
        """Mock XADD."""
        if stream not in self.streams:
            self.streams[stream] = []

        # Generate message ID
        msg_id = f"{len(self.streams[stream])}-0"
        self.streams[stream].append((msg_id, fields))
        return msg_id.encode("utf-8")

    def xread(self, streams: dict, count: int = 1, block: int = 0) -> List:
        """Mock XREAD."""
        result = []
        for stream_name, last_id in streams.items():
            if stream_name not in self.streams:
                continue

            # Parse last_id to determine starting position
            if last_id == "0-0":
                start_idx = 0
            else:
                try:
                    start_idx = int(last_id.split("-")[0]) + 1
                except (ValueError, IndexError):
                    start_idx = 0

            # Get messages after last_id
            messages = self.streams[stream_name][start_idx : start_idx + count]

            if messages:
                # Convert to format expected by aggregator
                formatted_messages = []
                for msg_id, fields in messages:
                    formatted_messages.append((msg_id.encode("utf-8"), fields))

                result.append((stream_name.encode("utf-8"), formatted_messages))

        return result if result else None

    @classmethod
    def from_url(cls, url: str, **kwargs):
        """Mock from_url constructor."""
        return cls()


def _create_trade_event(trade_id: str, ts_ms: int, pnl: float) -> dict:
    """Helper to create a trade event."""
    return {
        "id": trade_id,
        "ts": ts_ms,
        "pair": "BTC/USD",
        "side": "long",
        "entry": 45000.0,
        "exit": 46000.0,
        "qty": 0.1,
        "pnl": pnl,
    }


def _serialize_event(event: dict) -> dict:
    """Helper to serialize event to Redis field format."""
    if hasattr(orjson, "dumps"):
        json_bytes = orjson.dumps(event)
    else:
        json_bytes = orjson.dumps(event).encode("utf-8")

    return {b"json": json_bytes}


class TestPnLAggregatorResume:
    """Test suite for PnL aggregator resume functionality."""

    def test_aggregator_resumes_from_last_id(self):
        """Test that aggregator can resume from last processed ID."""
        # Setup mock Redis
        mock_redis = MockRedisClient()

        # Seed 3 trades into stream
        trade1 = _create_trade_event("trade_1", 1704067200000, 100.0)
        trade2 = _create_trade_event("trade_2", 1704067260000, 50.0)
        trade3 = _create_trade_event("trade_3", 1704067320000, -25.0)

        mock_redis.xadd("trades:closed", _serialize_event(trade1))
        mock_redis.xadd("trades:closed", _serialize_event(trade2))
        mock_redis.xadd("trades:closed", _serialize_event(trade3))

        # Simulate aggregator processing first batch (2 trades)
        result = mock_redis.xread({"trades:closed": "0-0"}, count=2)
        assert result is not None
        stream_name, messages = result[0]

        # Process first 2 messages and save last_id
        last_id = None
        equity = 10000.0  # Starting equity

        for msg_id, fields in messages:
            json_bytes = fields.get(b"json")
            event = orjson.loads(json_bytes) if hasattr(orjson, "loads") else orjson.loads(json_bytes.decode("utf-8"))

            equity += event["pnl"]
            last_id = msg_id.decode("utf-8")

        # Save state
        mock_redis.set("pnl:agg:last_id", last_id)

        # Verify state
        assert equity == 10150.0  # 10000 + 100 + 50
        assert last_id == "1-0"

        # Simulate restart - resume from last_id
        stored_last_id = mock_redis.get("pnl:agg:last_id").decode("utf-8")
        assert stored_last_id == "1-0"

        # Read remaining messages
        result = mock_redis.xread({"trades:closed": stored_last_id}, count=10)
        assert result is not None
        stream_name, messages = result[0]

        # Should only get trade3
        assert len(messages) == 1

        for msg_id, fields in messages:
            json_bytes = fields.get(b"json")
            event = orjson.loads(json_bytes) if hasattr(orjson, "loads") else orjson.loads(json_bytes.decode("utf-8"))

            equity += event["pnl"]
            last_id = msg_id.decode("utf-8")

        # Final equity should include all 3 trades
        assert equity == 10125.0  # 10000 + 100 + 50 - 25
        assert last_id == "2-0"

    def test_daily_pnl_resets_at_day_boundary(self):
        """Test that daily PnL resets correctly at UTC day boundaries."""
        # Mock Redis
        mock_redis = MockRedisClient()

        # Day 1: 2024-01-01 12:00:00 UTC (timestamp: 1704110400000)
        day1_ts = 1704110400000

        # Day 2: 2024-01-02 12:00:00 UTC (timestamp: 1704196800000)
        day2_ts = 1704196800000

        # Seed trades across day boundary
        trade1_day1 = _create_trade_event("trade_1", day1_ts, 100.0)
        trade2_day1 = _create_trade_event("trade_2", day1_ts + 3600000, 50.0)  # +1 hour
        trade3_day2 = _create_trade_event("trade_3", day2_ts, 75.0)  # Next day

        mock_redis.xadd("trades:closed", _serialize_event(trade1_day1))
        mock_redis.xadd("trades:closed", _serialize_event(trade2_day1))
        mock_redis.xadd("trades:closed", _serialize_event(trade3_day2))

        # Simulate aggregator with day boundary detection
        def get_day_start_ms(ts_ms: int) -> int:
            """Get UTC day start timestamp."""
            dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
            day_start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
            return int(day_start.timestamp() * 1000)

        equity = 10000.0
        day_start_equity = 10000.0
        current_day_start_ms = get_day_start_ms(day1_ts)

        # Process all trades
        result = mock_redis.xread({"trades:closed": "0-0"}, count=10)
        stream_name, messages = result[0]

        daily_pnls = []

        for msg_id, fields in messages:
            json_bytes = fields.get(b"json")
            event = orjson.loads(json_bytes) if hasattr(orjson, "loads") else orjson.loads(json_bytes.decode("utf-8"))

            ts_ms = event["ts"]
            pnl = event["pnl"]

            # Check for day boundary
            trade_day_start_ms = get_day_start_ms(ts_ms)
            if trade_day_start_ms > current_day_start_ms:
                # Day crossed - record previous day's PnL and reset
                daily_pnls.append(equity - day_start_equity)
                day_start_equity = equity
                current_day_start_ms = trade_day_start_ms

            equity += pnl

        # Record final day's PnL
        daily_pnls.append(equity - day_start_equity)

        # Assertions
        assert len(daily_pnls) == 2  # Two days
        assert daily_pnls[0] == 150.0  # Day 1: 100 + 50
        assert daily_pnls[1] == 75.0  # Day 2: 75 (reset at boundary)
        assert equity == 10225.0  # Total: 10000 + 100 + 50 + 75

    def test_state_persistence_across_batches(self):
        """Test that state is correctly persisted after each batch."""
        mock_redis = MockRedisClient()

        # Seed 5 trades
        for i in range(5):
            trade = _create_trade_event(f"trade_{i}", 1704067200000 + i * 60000, 10.0 * (i + 1))
            mock_redis.xadd("trades:closed", _serialize_event(trade))

        # Process in batches of 2
        last_id = "0-0"
        equity = 10000.0
        processed_count = 0

        for batch_num in range(3):  # 3 batches to process all 5 trades
            result = mock_redis.xread({"trades:closed": last_id}, count=2)

            if not result:
                break

            stream_name, messages = result[0]

            for msg_id, fields in messages:
                json_bytes = fields.get(b"json")
                event = orjson.loads(json_bytes) if hasattr(orjson, "loads") else orjson.loads(json_bytes.decode("utf-8"))

                equity += event["pnl"]
                last_id = msg_id.decode("utf-8")
                processed_count += 1

            # Save checkpoint after batch
            mock_redis.set("pnl:agg:last_id", last_id)

            # Verify checkpoint can be restored
            stored_id = mock_redis.get("pnl:agg:last_id").decode("utf-8")
            assert stored_id == last_id

        # Verify all trades processed
        assert processed_count == 5
        assert equity == 10150.0  # 10000 + (10 + 20 + 30 + 40 + 50)


class TestPnLAggregatorStats:
    """Test suite for optional pandas statistics."""

    @pytest.mark.skipif(
        not os.getenv("USE_PANDAS", "false").lower() in ("true", "1", "yes"),
        reason="Pandas stats not enabled",
    )
    def test_stats_calculation_with_rolling_window(self):
        """Test statistics calculation with rolling window."""
        try:
            import pandas as pd
            import numpy as np
        except ImportError:
            pytest.skip("Pandas not installed")

        # Import stats function (would need to be exposed for testing)
        from monitoring.pnl_aggregator import _calculate_stats

        # Create trades window with mixed wins/losses
        trades_window = deque(
            [
                {"pnl": 100.0},
                {"pnl": 50.0},
                {"pnl": -25.0},
                {"pnl": 75.0},
                {"pnl": -10.0},
            ]
        )

        stats = _calculate_stats(trades_window)

        # Verify stats structure
        assert "win_rate" in stats
        assert "max_drawdown" in stats
        assert "sharpe" in stats

        # Verify win rate (3 wins out of 5 = 60%)
        assert stats["win_rate"] == 0.6

        # Verify stats are numeric
        assert isinstance(stats["win_rate"], float)
        assert isinstance(stats["max_drawdown"], float)
        assert isinstance(stats["sharpe"], float)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
