#!/usr/bin/env python3
"""
Minimal Kraken → Redis ingestor (trades + 15s OHLC) for crypto-ai-bot.
- Works with redis-py 6.x (no SSL kwargs; uses rediss://)
- Publishes to the env-configured streams:
    STREAM_MD_TRADES=md:trades
    STREAM_MD_CANDLES=md:candles
- Conservative, safe, no orders. Ctrl+C to stop.

Usage:
  python scripts/kraken_ingestor_min.py --pairs BTC/USD ETH/USD SOL/USD --verbose
"""

from __future__ import annotations
import os
import sys
import json
import argparse
import logging
import asyncio
from typing import List, Dict

import redis
import websockets
from agents.infrastructure.redis_client import create_kraken_ingestor_redis_client

LOG = logging.getLogger("kraken_ingestor_min")

WS_URL = "wss://ws.kraken.com"


def getenv_list(key: str, default: str = "", sep: str = ",") -> List[str]:
    v = os.getenv(key, default)
    return [s.strip() for s in v.split(sep) if s.strip()]


def to_kraken_pair(pair: str) -> str:
    # Kraken uses XBT for BTC in spot pairs
    base, quote = [p.strip().upper() for p in pair.split("/")]
    if base == "BTC":
        base = "XBT"
    return f"{base}/{quote}"


def get_env_streams() -> Dict[str, str]:
    return {
        "trades": os.getenv("STREAM_MD_TRADES", "md:trades"),
        "candles": os.getenv("STREAM_MD_CANDLES", "md:candles"),
    }


async def make_redis() -> redis.Redis:
    """Create Redis client using Redis Cloud client utility."""
    url = os.getenv("REDIS_URL")
    if not url or not url.startswith("rediss://"):
        raise SystemExit("REDIS_URL must be set and start with rediss://")
    return await create_kraken_ingestor_redis_client()


async def kraken_loop(pairs: List[str], r: redis.Redis, streams: Dict[str, str], ohlc_secs: int = 15):
    k_pairs = [to_kraken_pair(p) for p in pairs]
    LOG.info("Connecting to Kraken WS: %s", WS_URL)
    try:
        async with websockets.connect(WS_URL, ping_interval=20, close_timeout=5) as ws:
            # Subscribe to trades
            sub_trades = {"event": "subscribe", "pair": k_pairs, "subscription": {"name": "trade"}}
            await ws.send(json.dumps(sub_trades))
            LOG.info("Subscribed to trades: %s", k_pairs)

            # Subscribe to OHLC
            sub_ohlc = {"event": "subscribe", "pair": k_pairs, "subscription": {"name": "ohlc", "interval": ohlc_secs}}
            await ws.send(json.dumps(sub_ohlc))
            LOG.info("Subscribed to ohlc[%ss]: %s", ohlc_secs, k_pairs)

            while True:
                raw = await ws.recv()
                msg = json.loads(raw)

                # Heartbeats & status
                if isinstance(msg, dict) and msg.get("event") in {"systemStatus", "subscriptionStatus", "heartbeat"}:
                    LOG.debug("CTRL: %s", msg)
                    continue

                # Trade message format (array):
                # [channelID, [ [price, volume, time, side, ordertype, misc], ... ], "trade", "PAIR"]
                if isinstance(msg, list) and len(msg) >= 4 and msg[-2] == "trade":
                    pair = msg[-1]
                    for trade in msg[1]:
                        try:
                            price = trade[0]
                            volume = trade[1]
                            ts = trade[2]  # epoch sec with fraction
                            side = trade[3]  # "b"/"s"
                            otype = trade[4]  # "m" or "l"
                            fields = {
                                "pair": pair,
                                "price": str(price),
                                "volume": str(volume),
                                "ts": str(int(float(ts) * 1000)),
                                "side": side,
                                "otype": otype,
                            }
                            r.xadd(
                                streams["trades"],
                                fields,
                                maxlen=int(os.getenv("STREAM_MAXLEN_TRADES", "50000") or 50000),
                                approximate=True,
                            )
                        except Exception as e:
                            LOG.warning("Trade parse/publish error: %s | raw=%s", e, trade)

                # OHLC message format (array):
                # [channelID, {"time":"169...","et":"...","open":"...","high":"...","low":"...","close":"...","v":"...","trades":n,"interval":N}, "ohlc-<N>", "PAIR"]
                if isinstance(msg, list) and len(msg) >= 4 and str(msg[-2]).startswith("ohlc-"):
                    pair = msg[-1]
                    o = msg[1]
                    try:
                        fields = {
                            "pair": pair,
                            "interval": str(o.get("interval")),
                            "t": str(int(float(o.get("time")) * 1000)) if o.get("time") else "",
                            "o": str(o.get("open")),
                            "h": str(o.get("high")),
                            "l": str(o.get("low")),
                            "c": str(o.get("close")),
                            "v": str(o.get("v")),
                            "trades": str(o.get("trades")),
                        }
                        r.xadd(
                            streams["candles"],
                            fields,
                            maxlen=int(os.getenv("STREAM_MAXLEN_CANDLES", "20000") or 20000),
                            approximate=True,
                        )
                    except Exception as e:
                        LOG.warning("OHLC parse/publish error: %s | raw=%s", e, o)
    except Exception as e:
        LOG.error("Kraken WS connection failed: %s", e)
        # Metrics instrumentation for disconnect
        try:
            from monitoring.metrics_exporter import inc_ingestor_disconnect
            inc_ingestor_disconnect(source="kraken_ws")
        except ImportError:
            pass  # Metrics not available
        
        # Discord alert for connection failure
        try:
            from monitoring.discord_alerts import send_system_alert
            send_system_alert(
                "kraken", 
                f"WebSocket connection failed: {e}", 
                "ERROR",
                component="kraken_ingestor_min",
                error=str(e)
            )
        except ImportError:
            pass  # Discord alerts not available
        except Exception:
            pass  # Don't fail on Discord errors
        
        raise


async def main_async(pairs: List[str], verbose: bool):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s | %(levelname)s | %(message)s")

    if not pairs:
        # fallback to TRADING_PAIRS from .env
        pairs = getenv_list("TRADING_PAIRS", "BTC/USD,ETH/USD,SOL/USD")

    r = await make_redis()
    # quick handshake
    if not await r.ping():
        raise SystemExit("Redis PING failed.")

    streams = get_env_streams()
    LOG.info("Publishing to streams: trades=%s candles=%s", streams["trades"], streams["candles"])
    LOG.info("Pairs: %s", pairs)
    await kraken_loop(pairs, r, streams, ohlc_secs=15)


def main():
    ap = argparse.ArgumentParser(description="Minimal Kraken→Redis ingestor")
    ap.add_argument("--pairs", nargs="*", help="Pairs like BTC/USD ETH/USD ...")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    try:
        asyncio.run(main_async(args.pairs or [], args.verbose))
    except KeyboardInterrupt:
        print("\nBye.")
    except Exception as e:
        LOG.exception("Fatal error: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
