"""
Pytest fixtures for scalper agent tests.

Provides reusable test fixtures with no external dependencies:
- Mock configurations
- Sample OHLCV data
- Kraken WebSocket message fixtures
- Mock gateway implementations
- Test data generators

All fixtures are hermetic - no live network calls, no Redis, no file I/O.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict, List

import numpy as np
import pandas as pd
import pytest


# ======================== Configuration Fixtures ========================


@pytest.fixture
def sample_config_dict() -> Dict:
    """Sample scalper configuration as dictionary"""
    return {
        "agent_id": "test_scalper",
        "mode": "paper",
        "risk": {
            "daily_stop_loss": -100.0,
            "max_total_exposure_usd": 10000.0,
            "per_symbol_max_exposure": 0.2,
            "max_concurrent_positions": 5,
        },
        "scalp": {
            "target_bps": 10,
            "stop_loss_bps": 5,
            "max_hold_seconds": 300,
            "max_spread_bps": 20,
            "max_trades_per_minute": 10,
            "max_trades_per_hour": 100,
        },
        "trading": {
            "pairs": ["BTC/USD"],
            "timeframe": "1m",
        },
        "kraken": {
            "api_key": "test_key",
            "api_secret": "test_secret",
            "base_url": "https://api.kraken.com",
        },
    }


# ======================== OHLCV Data Fixtures ========================


@pytest.fixture
def sample_btcusdt_1m() -> pd.DataFrame:
    """
    Sample 1-minute BTCUSDT OHLCV data.

    Generates realistic price movement with:
    - Trending price action
    - Realistic OHLCV relationships
    - Volume variability
    - 100 bars total (100 minutes)
    """
    np.random.seed(42)  # Deterministic

    # Generate price series with trend + noise
    base_price = 50000.0
    trend = np.linspace(0, 500, 100)  # Upward trend
    noise = np.random.normal(0, 50, 100)
    close_prices = base_price + trend + noise

    # Generate OHLC from close prices
    data = []
    for i, close in enumerate(close_prices):
        # Realistic OHLC relationships
        high = close + abs(np.random.normal(0, 20))
        low = close - abs(np.random.normal(0, 20))
        open_price = close_prices[i - 1] if i > 0 else close

        # Ensure OHLC logic: L <= O,C <= H
        low = min(low, open_price, close)
        high = max(high, open_price, close)

        volume = np.random.uniform(1.0, 10.0)

        data.append(
            {
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            }
        )

    # Create DataFrame with datetime index
    timestamps = pd.date_range(start="2025-01-01", periods=100, freq="1min", tz="UTC")
    df = pd.DataFrame(data, index=timestamps)

    return df


@pytest.fixture
def sample_ethusdt_1m() -> pd.DataFrame:
    """Sample 1-minute ETHUSDT OHLCV data"""
    np.random.seed(43)  # Different seed for ETH

    base_price = 3000.0
    trend = np.linspace(0, 50, 100)
    noise = np.random.normal(0, 10, 100)
    close_prices = base_price + trend + noise

    data = []
    for i, close in enumerate(close_prices):
        high = close + abs(np.random.normal(0, 5))
        low = close - abs(np.random.normal(0, 5))
        open_price = close_prices[i - 1] if i > 0 else close

        low = min(low, open_price, close)
        high = max(high, open_price, close)

        volume = np.random.uniform(5.0, 50.0)

        data.append(
            {
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            }
        )

    timestamps = pd.date_range(start="2025-01-01", periods=100, freq="1min", tz="UTC")
    df = pd.DataFrame(data, index=timestamps)

    return df


# ======================== Kraken WebSocket Fixtures ========================


@pytest.fixture
def kraken_ws_ticker_message() -> Dict:
    """Sample Kraken WebSocket ticker message"""
    return {
        "channel": "ticker",
        "type": "update",
        "data": [
            {
                "symbol": "BTC/USD",
                "bid": 49950.0,
                "bid_qty": 1.234,
                "ask": 50050.0,
                "ask_qty": 2.345,
                "last": 50000.0,
                "volume": 123.456,
                "vwap": 49980.0,
                "low": 49500.0,
                "high": 50500.0,
                "change": 100.0,
                "change_pct": 0.2,
            }
        ],
    }


@pytest.fixture
def kraken_ws_trade_message() -> Dict:
    """Sample Kraken WebSocket trade message"""
    return {
        "channel": "trade",
        "type": "update",
        "data": [
            {
                "symbol": "BTC/USD",
                "side": "buy",
                "price": 50000.0,
                "qty": 0.5,
                "ord_type": "limit",
                "trade_id": 123456789,
                "timestamp": "2025-01-01T12:00:00.000000Z",
            },
            {
                "symbol": "BTC/USD",
                "side": "sell",
                "price": 50010.0,
                "qty": 0.3,
                "ord_type": "market",
                "trade_id": 123456790,
                "timestamp": "2025-01-01T12:00:01.000000Z",
            },
        ],
    }


@pytest.fixture
def kraken_ws_orderbook_message() -> Dict:
    """Sample Kraken WebSocket orderbook snapshot message"""
    return {
        "channel": "book",
        "type": "snapshot",
        "data": [
            {
                "symbol": "BTC/USD",
                "bids": [
                    {"price": 49990.0, "qty": 1.0},
                    {"price": 49980.0, "qty": 2.0},
                    {"price": 49970.0, "qty": 3.0},
                    {"price": 49960.0, "qty": 1.5},
                    {"price": 49950.0, "qty": 2.5},
                ],
                "asks": [
                    {"price": 50010.0, "qty": 1.0},
                    {"price": 50020.0, "qty": 2.0},
                    {"price": 50030.0, "qty": 3.0},
                    {"price": 50040.0, "qty": 1.5},
                    {"price": 50050.0, "qty": 2.5},
                ],
                "checksum": 123456789,
                "timestamp": "2025-01-01T12:00:00.000000Z",
            }
        ],
    }


@pytest.fixture
def kraken_ws_orderbook_update() -> Dict:
    """Sample Kraken WebSocket orderbook update message"""
    return {
        "channel": "book",
        "type": "update",
        "data": [
            {
                "symbol": "BTC/USD",
                "bids": [
                    {"price": 49995.0, "qty": 0.5},  # New bid
                    {"price": 49980.0, "qty": 0.0},  # Remove bid
                ],
                "asks": [
                    {"price": 50015.0, "qty": 0.8},  # New ask
                    {"price": 50030.0, "qty": 0.0},  # Remove ask
                ],
                "timestamp": "2025-01-01T12:00:01.000000Z",
            }
        ],
    }


@pytest.fixture
def kraken_ws_error_message() -> Dict:
    """Sample Kraken WebSocket error message"""
    return {
        "channel": "book",
        "type": "error",
        "error": "Rate limit exceeded",
        "error_code": "EAPI:Rate limit exceeded",
    }


# ======================== Trade Fixtures ========================


@pytest.fixture
def sample_trades() -> List[Dict]:
    """Sample trade list for analysis"""
    return [
        {
            "ts": 1704110400000,  # 2025-01-01 12:00:00
            "symbol": "BTC/USD",
            "side": "buy",
            "qty": 0.1,
            "price": 50000.0,
            "fee_usd": 3.0,
            "slippage_bps": 2.0,
            "order_type": "limit",
        },
        {
            "ts": 1704110460000,  # 2025-01-01 12:01:00
            "symbol": "BTC/USD",
            "side": "sell",
            "qty": 0.1,
            "price": 50050.0,
            "fee_usd": 3.0,
            "slippage_bps": 2.0,
            "order_type": "market",
        },
        {
            "ts": 1704110520000,  # 2025-01-01 12:02:00
            "symbol": "BTC/USD",
            "side": "buy",
            "qty": 0.05,
            "price": 50060.0,
            "fee_usd": 1.5,
            "slippage_bps": 2.0,
            "order_type": "limit",
        },
        {
            "ts": 1704110580000,  # 2025-01-01 12:03:00
            "symbol": "BTC/USD",
            "side": "sell",
            "qty": 0.05,
            "price": 50010.0,
            "fee_usd": 1.5,
            "slippage_bps": 2.0,
            "order_type": "market",
        },
    ]


# ======================== Mock Gateway Fixtures ========================


@pytest.fixture
def mock_order_response() -> Dict:
    """Sample order response from exchange"""
    return {
        "order_id": "test_order_123",
        "symbol": "BTC/USD",
        "side": "buy",
        "order_type": "limit",
        "status": "open",
        "size": 0.1,
        "filled_size": 0.0,
        "price": 50000.0,
        "average_fill_price": None,
        "timestamp": 1704110400.0,
        "client_order_id": "client_123",
        "fee": 0.0,
        "fee_currency": "USD",
    }


@pytest.fixture
def mock_fill_response() -> Dict:
    """Sample fill response from exchange"""
    return {
        "order_id": "test_order_123",
        "symbol": "BTC/USD",
        "side": "buy",
        "order_type": "limit",
        "status": "closed",
        "size": 0.1,
        "filled_size": 0.1,
        "price": 50000.0,
        "average_fill_price": 50005.0,
        "timestamp": 1704110401.0,
        "client_order_id": "client_123",
        "fee": 3.0,
        "fee_currency": "USD",
    }


@pytest.fixture
def mock_balance_response() -> Dict:
    """Sample balance response from exchange"""
    return {
        "USD": {"available": 10000.0, "total": 10000.0, "reserved": 0.0},
        "BTC": {"available": 0.5, "total": 0.5, "reserved": 0.0},
    }


# ======================== Helper Functions ========================


def generate_price_series(
    base_price: float = 50000.0,
    num_points: int = 100,
    trend: float = 0.0,
    volatility: float = 50.0,
    seed: int = 42,
) -> np.ndarray:
    """
    Generate realistic price series with trend and volatility.

    Args:
        base_price: Starting price
        num_points: Number of price points
        trend: Linear trend per point
        volatility: Standard deviation of noise
        seed: Random seed for reproducibility

    Returns:
        Array of prices
    """
    np.random.seed(seed)
    trend_component = np.linspace(0, trend * num_points, num_points)
    noise_component = np.random.normal(0, volatility, num_points)
    return base_price + trend_component + noise_component


def generate_ohlcv_from_prices(
    prices: np.ndarray,
    start_time: str = "2025-01-01",
    freq: str = "1min",
) -> pd.DataFrame:
    """
    Generate OHLCV DataFrame from price series.

    Args:
        prices: Array of close prices
        start_time: Start timestamp
        freq: Frequency string (pandas offset alias)

    Returns:
        DataFrame with OHLCV data and datetime index
    """
    data = []
    for i, close in enumerate(prices):
        # Realistic OHLC from close
        high = close + abs(np.random.normal(0, close * 0.001))
        low = close - abs(np.random.normal(0, close * 0.001))
        open_price = prices[i - 1] if i > 0 else close

        # Ensure OHLC logic
        low = min(low, open_price, close)
        high = max(high, open_price, close)

        volume = np.random.uniform(1.0, 10.0)

        data.append(
            {
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            }
        )

    timestamps = pd.date_range(start=start_time, periods=len(prices), freq=freq, tz="UTC")
    return pd.DataFrame(data, index=timestamps)


# ======================== Pytest Configuration ========================


def pytest_configure(config):
    """Configure pytest markers"""
    config.addinivalue_line("markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')")
    config.addinivalue_line("markers", "integration: marks tests as integration tests")
    config.addinivalue_line("markers", "unit: marks tests as unit tests")


# ======================== Export ========================

__all__ = [
    "sample_config_dict",
    "sample_btcusdt_1m",
    "sample_ethusdt_1m",
    "kraken_ws_ticker_message",
    "kraken_ws_trade_message",
    "kraken_ws_orderbook_message",
    "kraken_ws_orderbook_update",
    "kraken_ws_error_message",
    "sample_trades",
    "mock_order_response",
    "mock_fill_response",
    "mock_balance_response",
    "generate_price_series",
    "generate_ohlcv_from_prices",
]
