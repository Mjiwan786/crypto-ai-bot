"""
Redis Signal Publisher for ML Predictions.

Publishes probability-rich trading signals from ML ensemble to Redis streams
for consumption by trading strategies.

Author: AI Architecture Team
Version: 1.0.0
Date: 2025-11-17
"""

import redis
import json
import time
import logging
from typing import Dict, Optional, List
from datetime import datetime
import numpy as np
from dataclasses import dataclass, asdict

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class MLSignal:
    """
    ML Signal data structure.

    Contains all probability and confidence information for trading decisions.
    """
    # Basic info
    timestamp: str
    symbol: str
    timeframe: str

    # Signal
    signal: str  # 'LONG', 'SHORT', 'NEUTRAL'
    confidence: float  # 0-1

    # Probabilities
    prob_long: float
    prob_short: float
    prob_neutral: float

    # Ensemble details
    regime: str
    agreement: float  # Model agreement 0-1
    weights: Dict[str, float]  # Model weights used

    # Individual model predictions
    lstm_signal: str
    lstm_confidence: float
    transformer_signal: str
    transformer_confidence: float
    cnn_signal: str
    cnn_confidence: float

    # Risk parameters
    confidence_level: str  # 'very_low', 'low', 'medium', 'high', 'very_high'
    position_size: float  # 0-1
    stop_loss_pct: float
    take_profit_pct: float

    # Regime features (optional)
    regime_features: Optional[Dict[str, float]] = None

    # Metadata
    model_version: str = "v1.0"
    generation_time_ms: Optional[float] = None


class RedisSignalPublisher:
    """
    Publishes ML signals to Redis streams.

    Features:
    - Publishes to Redis streams for real-time consumption
    - Stores latest signals in Redis hash
    - Maintains signal history
    - Health check and monitoring
    """

    def __init__(self,
                 redis_url: str,
                 stream_prefix: str = "ml_signals",
                 max_stream_length: int = 10000,
                 enable_persistence: bool = True):
        """
        Args:
            redis_url: Redis connection URL
            stream_prefix: Prefix for stream keys
            max_stream_length: Maximum stream length (for trimming)
            enable_persistence: Store latest signals in hash
        """
        self.redis_url = redis_url
        self.stream_prefix = stream_prefix
        self.max_stream_length = max_stream_length
        self.enable_persistence = enable_persistence

        # Connect to Redis
        logger.info(f"Connecting to Redis: {redis_url}")
        self.redis_client = redis.from_url(
            redis_url,
            decode_responses=True,
            ssl=True,
            ssl_cert_reqs='required'
        )

        # Test connection
        self.redis_client.ping()
        logger.info("Successfully connected to Redis")

        # Stats
        self.published_count = 0
        self.error_count = 0

    def publish_signal(self, signal: MLSignal) -> bool:
        """
        Publish ML signal to Redis.

        Args:
            signal: MLSignal to publish

        Returns:
            True if published successfully, False otherwise
        """
        try:
            start_time = time.time()

            # Convert signal to dictionary
            signal_dict = asdict(signal)

            # Remove None values
            signal_dict = {k: v for k, v in signal_dict.items() if v is not None}

            # Convert numpy types to Python types
            for key, value in signal_dict.items():
                if isinstance(value, (np.integer, np.floating)):
                    signal_dict[key] = float(value)
                elif isinstance(value, dict):
                    signal_dict[key] = json.dumps(value)

            # Stream key: ml_signals:{symbol}:{timeframe}
            stream_key = f"{self.stream_prefix}:{signal.symbol}:{signal.timeframe}"

            # Publish to stream
            message_id = self.redis_client.xadd(
                name=stream_key,
                fields=signal_dict,
                maxlen=self.max_stream_length,
                approximate=True
            )

            # Store latest signal in hash (for quick lookup)
            if self.enable_persistence:
                hash_key = f"{self.stream_prefix}:latest:{signal.symbol}:{signal.timeframe}"
                signal_json = json.dumps(signal_dict, default=str)
                self.redis_client.setex(
                    hash_key,
                    3600,  # Expire after 1 hour
                    signal_json
                )

            # Track latency
            latency_ms = (time.time() - start_time) * 1000

            # Update stats
            self.published_count += 1

            logger.info(
                f"Published ML signal: {signal.symbol} {signal.timeframe} "
                f"-> {signal.signal} (conf: {signal.confidence:.3f}, "
                f"regime: {signal.regime}) [latency: {latency_ms:.2f}ms]"
            )

            # Publish metrics
            self._publish_metrics(latency_ms)

            return True

        except Exception as e:
            self.error_count += 1
            logger.error(f"Error publishing signal: {e}")
            return False

    def publish_batch(self, signals: List[MLSignal]) -> Dict[str, int]:
        """
        Publish multiple signals in batch.

        Args:
            signals: List of MLSignals to publish

        Returns:
            Dictionary with success/failure counts
        """
        success_count = 0
        failure_count = 0

        for signal in signals:
            if self.publish_signal(signal):
                success_count += 1
            else:
                failure_count += 1

        logger.info(f"Batch publish: {success_count} succeeded, {failure_count} failed")

        return {
            'success': success_count,
            'failure': failure_count
        }

    def get_latest_signal(self, symbol: str, timeframe: str) -> Optional[MLSignal]:
        """
        Get latest signal for symbol and timeframe.

        Args:
            symbol: Trading symbol
            timeframe: Timeframe

        Returns:
            Latest MLSignal or None
        """
        try:
            hash_key = f"{self.stream_prefix}:latest:{symbol}:{timeframe}"
            signal_json = self.redis_client.get(hash_key)

            if signal_json is None:
                return None

            signal_dict = json.loads(signal_json)

            # Parse nested JSON fields
            if 'weights' in signal_dict and isinstance(signal_dict['weights'], str):
                signal_dict['weights'] = json.loads(signal_dict['weights'])
            if 'regime_features' in signal_dict and isinstance(signal_dict['regime_features'], str):
                signal_dict['regime_features'] = json.loads(signal_dict['regime_features'])

            return MLSignal(**signal_dict)

        except Exception as e:
            logger.error(f"Error getting latest signal: {e}")
            return None

    def get_signal_history(self,
                          symbol: str,
                          timeframe: str,
                          count: int = 100) -> List[MLSignal]:
        """
        Get signal history from stream.

        Args:
            symbol: Trading symbol
            timeframe: Timeframe
            count: Number of signals to retrieve

        Returns:
            List of MLSignals
        """
        try:
            stream_key = f"{self.stream_prefix}:{symbol}:{timeframe}"

            # Read from stream (most recent first)
            messages = self.redis_client.xrevrange(
                stream_key,
                count=count
            )

            signals = []
            for message_id, fields in messages:
                # Parse nested JSON fields
                if 'weights' in fields and isinstance(fields['weights'], str):
                    fields['weights'] = json.loads(fields['weights'])
                if 'regime_features' in fields and isinstance(fields['regime_features'], str):
                    fields['regime_features'] = json.loads(fields['regime_features'])

                signals.append(MLSignal(**fields))

            return signals

        except Exception as e:
            logger.error(f"Error getting signal history: {e}")
            return []

    def _publish_metrics(self, latency_ms: float) -> None:
        """
        Publish monitoring metrics to Redis.

        Args:
            latency_ms: Publishing latency in milliseconds
        """
        try:
            metrics_key = f"{self.stream_prefix}:metrics"

            metrics = {
                'published_count': self.published_count,
                'error_count': self.error_count,
                'last_publish_time': datetime.utcnow().isoformat(),
                'last_latency_ms': latency_ms
            }

            self.redis_client.hmset(metrics_key, metrics)
            self.redis_client.expire(metrics_key, 3600)

        except Exception as e:
            logger.warning(f"Error publishing metrics: {e}")

    def get_stats(self) -> Dict:
        """
        Get publisher statistics.

        Returns:
            Dictionary of stats
        """
        try:
            metrics_key = f"{self.stream_prefix}:metrics"
            metrics = self.redis_client.hgetall(metrics_key)

            return {
                'published_count': self.published_count,
                'error_count': self.error_count,
                'success_rate': self.published_count / (self.published_count + self.error_count)
                if (self.published_count + self.error_count) > 0 else 0,
                'last_publish_time': metrics.get('last_publish_time'),
                'last_latency_ms': float(metrics.get('last_latency_ms', 0))
            }

        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {}

    def health_check(self) -> bool:
        """
        Check Redis connection health.

        Returns:
            True if healthy, False otherwise
        """
        try:
            self.redis_client.ping()
            return True
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False

    def cleanup_old_signals(self, symbol: str, timeframe: str, keep_count: int = 1000) -> int:
        """
        Cleanup old signals from stream.

        Args:
            symbol: Trading symbol
            timeframe: Timeframe
            keep_count: Number of signals to keep

        Returns:
            Number of signals removed
        """
        try:
            stream_key = f"{self.stream_prefix}:{symbol}:{timeframe}"

            # Trim stream
            self.redis_client.xtrim(stream_key, maxlen=keep_count, approximate=True)

            logger.info(f"Cleaned up old signals for {symbol} {timeframe}")
            return 0  # Redis doesn't return count for xtrim

        except Exception as e:
            logger.error(f"Error cleaning up signals: {e}")
            return 0

    def close(self):
        """Close Redis connection."""
        try:
            self.redis_client.close()
            logger.info("Redis connection closed")
        except Exception as e:
            logger.error(f"Error closing Redis connection: {e}")


class SignalSubscriber:
    """
    Subscribe to ML signals from Redis streams.

    For testing and monitoring purposes.
    """

    def __init__(self, redis_url: str, stream_prefix: str = "ml_signals"):
        """
        Args:
            redis_url: Redis connection URL
            stream_prefix: Prefix for stream keys
        """
        self.redis_url = redis_url
        self.stream_prefix = stream_prefix

        logger.info(f"Connecting subscriber to Redis: {redis_url}")
        self.redis_client = redis.from_url(
            redis_url,
            decode_responses=True,
            ssl=True,
            ssl_cert_reqs='required'
        )

        self.redis_client.ping()
        logger.info("Subscriber connected to Redis")

    def subscribe(self,
                 symbol: str,
                 timeframe: str,
                 callback,
                 block_ms: int = 1000):
        """
        Subscribe to signals for symbol/timeframe.

        Args:
            symbol: Trading symbol
            timeframe: Timeframe
            callback: Function to call with new signals
            block_ms: Blocking timeout in milliseconds
        """
        stream_key = f"{self.stream_prefix}:{symbol}:{timeframe}"
        last_id = '$'  # Start from latest

        logger.info(f"Subscribing to {stream_key}")

        while True:
            try:
                # Read new messages
                messages = self.redis_client.xread(
                    {stream_key: last_id},
                    block=block_ms,
                    count=10
                )

                if not messages:
                    continue

                for stream, stream_messages in messages:
                    for message_id, fields in stream_messages:
                        # Parse signal
                        if 'weights' in fields and isinstance(fields['weights'], str):
                            fields['weights'] = json.loads(fields['weights'])
                        if 'regime_features' in fields and isinstance(fields['regime_features'], str):
                            fields['regime_features'] = json.loads(fields['regime_features'])

                        signal = MLSignal(**fields)

                        # Call callback
                        callback(signal)

                        # Update last ID
                        last_id = message_id

            except KeyboardInterrupt:
                logger.info("Subscription interrupted")
                break
            except Exception as e:
                logger.error(f"Error in subscription: {e}")
                time.sleep(1)

    def close(self):
        """Close Redis connection."""
        try:
            self.redis_client.close()
            logger.info("Subscriber connection closed")
        except Exception as e:
            logger.error(f"Error closing subscriber connection: {e}")


if __name__ == "__main__":
    # Test signal publisher
    print("Testing Redis Signal Publisher...\n")

    # Redis URL (from environment or config)
    REDIS_URL = "redis://default:password@localhost:6379"

    # Create publisher
    try:
        publisher = RedisSignalPublisher(
            redis_url=REDIS_URL,
            stream_prefix="ml_signals_test"
        )

        # Test health check
        print("1. Health Check:")
        print(f"   Healthy: {publisher.health_check()}")

        # Create test signal
        print("\n2. Publishing Test Signal:")
        test_signal = MLSignal(
            timestamp=datetime.utcnow().isoformat(),
            symbol="BTC/USDT",
            timeframe="15m",
            signal="LONG",
            confidence=0.75,
            prob_long=0.75,
            prob_short=0.10,
            prob_neutral=0.15,
            regime="trending_up",
            agreement=0.85,
            weights={'lstm': 0.45, 'transformer': 0.35, 'cnn': 0.20},
            lstm_signal="LONG",
            lstm_confidence=0.80,
            transformer_signal="LONG",
            transformer_confidence=0.72,
            cnn_signal="NEUTRAL",
            cnn_confidence=0.65,
            confidence_level="high",
            position_size=0.75,
            stop_loss_pct=2.0,
            take_profit_pct=4.0,
            regime_features={'adx': 32.5, 'atr_normalized': 0.025, 'momentum': 0.015}
        )

        success = publisher.publish_signal(test_signal)
        print(f"   Published: {success}")

        # Get latest signal
        print("\n3. Retrieving Latest Signal:")
        latest = publisher.get_latest_signal("BTC/USDT", "15m")
        if latest:
            print(f"   Signal: {latest.signal}")
            print(f"   Confidence: {latest.confidence}")
            print(f"   Regime: {latest.regime}")

        # Publish batch
        print("\n4. Publishing Batch:")
        batch_signals = [
            test_signal,
            MLSignal(
                timestamp=datetime.utcnow().isoformat(),
                symbol="ETH/USDT",
                timeframe="15m",
                signal="SHORT",
                confidence=0.65,
                prob_long=0.15,
                prob_short=0.65,
                prob_neutral=0.20,
                regime="trending_down",
                agreement=0.75,
                weights={'lstm': 0.45, 'transformer': 0.35, 'cnn': 0.20},
                lstm_signal="SHORT",
                lstm_confidence=0.70,
                transformer_signal="SHORT",
                transformer_confidence=0.68,
                cnn_signal="SHORT",
                cnn_confidence=0.60,
                confidence_level="medium",
                position_size=0.50,
                stop_loss_pct=1.5,
                take_profit_pct=3.0
            )
        ]

        batch_result = publisher.publish_batch(batch_signals)
        print(f"   Success: {batch_result['success']}, Failed: {batch_result['failure']}")

        # Get stats
        print("\n5. Publisher Stats:")
        stats = publisher.get_stats()
        for key, value in stats.items():
            print(f"   {key}: {value}")

        # Close
        publisher.close()

        print("\n✓ Redis Signal Publisher test completed!")

    except redis.ConnectionError as e:
        print(f"\n✗ Redis connection error: {e}")
        print("  Make sure Redis is running and the URL is correct")
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
