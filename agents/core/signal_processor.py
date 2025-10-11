"""
Signal Processor Agent for Crypto AI Bot

Processes and routes signals from the AI-driven signal_analyst.py.
Handles execution preparation, filtering, and Redis stream management.
Works alongside your existing signal_analyst.py with AI fusion.

This module provides:
- Signal processing and enhancement with AI integration
- Quality assessment and confidence scoring
- Signal routing and stream management
- Execution preparation and validation
- Real-time monitoring and diagnostics
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import redis.asyncio as redis
from dotenv import load_dotenv

from agents.core.errors import ConfigError, RedisError

# Import your existing AI engine components
try:
    from strategies.regime_based_router import MarketContext

    AI_ENGINE_AVAILABLE = True
except ImportError:
    AI_ENGINE_AVAILABLE = False
    logging.warning("AI Engine not available, running in basic mode")

# Defer dotenv loading - will be called explicitly in initialization
def _load_env():
    """Load environment variables - call this explicitly in __init__ or startup."""
    load_dotenv()

# Setup logging
logger = logging.getLogger(__name__)


class SignalAction(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    CLOSE_LONG = "close_long"
    CLOSE_SHORT = "close_short"
    SCALP_ENTRY = "scalp_entry"
    SCALP_EXIT = "scalp_exit"


class ExecutionUrgency(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class SignalQuality(str, Enum):
    POOR = "poor"
    FAIR = "fair"
    GOOD = "good"
    EXCELLENT = "excellent"


@dataclass
class ProcessedSignal:
    """Enhanced signal ready for execution"""

    signal_id: str
    timestamp: float
    pair: str
    action: SignalAction
    quality: SignalQuality
    urgency: ExecutionUrgency

    # AI-driven metrics from your signal_analyst
    unified_signal: float  # 0-1 score from your AI fusion
    regime_state: str
    confidence: float

    # Market context from AI analysis
    market_context: Dict[str, Any]
    ta_analysis: Dict[str, Any]
    sentiment_analysis: Dict[str, Any]
    macro_analysis: Dict[str, Any]

    # Strategy routing
    target_strategy: str

    # Execution parameters
    price: float
    quantity: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    max_slippage_bps: float = 10.0

    # Priority and risk metrics
    priority: int = 5  # 1-10 scale
    risk_score: float = 0.5
    position_size_pct: float = 0.02

    def to_execution_order(self) -> Dict[str, Any]:
        """Convert to execution order format"""
        return {
            "signal_id": self.signal_id,
            "timestamp": self.timestamp,
            "pair": self.pair,
            "action": self.action.value,
            "price": self.price,
            "quantity": self.quantity,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "max_slippage_bps": self.max_slippage_bps,
            "strategy": self.target_strategy,
            "priority": self.priority,
            "ai_confidence": self.confidence,
            "unified_signal": self.unified_signal,
            "regime": self.regime_state,
            "urgency": self.urgency.value,
            "quality": self.quality.value,
        }


class SignalQualityAssessor:
    """Assess signal quality based on AI analysis"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.SignalQualityAssessor")

    def assess_quality(
        self, market_context: MarketContext, unified_signal: float
    ) -> Tuple[SignalQuality, float]:
        """
        Assess signal quality based on AI analysis
        Returns: (quality, confidence_adjustment)
        """
        try:
            quality_score = 0.0
            confidence_multiplier = 1.0

            # Factor 1: Unified signal strength (from your AI fusion)
            signal_strength = abs(unified_signal - 0.5) * 2  # 0-1 scale
            quality_score += signal_strength * 0.4

            # Factor 2: Regime consistency
            regime_quality = self._assess_regime_quality(market_context)
            quality_score += regime_quality * 0.25

            # Factor 3: Technical alignment
            ta_quality = self._assess_ta_quality(market_context)
            quality_score += ta_quality * 0.20

            # Factor 4: Sentiment-macro alignment
            fundamental_quality = self._assess_fundamental_quality(market_context)
            quality_score += fundamental_quality * 0.15

            # Map to quality enum
            if quality_score >= 0.8:
                quality = SignalQuality.EXCELLENT
                confidence_multiplier = 1.2
            elif quality_score >= 0.65:
                quality = SignalQuality.GOOD
                confidence_multiplier = 1.1
            elif quality_score >= 0.45:
                quality = SignalQuality.FAIR
                confidence_multiplier = 1.0
            else:
                quality = SignalQuality.POOR
                confidence_multiplier = 0.8

            return quality, confidence_multiplier

        except Exception as e:
            self.logger.error(f"Error assessing signal quality: {e}")
            return SignalQuality.FAIR, 1.0

    def _assess_regime_quality(self, context: MarketContext) -> float:
        """Assess how well-defined the current regime is"""
        try:
            # Strong trending regime = good for trend signals
            if context.regime_state in ["strong_uptrend", "strong_downtrend"]:
                trend_strength = context.trend_strength or 0.0
                return min(1.0, trend_strength + 0.3)

            # Ranging regime = good for mean reversion
            elif context.regime_state in ["sideways", "consolidation"]:
                bb_width = context.bb_width or 0.0
                # Lower BB width = better defined range
                return max(0.3, 1.0 - bb_width)

            # Volatile regime = lower quality for most strategies
            elif context.regime_state == "volatile":
                return 0.4

            return 0.6  # Neutral regime

        except Exception:
            return 0.5

    def _assess_ta_quality(self, context: MarketContext) -> float:
        """Assess technical analysis signal quality"""
        try:
            quality = 0.5

            # RSI not in extreme overbought/oversold (unless that's the strategy)
            if context.rsi is not None:
                if 30 < context.rsi < 70:
                    quality += 0.2
                elif context.rsi < 20 or context.rsi > 80:
                    quality += 0.3  # Extreme levels can be good for reversals

            # MACD alignment
            if context.macd is not None and context.macd_signal is not None:
                macd_diff = abs(context.macd - context.macd_signal)
                if macd_diff > 0.001:  # Clear MACD signal
                    quality += 0.3

            return min(1.0, quality)

        except Exception:
            return 0.5

    def _assess_fundamental_quality(self, context: MarketContext) -> float:
        """Assess sentiment and macro alignment"""
        try:
            quality = 0.5

            # Strong sentiment signals
            if context.sentiment_score is not None:
                sentiment_strength = abs(context.sentiment_score)
                if sentiment_strength > 0.3:
                    quality += 0.3

            # Macro signal alignment
            if context.macro_signal is not None:
                macro_strength = abs(context.macro_signal)
                if macro_strength > 0.2:
                    quality += 0.2

            return min(1.0, quality)

        except Exception:
            return 0.5


class SignalRouter:
    """Route signals to appropriate strategies and execution streams"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.SignalRouter")

        # Strategy mappings from your config
        self.strategy_mappings = {
            "strong_uptrend": ["trend_following", "momentum"],
            "strong_downtrend": ["trend_following", "momentum"],
            "sideways": ["sideways", "mean_reversion"],
            "consolidation": ["sideways", "scalp"],
            "volatile": ["breakout"],
            "calm": ["scalp", "mean_reversion"],
        }

        # Stream mappings
        self.execution_streams = {
            "scalp": "signals:scalp",
            "trend_following": "signals:trend",
            "sideways": "signals:sideways",
            "momentum": "signals:momentum",
            "breakout": "signals:breakout",
            "default": os.getenv("STREAM_SIGNALS_PAPER", "signals:paper"),
        }

    def route_signal(self, processed_signal: ProcessedSignal) -> List[str]:
        """
        Route signal to appropriate execution streams
        Returns list of stream names
        """
        try:
            streams = []
            regime = processed_signal.regime_state

            # Get target strategies for this regime
            target_strategies = self.strategy_mappings.get(regime, ["default"])

            # Add strategy-specific streams
            for strategy in target_strategies:
                if strategy in self.execution_streams:
                    streams.append(self.execution_streams[strategy])

            # Always add to main signal stream
            streams.append(self.execution_streams["default"])

            # High priority signals go to priority stream
            if processed_signal.priority >= 8:
                streams.append("signals:priority")

            # Scalp signals get special routing
            if processed_signal.action in [SignalAction.SCALP_ENTRY, SignalAction.SCALP_EXIT]:
                streams.append("signals:scalp")

            return list(set(streams))  # Remove duplicates

        except Exception as e:
            self.logger.error(f"Error routing signal: {e}")
            return [self.execution_streams["default"]]


class SignalProcessor:
    """Main Signal Processor Agent"""

    def __init__(self, config_path: str = "config/settings.yaml"):
        self.logger = logging.getLogger(__name__)

        # Load environment variables
        _load_env()

        # Load configuration
        self.config = self._load_config()

        # Initialize components
        self.quality_assessor = SignalQualityAssessor(self.config)
        self.signal_router = SignalRouter(self.config)

        # Redis connection
        self.redis_client: Optional[redis.Redis] = None

        # State management
        self.running = False
        self.last_market_context: Optional[MarketContext] = None

        # Performance tracking
        self.stats = {
            "signals_processed": 0,
            "signals_routed": 0,
            "signals_filtered": 0,
            "quality_upgrades": 0,
            "quality_downgrades": 0,
            "errors": 0,
            "start_time": time.time(),
        }

        # Signal processing strategies
        self.signal_generators = {
            "ai_fusion": self._process_ai_fusion_signal,
            "regime_change": self._process_regime_change_signal,
            "quality_threshold": self._process_quality_threshold_signal,
        }

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from environment"""
        config = {
            # Redis configuration
            "redis_url": os.getenv("REDIS_URL"),
            "redis_streams": {
                "market_context": "ai:market_context",
                "raw_signals": "signals:raw",
                "processed_signals": os.getenv("STREAM_SIGNALS_PAPER", "signals:paper"),
                "regime_updates": "ai:regime",
            },
            # Signal processing parameters
            "processing": {
                "min_confidence": float(os.getenv("MIN_CONFIDENCE", "0.7")),
                "min_unified_signal": 0.55,  # Threshold for unified AI signal
                "quality_boost_threshold": 0.8,
                "max_signals_per_minute": int(os.getenv("MAX_SIGNALS_PER_MINUTE", "10")),
                "regime_change_sensitivity": 0.1,
            },
            # Position sizing
            "position_sizing": {
                "base_size_pct": float(os.getenv("BASE_POSITION_SIZE", "0.08")),
                "max_size_pct": float(os.getenv("MAX_POSITION_SIZE", "0.25")),
                "scalp_size_pct": float(os.getenv("SCALP_POSITION_SIZE", "0.02")),
                "quality_multiplier": True,
            },
            # Strategy allocations (your existing config)
            "strategy_allocations": {
                "trend_following": float(os.getenv("ALLOCATION_TREND_FOLLOWING", "0.5")),
                "sideways": float(os.getenv("ALLOCATION_SIDEWAYS", "0.3")),
                "scalp": float(os.getenv("ALLOCATION_SCALP", "0.2")),
            },
            # Trading pairs and timeframes
            "trading_pairs": os.getenv("TRADING_PAIRS", "BTC/USD,ETH/USD,SOL/USD,ADA/USD").split(
                ","
            ),
            "timeframes": os.getenv("TIMEFRAMES", "1m,3m,5m").split(","),
            # AI fusion weights (for your signal_analyst.py)
            "ai_weights": {
                "ta": float(os.getenv("AI_WEIGHT_TA", "0.55")),
                "sentiment": float(os.getenv("AI_WEIGHT_SENTIMENT", "0.25")),
                "macro": float(os.getenv("AI_WEIGHT_MACRO", "0.20")),
            },
            # Risk management
            "risk": {
                "max_daily_signals": int(os.getenv("MAX_DAILY_SIGNALS", "50")),
                "cooldown_after_loss": int(os.getenv("SIGNAL_COOLDOWN_SECONDS", "300")),
                "max_concurrent_signals": int(os.getenv("MAX_CONCURRENT_SIGNALS", "3")),
            },
        }

        self.logger.info("Signal Processor configuration loaded")
        return config

    async def initialize(self):
        """Initialize the Signal Processor.

        Raises:
            RedisError: If Redis connection fails
            ConfigError: If configuration is invalid
        """
        try:
            # Initialize Redis connection
            await self._init_redis()

            # Load any cached market context
            await self._load_market_context()

            self.logger.info("Signal Processor initialized successfully")

        except (RedisError, ConfigError):
            # Re-raise known errors
            raise
        except Exception as e:
            # Wrap unexpected initialization errors
            raise ConfigError(
                f"Failed to initialize Signal Processor: {e}",
                config_key="initialization",
                details={"original_error": str(e)},
            ) from e

    async def _init_redis(self):
        """Initialize Redis connection.

        Raises:
            ConfigError: If Redis URL is not configured
            RedisError: If Redis connection fails
        """
        if not self.config["redis_url"]:
            raise ConfigError(
                "Redis URL not configured",
                config_key="redis_url",
                details={"env_var": "REDIS_URL"},
            )

        try:
            # Use the specific Redis Cloud format
            if "redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com" in self.config["redis_url"]:
                self.redis_client = redis.Redis(
                    host="redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com",
                    port=19818,
                    username="default",
                    password="inwjuBWkh4rAtGnbQkLBuPkHXSmfokn8",
                    ssl=True,
                    ssl_cert_reqs="required",
                    decode_responses=False,
                    socket_timeout=30,
                    socket_keepalive=True,
                    socket_keepalive_options={
                        "TCP_KEEPIDLE": 1,
                        "TCP_KEEPINTVL": 3,
                        "TCP_KEEPCNT": 5,
                    },
                )
            else:
                self.redis_client = redis.from_url(
                    self.config["redis_url"],
                    socket_timeout=30,
                    socket_keepalive=True,
                    decode_responses=False,
                )

            # Test connection
            await self.redis_client.ping()
            self.logger.info("Redis connection established")

        except redis.ConnectionError as e:
            raise RedisError(
                f"Redis connection failed: {e}",
                operation="connect",
                details={"redis_url": self.config["redis_url"], "original_error": str(e)},
            ) from e
        except Exception as e:
            raise RedisError(
                f"Redis initialization error: {e}",
                operation="initialize",
                details={"original_error": str(e)},
            ) from e

    async def _load_market_context(self):
        """Load latest market context from AI engine"""
        try:
            if self.redis_client:
                context_stream = self.config["redis_streams"]["market_context"]
                messages = await self.redis_client.xrevrange(context_stream, count=1)

                if messages:
                    latest_message = messages[0]
                    context_data = latest_message[1]

                    # Reconstruct MarketContext if AI engine is available
                    if AI_ENGINE_AVAILABLE:
                        # This would reconstruct your MarketContext object
                        self.last_market_context = self._deserialize_market_context(context_data)
                        self.logger.info(
                            f"Loaded market context: regime={self.last_market_context.regime_state}"
                        )

        except Exception as e:
            self.logger.warning(f"Could not load market context: {e}")

    def _deserialize_market_context(self, data: Dict[bytes, bytes]) -> MarketContext:
        """Reconstruct MarketContext from Redis data"""
        try:
            return MarketContext(
                rsi=float(data.get(b"rsi", b"0")) if data.get(b"rsi") != b"None" else None,
                macd=float(data.get(b"macd", b"0")) if data.get(b"macd") != b"None" else None,
                macd_signal=(
                    float(data.get(b"macd_signal", b"0"))
                    if data.get(b"macd_signal") != b"None"
                    else None
                ),
                bb_width=float(data.get(b"bb_width", b"0")),
                trend_strength=float(data.get(b"trend_strength", b"0")),
                sentiment_score=float(data.get(b"sentiment_score", b"0")),
                sentiment_trend=data.get(b"sentiment_trend", b"neutral").decode("utf-8"),
                macro_signal=float(data.get(b"macro_signal", b"0")),
                macro_notes=json.loads(data.get(b"macro_notes", b"{}").decode("utf-8")),
                unified_signal=float(data.get(b"unified_signal", b"0.5")),
                regime_state=data.get(b"regime_state", b"uncertain").decode("utf-8"),
                meta=json.loads(data.get(b"meta", b"{}").decode("utf-8")),
            )
        except Exception as e:
            self.logger.error(f"Error deserializing market context: {e}")
            # Return default context
            return MarketContext(
                unified_signal=0.5,
                regime_state="uncertain",
                sentiment_score=0.0,
                sentiment_trend="neutral",
                macro_signal=0.0,
                macro_notes={},
                meta={},
            )

    async def start(self):
        """Start the Signal Processor agent"""
        self.running = True
        self.logger.info("Starting Signal Processor agent...")

        try:
            # Start processing tasks
            tasks = [
                asyncio.create_task(self._process_market_context_updates()),
                asyncio.create_task(self._process_raw_signals()),
                asyncio.create_task(self._generate_ai_fusion_signals()),
                asyncio.create_task(self._monitor_performance()),
            ]

            await asyncio.gather(*tasks, return_exceptions=True)

        except Exception as e:
            self.logger.error(f"Error in Signal Processor main loop: {e}")
            self.stats["errors"] += 1
        finally:
            await self.stop()

    async def stop(self):
        """Stop the Signal Processor agent"""
        self.logger.info("Stopping Signal Processor agent...")
        self.running = False

        if self.redis_client:
            await self.redis_client.aclose()

        # Log final statistics
        uptime = time.time() - self.stats["start_time"]
        self.logger.info(
            f"Signal Processor stopped. Stats: "
            f"Processed: {self.stats['signals_processed']}, "
            f"Routed: {self.stats['signals_routed']}, "
            f"Filtered: {self.stats['signals_filtered']}, "
            f"Errors: {self.stats['errors']}, "
            f"Uptime: {uptime:.1f}s"
        )

    async def _process_market_context_updates(self):
        """Process market context updates from your AI signal_analyst"""
        context_stream = self.config["redis_streams"]["market_context"]
        consumer_group = "signal_processor_context_grp"
        consumer_name = "processor-context-1"

        try:
            # Create consumer group
            try:
                await self.redis_client.xgroup_create(
                    context_stream, consumer_group, id="0", mkstream=True
                )
            except redis.ResponseError:
                pass

            self.logger.info(f"Processing market context from: {context_stream}")

            while self.running:
                try:
                    messages = await self.redis_client.xreadgroup(
                        consumer_group, consumer_name, {context_stream: ">"}, count=1, block=2000
                    )

                    for stream_name, stream_messages in messages:
                        for message_id, fields in stream_messages:
                            await self._update_market_context(fields)

                            # Acknowledge message
                            await self.redis_client.xack(context_stream, consumer_group, message_id)

                except redis.ConnectionError:
                    self.logger.error("Redis connection lost in context processor")
                    await asyncio.sleep(5)
                    await self._init_redis()

                except Exception as e:
                    self.logger.error(f"Error processing market context: {e}")
                    await asyncio.sleep(1)

        except Exception as e:
            self.logger.error(f"Fatal error in market context processing: {e}")

    async def _update_market_context(self, fields: Dict[bytes, bytes]):
        """Update market context from AI analysis"""
        try:
            if AI_ENGINE_AVAILABLE:
                new_context = self._deserialize_market_context(fields)

                # Check for significant regime change
                if (
                    self.last_market_context
                    and new_context.regime_state != self.last_market_context.regime_state
                ):

                    await self._handle_regime_change(
                        self.last_market_context.regime_state, new_context.regime_state, new_context
                    )

                self.last_market_context = new_context

                # Generate signals based on context update
                await self._process_context_based_signals(new_context)

        except Exception as e:
            self.logger.error(f"Error updating market context: {e}")

    async def _handle_regime_change(self, old_regime: str, new_regime: str, context: MarketContext):
        """Handle significant regime changes"""
        try:
            self.logger.info(f"Regime change detected: {old_regime} -> {new_regime}")

            # Generate regime change signal
            regime_signal = ProcessedSignal(
                signal_id=f"regime_change_{int(time.time())}",
                timestamp=time.time(),
                pair="ALL",  # Affects all pairs
                action=SignalAction.HOLD,  # Pause for regime transition
                quality=SignalQuality.GOOD,
                urgency=ExecutionUrgency.HIGH,
                unified_signal=context.unified_signal,
                regime_state=new_regime,
                confidence=0.8,
                market_context={
                    "regime_change": {
                        "from": old_regime,
                        "to": new_regime,
                        "unified_signal": context.unified_signal,
                    }
                },
                ta_analysis={"regime_transition": True},
                sentiment_analysis={"regime_change_impact": context.sentiment_score},
                macro_analysis={"regime_shift": context.macro_signal},
                price=0.0,  # Not applicable for regime signals
                quantity=0.0,
                target_strategy="regime_management",
            )

            # Route to all strategy streams
            await self._route_and_send_signal(regime_signal)

        except Exception as e:
            self.logger.error(f"Error handling regime change: {e}")

    async def _process_raw_signals(self):
        """Process raw signals from other components"""
        raw_stream = self.config["redis_streams"]["raw_signals"]
        consumer_group = "signal_processor_raw_grp"
        consumer_name = "processor-raw-1"

        try:
            # Create consumer group
            try:
                await self.redis_client.xgroup_create(
                    raw_stream, consumer_group, id="0", mkstream=True
                )
            except redis.ResponseError:
                pass

            self.logger.info(f"Processing raw signals from: {raw_stream}")

            while self.running:
                try:
                    messages = await self.redis_client.xreadgroup(
                        consumer_group, consumer_name, {raw_stream: ">"}, count=5, block=1000
                    )

                    for stream_name, stream_messages in messages:
                        for message_id, fields in stream_messages:
                            await self._process_raw_signal(message_id, fields)

                            # Acknowledge message
                            await self.redis_client.xack(raw_stream, consumer_group, message_id)

                except redis.ConnectionError:
                    self.logger.error("Redis connection lost in raw signal processor")
                    await asyncio.sleep(5)
                    await self._init_redis()

                except Exception as e:
                    self.logger.error(f"Error processing raw signals: {e}")
                    await asyncio.sleep(1)

        except Exception as e:
            self.logger.error(f"Fatal error in raw signal processing: {e}")

    async def _process_raw_signal(self, message_id: str, fields: Dict[bytes, bytes]):
        """Process individual raw signal"""
        try:
            # Parse raw signal data
            signal_data = {
                "pair": fields.get(b"pair", b"").decode("utf-8"),
                "action": fields.get(b"action", b"hold").decode("utf-8"),
                "price": float(fields.get(b"price", b"0")),
                "confidence": float(fields.get(b"confidence", b"0.5")),
                "strategy": fields.get(b"strategy", b"unknown").decode("utf-8"),
                "timeframe": fields.get(b"timeframe", b"1m").decode("utf-8"),
            }

            # Skip if no market context available
            if not self.last_market_context:
                self.logger.debug("No market context available, skipping signal")
                return

            # Enhance raw signal with AI context
            processed_signal = await self._enhance_raw_signal(signal_data, self.last_market_context)

            if processed_signal:
                await self._route_and_send_signal(processed_signal)
                self.stats["signals_processed"] += 1
            else:
                self.stats["signals_filtered"] += 1

        except Exception as e:
            self.logger.error(f"Error processing raw signal {message_id}: {e}")
            self.stats["errors"] += 1

    async def _enhance_raw_signal(
        self, signal_data: Dict[str, Any], context: MarketContext
    ) -> Optional[ProcessedSignal]:
        """Enhance raw signal with AI analysis"""
        try:
            # Apply quality assessment
            quality, confidence_adj = self.quality_assessor.assess_quality(
                context, context.unified_signal
            )

            # Filter low quality signals
            adjusted_confidence = signal_data["confidence"] * confidence_adj
            if adjusted_confidence < self.config["processing"]["min_confidence"]:
                return None

            # Map action string to enum
            try:
                action = SignalAction(signal_data["action"].lower())
            except ValueError:
                action = SignalAction.HOLD

            # Determine urgency based on unified signal strength
            signal_strength = abs(context.unified_signal - 0.5) * 2
            if signal_strength > 0.8:
                urgency = ExecutionUrgency.CRITICAL
            elif signal_strength > 0.6:
                urgency = ExecutionUrgency.HIGH
            elif signal_strength > 0.4:
                urgency = ExecutionUrgency.NORMAL
            else:
                urgency = ExecutionUrgency.LOW

            # Calculate position size
            base_size = self.config["position_sizing"]["base_size_pct"]
            if signal_data["strategy"] == "scalp":
                position_size = self.config["position_sizing"]["scalp_size_pct"]
            else:
                strategy_allocation = self.config["strategy_allocations"].get(
                    signal_data["strategy"], 0.5
                )
                position_size = base_size * strategy_allocation

                # Adjust for quality
                if self.config["position_sizing"]["quality_multiplier"]:
                    if quality == SignalQuality.EXCELLENT:
                        position_size *= 1.2
                    elif quality == SignalQuality.POOR:
                        position_size *= 0.7

            # Create processed signal
            processed_signal = ProcessedSignal(
                signal_id=f"proc_{signal_data['pair']}_{int(time.time() * 1000)}",
                timestamp=time.time(),
                pair=signal_data["pair"],
                action=action,
                quality=quality,
                urgency=urgency,
                unified_signal=context.unified_signal,
                regime_state=context.regime_state,
                confidence=adjusted_confidence,
                market_context={
                    "regime": context.regime_state,
                    "unified_signal": context.unified_signal,
                    "sentiment_score": context.sentiment_score,
                    "macro_signal": context.macro_signal,
                    "timeframe": signal_data["timeframe"],
                },
                ta_analysis={
                    "rsi": context.rsi,
                    "macd": context.macd,
                    "macd_signal": context.macd_signal,
                    "bb_width": context.bb_width,
                    "trend_strength": context.trend_strength,
                },
                sentiment_analysis={
                    "score": context.sentiment_score,
                    "trend": context.sentiment_trend,
                },
                macro_analysis={"signal": context.macro_signal, "notes": context.macro_notes},
                price=signal_data["price"],
                quantity=position_size,
                target_strategy=signal_data["strategy"],
                position_size_pct=position_size,
                priority=self._calculate_priority(context, quality, urgency),
            )

            # Add stop loss and take profit based on strategy
            self._add_risk_parameters(processed_signal, context)

            return processed_signal

        except Exception as e:
            self.logger.error(f"Error enhancing raw signal: {e}")
            return None

    def _calculate_priority(
        self, context: MarketContext, quality: SignalQuality, urgency: ExecutionUrgency
    ) -> int:
        """Calculate signal priority (1-10)"""
        priority = 5  # Base priority

        # Quality adjustment
        if quality == SignalQuality.EXCELLENT:
            priority += 2
        elif quality == SignalQuality.GOOD:
            priority += 1
        elif quality == SignalQuality.POOR:
            priority -= 2

        # Urgency adjustment
        if urgency == ExecutionUrgency.CRITICAL:
            priority += 3
        elif urgency == ExecutionUrgency.HIGH:
            priority += 2
        elif urgency == ExecutionUrgency.LOW:
            priority -= 1

        # Unified signal strength adjustment
        signal_strength = abs(context.unified_signal - 0.5) * 2
        if signal_strength > 0.8:
            priority += 1

        return max(1, min(10, priority))

    def _add_risk_parameters(self, signal: ProcessedSignal, context: MarketContext):
        """Add stop loss and take profit based on strategy and market conditions"""
        try:
            price = signal.price

            # Base risk parameters from config
            if signal.target_strategy == "scalp":
                # Tight stops for scalping
                stop_pct = 0.005  # 0.5%
                tp_pct = 0.01  # 1.0%
                signal.max_slippage_bps = 5.0
            elif signal.target_strategy == "trend_following":
                # Wider stops for trend following
                stop_pct = 0.02  # 2.0%
                tp_pct = 0.04  # 4.0%
                signal.max_slippage_bps = 15.0
            elif signal.target_strategy == "sideways":
                # Medium stops for range trading
                stop_pct = 0.015  # 1.5%
                tp_pct = 0.025  # 2.5%
                signal.max_slippage_bps = 10.0
            else:
                # Default parameters
                stop_pct = 0.015
                tp_pct = 0.03
                signal.max_slippage_bps = 10.0

            # Adjust for volatility (using BB width as proxy)
            if context.bb_width and context.bb_width > 0.02:  # High volatility
                stop_pct *= 1.5
                tp_pct *= 1.3
                signal.max_slippage_bps *= 1.5
            elif context.bb_width and context.bb_width < 0.01:  # Low volatility
                stop_pct *= 0.8
                tp_pct *= 0.9
                signal.max_slippage_bps *= 0.8

            # Set stop loss and take profit based on action
            if signal.action in [SignalAction.BUY, SignalAction.SCALP_ENTRY]:
                signal.stop_loss = price * (1 - stop_pct)
                signal.take_profit = price * (1 + tp_pct)
            elif signal.action in [SignalAction.SELL]:
                signal.stop_loss = price * (1 + stop_pct)
                signal.take_profit = price * (1 - tp_pct)

            # Calculate risk score
            signal.risk_score = min(1.0, stop_pct * 10 + (context.bb_width or 0.02) * 5)

        except Exception as e:
            self.logger.error(f"Error adding risk parameters: {e}")

    async def _generate_ai_fusion_signals(self):
        """Generate signals based on AI fusion analysis"""

        while self.running:
            try:
                # Only generate if we have market context
                if not self.last_market_context:
                    await asyncio.sleep(10)
                    continue

                # Check if unified signal is strong enough
                if (
                    abs(self.last_market_context.unified_signal - 0.5)
                    > self.config["processing"]["min_unified_signal"] - 0.5
                ):

                    # Generate AI fusion signals for each trading pair
                    for pair in self.config["trading_pairs"]:
                        signal = await self._generate_ai_signal_for_pair(pair)
                        if signal:
                            await self._route_and_send_signal(signal)

                # Wait before next generation cycle
                await asyncio.sleep(30)  # Generate every 30 seconds

            except Exception as e:
                self.logger.error(f"Error in AI fusion signal generation: {e}")
                await asyncio.sleep(10)

    async def _generate_ai_signal_for_pair(self, pair: str) -> Optional[ProcessedSignal]:
        """Generate AI-driven signal for specific pair"""
        try:
            context = self.last_market_context
            if not context:
                return None

            # Determine action based on unified signal and regime
            unified = context.unified_signal
            regime = context.regime_state

            # Signal generation logic
            if unified > 0.65 and regime in ["strong_uptrend", "momentum_up"]:
                action = SignalAction.BUY
                confidence = min(0.95, unified + 0.1)
            elif unified < 0.35 and regime in ["strong_downtrend", "momentum_down"]:
                action = SignalAction.SELL
                confidence = min(0.95, (1 - unified) + 0.1)
            elif regime == "sideways" and abs(unified - 0.5) > 0.1:
                # Mean reversion in sideways market
                action = SignalAction.BUY if unified < 0.4 else SignalAction.SELL
                confidence = 0.7
            elif regime in ["consolidation", "calm"] and abs(unified - 0.5) > 0.05:
                # Scalping opportunities
                action = SignalAction.SCALP_ENTRY
                confidence = 0.65
            else:
                return None  # No clear signal

            # Get current price (this would come from market data)
            current_price = await self._get_current_price(pair)
            if not current_price:
                return None

            # Assess quality
            quality, confidence_adj = self.quality_assessor.assess_quality(context, unified)
            final_confidence = confidence * confidence_adj

            # Filter low confidence signals
            if final_confidence < self.config["processing"]["min_confidence"]:
                return None

            # Determine strategy based on regime and action
            if action == SignalAction.SCALP_ENTRY:
                strategy = "scalp"
            elif regime in ["strong_uptrend", "strong_downtrend"]:
                strategy = "trend_following"
            elif regime == "sideways":
                strategy = "sideways"
            else:
                strategy = "adaptive"

            # Create signal
            signal = ProcessedSignal(
                signal_id=f"ai_fusion_{pair}_{int(time.time() * 1000)}",
                timestamp=time.time(),
                pair=pair,
                action=action,
                quality=quality,
                urgency=ExecutionUrgency.NORMAL,
                unified_signal=unified,
                regime_state=regime,
                confidence=final_confidence,
                market_context={
                    "source": "ai_fusion",
                    "regime": regime,
                    "unified_signal": unified,
                    "sentiment": context.sentiment_score,
                    "macro": context.macro_signal,
                },
                ta_analysis={
                    "rsi": context.rsi,
                    "macd": context.macd,
                    "trend_strength": context.trend_strength,
                    "bb_width": context.bb_width,
                },
                sentiment_analysis={
                    "score": context.sentiment_score,
                    "trend": context.sentiment_trend,
                },
                macro_analysis={"signal": context.macro_signal, "notes": context.macro_notes},
                price=current_price,
                quantity=0.0,  # Will be calculated later
                target_strategy=strategy,
                priority=7,  # High priority for AI fusion signals
            )

            # Add risk parameters and position sizing
            self._add_risk_parameters(signal, context)
            signal.quantity = signal.position_size_pct

            return signal

        except Exception as e:
            self.logger.error(f"Error generating AI signal for {pair}: {e}")
            return None

    async def _get_current_price(self, pair: str) -> Optional[float]:
        """Get current market price for pair"""
        try:
            # This would typically query your market data stream
            # For now, return a placeholder
            market_stream = f"md:trades:{pair.replace('/', '-')}"
            messages = await self.redis_client.xrevrange(market_stream, count=1)

            if messages:
                latest_message = messages[0]
                trades_data = json.loads(latest_message[1][b"trades"].decode("utf-8"))
                if trades_data:
                    return float(trades_data[0]["price"])

            return None

        except Exception as e:
            self.logger.debug(f"Could not get current price for {pair}: {e}")
            return None

    async def _route_and_send_signal(self, signal: ProcessedSignal):
        """Route and send processed signal to appropriate streams"""
        start_time = time.time()
        try:
            # Get target streams
            target_streams = self.signal_router.route_signal(signal)

            # Convert to execution order format
            order_data = signal.to_execution_order()

            # Send to each target stream
            for stream_name in target_streams:
                try:
                    await self.redis_client.xadd(stream_name, order_data)
                    self.stats["signals_routed"] += 1
                except Exception as e:
                    self.logger.error(f"Failed to send to stream {stream_name}: {e}")
                    # Metrics instrumentation for Redis errors
                    try:
                        from monitoring.metrics_exporter import inc_redis_publish_error

                        inc_redis_publish_error(stream=stream_name)
                    except ImportError:
                        pass  # Metrics not available

            # Metrics instrumentation for successful signals
            try:
                from monitoring.metrics_exporter import (
                    inc_signals_published,
                    observe_publish_latency_ms,
                )
                from monitoring.slo_metrics import record_signal_latency

                latency_ms = (time.time() - start_time) * 1000
                inc_signals_published(agent="signal_processor", stream="routed", symbol=signal.pair)
                observe_publish_latency_ms("signal_processor", "routed", latency_ms)

                # Record e2e latency to Redis for SLO monitoring
                signal_payload = {
                    "signal_id": signal.signal_id,
                    "pair": signal.pair,
                    "action": signal.action.value,
                    "confidence": signal.confidence,
                }
                await record_signal_latency(
                    agent="signal_processor",
                    stream="routed",
                    latency_ms=latency_ms,
                    signal_payload=signal_payload,
                    redis_client=self.redis_client,
                )
            except ImportError:
                pass  # Metrics not available
            except Exception as e:
                self.logger.warning(f"Failed to record SLO metrics: {e}")

            # Log signal generation
            self.logger.info(
                f"Routed signal: {signal.action.value} {signal.pair} "
                f"@ {signal.price:.4f} (quality: {signal.quality.value}, "
                f"confidence: {signal.confidence:.2f}, unified: {signal.unified_signal:.2f})"
            )

            # Send to metrics stream for monitoring
            await self._send_signal_metrics(signal)

        except Exception as e:
            self.logger.error(f"Error routing signal {signal.signal_id}: {e}")
            self.stats["errors"] += 1

    async def _send_signal_metrics(self, signal: ProcessedSignal):
        """Send signal metrics for monitoring"""
        try:
            metrics_data = {
                "timestamp": str(signal.timestamp),
                "pair": signal.pair,
                "action": signal.action.value,
                "quality": signal.quality.value,
                "urgency": signal.urgency.value,
                "confidence": str(signal.confidence),
                "unified_signal": str(signal.unified_signal),
                "regime": signal.regime_state,
                "strategy": signal.target_strategy,
                "priority": str(signal.priority),
                "position_size_pct": str(signal.position_size_pct),
            }

            await self.redis_client.xadd("signal_processor:metrics", metrics_data)

        except Exception as e:
            self.logger.debug(f"Failed to send signal metrics: {e}")

    async def _process_context_based_signals(self, context: MarketContext):
        """Generate signals based on context updates"""
        try:
            # Check for strong unified signal changes
            if abs(context.unified_signal - 0.5) > 0.3:  # Strong signal
                for pair in self.config["trading_pairs"]:
                    signal = await self._generate_ai_signal_for_pair(pair)
                    if signal:
                        signal.urgency = ExecutionUrgency.HIGH
                        await self._route_and_send_signal(signal)

        except Exception as e:
            self.logger.error(f"Error processing context-based signals: {e}")

    async def _monitor_performance(self):
        """Monitor and report performance metrics"""

        while self.running:
            try:
                await asyncio.sleep(60)  # Report every minute

                uptime = time.time() - self.stats["start_time"]

                # Calculate rates
                process_rate = self.stats["signals_processed"] / max(uptime / 60, 1)
                route_rate = self.stats["signals_routed"] / max(uptime / 60, 1)
                filter_rate = self.stats["signals_filtered"] / max(
                    self.stats["signals_processed"], 1
                )
                error_rate = self.stats["errors"] / max(uptime / 60, 1)

                # Log performance
                self.logger.info(
                    f"Performance: Process/min: {process_rate:.1f}, "
                    f"Route/min: {route_rate:.1f}, "
                    f"Filter rate: {filter_rate:.2%}, "
                    f"Errors/min: {error_rate:.1f}"
                )

                # Current market state
                if self.last_market_context:
                    self.logger.info(
                        f"Market: Regime={self.last_market_context.regime_state}, "
                        f"Unified={self.last_market_context.unified_signal:.3f}, "
                        f"Sentiment={self.last_market_context.sentiment_score:.2f}"
                    )

                # Send performance metrics to Redis
                if self.redis_client:
                    perf_metrics = {
                        "timestamp": str(time.time()),
                        "signals_processed": str(self.stats["signals_processed"]),
                        "signals_routed": str(self.stats["signals_routed"]),
                        "signals_filtered": str(self.stats["signals_filtered"]),
                        "process_rate_per_min": str(process_rate),
                        "route_rate_per_min": str(route_rate),
                        "filter_rate": str(filter_rate),
                        "error_rate_per_min": str(error_rate),
                        "uptime_seconds": str(uptime),
                    }

                    if self.last_market_context:
                        perf_metrics.update(
                            {
                                "current_regime": self.last_market_context.regime_state,
                                "unified_signal": str(self.last_market_context.unified_signal),
                                "sentiment_score": str(self.last_market_context.sentiment_score),
                            }
                        )

                    await self.redis_client.xadd("signal_processor:performance", perf_metrics)

            except Exception as e:
                self.logger.error(f"Error in performance monitoring: {e}")


# Main execution and utility functions


async def main():
    """Main execution function for Signal Processor"""

    # Setup logging
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger = logging.getLogger(__name__)
    logger.info("⚙️ Starting Signal Processor Agent...")

    # Validate environment
    required_env_vars = ["REDIS_URL"]
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    if missing_vars:
        logger.error(f"❌ Missing required environment variables: {missing_vars}")
        return

    # Check AI Engine availability
    if not AI_ENGINE_AVAILABLE:
        logger.warning("⚠️ AI Engine not available, running in basic mode")

    # Create and initialize processor
    processor = SignalProcessor()

    try:
        await processor.initialize()
        logger.info("✅ Signal Processor initialized successfully")

        # Start the processor
        await processor.start()

    except KeyboardInterrupt:
        logger.info("\n⏹️ Graceful shutdown initiated...")
    except Exception as e:
        logger.error(f"❌ Signal Processor error: {e}")
    finally:
        await processor.stop()
        logger.info("✅ Signal Processor shutdown complete")


def validate_config():
    """Validate configuration"""

    required_vars = ["REDIS_URL"]
    missing = [var for var in required_vars if not os.getenv(var)]

    if missing:
        logger.error("Missing required environment variables: %s", missing)
        return False

    # Validate Redis URL
    redis_url = os.getenv("REDIS_URL", "")
    if not (redis_url.startswith("redis://") or redis_url.startswith("rediss://")):
        logger.error("REDIS_URL must start with redis:// or rediss://")
        return False

    logger.info("Signal Processor configuration valid")
    return True


async def test_ai_integration():
    """Test AI engine integration"""

    if not AI_ENGINE_AVAILABLE:
        logger.error("AI Engine not available for testing")
        return False

    try:
        # Test AI components
        from ai_engine.global_context import MarketContext

        # Create test context
        test_context = MarketContext(
            rsi=65.0,
            macd=0.02,
            macd_signal=0.015,
            bb_width=0.015,
            trend_strength=0.7,
            sentiment_score=0.3,
            sentiment_trend="bullish",
            macro_signal=0.2,
            macro_notes={"test": True},
            unified_signal=0.65,
            regime_state="strong_uptrend",
            meta={},
        )

        logger.info("AI Context test passed: %s", test_context.regime_state)

        # Test signal processor components
        processor = SignalProcessor()
        quality, conf_adj = processor.quality_assessor.assess_quality(test_context, 0.65)
        logger.info("Quality assessment test passed: %s (adj: %.2f)", quality.value, conf_adj)

        return True

    except Exception as e:
        logger.error("AI integration test failed: %s", e)
        return False


async def test_signal_processing():
    """Test signal processing pipeline"""

    logger.info("Testing Signal Processor pipeline...")

    try:
        processor = SignalProcessor()

        # Test raw signal enhancement
        test_signal_data = {
            "pair": "BTC/USD",
            "action": "buy",
            "price": 50000.0,
            "confidence": 0.75,
            "strategy": "trend_following",
            "timeframe": "5m",
        }

        # Create test market context
        if AI_ENGINE_AVAILABLE:
            test_context = MarketContext(
                unified_signal=0.7,
                regime_state="strong_uptrend",
                sentiment_score=0.2,
                sentiment_trend="bullish",
                macro_signal=0.1,
                macro_notes={},
                meta={},
            )
        else:
            # Mock context for testing
            class MockContext:
                def __init__(self):
                    self.unified_signal = 0.7
                    self.regime_state = "strong_uptrend"
                    self.sentiment_score = 0.2
                    self.sentiment_trend = "bullish"
                    self.macro_signal = 0.1
                    self.macro_notes = {}
                    self.rsi = 65.0
                    self.macd = 0.02
                    self.macd_signal = 0.015
                    self.bb_width = 0.015
                    self.trend_strength = 0.7

            test_context = MockContext()

        # Test signal enhancement
        enhanced_signal = await processor._enhance_raw_signal(test_signal_data, test_context)

        if enhanced_signal:
            logger.info("Signal enhancement test passed")
            logger.info("   Quality: %s", enhanced_signal.quality.value)
            logger.info("   Confidence: %.2f", enhanced_signal.confidence)
            logger.info("   Priority: %s", enhanced_signal.priority)
        else:
            logger.error("Signal was filtered out")
            return False

        # Test signal routing
        target_streams = processor.signal_router.route_signal(enhanced_signal)
        logger.info("Signal routing test passed: %d streams", len(target_streams))

        logger.info("All signal processing tests passed!")
        return True

    except Exception as e:
        logger.error("Signal processing test failed: %s", e)
        return False


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == "validate":
            if validate_config():
                sys.exit(0)
            else:
                sys.exit(1)

        elif command == "test-ai":
            success = asyncio.run(test_ai_integration())
            sys.exit(0 if success else 1)

        elif command == "test-processing":
            success = asyncio.run(test_signal_processing())
            sys.exit(0 if success else 1)

        else:
            logger.error("Unknown command: %s", command)
            logger.error("Available commands: validate, test-ai, test-processing")
            sys.exit(1)
    else:
        # Run the main Signal Processor
        asyncio.run(main())
