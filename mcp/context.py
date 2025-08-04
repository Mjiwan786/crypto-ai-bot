# Context management built on top of Redis.
#
# This module exposes a pair of convenience functions for reading and writing
# arbitrary string values into a shared Redis keyspace.  Agents and other
# components of the system should exclusively use these helpers rather than
# interacting with Redis directly.  This indirection makes it possible to
# substitute other persistence mechanisms in the future if needed.

from mcp.redis_manager import get_redis

redis = get_redis()


def set_context(key: str, value: str) -> None:
    """Persist a context value.

    Args:
        key: The key under which to store the value.
        value: A UTF‑8 string to store.
    """
    redis.set(key, value)


def get_context(key: str) -> str | None:
    """Retrieve a context value.

    Returns the string previously stored for ``key`` or ``None`` if the key
    does not exist.

    Args:
        key: The key to look up.

    Returns:
        The stored string or ``None``.
    """
    return redis.get(key)