"""Utility functions for connecting to a Redis database.

This module reads connection details from environment variables and exposes helper
functions to obtain and close a Redis connection.  The pattern of loading
environment variables from a `.env` file is common practice; using `python‑dotenv`
to load the file keeps your configuration out of source control【511646157036576†L160-L169】.

Example usage:

```python
from utils.redis_connection import get_redis_connection, close_connection

redis_conn = get_redis_connection()
if redis_conn:
    redis_conn.set('foo', 'bar')
    print(redis_conn.get('foo'))
    close_connection(redis_conn)
```

When you create your own `.env` file, populate it with `REDIS_HOST`,
`REDIS_PORT` and `REDIS_PASSWORD` as shown in `.env.example`【159958007288812†L68-L103】.
"""

import os
from dotenv import load_dotenv
import redis


# Load environment variables from a local `.env` file (if present).  If the file
# does not exist or a variable is undefined it will fall back to the system
# environment.  This call is idempotent and safe to call multiple times【511646157036576†L177-L190】.
load_dotenv()


def get_redis_connection():
    """Establish and return a Redis connection.

    The function reads the host, port and password from environment variables
    `REDIS_HOST`, `REDIS_PORT` and `REDIS_PASSWORD`.  It attempts to
    authenticate and ping the server; if successful, the connection object is
    returned.  Otherwise, it prints an error and returns ``None``【159958007288812†L68-L103】.

    Returns:
        redis.Redis | None: A Redis connection or ``None`` on failure.
    """
    host = os.getenv('REDIS_HOST', 'localhost')
    port_str = os.getenv('REDIS_PORT', '6379')
    try:
        port = int(port_str)
    except ValueError:
        port = 6379
    password = os.getenv('REDIS_PASSWORD')

    try:
        connection = redis.Redis(
            host=host,
            port=port,
            password=password,
            decode_responses=True
        )
        # Test the connection by issuing a ping
        connection.ping()
        return connection
    except redis.ConnectionError as e:
        print(f"Error connecting to Redis at {host}:{port}: {e}")
        return None


def close_connection(connection: redis.Redis | None) -> None:
    """Close a Redis connection.

    Parameters:
        connection (redis.Redis | None): The connection to close.  If ``None``
            is passed, the function does nothing.
    """
    if connection:
        try:
            connection.close()
        except Exception as e:  # pylint: disable=broad-except
            print(f"Error while closing Redis connection: {e}")