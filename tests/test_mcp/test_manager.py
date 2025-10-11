import asyncio
import pytest

from mcp.mocks import FakeRedisManager

@pytest.mark.anyio
async def test_fake_manager_kv_and_streams():
    rm = FakeRedisManager()
    async with rm:
        key = rm.ns_key("hello")
        await rm.set_json(key, {"x": 1}, ttl=1)
        d = await rm.get_json(key)
        assert d["x"] == 1

        sid = await rm.xadd(rm.stream("test"), {"data": b"123"})
        assert isinstance(sid, str)
        rows = await rm.xread({rm.stream("test"): "0-0"})
        assert rows and rows[0][0].endswith("test")

@pytest.mark.anyio
async def test_fake_manager_pubsub():
    rm = FakeRedisManager()
    async with rm:
        ch = rm.channel("pubsub")
        async def sub():
            async for msg in rm.subscribe(ch):
                return msg
        t = asyncio.create_task(sub())
        await asyncio.sleep(0.05)
        await rm.publish(ch, b"hi")
        got = await asyncio.wait_for(t, timeout=1.0)
        assert got == b"hi"
