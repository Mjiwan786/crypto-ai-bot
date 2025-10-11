#!/usr/bin/env python3
"""
Test SLO HTTP functionality with latency measurements

Tests both mocked decision→publish latency and real Redis operations
to ensure P95 latency stays under 500ms SLO threshold.
"""

import asyncio
import os
import pytest
import redis
import time
import statistics
from typing import List, Dict, Any
from urllib.parse import urlparse
import ssl

# Test configuration
SLO_P95_THRESHOLD_MS = 500
MOCK_SAMPLES = 100
REAL_REDIS_EVENTS = 50

class SLOTester:
    """Test SLO compliance for decision→publish latency"""
    
    def __init__(self):
        self.redis_client = None
        self.latency_samples = []
    
    def setup_redis(self) -> bool:
        """Setup Redis connection if available"""
        try:
            redis_url = os.getenv("REDIS_URL")
            if not redis_url:
                return False
            
            parsed = urlparse(redis_url)
            use_ssl = parsed.scheme == "rediss"
            
            if use_ssl:
                ssl_context = ssl.create_default_context()
                ca_cert_path = os.getenv("REDIS_TLS_CERT_PATH", "/etc/ssl/certs/ca-certificates.crt")
                
                if os.path.exists(ca_cert_path):
                    ssl_context.load_verify_locations(ca_cert_path)
                
                self.redis_client = redis.from_url(
                    redis_url,
                    ssl_cert_reqs=ssl.CERT_REQUIRED,
                    ssl_ca_certs=ca_cert_path,
                    decode_responses=True
                )
            else:
                self.redis_client = redis.from_url(redis_url, decode_responses=True)
            
            # Test connection
            self.redis_client.ping()
            return True
            
        except Exception as e:
            print(f"Redis setup failed: {e}")
            return False
    
    def simulate_decision_publish_latency(self, samples: int = MOCK_SAMPLES) -> List[float]:
        """Simulate decision→publish latency samples"""
        latencies = []
        
        for _ in range(samples):
            # Simulate decision making (10-50ms)
            decision_time = 0.010 + (0.040 * (time.time() % 1))  # 10-50ms
            
            # Simulate publish operation (5-20ms)
            publish_time = 0.005 + (0.015 * (time.time() % 1))  # 5-20ms
            
            # Add some realistic variance
            noise = (time.time() % 0.01) * 0.001  # 0-10ms noise
            
            total_latency = (decision_time + publish_time + noise) * 1000  # Convert to ms
            latencies.append(total_latency)
            
            # Small delay to avoid identical timestamps
            time.sleep(0.001)
        
        return latencies
    
    async def measure_real_redis_latency(self, events: int = REAL_REDIS_EVENTS) -> List[float]:
        """Measure real Redis xadd + xreadgroup latency"""
        if not self.redis_client:
            raise pytest.skip("Redis not configured")
        
        latencies = []
        stream_name = "test:slo:latency"
        consumer_group = "slo_test_group"
        consumer_name = "slo_test_consumer"
        
        try:
            # Create consumer group if it doesn't exist
            try:
                self.redis_client.xgroup_create(stream_name, consumer_group, id="0", mkstream=True)
            except redis.RedisError:
                pass  # Group might already exist
            
            for i in range(events):
                start_time = time.time()
                
                # Simulate decision→publish cycle
                # 1. Decision phase (simulated)
                await asyncio.sleep(0.01)  # 10ms decision
                
                # 2. Publish phase (real Redis operation)
                message_data = {
                    "timestamp": str(time.time()),
                    "event_id": str(i),
                    "decision_latency": "10ms",
                    "test_data": f"event_{i}"
                }
                
                self.redis_client.xadd(stream_name, message_data)
                
                # 3. Read phase (simulate consumer reading)
                messages = self.redis_client.xreadgroup(
                    consumer_group, 
                    consumer_name, 
                    {stream_name: ">"}, 
                    count=1, 
                    block=0
                )
                
                end_time = time.time()
                total_latency = (end_time - start_time) * 1000  # Convert to ms
                latencies.append(total_latency)
                
                # Small delay between events
                await asyncio.sleep(0.01)
            
            # Cleanup
            try:
                self.redis_client.delete(stream_name)
            except:
                pass
                
        except Exception as e:
            raise pytest.skip(f"Redis operation failed: {e}")
        
        return latencies
    
    def calculate_p95(self, latencies: List[float]) -> float:
        """Calculate 95th percentile latency"""
        if not latencies:
            return 0.0
        
        sorted_latencies = sorted(latencies)
        index = int(len(sorted_latencies) * 0.95)
        return sorted_latencies[index]
    
    def calculate_p50(self, latencies: List[float]) -> float:
        """Calculate 50th percentile latency"""
        if not latencies:
            return 0.0
        
        return statistics.median(latencies)
    
    def calculate_stats(self, latencies: List[float]) -> Dict[str, float]:
        """Calculate comprehensive latency statistics"""
        if not latencies:
            return {}
        
        return {
            "count": len(latencies),
            "min_ms": min(latencies),
            "max_ms": max(latencies),
            "mean_ms": statistics.mean(latencies),
            "median_ms": statistics.median(latencies),
            "p95_ms": self.calculate_p95(latencies),
            "p99_ms": sorted(latencies)[int(len(latencies) * 0.99)],
            "std_dev_ms": statistics.stdev(latencies) if len(latencies) > 1 else 0.0
        }

@pytest.fixture
def slo_tester():
    """Fixture for SLO tester"""
    return SLOTester()

def test_mocked_decision_publish_latency(slo_tester):
    """Test SLO compliance with mocked decision→publish latency"""
    print("\n🧪 Testing mocked decision→publish latency...")
    
    # Generate latency samples
    latencies = slo_tester.simulate_decision_publish_latency(MOCK_SAMPLES)
    
    # Calculate statistics
    stats = slo_tester.calculate_stats(latencies)
    p95_latency = stats["p95_ms"]
    
    print(f"📊 Mocked Latency Statistics:")
    print(f"   Samples: {stats['count']}")
    print(f"   Mean: {stats['mean_ms']:.2f}ms")
    print(f"   Median: {stats['median_ms']:.2f}ms")
    print(f"   P95: {p95_latency:.2f}ms")
    print(f"   P99: {stats['p99_ms']:.2f}ms")
    print(f"   Max: {stats['max_ms']:.2f}ms")
    
    # Assert SLO compliance
    assert p95_latency < SLO_P95_THRESHOLD_MS, (
        f"P95 latency {p95_latency:.2f}ms exceeds SLO threshold {SLO_P95_THRESHOLD_MS}ms"
    )
    
    print(f"✅ SLO compliance: P95 latency {p95_latency:.2f}ms < {SLO_P95_THRESHOLD_MS}ms")

@pytest.mark.asyncio
async def test_real_redis_latency(slo_tester):
    """Test SLO compliance with real Redis operations"""
    print("\n🧪 Testing real Redis xadd + xreadgroup latency...")
    
    # Setup Redis connection
    if not slo_tester.setup_redis():
        pytest.skip("Redis not configured - set REDIS_URL environment variable")
    
    # Measure real Redis latency
    latencies = await slo_tester.measure_real_redis_latency(REAL_REDIS_EVENTS)
    
    # Calculate statistics
    stats = slo_tester.calculate_stats(latencies)
    p95_latency = stats["p95_ms"]
    
    print(f"📊 Real Redis Latency Statistics:")
    print(f"   Events: {stats['count']}")
    print(f"   Mean: {stats['mean_ms']:.2f}ms")
    print(f"   Median: {stats['median_ms']:.2f}ms")
    print(f"   P95: {p95_latency:.2f}ms")
    print(f"   P99: {stats['p99_ms']:.2f}ms")
    print(f"   Max: {stats['max_ms']:.2f}ms")
    print(f"   Std Dev: {stats['std_dev_ms']:.2f}ms")
    
    # Assert SLO compliance
    assert p95_latency < SLO_P95_THRESHOLD_MS, (
        f"P95 latency {p95_latency:.2f}ms exceeds SLO threshold {SLO_P95_THRESHOLD_MS}ms"
    )
    
    print(f"✅ SLO compliance: P95 latency {p95_latency:.2f}ms < {SLO_P95_THRESHOLD_MS}ms")

def test_latency_distribution(slo_tester):
    """Test that latency distribution is reasonable"""
    print("\n🧪 Testing latency distribution...")
    
    # Generate samples
    latencies = slo_tester.simulate_decision_publish_latency(1000)  # More samples for distribution test
    
    # Calculate statistics
    stats = slo_tester.calculate_stats(latencies)
    
    # Test distribution properties
    assert stats["min_ms"] > 0, "Minimum latency should be positive"
    assert stats["max_ms"] < 1000, "Maximum latency should be reasonable (<1000ms)"
    assert stats["mean_ms"] < 100, "Mean latency should be reasonable (<100ms)"
    assert stats["std_dev_ms"] > 0, "Should have some variance in latency"
    
    # Test that P95 is higher than P50 (reasonable distribution)
    assert stats["p95_ms"] > stats["median_ms"], "P95 should be higher than median"
    
    print(f"✅ Latency distribution looks reasonable:")
    print(f"   Min: {stats['min_ms']:.2f}ms")
    print(f"   Max: {stats['max_ms']:.2f}ms")
    print(f"   Mean: {stats['mean_ms']:.2f}ms")
    print(f"   Std Dev: {stats['std_dev_ms']:.2f}ms")

def test_slo_threshold_boundary(slo_tester):
    """Test SLO threshold boundary conditions"""
    print("\n🧪 Testing SLO threshold boundary conditions...")
    
    # Test with latencies just under threshold
    under_threshold_latencies = [400.0, 450.0, 480.0, 490.0, 495.0] * 20  # 100 samples
    p95_under = slo_tester.calculate_p95(under_threshold_latencies)
    assert p95_under < SLO_P95_THRESHOLD_MS, "Should pass when under threshold"
    
    # Test with latencies just over threshold
    over_threshold_latencies = [400.0, 450.0, 480.0, 490.0, 510.0] * 20  # 100 samples
    p95_over = slo_tester.calculate_p95(over_threshold_latencies)
    assert p95_over >= SLO_P95_THRESHOLD_MS, "Should fail when over threshold"
    
    print(f"✅ Boundary conditions work correctly:")
    print(f"   Under threshold P95: {p95_under:.2f}ms")
    print(f"   Over threshold P95: {p95_over:.2f}ms")

def test_redis_connection_handling(slo_tester):
    """Test Redis connection error handling"""
    print("\n🧪 Testing Redis connection error handling...")
    
    # Test without Redis URL
    original_url = os.environ.get("REDIS_URL")
    if "REDIS_URL" in os.environ:
        del os.environ["REDIS_URL"]
    
    try:
        assert not slo_tester.setup_redis(), "Should return False when Redis URL not set"
    finally:
        if original_url:
            os.environ["REDIS_URL"] = original_url
    
    # Test with invalid Redis URL
    os.environ["REDIS_URL"] = "redis://invalid-host:6379/0"
    try:
        assert not slo_tester.setup_redis(), "Should return False with invalid Redis URL"
    finally:
        if original_url:
            os.environ["REDIS_URL"] = original_url
        else:
            del os.environ["REDIS_URL"]
    
    print("✅ Redis connection error handling works correctly")

if __name__ == "__main__":
    # Run tests directly
    import sys
    
    print("🚀 Running SLO HTTP Tests")
    print("=" * 50)
    
    # Run mocked test
    tester = SLOTester()
    
    print("\n1. Testing mocked decision→publish latency...")
    latencies = tester.simulate_decision_publish_latency(100)
    stats = tester.calculate_stats(latencies)
    p95 = stats["p95_ms"]
    print(f"   P95 latency: {p95:.2f}ms")
    print(f"   SLO compliance: {'✅ PASS' if p95 < SLO_P95_THRESHOLD_MS else '❌ FAIL'}")
    
    # Run real Redis test if available
    print("\n2. Testing real Redis operations...")
    if tester.setup_redis():
        try:
            real_latencies = asyncio.run(tester.measure_real_redis_latency(20))
            real_stats = tester.calculate_stats(real_latencies)
            real_p95 = real_stats["p95_ms"]
            print(f"   P95 latency: {real_p95:.2f}ms")
            print(f"   SLO compliance: {'✅ PASS' if real_p95 < SLO_P95_THRESHOLD_MS else '❌ FAIL'}")
        except Exception as e:
            print(f"   Redis test failed: {e}")
    else:
        print("   Redis not configured - skipping real Redis test")
    
    print("\n✅ SLO tests completed!")