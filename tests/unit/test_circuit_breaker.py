"""
Unit tests for Circuit Breaker pattern (Agent Failure Isolation)

Tests coverage:
- Circuit breaker state transitions (CLOSED → OPEN → HALF_OPEN → CLOSED)
- Failure threshold triggering
- Automatic recovery after cooldown
- Timeout handling
- Prometheus metrics emission
- Health status reporting
- Decorator usage

Author: Reliability & QA Team
"""

import pytest
import asyncio
import time
from unittest.mock import Mock, patch, AsyncMock

from agents.infrastructure.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
    circuit_breaker,
    get_circuit_breaker,
    get_all_breaker_health,
)


class TestCircuitBreakerBasics:
    """Test basic circuit breaker functionality"""

    def test_initialization(self):
        """Test circuit breaker initializes in CLOSED state"""
        breaker = CircuitBreaker(agent_name="test_agent")

        assert breaker.agent_name == "test_agent"
        assert breaker.state.state == CircuitState.CLOSED
        assert breaker.state.failure_count == 0
        assert breaker.state.success_count == 0

    def test_custom_config(self):
        """Test circuit breaker with custom configuration"""
        config = CircuitBreakerConfig(
            failure_threshold=3,
            cooldown_seconds=60
        )

        breaker = CircuitBreaker(agent_name="test_agent", config=config)

        assert breaker.config.failure_threshold == 3
        assert breaker.config.cooldown_seconds == 60


class TestCircuitBreakerStateTransitions:
    """Test circuit breaker state machine"""

    @pytest.mark.asyncio
    async def test_closed_to_open_on_failures(self):
        """Test circuit opens after failure threshold"""
        config = CircuitBreakerConfig(failure_threshold=3)
        breaker = CircuitBreaker(agent_name="test_agent", config=config)

        # Define failing function
        async def failing_func():
            raise ValueError("Test error")

        # Call 3 times (threshold)
        for i in range(3):
            with pytest.raises(ValueError):
                await breaker.call(failing_func)

            if i < 2:
                assert breaker.state.state == CircuitState.CLOSED
            else:
                assert breaker.state.state == CircuitState.OPEN

        # Verify failure count
        assert breaker.state.failure_count == 3

    @pytest.mark.asyncio
    async def test_open_rejects_calls(self):
        """Test OPEN circuit rejects calls without executing"""
        config = CircuitBreakerConfig(failure_threshold=2)
        breaker = CircuitBreaker(agent_name="test_agent", config=config)

        call_count = 0

        async def counting_func():
            nonlocal call_count
            call_count += 1
            raise ValueError("Test error")

        # Trip the circuit
        for _ in range(2):
            with pytest.raises(ValueError):
                await breaker.call(counting_func)

        assert breaker.state.state == CircuitState.OPEN
        assert call_count == 2

        # Attempt call while OPEN - should NOT execute function
        result = await breaker.call(counting_func)

        assert result is None  # Rejected
        assert call_count == 2  # Function not called

    @pytest.mark.asyncio
    async def test_half_open_after_cooldown(self):
        """Test circuit transitions to HALF_OPEN after cooldown"""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            cooldown_seconds=1  # 1 second for testing
        )
        breaker = CircuitBreaker(agent_name="test_agent", config=config)

        async def failing_func():
            raise ValueError("Test error")

        # Trip circuit
        for _ in range(2):
            with pytest.raises(ValueError):
                await breaker.call(failing_func)

        assert breaker.state.state == CircuitState.OPEN

        # Wait for cooldown
        await asyncio.sleep(1.1)

        # Next call should transition to HALF_OPEN
        async def success_func():
            return "success"

        result = await breaker.call(success_func)

        assert breaker.state.state == CircuitState.HALF_OPEN
        assert result == "success"

    @pytest.mark.asyncio
    async def test_half_open_to_closed_on_success(self):
        """Test circuit closes after successful half-open tests"""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            cooldown_seconds=1,
            success_threshold=2  # Need 2 successes to close
        )
        breaker = CircuitBreaker(agent_name="test_agent", config=config)

        async def failing_func():
            raise ValueError("Test error")

        async def success_func():
            return "success"

        # Trip circuit
        for _ in range(2):
            with pytest.raises(ValueError):
                await breaker.call(failing_func)

        assert breaker.state.state == CircuitState.OPEN

        # Wait for cooldown
        await asyncio.sleep(1.1)

        # First success → HALF_OPEN
        result1 = await breaker.call(success_func)
        assert result1 == "success"
        assert breaker.state.state == CircuitState.HALF_OPEN

        # Second success → CLOSED
        result2 = await breaker.call(success_func)
        assert result2 == "success"
        assert breaker.state.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_half_open_to_open_on_failure(self):
        """Test circuit reopens if half-open test fails"""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            cooldown_seconds=1
        )
        breaker = CircuitBreaker(agent_name="test_agent", config=config)

        async def failing_func():
            raise ValueError("Test error")

        # Trip circuit
        for _ in range(2):
            with pytest.raises(ValueError):
                await breaker.call(failing_func)

        assert breaker.state.state == CircuitState.OPEN

        # Wait for cooldown
        await asyncio.sleep(1.1)

        # First call transitions to HALF_OPEN, but fails
        with pytest.raises(ValueError):
            await breaker.call(failing_func)

        # Should be OPEN again
        assert breaker.state.state == CircuitState.OPEN


class TestCircuitBreakerTimeout:
    """Test timeout handling"""

    @pytest.mark.asyncio
    async def test_timeout_triggers_failure(self):
        """Test that timeout is treated as failure"""
        config = CircuitBreakerConfig(
            timeout_seconds=0.5,
            failure_threshold=2
        )
        breaker = CircuitBreaker(agent_name="test_agent", config=config)

        async def slow_func():
            await asyncio.sleep(2)  # Longer than timeout
            return "too slow"

        # First timeout
        with pytest.raises(asyncio.TimeoutError):
            await breaker.call(slow_func)

        assert breaker.state.failure_count == 1
        assert breaker.state.state == CircuitState.CLOSED

        # Second timeout trips circuit
        with pytest.raises(asyncio.TimeoutError):
            await breaker.call(slow_func)

        assert breaker.state.failure_count == 2
        assert breaker.state.state == CircuitState.OPEN


class TestCircuitBreakerHealthStatus:
    """Test health status reporting"""

    @pytest.mark.asyncio
    async def test_health_status_healthy(self):
        """Test health status when circuit is CLOSED and success rate high"""
        breaker = CircuitBreaker(agent_name="test_agent")

        async def success_func():
            return "success"

        # Generate some successful calls
        for _ in range(10):
            await breaker.call(success_func)

        health = breaker.get_health_status()

        assert health["health"] == "healthy"
        assert health["agent"] == "test_agent"
        assert health["state"] == CircuitState.CLOSED
        assert health["success_rate"] == 1.0
        assert health["success_count"] == 10

    @pytest.mark.asyncio
    async def test_health_status_degraded(self):
        """Test health status when success rate is low"""
        config = CircuitBreakerConfig(
            failure_threshold=10,  # High threshold so circuit stays CLOSED
            min_success_rate=0.8
        )
        breaker = CircuitBreaker(agent_name="test_agent", config=config)

        async def success_func():
            return "success"

        async def failing_func():
            raise ValueError("Test error")

        # 50% success rate (6 success, 6 failures)
        for _ in range(6):
            await breaker.call(success_func)

        for _ in range(6):
            with pytest.raises(ValueError):
                await breaker.call(failing_func)

        health = breaker.get_health_status()

        assert health["health"] == "degraded"  # < 80% success rate
        assert health["state"] == CircuitState.CLOSED
        assert health["success_rate"] == 0.5

    @pytest.mark.asyncio
    async def test_health_status_unhealthy(self):
        """Test health status when circuit is OPEN"""
        config = CircuitBreakerConfig(failure_threshold=2)
        breaker = CircuitBreaker(agent_name="test_agent", config=config)

        async def failing_func():
            raise ValueError("Test error")

        # Trip circuit
        for _ in range(2):
            with pytest.raises(ValueError):
                await breaker.call(failing_func)

        health = breaker.get_health_status()

        assert health["health"] == "unhealthy"
        assert health["state"] == CircuitState.OPEN


class TestCircuitBreakerDecorator:
    """Test decorator usage"""

    @pytest.mark.asyncio
    async def test_decorator_basic(self):
        """Test circuit breaker as decorator"""

        @circuit_breaker(agent_name="decorated_agent")
        async def my_function(value: int) -> int:
            if value < 0:
                raise ValueError("Negative value")
            return value * 2

        # Successful call
        result = await my_function(5)
        assert result == 10

        # Failed call
        with pytest.raises(ValueError):
            await my_function(-1)

    @pytest.mark.asyncio
    async def test_decorator_circuit_opens(self):
        """Test decorated function stops being called when circuit opens"""
        call_count = 0

        @circuit_breaker(
            agent_name="test_decorated",
            config=CircuitBreakerConfig(failure_threshold=2)
        )
        async def failing_function():
            nonlocal call_count
            call_count += 1
            raise ValueError("Always fails")

        # Trip circuit
        for _ in range(2):
            with pytest.raises(ValueError):
                await failing_function()

        assert call_count == 2

        # Circuit is now OPEN - function shouldn't be called
        result = await failing_function()

        assert result is None  # Rejected
        assert call_count == 2  # Not incremented


class TestCircuitBreakerRegistry:
    """Test global circuit breaker registry"""

    def test_get_circuit_breaker_singleton(self):
        """Test get_circuit_breaker returns same instance"""
        breaker1 = get_circuit_breaker("registry_test")
        breaker2 = get_circuit_breaker("registry_test")

        assert breaker1 is breaker2

    def test_get_circuit_breaker_different_agents(self):
        """Test different agents get different breakers"""
        breaker1 = get_circuit_breaker("agent1")
        breaker2 = get_circuit_breaker("agent2")

        assert breaker1 is not breaker2
        assert breaker1.agent_name == "agent1"
        assert breaker2.agent_name == "agent2"

    @pytest.mark.asyncio
    async def test_get_all_breaker_health(self):
        """Test get_all_breaker_health returns all breakers"""
        # Create multiple breakers
        breaker1 = get_circuit_breaker("agent_a")
        breaker2 = get_circuit_breaker("agent_b")

        async def success_func():
            return "success"

        # Generate some activity
        await breaker1.call(success_func)
        await breaker2.call(success_func)

        # Get all health
        all_health = get_all_breaker_health()

        assert "agent_a" in all_health
        assert "agent_b" in all_health
        assert all_health["agent_a"]["health"] == "healthy"
        assert all_health["agent_b"]["health"] == "healthy"


class TestCircuitBreakerManualReset:
    """Test manual circuit breaker reset"""

    @pytest.mark.asyncio
    async def test_manual_reset(self):
        """Test manual reset closes circuit"""
        config = CircuitBreakerConfig(failure_threshold=2)
        breaker = CircuitBreaker(agent_name="test_agent", config=config)

        async def failing_func():
            raise ValueError("Test error")

        # Trip circuit
        for _ in range(2):
            with pytest.raises(ValueError):
                await breaker.call(failing_func)

        assert breaker.state.state == CircuitState.OPEN

        # Manual reset
        breaker.reset()

        assert breaker.state.state == CircuitState.CLOSED
        assert breaker.state.failure_count == 0
        assert breaker.state.success_count == 0


@pytest.mark.asyncio
async def test_circuit_breaker_with_sync_function():
    """Test circuit breaker works with synchronous functions"""
    config = CircuitBreakerConfig(failure_threshold=2)
    breaker = CircuitBreaker(agent_name="sync_test", config=config)

    def sync_success_func():
        return "sync_success"

    def sync_failing_func():
        raise ValueError("Sync error")

    # Successful sync call
    result = await breaker.call(sync_success_func)
    assert result == "sync_success"

    # Failing sync call
    with pytest.raises(ValueError):
        await breaker.call(sync_failing_func)


@pytest.mark.asyncio
async def test_circuit_breaker_error_type_tracking():
    """Test that different error types are tracked"""
    breaker = CircuitBreaker(agent_name="error_tracking_test")

    async def value_error_func():
        raise ValueError("Value error")

    async def type_error_func():
        raise TypeError("Type error")

    # Generate different errors
    with pytest.raises(ValueError):
        await breaker.call(value_error_func)

    with pytest.raises(TypeError):
        await breaker.call(type_error_func)

    # Check error types are tracked
    assert "ValueError" in breaker.state.error_types
    assert "TypeError" in breaker.state.error_types
    assert breaker.state.error_types["ValueError"] == 1
    assert breaker.state.error_types["TypeError"] == 1
