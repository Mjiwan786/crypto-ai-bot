"""
Exchange Quality Scorer — selects the best OHLCV data source per pair/timeframe.

Policy: Pick the highest-quality exchange per pair, with ranked fallbacks.
NOT first-response-wins. NOT multi-exchange merge.

Scoring criteria:
  1. Freshness — age of the latest candle (newer = better)
  2. Continuity — missing candle rate over last 100 candles
  3. Spread proxy — average (high - low) / close ratio (lower = better liquidity)
  4. Reliability — cumulative hit rate over session lifetime
"""

import os
import time
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Exchanges available from multi_exchange_streamer
SUPPORTED_EXCHANGES = ["coinbase", "bitfinex", "binance", "bybit", "okx", "kucoin", "gateio", "kraken"]

# USDT exchanges — these stream BTC/USDT not BTC/USD
USDT_EXCHANGES = frozenset({"binance", "bybit", "okx", "kucoin", "gateio"})

# Timeframe string formats per exchange convention
TIMEFRAME_FORMATS: Dict[str, List[str]] = {
    "15s": ["15s", "15"],
    "1m": ["1m", "1", "60"],
    "5m": ["5m", "5", "300"],
    "15m": ["15m", "15", "900"],
    "1h": ["1h", "60", "3600"],
}


@dataclass
class ExchangeScore:
    exchange: str
    pair: str
    timeframe: str
    freshness_score: float = 0.0       # 0-1, higher = fresher
    continuity_score: float = 0.0      # 0-1, higher = fewer gaps
    spread_score: float = 0.0          # 0-1, higher = tighter spread
    reliability_score: float = 0.0     # 0-1, higher = more uptime
    available: bool = False            # Does data exist at all?
    candle_count: int = 0
    latest_candle_age_s: float = float('inf')

    @property
    def total_score(self) -> float:
        if not self.available:
            return 0.0
        # Weighted composite: freshness matters most, then continuity, then spread
        return (
            0.35 * self.freshness_score
            + 0.30 * self.continuity_score
            + 0.20 * self.spread_score
            + 0.15 * self.reliability_score
        )


class ExchangeScorer:
    """
    Scores and ranks exchanges for each pair/timeframe combination.

    Usage:
        scorer = ExchangeScorer()
        await scorer.score_all(redis_client, "BTC/USD", "5m")
        best = scorer.get_best("BTC/USD", "5m")
        fallbacks = scorer.get_ranked("BTC/USD", "5m")
    """

    def __init__(self, cache_ttl_s: int = 300):
        self._cache: Dict[str, Tuple[List[Tuple[str, ExchangeScore]], float]] = {}
        self._cache_ttl = cache_ttl_s
        self._reliability_tracker: Dict[str, Dict[str, int]] = {}

    async def score_all(
        self,
        redis_client: Any,
        pair: str,
        timeframe: str,
        lookback: int = 100,
    ) -> List[Tuple[str, ExchangeScore]]:
        """
        Score all exchanges for a given pair/timeframe.

        Returns list of (exchange_name, ExchangeScore) sorted by total_score descending.
        Results are cached for cache_ttl_s seconds.
        """
        cache_key = f"{pair}:{timeframe}"
        now = time.time()

        # Check cache
        if cache_key in self._cache:
            cached_scores, cached_time = self._cache[cache_key]
            if now - cached_time < self._cache_ttl:
                return cached_scores

        scores = []
        dash_pair = pair.replace("/", "-")

        for exchange in SUPPORTED_EXCHANGES:
            score = await self._score_exchange(
                redis_client, exchange, pair, dash_pair, timeframe, lookback
            )
            scores.append((exchange, score))

        # Sort by total score descending
        scores.sort(key=lambda x: x[1].total_score, reverse=True)

        # Cache
        self._cache[cache_key] = (scores, now)

        # Log the ranking
        available = [(ex, s) for ex, s in scores if s.available]
        if available:
            best_ex, best_score = available[0]
            logger.info(
                "[EXCHANGE_SCORER] %s %s: best=%s (score=%.2f, age=%.0fs, candles=%d) | "
                "alternatives=%s",
                pair, timeframe, best_ex, best_score.total_score,
                best_score.latest_candle_age_s, best_score.candle_count,
                ", ".join(f"{ex}={s.total_score:.2f}" for ex, s in available[1:3]),
            )
        else:
            logger.warning("[EXCHANGE_SCORER] %s %s: NO DATA from any exchange", pair, timeframe)

        return scores

    async def _score_exchange(
        self,
        redis_client: Any,
        exchange: str,
        pair: str,
        dash_pair: str,
        timeframe: str,
        lookback: int,
    ) -> ExchangeScore:
        """Score a single exchange for a pair/timeframe."""
        score = ExchangeScore(exchange=exchange, pair=pair, timeframe=timeframe)

        # Build Redis key candidates for this exchange
        keys_to_try = self._build_key_candidates(exchange, pair, dash_pair, timeframe)

        # Track reliability (miss if no data found)
        tracker_key = f"{exchange}:{pair}"
        if tracker_key not in self._reliability_tracker:
            self._reliability_tracker[tracker_key] = {"checks": 0, "hits": 0}
        tracker = self._reliability_tracker[tracker_key]
        tracker["checks"] += 1

        # Try each key
        candles = None
        for key in keys_to_try:
            try:
                client = redis_client.client if hasattr(redis_client, 'client') else redis_client
                entries = await client.xrevrange(key, count=lookback)
                if entries and len(entries) >= 20:
                    candles = list(entries)
                    candles.reverse()  # chronological
                    break
            except Exception:
                continue

        if candles is None or len(candles) < 20:
            return score

        score.available = True
        score.candle_count = len(candles)
        tracker["hits"] += 1

        # Parse candles for scoring
        closes: List[float] = []
        highs: List[float] = []
        lows: List[float] = []
        timestamps: List[float] = []
        for entry_id, fields in candles:
            try:
                def _get(k: str) -> float:
                    v = fields.get(k) or fields.get(k.encode() if isinstance(k, str) else k)
                    if v is None:
                        return 0.0
                    return float(v.decode() if isinstance(v, bytes) else v)

                c, h, l_val = _get("close"), _get("high"), _get("low")
                if c > 0:
                    closes.append(c)
                    highs.append(h if h > 0 else c)
                    lows.append(l_val if l_val > 0 else c)
                    # Extract timestamp from entry ID (milliseconds before the dash)
                    eid = entry_id.decode() if isinstance(entry_id, bytes) else entry_id
                    ts_ms = int(eid.split("-")[0])
                    timestamps.append(ts_ms / 1000.0)
            except (ValueError, TypeError):
                continue

        if len(closes) < 20:
            score.available = False
            return score

        now = time.time()

        # 1. FRESHNESS: age of latest candle
        latest_ts = timestamps[-1] if timestamps else 0
        age_s = now - latest_ts
        score.latest_candle_age_s = age_s
        # Exponential decay: <60s = ~1.0, >600s = ~0.13
        score.freshness_score = max(0.0, min(1.0, np.exp(-age_s / 300.0)))

        # 2. CONTINUITY: expected vs actual candle count
        if len(timestamps) >= 2:
            diffs = np.diff(timestamps)
            median_interval = float(np.median(diffs))
            if median_interval > 0:
                time_span = timestamps[-1] - timestamps[0]
                expected_candles = time_span / median_interval
                actual_candles = len(closes)
                if expected_candles > 0:
                    score.continuity_score = min(1.0, actual_candles / expected_candles)

        # 3. SPREAD PROXY: average (high - low) / close — lower is better (tighter)
        spreads = [(h - l_v) / c for h, l_v, c in zip(highs, lows, closes) if c > 0]
        if spreads:
            avg_spread = float(np.mean(spreads))
            # Invert: 0 spread = 1.0, 1% spread = ~0.0
            score.spread_score = max(0.0, min(1.0, 1.0 - avg_spread * 100))

        # 4. RELIABILITY: cumulative hit rate
        score.reliability_score = tracker["hits"] / tracker["checks"]

        return score

    def _build_key_candidates(
        self, exchange: str, pair: str, dash_pair: str, timeframe: str
    ) -> List[str]:
        """Build all possible Redis key formats for this exchange/pair/timeframe."""
        keys: List[str] = []
        # USDT exchanges use different pair format
        if exchange in USDT_EXCHANGES:
            usdt_pair = dash_pair.replace("-USD", "-USDT")
            for tf_fmt in TIMEFRAME_FORMATS.get(timeframe, [timeframe]):
                keys.append(f"{exchange}:ohlc:{tf_fmt}:{usdt_pair}")
        else:
            for tf_fmt in TIMEFRAME_FORMATS.get(timeframe, [timeframe]):
                keys.append(f"{exchange}:ohlc:{tf_fmt}:{dash_pair}")

        # Also try the aggregator format
        keys.append(f"ohlc:{timeframe}:{exchange}:{pair}")

        return keys

    def get_best(self, pair: str, timeframe: str) -> Optional[Tuple[str, ExchangeScore]]:
        """Get the best exchange for a pair/timeframe from cache."""
        cache_key = f"{pair}:{timeframe}"
        if cache_key in self._cache:
            scores, _ = self._cache[cache_key]
            for ex, score in scores:
                if score.available:
                    return (ex, score)
        return None

    def get_ranked(self, pair: str, timeframe: str) -> List[Tuple[str, float]]:
        """Get ranked exchanges for a pair/timeframe from cache."""
        cache_key = f"{pair}:{timeframe}"
        if cache_key in self._cache:
            scores, _ = self._cache[cache_key]
            return [(ex, s.total_score) for ex, s in scores if s.available]
        return []

    def invalidate_cache(self, pair: Optional[str] = None, timeframe: Optional[str] = None) -> None:
        """Clear cached scores. If pair+timeframe given, clear only that entry."""
        if pair and timeframe:
            cache_key = f"{pair}:{timeframe}"
            self._cache.pop(cache_key, None)
        else:
            self._cache.clear()
