"""
Whale Flow Detection Module (ai_engine/whale_detection.py)

Detects and quantifies whale activity (large traders) based on:
- Order book imbalances at critical levels
- Large transaction detection
- Whale wallet inflow/outflow tracking
- Smart money divergence signals

For Prompt 2: ML Predictor Enhancement
Author: Crypto AI Bot Team
Version: 2.0.0
"""

from __future__ import annotations

import logging
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class WhaleFlowMetrics(BaseModel):
    """Whale flow analysis results."""

    inflow_ratio: float = Field(description="Whale inflow vs total volume (0-1)")
    outflow_ratio: float = Field(description="Whale outflow vs total volume (0-1)")
    net_flow: float = Field(description="Net whale flow: inflow - outflow (-1 to 1)")
    order_book_imbalance: float = Field(description="Bid/ask imbalance at key levels (-1 to 1)")
    large_tx_count: int = Field(description="Count of large transactions in period")
    smart_money_divergence: float = Field(description="Price vs whale flow divergence (-1 to 1)")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in whale detection")


def detect_whale_flow(
    df: pd.DataFrame,
    price: float,
    volume: float,
    bid_depth: Optional[Dict[float, float]] = None,
    ask_depth: Optional[Dict[float, float]] = None,
    whale_threshold_pct: float = 0.05,
) -> WhaleFlowMetrics:
    """
    Detect whale activity from market microstructure.

    Args:
        df: OHLCV DataFrame with volume data
        price: Current price
        volume: Current volume
        bid_depth: Order book bids {price: size}
        ask_depth: Order book asks {price: size}
        whale_threshold_pct: % threshold for whale detection (default 5% of avg volume)

    Returns:
        WhaleFlowMetrics with inflow/outflow ratios and signals
    """
    try:
        if df.empty or len(df) < 20:
            return WhaleFlowMetrics(
                inflow_ratio=0.0,
                outflow_ratio=0.0,
                net_flow=0.0,
                order_book_imbalance=0.0,
                large_tx_count=0,
                smart_money_divergence=0.0,
                confidence=0.0,
            )

        # Calculate average volume for whale threshold
        avg_volume = df["volume"].tail(50).mean()
        whale_volume_threshold = avg_volume * whale_threshold_pct

        # 1. Detect large transactions (whale trades)
        large_txs = df[df["volume"] > whale_volume_threshold].tail(20)
        large_tx_count = len(large_txs)

        # 2. Infer inflow vs outflow from price action + volume
        # Upward price moves with high volume = whale buying (inflow)
        # Downward price moves with high volume = whale selling (outflow)
        df_copy = df.copy()
        df_copy["price_change"] = df_copy["close"].pct_change()
        df_copy["vol_weighted_flow"] = df_copy["price_change"] * df_copy["volume"]

        # Positive flow = buying, negative = selling
        recent_flows = df_copy["vol_weighted_flow"].tail(20)
        total_abs_flow = recent_flows.abs().sum()

        if total_abs_flow > 0:
            inflow = recent_flows[recent_flows > 0].sum() / total_abs_flow
            outflow = abs(recent_flows[recent_flows < 0].sum()) / total_abs_flow
        else:
            inflow = 0.0
            outflow = 0.0

        # Normalize to [0, 1]
        inflow_ratio = float(np.clip(inflow, 0.0, 1.0))
        outflow_ratio = float(np.clip(outflow, 0.0, 1.0))
        net_flow = float(np.clip(inflow_ratio - outflow_ratio, -1.0, 1.0))

        # 3. Order book imbalance (if available)
        order_book_imbalance = 0.0
        if bid_depth and ask_depth:
            # Calculate depth within 1% of current price
            price_range = price * 0.01

            bid_volume = sum(
                size for p, size in bid_depth.items()
                if price - price_range <= p <= price
            )
            ask_volume = sum(
                size for p, size in ask_depth.items()
                if price <= p <= price + price_range
            )

            total_depth = bid_volume + ask_volume
            if total_depth > 0:
                order_book_imbalance = float((bid_volume - ask_volume) / total_depth)
                order_book_imbalance = np.clip(order_book_imbalance, -1.0, 1.0)

        # 4. Smart money divergence (price vs whale flow)
        # If price down but whales buying = bullish divergence (positive)
        # If price up but whales selling = bearish divergence (negative)
        recent_price_change = float(df["close"].iloc[-1] / df["close"].iloc[-20] - 1.0)
        price_direction = np.sign(recent_price_change)
        flow_direction = np.sign(net_flow)

        # Divergence: opposite signs indicate smart money divergence
        if price_direction != 0 and flow_direction != 0:
            if price_direction != flow_direction:
                # Divergence detected: use whale flow direction (contrarian)
                smart_money_divergence = -float(price_direction) * abs(net_flow)
            else:
                # Confirmation: whales and price align
                smart_money_divergence = flow_direction * 0.5
        else:
            smart_money_divergence = 0.0

        smart_money_divergence = float(np.clip(smart_money_divergence, -1.0, 1.0))

        # 5. Confidence calculation
        # Higher confidence with:
        # - More large transactions
        # - Higher volume
        # - Order book data available
        data_quality = min(1.0, len(df) / 50.0)  # More data = higher confidence
        volume_quality = min(1.0, volume / (avg_volume * 2.0))  # High volume = higher confidence
        orderbook_quality = 1.0 if (bid_depth and ask_depth) else 0.5
        whale_tx_quality = min(1.0, large_tx_count / 5.0)  # 5+ large txs = high confidence

        confidence = float(np.mean([data_quality, volume_quality, orderbook_quality, whale_tx_quality]))
        confidence = np.clip(confidence, 0.0, 1.0)

        logger.debug(
            "Whale flow detected: inflow=%.2f, outflow=%.2f, net=%.2f, imbalance=%.2f, "
            "large_txs=%d, divergence=%.2f, conf=%.2f",
            inflow_ratio, outflow_ratio, net_flow, order_book_imbalance,
            large_tx_count, smart_money_divergence, confidence
        )

        return WhaleFlowMetrics(
            inflow_ratio=inflow_ratio,
            outflow_ratio=outflow_ratio,
            net_flow=net_flow,
            order_book_imbalance=order_book_imbalance,
            large_tx_count=large_tx_count,
            smart_money_divergence=smart_money_divergence,
            confidence=confidence,
        )

    except Exception as e:
        logger.exception("Error detecting whale flow: %s", e)
        return WhaleFlowMetrics(
            inflow_ratio=0.0,
            outflow_ratio=0.0,
            net_flow=0.0,
            order_book_imbalance=0.0,
            large_tx_count=0,
            smart_money_divergence=0.0,
            confidence=0.0,
        )


def calculate_whale_pressure(
    whale_metrics: WhaleFlowMetrics,
    funding_rate: float = 0.0,
) -> Tuple[float, str]:
    """
    Calculate overall whale pressure signal.

    Combines whale flow, order book, and divergence into single signal.

    Args:
        whale_metrics: WhaleFlowMetrics from detect_whale_flow
        funding_rate: Perpetual futures funding rate for confirmation

    Returns:
        (pressure_score, explanation)
        pressure_score: -1 (bearish) to 1 (bullish)
    """
    # Weight different components
    weights = {
        "net_flow": 0.4,
        "order_book": 0.3,
        "divergence": 0.3,
    }

    # Aggregate signals
    pressure = (
        weights["net_flow"] * whale_metrics.net_flow +
        weights["order_book"] * whale_metrics.order_book_imbalance +
        weights["divergence"] * whale_metrics.smart_money_divergence
    )

    # Adjust by confidence
    pressure = pressure * whale_metrics.confidence

    # Funding rate confirmation (if whales buying but funding very negative = contrarian opportunity)
    if funding_rate < -0.0001 and pressure > 0.3:
        pressure *= 1.2  # Boost bullish signal
        explanation = "Strong whale buying despite negative funding (contrarian)"
    elif funding_rate > 0.0001 and pressure < -0.3:
        pressure *= 1.2  # Boost bearish signal
        explanation = "Strong whale selling despite positive funding (contrarian)"
    elif abs(pressure) > 0.5:
        direction = "bullish" if pressure > 0 else "bearish"
        explanation = f"Strong {direction} whale pressure (net_flow={whale_metrics.net_flow:.2f})"
    elif abs(pressure) > 0.2:
        direction = "bullish" if pressure > 0 else "bearish"
        explanation = f"Moderate {direction} whale pressure"
    else:
        explanation = "Neutral whale pressure"

    pressure = float(np.clip(pressure, -1.0, 1.0))

    return pressure, explanation


# Self-check for development/testing
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    logger.info("Running whale detection self-check...")

    try:
        # Create synthetic OHLCV data
        np.random.seed(42)
        n_rows = 100

        dates = pd.date_range("2025-01-01", periods=n_rows, freq="1T")
        prices = 50000 + np.cumsum(np.random.randn(n_rows) * 100)

        test_df = pd.DataFrame({
            "timestamp": dates,
            "open": prices,
            "high": prices * 1.002,
            "low": prices * 0.998,
            "close": prices,
            "volume": np.random.exponential(100, n_rows),
        })

        # Add some whale activity (large volume spikes)
        test_df.loc[50:55, "volume"] *= 10  # Whale buying
        test_df.loc[50:55, "close"] *= 1.01  # Price up

        # Test whale detection
        current_price = float(test_df["close"].iloc[-1])
        current_volume = float(test_df["volume"].iloc[-1])

        # Mock order book
        bid_depth = {current_price * 0.999: 1000, current_price * 0.998: 500}
        ask_depth = {current_price * 1.001: 300, current_price * 1.002: 200}

        metrics = detect_whale_flow(
            df=test_df,
            price=current_price,
            volume=current_volume,
            bid_depth=bid_depth,
            ask_depth=ask_depth,
        )

        # Validate
        assert 0.0 <= metrics.inflow_ratio <= 1.0
        assert 0.0 <= metrics.outflow_ratio <= 1.0
        assert -1.0 <= metrics.net_flow <= 1.0
        assert -1.0 <= metrics.order_book_imbalance <= 1.0
        assert metrics.large_tx_count >= 0
        assert -1.0 <= metrics.smart_money_divergence <= 1.0
        assert 0.0 <= metrics.confidence <= 1.0

        logger.info("Whale metrics: %s", metrics)

        # Test pressure calculation
        pressure, explanation = calculate_whale_pressure(metrics, funding_rate=0.0001)
        assert -1.0 <= pressure <= 1.0
        assert len(explanation) > 0

        logger.info("Whale pressure: %.2f (%s)", pressure, explanation)
        logger.info("Self-check passed!")

        sys.exit(0)

    except Exception as e:
        logger.error("Self-check failed: %s", e)
        sys.exit(1)
