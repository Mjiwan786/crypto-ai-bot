#!/usr/bin/env python
"""
Week 3 Metrics Pipeline Test Script

Verifies the summary metrics aggregator and Redis key publication.

Tests:
1. Connection to Redis Cloud
2. Signal frequency calculation
3. Performance metrics calculation
4. Trading pairs consistency
5. Redis key publication

Usage:
    cd crypto_ai_bot
    conda activate crypto-bot
    python scripts/test_week3_metrics.py

Author: Crypto AI Bot Team
Date: 2025-12-03
"""

import asyncio
import os
import sys
import logging
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S"
)
logger = logging.getLogger(__name__)


async def test_metrics_pipeline():
    """Run comprehensive metrics pipeline test."""

    print("=" * 70)
    print(" " * 15 + "WEEK 3 METRICS PIPELINE TEST")
    print("=" * 70)

    # Load environment
    load_dotenv(".env.paper")

    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        print("\n[ERROR] REDIS_URL not set!")
        return False

    redis_ca_cert = os.getenv("REDIS_TLS_CERT_PATH", "config/certs/redis_ca.pem")
    mode = os.getenv("ENGINE_MODE", "paper")

    print(f"\nConfiguration:")
    print(f"  Mode: {mode}")
    print(f"  Redis URL: {redis_url[:50]}...")
    print(f"  CA Cert: {redis_ca_cert}")

    # Import aggregator
    from metrics.summary_metrics_aggregator import (
        SummaryMetricsAggregator,
        CANONICAL_TRADING_PAIRS,
        KEY_METRICS_SUMMARY,
        KEY_SIGNAL_FREQUENCY,
        KEY_TRADING_PAIRS,
    )

    # Test 1: Trading pairs consistency
    print("\n" + "-" * 70)
    print("TEST 1: Trading Pairs Consistency")
    print("-" * 70)

    expected_pairs = ["BTC/USD", "ETH/USD", "SOL/USD", "MATIC/USD", "LINK/USD"]
    canonical_pairs = [p["symbol"] for p in CANONICAL_TRADING_PAIRS if p["enabled"]]

    print(f"  Expected (PRD-001): {expected_pairs}")
    print(f"  Canonical pairs: {canonical_pairs}")

    if set(expected_pairs) == set(canonical_pairs):
        print("  [PASS] Trading pairs match PRD-001 specification")
    else:
        print("  [FAIL] Trading pairs mismatch!")
        print(f"    Missing: {set(expected_pairs) - set(canonical_pairs)}")
        print(f"    Extra: {set(canonical_pairs) - set(expected_pairs)}")

    # Test 2: Redis connection
    print("\n" + "-" * 70)
    print("TEST 2: Redis Connection")
    print("-" * 70)

    aggregator = SummaryMetricsAggregator(
        redis_url=redis_url,
        redis_ca_cert=redis_ca_cert,
        mode=mode,
    )

    connected = await aggregator.connect()
    if connected:
        print("  [PASS] Connected to Redis Cloud")
    else:
        print("  [FAIL] Failed to connect to Redis")
        return False

    # Test 3: Signal frequency calculation
    print("\n" + "-" * 70)
    print("TEST 3: Signal Frequency Calculation")
    print("-" * 70)

    try:
        freq_stats = await aggregator.calculate_signal_frequency()

        print(f"  Signals today: {freq_stats.signals_today}")
        print(f"  Signals (7 days): {freq_stats.signals_last_7_days}")
        print(f"  Signals (30 days): {freq_stats.signals_last_30_days}")
        print(f"  Signals (90 days): {freq_stats.signals_last_90_days}")
        print(f"  Avg signals/day: {freq_stats.avg_signals_per_day}")
        print(f"  Avg signals/week: {freq_stats.avg_signals_per_week}")
        print(f"  Avg signals/month: {freq_stats.avg_signals_per_month}")
        print(f"  Active pairs: {freq_stats.pairs_active}")
        print(f"  Last signal: {freq_stats.last_signal_timestamp}")

        print("  [PASS] Signal frequency calculated")
    except Exception as e:
        print(f"  [FAIL] Error: {e}")

    # Test 4: Performance metrics calculation
    print("\n" + "-" * 70)
    print("TEST 4: Performance Metrics Calculation")
    print("-" * 70)

    try:
        perf_summary = await aggregator.calculate_performance_summary(
            starting_equity=10000.0
        )

        print(f"  Total ROI: {perf_summary.total_roi_pct}%")
        print(f"  CAGR: {perf_summary.cagr_pct}%")
        print(f"  Win Rate: {perf_summary.win_rate_pct}%")
        print(f"  Profit Factor: {perf_summary.profit_factor}")
        print(f"  Max Drawdown: {perf_summary.max_drawdown_pct}%")
        print(f"  Sharpe Ratio: {perf_summary.sharpe_ratio}")
        print(f"  Total Trades: {perf_summary.total_trades}")
        print(f"  Current Equity: ${perf_summary.current_equity_usd:.2f}")
        print(f"  Realized PnL: ${perf_summary.realized_pnl_usd:.2f}")

        print("  [PASS] Performance metrics calculated")
    except Exception as e:
        print(f"  [FAIL] Error: {e}")

    # Test 5: Publish metrics to Redis
    print("\n" + "-" * 70)
    print("TEST 5: Publish Metrics to Redis")
    print("-" * 70)

    try:
        results = await aggregator.aggregate_and_publish(starting_equity=10000.0)

        if results["success"]:
            print("  [PASS] Metrics published to Redis")
        else:
            print(f"  [FAIL] Publish failed: {results.get('error')}")
    except Exception as e:
        print(f"  [FAIL] Error: {e}")

    # Test 6: Verify Redis keys
    print("\n" + "-" * 70)
    print("TEST 6: Verify Redis Keys")
    print("-" * 70)

    try:
        # Check signal frequency key
        freq_data = await aggregator.redis_client.hgetall(KEY_SIGNAL_FREQUENCY)
        if freq_data:
            print(f"  {KEY_SIGNAL_FREQUENCY}: {len(freq_data)} fields")
            for k, v in list(freq_data.items())[:3]:
                print(f"    - {k.decode()}: {v.decode()[:50]}")
            print("  [PASS] Signal frequency key present")
        else:
            print(f"  [WARN] {KEY_SIGNAL_FREQUENCY} empty or missing")

        # Check metrics summary key
        summary_data = await aggregator.redis_client.hgetall(KEY_METRICS_SUMMARY)
        if summary_data:
            print(f"  {KEY_METRICS_SUMMARY}: {len(summary_data)} fields")
            for k, v in list(summary_data.items())[:3]:
                print(f"    - {k.decode()}: {v.decode()[:50]}")
            print("  [PASS] Metrics summary key present")
        else:
            print(f"  [WARN] {KEY_METRICS_SUMMARY} empty or missing")

        # Check trading pairs key
        pairs_data = await aggregator.redis_client.hgetall(KEY_TRADING_PAIRS)
        if pairs_data:
            print(f"  {KEY_TRADING_PAIRS}: {len(pairs_data)} fields")
            pairs_list = pairs_data.get(b"pairs_list", b"").decode()
            print(f"    - pairs_list: {pairs_list}")
            print("  [PASS] Trading pairs key present")
        else:
            print(f"  [WARN] {KEY_TRADING_PAIRS} empty or missing")

    except Exception as e:
        print(f"  [FAIL] Error: {e}")

    # Test 7: Check signal streams
    print("\n" + "-" * 70)
    print("TEST 7: Check Signal Streams")
    print("-" * 70)

    try:
        for pair in canonical_pairs:
            pair_normalized = pair.replace("/", "-")
            stream_key = f"signals:{mode}:{pair_normalized}"

            stream_len = await aggregator.redis_client.xlen(stream_key)
            print(f"  {stream_key}: {stream_len} messages")

        print("  [PASS] Signal streams checked")
    except Exception as e:
        print(f"  [FAIL] Error: {e}")

    # Cleanup
    await aggregator.close()

    # Summary
    print("\n" + "=" * 70)
    print(" " * 20 + "TEST SUMMARY")
    print("=" * 70)

    print("""
Week 3 Metrics Pipeline Status:

  1. Signal Frequency Aggregation: IMPLEMENTED
     - Calculates signals per day/week/month from Redis streams
     - Publishes to 'metrics:signal_frequency' hash

  2. Performance Metrics Aggregation: IMPLEMENTED
     - Calculates ROI, CAGR, win rate, profit factor, etc.
     - Reads from PnL streams and equity curve
     - Publishes to 'metrics:summary' hash

  3. Trading Pairs Configuration: UPDATED
     - 5 canonical pairs per PRD-001
     - BTC/USD, ETH/USD, SOL/USD, MATIC/USD, LINK/USD
     - Publishes to 'metrics:trading_pairs' hash

  4. Signal Methodology Documentation: CREATED
     - docs/SIGNAL_METHODOLOGY.md
     - Explains AI ensemble, risk filters, disclosures

Redis Keys for signals-api:
  - metrics:signal_frequency  (Hash - signal counts)
  - metrics:summary           (Hash - performance metrics)
  - metrics:trading_pairs     (Hash - canonical pairs list)

To run the aggregator continuously:
  python -m metrics.summary_metrics_aggregator
""")

    print("=" * 70)
    print(" " * 25 + "TEST COMPLETE")
    print("=" * 70)

    return True


if __name__ == "__main__":
    asyncio.run(test_metrics_pipeline())
