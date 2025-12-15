#!/usr/bin/env python3
"""
Controlled paper test run mode.

Runs the engine for a fixed duration or number of bars and logs:
- How many signals produced
- How many PnL entries produced
- Summary statistics

Usage:
    python -m diagnostics.paper_test_run
    python -m diagnostics.paper_test_run --duration 1800  # 30 minutes
    python -m diagnostics.paper_test_run --bars 100
"""

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

# Import engine components
from engine.loop import LiveEngine, EngineConfig
from agents.infrastructure.redis_client import RedisCloudClient, RedisCloudConfig
from agents.infrastructure.prd_redis_publisher import get_signal_stream_name, get_pnl_stream_name, get_engine_mode


class PaperTestRun:
    """Controlled paper test run."""
    
    def __init__(self, duration: Optional[int] = None, bars: Optional[int] = None):
        self.duration = duration
        self.bars = bars
        self.start_time = time.time()
        self.engine: Optional[LiveEngine] = None
        self.initial_metrics: Dict[str, Any] = {}
        self.final_metrics: Dict[str, Any] = {}
        
    async def run(self):
        """Run the paper test."""
        print("=" * 80)
        print("PAPER TEST RUN")
        print("=" * 80)
        print()
        
        # Setup
        print("[1] Setting up engine...")
        config = EngineConfig(
            mode="paper",
            ohlcv_window_size=300,
            min_bars_required=100,
            signal_cooldown_seconds=60,
        )
        
        self.engine = LiveEngine(config=config)
        print("  ✅ Engine created")
        print()
        
        # Start engine
        print("[2] Starting engine...")
        engine_task = asyncio.create_task(self.engine.start())
        
        # Get initial metrics
        await asyncio.sleep(5)  # Wait for engine to initialize
        self.initial_metrics = self.engine.get_metrics()
        print("  ✅ Engine started")
        print()
        
        # Run for specified duration or bars
        if self.duration:
            print(f"[3] Running for {self.duration} seconds...")
            print()
            await asyncio.sleep(self.duration)
        elif self.bars:
            print(f"[3] Running until {self.bars} bars processed...")
            print()
            # Monitor until bars processed
            while True:
                metrics = self.engine.get_metrics()
                bars_processed = metrics.get("ticks_processed", 0)
                if bars_processed >= self.bars:
                    break
                await asyncio.sleep(1)
        else:
            # Default: 30 minutes
            print("[3] Running for 30 minutes (default)...")
            print()
            await asyncio.sleep(1800)
            
        # Stop engine
        print()
        print("[4] Stopping engine...")
        await self.engine.stop()
        engine_task.cancel()
        try:
            await engine_task
        except asyncio.CancelledError:
            pass
        print("  ✅ Engine stopped")
        print()
        
        # Get final metrics
        self.final_metrics = self.engine.get_metrics()
        
        # Generate report
        await self._generate_report()
        
    async def _generate_report(self):
        """Generate test run report."""
        print("=" * 80)
        print("PAPER TEST RUN REPORT")
        print("=" * 80)
        print()
        
        # Calculate deltas
        signals_generated = self.final_metrics.get("signals_generated", 0) - self.initial_metrics.get("signals_generated", 0)
        signals_published = self.final_metrics.get("signals_published", 0) - self.initial_metrics.get("signals_published", 0)
        signals_rejected = self.final_metrics.get("signals_rejected", 0) - self.initial_metrics.get("signals_rejected", 0)
        ticks_processed = self.final_metrics.get("ticks_processed", 0) - self.initial_metrics.get("ticks_processed", 0)
        
        print(f"[Signals]")
        print(f"  Generated: {signals_generated}")
        print(f"  Published: {signals_published}")
        print(f"  Rejected: {signals_rejected}")
        print()
        
        # Check Redis for PnL entries
        print(f"[PnL Entries]")
        try:
            redis_config = RedisCloudConfig()
            redis_client = RedisCloudClient(redis_config)
            await redis_client.connect()
            
            mode = get_engine_mode()
            pnl_signals_stream = f"pnl:{mode}:signals"
            
            # Count entries
            client = redis_client._client
            stream_length = await client.xlen(pnl_signals_stream.encode() if isinstance(pnl_signals_stream, str) else pnl_signals_stream)
            print(f"  Trade records in {pnl_signals_stream}: {stream_length}")
            
            await redis_client.disconnect()
        except Exception as e:
            print(f"  ⚠️ Could not check PnL entries: {e}")
        print()
        
        print(f"[Processing]")
        print(f"  Ticks processed: {ticks_processed}")
        print(f"  Duration: {time.time() - self.start_time:.1f} seconds")
        print()
        
        # Latency metrics
        if signals_published > 0:
            avg_decision_latency = self.final_metrics.get("avg_decision_latency_ms", 0)
            avg_publish_latency = self.final_metrics.get("avg_publish_latency_ms", 0)
            print(f"[Latency]")
            print(f"  Avg decision latency: {avg_decision_latency:.2f}ms")
            print(f"  Avg publish latency: {avg_publish_latency:.2f}ms")
            print()
        
        print("=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print(f"✅ Signals produced: {signals_published}")
        print(f"✅ PnL entries: Check Redis stream {pnl_signals_stream}")
        print("=" * 80)


async def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Paper test run")
    parser.add_argument("--duration", type=int, help="Duration in seconds")
    parser.add_argument("--bars", type=int, help="Number of bars to process")
    
    args = parser.parse_args()
    
    runner = PaperTestRun(duration=args.duration, bars=args.bars)
    await runner.run()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))








