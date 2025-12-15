#!/usr/bin/env python3
"""
Run Engine for 10 Minutes and Monitor Signal/PnL Production

This script:
1. Checks Redis stream lengths before starting
2. Runs the engine for 10 minutes
3. Monitors logs for WebSocket connections, strategy execution, and publish confirmations
4. Checks Redis stream lengths after
5. Provides summary of signals and PnL entries produced
"""

import asyncio
import os
import sys
import time
import subprocess
import signal
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Optional
from dotenv import load_dotenv
import redis

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# Load environment
project_root = Path(__file__).parent
load_dotenv(project_root / ".env.paper", override=False)
load_dotenv(project_root / ".env.prod", override=False)

# Redis connection
redis_url = os.getenv("REDIS_URL")
redis_ca_cert = os.getenv(
    "REDIS_CA_CERT",
    os.getenv("REDIS_CA_CERT_PATH", str(project_root / "config" / "certs" / "redis_ca.pem"))
)

TRADING_PAIRS = ["BTC/USD", "ETH/USD", "SOL/USD", "MATIC/USD", "LINK/USD"]
MODE = os.getenv("ENGINE_MODE", "paper")
DURATION_SECONDS = 10 * 60  # 10 minutes


def get_redis_client():
    """Get Redis client"""
    if not redis_url:
        print("ERROR: REDIS_URL not set")
        return None
    
    return redis.from_url(
        redis_url,
        ssl_cert_reqs='required',
        ssl_ca_certs=redis_ca_cert if os.path.exists(redis_ca_cert) else None,
        decode_responses=True,
        socket_connect_timeout=10,
        socket_timeout=10,
    )


def get_stream_lengths(client: redis.Redis) -> Dict[str, int]:
    """Get current stream lengths"""
    lengths = {}
    
    # Signal streams
    for pair in TRADING_PAIRS:
        safe_pair = pair.replace("/", "-")
        stream_key = f"signals:{MODE}:{safe_pair}"
        try:
            lengths[stream_key] = client.xlen(stream_key)
        except Exception as e:
            lengths[stream_key] = -1
            print(f"  [WARN] Failed to get length for {stream_key}: {e}")
    
    # PnL streams
    pnl_streams = [
        f"pnl:{MODE}:equity_curve",
        f"pnl:{MODE}:signals",
    ]
    
    for stream_key in pnl_streams:
        try:
            lengths[stream_key] = client.xlen(stream_key)
        except Exception as e:
            lengths[stream_key] = -1
            print(f"  [WARN] Failed to get length for {stream_key}: {e}")
    
    return lengths


def print_stream_summary(lengths: Dict[str, int], label: str):
    """Print stream length summary"""
    print(f"\n{'=' * 80}")
    print(f"{label}")
    print(f"{'=' * 80}")
    
    print("\nSignal Streams:")
    total_signals = 0
    for pair in TRADING_PAIRS:
        safe_pair = pair.replace("/", "-")
        stream_key = f"signals:{MODE}:{safe_pair}"
        length = lengths.get(stream_key, 0)
        if length >= 0:
            print(f"  {stream_key:35} {length:>10} messages")
            total_signals += length
        else:
            print(f"  {stream_key:35} {'ERROR':>10}")
    
    print(f"\n  {'Total signals:':35} {total_signals:>10}")
    
    print("\nPnL Streams:")
    for stream_key in [f"pnl:{MODE}:equity_curve", f"pnl:{MODE}:signals"]:
        length = lengths.get(stream_key, 0)
        if length >= 0:
            print(f"  {stream_key:35} {length:>10} messages")
        else:
            print(f"  {stream_key:35} {'ERROR':>10}")


def run_engine_with_timeout(duration_seconds: int) -> Optional[subprocess.Popen]:
    """Run engine with timeout"""
    print(f"\n{'=' * 80}")
    print("STARTING ENGINE")
    print(f"{'=' * 80}")
    print(f"Mode: {MODE}")
    print(f"Duration: {duration_seconds // 60} minutes")
    print(f"Start time: {datetime.now(timezone.utc).isoformat()}")
    print()
    
    # Try main_engine.py first (production entrypoint)
    entrypoints = [
        ("main_engine.py", ["python", "main_engine.py", "--mode", MODE]),
        ("main.py", ["python", "main.py", "run", "--mode", MODE]),
        ("production_engine.py", ["python", "production_engine.py", "--mode", MODE]),
    ]
    
    process = None
    for name, cmd in entrypoints:
        if os.path.exists(name):
            print(f"Trying entrypoint: {name}")
            try:
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )
                print(f"[OK] Started {name} (PID: {process.pid})")
                return process
            except Exception as e:
                print(f"[ERROR] Failed to start {name}: {e}")
                continue
    
    print("[ERROR] No valid entrypoint found")
    return None


def monitor_logs(process: subprocess.Popen, duration_seconds: int):
    """Monitor engine logs for key events"""
    print(f"\n{'=' * 80}")
    print("MONITORING LOGS")
    print(f"{'=' * 80}")
    print("Looking for:")
    print("  - WebSocket connections")
    print("  - Strategy execution")
    print("  - Signal publish confirmations")
    print("  - PnL updates")
    print()
    
    start_time = time.time()
    events = {
        "websocket_connected": 0,
        "signal_published": 0,
        "pnl_updated": 0,
        "strategy_executed": 0,
        "errors": 0,
    }
    
    keywords = {
        "websocket_connected": ["websocket", "connected", "kraken", "ws"],
        "signal_published": ["published signal", "signal published", "publish_signal"],
        "pnl_updated": ["pnl", "equity", "published pnl"],
        "strategy_executed": ["strategy", "scalper", "trend", "signal generated"],
        "errors": ["error", "exception", "failed", "traceback"],
    }
    
    try:
        while process.poll() is None and (time.time() - start_time) < duration_seconds:
            line = process.stdout.readline()
            if not line:
                time.sleep(0.1)
                continue
            
            # Print important lines
            line_lower = line.lower()
            for event_type, search_terms in keywords.items():
                if any(term in line_lower for term in search_terms):
                    events[event_type] += 1
                    if event_type == "errors":
                        print(f"[ERROR] {line.strip()}")
                    elif event_type == "signal_published":
                        print(f"[SIGNAL] {line.strip()[:100]}")
                    elif event_type == "websocket_connected":
                        print(f"[WS] {line.strip()[:100]}")
                    break
            
            # Print every 30 seconds summary
            elapsed = time.time() - start_time
            if int(elapsed) % 30 == 0 and int(elapsed) > 0:
                print(f"\n[Progress] {int(elapsed)}s elapsed - Signals: {events['signal_published']}, Errors: {events['errors']}")
    
    except KeyboardInterrupt:
        print("\n[INTERRUPT] Monitoring interrupted")
    
    print(f"\n{'=' * 80}")
    print("LOG MONITORING SUMMARY")
    print(f"{'=' * 80}")
    for event_type, count in events.items():
        print(f"  {event_type:25} {count:>5} occurrences")
    
    return events


def main():
    """Main test execution"""
    print("=" * 80)
    print("ENGINE 10-MINUTE TEST")
    print("=" * 80)
    print(f"Mode: {MODE}")
    print(f"Duration: {DURATION_SECONDS // 60} minutes")
    print()
    
    # Connect to Redis
    print("Connecting to Redis...")
    client = get_redis_client()
    if not client:
        print("ERROR: Failed to get Redis client")
        return
    
    try:
        client.ping()
        print("[OK] Connected to Redis")
    except Exception as e:
        print(f"ERROR: Failed to connect to Redis: {e}")
        return
    
    # Get initial stream lengths
    print("\nGetting initial stream lengths...")
    initial_lengths = get_stream_lengths(client)
    print_stream_summary(initial_lengths, "INITIAL STREAM LENGTHS")
    
    # Run engine
    process = run_engine_with_timeout(DURATION_SECONDS)
    if not process:
        print("ERROR: Failed to start engine")
        return
    
    # Monitor logs
    log_events = monitor_logs(process, DURATION_SECONDS)
    
    # Wait for process to complete or timeout
    print(f"\nWaiting for engine to run for {DURATION_SECONDS // 60} minutes...")
    try:
        process.wait(timeout=DURATION_SECONDS + 10)
    except subprocess.TimeoutExpired:
        print(f"\n[Timeout] Stopping engine after {DURATION_SECONDS // 60} minutes...")
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            print("[Force] Killing engine process...")
            process.kill()
            process.wait()
    
    # Get final stream lengths
    print("\nGetting final stream lengths...")
    time.sleep(2)  # Wait for final publishes
    final_lengths = get_stream_lengths(client)
    print_stream_summary(final_lengths, "FINAL STREAM LENGTHS")
    
    # Calculate differences
    print(f"\n{'=' * 80}")
    print("PRODUCTION SUMMARY")
    print(f"{'=' * 80}")
    
    total_signals_produced = 0
    for pair in TRADING_PAIRS:
        safe_pair = pair.replace("/", "-")
        stream_key = f"signals:{MODE}:{safe_pair}"
        initial = initial_lengths.get(stream_key, 0)
        final = final_lengths.get(stream_key, 0)
        diff = final - initial
        if diff > 0:
            total_signals_produced += diff
            print(f"  {stream_key:35} {diff:>+10} signals")
    
    print(f"\n  {'Total signals produced:':35} {total_signals_produced:>10}")
    
    # PnL updates
    pnl_stream = f"pnl:{MODE}:equity_curve"
    initial_pnl = initial_lengths.get(pnl_stream, 0)
    final_pnl = final_lengths.get(pnl_stream, 0)
    pnl_updates = final_pnl - initial_pnl
    print(f"  {pnl_stream:35} {pnl_updates:>+10} updates")
    
    # Log events summary
    print(f"\n  {'Log events - Signals published:':35} {log_events['signal_published']:>10}")
    print(f"  {'Log events - WebSocket connected:':35} {log_events['websocket_connected']:>10}")
    print(f"  {'Log events - Errors:':35} {log_events['errors']:>10}")
    
    # Evidence summary
    print(f"\n{'=' * 80}")
    print("EVIDENCE FOR FRONT-END CONSUMPTION")
    print(f"{'=' * 80}")
    
    if total_signals_produced > 0:
        print(f"✅ {total_signals_produced} signals produced in {DURATION_SECONDS // 60} minutes")
        print(f"   Rate: ~{total_signals_produced / (DURATION_SECONDS / 60):.1f} signals/minute")
    else:
        print("⚠️  No signals produced - engine may not be publishing")
    
    if pnl_updates > 0:
        print(f"✅ {pnl_updates} PnL updates produced")
    else:
        print("⚠️  No PnL updates produced")
    
    if log_events['signal_published'] > 0:
        print(f"✅ {log_events['signal_published']} signal publish confirmations in logs")
    
    if log_events['websocket_connected'] > 0:
        print(f"✅ WebSocket connections established")
    
    if log_events['errors'] > 0:
        print(f"⚠️  {log_events['errors']} errors encountered - check logs")
    
    print(f"\n{'=' * 80}")
    print("TEST COMPLETE")
    print(f"{'=' * 80}")
    print(f"End time: {datetime.now(timezone.utc).isoformat()}")
    print(f"Duration: {DURATION_SECONDS // 60} minutes")
    print()
    print("Redis streams are ready for signals-api consumption:")
    for pair in TRADING_PAIRS:
        safe_pair = pair.replace("/", "-")
        stream_key = f"signals:{MODE}:{safe_pair}"
        length = final_lengths.get(stream_key, 0)
        if length > 0:
            print(f"  ✅ {stream_key}: {length} messages")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[INTERRUPT] Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

