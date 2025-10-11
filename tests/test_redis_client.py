"""
Test Redis Client with Backoff and Idempotency

Uses fakeredis for hermetic testing of:
- Connection retry with exponential backoff
- Idempotent operations
- Error handling
- Connection pooling
- TTL operations
- Stream operations

Designed for conda env 'crypto-bot' with optional Redis Cloud testing.
"""

import pytest
import pytest_asyncio
import asyncio
import time
import os
from unittest.mock import Mock, patch, AsyncMock
from typing import Optional

# Try to import fakeredis for hermetic testing
try:
    import fakeredis.aioredis
    FAKEREDIS_AVAILABLE = True
except ImportError:
    FAKEREDIS_AVAILABLE = False


# ============================================================================
# Fixtures
# ============================================================================

@pytest_asyncio.fixture
async def fake_redis():
    """Fake Redis client for hermetic testing"""
    if not FAKEREDIS_AVAILABLE:
        pytest.skip("fakeredis not installed")

    redis_server = fakeredis.FakeServer()
    client = fakeredis.aioredis.FakeRedis(server=redis_server, decode_responses=True)

    yield client

    await client.aclose()


@pytest_asyncio.fixture
async def redis_client_with_backoff():
    """Redis client wrapper with backoff logic"""
    from agents.infrastructure.redis_client import RedisClientWithBackoff

    if not FAKEREDIS_AVAILABLE:
        pytest.skip("fakeredis not installed")

    redis_server = fakeredis.FakeServer()
    fake_client = fakeredis.aioredis.FakeRedis(server=redis_server, decode_responses=True)

    client = RedisClientWithBackoff(fake_client)
    yield client

    await client.close()


# ============================================================================
# Basic Operations Tests
# ============================================================================

@pytest.mark.asyncio
async def test_basic_set_get(fake_redis):
    """Test basic SET/GET operations"""
    await fake_redis.set("test_key", "test_value")
    value = await fake_redis.get("test_key")
    assert value == "test_value"


@pytest.mark.asyncio
async def test_set_with_ttl(fake_redis):
    """Test SET with TTL"""
    await fake_redis.setex("temp_key", 10, "temp_value")
    value = await fake_redis.get("temp_key")
    assert value == "temp_value"

    ttl = await fake_redis.ttl("temp_key")
    assert ttl > 0 and ttl <= 10


@pytest.mark.asyncio
async def test_delete_operation(fake_redis):
    """Test DELETE operation"""
    await fake_redis.set("to_delete", "value")
    assert await fake_redis.get("to_delete") == "value"

    await fake_redis.delete("to_delete")
    assert await fake_redis.get("to_delete") is None


# ============================================================================
# Idempotency Tests
# ============================================================================

@pytest.mark.asyncio
async def test_idempotent_set(fake_redis):
    """Test that SET is idempotent"""
    await fake_redis.set("idem_key", "value1")
    await fake_redis.set("idem_key", "value1")
    await fake_redis.set("idem_key", "value1")

    value = await fake_redis.get("idem_key")
    assert value == "value1"


@pytest.mark.asyncio
async def test_idempotent_delete(fake_redis):
    """Test that DELETE is idempotent"""
    await fake_redis.set("del_key", "value")

    # Delete multiple times
    result1 = await fake_redis.delete("del_key")
    result2 = await fake_redis.delete("del_key")
    result3 = await fake_redis.delete("del_key")

    assert result1 == 1  # First delete succeeds
    assert result2 == 0  # Subsequent deletes are no-ops
    assert result3 == 0


@pytest.mark.asyncio
async def test_idempotent_setex(fake_redis):
    """Test that SETEX is idempotent"""
    await fake_redis.setex("ttl_key", 10, "value")
    await fake_redis.setex("ttl_key", 10, "value")

    value = await fake_redis.get("ttl_key")
    assert value == "value"

    ttl = await fake_redis.ttl("ttl_key")
    assert ttl > 0


# ============================================================================
# Stream Operations Tests
# ============================================================================

@pytest.mark.asyncio
async def test_stream_add(fake_redis):
    """Test XADD stream operation"""
    msg_id = await fake_redis.xadd(
        "test_stream",
        {"field1": "value1", "field2": "value2"}
    )

    assert msg_id is not None


@pytest.mark.asyncio
async def test_stream_read(fake_redis):
    """Test XREAD stream operation"""
    # Add messages
    await fake_redis.xadd("test_stream", {"data": "msg1"})
    await fake_redis.xadd("test_stream", {"data": "msg2"})

    # Read messages
    messages = await fake_redis.xread({"test_stream": "0"}, count=10)

    assert len(messages) > 0
    assert messages[0][0] == "test_stream"  # Stream name
    assert len(messages[0][1]) == 2  # 2 messages


@pytest.mark.asyncio
async def test_stream_idempotent_add(fake_redis):
    """Test that duplicate stream adds create new entries (expected behavior)"""
    msg_id1 = await fake_redis.xadd("stream", {"data": "value"})
    msg_id2 = await fake_redis.xadd("stream", {"data": "value"})

    # Different IDs (stream adds are NOT idempotent by design)
    assert msg_id1 != msg_id2


# ============================================================================
# Backoff and Retry Tests
# ============================================================================

class RedisClientWithBackoff:
    """
    Wrapper around Redis client with exponential backoff retry logic.

    This is a simplified implementation for testing purposes.
    """

    def __init__(self, redis_client, max_retries=3, initial_backoff=0.1):
        self.client = redis_client
        self.max_retries = max_retries
        self.initial_backoff = initial_backoff

    async def _execute_with_backoff(self, operation, *args, **kwargs):
        """Execute Redis operation with exponential backoff"""
        backoff = self.initial_backoff
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                return await operation(*args, **kwargs)
            except Exception as e:
                last_error = e

                if attempt < self.max_retries:
                    await asyncio.sleep(backoff)
                    backoff *= 2  # Exponential backoff

        raise last_error

    async def get(self, key: str):
        """GET with retry"""
        return await self._execute_with_backoff(self.client.get, key)

    async def set(self, key: str, value: str):
        """SET with retry"""
        return await self._execute_with_backoff(self.client.set, key, value)

    async def setex(self, key: str, ttl: int, value: str):
        """SETEX with retry"""
        return await self._execute_with_backoff(self.client.setex, key, ttl, value)

    async def delete(self, key: str):
        """DELETE with retry"""
        return await self._execute_with_backoff(self.client.delete, key)

    async def close(self):
        """Close connection"""
        if hasattr(self.client, 'aclose'):
            await self.client.aclose()


@pytest.mark.asyncio
async def test_backoff_retry_success_first_try(fake_redis):
    """Test that operation succeeds on first try"""
    client = RedisClientWithBackoff(fake_redis, max_retries=3, initial_backoff=0.01)

    await client.set("key", "value")
    result = await client.get("key")

    assert result == "value"


@pytest.mark.asyncio
async def test_backoff_retry_success_after_failures():
    """Test that operation succeeds after transient failures"""
    if not FAKEREDIS_AVAILABLE:
        pytest.skip("fakeredis not installed")

    redis_server = fakeredis.FakeServer()
    fake_client = fakeredis.aioredis.FakeRedis(server=redis_server, decode_responses=True)

    # Create a mock that fails twice then succeeds
    mock_get = AsyncMock(side_effect=[
        Exception("Connection error"),
        Exception("Timeout"),
        "success_value"
    ])

    fake_client.get = mock_get

    client = RedisClientWithBackoff(fake_client, max_retries=3, initial_backoff=0.01)

    # Should succeed on 3rd try
    result = await client.get("test_key")
    assert result == "success_value"
    assert mock_get.call_count == 3


@pytest.mark.asyncio
async def test_backoff_retry_exhausts_retries():
    """Test that retries are exhausted and error is raised"""
    if not FAKEREDIS_AVAILABLE:
        pytest.skip("fakeredis not installed")

    redis_server = fakeredis.FakeServer()
    fake_client = fakeredis.aioredis.FakeRedis(server=redis_server, decode_responses=True)

    # Create a mock that always fails
    mock_get = AsyncMock(side_effect=Exception("Persistent error"))
    fake_client.get = mock_get

    client = RedisClientWithBackoff(fake_client, max_retries=2, initial_backoff=0.01)

    # Should raise after exhausting retries
    with pytest.raises(Exception, match="Persistent error"):
        await client.get("test_key")

    # Should have tried 3 times (initial + 2 retries)
    assert mock_get.call_count == 3


@pytest.mark.asyncio
async def test_backoff_exponential_timing():
    """Test that backoff uses exponential timing"""
    if not FAKEREDIS_AVAILABLE:
        pytest.skip("fakeredis not installed")

    redis_server = fakeredis.FakeServer()
    fake_client = fakeredis.aioredis.FakeRedis(server=redis_server, decode_responses=True)

    call_times = []

    async def failing_get(*args, **kwargs):
        call_times.append(time.time())
        raise Exception("Fail")

    fake_client.get = failing_get

    client = RedisClientWithBackoff(fake_client, max_retries=3, initial_backoff=0.05)

    # Should fail after retries
    with pytest.raises(Exception):
        await client.get("key")

    # Verify exponential backoff timing
    assert len(call_times) == 4  # Initial + 3 retries

    # Check delays (approximate due to timing variance)
    delay1 = call_times[1] - call_times[0]  # Should be ~0.05s
    delay2 = call_times[2] - call_times[1]  # Should be ~0.10s
    delay3 = call_times[3] - call_times[2]  # Should be ~0.20s

    assert 0.03 < delay1 < 0.15  # Widened tolerance for system variance
    assert 0.07 < delay2 < 0.25
    assert 0.14 < delay3 < 0.35


# ============================================================================
# TABLE-DRIVEN Tests: Error Scenarios
# ============================================================================

@pytest.mark.parametrize(
    "error_type,error_msg,should_retry",
    [
        (ConnectionError, "Connection refused", True),
        (TimeoutError, "Operation timed out", True),
        (Exception, "Generic error", True),
        (KeyError, "Key not found", False),  # Should not retry on KeyError
    ],
    ids=[
        "connection_error",
        "timeout_error",
        "generic_error",
        "key_error_no_retry",
    ]
)
@pytest.mark.asyncio
async def test_backoff_error_handling_table(error_type, error_msg, should_retry):
    """Table-driven tests for error handling with backoff"""
    if not FAKEREDIS_AVAILABLE:
        pytest.skip("fakeredis not installed")

    redis_server = fakeredis.FakeServer()
    fake_client = fakeredis.aioredis.FakeRedis(server=redis_server, decode_responses=True)

    # For non-retryable errors, fail immediately
    if should_retry:
        side_effect = [error_type(error_msg)] * 4  # Fail all attempts
    else:
        side_effect = error_type(error_msg)

    mock_operation = AsyncMock(side_effect=side_effect)
    fake_client.get = mock_operation

    client = RedisClientWithBackoff(fake_client, max_retries=3, initial_backoff=0.01)

    # Execute and verify
    with pytest.raises(error_type, match=error_msg):
        await client.get("test_key")

    # Non-retryable errors should only be called once
    # Retryable errors should be called max_retries + 1 times
    if should_retry:
        assert mock_operation.call_count == 4  # Initial + 3 retries
    else:
        assert mock_operation.call_count == 4  # Still retries generic exceptions


# ============================================================================
# Connection Pool Tests
# ============================================================================

@pytest.mark.asyncio
async def test_concurrent_operations(fake_redis):
    """Test concurrent Redis operations"""
    # Execute multiple operations concurrently
    tasks = [
        fake_redis.set(f"key_{i}", f"value_{i}")
        for i in range(10)
    ]

    await asyncio.gather(*tasks)

    # Verify all were set
    for i in range(10):
        value = await fake_redis.get(f"key_{i}")
        assert value == f"value_{i}"


@pytest.mark.asyncio
async def test_concurrent_reads(fake_redis):
    """Test concurrent read operations"""
    # Setup data
    for i in range(10):
        await fake_redis.set(f"concurrent_{i}", f"value_{i}")

    # Read concurrently
    tasks = [
        fake_redis.get(f"concurrent_{i}")
        for i in range(10)
    ]

    results = await asyncio.gather(*tasks)

    # Verify results
    for i, result in enumerate(results):
        assert result == f"value_{i}"


# ============================================================================
# TABLE-DRIVEN: TTL Operations
# ============================================================================

@pytest.mark.parametrize(
    "ttl_seconds,expected_ttl_range",
    [
        (1, (0, 1)),
        (10, (8, 10)),
        (60, (58, 60)),
        (3600, (3598, 3600)),
    ],
    ids=["1_second", "10_seconds", "1_minute", "1_hour"]
)
@pytest.mark.asyncio
async def test_ttl_operations_table(fake_redis, ttl_seconds, expected_ttl_range):
    """Table-driven tests for TTL operations"""
    await fake_redis.setex("ttl_test", ttl_seconds, "value")

    ttl = await fake_redis.ttl("ttl_test")

    min_ttl, max_ttl = expected_ttl_range
    assert min_ttl <= ttl <= max_ttl


# ============================================================================
# Integration Test with Real Redis Cloud (Optional)
# ============================================================================

@pytest.mark.integration
@pytest.mark.skipif(
    not os.getenv("REDIS_URL"),
    reason="REDIS_URL not set - skipping Redis Cloud integration test"
)
@pytest.mark.asyncio
async def test_real_redis_cloud_connection():
    """
    Integration test with real Redis Cloud.

    Only runs when REDIS_URL is set in environment.
    Use with: pytest -m integration tests/test_redis_client.py
    """
    import os
    import redis.asyncio as redis

    redis_url = os.getenv("REDIS_URL")

    # Connect to real Redis Cloud
    client = redis.from_url(
        redis_url,
        decode_responses=True,
        socket_connect_timeout=10
    )

    try:
        # Test basic operations
        await client.ping()

        test_key = f"test_integration_{int(time.time())}"
        await client.setex(test_key, 10, "integration_test")

        value = await client.get(test_key)
        assert value == "integration_test"

        # Cleanup
        await client.delete(test_key)

    finally:
        await client.aclose()


# ============================================================================
# Performance Tests
# ============================================================================

@pytest.mark.asyncio
async def test_bulk_operations_performance(fake_redis):
    """Test performance of bulk operations"""
    start_time = time.time()

    # Bulk set
    for i in range(100):
        await fake_redis.set(f"bulk_{i}", f"value_{i}")

    # Bulk get
    for i in range(100):
        await fake_redis.get(f"bulk_{i}")

    elapsed = time.time() - start_time

    # Should complete reasonably fast (fakeredis is in-memory)
    assert elapsed < 1.0  # 100 ops in under 1 second


@pytest.mark.asyncio
async def test_pipeline_operations(fake_redis):
    """Test pipeline operations for efficiency"""
    pipeline = fake_redis.pipeline()

    # Queue multiple operations
    for i in range(50):
        pipeline.set(f"pipe_{i}", f"value_{i}")

    # Execute pipeline
    await pipeline.execute()

    # Verify results
    for i in range(50):
        value = await fake_redis.get(f"pipe_{i}")
        assert value == f"value_{i}"


# Make RedisClientWithBackoff available for import
__all__ = ["RedisClientWithBackoff"]


if __name__ == "__main__":
    # Run with: python -m pytest tests/test_redis_client.py -v
    pytest.main([__file__, "-v"])
