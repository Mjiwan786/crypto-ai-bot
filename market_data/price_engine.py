"""
Internal Synthetic Price Engine

Computes weighted synthetic prices from multiple exchange feeds.
Applies outlier filtering, staleness checks, and confidence scoring.

Redis Stream Namespaces:
- market:price:{pair}   - Synthetic weighted prices
- market:spread:{pair}  - Spread estimates

Example:
    from market_data.price_engine import PriceEngine

    engine = PriceEngine(orchestrator, config)
    await engine.start()

    # Get synthetic price
    price_data = await engine.get_price("BTC/USD")
    print(price_data.price)  # Weighted average price
"""

from __future__ import annotations

import asyncio
import logging
import statistics
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from market_data.base import TickerData, internal_to_stream
from market_data.config import MarketDataConfig

logger = logging.getLogger(__name__)


@dataclass
class SyntheticPrice:
    """Synthetic price computed from multiple exchanges.

    Attributes:
        ts_ms: Timestamp in milliseconds
        pair: Trading pair in internal format
        price: Weighted average price
        exchanges_used: List of exchanges contributing to price
        weights_used: Weights applied to each exchange
        spread: Estimated spread (bid-ask)
        confidence: Confidence score (0-1)
        stale_exchanges: Exchanges with stale data
    """

    ts_ms: int
    pair: str
    price: float
    exchanges_used: List[str]
    weights_used: Dict[str, float]
    spread: Optional[float] = None
    confidence: float = 1.0
    stale_exchanges: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, str]:
        """Convert to string dict for Redis publishing."""
        return {
            "ts_ms": str(self.ts_ms),
            "pair": self.pair,
            "price": str(self.price),
            "exchanges_used": ",".join(self.exchanges_used),
            "weights_used": ",".join(f"{k}:{v}" for k, v in self.weights_used.items()),
            "spread": str(self.spread) if self.spread is not None else "",
            "confidence": str(self.confidence),
            "stale_exchanges": ",".join(self.stale_exchanges),
        }

    def to_json_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "ts_ms": self.ts_ms,
            "pair": self.pair,
            "price": self.price,
            "exchanges_used": self.exchanges_used,
            "weights_used": self.weights_used,
            "spread": self.spread,
            "confidence": self.confidence,
            "stale_exchanges": self.stale_exchanges,
        }


class PriceEngine:
    """Computes synthetic prices from multiple exchange feeds.

    Consumes ticker data from orchestrator, applies weighting and
    filtering, and produces synthetic prices.

    Features:
    - Weighted price averaging (configurable weights per exchange)
    - Staleness detection (drops data older than threshold)
    - Outlier filtering (filters prices deviating from median)
    - Spread estimation from best bid/ask
    - Confidence scoring based on data quality

    Attributes:
        orchestrator: MarketDataOrchestrator providing raw data
        config: Market data configuration
    """

    def __init__(
        self,
        orchestrator: Any,  # MarketDataOrchestrator
        config: Optional[MarketDataConfig] = None,
        redis_client: Optional[Any] = None,
    ):
        """Initialize price engine.

        Args:
            orchestrator: MarketDataOrchestrator instance
            config: Optional config (uses orchestrator's config if not provided)
            redis_client: Optional Redis client for publishing
        """
        self._orchestrator = orchestrator
        self._config = config or orchestrator.config
        self._redis = redis_client
        self._running = False
        self._tasks: List[asyncio.Task] = []

        # Cache of latest synthetic prices
        self._latest_prices: Dict[str, SyntheticPrice] = {}

        # Statistics
        self._compute_count = 0
        self._start_time: Optional[float] = None

    async def start(self) -> None:
        """Start the price engine.

        Begins computing synthetic prices for all configured pairs.
        """
        if self._running:
            logger.warning("Price engine already running")
            return

        if not self._config.feature_flags.price_engine_enabled:
            logger.warning("Price engine feature flag is disabled. Not starting.")
            return

        logger.info(f"Starting Price Engine for {len(self._config.pairs)} pairs")

        self._running = True
        self._start_time = time.time()

        # Start compute loops for each pair
        for pair in self._config.pairs:
            task = asyncio.create_task(self._compute_loop(pair))
            self._tasks.append(task)

        logger.info("Price Engine started")

    async def stop(self) -> None:
        """Stop the price engine."""
        if not self._running:
            return

        logger.info("Stopping Price Engine...")
        self._running = False

        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self._tasks.clear()

        if self._start_time:
            runtime = time.time() - self._start_time
            logger.info(
                f"Price Engine stopped. Runtime: {runtime:.1f}s, "
                f"Computations: {self._compute_count}"
            )

    async def _compute_loop(self, pair: str) -> None:
        """Continuously compute synthetic price for a pair.

        Args:
            pair: Trading pair in internal format
        """
        interval = self._config.polling.interval_sec

        while self._running:
            try:
                price = await self.compute_price(pair)

                if price:
                    self._latest_prices[pair] = price

                    # Publish to Redis
                    await self._publish_price(price)
                    await self._publish_spread(price)

                    self._compute_count += 1

            except Exception as e:
                logger.error(f"Price computation error for {pair}: {e}")

            await asyncio.sleep(interval)

    async def compute_price(self, pair: str) -> Optional[SyntheticPrice]:
        """Compute synthetic price for a pair.

        Gathers tickers from all exchanges, applies filtering,
        and computes weighted average.

        Args:
            pair: Trading pair in internal format

        Returns:
            SyntheticPrice or None if insufficient data
        """
        now_ms = int(time.time() * 1000)
        stale_threshold_ms = int(self._config.health.stale_after_sec * 1000)

        # Gather tickers from all exchanges
        tickers = self._orchestrator.get_all_latest_tickers(pair)

        if not tickers:
            logger.debug(f"No tickers available for {pair}")
            return None

        # Separate fresh and stale tickers
        fresh_tickers: Dict[str, TickerData] = {}
        stale_exchanges: List[str] = []

        for exchange, ticker in tickers.items():
            age_ms = now_ms - ticker.ts_ms
            if age_ms <= stale_threshold_ms:
                fresh_tickers[exchange] = ticker
            else:
                stale_exchanges.append(exchange)
                logger.debug(f"Stale ticker from {exchange}: {age_ms}ms old")

        if not fresh_tickers:
            logger.warning(f"All tickers stale for {pair}")
            return None

        # Apply outlier filter
        if (
            self._config.feature_flags.outlier_filtering
            and len(fresh_tickers) >= self._config.outlier_filter.min_exchanges_for_filter
        ):
            fresh_tickers = self._filter_outliers(fresh_tickers)

        if not fresh_tickers:
            logger.warning(f"All tickers filtered as outliers for {pair}")
            return None

        # Compute weighted price
        weighted_price, weights_used = self._compute_weighted_price(fresh_tickers)

        # Compute spread
        spread = self._compute_spread(fresh_tickers)

        # Compute confidence
        confidence = self._compute_confidence(
            exchanges_used=list(fresh_tickers.keys()),
            total_exchanges=len(self._config.enabled_exchanges),
            has_spread=(spread is not None),
        )

        return SyntheticPrice(
            ts_ms=now_ms,
            pair=pair,
            price=weighted_price,
            exchanges_used=list(fresh_tickers.keys()),
            weights_used=weights_used,
            spread=spread,
            confidence=confidence,
            stale_exchanges=stale_exchanges,
        )

    def _filter_outliers(
        self, tickers: Dict[str, TickerData]
    ) -> Dict[str, TickerData]:
        """Filter outlier prices that deviate too much from median.

        Args:
            tickers: Dict of exchange -> TickerData

        Returns:
            Filtered dict with outliers removed
        """
        if len(tickers) < 2:
            return tickers

        prices = [t.price for t in tickers.values()]
        median_price = statistics.median(prices)
        max_deviation_pct = self._config.outlier_filter.max_deviation_pct

        filtered = {}
        for exchange, ticker in tickers.items():
            deviation_pct = abs(ticker.price - median_price) / median_price * 100

            if deviation_pct <= max_deviation_pct:
                filtered[exchange] = ticker
            else:
                logger.warning(
                    f"Outlier filtered: {exchange} {ticker.pair} "
                    f"${ticker.price:.2f} (deviation: {deviation_pct:.2f}%)"
                )

        return filtered

    def _compute_weighted_price(
        self, tickers: Dict[str, TickerData]
    ) -> tuple[float, Dict[str, float]]:
        """Compute weighted average price.

        Args:
            tickers: Dict of exchange -> TickerData

        Returns:
            Tuple of (weighted_price, weights_used)
        """
        if not tickers:
            return 0.0, {}

        # Get raw weights
        raw_weights = {}
        for exchange in tickers:
            raw_weights[exchange] = self._config.get_weight(exchange)

        # Normalize weights to sum to 1.0
        total_weight = sum(raw_weights.values())
        if total_weight == 0:
            # Equal weights if all zero
            equal_weight = 1.0 / len(tickers)
            normalized_weights = {ex: equal_weight for ex in tickers}
        else:
            normalized_weights = {
                ex: w / total_weight for ex, w in raw_weights.items()
            }

        # Compute weighted sum
        weighted_sum = 0.0
        for exchange, ticker in tickers.items():
            weighted_sum += ticker.price * normalized_weights[exchange]

        return weighted_sum, normalized_weights

    def _compute_spread(
        self, tickers: Dict[str, TickerData]
    ) -> Optional[float]:
        """Compute spread estimate from best bid/ask across exchanges.

        Args:
            tickers: Dict of exchange -> TickerData

        Returns:
            Spread in price units, or None if insufficient data
        """
        best_bid: Optional[float] = None
        best_ask: Optional[float] = None

        for ticker in tickers.values():
            if ticker.bid is not None:
                if best_bid is None or ticker.bid > best_bid:
                    best_bid = ticker.bid
            if ticker.ask is not None:
                if best_ask is None or ticker.ask < best_ask:
                    best_ask = ticker.ask

        if best_bid is not None and best_ask is not None:
            return best_ask - best_bid

        return None

    def _compute_confidence(
        self,
        exchanges_used: List[str],
        total_exchanges: int,
        has_spread: bool,
    ) -> float:
        """Compute confidence score.

        Confidence heuristic:
        - Start at base_confidence (1.0)
        - Subtract penalty for each missing exchange
        - Subtract penalty if spread unavailable
        - Clamp to [min_confidence, max_confidence]

        Args:
            exchanges_used: List of exchanges contributing data
            total_exchanges: Total configured exchanges
            has_spread: Whether spread data is available

        Returns:
            Confidence score between 0 and 1
        """
        conf = self._config.confidence

        score = conf.base_confidence

        # Penalty for missing exchanges
        missing = total_exchanges - len(exchanges_used)
        score -= missing * conf.penalty_per_missing_exchange

        # Penalty for missing spread
        if not has_spread:
            score -= conf.penalty_no_spread

        # Clamp to bounds
        return max(conf.min_confidence, min(conf.max_confidence, score))

    async def _publish_price(self, price: SyntheticPrice) -> None:
        """Publish synthetic price to Redis stream.

        Stream: market:price:{pair}
        Example: market:price:BTC-USD

        Args:
            price: SyntheticPrice to publish
        """
        if self._redis is None:
            return

        try:
            stream_pair = internal_to_stream(price.pair)
            stream_name = self._config.redis.streams.price.format(pair=stream_pair)

            fields = price.to_dict()
            maxlen = self._config.redis.maxlen.price

            await self._redis.xadd(stream_name, fields, maxlen=maxlen)

        except Exception as e:
            logger.error(f"Failed to publish price to Redis: {e}")

    async def _publish_spread(self, price: SyntheticPrice) -> None:
        """Publish spread estimate to Redis stream.

        Stream: market:spread:{pair}
        Example: market:spread:BTC-USD

        Args:
            price: SyntheticPrice containing spread
        """
        if self._redis is None or price.spread is None:
            return

        try:
            stream_pair = internal_to_stream(price.pair)
            stream_name = self._config.redis.streams.spread.format(pair=stream_pair)

            fields = {
                "ts_ms": str(price.ts_ms),
                "pair": price.pair,
                "spread": str(price.spread),
                "price": str(price.price),
                "spread_bps": str(int(price.spread / price.price * 10000))
                if price.price > 0
                else "0",
            }

            maxlen = self._config.redis.maxlen.spread

            await self._redis.xadd(stream_name, fields, maxlen=maxlen)

        except Exception as e:
            logger.error(f"Failed to publish spread to Redis: {e}")

    # ==========================================================================
    # Public API
    # ==========================================================================

    def get_price(self, pair: str) -> Optional[SyntheticPrice]:
        """Get latest cached synthetic price for a pair.

        Args:
            pair: Trading pair in internal format

        Returns:
            SyntheticPrice or None if not available
        """
        return self._latest_prices.get(pair)

    def get_all_prices(self) -> Dict[str, SyntheticPrice]:
        """Get all cached synthetic prices.

        Returns:
            Dict of pair -> SyntheticPrice
        """
        return self._latest_prices.copy()

    @property
    def is_running(self) -> bool:
        """Check if engine is running."""
        return self._running

    @property
    def stats(self) -> Dict[str, Any]:
        """Get engine statistics."""
        runtime = 0.0
        if self._start_time:
            runtime = time.time() - self._start_time

        return {
            "running": self._running,
            "runtime_seconds": runtime,
            "compute_count": self._compute_count,
            "pairs": list(self._latest_prices.keys()),
            "computes_per_second": self._compute_count / runtime if runtime > 0 else 0,
        }


# ==============================================================================
# Exports
# ==============================================================================

__all__ = [
    "PriceEngine",
    "SyntheticPrice",
]
