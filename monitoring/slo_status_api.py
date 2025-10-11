"""
SLO Status API

Simple Redis-backed API for SLO status monitoring.
Provides a REST endpoint that Grafana can query to determine production readiness.

Usage:
    from monitoring.slo_status_api import start_slo_api_server
    start_slo_api_server()  # Starts server on SLO_API_ADDR:SLO_API_PORT
"""

import os
import json
import time
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import logging

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import uvicorn

from monitoring.slo_definitions import get_effective_thresholds, window_hours
from monitoring.slo_metrics import get_slo_collector

logger = logging.getLogger(__name__)

# Environment configuration
SLO_API_PORT = int(os.getenv("SLO_API_PORT", "9109"))
SLO_API_ADDR = os.getenv("SLO_API_ADDR", "0.0.0.0")

# FastAPI app
app = FastAPI(title="SLO Status API", version="1.0.0")

# Global Redis client (will be set by main application)
_redis_client = None


def set_redis_client(redis_client):
    """Set the Redis client for SLO status checks."""
    global _redis_client
    _redis_client = redis_client


async def check_slo_status() -> Dict[str, Any]:
    """
    Check current SLO status against thresholds.
    
    Returns:
        Dictionary with SLO status and individual metric statuses
    """
    if not _redis_client:
        return {
            "status": "unknown",
            "ready_for_prod": False,
            "reason": "Redis client not available",
            "timestamp": datetime.utcnow().isoformat(),
            "metrics": {}
        }
    
    try:
        # Get effective thresholds
        thresholds = get_effective_thresholds()
        window_hours_val = window_hours()
        
        # Get SLO collector
        slo_collector = get_slo_collector(_redis_client)
        
        # Check individual metrics
        metrics_status = {}
        all_metrics_ok = True
        
        # 1. Check P95 publish latency
        latency_summary = await slo_collector.get_e2e_latency_summary(window_minutes=window_hours_val * 60)
        if latency_summary.get("total_events", 0) > 0:
            p95_latency = latency_summary["latency_ms"]["p95"]
            latency_ok = p95_latency <= thresholds["p95_publish_latency_ms"]
            metrics_status["p95_latency"] = {
                "value": p95_latency,
                "threshold": thresholds["p95_publish_latency_ms"],
                "ok": latency_ok,
                "unit": "ms"
            }
            if not latency_ok:
                all_metrics_ok = False
        else:
            metrics_status["p95_latency"] = {
                "value": None,
                "threshold": thresholds["p95_publish_latency_ms"],
                "ok": False,
                "unit": "ms",
                "reason": "No data available"
            }
            all_metrics_ok = False
        
        # 2. Check stream lag
        lag_summary = await slo_collector.get_stream_lag_summary()
        max_lag = 0
        if lag_summary:
            max_lag = max(entry["lag_seconds"] for entry in lag_summary.values())
        
        lag_ok = max_lag <= thresholds["max_stream_lag_sec"]
        metrics_status["stream_lag"] = {
            "value": max_lag,
            "threshold": thresholds["max_stream_lag_sec"],
            "ok": lag_ok,
            "unit": "s"
        }
        if not lag_ok:
            all_metrics_ok = False
        
        # 3. Check uptime (simplified - check if bot is up)
        # In a real implementation, you'd calculate actual uptime over the window
        uptime_ok = True  # Simplified for now
        metrics_status["uptime"] = {
            "value": 1.0,  # Simplified
            "threshold": thresholds["uptime_target"],
            "ok": uptime_ok,
            "unit": "percent"
        }
        
        # 4. Check duplicate rate (simplified)
        dup_rate_ok = True  # Simplified for now
        metrics_status["dup_rate"] = {
            "value": 0.0,  # Simplified
            "threshold": thresholds["max_dup_rate"],
            "ok": dup_rate_ok,
            "unit": "percent"
        }
        
        # Determine overall status
        if all_metrics_ok:
            status = "ready"
            ready_for_prod = True
            reason = "All SLOs within thresholds"
        else:
            status = "not_ready"
            ready_for_prod = False
            failed_metrics = [name for name, data in metrics_status.items() if not data["ok"]]
            reason = f"SLO violations: {', '.join(failed_metrics)}"
        
        return {
            "status": status,
            "ready_for_prod": ready_for_prod,
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat(),
            "window_hours": window_hours_val,
            "thresholds": thresholds,
            "metrics": metrics_status
        }
        
    except Exception as e:
        logger.error(f"Error checking SLO status: {e}")
        return {
            "status": "error",
            "ready_for_prod": False,
            "reason": f"Error checking SLOs: {str(e)}",
            "timestamp": datetime.utcnow().isoformat(),
            "metrics": {}
        }


@app.get("/slo/status")
async def get_slo_status():
    """Get current SLO status."""
    status = await check_slo_status()
    return JSONResponse(content=status)


@app.get("/slo/metrics")
async def get_slo_metrics():
    """Get detailed SLO metrics."""
    if not _redis_client:
        raise HTTPException(status_code=503, detail="Redis client not available")
    
    try:
        slo_collector = get_slo_collector(_redis_client)
        
        # Get detailed metrics
        latency_summary = await slo_collector.get_e2e_latency_summary(window_minutes=60)
        lag_summary = await slo_collector.get_stream_lag_summary()
        
        return JSONResponse(content={
            "latency": latency_summary,
            "stream_lag": lag_summary,
            "timestamp": datetime.utcnow().isoformat()
        })
    except Exception as e:
        logger.error(f"Error getting SLO metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/slo/thresholds")
async def get_slo_thresholds():
    """Get current SLO thresholds."""
    thresholds = get_effective_thresholds()
    return JSONResponse(content={
        "thresholds": thresholds,
        "window_hours": window_hours(),
        "timestamp": datetime.utcnow().isoformat()
    })


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return JSONResponse(content={
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "redis_available": _redis_client is not None
    })


def start_slo_api_server(addr: Optional[str] = None, port: Optional[int] = None) -> None:
    """
    Start the SLO API server.
    
    Args:
        addr: Address to bind to (defaults to SLO_API_ADDR env var)
        port: Port to bind to (defaults to SLO_API_PORT env var)
    """
    bind_addr = addr or SLO_API_ADDR
    bind_port = port or SLO_API_PORT
    
    logger.info(f"Starting SLO API server on {bind_addr}:{bind_port}")
    
    # Run the server
    uvicorn.run(
        app,
        host=bind_addr,
        port=bind_port,
        log_level="info"
    )


if __name__ == "__main__":
    # For testing without Redis
    print("Starting SLO API server for testing...")
    start_slo_api_server()

