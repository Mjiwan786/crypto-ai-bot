"""
Cross-Venue Market Data Analyzer

Compares market data across venues (Binance vs Kraken) to detect:
- Price spreads (arbitrage opportunities)
- Liquidity imbalances
- Funding rate differentials
- Volume discrepancies

Emits signals for AI feature extraction.

Author: Crypto AI Bot Team
Date: 2025-11-08
"""

import time
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class VenueArbitrageDirection(Enum):
    """Direction of arbitrage opportunity."""
    BUY_BINANCE_SELL_KRAKEN = "buy_binance_sell_kraken"
    BUY_KRAKEN_SELL_BINANCE = "buy_kraken_sell_binance"
    NO_ARBITRAGE = "no_arbitrage"


@dataclass
class CrossVenueSpread:
    """Price spread between two venues."""
    symbol: str
    timestamp: float
    binance_bid: float
    binance_ask: float
    kraken_bid: float
    kraken_ask: float
    spread_bps: float  # (kraken_mid - binance_mid) / avg_mid * 10000
    arb_direction: VenueArbitrageDirection
    gross_edge_bps: float  # Before fees
    net_edge_bps: float  # After estimated fees (0.1% each side)
    is_arbitrageable: bool  # net_edge_bps >= 30 (0.3%)


@dataclass
class CrossVenueLiquidityImbalance:
    """Liquidity imbalance signal across venues."""
    symbol: str
    timestamp: float
    binance_imbalance: float  # Bid volume / (bid + ask)
    kraken_imbalance: float
    imbalance_divergence: float  # abs(binance - kraken)
    stronger_venue: str  # "binance" or "kraken"
    signal_strength: float  # 0.0 to 1.0


@dataclass
class FundingRateSignal:
    """Funding rate arbitrage signal."""
    symbol: str
    timestamp: float
    binance_funding_rate_8h: float  # Annualized
    kraken_funding_rate_8h: float  # Annualized (if available)
    funding_differential: float  # binance - kraken
    carry_trade_signal: str  # "long_binance", "short_binance", "neutral"
    annualized_carry_bps: float


class CrossVenueAnalyzer:
    """
    Analyzes market data across multiple venues.

    Detects arbitrage opportunities, liquidity imbalances, and funding differentials.
    """

    def __init__(self, redis_manager=None, logger=None):
        """
        Initialize cross-venue analyzer.

        Args:
            redis_manager: Redis manager for publishing signals
            logger: Logger instance
        """
        self.redis = redis_manager
        self.logger = logger or logging.getLogger(__name__)

        # Fee assumptions (conservative)
        self.binance_fee_bps = 10  # 0.1% maker/taker
        self.kraken_fee_bps = 16  # 0.16% maker, 0.26% taker (use taker)
        self.total_fees_bps = self.binance_fee_bps + self.kraken_fee_bps

        # Arbitrage thresholds
        self.min_arb_edge_bps = 30  # 0.3% minimum edge
        self.target_arb_edge_bps = 80  # 0.8% target edge

    def calculate_cross_venue_spread(
        self,
        symbol: str,
        binance_data: Dict,
        kraken_data: Dict,
    ) -> Optional[CrossVenueSpread]:
        """
        Calculate price spread between Binance and Kraken.

        Args:
            symbol: Symbol (e.g., "BTC/USD")
            binance_data: Binance market data dict
            kraken_data: Kraken market data dict

        Returns:
            CrossVenueSpread or None
        """
        # Extract liquidity snapshots
        binance_liq = binance_data.get("liquidity")
        kraken_liq = kraken_data.get("liquidity")

        if not binance_liq or not kraken_liq:
            return None

        try:
            # Get best bid/ask from each venue
            binance_bid = binance_liq.best_bid
            binance_ask = binance_liq.best_ask
            kraken_bid = kraken_liq.best_bid
            kraken_ask = kraken_liq.best_ask

            # Calculate mid prices
            binance_mid = (binance_bid + binance_ask) / 2
            kraken_mid = (kraken_bid + kraken_ask) / 2
            avg_mid = (binance_mid + kraken_mid) / 2

            # Spread in basis points
            spread_bps = ((kraken_mid - binance_mid) / avg_mid) * 10000

            # Determine arbitrage direction
            # Buy on cheaper venue, sell on more expensive venue
            if binance_ask < kraken_bid:
                # Can buy on Binance, sell on Kraken
                arb_direction = VenueArbitrageDirection.BUY_BINANCE_SELL_KRAKEN
                gross_edge_bps = ((kraken_bid - binance_ask) / binance_ask) * 10000
            elif kraken_ask < binance_bid:
                # Can buy on Kraken, sell on Binance
                arb_direction = VenueArbitrageDirection.BUY_KRAKEN_SELL_BINANCE
                gross_edge_bps = ((binance_bid - kraken_ask) / kraken_ask) * 10000
            else:
                arb_direction = VenueArbitrageDirection.NO_ARBITRAGE
                gross_edge_bps = 0.0

            # Net edge after fees
            net_edge_bps = gross_edge_bps - self.total_fees_bps

            # Is it arbitrageable?
            is_arbitrageable = (
                arb_direction != VenueArbitrageDirection.NO_ARBITRAGE
                and net_edge_bps >= self.min_arb_edge_bps
            )

            spread = CrossVenueSpread(
                symbol=symbol,
                timestamp=time.time(),
                binance_bid=binance_bid,
                binance_ask=binance_ask,
                kraken_bid=kraken_bid,
                kraken_ask=kraken_ask,
                spread_bps=spread_bps,
                arb_direction=arb_direction,
                gross_edge_bps=gross_edge_bps,
                net_edge_bps=net_edge_bps,
                is_arbitrageable=is_arbitrageable,
            )

            # Publish to Redis
            if self.redis:
                self._publish_spread_signal(spread)

            return spread

        except Exception as e:
            self.logger.error(f"Error calculating cross-venue spread for {symbol}: {e}")
            return None

    def calculate_liquidity_imbalance(
        self,
        symbol: str,
        binance_data: Dict,
        kraken_data: Dict,
    ) -> Optional[CrossVenueLiquidityImbalance]:
        """
        Calculate liquidity imbalance divergence across venues.

        Args:
            symbol: Symbol (e.g., "BTC/USD")
            binance_data: Binance market data dict
            kraken_data: Kraken market data dict

        Returns:
            CrossVenueLiquidityImbalance or None
        """
        binance_liq = binance_data.get("liquidity")
        kraken_liq = kraken_data.get("liquidity")

        if not binance_liq or not kraken_liq:
            return None

        try:
            binance_imbalance = binance_liq.imbalance_ratio
            kraken_imbalance = kraken_liq.imbalance_ratio

            # Divergence in imbalance
            imbalance_divergence = abs(binance_imbalance - kraken_imbalance)

            # Which venue has stronger buy pressure?
            stronger_venue = "binance" if binance_imbalance > kraken_imbalance else "kraken"

            # Signal strength: 0.0 (no divergence) to 1.0 (max divergence)
            # Max divergence = 1.0 (one venue 100% bid, other 100% ask)
            signal_strength = min(imbalance_divergence, 1.0)

            imbalance = CrossVenueLiquidityImbalance(
                symbol=symbol,
                timestamp=time.time(),
                binance_imbalance=binance_imbalance,
                kraken_imbalance=kraken_imbalance,
                imbalance_divergence=imbalance_divergence,
                stronger_venue=stronger_venue,
                signal_strength=signal_strength,
            )

            # Publish to Redis
            if self.redis:
                self._publish_liquidity_imbalance(imbalance)

            return imbalance

        except Exception as e:
            self.logger.error(
                f"Error calculating liquidity imbalance for {symbol}: {e}"
            )
            return None

    def calculate_funding_rate_signal(
        self,
        symbol: str,
        binance_data: Dict,
        kraken_data: Optional[Dict] = None,
    ) -> Optional[FundingRateSignal]:
        """
        Calculate funding rate arbitrage signal.

        Args:
            symbol: Symbol (e.g., "BTC/USD")
            binance_data: Binance market data dict
            kraken_data: Kraken market data dict (optional)

        Returns:
            FundingRateSignal or None
        """
        binance_funding = binance_data.get("funding")

        if not binance_funding:
            return None

        try:
            binance_rate = binance_funding.funding_rate_8h_annualized

            # Kraken funding rate (if available)
            # For now, assume 0 or use a default
            kraken_rate = 0.0
            if kraken_data and "funding" in kraken_data:
                kraken_rate = kraken_data["funding"].funding_rate_8h_annualized

            # Funding differential
            funding_differential = binance_rate - kraken_rate

            # Carry trade signal
            # Positive funding = longs pay shorts (expensive to be long)
            # Negative funding = shorts pay longs (expensive to be short)
            if funding_differential > 50:  # 0.5% annualized difference
                carry_trade_signal = "short_binance"  # Binance funding too high
            elif funding_differential < -50:
                carry_trade_signal = "long_binance"  # Binance funding too low
            else:
                carry_trade_signal = "neutral"

            # Annualized carry in basis points
            annualized_carry_bps = abs(funding_differential)

            signal = FundingRateSignal(
                symbol=symbol,
                timestamp=time.time(),
                binance_funding_rate_8h=binance_rate,
                kraken_funding_rate_8h=kraken_rate,
                funding_differential=funding_differential,
                carry_trade_signal=carry_trade_signal,
                annualized_carry_bps=annualized_carry_bps,
            )

            # Publish to Redis
            if self.redis:
                self._publish_funding_signal(signal)

            return signal

        except Exception as e:
            self.logger.error(f"Error calculating funding rate signal for {symbol}: {e}")
            return None

    def analyze_all_symbols(
        self,
        symbols: List[str],
        binance_data_map: Dict[str, Dict],
        kraken_data_map: Dict[str, Dict],
    ) -> Dict[str, Dict]:
        """
        Analyze all symbols for cross-venue signals.

        Args:
            symbols: List of symbols
            binance_data_map: Map of symbol -> Binance data
            kraken_data_map: Map of symbol -> Kraken data

        Returns:
            Dict mapping symbol to analysis results
        """
        results = {}

        for symbol in symbols:
            binance_data = binance_data_map.get(symbol, {})
            kraken_data = kraken_data_map.get(symbol, {})

            if not binance_data:
                continue

            analysis = {}

            # Calculate spread
            spread = self.calculate_cross_venue_spread(symbol, binance_data, kraken_data)
            if spread:
                analysis["spread"] = spread

            # Calculate liquidity imbalance
            imbalance = self.calculate_liquidity_imbalance(
                symbol, binance_data, kraken_data
            )
            if imbalance:
                analysis["liquidity_imbalance"] = imbalance

            # Calculate funding signal
            funding_signal = self.calculate_funding_rate_signal(
                symbol, binance_data, kraken_data
            )
            if funding_signal:
                analysis["funding_signal"] = funding_signal

            if analysis:
                results[symbol] = analysis

        return results

    def get_arbitrage_opportunities(
        self,
        symbols: List[str],
        binance_data_map: Dict[str, Dict],
        kraken_data_map: Dict[str, Dict],
    ) -> List[CrossVenueSpread]:
        """
        Get all active arbitrage opportunities.

        Args:
            symbols: List of symbols
            binance_data_map: Binance data map
            kraken_data_map: Kraken data map

        Returns:
            List of arbitrageable spreads
        """
        opportunities = []

        for symbol in symbols:
            binance_data = binance_data_map.get(symbol, {})
            kraken_data = kraken_data_map.get(symbol, {})

            if not binance_data or not kraken_data:
                continue

            spread = self.calculate_cross_venue_spread(symbol, binance_data, kraken_data)

            if spread and spread.is_arbitrageable:
                opportunities.append(spread)

        # Sort by net edge (highest first)
        opportunities.sort(key=lambda x: x.net_edge_bps, reverse=True)

        return opportunities

    def _publish_spread_signal(self, spread: CrossVenueSpread):
        """Publish cross-venue spread signal to Redis."""
        if not self.redis:
            return

        try:
            data = {
                "signal_type": "cross_venue_spread",
                "symbol": spread.symbol,
                "timestamp": spread.timestamp,
                "binance_bid": spread.binance_bid,
                "binance_ask": spread.binance_ask,
                "kraken_bid": spread.kraken_bid,
                "kraken_ask": spread.kraken_ask,
                "spread_bps": spread.spread_bps,
                "arb_direction": spread.arb_direction.value,
                "gross_edge_bps": spread.gross_edge_bps,
                "net_edge_bps": spread.net_edge_bps,
                "is_arbitrageable": spread.is_arbitrageable,
            }

            self.redis.publish_event(
                f"cross_venue:spread:{spread.symbol}",
                data
            )

        except Exception as e:
            self.logger.error(f"Error publishing spread signal: {e}")

    def _publish_liquidity_imbalance(self, imbalance: CrossVenueLiquidityImbalance):
        """Publish liquidity imbalance signal to Redis."""
        if not self.redis:
            return

        try:
            data = {
                "signal_type": "liquidity_imbalance",
                "symbol": imbalance.symbol,
                "timestamp": imbalance.timestamp,
                "binance_imbalance": imbalance.binance_imbalance,
                "kraken_imbalance": imbalance.kraken_imbalance,
                "imbalance_divergence": imbalance.imbalance_divergence,
                "stronger_venue": imbalance.stronger_venue,
                "signal_strength": imbalance.signal_strength,
            }

            self.redis.publish_event(
                f"cross_venue:liquidity_imbalance:{imbalance.symbol}",
                data
            )

        except Exception as e:
            self.logger.error(f"Error publishing liquidity imbalance: {e}")

    def _publish_funding_signal(self, signal: FundingRateSignal):
        """Publish funding rate signal to Redis."""
        if not self.redis:
            return

        try:
            data = {
                "signal_type": "funding_rate_signal",
                "symbol": signal.symbol,
                "timestamp": signal.timestamp,
                "binance_funding_rate_8h": signal.binance_funding_rate_8h,
                "kraken_funding_rate_8h": signal.kraken_funding_rate_8h,
                "funding_differential": signal.funding_differential,
                "carry_trade_signal": signal.carry_trade_signal,
                "annualized_carry_bps": signal.annualized_carry_bps,
            }

            self.redis.publish_event(
                f"cross_venue:funding:{signal.symbol}",
                data
            )

        except Exception as e:
            self.logger.error(f"Error publishing funding signal: {e}")
