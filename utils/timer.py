
"""Timer context manager."""
import time

class Timer:
    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.end = time.perf_counter()

    @property
    def elapsed(self) -> float:
        return self.end - self.start
