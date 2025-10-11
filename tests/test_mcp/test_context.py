import asyncio
import pytest

from mcp.mocks import FakeRedisManager
from mcp.context import MCPContext
from mcp.schemas import (
    Signal, Side, OrderIntent, OrderType, OrderAck, OrderStatus, 
    Fill, ContextSnapshot, Metric
)

@pytest.mark.anyio
async def test_context_signal_and_fill_flow():
    rm = FakeRedisManager()
    ctx = MCPContext(manager=rm)
    async with rm:
        s = Signal(
            strategy="ema", exchange="binance", symbol="BTC/USDT", 
            side=Side.BUY, confidence=0.8, size_quote_usd=50.0
        )
        sid = await ctx.emit_signal(s)
        assert isinstance(sid, str)

        async def consume_one():
            it = ctx.stream_signals(start_id="0-0")
            return await asyncio.wait_for(it.__anext__(), timeout=1.0)

        got = await consume_one()
        assert got.id == s.id

        f = Fill(price=100.0, qty=1.0, side=Side.BUY, fee=0.0, trade_id="t1")
        fid = await ctx.record_fill(f)
        assert isinstance(fid, str)

        async def consume_fill():
            it = ctx.stream_fills(start_id="0-0")
            return await asyncio.wait_for(it.__anext__(), timeout=1.0)

        gfill = await consume_fill()
        assert gfill.trade_id == "t1"

@pytest.mark.anyio
async def test_context_orders_acks_snapshot_metrics():
    rm = FakeRedisManager()
    ctx = MCPContext(manager=rm)
    async with rm:
        o = OrderIntent(client_id="c1", type=OrderType.MARKET, price=None, qty=1.0)
        oid = await ctx.emit_order(o)
        assert isinstance(oid, str)

        # Ack via pubsub
        async def ack_listener():
            it = ctx.stream_order_acks()
            return await asyncio.wait_for(it.__anext__(), timeout=1.0)

        task = asyncio.create_task(ack_listener())
        ack = OrderAck(exchange_order_id="ex1", status=OrderStatus.ACCEPTED)
        await rm.publish(rm.channel("order_acks"), ack.to_json())
        got = await task
        assert got.exchange_order_id == "ex1"

        # Snapshot
        snap = ContextSnapshot(
            env="paper", balances={"USDT": 1000.0}, 
            open_positions=[], last_prices={}
        )
        await ctx.put_snapshot(snap)
        back = await ctx.get_latest_snapshot()
        assert back and back.env == "paper"

        # Metric
        async def metric_listener():
            it = ctx.stream_metrics(name="orders_total")
            return await asyncio.wait_for(it.__anext__(), timeout=1.0)

        mt = asyncio.create_task(metric_listener())
        await ctx.push_metric(Metric(name="orders_total", value=1.0, labels={"env": "paper"}))
        gotm = await mt
        assert gotm.value == 1.0
