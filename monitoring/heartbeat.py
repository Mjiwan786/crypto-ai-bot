"""
Redis Heartbeat Monitor

This module provides a Redis-based heartbeat system for external health checks.
It maintains a heartbeat key with TTL that gets refreshed periodically to indicate
the bot is alive and healthy.

Usage:
    from monitoring.heartbeat import start_heartbeat
    await start_heartbeat(redis_client)  # Async version
    start_heartbeat(redis_client)        # Sync version
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional, Union

logger = logging.getLogger(__name__)

# Environment configuration
HEARTBEAT_KEY = os.getenv("HEARTBEAT_KEY", "bot:heartbeat")
HEARTBEAT_TTL_SEC = int(os.getenv("HEARTBEAT_TTL_SEC", "60"))

# Global state
_heartbeat_task: Optional[asyncio.Task] = None
_heartbeat_running = False


def _get_utc_timestamp() -> str:
    """Get current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


async def _async_heartbeat_loop(redis_client, key: str, ttl: int) -> None:
    """Async heartbeat loop that updates Redis key every TTL/2 seconds."""
    global _heartbeat_running
    
    _heartbeat_running = True
    interval = ttl // 2  # Update every half of TTL
    
    logger.info(f"Starting async heartbeat loop: key={key}, ttl={ttl}s, interval={interval}s")
    
    while _heartbeat_running:
        try:
            timestamp = _get_utc_timestamp()
            await redis_client.setex(key, ttl, timestamp)
            logger.debug(f"Heartbeat updated: {key} = {timestamp} (TTL: {ttl}s)")
            
        except Exception as e:
            logger.warning(f"Failed to update heartbeat key {key}: {e}")
            # Continue running despite Redis failures
        
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("Heartbeat loop cancelled")
            break
    
    _heartbeat_running = False
    logger.info("Async heartbeat loop stopped")


def _sync_heartbeat_loop(redis_client, key: str, ttl: int) -> None:
    """Sync heartbeat loop that updates Redis key every TTL/2 seconds."""
    global _heartbeat_running
    
    _heartbeat_running = True
    interval = ttl // 2  # Update every half of TTL
    
    logger.info(f"Starting sync heartbeat loop: key={key}, ttl={ttl}s, interval={interval}s")
    
    while _heartbeat_running:
        try:
            timestamp = _get_utc_timestamp()
            redis_client.setex(key, ttl, timestamp)
            logger.debug(f"Heartbeat updated: {key} = {timestamp} (TTL: {ttl}s)")
            
        except Exception as e:
            logger.warning(f"Failed to update heartbeat key {key}: {e}")
            # Continue running despite Redis failures
        
        time.sleep(interval)
    
    logger.info("Sync heartbeat loop stopped")


async def start_heartbeat(redis_client, key: Optional[str] = None, ttl: Optional[int] = None) -> None:
    """
    Start the async heartbeat loop.

    Args:
        redis_client: Redis client (async or sync)
        key: Heartbeat key (defaults to HEARTBEAT_KEY env var)
        ttl: TTL in seconds (defaults to HEARTBEAT_TTL_SEC env var)

    Raises:
        RuntimeError: If heartbeat is already running
    """
    global _heartbeat_task, _heartbeat_running

    if _heartbeat_running:
        raise RuntimeError("Heartbeat is already running")

    heartbeat_key = key or HEARTBEAT_KEY
    heartbeat_ttl = ttl or HEARTBEAT_TTL_SEC

    # Check if redis_client is async by testing if it has an async ping method
    # redis.asyncio.Redis methods return coroutines, so we check for that
    is_async = False
    if hasattr(redis_client, 'ping'):
        # Try to detect async by checking the module name or by testing a method call
        client_module = type(redis_client).__module__
        if 'asyncio' in client_module or 'aioredis' in client_module:
            is_async = True
        else:
            # Fallback: check if ping returns a coroutine
            try:
                result = redis_client.ping()
                if asyncio.iscoroutine(result):
                    is_async = True
                    # Cancel the pending coroutine
                    result.close()
            except:
                pass

    if is_async:
        # Async Redis client
        logger.info(f"Detected async Redis client: {type(redis_client).__name__}")
        _heartbeat_task = asyncio.create_task(
            _async_heartbeat_loop(redis_client, heartbeat_key, heartbeat_ttl)
        )
    else:
        # Sync Redis client - run in thread
        logger.info(f"Detected sync Redis client: {type(redis_client).__name__}")
        import threading
        def run_sync_heartbeat():
            _sync_heartbeat_loop(redis_client, heartbeat_key, heartbeat_ttl)

        heartbeat_thread = threading.Thread(target=run_sync_heartbeat, daemon=True)
        heartbeat_thread.start()
        logger.info("Started sync heartbeat in background thread")


def stop_heartbeat() -> None:
    """Stop the heartbeat loop."""
    global _heartbeat_task, _heartbeat_running
    
    if not _heartbeat_running:
        logger.warning("Heartbeat is not running")
        return
    
    _heartbeat_running = False
    
    if _heartbeat_task and not _heartbeat_task.done():
        _heartbeat_task.cancel()
        logger.info("Heartbeat task cancelled")
    
    logger.info("Heartbeat stopped")


def is_heartbeat_running() -> bool:
    """Check if heartbeat is currently running."""
    return _heartbeat_running


async def check_heartbeat(redis_client, key: Optional[str] = None) -> dict:
    """
    Check the current heartbeat status.
    
    Args:
        redis_client: Redis client
        key: Heartbeat key (defaults to HEARTBEAT_KEY env var)
        
    Returns:
        Dictionary with heartbeat status information
    """
    heartbeat_key = key or HEARTBEAT_KEY
    
    try:
        if hasattr(redis_client, 'get') and asyncio.iscoroutinefunction(redis_client.get):
            # Async Redis client
            timestamp = await redis_client.get(heartbeat_key)
            ttl = await redis_client.ttl(heartbeat_key)
        else:
            # Sync Redis client
            timestamp = redis_client.get(heartbeat_key)
            ttl = redis_client.ttl(heartbeat_key)
        
        if timestamp is None:
            return {
                "status": "missing",
                "timestamp": None,
                "ttl": None,
                "healthy": False
            }
        
        # Decode timestamp if it's bytes
        if isinstance(timestamp, bytes):
            timestamp = timestamp.decode('utf-8')
        
        return {
            "status": "active",
            "timestamp": timestamp,
            "ttl": ttl,
            "healthy": ttl > 0
        }
        
    except Exception as e:
        logger.error(f"Failed to check heartbeat: {e}")
        return {
            "status": "error",
            "timestamp": None,
            "ttl": None,
            "healthy": False,
            "error": str(e)
        }


# Convenience function for testing
async def test_heartbeat(redis_client, key: Optional[str] = None, duration: int = 30) -> None:
    """
    Test the heartbeat system for a specified duration.
    
    Args:
        redis_client: Redis client
        key: Heartbeat key (defaults to HEARTBEAT_KEY env var)
        duration: Test duration in seconds
    """
    heartbeat_key = key or HEARTBEAT_KEY
    
    print(f"Testing heartbeat system for {duration} seconds...")
    print(f"Key: {heartbeat_key}")
    print(f"TTL: {HEARTBEAT_TTL_SEC}s")
    print(f"Update interval: {HEARTBEAT_TTL_SEC // 2}s")
    
    try:
        await start_heartbeat(redis_client, key)
        print("Heartbeat started successfully")
        
        # Monitor for the specified duration
        for i in range(duration):
            await asyncio.sleep(1)
            status = await check_heartbeat(redis_client, key)
            print(f"  {i+1:2d}s: {status['status']} - TTL: {status['ttl']}s - {status['timestamp']}")
        
    except Exception as e:
        print(f"Test failed: {e}")
    finally:
        stop_heartbeat()
        print("Heartbeat stopped")


if __name__ == "__main__":
    # Example usage and testing
    import redis
    
    async def main():
        # Connect to Redis (adjust URL as needed)
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        
        # Handle Redis Cloud SSL connections
        if "rediss://" in redis_url or "redis-cloud.com" in redis_url:
            # For Redis Cloud, use rediss:// and handle SSL properly
            if redis_url.startswith("redis://"):
                redis_url = redis_url.replace("redis://", "rediss://")
            
            # Create Redis client with SSL support
            redis_client = redis.from_url(redis_url, ssl_cert_reqs=None)
        else:
            redis_client = redis.from_url(redis_url)
        
        try:
            await test_heartbeat(redis_client, duration=10)
        finally:
            if hasattr(redis_client, 'close'):
                await redis_client.close()
    
    asyncio.run(main())
