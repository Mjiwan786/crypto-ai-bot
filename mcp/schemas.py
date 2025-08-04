# Stub definitions for context serialization and storage.
#
# In a fully fledged implementation these schemas would likely be Pydantic
# models or dataclasses describing the shape of various pieces of state that
# need to be persisted.  For the purpose of this exercise we provide simple
# helper functions that serialize dictionaries to JSON and store them via
# Redis.  Consumers can call :func:`load_schema` to retrieve the data again.

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from mcp.redis_manager import get_redis

redis = get_redis()


def save_schema(key: str, data: Dict[str, Any]) -> None:
    """Serialize and persist a dictionary under ``key``.

    Args:
        key: The Redis key under which to store the serialized data.
        data: A dictionary of data to be JSON encoded.
    """
    redis.set(key, json.dumps(data))


def load_schema(key: str) -> Optional[Dict[str, Any]]:
    """Retrieve and deserialize a dictionary previously saved.

    Args:
        key: The Redis key to look up.

    Returns:
        The decoded dictionary if present, otherwise ``None``.
    """
    raw = redis.get(key)
    return json.loads(raw) if raw is not None else None