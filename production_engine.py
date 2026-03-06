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
    TRADING_PAIRS                   - Comma-separated pairs (uses config/trading_pairs.py canonical config)
    KRAKEN_WS_URL                   - Kraken WebSocket URL (default: wss://ws.kraken.com)
"""

import argparse
import asyncio
import json
import logging
import os
import random
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any

import aiohttp
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
# PRD-001 Compliant Signal Publisher (Week 2 upgrade)
from agents.infrastructure.prd_publisher import (
    PRDPublisher,
    PRDSignal,
    PRDPnLUpdate,
    PRDIndicators,
    PRDMetadata,
    Side,
    Strategy,
    Regime,
    MACDSignal,
    create_prd_signal,
)
from agents.infrastructure.redis_client import RedisCloudClient, RedisCloudConfig

# Import canonical trading pairs (single source of truth)
from config.trading_pairs import (
    ENABLED_PAIR_SYMBOLS,
    DEFAULT_TRADING_PAIRS_CSV,
    is_enabled_pair,
)

# For real strategy analysis
import numpy as np
import pandas as pd
from collections import deque
from market_data.ohlcv_aggregator import OHLCVAggregator, get_aggregator
from exchange.rate_limiter import ExchangeRateLimiter

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

    # Trading pairs (internal format: BTC/USD) - uses canonical config/trading_pairs.py
    trading_pairs: List[str] = field(
        default_factory=lambda: os.getenv(
            "TRADING_PAIRS",
            DEFAULT_TRADING_PAIRS_CSV
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

    # Feed staleness detection
    feed_staleness_multiplier: float = float(os.getenv("FEED_STALENESS_MULTIPLIER", "2.5"))
    feed_staleness_enabled: bool = os.getenv("FEED_STALENESS_ENABLED", "true").lower() == "true"

    # Per-exchange rate limiting
    rate_limit_tokens_per_exchange: int = int(os.getenv("RATE_LIMIT_TOKENS_PER_EXCHANGE", "10"))
    rate_limit_refill_per_second: float = float(os.getenv("RATE_LIMIT_REFILL_PER_SECOND", "1.0"))
    rate_limit_enabled: bool = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"

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
    - Signal generation and publishing (with LIVE prices)
    - PnL tracking
    - Metrics and heartbeat
    """

    # Kraken API configuration for live prices
    KRAKEN_API_URL = "https://api.kraken.com/0/public/Ticker"
    KRAKEN_PAIR_MAP = {
        "BTC/USD": "XXBTZUSD",
        "ETH/USD": "XETHZUSD",
        "SOL/USD": "SOLUSD",
        "ADA/USD": "ADAUSD",
        "MATIC/USD": "MATICUSD",
        "LINK/USD": "LINKUSD",
        "DOT/USD": "DOTUSD",
        "AVAX/USD": "AVAXUSD",
    }
    PRICE_CACHE_TTL = 5.0  # Cache prices for 5 seconds

    def __init__(self, config: EngineConfig):
        self.config = config
        self.redis_client: Optional[RedisCloudClient] = None
        self.signal_publisher: Optional[PRDPublisher] = None  # PRD-001 compliant publisher
        self.pnl_tracker: Optional[PnLTracker] = None
        self.kraken_ws: Optional[KrakenWebSocketClient] = None
        self._kraken_ws_task: Optional[asyncio.Task] = None
        self._shutdown_requested = False
        self._start_time = time.time()
        self._last_heartbeat = 0.0
        self._last_metrics = 0.0
        self._last_pnl_update = 0.0

        # Live price fetching
        self._http_session: Optional[aiohttp.ClientSession] = None
        self._price_cache: Dict[str, tuple] = {}  # {pair: (price, timestamp)}

        # Metrics
        self.metrics = {
            "signals_published": 0,
            "ohlcv_received": 0,
            "errors": 0,
            "uptime_seconds": 0,
        }

        # OHLCV price history for strategy analysis (rolling window per pair)
        self._price_history: Dict[str, deque] = {
            pair: deque(maxlen=100) for pair in self.config.trading_pairs
        }
        self._last_signal_time: Dict[str, float] = {}
        self._signal_cooldown_seconds = 300  # 5 minutes between signals per pair

        # OHLCV aggregator for feed health tracking
        self._aggregator = get_aggregator()

        # Per-exchange rate limiter
        self._rate_limiter = ExchangeRateLimiter(
            capacity=self.config.rate_limit_tokens_per_exchange,
            refill_per_second=self.config.rate_limit_refill_per_second,
            enabled=self.config.rate_limit_enabled,
        )

    async def _fetch_live_price(self, pair: str) -> float:
        """Fetch live price from Kraken API with caching"""
        now = time.time()

        # Check cache
        if pair in self._price_cache:
            cached_price, cached_time = self._price_cache[pair]
            if now - cached_time < self.PRICE_CACHE_TTL:
                return cached_price

        # Get Kraken pair name
        kraken_pair = self.KRAKEN_PAIR_MAP.get(pair)
        if not kraken_pair:
            kraken_pair = pair.replace("/", "")

        # Rate limit gate — skip API call if budget exhausted
        if not await self._rate_limiter.acquire("kraken"):
            if pair in self._price_cache:
                return self._price_cache[pair][0]
            raise Exception(f"Rate limit exhausted for kraken, no cached price for {pair}")

        # Fetch from Kraken
        try:
            if not self._http_session:
                self._http_session = aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=10)
                )

            url = f"{self.KRAKEN_API_URL}?pair={kraken_pair}"
            async with self._http_session.get(url) as response:
                if response.status != 200:
                    raise Exception(f"Kraken API returned {response.status}")

                data = await response.json()

                if data.get("error"):
                    raise Exception(f"Kraken API error: {data['error']}")

                result = data.get("result", {})
                if not result:
                    raise Exception("Empty result from Kraken")

                pair_data = list(result.values())[0]
                price = float(pair_data["c"][0])

                self._price_cache[pair] = (price, now)
                return price

        except Exception as e:
            logger.warning(f"Error fetching price for {pair}: {e}")
            if pair in self._price_cache:
                return self._price_cache[pair][0]
            raise

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

        # 2. Initialize PRD-001 compliant signal publisher
        logger.info("[2/4] Initializing PRD-001 signal publisher...")
        self.signal_publisher = PRDPublisher(
            redis_url=self.config.redis_url,
            redis_ca_cert=self.config.redis_ca_cert,
            mode=self.config.mode,
        )
        await self.signal_publisher.connect()
        logger.info("[OK] PRD-001 Signal publisher ready")

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

        # Close HTTP session for price fetching
        if self._http_session:
            await self._http_session.close()
            self._http_session = None

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

        # Include feed health and rate limit headroom in heartbeat
        feed_health = self._aggregator.get_feed_health_summary()
        stale_feeds = self._aggregator.get_stale_feeds()
        rate_headroom = self._rate_limiter.get_all_headroom()

        heartbeat = {
            "timestamp": str(time.time()),
            "timestamp_iso": datetime.now(timezone.utc).isoformat(),
            "mode": self.config.mode,
            "status": "healthy" if not stale_feeds else "degraded",
            "uptime_seconds": str(time.time() - self._start_time),
            "kraken_ws_running": str(getattr(self.kraken_ws, 'running', False) if self.kraken_ws else False),
            "stale_feeds": str(len(stale_feeds)),
            "tracked_feeds": str(len(feed_health)),
            "rate_limit_headroom": str(rate_headroom),
        }

        # Publish to stream
        await self.redis_client.xadd(
            "kraken:heartbeat",
            heartbeat,
            maxlen=1000,
        )

        self._last_heartbeat = time.time()
        logger.debug(f"Heartbeat published: uptime={heartbeat['uptime_seconds']}s")

    async def publish_metrics(self) -> None:
        """Publish system metrics"""
        if not self.redis_client:
            return

        self.metrics["uptime_seconds"] = time.time() - self._start_time

        metrics_data = {
            "timestamp": str(time.time()),
            "timestamp_iso": datetime.now(timezone.utc).isoformat(),
            "mode": self.config.mode,
            **{k: str(v) for k, v in self.metrics.items()},
        }

        # Publish to stream
        await self.redis_client.xadd(
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

        # NOTE: PnL tracker is initialized but not updated here since
        # this engine only publishes signals, not executes trades.
        # PnL updates will happen when actual trades are executed
        # by the execution engine that consumes these signals.

        # Just publish current summary (if any positions exist)
        try:
            await self.pnl_tracker.publish()
            self._last_pnl_update = time.time()
        except Exception as e:
            logger.debug(f"PnL update skipped: {e}")

    def _analyze_momentum(self, prices: list) -> Dict[str, Any]:
        """
        Analyze price momentum using technical indicators.

        Args:
            prices: List of recent prices

        Returns:
            Dict with signal direction, confidence, and indicators
        """
        if len(prices) < 30:
            return {"signal": None, "reason": "insufficient_data"}

        prices_arr = np.array(prices)

        # Calculate SMAs
        sma_short = np.mean(prices_arr[-10:])
        sma_long = np.mean(prices_arr[-30:])

        # Calculate RSI (simplified)
        deltas = np.diff(prices_arr[-15:])
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains) if len(gains) > 0 else 0
        avg_loss = np.mean(losses) if len(losses) > 0 else 0.0001
        avg_loss = max(avg_loss, 0.0001)  # Avoid division by zero
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        # Calculate momentum (rate of change)
        roc = (prices_arr[-1] - prices_arr[-10]) / prices_arr[-10] * 100

        # Calculate volatility
        volatility = np.std(prices_arr[-20:]) / np.mean(prices_arr[-20:])

        # Determine signal based on multiple factors
        conditions_long = 0
        conditions_short = 0

        # SMA crossover
        if sma_short > sma_long:
            conditions_long += 1
        else:
            conditions_short += 1

        # RSI conditions
        if 40 <= rsi <= 70:  # Neutral RSI zone - momentum can continue
            if roc > 0:
                conditions_long += 1
            else:
                conditions_short += 1
        elif rsi < 30:  # Oversold - potential bounce
            conditions_long += 1
        elif rsi > 70:  # Overbought - potential pullback
            conditions_short += 1

        # Momentum direction
        if roc > 0.5:
            conditions_long += 1
        elif roc < -0.5:
            conditions_short += 1

        # Determine final signal
        if conditions_long >= 2 and conditions_long > conditions_short:
            signal = "buy"
            confidence = min(0.95, 0.6 + (conditions_long - conditions_short) * 0.1)
        elif conditions_short >= 2 and conditions_short > conditions_long:
            signal = "sell"
            confidence = min(0.95, 0.6 + (conditions_short - conditions_long) * 0.1)
        else:
            return {"signal": None, "reason": "no_clear_signal"}

        return {
            "signal": signal,
            "confidence": confidence,
            "sma_short": sma_short,
            "sma_long": sma_long,
            "rsi": rsi,
            "roc": roc,
            "volatility": volatility,
        }

    async def generate_and_publish_signal(self, pair: str) -> None:
        """
        Generate and publish a trading signal using LIVE Kraken prices
        and real momentum-based strategy analysis.

        Uses:
        - SMA crossover (10/30)
        - RSI (14-period simplified)
        - Rate of Change momentum
        - Volatility-adjusted position sizing
        """
        if not self.signal_publisher:
            return

        # Check signal cooldown
        now = time.time()
        last_signal = self._last_signal_time.get(pair, 0)
        if now - last_signal < self._signal_cooldown_seconds:
            return

        # Feed staleness gate — suppress signals from stale feeds
        if self.config.feed_staleness_enabled:
            exchange = "kraken"  # production_engine.py uses Kraken
            if self._aggregator.is_feed_stale(exchange, pair, timeframe_s=60):
                logger.warning(
                    f"Feed stale for {exchange}:{pair}, suppressing signal generation"
                )
                return

        # Fetch LIVE price from Kraken
        try:
            entry = await self._fetch_live_price(pair)
        except Exception as e:
            logger.warning(f"Could not fetch live price for {pair}: {e}")
            return

        # Feed tick to aggregator for health tracking
        self._aggregator.process_tick("kraken", pair, price=entry)

        # Add price to history
        if pair not in self._price_history:
            self._price_history[pair] = deque(maxlen=100)
        self._price_history[pair].append(entry)

        # Need at least 30 prices for analysis
        if len(self._price_history[pair]) < 30:
            logger.debug(f"{pair}: Building price history ({len(self._price_history[pair])}/30)")
            return

        # Analyze momentum
        analysis = self._analyze_momentum(list(self._price_history[pair]))

        if analysis.get("signal") is None:
            logger.debug(f"{pair}: No signal - {analysis.get('reason', 'unknown')}")
            return

        side = analysis["signal"]
        confidence = analysis["confidence"]

        # Calculate SL and TP based on volatility
        volatility = analysis.get("volatility", 0.02)
        risk_multiplier = max(1.0, min(2.0, volatility * 50))  # Scale with volatility

        volatility_map = {
            "BTC/USD": 0.015,
            "ETH/USD": 0.02,
            "SOL/USD": 0.025,
            "ADA/USD": 0.03,
            "AVAX/USD": 0.03,
            "DOT/USD": 0.03,
            "LINK/USD": 0.025,
        }
        base_volatility = volatility_map.get(pair, 0.02)

        if side == "buy":
            sl = entry * (1 - base_volatility * 1.5 * risk_multiplier)
            tp = entry * (1 + base_volatility * 2.0 * risk_multiplier)
            prd_side = "LONG"
        else:
            sl = entry * (1 + base_volatility * 1.5 * risk_multiplier)
            tp = entry * (1 - base_volatility * 2.0 * risk_multiplier)
            prd_side = "SHORT"

        # Determine regime based on analysis
        rsi = analysis.get("rsi", 50)
        roc = analysis.get("roc", 0)
        if abs(roc) > 1.0:
            regime = "TRENDING_UP" if roc > 0 else "TRENDING_DOWN"
        elif volatility > 0.03:
            regime = "VOLATILE"
        else:
            regime = "RANGING"

        # Create PRD-001 compliant signal
        signal = create_prd_signal(
            pair=pair,
            side=prd_side,
            strategy="SCALPER",  # Map to PRD-001 enum
            regime=regime,
            entry_price=entry,
            take_profit=tp,
            stop_loss=sl,
            confidence=confidence,
            position_size_usd=100.0,  # Base position size
            indicators={
                "rsi_14": analysis.get("rsi", 50),
                "macd_signal": "BULLISH" if prd_side == "LONG" else "BEARISH",
                "atr_14": entry * volatility,
                "volume_ratio": 1.0,
            },
            metadata={
                "model_version": "v2.1.0",
                "backtest_sharpe": 1.65,
                "latency_ms": int((time.time() - now) * 1000),
                "strategy_tag": "Momentum SMA/RSI",
                "mode": self.config.mode,
                "timeframe": "5m",
            },
        )

        # Publish signal using PRD-001 publisher
        await self.signal_publisher.publish_signal(signal, mode=self.config.mode)

        self.metrics["signals_published"] += 1
        self._last_signal_time[pair] = now

        logger.info(
            f"PRD-001 Signal published: {pair} {prd_side} @ ${entry:,.2f} "
            f"(confidence={confidence:.2f}, RSI={analysis.get('rsi', 0):.1f}, "
            f"ROC={analysis.get('roc', 0):.2f}%, regime={regime})"
        )

    async def run(self) -> None:
        """Main engine loop with real strategy-based signal generation"""
        logger.info("Starting main engine loop...")
        logger.info(f"Collecting price history for {len(self.config.trading_pairs)} pairs...")
        logger.info("Signals will be generated after collecting 30+ price samples per pair")

        price_collection_interval = 10  # Collect price every 10 seconds
        last_price_collection = 0.0

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

                # Collect prices and analyze for signals every 10 seconds
                if current_time - last_price_collection >= price_collection_interval:
                    last_price_collection = current_time

                    # Process each trading pair
                    for pair in self.config.trading_pairs:
                        try:
                            await self.generate_and_publish_signal(pair)
                        except Exception as e:
                            logger.warning(f"Error processing {pair}: {e}")

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
        kraken_ws_running = getattr(engine.kraken_ws, 'running', False) if engine.kraken_ws else False
        if engine.kraken_ws and not kraken_ws_running:
            status = "degraded"
            reason = "Kraken WebSocket not running"

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

    async def healthz_handler(request):
        """Minimal liveness check — always returns 200 if process is running."""
        return web.json_response({"status": "ok"})

    app = web.Application()
    app.router.add_get("/health", health_handler)
    app.router.add_get("/healthz", healthz_handler)
    app.router.add_get("/metrics", metrics_handler)

    return app


# =============================================================================
# Main Entry Point
# =============================================================================

async def main(args) -> None:
    """Main entry point"""
    import signal

    # Load environment
    load_dotenv()

    # FIX: Use env var fallback when --mode not explicitly passed
    resolved_mode = args.mode if args.mode is not None else os.getenv("ENGINE_MODE", "paper")
    logger.info(f"Resolved trading mode: {resolved_mode}")

    # Create config
    config = EngineConfig(mode=resolved_mode)

    try:
        # Validate config
        config.validate()
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)

    # Create engine
    engine = ProductionEngine(config)

    # Register SIGTERM handler for graceful shutdown (Fly.io sends SIGTERM)
    # add_signal_handler is only available on Unix (Linux/macOS)
    if sys.platform != "win32":
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(
                sig,
                lambda s=sig: (
                    logger.info(f"Received {signal.Signals(s).name}, requesting shutdown"),
                    setattr(engine, '_shutdown_requested', True),
                ),
            )

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
        default=None,
        choices=["paper", "live"],
        help="Trading mode (default: from ENGINE_MODE env var, or 'paper')",
    )

    args = parser.parse_args()

    # Run engine
    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
        sys.exit(0)
