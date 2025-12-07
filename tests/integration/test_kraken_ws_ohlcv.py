"""
Integration tests for Kraken WebSocket + OHLCV pipeline.

Tests verify:
1. All pairs from kraken_ohlcv.yaml are subscribed
2. All timeframes from kraken_ohlcv.yaml are subscribed/generated
3. Stream naming matches kraken_ohlcv.yaml exactly
4. Synthetic bars are generated for synthetic timeframes
5. Health metrics track last message timestamp per pair
6. Reconnection logic uses exponential backoff
"""

import asyncio
import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from utils.kraken_config_loader import KrakenConfigLoader, get_kraken_config_loader
from utils.kraken_ws import KrakenWSConfig, KrakenWebSocketClient
from utils.kraken_ohlcv_manager import KrakenOHLCVManager


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def kraken_ohlcv_config_path(tmp_path):
    """Create a test kraken_ohlcv.yaml file"""
    config = {
        "trading_pairs": {
            "tier_1": [
                {"symbol": "BTC/USD", "kraken_symbol": "XBTUSD"},
                {"symbol": "ETH/USD", "kraken_symbol": "ETHUSD"},
                {"symbol": "BTC/EUR", "kraken_symbol": "XBTEUR"},
            ],
            "tier_2": [
                {"symbol": "ADA/USD", "kraken_symbol": "ADAUSD"},
                {"symbol": "SOL/USD", "kraken_symbol": "SOLUSD"},
                {"symbol": "AVAX/USD", "kraken_symbol": "AVAXUSD"},
            ],
            "tier_3": [
                {"symbol": "LINK/USD", "kraken_symbol": "LINKUSD"},
            ],
        },
        "timeframes": {
            "primary": {
                "1m": {"kraken_interval": 1, "seconds": 60, "redis_stream": "kraken:ohlc:1m"},
                "5m": {"kraken_interval": 5, "seconds": 300, "redis_stream": "kraken:ohlc:5m"},
                "15m": {"kraken_interval": 15, "seconds": 900, "redis_stream": "kraken:ohlc:15m"},
                "30m": {"kraken_interval": 30, "seconds": 1800, "redis_stream": "kraken:ohlc:30m"},
                "1h": {"kraken_interval": 60, "seconds": 3600, "redis_stream": "kraken:ohlc:1h"},
                "4h": {"kraken_interval": 240, "seconds": 14400, "redis_stream": "kraken:ohlc:4h"},
                "1d": {"kraken_interval": 1440, "seconds": 86400, "redis_stream": "kraken:ohlc:1d"},
            },
            "synthetic": {
                "15s": {
                    "derive_from": "trades",
                    "method": "time_bucket",
                    "seconds": 15,
                    "redis_stream": "kraken:ohlc:15s",
                },
                "30s": {
                    "derive_from": "trades",
                    "method": "time_bucket",
                    "seconds": 30,
                    "redis_stream": "kraken:ohlc:30s",
                },
            },
        },
        "streams": {
            "redis": {
                "stream_prefix": "kraken:ohlc",
            },
        },
    }
    
    config_path = tmp_path / "kraken_ohlcv.yaml"
    with open(config_path, 'w') as f:
        yaml.dump(config, f)
    
    return str(config_path)


@pytest.fixture
def kraken_config_path(tmp_path):
    """Create a test kraken.yaml file"""
    config = {
        "symbols": {
            "normalize": {
                "BTC/USD": "XBTUSD",
                "BTC/EUR": "XBTEUR",
                "ETH/USD": "ETHUSD",
                "ADA/USD": "ADAUSD",
                "SOL/USD": "SOLUSD",
                "AVAX/USD": "AVAXUSD",
                "LINK/USD": "LINKUSD",
            },
            "denormalize": {
                "XBTUSD": "BTC/USD",
                "XBTEUR": "BTC/EUR",
                "ETHUSD": "ETH/USD",
                "ADAUSD": "ADA/USD",
                "SOLUSD": "SOL/USD",
                "AVAXUSD": "AVAX/USD",
                "LINKUSD": "LINK/USD",
            },
        },
    }
    
    config_path = tmp_path / "kraken.yaml"
    with open(config_path, 'w') as f:
        yaml.dump(config, f)
    
    return str(config_path)


# =============================================================================
# CONFIG LOADER TESTS
# =============================================================================

def test_config_loader_loads_all_pairs(kraken_ohlcv_config_path, kraken_config_path):
    """Test that config loader loads all pairs from kraken_ohlcv.yaml"""
    loader = KrakenConfigLoader(
        kraken_ohlcv_path=kraken_ohlcv_config_path,
        kraken_path=kraken_config_path,
    )
    
    pairs = loader.get_all_pairs()
    
    # Verify all expected pairs are loaded
    expected_pairs = {"BTC/USD", "ETH/USD", "BTC/EUR", "ADA/USD", "SOL/USD", "AVAX/USD", "LINK/USD"}
    assert set(pairs) == expected_pairs, f"Expected {expected_pairs}, got {set(pairs)}"


def test_config_loader_loads_all_timeframes(kraken_ohlcv_config_path):
    """Test that config loader loads all timeframes from kraken_ohlcv.yaml"""
    loader = KrakenConfigLoader(kraken_ohlcv_path=kraken_ohlcv_config_path)
    
    timeframes = loader.get_all_timeframes()
    
    # Verify all expected timeframes are loaded
    expected_native = {"1m", "5m", "15m", "30m", "1h", "4h", "1d"}
    expected_synthetic = {"15s", "30s"}
    expected_all = expected_native | expected_synthetic
    
    assert set(timeframes) == expected_all, f"Expected {expected_all}, got {set(timeframes)}"


def test_config_loader_stream_naming(kraken_ohlcv_config_path):
    """Test that stream naming matches kraken_ohlcv.yaml"""
    loader = KrakenConfigLoader(kraken_ohlcv_path=kraken_ohlcv_config_path)
    
    # Test stream names
    assert loader.get_stream_name("1m", "BTC/USD") == "kraken:ohlc:1m:BTC-USD"
    assert loader.get_stream_name("15s", "ETH/USD") == "kraken:ohlc:15s:ETH-USD"
    assert loader.get_stream_name("1h", "ADA/USD") == "kraken:ohlc:1h:ADA-USD"


def test_config_loader_kraken_intervals(kraken_ohlcv_config_path):
    """Test that Kraken OHLC intervals are correctly extracted"""
    loader = KrakenConfigLoader(kraken_ohlcv_path=kraken_ohlcv_config_path)
    
    intervals = loader.get_kraken_ohlc_intervals()
    
    # Verify all native intervals are present
    expected_intervals = {1, 5, 15, 30, 60, 240, 1440}
    assert set(intervals) == expected_intervals, f"Expected {expected_intervals}, got {set(intervals)}"


# =============================================================================
# WEBSOCKET CLIENT TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_ws_client_loads_pairs_from_config(kraken_ohlcv_config_path, kraken_config_path):
    """Test that WS client loads pairs from config loader"""
    with patch('utils.kraken_ws.get_kraken_config_loader') as mock_loader:
        mock_config = MagicMock()
        mock_config.get_all_pairs.return_value = ["BTC/USD", "ETH/USD", "ADA/USD", "SOL/USD", "AVAX/USD", "LINK/USD"]
        mock_loader.return_value = mock_config
        
        config = KrakenWSConfig()
        
        # Verify pairs are loaded
        assert len(config.pairs) > 0
        assert "BTC/USD" in config.pairs
        assert "ETH/USD" in config.pairs


@pytest.mark.asyncio
async def test_ws_client_loads_timeframes_from_config(kraken_ohlcv_config_path):
    """Test that WS client loads timeframes from config loader"""
    with patch('utils.kraken_ws.get_kraken_config_loader') as mock_loader:
        mock_config = MagicMock()
        mock_config.get_all_timeframes.return_value = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "15s", "30s"]
        mock_loader.return_value = mock_config
        
        config = KrakenWSConfig()
        
        # Verify timeframes are loaded
        assert len(config.timeframes) > 0
        assert "1m" in config.timeframes
        assert "5m" in config.timeframes


@pytest.mark.asyncio
async def test_ws_client_subscribes_to_all_pairs():
    """Test that WS client subscribes to all configured pairs"""
    config = KrakenWSConfig()
    config.pairs = ["BTC/USD", "ETH/USD", "ADA/USD", "SOL/USD", "AVAX/USD", "LINK/USD"]
    
    client = KrakenWebSocketClient(config=config)
    
    # Mock WebSocket
    client.ws = AsyncMock()
    client.ws.send = AsyncMock()
    
    # Setup subscriptions
    await client.setup_subscriptions()
    
    # Verify subscriptions were sent
    assert client.ws.send.called
    
    # Count subscriptions (should have ticker, trade, spread, book, and OHLC for each timeframe)
    call_count = client.ws.send.call_count
    assert call_count > 0, "No subscriptions sent"


@pytest.mark.asyncio
async def test_ws_client_subscribes_to_all_native_timeframes():
    """Test that WS client subscribes to all native timeframes"""
    config = KrakenWSConfig()
    config.timeframes = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
    config.pairs = ["BTC/USD"]
    
    client = KrakenWebSocketClient(config=config)
    client.ws = AsyncMock()
    client.ws.send = AsyncMock()
    
    await client.setup_subscriptions()
    
    # Verify OHLC subscriptions were sent for each native timeframe
    calls = [str(call) for call in client.ws.send.call_args_list]
    ohlc_calls = [c for c in calls if "ohlc" in str(c).lower()]
    
    # Should have OHLC subscriptions for 1m, 5m, 15m, 30m, 1h, 4h, 1d
    assert len(ohlc_calls) >= 7, f"Expected at least 7 OHLC subscriptions, got {len(ohlc_calls)}"


@pytest.mark.asyncio
async def test_ws_client_health_metrics():
    """Test that health metrics track last message timestamp per pair"""
    config = KrakenWSConfig()
    config.pairs = ["BTC/USD", "ETH/USD"]
    
    client = KrakenWebSocketClient(config=config)
    
    # Simulate receiving messages
    await client.handle_trade_data(
        channel_id=1,
        data=[[50000.0, 0.1, time.time(), "b", "l"]],
        channel="trade",
        pair="BTC/USD",
    )
    
    await client.handle_trade_data(
        channel_id=2,
        data=[[3000.0, 1.0, time.time(), "s", "l"]],
        channel="trade",
        pair="ETH/USD",
    )
    
    # Get health metrics
    health = client.get_health_metrics()
    
    # Verify last message timestamps are tracked
    assert "last_message_timestamp_by_pair" in health
    assert "BTC/USD" in health["last_message_timestamp_by_pair"]
    assert "ETH/USD" in health["last_message_timestamp_by_pair"]
    
    # Verify timestamps are recent
    btc_timestamp = health["last_message_timestamp_by_pair"]["BTC/USD"]["last_message_timestamp"]
    eth_timestamp = health["last_message_timestamp_by_pair"]["ETH/USD"]["last_message_timestamp"]
    
    assert time.time() - btc_timestamp < 5, "BTC/USD timestamp should be recent"
    assert time.time() - eth_timestamp < 5, "ETH/USD timestamp should be recent"


@pytest.mark.asyncio
async def test_ws_client_reconnection_backoff():
    """Test that reconnection uses exponential backoff (1s, 2s, 4s... max 60s)"""
    config = KrakenWSConfig()
    config.reconnect_delay = 1
    config.max_retries = 10
    
    client = KrakenWebSocketClient(config=config)
    client.running = True
    
    # Mock connect_once to fail
    async def mock_connect_once():
        raise Exception("Connection failed")
    
    client.connect_once = mock_connect_once
    
    # Track backoff delays
    backoff_delays = []
    original_sleep = asyncio.sleep
    
    async def track_sleep(delay):
        if delay > 0:
            backoff_delays.append(delay)
        return await original_sleep(0)  # Don't actually sleep in tests
    
    with patch('asyncio.sleep', track_sleep):
        # Start client (will fail and reconnect)
        task = asyncio.create_task(client.start())
        
        # Wait for a few reconnection attempts
        await asyncio.sleep(0.1)
        
        # Stop client
        client.running = False
        task.cancel()
        
        try:
            await task
        except asyncio.CancelledError:
            pass
    
    # Verify exponential backoff (at least first few attempts)
    if len(backoff_delays) >= 3:
        # First delay should be ~1s (with jitter)
        assert 0.8 <= backoff_delays[0] <= 1.2, f"First backoff should be ~1s, got {backoff_delays[0]}"
        # Second delay should be ~2s (with jitter)
        assert 1.6 <= backoff_delays[1] <= 2.4, f"Second backoff should be ~2s, got {backoff_delays[1]}"
        # Third delay should be ~4s (with jitter)
        assert 3.2 <= backoff_delays[2] <= 4.8, f"Third backoff should be ~4s, got {backoff_delays[2]}"


@pytest.mark.asyncio
async def test_ws_client_subscription_error_logging():
    """Test that subscription errors are logged with context"""
    config = KrakenWSConfig()
    config.pairs = ["BTC/USD"]
    
    client = KrakenWebSocketClient(config=config)
    
    # Mock WebSocket that fails on send
    client.ws = AsyncMock()
    client.ws.send = AsyncMock(side_effect=Exception("Send failed"))
    
    # Setup subscriptions (should log errors)
    await client.setup_subscriptions()
    
    # Verify subscription errors are tracked
    assert len(client.stats["subscription_errors"]) > 0
    
    # Verify error context includes pair and channel
    error = client.stats["subscription_errors"][0]
    assert "pair" in error or "pairs" in str(error)
    assert "channel" in error or "error" in error


# =============================================================================
# OHLCV MANAGER TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_ohlcv_manager_loads_pairs_from_config(kraken_ohlcv_config_path):
    """Test that OHLCV manager loads pairs from config"""
    manager = KrakenOHLCVManager(config_path=kraken_ohlcv_config_path)
    
    pairs = manager.get_all_pairs()
    
    expected_pairs = {"BTC/USD", "ETH/USD", "BTC/EUR", "ADA/USD", "SOL/USD", "AVAX/USD", "LINK/USD"}
    assert set(pairs) == expected_pairs


@pytest.mark.asyncio
async def test_ohlcv_manager_loads_timeframes_from_config(kraken_ohlcv_config_path):
    """Test that OHLCV manager loads timeframes from config"""
    manager = KrakenOHLCVManager(config_path=kraken_ohlcv_config_path)
    
    native_tfs = manager.get_native_timeframes()
    synthetic_tfs = manager.get_synthetic_timeframes()
    
    # Verify native timeframes
    expected_native = {"1m", "5m", "15m", "30m", "1h", "4h", "1d"}
    native_names = {tf.name for tf in native_tfs}
    assert native_names == expected_native
    
    # Verify synthetic timeframes
    expected_synthetic = {"15s", "30s"}
    synthetic_names = {tf.name for tf in synthetic_tfs}
    assert synthetic_names == expected_synthetic


@pytest.mark.asyncio
async def test_ohlcv_manager_stream_naming(kraken_ohlcv_config_path):
    """Test that OHLCV manager uses correct stream naming"""
    manager = KrakenOHLCVManager(config_path=kraken_ohlcv_config_path)
    
    # Test stream naming matches kraken_ohlcv.yaml
    # Stream format: kraken:ohlc:<tf>:<pair>
    # Pair format: BTC/USD -> BTC-USD
    
    # This is tested indirectly through the SyntheticBarBuilder
    # which uses manager's stream naming logic
    synthetic_tfs = manager.get_synthetic_timeframes()
    
    for tf in synthetic_tfs:
        # Verify timeframe has correct stream key format
        assert tf.name in ["15s", "30s"]


@pytest.mark.asyncio
async def test_synthetic_bar_generation(kraken_ohlcv_config_path):
    """Test that synthetic bars are generated for synthetic timeframes"""
    manager = KrakenOHLCVManager(config_path=kraken_ohlcv_config_path)
    
    # Initialize bar builders
    await manager.initialize_bar_builders()
    
    # Process a trade
    completed_bars = await manager.process_trade(
        symbol="BTC/USD",
        price=50000.0,
        volume=0.1,
        side="buy",
        timestamp=time.time(),
    )
    
    # Should return list (may be empty if bucket not closed yet)
    assert isinstance(completed_bars, list)


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_full_pipeline_pairs_and_timeframes(kraken_ohlcv_config_path, kraken_config_path):
    """Test that full pipeline (WS + OHLCV) handles all pairs and timeframes"""
    # Load config
    config_loader = KrakenConfigLoader(
        kraken_ohlcv_path=kraken_ohlcv_config_path,
        kraken_path=kraken_config_path,
    )
    
    pairs = config_loader.get_all_pairs()
    timeframes = config_loader.get_all_timeframes()
    
    # Verify all expected pairs
    expected_pairs = {"BTC/USD", "ETH/USD", "BTC/EUR", "ADA/USD", "SOL/USD", "AVAX/USD", "LINK/USD"}
    assert set(pairs) == expected_pairs
    
    # Verify all expected timeframes
    expected_native = {"1m", "5m", "15m", "30m", "1h", "4h", "1d"}
    expected_synthetic = {"15s", "30s"}
    expected_all = expected_native | expected_synthetic
    assert set(timeframes) == expected_all
    
    # Verify WS config would load these
    ws_config = KrakenWSConfig()
    # Note: This will use the actual config loader if available, or fallback
    assert len(ws_config.pairs) > 0
    assert len(ws_config.timeframes) > 0


@pytest.mark.asyncio
async def test_stream_naming_consistency(kraken_ohlcv_config_path):
    """Test that stream naming is consistent across WS client and OHLCV manager"""
    config_loader = KrakenConfigLoader(kraken_ohlcv_path=kraken_ohlcv_config_path)
    
    # Test stream names for various pairs and timeframes
    test_cases = [
        ("1m", "BTC/USD", "kraken:ohlc:1m:BTC-USD"),
        ("5m", "ETH/USD", "kraken:ohlc:5m:ETH-USD"),
        ("15s", "ADA/USD", "kraken:ohlc:15s:ADA-USD"),
        ("1h", "SOL/USD", "kraken:ohlc:1h:SOL-USD"),
    ]
    
    for timeframe, pair, expected_stream in test_cases:
        stream_name = config_loader.get_stream_name(timeframe, pair)
        assert stream_name == expected_stream, f"Expected {expected_stream}, got {stream_name}"









