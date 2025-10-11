"""
Kraken WebSocket health checker for crypto-ai-bot.

Features:
- Subscribes to trade & spread channels for given pairs
- Tracks heartbeat & data freshness windows
- Actively pings and measures pong RTT
- Detects Kraken systemStatus (maintenance/post_only/cancel_only)
- Reconnect loop with capped attempts and jittered delay
"""

from __future__ import annotations

import asyncio
import json
import time
import random
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator
import websockets


# ----------------------------- Models ----------------------------- #

class KrakenWSHealthConfig(BaseModel):
    url: str = "wss://ws.kraken.com"
    pairs: List[str] = Field(default_factory=lambda: ["BTC/USD", "ETH/USD"])

    ping_interval: int = 20               # seconds
    close_timeout: int = 5                # seconds for websockets client
    connect_timeout: float = 10.0         # seconds (ws connect + pong wait)

    max_reconnects: int = 5
    reconnect_delay: float = 3.0          # base delay (seconds)

    heartbeat_timeout: float = 60.0       # max seconds since heartbeat
    data_timeout: float = 30.0            # max seconds since data
    test_duration: float = 30.0           # total run time before success

    # Upgrades (non-breaking)
    min_messages: int = 1                 # minimal messages to consider healthy
    require_data_fresh: bool = True
    latency_warn_ms: float = 800.0        # informational only

    @field_validator("max_reconnects")
    @classmethod
    def _vr_reconnects(cls, v: int) -> int:
        if v < 1:
            raise ValueError("max_reconnects must be >= 1")
        return v

    @field_validator("reconnect_delay")
    @classmethod
    def _vr_reconnect_delay(cls, v: float) -> float:
        if v < 1.0:
            raise ValueError("reconnect_delay must be >= 1.0")
        return v


class KrakenWSHealthResult(BaseModel):
    connected: bool = False
    reconnects: int = 0
    messages_received: int = 0
    last_heartbeat: Optional[float] = None
    last_data: Optional[float] = None
    latency_ms: float = 0.0
    error_message: Optional[str] = None
    test_duration: float = 0.0
    timestamp: float = Field(default_factory=lambda: time.time())


# ----------------------------- Checker ----------------------------- #

class KrakenWSHealthChecker:
    """Runs a timed WS health test with reconnect policy."""

    def __init__(self, config: KrakenWSHealthConfig):
        self.config = config
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.last_heartbeat: Optional[float] = None
        self.last_data: Optional[float] = None
        self.messages_received: int = 0
        self.latency_ms: float = 0.0

        self.system_status: str = "online"
        self.subscribe_errors: int = 0

    # -------- Subscriptions -------- #

    def _create_subscription(self, name: str, pairs: List[str], **subscription_kwargs) -> Dict[str, Any]:
        sub = {
            "event": "subscribe",
            "pair": pairs,
            "subscription": {"name": name},
        }
        if subscription_kwargs:
            sub["subscription"].update(subscription_kwargs)
        return sub

    async def _setup_subscriptions(self) -> None:
        """Subscribe to trade and spread for configured pairs."""
        assert self.ws is not None
        subs = [
            self._create_subscription("trade", self.config.pairs, depth=10),
            self._create_subscription("spread", self.config.pairs, depth=10),
        ]
        for s in subs:
            await self.ws.send(json.dumps(s))

    # -------- Message handling -------- #

    async def _handle_message(self, raw: str) -> None:
        """Process a single WS message (dict status/heartbeat or list data)."""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            # Ignore noise
            return

        # Control-plane / status messages
        if isinstance(msg, dict):
            ev = msg.get("event")
            if ev == "systemStatus":
                self.system_status = msg.get("status", "online")
                self.messages_received += 1
                return

            if ev == "heartbeat":
                self.last_heartbeat = time.time()
                self.messages_received += 1
                return

            if ev == "subscriptionStatus":
                self.messages_received += 1
                if msg.get("status") != "subscribed":
                    self.subscribe_errors += 1
                return

            # other events ignored
            self.messages_received += 1
            return

        # Data messages: expected format: [chanId, payload, channelName, pair]
        if isinstance(msg, list) and len(msg) >= 3:
            self.last_data = time.time()
            self.messages_received += 1

    # -------- Health logic -------- #

    async def _check_health_status(self) -> bool:
        """Evaluate freshness gates and minimal activity."""
        if self.system_status not in ("online", "online_partial"):
            return False

        now = time.time()
        hb_ok = (self.last_heartbeat is not None) and ((now - self.last_heartbeat) <= self.config.heartbeat_timeout)
        data_ok = (self.last_data is not None) and ((now - self.last_data) <= self.config.data_timeout)

        msgs_ok = self.messages_received >= self.config.min_messages

        if self.config.require_data_fresh:
            return bool(hb_ok and data_ok and msgs_ok)
        return bool(hb_ok and msgs_ok)

    # -------- Connect/run cycle -------- #

    async def _connect_once(self) -> bool:
        """Single connect + receive loop. Returns True if session ran without fatal close."""
        try:
            async with websockets.connect(self.config.url, close_timeout=self.config.close_timeout) as ws:
                self.ws = ws
                await self._setup_subscriptions()

                last_ping_ts = 0.0
                async for raw in ws:
                    await self._handle_message(raw)

                    # Ping periodically and measure pong RTT
                    if (time.time() - last_ping_ts) >= self.config.ping_interval:
                        last_ping_ts = time.time()
                        pong_waiter = await ws.ping()
                        t0 = time.perf_counter()
                        await asyncio.wait_for(pong_waiter, timeout=self.config.connect_timeout)
                        self.latency_ms = (time.perf_counter() - t0) * 1000.0

                return True
        except websockets.exceptions.ConnectionClosed:
            return False
        except Exception:
            # Treat unexpected exceptions as a connection failure for retry purposes
            return False

    async def run_health_check(self) -> KrakenWSHealthResult:
        """Run for up to test_duration, attempting reconnects as needed."""
        start = time.perf_counter()
        reconnects = 0

        # End time
        deadline = time.time() + self.config.test_duration

        while True:
            ok = await self._connect_once()
            if ok and await self._check_health_status():
                # Healthy session
                dur = time.perf_counter() - start
                return KrakenWSHealthResult(
                    connected=True,
                    reconnects=reconnects,
                    messages_received=self.messages_received,
                    last_heartbeat=self.last_heartbeat,
                    last_data=self.last_data,
                    latency_ms=self.latency_ms,
                    test_duration=dur,
                )

            # Decide whether to retry
            reconnects += 1
            if reconnects >= self.config.max_reconnects:
                dur = time.perf_counter() - start
                return KrakenWSHealthResult(
                    connected=False,
                    reconnects=reconnects,
                    messages_received=self.messages_received,
                    last_heartbeat=self.last_heartbeat,
                    last_data=self.last_data,
                    latency_ms=self.latency_ms,
                    error_message="Max reconnects reached",
                    test_duration=dur,
                )

            # Check time budget
            if time.time() >= deadline:
                dur = time.perf_counter() - start
                return KrakenWSHealthResult(
                    connected=False,
                    reconnects=reconnects,
                    messages_received=self.messages_received,
                    last_heartbeat=self.last_heartbeat,
                    last_data=self.last_data,
                    latency_ms=self.latency_ms,
                    error_message="Health gates not met within test_duration",
                    test_duration=dur,
                )

            # Jittered backoff to avoid thundering herds
            base = self.config.reconnect_delay
            sleep_s = random.uniform(base * 0.8, base * 1.2)
            await asyncio.sleep(sleep_s)


# ----------------------------- Convenience ----------------------------- #

async def check_kraken_ws_health(**kwargs) -> KrakenWSHealthResult:
    """
    Convenience function:
    `await check_kraken_ws_health(url=..., pairs=[...], test_duration=..., max_reconnects=...)`
    """
    cfg = KrakenWSHealthConfig(**kwargs)
    return await KrakenWSHealthChecker(cfg).run_health_check()


# ----------------------------- CLI ----------------------------- #

async def main():
    """Command-line interface for Kraken WebSocket health check."""
    import argparse
    import sys
    
    parser = argparse.ArgumentParser(description="Kraken WebSocket health checker")
    parser.add_argument("--url", default="wss://ws.kraken.com", help="WebSocket URL")
    parser.add_argument("--pairs", nargs="+", default=["BTC/USD", "ETH/USD"], help="Trading pairs to test")
    parser.add_argument("--test-duration", type=float, default=30.0, help="Test duration in seconds")
    parser.add_argument("--max-reconnects", type=int, default=5, help="Maximum reconnection attempts")
    parser.add_argument("--ping-interval", type=int, default=20, help="Ping interval in seconds")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    
    args = parser.parse_args()
    
    config = KrakenWSHealthConfig(
        url=args.url,
        pairs=args.pairs,
        test_duration=args.test_duration,
        max_reconnects=args.max_reconnects,
        ping_interval=args.ping_interval
    )
    
    if args.verbose:
        print(f"Starting Kraken WebSocket health check...")
        print(f"URL: {config.url}")
        print(f"Pairs: {config.pairs}")
        print(f"Test duration: {config.test_duration}s")
        print(f"Max reconnects: {config.max_reconnects}")
        print()
    
    try:
        result = await check_kraken_ws_health(**config.model_dump())
        
        if result.connected:
            print("✅ Kraken WebSocket health check PASSED")
            print(f"   Messages received: {result.messages_received}")
            print(f"   Reconnects: {result.reconnects}")
            print(f"   Latency: {result.latency_ms:.2f}ms")
            print(f"   Test duration: {result.test_duration:.2f}s")
            sys.exit(0)
        else:
            print("❌ Kraken WebSocket health check FAILED")
            print(f"   Error: {result.error_message}")
            print(f"   Messages received: {result.messages_received}")
            print(f"   Reconnects: {result.reconnects}")
            print(f"   Test duration: {result.test_duration:.2f}s")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n🛑 Health check interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"❌ Health check failed with exception: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())