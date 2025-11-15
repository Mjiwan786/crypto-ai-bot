"""
Agent Registry - Plugin Discovery and Management System

This module provides the registry system for discovering, registering, and
instantiating strategy agents without core rewrites.

Features:
- Auto-discovery via Python entry points
- Manual agent registration
- Agent filtering by capabilities, symbols, timeframes
- Singleton pattern for global registry access
- Thread-safe operations

Usage:
    from agents.base.agent_registry import AgentRegistry, register_agent
    from agents.base.strategy_agent_base import StrategyAgentBase

    # Register an agent
    @register_agent
    class MyAgent(StrategyAgentBase):
        ...

    # Or manually
    AgentRegistry.register("my_agent", MyAgent)

    # Discover agents
    registry = AgentRegistry.get_instance()
    agents = registry.list_agents()
    agent = registry.get_agent("my_agent")
"""

from __future__ import annotations

import logging
import threading
from typing import Dict, List, Optional, Type, Any

from agents.base.strategy_agent_base import (
    StrategyAgentBase,
    AgentMetadata,
    AgentCapability
)

logger = logging.getLogger(__name__)


# =============================================================================
# AGENT REGISTRY
# =============================================================================

class AgentRegistry:
    """
    Global registry for strategy agents.

    Singleton pattern ensures single source of truth for all agents.
    Thread-safe for concurrent access.

    Attributes:
        _agents: Dictionary mapping agent names to agent classes
        _instances: Dictionary mapping agent names to agent instances
        _lock: Thread lock for thread-safe operations
    """

    _instance: Optional[AgentRegistry] = None
    _lock = threading.RLock()

    def __init__(self):
        """Initialize registry. Use get_instance() instead."""
        self._agents: Dict[str, Type[StrategyAgentBase]] = {}
        self._instances: Dict[str, StrategyAgentBase] = {}
        self._metadata_cache: Dict[str, AgentMetadata] = {}
        self.logger = logging.getLogger(self.__class__.__name__)

    @classmethod
    def get_instance(cls) -> AgentRegistry:
        """
        Get the global registry instance (singleton).

        Returns:
            The global AgentRegistry instance
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
                    cls._instance.logger.info("AgentRegistry initialized")
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """
        Reset the registry (mainly for testing).

        Clears all registered agents and instances.
        """
        with cls._lock:
            if cls._instance is not None:
                cls._instance._agents.clear()
                cls._instance._instances.clear()
                cls._instance._metadata_cache.clear()
                cls._instance.logger.info("AgentRegistry reset")

    def register(
        self,
        agent_class: Type[StrategyAgentBase],
        override: bool = False
    ) -> None:
        """
        Register an agent class in the registry.

        Args:
            agent_class: Agent class (must inherit from StrategyAgentBase)
            override: If True, override existing agent with same name

        Raises:
            ValueError: If agent_class is not a StrategyAgentBase subclass
            KeyError: If agent already registered and override=False

        Example:
            registry = AgentRegistry.get_instance()
            registry.register(MyAgent)
        """
        if not issubclass(agent_class, StrategyAgentBase):
            raise ValueError(
                f"{agent_class.__name__} must inherit from StrategyAgentBase"
            )

        with self._lock:
            # Get metadata from class
            metadata = agent_class.get_metadata()
            agent_name = metadata.name

            # Check if already registered
            if agent_name in self._agents and not override:
                raise KeyError(
                    f"Agent '{agent_name}' already registered. "
                    f"Use override=True to replace."
                )

            # Register agent
            self._agents[agent_name] = agent_class
            self._metadata_cache[agent_name] = metadata

            self.logger.info(
                f"✅ Registered agent: {agent_name} "
                f"(v{metadata.version}, capabilities: {[c.value for c in metadata.capabilities]})"
            )

    def unregister(self, agent_name: str) -> None:
        """
        Unregister an agent.

        Args:
            agent_name: Name of agent to unregister

        Raises:
            KeyError: If agent not found
        """
        with self._lock:
            if agent_name not in self._agents:
                raise KeyError(f"Agent '{agent_name}' not registered")

            # Shutdown instance if exists
            if agent_name in self._instances:
                instance = self._instances[agent_name]
                # Schedule async shutdown (best effort)
                import asyncio
                try:
                    asyncio.create_task(instance.shutdown())
                except RuntimeError:
                    # No event loop, skip async shutdown
                    pass
                del self._instances[agent_name]

            del self._agents[agent_name]
            del self._metadata_cache[agent_name]

            self.logger.info(f"Unregistered agent: {agent_name}")

    def get_agent_class(self, agent_name: str) -> Type[StrategyAgentBase]:
        """
        Get agent class by name.

        Args:
            agent_name: Name of agent

        Returns:
            Agent class

        Raises:
            KeyError: If agent not found
        """
        with self._lock:
            if agent_name not in self._agents:
                raise KeyError(
                    f"Agent '{agent_name}' not registered. "
                    f"Available: {list(self._agents.keys())}"
                )
            return self._agents[agent_name]

    async def get_agent_instance(
        self,
        agent_name: str,
        config: Optional[Dict[str, Any]] = None,
        redis_client: Optional[Any] = None,
        force_new: bool = False
    ) -> StrategyAgentBase:
        """
        Get or create agent instance.

        If instance already exists, returns it (unless force_new=True).
        If not, creates new instance and initializes it.

        Args:
            agent_name: Name of agent
            config: Configuration for agent initialization
            redis_client: Redis client for agent
            force_new: If True, create new instance even if exists

        Returns:
            Initialized agent instance

        Raises:
            KeyError: If agent not found
        """
        with self._lock:
            # Return existing instance if available
            if agent_name in self._instances and not force_new:
                return self._instances[agent_name]

            # Create new instance
            agent_class = self.get_agent_class(agent_name)
            instance = agent_class()

            # Initialize
            await instance.initialize(config or {}, redis_client)

            # Cache instance
            self._instances[agent_name] = instance

            self.logger.info(f"Created instance of {agent_name}")
            return instance

    def get_metadata(self, agent_name: str) -> AgentMetadata:
        """
        Get metadata for an agent.

        Args:
            agent_name: Name of agent

        Returns:
            Agent metadata

        Raises:
            KeyError: If agent not found
        """
        with self._lock:
            if agent_name not in self._metadata_cache:
                # Fetch metadata if not cached
                agent_class = self.get_agent_class(agent_name)
                self._metadata_cache[agent_name] = agent_class.get_metadata()
            return self._metadata_cache[agent_name]

    def list_agents(
        self,
        capability: Optional[AgentCapability] = None,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None
    ) -> List[str]:
        """
        List registered agents with optional filtering.

        Args:
            capability: Filter by capability (e.g., SCALPING)
            symbol: Filter by supported symbol (e.g., "BTC/USD")
            timeframe: Filter by supported timeframe (e.g., "5m")

        Returns:
            List of agent names matching filters

        Example:
            # Get all agents
            all_agents = registry.list_agents()

            # Get only scalping agents
            scalpers = registry.list_agents(capability=AgentCapability.SCALPING)

            # Get agents that support BTC/USD on 5m timeframe
            btc_agents = registry.list_agents(symbol="BTC/USD", timeframe="5m")
        """
        with self._lock:
            agent_names = list(self._agents.keys())

            # Apply filters
            if capability is not None:
                agent_names = [
                    name for name in agent_names
                    if capability in self.get_metadata(name).capabilities
                ]

            if symbol is not None:
                agent_names = [
                    name for name in agent_names
                    if symbol in self.get_metadata(name).supported_symbols
                    or "*" in self.get_metadata(name).supported_symbols
                ]

            if timeframe is not None:
                agent_names = [
                    name for name in agent_names
                    if timeframe in self.get_metadata(name).supported_timeframes
                    or "*" in self.get_metadata(name).supported_timeframes
                ]

            return agent_names

    def get_all_metadata(self) -> Dict[str, AgentMetadata]:
        """
        Get metadata for all registered agents.

        Returns:
            Dictionary mapping agent names to metadata
        """
        with self._lock:
            return {
                name: self.get_metadata(name)
                for name in self._agents.keys()
            }

    def is_registered(self, agent_name: str) -> bool:
        """
        Check if an agent is registered.

        Args:
            agent_name: Name of agent

        Returns:
            True if registered, False otherwise
        """
        with self._lock:
            return agent_name in self._agents

    def count(self) -> int:
        """
        Get number of registered agents.

        Returns:
            Number of registered agents
        """
        with self._lock:
            return len(self._agents)

    async def shutdown_all(self) -> None:
        """
        Shutdown all agent instances.

        Calls shutdown() on all instantiated agents.
        """
        with self._lock:
            for agent_name, instance in self._instances.items():
                try:
                    await instance.shutdown()
                    self.logger.info(f"Shutdown {agent_name}")
                except Exception as e:
                    self.logger.error(f"Error shutting down {agent_name}: {e}")

            self._instances.clear()


# =============================================================================
# DECORATOR FOR EASY REGISTRATION
# =============================================================================

def register_agent(agent_class: Type[StrategyAgentBase]) -> Type[StrategyAgentBase]:
    """
    Decorator to automatically register an agent.

    Usage:
        @register_agent
        class MyAgent(StrategyAgentBase):
            ...

    Args:
        agent_class: Agent class to register

    Returns:
        The same agent class (for chaining)
    """
    registry = AgentRegistry.get_instance()
    registry.register(agent_class)
    return agent_class


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def get_registry() -> AgentRegistry:
    """Get the global agent registry."""
    return AgentRegistry.get_instance()


def register(agent_class: Type[StrategyAgentBase], override: bool = False) -> None:
    """Register an agent class."""
    get_registry().register(agent_class, override)


def list_agents(**filters) -> List[str]:
    """List registered agents with optional filters."""
    return get_registry().list_agents(**filters)


async def get_agent(
    agent_name: str,
    config: Optional[Dict[str, Any]] = None,
    redis_client: Optional[Any] = None
) -> StrategyAgentBase:
    """Get or create agent instance."""
    return await get_registry().get_agent_instance(agent_name, config, redis_client)


# =============================================================================
# PUBLIC API
# =============================================================================

__all__ = [
    "AgentRegistry",
    "register_agent",
    "get_registry",
    "register",
    "list_agents",
    "get_agent",
]


# =============================================================================
# AUTO-DISCOVERY (Optional - for entry points)
# =============================================================================

def discover_agents() -> None:
    """
    Auto-discover agents via Python entry points.

    Add this to your setup.py to enable auto-discovery:
        entry_points={
            'crypto_ai_bot.agents': [
                'my_agent = my_module:MyAgent',
            ]
        }

    Then call discover_agents() at startup to auto-register all agents.
    """
    try:
        import pkg_resources

        for entry_point in pkg_resources.iter_entry_points('crypto_ai_bot.agents'):
            try:
                agent_class = entry_point.load()
                get_registry().register(agent_class)
                logger.info(f"Auto-discovered agent: {entry_point.name}")
            except Exception as e:
                logger.error(f"Failed to load agent {entry_point.name}: {e}")

    except ImportError:
        logger.debug("pkg_resources not available, skipping auto-discovery")


# =============================================================================
# USAGE EXAMPLE
# =============================================================================

if __name__ == "__main__":
    """Example usage of agent registry"""
    import asyncio
    import time
    from agents.base.strategy_agent_base import StrategyAgentBase, AgentMetadata, AgentCapability

    # Define a simple agent
    @register_agent
    class ExampleScalper(StrategyAgentBase):
        @classmethod
        def get_metadata(cls) -> AgentMetadata:
            return AgentMetadata(
                name="example_scalper",
                description="Example scalping agent",
                version="1.0.0",
                author="Platform Team",
                capabilities=[AgentCapability.SCALPING],
                supported_symbols=["BTC/USD", "ETH/USD"],
                supported_timeframes=["1m", "5m"]
            )

        async def initialize(self, config, redis_client=None):
            self._initialized = True
            self.logger.info("ExampleScalper initialized")

        async def generate_signals(self, market_data):
            return [{
                "timestamp": time.time(),
                "signal_type": "entry",
                "trading_pair": market_data["symbol"],
                "size": 0.05,
                "confidence_score": 0.75,
                "agent_id": self.get_metadata().name
            }]

        async def shutdown(self):
            self._shutdown = True

    async def main():
        registry = AgentRegistry.get_instance()

        # List all agents
        print(f"Registered agents: {registry.list_agents()}")

        # Get metadata
        metadata = registry.get_metadata("example_scalper")
        print(f"Agent metadata: {metadata.name} - {metadata.description}")

        # Get instance
        agent = await registry.get_agent_instance("example_scalper", {"param": 123})

        # Generate signals
        market_data = {"symbol": "BTC/USD", "mid_price": 50000.0}
        signals = await agent.generate_signals(market_data)
        print(f"Generated signals: {signals}")

        # Shutdown
        await registry.shutdown_all()

    asyncio.run(main())
