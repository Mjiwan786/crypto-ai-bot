"""
Strategy Agent Base Class - Plug-in Architecture Foundation

This module provides the abstract base class that ALL strategy agents must inherit from.
It defines the interface contract that enables plug-and-play agent architecture without
core rewrites.

Requirements (PRD-001):
- Agents must support plug-in architecture
- New agent can be added in < 2 days (proven < 2 minutes with DummyAgent)
- No core rewrites required when adding agents
- Clear interface contract for signal generation

Architecture:
- StrategyAgentBase: Abstract base class defining required interface
- AgentRegistry: Global registry for discovering and instantiating agents
- Auto-discovery via Python entry points or manual registration
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Type
from enum import Enum

import redis.asyncio as redis


# =============================================================================
# AGENT METADATA
# =============================================================================

class AgentCapability(str, Enum):
    """Agent capabilities for routing and discovery"""
    SCALPING = "scalping"
    TREND_FOLLOWING = "trend_following"
    MEAN_REVERSION = "mean_reversion"
    ARBITRAGE = "arbitrage"
    MARKET_MAKING = "market_making"
    MOMENTUM = "momentum"
    BREAKOUT = "breakout"
    RANGE_TRADING = "range_trading"
    CUSTOM = "custom"


@dataclass
class AgentMetadata:
    """
    Metadata describing an agent's characteristics.

    Used by the registry for agent discovery and routing.
    """
    name: str  # Unique agent identifier
    description: str  # Human-readable description
    version: str  # Semantic version (e.g., "1.0.0")
    author: str  # Author/team name
    capabilities: List[AgentCapability]  # What the agent can do
    supported_symbols: List[str]  # Symbols agent can trade (e.g., ["BTC/USD", "ETH/USD"])
    supported_timeframes: List[str]  # Timeframes agent supports (e.g., ["1m", "5m"])
    min_capital: float = 0.0  # Minimum capital required
    max_drawdown: float = 0.20  # Maximum drawdown tolerance (0.20 = 20%)
    risk_level: str = "medium"  # low/medium/high
    requires_realtime: bool = False  # Whether agent needs real-time data
    tags: List[str] = None  # Additional tags for categorization

    def __post_init__(self):
        if self.tags is None:
            self.tags = []


# =============================================================================
# BASE AGENT CLASS
# =============================================================================

class StrategyAgentBase(ABC):
    """
    Abstract base class for all strategy agents.

    ALL agents must inherit from this class and implement the required methods.
    This ensures a consistent interface and enables plug-and-play architecture.

    Required Methods:
        - get_metadata(): Return agent metadata
        - initialize(config, redis_client): Setup agent with configuration
        - generate_signals(market_data): Generate trading signals
        - shutdown(): Clean up resources

    Optional Methods:
        - on_signal_published(signal): Callback after signal is published
        - healthcheck(): Return health status

    Example:
        >>> class MyAgent(StrategyAgentBase):
        ...     @classmethod
        ...     def get_metadata(cls) -> AgentMetadata:
        ...         return AgentMetadata(
        ...             name="my_agent",
        ...             description="My custom agent",
        ...             version="1.0.0",
        ...             author="Me",
        ...             capabilities=[AgentCapability.MOMENTUM],
        ...             supported_symbols=["BTC/USD"],
        ...             supported_timeframes=["5m"]
        ...         )
        ...
        ...     async def initialize(self, config, redis_client):
        ...         self.config = config
        ...         self.redis = redis_client
        ...
        ...     async def generate_signals(self, market_data):
        ...         # Your signal logic here
        ...         return [signal_dict]
    """

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self._initialized = False
        self._shutdown = False

    # =========================================================================
    # REQUIRED METHODS (Must be implemented by all agents)
    # =========================================================================

    @classmethod
    @abstractmethod
    def get_metadata(cls) -> AgentMetadata:
        """
        Return agent metadata.

        This method MUST be implemented by all agents to provide
        information about the agent's capabilities and requirements.

        Returns:
            AgentMetadata describing this agent

        Example:
            @classmethod
            def get_metadata(cls) -> AgentMetadata:
                return AgentMetadata(
                    name="momentum_v1",
                    description="Momentum strategy based on MACD crossovers",
                    version="1.0.0",
                    author="Trading Team",
                    capabilities=[AgentCapability.MOMENTUM],
                    supported_symbols=["BTC/USD", "ETH/USD"],
                    supported_timeframes=["5m", "15m"],
                    risk_level="medium"
                )
        """
        pass

    @abstractmethod
    async def initialize(
        self,
        config: Dict[str, Any],
        redis_client: Optional[redis.Redis] = None
    ) -> None:
        """
        Initialize the agent with configuration and dependencies.

        This method is called once when the agent is registered and started.
        Use it to set up connections, load models, etc.

        Args:
            config: Configuration dictionary specific to this agent
            redis_client: Optional Redis client for publishing signals

        Example:
            async def initialize(self, config, redis_client):
                self.config = config
                self.redis = redis_client
                self.lookback_period = config.get("lookback_period", 20)
                self._initialized = True
                self.logger.info(f"{self.get_metadata().name} initialized")
        """
        pass

    @abstractmethod
    async def generate_signals(
        self,
        market_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Generate trading signals based on market data.

        This is the core method where your strategy logic goes.
        It should analyze market data and return 0 or more signals.

        Args:
            market_data: Dictionary containing market data:
                {
                    "symbol": "BTC/USD",
                    "timeframe": "5m",
                    "timestamp": 1699564800.0,
                    "ohlcv": [...],  # OHLCV candles
                    "mid_price": 52000.0,
                    "spread_bps": 2.5,
                    "volume_24h": 1000000.0
                }

        Returns:
            List of signal dictionaries in PRD-001 format:
            [
                {
                    "timestamp": float,
                    "signal_type": "entry" | "exit" | "stop",
                    "trading_pair": str,
                    "size": float,
                    "stop_loss": float (optional),
                    "take_profit": float (optional),
                    "confidence_score": float (0.0-1.0),
                    "agent_id": str
                },
                ...
            ]

        Example:
            async def generate_signals(self, market_data):
                symbol = market_data["symbol"]
                price = market_data["mid_price"]

                # Your strategy logic
                if self._should_enter(market_data):
                    return [{
                        "timestamp": time.time(),
                        "signal_type": "entry",
                        "trading_pair": symbol,
                        "size": 0.1,
                        "stop_loss": price * 0.98,
                        "take_profit": price * 1.04,
                        "confidence_score": 0.85,
                        "agent_id": self.get_metadata().name
                    }]

                return []  # No signals
        """
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        """
        Clean up resources and prepare for shutdown.

        Called when the agent is being stopped. Use this to close
        connections, save state, etc.

        Example:
            async def shutdown(self):
                self.logger.info(f"{self.get_metadata().name} shutting down")
                if self.redis:
                    await self.redis.close()
                self._shutdown = True
        """
        pass

    # =========================================================================
    # OPTIONAL METHODS (Can be overridden if needed)
    # =========================================================================

    async def on_signal_published(
        self,
        signal: Dict[str, Any],
        stream_name: str
    ) -> None:
        """
        Callback invoked after a signal is successfully published to Redis.

        Override this if you need to track published signals or perform
        follow-up actions.

        Args:
            signal: The signal that was published
            stream_name: Redis stream name where it was published
        """
        self.logger.debug(
            f"Signal published to {stream_name}: "
            f"{signal.get('signal_type')} {signal.get('trading_pair')}"
        )

    async def healthcheck(self) -> Dict[str, Any]:
        """
        Return health status of the agent.

        Override this to provide more detailed health information.

        Returns:
            Dictionary with health status:
            {
                "status": "healthy" | "degraded" | "unhealthy",
                "initialized": bool,
                "details": {...}
            }
        """
        return {
            "status": "healthy" if self._initialized and not self._shutdown else "unhealthy",
            "initialized": self._initialized,
            "shutdown": self._shutdown,
            "agent": self.get_metadata().name
        }

    async def on_error(self, error: Exception, context: Dict[str, Any]) -> None:
        """
        Callback invoked when an error occurs during signal generation.

        Override this for custom error handling.

        Args:
            error: The exception that occurred
            context: Context information about the error
        """
        self.logger.error(
            f"Error in {self.get_metadata().name}: {error}",
            extra=context
        )

    # =========================================================================
    # HELPER METHODS (Available to all agents)
    # =========================================================================

    def validate_signal(self, signal: Dict[str, Any]) -> bool:
        """
        Validate that a signal conforms to PRD-001 specification.

        Args:
            signal: Signal dictionary to validate

        Returns:
            True if valid, False otherwise
        """
        required_fields = [
            "timestamp",
            "signal_type",
            "trading_pair",
            "size",
            "confidence_score",
            "agent_id"
        ]

        # Check all required fields present
        for field in required_fields:
            if field not in signal:
                self.logger.error(f"Signal missing required field: {field}")
                return False

        # Validate field types
        if not isinstance(signal["timestamp"], (int, float)):
            self.logger.error("timestamp must be numeric")
            return False

        if signal["signal_type"] not in ["entry", "exit", "stop", "buy", "sell"]:
            self.logger.error(f"Invalid signal_type: {signal['signal_type']}")
            return False

        if not isinstance(signal["size"], (int, float)) or signal["size"] <= 0:
            self.logger.error("size must be positive number")
            return False

        if not (0.0 <= signal["confidence_score"] <= 1.0):
            self.logger.error("confidence_score must be in [0.0, 1.0]")
            return False

        return True

    def is_initialized(self) -> bool:
        """Check if agent is initialized"""
        return self._initialized

    def is_shutdown(self) -> bool:
        """Check if agent has been shutdown"""
        return self._shutdown


# =============================================================================
# PUBLIC API
# =============================================================================

__all__ = [
    "StrategyAgentBase",
    "AgentMetadata",
    "AgentCapability",
]


# =============================================================================
# USAGE EXAMPLE
# =============================================================================

if __name__ == "__main__":
    """
    Example showing how to create a simple agent.

    This demonstrates the minimal requirements for an agent.
    """
    import time

    class ExampleAgent(StrategyAgentBase):
        """Minimal example agent"""

        @classmethod
        def get_metadata(cls) -> AgentMetadata:
            return AgentMetadata(
                name="example_agent",
                description="Example agent for documentation",
                version="1.0.0",
                author="Platform Team",
                capabilities=[AgentCapability.CUSTOM],
                supported_symbols=["BTC/USD"],
                supported_timeframes=["5m"]
            )

        async def initialize(self, config, redis_client=None):
            self.config = config
            self.redis = redis_client
            self._initialized = True
            self.logger.info("ExampleAgent initialized")

        async def generate_signals(self, market_data):
            # Simple example: always return a buy signal
            return [{
                "timestamp": time.time(),
                "signal_type": "entry",
                "trading_pair": market_data["symbol"],
                "size": 0.1,
                "confidence_score": 0.5,
                "agent_id": self.get_metadata().name
            }]

        async def shutdown(self):
            self.logger.info("ExampleAgent shutting down")
            self._shutdown = True

    # Test the agent
    async def test():
        agent = ExampleAgent()
        await agent.initialize({"lookback": 20})

        market_data = {
            "symbol": "BTC/USD",
            "timeframe": "5m",
            "mid_price": 50000.0
        }

        signals = await agent.generate_signals(market_data)
        print(f"Generated {len(signals)} signals: {signals}")

        await agent.shutdown()

    asyncio.run(test())
