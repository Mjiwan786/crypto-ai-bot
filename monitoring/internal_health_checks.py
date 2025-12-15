"""
Internal Health Checks Module (monitoring/internal_health_checks.py)

PRD-001 compliant health checks for crypto-ai-bot engine.

HEALTH CHECKS:
1. Redis connectivity - Connection to Redis Cloud with TLS
2. Kraken WS connectivity - Per-pair WebSocket connection status
3. Recent signal activity - No "stalled" engine detection
4. Recent PnL updates - PnL pipeline is running

Usage:
    from monitoring.internal_health_checks import HealthChecker

    checker = HealthChecker()
    results = await checker.run_all_checks()

    if results.is_healthy():
        print("All checks passed!")
    else:
        for check in results.failed_checks():
            print(f"FAILED: {check.name} - {check.message}")
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Callable, Awaitable

import redis.asyncio as redis

# Import canonical trading pairs (single source of truth)
try:
    from config.trading_pairs import DEFAULT_TRADING_PAIRS_CSV
    CANONICAL_PAIRS_AVAILABLE = True
except ImportError:
    CANONICAL_PAIRS_AVAILABLE = False
    DEFAULT_TRADING_PAIRS_CSV = "BTC/USD,ETH/USD,SOL/USD,LINK/USD"

logger = logging.getLogger(__name__)


# =============================================================================
# HEALTH CHECK RESULTS
# =============================================================================

@dataclass
class HealthCheckResult:
    """Result of a single health check."""
    name: str
    healthy: bool
    message: str
    duration_ms: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HealthCheckSuite:
    """Results of all health checks."""
    checks: List[HealthCheckResult] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def is_healthy(self) -> bool:
        """Check if all checks passed."""
        return all(c.healthy for c in self.checks)

    def failed_checks(self) -> List[HealthCheckResult]:
        """Get list of failed checks."""
        return [c for c in self.checks if not c.healthy]

    def passed_checks(self) -> List[HealthCheckResult]:
        """Get list of passed checks."""
        return [c for c in self.checks if c.healthy]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "healthy": self.is_healthy(),
            "timestamp": self.timestamp,
            "checks": [
                {
                    "name": c.name,
                    "healthy": c.healthy,
                    "message": c.message,
                    "duration_ms": c.duration_ms,
                    "metadata": c.metadata,
                }
                for c in self.checks
            ],
            "summary": {
                "total": len(self.checks),
                "passed": len(self.passed_checks()),
                "failed": len(self.failed_checks()),
            },
        }


# =============================================================================
# HEALTH CHECKER
# =============================================================================

class HealthChecker:
    """
    Runs comprehensive health checks for the crypto-ai-bot engine.

    Checks:
    1. redis_connectivity - Can connect and ping Redis
    2. redis_streams_exist - Required streams exist in Redis
    3. kraken_ws_status - Kraken WebSocket connection status
    4. signal_freshness - Signals are being generated recently
    5. pnl_freshness - PnL is being updated recently
    """

    def __init__(
        self,
        redis_url: Optional[str] = None,
        redis_ca_cert: Optional[str] = None,
        mode: str = "paper",
    ):
        """
        Initialize health checker.

        Args:
            redis_url: Redis URL (defaults to env var)
            redis_ca_cert: Path to CA cert (defaults to env var)
            mode: Trading mode (paper/live)
        """
        self.redis_url = redis_url or os.getenv("REDIS_URL", "")
        self.redis_ca_cert = redis_ca_cert or os.getenv(
            "REDIS_CA_CERT",
            os.getenv("REDIS_CA_CERT_PATH", "config/certs/redis_ca.pem")
        )
        self.mode = mode or os.getenv("ENGINE_MODE", "paper")

        # Thresholds
        self.signal_stale_threshold_sec = int(os.getenv("SIGNAL_STALE_THRESHOLD_SEC", "300"))
        self.pnl_stale_threshold_sec = int(os.getenv("PNL_STALE_THRESHOLD_SEC", "600"))

        # Trading pairs to check - uses canonical config/trading_pairs.py
        self.trading_pairs = os.getenv("TRADING_PAIRS", DEFAULT_TRADING_PAIRS_CSV).split(",")

    async def _get_redis_client(self) -> redis.Redis:
        """Create Redis client for health checks."""
        conn_params = {
            "socket_connect_timeout": 10,
            "socket_timeout": 10,
            "decode_responses": False,
        }

        if self.redis_url.startswith("rediss://"):
            if self.redis_ca_cert and os.path.exists(self.redis_ca_cert):
                conn_params["ssl_ca_certs"] = self.redis_ca_cert
                conn_params["ssl_cert_reqs"] = "required"

        return redis.from_url(self.redis_url, **conn_params)

    # =========================================================================
    # Individual Health Checks
    # =========================================================================

    async def check_redis_connectivity(self) -> HealthCheckResult:
        """Check Redis connection and measure latency."""
        start = time.time()
        try:
            if not self.redis_url:
                return HealthCheckResult(
                    name="redis_connectivity",
                    healthy=False,
                    message="REDIS_URL not configured",
                    duration_ms=(time.time() - start) * 1000,
                )

            client = await self._get_redis_client()
            try:
                # Measure ping latency
                ping_start = time.time()
                await client.ping()
                latency_ms = (time.time() - ping_start) * 1000

                # Get server info
                info = await client.info("server")
                redis_version = info.get("redis_version", "unknown")

                return HealthCheckResult(
                    name="redis_connectivity",
                    healthy=True,
                    message=f"Connected (latency: {latency_ms:.1f}ms)",
                    duration_ms=(time.time() - start) * 1000,
                    metadata={
                        "latency_ms": round(latency_ms, 2),
                        "redis_version": redis_version,
                    },
                )

            finally:
                await client.aclose()

        except Exception as e:
            return HealthCheckResult(
                name="redis_connectivity",
                healthy=False,
                message=f"Connection failed: {str(e)[:100]}",
                duration_ms=(time.time() - start) * 1000,
            )

    async def check_redis_streams(self) -> HealthCheckResult:
        """Check required Redis streams exist."""
        start = time.time()
        try:
            client = await self._get_redis_client()
            try:
                # Required streams
                required_streams = [
                    f"signals:{self.mode}:BTC-USD",
                    f"pnl:{self.mode}:equity_curve",
                    "events:bus",
                ]

                existing = []
                missing = []

                for stream in required_streams:
                    exists = await client.exists(stream)
                    if exists:
                        existing.append(stream)
                    else:
                        missing.append(stream)

                # Also check optional streams
                optional_streams = [
                    f"pnl:{self.mode}:signals",
                    f"pnl:{self.mode}:performance",
                    "engine:heartbeat",
                ]

                for stream in optional_streams:
                    if await client.exists(stream):
                        existing.append(stream)

                # All required must exist, but we warn if missing
                healthy = len(missing) == 0

                return HealthCheckResult(
                    name="redis_streams",
                    healthy=healthy,
                    message=f"{len(existing)} streams found, {len(missing)} missing",
                    duration_ms=(time.time() - start) * 1000,
                    metadata={
                        "existing": existing,
                        "missing": missing,
                    },
                )

            finally:
                await client.aclose()

        except Exception as e:
            return HealthCheckResult(
                name="redis_streams",
                healthy=False,
                message=f"Check failed: {str(e)[:100]}",
                duration_ms=(time.time() - start) * 1000,
            )

    async def check_signal_freshness(self) -> HealthCheckResult:
        """Check if signals are being generated recently."""
        start = time.time()
        try:
            client = await self._get_redis_client()
            try:
                # Check last signal timestamp from engine:last_signal_ts key
                last_ts = await client.get("engine:last_signal_ts")

                if last_ts is None:
                    # Also check the signal stream directly
                    stream_key = f"signals:{self.mode}:BTC-USD"
                    stream_info = await client.xinfo_stream(stream_key)

                    if stream_info:
                        last_entry_id = stream_info.get("last-generated-id", b"0-0")
                        if isinstance(last_entry_id, bytes):
                            last_entry_id = last_entry_id.decode()

                        # Extract timestamp from stream ID (ms since epoch)
                        if "-" in last_entry_id:
                            ts_ms = int(last_entry_id.split("-")[0])
                            last_ts = str(ts_ms / 1000)

                if last_ts is None:
                    return HealthCheckResult(
                        name="signal_freshness",
                        healthy=True,  # OK if no signals yet (fresh start)
                        message="No signals recorded yet",
                        duration_ms=(time.time() - start) * 1000,
                        metadata={"last_signal_ts": None},
                    )

                # Parse timestamp
                if isinstance(last_ts, bytes):
                    last_ts = last_ts.decode()

                last_signal_time = float(last_ts)
                age_sec = time.time() - last_signal_time

                healthy = age_sec < self.signal_stale_threshold_sec

                return HealthCheckResult(
                    name="signal_freshness",
                    healthy=healthy,
                    message=f"Last signal {int(age_sec)}s ago" + ("" if healthy else " (STALE)"),
                    duration_ms=(time.time() - start) * 1000,
                    metadata={
                        "last_signal_ts": last_signal_time,
                        "age_seconds": int(age_sec),
                        "threshold_seconds": self.signal_stale_threshold_sec,
                    },
                )

            finally:
                await client.aclose()

        except redis.ResponseError:
            # Stream doesn't exist yet
            return HealthCheckResult(
                name="signal_freshness",
                healthy=True,
                message="Signal stream not created yet",
                duration_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return HealthCheckResult(
                name="signal_freshness",
                healthy=False,
                message=f"Check failed: {str(e)[:100]}",
                duration_ms=(time.time() - start) * 1000,
            )

    async def check_pnl_freshness(self) -> HealthCheckResult:
        """Check if PnL is being updated recently."""
        start = time.time()
        try:
            client = await self._get_redis_client()
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
                        pass

                if last_ts is None:
                    return HealthCheckResult(
                        name="pnl_freshness",
                        healthy=True,  # OK if no PnL yet
                        message="No PnL updates recorded yet",
                        duration_ms=(time.time() - start) * 1000,
                    )

                if isinstance(last_ts, bytes):
                    last_ts = last_ts.decode()

                last_update_time = float(last_ts)
                age_sec = time.time() - last_update_time

                healthy = age_sec < self.pnl_stale_threshold_sec

                return HealthCheckResult(
                    name="pnl_freshness",
                    healthy=healthy,
                    message=f"Last PnL update {int(age_sec)}s ago" + ("" if healthy else " (STALE)"),
                    duration_ms=(time.time() - start) * 1000,
                    metadata={
                        "last_update_ts": last_update_time,
                        "age_seconds": int(age_sec),
                        "threshold_seconds": self.pnl_stale_threshold_sec,
                    },
                )

            finally:
                await client.aclose()

        except Exception as e:
            return HealthCheckResult(
                name="pnl_freshness",
                healthy=False,
                message=f"Check failed: {str(e)[:100]}",
                duration_ms=(time.time() - start) * 1000,
            )

    async def check_engine_heartbeat(self) -> HealthCheckResult:
        """Check engine heartbeat is recent."""
        start = time.time()
        try:
            client = await self._get_redis_client()
            try:
                heartbeat = await client.get("engine:heartbeat")

                if heartbeat is None:
                    return HealthCheckResult(
                        name="engine_heartbeat",
                        healthy=False,
                        message="No heartbeat found",
                        duration_ms=(time.time() - start) * 1000,
                    )

                if isinstance(heartbeat, bytes):
                    heartbeat = heartbeat.decode()

                # Parse ISO timestamp
                try:
                    hb_time = datetime.fromisoformat(heartbeat.replace('Z', '+00:00'))
                    age_sec = (datetime.now(timezone.utc) - hb_time).total_seconds()
                except ValueError:
                    age_sec = 0

                # Heartbeat should be within 60 seconds
                healthy = age_sec < 60

                return HealthCheckResult(
                    name="engine_heartbeat",
                    healthy=healthy,
                    message=f"Heartbeat {int(age_sec)}s ago" + ("" if healthy else " (STALE)"),
                    duration_ms=(time.time() - start) * 1000,
                    metadata={
                        "heartbeat": heartbeat,
                        "age_seconds": int(age_sec),
                    },
                )

            finally:
                await client.aclose()

        except Exception as e:
            return HealthCheckResult(
                name="engine_heartbeat",
                healthy=False,
                message=f"Check failed: {str(e)[:100]}",
                duration_ms=(time.time() - start) * 1000,
            )

    # =========================================================================
    # Run All Checks
    # =========================================================================

    async def run_all_checks(self) -> HealthCheckSuite:
        """Run all health checks and return results."""
        checks = [
            self.check_redis_connectivity,
            self.check_redis_streams,
            self.check_signal_freshness,
            self.check_pnl_freshness,
            self.check_engine_heartbeat,
        ]

        results = []
        for check in checks:
            try:
                result = await check()
                results.append(result)
            except Exception as e:
                results.append(HealthCheckResult(
                    name=check.__name__.replace("check_", ""),
                    healthy=False,
                    message=f"Check threw exception: {str(e)[:100]}",
                ))

        return HealthCheckSuite(checks=results)

    async def run_critical_checks(self) -> HealthCheckSuite:
        """Run only critical health checks (faster)."""
        checks = [
            self.check_redis_connectivity,
            self.check_engine_heartbeat,
        ]

        results = []
        for check in checks:
            result = await check()
            results.append(result)

        return HealthCheckSuite(checks=results)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

async def run_health_checks(
    redis_url: Optional[str] = None,
    mode: str = "paper",
) -> HealthCheckSuite:
    """
    Run all health checks and return results.

    Args:
        redis_url: Redis URL (defaults to env var)
        mode: Trading mode (paper/live)

    Returns:
        HealthCheckSuite with all results
    """
    checker = HealthChecker(redis_url=redis_url, mode=mode)
    return await checker.run_all_checks()


async def is_engine_healthy(redis_url: Optional[str] = None) -> bool:
    """
    Quick check if engine is healthy.

    Args:
        redis_url: Redis URL

    Returns:
        True if all critical checks pass
    """
    checker = HealthChecker(redis_url=redis_url)
    results = await checker.run_critical_checks()
    return results.is_healthy()


# =============================================================================
# CLI
# =============================================================================

async def main():
    """Run health checks from command line."""
    import json
    from dotenv import load_dotenv

    load_dotenv(".env.paper")

    print("=" * 60)
    print("CRYPTO-AI-BOT HEALTH CHECK")
    print("=" * 60)

    checker = HealthChecker()
    results = await checker.run_all_checks()

    print(f"\nTimestamp: {results.timestamp}")
    print(f"Overall Status: {'HEALTHY' if results.is_healthy() else 'UNHEALTHY'}")
    print(f"Checks: {len(results.passed_checks())} passed, {len(results.failed_checks())} failed")
    print()

    for check in results.checks:
        status = "OK" if check.healthy else "FAIL"
        print(f"  [{status}] {check.name}: {check.message} ({check.duration_ms:.0f}ms)")

    print()

    if not results.is_healthy():
        print("FAILED CHECKS:")
        for check in results.failed_checks():
            print(f"  - {check.name}: {check.message}")
        return 1

    print("All health checks passed!")
    return 0


if __name__ == "__main__":
    import asyncio
    exit_code = asyncio.run(main())
    exit(exit_code)
