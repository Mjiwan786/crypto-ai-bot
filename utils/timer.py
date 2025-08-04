# Timing utility.

import time
from contextlib import contextmanager


@contextmanager
def timer(name: str):
    start = time.time()
    yield
    end = time.time()
    print(f"[{name}] elapsed {end - start:.2f}s")