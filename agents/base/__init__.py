"""
Agents Base Module - Plugin Architecture Foundation

This module provides the foundation for plug-and-play agent architecture:
- StrategyAgentBase: Abstract base class for all agents
- AgentRegistry: Global registry for agent discovery and management
- Agent

Metadata: Agent capability and requirement descriptions

Quick Start:
    from agents.base import StrategyAgentBase, AgentMetadata, AgentCapability, register_agent

    @register_agent
    class MyAgent(StrategyAgentBase):
        @classmethod
        def get_metadata(cls):
            return AgentMetadata(
                name="my_agent",
                description="My custom agent",
                version="1.0.0",
                author="Me",
                capabilities=[AgentCapability.MOMENTUM],
                supported_symbols=["BTC/USD"],
                supported_timeframes=["5m"]
            )

        async def initialize(self, config, redis_client=None):
            self._initialized = True

        async def generate_signals(self, market_data):
            return []  # Your signal logic

        async def shutdown(self):
            self._shutdown = True
"""

from agents.base.strategy_agent_base import (
    StrategyAgentBase,
    AgentMetadata,
    AgentCapability,
)

from agents.base.agent_registry import (
    AgentRegistry,
    register_agent,
    get_registry,
    register,
    list_agents,
    get_agent,
    discover_agents,
)

__all__ = [
    # Base class
    "StrategyAgentBase",
    "AgentMetadata",
    "AgentCapability",

    # Registry
    "AgentRegistry",
    "register_agent",
    "get_registry",
    "register",
    "list_agents",
    "get_agent",
    "discover_agents",
]

__version__ = "1.0.0"
