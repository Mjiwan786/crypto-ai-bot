# This module defines a simple key/value context built on top of Redis.
# It centralizes the storage of transient state across the AI engine and its agents.

from mcp.redis_manager import get_redis

# Instantiate a shared Redis connection for the context.  By instantiating
# the connection at module load time we ensure that every caller imports
# the same Redis client instance rather than creating a new one on every
# call.  Connection details are defined in ``mcp/redis_manager.py``.
redis = get_redis()

def set_context(key: str, value: str) -> None:
    """Persist a context value.

    This function stores the string ``value`` under the given ``key`` in
    Redis.  Values will be available to all other components that read
    from the same key.  Use strings exclusively here to avoid implicit
    encoding/decoding mismatches.

    Args:
        key: The name of the context variable to set.
        value: The string value to persist.
    """
    redis.set(key, value)


def get_context(key: str) -> str | None:
    """Retrieve a context value.

    Fetches the value previously stored under ``key`` from Redis.  If no
    value has been stored yet the call returns ``None``.  Callers are
    responsible for casting the returned string back to the desired type.

    Args:
        key: The name of the context variable to look up.

    Returns:
        A string if one was stored or ``None`` if the key is absent.
    """
    return redis.get(key)