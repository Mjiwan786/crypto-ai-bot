#!/usr/bin/env python3
"""
Wait for Redis connection script.

Reads REDIS_URL from environment, attempts PING every 1 second
up to --timeout seconds. Exits 0 on success, 1 on failure.
Supports both redis:// and rediss:// protocols.
"""

import argparse
import os
import sys
import time
from urllib.parse import urlparse

try:
    import redis
except ImportError:
    print("ERROR: redis package not installed", file=sys.stderr)
    sys.exit(1)


def parse_redis_url(url: str) -> dict:
    """Parse Redis URL and return connection parameters."""
    parsed = urlparse(url)
    
    # Handle rediss:// (Redis with SSL)
    ssl = parsed.scheme == 'rediss'
    
    # Extract connection parameters
    params = {
        'host': parsed.hostname or 'localhost',
        'port': parsed.port or (6380 if ssl else 6379),
        'password': parsed.password,
        'ssl': ssl,
        'ssl_cert_reqs': None,  # Don't verify SSL certificates
    }
    
    # Handle database number from path
    if parsed.path and len(parsed.path) > 1:
        try:
            params['db'] = int(parsed.path[1:])
        except ValueError:
            pass
    
    # Remove None values
    return {k: v for k, v in params.items() if v is not None}


def wait_for_redis(redis_url: str, timeout: int) -> bool:
    """
    Wait for Redis connection to be available.
    
    Args:
        redis_url: Redis connection URL
        timeout: Maximum time to wait in seconds
        
    Returns:
        True if connection successful, False otherwise
    """
    print(f"Attempting to connect to Redis: {redis_url}")
    print(f"Timeout: {timeout} seconds")
    
    # Parse Redis URL
    try:
        conn_params = parse_redis_url(redis_url)
    except Exception as e:
        print(f"ERROR: Failed to parse Redis URL: {e}", file=sys.stderr)
        return False
    
    # Attempt connection with retries
    start_time = time.time()
    attempt = 1
    
    while time.time() - start_time < timeout:
        try:
            # Create Redis connection
            r = redis.Redis(**conn_params)
            
            # Test connection with PING
            response = r.ping()
            
            if response:
                elapsed = time.time() - start_time
                print(f"SUCCESS: Redis connection established after {elapsed:.1f}s (attempt {attempt})")
                return True
            else:
                print(f"WARN: PING returned False (attempt {attempt})")
                
        except redis.ConnectionError as e:
            print(f"Connection attempt {attempt} failed: {e}")
        except redis.TimeoutError as e:
            print(f"Connection attempt {attempt} timed out: {e}")
        except Exception as e:
            print(f"Unexpected error on attempt {attempt}: {e}")
        
        attempt += 1
        time.sleep(1)
    
    print(f"ERROR: Failed to connect to Redis after {timeout} seconds", file=sys.stderr)
    return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Wait for Redis connection to be available"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=15,
        help="Maximum time to wait in seconds (default: 15)"
    )
    parser.add_argument(
        "--redis-url",
        help="Redis URL (default: read from REDIS_URL environment variable)"
    )
    
    args = parser.parse_args()
    
    # Get Redis URL from argument or environment
    redis_url = args.redis_url or os.getenv('REDIS_URL')
    
    if not redis_url:
        print("ERROR: Redis URL not provided. Set REDIS_URL environment variable or use --redis-url", file=sys.stderr)
        sys.exit(1)
    
    # Wait for Redis connection
    success = wait_for_redis(redis_url, args.timeout)
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()



