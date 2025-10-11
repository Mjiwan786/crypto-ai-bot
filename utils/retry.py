
"""Retry decorator."""
import functools
import time

def retry(retries: int = 3, delay: float = 0.5):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            last_exc = None
            for _ in range(retries):
                try:
                    return fn(*args, **kwargs)
                except Exception as exc:
                    last_exc = exc
                    time.sleep(delay)
            raise last_exc
        return wrapper
    return decorator
