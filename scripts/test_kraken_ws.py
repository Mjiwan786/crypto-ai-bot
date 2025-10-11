import asyncio
import websockets
import json

async def test_ws():
    url = "wss://ws.kraken.com"
    async with websockets.connect(url) as ws:
        await ws.send(json.dumps({
            "event": "subscribe",
            "pair": ["BTC/USD"],
            "subscription": {"name": "trade"}
        }))
        while True:
            msg = await ws.recv()
            print(msg)

asyncio.run(test_ws())
