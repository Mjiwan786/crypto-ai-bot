"""
SLO Integration Example

Example of how to integrate the SLO monitoring system into the main application.

This shows how to:
1. Start the SLO API server
2. Set up Redis client for SLO metrics
3. Initialize SLO monitoring in the main application
"""

import asyncio
import logging
from typing import Optional

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import SLO components
from monitoring.slo_status_api import start_slo_api_server, set_redis_client
from monitoring.slo_metrics import get_slo_collector
from monitoring.metrics_exporter import start_metrics_server, heartbeat


async def setup_slo_monitoring(redis_client, start_api: bool = True):
    """
    Set up SLO monitoring for the application.
    
    Args:
        redis_client: Redis client instance
        start_api: Whether to start the SLO API server
    """
    try:
        # Set Redis client for SLO API
        set_redis_client(redis_client)
        
        # Start metrics server if not already started
        try:
            start_metrics_server()
            logger.info("Prometheus metrics server started")
        except RuntimeError:
            logger.info("Prometheus metrics server already running")
        
        # Start SLO API server in background if requested
        if start_api:
            import threading
            api_thread = threading.Thread(
                target=start_slo_api_server,
                daemon=True
            )
            api_thread.start()
            logger.info("SLO API server started in background")
        
        # Initialize SLO collector
        slo_collector = get_slo_collector(redis_client)
        logger.info("SLO monitoring initialized")
        
        return slo_collector
        
    except Exception as e:
        logger.error(f"Failed to setup SLO monitoring: {e}")
        raise


async def slo_heartbeat_task(slo_collector, redis_client):
    """
    Background task to maintain SLO metrics and heartbeat.
    
    Args:
        slo_collector: SLO metrics collector instance
        redis_client: Redis client instance
    """
    while True:
        try:
            # Update bot uptime
            await slo_collector.set_bot_uptime()
            
            # Update Prometheus heartbeat
            heartbeat()
            
            # Log current SLO status
            status = await slo_collector.get_e2e_latency_summary(window_minutes=5)
            if status.get("total_events", 0) > 0:
                logger.info(f"SLO Status - Events: {status['total_events']}, "
                          f"P95 Latency: {status['latency_ms']['p95']}ms")
            
        except Exception as e:
            logger.error(f"Error in SLO heartbeat: {e}")
        
        # Wait 30 seconds before next update
        await asyncio.sleep(30)


async def example_usage():
    """
    Example of how to use SLO monitoring in your application.
    """
    # This would be your actual Redis client
    # import redis
    # redis_client = redis.Redis(host='localhost', port=6379, db=0)
    
    # For this example, we'll use a mock
    class MockRedisClient:
        def xadd(self, stream, data, **kwargs):
            logger.info(f"Mock Redis XADD: {stream} -> {data}")
        
        def xrevrange(self, stream, **kwargs):
            return []
    
    redis_client = MockRedisClient()
    
    try:
        # Set up SLO monitoring
        slo_collector = await setup_slo_monitoring(redis_client, start_api=True)
        
        # Start heartbeat task
        heartbeat_task = asyncio.create_task(
            slo_heartbeat_task(slo_collector, redis_client)
        )
        
        # Simulate some activity
        logger.info("Simulating trading activity...")
        
        # Record some sample metrics
        await slo_collector.record_e2e_latency(
            agent="scalper",
            stream="signals:paper",
            latency_ms=45.2,
            signal_payload={"symbol": "BTC/USD", "price": 50000}
        )
        
        await slo_collector.record_stream_lag(
            stream="md:trades",
            consumer="strategy_consumer",
            lag_seconds=0.3
        )
        
        # Check SLO status
        status = await slo_collector.get_e2e_latency_summary(window_minutes=1)
        logger.info(f"Current latency summary: {status}")
        
        # Let it run for a bit
        await asyncio.sleep(60)
        
        # Clean up
        heartbeat_task.cancel()
        await slo_collector.clear_bot_uptime()
        
    except Exception as e:
        logger.error(f"Error in example: {e}")


if __name__ == "__main__":
    # Run the example
    asyncio.run(example_usage())

