"""
Context manager for the Model Context Protocol (MCP).

This class orchestrates the storage and retrieval of conversation
context.  It supports in‑memory storage, JSON file persistence and
optional Redis backends for distributed deployments.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List, Optional

from pydantic import BaseModel

from .schemas import ConversationContext, Message
from .redis_client import RedisClient
from config.config_loader import ContextSettings


class ContextManager:
    """Manages the conversational context for agents."""

    def __init__(self, settings: ContextSettings, storage_path: str = ".context_history.json") -> None:
        self.settings = settings
        self.context = ConversationContext(max_length=settings.history_length)
        self.storage_path = Path(storage_path)
        self.redis_client: Optional[RedisClient] = None
        if settings.redis_enabled:
            self.redis_client = RedisClient(settings.redis_url)
        # Attempt to load existing context from storage
        self.load()

    def add_message(self, message: Message) -> None:
        """Add a message to the context and trim if necessary."""
        self.context.add_message(message)

    def get_messages(self) -> List[Message]:
        """Return a copy of the current message history."""
        return list(self.context.messages)

    def persist(self) -> None:
        """Persist the context to disk or Redis depending on configuration."""
        if self.redis_client:
            self.redis_client.store_context(self.context)
        else:
            try:
                with self.storage_path.open("w", encoding="utf-8") as f:
                    json.dump(self.context.to_json_serialisable(), f, default=str, indent=2)
            except Exception as exc:  # pylint: disable=broad-except
                # Logging not imported here to avoid circular import
                print(f"Warning: failed to persist context to disk: {exc}")

    def load(self) -> None:
        """Attempt to load previously persisted context from disk or Redis."""
        # Prefer Redis if available
        if self.redis_client:
            stored = self.redis_client.load_context()
            if stored:
                # stored is list of dicts; convert to Message objects
                for entry in stored:
                    self.context.add_message(Message(**entry))
            return

        if self.storage_path.exists():
            try:
                data = json.loads(self.storage_path.read_text())
                for entry in data:
                    self.context.add_message(Message(**entry))
            except Exception:
                # ignore malformed context file
                pass