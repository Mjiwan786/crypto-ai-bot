"""
PRD-001 Compliant Health Checker

Comprehensive health checks for crypto-ai-bot engine with HTTP endpoint.

Health Checks (Task D):
1. Redis connectivity - Connection to Redis Cloud with TLS
2. Kraken WS connectivity - Per-pair WebSocket connection status
3. Recent signal activity - No "stalled" engine detection
4. Recent PnL updates - PnL pipeline is running

Usage:
    from monitoring.prd_health_checker import PRDHealthChecker

    checker = PRDHealthChecker()
    health = await checker.check_all()

    if health.is_healthy():
        print("Engine is healthy!")
    else:
        for issue in health.issues:
            print(f"FAILED: {issue}")
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import redis.asyncio as redis

# Import canonical trading pairs (single source of truth)
try:
    from config.trading_pairs import DEFAULT_TRADING_PAIRS_CSV
    CANONICAL_PAIRS_AVAILABLE = True
except ImportError:
    CANONICAL_PAIRS_AVAILABLE = False
    DEFAULT_TRADING_PAIRS_CSV = "BTC/USD,ETH/USD,SOL/USD,LINK/USD"

logger = logging.getLogger(__name__)


@dataclass
class HealthStatus:
    """Health check status result."""

    healthy: bool
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    uptime_seconds: float = 0.0
    issues: List[str] = field(default_factory=list)
    components: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON response."""
        return {
            "status": "healthy" if self.healthy else "unhealthy",
            "timestamp": self.timestamp,
            "uptime_seconds": round(self.uptime_seconds, 2),
            "issues": self.issues,
            "components": self.components,
        }


class PRDHealthChecker:
    """
    PRD-001 Compliant Health Checker

    Performs comprehensive health checks for the engine.
    """

    def __init__(
        self,
        redis_url: Optional[str] = None,
        redis_ca_cert: Optional[str] = None,
        mode: str = "paper",
        start_time: Optional[float] = None,
    ):
        """
        Initialize health checker.

        Args:
            redis_url: Redis URL (defaults to REDIS_URL env var)
            redis_ca_cert: Path to CA cert (defaults to env var)
            mode: Trading mode (paper/live)
            start_time: Engine start time for uptime calculation
        """
        self.redis_url = redis_url or os.getenv("REDIS_URL", "")
        self.redis_ca_cert = redis_ca_cert or os.getenv(
            "REDIS_CA_CERT",
            os.getenv("REDIS_CA_CERT_PATH", "config/certs/redis_ca.pem")
        )
        self.mode = mode or os.getenv("ENGINE_MODE", "paper")
        self.start_time = start_time or time.time()

        # Thresholds
        self.signal_stale_threshold_sec = int(os.getenv("SIGNAL_STALE_THRESHOLD_SEC", "300"))  # 5 min
        self.pnl_stale_threshold_sec = int(os.getenv("PNL_STALE_THRESHOLD_SEC", "600"))  # 10 min
        self.redis_timeout_sec = int(os.getenv("REDIS_HEALTH_TIMEOUT_SEC", "5"))
        self.kraken_ws_timeout_sec = int(os.getenv("KRAKEN_WS_HEALTH_TIMEOUT_SEC", "10"))

        # Trading pairs to check - uses canonical config/trading_pairs.py
        pairs_env = os.getenv("TRADING_PAIRS", DEFAULT_TRADING_PAIRS_CSV)
        self.trading_pairs = [p.strip() for p in pairs_env.split(",")]

    async def _get_redis_client(self) -> Optional[redis.Redis]:
        """Create Redis client for health checks."""
        if not self.redis_url:
            return None

        conn_params = {
            "socket_connect_timeout": self.redis_timeout_sec,
            "socket_timeout": self.redis_timeout_sec,
            "decode_responses": False,
        }

        if self.redis_url.startswith("rediss://"):
            if self.redis_ca_cert and os.path.exists(self.redis_ca_cert):
                conn_params["ssl_ca_certs"] = self.redis_ca_cert
                conn_params["ssl_cert_reqs"] = "required"

        return redis.from_url(self.redis_url, **conn_params)

    async def check_redis_connectivity(self) -> Dict[str, Any]:
        """
        Check Redis connectivity and measure latency.

        Returns:
            Dict with status, latency_ms, error
        """
        start = time.time()
        try:
            client = await self._get_redis_client()
            if not client:
                return {
                    "status": "unhealthy",
                    "error": "REDIS_URL not configured",
                    "latency_ms": 0.0,
                }

            try:
                ping_start = time.time()
                await asyncio.wait_for(client.ping(), timeout=self.redis_timeout_sec)
                latency_ms = (time.time() - ping_start) * 1000

                return {
                    "status": "healthy",
                    "latency_ms": round(latency_ms, 2),
                    "error": None,
                }
            finally:
                await client.aclose()

        except asyncio.TimeoutError:
            return {
                "status": "unhealthy",
                "error": f"Redis ping timeout after {self.redis_timeout_sec}s",
                "latency_ms": 0.0,
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e)[:100],
                "latency_ms": 0.0,
            }

    async def check_kraken_ws_connectivity(self) -> Dict[str, Dict[str, Any]]:
        """
        Check Kraken WebSocket connectivity per pair.

        Returns:
            Dict of {pair: {status, last_message_age_sec, error}}
        """
        results = {}

        # Try to get connection status from Redis
        try:
            client = await self._get_redis_client()
            if not client:
                # If no Redis, mark all as unknown
                for pair in self.trading_pairs:
                    results[pair] = {
                        "status": "unknown",
                        "error": "Redis not available for WS status check",
                    }
                return results

            try:
                # Check for heartbeat or last message timestamp per pair
                for pair in self.trading_pairs:
                    # Try to get last message timestamp from Redis
                    heartbeat_key = f"kraken:ws:heartbeat:{pair}"
                    last_msg_key = f"kraken:ws:last_message:{pair}"

                    heartbeat = await client.get(heartbeat_key)
                    last_msg = await client.get(last_msg_key)

                    if heartbeat or last_msg:
                        # Parse timestamp
                        ts_str = (heartbeat or last_msg).decode() if isinstance(heartbeat or last_msg, bytes) else (heartbeat or last_msg)
                        try:
                            last_ts = float(ts_str)
                            age_sec = time.time() - last_ts

                            # Healthy if message within last 60 seconds
                            if age_sec < 60:
                                results[pair] = {
                                    "status": "healthy",
                                    "last_message_age_sec": round(age_sec, 1),
                                    "error": None,
                                }
                            else:
                                results[pair] = {
                                    "status": "unhealthy",
                                    "last_message_age_sec": round(age_sec, 1),
                                    "error": f"No message for {int(age_sec)}s",
                                }
                        except ValueError:
                            results[pair] = {
                                "status": "unknown",
                                "error": "Invalid timestamp format",
                            }
                    else:
                        # No heartbeat found - may be starting up
                        results[pair] = {
                            "status": "unknown",
                            "error": "No heartbeat found (may be starting up)",
                        }

            finally:
                await client.aclose()

        except Exception as e:
            # If check fails, mark all as unknown
            for pair in self.trading_pairs:
                results[pair] = {
                    "status": "unknown",
                    "error": f"Check failed: {str(e)[:100]}",
                }

        return results

    async def check_signal_activity(self) -> Dict[str, Any]:
        """
        Check if signals are being generated recently.

        Returns:
            Dict with status, last_signal_age_sec, error
        """
        try:
            client = await self._get_redis_client()
            if not client:
                return {
                    "status": "unknown",
                    "error": "Redis not available",
                    "last_signal_age_sec": None,
                }

            try:
                # Check last signal timestamp
                last_ts_key = "engine:last_signal_ts"
                last_ts = await client.get(last_ts_key)

                if last_ts is None:
                    # Try to check signal stream directly
                    stream_key = f"signals:{self.mode}:{self.trading_pairs[0]}"
                    try:
                        stream_info = await client.xinfo_stream(stream_key)
                        last_entry_id = stream_info.get("last-generated-id", b"0-0")
                        if isinstance(last_entry_id, bytes):
                            last_entry_id = last_entry_id.decode()

                        if "-" in last_entry_id and last_entry_id != "0-0":
                            ts_ms = int(last_entry_id.split("-")[0])
                            last_ts = str(ts_ms / 1000)
                    except redis.ResponseError:
                        # Stream doesn't exist yet
                        return {
                            "status": "healthy",  # OK if no signals yet
                            "error": None,
                            "last_signal_age_sec": None,
                        }

                if last_ts is None:
                    return {
                        "status": "healthy",  # OK if no signals yet
                        "error": None,
                        "last_signal_age_sec": None,
                    }

                if isinstance(last_ts, bytes):
                    last_ts = last_ts.decode()

                last_signal_time = float(last_ts)
                age_sec = time.time() - last_signal_time

                healthy = age_sec < self.signal_stale_threshold_sec

                return {
                    "status": "healthy" if healthy else "unhealthy",
                    "last_signal_age_sec": round(age_sec, 1),
                    "error": None if healthy else f"Last signal {int(age_sec)}s ago (stale)",
                }

            finally:
                await client.aclose()

        except Exception as e:
            return {
                "status": "unknown",
                "error": str(e)[:100],
                "last_signal_age_sec": None,
            }

    async def check_pnl_activity(self) -> Dict[str, Any]:
        """
        Check if PnL is being updated recently.

        Returns:
            Dict with status, last_pnl_age_sec, error
        """
        try:
            client = await self._get_redis_client()
            if not client:
                return {
                    "status": "unknown",
                    "error": "Redis not available",
                    "last_pnl_age_sec": None,
                }

            try:
                # Check last PnL update timestamp
                ts_key = f"pnl:{self.mode}:last_update_ts"
                last_ts = await client.get(ts_key)

                if last_ts is None:
                    # Check equity curve stream
                    stream_key = f"pnl:{self.mode}:equity_curve"
                    try:
                        stream_info = await client.xinfo_stream(stream_key)
                        last_entry_id = stream_info.get("last-generated-id", b"0-0")
                        if isinstance(last_entry_id, bytes):
                            last_entry_id = last_entry_id.decode()

                        if "-" in last_entry_id and last_entry_id != "0-0":
                            ts_ms = int(last_entry_id.split("-")[0])
                            last_ts = str(ts_ms / 1000)
                    except redis.ResponseError:
                        # Stream doesn't exist yet
                        return {
                            "status": "healthy",  # OK if no PnL yet
                            "error": None,
                            "last_pnl_age_sec": None,
                        }

                if last_ts is None:
                    return {
                        "status": "healthy",  # OK if no PnL yet
                        "error": None,
                        "last_pnl_age_sec": None,
                    }

                if isinstance(last_ts, bytes):
                    last_ts = last_ts.decode()

                last_update_time = float(last_ts)
                age_sec = time.time() - last_update_time

                healthy = age_sec < self.pnl_stale_threshold_sec

                return {
                    "status": "healthy" if healthy else "unhealthy",
                    "last_pnl_age_sec": round(age_sec, 1),
                    "error": None if healthy else f"Last PnL update {int(age_sec)}s ago (stale)",
                }

            finally:
                await client.aclose()

        except Exception as e:
            return {
                "status": "unknown",
                "error": str(e)[:100],
                "last_pnl_age_sec": None,
            }

    async def check_all(self) -> HealthStatus:
        """
        Run all health checks and return comprehensive status.

        Returns:
            HealthStatus with all check results
        """
        issues = []
        components = {}

        # Check Redis
        redis_check = await self.check_redis_connectivity()
        components["redis"] = redis_check
        if redis_check["status"] != "healthy":
            issues.append(f"Redis: {redis_check.get('error', 'unhealthy')}")

        # Check Kraken WS
        kraken_ws_check = await self.check_kraken_ws_connectivity()
        components["kraken_ws"] = kraken_ws_check
        unhealthy_pairs = [
            pair for pair, status in kraken_ws_check.items()
            if status.get("status") == "unhealthy"
        ]
        if unhealthy_pairs:
            issues.append(f"Kraken WS unhealthy pairs: {', '.join(unhealthy_pairs)}")

        # Check signal activity
        signal_check = await self.check_signal_activity()
        components["signal_activity"] = signal_check
        if signal_check["status"] == "unhealthy":
            issues.append(f"Signal activity: {signal_check.get('error', 'stale')}")

        # Check PnL activity
        pnl_check = await self.check_pnl_activity()
        components["pnl_activity"] = pnl_check
        if pnl_check["status"] == "unhealthy":
            issues.append(f"PnL activity: {pnl_check.get('error', 'stale')}")

        # Overall health
        healthy = (
            redis_check["status"] == "healthy" and
            len(unhealthy_pairs) == 0 and
            signal_check["status"] in ("healthy", "unknown") and
            pnl_check["status"] in ("healthy", "unknown")
        )

        uptime = time.time() - self.start_time

        return HealthStatus(
            healthy=healthy,
            uptime_seconds=uptime,
            issues=issues,
            components=components,
        )


__all__ = [
    "PRDHealthChecker",
    "HealthStatus",
]









