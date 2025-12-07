"""
engine/loop.py - Live Trading Engine Loop

Production-grade live engine that wires:
WS → indicators → regime → router → strategy → risk → publisher

Features:
- Rolling OHLCV cache with configurable window
- Cached indicator computation
- Circuit breakers for spread/latency
- Scalper throttle enforcement
- Decision and publish latency tracking
- Paper mode only (mode=paper)

Architecture (PRD §3, §9, §11):
1. Subscribe to Kraken WS (trades, spread, ohlc)
2. Maintain rolling OHLCV buffer
3. On each tick:
   - Update indicators
   - Detect regime
   - Route to appropriate strategy
   - Size position via risk manager
   - Publish SignalDTO to Redis (mode=paper)
4. Enforce breakers:
   - SPREAD_BPS_MAX
   - LATENCY_MS_MAX
   - SCALP_MAX_TRADES_PER_MINUTE

Author: Crypto AI Bot Team
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Deque, Dict, List, Optional

import pandas as pd
import numpy as np

from utils.kraken_ws import KrakenWebSocketClient, KrakenWSConfig
from ai_engine.regime_detector.detector import RegimeDetector, RegimeConfig
from agents.strategy_router import StrategyRouter, RouterConfig
from agents.risk_manager import RiskManager, RiskConfig, SignalInput
from strategies.momentum_strategy import MomentumStrategy
from strategies.mean_reversion import MeanReversionStrategy
from streams.publisher import SignalPublisher, PublisherConfig
from models.signal_dto import create_signal_dto
from ai_engine.schemas import MarketSnapshot

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class EngineConfig:
    """Live engine configuration"""

    # Data window
    ohlcv_window_size: int = 300  # Keep last 300 bars (~25 hours at 5m)
    min_bars_required: int = 100  # Minimum bars before generating signals

    # Trading mode
    mode: str = "paper"  # Only paper mode for now

    # Circuit breakers (from env)
    spread_bps_max: float = field(
        default_factory=lambda: float(os.getenv("SPREAD_BPS_MAX", "5.0"))
    )
    latency_ms_max: float = field(
        default_factory=lambda: float(os.getenv("LATENCY_MS_MAX", "500.0"))
    )
    scalp_max_trades_per_minute: int = field(
        default_factory=lambda: int(os.getenv("SCALP_MAX_TRADES_PER_MINUTE", "3"))
    )

    # Throttling
    signal_cooldown_seconds: int = 60  # Minimum seconds between signals per pair

    # Equity (for risk sizing)
    initial_equity_usd: Decimal = Decimal("10000.00")

    # Redis
    redis_url: str = field(
        default_factory=lambda: os.getenv("REDIS_URL", "")
    )
    redis_ca_cert: str = field(
        default_factory=lambda: os.getenv("REDIS_CA_CERT") or os.getenv("REDIS_CA_CERT_PATH") or ""
    )

    # Logging
    log_level: str = field(
        default_factory=lambda: os.getenv("LOG_LEVEL", "INFO")
    )


# =============================================================================
# OHLCV CACHE
# =============================================================================

class OHLCVCache:
    """
    Rolling OHLCV cache with efficient updates.

    Maintains fixed-size deque for each OHLCV column.
    """

    def __init__(self, symbol: str, timeframe: str, window_size: int = 300):
        """
        Initialize OHLCV cache.

        Args:
            symbol: Trading pair (e.g., "BTC/USD")
            timeframe: Timeframe (e.g., "5m")
            window_size: Maximum bars to keep
        """
        self.symbol = symbol
        self.timeframe = timeframe
        self.window_size = window_size

        # Rolling buffers
        self._timestamps: Deque[int] = deque(maxlen=window_size)
        self._open: Deque[float] = deque(maxlen=window_size)
        self._high: Deque[float] = deque(maxlen=window_size)
        self._low: Deque[float] = deque(maxlen=window_size)
        self._close: Deque[float] = deque(maxlen=window_size)
        self._volume: Deque[float] = deque(maxlen=window_size)

    def update(self, timestamp: int, open_: float, high: float, low: float,
               close: float, volume: float) -> None:
        """
        Add new OHLCV bar to cache.

        Args:
            timestamp: Bar timestamp (ms)
            open_: Open price
            high: High price
            low: Low price
            close: Close price
            volume: Volume
        """
        self._timestamps.append(timestamp)
        self._open.append(open_)
        self._high.append(high)
        self._low.append(low)
        self._close.append(close)
        self._volume.append(volume)

    def get_dataframe(self) -> pd.DataFrame:
        """
        Get OHLCV data as DataFrame.

        Returns:
            DataFrame with columns: timestamp, open, high, low, close, volume
        """
        return pd.DataFrame({
            "timestamp": pd.to_datetime(list(self._timestamps), unit="ms"),
            "open": list(self._open),
            "high": list(self._high),
            "low": list(self._low),
            "close": list(self._close),
            "volume": list(self._volume),
        })

    def size(self) -> int:
        """Get number of bars in cache"""
        return len(self._timestamps)

    def is_ready(self, min_bars: int) -> bool:
        """Check if cache has minimum required bars"""
        return self.size() >= min_bars


# =============================================================================
# CIRCUIT BREAKERS
# =============================================================================

class CircuitBreakerManager:
    """
    Manage circuit breakers for spread, latency, and scalper throttle.
    """

    def __init__(self, config: EngineConfig):
        """
        Initialize breaker manager.

        Args:
            config: Engine configuration
        """
        self.config = config

        # Breaker states
        self.spread_breaker_active = False
        self.latency_breaker_active = False
        self.scalper_throttle_active = False

        # Scalper throttle: track recent signal timestamps
        self.recent_signals: Deque[float] = deque(maxlen=100)

        # Metrics
        self._metrics = {
            "spread_breaker_trips": 0,
            "latency_breaker_trips": 0,
            "scalper_throttle_trips": 0,
        }

    def check_spread(self, spread_bps: float, pair: str) -> bool:
        """
        Check if spread exceeds maximum.

        Args:
            spread_bps: Spread in basis points
            pair: Trading pair

        Returns:
            True if spread OK, False if breaker tripped
        """
        if spread_bps > self.config.spread_bps_max:
            self.spread_breaker_active = True
            self._metrics["spread_breaker_trips"] += 1
            logger.warning(
                f"SPREAD BREAKER: {pair} spread {spread_bps:.2f} bps > "
                f"limit {self.config.spread_bps_max} bps"
            )
            return False

        self.spread_breaker_active = False
        return True

    def check_latency(self, latency_ms: float, operation: str) -> bool:
        """
        Check if latency exceeds maximum.

        Args:
            latency_ms: Latency in milliseconds
            operation: Operation name (for logging)

        Returns:
            True if latency OK, False if breaker tripped
        """
        if latency_ms > self.config.latency_ms_max:
            self.latency_breaker_active = True
            self._metrics["latency_breaker_trips"] += 1
            logger.warning(
                f"LATENCY BREAKER: {operation} took {latency_ms:.2f}ms > "
                f"limit {self.config.latency_ms_max}ms"
            )
            return False

        self.latency_breaker_active = False
        return True

    def check_scalper_throttle(self) -> bool:
        """
        Check if scalper rate limit exceeded.

        Returns:
            True if OK to trade, False if throttled
        """
        now = time.time()

        # Remove signals older than 1 minute
        while self.recent_signals and now - self.recent_signals[0] > 60:
            self.recent_signals.popleft()

        # Check rate limit
        if len(self.recent_signals) >= self.config.scalp_max_trades_per_minute:
            self.scalper_throttle_active = True
            self._metrics["scalper_throttle_trips"] += 1
            logger.warning(
                f"SCALPER THROTTLE: {len(self.recent_signals)} signals/min >= "
                f"limit {self.config.scalp_max_trades_per_minute}"
            )
            return False

        self.scalper_throttle_active = False
        return True

    def record_signal(self) -> None:
        """Record a signal for throttle tracking"""
        self.recent_signals.append(time.time())

    def get_metrics(self) -> Dict[str, int]:
        """Get breaker metrics"""
        return self._metrics.copy()


# =============================================================================
# LIVE ENGINE
# =============================================================================

class LiveEngine:
    """
    Live trading engine coordinating WS → regime → strategy → risk → publish.

    Maintains rolling OHLCV cache, computes indicators, detects regime,
    routes to strategies, sizes positions, and publishes signals to Redis.
    """

    def __init__(self, config: EngineConfig):
        """
        Initialize live engine.

        Args:
            config: Engine configuration
        """
        self.config = config

        # Components
        self.ws_client: Optional[KrakenWebSocketClient] = None
        self.regime_detector = RegimeDetector(config=RegimeConfig())
        self.risk_manager = RiskManager(config=RiskConfig())
        self.breaker_manager = CircuitBreakerManager(config=config)

        # Strategy router with strategies
        self.router = StrategyRouter(config=RouterConfig(
            regime_change_cooldown_bars=2,
            min_confidence=Decimal("0.40"),
            spread_bps_max=config.spread_bps_max,
        ))

        # Register strategies
        momentum_strategy = MomentumStrategy()
        mean_reversion_strategy = MeanReversionStrategy()
        self.router.register("momentum", momentum_strategy)
        self.router.register("mean_reversion", mean_reversion_strategy)

        # Map regimes to strategies
        from ai_engine.schemas import RegimeLabel
        self.router.map_regime_to_strategy(RegimeLabel.BULL, "momentum")
        self.router.map_regime_to_strategy(RegimeLabel.BEAR, "momentum")
        self.router.map_regime_to_strategy(RegimeLabel.CHOP, "mean_reversion")

        # Publisher
        self.publisher: Optional[SignalPublisher] = None

        # OHLCV caches per pair
        self.ohlcv_caches: Dict[str, OHLCVCache] = {}

        # State
        self.running = False
        self.current_equity = config.initial_equity_usd

        # Last signal time per pair (for cooldown)
        self.last_signal_time: Dict[str, float] = {}

        # Metrics
        self._metrics = {
            "ticks_processed": 0,
            "signals_generated": 0,
            "signals_published": 0,
            "signals_rejected": 0,
            "total_decision_latency_ms": 0,
            "total_publish_latency_ms": 0,
        }

        # Spread tracking (latest spread per pair)
        self.latest_spread: Dict[str, float] = {}

        logger.info(f"LiveEngine initialized: mode={config.mode}")

    async def start(self) -> None:
        """Start live engine"""
        logger.info("Starting live engine...")

        # Initialize publisher
        self._init_publisher()

        # Initialize WS client
        await self._init_ws_client()

        # Register WS callbacks
        self._register_ws_callbacks()

        # Start WS client
        self.running = True
        logger.info("Live engine started")

        # Start WS client (blocks until stopped)
        await self.ws_client.start()

    async def stop(self) -> None:
        """Stop live engine"""
        logger.info("Stopping live engine...")
        self.running = False

        if self.ws_client:
            await self.ws_client.stop()

        if self.publisher:
            self.publisher.disconnect()

        logger.info("Live engine stopped")

        # Print final metrics
        self._print_metrics()

    def _init_publisher(self) -> None:
        """Initialize Redis publisher"""
        logger.info("Initializing Redis publisher...")

        pub_config = PublisherConfig(
            redis_url=self.config.redis_url,
            ssl_ca_certs=self.config.redis_ca_cert if self.config.redis_url.startswith("rediss://") else None,
        )

        self.publisher = SignalPublisher(config=pub_config)
        self.publisher.connect()

        logger.info("Redis publisher connected")

    async def _init_ws_client(self) -> None:
        """Initialize Kraken WebSocket client"""
        logger.info("Initializing Kraken WS client...")

        ws_config = KrakenWSConfig()
        self.ws_client = KrakenWebSocketClient(config=ws_config)

        # Initialize OHLCV caches for each pair
        for pair in ws_config.pairs:
            self.ohlcv_caches[pair] = OHLCVCache(
                symbol=pair,
                timeframe="5m",  # Default to 5m for now
                window_size=self.config.ohlcv_window_size,
            )

        logger.info(f"Kraken WS client initialized for pairs: {ws_config.pairs}")

    def _register_ws_callbacks(self) -> None:
        """Register callbacks for WS data"""
        self.ws_client.register_callback("ohlc", self._on_ohlc)
        self.ws_client.register_callback("spread", self._on_spread)
        self.ws_client.register_callback("trade", self._on_trade)

        logger.info("WS callbacks registered")

    async def _on_ohlc(self, pair: str, ohlc: Dict) -> None:
        """
        Handle OHLC data from WS.

        Args:
            pair: Trading pair
            ohlc: OHLC dict with time, etime, open, high, low, close, vwap, volume, count
        """
        try:
            # Update OHLCV cache
            cache = self.ohlcv_caches.get(pair)
            if not cache:
                logger.warning(f"No cache for pair {pair}")
                return

            # Extract OHLCV
            timestamp_ms = int(ohlc["time"] * 1000)
            cache.update(
                timestamp=timestamp_ms,
                open_=ohlc["open"],
                high=ohlc["high"],
                low=ohlc["low"],
                close=ohlc["close"],
                volume=ohlc["volume"],
            )

            # Process tick if cache is ready
            if cache.is_ready(self.config.min_bars_required):
                await self._process_tick(pair)
            else:
                logger.debug(
                    f"{pair}: Cache not ready ({cache.size()}/{self.config.min_bars_required})"
                )

        except Exception as e:
            logger.error(f"Error handling OHLC for {pair}: {e}", exc_info=True)

    async def _on_spread(self, pair: str, spread_data: Dict) -> None:
        """
        Handle spread data from WS.

        Args:
            pair: Trading pair
            spread_data: Spread dict with bid, ask, timestamp, spread_bps
        """
        try:
            # Update latest spread
            spread_bps = spread_data.get("spread_bps", 0.0)
            self.latest_spread[pair] = spread_bps

            # Check spread breaker
            self.breaker_manager.check_spread(spread_bps, pair)

        except Exception as e:
            logger.error(f"Error handling spread for {pair}: {e}", exc_info=True)

    async def _on_trade(self, pair: str, trades: List[Dict]) -> None:
        """
        Handle trade data from WS (for monitoring).

        Args:
            pair: Trading pair
            trades: List of trade dicts
        """
        # Currently just log significant trades
        for trade in trades:
            if trade.get("volume", 0) >= 0.01:  # Log trades >= 0.01 BTC
                logger.debug(
                    f"Trade: {pair} {trade['side'].upper()} "
                    f"{trade['volume']:.4f} @ ${trade['price']:.2f}"
                )

    async def _process_tick(self, pair: str) -> None:
        """
        Process a tick: regime → router → strategy → risk → publish.

        Args:
            pair: Trading pair to process
        """
        t_start = time.perf_counter()

        try:
            self._metrics["ticks_processed"] += 1

            # Check signal cooldown
            if not self._check_signal_cooldown(pair):
                return

            # Check scalper throttle
            if not self.breaker_manager.check_scalper_throttle():
                return

            # Get OHLCV dataframe
            cache = self.ohlcv_caches[pair]
            ohlcv_df = cache.get_dataframe()

            # Detect regime
            regime_tick = self.regime_detector.detect(ohlcv_df, timeframe="5m")
            logger.info(
                f"{pair}: Regime={regime_tick.regime.value}, "
                f"Vol={regime_tick.vol_regime}, Strength={regime_tick.strength:.2f}, "
                f"Changed={regime_tick.changed}"
            )

            # Create market snapshot
            latest_close = float(ohlcv_df["close"].iloc[-1])
            snapshot = MarketSnapshot(
                symbol=pair,
                timeframe="5m",
                timestamp_ms=int(time.time() * 1000),
                mid_price=latest_close,
                spread_bps=self.latest_spread.get(pair, 0.0),
                volume_24h=float(ohlcv_df["volume"].iloc[-24:].sum()) if len(ohlcv_df) >= 24 else 0.0,
            )

            # Check spread breaker
            if not self.breaker_manager.check_spread(snapshot.spread_bps, pair):
                self._metrics["signals_rejected"] += 1
                return

            # Route to strategy
            signal_spec = self.router.route(regime_tick, snapshot, ohlcv_df)

            if not signal_spec:
                logger.debug(f"{pair}: No signal generated")
                return

            self._metrics["signals_generated"] += 1
            logger.info(
                f"{pair}: Signal generated: {signal_spec.side} @ {signal_spec.entry_price}, "
                f"confidence={signal_spec.confidence:.2f}, strategy={signal_spec.strategy}"
            )

            # Size position via risk manager
            signal_input = SignalInput(
                signal_id=signal_spec.signal_id,
                symbol=signal_spec.symbol,
                side=signal_spec.side,
                entry_price=signal_spec.entry_price,
                stop_loss=signal_spec.stop_loss,
                take_profit=signal_spec.take_profit,
                confidence=signal_spec.confidence,
            )

            position_size = self.risk_manager.size_position(
                signal_input,
                equity_usd=self.current_equity,
            )

            if not position_size.allowed:
                logger.info(
                    f"{pair}: Position rejected by risk manager: "
                    f"{position_size.rejection_reasons}"
                )
                self._metrics["signals_rejected"] += 1
                return

            logger.info(
                f"{pair}: Position sized: size={position_size.size:.8f}, "
                f"notional=${position_size.notional_usd:.2f}, "
                f"risk=${position_size.expected_risk_usd:.2f} ({float(position_size.risk_pct):.2%})"
            )

            # Measure decision latency
            t_decision = time.perf_counter()
            decision_latency_ms = (t_decision - t_start) * 1000
            self._metrics["total_decision_latency_ms"] += decision_latency_ms

            # Check decision latency breaker
            if not self.breaker_manager.check_latency(decision_latency_ms, "decision"):
                self._metrics["signals_rejected"] += 1
                return

            logger.info(f"{pair}: Decision latency: {decision_latency_ms:.2f}ms")

            # Publish signal to Redis (mode=paper)
            t_publish_start = time.perf_counter()

            signal_dto = create_signal_dto(
                ts_ms=int(time.time() * 1000),
                pair=pair.replace("/", "-"),  # BTC/USD → BTC-USD
                side=signal_spec.side,
                entry=float(signal_spec.entry_price),
                sl=float(signal_spec.stop_loss),
                tp=float(signal_spec.take_profit),
                strategy=signal_spec.strategy,
                confidence=float(signal_spec.confidence),
                mode=self.config.mode,
            )

            entry_id = self.publisher.publish(signal_dto)

            t_publish_end = time.perf_counter()
            publish_latency_ms = (t_publish_end - t_publish_start) * 1000
            self._metrics["total_publish_latency_ms"] += publish_latency_ms

            # Check publish latency breaker
            self.breaker_manager.check_latency(publish_latency_ms, "publish")

            logger.info(
                f"{pair}: Signal published to Redis: entry_id={entry_id}, "
                f"publish_latency={publish_latency_ms:.2f}ms"
            )

            self._metrics["signals_published"] += 1
            self.breaker_manager.record_signal()
            self.last_signal_time[pair] = time.time()

        except Exception as e:
            logger.error(f"Error processing tick for {pair}: {e}", exc_info=True)

    def _check_signal_cooldown(self, pair: str) -> bool:
        """
        Check if signal cooldown has expired.

        Args:
            pair: Trading pair

        Returns:
            True if OK to generate signal, False if in cooldown
        """
        last_time = self.last_signal_time.get(pair, 0)
        elapsed = time.time() - last_time

        if elapsed < self.config.signal_cooldown_seconds:
            logger.debug(
                f"{pair}: Signal cooldown active "
                f"({elapsed:.1f}s / {self.config.signal_cooldown_seconds}s)"
            )
            return False

        return True

    def get_metrics(self) -> Dict:
        """Get engine metrics"""
        metrics = self._metrics.copy()

        # Add averages
        if metrics["signals_published"] > 0:
            metrics["avg_decision_latency_ms"] = (
                metrics["total_decision_latency_ms"] / metrics["ticks_processed"]
            )
            metrics["avg_publish_latency_ms"] = (
                metrics["total_publish_latency_ms"] / metrics["signals_published"]
            )
        else:
            metrics["avg_decision_latency_ms"] = 0
            metrics["avg_publish_latency_ms"] = 0

        # Add breaker metrics
        metrics["breakers"] = self.breaker_manager.get_metrics()

        # Add router metrics
        metrics["router"] = self.router.get_metrics()

        # Add risk manager metrics
        metrics["risk"] = self.risk_manager.get_metrics()

        return metrics

    def _print_metrics(self) -> None:
        """Print metrics summary"""
        metrics = self.get_metrics()

        logger.info("\n" + "="*60)
        logger.info("LIVE ENGINE METRICS SUMMARY")
        logger.info("="*60)
        logger.info(f"Ticks processed: {metrics['ticks_processed']}")
        logger.info(f"Signals generated: {metrics['signals_generated']}")
        logger.info(f"Signals published: {metrics['signals_published']}")
        logger.info(f"Signals rejected: {metrics['signals_rejected']}")
        logger.info(f"Avg decision latency: {metrics['avg_decision_latency_ms']:.2f}ms")
        logger.info(f"Avg publish latency: {metrics['avg_publish_latency_ms']:.2f}ms")
        logger.info("")
        logger.info("Circuit Breakers:")
        for key, val in metrics["breakers"].items():
            logger.info(f"  {key}: {val}")
        logger.info("")
        logger.info("Router:")
        for key, val in metrics["router"].items():
            logger.info(f"  {key}: {val}")
        logger.info("")
        logger.info("Risk Manager:")
        for key, val in metrics["risk"].items():
            logger.info(f"  {key}: {val}")
        logger.info("="*60 + "\n")


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

async def main():
    """Main entry point for live engine"""

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    logger.info("="*60)
    logger.info("LIVE ENGINE STARTING (PAPER MODE)")
    logger.info("="*60)

    # Create engine config
    config = EngineConfig()

    # Validate environment
    if not config.redis_url:
        logger.error("REDIS_URL not set in environment")
        return

    logger.info(f"Mode: {config.mode}")
    logger.info(f"Initial equity: ${config.initial_equity_usd}")
    logger.info(f"Spread breaker: {config.spread_bps_max} bps")
    logger.info(f"Latency breaker: {config.latency_ms_max} ms")
    logger.info(f"Scalper throttle: {config.scalp_max_trades_per_minute} trades/min")
    logger.info(f"Signal cooldown: {config.signal_cooldown_seconds}s")
    logger.info("")

    # Create and start engine
    engine = LiveEngine(config=config)

    try:
        await engine.start()
    except KeyboardInterrupt:
        logger.info("\nShutdown signal received...")
    except Exception as e:
        logger.error(f"Engine error: {e}", exc_info=True)
    finally:
        await engine.stop()


if __name__ == "__main__":
    asyncio.run(main())
