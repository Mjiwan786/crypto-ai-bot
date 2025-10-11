# MCP (Model Context Protocol) – Redis Layer

**Purpose:** move signals, orders, fills, snapshots & metrics between agents using Redis Streams + Pub/Sub + KV. Fast orjson, Pydantic v2, async-first, with retries and a simple circuit breaker.

## Topics & Keys (for `BOT_ENV=paper`)
- Channels: `mcp:paper:ch:signals`, `mcp:paper:ch:order_acks`, `mcp:paper:ch:metrics`
- Streams: `mcp:paper:x:signals`, `mcp:paper:x:fills`, `mcp:paper:x:snapshots`
- KV: `mcp:paper:kv:latest_snapshot`, `mcp:paper:kv:idem`

Retention defaults via env:
- `MCP_RETENTION_SIGNALS=5000`, `MCP_RETENTION_FILLS=5000`, `MCP_RETENTION_SNAPSHOTS=1000`

## Quickstart

```py
import asyncio
from mcp import MCPContext
from mcp.schemas import Signal, Side

async def main():
    async with MCPContext() as ctx:
        await ctx.emit_signal(Signal(strategy="tf", exchange="kraken",
                                     symbol="ETH/USD", side=Side.buy,
                                     confidence=0.9, size_quote_usd=25))
        async for sig in ctx.stream_signals():
            print("got:", sig)

asyncio.run(main())
