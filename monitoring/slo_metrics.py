"""
SLO Metrics Redis Integration

This module provides Redis-based metrics collection for SLO monitoring.
It handles end-to-end latency tracking and stream lag monitoring via Redis streams.
"""

import time
import hashlib
import json
import asyncio
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


class SLOMetricsCollector:
    """
    Collects SLO metrics and publishes them to Redis streams for monitoring.
    """
    
    def __init__(self, redis_client):
        """
        Initialize SLO metrics collector.
        
        Args:
            redis_client: Redis client instance
        """
        self.redis = redis_client
        self.logger = logger
        
    async def record_e2e_latency(
        self, 
        agent: str, 
        stream: str, 
        latency_ms: float,
        signal_payload: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Record end-to-end publish latency to Redis metrics stream.
        
        Args:
            agent: Agent name (e.g., "signal_processor", "scalper")
            stream: Stream name (e.g., "signals:paper", "signals:live")
            latency_ms: Latency in milliseconds
            signal_payload: Optional signal payload for duplicate detection
        """
        try:
            # Create compact event for Redis stream
            event_data = {
                "ts": str(int(time.time() * 1000)),  # Timestamp in ms
                "ms": str(int(latency_ms)),  # Latency in ms
                "agent": agent,
                "stream": stream,
            }
            
            # Add signal hash for duplicate detection if payload provided
            if signal_payload:
                signal_str = json.dumps(signal_payload, sort_keys=True)
                signal_hash = hashlib.md5(signal_str.encode()).hexdigest()[:8]
                event_data["hash"] = signal_hash
            
            # Publish to Redis metrics stream (handle both sync and async)
            if hasattr(self.redis, 'xadd') and asyncio.iscoroutinefunction(self.redis.xadd):
                await self.redis.xadd("metrics:signals:e2e", event_data, maxlen=10000, approximate=True)
            else:
                self.redis.xadd("metrics:signals:e2e", event_data, maxlen=10000, approximate=True)
            
            # Also update Prometheus metrics
            try:
                from monitoring.metrics_exporter import observe_publish_latency_ms
                observe_publish_latency_ms(agent, stream, latency_ms)
            except ImportError:
                pass  # Prometheus not available
            
        except Exception as e:
            self.logger.error(f"Failed to record e2e latency: {e}")
    
    async def record_stream_lag(
        self, 
        stream: str, 
        consumer: str, 
        lag_seconds: float
    ) -> None:
        """
        Record stream lag to Redis metrics stream.
        
        Args:
            stream: Stream name (e.g., "md:trades", "md:spread")
            consumer: Consumer name (e.g., "strategy_consumer")
            lag_seconds: Lag in seconds (now - ts_last_md)
        """
        try:
            # Create compact event for Redis stream
            event_data = {
                "ts": str(int(time.time() * 1000)),  # Timestamp in ms
                "lag": str(int(lag_seconds * 1000)),  # Lag in ms
                "stream": stream,
                "consumer": consumer,
            }
            
            # Publish to Redis metrics stream (handle both sync and async)
            if hasattr(self.redis, 'xadd') and asyncio.iscoroutinefunction(self.redis.xadd):
                await self.redis.xadd("metrics:md:lag", event_data, maxlen=10000, approximate=True)
            else:
                self.redis.xadd("metrics:md:lag", event_data, maxlen=10000, approximate=True)
            
            # Also update Prometheus metrics
            try:
                from monitoring.metrics_exporter import observe_stream_lag
                observe_stream_lag(stream, consumer, lag_seconds)
            except ImportError:
                pass  # Prometheus not available
            
        except Exception as e:
            self.logger.error(f"Failed to record stream lag: {e}")
    
    async def set_bot_uptime(self, ttl_seconds: int = 300) -> None:
        """
        Set bot uptime key in Redis with TTL.
        
        Args:
            ttl_seconds: TTL in seconds (default: 5 minutes)
        """
        try:
            uptime_data = {
                "start_time": str(int(time.time())),
                "last_seen": str(int(time.time())),
                "status": "running"
            }
            
            # Set with TTL for automatic cleanup (handle both sync and async)
            if hasattr(self.redis, 'setex') and asyncio.iscoroutinefunction(self.redis.setex):
                await self.redis.setex(
                    "bot:up", 
                    ttl_seconds, 
                    json.dumps(uptime_data)
                )
            else:
                self.redis.setex(
                    "bot:up", 
                    ttl_seconds, 
                    json.dumps(uptime_data)
                )
            
        except Exception as e:
            self.logger.error(f"Failed to set bot uptime: {e}")
    
    async def clear_bot_uptime(self) -> None:
        """
        Clear bot uptime key on graceful shutdown.
        """
        try:
            if hasattr(self.redis, 'delete') and asyncio.iscoroutinefunction(self.redis.delete):
                await self.redis.delete("bot:up")
            else:
                self.redis.delete("bot:up")
            self.logger.info("Bot uptime key cleared")
        except Exception as e:
            self.logger.error(f"Failed to clear bot uptime: {e}")
    
    async def get_stream_lag_summary(self) -> Dict[str, Any]:
        """
        Get current stream lag summary from Redis.
        
        Returns:
            Dictionary with current lag information
        """
        try:
            # Read recent lag events (handle both sync and async)
            if hasattr(self.redis, 'xrevrange') and asyncio.iscoroutinefunction(self.redis.xrevrange):
                lag_events = await self.redis.xrevrange("metrics:md:lag", count=100)
            else:
                lag_events = self.redis.xrevrange("metrics:md:lag", count=100)
            
            summary = {}
            for event_id, fields in lag_events:
                stream = fields.get(b"stream", b"").decode()
                consumer = fields.get(b"consumer", b"").decode()
                lag_ms = int(fields.get(b"lag", b"0").decode())
                
                key = f"{stream}:{consumer}"
                if key not in summary or lag_ms > summary[key]["lag_ms"]:
                    summary[key] = {
                        "stream": stream,
                        "consumer": consumer,
                        "lag_ms": lag_ms,
                        "lag_seconds": lag_ms / 1000.0
                    }
            
            return summary
            
        except Exception as e:
            self.logger.error(f"Failed to get stream lag summary: {e}")
            return {}
    
    async def get_e2e_latency_summary(self, window_minutes: int = 5) -> Dict[str, Any]:
        """
        Get end-to-end latency summary from Redis.
        
        Args:
            window_minutes: Time window in minutes for analysis
            
        Returns:
            Dictionary with latency statistics
        """
        try:
            # Calculate cutoff time
            cutoff_ms = int((time.time() - window_minutes * 60) * 1000)
            
            # Read recent latency events (handle both sync and async)
            if hasattr(self.redis, 'xrevrange') and asyncio.iscoroutinefunction(self.redis.xrevrange):
                latency_events = await self.redis.xrevrange("metrics:signals:e2e", count=1000)
            else:
                latency_events = self.redis.xrevrange("metrics:signals:e2e", count=1000)
            
            latencies = []
            agent_streams = set()
            
            for event_id, fields in latency_events:
                event_ts = int(fields.get(b"ts", b"0").decode())
                if event_ts < cutoff_ms:
                    break
                    
                latency_ms = int(fields.get(b"ms", b"0").decode())
                agent = fields.get(b"agent", b"").decode()
                stream = fields.get(b"stream", b"").decode()
                
                latencies.append(latency_ms)
                agent_streams.add(f"{agent}:{stream}")
            
            if not latencies:
                return {"total_events": 0, "agent_streams": list(agent_streams)}
            
            # Calculate statistics
            latencies.sort()
            count = len(latencies)
            p50 = latencies[count // 2]
            p95 = latencies[int(count * 0.95)]
            p99 = latencies[int(count * 0.99)]
            
            return {
                "total_events": count,
                "agent_streams": list(agent_streams),
                "latency_ms": {
                    "min": min(latencies),
                    "max": max(latencies),
                    "p50": p50,
                    "p95": p95,
                    "p99": p99,
                    "avg": sum(latencies) / count
                }
            }
            
        except Exception as e:
            self.logger.error(f"Failed to get e2e latency summary: {e}")
            return {"total_events": 0, "agent_streams": []}


# Global instance for easy access
_slo_collector: Optional[SLOMetricsCollector] = None


def get_slo_collector(redis_client) -> SLOMetricsCollector:
    """
    Get or create global SLO metrics collector.
    
    Args:
        redis_client: Redis client instance
        
    Returns:
        SLOMetricsCollector instance
    """
    global _slo_collector
    if _slo_collector is None:
        _slo_collector = SLOMetricsCollector(redis_client)
    return _slo_collector


async def record_signal_latency(
    agent: str, 
    stream: str, 
    latency_ms: float,
    signal_payload: Optional[Dict[str, Any]] = None,
    redis_client = None
) -> None:
    """
    Convenience function to record signal latency.
    
    Args:
        agent: Agent name
        stream: Stream name
        latency_ms: Latency in milliseconds
        signal_payload: Optional signal payload
        redis_client: Redis client (will use global collector if None)
    """
    if redis_client:
        collector = SLOMetricsCollector(redis_client)
    else:
        collector = _slo_collector
        
    if collector:
        await collector.record_e2e_latency(agent, stream, latency_ms, signal_payload)


async def record_consumer_lag(
    stream: str, 
    consumer: str, 
    lag_seconds: float,
    redis_client = None
) -> None:
    """
    Convenience function to record consumer lag.
    
    Args:
        stream: Stream name
        consumer: Consumer name
        lag_seconds: Lag in seconds
        redis_client: Redis client (will use global collector if None)
    """
    if redis_client:
        collector = SLOMetricsCollector(redis_client)
    else:
        collector = _slo_collector
        
    if collector:
        await collector.record_stream_lag(stream, consumer, lag_seconds)
