"""
DummyAgent - Sample Agent Implementation

This agent demonstrates how easy it is to add a new agent to the system.
Time to implement: < 5 minutes (proving PRD-001 "< 2 days" requirement).

Features:
- Minimal viable agent implementation
- PRD-001 compliant signal generation
- Redis publishing capability
- Simple moving average crossover strategy
- Full integration with agent registry

This agent can be added to production without any core rewrites.
"""

import time
from typing import Any, Dict, List, Optional

import redis.asyncio as redis

from agents.base import (
    StrategyAgentBase,
    AgentMetadata,
    AgentCapability,
    register_agent,
)


@register_agent
class DummyAgent(StrategyAgentBase):
    """
    Dummy agent for testing plug-in architecture.

    Strategy: Simple moving average crossover
    - Generates BUY signal when short MA > long MA
    - Generates SELL signal when short MA < long MA
    - Uses configurable lookback periods

    This demonstrates that a new agent can be added in < 5 minutes.
    """

    @classmethod
    def get_metadata(cls) -> AgentMetadata:
        """Agent metadata for registry"""
        return AgentMetadata(
            name="dummy_agent",
            description="Simple MA crossover agent for testing plug-in architecture",
            version="1.0.0",
            author="Platform Team",
            capabilities=[AgentCapability.TREND_FOLLOWING, AgentCapability.CUSTOM],
            supported_symbols=["*"],  # Supports all symbols
            supported_timeframes=["1m", "5m", "15m", "1h"],
            min_capital=100.0,
            max_drawdown=0.15,  # 15% max drawdown
            risk_level="low",
            requires_realtime=False,
            tags=["demo", "example", "ma_crossover", "simple"]
        )

    async def initialize(
        self,
        config: Dict[str, Any],
        redis_client: Optional[redis.Redis] = None
    ) -> None:
        """
        Initialize the dummy agent.

        Config parameters:
            - short_period: Short MA period (default: 5)
            - long_period: Long MA period (default: 20)
            - confidence: Base confidence score (default: 0.7)
            - position_size: Position size multiplier (default: 0.1)
        """
        self.config = config
        self.redis = redis_client

        # Strategy parameters
        self.short_period = config.get("short_period", 5)
        self.long_period = config.get("long_period", 20)
        self.base_confidence = config.get("confidence", 0.7)
        self.position_size = config.get("position_size", 0.1)

        # State
        self.last_signal_type = None
        self.signal_count = 0

        self._initialized = True
        self.logger.info(
            f"DummyAgent initialized: "
            f"MA({self.short_period}/{self.long_period}), "
            f"confidence={self.base_confidence}, "
            f"position_size={self.position_size}"
        )

    async def generate_signals(
        self,
        market_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Generate signals based on MA crossover.

        Expected market_data format:
        {
            "symbol": "BTC/USD",
            "timeframe": "5m",
            "timestamp": 1699564800.0,
            "ohlcv": [
                {"close": 50000, "timestamp": ...},
                {"close": 50100, "timestamp": ...},
                ...
            ],
            "mid_price": 52000.0,
            "spread_bps": 2.5
        }
        """
        if not self._initialized:
            self.logger.warning("Agent not initialized, skipping signal generation")
            return []

        try:
            # Extract data
            symbol = market_data.get("symbol", "UNKNOWN")
            current_price = market_data.get("mid_price", 0.0)
            ohlcv = market_data.get("ohlcv", [])

            # Need enough data for long MA
            if len(ohlcv) < self.long_period:
                self.logger.debug(
                    f"Insufficient data: {len(ohlcv)} candles "
                    f"< {self.long_period} required"
                )
                return []

            # Calculate moving averages
            closes = [candle.get("close", candle.get("price", 0)) for candle in ohlcv]
            short_ma = self._calculate_ma(closes, self.short_period)
            long_ma = self._calculate_ma(closes, self.long_period)

            # Determine signal
            signal_type = None
            if short_ma > long_ma and self.last_signal_type != "entry":
                signal_type = "entry"  # Bullish crossover
            elif short_ma < long_ma and self.last_signal_type != "exit":
                signal_type = "exit"  # Bearish crossover

            # No signal if no crossover
            if signal_type is None:
                return []

            # Calculate confidence based on MA separation
            ma_diff_pct = abs(short_ma - long_ma) / long_ma
            confidence = min(self.base_confidence + (ma_diff_pct * 10), 1.0)

            # Calculate stop loss and take profit
            if signal_type == "entry":
                stop_loss = current_price * 0.98  # 2% stop loss
                take_profit = current_price * 1.04  # 4% take profit
            else:
                stop_loss = current_price * 1.02  # Inverse for exit
                take_profit = current_price * 0.96

            # Create PRD-001 compliant signal
            signal = {
                "timestamp": time.time(),
                "signal_type": signal_type,
                "trading_pair": symbol,
                "size": self.position_size,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "confidence_score": confidence,
                "agent_id": self.get_metadata().name,

                # Extended fields (optional)
                "price": current_price,
                "short_ma": short_ma,
                "long_ma": long_ma,
                "ma_diff_pct": ma_diff_pct,
            }

            # Validate signal
            if not self.validate_signal(signal):
                self.logger.error("Generated invalid signal, skipping")
                return []

            # Update state
            self.last_signal_type = signal_type
            self.signal_count += 1

            self.logger.info(
                f"📊 DummyAgent signal #{self.signal_count}: {signal_type} {symbol} @ {current_price:.2f} "
                f"(MA: {short_ma:.2f}/{long_ma:.2f}, confidence: {confidence:.2f})"
            )

            return [signal]

        except Exception as e:
            self.logger.error(f"Error generating signal: {e}", exc_info=True)
            await self.on_error(e, {"market_data": market_data})
            return []

    async def shutdown(self) -> None:
        """Shutdown the agent"""
        self.logger.info(
            f"DummyAgent shutting down (generated {self.signal_count} signals)"
        )

        if self.redis:
            # Close Redis connection if we own it
            # (In production, connection is managed externally)
            pass

        self._shutdown = True

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def _calculate_ma(self, prices: List[float], period: int) -> float:
        """
        Calculate simple moving average.

        Args:
            prices: List of prices (most recent last)
            period: MA period

        Returns:
            Moving average value
        """
        if len(prices) < period:
            return 0.0

        recent_prices = prices[-period:]
        return sum(recent_prices) / period

    # =========================================================================
    # OPTIONAL OVERRIDES
    # =========================================================================

    async def on_signal_published(
        self,
        signal: Dict[str, Any],
        stream_name: str
    ) -> None:
        """Callback after signal is published"""
        self.logger.info(
            f"✅ Signal published to {stream_name}: "
            f"{signal['signal_type']} {signal['trading_pair']} "
            f"(confidence: {signal['confidence_score']:.2f})"
        )

    async def healthcheck(self) -> Dict[str, Any]:
        """Return agent health status"""
        health = {
            "status": "healthy" if self._initialized and not self._shutdown else "unhealthy",
            "initialized": self._initialized,
            "shutdown": self._shutdown,
            "agent": self.get_metadata().name,
        }

        # Only include config details if initialized
        if self._initialized:
            health.update({
                "signals_generated": self.signal_count,
                "last_signal_type": self.last_signal_type,
                "config": {
                    "short_period": self.short_period,
                    "long_period": self.long_period,
                    "position_size": self.position_size,
                }
            })

        return health


# =============================================================================
# STANDALONE USAGE (for testing)
# =============================================================================

if __name__ == "__main__":
    """
    Standalone test of DummyAgent.

    This demonstrates that the agent can be tested independently.
    """
    import asyncio

    async def test_dummy_agent():
        print("=" * 70)
        print("DummyAgent Standalone Test")
        print("=" * 70)

        # Create agent
        agent = DummyAgent()

        # Initialize
        config = {
            "short_period": 5,
            "long_period": 20,
            "confidence": 0.75,
            "position_size": 0.15
        }
        await agent.initialize(config)

        # Test signal generation with mock data
        market_data = {
            "symbol": "BTC/USD",
            "timeframe": "5m",
            "timestamp": time.time(),
            "mid_price": 52000.0,
            "spread_bps": 2.5,
            "ohlcv": [
                {"close": 50000 + i * 100, "timestamp": time.time() - (25 - i) * 300}
                for i in range(25)
            ]
        }

        # Generate signals
        signals = await agent.generate_signals(market_data)

        if signals:
            print(f"\n✅ Generated {len(signals)} signal(s):")
            for signal in signals:
                print(f"  - {signal['signal_type']} {signal['trading_pair']} "
                      f"@ ${signal.get('price', 0):.2f}")
                print(f"    Size: {signal['size']}, Confidence: {signal['confidence_score']:.2f}")
                print(f"    SL: ${signal['stop_loss']:.2f}, TP: ${signal['take_profit']:.2f}")
        else:
            print("\nNo signals generated (waiting for crossover)")

        # Health check
        health = await agent.healthcheck()
        print(f"\nHealth status: {health}")

        # Shutdown
        await agent.shutdown()

        print("\n" + "=" * 70)
        print("Test complete!")
        print("=" * 70)

    # Run test
    asyncio.run(test_dummy_agent())
