"""
Benchmark: Signal Publisher (crypto-ai-bot)

Measures signal publication latency to Redis streams.
Tests PRD-001 requirement: p95 ≤ 500ms

Usage:
    python scripts/benchmark_signal_publisher.py --signals 100 --rate 60

Environment Variables:
    REDIS_URL: Redis connection URL with TLS
"""

import argparse
import asyncio
import json
import os
import redis
import statistics
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any
from urllib.parse import urlparse


class SignalPublisherBenchmark:
    """Benchmarks signal publication to Redis."""

    def __init__(self, redis_url: str, stream_name: str = "signals:paper:benchmark"):
        """Initialize benchmark."""
        self.redis_url = redis_url
        self.stream_name = stream_name
        self.redis_client = None
        self.latencies_ms: List[float] = []

    def connect(self):
        """Connect to Redis Cloud with TLS."""
        parsed = urlparse(self.redis_url)

        # Get certificate path
        cert_path = Path(__file__).parent.parent / "config" / "certs" / "redis_ca.pem"

        self.redis_client = redis.Redis(
            host=parsed.hostname,
            port=parsed.port or 19818,
            username=parsed.username or "default",
            password=parsed.password,
            ssl=True,
            ssl_cert_reqs="required",
            ssl_ca_certs=str(cert_path) if cert_path.exists() else None,
            decode_responses=True,
        )

        # Test connection
        self.redis_client.ping()
        print(f"✓ Connected to Redis: {parsed.hostname}:{parsed.port}")

    def generate_signal(self, sequence: int) -> Dict[str, Any]:
        """Generate a synthetic signal."""
        base_price = 50000.0
        price_variance = sequence % 1000

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "signal_type": "entry",
            "side": "long" if sequence % 2 == 0 else "short",
            "trading_pair": "BTC/USD",
            "entry_price": base_price + price_variance,
            "size": 0.01,
            "stop_loss": base_price + price_variance - 1000,
            "take_profit": base_price + price_variance + 2000,
            "confidence_score": 0.65 + (sequence % 35) / 100,
            "agent_id": "benchmark_agent",
            "strategy": "benchmark",
            "metadata": {
                "sequence": sequence,
                "benchmark": True,
                "publish_time": time.time()
            }
        }

    def publish_signal(self, signal: Dict[str, Any]) -> float:
        """Publish signal and measure latency in milliseconds."""
        start_time = time.time()

        # Publish to Redis stream
        message_id = self.redis_client.xadd(
            self.stream_name,
            {"json": json.dumps(signal)},
            maxlen=10000  # Keep last 10k messages
        )

        end_time = time.time()
        latency_ms = (end_time - start_time) * 1000

        return latency_ms

    def run_benchmark(self, num_signals: int, signals_per_minute: int) -> Dict[str, Any]:
        """Run benchmark with N signals at specified rate."""
        print(f"\n{'='*60}")
        print(f"Signal Publisher Benchmark")
        print(f"{'='*60}")
        print(f"Signals to publish: {num_signals}")
        print(f"Target rate: {signals_per_minute} signals/min")
        print(f"Target interval: {60/signals_per_minute:.3f}s between signals")
        print(f"Stream: {self.stream_name}")
        print(f"{'='*60}\n")

        interval_seconds = 60.0 / signals_per_minute
        self.latencies_ms = []

        start_benchmark = time.time()

        for i in range(num_signals):
            signal = self.generate_signal(i)

            # Measure publish latency
            latency_ms = self.publish_signal(signal)
            self.latencies_ms.append(latency_ms)

            # Progress indicator
            if (i + 1) % 10 == 0 or i == 0:
                print(f"Published {i+1}/{num_signals} signals | "
                      f"Last latency: {latency_ms:.2f}ms")

            # Rate limiting (skip for last signal)
            if i < num_signals - 1:
                time.sleep(interval_seconds)

        end_benchmark = time.time()
        total_time = end_benchmark - start_benchmark

        # Calculate statistics
        results = self._calculate_statistics(total_time, num_signals)

        return results

    def _calculate_statistics(self, total_time: float, num_signals: int) -> Dict[str, Any]:
        """Calculate latency statistics."""
        latencies_sorted = sorted(self.latencies_ms)

        results = {
            "total_signals": num_signals,
            "total_time_seconds": total_time,
            "actual_rate_per_min": (num_signals / total_time) * 60,
            "latency_ms": {
                "min": min(latencies_sorted),
                "max": max(latencies_sorted),
                "mean": statistics.mean(latencies_sorted),
                "median": statistics.median(latencies_sorted),
                "p50": self._percentile(latencies_sorted, 50),
                "p95": self._percentile(latencies_sorted, 95),
                "p99": self._percentile(latencies_sorted, 99),
                "stddev": statistics.stdev(latencies_sorted) if len(latencies_sorted) > 1 else 0,
            },
            "threshold_status": {
                "p95_threshold_ms": 500,
                "p95_actual_ms": self._percentile(latencies_sorted, 95),
                "pass": self._percentile(latencies_sorted, 95) <= 500
            }
        }

        return results

    def _percentile(self, data: List[float], percentile: int) -> float:
        """Calculate percentile."""
        size = len(data)
        index = (percentile / 100) * (size - 1)
        lower = int(index)
        upper = lower + 1

        if upper >= size:
            return data[-1]

        weight = index - lower
        return data[lower] * (1 - weight) + data[upper] * weight

    def print_results(self, results: Dict[str, Any]):
        """Print benchmark results."""
        print(f"\n{'='*60}")
        print(f"BENCHMARK RESULTS")
        print(f"{'='*60}")
        print(f"Total Signals: {results['total_signals']}")
        print(f"Total Time: {results['total_time_seconds']:.2f}s")
        print(f"Actual Rate: {results['actual_rate_per_min']:.2f} signals/min")
        print(f"\nLatency Statistics (ms):")
        print(f"  Min:    {results['latency_ms']['min']:.2f}ms")
        print(f"  Max:    {results['latency_ms']['max']:.2f}ms")
        print(f"  Mean:   {results['latency_ms']['mean']:.2f}ms")
        print(f"  Median: {results['latency_ms']['median']:.2f}ms")
        print(f"  p50:    {results['latency_ms']['p50']:.2f}ms")
        print(f"  p95:    {results['latency_ms']['p95']:.2f}ms ← PRD-001 Threshold: ≤ 500ms")
        print(f"  p99:    {results['latency_ms']['p99']:.2f}ms")
        print(f"  StdDev: {results['latency_ms']['stddev']:.2f}ms")

        # Threshold check
        threshold = results['threshold_status']
        print(f"\n{'='*60}")
        print(f"THRESHOLD CHECK (PRD-001)")
        print(f"{'='*60}")
        print(f"Requirement: p95 publish latency ≤ 500ms")
        print(f"Actual p95:  {threshold['p95_actual_ms']:.2f}ms")

        if threshold['pass']:
            print(f"Status: ✓ PASS")
        else:
            print(f"Status: ✗ FAIL (exceeds threshold by {threshold['p95_actual_ms'] - 500:.2f}ms)")

        print(f"{'='*60}\n")

    def save_results(self, results: Dict[str, Any], output_file: str):
        """Save results to JSON file."""
        results['timestamp'] = datetime.utcnow().isoformat()
        results['stream_name'] = self.stream_name

        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2)

        print(f"✓ Results saved to: {output_file}")

    def cleanup(self):
        """Cleanup resources."""
        if self.redis_client:
            # Optionally delete benchmark stream
            # self.redis_client.delete(self.stream_name)
            self.redis_client.close()
            print(f"✓ Disconnected from Redis")


def main():
    """Main benchmark entry point."""
    parser = argparse.ArgumentParser(description="Benchmark signal publisher")
    parser.add_argument("--signals", type=int, default=100,
                        help="Number of signals to publish (default: 100)")
    parser.add_argument("--rate", type=int, default=60,
                        help="Signals per minute (default: 60)")
    parser.add_argument("--stream", type=str, default="signals:paper:benchmark",
                        help="Redis stream name (default: signals:paper:benchmark)")
    parser.add_argument("--output", type=str, default="benchmark_publisher_results.json",
                        help="Output file for results (default: benchmark_publisher_results.json)")

    args = parser.parse_args()

    # Get Redis URL from environment
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        print("ERROR: REDIS_URL environment variable not set")
        print("Export REDIS_URL with your Redis Cloud connection string")
        return 1

    # Run benchmark
    benchmark = SignalPublisherBenchmark(redis_url, args.stream)

    try:
        benchmark.connect()
        results = benchmark.run_benchmark(args.signals, args.rate)
        benchmark.print_results(results)
        benchmark.save_results(results, args.output)

        # Return exit code based on threshold
        if not results['threshold_status']['pass']:
            print("ERROR: Benchmark failed to meet p95 ≤ 500ms threshold")
            return 1

        return 0

    except KeyboardInterrupt:
        print("\n\nBenchmark interrupted by user")
        return 1
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        benchmark.cleanup()


if __name__ == "__main__":
    exit(main())
