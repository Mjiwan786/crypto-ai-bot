# -*- coding: utf-8 -*-
"""
Signal Publisher Integration for Kraken Scalper

Integrates the SignalPublisher from streams/publisher.py with the KrakenScalperAgent
to publish trading signals to Redis streams (signals:live or signals:paper).

This module bridges the gap between the scalper agent's internal signals and the
public-facing signal streams consumed by signals-api and signals-site.
"""

import logging
import os
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

import sys

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from streams.publisher import SignalPublisher, PublisherConfig
from models.signal_dto import SignalDTO, create_signal_dto


class ScalperSignalPublisher:
    """
    Publishes scalper signals to Redis streams for consumption by signals-api/signals-site.

    Features:
    - Converts internal ScalperSignal to StandardSignalDTO format
    - Routes signals to correct stream based on trading MODE
    - Handles idempotent publishing with retry logic
    - Integrates with existing SignalPublisher infrastructure
    """

    def __init__(
        self,
        redis_url: str,
        ssl_ca_certs: Optional[str] = None,
        mode: Optional[str] = None
    ):
        """
        Initialize signal publisher.

        Args:
            redis_url: Redis connection URL (rediss:// for TLS)
            ssl_ca_certs: Path to CA certificate for TLS
            mode: Trading mode (PAPER or LIVE), auto-detected from env if None
        """
        self.logger = logging.getLogger(__name__)

        # Determine trading mode
        if mode is None:
            mode = os.getenv("MODE") or os.getenv("TRADING_MODE") or os.getenv("BOT_MODE", "PAPER")
        self.mode = mode.upper()

        # Create publisher config
        config = PublisherConfig(
            redis_url=redis_url,
            ssl_ca_certs=ssl_ca_certs,
            max_retries=3,
            base_delay_ms=100,
            max_delay_ms=5000,
            jitter=True,
            stream_maxlen=10000,
        )

        # Create publisher instance
        self.publisher = SignalPublisher(config=config)
        self.logger.info(f"ScalperSignalPublisher initialized for {self.mode} mode")

    async def connect(self):
        """Connect to Redis"""
        self.publisher.connect()
        self.logger.info("Connected to Redis for signal publishing")

    async def disconnect(self):
        """Disconnect from Redis"""
        self.publisher.disconnect()
        self.logger.info("Disconnected from Redis")

    async def publish_scalper_signal(
        self,
        scalper_signal: dict,
        order_intent: Optional[dict] = None
    ) -> str:
        """
        Publish a scalper signal to the appropriate Redis stream.

        Args:
            scalper_signal: ScalperSignal dict with fields:
                - symbol: Trading pair (e.g., "BTC/USD")
                - side: Trade direction ("buy" or "sell")
                - confidence: Signal confidence (0.0-1.0)
                - expected_profit_bps: Expected profit in bps
                - timestamp: Signal timestamp
                - features: Dict of market features
            order_intent: Optional OrderIntent dict with pricing details

        Returns:
            Redis stream entry ID
        """

        try:
            # Extract signal data
            symbol = scalper_signal.get("symbol", "BTC/USD")
            side = scalper_signal.get("side", "buy")
            confidence = scalper_signal.get("confidence", 0.7)
            timestamp = scalper_signal.get("timestamp", time.time())

            # Get pricing from order_intent if available
            if order_intent:
                entry_price = float(order_intent.get("price", 0))
                size_usd = float(order_intent.get("size_quote_usd", 0))
            else:
                # Fallback to feature data
                features = scalper_signal.get("features", {})
                best_bid = features.get("best_bid", 0)
                best_ask = features.get("best_ask", 0)
                entry_price = (best_bid + best_ask) / 2 if best_bid and best_ask else 0
                size_usd = 100.0  # Default

            # Calculate SL/TP from bps
            expected_profit_bps = scalper_signal.get("expected_profit_bps", 10.0)
            stop_loss_bps = scalper_signal.get("stop_loss_bps", 20.0)

            # Convert bps to price
            bps_to_pct = 0.0001  # 1 bps = 0.01% = 0.0001
            if side.lower() == "buy":
                tp_price = entry_price * (1.0 + (expected_profit_bps * bps_to_pct))
                sl_price = entry_price * (1.0 - (stop_loss_bps * bps_to_pct))
            else:
                tp_price = entry_price * (1.0 - (expected_profit_bps * bps_to_pct))
                sl_price = entry_price * (1.0 + (stop_loss_bps * bps_to_pct))

            # Create SignalDTO
            ts_ms = int(timestamp * 1000)
            signal_dto = create_signal_dto(
                ts_ms=ts_ms,
                pair=symbol,
                side=side.lower(),
                entry=entry_price,
                sl=sl_price,
                tp=tp_price,
                strategy="kraken_scalper",
                confidence=confidence,
                mode=self.mode.lower(),
            )

            # Publish signal
            entry_id = self.publisher.publish(signal_dto)

            self.logger.info(
                f"Published scalper signal: {symbol} {side} @ ${entry_price:.2f} "
                f"(confidence: {confidence:.2f}) -> {entry_id}"
            )

            return entry_id

        except Exception as e:
            self.logger.error(f"Failed to publish scalper signal: {e}")
            raise

    async def publish_order_filled(
        self,
        symbol: str,
        side: str,
        fill_price: float,
        size: float,
        order_id: str
    ):
        """
        Publish a signal when an order is filled.

        This creates a "confirmation" signal showing the actual execution.

        Args:
            symbol: Trading pair
            side: Trade direction
            fill_price: Actual fill price
            size: Position size
            order_id: Exchange order ID
        """

        try:
            # Create filled signal
            ts_ms = int(time.time() * 1000)
            signal_dto = create_signal_dto(
                ts_ms=ts_ms,
                pair=symbol,
                side=side.lower(),
                entry=fill_price,
                sl=fill_price * 0.98 if side == "buy" else fill_price * 1.02,  # 2% SL
                tp=fill_price * 1.02 if side == "buy" else fill_price * 0.98,  # 2% TP
                strategy="kraken_scalper_fill",
                confidence=1.0,  # Filled orders have 100% confidence
                mode=self.mode.lower(),
            )

            # Add fill metadata
            signal_dto_dict = signal_dto.to_dict()
            signal_dto_dict["order_id"] = order_id
            signal_dto_dict["position_size"] = size
            signal_dto_dict["status"] = "filled"

            # Publish via direct XADD since we modified the dict
            stream_key = f"signals:{self.mode.lower()}"
            entry_id = self.publisher._client.xadd(
                name=stream_key,
                fields=signal_dto_dict,
                maxlen=10000,
                approximate=True
            )

            self.logger.info(f"Published fill confirmation: {symbol} {side} @ ${fill_price:.2f}")

            return entry_id

        except Exception as e:
            self.logger.error(f"Failed to publish fill confirmation: {e}")

    def get_metrics(self) -> dict:
        """Get publisher metrics"""
        return self.publisher.get_metrics()


# Convenience function for integration
def create_scalper_signal_publisher(redis_url: str, ssl_ca_certs: Optional[str] = None):
    """
    Create and connect a ScalperSignalPublisher instance.

    Args:
        redis_url: Redis connection URL
        ssl_ca_certs: Path to CA certificate

    Returns:
        Connected ScalperSignalPublisher instance
    """
    publisher = ScalperSignalPublisher(redis_url=redis_url, ssl_ca_certs=ssl_ca_certs)
    publisher.connect()
    return publisher


__all__ = [
    "ScalperSignalPublisher",
    "create_scalper_signal_publisher",
]
