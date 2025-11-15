"""
Tests for Agent Base Class (PRD-001 Section 3.1)

Tests cover:
- Agent base class with common logging, metrics, error handling
- Lifecycle event logging at INFO level (startup, shutdown)
- Prometheus counter agent_invocations_total{agent, method, outcome}
- Abstract method enforcement for get_metadata(), initialize(), generate_signals(), shutdown()
- Helper methods: validate_signal(), healthcheck(), on_error()
"""

import pytest
import logging
import time
from unittest.mock import Mock, AsyncMock, patch
from typing import Dict, Any, List

from agents.base.strategy_agent_base import (
    StrategyAgentBase,
    AgentMetadata,
    AgentCapability,
    PROMETHEUS_AVAILABLE,
    AGENT_INVOCATIONS_TOTAL
)


# Test implementation of abstract base class
class TestAgent(StrategyAgentBase):
    """Test agent implementation for testing base class functionality"""

    @classmethod
    def get_metadata(cls) -> AgentMetadata:
        return AgentMetadata(
            name="test_agent",
            description="Test agent for unit tests",
            version="1.0.0",
            author="Test Team",
            capabilities=[AgentCapability.SCALPING],
            supported_symbols=["BTC/USD"],
            supported_timeframes=["5m"]
        )

    async def initialize(self, config: Dict[str, Any], redis_client=None):
        self._log_lifecycle("startup", "Starting initialization")
        self.config = config
        self.redis = redis_client
        self._initialized = True
        self._log_lifecycle("startup", "Initialization complete")
        self._emit_metric("initialize", "success")

    async def generate_signals(self, market_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        self._emit_metric("generate_signals", "success")
        return [{
            "timestamp": time.time(),
            "signal_type": "entry",
            "trading_pair": "BTC/USD",
            "size": 0.1,
            "confidence_score": 0.8,
            "agent_id": "test_agent"
        }]

    async def shutdown(self):
        self._log_lifecycle("shutdown", "Starting shutdown")
        self._shutdown = True
        self._log_lifecycle("shutdown", "Shutdown complete")
        self._emit_metric("shutdown", "success")


@pytest.fixture
def test_agent():
    """Create test agent instance"""
    return TestAgent()


@pytest.fixture
def valid_market_data():
    """Create valid market data"""
    return {
        "symbol": "BTC/USD",
        "timeframe": "5m",
        "timestamp": time.time(),
        "mid_price": 50000.0,
        "spread_bps": 2.0
    }


class TestAgentMetadata:
    """Test agent metadata (PRD-001 Section 3.1 Item 5)"""

    def test_get_metadata_returns_agent_metadata(self, test_agent):
        """Test that get_metadata returns AgentMetadata instance"""
        metadata = test_agent.get_metadata()
        assert isinstance(metadata, AgentMetadata)
        assert metadata.name == "test_agent"
        assert metadata.version == "1.0.0"

    def test_metadata_includes_capabilities(self, test_agent):
        """Test that metadata includes capabilities"""
        metadata = test_agent.get_metadata()
        assert AgentCapability.SCALPING in metadata.capabilities

    def test_metadata_includes_supported_symbols(self, test_agent):
        """Test that metadata includes supported symbols"""
        metadata = test_agent.get_metadata()
        assert "BTC/USD" in metadata.supported_symbols


class TestLifecycleLogging:
    """Test lifecycle event logging at INFO level (PRD-001 Section 3.1 Item 6)"""

    @pytest.mark.asyncio
    async def test_initialize_logs_at_info_level(self, test_agent, caplog):
        """Test that initialize logs at INFO level"""
        with caplog.at_level(logging.INFO):
            await test_agent.initialize({"test": "config"})

        info_logs = [r for r in caplog.records if r.levelname == "INFO"]
        assert len(info_logs) >= 2  # At least startup and complete

    @pytest.mark.asyncio
    async def test_initialize_logs_include_agent_name(self, test_agent, caplog):
        """Test that initialize logs include agent name"""
        with caplog.at_level(logging.INFO):
            await test_agent.initialize({})

        assert any("test_agent" in log.message for log in caplog.records)

    @pytest.mark.asyncio
    async def test_shutdown_logs_at_info_level(self, test_agent, caplog):
        """Test that shutdown logs at INFO level"""
        await test_agent.initialize({})

        with caplog.at_level(logging.INFO):
            await test_agent.shutdown()

        info_logs = [r for r in caplog.records if r.levelname == "INFO"]
        assert len(info_logs) >= 2  # At least starting and complete

    @pytest.mark.asyncio
    async def test_lifecycle_logs_use_helper_method(self, test_agent, caplog):
        """Test that lifecycle logs use _log_lifecycle helper"""
        with caplog.at_level(logging.INFO):
            test_agent._log_lifecycle("test_event", "Test message")

        assert any("TEST_EVENT" in log.message for log in caplog.records)
        assert any("Test message" in log.message for log in caplog.records)


class TestPrometheusMetrics:
    """Test Prometheus metrics (PRD-001 Section 3.1 Item 7)"""

    @pytest.mark.skipif(not PROMETHEUS_AVAILABLE, reason="Prometheus not available")
    @pytest.mark.asyncio
    async def test_initialize_emits_metric(self, test_agent):
        """Test that initialize emits agent_invocations_total metric"""
        # Get initial count
        initial_count = AGENT_INVOCATIONS_TOTAL.labels(
            agent="test_agent",
            method="initialize",
            outcome="success"
        )._value.get()

        await test_agent.initialize({})

        # Count should have incremented
        final_count = AGENT_INVOCATIONS_TOTAL.labels(
            agent="test_agent",
            method="initialize",
            outcome="success"
        )._value.get()

        assert final_count > initial_count

    @pytest.mark.skipif(not PROMETHEUS_AVAILABLE, reason="Prometheus not available")
    @pytest.mark.asyncio
    async def test_generate_signals_emits_metric(self, test_agent, valid_market_data):
        """Test that generate_signals emits metric"""
        await test_agent.initialize({})

        initial_count = AGENT_INVOCATIONS_TOTAL.labels(
            agent="test_agent",
            method="generate_signals",
            outcome="success"
        )._value.get()

        await test_agent.generate_signals(valid_market_data)

        final_count = AGENT_INVOCATIONS_TOTAL.labels(
            agent="test_agent",
            method="generate_signals",
            outcome="success"
        )._value.get()

        assert final_count > initial_count

    @pytest.mark.skipif(not PROMETHEUS_AVAILABLE, reason="Prometheus not available")
    @pytest.mark.asyncio
    async def test_shutdown_emits_metric(self, test_agent):
        """Test that shutdown emits metric"""
        await test_agent.initialize({})

        initial_count = AGENT_INVOCATIONS_TOTAL.labels(
            agent="test_agent",
            method="shutdown",
            outcome="success"
        )._value.get()

        await test_agent.shutdown()

        final_count = AGENT_INVOCATIONS_TOTAL.labels(
            agent="test_agent",
            method="shutdown",
            outcome="success"
        )._value.get()

        assert final_count > initial_count

    @pytest.mark.skipif(not PROMETHEUS_AVAILABLE, reason="Prometheus not available")
    def test_emit_metric_helper(self, test_agent):
        """Test that _emit_metric helper works correctly"""
        initial_count = AGENT_INVOCATIONS_TOTAL.labels(
            agent="test_agent",
            method="test_method",
            outcome="success"
        )._value.get()

        test_agent._emit_metric("test_method", "success")

        final_count = AGENT_INVOCATIONS_TOTAL.labels(
            agent="test_agent",
            method="test_method",
            outcome="success"
        )._value.get()

        assert final_count == initial_count + 1


class TestAbstractMethods:
    """Test abstract method enforcement (PRD-001 Section 3.1 Items 1-4)"""

    def test_cannot_instantiate_base_class(self):
        """Test that StrategyAgentBase cannot be instantiated directly"""
        with pytest.raises(TypeError):
            StrategyAgentBase()

    def test_subclass_must_implement_get_metadata(self):
        """Test that subclasses must implement get_metadata()"""
        class IncompleteAgent(StrategyAgentBase):
            async def initialize(self, config, redis_client=None):
                pass

            async def generate_signals(self, market_data):
                pass

            async def shutdown(self):
                pass

        with pytest.raises(TypeError):
            IncompleteAgent()

    def test_subclass_must_implement_initialize(self):
        """Test that subclasses must implement initialize()"""
        class IncompleteAgent(StrategyAgentBase):
            @classmethod
            def get_metadata(cls):
                return AgentMetadata(
                    name="incomplete",
                    description="Test",
                    version="1.0.0",
                    author="Test",
                    capabilities=[],
                    supported_symbols=[],
                    supported_timeframes=[]
                )

            async def generate_signals(self, market_data):
                pass

            async def shutdown(self):
                pass

        with pytest.raises(TypeError):
            IncompleteAgent()


class TestValidateSignal:
    """Test signal validation helper (PRD-001 Section 3.1 Item 5)"""

    def test_validate_signal_accepts_valid_signal(self, test_agent):
        """Test that validate_signal accepts valid signals"""
        valid_signal = {
            "timestamp": time.time(),
            "signal_type": "entry",
            "trading_pair": "BTC/USD",
            "size": 0.1,
            "confidence_score": 0.8,
            "agent_id": "test_agent"
        }

        assert test_agent.validate_signal(valid_signal) is True

    def test_validate_signal_rejects_missing_field(self, test_agent):
        """Test that validate_signal rejects signals missing required fields"""
        invalid_signal = {
            "timestamp": time.time(),
            "signal_type": "entry",
            # Missing trading_pair
            "size": 0.1,
            "confidence_score": 0.8,
            "agent_id": "test_agent"
        }

        assert test_agent.validate_signal(invalid_signal) is False

    def test_validate_signal_rejects_invalid_signal_type(self, test_agent):
        """Test that validate_signal rejects invalid signal_type"""
        invalid_signal = {
            "timestamp": time.time(),
            "signal_type": "invalid_type",
            "trading_pair": "BTC/USD",
            "size": 0.1,
            "confidence_score": 0.8,
            "agent_id": "test_agent"
        }

        assert test_agent.validate_signal(invalid_signal) is False

    def test_validate_signal_rejects_negative_size(self, test_agent):
        """Test that validate_signal rejects negative size"""
        invalid_signal = {
            "timestamp": time.time(),
            "signal_type": "entry",
            "trading_pair": "BTC/USD",
            "size": -0.1,
            "confidence_score": 0.8,
            "agent_id": "test_agent"
        }

        assert test_agent.validate_signal(invalid_signal) is False

    def test_validate_signal_rejects_invalid_confidence(self, test_agent):
        """Test that validate_signal rejects confidence outside [0,1]"""
        invalid_signal = {
            "timestamp": time.time(),
            "signal_type": "entry",
            "trading_pair": "BTC/USD",
            "size": 0.1,
            "confidence_score": 1.5,  # > 1.0
            "agent_id": "test_agent"
        }

        assert test_agent.validate_signal(invalid_signal) is False


class TestHealthcheck:
    """Test healthcheck method (PRD-001 Section 3.1 Item 5)"""

    @pytest.mark.asyncio
    async def test_healthcheck_returns_dict(self, test_agent):
        """Test that healthcheck returns a dictionary"""
        health = await test_agent.healthcheck()
        assert isinstance(health, dict)

    @pytest.mark.asyncio
    async def test_healthcheck_includes_status(self, test_agent):
        """Test that healthcheck includes status field"""
        health = await test_agent.healthcheck()
        assert "status" in health
        assert health["status"] in ["healthy", "degraded", "unhealthy"]

    @pytest.mark.asyncio
    async def test_healthcheck_reports_initialized_status(self, test_agent):
        """Test that healthcheck reports initialization status"""
        # Before initialization
        health_before = await test_agent.healthcheck()
        assert health_before["initialized"] is False
        assert health_before["status"] == "unhealthy"

        # After initialization
        await test_agent.initialize({})
        health_after = await test_agent.healthcheck()
        assert health_after["initialized"] is True
        assert health_after["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_healthcheck_reports_shutdown_status(self, test_agent):
        """Test that healthcheck reports shutdown status"""
        await test_agent.initialize({})
        await test_agent.shutdown()

        health = await test_agent.healthcheck()
        assert health["shutdown"] is True
        assert health["status"] == "unhealthy"


class TestErrorHandling:
    """Test error handling (PRD-001 Section 3.1 Item 5)"""

    @pytest.mark.asyncio
    async def test_on_error_logs_error(self, test_agent, caplog):
        """Test that on_error logs errors"""
        error = ValueError("Test error")
        context = {"test_key": "test_value"}

        with caplog.at_level(logging.ERROR):
            await test_agent.on_error(error, context)

        error_logs = [r for r in caplog.records if r.levelname == "ERROR"]
        assert len(error_logs) > 0
        assert any("Test error" in log.message for log in error_logs)

    @pytest.mark.asyncio
    async def test_is_initialized_tracks_state(self, test_agent):
        """Test that is_initialized() tracks state correctly"""
        assert test_agent.is_initialized() is False

        await test_agent.initialize({})
        assert test_agent.is_initialized() is True

    @pytest.mark.asyncio
    async def test_is_shutdown_tracks_state(self, test_agent):
        """Test that is_shutdown() tracks state correctly"""
        await test_agent.initialize({})
        assert test_agent.is_shutdown() is False

        await test_agent.shutdown()
        assert test_agent.is_shutdown() is True


class TestOnSignalPublished:
    """Test on_signal_published callback"""

    @pytest.mark.asyncio
    async def test_on_signal_published_logs_debug(self, test_agent, caplog):
        """Test that on_signal_published logs at DEBUG level"""
        signal = {
            "signal_type": "entry",
            "trading_pair": "BTC/USD"
        }

        with caplog.at_level(logging.DEBUG):
            await test_agent.on_signal_published(signal, "signals:paper")

        debug_logs = [r for r in caplog.records if r.levelname == "DEBUG"]
        assert len(debug_logs) > 0
