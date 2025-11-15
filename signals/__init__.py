"""
Signals Package - Standardized signal schema and publisher for crypto-ai-bot.

This package provides:
- Unified signal schema with idempotency (signals/schema.py)
- Redis stream publisher for signals:live:<PAIR> and signals:paper:<PAIR> (signals/publisher.py)

Usage:
    from signals.schema import Signal, create_signal
    from signals.publisher import SignalPublisher

    # Create signal
    signal = create_signal(
        pair="BTC/USD",
        side="long",
        entry=50000.0,
        sl=49000.0,
        tp=52000.0,
        strategy="momentum_v1",
        confidence=0.85,
        mode="paper"
    )

    # Publish to Redis
    publisher = SignalPublisher(redis_url=REDIS_URL, redis_cert_path=CERT_PATH)
    await publisher.connect()
    await publisher.publish(signal)
"""

from .schema import Signal, create_signal, generate_signal_id
from .publisher import SignalPublisher

__all__ = [
    "Signal",
    "create_signal",
    "generate_signal_id",
    "SignalPublisher",
]
