"""
Whale Watcher Agent - Monitors large cryptocurrency transfers and whale activity.

This module tracks significant on-chain movements, analyzes patterns, and generates
signals based on whale behavior that could impact market prices.

Features:
- Real-time whale transaction monitoring
- Pattern analysis and behavior detection
- Signal generation based on whale activity
- Multi-chain support and address labeling
- Risk assessment and impact analysis
- Comprehensive error handling and logging
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections import deque
from typing import Dict, List, Optional, Tuple

from prometheus_client import Counter, Gauge, Histogram
from pydantic import BaseModel, Field


# Data models
class WhaleEvent(BaseModel):
    """Represents a whale transaction or significant on-chain event."""

    event_id: str = Field(..., description="Unique event identifier")
    tx_hash: str = Field(..., description="Transaction hash")
    asset: str = Field(..., description="Asset transferred")
    amount: float = Field(..., description="Amount transferred", gt=0)
    amount_usd: float = Field(..., description="USD value of transfer", gt=0)
    from_address: str = Field(..., description="Source address")
    to_address: str = Field(..., description="Destination address")
    from_label: Optional[str] = Field(None, description="Source label (exchange, whale, etc.)")
    to_label: Optional[str] = Field(None, description="Destination label")
    timestamp: float = Field(..., description="Transaction timestamp")
    block_number: int = Field(..., description="Block number", gt=0)
    significance_score: float = Field(..., description="Event significance 0-1", ge=0, le=1)
    market_impact: str = Field(
        ..., description="Predicted impact", pattern="^(bullish|bearish|neutral)$"
    )
    confidence: float = Field(..., description="Signal confidence", ge=0, le=1)


class WalletProfile(BaseModel):
    """Profile information for a tracked wallet address."""

    address: str = Field(..., description="Wallet address")
    label: str = Field(..., description="Wallet label/name")
    category: str = Field(..., description="Category (exchange, whale, institution)")
    balance_usd: float = Field(0, description="Current USD balance estimate", ge=0)
    last_activity: float = Field(..., description="Last activity timestamp")
    transaction_count: int = Field(0, description="Total transactions tracked", ge=0)
    avg_transaction_size: float = Field(0, description="Average transaction size USD", ge=0)


class WhaleAlert(BaseModel):
    """Alert generated from whale activity analysis."""

    alert_id: str = Field(..., description="Unique alert identifier")
    alert_type: str = Field(..., description="Alert type")
    asset: str = Field(..., description="Affected asset")
    description: str = Field(..., description="Alert description")
    severity: str = Field(..., description="Alert severity", pattern="^(low|medium|high|critical)$")
    related_events: List[str] = Field(..., description="Related whale event IDs")
    created_at: float = Field(..., description="Alert creation time")
    expires_at: float = Field(..., description="Alert expiration time")


# Minimal config fallback
class LocalConfigLoader:
    def __init__(self):
        self.data = {
            "whale_watcher": {
                "min_transfer_usd": 1000000,  # $1M minimum
                "tracking_addresses": {
                    # Mock exchange addresses
                    "0x28C6c06298d514Db089934071355E5743bf21d60": "Binance Hot Wallet",
                    "0x21a31Ee1afC51d94C2eFcCAa2092aD1028285549": "Binance Cold Storage",
                    "0x267be1C1D684F78cb4F6a176C4911b741E4Ffdc0": "Kraken Wallet",
                    "0x6cc5f688a315f3dc28a7781717a9a798a59fda7b": "OKEx Wallet",
                    # Mock whale addresses
                    "0x742c3cF9Af45f91B109a81EfEaf11535ECDe9571": "Whale #1",
                    "0x189B9cBd4AfF470aF2C0102f40B1c8A97F5c9a5A": "Whale #2",
                },
                "alert_thresholds": {
                    "massive_transfer": 10000000,  # $10M
                    "exchange_inflow_spike": 5000000,  # $5M
                    "whale_accumulation": 2000000,  # $2M
                },
                "rate_limit_seconds": 60,
            },
            "assets": {
                "tracked": ["BTC", "ETH", "USDT", "USDC", "SOL"],
                "prices": {  # Mock prices for calculations
                    "BTC": 45000,
                    "ETH": 2500,
                    "SOL": 100,
                    "USDT": 1,
                    "USDC": 1,
                },
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


class MockDataSource:
    """Mock data source for whale transactions (simulates on-chain data)."""

    def __init__(self, config: dict):
        self.config = config
        self.asset_prices = config.get("assets", {}).get("prices", {})
        self.tracked_addresses = config.get("whale_watcher", {}).get("tracking_addresses", {})

    async def get_recent_transactions(self, limit: int = 100) -> List[Dict]:
        """
        Get recent large transactions (mock implementation).

        Args:
            limit: Maximum number of transactions to return

        Returns:
            List of transaction dictionaries
        """
        # Generate mock whale transactions
        import random

        mock_transactions = []
        current_time = time.time()

        # Generate some realistic whale movements
        whale_scenarios = [
            {
                "asset": "BTC",
                "amount": 500.0,
                "from": "0x742c3cF9Af45f91B109a81EfEaf11535ECDe9571",  # Whale #1
                "to": "0x28C6c06298d514Db089934071355E5743bf21d60",  # Binance
                "scenario": "whale_to_exchange",
            },
            {
                "asset": "ETH",
                "amount": 2000.0,
                "from": "0x21a31Ee1afC51d94C2eFcCAa2092aD1028285549",  # Binance Cold
                "to": "0x189B9cBd4AfF470aF2C0102f40B1c8A97F5c9a5A",  # Whale #2
                "scenario": "exchange_to_whale",
            },
            {
                "asset": "USDT",
                "amount": 5000000.0,
                "from": "0x267be1C1D684F78cb4F6a176C4911b741E4Ffdc0",  # Kraken
                "to": "0x6cc5f688a315f3dc28a7781717a9a798a59fda7b",  # OKEx
                "scenario": "exchange_to_exchange",
            },
        ]

        for i, scenario in enumerate(whale_scenarios):
            # Random timing in last 6 hours
            tx_time = current_time - random.uniform(0, 6 * 3600)

            tx = {
                "hash": f"0x{''.join(random.choices('0123456789abcdef', k=64))}",
                "asset": scenario["asset"],
                "amount": scenario["amount"],
                "from_address": scenario["from"],
                "to_address": scenario["to"],
                "timestamp": tx_time,
                "block_number": 18500000 + i,
                "gas_used": random.randint(21000, 100000),
                "scenario_type": scenario["scenario"],
            }

            mock_transactions.append(tx)

        return mock_transactions[:limit]


class WhaleWatcher:
    """
    Monitors large cryptocurrency transfers and whale activity.

    This agent tracks significant on-chain movements, analyzes wallet patterns,
    and generates market impact signals based on whale behavior.
    """

    def __init__(self, mcp=None, redis=None, logger=None, **kwargs):
        """
        Initialize the Whale Watcher.

        Args:
            mcp: Model Context Protocol instance
            redis: Redis instance for event storage
            logger: Logger instance
            **kwargs: Additional configuration
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

        self.whale_config = self.config.get("whale_watcher", {})
        self.asset_config = self.config.get("assets", {})

        self.min_transfer_usd = self.whale_config.get("min_transfer_usd", 1000000)
        self.tracking_addresses = self.whale_config.get("tracking_addresses", {})
        self.alert_thresholds = self.whale_config.get("alert_thresholds", {})
        self.rate_limit = self.whale_config.get("rate_limit_seconds", 60)

        # Asset prices for USD calculations
        self.asset_prices = self.asset_config.get("prices", {})

        # Initialize data source
        self.data_source = MockDataSource(self.config)

        # Event storage (in-memory ring buffer if no Redis)
        self.recent_events = deque(maxlen=1000)
        self.wallet_profiles = {}

        # Running state
        self.running = False
        self.check_interval = kwargs.get("check_interval", 120.0)  # 2 minutes
        self.last_check_time = 0

        # Metrics
        self.metrics = self._init_metrics()

        # Initialize wallet profiles
        self._init_wallet_profiles()

        self.logger.info(
            f"WhaleWatcher initialized, tracking {len(self.tracking_addresses)} addresses"
        )

    def _init_metrics(self) -> Dict:
        """Initialize Prometheus metrics."""
        return {
            "whale_events_detected": Counter(
                "whale_events_detected_total",
                "Total whale events detected",
                ["asset", "event_type"],
            ),
            "whale_transfer_volume": Histogram(
                "whale_transfer_volume_usd",
                "Volume of whale transfers in USD",
                buckets=(1e6, 5e6, 10e6, 25e6, 50e6, 100e6, float("inf")),
            ),
            "alerts_generated": Counter(
                "whale_alerts_generated_total",
                "Total whale alerts generated",
                ["severity", "alert_type"],
            ),
            "tracked_wallets": Gauge("whale_tracked_wallets", "Number of wallets being tracked"),
            "recent_events": Gauge(
                "whale_recent_events", "Number of recent whale events in memory"
            ),
        }

    def _init_wallet_profiles(self):
        """Initialize wallet profiles for tracked addresses."""
        for address, label in self.tracking_addresses.items():
            category = (
                "exchange"
                if any(ex in label.lower() for ex in ["binance", "kraken", "okex", "coinbase"])
                else "whale"
            )

            self.wallet_profiles[address] = WalletProfile(
                address=address,
                label=label,
                category=category,
                last_activity=time.time(),
                balance_usd=0.0,
                transaction_count=0,
                avg_transaction_size=0.0,
            )

        self.metrics["tracked_wallets"].set(len(self.wallet_profiles))

    def _calculate_usd_value(self, asset: str, amount: float) -> float:
        """
        Calculate USD value of an asset amount.

        Args:
            asset: Asset symbol
            amount: Asset amount

        Returns:
            USD value
        """
        price = self.asset_prices.get(asset, 1.0)
        return amount * price

    def _classify_transfer_type(self, from_addr: str, to_addr: str) -> Tuple[str, str]:
        """
        Classify transfer type based on address labels.

        Args:
            from_addr: Source address
            to_addr: Destination address

        Returns:
            Tuple of (transfer_type, description)
        """
        from_profile = self.wallet_profiles.get(from_addr)
        to_profile = self.wallet_profiles.get(to_addr)

        from_type = from_profile.category if from_profile else "unknown"
        to_type = to_profile.category if to_profile else "unknown"

        if from_type == "whale" and to_type == "exchange":
            return "whale_to_exchange", "Whale depositing to exchange (potentially bearish)"
        elif from_type == "exchange" and to_type == "whale":
            return "exchange_to_whale", "Whale withdrawing from exchange (potentially bullish)"
        elif from_type == "exchange" and to_type == "exchange":
            return "exchange_to_exchange", "Inter-exchange transfer (neutral)"
        elif from_type == "whale" and to_type == "whale":
            return "whale_to_whale", "Whale-to-whale transfer (accumulation pattern)"
        else:
            return "unknown", "Transfer involving unknown addresses"

    def _calculate_significance_score(
        self, amount_usd: float, transfer_type: str, asset: str
    ) -> float:
        """
        Calculate significance score for a whale event.

        Args:
            amount_usd: USD value of transfer
            transfer_type: Type of transfer
            asset: Asset being transferred

        Returns:
            Significance score between 0 and 1
        """
        # Base score from amount
        base_score = min(1.0, amount_usd / 50000000)  # $50M = max score

        # Adjust for transfer type
        type_multipliers = {
            "whale_to_exchange": 1.3,  # More significant (selling pressure)
            "exchange_to_whale": 1.2,  # Significant (accumulation)
            "whale_to_whale": 1.1,  # Moderately significant
            "exchange_to_exchange": 0.8,  # Less significant
            "unknown": 0.5,  # Least significant
        }

        base_score *= type_multipliers.get(transfer_type, 1.0)

        # Adjust for asset importance
        asset_importance = {
            "BTC": 1.5,  # Bitcoin moves are most significant
            "ETH": 1.3,  # Ethereum is also very important
            "SOL": 1.1,  # Other major alts
            "USDT": 0.9,  # Stablecoins less significant for price
            "USDC": 0.9,
        }

        base_score *= asset_importance.get(asset, 1.0)

        return min(1.0, base_score)

    def _determine_market_impact(
        self, transfer_type: str, significance: float
    ) -> Tuple[str, float]:
        """
        Determine predicted market impact and confidence.

        Args:
            transfer_type: Type of transfer
            significance: Significance score

        Returns:
            Tuple of (impact_direction, confidence)
        """
        impact_rules = {
            "whale_to_exchange": ("bearish", 0.7),  # Selling pressure
            "exchange_to_whale": ("bullish", 0.6),  # Accumulation
            "whale_to_whale": ("bullish", 0.4),  # Potential accumulation
            "exchange_to_exchange": ("neutral", 0.3),  # Operational
            "unknown": ("neutral", 0.2),
        }

        base_impact, base_confidence = impact_rules.get(transfer_type, ("neutral", 0.2))

        # Adjust confidence based on significance
        adjusted_confidence = min(1.0, base_confidence * (1 + significance))

        return base_impact, adjusted_confidence

    def _create_whale_event(self, tx_data: dict) -> Optional[WhaleEvent]:
        """
        Create a WhaleEvent from transaction data.

        Args:
            tx_data: Raw transaction data

        Returns:
            WhaleEvent object or None if not significant enough
        """
        try:
            amount_usd = self._calculate_usd_value(tx_data["asset"], tx_data["amount"])

            # Skip if below minimum threshold
            if amount_usd < self.min_transfer_usd:
                return None

            transfer_type, description = self._classify_transfer_type(
                tx_data["from_address"], tx_data["to_address"]
            )

            significance = self._calculate_significance_score(
                amount_usd, transfer_type, tx_data["asset"]
            )

            market_impact, confidence = self._determine_market_impact(transfer_type, significance)

            # Get address labels
            from_label = self.tracking_addresses.get(tx_data["from_address"])
            to_label = self.tracking_addresses.get(tx_data["to_address"])

            event_id = hashlib.sha256(f"{tx_data['hash']}_{tx_data['asset']}".encode()).hexdigest()[
                :16
            ]

            whale_event = WhaleEvent(
                event_id=event_id,
                tx_hash=tx_data["hash"],
                asset=tx_data["asset"],
                amount=tx_data["amount"],
                amount_usd=amount_usd,
                from_address=tx_data["from_address"],
                to_address=tx_data["to_address"],
                from_label=from_label,
                to_label=to_label,
                timestamp=tx_data["timestamp"],
                block_number=tx_data["block_number"],
                significance_score=significance,
                market_impact=market_impact,
                confidence=confidence,
            )

            return whale_event

        except Exception as e:
            self.logger.warning(f"Failed to create whale event from tx data: {e}")
            return None

    def _update_wallet_profiles(self, event: WhaleEvent):
        """Update wallet profiles with new transaction data."""
        for address in [event.from_address, event.to_address]:
            if address in self.wallet_profiles:
                profile = self.wallet_profiles[address]
                profile.last_activity = event.timestamp
                profile.transaction_count += 1

                # Update average transaction size
                if profile.transaction_count > 1:
                    profile.avg_transaction_size = (
                        profile.avg_transaction_size * (profile.transaction_count - 1)
                        + event.amount_usd
                    ) / profile.transaction_count
                else:
                    profile.avg_transaction_size = event.amount_usd

    def _generate_alerts(self, events: List[WhaleEvent]) -> List[WhaleAlert]:
        """
        Generate alerts based on whale events.

        Args:
            events: List of recent whale events

        Returns:
            List of WhaleAlert objects
        """
        alerts = []
        current_time = time.time()

        for event in events:
            alert_type = None
            severity = "low"
            description = ""

            # Massive transfer alert
            if event.amount_usd >= self.alert_thresholds.get("massive_transfer", 10000000):
                alert_type = "massive_transfer"
                severity = "critical"
                description = f"Massive {event.asset} transfer of ${event.amount_usd:,.0f} detected"

            # Exchange inflow alert
            elif (
                event.amount_usd >= self.alert_thresholds.get("exchange_inflow_spike", 5000000)
                and "exchange" in event.to_label.lower()
                if event.to_label
                else False
            ):
                alert_type = "exchange_inflow"
                severity = "high"
                description = (
                    f"Large {event.asset} inflow to {event.to_label}: ${event.amount_usd:,.0f}"
                )

            # Whale accumulation alert
            elif (
                event.amount_usd >= self.alert_thresholds.get("whale_accumulation", 2000000)
                and event.market_impact == "bullish"
            ):
                alert_type = "whale_accumulation"
                severity = "medium"
                description = (
                    f"Whale accumulation pattern detected: ${event.amount_usd:,.0f} {event.asset}"
                )

            if alert_type:
                alert_id = f"alert_{event.event_id}_{alert_type}"

                alert = WhaleAlert(
                    alert_id=alert_id,
                    alert_type=alert_type,
                    asset=event.asset,
                    description=description,
                    severity=severity,
                    related_events=[event.event_id],
                    created_at=current_time,
                    expires_at=current_time + (6 * 3600),  # 6 hour expiry
                )

                alerts.append(alert)

                # Update metrics
                self.metrics["alerts_generated"].labels(
                    severity=severity, alert_type=alert_type
                ).inc()

        return alerts

    async def scan_once(self, publish: bool = True) -> List[WhaleEvent]:
        """
        Perform a single scan for whale activity.

        Args:
            publish: Whether to publish events to MCP

        Returns:
            List of detected WhaleEvent objects

        Raises:
            Exception: If scan fails
        """
        try:
            # Fetch recent transactions
            raw_transactions = await self.data_source.get_recent_transactions(100)

            new_events = []
            current_time = time.time()

            # Process each transaction
            for tx_data in raw_transactions:
                # Skip if too old (only process recent transactions)
                if current_time - tx_data["timestamp"] > 3600:  # 1 hour
                    continue

                # Create whale event
                whale_event = self._create_whale_event(tx_data)
                if whale_event:
                    new_events.append(whale_event)

                    # Update wallet profiles
                    self._update_wallet_profiles(whale_event)

                    # Update metrics
                    self.metrics["whale_events_detected"].labels(
                        asset=whale_event.asset, event_type=whale_event.market_impact
                    ).inc()
                    self.metrics["whale_transfer_volume"].observe(whale_event.amount_usd)

            # Add events to storage
            for event in new_events:
                self.recent_events.append(event)

            # Generate alerts
            alerts = self._generate_alerts(new_events)

            # Update metrics
            self.metrics["recent_events"].set(len(self.recent_events))

            # Publish results
            if publish and (new_events or alerts):
                await self.mcp.publish(
                    "signals.whale",
                    {
                        "events": [event.dict() for event in new_events],
                        "alerts": [alert.dict() for alert in alerts],
                        "total_tracked_events": len(self.recent_events),
                        "timestamp": current_time,
                    },
                )

            self.logger.info(
                f"Detected {len(new_events)} whale events, generated {len(alerts)} alerts"
            )
            return new_events

        except Exception as e:
            self.logger.error(f"Whale scan failed: {e}")
            raise

    async def get_recent_events(
        self, asset: Optional[str] = None, hours: int = 24
    ) -> List[WhaleEvent]:
        """
        Get recent whale events, optionally filtered.

        Args:
            asset: Optional asset filter
            hours: Hours to look back

        Returns:
            List of WhaleEvent objects
        """
        cutoff_time = time.time() - (hours * 3600)

        filtered_events = [event for event in self.recent_events if event.timestamp >= cutoff_time]

        if asset:
            filtered_events = [event for event in filtered_events if event.asset == asset]

        return filtered_events

    async def get_wallet_summary(self, address: str) -> Optional[WalletProfile]:
        """
        Get wallet profile summary.

        Args:
            address: Wallet address

        Returns:
            WalletProfile object or None
        """
        return self.wallet_profiles.get(address)

    async def analyze_trends(self, hours: int = 168) -> Dict:
        """
        Analyze whale activity trends over time period.

        Args:
            hours: Analysis time window in hours

        Returns:
            Dictionary with trend analysis
        """
        recent_events = await self.get_recent_events(hours=hours)

        if not recent_events:
            return {"total_events": 0, "total_volume_usd": 0, "trend": "neutral"}

        # Calculate metrics
        total_volume = sum(event.amount_usd for event in recent_events)
        avg_significance = sum(event.significance_score for event in recent_events) / len(
            recent_events
        )

        # Count by impact type
        bullish_events = [e for e in recent_events if e.market_impact == "bullish"]
        bearish_events = [e for e in recent_events if e.market_impact == "bearish"]

        bullish_volume = sum(e.amount_usd for e in bullish_events)
        bearish_volume = sum(e.amount_usd for e in bearish_events)

        # Determine overall trend
        if bullish_volume > bearish_volume * 1.5:
            trend = "bullish"
        elif bearish_volume > bullish_volume * 1.5:
            trend = "bearish"
        else:
            trend = "neutral"

        return {
            "total_events": len(recent_events),
            "total_volume_usd": total_volume,
            "avg_significance": avg_significance,
            "bullish_events": len(bullish_events),
            "bearish_events": len(bearish_events),
            "bullish_volume": bullish_volume,
            "bearish_volume": bearish_volume,
            "trend": trend,
            "analysis_period_hours": hours,
        }

    async def start(self):
        """Start the continuous whale monitoring loop."""
        self.running = True
        self.logger.info("Starting WhaleWatcher monitoring loop")

        try:
            while self.running:
                try:
                    await self.scan_once()
                except Exception as e:
                    self.logger.error(f"Whale monitoring iteration failed: {e}")

                await asyncio.sleep(self.check_interval)

        except asyncio.CancelledError:
            self.logger.info("WhaleWatcher monitoring loop cancelled")
        except Exception as e:
            self.logger.error(f"WhaleWatcher loop failed: {e}")
        finally:
            self.running = False

    async def stop(self):
        """Stop the whale monitoring loop gracefully."""
        self.logger.info("Stopping WhaleWatcher")
        self.running = False


# Demo/test runner
if __name__ == "__main__":

    async def demo():
        """Demo the WhaleWatcher with mock transaction data."""
        logging.basicConfig(level=logging.INFO)

        watcher = WhaleWatcher()

        logger = logging.getLogger(__name__)
        logger.info("🐋 Running WhaleWatcher demo...")
        logger.info("This is a SAFE DEMO using mock blockchain data")
        logger.info("-" * 55)

        try:
            # Perform whale scan
            logger.info("🔍 Scanning for whale activity...")
            events = await watcher.scan_once(publish=False)

            if events:
                logger.info(f"\n✅ Detected {len(events)} whale events:")

                for i, event in enumerate(events, 1):
                    impact_emoji = (
                        "🟢"
                        if event.market_impact == "bullish"
                        else "🔴" if event.market_impact == "bearish" else "🟡"
                    )

                    logger.info(f"\n{i}. {impact_emoji} {event.asset} Whale Movement")
                    logger.info(
                        f"   Amount: {event.amount:,.2f} {event.asset} (${event.amount_usd:,.0f})"
                    )
                    logger.info(f"   From: {event.from_label or event.from_address[:10]}...")
                    logger.info(f"   To: {event.to_label or event.to_address[:10]}...")
                    logger.info(f"   Impact: {event.market_impact.upper()}")
                    logger.info(f"   Significance: {event.significance_score:.1%}")
                    logger.info(f"   Confidence: {event.confidence:.1%}")
                    logger.info(f"   Tx Hash: {event.tx_hash[:20]}...")

                    # Time since transaction
                    hours_ago = (time.time() - event.timestamp) / 3600
                    logger.info(f"   Time: {hours_ago:.1f} hours ago")
            else:
                logger.info("❌ No significant whale events detected")

            # Show wallet profiles
            logger.info("\n👛 Tracked Wallet Summary:")
            for address, profile in list(watcher.wallet_profiles.items())[:5]:  # Show first 5
                logger.info(f"   {profile.label}:")
                logger.info(f"     Category: {profile.category}")
                logger.info(f"     Transactions: {profile.transaction_count}")
                logger.info(f"     Avg Size: ${profile.avg_transaction_size:,.0f}")

                hours_since_activity = (time.time() - profile.last_activity) / 3600
                logger.info(f"     Last Activity: {hours_since_activity:.1f} hours ago")

            # Analyze trends
            logger.info("\n📊 Trend Analysis (Last 24h):")
            trends = await watcher.analyze_trends(24)

            trend_emoji = (
                "🟢"
                if trends["trend"] == "bullish"
                else "🔴" if trends["trend"] == "bearish" else "🟡"
            )
            logger.info(f"   Overall Trend: {trend_emoji} {trends['trend'].upper()}")
            logger.info(f"   Total Events: {trends['total_events']}")
            logger.info(f"   Total Volume: ${trends['total_volume_usd']:,.0f}")
            logger.info(
                f"   Bullish Events: {trends['bullish_events']} (${trends['bullish_volume']:,.0f})"
            )
            logger.info(
                f"   Bearish Events: {trends['bearish_events']} (${trends['bearish_volume']:,.0f})"
            )

            if trends["total_events"] > 0:
                logger.info(f"   Avg Significance: {trends['avg_significance']:.1%}")

            # Test specific asset query
            logger.info("\n🔍 Recent BTC whale activity:")
            btc_events = await watcher.get_recent_events(asset="BTC", hours=48)

            if btc_events:
                total_btc_volume = sum(e.amount for e in btc_events)
                total_btc_usd = sum(e.amount_usd for e in btc_events)
                logger.info(f"   {len(btc_events)} BTC events in last 48h")
                logger.info(f"   Total BTC moved: {total_btc_volume:,.2f} BTC")
                logger.info(f"   Total USD value: ${total_btc_usd:,.0f}")
            else:
                logger.info("   No recent BTC whale activity")

        except Exception as e:
            logger.error(f"❌ Demo failed: {e}")
        finally:
            await watcher.stop()

        logger.info("\n" + "=" * 55)
        logger.info("💡 WhaleWatcher demo completed!")
        logger.info("💡 Real implementation would connect to blockchain APIs")
        logger.info("💡 Whale movements can be leading indicators for price action")

    asyncio.run(demo())
