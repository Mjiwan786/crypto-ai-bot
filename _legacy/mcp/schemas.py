# Stub definitions for context serialization and storage.
#
# In a fully fledged implementation these schemas would likely be Pydantic
# models or dataclasses describing the shape of various pieces of state that
# need to be persisted.  For the purpose of this exercise we provide simple
# helper functions that serialize dictionaries to JSON and store them via
# Redis.  Consumers can call :func:`load_schema` to retrieve the data again.
#
# SignalScore and MarketContext are lightweight dataclass stubs used by
# agents/core/execution_agent.py and agents/core/signal_analyst.py.

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from mcp.redis_manager import get_redis

# Lazy Redis client — connection is deferred until first use so that
# importing this module at test collection time does NOT trigger a
# network connection to Redis Cloud.
_redis_client = None


def _get_redis_client():
    global _redis_client
    if _redis_client is None:
        _redis_client = get_redis()
    return _redis_client


# ---------------------------------------------------------------------------
# Domain stubs used by the agent layer
# ---------------------------------------------------------------------------

@dataclass
class SignalScore:
    """Lightweight signal score object used by execution and analyst agents."""

    symbol: str = ""
    technical_score: float = 0.0
    sentiment_score: float = 0.0
    total_score: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def model_dump(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "technical_score": self.technical_score,
            "sentiment_score": self.sentiment_score,
            "total_score": self.total_score,
            "metadata": self.metadata,
        }


@dataclass
class MarketContext:
    """Market context snapshot used by MCP coordination layer."""

    sentiment_score: float = 0.0
    sentiment_trend: str = "neutral"
    regime_state: str = "neutral"
    regime_confidence: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def model_dump_json(self) -> str:
        return json.dumps({
            "sentiment_score": self.sentiment_score,
            "sentiment_trend": self.sentiment_trend,
            "regime_state": self.regime_state,
            "regime_confidence": self.regime_confidence,
            "metadata": self.metadata,
        })

    @classmethod
    def parse_raw(cls, raw: str) -> "MarketContext":
        data = json.loads(raw)
        return cls(
            sentiment_score=data.get("sentiment_score", 0.0),
            sentiment_trend=data.get("sentiment_trend", "neutral"),
            regime_state=data.get("regime_state", "neutral"),
            regime_confidence=data.get("regime_confidence", 0.0),
            metadata=data.get("metadata", {}),
        )


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def save_schema(key: str, data: Dict[str, Any]) -> None:
    """Serialize and persist a dictionary under ``key``.

    Args:
        key: The Redis key under which to store the serialized data.
        data: A dictionary of data to be JSON encoded.
    """
    _get_redis_client().set(key, json.dumps(data))


def load_schema(key: str) -> Optional[Dict[str, Any]]:
    """Retrieve and deserialize a dictionary previously saved.

    Args:
        key: The Redis key to look up.

    Returns:
        The decoded dictionary if present, otherwise ``None``.
    """
    raw = _get_redis_client().get(key)
    return json.loads(raw) if raw is not None else None