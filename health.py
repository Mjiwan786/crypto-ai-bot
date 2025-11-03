#!/usr/bin/env python3
"""
Crypto AI Bot - Health Check ASGI Server

Minimal health endpoint for Docker/Kubernetes deployments.
Runs on port 8080 and checks Redis + system status.

Usage:
    # Run standalone
    python health.py

    # Run with uvicorn
    uvicorn health:app --host 0.0.0.0 --port 8080

Environment Variables:
    REDIS_URL: Redis connection string (rediss://... for TLS)
    REDIS_CA_CERT: Path to Redis CA certificate (for TLS)
    HEALTH_API_PORT: Port for health server (default: 8080)
"""

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Global health state
_health_state = {
    "status": "starting",
    "redis_connected": False,
    "last_check": None,
    "uptime_seconds": 0,
    "start_time": time.time(),
}


async def check_redis_connection() -> Dict[str, Any]:
    """
    Check Redis connectivity with TLS support.

    Returns:
        Dictionary with connection status and metadata
    """
    try:
        import redis
        from urllib.parse import urlparse

        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        parsed = urlparse(redis_url)
        use_ssl = parsed.scheme == "rediss"

        if use_ssl:
            # TLS connection with CA cert
            import ssl

            ssl_context = ssl.create_default_context()
            ca_cert_path = os.getenv(
                "REDIS_CA_CERT",
                str(project_root / "config" / "certs" / "redis_ca.pem"),
            )

            if os.path.exists(ca_cert_path):
                ssl_context.load_verify_locations(ca_cert_path)
                logger.debug(f"Using Redis CA cert: {ca_cert_path}")
            else:
                logger.warning(f"Redis CA cert not found: {ca_cert_path}")

            client = redis.from_url(
                redis_url,
                ssl_cert_reqs=ssl.CERT_REQUIRED,
                ssl_ca_certs=ca_cert_path if os.path.exists(ca_cert_path) else None,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
            )
        else:
            # Non-TLS connection
            client = redis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
            )

        # Test connection
        start_time = time.time()
        pong = client.ping()
        latency = (time.time() - start_time) * 1000

        if pong:
            return {
                "connected": True,
                "latency_ms": round(latency, 2),
                "url": redis_url.split("@")[-1] if "@" in redis_url else redis_url,
                "ssl_enabled": use_ssl,
            }
        else:
            return {"connected": False, "error": "PING failed"}

    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        return {"connected": False, "error": str(e)}


async def health_endpoint(request):
    """
    Health check endpoint.

    Returns:
        200 OK if healthy, 503 Service Unavailable if unhealthy
    """
    # Check Redis
    redis_status = await check_redis_connection()

    # Update global health state
    _health_state["redis_connected"] = redis_status["connected"]
    _health_state["last_check"] = datetime.utcnow().isoformat()
    _health_state["uptime_seconds"] = int(time.time() - _health_state["start_time"])

    # Determine overall status
    if redis_status["connected"]:
        _health_state["status"] = "healthy"
        status_code = 200
    else:
        _health_state["status"] = "unhealthy"
        status_code = 503

    # Build response
    response_data = {
        "status": _health_state["status"],
        "timestamp": _health_state["last_check"],
        "uptime_seconds": _health_state["uptime_seconds"],
        "redis": redis_status,
        "environment": os.getenv("ENVIRONMENT", "unknown"),
        "version": "0.5.0",
    }

    return JSONResponse(response_data, status_code=status_code)


async def liveness_endpoint(request):
    """
    Kubernetes liveness probe endpoint.

    Returns:
        200 OK if process is alive
    """
    return Response("OK", status_code=200)


async def readiness_endpoint(request):
    """
    Kubernetes readiness probe endpoint.

    Returns:
        200 OK if ready to accept traffic, 503 otherwise
    """
    # Check if Redis is connected
    redis_status = await check_redis_connection()

    if redis_status["connected"]:
        return Response("READY", status_code=200)
    else:
        return Response("NOT READY", status_code=503)


# Background task to update health state periodically
async def health_monitor_task():
    """Background task to monitor system health"""
    logger.info("Starting health monitor task")

    while True:
        try:
            # Check Redis every 30 seconds
            redis_status = await check_redis_connection()
            _health_state["redis_connected"] = redis_status["connected"]
            _health_state["last_check"] = datetime.utcnow().isoformat()
            _health_state["uptime_seconds"] = int(
                time.time() - _health_state["start_time"]
            )

            if redis_status["connected"]:
                _health_state["status"] = "healthy"
            else:
                _health_state["status"] = "unhealthy"

            logger.debug(f"Health check: {_health_state['status']}")

        except Exception as e:
            logger.error(f"Health monitor error: {e}")

        # Wait 30 seconds before next check
        await asyncio.sleep(30)


# Define routes
routes = [
    Route("/health", health_endpoint),
    Route("/", health_endpoint),  # Root also returns health
    Route("/liveness", liveness_endpoint),
    Route("/readiness", readiness_endpoint),
]

# Create Starlette app
app = Starlette(
    debug=False,
    routes=routes,
)


# Startup event
@app.on_event("startup")
async def startup_event():
    """Application startup"""
    logger.info("Health server starting...")
    logger.info(f"Environment: {os.getenv('ENVIRONMENT', 'unknown')}")
    logger.info(f"Redis URL: {os.getenv('REDIS_URL', 'not set')}")

    # Start background health monitor
    asyncio.create_task(health_monitor_task())

    _health_state["status"] = "starting"
    logger.info("Health server ready")


@app.on_event("shutdown")
async def shutdown_event():
    """Application shutdown"""
    logger.info("Health server shutting down...")
    _health_state["status"] = "shutdown"


if __name__ == "__main__":
    """Run health server standalone"""
    import uvicorn

    port = int(os.getenv("HEALTH_API_PORT", "8080"))

    logger.info("=" * 60)
    logger.info("CRYPTO AI BOT - HEALTH SERVER")
    logger.info("=" * 60)
    logger.info(f"Port: {port}")
    logger.info(f"Endpoints: /health, /liveness, /readiness")
    logger.info("=" * 60)

    uvicorn.run(
        "health:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
        access_log=True,
    )
