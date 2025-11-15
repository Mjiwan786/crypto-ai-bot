"""
PRD-001 Compliant Regime Detector Wrapper

This module wraps the existing RegimeDetector with PRD-001 Section 3.2 compliance:
- Maps regime labels to PRD format (TRENDING_UP, TRENDING_DOWN, RANGING, VOLATILE)
- Caches regime labels in Redis with 24hr TTL
- Logs regime changes at INFO level with confidence score
- Emits Prometheus gauge current_regime{pair}
- Updates classification every 5 minutes (configurable)

Architecture:
- Wraps ai_engine/regime_detector/detector.py
- Adds Redis caching, Prometheus metrics, logging
- Maintains backward compatibility with existing detector
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, Literal, Optional
from enum import Enum

import pandas as pd
import redis.asyncio as redis

from ai_engine.regime_detector.detector import RegimeDetector, RegimeTick, RegimeConfig

# PRD-001 Section 3.2: Prometheus metrics
try:
    from prometheus_client import Gauge
    CURRENT_REGIME = Gauge(
        'current_regime',
        'Current market regime by trading pair (0=RANGING, 1=TRENDING_UP, -1=TRENDING_DOWN, 2=VOLATILE)',
        ['pair']
    )
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    CURRENT_REGIME = None

logger = logging.getLogger(__name__)


# PRD-001 Section 3.2: Regime labels
class PRDRegimeLabel(str, Enum):
    """PRD-001 compliant regime labels"""
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGING = "RANGING"
    VOLATILE = "VOLATILE"


# Mapping from detector labels to PRD labels
REGIME_LABEL_MAP = {
    "bull": PRDRegimeLabel.TRENDING_UP,
    "bear": PRDRegimeLabel.TRENDING_DOWN,
    "chop": PRDRegimeLabel.RANGING,
}

# Prometheus gauge values for each regime
REGIME_GAUGE_VALUES = {
    PRDRegimeLabel.RANGING: 0,
    PRDRegimeLabel.TRENDING_UP: 1,
    PRDRegimeLabel.TRENDING_DOWN: -1,
    PRDRegimeLabel.VOLATILE: 2,
}


class PRDCompliantRegimeDetector:
    """
    PRD-001 Section 3.2 compliant regime detector.

    Wraps the existing RegimeDetector and adds:
    - Redis caching with 24hr TTL
    - Prometheus metrics
    - INFO level logging for regime changes
    - PRD-compliant regime labels

    Usage:
        detector = PRDCompliantRegimeDetector(redis_client=redis_client)
        regime_label = await detector.classify(ohlcv_df, pair="BTC/USD")
        # Returns: PRDRegimeLabel.TRENDING_UP, etc.
    """

    def __init__(
        self,
        redis_client: Optional[redis.Redis] = None,
        config: Optional[RegimeConfig] = None,
        update_interval_seconds: int = 300  # 5 minutes per PRD
    ):
        """
        Initialize PRD-compliant regime detector.

        Args:
            redis_client: Redis client for caching (optional)
            config: RegimeConfig for underlying detector (optional)
            update_interval_seconds: How often to update regime (default 300s = 5min)
        """
        self.detector = RegimeDetector(config=config)
        self.redis_client = redis_client
        self.update_interval_seconds = update_interval_seconds

        # Cache of last classification per pair
        self.last_classification: Dict[str, tuple[PRDRegimeLabel, float]] = {}  # pair -> (regime, timestamp)
        self.last_logged_regime: Dict[str, PRDRegimeLabel] = {}  # pair -> last logged regime

        logger.info(
            f"PRDCompliantRegimeDetector initialized with "
            f"update_interval={update_interval_seconds}s, "
            f"redis_enabled={redis_client is not None}"
        )

    async def classify(
        self,
        ohlcv_df: pd.DataFrame,
        pair: str,
        timeframe: str = "1h",
        force_update: bool = False
    ) -> PRDRegimeLabel:
        """
        Classify market regime with PRD-001 Section 3.2 compliance.

        Args:
            ohlcv_df: OHLCV DataFrame (PRD requires 200 candles = 16.7 hours for 1h data)
            pair: Trading pair (e.g., "BTC/USD")
            timeframe: Timeframe (default "1h" per PRD)
            force_update: Force classification update even if cached

        Returns:
            PRDRegimeLabel (TRENDING_UP, TRENDING_DOWN, RANGING, VOLATILE)
        """
        # PRD-001 Section 3.2: Check if update needed (every 5 minutes)
        now = time.time()
        last_regime, last_ts = self.last_classification.get(pair, (None, 0))

        if not force_update and (now - last_ts) < self.update_interval_seconds:
            # Use cached classification
            if last_regime:
                logger.debug(
                    f"Using cached regime for {pair}: {last_regime.value} "
                    f"(age: {now - last_ts:.1f}s)"
                )
                return last_regime

        # PRD-001 Section 3.2: Check Redis cache
        if self.redis_client:
            cached_regime = await self._get_from_redis(pair)
            if cached_regime:
                logger.debug(f"Using Redis cached regime for {pair}: {cached_regime.value}")
                self.last_classification[pair] = (cached_regime, now)
                return cached_regime

        # Run detection
        tick = self.detector.detect(ohlcv_df, timeframe=timeframe)

        # Map to PRD regime label
        prd_regime = self._map_to_prd_regime(tick)

        # PRD-001 Section 3.2: Log regime changes at INFO level with confidence
        if prd_regime != self.last_logged_regime.get(pair):
            logger.info(
                f"[REGIME CHANGE] {pair}: {self.last_logged_regime.get(pair, 'UNKNOWN')} → "
                f"{prd_regime.value} (confidence: {tick.strength:.2f}, "
                f"volatility: {tick.vol_regime})"
            )
            self.last_logged_regime[pair] = prd_regime

        # PRD-001 Section 3.2: Emit Prometheus gauge
        if PROMETHEUS_AVAILABLE and CURRENT_REGIME:
            gauge_value = REGIME_GAUGE_VALUES[prd_regime]
            CURRENT_REGIME.labels(pair=pair).set(gauge_value)

        # Update cache
        self.last_classification[pair] = (prd_regime, now)

        # PRD-001 Section 3.2: Cache in Redis with 24hr TTL
        if self.redis_client:
            await self._cache_to_redis(pair, prd_regime)

        return prd_regime

    def _map_to_prd_regime(self, tick: RegimeTick) -> PRDRegimeLabel:
        """
        Map RegimeTick to PRD regime label.

        PRD logic:
        - If vol_regime == vol_high → VOLATILE
        - Otherwise map regime: bull→TRENDING_UP, bear→TRENDING_DOWN, chop→RANGING

        Args:
            tick: RegimeTick from detector

        Returns:
            PRDRegimeLabel
        """
        # PRD-001 Section 3.2: High volatility overrides trend
        if tick.vol_regime == "vol_high":
            return PRDRegimeLabel.VOLATILE

        # Map trend regime
        return REGIME_LABEL_MAP.get(tick.regime, PRDRegimeLabel.RANGING)

    async def _get_from_redis(self, pair: str) -> Optional[PRDRegimeLabel]:
        """
        Get cached regime from Redis.

        Args:
            pair: Trading pair

        Returns:
            Cached PRDRegimeLabel or None if not found
        """
        if not self.redis_client:
            return None

        try:
            key = f"state:regime:{pair}"
            value = await self.redis_client.get(key)

            if value:
                regime_str = value.decode('utf-8') if isinstance(value, bytes) else value
                return PRDRegimeLabel(regime_str)

        except Exception as e:
            logger.warning(f"Failed to get regime from Redis for {pair}: {e}")

        return None

    async def _cache_to_redis(self, pair: str, regime: PRDRegimeLabel) -> None:
        """
        Cache regime to Redis with 24hr TTL.

        Args:
            pair: Trading pair
            regime: Regime label to cache
        """
        if not self.redis_client:
            return

        try:
            key = f"state:regime:{pair}"
            # PRD-001 Section 3.2: 24hr TTL
            ttl_seconds = 24 * 60 * 60

            await self.redis_client.setex(
                key,
                ttl_seconds,
                regime.value
            )

            logger.debug(f"Cached regime for {pair} in Redis: {regime.value} (TTL: 24h)")

        except Exception as e:
            logger.warning(f"Failed to cache regime to Redis for {pair}: {e}")

    async def get_cached_regime(self, pair: str) -> Optional[PRDRegimeLabel]:
        """
        Get cached regime without running detection.

        Args:
            pair: Trading pair

        Returns:
            Cached PRDRegimeLabel or None if not available
        """
        # Check memory cache
        regime, ts = self.last_classification.get(pair, (None, 0))
        if regime and (time.time() - ts) < self.update_interval_seconds:
            return regime

        # Check Redis cache
        if self.redis_client:
            return await self._get_from_redis(pair)

        return None

    def get_metrics(self) -> Dict[str, int]:
        """
        Get detector metrics.

        Returns:
            Dictionary with metrics
        """
        return {
            "cached_pairs": len(self.last_classification),
            "update_interval_seconds": self.update_interval_seconds,
        }


# Export for convenience
__all__ = [
    "PRDCompliantRegimeDetector",
    "PRDRegimeLabel",
]
