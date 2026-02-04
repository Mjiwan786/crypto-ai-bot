"""
PRD-001 Compliant Kraken OHLCV Manager (utils/kraken_ohlcv_manager.py)

Manages OHLCV data for all trading pairs and timeframes defined in kraken_ohlcv.yaml.
Handles both native Kraken OHLCV subscriptions and synthetic bar generation from trades.

PRD-001 REQUIREMENTS:
- Section B.3: Stream naming pattern: kraken:ohlc:{tf}:{pair}
- Section 4.1: WebSocket connection management
- Section 4.2: Reconnection with exponential backoff
- All pairs from kraken_ohlcv.yaml tiers must be active

STREAM NAMING (per kraken_ohlcv.yaml):
- Native OHLCV: kraken:ohlc:{tf}:{pair} (e.g., kraken:ohlc:1m:BTC-USD)
- Synthetic bars: kraken:ohlc:{tf}:{pair} (e.g., kraken:ohlc:15s:BTC-USD)
- Trade events: kraken:trade:{pair} (e.g., kraken:trade:BTC-USD)

PAIR TIERS (from kraken_ohlcv.yaml):
- tier_1 (highest priority): BTC/USD, ETH/USD, BTC/EUR
- tier_2 (medium priority): ADA/USD, SOL/USD, AVAX/USD
- tier_3 (lower priority): LINK/USD

TIMEFRAMES:
- Native Kraken OHLCV: 1m (1), 5m (5), 15m (15), 30m (30), 1h (60), 4h (240), 1d (1440)
- Synthetic from trades: 5s, 15s, 30s, 2m, 3m (built from trade ticks)

USAGE:
    from utils.kraken_ohlcv_manager import KrakenOHLCVManager

    # Create manager (auto-loads kraken_ohlcv.yaml)
    manager = KrakenOHLCVManager()

    # Get all configured pairs
    all_pairs = manager.get_all_pairs()  # ['BTC/USD', 'ETH/USD', ...]

    # Get pairs by tier
    tier_1 = manager.get_pairs_by_tier('tier_1')  # ['BTC/USD', 'ETH/USD', 'BTC/EUR']

    # Start OHLCV streaming
    await manager.start()

    # Access latest OHLCV for a pair/timeframe
    ohlcv = manager.get_latest_ohlcv('BTC/USD', '1m')

Author: Crypto AI Bot Team
PRD Reference: PRD-001 Sections B.3, 4.1, 4.2
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import yaml
import redis.asyncio as redis

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION CLASSES
# =============================================================================

class PairTier(str, Enum):
    """Trading pair priority tiers from kraken_ohlcv.yaml"""
    TIER_1 = "tier_1"  # Highest priority (BTC/USD, ETH/USD, BTC/EUR)
    TIER_2 = "tier_2"  # Medium priority (ADA/USD, SOL/USD, AVAX/USD)
    TIER_3 = "tier_3"  # Lower priority (LINK/USD)


class TimeframeType(str, Enum):
    """Timeframe type: native Kraken or synthetic from trades"""
    NATIVE = "native"      # Kraken native OHLC subscription
    SYNTHETIC = "synthetic"  # Built from trade ticks


@dataclass
class TimeframeConfig:
    """Configuration for a single timeframe"""
    name: str                    # e.g., "1m", "15s"
    seconds: int                 # Duration in seconds
    kraken_interval: Optional[int]  # Kraken API interval (None for synthetic)
    type: TimeframeType         # Native or synthetic
    min_trades: int = 1         # Minimum trades to form a bar (synthetic only)


@dataclass
class PairConfig:
    """Configuration for a trading pair"""
    symbol: str                  # Standard format: "BTC/USD"
    kraken_symbol: str          # Kraken API format: "XBT/USD" or "XBTUSD"
    tier: PairTier              # Priority tier
    enabled: bool = True


@dataclass
class OHLCVBar:
    """OHLCV bar data structure"""
    timestamp: float            # Bar open timestamp (Unix)
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    trade_count: int = 0
    vwap: Optional[Decimal] = None
    buy_volume: Decimal = field(default_factory=lambda: Decimal("0"))
    sell_volume: Decimal = field(default_factory=lambda: Decimal("0"))

    def to_dict(self) -> Dict[str, str]:
        """Convert to Redis-compatible dict with string values"""
        return {
            "timestamp": str(self.timestamp),
            "open": str(self.open),
            "high": str(self.high),
            "low": str(self.low),
            "close": str(self.close),
            "volume": str(self.volume),
            "trade_count": str(self.trade_count),
            "vwap": str(float(self.vwap)) if self.vwap else "0.0",
            "buy_volume": str(self.buy_volume),
            "sell_volume": str(self.sell_volume),
        }


# =============================================================================
# KRAKEN SYMBOL MAPPING
# =============================================================================

# Standard to Kraken symbol mapping
SYMBOL_TO_KRAKEN = {
    "BTC/USD": "XBT/USD",
    "ETH/USD": "ETH/USD",
    "BTC/EUR": "XBT/EUR",
    "ADA/USD": "ADA/USD",
    "SOL/USD": "SOL/USD",
    "AVAX/USD": "AVAX/USD",
    "LINK/USD": "LINK/USD",
    "MATIC/USD": "MATIC/USD",
    "DOT/USD": "DOT/USD",
    "ATOM/USD": "ATOM/USD",
}

# Kraken to Standard symbol mapping (reverse)
KRAKEN_TO_SYMBOL = {v: k for k, v in SYMBOL_TO_KRAKEN.items()}

# Kraken WebSocket pair format (no slash)
KRAKEN_WS_PAIRS = {
    "BTC/USD": "XBT/USD",
    "ETH/USD": "ETH/USD",
    "BTC/EUR": "XBT/EUR",
    "ADA/USD": "ADA/USD",
    "SOL/USD": "SOL/USD",
    "AVAX/USD": "AVAX/USD",
    "LINK/USD": "LINK/USD",
}


# =============================================================================
# TIMEFRAME CONFIGURATION
# =============================================================================

# Native Kraken OHLC intervals (in minutes)
# Kraken supports: 1, 5, 15, 30, 60, 240, 1440, 10080, 21600
NATIVE_TIMEFRAMES: Dict[str, TimeframeConfig] = {
    "1m": TimeframeConfig("1m", 60, 1, TimeframeType.NATIVE),
    "5m": TimeframeConfig("5m", 300, 5, TimeframeType.NATIVE),
    "15m": TimeframeConfig("15m", 900, 15, TimeframeType.NATIVE),
    "30m": TimeframeConfig("30m", 1800, 30, TimeframeType.NATIVE),
    "1h": TimeframeConfig("1h", 3600, 60, TimeframeType.NATIVE),
    "4h": TimeframeConfig("4h", 14400, 240, TimeframeType.NATIVE),
    "1d": TimeframeConfig("1d", 86400, 1440, TimeframeType.NATIVE),
}

# Synthetic timeframes (derived from trade ticks)
# These are NOT available via Kraken OHLC subscription
SYNTHETIC_TIMEFRAMES: Dict[str, TimeframeConfig] = {
    "5s": TimeframeConfig("5s", 5, None, TimeframeType.SYNTHETIC, min_trades=3),
    "15s": TimeframeConfig("15s", 15, None, TimeframeType.SYNTHETIC, min_trades=1),
    "30s": TimeframeConfig("30s", 30, None, TimeframeType.SYNTHETIC, min_trades=1),
    "2m": TimeframeConfig("2m", 120, None, TimeframeType.SYNTHETIC, min_trades=1),
    "3m": TimeframeConfig("3m", 180, None, TimeframeType.SYNTHETIC, min_trades=1),
}

ALL_TIMEFRAMES = {**NATIVE_TIMEFRAMES, **SYNTHETIC_TIMEFRAMES}


# =============================================================================
# DEFAULT PAIR TIERS (fallback if kraken_ohlcv.yaml not found)
# =============================================================================

DEFAULT_PAIR_TIERS = {
    PairTier.TIER_1: ["BTC/USD", "ETH/USD", "BTC/EUR"],
    PairTier.TIER_2: ["ADA/USD", "SOL/USD", "AVAX/USD"],
    PairTier.TIER_3: ["LINK/USD"],
}


# =============================================================================
# SYNTHETIC BAR BUILDER (inline for single-file simplicity)
# =============================================================================

@dataclass
class Trade:
    """Individual trade tick"""
    timestamp: float
    price: Decimal
    volume: Decimal
    side: str  # "buy" or "sell"


class SyntheticBarBuilder:
    """
    Builds synthetic OHLCV bars from trade ticks using time-bucketing.

    PRD-001 compliant: Aligns bucket boundaries (e.g., 15s bars at :00, :15, :30, :45)
    """

    def __init__(
        self,
        symbol: str,
        timeframe: TimeframeConfig,
        redis_client: Optional[redis.Redis] = None,
    ):
        self.symbol = symbol
        self.timeframe = timeframe
        self.redis_client = redis_client
        self.stream_key = f"kraken:ohlc:{timeframe.name}:{symbol.replace('/', '-')}"

        # Trade accumulator: bucket_timestamp -> trades
        self.buckets: Dict[float, List[Trade]] = defaultdict(list)

        # Metrics
        self.bars_created = 0
        self.trades_processed = 0

    def get_bucket_timestamp(self, timestamp: float) -> float:
        """Get aligned bucket start timestamp"""
        return (timestamp // self.timeframe.seconds) * self.timeframe.seconds

    async def add_trade(self, trade: Trade) -> Optional[OHLCVBar]:
        """Add trade to bucket, return completed bar if boundary crossed"""
        self.trades_processed += 1
        bucket_ts = self.get_bucket_timestamp(trade.timestamp)
        self.buckets[bucket_ts].append(trade)

        # Close old buckets
        current_time = time.time()
        completed_bar = None

        for ts in list(self.buckets.keys()):
            if current_time >= ts + self.timeframe.seconds:
                bar = await self._close_bucket(ts)
                if bar:
                    completed_bar = bar

        return completed_bar

    async def _close_bucket(self, bucket_ts: float) -> Optional[OHLCVBar]:
        """Close bucket and create OHLCV bar"""
        trades = self.buckets.pop(bucket_ts, [])

        if len(trades) < self.timeframe.min_trades:
            return None

        # Build OHLCV
        sorted_trades = sorted(trades, key=lambda t: t.timestamp)

        open_price = sorted_trades[0].price
        close_price = sorted_trades[-1].price
        high_price = max(t.price for t in sorted_trades)
        low_price = min(t.price for t in sorted_trades)
        total_volume = sum(t.volume for t in sorted_trades)
        buy_volume = sum(t.volume for t in sorted_trades if t.side == "buy")
        sell_volume = sum(t.volume for t in sorted_trades if t.side == "sell")

        # VWAP
        volume_weighted_sum = sum(t.price * t.volume for t in sorted_trades)
        vwap = volume_weighted_sum / total_volume if total_volume > 0 else close_price

        bar = OHLCVBar(
            timestamp=bucket_ts,
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
            volume=total_volume,
            trade_count=len(sorted_trades),
            vwap=vwap,
            buy_volume=buy_volume,
            sell_volume=sell_volume,
        )

        self.bars_created += 1

        # Publish to Redis
        if self.redis_client:
            await self._publish_bar(bar)

        return bar

    async def _publish_bar(self, bar: OHLCVBar) -> None:
        """Publish bar to Redis stream"""
        try:
            data = bar.to_dict()
            data["symbol"] = self.symbol
            data["timeframe"] = self.timeframe.name
            data["type"] = "synthetic"

            await self.redis_client.xadd(
                self.stream_key,
                data,
                maxlen=10000,
                approximate=True,
            )

            logger.debug(f"Published synthetic bar to {self.stream_key}")

        except Exception as e:
            logger.error(f"Error publishing synthetic bar: {e}")


# =============================================================================
# KRAKEN OHLCV MANAGER
# =============================================================================

class KrakenOHLCVManager:
    """
    PRD-001 Compliant Kraken OHLCV Manager

    Manages all OHLCV data for trading pairs and timeframes:
    - Loads configuration from kraken_ohlcv.yaml
    - Handles native Kraken OHLCV subscriptions (1m, 5m, 15m, etc.)
    - Generates synthetic bars from trade ticks (5s, 15s, 30s)
    - Publishes to Redis streams with PRD-compliant naming

    Stream naming: kraken:ohlc:{tf}:{pair} (e.g., kraken:ohlc:1m:BTC-USD)
    """

    # PRD-001 compliant stream configuration
    STREAM_MAXLEN = 10000

    def __init__(
        self,
        config_path: Optional[str] = None,
        redis_client: Optional[redis.Redis] = None,
        enabled_tiers: Optional[List[PairTier]] = None,
        enabled_timeframes: Optional[List[str]] = None,
    ):
        """
        Initialize OHLCV manager.

        Args:
            config_path: Path to kraken_ohlcv.yaml (auto-discovered if None)
            redis_client: Redis client for stream publishing
            enabled_tiers: Pair tiers to enable (default: all)
            enabled_timeframes: Timeframes to enable (default: from config)
        """
        self.config_path = config_path or self._find_config()
        self.redis_client = redis_client

        # Configuration
        self.pair_configs: Dict[str, PairConfig] = {}
        self.enabled_tiers = enabled_tiers or list(PairTier)
        self.enabled_timeframes: Set[str] = set()

        # Load configuration
        self._load_config()

        # Override timeframes if specified
        if enabled_timeframes:
            self.enabled_timeframes = set(enabled_timeframes)

        # Synthetic bar builders: (symbol, timeframe) -> builder
        self.bar_builders: Dict[Tuple[str, str], SyntheticBarBuilder] = {}

        # Latest OHLCV cache: (symbol, timeframe) -> OHLCVBar
        self.latest_ohlcv: Dict[Tuple[str, str], OHLCVBar] = {}

        # Metrics
        self.native_bars_received = 0
        self.synthetic_bars_created = 0
        self.trades_processed = 0

        # Health tracking
        self.last_update_by_pair: Dict[str, float] = {}

        logger.info(
            f"KrakenOHLCVManager initialized: {len(self.pair_configs)} pairs, "
            f"{len(self.enabled_timeframes)} timeframes"
        )

    def _find_config(self) -> str:
        """Find kraken_ohlcv.yaml configuration file"""
        possible_paths = [
            "config/exchange_configs/kraken_ohlcv.yaml",
            "config/kraken_ohlcv.yaml",
            "../config/exchange_configs/kraken_ohlcv.yaml",
        ]

        for path in possible_paths:
            if Path(path).exists():
                return path

        logger.warning("kraken_ohlcv.yaml not found, using default configuration")
        return ""

    def _load_config(self) -> None:
        """Load configuration from kraken_ohlcv.yaml"""
        config = {}

        if self.config_path and Path(self.config_path).exists():
            try:
                with open(self.config_path, 'r') as f:
                    config = yaml.safe_load(f) or {}
                logger.info(f"Loaded OHLCV config from {self.config_path}")
            except Exception as e:
                logger.error(f"Error loading OHLCV config: {e}")

        # Load pairs from config or use defaults
        pairs_config = config.get("pairs", {})

        if pairs_config:
            # Load from YAML
            for tier_name in ["tier_1", "tier_2", "tier_3"]:
                tier_pairs = pairs_config.get(tier_name, [])
                tier = PairTier(tier_name)

                for pair_data in tier_pairs:
                    if isinstance(pair_data, dict):
                        symbol = pair_data.get("symbol", "")
                        kraken_symbol = pair_data.get("kraken_symbol", symbol)
                    else:
                        symbol = pair_data
                        kraken_symbol = SYMBOL_TO_KRAKEN.get(symbol, symbol)

                    if symbol and tier in self.enabled_tiers:
                        self.pair_configs[symbol] = PairConfig(
                            symbol=symbol,
                            kraken_symbol=kraken_symbol,
                            tier=tier,
                            enabled=True,
                        )
        else:
            # Use defaults
            for tier, pairs in DEFAULT_PAIR_TIERS.items():
                if tier in self.enabled_tiers:
                    for symbol in pairs:
                        kraken_symbol = SYMBOL_TO_KRAKEN.get(symbol, symbol)
                        self.pair_configs[symbol] = PairConfig(
                            symbol=symbol,
                            kraken_symbol=kraken_symbol,
                            tier=tier,
                            enabled=True,
                        )

        # Load timeframes from config
        timeframes_config = config.get("timeframes", {})

        if timeframes_config:
            # Native timeframes
            for tf in timeframes_config.get("primary", []):
                tf_name = tf.get("name", "") if isinstance(tf, dict) else tf
                if tf_name in NATIVE_TIMEFRAMES:
                    self.enabled_timeframes.add(tf_name)

            # Synthetic timeframes
            for tf in timeframes_config.get("synthetic", []):
                tf_name = tf.get("name", "") if isinstance(tf, dict) else tf
                if tf_name in SYNTHETIC_TIMEFRAMES:
                    self.enabled_timeframes.add(tf_name)
        else:
            # Default timeframes: 1m, 5m, 15m, 1h (native) + 15s (synthetic)
            self.enabled_timeframes = {"1m", "5m", "15m", "1h", "15s"}

        logger.info(
            f"Configured pairs: {list(self.pair_configs.keys())}"
        )
        logger.info(
            f"Configured timeframes: {sorted(self.enabled_timeframes)}"
        )

    def get_all_pairs(self) -> List[str]:
        """Get all configured trading pairs"""
        return list(self.pair_configs.keys())

    def get_pairs_by_tier(self, tier: PairTier) -> List[str]:
        """Get pairs for a specific tier"""
        return [
            p.symbol for p in self.pair_configs.values()
            if p.tier == tier and p.enabled
        ]

    def get_kraken_pairs(self) -> List[str]:
        """Get pairs in Kraken format for WebSocket subscription"""
        return [
            KRAKEN_WS_PAIRS.get(p.symbol, p.kraken_symbol)
            for p in self.pair_configs.values()
            if p.enabled
        ]

    def get_native_timeframes(self) -> List[TimeframeConfig]:
        """Get enabled native (Kraken API) timeframes"""
        return [
            NATIVE_TIMEFRAMES[tf]
            for tf in self.enabled_timeframes
            if tf in NATIVE_TIMEFRAMES
        ]

    def get_synthetic_timeframes(self) -> List[TimeframeConfig]:
        """Get enabled synthetic timeframes"""
        return [
            SYNTHETIC_TIMEFRAMES[tf]
            for tf in self.enabled_timeframes
            if tf in SYNTHETIC_TIMEFRAMES
        ]

    def get_kraken_ohlc_intervals(self) -> List[int]:
        """Get Kraken OHLC intervals to subscribe to"""
        intervals = []
        for tf in self.enabled_timeframes:
            config = NATIVE_TIMEFRAMES.get(tf)
            if config and config.kraken_interval:
                intervals.append(config.kraken_interval)
        return sorted(set(intervals))

    async def initialize_bar_builders(self) -> None:
        """Initialize synthetic bar builders for all pair/timeframe combinations"""
        synthetic_tfs = self.get_synthetic_timeframes()

        for symbol in self.get_all_pairs():
            for tf in synthetic_tfs:
                key = (symbol, tf.name)
                self.bar_builders[key] = SyntheticBarBuilder(
                    symbol=symbol,
                    timeframe=tf,
                    redis_client=self.redis_client,
                )

        logger.info(
            f"Initialized {len(self.bar_builders)} synthetic bar builders"
        )

    async def process_trade(
        self,
        symbol: str,
        price: float,
        volume: float,
        side: str,
        timestamp: float,
    ) -> List[OHLCVBar]:
        """
        Process a trade tick for synthetic bar generation.

        Called by KrakenWebSocketClient's trade handler.

        Args:
            symbol: Trading pair (e.g., "BTC/USD")
            price: Trade price
            volume: Trade volume
            side: "buy" or "sell"
            timestamp: Trade timestamp (Unix)

        Returns:
            List of completed synthetic bars (if any)
        """
        self.trades_processed += 1
        self.last_update_by_pair[symbol] = time.time()

        trade = Trade(
            timestamp=timestamp,
            price=Decimal(str(price)),
            volume=Decimal(str(volume)),
            side=side,
        )

        completed_bars = []

        # Feed trade to all synthetic bar builders for this symbol
        for tf in self.get_synthetic_timeframes():
            key = (symbol, tf.name)
            builder = self.bar_builders.get(key)

            if builder:
                bar = await builder.add_trade(trade)
                if bar:
                    completed_bars.append(bar)
                    self.synthetic_bars_created += 1
                    self.latest_ohlcv[key] = bar

        return completed_bars

    async def process_native_ohlc(
        self,
        symbol: str,
        timeframe_minutes: int,
        ohlc_data: Dict[str, Any],
    ) -> Optional[OHLCVBar]:
        """
        Process native Kraken OHLCV data.

        Called by KrakenWebSocketClient's OHLC handler.

        Args:
            symbol: Trading pair (e.g., "BTC/USD")
            timeframe_minutes: Kraken interval in minutes (1, 5, 15, etc.)
            ohlc_data: OHLCV data from Kraken WebSocket

        Returns:
            OHLCVBar if processed successfully
        """
        # Map Kraken interval to timeframe name
        interval_to_tf = {1: "1m", 5: "5m", 15: "15m", 30: "30m", 60: "1h", 240: "4h", 1440: "1d"}
        tf_name = interval_to_tf.get(timeframe_minutes)

        if not tf_name or tf_name not in self.enabled_timeframes:
            return None

        self.native_bars_received += 1
        self.last_update_by_pair[symbol] = time.time()

        try:
            bar = OHLCVBar(
                timestamp=float(ohlc_data.get("time", 0)),
                open=Decimal(str(ohlc_data.get("open", 0))),
                high=Decimal(str(ohlc_data.get("high", 0))),
                low=Decimal(str(ohlc_data.get("low", 0))),
                close=Decimal(str(ohlc_data.get("close", 0))),
                volume=Decimal(str(ohlc_data.get("volume", 0))),
                trade_count=int(ohlc_data.get("count", 0)),
                vwap=Decimal(str(ohlc_data.get("vwap", 0))) if ohlc_data.get("vwap") else None,
            )

            # Cache
            key = (symbol, tf_name)
            self.latest_ohlcv[key] = bar

            # Publish to Redis
            if self.redis_client:
                await self._publish_native_bar(symbol, tf_name, bar)

            return bar

        except Exception as e:
            logger.error(f"Error processing native OHLC for {symbol}/{tf_name}: {e}")
            return None

    async def _publish_native_bar(
        self,
        symbol: str,
        timeframe: str,
        bar: OHLCVBar,
    ) -> None:
        """Publish native OHLCV bar to Redis stream"""
        try:
            stream_key = f"kraken:ohlc:{timeframe}:{symbol.replace('/', '-')}"

            data = bar.to_dict()
            data["symbol"] = symbol
            data["timeframe"] = timeframe
            data["type"] = "native"

            await self.redis_client.xadd(
                stream_key,
                data,
                maxlen=self.STREAM_MAXLEN,
                approximate=True,
            )

            logger.debug(f"Published native bar to {stream_key}")

        except Exception as e:
            logger.error(f"Error publishing native bar: {e}")

    def get_latest_ohlcv(
        self,
        symbol: str,
        timeframe: str,
    ) -> Optional[OHLCVBar]:
        """Get latest OHLCV bar for a symbol/timeframe"""
        return self.latest_ohlcv.get((symbol, timeframe))

    def get_health_status(self) -> Dict[str, Any]:
        """Get health status for all pairs"""
        current_time = time.time()

        pair_status = {}
        for symbol in self.get_all_pairs():
            last_update = self.last_update_by_pair.get(symbol, 0)
            age_seconds = current_time - last_update if last_update else float("inf")

            pair_status[symbol] = {
                "last_update": last_update,
                "age_seconds": age_seconds,
                "healthy": age_seconds < 60,  # Consider healthy if updated within 60s
            }

        return {
            "total_pairs": len(self.pair_configs),
            "enabled_pairs": len([p for p in self.pair_configs.values() if p.enabled]),
            "native_timeframes": [tf.name for tf in self.get_native_timeframes()],
            "synthetic_timeframes": [tf.name for tf in self.get_synthetic_timeframes()],
            "native_bars_received": self.native_bars_received,
            "synthetic_bars_created": self.synthetic_bars_created,
            "trades_processed": self.trades_processed,
            "pair_status": pair_status,
        }

    def get_subscription_config(self) -> Dict[str, Any]:
        """
        Get WebSocket subscription configuration for KrakenWebSocketClient.

        Returns dict with pairs and intervals to subscribe to.
        """
        return {
            "pairs": self.get_kraken_pairs(),
            "ohlc_intervals": self.get_kraken_ohlc_intervals(),
            "subscribe_trades": len(self.get_synthetic_timeframes()) > 0,
            "native_timeframes": [tf.name for tf in self.get_native_timeframes()],
            "synthetic_timeframes": [tf.name for tf in self.get_synthetic_timeframes()],
        }


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def create_ohlcv_manager(
    redis_url: Optional[str] = None,
    enabled_tiers: Optional[List[str]] = None,
) -> KrakenOHLCVManager:
    """
    Factory function to create OHLCV manager.

    Args:
        redis_url: Redis URL (defaults to REDIS_URL env var)
        enabled_tiers: Tier names to enable (default: all)

    Returns:
        Configured KrakenOHLCVManager
    """
    redis_client = None

    if redis_url or os.getenv("REDIS_URL"):
        url = redis_url or os.getenv("REDIS_URL")
        try:
            # Create async Redis client
            if url.startswith("rediss://"):
                # TLS connection
                ca_cert = os.getenv("REDIS_CA_CERT_PATH", "config/certs/redis_ca.pem")
                redis_client = redis.from_url(
                    url,
                    ssl_ca_certs=ca_cert if Path(ca_cert).exists() else None,
                    decode_responses=False,
                )
            else:
                redis_client = redis.from_url(url, decode_responses=False)
        except Exception as e:
            logger.warning(f"Could not create Redis client: {e}")

    tiers = None
    if enabled_tiers:
        tiers = [PairTier(t) for t in enabled_tiers if t in [e.value for e in PairTier]]

    return KrakenOHLCVManager(
        redis_client=redis_client,
        enabled_tiers=tiers,
    )


def get_stream_key(symbol: str, timeframe: str) -> str:
    """
    Get PRD-compliant Redis stream key for OHLCV data.

    Pattern: kraken:ohlc:{tf}:{pair}

    Args:
        symbol: Trading pair (e.g., "BTC/USD")
        timeframe: Timeframe (e.g., "1m", "15s")

    Returns:
        Stream key (e.g., "kraken:ohlc:1m:BTC-USD")
    """
    return f"kraken:ohlc:{timeframe}:{symbol.replace('/', '-')}"


# =============================================================================
# SELF-TEST
# =============================================================================

if __name__ == "__main__":
    import asyncio
    from dotenv import load_dotenv

    load_dotenv(".env.paper")

    async def main():
        print("=" * 70)
        print(" " * 15 + "KRAKEN OHLCV MANAGER SELF-TEST")
        print("=" * 70)

        # Create manager
        manager = create_ohlcv_manager()

        # Test 1: Pair configuration
        print("\n1. Pair Configuration:")
        all_pairs = manager.get_all_pairs()
        print(f"   All pairs ({len(all_pairs)}): {all_pairs}")

        for tier in PairTier:
            tier_pairs = manager.get_pairs_by_tier(tier)
            print(f"   {tier.value}: {tier_pairs}")

        # Test 2: Timeframe configuration
        print("\n2. Timeframe Configuration:")
        print(f"   Native: {[tf.name for tf in manager.get_native_timeframes()]}")
        print(f"   Synthetic: {[tf.name for tf in manager.get_synthetic_timeframes()]}")
        print(f"   Kraken intervals: {manager.get_kraken_ohlc_intervals()}")

        # Test 3: Kraken symbols
        print("\n3. Kraken WebSocket Pairs:")
        kraken_pairs = manager.get_kraken_pairs()
        print(f"   {kraken_pairs}")

        # Test 4: Subscription config
        print("\n4. Subscription Config:")
        sub_config = manager.get_subscription_config()
        for key, value in sub_config.items():
            print(f"   {key}: {value}")

        # Test 5: Stream keys
        print("\n5. Stream Key Examples:")
        for symbol in ["BTC/USD", "ETH/USD"]:
            for tf in ["1m", "15s"]:
                key = get_stream_key(symbol, tf)
                print(f"   {symbol}/{tf} -> {key}")

        # Test 6: Initialize bar builders
        print("\n6. Initialize Bar Builders:")
        await manager.initialize_bar_builders()
        print(f"   Created {len(manager.bar_builders)} builders")

        # Test 7: Process sample trade
        print("\n7. Process Sample Trade:")
        bars = await manager.process_trade(
            symbol="BTC/USD",
            price=50000.0,
            volume=0.1,
            side="buy",
            timestamp=time.time(),
        )
        print(f"   Processed trade, completed bars: {len(bars)}")

        # Test 8: Health status
        print("\n8. Health Status:")
        health = manager.get_health_status()
        print(f"   Total pairs: {health['total_pairs']}")
        print(f"   Native bars: {health['native_bars_received']}")
        print(f"   Synthetic bars: {health['synthetic_bars_created']}")
        print(f"   Trades processed: {health['trades_processed']}")

        print("\n" + "=" * 70)
        print("[OK] Kraken OHLCV Manager Self-Test Complete")
        print("=" * 70)

    asyncio.run(main())
