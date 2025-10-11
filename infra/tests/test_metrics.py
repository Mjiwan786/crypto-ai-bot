#!/usr/bin/env python3
"""
Unit tests for infra.metrics module.

Tests timing decorators, context managers, counters, and resilience metrics.
All tests are hermetic (no external dependencies).
"""

from __future__ import annotations

import asyncio
import logging
import pytest
import time
from unittest.mock import Mock, patch

from infra.metrics import (
    time_operation,
    TimeOperation,
    increment_counter,
    set_gauge,
    record_retry,
    record_throttle,
    record_circuit_breaker_trip,
    set_metrics_backend,
    get_metrics_backend,
)


# ============================================================================
# Timing Decorator Tests
# ============================================================================

class TestTimeOperationDecorator:
    """Test @time_operation decorator."""

    def test_sync_function_timing(self, caplog):
        """Test decorator measures sync function duration."""
        caplog.set_level(logging.INFO)

        @time_operation("test_operation")
        def slow_function():
            time.sleep(0.01)  # 10ms
            return "result"

        result = slow_function()

        assert result == "result"
        assert any("test_operation" in record.message for record in caplog.records)
        assert any("completed" in record.message for record in caplog.records)

    @pytest.mark.asyncio
    async def test_async_function_timing(self, caplog):
        """Test decorator measures async function duration."""
        caplog.set_level(logging.INFO)

        @time_operation("async_operation")
        async def async_function():
            await asyncio.sleep(0.01)  # 10ms
            return "async_result"

        result = await async_function()

        assert result == "async_result"
        assert any("async_operation" in record.message for record in caplog.records)

    def test_decorator_with_component(self, caplog):
        """Test decorator includes component in logs."""
        caplog.set_level(logging.INFO)

        @time_operation("test_op", component="test_component")
        def func():
            return "result"

        func()

        # Check component is in extra fields
        assert any(
            record.component == "test_component"
            for record in caplog.records
            if hasattr(record, "component")
        )

    def test_decorator_handles_exceptions(self, caplog):
        """Test decorator measures duration even when function raises."""
        caplog.set_level(logging.WARNING)

        @time_operation("failing_operation")
        def failing_function():
            raise ValueError("Test error")

        with pytest.raises(ValueError, match="Test error"):
            failing_function()

        # Should still log timing info
        assert any("failing_operation" in record.message for record in caplog.records)

    def test_decorator_with_result_logging(self, caplog):
        """Test decorator can include result in logs."""
        caplog.set_level(logging.INFO)

        @time_operation("test_op", include_result=True)
        def func():
            return {"status": "ok"}

        func()

        # Result should be in log (truncated)
        assert any("test_op" in record.message for record in caplog.records)

    def test_decorator_no_op_safe(self):
        """Test decorator completes even if logging fails."""
        @time_operation("test_op")
        def func():
            return "result"

        # Should not raise even if logging infrastructure is broken
        with patch("infra.metrics.logger", None):
            result = func()
            assert result == "result"


# ============================================================================
# Timing Context Manager Tests
# ============================================================================

class TestTimeOperationContextManager:
    """Test TimeOperation context manager."""

    def test_context_manager_measures_duration(self, caplog):
        """Test context manager measures code block duration."""
        caplog.set_level(logging.INFO)

        with TimeOperation("block_operation"):
            time.sleep(0.01)  # 10ms

        assert any("block_operation" in record.message for record in caplog.records)
        assert any("completed" in record.message for record in caplog.records)

    def test_context_manager_with_component(self, caplog):
        """Test context manager includes component."""
        caplog.set_level(logging.INFO)

        with TimeOperation("test_block", component="test_component"):
            pass

        assert any(
            record.component == "test_component"
            for record in caplog.records
            if hasattr(record, "component")
        )

    def test_context_manager_with_labels(self, caplog):
        """Test context manager includes custom labels."""
        caplog.set_level(logging.INFO)

        with TimeOperation("test_block", labels={"custom": "value"}):
            pass

        # Labels should be in log context
        assert any("test_block" in record.message for record in caplog.records)

    def test_context_manager_handles_exceptions(self, caplog):
        """Test context manager measures duration even on exception."""
        caplog.set_level(logging.WARNING)

        with pytest.raises(ValueError):
            with TimeOperation("failing_block"):
                raise ValueError("Test error")

        # Should still log timing
        assert any("failing_block" in record.message for record in caplog.records)

    def test_context_manager_no_op_safe(self):
        """Test context manager completes even if logging fails."""
        executed = False

        with patch("infra.metrics.logger", None):
            with TimeOperation("test_block"):
                executed = True

        assert executed


# ============================================================================
# Counter Tests
# ============================================================================

class TestCounters:
    """Test counter metrics."""

    def test_increment_counter_basic(self, caplog):
        """Test basic counter increment."""
        caplog.set_level(logging.DEBUG)

        increment_counter("test_counter")

        assert any("test_counter" in record.message for record in caplog.records)

    def test_increment_counter_with_delta(self, caplog):
        """Test counter increment with custom delta."""
        caplog.set_level(logging.DEBUG)

        increment_counter("test_counter", delta=5)

        # Should log the delta
        assert any(
            "test_counter" in record.message and "5" in record.message
            for record in caplog.records
        )

    def test_increment_counter_with_component(self, caplog):
        """Test counter with component label."""
        caplog.set_level(logging.DEBUG)

        increment_counter("test_counter", component="test_component")

        assert any("test_counter" in record.message for record in caplog.records)

    def test_increment_counter_with_labels(self, caplog):
        """Test counter with custom labels."""
        caplog.set_level(logging.DEBUG)

        increment_counter(
            "test_counter",
            labels={"operation": "test", "status": "ok"}
        )

        assert any("test_counter" in record.message for record in caplog.records)

    def test_increment_counter_no_op_safe(self):
        """Test counter increment never raises."""
        # Should not raise even with broken logger
        with patch("infra.metrics.logger", None):
            increment_counter("test_counter")


class TestGauges:
    """Test gauge metrics."""

    def test_set_gauge_basic(self, caplog):
        """Test basic gauge setting."""
        caplog.set_level(logging.DEBUG)

        set_gauge("test_gauge", 42.5)

        assert any("test_gauge" in record.message for record in caplog.records)

    def test_set_gauge_with_component(self, caplog):
        """Test gauge with component label."""
        caplog.set_level(logging.DEBUG)

        set_gauge("queue_depth", 100, component="redis")

        assert any("queue_depth" in record.message for record in caplog.records)

    def test_set_gauge_no_op_safe(self):
        """Test gauge setting never raises."""
        with patch("infra.metrics.logger", None):
            set_gauge("test_gauge", 123)


# ============================================================================
# Resilience Metrics Tests
# ============================================================================

class TestRetryMetrics:
    """Test retry recording."""

    def test_record_retry_basic(self, caplog):
        """Test basic retry recording."""
        caplog.set_level(logging.INFO)

        record_retry("test_operation", attempt=1, max_retries=3)

        assert any("Retry attempt" in record.message for record in caplog.records)
        assert any("test_operation" in record.message for record in caplog.records)

    def test_record_retry_with_backoff(self, caplog):
        """Test retry recording with backoff."""
        caplog.set_level(logging.INFO)

        record_retry(
            "test_operation",
            attempt=2,
            max_retries=3,
            backoff_ms=1000
        )

        # Should include backoff in log
        assert any("Retry" in record.message for record in caplog.records)

    def test_record_retry_with_error(self, caplog):
        """Test retry recording with error message."""
        caplog.set_level(logging.INFO)

        record_retry(
            "test_operation",
            attempt=1,
            max_retries=3,
            error="Rate limited"
        )

        assert any("Retry" in record.message for record in caplog.records)

    def test_record_retry_no_op_safe(self):
        """Test retry recording never raises."""
        with patch("infra.metrics.logger", None):
            record_retry("test_op", 1, 3)


class TestThrottleMetrics:
    """Test throttle recording."""

    def test_record_throttle_basic(self, caplog):
        """Test basic throttle recording."""
        caplog.set_level(logging.WARNING)

        record_throttle("test_operation")

        assert any("throttled" in record.message.lower() for record in caplog.records)

    def test_record_throttle_with_reason(self, caplog):
        """Test throttle recording with reason."""
        caplog.set_level(logging.WARNING)

        record_throttle("test_operation", reason="rate_limit")

        assert any("rate_limit" in record.message for record in caplog.records)

    def test_record_throttle_with_duration(self, caplog):
        """Test throttle recording with duration."""
        caplog.set_level(logging.WARNING)

        record_throttle(
            "test_operation",
            reason="backpressure",
            duration_ms=1000
        )

        assert any("throttled" in record.message.lower() for record in caplog.records)

    def test_record_throttle_no_op_safe(self):
        """Test throttle recording never raises."""
        with patch("infra.metrics.logger", None):
            record_throttle("test_op")


class TestCircuitBreakerMetrics:
    """Test circuit breaker recording."""

    def test_record_circuit_breaker_trip_open(self, caplog):
        """Test recording circuit breaker opening."""
        caplog.set_level(logging.ERROR)

        record_circuit_breaker_trip("test_circuit", "open", failure_count=5)

        assert any("Circuit breaker" in record.message for record in caplog.records)
        assert any("open" in record.message for record in caplog.records)

    def test_record_circuit_breaker_trip_half_open(self, caplog):
        """Test recording circuit breaker half-open."""
        caplog.set_level(logging.ERROR)

        record_circuit_breaker_trip("test_circuit", "half_open")

        assert any("half_open" in record.message for record in caplog.records)

    def test_record_circuit_breaker_trip_with_error(self, caplog):
        """Test circuit breaker recording with error."""
        caplog.set_level(logging.ERROR)

        record_circuit_breaker_trip(
            "test_circuit",
            "open",
            failure_count=5,
            error="Connection timeout"
        )

        assert any("Circuit breaker" in record.message for record in caplog.records)

    def test_record_circuit_breaker_no_op_safe(self):
        """Test circuit breaker recording never raises."""
        with patch("infra.metrics.logger", None):
            record_circuit_breaker_trip("test_circuit", "open")


# ============================================================================
# Metrics Backend Tests
# ============================================================================

class TestMetricsBackend:
    """Test metrics backend configuration."""

    def test_set_and_get_backend(self):
        """Test setting and getting metrics backend."""
        mock_backend = Mock()

        set_metrics_backend(mock_backend)
        backend = get_metrics_backend()

        assert backend is mock_backend

    def test_backend_initially_none(self):
        """Test backend is None by default."""
        # Reset backend
        set_metrics_backend(None)

        backend = get_metrics_backend()
        assert backend is None

    def test_timing_with_redis_backend(self, caplog):
        """Test timing metric publishes to Redis backend."""
        caplog.set_level(logging.INFO)

        mock_redis = Mock()
        mock_redis.xadd = Mock()

        set_metrics_backend(mock_redis)

        @time_operation("test_op")
        def func():
            return "result"

        func()

        # Should call xadd on Redis backend
        mock_redis.xadd.assert_called()
        call_args = mock_redis.xadd.call_args
        assert call_args[0][0] == "metrics:timing"

        # Cleanup
        set_metrics_backend(None)

    def test_counter_with_redis_backend(self):
        """Test counter publishes to Redis backend."""
        mock_redis = Mock()
        mock_redis.hincrby = Mock()

        set_metrics_backend(mock_redis)

        increment_counter("test_counter", delta=5)

        # Should call hincrby on Redis backend
        mock_redis.hincrby.assert_called()

        # Cleanup
        set_metrics_backend(None)

    def test_gauge_with_redis_backend(self):
        """Test gauge publishes to Redis backend."""
        mock_redis = Mock()
        mock_redis.hset = Mock()

        set_metrics_backend(mock_redis)

        set_gauge("test_gauge", 42)

        # Should call hset on Redis backend
        mock_redis.hset.assert_called()

        # Cleanup
        set_metrics_backend(None)


# ============================================================================
# Integration Tests
# ============================================================================

class TestIntegration:
    """Test realistic integration scenarios."""

    @pytest.mark.asyncio
    async def test_complete_workflow_with_metrics(self, caplog):
        """Test complete workflow with timing, retries, and counters."""
        caplog.set_level(logging.DEBUG)  # Capture DEBUG level for counter logs

        @time_operation("api_call", component="kraken")
        async def fetch_data(fail_first=False):
            if fail_first:
                raise ValueError("Temporary error")
            await asyncio.sleep(0.01)
            return {"data": "ok"}

        # First attempt fails
        try:
            await fetch_data(fail_first=True)
        except ValueError:
            record_retry("api_call", attempt=1, max_retries=3, backoff_ms=100)

        # Second attempt succeeds
        result = await fetch_data(fail_first=False)

        # Increment success counter
        increment_counter("api_calls_success", component="kraken")

        # Verify all metrics logged
        assert any("api_call" in record.message for record in caplog.records)
        assert any("Retry" in record.message for record in caplog.records)
        assert any("api_calls_success" in record.message for record in caplog.records)
        assert result == {"data": "ok"}

    def test_circuit_breaker_workflow(self, caplog):
        """Test circuit breaker workflow with metrics."""
        caplog.set_level(logging.DEBUG)  # Capture all levels including WARNING for throttle

        # Simulate 5 failures
        for i in range(5):
            record_retry("api_call", attempt=i+1, max_retries=3)

        # Circuit breaker opens
        record_circuit_breaker_trip("api_circuit", "open", failure_count=5)

        # Record throttling while circuit is open
        record_throttle("api_call", reason="circuit_open")

        # Verify metrics
        assert any("Circuit breaker" in record.message for record in caplog.records)
        assert any("throttled" in record.message.lower() for record in caplog.records)

    def test_no_op_safe_complete_workflow(self):
        """Test entire workflow is no-op safe."""
        # Break all logging
        with patch("infra.metrics.logger", None):
            @time_operation("test_op")
            def func():
                increment_counter("test")
                record_retry("test", 1, 3)
                record_throttle("test")
                record_circuit_breaker_trip("test", "open")
                return "result"

            # Should complete without errors
            result = func()
            assert result == "result"


# Run tests with: pytest infra/tests/test_metrics.py -v
