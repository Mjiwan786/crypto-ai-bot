import asyncio

import pytest
from crypto_ai_bot.agents.core.scalper_agent import run_scalper_agent
from crypto_ai_bot.scalper.data.ws_client import Tick


@pytest.mark.asyncio
async def test_scalper_agent_runs_briefly(monkeypatch):
    # Patch the tick stream to generate a few ticks then stop
    async def dummy_stream(symbol: str, ws_url=None):
        for i in range(3):
            yield Tick(ts=float(i), price=100 + i, volume=1.0, side="buy")

    monkeypatch.setattr("crypto_ai_bot.scalper.data.ws_client.stream_ticks", dummy_stream)
    # Run the agent in a task and cancel after a short delay
    task = asyncio.create_task(run_scalper_agent("crypto_ai_bot/config/settings.yaml"))
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
