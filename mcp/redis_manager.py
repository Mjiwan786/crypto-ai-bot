# This module centralizes all Redis configuration for the Model Context Protocol (MCP).
#
# Rather than scattering connection details throughout the code base, we define a
# single connection URL here and provide a helper to return a configured client.
# Downstream modules import ``get_redis`` to obtain the shared client.  If the
# connection cannot be established, a ``RuntimeError`` will be raised to signal
# a fatal configuration problem.

from redis import Redis
from redis.exceptions import ConnectionError

# Remote Redis Cloud connection string.  Update this value whenever the
# deployment target changes.  Credentials are supplied here rather than
# pulled from the environment to ease debugging and testing.
REDIS_URL = (
    "redis://default:inwjuBWkh4rAtGnbQkLBuPkHXSmfokn8"
    "@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818"
)


def get_redis() -> Redis:
    """Return a Redis client configured to talk to the Redis Cloud instance.

    The client returned by this function will decode responses as UTF‑8
    strings automatically.  Should the underlying socket be unreachable
    due to networking issues or invalid credentials, a ``RuntimeError``
    is raised with an explanatory message.

    Returns:
        An instance of :class:`redis.Redis` connected to the remote server.
    """
    try:
        return Redis.from_url(REDIS_URL, decode_responses=True)
    except ConnectionError as exc:
        # Normalise Redis connection errors into a single, descriptive exception
        raise RuntimeError("Failed to connect to Redis Cloud.") from exc