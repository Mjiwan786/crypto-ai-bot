"""
Crypto AI Bot Metrics Exporter

This module provides Prometheus metrics collection and export functionality for the crypto AI bot.
It exposes a Prometheus endpoint and provides a simple API for the application to push metrics.

Usage:
    from monitoring.metrics_exporter import start_metrics_server, inc_signals_published
    start_metrics_server()  # Starts server on METRICS_ADDR:METRICS_PORT
    inc_signals_published("scalper", "ticker", "BTC/USD")

Integration in main.py:
    ```python
    # In main.py, add metrics initialization
    from monitoring.metrics_exporter import start_metrics_server, heartbeat
    
    def main():
        # Start metrics server early in the application lifecycle
        start_metrics_server()
        
        # In your main event loop, call heartbeat periodically
        async def metrics_heartbeat():
            while True:
                heartbeat()
                await asyncio.sleep(30)  # Update every 30 seconds
        
        # Start heartbeat task
        asyncio.create_task(metrics_heartbeat())
        
        # Your existing application logic...
    ```
"""

import os
import time
import threading
from typing import Optional

from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    start_http_server,
    REGISTRY,
    PROCESS_COLLECTOR,
    PLATFORM_COLLECTOR,
    GC_COLLECTOR,
)

# Environment configuration
METRICS_PORT = int(os.getenv("METRICS_PORT", "9108"))
METRICS_ADDR = os.getenv("METRICS_ADDR", "0.0.0.0")

# Thread-safe lock for metric operations
_metrics_lock = threading.Lock()

# Define metrics
signals_published_total = Counter(
    "signals_published_total",
    "Total number of signals published",
    ["agent", "stream", "symbol"]
)

publish_latency_ms = Histogram(
    "publish_latency_ms_bucket",
    "Publish latency in milliseconds",
    ["agent", "stream"],
    buckets=[5, 10, 20, 50, 100, 200, 500, 1000, 2000]
)

ingestor_disconnects_total = Counter(
    "ingestor_disconnects_total",
    "Total number of ingestor disconnections",
    ["source"]
)

redis_publish_errors_total = Counter(
    "redis_publish_errors_total",
    "Total number of Redis publish errors",
    ["stream"]
)

bot_heartbeat_seconds = Gauge(
    "bot_heartbeat_seconds",
    "Bot heartbeat timestamp in seconds since epoch"
)

# SLO Metrics for monitoring
stream_lag_seconds = Gauge(
    "stream_lag_seconds",
    "Stream lag in seconds (now - ts_last_md)",
    ["stream", "consumer"]
)

bot_uptime_seconds = Gauge(
    "bot_uptime_seconds",
    "Bot uptime in seconds since start"
)

# Server state
_server_started = False
_server_thread = None
_start_time = None


def start_metrics_server(addr: Optional[str] = None, port: Optional[int] = None) -> None:
    """
    Start the Prometheus metrics server.
    
    Args:
        addr: Address to bind to (defaults to METRICS_ADDR env var or "0.0.0.0")
        port: Port to bind to (defaults to METRICS_PORT env var or 9108)
    
    Raises:
        RuntimeError: If server is already started
    """
    global _server_started, _server_thread, _start_time
    
    with _metrics_lock:
        if _server_started:
            raise RuntimeError("Metrics server is already started")
        
        # Record start time for uptime tracking
        _start_time = time.time()
        
        # Use provided values or fall back to environment/defaults
        bind_addr = addr or METRICS_ADDR
        bind_port = port or METRICS_PORT
        
        # Register default collectors for process and Python metrics
        # Only register if not already present to avoid duplicates
        try:
            REGISTRY.register(PROCESS_COLLECTOR)
        except ValueError:
            pass  # Already registered
        try:
            REGISTRY.register(PLATFORM_COLLECTOR)
        except ValueError:
            pass  # Already registered
        try:
            REGISTRY.register(GC_COLLECTOR)
        except ValueError:
            pass  # Already registered
        
        # Start the HTTP server in a separate thread
        def _start_server():
            start_http_server(bind_port, addr=bind_addr)
        
        _server_thread = threading.Thread(target=_start_server, daemon=True)
        _server_thread.start()
        _server_started = True
        
        print(f"Prometheus metrics server started on {bind_addr}:{bind_port}")


def inc_signals_published(agent: str, stream: str, symbol: str) -> None:
    """
    Increment the signals published counter.
    
    Args:
        agent: Agent name (e.g., "scalper", "trend_following")
        stream: Stream name (e.g., "ticker", "orderbook")
        symbol: Trading symbol (e.g., "BTC/USD", "ETH/USD")
    """
    with _metrics_lock:
        signals_published_total.labels(agent=agent, stream=stream, symbol=symbol).inc()


def observe_publish_latency_ms(agent: str, stream: str, ms: float) -> None:
    """
    Observe publish latency in milliseconds.
    
    Args:
        agent: Agent name
        stream: Stream name
        ms: Latency in milliseconds
    """
    with _metrics_lock:
        publish_latency_ms.labels(agent=agent, stream=stream).observe(ms)


def inc_ingestor_disconnect(source: str) -> None:
    """
    Increment the ingestor disconnects counter.
    
    Args:
        source: Data source name (e.g., "kraken", "binance", "coinbase")
    """
    with _metrics_lock:
        ingestor_disconnects_total.labels(source=source).inc()


def inc_redis_publish_error(stream: str) -> None:
    """
    Increment the Redis publish errors counter.
    
    Args:
        stream: Stream name where the error occurred
    """
    with _metrics_lock:
        redis_publish_errors_total.labels(stream=stream).inc()


def heartbeat() -> None:
    """
    Update the bot heartbeat timestamp.
    Call this periodically to indicate the bot is alive.
    """
    with _metrics_lock:
        bot_heartbeat_seconds.set(time.time())
        
        # Update uptime if server is started
        if _start_time is not None:
            uptime = time.time() - _start_time
            bot_uptime_seconds.set(uptime)
    
    # Send Discord alert for heartbeat (only once per hour to avoid spam)
    try:
        from monitoring.discord_alerts import send_alert
        current_hour = int(time.time() // 3600)
        if not hasattr(heartbeat, '_last_alert_hour') or heartbeat._last_alert_hour != current_hour:
            send_alert("Bot Heartbeat", "Crypto AI bot is running normally", "INFO", {"component": "heartbeat"})
            heartbeat._last_alert_hour = current_hour
    except ImportError:
        pass  # Discord alerts not available
    except Exception:
        pass  # Don't fail heartbeat on Discord errors


def observe_stream_lag(stream: str, consumer: str, lag_seconds: float) -> None:
    """
    Observe stream lag in seconds.
    
    Args:
        stream: Stream name (e.g., "md:trades", "md:spread")
        consumer: Consumer name (e.g., "strategy_consumer", "execution_consumer")
        lag_seconds: Lag in seconds (now - ts_last_md)
    """
    with _metrics_lock:
        stream_lag_seconds.labels(stream=stream, consumer=consumer).set(lag_seconds)


# Convenience function for testing
def get_metrics_summary() -> dict:
    """
    Get a summary of current metric values for debugging/testing.
    
    Returns:
        Dictionary with metric summaries
    """
    with _metrics_lock:
        return {
            "signals_published_total": {
                "samples": len(signals_published_total._metrics),
                "total": sum(sample.value for sample in signals_published_total.collect()[0].samples)
            },
            "publish_latency_ms": {
                "samples": len(publish_latency_ms._metrics),
                "total_observations": sum(sample.value for sample in publish_latency_ms.collect()[0].samples if sample.name.endswith('_count'))
            },
            "ingestor_disconnects_total": {
                "samples": len(ingestor_disconnects_total._metrics),
                "total": sum(sample.value for sample in ingestor_disconnects_total.collect()[0].samples)
            },
            "redis_publish_errors_total": {
                "samples": len(redis_publish_errors_total._metrics),
                "total": sum(sample.value for sample in redis_publish_errors_total.collect()[0].samples)
            },
            "bot_heartbeat_seconds": {
                "value": bot_heartbeat_seconds._value.get()
            },
            "stream_lag_seconds": {
                "samples": len(stream_lag_seconds._metrics),
                "current_lags": {f"{labels[0]}:{labels[1]}": sample._value.get() 
                                for labels, sample in stream_lag_seconds._metrics.items()}
            },
            "bot_uptime_seconds": {
                "value": bot_uptime_seconds._value.get()
            }
        }


if __name__ == "__main__":
    # Example usage and testing
    print("Starting metrics server for testing...")
    start_metrics_server()
    
    # Simulate some metrics
    print("Simulating metrics...")
    inc_signals_published("scalper", "ticker", "BTC/USD")
    inc_signals_published("scalper", "ticker", "ETH/USD")
    observe_publish_latency_ms("scalper", "ticker", 15.5)
    observe_publish_latency_ms("scalper", "ticker", 8.2)
    observe_stream_lag("md:trades", "strategy_consumer", 0.5)
    observe_stream_lag("md:spread", "execution_consumer", 1.2)
    inc_ingestor_disconnect("kraken")
    inc_redis_publish_error("ticker")
    heartbeat()
    
    print("Metrics summary:")
    print(get_metrics_summary())
    
    print(f"Metrics available at http://{METRICS_ADDR}:{METRICS_PORT}/metrics")
    print("Press Ctrl+C to stop...")
    
    try:
        while True:
            time.sleep(1)
            heartbeat()  # Keep heartbeat alive
    except KeyboardInterrupt:
        print("\nShutting down...")
