"""
Cross-Venue Market Data Runner

Orchestrates Binance data collection, cross-venue analysis, and arbitrage detection.
Publishes signals to Redis for AI feature extraction.

Run continuously or on schedule.

Author: Crypto AI Bot Team
Date: 2025-11-08
"""

import os
import sys
import time
import logging
from pathlib import Path
from typing import Dict, List

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agents.infrastructure.binance_reader import BinanceReader
from agents.infrastructure.cross_venue_analyzer import CrossVenueAnalyzer
from agents.infrastructure.arbitrage_detector import ArbitrageDetector
from agents.infrastructure.redis_client import RedisCloudClient


class CrossVenueRunner:
    """
    Orchestrates cross-venue market data collection and analysis.
    """

    def __init__(
        self,
        symbols: List[str] = None,
        update_interval_seconds: int = 10,
        redis_url: str = None,
    ):
        """
        Initialize cross-venue runner.

        Args:
            symbols: List of symbols to monitor (default: BTC/USD, ETH/USD, SOL/USD)
            update_interval_seconds: Update interval (default: 10s)
            redis_url: Redis URL (default: from env)
        """
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )
        self.logger = logging.getLogger(__name__)

        # Symbols to monitor
        self.symbols = symbols or ["BTC/USD", "ETH/USD", "SOL/USD"]
        self.update_interval = update_interval_seconds

        # Initialize Redis
        redis_url = redis_url or os.getenv("REDIS_URL")
        self.redis = None
        if redis_url:
            try:
                self.redis = RedisCloudClient()
                self.logger.info("Redis connection established")
            except Exception as e:
                self.logger.error(f"Failed to connect to Redis: {e}")

        # Initialize components
        self.binance_reader = BinanceReader(
            redis_manager=self.redis,
            logger=self.logger,
        )

        self.analyzer = CrossVenueAnalyzer(
            redis_manager=self.redis,
            logger=self.logger,
        )

        self.arb_detector = ArbitrageDetector(
            binance_reader=self.binance_reader,
            cross_venue_analyzer=self.analyzer,
            redis_manager=self.redis,
            logger=self.logger,
        )

        # Check if enabled
        self.enabled = self.binance_reader.enabled

        if not self.enabled:
            self.logger.warning(
                "Cross-venue runner disabled. Set EXTERNAL_VENUE_READS=binance to enable."
            )
        else:
            self.logger.info(
                f"Cross-venue runner initialized for symbols: {', '.join(self.symbols)}"
            )

    def collect_binance_data(self) -> Dict[str, Dict]:
        """
        Collect market data from Binance for all symbols.

        Returns:
            Dict mapping symbol to data
        """
        if not self.enabled:
            return {}

        return self.binance_reader.get_all_symbols_data(self.symbols)

    def collect_kraken_data(self) -> Dict[str, Dict]:
        """
        Collect market data from Kraken for all symbols.

        For now, this is a placeholder. In production, would fetch from:
        - Kraken WebSocket
        - Kraken REST API
        - Cached data from existing Kraken connection

        Returns:
            Dict mapping symbol to data
        """
        # TODO: Integrate with existing Kraken data source
        # For now, return empty dict (arbitrage detection will skip)
        return {}

    def run_update_cycle(self):
        """Run a single update cycle."""
        if not self.enabled:
            return

        try:
            start_time = time.time()

            # Collect Binance data
            self.logger.debug("Collecting Binance market data...")
            binance_data = self.collect_binance_data()

            # Collect Kraken data
            self.logger.debug("Collecting Kraken market data...")
            kraken_data = self.collect_kraken_data()

            # Run cross-venue analysis
            self.logger.debug("Running cross-venue analysis...")
            if binance_data and kraken_data:
                analysis_results = self.analyzer.analyze_all_symbols(
                    self.symbols, binance_data, kraken_data
                )

                # Update arbitrage detector
                self.arb_detector.update_opportunities(
                    self.symbols, binance_data, kraken_data
                )

                # Get top opportunities
                opportunities = self.arb_detector.get_top_opportunities(limit=3)

                if opportunities:
                    self.logger.info(
                        f"Found {len(opportunities)} arbitrage opportunities:"
                    )
                    for opp in opportunities:
                        self.logger.info(
                            f"  - {opp.symbol} ({opp.direction}): "
                            f"{opp.net_edge_bps:.1f}bps edge, "
                            f"${opp.estimated_size_usd:,.0f} size"
                        )
            else:
                self.logger.debug("Insufficient data for cross-venue analysis")

            # Publish AI features to Redis
            self._publish_ai_features(binance_data, kraken_data)

            elapsed = time.time() - start_time
            self.logger.debug(f"Update cycle completed in {elapsed:.2f}s")

        except Exception as e:
            self.logger.error(f"Error in update cycle: {e}", exc_info=True)

    def _publish_ai_features(
        self, binance_data: Dict[str, Dict], kraken_data: Dict[str, Dict]
    ):
        """
        Publish AI-ready features to Redis.

        Args:
            binance_data: Binance market data
            kraken_data: Kraken market data
        """
        if not self.redis:
            return

        try:
            for symbol in self.symbols:
                binance = binance_data.get(symbol, {})
                kraken = kraken_data.get(symbol, {})

                if not binance:
                    continue

                # Build AI features
                features = {
                    "symbol": symbol,
                    "timestamp": time.time(),
                }

                # Binance liquidity features
                binance_liq = binance.get("liquidity")
                if binance_liq:
                    features["binance_liquidity_imbalance"] = binance_liq.imbalance_ratio
                    features["binance_spread_bps"] = binance_liq.spread_bps
                    features["binance_bid_depth_usd"] = binance_liq.bid_depth_usd
                    features["binance_ask_depth_usd"] = binance_liq.ask_depth_usd

                # Binance funding features
                binance_funding = binance.get("funding")
                if binance_funding:
                    features["binance_funding_rate_annualized"] = (
                        binance_funding.funding_rate_8h_annualized
                    )

                # Cross-venue features (if Kraken data available)
                if kraken:
                    spread = self.analyzer.calculate_cross_venue_spread(
                        symbol, binance, kraken
                    )
                    if spread:
                        features["cross_venue_spread_bps"] = spread.spread_bps
                        features["cross_venue_arb_edge_bps"] = spread.net_edge_bps
                        features["cross_venue_arb_opportunity"] = spread.is_arbitrageable

                    imbalance = self.analyzer.calculate_liquidity_imbalance(
                        symbol, binance, kraken
                    )
                    if imbalance:
                        features["liquidity_imbalance_divergence"] = (
                            imbalance.imbalance_divergence
                        )
                        features["liquidity_imbalance_strength"] = (
                            imbalance.signal_strength
                        )

                # Publish to AI features stream
                self.redis.publish_event(f"ai_features:cross_venue:{symbol}", features)

        except Exception as e:
            self.logger.error(f"Error publishing AI features: {e}")

    def run_continuous(self):
        """Run continuous monitoring loop."""
        if not self.enabled:
            self.logger.warning("Cross-venue runner not enabled. Exiting.")
            return

        self.logger.info(
            f"Starting continuous monitoring (interval: {self.update_interval}s)..."
        )

        try:
            while True:
                self.run_update_cycle()
                time.sleep(self.update_interval)
        except KeyboardInterrupt:
            self.logger.info("Shutting down cross-venue runner...")
        except Exception as e:
            self.logger.error(f"Fatal error in continuous loop: {e}", exc_info=True)


def main():
    """Main entry point."""
    # Parse command line args
    import argparse

    parser = argparse.ArgumentParser(
        description="Cross-venue market data runner (READ-ONLY)"
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default="BTC/USD,ETH/USD,SOL/USD",
        help="Comma-separated symbols to monitor",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=10,
        help="Update interval in seconds (default: 10)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run once and exit (default: continuous)",
    )

    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",")]

    runner = CrossVenueRunner(
        symbols=symbols,
        update_interval_seconds=args.interval,
    )

    if args.once:
        runner.run_update_cycle()
    else:
        runner.run_continuous()


if __name__ == "__main__":
    main()
