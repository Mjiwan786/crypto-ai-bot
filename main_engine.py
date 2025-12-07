#!/usr/bin/env python3
"""
main_engine.py - Production-Ready Engine Entrypoint for crypto-ai-bot

This is the SINGLE canonical entrypoint for running the crypto trading engine.
It provides:
- 24/7 uptime with graceful error recovery
- Task supervision with exponential backoff
- Unified Redis client factory
- Health/heartbeat publishing for signals-api consumption
- Graceful shutdown on SIGTERM/SIGINT
- Environment-driven configuration (no hardcoded secrets)

Usage:
    python main_engine.py                    # Run in paper mode (default)
    python main_engine.py --mode live        # Run in live mode
    python main_engine.py --health-only      # Run health check and exit

Architecture (PRD-001):
    ConfigManager -> Kraken WS -> Signal Generation -> Redis Streams
                          |
                   Health Publisher -> engine:heartbeat, engine:last_signal_ts
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

# Load environment variables before any other imports
load_dotenv()

# Setup logging early
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
_log_format_env = os.getenv("LOG_FORMAT", "")
# Only use LOG_FORMAT if it contains % placeholders (valid Python format)
# Otherwise use default format (handles LOG_FORMAT=json case)
if _log_format_env and "%" in _log_format_env:
    LOG_FORMAT = _log_format_env
else:
    LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format=LOG_FORMAT,
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)

logger = logging.getLogger("main_engine")

# Version info
__version__ = "1.0.0"
ENGINE_CLIENT_NAME = "crypto-ai-bot-engine"


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class EngineSettings:
    """
    Engine settings derived from environment variables and config files.
    This is the single source of truth for all engine configuration.
    """
    # Mode
    trading_mode: str = field(default_factory=lambda: os.getenv("TRADING_MODE", "paper"))
    engine_mode: str = field(default_factory=lambda: os.getenv("ENGINE_MODE", "paper"))

    # Redis (all from environment)
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", ""))
    redis_ca_cert: Optional[str] = field(default_factory=lambda: os.getenv("REDIS_CA_CERT") or os.getenv("REDIS_CA_CERT_PATH"))

    # Trading pairs (comma-separated)
    trading_pairs: List[str] = field(default_factory=lambda: (
        os.getenv("TRADING_PAIRS", "BTC/USD,ETH/USD,SOL/USD").split(",")
    ))

    # Timeframes
    timeframes: List[str] = field(default_factory=lambda: (
        os.getenv("TIMEFRAMES", "15s,1m,5m").split(",")
    ))

    # Health/Heartbeat
    heartbeat_interval_sec: int = field(default_factory=lambda: int(os.getenv("HEARTBEAT_INTERVAL_SEC", "30")))
    heartbeat_ttl_sec: int = field(default_factory=lambda: int(os.getenv("HEARTBEAT_TTL_SEC", "60")))

    # Task supervision
    task_restart_delay_sec: float = field(default_factory=lambda: float(os.getenv("TASK_RESTART_DELAY_SEC", "5.0")))
    task_max_restart_delay_sec: float = field(default_factory=lambda: float(os.getenv("TASK_MAX_RESTART_DELAY_SEC", "300.0")))
    task_backoff_multiplier: float = field(default_factory=lambda: float(os.getenv("TASK_BACKOFF_MULTIPLIER", "2.0")))

    # Stream names (PRD-001 Section 2.2)
    @property
    def signal_stream(self) -> str:
        return f"signals:{self.trading_mode}"

    @property
    def pnl_stream(self) -> str:
        return f"pnl:{self.trading_mode}"

    @property
    def events_stream(self) -> str:
        return "events:bus"


# =============================================================================
# REDIS CLIENT FACTORY (Unified)
# =============================================================================

_redis_client: Optional[Any] = None
_redis_lock = asyncio.Lock()


async def get_redis_client(settings: EngineSettings) -> Any:
    """
    Get the unified Redis client instance.

    This is the SINGLE factory for Redis connections in the engine.
    Uses RedisCloudClient from agents/infrastructure/redis_client.py
    which handles TLS, connection pooling, and health checks.

    Args:
        settings: Engine settings with Redis configuration

    Returns:
        Connected Redis client instance
    """
    global _redis_client

    async with _redis_lock:
        if _redis_client is not None:
            # Check if still connected
            try:
                if hasattr(_redis_client, '_client') and _redis_client._client:
                    await _redis_client._client.ping()
                elif hasattr(_redis_client, 'ping'):
                    await _redis_client.ping()
                return _redis_client
            except Exception:
                logger.warning("Redis client disconnected, reconnecting...")
                _redis_client = None

        if not settings.redis_url:
            raise ValueError("REDIS_URL environment variable is required")

        # Try to use RedisCloudClient first (preferred)
        try:
            from agents.infrastructure.redis_client import RedisCloudClient, RedisCloudConfig

            config = RedisCloudConfig(
                url=settings.redis_url,
                ca_cert_path=settings.redis_ca_cert,
                client_name=ENGINE_CLIENT_NAME,
            )
            client = RedisCloudClient(config)
            await client.connect()
            _redis_client = client
            logger.info("Redis connected via RedisCloudClient")
            return _redis_client

        except ImportError:
            logger.warning("RedisCloudClient not available, using AsyncRedisManager")

        # Fallback to AsyncRedisManager
        try:
            from mcp.redis_manager import AsyncRedisManager, RedisConfig

            config = RedisConfig(
                url=settings.redis_url,
                ca_cert=settings.redis_ca_cert,
                client_name=ENGINE_CLIENT_NAME,
            )
            manager = AsyncRedisManager(config)
            await manager.aconnect()
            _redis_client = manager
            logger.info("Redis connected via AsyncRedisManager")
            return _redis_client

        except ImportError:
            logger.error("No Redis client available")
            raise ImportError("Neither RedisCloudClient nor AsyncRedisManager available")


async def close_redis_client():
    """Close the Redis client connection."""
    global _redis_client

    if _redis_client is not None:
        try:
            if hasattr(_redis_client, 'disconnect'):
                await _redis_client.disconnect()
            elif hasattr(_redis_client, 'aclose'):
                await _redis_client.aclose()
            elif hasattr(_redis_client, 'close'):
                await _redis_client.close()
            logger.info("Redis client disconnected")
        except Exception as e:
            logger.warning(f"Error closing Redis client: {e}")
        finally:
            _redis_client = None


# =============================================================================
# HEALTH PUBLISHER
# =============================================================================

class HealthPublisher:
    """
    Publishes engine health status to Redis for signals-api consumption.

    Keys published:
    - engine:heartbeat -> ISO timestamp (TTL 60s)
    - engine:last_signal_ts -> Epoch timestamp of last signal
    - engine:status -> JSON with uptime, mode, version, etc.
    """

    HEARTBEAT_KEY = "engine:heartbeat"
    LAST_SIGNAL_KEY = "engine:last_signal_ts"
    STATUS_KEY = "engine:status"

    def __init__(self, settings: EngineSettings):
        self.settings = settings
        self.start_time = time.time()
        self._last_signal_ts: float = 0.0
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self.logger = logging.getLogger("health_publisher")

    def record_signal(self, timestamp: Optional[float] = None):
        """Record that a signal was published."""
        self._last_signal_ts = timestamp or time.time()

    async def _publish_loop(self, redis_client: Any):
        """Background loop that publishes health status."""
        self._running = True
        interval = self.settings.heartbeat_interval_sec
        ttl = self.settings.heartbeat_ttl_sec

        self.logger.info(f"Starting health publisher: interval={interval}s, ttl={ttl}s")

        while self._running:
            try:
                now = datetime.now(timezone.utc)
                heartbeat_value = now.isoformat()

                # Get the underlying Redis client for direct operations
                client = redis_client
                if hasattr(redis_client, '_client') and redis_client._client is not None:
                    client = redis_client._client

                # Publish heartbeat with TTL
                await client.setex(self.HEARTBEAT_KEY, ttl, heartbeat_value)

                # Publish last signal timestamp
                if self._last_signal_ts > 0:
                    await client.set(self.LAST_SIGNAL_KEY, str(self._last_signal_ts))

                # Publish status JSON
                import json
                status = {
                    "version": __version__,
                    "mode": self.settings.trading_mode,
                    "uptime_sec": int(time.time() - self.start_time),
                    "heartbeat": heartbeat_value,
                    "last_signal_ts": self._last_signal_ts,
                    "pairs": self.settings.trading_pairs,
                }
                await client.setex(self.STATUS_KEY, ttl, json.dumps(status))

                self.logger.debug(f"Health published: {self.HEARTBEAT_KEY}={heartbeat_value}")

            except asyncio.CancelledError:
                self.logger.info("Health publisher cancelled")
                break
            except Exception as e:
                self.logger.warning(f"Failed to publish health: {e}")
                # Continue running despite errors

            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break

        self._running = False
        self.logger.info("Health publisher stopped")

    async def start(self, redis_client: Any):
        """Start the health publisher background task."""
        if self._task is not None and not self._task.done():
            return

        self._task = asyncio.create_task(
            self._publish_loop(redis_client),
            name="health_publisher"
        )

    async def stop(self):
        """Stop the health publisher."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None


# =============================================================================
# TASK SUPERVISOR
# =============================================================================

@dataclass
class SupervisedTask:
    """Configuration for a supervised task."""
    name: str
    coro_factory: Callable[[], Any]
    restart_on_failure: bool = True
    restart_count: int = 0
    max_restarts: int = -1  # -1 = unlimited
    last_restart: float = 0.0


class TaskSupervisor:
    """
    Supervises asyncio tasks with automatic restart and exponential backoff.

    Never lets a task die permanently unless:
    - Explicit cancellation via stop()
    - max_restarts exceeded (if set)
    - Unrecoverable error (e.g., configuration error)
    """

    def __init__(self, settings: EngineSettings):
        self.settings = settings
        self.tasks: Dict[str, SupervisedTask] = {}
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._shutdown = False
        self.logger = logging.getLogger("task_supervisor")

    def register(
        self,
        name: str,
        coro_factory: Callable[[], Any],
        restart_on_failure: bool = True,
        max_restarts: int = -1,
    ):
        """
        Register a task for supervision.

        Args:
            name: Unique task name
            coro_factory: Callable that returns a coroutine
            restart_on_failure: Whether to restart on failure
            max_restarts: Max restart attempts (-1 = unlimited)
        """
        self.tasks[name] = SupervisedTask(
            name=name,
            coro_factory=coro_factory,
            restart_on_failure=restart_on_failure,
            max_restarts=max_restarts,
        )
        self.logger.info(f"Registered task: {name} (restart={restart_on_failure})")

    def _calculate_backoff(self, task: SupervisedTask) -> float:
        """Calculate exponential backoff delay."""
        base = self.settings.task_restart_delay_sec
        multiplier = self.settings.task_backoff_multiplier
        max_delay = self.settings.task_max_restart_delay_sec

        delay = base * (multiplier ** min(task.restart_count, 10))
        return min(delay, max_delay)

    async def _run_supervised(self, name: str):
        """Run a task with supervision."""
        task_config = self.tasks[name]

        while not self._shutdown:
            try:
                self.logger.info(f"Starting task: {name}")
                coro = task_config.coro_factory()
                await coro

                # Task completed normally
                if self._shutdown:
                    break

                self.logger.info(f"Task {name} completed normally")

                if not task_config.restart_on_failure:
                    break

            except asyncio.CancelledError:
                self.logger.info(f"Task {name} cancelled")
                break

            except Exception as e:
                task_config.restart_count += 1
                task_config.last_restart = time.time()

                self.logger.error(
                    f"Task {name} failed (attempt {task_config.restart_count}): {e}",
                    exc_info=True
                )

                # Check max restarts
                if task_config.max_restarts >= 0 and task_config.restart_count > task_config.max_restarts:
                    self.logger.error(
                        f"Task {name} exceeded max restarts ({task_config.max_restarts}), giving up"
                    )
                    break

                if not task_config.restart_on_failure:
                    break

                # Exponential backoff before restart
                delay = self._calculate_backoff(task_config)
                self.logger.info(f"Restarting task {name} in {delay:.1f}s...")

                try:
                    await asyncio.sleep(delay)
                except asyncio.CancelledError:
                    break

        self.logger.info(f"Task supervisor for {name} exiting")

    async def start_all(self):
        """Start all registered tasks."""
        self._shutdown = False

        for name in self.tasks:
            if name not in self._running_tasks or self._running_tasks[name].done():
                self._running_tasks[name] = asyncio.create_task(
                    self._run_supervised(name),
                    name=f"supervisor_{name}"
                )

        self.logger.info(f"Started {len(self._running_tasks)} supervised tasks")

    async def stop_all(self):
        """Stop all supervised tasks gracefully."""
        self._shutdown = True

        for name, task in self._running_tasks.items():
            if not task.done():
                self.logger.info(f"Stopping task: {name}")
                task.cancel()

        if self._running_tasks:
            await asyncio.gather(*self._running_tasks.values(), return_exceptions=True)

        self._running_tasks.clear()
        self.logger.info("All tasks stopped")

    async def wait(self):
        """Wait for all tasks to complete (or supervisor shutdown)."""
        if self._running_tasks:
            await asyncio.gather(*self._running_tasks.values(), return_exceptions=True)


# =============================================================================
# SIGNAL GENERATION (Wrapper for existing engine components)
# =============================================================================

async def create_signal_generator(
    settings: EngineSettings,
    redis_client: Any,
    health_publisher: HealthPublisher,
) -> Callable[[], Any]:
    """
    Create a signal generation coroutine factory.

    This wraps the existing engine components (Kraken WS, regime detector,
    strategy router, risk manager) into a supervised task.
    """

    async def signal_generation_loop():
        """Main signal generation loop."""
        gen_logger = logging.getLogger("signal_generator")
        gen_logger.info(f"Starting signal generation: mode={settings.trading_mode}, pairs={settings.trading_pairs}")

        # Import engine components lazily to avoid import-time issues
        try:
            from utils.kraken_ws import KrakenWebSocketClient, KrakenWSConfig
            HAS_KRAKEN_WS = True
        except ImportError as e:
            gen_logger.warning(f"KrakenWebSocketClient not available: {e}")
            HAS_KRAKEN_WS = False

        if not HAS_KRAKEN_WS:
            gen_logger.error("Cannot start signal generation without Kraken WS client")
            # Keep running but do nothing (health publisher will still work)
            while True:
                await asyncio.sleep(60)
                gen_logger.warning("Signal generation disabled: no Kraken WS client")

        # Configure Kraken WS
        ws_config = KrakenWSConfig(
            pairs=settings.trading_pairs,
            timeframes=settings.timeframes,
            redis_url=settings.redis_url,
            trading_mode=settings.trading_mode,
        )

        # Create WS client
        ws_client = KrakenWebSocketClient(ws_config)

        # Connect and run
        try:
            # Run the WebSocket client (uses start() method)
            await ws_client.start()

        except Exception as e:
            gen_logger.error(f"Signal generation error: {e}")
            raise
        finally:
            # Cleanup
            if hasattr(ws_client, 'stop'):
                await ws_client.stop()
            elif hasattr(ws_client, 'close'):
                await ws_client.close()

    return signal_generation_loop


# =============================================================================
# MAIN ENGINE
# =============================================================================

class MainEngine:
    """
    The main engine that orchestrates all components.

    This is the single entrypoint for running the crypto trading engine.
    """

    def __init__(self, settings: EngineSettings):
        self.settings = settings
        self.logger = logging.getLogger("main_engine")

        # Components
        self.redis_client: Optional[Any] = None
        self.health_publisher = HealthPublisher(settings)
        self.task_supervisor = TaskSupervisor(settings)

        # Shutdown handling
        self._shutdown_event = asyncio.Event()
        self._shutdown_requested = False
        self._startup_started_at = time.monotonic()
        self._run_started_at: Optional[float] = None  # Track runtime for teardown logs

    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown."""
        loop = asyncio.get_event_loop()

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, self._request_shutdown, sig)
                self.logger.debug(f"Registered signal handler for {sig.name}")
            except NotImplementedError:
                # Windows doesn't support add_signal_handler
                signal.signal(sig, lambda s, f: self._request_shutdown(s))
                self.logger.debug(f"Registered signal handler for {sig} (Windows fallback)")

    def _request_shutdown(self, sig: Any = None):
        """Request graceful shutdown."""
        sig_name = sig.name if hasattr(sig, 'name') else str(sig)
        self.logger.info(f"Shutdown requested via signal: {sig_name}")
        self._shutdown_requested = True
        self._shutdown_event.set()

    async def initialize(self) -> bool:
        """Initialize all engine components."""
        self.logger.info("=" * 60)
        self.logger.info(f"Initializing crypto-ai-bot engine v{__version__}")
        self.logger.info(f"Mode: {self.settings.trading_mode}")
        self.logger.info(f"Pairs: {self.settings.trading_pairs}")
        self.logger.info("=" * 60)
        startup_marker = time.monotonic()

        try:
            # 1. Connect to Redis
            self.logger.info("Connecting to Redis...")
            self.redis_client = await get_redis_client(self.settings)
            self.logger.info("Redis connection established")

            # 2. Start health publisher
            self.logger.info("Starting health publisher...")
            await self.health_publisher.start(self.redis_client)

            # 3. Register supervised tasks
            self.logger.info("Registering supervised tasks...")

            # Signal generation task
            signal_gen_factory = await create_signal_generator(
                self.settings,
                self.redis_client,
                self.health_publisher,
            )
            self.task_supervisor.register(
                name="signal_generator",
                coro_factory=signal_gen_factory,
                restart_on_failure=True,
            )

            startup_duration = time.monotonic() - startup_marker
            # Extra context makes cold-start issues easier to trace
            self.logger.info(
                "Engine initialization complete in %.2fs (tasks=%d)",
                startup_duration,
                len(self.task_supervisor.tasks),
            )
            return True

        except Exception as e:
            self.logger.error(f"Failed to initialize engine: {e}", exc_info=True)
            return False

    async def run(self):
        """Run the engine until shutdown."""
        # Setup signal handlers
        self._setup_signal_handlers()

        # Initialize
        if not await self.initialize():
            self.logger.error("Engine initialization failed, exiting")
            return 1

        try:
            # Start all supervised tasks
            self.logger.info("Starting supervised tasks...")
            await self.task_supervisor.start_all()

            self._run_started_at = time.monotonic()
            # Include PID so operators can confirm the single engine process
            self.logger.info("Engine running as PID %s. Press Ctrl+C to stop.", os.getpid())

            # Wait for shutdown signal or all tasks to complete
            await self._shutdown_event.wait()

        except asyncio.CancelledError:
            self.logger.info("Engine cancelled")
        except Exception as e:
            self.logger.error(f"Engine error: {e}", exc_info=True)
        finally:
            await self.shutdown()

        return 0

    async def shutdown(self):
        """Graceful shutdown."""
        self.logger.info("Shutting down engine...")
        if self._run_started_at:
            runtime = time.monotonic() - self._run_started_at
            # Record runtime to correlate with uptime dashboards
            self.logger.info("Engine runtime before shutdown: %.2fs", runtime)

        # Stop task supervisor
        await self.task_supervisor.stop_all()

        # Stop health publisher
        await self.health_publisher.stop()

        # Close Redis
        await close_redis_client()

        self.logger.info("Engine shutdown complete")


# =============================================================================
# CLI
# =============================================================================

def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="crypto-ai-bot engine - Production-ready trading engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python main_engine.py                    # Run in paper mode
    python main_engine.py --mode live        # Run in live mode
    python main_engine.py --health-only      # Health check and exit
    python main_engine.py --version          # Show version
        """
    )

    parser.add_argument(
        "--mode",
        choices=["paper", "live"],
        default=os.getenv("TRADING_MODE", "paper"),
        help="Trading mode (default: paper)",
    )

    parser.add_argument(
        "--pairs",
        type=str,
        default=None,
        help="Comma-separated trading pairs (overrides env var)",
    )

    parser.add_argument(
        "--health-only",
        action="store_true",
        help="Run health check and exit",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"crypto-ai-bot engine v{__version__}",
    )

    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=None,
        help="Log level (overrides env var)",
    )

    return parser.parse_args()


async def health_check(settings: EngineSettings) -> int:
    """Run health check and return exit code."""
    logger.info("Running health check...")

    try:
        # Check Redis connection
        redis_client = await get_redis_client(settings)

        # Get underlying client for ping
        client = redis_client
        if hasattr(redis_client, '_client') and redis_client._client is not None:
            client = redis_client._client

        pong = await client.ping()

        if pong:
            logger.info("Health check PASSED: Redis connection OK")
            await close_redis_client()
            return 0
        else:
            logger.error("Health check FAILED: Redis ping returned False")
            await close_redis_client()
            return 1

    except Exception as e:
        logger.error(f"Health check FAILED: {e}")
        return 1


async def main(args):
    """Main entry point."""
    # Apply log level override
    if args.log_level:
        logging.getLogger().setLevel(getattr(logging, args.log_level))

    # Build settings
    settings = EngineSettings()

    # Apply CLI overrides
    if args.mode:
        settings.trading_mode = args.mode
        settings.engine_mode = args.mode

    if args.pairs:
        settings.trading_pairs = args.pairs.split(",")

    # Health check mode
    if args.health_only:
        return await health_check(settings)

    # Run engine
    engine = MainEngine(settings)
    return await engine.run()


if __name__ == "__main__":
    args = parse_args()

    try:
        exit_code = asyncio.run(main(args))
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
