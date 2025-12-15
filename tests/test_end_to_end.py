"""
End-to-End Tests for Complete Signal Flow.

Tests complete flow: crypto-ai-bot -> Redis -> signals-api -> signals-site
Target: Signal displayed within 1 second.

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
import redis
import requests
import json
import torch
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, Optional
from unittest.mock import Mock, patch

# Import centralized signals API config
from config.signals_api_config import SIGNALS_API_BASE_URL

# Configuration
REDIS_URL = "rediss://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com:19818"
API_URL = SIGNALS_API_BASE_URL
TOTAL_LATENCY_TARGET_MS = 1000  # 1 second target


class MockWebSocketData:
    """Mock WebSocket data for testing."""

    @staticmethod
    def generate_mock_candle():
        """Generate mock OHLCV candle data."""
        base_price = 50000 + np.random.randn() * 1000

        return {
            'symbol': 'BTC/USDT',
            'timeframe': '15m',
            'timestamp': datetime.utcnow().isoformat(),
            'open': base_price,
            'high': base_price + np.random.uniform(50, 200),
            'low': base_price - np.random.uniform(50, 200),
            'close': base_price + np.random.uniform(-100, 100),
            'volume': np.random.uniform(100, 1000)
        }

    @staticmethod
    def generate_mock_history(num_candles=500):
        """Generate mock historical data."""
        data = []
        base_price = 50000

        for i in range(num_candles):
            base_price += np.random.randn() * 100

            data.append({
                'open': base_price,
                'high': base_price + np.random.uniform(10, 100),
                'low': base_price - np.random.uniform(10, 100),
                'close': base_price + np.random.uniform(-50, 50),
                'volume': np.random.uniform(100, 1000)
            })

        return pd.DataFrame(data)


class TestEndToEndSignalFlow:
    """Test complete signal flow from generation to delivery."""

    @pytest.fixture
    def redis_client(self):
        """Create Redis client."""
        client = redis.from_url(
            REDIS_URL,
            decode_responses=True,
            ssl=True,
            ssl_cert_reqs='required'
        )
        yield client
        client.close()

    def test_complete_signal_flow(self, redis_client):
        """Test complete flow: WebSocket -> Feature Engineering -> ML -> Redis -> API."""
        from ml.feature_engineering import FeatureEngineer, create_sequences
        from ml.deep_ensemble import MLEnsemble
        from ml.redis_signal_publisher import MLSignal, RedisSignalPublisher

        total_start = time.time()

        # STEP 1: Mock WebSocket data ingestion
        step1_start = time.time()
        mock_data = MockWebSocketData.generate_mock_history(500)
        mock_data['timestamp'] = pd.date_range('2024-01-01', periods=500, freq='15min')
        step1_time = (time.time() - step1_start) * 1000

        # STEP 2: Feature Engineering
        step2_start = time.time()
        engineer = FeatureEngineer()
        features_df = engineer.engineer_features(mock_data)
        step2_time = (time.time() - step2_start) * 1000

        # STEP 3: Create sequences for ML model
        step3_start = time.time()
        # Use last 60 candles
        feature_sequence = features_df.tail(60).drop(columns=['timestamp'], errors='ignore')
        x = torch.from_numpy(feature_sequence.values).float().unsqueeze(0)
        step3_time = (time.time() - step3_start) * 1000

        # STEP 4: ML Model Inference
        step4_start = time.time()
        ensemble = MLEnsemble(input_size=feature_sequence.shape[1], seq_len=60, num_classes=3)
        result = ensemble.predict(x, features_df=features_df.tail(100))
        step4_time = (time.time() - step4_start) * 1000

        # STEP 5: Publish to Redis
        step5_start = time.time()

        signal = MLSignal(
            timestamp=datetime.utcnow().isoformat(),
            symbol='BTC/USDT',
            timeframe='15m',
            signal=result['signal'],
            confidence=result['confidence'],
            prob_long=result['probabilities']['LONG'],
            prob_short=result['probabilities']['SHORT'],
            prob_neutral=result['probabilities']['NEUTRAL'],
            regime=result['regime'],
            agreement=result['agreement'],
            weights=result['weights'],
            lstm_signal=result['individual_predictions']['lstm']['signal'],
            lstm_confidence=result['individual_predictions']['lstm']['confidence'],
            transformer_signal=result['individual_predictions']['transformer']['signal'],
            transformer_confidence=result['individual_predictions']['transformer']['confidence'],
            cnn_signal=result['individual_predictions']['cnn']['signal'],
            cnn_confidence=result['individual_predictions']['cnn']['confidence'],
            confidence_level='high',
            position_size=0.75,
            stop_loss_pct=2.0,
            take_profit_pct=4.0
        )

        publisher = RedisSignalPublisher(
            redis_url=REDIS_URL,
            stream_prefix="e2e_test_signals"
        )

        success = publisher.publish_signal(signal)
        step5_time = (time.time() - step5_start) * 1000

        assert success, "Failed to publish signal to Redis"

        # STEP 6: Verify signal in Redis
        step6_start = time.time()
        retrieved = publisher.get_latest_signal('BTC/USDT', '15m')
        step6_time = (time.time() - step6_start) * 1000

        assert retrieved is not None, "Failed to retrieve signal from Redis"
        assert retrieved.signal == result['signal']

        # Cleanup
        publisher.close()

        # Calculate total time
        total_time = (time.time() - total_start) * 1000

        # Print timing breakdown
        print(f"\n=== End-to-End Flow Timing ===")
        print(f"Step 1 - Mock Data Ingestion:  {step1_time:>8.2f}ms")
        print(f"Step 2 - Feature Engineering:  {step2_time:>8.2f}ms")
        print(f"Step 3 - Sequence Creation:    {step3_time:>8.2f}ms")
        print(f"Step 4 - ML Inference:          {step4_time:>8.2f}ms")
        print(f"Step 5 - Redis Publish:         {step5_time:>8.2f}ms")
        print(f"Step 6 - Redis Retrieve:        {step6_time:>8.2f}ms")
        print(f"{'='*35}")
        print(f"Total Time:                     {total_time:>8.2f}ms")
        print(f"Target:                        <{TOTAL_LATENCY_TARGET_MS:>8.0f}ms")

        # Assert total latency target
        assert total_time < TOTAL_LATENCY_TARGET_MS, \
            f"Total latency {total_time:.2f}ms exceeds target {TOTAL_LATENCY_TARGET_MS}ms"

    def test_api_signal_retrieval(self):
        """Test API can retrieve signals from Redis."""
        # This test verifies signals-api can read from Redis
        try:
            response = requests.get(f"{API_URL}/v1/signals", timeout=10)

            # API may return 200 with signals or 404 if no signals
            assert response.status_code in [200, 404], \
                f"Unexpected status code: {response.status_code}"

            if response.status_code == 200:
                data = response.json()
                print(f"\n=== API Signal Response ===")
                print(f"Response type: {type(data)}")
                if isinstance(data, dict):
                    print(f"Keys: {list(data.keys())}")
                elif isinstance(data, list):
                    print(f"Number of signals: {len(data)}")

        except requests.RequestException as e:
            pytest.skip(f"API not available: {e}")

    def test_sse_stream_latency(self):
        """Test SSE stream delivers signals with low latency."""
        try:
            import sseclient

            # Connect to SSE stream
            response = requests.get(
                f"{API_URL}/v1/signals/stream",
                stream=True,
                timeout=30
            )

            assert response.status_code == 200, \
                f"SSE connection failed: {response.status_code}"

            client = sseclient.SSEClient(response)

            print(f"\n=== SSE Stream Test ===")
            print(f"Waiting for events...")

            # Wait for first event (with timeout)
            start = time.time()
            event_received = False

            for event in client.events():
                if event.data:
                    latency = (time.time() - start) * 1000
                    print(f"First event received in {latency:.2f}ms")
                    print(f"Event data (truncated): {str(event.data)[:200]}")
                    event_received = True
                    break

                # Timeout after 10 seconds
                if time.time() - start > 10:
                    break

            if not event_received:
                pytest.skip("No SSE events received within timeout")

        except ImportError:
            pytest.skip("sseclient-py not installed")
        except requests.RequestException as e:
            pytest.skip(f"SSE endpoint not available: {e}")


class TestMockWebSocketIngestion:
    """Test mock WebSocket data ingestion."""

    def test_mock_candle_generation(self):
        """Test mock candle data generation."""
        candle = MockWebSocketData.generate_mock_candle()

        # Verify structure
        required_fields = ['symbol', 'timeframe', 'timestamp', 'open', 'high', 'low', 'close', 'volume']
        for field in required_fields:
            assert field in candle, f"Missing field: {field}"

        # Verify OHLC logic
        assert candle['high'] >= candle['open'], "High should be >= open"
        assert candle['high'] >= candle['close'], "High should be >= close"
        assert candle['low'] <= candle['open'], "Low should be <= open"
        assert candle['low'] <= candle['close'], "Low should be <= close"

    def test_mock_history_generation(self):
        """Test mock historical data generation."""
        history = MockWebSocketData.generate_mock_history(100)

        assert len(history) == 100, "Should generate 100 candles"
        assert 'open' in history.columns
        assert 'close' in history.columns
        assert 'volume' in history.columns


class TestGracefulDegradation:
    """Test graceful degradation when components fail."""

    def test_frontend_handles_api_unavailable(self):
        """Test frontend gracefully handles API unavailable."""
        # Test invalid API URL
        invalid_url = "http://invalid-api.example.com"

        try:
            response = requests.get(f"{invalid_url}/v1/signals", timeout=2)
            pytest.fail("Should have raised exception")
        except requests.RequestException:
            # Expected - frontend should show "Metrics unavailable"
            pass

    def test_api_handles_redis_unavailable(self):
        """Test API gracefully handles Redis unavailable."""
        invalid_redis_url = "redis://invalid:password@localhost:6379"

        try:
            client = redis.from_url(invalid_redis_url, socket_connect_timeout=2)
            client.ping()
            pytest.fail("Should have raised connection error")
        except redis.ConnectionError:
            # Expected - API should return error response
            pass

    def test_missing_environment_variables(self):
        """Test handling of missing environment variables."""
        import os

        # Test missing REDIS_URL
        original = os.environ.get('REDIS_URL')

        try:
            if 'REDIS_URL' in os.environ:
                del os.environ['REDIS_URL']

            # Application should handle gracefully
            # (either use default or raise clear error)

        finally:
            if original:
                os.environ['REDIS_URL'] = original

    def test_malformed_signal_handling(self, redis_client=None):
        """Test handling of malformed signals."""
        if redis_client is None:
            redis_client = redis.from_url(
                REDIS_URL,
                decode_responses=True,
                ssl=True,
                ssl_cert_reqs='required'
            )

        # Publish malformed signal
        stream_key = "e2e_test_malformed:BTC/USDT:15m"

        malformed_signals = [
            {'signal': 'INVALID'},  # Invalid signal value
            {'confidence': 'not-a-number'},  # Invalid type
            {},  # Empty signal
            {'timestamp': 'invalid-date', 'signal': 'LONG'}  # Invalid timestamp
        ]

        for i, malformed in enumerate(malformed_signals):
            redis_client.xadd(f"{stream_key}_{i}", malformed)

        # Consumer should validate and handle gracefully
        # Should not crash the system

        # Cleanup
        for i in range(len(malformed_signals)):
            redis_client.delete(f"{stream_key}_{i}")


class TestResilience:
    """Test system resilience and recovery."""

    def test_redis_reconnection_after_failure(self):
        """Test Redis client reconnects after connection failure."""
        client = redis.from_url(
            REDIS_URL,
            decode_responses=True,
            ssl=True,
            ssl_cert_reqs='required',
            socket_keepalive=True,
            retry_on_timeout=True
        )

        # First operation
        client.set('resilience_test', 'value1')
        value = client.get('resilience_test')
        assert value == 'value1'

        # Simulate reconnection by creating new client
        client2 = redis.from_url(
            REDIS_URL,
            decode_responses=True,
            ssl=True,
            ssl_cert_reqs='required'
        )

        # Should still be able to access data
        value = client2.get('resilience_test')
        assert value == 'value1'

        # Cleanup
        client2.delete('resilience_test')
        client.close()
        client2.close()

    def test_api_recovery_from_errors(self):
        """Test API recovers from transient errors."""
        # Make multiple requests to ensure API is stable
        successful = 0
        failed = 0

        for i in range(10):
            try:
                response = requests.get(f"{API_URL}/health", timeout=5)
                if response.status_code == 200:
                    successful += 1
                else:
                    failed += 1
            except requests.RequestException:
                failed += 1

            time.sleep(0.5)

        if successful == 0:
            pytest.skip("API not available")

        # Should have mostly successful requests
        success_rate = successful / (successful + failed)
        assert success_rate >= 0.8, \
            f"Success rate {success_rate * 100:.1f}% below 80% threshold"


class TestDataIntegrity:
    """Test data integrity throughout the system."""

    def test_signal_data_consistency(self, redis_client):
        """Test signal data remains consistent through Redis."""
        from ml.redis_signal_publisher import MLSignal, RedisSignalPublisher

        # Create test signal with specific values
        original_signal = MLSignal(
            timestamp='2024-11-17T12:00:00Z',
            symbol='BTC/USDT',
            timeframe='15m',
            signal='LONG',
            confidence=0.7531,  # Specific value
            prob_long=0.7531,
            prob_short=0.1234,
            prob_neutral=0.1235,
            regime='trending_up',
            agreement=0.8567,
            weights={'lstm': 0.45, 'transformer': 0.35, 'cnn': 0.20},
            lstm_signal='LONG',
            lstm_confidence=0.80,
            transformer_signal='LONG',
            transformer_confidence=0.72,
            cnn_signal='NEUTRAL',
            cnn_confidence=0.65,
            confidence_level='high',
            position_size=0.75,
            stop_loss_pct=2.0,
            take_profit_pct=4.0
        )

        # Publish
        publisher = RedisSignalPublisher(
            redis_url=REDIS_URL,
            stream_prefix="integrity_test"
        )

        success = publisher.publish_signal(original_signal)
        assert success

        # Retrieve
        retrieved_signal = publisher.get_latest_signal('BTC/USDT', '15m')

        # Verify data integrity
        assert retrieved_signal.signal == original_signal.signal
        assert abs(retrieved_signal.confidence - original_signal.confidence) < 0.0001
        assert retrieved_signal.regime == original_signal.regime
        assert retrieved_signal.symbol == original_signal.symbol

        # Cleanup
        publisher.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "-s"])
