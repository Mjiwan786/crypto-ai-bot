#!/usr/bin/env python3
"""
Signal Publisher Integration
============================

Integrates EnhancedScalperAgent with the new ScalperSignal schema
and publishes validated signals to Redis streams.

Features:
- Converts EnhancedSignal to ScalperSignal
- Validates signals before publishing
- Publishes to symbol-specific Redis streams
- Handles errors gracefully with alerting
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Dict, Optional

from agents.scalper.enhanced_scalper_agent import EnhancedSignal, EnhancedScalperAgent
from agents.infrastructure.redis_client import RedisCloudClient
from signals.scalper_schema import (
    ScalperSignal,
    validate_signal_safe,
    drop_invalid_signal,
    get_metrics_stream_key,
)

logger = logging.getLogger(__name__)


class SignalPublisher:
    """
    Publishes validated scalper signals to Redis streams

    Responsibilities:
    1. Convert EnhancedSignal to ScalperSignal format
    2. Validate signals before publishing
    3. Publish to symbol-specific streams (signals:<SYMBOL>:<TF>)
    4. Track metrics (signals published, errors, etc.)
    """

    def __init__(
        self,
        redis_client: RedisCloudClient,
        timeframe: str = "15s",
        model_name: str = "enhanced_scalper_v1",
    ):
        self.redis = redis_client
        self.timeframe = timeframe
        self.model_name = model_name

        # Metrics
        self.signals_generated = 0
        self.signals_published = 0
        self.signals_rejected = 0
        self.last_publish_time = 0

        logger.info(f"SignalPublisher initialized (TF={timeframe}, model={model_name})")

    def convert_enhanced_signal(
        self,
        enhanced_signal: EnhancedSignal,
        ts_exchange: int,
        ts_server: int,
    ) -> Dict:
        """
        Convert EnhancedSignal to ScalperSignal format

        Args:
            enhanced_signal: Signal from EnhancedScalperAgent
            ts_exchange: Exchange timestamp in milliseconds
            ts_server: Server timestamp in milliseconds

        Returns:
            Dictionary ready for ScalperSignal validation
        """
        return {
            "ts_exchange": ts_exchange,
            "ts_server": ts_server,
            "symbol": enhanced_signal.pair,
            "timeframe": self.timeframe,
            "side": enhanced_signal.side,
            "confidence": enhanced_signal.confidence,
            "entry": float(enhanced_signal.entry_price),
            "stop": float(enhanced_signal.stop_loss),
            "tp": float(enhanced_signal.take_profit),
            "model": self.model_name,
            "trace_id": enhanced_signal.signal_id,
        }

    async def publish_signal(
        self,
        enhanced_signal: EnhancedSignal,
        ts_exchange: Optional[int] = None,
        ts_server: Optional[int] = None,
    ) -> bool:
        """
        Validate and publish a signal to Redis

        Args:
            enhanced_signal: Signal from EnhancedScalperAgent
            ts_exchange: Exchange timestamp (defaults to current time)
            ts_server: Server timestamp (defaults to current time)

        Returns:
            True if published successfully, False otherwise
        """
        self.signals_generated += 1

        # Default timestamps to current time if not provided
        if ts_exchange is None:
            ts_exchange = int(time.time() * 1000)
        if ts_server is None:
            ts_server = int(time.time() * 1000)

        # Convert to ScalperSignal format
        signal_data = self.convert_enhanced_signal(
            enhanced_signal,
            ts_exchange=ts_exchange,
            ts_server=ts_server,
        )

        # Validate signal
        signal, error = validate_signal_safe(signal_data)

        if signal is None:
            # Invalid signal - drop and alert
            drop_invalid_signal(signal_data, error)
            self.signals_rejected += 1
            logger.error(f"Signal rejected: {error}")
            return False

        # Publish to Redis
        try:
            stream_key = signal.get_stream_key()
            signal_json = signal.to_json_str()

            # Publish to stream
            await self.redis.xadd(
                stream_key,
                {"signal": signal_json},
                maxlen=1000,  # Keep last 1000 signals per stream
            )

            self.signals_published += 1
            self.last_publish_time = ts_server

            logger.info(
                f"[PUBLISHED] {signal.symbol} {signal.side} @ {signal.entry:.2f} "
                f"(conf={signal.confidence:.2f}, stream={stream_key})"
            )

            return True

        except Exception as e:
            logger.error(f"Failed to publish signal: {e}", exc_info=True)
            return False

    async def publish_metrics(self) -> None:
        """Publish publisher metrics to Redis"""
        try:
            metrics_stream = get_metrics_stream_key()
            metrics = {
                "ts": int(time.time() * 1000),
                "signals_generated": self.signals_generated,
                "signals_published": self.signals_published,
                "signals_rejected": self.signals_rejected,
                "last_publish_time": self.last_publish_time,
                "timeframe": self.timeframe,
                "model": self.model_name,
            }

            await self.redis.xadd(
                metrics_stream,
                metrics,
                maxlen=10000,  # Keep last 10k metric entries
            )

        except Exception as e:
            logger.error(f"Failed to publish metrics: {e}")

    def get_metrics_summary(self) -> Dict:
        """Get current metrics summary"""
        return {
            "signals_generated": self.signals_generated,
            "signals_published": self.signals_published,
            "signals_rejected": self.signals_rejected,
            "publish_rate": (
                self.signals_published / self.signals_generated
                if self.signals_generated > 0
                else 0.0
            ),
            "last_publish_time": self.last_publish_time,
        }


# =============================================================================
# Self-Test
# =============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("                   SIGNAL PUBLISHER TEST")
    print("=" * 80)

    # This is a unit test without Redis connection
    from decimal import Decimal
    import uuid

    # Mock EnhancedSignal
    mock_signal = EnhancedSignal(
        pair="BTC/USD",
        side="long",
        entry_price=Decimal("45000.0"),
        take_profit=Decimal("46000.0"),
        stop_loss=Decimal("44500.0"),
        size_quote_usd=Decimal("1000.0"),
        confidence=0.85,
        strategy_alignment=True,
        regime_state="trending",
        regime_confidence=0.75,
        scalping_confidence=0.80,
        strategy_confidence=0.90,
        metadata={"strategy": "momentum"},
        signal_id=str(uuid.uuid4()),
    )

    # Mock Redis client (without actually connecting)
    class MockRedis:
        async def xadd(self, stream, data, maxlen=None):
            print(f"[MOCK] XADD to {stream}: {data}")

    # Create publisher with mock Redis
    publisher = SignalPublisher(
        redis_client=MockRedis(),
        timeframe="15s",
        model_name="test_model",
    )

    # Convert signal
    signal_data = publisher.convert_enhanced_signal(
        mock_signal,
        ts_exchange=int(time.time() * 1000),
        ts_server=int(time.time() * 1000),
    )

    print("\n1. Test signal conversion:")
    print(f"   [OK] Converted EnhancedSignal to ScalperSignal format")
    print(f"   Symbol: {signal_data['symbol']}")
    print(f"   Side: {signal_data['side']}")
    print(f"   Entry: {signal_data['entry']}")
    print(f"   Stop: {signal_data['stop']}")
    print(f"   TP: {signal_data['tp']}")

    # Validate
    from signals.scalper_schema import validate_signal_safe
    signal, error = validate_signal_safe(signal_data)

    if signal:
        print("\n2. Test validation:")
        print(f"   [OK] Signal validated successfully")
        print(f"   Stream key: {signal.get_stream_key()}")
        print(f"   Trace ID: {signal.trace_id}")
    else:
        print(f"\n2. Test validation:")
        print(f"   [FAIL] Validation failed: {error}")
        import sys
        sys.exit(1)

    print("\n3. Test metrics:")
    publisher.signals_generated = 100
    publisher.signals_published = 95
    publisher.signals_rejected = 5
    metrics = publisher.get_metrics_summary()
    print(f"   [OK] Generated: {metrics['signals_generated']}")
    print(f"   [OK] Published: {metrics['signals_published']}")
    print(f"   [OK] Rejected: {metrics['signals_rejected']}")
    print(f"   [OK] Publish rate: {metrics['publish_rate']:.2%}")

    print("\n" + "=" * 80)
    print("[PASS] All tests PASSED")
    print("=" * 80)
