"""Tick replay for backtesting."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Iterable

from ..data.ws_client import Tick


async def replay_ticks(ticks: Iterable[Tick], speed: float = 1.0) -> AsyncIterator[Tick]:
    """Yield ticks at real time scaled by ``speed``.

    Args:
        ticks: Sequence of :class:`Tick` instances sorted by timestamp.
        speed: Replay speed. ``1.0`` means real time; ``2.0`` means twice
            as fast; values less than one slow down replay.

    Yields:
        Each tick in order, waiting the scaled time difference between
        consecutive ticks.
    """
    previous_ts: float | None = None
    for tick in ticks:
        if previous_ts is not None:
            delay = (tick.ts - previous_ts) / speed
            if delay > 0:
                await asyncio.sleep(delay)
        previous_ts = tick.ts
        yield tick
