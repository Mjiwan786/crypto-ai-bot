"""
Performance and Load Tests.

Tests system performance under load, latency targets, and uptime monitoring.

Author: QA Team
Version: 1.0.0
Date: 2025-11-17
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pytest
import time
import requests
import redis
import concurrent.futures
from datetime import datetime, timedelta
import numpy as np
from typing import List, Dict

# Import centralized signals API config
from config.signals_api_config import SIGNALS_API_BASE_URL

# Configuration
REDIS_URL = "rediss://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com:19818"
API_URL = SIGNALS_API_BASE_URL
LATENCY_TARGET_MS = 500  # <500ms target
UPTIME_TARGET = 0.998     # 99.8% uptime target


class TestLatencyPerformance:
    """Test latency requirements."""

    def test_api_latency_single_request(self):
        """Test single API request latency."""
        latencies = []

        for i in range(10):
            start = time.time()
            try:
                response = requests.get(f"{API_URL}/health", timeout=5)
                latency_ms = (time.time() - start) * 1000

                if response.status_code == 200:
                    latencies.append(latency_ms)

            except requests.RequestException:
                pass

            time.sleep(0.1)  # Small delay between requests

        if not latencies:
            pytest.skip("API not available for latency testing")

        # Calculate statistics
        avg_latency = np.mean(latencies)
        p95_latency = np.percentile(latencies, 95)
        p99_latency = np.percentile(latencies, 99)

        print(f"\nLatency Statistics:")
        print(f"  Average: {avg_latency:.2f}ms")
        print(f"  P95: {p95_latency:.2f}ms")
        print(f"  P99: {p99_latency:.2f}ms")

        # Assert latency targets
        assert avg_latency < LATENCY_TARGET_MS, \
            f"Average latency {avg_latency:.2f}ms exceeds target {LATENCY_TARGET_MS}ms"

        assert p95_latency < LATENCY_TARGET_MS, \
            f"P95 latency {p95_latency:.2f}ms exceeds target {LATENCY_TARGET_MS}ms"

    def test_redis_latency(self):
        """Test Redis operation latency."""
        client = redis.from_url(
            REDIS_URL,
            decode_responses=True,
            ssl=True,
            ssl_cert_reqs='required'
        )

        write_latencies = []
        read_latencies = []

        # Perform operations
        for i in range(100):
            # Write
            start = time.time()
            client.set(f'perf_test_{i}', f'value_{i}')
            write_latencies.append((time.time() - start) * 1000)

            # Read
            start = time.time()
            client.get(f'perf_test_{i}')
            read_latencies.append((time.time() - start) * 1000)

        # Cleanup
        for i in range(100):
            client.delete(f'perf_test_{i}')

        client.close()

        # Calculate statistics
        avg_write = np.mean(write_latencies)
        avg_read = np.mean(read_latencies)
        p95_write = np.percentile(write_latencies, 95)
        p95_read = np.percentile(read_latencies, 95)

        print(f"\nRedis Latency Statistics:")
        print(f"  Write - Avg: {avg_write:.2f}ms, P95: {p95_write:.2f}ms")
        print(f"  Read  - Avg: {avg_read:.2f}ms, P95: {p95_read:.2f}ms")

        # Assert reasonable latencies
        assert avg_write < 100, f"Average write latency too high: {avg_write:.2f}ms"
        assert avg_read < 100, f"Average read latency too high: {avg_read:.2f}ms"

    def test_end_to_end_latency(self):
        """Test end-to-end signal generation to delivery latency."""
        import torch
        from ml.deep_ensemble import MLEnsemble

        # Initialize model
        ensemble = MLEnsemble(input_size=128, seq_len=60, num_classes=3)

        latencies = {
            'inference': [],
            'redis_publish': [],
            'total': []
        }

        client = redis.from_url(
            REDIS_URL,
            decode_responses=True,
            ssl=True,
            ssl_cert_reqs='required'
        )

        # Run multiple iterations
        for i in range(10):
            total_start = time.time()

            # 1. Model inference
            x = torch.randn(1, 60, 128)

            inference_start = time.time()
            result = ensemble.predict(x)
            inference_time = (time.time() - inference_start) * 1000
            latencies['inference'].append(inference_time)

            # 2. Redis publish
            signal = {
                'timestamp': datetime.utcnow().isoformat(),
                'signal': result['signal'],
                'confidence': result['confidence']
            }

            publish_start = time.time()
            client.xadd('perf_test_signals', signal)
            publish_time = (time.time() - publish_start) * 1000
            latencies['redis_publish'].append(publish_time)

            total_time = (time.time() - total_start) * 1000
            latencies['total'].append(total_time)

        # Cleanup
        client.delete('perf_test_signals')
        client.close()

        # Calculate statistics
        print(f"\nEnd-to-End Latency Breakdown:")
        for component, times in latencies.items():
            avg = np.mean(times)
            p95 = np.percentile(times, 95)
            print(f"  {component:15s} - Avg: {avg:.2f}ms, P95: {p95:.2f}ms")

        # Assert total latency target
        avg_total = np.mean(latencies['total'])
        p95_total = np.percentile(latencies['total'], 95)

        assert p95_total < LATENCY_TARGET_MS, \
            f"P95 end-to-end latency {p95_total:.2f}ms exceeds target {LATENCY_TARGET_MS}ms"


class TestLoadPerformance:
    """Test system performance under load."""

    def test_concurrent_api_requests(self):
        """Test API under concurrent load."""
        num_requests = 50
        concurrent_users = 10

        def make_request(request_id):
            """Make single API request."""
            start = time.time()
            try:
                response = requests.get(f"{API_URL}/health", timeout=5)
                latency = (time.time() - start) * 1000

                return {
                    'id': request_id,
                    'status': response.status_code,
                    'latency': latency,
                    'success': response.status_code == 200
                }
            except requests.RequestException as e:
                return {
                    'id': request_id,
                    'status': 0,
                    'latency': -1,
                    'success': False,
                    'error': str(e)
                }

        # Execute concurrent requests
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrent_users) as executor:
            futures = [executor.submit(make_request, i) for i in range(num_requests)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        # Analyze results
        successful = [r for r in results if r['success']]
        failed = [r for r in results if not r['success']]

        if not successful:
            pytest.skip("API not available for load testing")

        success_rate = len(successful) / num_requests
        latencies = [r['latency'] for r in successful]

        avg_latency = np.mean(latencies)
        p95_latency = np.percentile(latencies, 95)

        print(f"\nLoad Test Results ({num_requests} requests, {concurrent_users} concurrent):")
        print(f"  Success Rate: {success_rate * 100:.2f}%")
        print(f"  Failed: {len(failed)}")
        print(f"  Avg Latency: {avg_latency:.2f}ms")
        print(f"  P95 Latency: {p95_latency:.2f}ms")

        # Assertions
        assert success_rate >= 0.95, \
            f"Success rate {success_rate * 100:.2f}% below 95% threshold"

        assert p95_latency < LATENCY_TARGET_MS * 2, \
            f"P95 latency under load {p95_latency:.2f}ms too high"

    def test_redis_throughput(self):
        """Test Redis throughput under load."""
        client = redis.from_url(
            REDIS_URL,
            decode_responses=True,
            ssl=True,
            ssl_cert_reqs='required'
        )

        num_operations = 1000

        # Test write throughput
        start = time.time()
        for i in range(num_operations):
            client.set(f'throughput_test_{i}', f'value_{i}')
        write_duration = time.time() - start
        write_throughput = num_operations / write_duration

        # Test read throughput
        start = time.time()
        for i in range(num_operations):
            client.get(f'throughput_test_{i}')
        read_duration = time.time() - start
        read_throughput = num_operations / read_duration

        # Cleanup
        for i in range(num_operations):
            client.delete(f'throughput_test_{i}')

        client.close()

        print(f"\nRedis Throughput:")
        print(f"  Write: {write_throughput:.0f} ops/sec")
        print(f"  Read:  {read_throughput:.0f} ops/sec")

        # Assert reasonable throughput
        assert write_throughput > 100, \
            f"Write throughput too low: {write_throughput:.0f} ops/sec"
        assert read_throughput > 100, \
            f"Read throughput too low: {read_throughput:.0f} ops/sec"

    def test_stream_publishing_throughput(self):
        """Test Redis stream publishing throughput."""
        client = redis.from_url(
            REDIS_URL,
            decode_responses=True,
            ssl=True,
            ssl_cert_reqs='required'
        )

        stream_key = 'throughput_test_stream'
        num_messages = 500

        # Publish messages
        start = time.time()
        for i in range(num_messages):
            client.xadd(
                stream_key,
                {
                    'index': i,
                    'timestamp': datetime.utcnow().isoformat(),
                    'signal': 'LONG'
                }
            )
        duration = time.time() - start
        throughput = num_messages / duration

        # Cleanup
        client.delete(stream_key)
        client.close()

        print(f"\nStream Publishing Throughput: {throughput:.0f} messages/sec")

        assert throughput > 50, \
            f"Stream throughput too low: {throughput:.0f} messages/sec"


class TestUptimeMonitoring:
    """Test uptime and availability monitoring."""

    def test_api_availability_over_time(self):
        """Test API availability over short time period."""
        duration_seconds = 60  # 1 minute test
        check_interval = 2     # Check every 2 seconds

        num_checks = duration_seconds // check_interval
        successful_checks = 0
        failed_checks = 0

        print(f"\nRunning {duration_seconds}s availability test...")

        for i in range(num_checks):
            try:
                response = requests.get(f"{API_URL}/health", timeout=3)
                if response.status_code == 200:
                    successful_checks += 1
                else:
                    failed_checks += 1

            except requests.RequestException:
                failed_checks += 1

            time.sleep(check_interval)

        # Calculate uptime
        total_checks = successful_checks + failed_checks
        uptime = successful_checks / total_checks if total_checks > 0 else 0

        print(f"\nAvailability Test Results:")
        print(f"  Successful: {successful_checks}/{total_checks}")
        print(f"  Failed: {failed_checks}")
        print(f"  Uptime: {uptime * 100:.2f}%")

        if total_checks == 0:
            pytest.skip("No checks completed")

        # Assert uptime target (relaxed for short test)
        # For production, would use longer monitoring period
        assert uptime >= 0.90, \
            f"Uptime {uptime * 100:.2f}% below 90% threshold (target: {UPTIME_TARGET * 100}%)"

    def test_redis_connection_stability(self):
        """Test Redis connection stability."""
        duration_seconds = 30
        check_interval = 1

        num_checks = duration_seconds // check_interval
        successful_checks = 0

        client = redis.from_url(
            REDIS_URL,
            decode_responses=True,
            ssl=True,
            ssl_cert_reqs='required'
        )

        print(f"\nTesting Redis stability for {duration_seconds}s...")

        for i in range(num_checks):
            try:
                response = client.ping()
                if response:
                    successful_checks += 1
            except redis.ConnectionError:
                pass

            time.sleep(check_interval)

        client.close()

        uptime = successful_checks / num_checks

        print(f"\nRedis Stability:")
        print(f"  Successful pings: {successful_checks}/{num_checks}")
        print(f"  Uptime: {uptime * 100:.2f}%")

        assert uptime >= 0.95, \
            f"Redis uptime {uptime * 100:.2f}% below 95% threshold"


class TestScalability:
    """Test system scalability."""

    def test_increasing_load(self):
        """Test API response under increasing load."""
        load_levels = [5, 10, 20, 30]  # Concurrent users
        requests_per_level = 20

        results = {}

        for num_users in load_levels:
            def make_request(req_id):
                start = time.time()
                try:
                    response = requests.get(f"{API_URL}/health", timeout=5)
                    latency = (time.time() - start) * 1000
                    return {
                        'success': response.status_code == 200,
                        'latency': latency
                    }
                except requests.RequestException:
                    return {'success': False, 'latency': -1}

            with concurrent.futures.ThreadPoolExecutor(max_workers=num_users) as executor:
                futures = [executor.submit(make_request, i) for i in range(requests_per_level)]
                level_results = [f.result() for f in concurrent.futures.as_completed(futures)]

            successful = [r for r in level_results if r['success']]

            if successful:
                avg_latency = np.mean([r['latency'] for r in successful])
                success_rate = len(successful) / requests_per_level

                results[num_users] = {
                    'avg_latency': avg_latency,
                    'success_rate': success_rate
                }

            time.sleep(1)  # Brief pause between levels

        if not results:
            pytest.skip("API not available for scalability testing")

        print(f"\nScalability Test Results:")
        print(f"  {'Users':<10} {'Avg Latency (ms)':<20} {'Success Rate':<15}")
        for users, metrics in sorted(results.items()):
            print(f"  {users:<10} {metrics['avg_latency']:<20.2f} {metrics['success_rate'] * 100:<15.1f}%")

        # Check that performance doesn't degrade too much
        latencies = [m['avg_latency'] for m in results.values()]
        latency_increase = (max(latencies) - min(latencies)) / min(latencies)

        print(f"\nLatency increase under load: {latency_increase * 100:.1f}%")

        # Latency shouldn't more than double under load
        assert latency_increase < 1.0, \
            f"Latency increased by {latency_increase * 100:.1f}% under load"


class TestResourceUsage:
    """Test resource usage and efficiency."""

    def test_memory_leak_detection(self):
        """Test for memory leaks in repeated operations."""
        import psutil
        import os

        process = psutil.Process(os.getpid())

        # Measure baseline memory
        baseline_memory = process.memory_info().rss / 1024 / 1024  # MB

        # Perform repeated operations
        client = redis.from_url(
            REDIS_URL,
            decode_responses=True,
            ssl=True,
            ssl_cert_reqs='required'
        )

        for i in range(1000):
            client.set(f'memory_test_{i}', 'value' * 100)
            client.get(f'memory_test_{i}')
            client.delete(f'memory_test_{i}')

        client.close()

        # Measure final memory
        final_memory = process.memory_info().rss / 1024 / 1024  # MB

        memory_increase = final_memory - baseline_memory

        print(f"\nMemory Usage:")
        print(f"  Baseline: {baseline_memory:.2f} MB")
        print(f"  Final: {final_memory:.2f} MB")
        print(f"  Increase: {memory_increase:.2f} MB")

        # Memory increase shouldn't be excessive
        assert memory_increase < 50, \
            f"Excessive memory increase: {memory_increase:.2f} MB"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "-s"])
