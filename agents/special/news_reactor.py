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
