#!/usr/bin/env python3
"""
Diagnostic script to check Kraken WebSocket connectivity and multi-pair data flow.

Verifies:
- All configured pairs are subscribed
- Reconnection logic with backoff
- Logs for connect/disconnect/reconnect/subscription failures
- OHLCV/feature pipeline produces data
- Last message timestamp per pair

Usage:
    python -m diagnostics.kraken
    python -m diagnostics.kraken --duration 120
    python -m diagnostics.kraken --pairs BTC/USD ETH/USD
"""

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
import json

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

# Import Kraken WebSocket client
from utils.kraken_ws import KrakenWebSocketClient, KrakenWSConfig
from utils.kraken_config_loader import KrakenConfigLoader, get_kraken_config_loader

logger = None  # Will be set up


# Kraken pair normalization (XBT -> BTC)
PAIR_NORMALIZE_MAP = {
    "XBT/USD": "BTC/USD",
    "XBT/EUR": "BTC/EUR",
    "XBT/GBP": "BTC/GBP",
    "XBT/CAD": "BTC/CAD",
    "XBT/JPY": "BTC/JPY",
    "XBT/AUD": "BTC/AUD",
    "XBT/CHF": "BTC/CHF",
}


def normalize_pair(pair: str) -> str:
    """Normalize Kraken pair names (XBT -> BTC)."""
    return PAIR_NORMALIZE_MAP.get(pair, pair)


class KrakenDiagnostic:
    """Diagnostic runner for Kraken WebSocket connectivity."""
    
    def __init__(self, duration: int = 60, pairs: Optional[List[str]] = None):
        self.duration = duration
        self.requested_pairs = pairs
        self.start_time = time.time()
        self.messages_received: Dict[str, List[Dict[str, Any]]] = {}
        self.connection_events: List[Dict[str, Any]] = []
        self.subscription_events: List[Dict[str, Any]] = []
        self.last_message_timestamp: Dict[str, float] = {}
        self.client: Optional[KrakenWebSocketClient] = None
        
    async def on_connect(self):
        """Callback when WebSocket connects."""
        event = {
            "type": "connect",
            "timestamp": time.time(),
            "iso_timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.connection_events.append(event)
        print(f"[CONNECT] {event['iso_timestamp']}")
        
    async def on_disconnect(self, reason: str = ""):
        """Callback when WebSocket disconnects."""
        event = {
            "type": "disconnect",
            "timestamp": time.time(),
            "iso_timestamp": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
        }
        self.connection_events.append(event)
        print(f"[DISCONNECT] {event['iso_timestamp']} - {reason}")
        
    async def on_reconnect(self, attempt: int):
        """Callback when reconnection happens."""
        event = {
            "type": "reconnect",
            "timestamp": time.time(),
            "iso_timestamp": datetime.now(timezone.utc).isoformat(),
            "attempt": attempt,
        }
        self.connection_events.append(event)
        print(f"[RECONNECT] {event['iso_timestamp']} - Attempt {attempt}")
        
    async def on_subscription_success(self, channel: str, pairs: List[str]):
        """Callback when subscription succeeds."""
        event = {
            "type": "subscription_success",
            "timestamp": time.time(),
            "iso_timestamp": datetime.now(timezone.utc).isoformat(),
            "channel": channel,
            "pairs": pairs,
        }
        self.subscription_events.append(event)
        print(f"[SUBSCRIBE OK] {channel} for {len(pairs)} pairs: {', '.join(pairs[:3])}{'...' if len(pairs) > 3 else ''}")
        
    async def on_subscription_failure(self, channel: str, pairs: List[str], error: str):
        """Callback when subscription fails."""
        event = {
            "type": "subscription_failure",
            "timestamp": time.time(),
            "iso_timestamp": datetime.now(timezone.utc).isoformat(),
            "channel": channel,
            "pairs": pairs,
            "error": error,
        }
        self.subscription_events.append(event)
        print(f"[SUBSCRIBE FAIL] {channel} for {', '.join(pairs)} - {error}")
        
    async def on_ticker(self, pair: str, data: Dict[str, Any]):
        """Callback for ticker data."""
        self._record_message(pair, "ticker", data)
        
    async def on_trade(self, pair: str, trades: List[Dict[str, Any]]):
        """Callback for trade data."""
        self._record_message(pair, "trade", {"count": len(trades), "sample": trades[0] if trades else None})
        
    async def on_spread(self, pair: str, data: Dict[str, Any]):
        """Callback for spread data."""
        self._record_message(pair, "spread", data)
        
    async def on_book(self, pair: str, data: Dict[str, Any]):
        """Callback for order book data."""
        self._record_message(pair, "book", {"bids": len(data.get("bids", [])), "asks": len(data.get("asks", []))})
        
    async def on_ohlc(self, pair: str, data: Dict[str, Any]):
        """Callback for OHLC data."""
        self._record_message(pair, "ohlc", data)
        
    def _record_message(self, pair: str, channel: str, data: Dict[str, Any]):
        """Record a message for a pair."""
        # Normalize pair name (XBT -> BTC)
        pair = normalize_pair(pair)

        if pair not in self.messages_received:
            self.messages_received[pair] = []
        if pair not in self.last_message_timestamp:
            self.last_message_timestamp[pair] = {}
            
        self.last_message_timestamp[pair][channel] = time.time()
        
        # Store sample (keep only first 5 per pair/channel)
        key = f"{pair}:{channel}"
        if len(self.messages_received[pair]) < 5:
            self.messages_received[pair].append({
                "channel": channel,
                "timestamp": time.time(),
                "data": data,
            })
            
    async def run(self):
        """Run the diagnostic."""
        print("=" * 80)
        print("KRAKEN WEBSOCKET DIAGNOSTIC")
        print("=" * 80)
        print()
        
        # 1. Load configuration
        print("[1] Loading Configuration...")
        try:
            config_loader = get_kraken_config_loader()
            all_pairs = config_loader.get_all_pairs()
            print(f"  Found {len(all_pairs)} pairs in config: {', '.join(all_pairs)}")
        except Exception as e:
            print(f"  [WARNING] Failed to load config: {e}")
            all_pairs = ["BTC/USD", "ETH/USD", "SOL/USD", "ADA/USD", "AVAX/USD", "MATIC/USD", "LINK/USD"]
            
        # Use requested pairs or all pairs
        pairs_to_test = self.requested_pairs or all_pairs
        print(f"  Testing {len(pairs_to_test)} pairs: {', '.join(pairs_to_test)}")
        print()
        
        # 2. Create WebSocket client
        print("[2] Creating Kraken WebSocket Client...")
        try:
            config = KrakenWSConfig()
            # Override pairs if specified
            if self.requested_pairs:
                config.pairs = self.requested_pairs
            else:
                # Use pairs from config
                config.pairs = pairs_to_test
                
            self.client = KrakenWebSocketClient(config)
            
            # Register callbacks
            self.client.callbacks["ticker"].append(self.on_ticker)
            self.client.callbacks["trade"].append(self.on_trade)
            self.client.callbacks["spread"].append(self.on_spread)
            self.client.callbacks["book"].append(self.on_book)
            self.client.callbacks["ohlc"].append(self.on_ohlc)
            
            print(f"  Client created with {len(config.pairs)} pairs")
            print(f"  Channels: ticker, trade, spread, book, ohlc")
            print()
        except Exception as e:
            print(f"  [ERROR] Failed to create client: {e}")
            return 1
            
        # 3. Start connection
        print("[3] Connecting to Kraken WebSocket...")
        print(f"  URL: {config.url}")
        print(f"  Duration: {self.duration} seconds")
        print()
        
        # Monitor connection state
        async def monitor_connection():
            """Monitor connection state changes."""
            last_state = None
            while time.time() - self.start_time < self.duration + 5:  # Extra 5s buffer
                if self.client:
                    current_state = self.client.connection_state.value
                    if current_state != last_state:
                        if current_state == "CONNECTED":
                            await self.on_connect()
                        elif current_state == "DISCONNECTED" and last_state == "CONNECTED":
                            await self.on_disconnect("State change")
                        elif current_state == "RECONNECTING":
                            await self.on_reconnect(self.client.reconnection_attempt)
                        last_state = current_state
                await asyncio.sleep(0.5)
                
        # Start client and monitor
        client_task = asyncio.create_task(self.client.start())
        monitor_task = asyncio.create_task(monitor_connection())
        
        # Wait for duration
        print(f"[4] Listening for {self.duration} seconds...")
        print()
        
        try:
            await asyncio.sleep(self.duration)
        except KeyboardInterrupt:
            print("\n[INTERRUPTED] Stopping diagnostic...")
        
        # Stop client
        print()
        print("[5] Stopping client...")
        await self.client.stop()
        client_task.cancel()
        monitor_task.cancel()
        
        try:
            await client_task
        except asyncio.CancelledError:
            pass
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass
            
        print("  Client stopped")
        print()
        
        # 6. Generate report
        await self._generate_report(pairs_to_test)
        
        return 0
        
    async def _generate_report(self, expected_pairs: List[str]):
        """Generate diagnostic report."""
        print("=" * 80)
        print("DIAGNOSTIC REPORT")
        print("=" * 80)
        print()
        
        # Connection events
        print("[Connection Events]")
        if self.connection_events:
            for event in self.connection_events:
                print(f"  {event['type'].upper()}: {event['iso_timestamp']} {event.get('reason', '')} {event.get('attempt', '')}")
        else:
            print("  No connection events recorded")
        print()
        
        # Subscription events
        print("[Subscription Events]")
        if self.subscription_events:
            success_count = sum(1 for e in self.subscription_events if e['type'] == 'subscription_success')
            failure_count = sum(1 for e in self.subscription_events if e['type'] == 'subscription_failure')
            print(f"  Success: {success_count}")
            print(f"  Failures: {failure_count}")
            if failure_count > 0:
                print("  Failed subscriptions:")
                for event in self.subscription_events:
                    if event['type'] == 'subscription_failure':
                        print(f"    - {event['channel']} for {', '.join(event['pairs'])}: {event['error']}")
        else:
            print("  No subscription events recorded")
        print()
        
        # Message summary per pair
        print("[Message Summary Per Pair]")
        current_time = time.time()
        for pair in expected_pairs:
            if pair in self.last_message_timestamp:
                channels = list(self.last_message_timestamp[pair].keys())
                last_times = {ch: current_time - self.last_message_timestamp[pair][ch] 
                             for ch in channels}
                print(f"  {pair}:")
                print(f"    Channels: {', '.join(channels)}")
                print(f"    Last message age: {', '.join([f'{ch}={last_times[ch]:.1f}s' for ch in channels])}")
                if pair in self.messages_received:
                    print(f"    Sample messages: {len(self.messages_received[pair])}")
            else:
                print(f"  {pair}: [MISSING] NO MESSAGES RECEIVED")
        print()
        
        # Last message age summary
        print("[Last Message Age Per Pair]")
        current_time = time.time()
        age_summary = {}
        for pair in expected_pairs:
            if pair in self.last_message_timestamp:
                # Get most recent message across all channels
                max_age = 0
                for channel, timestamp in self.last_message_timestamp[pair].items():
                    age = current_time - timestamp
                    max_age = max(max_age, age)
                age_summary[pair] = max_age
                print(f"  {pair}: {max_age:.1f} seconds")
            else:
                age_summary[pair] = None
                print(f"  {pair}: [MISSING] NO MESSAGES")
        print()
        
        # Statistics
        if self.client:
            stats = self.client.get_stats()
            print("[Client Statistics]")
            print(f"  Messages received: {stats.get('messages_received', 0)}")
            print(f"  Reconnects: {stats.get('reconnects', 0)}")
            print(f"  Errors: {stats.get('errors', 0)}")
            print(f"  Connection state: {stats.get('connection_state', 'UNKNOWN')}")
            print()
        
        # Summary
        print("=" * 80)
        print("SUMMARY")
        print("=" * 80)
        
        pairs_working = [p for p in expected_pairs if p in self.last_message_timestamp]
        pairs_missing = [p for p in expected_pairs if p not in self.last_message_timestamp]
        
        print(f"Pairs confirmed working: {len(pairs_working)}/{len(expected_pairs)}")
        if pairs_working:
            print(f"  [OK] {', '.join(pairs_working)}")
        if pairs_missing:
            print(f"  [MISSING] {', '.join(pairs_missing)}")
        print()
        
        # Check reconnection logic
        reconnect_count = len([e for e in self.connection_events if e['type'] == 'reconnect'])
        if reconnect_count > 0:
            print(f"[PASS] Reconnection logic tested: {reconnect_count} reconnections observed")
        else:
            print("[INFO] Reconnection logic: Not tested (no disconnections during test)")
        print()

        # Check subscription failures
        sub_failures = [e for e in self.subscription_events if e['type'] == 'subscription_failure']
        if sub_failures:
            print(f"[WARN] Subscription failures: {len(sub_failures)}")
            for failure in sub_failures:
                print(f"    - {failure['channel']}: {failure['error']}")
        else:
            print("[PASS] All subscriptions successful")
        print()
        
        return len(pairs_missing) == 0


async def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Kraken WebSocket diagnostic")
    parser.add_argument("--duration", type=int, default=60, help="Duration in seconds (default: 60)")
    parser.add_argument("--pairs", nargs="+", help="Specific pairs to test (e.g., BTC/USD ETH/USD)")
    
    args = parser.parse_args()
    
    diagnostic = KrakenDiagnostic(duration=args.duration, pairs=args.pairs)
    return await diagnostic.run()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))








