from typing import Optional
from .schemas import MarketContext
from ..context import MarketContextManager

class BaseAgent:
    def __init__(self, context_manager: MarketContextManager):
        self.context_manager = context_manager
        self._current_context: Optional[MarketContext] = None
        
    async def refresh_context(self):
        """Refresh the agent's local context copy"""
        self._current_context = await self.context_manager.get_context()
        
    @property
    def context(self) -> MarketContext:
        """Get the current context (must call refresh_context first)"""
        if self._current_context is None:
            raise ValueError("Context not loaded - call refresh_context() first")
        return self._current_context
        
    async def update_shared_context(self, update: dict, sources: list):
        """
        Update the shared market context
        
        Args:
            update: Dictionary of fields to update
            sources: List of data sources contributing this update
        """
        await self.context_manager.update_context(update, sources=sources)
        await self.refresh_context()