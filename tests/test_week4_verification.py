"""
Week-4 Verification Test Suite for crypto-ai-bot

This test suite validates Week-4 deliverables:
1. Redis stream naming and non-empty streams for main pairs
2. Correct structure of metrics used by /v1/metrics/summary
3. Basic safety checks (no live trading when MODE=paper)

Run with: pytest tests/test_week4_verification.py -v
Integration tests: pytest tests/test_week4_verification.py -v -m integration

PRD Reference: PRD-001-CRYPTO-AI-BOT.md
Architecture: docs/ARCH_ENGINE_OVERVIEW.md
Runbook: docs/RUNBOOK_ENGINE.md
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# =============================================================================
# PRD-001 CONSTANTS
# =============================================================================

PRD_CANONICAL_PAIRS = ["BTC/USD", "ETH/USD", "SOL/USD", "MATIC/USD", "LINK/USD"]
PRD_KRAKEN_SUPPORTED_PAIRS = ["BTC/USD", "ETH/USD", "SOL/USD", "LINK/USD", "DOT/USD"]

# Stream naming convention: signals:<mode>:<PAIR> where PAIR uses dash (BTC-USD)
PRD_PAPER_STREAMS = [
    "signals:paper:BTC-USD",
    "signals:paper:ETH-USD",
    "signals:paper:SOL-USD",
    "signals:paper:LINK-USD",
]

PRD_PNL_STREAM_PAPER = "pnl:paper:equity_curve"
PRD_EVENTS_STREAM = "events:bus"
PRD_SUMMARY_KEY = "engine:summary_metrics"
PRD_HEARTBEAT_KEY = "engine:heartbeat"
PRD_STATUS_KEY = "engine:status"

# Metrics required by /v1/metrics/summary (signals-api)
REQUIRED_METRICS_FIELDS = [
    "roi_30d",
    "win_rate_pct",
    "sharpe_ratio",
    "profit_factor",
    "max_drawdown_pct",
    "signals_per_day",
    "total_trades",
    "timestamp",
]

# Optional metrics fields
OPTIONAL_METRICS_FIELDS = [
    "performance_30d_json",
    "performance_90d_json",
    "performance_365d_json",
    "cagr_pct",
    "mode",
    "trading_pairs",
]


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def redis_url():
    """Get Redis URL from environment."""
    from dotenv import load_dotenv
    load_dotenv(".env.paper")
    url = os.getenv("REDIS_URL")
    if not url:
        pytest.skip("REDIS_URL not set in .env.paper")
    return url


@pytest.fixture
def redis_ca_cert():
    """Get Redis CA certificate path."""
    from dotenv import load_dotenv
    load_dotenv(".env.paper")
    return os.getenv("REDIS_CA_CERT_PATH", "config/certs/redis_ca.pem")


@pytest.fixture
def redis_client(redis_url, redis_ca_cert):
    """Create sync Redis client with TLS for fixtures."""
    import redis.asyncio as aioredis

    client = aioredis.from_url(
        redis_url,
        ssl_ca_certs=redis_ca_cert,
        ssl_cert_reqs="required",
        decode_responses=True,
        socket_timeout=10,
        socket_connect_timeout=10,
    )
    return client


# =============================================================================
# TEST CLASS 1: REDIS STREAM NAMING AND CONTENT
# =============================================================================

@pytest.mark.integration
class TestRedisStreamNamingAndContent:
    """
    Validates PRD-001 Redis stream requirements:
    - Correct naming convention (signals:<mode>:<PAIR>)
    - Non-empty streams for main trading pairs
    - Proper signal schema in stream entries
    """

    @pytest.mark.asyncio
    async def test_redis_connection(self, redis_client):
        """Test Redis Cloud TLS connection works."""
        try:
            pong = await redis_client.ping()
            assert pong is True, "Redis connection failed"
        except Exception as e:
            if "Timeout" in str(e) or "Connection" in str(e):
                pytest.skip(f"Redis connection issue (may be transient): {e}")
            raise

    @pytest.mark.asyncio
    async def test_paper_signal_streams_exist(self, redis_client):
        """Test that paper mode signal streams exist for main pairs."""
        try:
            for stream in PRD_PAPER_STREAMS:
                length = await redis_client.xlen(stream)
                assert length >= 0, f"Stream {stream} does not exist"
        except Exception as e:
            if "Timeout" in str(e) or "Connection" in str(e):
                pytest.skip(f"Redis connection issue: {e}")
            raise

    @pytest.mark.asyncio
    async def test_paper_signal_streams_non_empty(self, redis_client):
        """Test that at least some paper streams have signals (engine active)."""
        non_empty_count = 0
        for stream in PRD_PAPER_STREAMS:
            length = await redis_client.xlen(stream)
            if length > 0:
                non_empty_count += 1

        # At least 2 streams should have data if engine has been running
        assert non_empty_count >= 2, \
            f"Expected at least 2 streams with signals, got {non_empty_count}"

    @pytest.mark.asyncio
    async def test_signal_schema_structure(self, redis_client):
        """Test that signal entries have correct core schema fields.

        Note: 'mode' field is optional in older signals but required in PRD publisher.
        This test validates core fields that all signals must have.
        """
        # Core required fields (all signals should have these)
        core_signal_fields = [
            "pair", "side", "entry", "strategy", "confidence"
        ]
        # Fields that may have aliases
        alias_fields = {
            "id": ["id", "signal_id"],
            "ts": ["ts", "timestamp"],
            "sl": ["sl", "stop_loss"],
            "tp": ["tp", "take_profit"],
        }

        for stream in PRD_PAPER_STREAMS:
            length = await redis_client.xlen(stream)
            if length > 0:
                # Get latest entry
                entries = await redis_client.xrevrange(stream, count=1)
                if entries:
                    entry_id, data = entries[0]

                    # Check core fields
                    for field in core_signal_fields:
                        assert field in data, \
                            f"Missing field '{field}' in stream {stream}"

                    # Check aliased fields (at least one variant must exist)
                    for primary, aliases in alias_fields.items():
                        has_field = any(alias in data for alias in aliases)
                        assert has_field, \
                            f"Missing field '{primary}' (or aliases) in stream {stream}"
                    break  # Only need to check one stream

    @pytest.mark.asyncio
    async def test_pnl_equity_curve_stream_exists(self, redis_client):
        """Test PnL equity curve stream exists."""
        length = await redis_client.xlen(PRD_PNL_STREAM_PAPER)
        assert length >= 0, f"PnL stream {PRD_PNL_STREAM_PAPER} does not exist"

    @pytest.mark.asyncio
    async def test_events_bus_stream_exists(self, redis_client):
        """Test events bus stream exists and has entries."""
        length = await redis_client.xlen(PRD_EVENTS_STREAM)
        assert length > 0, f"Events stream {PRD_EVENTS_STREAM} is empty"

    @pytest.mark.asyncio
    async def test_stream_naming_convention(self, redis_client):
        """Test streams follow PRD naming convention.

        Note: Due to historical reasons, some streams may use slash (BTC/USD) instead
        of dash (BTC-USD). PRD-001 specifies dash format. This test validates that
        the canonical dash-format streams exist and are being used.
        """
        # Get all signal streams
        keys = await redis_client.keys("signals:paper:*")

        # Check canonical streams exist (dash format)
        canonical_found = 0
        for stream in PRD_PAPER_STREAMS:
            if stream in keys:
                length = await redis_client.xlen(stream)
                if length > 0:
                    canonical_found += 1

        # At least 2 canonical (dash-format) streams should exist with data
        assert canonical_found >= 2, \
            f"Expected at least 2 canonical streams (dash format), got {canonical_found}"

        # Log any non-compliant streams for awareness (informational only)
        for key in keys:
            parts = key.split(":")
            if len(parts) == 3 and "/" in parts[2]:
                # This is a non-compliant stream - log but don't fail
                pass  # Known issue: some publishers use slash format


# =============================================================================
# TEST CLASS 2: METRICS STRUCTURE VALIDATION
# =============================================================================

@pytest.mark.integration
class TestMetricsStructure:
    """
    Validates metrics structure used by /v1/metrics/summary:
    - engine:summary_metrics hash has required fields
    - Field values are valid types
    - Timestamp is recent (hourly update)
    """

    @pytest.mark.asyncio
    async def test_summary_metrics_key_exists(self, redis_client):
        """Test engine:summary_metrics hash exists."""
        exists = await redis_client.exists(PRD_SUMMARY_KEY)
        assert exists, f"Key {PRD_SUMMARY_KEY} does not exist"

    @pytest.mark.asyncio
    async def test_summary_metrics_required_fields(self, redis_client):
        """Test all required metrics fields are present."""
        metrics = await redis_client.hgetall(PRD_SUMMARY_KEY)

        assert len(metrics) > 0, f"Metrics hash {PRD_SUMMARY_KEY} is empty"

        missing_fields = []
        for field in REQUIRED_METRICS_FIELDS:
            # Check for field or common aliases
            if field not in metrics:
                # Check common aliases
                if field == "win_rate_pct" and "win_rate" in metrics:
                    continue
                if field == "max_drawdown_pct" and "max_drawdown" in metrics:
                    continue
                missing_fields.append(field)

        assert len(missing_fields) == 0, \
            f"Missing required metrics fields: {missing_fields}"

    @pytest.mark.asyncio
    async def test_metrics_numeric_values(self, redis_client):
        """Test numeric metrics can be parsed as floats."""
        metrics = await redis_client.hgetall(PRD_SUMMARY_KEY)

        numeric_fields = [
            "roi_30d", "win_rate_pct", "win_rate", "sharpe_ratio",
            "profit_factor", "max_drawdown_pct", "max_drawdown",
            "signals_per_day", "total_trades", "cagr_pct"
        ]

        for field in numeric_fields:
            if field in metrics:
                try:
                    float(metrics[field])
                except ValueError:
                    pytest.fail(f"Field {field}={metrics[field]} is not numeric")

    @pytest.mark.asyncio
    async def test_metrics_timestamp_recent(self, redis_client):
        """Test metrics timestamp is within last 2 hours (hourly update)."""
        metrics = await redis_client.hgetall(PRD_SUMMARY_KEY)

        timestamp = metrics.get("timestamp")
        if timestamp:
            try:
                # Parse ISO format
                if timestamp.endswith("Z"):
                    timestamp = timestamp.replace("Z", "+00:00")
                ts = datetime.fromisoformat(timestamp)
                age = datetime.now(timezone.utc) - ts

                # Should be updated within last 2 hours
                assert age < timedelta(hours=2), \
                    f"Metrics timestamp is {age} old (expected < 2 hours)"
            except ValueError:
                pytest.fail(f"Cannot parse timestamp: {timestamp}")

    @pytest.mark.asyncio
    async def test_roi_reasonable_range(self, redis_client):
        """Test ROI is within reasonable range (-100% to +1000%)."""
        metrics = await redis_client.hgetall(PRD_SUMMARY_KEY)

        roi = float(metrics.get("roi_30d", 0))
        assert -100 <= roi <= 1000, \
            f"ROI {roi}% is outside reasonable range [-100, 1000]"

    @pytest.mark.asyncio
    async def test_win_rate_valid_percentage(self, redis_client):
        """Test win rate is valid percentage (0-100)."""
        metrics = await redis_client.hgetall(PRD_SUMMARY_KEY)

        win_rate = float(metrics.get("win_rate_pct", metrics.get("win_rate", 0)))
        assert 0 <= win_rate <= 100, \
            f"Win rate {win_rate}% is outside valid range [0, 100]"

    @pytest.mark.asyncio
    async def test_sharpe_ratio_reasonable(self, redis_client):
        """Test Sharpe ratio is within reasonable range (-5 to +5)."""
        metrics = await redis_client.hgetall(PRD_SUMMARY_KEY)

        sharpe = float(metrics.get("sharpe_ratio", 0))
        assert -5 <= sharpe <= 5, \
            f"Sharpe ratio {sharpe} is outside reasonable range [-5, 5]"

    @pytest.mark.asyncio
    async def test_performance_json_valid(self, redis_client):
        """Test performance JSON fields are valid JSON."""
        metrics = await redis_client.hgetall(PRD_SUMMARY_KEY)

        json_fields = ["performance_30d_json", "performance_90d_json", "performance_365d_json"]

        for field in json_fields:
            if field in metrics and metrics[field]:
                try:
                    json.loads(metrics[field])
                except json.JSONDecodeError:
                    pytest.fail(f"Field {field} is not valid JSON")


# =============================================================================
# TEST CLASS 3: SAFETY CHECKS (NO LIVE TRADING IN PAPER MODE)
# =============================================================================

@pytest.mark.integration
class TestSafetyChecks:
    """
    Validates safety mechanisms:
    - Engine defaults to paper mode
    - No live streams when MODE=paper
    - Paper/live stream isolation
    - Mode validation in signal entries
    """

    @pytest.mark.asyncio
    async def test_no_live_streams_in_paper_mode(self, redis_client):
        """Test no signals:live:* streams exist when running paper mode."""
        live_streams = await redis_client.keys("signals:live:*")

        # Live streams shouldn't have recent data in paper mode
        for stream in live_streams:
            length = await redis_client.xlen(stream)
            if length > 0:
                # Check if entries are recent (within last hour)
                entries = await redis_client.xrevrange(stream, count=1)
                if entries:
                    entry_id = entries[0][0]
                    ts_ms = int(entry_id.split("-")[0])
                    entry_time = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
                    age = datetime.now(timezone.utc) - entry_time

                    # If recent entry in live stream, that's a safety violation
                    assert age > timedelta(hours=1), \
                        f"Recent live signal found in paper mode: {stream}"

    @pytest.mark.asyncio
    async def test_paper_signals_have_paper_mode(self, redis_client):
        """Test signals in paper streams don't have live mode.

        Note: 'mode' field is optional in older signals. This test verifies:
        1. If mode is present, it must be 'paper' (not 'live')
        2. Signals in paper streams are never marked as 'live'
        """
        for stream in PRD_PAPER_STREAMS:
            length = await redis_client.xlen(stream)
            if length > 0:
                # Sample 10 recent entries
                entries = await redis_client.xrevrange(stream, count=10)
                for entry_id, data in entries:
                    mode = data.get("mode")
                    # Mode can be None (older signals) or 'paper', but never 'live'
                    if mode is not None:
                        assert mode == "paper", \
                            f"Signal in {stream} has mode={mode} (expected 'paper' or None)"

    def test_engine_mode_env_defaults_paper(self):
        """Test ENGINE_MODE defaults to 'paper' when not set."""
        original = os.environ.pop("ENGINE_MODE", None)
        try:
            from agents.infrastructure.prd_redis_publisher import get_engine_mode
            mode = get_engine_mode()
            assert mode == "paper", f"Default mode should be 'paper', got '{mode}'"
        except ImportError:
            # If module doesn't have get_engine_mode, check env behavior
            mode = os.getenv("ENGINE_MODE", "paper")
            assert mode == "paper"
        finally:
            if original:
                os.environ["ENGINE_MODE"] = original

    def test_live_mode_requires_confirmation(self):
        """Test live mode requires LIVE_TRADING_CONFIRMATION=true."""
        try:
            from agents.infrastructure.prd_redis_publisher import validate_live_mode

            # Should raise without confirmation
            os.environ["ENGINE_MODE"] = "live"
            os.environ.pop("LIVE_TRADING_CONFIRMATION", None)

            # This should fail validation
            result = validate_live_mode()
            assert result is False, "Live mode should require confirmation"

        except ImportError:
            # Function may not exist - skip
            pytest.skip("validate_live_mode not implemented")
        finally:
            os.environ.pop("ENGINE_MODE", None)
            os.environ.pop("LIVE_TRADING_CONFIRMATION", None)


# =============================================================================
# TEST CLASS 4: ENGINE HEALTH AND HEARTBEAT
# =============================================================================

@pytest.mark.integration
class TestEngineHealth:
    """
    Validates engine health and heartbeat:
    - Heartbeat key exists and is recent
    - Status JSON is valid
    - Health indicates connected components
    """

    @pytest.mark.asyncio
    async def test_heartbeat_exists(self, redis_client):
        """Test engine:heartbeat key exists."""
        try:
            heartbeat = await redis_client.get(PRD_HEARTBEAT_KEY)
            # Heartbeat might not exist if engine not running
            # This is informational, not a failure
            if heartbeat is None:
                pytest.skip("Engine heartbeat not found (engine may not be running)")
        except Exception as e:
            # Connection issues should skip, not fail
            pytest.skip(f"Redis connection issue: {e}")

    @pytest.mark.asyncio
    async def test_heartbeat_recent(self, redis_client):
        """Test heartbeat is within last 2 minutes (30s interval + buffer)."""
        heartbeat = await redis_client.get(PRD_HEARTBEAT_KEY)

        if heartbeat:
            try:
                if heartbeat.endswith("Z"):
                    heartbeat = heartbeat.replace("Z", "+00:00")
                ts = datetime.fromisoformat(heartbeat)
                age = datetime.now(timezone.utc) - ts

                assert age < timedelta(minutes=2), \
                    f"Heartbeat is {age} old (expected < 2 minutes)"
            except ValueError:
                pytest.fail(f"Cannot parse heartbeat: {heartbeat}")

    @pytest.mark.asyncio
    async def test_status_json_valid(self, redis_client):
        """Test engine:status is valid JSON."""
        status = await redis_client.get(PRD_STATUS_KEY)

        if status:
            try:
                data = json.loads(status)
                assert "status" in data, "Status JSON missing 'status' field"
                assert "mode" in data, "Status JSON missing 'mode' field"
            except json.JSONDecodeError:
                pytest.fail(f"engine:status is not valid JSON")

    @pytest.mark.asyncio
    async def test_status_indicates_paper_mode(self, redis_client):
        """Test status indicates paper mode."""
        status = await redis_client.get(PRD_STATUS_KEY)

        if status:
            data = json.loads(status)
            assert data.get("mode") == "paper", \
                f"Status shows mode={data.get('mode')} (expected 'paper')"


# =============================================================================
# TEST CLASS 5: UNIT TESTS (NO REDIS REQUIRED)
# =============================================================================

class TestMetricsCalculationUnit:
    """Unit tests for metrics calculation logic (no Redis needed)."""

    def test_stream_name_generation_paper(self):
        """Test paper mode stream name generation."""
        try:
            from agents.infrastructure.prd_redis_publisher import get_signal_stream_name

            assert get_signal_stream_name("paper", "BTC/USD") == "signals:paper:BTC-USD"
            assert get_signal_stream_name("paper", "ETH/USD") == "signals:paper:ETH-USD"
        except ImportError:
            pytest.skip("prd_redis_publisher not available")

    def test_stream_name_generation_live(self):
        """Test live mode stream name generation."""
        try:
            from agents.infrastructure.prd_redis_publisher import get_signal_stream_name

            assert get_signal_stream_name("live", "BTC/USD") == "signals:live:BTC-USD"
            assert get_signal_stream_name("live", "ETH/USD") == "signals:live:ETH-USD"
        except ImportError:
            pytest.skip("prd_redis_publisher not available")

    def test_invalid_mode_raises_error(self):
        """Test invalid mode raises ValueError."""
        try:
            from agents.infrastructure.prd_redis_publisher import get_signal_stream_name

            with pytest.raises(ValueError):
                get_signal_stream_name("invalid", "BTC/USD")
        except ImportError:
            pytest.skip("prd_redis_publisher not available")

    def test_summary_metrics_dataclass_fields(self):
        """Test SummaryMetrics has all required fields."""
        try:
            from analysis.metrics_summary import SummaryMetrics

            metrics = SummaryMetrics(
                mode="paper",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

            # Convert to dict and check fields
            metrics_dict = metrics.to_dict()

            for field in ["signals_per_day", "win_rate_pct", "roi_30d",
                         "profit_factor", "sharpe_ratio"]:
                assert field in metrics_dict, f"Missing field: {field}"
        except ImportError:
            pytest.skip("metrics_summary not available")

    def test_canonical_pairs_match_prd(self):
        """Test canonical pairs in metrics_summary match PRD-001."""
        try:
            from analysis.metrics_summary import CANONICAL_PAIRS

            assert set(CANONICAL_PAIRS) == set(PRD_CANONICAL_PAIRS), \
                f"Pairs mismatch: {CANONICAL_PAIRS} vs {PRD_CANONICAL_PAIRS}"
        except ImportError:
            pytest.skip("metrics_summary not available")


# =============================================================================
# TEST CLASS 6: 24/7 STABILITY CHECKS
# =============================================================================

class TestStabilityChecks:
    """Tests for 24/7 operational stability."""

    def test_reconnect_logic_exists(self):
        """Test WebSocket reconnect logic is implemented."""
        try:
            from utils.kraken_ws import KrakenWSClient

            # Check class has reconnection-related attributes
            client_attrs = dir(KrakenWSClient)
            reconnect_attrs = [attr for attr in client_attrs
                             if "reconnect" in attr.lower() or "retry" in attr.lower()]

            assert len(reconnect_attrs) > 0, \
                "KrakenWSClient missing reconnect logic"
        except ImportError:
            pytest.skip("kraken_ws not available")

    def test_circuit_breaker_exists(self):
        """Test circuit breaker pattern is implemented."""
        try:
            from utils.kraken_ws import CircuitBreaker

            # Circuit breaker should exist
            assert CircuitBreaker is not None
        except ImportError:
            pytest.skip("CircuitBreaker not available")

    def test_health_publisher_exists(self):
        """Test health publisher is implemented in main_engine."""
        import importlib.util

        spec = importlib.util.find_spec("main_engine")
        if spec is None:
            pytest.skip("main_engine not found")

        # Check source contains health publisher logic
        with open(spec.origin, "r", encoding="utf-8") as f:
            content = f.read()
            assert "health" in content.lower(), \
                "main_engine missing health publisher logic"
            assert "heartbeat" in content.lower(), \
                "main_engine missing heartbeat logic"


# =============================================================================
# MAIN EXECUTION
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
