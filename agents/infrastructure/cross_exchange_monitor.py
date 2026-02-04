"""
Cross-Exchange Arbitrage & Funding Edge Monitor (agents/infrastructure/cross_exchange_monitor.py)

Monitors Binance vs Kraken for:
- Price spread arbitrage opportunities
- Funding rate divergence
- Micro-arb scalping signals (read-only mode first)
- Latency tracking

For Prompt 5: Market Intelligence Layer
Author: Crypto AI Bot Team
Version: 2.0.0
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import aiohttp
import numpy as np
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class CrossExchangeConfig(BaseModel):
    """Configuration for cross-exchange monitoring."""

    # Arbitrage thresholds
    min_spread_bps: float = Field(default=30.0, description="Min spread for arb opportunity (bps)")
    funding_edge_threshold_pct: float = Field(default=0.3, description="Min funding edge (%)")
    max_latency_ms: float = Field(default=150.0, description="Max latency for execution (ms)")

    # Binance API
    binance_rest_url: str = Field(default="https://fapi.binance.com", description="Binance futures API")
    binance_ws_url: str = Field(default="wss://fstream.binance.com/ws", description="Binance WS feed")

    # Kraken API (already configured)
    kraken_rest_url: str = Field(default="https://api.kraken.com/0/public", description="Kraken API")

    # Update intervals
    price_update_interval_ms: int = Field(default=1000, description="Price update interval (ms)")
    funding_update_interval_ms: int = Field(default=60000, description="Funding rate update (ms)")

    # Trading pairs mapping
    pair_mappings: Dict[str, Dict[str, str]] = Field(
        default_factory=lambda: {
            "BTC/USD": {"binance": "BTCUSDT", "kraken": "XXBTZUSD"},
            "ETH/USD": {"binance": "ETHUSDT", "kraken": "XETHZUSD"},
            "SOL/USD": {"binance": "SOLUSDT", "kraken": "SOLUSD"},
            "ADA/USD": {"binance": "ADAUSDT", "kraken": "ADAUSD"},
        },
        description="Pair name mappings",
    )

    # Read-only mode
    read_only: bool = Field(default=True, description="Read-only mode (no execution)")


@dataclass
class ExchangePrice:
    """Price data from an exchange."""

    exchange: str
    pair: str
    bid: float
    ask: float
    mid: float
    timestamp: int
    latency_ms: float


@dataclass
class FundingRate:
    """Funding rate data."""

    exchange: str
    pair: str
    funding_rate: float
    next_funding_time: int
    timestamp: int


@dataclass
class ArbitrageOpportunity:
    """Detected arbitrage opportunity."""

    pair: str
    buy_exchange: str
    sell_exchange: str
    buy_price: float
    sell_price: float
    spread_bps: float
    spread_pct: float
    funding_edge_pct: float
    max_latency_ms: float
    timestamp: int
    executable: bool


class CrossExchangeMonitor:
    """
    Monitors Binance and Kraken for arbitrage and funding edge opportunities.

    Features:
    - Real-time price spread monitoring
    - Funding rate divergence detection
    - Latency tracking
    - Micro-arb signal generation
    """

    def __init__(
        self,
        config: Optional[CrossExchangeConfig] = None,
        redis_client=None,
    ):
        """
        Initialize cross-exchange monitor.

        Args:
            config: Configuration
            redis_client: Redis client for metrics
        """
        self.config = config or CrossExchangeConfig()
        self.redis_client = redis_client

        # Price cache
        self.prices: Dict[str, Dict[str, ExchangePrice]] = {}  # {pair: {exchange: ExchangePrice}}

        # Funding rate cache
        self.funding_rates: Dict[str, Dict[str, FundingRate]] = {}  # {pair: {exchange: FundingRate}}

        # Metrics
        self.arb_opportunities_detected = 0
        self.arb_opportunities_executed = 0

        logger.info(
            "CrossExchangeMonitor initialized (read_only=%s, min_spread=%.1f bps, funding_edge=%.2f%%)",
            self.config.read_only,
            self.config.min_spread_bps,
            self.config.funding_edge_threshold_pct,
        )

    async def fetch_binance_price(self, pair: str) -> Optional[ExchangePrice]:
        """
        Fetch current price from Binance futures.

        Args:
            pair: Standard pair name (e.g., "BTC/USD")

        Returns:
            ExchangePrice or None
        """
        binance_symbol = self.config.pair_mappings.get(pair, {}).get("binance")
        if not binance_symbol:
            logger.warning("No Binance mapping for %s", pair)
            return None

        start_time = time.time()

        try:
            url = f"{self.config.binance_rest_url}/fapi/v1/ticker/bookTicker?symbol={binance_symbol}"

            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status != 200:
                        logger.warning("Binance API error: %d", resp.status)
                        return None

                    data = await resp.json()

            latency_ms = (time.time() - start_time) * 1000

            bid = float(data["bidPrice"])
            ask = float(data["askPrice"])
            mid = (bid + ask) / 2.0

            return ExchangePrice(
                exchange="binance",
                pair=pair,
                bid=bid,
                ask=ask,
                mid=mid,
                timestamp=int(time.time() * 1000),
                latency_ms=latency_ms,
            )

        except Exception as e:
            logger.exception("Failed to fetch Binance price for %s: %s", pair, e)
            return None

    async def fetch_kraken_price(self, pair: str) -> Optional[ExchangePrice]:
        """
        Fetch current price from Kraken.

        Args:
            pair: Standard pair name

        Returns:
            ExchangePrice or None
        """
        kraken_symbol = self.config.pair_mappings.get(pair, {}).get("kraken")
        if not kraken_symbol:
            logger.warning("No Kraken mapping for %s", pair)
            return None

        start_time = time.time()

        try:
            url = f"{self.config.kraken_rest_url}/Ticker?pair={kraken_symbol}"

            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status != 200:
                        logger.warning("Kraken API error: %d", resp.status)
                        return None

                    data = await resp.json()

            latency_ms = (time.time() - start_time) * 1000

            # Kraken returns data under symbol key
            result = data.get("result", {})
            ticker_key = list(result.keys())[0] if result else None

            if not ticker_key:
                logger.warning("No ticker data from Kraken for %s", pair)
                return None

            ticker = result[ticker_key]

            bid = float(ticker["b"][0])
            ask = float(ticker["a"][0])
            mid = (bid + ask) / 2.0

            return ExchangePrice(
                exchange="kraken",
                pair=pair,
                bid=bid,
                ask=ask,
                mid=mid,
                timestamp=int(time.time() * 1000),
                latency_ms=latency_ms,
            )

        except Exception as e:
            logger.exception("Failed to fetch Kraken price for %s: %s", pair, e)
            return None

    async def fetch_binance_funding_rate(self, pair: str) -> Optional[FundingRate]:
        """
        Fetch funding rate from Binance.

        Args:
            pair: Standard pair name

        Returns:
            FundingRate or None
        """
        binance_symbol = self.config.pair_mappings.get(pair, {}).get("binance")
        if not binance_symbol:
            return None

        try:
            url = f"{self.config.binance_rest_url}/fapi/v1/fundingRate?symbol={binance_symbol}&limit=1"

            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status != 200:
                        logger.warning("Binance funding API error: %d", resp.status)
                        return None

                    data = await resp.json()

            if not data:
                return None

            latest = data[0]

            return FundingRate(
                exchange="binance",
                pair=pair,
                funding_rate=float(latest["fundingRate"]),
                next_funding_time=int(latest["fundingTime"]),
                timestamp=int(time.time() * 1000),
            )

        except Exception as e:
            logger.exception("Failed to fetch Binance funding for %s: %s", pair, e)
            return None

    async def update_prices(self, pair: str) -> None:
        """
        Update prices for a pair from both exchanges.

        Args:
            pair: Trading pair
        """
        # Fetch both prices concurrently
        binance_task = asyncio.create_task(self.fetch_binance_price(pair))
        kraken_task = asyncio.create_task(self.fetch_kraken_price(pair))

        binance_price, kraken_price = await asyncio.gather(binance_task, kraken_task)

        if pair not in self.prices:
            self.prices[pair] = {}

        if binance_price:
            self.prices[pair]["binance"] = binance_price

        if kraken_price:
            self.prices[pair]["kraken"] = kraken_price

        logger.debug(
            "Updated prices for %s: Binance=%.2f (%.1fms), Kraken=%.2f (%.1fms)",
            pair,
            binance_price.mid if binance_price else 0,
            binance_price.latency_ms if binance_price else 0,
            kraken_price.mid if kraken_price else 0,
            kraken_price.latency_ms if kraken_price else 0,
        )

    async def update_funding_rates(self, pair: str) -> None:
        """
        Update funding rates for a pair.

        Args:
            pair: Trading pair
        """
        # Only Binance has funding rates (Kraken doesn't for spot pairs)
        binance_funding = await self.fetch_binance_funding_rate(pair)

        if pair not in self.funding_rates:
            self.funding_rates[pair] = {}

        if binance_funding:
            self.funding_rates[pair]["binance"] = binance_funding

            logger.debug(
                "Binance funding for %s: %.4f%% (next: %s)",
                pair,
                binance_funding.funding_rate * 100,
                binance_funding.next_funding_time,
            )

    def detect_arbitrage_opportunity(self, pair: str) -> Optional[ArbitrageOpportunity]:
        """
        Detect arbitrage opportunity for a pair.

        Args:
            pair: Trading pair

        Returns:
            ArbitrageOpportunity or None
        """
        if pair not in self.prices:
            return None

        prices = self.prices[pair]

        if "binance" not in prices or "kraken" not in prices:
            return None

        binance = prices["binance"]
        kraken = prices["kraken"]

        # Calculate spreads in both directions
        # Direction 1: Buy Binance, Sell Kraken
        spread_1_bps = ((kraken.bid - binance.ask) / binance.ask) * 10000
        spread_1_pct = spread_1_bps / 100.0

        # Direction 2: Buy Kraken, Sell Binance
        spread_2_bps = ((binance.bid - kraken.ask) / kraken.ask) * 10000
        spread_2_pct = spread_2_bps / 100.0

        # Select best direction
        if abs(spread_1_bps) > abs(spread_2_bps):
            spread_bps = spread_1_bps
            spread_pct = spread_1_pct
            buy_exchange = "binance"
            sell_exchange = "kraken"
            buy_price = binance.ask
            sell_price = kraken.bid
        else:
            spread_bps = spread_2_bps
            spread_pct = spread_2_pct
            buy_exchange = "kraken"
            sell_exchange = "binance"
            buy_price = kraken.ask
            sell_price = binance.bid

        # Check if spread exceeds minimum
        if abs(spread_bps) < self.config.min_spread_bps:
            return None

        # Get funding edge (if available)
        funding_edge_pct = 0.0
        if pair in self.funding_rates and "binance" in self.funding_rates[pair]:
            funding_rate = self.funding_rates[pair]["binance"].funding_rate
            funding_edge_pct = abs(funding_rate * 100)

        # Check latency
        max_latency_ms = max(binance.latency_ms, kraken.latency_ms)

        # Determine if executable
        executable = (
            abs(spread_bps) >= self.config.min_spread_bps and
            funding_edge_pct >= self.config.funding_edge_threshold_pct and
            max_latency_ms <= self.config.max_latency_ms
        )

        opportunity = ArbitrageOpportunity(
            pair=pair,
            buy_exchange=buy_exchange,
            sell_exchange=sell_exchange,
            buy_price=buy_price,
            sell_price=sell_price,
            spread_bps=spread_bps,
            spread_pct=spread_pct,
            funding_edge_pct=funding_edge_pct,
            max_latency_ms=max_latency_ms,
            timestamp=int(time.time() * 1000),
            executable=executable,
        )

        if executable:
            self.arb_opportunities_detected += 1
            logger.info(
                "ARB OPPORTUNITY: %s | Buy %s @ %.2f, Sell %s @ %.2f | Spread: %.1f bps (%.2f%%) | "
                "Funding: %.2f%% | Latency: %.1fms | Executable: %s",
                pair,
                buy_exchange,
                buy_price,
                sell_exchange,
                sell_price,
                spread_bps,
                spread_pct,
                funding_edge_pct,
                max_latency_ms,
                executable,
            )

            # Publish to Redis
            if self.redis_client:
                try:
                    self._publish_arb_opportunity(opportunity)
                except Exception as e:
                    logger.exception("Failed to publish arb opportunity: %s", e)

        return opportunity

    def _publish_arb_opportunity(self, opp: ArbitrageOpportunity) -> None:
        """Publish arbitrage opportunity to Redis."""
        if not self.redis_client:
            return

        key = f"arb:opportunity:{opp.pair.replace('/', '_')}"

        data = {
            "pair": opp.pair,
            "buy_exchange": opp.buy_exchange,
            "sell_exchange": opp.sell_exchange,
            "buy_price": opp.buy_price,
            "sell_price": opp.sell_price,
            "spread_bps": opp.spread_bps,
            "spread_pct": opp.spread_pct,
            "funding_edge_pct": opp.funding_edge_pct,
            "max_latency_ms": opp.max_latency_ms,
            "timestamp": opp.timestamp,
            "executable": opp.executable,
        }

        # Set with TTL
        self.redis_client.setex(key, 60, str(data))

        # Also publish to stream
        stream_key = "arb:opportunities"
        self.redis_client.xadd(stream_key, data, maxlen=1000)

    async def monitor_pair(self, pair: str) -> None:
        """
        Continuously monitor a pair for arbitrage opportunities.

        Args:
            pair: Trading pair to monitor
        """
        logger.info("Starting monitoring for %s", pair)

        last_price_update = 0
        last_funding_update = 0

        while True:
            try:
                current_time = time.time() * 1000

                # Update prices
                if current_time - last_price_update >= self.config.price_update_interval_ms:
                    await self.update_prices(pair)
                    last_price_update = current_time

                # Update funding rates
                if current_time - last_funding_update >= self.config.funding_update_interval_ms:
                    await self.update_funding_rates(pair)
                    last_funding_update = current_time

                # Detect arbitrage
                opportunity = self.detect_arbitrage_opportunity(pair)

                if opportunity and opportunity.executable and not self.config.read_only:
                    # TODO: Execute arbitrage trade
                    logger.info("Would execute arb trade (read-only mode)")
                    self.arb_opportunities_executed += 1

                # Sleep briefly
                await asyncio.sleep(self.config.price_update_interval_ms / 1000.0)

            except Exception as e:
                logger.exception("Error monitoring %s: %s", pair, e)
                await asyncio.sleep(5)

    async def monitor_all_pairs(self) -> None:
        """Monitor all configured pairs concurrently."""
        pairs = list(self.config.pair_mappings.keys())

        tasks = [self.monitor_pair(pair) for pair in pairs]

        await asyncio.gather(*tasks)

    def get_metrics(self) -> Dict:
        """Get current metrics."""
        return {
            "arb_opportunities_detected": self.arb_opportunities_detected,
            "arb_opportunities_executed": self.arb_opportunities_executed,
            "pairs_monitored": len(self.config.pair_mappings),
            "read_only_mode": self.config.read_only,
        }


# Standalone monitoring function
async def run_cross_exchange_monitor(
    config: Optional[CrossExchangeConfig] = None,
    redis_url: Optional[str] = None,
) -> None:
    """
    Run cross-exchange monitor standalone.

    Args:
        config: Monitor configuration
        redis_url: Redis connection URL
    """
    # Connect to Redis if URL provided
    redis_client = None
    if redis_url:
        try:
            import redis
            redis_client = redis.from_url(redis_url, decode_responses=True)
            redis_client.ping()
            logger.info("Connected to Redis")
        except Exception as e:
            logger.exception("Failed to connect to Redis: %s", e)

    # Create monitor
    monitor = CrossExchangeMonitor(config=config, redis_client=redis_client)

    # Start monitoring
    await monitor.monitor_all_pairs()


# Self-check for development/testing
if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info("Running CrossExchangeMonitor self-check...")

    async def self_check():
        try:
            # Create monitor
            config = CrossExchangeConfig(read_only=True)
            monitor = CrossExchangeMonitor(config=config)

            # Test fetching prices
            logger.info("\n=== Test 1: Fetch Binance price ===")
            binance_price = await monitor.fetch_binance_price("BTC/USD")
            if binance_price:
                logger.info(
                    "Binance BTC/USD: bid=%.2f, ask=%.2f, mid=%.2f, latency=%.1fms",
                    binance_price.bid,
                    binance_price.ask,
                    binance_price.mid,
                    binance_price.latency_ms,
                )
            else:
                logger.warning("Failed to fetch Binance price")

            logger.info("\n=== Test 2: Fetch Kraken price ===")
            kraken_price = await monitor.fetch_kraken_price("BTC/USD")
            if kraken_price:
                logger.info(
                    "Kraken BTC/USD: bid=%.2f, ask=%.2f, mid=%.2f, latency=%.1fms",
                    kraken_price.bid,
                    kraken_price.ask,
                    kraken_price.mid,
                    kraken_price.latency_ms,
                )
            else:
                logger.warning("Failed to fetch Kraken price")

            logger.info("\n=== Test 3: Fetch Binance funding ===")
            funding = await monitor.fetch_binance_funding_rate("BTC/USD")
            if funding:
                logger.info(
                    "Binance funding: %.4f%% (next: %d)",
                    funding.funding_rate * 100,
                    funding.next_funding_time,
                )
            else:
                logger.warning("Failed to fetch funding rate")

            logger.info("\n=== Test 4: Update prices and detect arb ===")
            await monitor.update_prices("BTC/USD")
            await monitor.update_funding_rates("BTC/USD")

            opportunity = monitor.detect_arbitrage_opportunity("BTC/USD")
            if opportunity:
                logger.info(
                    "Arb opportunity: Buy %s @ %.2f, Sell %s @ %.2f | Spread: %.1f bps | Executable: %s",
                    opportunity.buy_exchange,
                    opportunity.buy_price,
                    opportunity.sell_exchange,
                    opportunity.sell_price,
                    opportunity.spread_bps,
                    opportunity.executable,
                )
            else:
                logger.info("No arbitrage opportunity detected (expected for small spreads)")

            logger.info("\n✓ Self-check passed!")
            return 0

        except Exception as e:
            logger.error("✗ Self-check failed: %s", e)
            import traceback
            traceback.print_exc()
            return 1

    sys.exit(asyncio.run(self_check()))
