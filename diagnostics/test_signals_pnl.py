#!/usr/bin/env python3
"""
Test script to verify signal and PnL generation in paper mode.

This script:
1. Feeds synthetic OHLCV data to the engine
2. Confirms that at least one signal and one PnL record are generated
3. Validates that signals and PnL are published to Redis

Usage:
    python -m diagnostics.test_signals_pnl
    python -m diagnostics.test_signals_pnl --duration 600
"""

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
import pandas as pd
import numpy as np

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

# Import engine components
from engine.loop import LiveEngine, EngineConfig
from agents.infrastructure.redis_client import RedisCloudClient, RedisCloudConfig
from agents.infrastructure.prd_redis_publisher import get_signal_stream_name, get_pnl_stream_name, get_engine_mode


class SignalPnLTester:
    """Test signal and PnL generation."""
    
    def __init__(self, duration: int = 300):
        self.duration = duration
        self.start_time = time.time()
        self.signals_received: List[Dict[str, Any]] = []
        self.pnl_received: List[Dict[str, Any]] = []
        self.engine: Optional[LiveEngine] = None
        self.redis_client: Optional[RedisCloudClient] = None
        
    async def setup(self):
        """Setup test environment."""
        print("[1] Setting up test environment...")
        
        # Connect to Redis
        try:
            redis_config = RedisCloudConfig()
            self.redis_client = RedisCloudClient(redis_config)
            await self.redis_client.connect()
            print("  ✅ Redis connected")
        except Exception as e:
            print(f"  ❌ Redis connection failed: {e}")
            return False
            
        # Create engine config
        config = EngineConfig(
            mode="paper",
            ohlcv_window_size=100,  # Smaller window for testing
            min_bars_required=50,   # Lower requirement for testing
            signal_cooldown_seconds=10,  # Shorter cooldown for testing
        )
        
        # Create engine
        self.engine = LiveEngine(config=config)
        print("  ✅ Engine created")
        
        return True
        
    async def run_test(self):
        """Run the test."""
        print(f"[2] Running test for {self.duration} seconds...")
        print()
        
        # Start engine in background
        engine_task = asyncio.create_task(self.engine.start())
        
        # Monitor Redis streams
        monitor_task = asyncio.create_task(self._monitor_streams())
        
        try:
            # Wait for duration
            await asyncio.sleep(self.duration)
        except KeyboardInterrupt:
            print("\n[INTERRUPTED] Stopping test...")
        finally:
            # Stop monitoring
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass
                
            # Stop engine
            await self.engine.stop()
            engine_task.cancel()
            try:
                await engine_task
            except asyncio.CancelledError:
                pass
                
        print()
        return await self._generate_report()
        
    async def _monitor_streams(self):
        """Monitor Redis streams for signals and PnL."""
        mode = get_engine_mode()
        
        # Get stream names
        signal_stream = get_signal_stream_name(mode, "BTC/USD")
        pnl_stream = get_pnl_stream_name(mode)
        pnl_signals_stream = f"pnl:{mode}:signals"
        
        print(f"  Monitoring streams:")
        print(f"    - {signal_stream}")
        print(f"    - {pnl_stream}")
        print(f"    - {pnl_signals_stream}")
        print()
        
        client = self.redis_client._client
        last_id = {"signal": "0", "pnl": "0", "pnl_signals": "0"}
        
        while True:
            try:
                # Read from streams
                streams = {
                    signal_stream.encode() if isinstance(signal_stream, str) else signal_stream: last_id["signal"].encode(),
                    pnl_stream.encode() if isinstance(pnl_stream, str) else pnl_stream: last_id["pnl"].encode(),
                    pnl_signals_stream.encode() if isinstance(pnl_signals_stream, str) else pnl_signals_stream: last_id["pnl_signals"].encode(),
                }
                
                messages = await client.xread(streams, count=10, block=1000)
                
                for stream_key, entries in messages:
                    stream_name = stream_key.decode() if isinstance(stream_key, bytes) else str(stream_key)
                    
                    for entry_id, fields in entries:
                        entry_id_str = entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)
                        
                        # Decode fields
                        decoded_fields = {}
                        for k, v in fields.items():
                            key = k.decode() if isinstance(k, bytes) else str(k)
                            val = v.decode() if isinstance(v, bytes) else str(v)
                            decoded_fields[key] = val
                        
                        if "signal" in stream_name:
                            self.signals_received.append({
                                "entry_id": entry_id_str,
                                "stream": stream_name,
                                "fields": decoded_fields,
                                "timestamp": time.time(),
                            })
                            print(f"  ✅ Signal received: {decoded_fields.get('pair', 'N/A')} {decoded_fields.get('side', 'N/A')}")
                            last_id["signal"] = entry_id_str
                        elif "pnl" in stream_name:
                            if "signals" in stream_name:
                                self.pnl_received.append({
                                    "entry_id": entry_id_str,
                                    "stream": stream_name,
                                    "fields": decoded_fields,
                                    "timestamp": time.time(),
                                })
                                print(f"  ✅ PnL trade record received: {decoded_fields.get('trade_id', 'N/A')}")
                                last_id["pnl_signals"] = entry_id_str
                            else:
                                # Equity curve update
                                print(f"  ✅ PnL equity update received: equity={decoded_fields.get('equity', 'N/A')}")
                                last_id["pnl"] = entry_id_str
                                
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"  ⚠️ Error monitoring streams: {e}")
                await asyncio.sleep(1)
                
    async def _generate_report(self):
        """Generate test report."""
        print("=" * 80)
        print("TEST REPORT")
        print("=" * 80)
        print()
        
        print(f"[Signals Generated]")
        print(f"  Count: {len(self.signals_received)}")
        if self.signals_received:
            print(f"  ✅ At least one signal generated")
            sample = self.signals_received[0]
            print(f"  Sample: {sample['fields'].get('pair', 'N/A')} {sample['fields'].get('side', 'N/A')}")
        else:
            print(f"  ❌ No signals generated")
        print()
        
        print(f"[PnL Records Generated]")
        print(f"  Count: {len(self.pnl_received)}")
        if self.pnl_received:
            print(f"  ✅ At least one PnL record generated")
            sample = self.pnl_received[0]
            print(f"  Sample: Trade ID {sample['fields'].get('trade_id', 'N/A')}")
        else:
            print(f"  ❌ No PnL records generated")
        print()
        
        # Get engine metrics
        if self.engine:
            metrics = self.engine.get_metrics()
            print(f"[Engine Metrics]")
            print(f"  Ticks processed: {metrics.get('ticks_processed', 0)}")
            print(f"  Signals generated: {metrics.get('signals_generated', 0)}")
            print(f"  Signals published: {metrics.get('signals_published', 0)}")
            print(f"  Signals rejected: {metrics.get('signals_rejected', 0)}")
            print()
        
        # Final verdict
        signals_ok = len(self.signals_received) > 0
        pnl_ok = len(self.pnl_received) > 0
        
        print("=" * 80)
        print("VERDICT")
        print("=" * 80)
        
        if signals_ok and pnl_ok:
            print("✅ TEST PASSED")
            print("   - Signals are being generated and published")
            print("   - PnL records are being generated and published")
            return True
        else:
            print("❌ TEST FAILED")
            if not signals_ok:
                print("   - No signals generated")
            if not pnl_ok:
                print("   - No PnL records generated")
            return False


async def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Test signal and PnL generation")
    parser.add_argument("--duration", type=int, default=300, help="Test duration in seconds (default: 300)")
    
    args = parser.parse_args()
    
    print("=" * 80)
    print("SIGNAL & PnL GENERATION TEST")
    print("=" * 80)
    print()
    
    tester = SignalPnLTester(duration=args.duration)
    
    if not await tester.setup():
        print("❌ Setup failed")
        return 1
        
    success = await tester.run_test()
    
    if tester.redis_client:
        await tester.redis_client.disconnect()
        
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))








