"""
Health Check Server for Fly.io

Provides HTTP endpoints for:
- /health - Health check for Fly.io monitoring
- /metrics - Prometheus metrics export
- /readiness - Readiness probe
- /liveness - Liveness probe

Runs alongside the signal pipeline for 99.8% uptime monitoring.

Usage:
    python health_server.py

Author: DevOps Team
Version: 1.0.0
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from typing import Dict, Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class HealthStatus:
    """Track health status of the application."""

    def __init__(self):
        self.start_time = time.time()
        self.last_heartbeat = time.time()
        self.redis_connected = False
        self.websocket_connected = False
        self.signals_generated = 0
        self.errors_count = 0
        self.last_signal_time = None

    def update_heartbeat(self):
        """Update heartbeat timestamp."""
        self.last_heartbeat = time.time()

    def is_healthy(self) -> bool:
        """Check if application is healthy."""
        # Healthy if heartbeat within last 60 seconds
        heartbeat_ok = (time.time() - self.last_heartbeat) < 60

        # At least one connection should be active
        connections_ok = self.redis_connected or self.websocket_connected

        # Not too many errors
        error_rate_ok = self.errors_count < 100

        return heartbeat_ok and connections_ok and error_rate_ok

    def get_status(self) -> Dict[str, Any]:
        """Get current status as dictionary."""
        uptime = time.time() - self.start_time

        return {
            "status": "healthy" if self.is_healthy() else "unhealthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "uptime_seconds": int(uptime),
            "redis_connected": self.redis_connected,
            "websocket_connected": self.websocket_connected,
            "signals_generated": self.signals_generated,
            "errors_count": self.errors_count,
            "last_signal_time": self.last_signal_time.isoformat() if self.last_signal_time else None,
            "last_heartbeat_age_seconds": int(time.time() - self.last_heartbeat)
        }


# Global health status
health_status = HealthStatus()


class HealthCheckHandler(BaseHTTPRequestHandler):
    """HTTP request handler for health checks."""

    def log_message(self, format, *args):
        """Override to use logger instead of print."""
        logger.debug(f"{self.address_string()} - {format % args}")

    def do_GET(self):
        """Handle GET requests."""
        if self.path == '/health':
            self.handle_health()
        elif self.path == '/readiness':
            self.handle_readiness()
        elif self.path == '/liveness':
            self.handle_liveness()
        elif self.path == '/metrics':
            self.handle_metrics()
        else:
            self.send_error(404, "Not Found")

    def handle_health(self):
        """Handle /health endpoint."""
        status = health_status.get_status()
        is_healthy = health_status.is_healthy()

        # Set response code
        status_code = 200 if is_healthy else 503

        # Send response
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('X-Healthcheck-Source', 'crypto-ai-bot')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.end_headers()

        response = json.dumps(status, indent=2)
        self.wfile.write(response.encode())

    def handle_readiness(self):
        """Handle /readiness endpoint - checks if app is ready to serve traffic."""
        ready = health_status.redis_connected and health_status.websocket_connected

        status_code = 200 if ready else 503

        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()

        response = json.dumps({
            "ready": ready,
            "redis_connected": health_status.redis_connected,
            "websocket_connected": health_status.websocket_connected
        })
        self.wfile.write(response.encode())

    def handle_liveness(self):
        """Handle /liveness endpoint - checks if app is alive."""
        alive = (time.time() - health_status.last_heartbeat) < 120  # 2 minutes

        status_code = 200 if alive else 503

        self.send_response(status_code)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()

        self.wfile.write(b"OK" if alive else b"DEAD")

    def handle_metrics(self):
        """Handle /metrics endpoint - Prometheus format."""
        uptime = time.time() - health_status.start_time

        metrics = f"""# HELP crypto_ai_bot_uptime_seconds Uptime in seconds
# TYPE crypto_ai_bot_uptime_seconds counter
crypto_ai_bot_uptime_seconds {int(uptime)}

# HELP crypto_ai_bot_signals_generated_total Total signals generated
# TYPE crypto_ai_bot_signals_generated_total counter
crypto_ai_bot_signals_generated_total {health_status.signals_generated}

# HELP crypto_ai_bot_errors_total Total errors encountered
# TYPE crypto_ai_bot_errors_total counter
crypto_ai_bot_errors_total {health_status.errors_count}

# HELP crypto_ai_bot_redis_connected Redis connection status (1=connected, 0=disconnected)
# TYPE crypto_ai_bot_redis_connected gauge
crypto_ai_bot_redis_connected {1 if health_status.redis_connected else 0}

# HELP crypto_ai_bot_websocket_connected WebSocket connection status (1=connected, 0=disconnected)
# TYPE crypto_ai_bot_websocket_connected gauge
crypto_ai_bot_websocket_connected {1 if health_status.websocket_connected else 0}

# HELP crypto_ai_bot_healthy Health check status (1=healthy, 0=unhealthy)
# TYPE crypto_ai_bot_healthy gauge
crypto_ai_bot_healthy {1 if health_status.is_healthy() else 0}

# HELP crypto_ai_bot_heartbeat_age_seconds Age of last heartbeat in seconds
# TYPE crypto_ai_bot_heartbeat_age_seconds gauge
crypto_ai_bot_heartbeat_age_seconds {int(time.time() - health_status.last_heartbeat)}
"""

        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; version=0.0.4')
        self.end_headers()
        self.wfile.write(metrics.encode())


def run_health_server(port: int = 8080):
    """Run health check server."""
    server_address = ('', port)
    httpd = HTTPServer(server_address, HealthCheckHandler)

    logger.info(f"Health check server running on port {port}")
    logger.info(f"  Health: http://localhost:{port}/health")
    logger.info(f"  Readiness: http://localhost:{port}/readiness")
    logger.info(f"  Liveness: http://localhost:{port}/liveness")
    logger.info(f"  Metrics: http://localhost:{port}/metrics")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Health server shutting down...")
        httpd.shutdown()


def start_health_server_thread(port: int = 8080):
    """Start health server in background thread."""
    thread = Thread(target=run_health_server, args=(port,), daemon=True)
    thread.start()
    logger.info(f"Health server thread started on port {port}")
    return thread


# Heartbeat update function (call from main app)
def update_heartbeat():
    """Update heartbeat (call this periodically from main app)."""
    health_status.update_heartbeat()


def set_redis_status(connected: bool):
    """Update Redis connection status."""
    health_status.redis_connected = connected


def set_websocket_status(connected: bool):
    """Update WebSocket connection status."""
    health_status.websocket_connected = connected


def increment_signals():
    """Increment signals counter."""
    health_status.signals_generated += 1
    health_status.last_signal_time = datetime.now(timezone.utc)


def increment_errors():
    """Increment errors counter."""
    health_status.errors_count += 1


if __name__ == "__main__":
    # Run standalone health server for testing
    port = int(os.getenv("HEALTH_PORT", "8080"))

    # Simulate some activity
    health_status.redis_connected = True
    health_status.websocket_connected = True
    health_status.update_heartbeat()

    run_health_server(port)
