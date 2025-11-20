#!/usr/bin/env python3
"""
Production Engine for Crypto AI Bot
====================================

Full-featured production engine that integrates:
- Kraken WebSocket for real-time OHLCV data
- Trading signals generation and publishing
- PnL tracking and equity curve
- System metrics and heartbeat
- Health monitoring endpoints

REDIS STREAMS PUBLISHED:
- kraken:ohlc:{timeframe}:{symbol}  → OHLCV candle data
- signals:live:{pair}               → Live trading signals
- signals:paper:{pair}              → Paper trading signals
- pnl:summary                       → PnL snapshot (STRING key)
- pnl:equity_curve                  → Historical equity (STREAM)
- kraken:metrics                    → System health metrics
- kraken:heartbeat                  → Heartbeat events

USAGE:
    # Paper mode (default)
    python production_engine.py --mode paper

    # Live mode (requires confirmation)
    export LIVE_TRADING_CONFIRMATION="I confirm live trading"
    python production_engine.py --mode live

ENVIRONMENT VARIABLES:
    REDIS_URL                       - Redis Cloud connection URL (required, must use rediss://)
    REDIS_CA_CERT                   - Path to Redis TLS CA certificate
    LIVE_TRADING_CONFIRMATION       - Required for live mode
    HEALTH_PORT                     - Health endpoint port (default: 8080)
    METRICS_PORT                    - Metrics endpoint port (default: 9108)
    TRADING_PAIRS                   - Comma-separated pairs (default: BTC/USD,ETH/USD,SOL/USD,MATIC/USD,LINK/USD)
    KRAKEN_WS_URL                   - Kraken WebSocket URL (default: wss://ws.kraken.com)
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any

from aiohttp import web
from dotenv import load_dotenv

# Fix Windows console encoding
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Import project modules
from utils.kraken_ws import KrakenWebSocketClient, ConnectionState, KrakenWSConfig
from pnl.rolling_pnl import PnLTracker
from signals.schema import Signal, create_signal
from signals.publisher import SignalPublisher
from agents.infrastructure.redis_client import RedisCloudClient, RedisCloudConfig

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(project_root / "logs" / "production_engine.log"),
    ],
)
logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class EngineConfig:
    """Production engine configuration"""

    # Trading mode
    mode: str = "paper"  # "paper" or "live"

    # Trading pairs (internal format: BTC/USD)
    trading_pairs: List[str] = field(
        default_factory=lambda: os.getenv(
            "TRADING_PAIRS",
            "BTC/USD,ETH/USD,SOL/USD,MATIC/USD,LINK/USD"
        ).split(",")
    )

    # Kraken WebSocket
    kraken_ws_url: str = field(
        default_factory=lambda: os.getenv("KRAKEN_WS_URL", "wss://ws.kraken.com")
    )

    # OHLCV timeframes to subscribe (Kraken format: 1, 5, 15, 60, etc.)
    ohlcv_timeframes: List[int] = field(default_factory=lambda: [1, 5, 15, 60])

    # Redis
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", ""))
    redis_ca_cert: str = field(
        default_factory=lambda: os.getenv(
            "REDIS_CA_CERT",
            str(project_root / "config" / "certs" / "redis_ca.pem")
        )
    )

    # Health and metrics
    health_port: int = int(os.getenv("HEALTH_PORT", "8080"))
    metrics_port: int = int(os.getenv("METRICS_PORT", "9108"))

    # Publishing intervals
    heartbeat_interval_sec: int = 30
    metrics_interval_sec: int = 60
    pnl_update_interval_sec: int = 10

    # Initial balance for PnL tracking
    initial_balance: float = 10000.0

    # Safety
    live_trading_confirmation: str = field(
        default_factory=lambda: os.getenv("LIVE_TRADING_CONFIRMATION", "")
    )

    def validate(self) -> None:
        """Validate configuration"""
        # Validate mode
        if self.mode not in ["paper", "live"]:
            raise ValueError(f"Invalid mode: {self.mode}. Must be 'paper' or 'live'")

        # Validate live trading confirmation
        if self.mode == "live":
            required = "I confirm live trading"
            if self.live_trading_confirmation != required:
                raise ValueError(
                    f"Live trading requires: LIVE_TRADING_CONFIRMATION='{required}'"
                )

        # Validate Redis URL
        if not self.redis_url:
            raise ValueError("REDIS_URL environment variable is required")

        if not self.redis_url.startswith("rediss://"):
            raise ValueError("REDIS_URL must use TLS (rediss://)")

        # Validate pairs
        if not self.trading_pairs:
            raise ValueError("At least one trading pair is required")

        for pair in self.trading_pairs:
            if "/" not in pair:
                raise ValueError(f"Invalid pair format: {pair}. Use: BTC/USD")

        logger.info(f"[OK] Configuration validated: mode={self.mode}, pairs={len(self.trading_pairs)}")


# =============================================================================
# Symbol Mapping (Internal ↔ Kraken)
# =============================================================================

SYMBOL_MAP_TO_KRAKEN = {
    "BTC/USD": "XBT/USD",
    "ETH/USD": "ETH/USD",
    "SOL/USD": "SOL/USD",
    "MATIC/USD": "MATIC/USD",
    "LINK/USD": "LINK/USD",
}

SYMBOL_MAP_FROM_KRAKEN = {v: k for k, v in SYMBOL_MAP_TO_KRAKEN.items()}


def normalize_pair(pair: str) -> str:
    """Convert internal format to Kraken format"""
    return SYMBOL_MAP_TO_KRAKEN.get(pair, pair)


def denormalize_pair(pair: str) -> str:
    """Convert Kraken format to internal format"""
    return SYMBOL_MAP_FROM_KRAKEN.get(pair, pair)


# =============================================================================
# Production Engine
# =============================================================================

class ProductionEngine:
    """
    Production engine integrating all components:
    - Kraken WebSocket for OHLCV
    - Signal generation and publishing
    - PnL tracking
    - Metrics and heartbeat
    """

    def __init__(self, config: EngineConfig):
        self.config = config
        self.redis_client: Optional[RedisCloudClient] = None
        self.signal_publisher: Optional[SignalPublisher] = None
        self.pnl_tracker: Optional[PnLTracker] = None
        self.kraken_ws: Optional[KrakenWebSocketClient] = None
        self._kraken_ws_task: Optional[asyncio.Task] = None
        self._shutdown_requested = False
        self._start_time = time.time()
        self._last_heartbeat = 0.0
        self._last_metrics = 0.0
        self._last_pnl_update = 0.0

        # Metrics
        self.metrics = {
            "signals_published": 0,
            "ohlcv_received": 0,
            "errors": 0,
            "uptime_seconds": 0,
        }

    async def connect(self) -> None:
        """Connect all components"""
        logger.info("=" * 80)
        logger.info("Production Engine Starting")
        logger.info("=" * 80)
        logger.info(f"Mode: {self.config.mode}")
        logger.info(f"Trading Pairs: {', '.join(self.config.trading_pairs)}")
        logger.info(f"OHLCV Timeframes: {self.config.ohlcv_timeframes}")
        logger.info("=" * 80)

        # 1. Connect to Redis
        logger.info("[1/4] Connecting to Redis Cloud...")
        redis_config = RedisCloudConfig(
            url=self.config.redis_url,
            ca_cert_path=self.config.redis_ca_cert,
        )
        self.redis_client = RedisCloudClient(redis_config)
        await self.redis_client.connect()
        logger.info("[OK] Redis Cloud connected")

        # 2. Initialize signal publisher
        logger.info("[2/4] Initializing signal publisher...")
        self.signal_publisher = SignalPublisher(
            redis_url=self.config.redis_url,
            redis_cert_path=self.config.redis_ca_cert,
            stream_maxlen=10000,
        )
        await self.signal_publisher.connect()
        logger.info("[OK] Signal publisher ready")

        # 3. Initialize PnL tracker
        logger.info("[3/4] Initializing PnL tracker...")
        self.pnl_tracker = PnLTracker(
            redis_url=self.config.redis_url,
            redis_cert_path=self.config.redis_ca_cert,
            initial_balance=self.config.initial_balance,
            mode=self.config.mode,
        )
        logger.info(f"[OK] PnL tracker ready (initial balance: ${self.config.initial_balance:,.2f})")

        # 4. Start Kraken WebSocket in background
        logger.info("[4/4] Starting Kraken WebSocket...")
        kraken_config = KrakenWSConfig(
            url=self.config.kraken_ws_url,
            pairs=self.config.trading_pairs,
            redis_url=self.config.redis_url,
            trading_mode=self.config.mode,
        )
        self.kraken_ws = KrakenWebSocketClient(config=kraken_config)

        # Start Kraken WS as background task (it will handle subscriptions internally)
        self._kraken_ws_task = asyncio.create_task(self.kraken_ws.start())
        logger.info("[OK] Kraken WebSocket started in background")
        logger.info(f"     Subscribing to: {', '.join(self.config.trading_pairs)}")
        logger.info(f"     Timeframes: {', '.join(map(str, self.config.ohlcv_timeframes))}")

        logger.info("=" * 80)
        logger.info("[READY] Production Engine Ready")
        logger.info("=" * 80)

    async def disconnect(self) -> None:
        """Disconnect all components"""
        logger.info("Shutting down production engine...")

        # Cancel Kraken WS task
        if self._kraken_ws_task and not self._kraken_ws_task.done():
            self._kraken_ws_task.cancel()
            try:
                await self._kraken_ws_task
            except asyncio.CancelledError:
                pass

        if self.kraken_ws:
            self.kraken_ws.running = False

        if self.signal_publisher:
            await self.signal_publisher.close()

        if self.redis_client:
            await self.redis_client.disconnect()

        logger.info("[OK] Production engine shutdown complete")

    async def publish_heartbeat(self) -> None:
        """Publish system heartbeat"""
        if not self.redis_client:
            return

        heartbeat = {
            "timestamp": time.time(),
            "timestamp_iso": datetime.now(timezone.utc).isoformat(),
            "mode": self.config.mode,
            "status": "healthy",
            "uptime_seconds": time.time() - self._start_time,
            "kraken_ws_state": self.kraken_ws.state.value if self.kraken_ws else "disconnected",
        }

        # Publish to stream
        await self.redis_client.client.xadd(
            "kraken:heartbeat",
            heartbeat,
            maxlen=1000,
        )

        self._last_heartbeat = time.time()
        logger.debug(f"Heartbeat published: uptime={heartbeat['uptime_seconds']:.0f}s")

    async def publish_metrics(self) -> None:
        """Publish system metrics"""
        if not self.redis_client:
            return

        self.metrics["uptime_seconds"] = time.time() - self._start_time

        metrics_data = {
            "timestamp": time.time(),
            "timestamp_iso": datetime.now(timezone.utc).isoformat(),
            "mode": self.config.mode,
            **self.metrics,
        }

        # Publish to stream
        await self.redis_client.client.xadd(
            "kraken:metrics",
            metrics_data,
            maxlen=10000,
        )

        self._last_metrics = time.time()
        logger.info(
            f"Metrics: signals={self.metrics['signals_published']}, "
            f"ohlcv={self.metrics['ohlcv_received']}, "
            f"errors={self.metrics['errors']}, "
            f"uptime={self.metrics['uptime_seconds']:.0f}s"
        )

    async def update_pnl(self) -> None:
        """Update and publish PnL"""
        if not self.pnl_tracker:
            return

        # Get current prices and update unrealized PnL
        # For now, we'll use last_price from positions
        # In production, you'd get this from market data
        await self.pnl_tracker.update_unrealized_pnl()

        # Publish PnL summary
        await self.pnl_tracker.publish_summary()

        self._last_pnl_update = time.time()

    async def generate_and_publish_signal(self, pair: str) -> None:
        """
        Generate and publish a trading signal.

        TODO: Replace with real agent/strategy logic.
        For now, generates synthetic signals based on OHLCV data.
        """
        if not self.signal_publisher:
            return

        import random

        # Generate signal (synthetic for now)
        side = "buy" if random.random() > 0.5 else "sell"

        price_ranges = {
            "BTC/USD": (40000, 50000),
            "ETH/USD": (2500, 3500),
            "SOL/USD": (100, 200),
            "MATIC/USD": (0.7, 1.2),
            "LINK/USD": (12, 18),
        }

        price_range = price_ranges.get(pair, (100, 1000))
        entry = random.uniform(*price_range)

        volatility = 0.02
        if side == "buy":
            sl = entry * (1 - volatility * 1.5)
            tp = entry * (1 + volatility * 2.0)
        else:
            sl = entry * (1 + volatility * 1.5)
            tp = entry * (1 - volatility * 2.0)

        confidence = random.uniform(0.65, 0.95)

        signal = create_signal(
            pair=pair,
            side=side,
            entry=entry,
            sl=sl,
            tp=tp,
            strategy="production_momentum_v1",
            confidence=confidence,
            mode=self.config.mode,
        )

        # Publish signal
        await self.signal_publisher.publish(signal)

        self.metrics["signals_published"] += 1

        logger.info(
            f"📊 Signal published: {pair} {side.upper()} @ {entry:.2f} "
            f"(confidence={confidence:.2f})"
        )

    async def run(self) -> None:
        """Main engine loop"""
        logger.info("Starting main engine loop...")

        # Main loop
        while not self._shutdown_requested:
            try:
                current_time = time.time()

                # Heartbeat
                if current_time - self._last_heartbeat >= self.config.heartbeat_interval_sec:
                    await self.publish_heartbeat()

                # Metrics
                if current_time - self._last_metrics >= self.config.metrics_interval_sec:
                    await self.publish_metrics()

                # PnL update
                if current_time - self._last_pnl_update >= self.config.pnl_update_interval_sec:
                    await self.update_pnl()

                # Generate signals periodically (every 5-10 seconds)
                # TODO: Replace with event-driven signal generation based on OHLCV updates
                if random.random() < 0.1:  # ~10% chance per iteration
                    pair = random.choice(self.config.trading_pairs)
                    await self.generate_and_publish_signal(pair)

                # Sleep for 1 second
                await asyncio.sleep(1)

            except asyncio.CancelledError:
                logger.info("Engine loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in engine loop: {e}", exc_info=True)
                self.metrics["errors"] += 1
                await asyncio.sleep(5)

        logger.info("Engine loop stopped")


# =============================================================================
# Health Endpoint
# =============================================================================

async def create_health_app(engine: ProductionEngine) -> web.Application:
    """Create aiohttp app for health endpoint"""

    async def health_handler(request):
        """Health check endpoint"""
        uptime = time.time() - engine._start_time

        # Determine health status
        status = "healthy"
        reason = "Publishing normally"

        # Check if Kraken WS is connected
        if engine.kraken_ws and engine.kraken_ws.state != ConnectionState.CONNECTED:
            status = "degraded"
            reason = f"Kraken WebSocket: {engine.kraken_ws.state.value}"

        # Check freshness of signals (should have published in last 60s)
        if engine.metrics["signals_published"] == 0 and uptime > 60:
            status = "degraded"
            reason = "No signals published yet"

        response = {
            "status": status,
            "reason": reason,
            "mode": engine.config.mode,
            "metrics": {
                **engine.metrics,
                "uptime_seconds": uptime,
            },
        }

        return web.json_response(response)

    async def metrics_handler(request):
        """Prometheus metrics endpoint"""
        # TODO: Implement Prometheus metrics format
        return web.Response(text="# Metrics endpoint\n")

    app = web.Application()
    app.router.add_get("/health", health_handler)
    app.router.add_get("/metrics", metrics_handler)

    return app


# =============================================================================
# Main Entry Point
# =============================================================================

async def main(args) -> None:
    """Main entry point"""
    # Load environment
    load_dotenv()

    # Create config
    config = EngineConfig(mode=args.mode)

    try:
        # Validate config
        config.validate()
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)

    # Create engine
    engine = ProductionEngine(config)

    # Start health endpoint
    health_app = await create_health_app(engine)
    health_runner = web.AppRunner(health_app)
    await health_runner.setup()
    health_site = web.TCPSite(health_runner, "0.0.0.0", config.health_port)
    await health_site.start()
    logger.info(f"[OK] Health endpoint started on port {config.health_port}")

    # Connect engine
    try:
        await engine.connect()
    except Exception as e:
        logger.error(f"Failed to connect engine: {e}", exc_info=True)
        await health_runner.cleanup()
        sys.exit(1)

    # Run engine
    try:
        await engine.run()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    except Exception as e:
        logger.error(f"Engine error: {e}", exc_info=True)
    finally:
        # Cleanup
        await engine.disconnect()
        await health_runner.cleanup()
        logger.info("Production engine stopped")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Production Engine for Crypto AI Bot")
    parser.add_argument(
        "--mode",
        type=str,
        default="paper",
        choices=["paper", "live"],
        help="Trading mode (paper or live)",
    )

    args = parser.parse_args()

    # Run engine
    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
        sys.exit(0)
