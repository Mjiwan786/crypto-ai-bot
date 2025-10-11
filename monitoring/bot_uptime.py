"""
Bot Uptime Management

This module manages bot uptime tracking via Redis keys for SLO monitoring.
It handles process lifecycle events (start/stop) and maintains uptime status.
"""

import asyncio
import time
import json
import signal
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class BotUptimeManager:
    """
    Manages bot uptime tracking and process lifecycle events.
    """
    
    def __init__(self, redis_client, ttl_seconds: int = 300):
        """
        Initialize bot uptime manager.
        
        Args:
            redis_client: Redis client instance
            ttl_seconds: TTL for uptime key in seconds (default: 5 minutes)
        """
        self.redis = redis_client
        self.ttl_seconds = ttl_seconds
        self.running = False
        self.heartbeat_task: Optional[asyncio.Task] = None
        self.start_time = time.time()
        self.logger = logger
        
    async def start(self) -> None:
        """
        Start uptime tracking and heartbeat.
        """
        if self.running:
            return
            
        self.running = True
        self.start_time = time.time()
        
        # Set initial uptime key
        await self._set_uptime_key()
        
        # Start heartbeat task
        self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        
        self.logger.info("Bot uptime tracking started")
    
    async def stop(self) -> None:
        """
        Stop uptime tracking and clear Redis key.
        """
        if not self.running:
            return
            
        self.running = False
        
        # Cancel heartbeat task
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
            try:
                await self.heartbeat_task
            except asyncio.CancelledError:
                pass
        
        # Clear uptime key
        await self._clear_uptime_key()
        
        self.logger.info("Bot uptime tracking stopped")
    
    async def _set_uptime_key(self) -> None:
        """
        Set bot uptime key in Redis.
        """
        try:
            uptime_data = {
                "start_time": str(int(self.start_time)),
                "last_seen": str(int(time.time())),
                "status": "running",
                "uptime_seconds": str(int(time.time() - self.start_time)),
                "pid": str(os.getpid()) if 'os' in globals() else "unknown"
            }
            
            # Set with TTL for automatic cleanup (handle both sync and async)
            if hasattr(self.redis, 'setex') and asyncio.iscoroutinefunction(self.redis.setex):
                await self.redis.setex(
                    "bot:up", 
                    self.ttl_seconds, 
                    json.dumps(uptime_data)
                )
            else:
                self.redis.setex(
                    "bot:up", 
                    self.ttl_seconds, 
                    json.dumps(uptime_data)
                )
            
        except Exception as e:
            self.logger.error(f"Failed to set bot uptime key: {e}")
    
    async def _clear_uptime_key(self) -> None:
        """
        Clear bot uptime key from Redis.
        """
        try:
            if hasattr(self.redis, 'delete') and asyncio.iscoroutinefunction(self.redis.delete):
                await self.redis.delete("bot:up")
            else:
                self.redis.delete("bot:up")
            self.logger.info("Bot uptime key cleared")
        except Exception as e:
            self.logger.error(f"Failed to clear bot uptime key: {e}")
    
    async def _heartbeat_loop(self) -> None:
        """
        Heartbeat loop to maintain uptime key.
        """
        while self.running:
            try:
                await self._set_uptime_key()
                await asyncio.sleep(30)  # Update every 30 seconds
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in uptime heartbeat: {e}")
                await asyncio.sleep(5)  # Back off on error
    
    async def get_uptime_status(self) -> Dict[str, Any]:
        """
        Get current uptime status.
        
        Returns:
            Dictionary with uptime information
        """
        try:
            if hasattr(self.redis, 'get') and asyncio.iscoroutinefunction(self.redis.get):
                uptime_data = await self.redis.get("bot:up")
            else:
                uptime_data = self.redis.get("bot:up")
                
            if uptime_data:
                if isinstance(uptime_data, bytes):
                    uptime_data = uptime_data.decode()
                data = json.loads(uptime_data)
                return {
                    "status": "running",
                    "start_time": int(data.get("start_time", 0)),
                    "last_seen": int(data.get("last_seen", 0)),
                    "uptime_seconds": int(time.time() - self.start_time),
                    "ttl_seconds": self.ttl_seconds
                }
            else:
                return {
                    "status": "stopped",
                    "uptime_seconds": 0
                }
        except Exception as e:
            self.logger.error(f"Failed to get uptime status: {e}")
            return {"status": "error", "error": str(e)}


# Global instance for easy access
_uptime_manager: Optional[BotUptimeManager] = None


async def start_bot_uptime_tracking(redis_client, ttl_seconds: int = 300) -> BotUptimeManager:
    """
    Start bot uptime tracking.
    
    Args:
        redis_client: Redis client instance
        ttl_seconds: TTL for uptime key in seconds
        
    Returns:
        BotUptimeManager instance
    """
    global _uptime_manager
    
    if _uptime_manager is None:
        _uptime_manager = BotUptimeManager(redis_client, ttl_seconds)
    
    await _uptime_manager.start()
    return _uptime_manager


async def stop_bot_uptime_tracking() -> None:
    """
    Stop bot uptime tracking and clear Redis key.
    """
    global _uptime_manager
    
    if _uptime_manager:
        await _uptime_manager.stop()
        _uptime_manager = None


def get_uptime_manager() -> Optional[BotUptimeManager]:
    """
    Get current uptime manager instance.
    
    Returns:
        BotUptimeManager instance or None
    """
    return _uptime_manager


# Signal handlers for graceful shutdown
def setup_graceful_shutdown():
    """
    Setup signal handlers for graceful shutdown.
    """
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        asyncio.create_task(stop_bot_uptime_tracking())
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)


# Context manager for automatic lifecycle management
class BotUptimeContext:
    """
    Context manager for automatic bot uptime tracking.
    """
    
    def __init__(self, redis_client, ttl_seconds: int = 300):
        self.redis_client = redis_client
        self.ttl_seconds = ttl_seconds
        self.manager: Optional[BotUptimeManager] = None
    
    async def __aenter__(self):
        self.manager = await start_bot_uptime_tracking(self.redis_client, self.ttl_seconds)
        return self.manager
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.manager:
            await self.manager.stop()


# Example usage
if __name__ == "__main__":
    import redis
    import os
    
    async def main():
        # Connect to Redis
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        redis_client = redis.from_url(redis_url)
        
        # Setup graceful shutdown
        setup_graceful_shutdown()
        
        # Start uptime tracking
        async with BotUptimeContext(redis_client) as uptime_manager:
            print("Bot uptime tracking started")
            
            # Simulate bot running
            for i in range(10):
                status = await uptime_manager.get_uptime_status()
                print(f"Uptime status: {status}")
                await asyncio.sleep(5)
        
        print("Bot uptime tracking stopped")
    
    asyncio.run(main())
