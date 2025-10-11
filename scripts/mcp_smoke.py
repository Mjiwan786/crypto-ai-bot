import asyncio
from mcp.context import MCPContext
from mcp.redis_manager import RedisManager
from mcp.schemas import Signal, Side, OrderIntent, OrderType, Fill, ContextSnapshot, Metric

async def main():
    rm = RedisManager()
    ctx = MCPContext(manager=rm)
    async with rm:
        # Emit a signal
        sig = Signal(strategy="demo", exchange="binance", symbol="BTC/USDT", side=Side.BUY, confidence=0.9, size_quote_usd=10.0)
        await ctx.emit_signal(sig)

        # Emit an order
        order = OrderIntent(client_id="demo", type=OrderType.MARKET, price=None, qty=0.01)
        await ctx.emit_order(order)

        # Record a fill
        fill = Fill(price=100.0, qty=0.01, side=Side.BUY, fee=0.0, trade_id="T1")
        await ctx.record_fill(fill)

        # Snapshot
        snap = ContextSnapshot(env="paper", balances={"USDT": 1000.0}, open_positions=[], last_prices={"BTC/USDT": 100.0})
        await ctx.put_snapshot(snap)

        # Metric
        await ctx.push_metric(Metric(name="orders_total", value=1.0, labels={"env": "paper"}))

        # Consumers (signals and fills) for a few seconds
        async def consume_signals():
            async for s in ctx.stream_signals(start_id="0-0"):
                print("signal:", s.model_dump())
                break

        async def consume_fills():
            async for f in ctx.stream_fills(start_id="0-0"):
                print("fill:", f.model_dump())
                break

        tasks = [asyncio.create_task(consume_signals()), asyncio.create_task(consume_fills())]
        await asyncio.wait(tasks, timeout=3.0)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
