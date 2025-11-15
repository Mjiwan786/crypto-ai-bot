"""
News Reactor Agent - Processes crypto news and generates trading signals.

This module monitors news feeds, performs sentiment analysis, and generates
actionable trading signals with confidence scores and decay rates.

Features:
- Real-time news monitoring and processing
- Sentiment analysis and keyword extraction
- Signal generation with confidence scoring
- Signal decay and expiration management
- Multi-source news aggregation
- Comprehensive error handling and logging
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Set

import aiohttp
from prometheus_client import Counter, Gauge, Histogram
from pydantic import BaseModel, Field


# Data models
class NewsSignal(BaseModel):
    """Trading signal derived from news analysis."""

    signal_id: str = Field(..., description="Unique signal identifier")
    symbol: str = Field(..., description="Affected trading symbol")
    sentiment: float = Field(..., description="Sentiment score -1 to 1", ge=-1, le=1)
    confidence: float = Field(..., description="Signal confidence 0-1", ge=0, le=1)
    direction: str = Field(
        ..., description="Signal direction", pattern="^(bullish|bearish|neutral)$"
    )
    strength: float = Field(..., description="Signal strength 0-1", ge=0, le=1)
    half_life: float = Field(..., description="Signal decay half-life in hours", gt=0)
    created_at: float = Field(..., description="Signal creation timestamp")
    expires_at: float = Field(..., description="Signal expiration timestamp")
    source_url: Optional[str] = Field(None, description="Source news URL")
    headline: str = Field(..., description="News headline")
    keywords: List[str] = Field(default_factory=list, description="Extracted keywords")


class NewsArticle(BaseModel):
    """Raw news article data."""

    title: str = Field(..., description="Article title")
    url: str = Field(..., description="Article URL")
    published_at: float = Field(..., description="Publication timestamp")
    source: str = Field(..., description="News source")
    content: Optional[str] = Field(None, description="Article content")
    symbols_mentioned: List[str] = Field(default_factory=list, description="Crypto symbols found")


class SentimentScore(BaseModel):
    """Sentiment analysis result."""

    score: float = Field(..., description="Sentiment score -1 to 1", ge=-1, le=1)
    magnitude: float = Field(..., description="Sentiment magnitude 0-1", ge=0, le=1)
    positive_words: List[str] = Field(default_factory=list, description="Positive keywords")
    negative_words: List[str] = Field(default_factory=list, description="Negative keywords")
    confidence: float = Field(..., description="Analysis confidence", ge=0, le=1)


# Minimal config fallback
class LocalConfigLoader:
    def __init__(self):
        self.data = {
            "news_reactor": {
                "sources": [
                    "https://cryptopanic.com/api/v1/posts/",
                    "https://feeds.feedburner.com/CoinDesk",
                ],
                "update_interval": 300,  # 5 minutes
                "max_articles_per_fetch": 50,
                "signal_decay_hours": 24,
                "min_confidence": 0.3,
            },
            "symbols": {
                "whitelist": ["BTC", "ETH", "SOL", "ADA", "DOT", "LINK", "UNI"],
                "aliases": {
                    "bitcoin": "BTC",
                    "ethereum": "ETH",
                    "solana": "SOL",
                    "cardano": "ADA",
                    "polkadot": "DOT",
                    "chainlink": "LINK",
                    "uniswap": "UNI",
                },
            },
        }


# Minimal MCP fallback
class LocalMCP:
    def __init__(self):
        self.kv = {}
        self.signals_cache = []

    async def publish(self, topic: str, payload: dict):
        logger = logging.getLogger(__name__)
        logger.info("[MCP] Published to %s: %s", topic, payload)
        if topic == "signals.news":
            self.signals_cache.extend(payload.get("signals", []))

    def get(self, key: str, default=None):
        return self.kv.get(key, default)

    def set(self, key: str, value):
        self.kv[key] = value


class SentimentAnalyzer:
    """Simple rule-based sentiment analyzer for crypto news."""

    def __init__(self):
        self.positive_words = {
            "bullish",
            "bull",
            "surge",
            "pump",
            "moon",
            "rally",
            "breakout",
            "breakthrough",
            "adoption",
            "partnership",
            "upgrade",
            "profit",
            "gain",
            "rise",
            "increase",
            "upward",
            "positive",
            "optimistic",
            "institutional",
            "investment",
            "backing",
            "support",
            "approval",
        }

        self.negative_words = {
            "bearish",
            "bear",
            "crash",
            "dump",
            "plunge",
            "correction",
            "decline",
            "drop",
            "fall",
            "loss",
            "hack",
            "scam",
            "regulation",
            "ban",
            "crackdown",
            "warning",
            "concern",
            "risk",
            "selloff",
            "liquidation",
            "fear",
            "uncertainty",
            "doubt",
            "bubble",
        }

        self.crypto_positive = {
            "defi",
            "nft",
            "web3",
            "blockchain",
            "smart contract",
            "staking",
            "yield",
            "airdrop",
            "listing",
            "mainnet",
            "testnet",
            "halving",
        }

        self.crypto_negative = {
            "rugpull",
            "exploit",
            "vulnerability",
            "fork",
            "delisting",
            "sec",
            "regulation",
            "ponzi",
            "bubble",
            "scam",
        }

    def analyze_sentiment(self, text: str) -> SentimentScore:
        """
        Analyze sentiment of text using keyword matching.

        Args:
            text: Text to analyze

        Returns:
            SentimentScore object
        """
        text_lower = text.lower()
        words = re.findall(r"\b\w+\b", text_lower)

        positive_matches = []
        negative_matches = []

        # Find positive words
        for word in words:
            if word in self.positive_words or word in self.crypto_positive:
                positive_matches.append(word)

        # Find negative words
        for word in words:
            if word in self.negative_words or word in self.crypto_negative:
                negative_matches.append(word)

        # Calculate scores
        pos_count = len(positive_matches)
        neg_count = len(negative_matches)
        total_words = len(words)

        if total_words == 0:
            return SentimentScore(
                score=0.0, magnitude=0.0, confidence=0.0, positive_words=[], negative_words=[]
            )

        # Normalize sentiment score
        sentiment_balance = (pos_count - neg_count) / max(1, total_words) * 10
        sentiment_score = max(-1.0, min(1.0, sentiment_balance))

        # Calculate magnitude (strength of sentiment)
        magnitude = min(1.0, (pos_count + neg_count) / max(1, total_words) * 5)

        # Confidence based on number of sentiment words found
        confidence = min(1.0, (pos_count + neg_count) / 10)

        return SentimentScore(
            score=sentiment_score,
            magnitude=magnitude,
            confidence=confidence,
            positive_words=positive_matches[:5],  # Top 5
            negative_words=negative_matches[:5],  # Top 5
        )


class NewsReactor:
    """
    Processes crypto news and generates trading signals.

    This agent monitors news feeds, performs sentiment analysis, and generates
    actionable trading signals with appropriate confidence and decay rates.
    """

    def __init__(self, mcp=None, redis=None, logger=None, **kwargs):
        """
        Initialize the News Reactor.

        Args:
            mcp: Model Context Protocol instance
            redis: Redis instance for caching
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

        self.news_config = self.config.get("news_reactor", {})
        self.symbol_config = self.config.get("symbols", {})

        self.sources = self.news_config.get("sources", [])
        self.update_interval = self.news_config.get("update_interval", 300)
        self.max_articles = self.news_config.get("max_articles_per_fetch", 50)
        self.signal_decay_hours = self.news_config.get("signal_decay_hours", 24)
        self.min_confidence = self.news_config.get("min_confidence", 0.3)

        # Symbol mapping
        self.symbol_whitelist = set(self.symbol_config.get("whitelist", ["BTC", "ETH"]))
        self.symbol_aliases = self.symbol_config.get("aliases", {})

        # Initialize sentiment analyzer
        self.sentiment_analyzer = SentimentAnalyzer()

        # Running state
        self.running = False
        self.session: Optional[aiohttp.ClientSession] = None

        # Cache for processed articles to avoid duplicates
        self.processed_articles: Set[str] = set()
        self.recent_signals: List[NewsSignal] = []

        # Metrics
        self.metrics = self._init_metrics()

        self.logger.info("NewsReactor initialized")

    def _init_metrics(self) -> Dict:
        """Initialize Prometheus metrics."""
        return {
            "articles_processed": Counter(
                "news_articles_processed_total",
                "Total news articles processed",
                ["source", "has_signals"],
            ),
            "signals_generated": Counter(
                "news_signals_generated_total",
                "Total trading signals generated",
                ["symbol", "direction"],
            ),
            "processing_duration": Histogram(
                "news_processing_duration_seconds", "Time spent processing news"
            ),
            "active_signals": Gauge("news_active_signals", "Currently active news signals"),
            "sentiment_distribution": Histogram(
                "news_sentiment_scores",
                "Distribution of sentiment scores",
                buckets=(-1, -0.5, -0.2, 0, 0.2, 0.5, 1, float("inf")),
            ),
        }

    def _extract_symbols(self, text: str) -> List[str]:
        """
        Extract crypto symbols from text.

        Args:
            text: Text to search for symbols

        Returns:
            List of found symbols
        """
        found_symbols = set()
        text_lower = text.lower()

        # Direct symbol matches
        for symbol in self.symbol_whitelist:
            if symbol.lower() in text_lower:
                found_symbols.add(symbol)

        # Alias matches
        for alias, symbol in self.symbol_aliases.items():
            if alias.lower() in text_lower:
                found_symbols.add(symbol)

        # Pattern matching for $SYMBOL format
        symbol_pattern = r"\$([A-Z]{2,5})"
        matches = re.findall(symbol_pattern, text.upper())
        for match in matches:
            if match in self.symbol_whitelist:
                found_symbols.add(match)

        return list(found_symbols)

    def _calculate_signal_strength(self, sentiment: SentimentScore, symbols: List[str]) -> float:
        """
        Calculate signal strength based on sentiment and context.

        Args:
            sentiment: Sentiment analysis result
            symbols: Affected symbols

        Returns:
            Signal strength between 0 and 1
        """
        base_strength = sentiment.magnitude * sentiment.confidence

        # Boost for major coins
        major_coins = {"BTC", "ETH"}
        if any(symbol in major_coins for symbol in symbols):
            base_strength *= 1.2

        # Boost for multiple symbols mentioned
        if len(symbols) > 1:
            base_strength *= 1.1

        return min(1.0, base_strength)

    def _create_news_signal(
        self, article: NewsArticle, sentiment: SentimentScore
    ) -> List[NewsSignal]:
        """
        Create trading signals from news article and sentiment.

        Args:
            article: News article
            sentiment: Sentiment analysis result

        Returns:
            List of NewsSignal objects
        """
        signals = []
        for symbol in self._extract_symbols(article.content):
            signal_strength = self._calculate_signal_strength(sentiment, [symbol])
            if signal_strength > 0:
                signals.append(
                    NewsSignal(
                        article_id=article.id,
                        symbol=symbol,
                        direction=sentiment.direction,
                        strength=signal_strength,
                    )
                )
        return signals


# =============================================================================
# NEWS OVERRIDE CONTROLLER
# =============================================================================


class NewsOverrideConfig(BaseModel):
    """Configuration for news-based trading overrides."""

    enabled: bool = Field(False, description="Enable news overrides")
    major_news_sentiment_threshold: float = Field(
        0.7, description="Sentiment threshold for major news", ge=0, le=1
    )
    max_size_multiplier: float = Field(
        1.5, description="Maximum size multiplier", ge=1.0, le=2.0
    )
    tp_extension_seconds: int = Field(
        30, description="Take-profit extension in seconds", ge=0, le=300
    )
    min_confidence_for_override: float = Field(
        0.6, description="Minimum signal confidence for override", ge=0, le=1
    )
    override_decay_seconds: int = Field(
        300, description="Override decay duration", ge=60, le=3600
    )
    max_concurrent_overrides: int = Field(
        3, description="Maximum concurrent overrides", ge=1, le=10
    )


class NewsOverride(BaseModel):
    """Active news-based override."""

    override_id: str = Field(..., description="Unique override ID")
    signal_id: str = Field(..., description="Associated news signal ID")
    symbol: str = Field(..., description="Affected symbol")
    size_multiplier: float = Field(..., description="Applied size multiplier", ge=1.0, le=1.5)
    tp_extension_seconds: int = Field(..., description="TP extension in seconds")
    sentiment: float = Field(..., description="News sentiment score")
    confidence: float = Field(..., description="Signal confidence")
    created_at: float = Field(..., description="Creation timestamp")
    expires_at: float = Field(..., description="Expiration timestamp")
    headline: str = Field(..., description="News headline")
    is_active: bool = Field(True, description="Override is active")


class NewsOverrideController:
    """
    Controls news-based trading overrides with safety limits.

    Features:
    - Temporary size multipliers (<= 1.5x) for major news
    - Take-profit extension for high-confidence signals
    - Trailing stop-loss in profit (never widen stops)
    - Feature flag control (NEWS_OVERRIDES_ENABLED)
    - Prometheus metrics and audit logging
    - Circuit breaker integration
    """

    def __init__(
        self,
        redis_manager=None,
        mcp=None,
        logger=None,
        config: Optional[NewsOverrideConfig] = None,
        metrics: Optional[Dict] = None,
    ):
        """
        Initialize NewsOverrideController.

        Args:
            redis_manager: Redis manager for state storage
            mcp: Model Context Protocol for messaging
            logger: Logger instance
            config: Override configuration
            metrics: Optional metrics dict (for testing)
        """
        self.redis = redis_manager
        self.mcp = mcp or LocalMCP()
        self.logger = logger or logging.getLogger(__name__)

        # Load configuration
        import os

        if config is None:
            # Feature flag from environment (default: False)
            enabled_from_env = os.getenv("NEWS_OVERRIDES_ENABLED", "false").lower() == "true"

            config = NewsOverrideConfig(
                enabled=enabled_from_env,
                major_news_sentiment_threshold=float(
                    os.getenv("NEWS_SENTIMENT_THRESHOLD", "0.7")
                ),
                max_size_multiplier=float(os.getenv("NEWS_MAX_SIZE_MULTIPLIER", "1.5")),
                tp_extension_seconds=int(os.getenv("NEWS_TP_EXTENSION_SECONDS", "30")),
            )

        self.config = config
        # Use config's enabled flag (allows tests to override)
        self.enabled = self.config.enabled

        # Active overrides cache
        self.active_overrides: Dict[str, NewsOverride] = {}

        # Metrics (allow injection for testing)
        self.metrics = metrics if metrics is not None else self._init_metrics()

        # Audit log
        self.audit_events: List[Dict] = []

        self.logger.info(
            f"NewsOverrideController initialized: enabled={self.enabled}, "
            f"sentiment_threshold={self.config.major_news_sentiment_threshold}, "
            f"max_multiplier={self.config.max_size_multiplier}x"
        )

    def _init_metrics(self) -> Dict:
        """Initialize Prometheus metrics for override tracking."""
        return {
            "overrides_created": Counter(
                "news_overrides_created_total",
                "Total news overrides created",
                ["symbol", "override_type"],
            ),
            "overrides_active": Gauge(
                "news_overrides_active", "Currently active news overrides"
            ),
            "overrides_expired": Counter(
                "news_overrides_expired_total",
                "Total news overrides expired",
                ["symbol"],
            ),
            "size_multiplier_applied": Histogram(
                "news_size_multiplier_applied",
                "Size multipliers applied by news overrides",
                buckets=(1.0, 1.1, 1.2, 1.3, 1.4, 1.5, float("inf")),
            ),
            "tp_extension_applied": Histogram(
                "news_tp_extension_seconds_applied",
                "TP extension seconds applied by news overrides",
                buckets=(0, 10, 20, 30, 60, 120, 300, float("inf")),
            ),
            "override_rejections": Counter(
                "news_override_rejections_total",
                "News overrides rejected",
                ["reason"],
            ),
        }

    def _audit_log(self, event_type: str, data: Dict):
        """
        Log override event for audit trail.

        Args:
            event_type: Type of event (created, expired, rejected, etc.)
            data: Event data
        """
        import time

        event = {
            "timestamp": time.time(),
            "event_type": event_type,
            "data": data,
        }

        self.audit_events.append(event)
        self.logger.info(f"[AUDIT] News Override {event_type}: {data}")

        # Publish to Redis if available
        if self.redis:
            try:
                self.redis.publish_event("news_override_audit", event)
            except Exception as e:
                self.logger.error(f"Failed to publish audit event: {e}")

    def check_major_news_detected(self, news_signal: NewsSignal) -> bool:
        """
        Check if news signal qualifies as major news.

        Args:
            news_signal: News signal to check

        Returns:
            True if major news detected
        """
        # Check sentiment threshold
        if abs(news_signal.sentiment) < self.config.major_news_sentiment_threshold:
            return False

        # Check confidence threshold
        if news_signal.confidence < self.config.min_confidence_for_override:
            return False

        # Check signal strength
        if news_signal.strength < 0.5:
            return False

        return True

    def calculate_size_multiplier(self, news_signal: NewsSignal) -> float:
        """
        Calculate size multiplier based on news signal strength.

        Args:
            news_signal: News signal

        Returns:
            Size multiplier between 1.0 and config.max_size_multiplier
        """
        # Base multiplier: 1.0
        # Scale up to max based on combined sentiment and confidence
        signal_strength = (
            abs(news_signal.sentiment) * news_signal.confidence * news_signal.strength
        )

        # Linear interpolation between 1.0 and max_size_multiplier
        multiplier = 1.0 + (self.config.max_size_multiplier - 1.0) * signal_strength

        # Clamp to valid range
        return max(1.0, min(self.config.max_size_multiplier, multiplier))

    def calculate_tp_extension(self, news_signal: NewsSignal) -> int:
        """
        Calculate take-profit extension based on news signal.

        Args:
            news_signal: News signal

        Returns:
            TP extension in seconds
        """
        # Scale extension based on signal confidence and strength
        signal_quality = news_signal.confidence * news_signal.strength

        extension = int(self.config.tp_extension_seconds * signal_quality)

        # Clamp to valid range
        return max(0, min(self.config.tp_extension_seconds, extension))

    def should_apply_override(
        self,
        news_signal: NewsSignal,
        current_position_size: float,
        circuit_breaker_active: bool = False,
    ) -> Tuple[bool, str]:
        """
        Determine if override should be applied.

        Args:
            news_signal: News signal to evaluate
            current_position_size: Current position size
            circuit_breaker_active: Circuit breaker status

        Returns:
            (should_apply, reason)
        """
        # Check if overrides are enabled
        if not self.enabled or not self.config.enabled:
            return False, "Overrides disabled by feature flag"

        # Check circuit breaker
        if circuit_breaker_active:
            self.metrics["override_rejections"].labels(reason="circuit_breaker").inc()
            self._audit_log(
                "override_rejected",
                {
                    "signal_id": news_signal.signal_id,
                    "reason": "circuit_breaker_active",
                },
            )
            return False, "Circuit breaker active - overrides blocked"

        # Check if major news detected
        if not self.check_major_news_detected(news_signal):
            self.metrics["override_rejections"].labels(reason="not_major_news").inc()
            return False, "News does not meet major news criteria"

        # Check max concurrent overrides
        active_count = len([o for o in self.active_overrides.values() if o.is_active])
        if active_count >= self.config.max_concurrent_overrides:
            self.metrics["override_rejections"].labels(
                reason="max_concurrent_limit"
            ).inc()
            self._audit_log(
                "override_rejected",
                {
                    "signal_id": news_signal.signal_id,
                    "reason": "max_concurrent_overrides_reached",
                    "active_count": active_count,
                },
            )
            return False, f"Max concurrent overrides reached ({active_count})"

        # Check if symbol already has active override
        existing_override = next(
            (
                o
                for o in self.active_overrides.values()
                if o.symbol == news_signal.symbol and o.is_active
            ),
            None,
        )

        if existing_override:
            self.metrics["override_rejections"].labels(
                reason="existing_override"
            ).inc()
            return False, f"Symbol {news_signal.symbol} already has active override"

        return True, "OK"

    def create_override(
        self, news_signal: NewsSignal, circuit_breaker_active: bool = False
    ) -> Optional[NewsOverride]:
        """
        Create news-based override if conditions are met.

        Args:
            news_signal: News signal triggering override
            circuit_breaker_active: Circuit breaker status

        Returns:
            NewsOverride if created, None otherwise
        """
        import time
        import uuid

        # Check if should apply
        should_apply, reason = self.should_apply_override(
            news_signal, 0.0, circuit_breaker_active
        )

        if not should_apply:
            self.logger.info(f"Override rejected: {reason}")
            return None

        # Calculate override parameters
        size_multiplier = self.calculate_size_multiplier(news_signal)
        tp_extension = self.calculate_tp_extension(news_signal)

        # Create override
        override = NewsOverride(
            override_id=str(uuid.uuid4()),
            signal_id=news_signal.signal_id,
            symbol=news_signal.symbol,
            size_multiplier=size_multiplier,
            tp_extension_seconds=tp_extension,
            sentiment=news_signal.sentiment,
            confidence=news_signal.confidence,
            created_at=time.time(),
            expires_at=time.time() + self.config.override_decay_seconds,
            headline=news_signal.headline,
            is_active=True,
        )

        # Store override
        self.active_overrides[override.override_id] = override

        # Update metrics
        self.metrics["overrides_created"].labels(
            symbol=override.symbol, override_type="size_and_tp"
        ).inc()
        self.metrics["overrides_active"].set(
            len([o for o in self.active_overrides.values() if o.is_active])
        )
        self.metrics["size_multiplier_applied"].observe(size_multiplier)
        self.metrics["tp_extension_applied"].observe(tp_extension)

        # Audit log
        self._audit_log(
            "override_created",
            {
                "override_id": override.override_id,
                "signal_id": news_signal.signal_id,
                "symbol": override.symbol,
                "size_multiplier": size_multiplier,
                "tp_extension_seconds": tp_extension,
                "sentiment": news_signal.sentiment,
                "confidence": news_signal.confidence,
                "headline": news_signal.headline,
            },
        )

        self.logger.info(
            f"Created news override: {override.symbol} "
            f"multiplier={size_multiplier:.2f}x, "
            f"tp_ext={tp_extension}s, "
            f"sentiment={news_signal.sentiment:.2f}"
        )

        return override

    def get_active_override(self, symbol: str) -> Optional[NewsOverride]:
        """
        Get active override for symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Active NewsOverride or None
        """
        import time

        current_time = time.time()

        # Clean up expired overrides
        self._cleanup_expired_overrides(current_time)

        # Find active override for symbol
        for override in self.active_overrides.values():
            if override.symbol == symbol and override.is_active:
                if override.expires_at > current_time:
                    return override
                else:
                    # Mark as expired
                    override.is_active = False

        return None

    def _cleanup_expired_overrides(self, current_time: float):
        """
        Clean up expired overrides.

        Args:
            current_time: Current timestamp
        """
        expired_overrides = []

        for override_id, override in self.active_overrides.items():
            if override.expires_at <= current_time and override.is_active:
                override.is_active = False
                expired_overrides.append(override_id)

                # Update metrics
                self.metrics["overrides_expired"].labels(symbol=override.symbol).inc()

                # Audit log
                self._audit_log(
                    "override_expired",
                    {
                        "override_id": override_id,
                        "symbol": override.symbol,
                        "duration_seconds": current_time - override.created_at,
                    },
                )

                self.logger.info(f"Override expired: {override.symbol} ({override_id})")

        # Update active count
        if expired_overrides:
            self.metrics["overrides_active"].set(
                len([o for o in self.active_overrides.values() if o.is_active])
            )

    def apply_size_override(
        self, base_size: float, symbol: str, circuit_breaker_active: bool = False
    ) -> Tuple[float, Optional[str]]:
        """
        Apply size multiplier if override is active.

        Args:
            base_size: Base position size
            symbol: Trading symbol
            circuit_breaker_active: Circuit breaker status

        Returns:
            (adjusted_size, override_id or None)
        """
        # If circuit breaker is active, don't apply overrides
        if circuit_breaker_active:
            return base_size, None

        # Get active override
        override = self.get_active_override(symbol)

        if override is None:
            return base_size, None

        # Apply multiplier
        adjusted_size = base_size * override.size_multiplier

        self.logger.info(
            f"Applied size override: {symbol} "
            f"{base_size:.2f} -> {adjusted_size:.2f} "
            f"(multiplier={override.size_multiplier:.2f}x)"
        )

        return adjusted_size, override.override_id

    def apply_tp_override(
        self, base_tp_seconds: int, symbol: str, circuit_breaker_active: bool = False
    ) -> Tuple[int, Optional[str]]:
        """
        Apply take-profit extension if override is active.

        Args:
            base_tp_seconds: Base TP duration
            symbol: Trading symbol
            circuit_breaker_active: Circuit breaker status

        Returns:
            (adjusted_tp_seconds, override_id or None)
        """
        # If circuit breaker is active, don't apply overrides
        if circuit_breaker_active:
            return base_tp_seconds, None

        # Get active override
        override = self.get_active_override(symbol)

        if override is None:
            return base_tp_seconds, None

        # Apply extension
        adjusted_tp = base_tp_seconds + override.tp_extension_seconds

        self.logger.info(
            f"Applied TP override: {symbol} "
            f"{base_tp_seconds}s -> {adjusted_tp}s "
            f"(extension={override.tp_extension_seconds}s)"
        )

        return adjusted_tp, override.override_id

    def should_trail_stop(
        self, symbol: str, entry_price: float, current_price: float, side: str
    ) -> bool:
        """
        Determine if stop should trail (only in profit).

        SAFETY: Never widens stops, only trails in profit.

        Args:
            symbol: Trading symbol
            entry_price: Entry price
            current_price: Current price
            side: Trade side (long/short)

        Returns:
            True if should trail stop
        """
        override = self.get_active_override(symbol)

        if override is None:
            return False

        # Check if in profit
        if side == "long":
            in_profit = current_price > entry_price
        else:  # short
            in_profit = current_price < entry_price

        # Only trail if in profit
        if in_profit:
            self.logger.debug(f"Trailing stop enabled for {symbol} (in profit)")
            return True

        return False

    def _get_metric_value(self, metric) -> int:
        """
        Get value from metric (handles both real Prometheus and mock metrics).

        Args:
            metric: Prometheus metric or mock metric

        Returns:
            Metric value as int
        """
        # For mock metrics (testing), _value is directly an int
        if hasattr(metric, "_value") and isinstance(metric._value, int):
            return metric._value
        # For real Prometheus metrics, would need to access _metric or similar
        # For now, just return 0 for real metrics (not implemented)
        return 0

    def get_override_summary(self) -> Dict:
        """
        Get summary of active overrides.

        Returns:
            Override summary dict
        """
        import time

        current_time = time.time()
        self._cleanup_expired_overrides(current_time)

        active_overrides = [o for o in self.active_overrides.values() if o.is_active]

        return {
            "enabled": self.enabled and self.config.enabled,
            "active_count": len(active_overrides),
            "max_concurrent": self.config.max_concurrent_overrides,
            "active_overrides": [
                {
                    "symbol": o.symbol,
                    "size_multiplier": o.size_multiplier,
                    "tp_extension_seconds": o.tp_extension_seconds,
                    "sentiment": o.sentiment,
                    "confidence": o.confidence,
                    "time_remaining_seconds": max(0, int(o.expires_at - current_time)),
                    "headline": o.headline,
                }
                for o in active_overrides
            ],
            "total_created": self._get_metric_value(self.metrics["overrides_created"]),
            "total_expired": self._get_metric_value(self.metrics["overrides_expired"]),
        }

    def disable_all_overrides(self, reason: str):
        """
        Emergency disable all active overrides.

        Args:
            reason: Reason for disabling
        """
        import time

        current_time = time.time()

        for override in self.active_overrides.values():
            if override.is_active:
                override.is_active = False

                # Audit log
                self._audit_log(
                    "override_disabled",
                    {
                        "override_id": override.override_id,
                        "symbol": override.symbol,
                        "reason": reason,
                    },
                )

        # Update metrics
        self.metrics["overrides_active"].set(0)

        self.logger.warning(f"Disabled all news overrides: {reason}")

    def get_audit_log(self, limit: int = 100) -> List[Dict]:
        """
        Get recent audit log events.

        Args:
            limit: Maximum number of events to return

        Returns:
            List of audit events
        """
        return self.audit_events[-limit:]
