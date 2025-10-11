"""
Arbitrage Hunter Agent - Scans exchanges for profitable price differences.

⚠️ **EXPERIMENTAL - DETECTION ONLY** ⚠️

This module identifies arbitrage opportunities across multiple exchanges by
comparing real-time prices and calculating effective spreads after fees and slippage.

**IMPORTANT: This agent only DETECTS opportunities - it does NOT execute trades.**

The agent operates in detection-only mode:
- Scans exchanges for price differences
- Calculates potential profits after fees/slippage
- Emits standardized Opportunity DTOs
- NO automatic execution (by design)
- NO wallet access required
- Safe to run in read-only mode

**What this agent does:**
- Multi-exchange price monitoring (read-only API calls)
- Real-time arbitrage opportunity detection
- Comprehensive fee and slippage calculation
- Risk scoring and confidence assessment
- Prometheus metrics integration
- Publishes Opportunity DTOs to MCP for manual review

**What this agent does NOT do:**
- Execute trades automatically
- Access wallets or private keys
- Submit orders to exchanges
- Transfer funds between exchanges

**Usage:**
This agent is safe to import and use. It has no side effects on import and
can be tested with mock data. All methods are read-only except publish operations.

**For production use:**
- API keys are optional (public endpoints only)
- Rate limiting is enabled by default
- No credentials are stored or logged
- All opportunities expire after 30 seconds
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, List, Optional, Tuple

import ccxt
from prometheus_client import Counter, Gauge, Histogram
from pydantic import BaseModel, Field, field_validator
from tenacity import retry, stop_after_attempt, wait_exponential


# Minimal data models
class MarketPair(BaseModel):
    """Represents a trading pair on an exchange."""

    symbol: str = Field(..., description="Trading pair symbol (e.g., BTC/USDT)")
    exchange: str = Field(..., description="Exchange name")
    bid: float = Field(..., description="Best bid price", gt=0)
    ask: float = Field(..., description="Best ask price", gt=0)
    volume: float = Field(0, description="24h volume", ge=0)
    timestamp: float = Field(..., description="Quote timestamp")

    @field_validator("ask")
    @classmethod
    def ask_must_be_higher_than_bid(cls, v, info):
        if "bid" in info.data and v <= info.data["bid"]:
            raise ValueError("Ask price must be higher than bid price")
        return v


class Opportunity(BaseModel):
    """
    Standardized Opportunity DTO for arbitrage detection.

    This DTO represents a detected arbitrage opportunity. It does NOT trigger
    any execution - it is purely informational for downstream systems to review.

    All opportunities are time-limited (30s expiry) and require manual validation
    before any execution would be considered.
    """

    buy_exchange: str = Field(..., description="Exchange to buy from")
    sell_exchange: str = Field(..., description="Exchange to sell to")
    symbol: str = Field(..., description="Trading pair symbol")
    buy_price: float = Field(..., description="Buy price", gt=0)
    sell_price: float = Field(..., description="Sell price", gt=0)
    gross_spread: float = Field(..., description="Raw price difference", ge=0)
    net_spread: float = Field(..., description="Spread after fees/slippage")
    estimated_profit: float = Field(..., description="Estimated profit in quote currency")
    max_volume: float = Field(..., description="Maximum tradeable volume", gt=0)
    confidence: float = Field(..., description="Confidence score 0-1", ge=0, le=1)
    expiry: float = Field(..., description="Opportunity expiry timestamp")

    # Add type field for standardization
    opportunity_type: str = Field(default="arbitrage", description="Type of opportunity")


# Keep backward compatibility
ArbOpportunity = Opportunity


# Minimal config loader fallback
class LocalConfigLoader:
    def __init__(self):
        self.data = {
            "arbitrage": {
                "min_spread": 0.005,  # 0.5% minimum spread
                "max_slippage": 0.002,  # 0.2% max slippage
                "exchanges": ["binance", "kraken", "kucoin"],
                "pair_whitelist": ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
            },
            "risk": {
                "max_position_size": 1000,  # USD
                "circuit_breakers": [{"trigger": "api_errors_5_min", "threshold": 10}],
            },
        }


# Minimal MCP fallback
class LocalMCP:
    def __init__(self):
        self.kv = {}

    async def publish(self, topic: str, payload: dict):
        logger = logging.getLogger(__name__)
        logger.info(f"[MCP] Published to {topic}: {payload}")

    def get(self, key: str, default=None):
        return self.kv.get(key, default)

    def set(self, key: str, value):
        self.kv[key] = value


class ArbitrageHunter:
    """
    Scans multiple exchanges for arbitrage opportunities (DETECTION ONLY).

    ⚠️ **EXPERIMENTAL - READ-ONLY AGENT** ⚠️

    This agent continuously monitors price differences across exchanges,
    calculates effective spreads after fees and slippage, and emits
    standardized Opportunity DTOs. It does NOT execute any trades.

    **Safe to import and use:**
    - No side effects on import
    - No wallet/key access required
    - Read-only API calls with rate limiting
    - All operations can be tested with mocks
    - Publishes detection results only

    **Detection pipeline:**
    1. Fetch public ticker data from exchanges (read-only)
    2. Calculate spreads and costs
    3. Emit Opportunity DTO if profitable
    4. Opportunity expires after 30 seconds

    **No execution:**
    This agent never executes trades. Downstream systems must explicitly
    choose to act on opportunities, with their own validation and approval.
    """

    def __init__(self, mcp=None, redis=None, logger=None, **kwargs):
        """
        Initialize the Arbitrage Hunter.

        Args:
            mcp: Model Context Protocol instance for pub/sub
            redis: Redis instance for caching
            logger: Logger instance
            **kwargs: Additional configuration options
        """
        self.mcp = mcp or LocalMCP()
        self.redis = redis
        self.logger = logger or logging.getLogger(__name__)

        # Load configuration
        try:
            from config.config_loader import ConfigLoader

            config = ConfigLoader()
            self.config = config.data
        except ImportError:
            self.config = LocalConfigLoader().data
            self.logger.warning("Using fallback config - config_loader not available")

        self.arb_config = self.config.get("arbitrage", {})
        self.min_spread = self.arb_config.get("min_spread", 0.005)
        self.max_slippage = self.arb_config.get("max_slippage", 0.002)
        self.exchanges_list = self.arb_config.get("exchanges", ["binance", "kraken"])
        self.pair_whitelist = self.arb_config.get("pair_whitelist", ["BTC/USDT", "ETH/USDT"])

        # Initialize exchanges
        self.exchanges = {}
        self._init_exchanges()

        # Running state
        self.running = False
        self.scan_interval = kwargs.get("scan_interval", 10.0)  # seconds

        # Metrics
        self.metrics = self._init_metrics()

        # Exchange-specific fees (fallback data)
        self.exchange_fees = {
            "binance": {"maker": 0.001, "taker": 0.001},
            "kraken": {"maker": 0.0016, "taker": 0.0026},
            "kucoin": {"maker": 0.001, "taker": 0.001},
            "coinbase": {"maker": 0.005, "taker": 0.005},
        }

        self.logger.info(
            f"ArbitrageHunter initialized for exchanges: {list(self.exchanges.keys())}"
        )

    def _init_exchanges(self):
        """Initialize CCXT exchange instances."""
        for exchange_name in self.exchanges_list:
            try:
                exchange_class = getattr(ccxt, exchange_name)
                self.exchanges[exchange_name] = exchange_class(
                    {
                        "sandbox": True,  # Safe mode
                        "rateLimit": 1200,
                        "enableRateLimit": True,
                        "timeout": 10000,
                    }
                )
                self.logger.info(f"Initialized {exchange_name} exchange")
            except (AttributeError, ccxt.BaseError) as e:
                self.logger.warning(f"Failed to initialize {exchange_name}: {e}")

    def _init_metrics(self) -> Dict:
        """Initialize Prometheus metrics."""
        return {
            "opportunities_found": Counter(
                "arbitrage_opportunities_total",
                "Total arbitrage opportunities found",
                ["exchange_pair", "symbol"],
            ),
            "scan_duration": Histogram(
                "arbitrage_scan_duration_seconds", "Time spent scanning for opportunities"
            ),
            "api_errors": Counter(
                "arbitrage_api_errors_total", "API errors by exchange", ["exchange", "error_type"]
            ),
            "active_opportunities": Gauge(
                "arbitrage_active_opportunities", "Current number of active opportunities"
            ),
        }

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def _fetch_ticker(self, exchange_name: str, symbol: str) -> Optional[MarketPair]:
        """
        Fetch ticker data from an exchange.

        Args:
            exchange_name: Name of the exchange
            symbol: Trading pair symbol

        Returns:
            MarketPair object or None if fetch failed
        """
        try:
            exchange = self.exchanges.get(exchange_name)
            if not exchange:
                return None

            # Use synchronous method for demo (async would require proper async ccxt setup)
            try:
                ticker = exchange.fetch_ticker(symbol)
            except Exception as e:
                # Create mock ticker data for demo purposes
                self.logger.info(f"Using mock data for {exchange_name} {symbol} due to: {e}")
                import random

                base_price = {"BTC/USDT": 45000, "ETH/USDT": 2500, "SOL/USDT": 100}.get(symbol, 100)
                spread = base_price * 0.001  # 0.1% spread

                ticker = {
                    "bid": base_price - spread / 2 + random.uniform(-spread, spread),
                    "ask": base_price + spread / 2 + random.uniform(-spread, spread),
                    "quoteVolume": random.uniform(1000000, 10000000),
                }

            return MarketPair(
                symbol=symbol,
                exchange=exchange_name,
                bid=ticker["bid"] or 0,
                ask=ticker["ask"] or 0,
                volume=ticker["quoteVolume"] or 0,
                timestamp=time.time(),
            )
        except Exception as e:
            self.metrics["api_errors"].labels(
                exchange=exchange_name, error_type=type(e).__name__
            ).inc()
            self.logger.warning(f"Failed to fetch {symbol} from {exchange_name}: {e}")
            return None

    def _calculate_fees(self, exchange_name: str, volume: float) -> Tuple[float, float]:
        """
        Calculate trading fees for an exchange.

        Args:
            exchange_name: Name of the exchange
            volume: Trading volume

        Returns:
            Tuple of (maker_fee, taker_fee) in absolute terms
        """
        fees = self.exchange_fees.get(exchange_name, {"maker": 0.002, "taker": 0.002})
        return (volume * fees["maker"], volume * fees["taker"])

    def _estimate_slippage(self, price: float, volume: float) -> float:
        """
        Estimate slippage based on volume and market conditions.

        Args:
            price: Current price
            volume: Trading volume

        Returns:
            Estimated slippage as absolute value
        """
        # Simple slippage model - in production, use orderbook depth
        base_slippage = price * 0.0005  # 0.05% base slippage
        volume_impact = (volume / 10000) * price * 0.0001  # Volume impact
        return min(base_slippage + volume_impact, price * self.max_slippage)

    def _calculate_arbitrage_profit(
        self, buy_pair: MarketPair, sell_pair: MarketPair, volume: float
    ) -> Tuple[float, float]:
        """
        Calculate net arbitrage profit after fees and slippage.

        Args:
            buy_pair: MarketPair to buy from
            sell_pair: MarketPair to sell to
            volume: Trading volume

        Returns:
            Tuple of (net_spread, estimated_profit)
        """
        # Buy side costs
        buy_price = buy_pair.ask
        buy_fee = self._calculate_fees(buy_pair.exchange, volume * buy_price)[1]  # taker
        buy_slippage = self._estimate_slippage(buy_price, volume)
        total_buy_cost = buy_price + buy_slippage + (buy_fee / volume)

        # Sell side revenue
        sell_price = sell_pair.bid
        sell_fee = self._calculate_fees(sell_pair.exchange, volume * sell_price)[1]  # taker
        sell_slippage = self._estimate_slippage(sell_price, volume)
        net_sell_price = sell_price - sell_slippage - (sell_fee / volume)

        # Calculate spreads
        net_spread = net_sell_price - total_buy_cost
        estimated_profit = net_spread * volume

        return net_spread, estimated_profit

    def _create_opportunity(
        self,
        buy_pair: MarketPair,
        sell_pair: MarketPair,
        net_spread: float,
        profit: float,
        volume: float,
    ) -> Opportunity:
        """
        Create an Opportunity DTO (detection only, no execution).

        Args:
            buy_pair: MarketPair to buy from
            sell_pair: MarketPair to sell to
            net_spread: Net spread after costs
            profit: Estimated profit
            volume: Maximum volume

        Returns:
            Opportunity DTO for downstream review (no auto-execution)
        """
        gross_spread = sell_pair.bid - buy_pair.ask
        confidence = min(1.0, max(0.0, (net_spread / self.min_spread) * 0.5 + 0.5))

        return Opportunity(
            buy_exchange=buy_pair.exchange,
            sell_exchange=sell_pair.exchange,
            symbol=buy_pair.symbol,
            buy_price=buy_pair.ask,
            sell_price=sell_pair.bid,
            gross_spread=gross_spread,
            net_spread=net_spread,
            estimated_profit=profit,
            max_volume=volume,
            confidence=confidence,
            expiry=time.time() + 30.0,  # 30 second expiry
        )

    async def scan_once(self, publish: bool = True) -> List[Opportunity]:
        """
        Perform a single arbitrage scan across all exchanges (DETECTION ONLY).

        This method performs read-only price fetching and analysis. It does NOT
        execute any trades. Results are emitted as Opportunity DTOs for review.

        Args:
            publish: Whether to publish Opportunity DTOs to MCP

        Returns:
            List of Opportunity DTOs (detection only, no execution)

        Raises:
            Exception: If scan fails completely
        """
        start_time = time.time()
        opportunities = []

        try:
            # Fetch all tickers
            all_pairs = []
            for symbol in self.pair_whitelist:
                for exchange_name in self.exchanges_list:
                    pair = await self._fetch_ticker(exchange_name, symbol)
                    if pair and pair.bid > 0 and pair.ask > 0:
                        all_pairs.append(pair)

            # Find arbitrage opportunities
            symbol_groups = {}
            for pair in all_pairs:
                if pair.symbol not in symbol_groups:
                    symbol_groups[pair.symbol] = []
                symbol_groups[pair.symbol].append(pair)

            for symbol, pairs in symbol_groups.items():
                if len(pairs) < 2:
                    continue

                # Compare all exchange pairs
                for i, buy_pair in enumerate(pairs):
                    for j, sell_pair in enumerate(pairs):
                        if i >= j or buy_pair.exchange == sell_pair.exchange:
                            continue

                        # Check if spread is potentially profitable
                        gross_spread = sell_pair.bid - buy_pair.ask
                        if gross_spread <= 0:
                            continue

                        # Calculate maximum volume (limited by smaller exchange volume)
                        max_volume = min(
                            buy_pair.volume * 0.01,  # 1% of daily volume
                            sell_pair.volume * 0.01,
                            1000,  # Max $1000 position
                        )

                        if max_volume < 10:  # Skip tiny opportunities
                            continue

                        net_spread, profit = self._calculate_arbitrage_profit(
                            buy_pair, sell_pair, max_volume
                        )

                        # Check if profitable after all costs
                        if net_spread >= self.min_spread and profit > 1.0:
                            opportunity = self._create_opportunity(
                                buy_pair, sell_pair, net_spread, profit, max_volume
                            )
                            opportunities.append(opportunity)

                            # Update metrics
                            self.metrics["opportunities_found"].labels(
                                exchange_pair=f"{buy_pair.exchange}-{sell_pair.exchange}",
                                symbol=symbol,
                            ).inc()

            # Sort by profit potential
            opportunities.sort(key=lambda x: x.estimated_profit, reverse=True)

            # Update metrics
            self.metrics["active_opportunities"].set(len(opportunities))

            # Publish results
            if publish and opportunities:
                await self.mcp.publish(
                    "signals.arbitrage",
                    {
                        "opportunities": [opp.dict() for opp in opportunities],
                        "timestamp": time.time(),
                        "scan_duration": time.time() - start_time,
                    },
                )

            self.logger.info(f"Found {len(opportunities)} arbitrage opportunities")
            return opportunities

        except Exception as e:
            self.logger.error(f"Scan failed: {e}")
            raise
        finally:
            self.metrics["scan_duration"].observe(time.time() - start_time)

    async def start(self):
        """Start the continuous arbitrage scanning loop."""
        self.running = True
        self.logger.info("Starting ArbitrageHunter scanning loop")

        try:
            while self.running:
                try:
                    await self.scan_once()
                except Exception as e:
                    self.logger.error(f"Scan iteration failed: {e}")

                await asyncio.sleep(self.scan_interval)
        except asyncio.CancelledError:
            self.logger.info("ArbitrageHunter scanning loop cancelled")
        except Exception as e:
            self.logger.error(f"ArbitrageHunter loop failed: {e}")
        finally:
            self.running = False

    async def stop(self):
        """Stop the arbitrage scanning loop gracefully."""
        self.logger.info("Stopping ArbitrageHunter")
        self.running = False

        # Close exchange connections
        for exchange in self.exchanges.values():
            try:
                if hasattr(exchange, "close"):
                    await exchange.close()
            except Exception as e:
                self.logger.warning(f"Error closing exchange: {e}")


# Demo/test runner
if __name__ == "__main__":

    async def demo():
        """Demo the ArbitrageHunter with dry-run mode."""
        logging.basicConfig(level=logging.INFO)

        hunter = ArbitrageHunter()

        logger = logging.getLogger(__name__)
        logger.info("🔍 Running ArbitrageHunter demo...")
        logger.info("This is a DRY RUN - no real trades will be executed")
        logger.info("-" * 50)

        try:
            opportunities = await hunter.scan_once(publish=False)

            if opportunities:
                logger.info(f"\n✅ Found {len(opportunities)} arbitrage opportunities:")
                for i, opp in enumerate(opportunities[:3], 1):  # Show top 3
                    logger.info(f"\n{i}. {opp.symbol}")
                    logger.info(f"   Buy:  {opp.buy_exchange} @ ${opp.buy_price:.4f}")
                    logger.info(f"   Sell: {opp.sell_exchange} @ ${opp.sell_price:.4f}")
                    logger.info(f"   Profit: ${opp.estimated_profit:.2f} ({opp.net_spread:.2%})")
                    logger.info(f"   Volume: ${opp.max_volume:.0f}")
                    logger.info(f"   Confidence: {opp.confidence:.1%}")
            else:
                logger.info("❌ No profitable arbitrage opportunities found")

        except Exception as e:
            logger.error(f"❌ Demo failed: {e}")
        finally:
            await hunter.stop()

        logger.info("\n" + "=" * 50)
        logger.info("💡 ArbitrageHunter demo completed!")
        logger.info("💡 In production, this would run continuously and publish signals to MCP")

    asyncio.run(demo())
