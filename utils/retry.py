# Retry utility.

import time
from typing import Callable, TypeVar, Any


T = TypeVar("T")


def retry(fn: Callable[..., T], attempts: int = 3, delay: float = 1.0) -> Callable[..., T]:
    """Wrap ``fn`` with simple retry logic."""

    def wrapped(*args: Any, **kwargs: Any) -> T:
        last_exc = None
        for _ in range(attempts):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:  # pylint: disable=broad-except
                last_exc = exc
                time.sleep(delay)
        raise last_exc  # type: ignore[misc]

    return wrapped