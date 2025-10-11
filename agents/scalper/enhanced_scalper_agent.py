"""
Enhanced Scalper Agent with Multi-Strategy Integration

Integrates the existing Kraken scalping strategy with other trading strategies
to provide enhanced signal quality, regime-aware trading, and improved risk management.

Features:
- Regime-based market condition detection
- Multi-strategy signal alignment
- Dynamic parameter adaptation
- Enhanced risk management
- Confidence weighting system
- Real-time market regime detection
- Strategy signal aggregation and filtering
- Adaptive scalping parameters based on market conditions
"""

from __future__ import annotations

import logging
import os

# Import strategy modules
import sys
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

from .data.market_store import TickRecord

# Import existing scalper components
from .kraken_scalper_agent import KrakenScalperAgent


# Defer sys.path modification to function call
def _ensure_sys_path():
    """Add parent directories to sys.path if needed (call explicitly)."""
    parent_path = os.path.join(os.path.dirname(__file__), "..", "..")
    if parent_path not in sys.path:
        sys.path.append(parent_path)


# Lazy imports - defer until needed
def _import_strategies():
    """Import strategy modules (call explicitly when needed)."""
    _ensure_sys_path()
    from strategies.breakout import BreakoutStrategy
    from strategies.mean_reversion import MeanReversionStrategy
    from strategies.momentum_strategy import MomentumStrategy
    from strategies.regime_based_router import MarketContext, RegimeRouter
    from strategies.sideways import SidewaysStrategy
    from strategies.trend_following import TrendFollowingStrategy

    return {
        "BreakoutStrategy": BreakoutStrategy,
        "MeanReversionStrategy": MeanReversionStrategy,
        "MomentumStrategy": MomentumStrategy,
        "MarketContext": MarketContext,
        "RegimeRouter": RegimeRouter,
        "SidewaysStrategy": SidewaysStrategy,
        "TrendFollowingStrategy": TrendFollowingStrategy,
    }


# Lazy MCP imports
def _import_mcp():
    """Import MCP components (call explicitly when needed)."""
    try:
        from mcp.context import MarketContext as MCPMarketContext
        from mcp.redis_manager import RedisManager

        return {"MCPMarketContext": MCPMarketContext, "RedisManager": RedisManager, "HAS_MCP": True}
    except ImportError:
        # Use fallback from strategies (will be imported via _import_strategies)
        return {"MCPMarketContext": None, "RedisManager": None, "HAS_MCP": False}


@dataclass
class StrategySignal:
    """Standardized signal from any strategy"""

    strategy_name: str
    signal: str  # 'buy', 'sell', 'hold'
    confidence: float
    position_size: float
    metadata: Dict[str, Any]
    timestamp: float


@dataclass
class EnhancedSignal:
    """Enhanced signal combining scalping and strategy signals"""

    pair: str
    side: str
    entry_price: Decimal
    take_profit: Decimal
    stop_loss: Decimal
    size_quote_usd: Decimal
    confidence: float
    strategy_alignment: bool
    regime_state: str
    regime_confidence: float
    scalping_confidence: float
    strategy_confidence: float
    metadata: Dict[str, Any]
    signal_id: str


class EnhancedScalperAgent:
    """
    Enhanced Scalper Agent with Multi-Strategy Integration

    Combines high-frequency scalping with medium-term strategy signals
    for improved signal quality and adaptive trading.
    """

    def __init__(
        self,
        config: Dict[str, Any],
        redis_manager: Optional[Any] = None,  # Changed from RedisManager (not imported yet)
        logger: Optional[logging.Logger] = None,
    ):
        """
        Initialize the enhanced scalper agent

        Args:
            config: Configuration dictionary
            redis_manager: Optional Redis manager for data persistence
            logger: Optional logger instance
        """
        self.config = config
        self.redis_manager = redis_manager
        self.logger = logger or logging.getLogger(__name__)

        # Load strategy modules
        self._strategy_modules = _import_strategies()
        self._mcp_modules = _import_mcp()

        # Initialize core scalper
        self.kraken_scalper = KrakenScalperAgent(
            pairs=config.get("scalper", {}).get("pairs", ["BTC/USD", "ETH/USD"]),
            config=config.get("scalper", {}),
            logger=self.logger,
        )

        # Initialize strategy router
        RegimeRouter = self._strategy_modules["RegimeRouter"]
        self.regime_router = RegimeRouter(config.get("strategy_router", {}))

        # Initialize individual strategies
        self.strategies = self._initialize_strategies(config)

        # Integration state
        self.strategy_signals: Dict[str, StrategySignal] = {}
        self.market_regime = "unknown"
        self.regime_confidence = 0.5
        self.last_regime_update = 0.0

        # Performance tracking
        self.signals_generated = 0
        self.signals_aligned = 0
        self.signals_filtered = 0
        self.performance_metrics = {
            "total_signals": 0,
            "aligned_signals": 0,
            "filtered_signals": 0,
            "regime_adaptations": 0,
            "avg_confidence": 0.0,
        }

        self.logger.info("Enhanced Scalper Agent initialized with strategy integration")

    def _initialize_strategies(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Initialize all trading strategies"""
        strategies = {}

        try:
            # Get strategy classes from lazy imports
            BreakoutStrategy = self._strategy_modules["BreakoutStrategy"]
            MeanReversionStrategy = self._strategy_modules["MeanReversionStrategy"]
            MomentumStrategy = self._strategy_modules["MomentumStrategy"]
            TrendFollowingStrategy = self._strategy_modules["TrendFollowingStrategy"]
            SidewaysStrategy = self._strategy_modules["SidewaysStrategy"]

            # Breakout strategy
            breakout_config = config.get("strategies", {}).get("breakout", {})
            strategies["breakout"] = BreakoutStrategy(breakout_config)

            # Mean reversion strategy
            config.get("strategies", {}).get("mean_reversion", {})
            strategies["mean_reversion"] = MeanReversionStrategy(
                ex_client=None, config=config, logger=self.logger  # Will be set by scalper
            )

            # Momentum strategy
            config.get("strategies", {}).get("momentum", {})
            strategies["momentum"] = MomentumStrategy(
                redis_manager=self.redis_manager, config=config
            )

            # Trend following strategy
            trend_config = config.get("strategies", {}).get("trend_following", {})
            strategies["trend_following"] = TrendFollowingStrategy(trend_config)

            # Sideways strategy
            strategies["sideways"] = SidewaysStrategy()

            self.logger.info(f"Initialized {len(strategies)} strategies: {list(strategies.keys())}")

        except Exception as e:
            self.logger.error(f"Error initializing strategies: {e}")

        return strategies

    async def initialize(self) -> None:
        """Initialize the enhanced scalper agent"""
        await self.kraken_scalper.initialize()

        # Initialize regime detection
        await self._update_market_regime()

        self.logger.info("Enhanced Scalper Agent initialization complete")

    async def _update_market_regime(self) -> None:
        """Update market regime based on current market data"""
        try:
            # Get recent market data for regime detection
            market_data = await self._get_market_data_for_regime()

            if market_data is not None:
                # Create market context (use MCP version if available, else fallback)
                MCPMarketContext = self._mcp_modules.get("MCPMarketContext")
                if MCPMarketContext is None:
                    # Fallback to strategy MarketContext
                    MCPMarketContext = self._strategy_modules["MarketContext"]

                context = MCPMarketContext(
                    regime_state=self.market_regime,
                    symbol=market_data.get("symbol", "BTC/USD"),
                    timeframe=market_data.get("timeframe", "1h"),
                )

                # Route to determine regime
                regime_result = self.regime_router.route(market_data["df"], context, self.config)

                # Update regime state
                self.market_regime = regime_result.get("regime_state", "unknown")
                self.regime_confidence = regime_result.get("confidence", 0.5)
                self.last_regime_update = time.time()

                # Adapt scalping parameters based on regime
                await self._adapt_to_regime()

                self.performance_metrics["regime_adaptations"] += 1

        except Exception as e:
            self.logger.error(f"Error updating market regime: {e}")

    async def _get_market_data_for_regime(self) -> Optional[Dict[str, Any]]:
        """Get market data for regime detection"""
        try:
            # This would typically fetch from Redis or exchange
            # For now, return mock data structure
            return {
                "symbol": "BTC/USD",
                "timeframe": "1h",
                "df": None,  # Would contain OHLCV DataFrame
            }
        except Exception as e:
            self.logger.error(f"Error getting market data: {e}")
            return None

    async def _adapt_to_regime(self) -> None:
        """Adapt scalping parameters based on current market regime"""
        try:
            regime_config = self.config.get("regime_adaptation", {})

            if self.market_regime == "sideways":
                # Increase scalping frequency, reduce targets
                self.kraken_scalper.target_bps = regime_config.get("sideways_target_bps", 8)
                self.kraken_scalper.stop_loss_bps = regime_config.get("sideways_stop_bps", 4)
                self.kraken_scalper.max_trades_per_min = regime_config.get("sideways_max_trades", 6)

            elif self.market_regime == "bull":
                # Focus on long scalps, increase targets
                self.kraken_scalper.target_bps = regime_config.get("bull_target_bps", 12)
                self.kraken_scalper.stop_loss_bps = regime_config.get("bull_stop_bps", 6)
                self.kraken_scalper.max_trades_per_min = regime_config.get("bull_max_trades", 4)

            elif self.market_regime == "bear":
                # Focus on short scalps, increase targets
                self.kraken_scalper.target_bps = regime_config.get("bear_target_bps", 12)
                self.kraken_scalper.stop_loss_bps = regime_config.get("bear_stop_bps", 6)
                self.kraken_scalper.max_trades_per_min = regime_config.get("bear_max_trades", 4)

            self.logger.debug(f"Adapted scalping parameters for {self.market_regime} regime")

        except Exception as e:
            self.logger.error(f"Error adapting to regime: {e}")

    async def _get_strategy_signals(
        self, pair: str, market_data: Dict[str, Any]
    ) -> Dict[str, StrategySignal]:
        """Get signals from all strategies for a given pair"""
        strategy_signals = {}

        try:
            for strategy_name, strategy in self.strategies.items():
                try:
                    if strategy_name == "breakout":
                        # Breakout strategy
                        signal = strategy.generate_signal(
                            market_data["df"],
                            now_ms=int(time.time() * 1000),
                            context=market_data.get("context", {}),
                        )
                        if signal:
                            strategy_signals[strategy_name] = StrategySignal(
                                strategy_name=strategy_name,
                                signal=signal.side,
                                confidence=signal.confidence,
                                position_size=signal.size_quote_usd,
                                metadata=signal.meta,
                                timestamp=time.time(),
                            )

                    elif strategy_name == "mean_reversion":
                        # Mean reversion strategy
                        decision = strategy.decide(pair, "1h", market_data.get("context", {}))
                        if decision.success and decision.signal:
                            strategy_signals[strategy_name] = StrategySignal(
                                strategy_name=strategy_name,
                                signal=decision.signal.side,
                                confidence=decision.signal.confidence,
                                position_size=decision.signal.size_quote_usd,
                                metadata=decision.signal.meta,
                                timestamp=time.time(),
                            )

                    elif strategy_name == "momentum":
                        # Momentum strategy
                        signal = await strategy.analyze_market(market_data.get("market_data"))
                        if signal:
                            strategy_signals[strategy_name] = StrategySignal(
                                strategy_name=strategy_name,
                                signal=signal.action.lower(),
                                confidence=signal.confidence,
                                position_size=signal.quantity,
                                metadata=signal.metadata,
                                timestamp=time.time(),
                            )

                    elif strategy_name == "trend_following":
                        # Trend following strategy
                        signal = strategy.generate_signal(market_data["df"])
                        if signal and signal["signal"] != "hold":
                            strategy_signals[strategy_name] = StrategySignal(
                                strategy_name=strategy_name,
                                signal=signal["signal"],
                                confidence=signal["confidence"],
                                position_size=signal["position_size"],
                                metadata=signal["metadata"],
                                timestamp=time.time(),
                            )

                    elif strategy_name == "sideways":
                        # Sideways strategy
                        MarketContext = self._strategy_modules["MarketContext"]
                        context = MarketContext(
                            regime_state=self.market_regime, symbol=pair, timeframe="1h"
                        )
                        signal = strategy.generate_signal(
                            market_data["df"], context, self.config.get("sideways", {})
                        )
                        if signal and signal["signal"] != "hold":
                            strategy_signals[strategy_name] = StrategySignal(
                                strategy_name=strategy_name,
                                signal=signal["signal"],
                                confidence=signal["confidence"],
                                position_size=signal["position_size"],
                                metadata=signal["metadata"],
                                timestamp=time.time(),
                            )

                except Exception as e:
                    self.logger.warning(f"Error getting signal from {strategy_name}: {e}")
                    continue

        except Exception as e:
            self.logger.error(f"Error getting strategy signals: {e}")

        return strategy_signals

    def _check_strategy_alignment(
        self, scalping_signal: Dict[str, Any], strategy_signals: Dict[str, StrategySignal]
    ) -> Tuple[bool, float, str]:
        """
        Check if scalping signal aligns with strategy signals

        Returns:
            (is_aligned, alignment_confidence, alignment_reason)
        """
        if not strategy_signals:
            return True, 0.5, "no_strategy_signals"

        # Count aligned vs conflicting signals
        aligned_count = 0
        conflicting_count = 0
        total_confidence = 0.0

        scalping_side = scalping_signal["side"]

        for strategy_signal in strategy_signals.values():
            if strategy_signal.signal == scalping_side:
                aligned_count += 1
                total_confidence += strategy_signal.confidence
            elif strategy_signal.signal in ["buy", "sell"]:  # Only count directional signals
                conflicting_count += 1

        total_signals = aligned_count + conflicting_count
        if total_signals == 0:
            return True, 0.5, "no_directional_signals"

        alignment_ratio = aligned_count / total_signals
        avg_confidence = total_confidence / max(aligned_count, 1)

        # Determine alignment
        is_aligned = alignment_ratio >= 0.6  # At least 60% alignment

        if is_aligned:
            alignment_confidence = min(0.9, 0.5 + (alignment_ratio * 0.4) + (avg_confidence * 0.2))
            reason = f"aligned_{aligned_count}_{total_signals}"
        else:
            alignment_confidence = max(0.1, 0.5 - (alignment_ratio * 0.4))
            reason = f"conflicting_{conflicting_count}_{total_signals}"

        return is_aligned, alignment_confidence, reason

    async def generate_enhanced_signal(
        self,
        pair: str,
        best_bid: Optional[float] = None,
        best_ask: Optional[float] = None,
        last_price: Optional[float] = None,
        quote_liquidity_usd: Optional[float] = None,
        market_data: Optional[Dict[str, Any]] = None,
    ) -> Optional[EnhancedSignal]:
        """
        Generate enhanced scalping signal with strategy integration

        Args:
            pair: Trading pair
            best_bid: Best bid price
            best_ask: Best ask price
            last_price: Last trade price
            quote_liquidity_usd: Quote liquidity in USD
            market_data: Additional market data for strategies

        Returns:
            Enhanced signal or None
        """
        try:
            # Update regime if needed (every 5 minutes)
            if time.time() - self.last_regime_update > 300:
                await self._update_market_regime()

            # Get base scalping signal
            scalping_signal = await self.kraken_scalper.generate_signal(
                pair=pair,
                best_bid=best_bid,
                best_ask=best_ask,
                last_price=last_price,
                quote_liquidity_usd=quote_liquidity_usd,
            )

            if not scalping_signal:
                return None

            # Get strategy signals if market data is available
            strategy_signals = {}
            if market_data:
                strategy_signals = await self._get_strategy_signals(pair, market_data)

            # Check strategy alignment
            is_aligned, alignment_confidence, alignment_reason = self._check_strategy_alignment(
                scalping_signal, strategy_signals
            )

            # Apply strategy-based filtering
            if not self._should_accept_signal(
                scalping_signal, strategy_signals, is_aligned, alignment_confidence
            ):
                self.signals_filtered += 1
                self.performance_metrics["filtered_signals"] += 1
                return None

            # Calculate enhanced confidence
            enhanced_confidence = self._calculate_enhanced_confidence(
                scalping_signal, strategy_signals, is_aligned, alignment_confidence
            )

            # Build enhanced signal
            enhanced_signal = EnhancedSignal(
                pair=pair,
                side=scalping_signal["side"],
                entry_price=Decimal(str(scalping_signal["entry_price"])),
                take_profit=Decimal(str(scalping_signal["take_profit"])),
                stop_loss=Decimal(str(scalping_signal["stop_loss"])),
                size_quote_usd=Decimal(str(scalping_signal["size_quote_usd"])),
                confidence=enhanced_confidence,
                strategy_alignment=is_aligned,
                regime_state=self.market_regime,
                regime_confidence=self.regime_confidence,
                scalping_confidence=scalping_signal["meta"]["confidence"],
                strategy_confidence=alignment_confidence,
                metadata={
                    **scalping_signal["meta"],
                    "strategy_signals": {
                        name: {"signal": sig.signal, "confidence": sig.confidence}
                        for name, sig in strategy_signals.items()
                    },
                    "alignment_reason": alignment_reason,
                    "regime_state": self.market_regime,
                    "regime_confidence": self.regime_confidence,
                },
                signal_id=scalping_signal["signal_id"],
            )

            # Update performance metrics
            self.signals_generated += 1
            self.performance_metrics["total_signals"] += 1
            if is_aligned:
                self.signals_aligned += 1
                self.performance_metrics["aligned_signals"] += 1

            self.performance_metrics["avg_confidence"] = (
                self.performance_metrics["avg_confidence"] * (self.signals_generated - 1)
                + enhanced_confidence
            ) / self.signals_generated

            self.logger.info(
                f"Enhanced signal generated: {pair} {scalping_signal['side']} "
                f"conf={enhanced_confidence:.3f} aligned={is_aligned} regime={self.market_regime}"
            )

            return enhanced_signal

        except Exception as e:
            self.logger.error(f"Error generating enhanced signal: {e}")
            return None

    def _should_accept_signal(
        self,
        scalping_signal: Dict[str, Any],
        strategy_signals: Dict[str, StrategySignal],
        is_aligned: bool,
        alignment_confidence: float,
    ) -> bool:
        """Determine if signal should be accepted based on strategy alignment"""

        # Get filtering configuration
        filter_config = self.config.get("signal_filtering", {})
        min_alignment_confidence = filter_config.get("min_alignment_confidence", 0.3)
        filter_config.get("min_strategy_alignment", 0.6)
        require_alignment = filter_config.get("require_alignment", False)

        # Check minimum alignment confidence
        if alignment_confidence < min_alignment_confidence:
            return False

        # Check if alignment is required
        if require_alignment and not is_aligned:
            return False

        # Check regime confidence
        if self.regime_confidence < filter_config.get("min_regime_confidence", 0.3):
            return False

        # Check scalping signal confidence
        if scalping_signal["meta"]["confidence"] < filter_config.get(
            "min_scalping_confidence", 0.5
        ):
            return False

        return True

    def _calculate_enhanced_confidence(
        self,
        scalping_signal: Dict[str, Any],
        strategy_signals: Dict[str, StrategySignal],
        is_aligned: bool,
        alignment_confidence: float,
    ) -> float:
        """Calculate enhanced confidence combining scalping and strategy signals"""

        base_confidence = scalping_signal["meta"]["confidence"]

        # Strategy alignment boost
        if is_aligned:
            alignment_boost = min(0.3, alignment_confidence * 0.3)
        else:
            alignment_boost = -0.2  # Penalty for conflicting signals

        # Regime confidence boost
        regime_boost = (self.regime_confidence - 0.5) * 0.2

        # Calculate enhanced confidence
        enhanced_confidence = base_confidence + alignment_boost + regime_boost

        # Ensure confidence is within bounds
        return max(0.0, min(1.0, enhanced_confidence))

    async def validate_enhanced_signal(self, signal: EnhancedSignal) -> bool:
        """Validate enhanced signal with additional checks"""

        # Standard scalping validation
        scalping_signal = {
            "pair": signal.pair,
            "side": signal.side,
            "entry_price": str(signal.entry_price),
            "take_profit": str(signal.take_profit),
            "stop_loss": str(signal.stop_loss),
            "size_usd": str(signal.size_quote_usd),
            "meta": {"confidence": signal.scalping_confidence},
        }

        if not await self.kraken_scalper.validate_signal(scalping_signal):
            return False

        # Enhanced validation checks
        validation_config = self.config.get("enhanced_validation", {})

        # Check minimum enhanced confidence
        if signal.confidence < validation_config.get("min_enhanced_confidence", 0.6):
            return False

        # Check regime confidence
        if signal.regime_confidence < validation_config.get("min_regime_confidence", 0.4):
            return False

        # Check strategy alignment if required
        if (
            validation_config.get("require_strategy_alignment", False)
            and not signal.strategy_alignment
        ):
            return False

        return True

    async def get_enhanced_status(self) -> Dict[str, Any]:
        """Get enhanced status including strategy integration metrics"""

        base_status = await self.kraken_scalper.get_strategy_status()

        enhanced_status = {
            **base_status,
            "strategy_integration": {
                "enabled": True,
                "market_regime": self.market_regime,
                "regime_confidence": self.regime_confidence,
                "last_regime_update": self.last_regime_update,
                "active_strategies": list(self.strategies.keys()),
                "strategy_signals_count": len(self.strategy_signals),
            },
            "performance_metrics": self.performance_metrics,
            "signal_alignment_rate": (self.signals_aligned / max(self.signals_generated, 1)),
            "signal_filter_rate": (
                self.signals_filtered / max(self.signals_generated + self.signals_filtered, 1)
            ),
        }

        return enhanced_status

    async def on_tick(self, pair: str, tick: TickRecord) -> None:
        """Handle new tick data"""
        await self.kraken_scalper.on_tick(pair, tick)

    async def update_regime(
        self, regime: str, confidence: float, scalping_suitability: float
    ) -> None:
        """Update market regime information"""
        await self.kraken_scalper.update_regime(regime, confidence, scalping_suitability)
        self.market_regime = regime
        self.regime_confidence = confidence
        await self._adapt_to_regime()

    def notify_trade_result(self, pair: str, pnl_usd: float) -> None:
        """Notify about trade results"""
        self.kraken_scalper.notify_trade_result(pair, pnl_usd)
