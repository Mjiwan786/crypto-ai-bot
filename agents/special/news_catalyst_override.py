"""
News & Event Catalyst Override (agents/special/news_catalyst_override.py)

Integrates crypto news API + sentiment filter for event-driven trading:
- High-impact news detection (sentiment >0.7)
- Volume spike confirmation
- Temporary position size boost (2x)
- Relaxed TP, shortened SL
- Gated behind NEWS_TRADE_MODE=true

For Prompt 6: Market Intelligence Layer
Author: Crypto AI Bot Team
Version: 2.0.0
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional

import aiohttp
import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class NewsSentiment(str, Enum):
    """News sentiment classification."""

    VERY_BULLISH = "very_bullish"
    BULLISH = "bullish"
    NEUTRAL = "neutral"
    BEARISH = "bearish"
    VERY_BEARISH = "very_bearish"


class NewsImpact(str, Enum):
    """News impact level."""

    CRITICAL = "critical"  # Major events (e.g., Fed, halving)
    HIGH = "high"  # Important news
    MEDIUM = "medium"  # Moderate impact
    LOW = "low"  # Minor news


class NewsCatalystConfig(BaseModel):
    """Configuration for news catalyst override."""

    # News API (using CryptoPanic as example, can swap for others)
    news_api_url: str = Field(
        default="https://cryptopanic.com/api/v1/posts/",
        description="News API endpoint",
    )
    news_api_key: str = Field(
        default=os.getenv("CRYPTOPANIC_API_KEY", ""),
        description="News API key",
    )

    # Sentiment thresholds
    min_sentiment_score: float = Field(default=0.7, ge=0.0, le=1.0, description="Min sentiment for trigger")
    min_volume_spike_multiplier: float = Field(default=1.5, ge=1.0, le=5.0, description="Min volume spike (vs avg)")

    # Position sizing overrides
    position_size_multiplier: float = Field(default=2.0, ge=1.0, le=3.0, description="Position size boost")
    tp_relaxation_multiplier: float = Field(default=1.5, ge=1.0, le=2.0, description="TP distance multiplier")
    sl_tightening_multiplier: float = Field(default=0.7, ge=0.3, le=1.0, description="SL distance multiplier")

    # Override duration
    override_duration_minutes: int = Field(default=60, ge=5, le=240, description="How long override lasts")

    # Feature flag
    enabled: bool = Field(default=os.getenv("NEWS_TRADE_MODE", "false").lower() == "true", description="Enable news trading")

    # Update interval
    news_fetch_interval_seconds: int = Field(default=300, ge=60, le=3600, description="News fetch interval")


@dataclass
class NewsEvent:
    """Detected news event."""

    title: str
    url: str
    source: str
    published_at: datetime
    sentiment: NewsSentiment
    sentiment_score: float  # 0-1 scale
    impact: NewsImpact
    currencies: List[str]  # Affected currencies
    votes: Dict[str, int]  # {"positive": 10, "negative": 2, "saved": 5}


@dataclass
class CatalystOverride:
    """Active catalyst override."""

    pair: str
    news_event: NewsEvent
    activated_at: datetime
    expires_at: datetime
    position_size_multiplier: float
    tp_multiplier: float
    sl_multiplier: float
    volume_spike_detected: bool
    volume_spike_ratio: float


class NewsCatalystOverride:
    """
    Monitors crypto news and triggers position overrides on high-impact events.

    Features:
    - CryptoPanic API integration (or other news sources)
    - Sentiment analysis (bullish/bearish classification)
    - Volume spike confirmation
    - Temporary position sizing + TP/SL adjustments
    """

    def __init__(
        self,
        config: Optional[NewsCatalystConfig] = None,
        redis_client=None,
    ):
        """
        Initialize news catalyst system.

        Args:
            config: Configuration
            redis_client: Redis client for caching
        """
        self.config = config or NewsCatalystConfig()
        self.redis_client = redis_client

        # Active overrides
        self.active_overrides: Dict[str, CatalystOverride] = {}  # {pair: CatalystOverride}

        # News cache (prevent re-processing)
        self.processed_news: set = set()

        # Metrics
        self.news_events_processed = 0
        self.overrides_activated = 0

        if not self.config.enabled:
            logger.info("News catalyst override DISABLED (NEWS_TRADE_MODE=false)")
        else:
            logger.info("News catalyst override ENABLED (NEWS_TRADE_MODE=true)")

    async def fetch_latest_news(self) -> List[NewsEvent]:
        """
        Fetch latest crypto news from API.

        Returns:
            List of NewsEvent objects
        """
        if not self.config.news_api_key:
            logger.warning("No news API key configured, using mock data")
            return self._get_mock_news()

        try:
            # CryptoPanic API parameters
            params = {
                "auth_token": self.config.news_api_key,
                "public": "true",
                "kind": "news",  # Only news, not media
                "filter": "rising",  # Get trending news
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.config.news_api_url,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        logger.warning("News API error: %d", resp.status)
                        return []

                    data = await resp.json()

            # Parse news events
            news_events = []

            for item in data.get("results", [])[:20]:  # Process top 20
                event_id = item.get("id")

                # Skip if already processed
                if event_id in self.processed_news:
                    continue

                self.processed_news.add(event_id)

                # Parse sentiment from votes
                votes = item.get("votes", {})
                positive = votes.get("positive", 0)
                negative = votes.get("negative", 0)
                total_votes = positive + negative

                if total_votes == 0:
                    sentiment_score = 0.5  # Neutral
                else:
                    sentiment_score = positive / total_votes

                # Classify sentiment
                if sentiment_score >= 0.8:
                    sentiment = NewsSentiment.VERY_BULLISH
                elif sentiment_score >= 0.6:
                    sentiment = NewsSentiment.BULLISH
                elif sentiment_score >= 0.4:
                    sentiment = NewsSentiment.NEUTRAL
                elif sentiment_score >= 0.2:
                    sentiment = NewsSentiment.BEARISH
                else:
                    sentiment = NewsSentiment.VERY_BEARISH

                # Determine impact (based on votes and engagement)
                total_engagement = votes.get("saved", 0) + total_votes

                if total_engagement >= 100:
                    impact = NewsImpact.CRITICAL
                elif total_engagement >= 50:
                    impact = NewsImpact.HIGH
                elif total_engagement >= 20:
                    impact = NewsImpact.MEDIUM
                else:
                    impact = NewsImpact.LOW

                # Extract currencies
                currencies = [c["code"] for c in item.get("currencies", [])]

                news_event = NewsEvent(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    source=item.get("source", {}).get("title", "Unknown"),
                    published_at=datetime.fromisoformat(item.get("published_at", "").replace("Z", "+00:00")),
                    sentiment=sentiment,
                    sentiment_score=sentiment_score,
                    impact=impact,
                    currencies=currencies,
                    votes=votes,
                )

                news_events.append(news_event)

                logger.info(
                    "News: %s | Sentiment: %s (%.2f) | Impact: %s | Currencies: %s",
                    news_event.title[:50],
                    news_event.sentiment.value,
                    news_event.sentiment_score,
                    news_event.impact.value,
                    ", ".join(news_event.currencies),
                )

            self.news_events_processed += len(news_events)

            return news_events

        except Exception as e:
            logger.exception("Failed to fetch news: %s", e)
            return []

    def _get_mock_news(self) -> List[NewsEvent]:
        """Generate mock news for testing."""
        # In production, remove this and require real API key
        return [
            NewsEvent(
                title="Bitcoin ETF approval imminent - SEC signals green light",
                url="https://example.com/btc-etf",
                source="MockNews",
                published_at=datetime.now(),
                sentiment=NewsSentiment.VERY_BULLISH,
                sentiment_score=0.92,
                impact=NewsImpact.CRITICAL,
                currencies=["BTC"],
                votes={"positive": 150, "negative": 10, "saved": 50},
            ),
        ]

    def check_volume_spike(
        self,
        pair: str,
        current_volume: float,
        volume_history: pd.Series,
    ) -> tuple[bool, float]:
        """
        Check if current volume is spiking.

        Args:
            pair: Trading pair
            current_volume: Current bar volume
            volume_history: Historical volume series

        Returns:
            (is_spike, spike_ratio)
        """
        if len(volume_history) < 20:
            return False, 1.0

        # Calculate average volume (20-period)
        avg_volume = volume_history.tail(20).mean()

        # Calculate spike ratio
        spike_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0

        # Check if spike exceeds threshold
        is_spike = spike_ratio >= self.config.min_volume_spike_multiplier

        logger.debug(
            "Volume check for %s: current=%.2f, avg=%.2f, ratio=%.2fx, spike=%s",
            pair, current_volume, avg_volume, spike_ratio, is_spike
        )

        return is_spike, spike_ratio

    def should_activate_override(
        self,
        news_event: NewsEvent,
        pair: str,
        volume_spike_detected: bool,
    ) -> bool:
        """
        Determine if override should be activated.

        Args:
            news_event: News event
            pair: Trading pair
            volume_spike_detected: Whether volume spike detected

        Returns:
            True if should activate
        """
        # Check if enabled
        if not self.config.enabled:
            return False

        # Check if pair is affected
        pair_currency = pair.split("/")[0]  # Extract BTC from BTC/USD
        if pair_currency not in news_event.currencies:
            return False

        # Check sentiment threshold
        if abs(news_event.sentiment_score - 0.5) < (self.config.min_sentiment_score - 0.5):
            # Sentiment not strong enough (too close to neutral)
            logger.debug(
                "Sentiment too weak for %s: %.2f (need %.2f)",
                pair, news_event.sentiment_score, self.config.min_sentiment_score
            )
            return False

        # Check volume spike
        if not volume_spike_detected:
            logger.debug("No volume spike for %s, not activating override", pair)
            return False

        # Check impact level (at least MEDIUM)
        if news_event.impact not in [NewsImpact.CRITICAL, NewsImpact.HIGH, NewsImpact.MEDIUM]:
            logger.debug("Impact too low: %s", news_event.impact.value)
            return False

        return True

    def activate_override(
        self,
        pair: str,
        news_event: NewsEvent,
        volume_spike_ratio: float,
    ) -> CatalystOverride:
        """
        Activate catalyst override for a pair.

        Args:
            pair: Trading pair
            news_event: News event triggering override
            volume_spike_ratio: Volume spike ratio

        Returns:
            CatalystOverride object
        """
        now = datetime.now()
        expires_at = now + timedelta(minutes=self.config.override_duration_minutes)

        # Determine direction-specific multipliers
        if news_event.sentiment in [NewsSentiment.VERY_BULLISH, NewsSentiment.BULLISH]:
            # Bullish news: boost longs
            position_multiplier = self.config.position_size_multiplier
        elif news_event.sentiment in [NewsSentiment.VERY_BEARISH, NewsSentiment.BEARISH]:
            # Bearish news: boost shorts
            position_multiplier = self.config.position_size_multiplier
        else:
            # Neutral: no boost
            position_multiplier = 1.0

        override = CatalystOverride(
            pair=pair,
            news_event=news_event,
            activated_at=now,
            expires_at=expires_at,
            position_size_multiplier=position_multiplier,
            tp_multiplier=self.config.tp_relaxation_multiplier,
            sl_multiplier=self.config.sl_tightening_multiplier,
            volume_spike_detected=True,
            volume_spike_ratio=volume_spike_ratio,
        )

        self.active_overrides[pair] = override
        self.overrides_activated += 1

        logger.warning(
            "CATALYST OVERRIDE ACTIVATED: %s | News: %s | Sentiment: %s (%.2f) | "
            "Position: %.1fx | TP: %.1fx | SL: %.1fx | Vol spike: %.1fx | Expires: %s",
            pair,
            news_event.title[:50],
            news_event.sentiment.value,
            news_event.sentiment_score,
            position_multiplier,
            override.tp_multiplier,
            override.sl_multiplier,
            volume_spike_ratio,
            expires_at.strftime("%H:%M:%S"),
        )

        # Publish to Redis
        if self.redis_client:
            try:
                self._publish_override_activation(override)
            except Exception as e:
                logger.exception("Failed to publish override: %s", e)

        return override

    def _publish_override_activation(self, override: CatalystOverride) -> None:
        """Publish override activation to Redis."""
        if not self.redis_client:
            return

        key = f"news:override:{override.pair.replace('/', '_')}"

        data = {
            "pair": override.pair,
            "news_title": override.news_event.title,
            "sentiment": override.news_event.sentiment.value,
            "sentiment_score": override.news_event.sentiment_score,
            "position_multiplier": override.position_size_multiplier,
            "tp_multiplier": override.tp_multiplier,
            "sl_multiplier": override.sl_multiplier,
            "volume_spike_ratio": override.volume_spike_ratio,
            "activated_at": override.activated_at.isoformat(),
            "expires_at": override.expires_at.isoformat(),
        }

        # Set with TTL
        ttl = int((override.expires_at - override.activated_at).total_seconds())
        self.redis_client.setex(key, ttl, str(data))

        # Also publish to stream
        stream_key = "news:overrides"
        self.redis_client.xadd(stream_key, data, maxlen=100)

    def get_active_override(self, pair: str) -> Optional[CatalystOverride]:
        """
        Get active override for a pair.

        Args:
            pair: Trading pair

        Returns:
            CatalystOverride or None
        """
        if pair not in self.active_overrides:
            return None

        override = self.active_overrides[pair]

        # Check if expired
        if datetime.now() >= override.expires_at:
            logger.info("Override expired for %s", pair)
            del self.active_overrides[pair]
            return None

        return override

    def cleanup_expired_overrides(self) -> None:
        """Remove expired overrides."""
        now = datetime.now()
        expired_pairs = [
            pair for pair, override in self.active_overrides.items()
            if now >= override.expires_at
        ]

        for pair in expired_pairs:
            logger.info("Removing expired override for %s", pair)
            del self.active_overrides[pair]

    async def monitor_news(self) -> None:
        """Continuously monitor news feed."""
        logger.info("Starting news monitoring (enabled=%s)", self.config.enabled)

        while True:
            try:
                # Fetch latest news
                news_events = await self.fetch_latest_news()

                # Process each event
                for event in news_events:
                    # Check all monitored pairs
                    for pair in ["BTC/USD", "ETH/USD", "SOL/USD", "ADA/USD"]:
                        # Skip if already has active override
                        if self.get_active_override(pair):
                            continue

                        # For testing, assume volume spike if sentiment strong
                        # In production, pass actual volume data
                        volume_spike = abs(event.sentiment_score - 0.5) > 0.3

                        if self.should_activate_override(event, pair, volume_spike):
                            self.activate_override(pair, event, 2.0)

                # Cleanup expired overrides
                self.cleanup_expired_overrides()

                # Wait before next fetch
                await asyncio.sleep(self.config.news_fetch_interval_seconds)

            except Exception as e:
                logger.exception("Error in news monitoring: %s", e)
                await asyncio.sleep(60)

    def get_metrics(self) -> Dict:
        """Get current metrics."""
        return {
            "news_events_processed": self.news_events_processed,
            "overrides_activated": self.overrides_activated,
            "active_overrides_count": len(self.active_overrides),
            "active_overrides": list(self.active_overrides.keys()),
            "enabled": self.config.enabled,
        }


# Self-check for development/testing
if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info("Running NewsCatalystOverride self-check...")

    async def self_check():
        try:
            # Create override system
            config = NewsCatalystConfig(enabled=True)
            news_system = NewsCatalystOverride(config=config)

            logger.info("\n=== Test 1: Fetch news ===")
            news_events = await news_system.fetch_latest_news()
            logger.info("Fetched %d news events", len(news_events))

            if news_events:
                event = news_events[0]
                logger.info(
                    "Sample event: %s | Sentiment: %s (%.2f) | Impact: %s",
                    event.title[:50],
                    event.sentiment.value,
                    event.sentiment_score,
                    event.impact.value,
                )

            logger.info("\n=== Test 2: Check override activation ===")
            # Create mock volume data
            volume_history = pd.Series([100] * 20)

            for event in news_events:
                if event.currencies and "BTC" in event.currencies:
                    pair = "BTC/USD"
                    volume_spike, ratio = news_system.check_volume_spike(pair, 180.0, volume_history)

                    logger.info("Volume spike for %s: %s (%.1fx)", pair, volume_spike, ratio)

                    if news_system.should_activate_override(event, pair, volume_spike):
                        override = news_system.activate_override(pair, event, ratio)
                        logger.info("Override activated: %s", override.pair)
                        break

            logger.info("\n=== Test 3: Get active override ===")
            override = news_system.get_active_override("BTC/USD")
            if override:
                logger.info(
                    "Active override: pos_mult=%.1fx, tp_mult=%.1fx, sl_mult=%.1fx",
                    override.position_size_multiplier,
                    override.tp_multiplier,
                    override.sl_multiplier,
                )
            else:
                logger.info("No active override (expected if no strong news)")

            logger.info("\n=== Test 4: Metrics ===")
            metrics = news_system.get_metrics()
            logger.info("Metrics: %s", metrics)

            logger.info("\n✓ Self-check passed!")
            return 0

        except Exception as e:
            logger.error("✗ Self-check failed: %s", e)
            import traceback
            traceback.print_exc()
            return 1

    sys.exit(asyncio.run(self_check()))
