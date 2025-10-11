"""
WebSocket message parsing tests with Kraken fixtures.

Validates:
- Ticker message parsing
- Trade message parsing
- Orderbook snapshot parsing
- Orderbook update parsing
- Error message handling

All tests are hermetic - use fixtures only, no live connections.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest


# ======================== Mock Parser (Simplified) ========================


def parse_kraken_ticker(message: dict) -> dict:
    """Parse Kraken ticker message"""
    if message.get("type") != "update":
        return {}

    data = message.get("data", [])
    if not data:
        return {}

    ticker = data[0]
    return {
        "symbol": ticker.get("symbol"),
        "bid": float(ticker.get("bid", 0)),
        "ask": float(ticker.get("ask", 0)),
        "last": float(ticker.get("last", 0)),
        "volume": float(ticker.get("volume", 0)),
        "vwap": float(ticker.get("vwap", 0)),
        "spread_bps": _calculate_spread_bps(ticker.get("bid"), ticker.get("ask")),
    }


def parse_kraken_trades(message: dict) -> list:
    """Parse Kraken trade messages"""
    if message.get("type") != "update":
        return []

    data = message.get("data", [])
    trades = []

    for trade in data:
        trades.append(
            {
                "symbol": trade.get("symbol"),
                "side": trade.get("side"),
                "price": float(trade.get("price", 0)),
                "qty": float(trade.get("qty", 0)),
                "timestamp": trade.get("timestamp"),
                "trade_id": trade.get("trade_id"),
            }
        )

    return trades


def parse_kraken_orderbook(message: dict) -> dict:
    """Parse Kraken orderbook snapshot"""
    msg_type = message.get("type")
    if msg_type not in ("snapshot", "update"):
        return {}

    data = message.get("data", [])
    if not data:
        return {}

    book = data[0]
    return {
        "symbol": book.get("symbol"),
        "bids": [(float(b["price"]), float(b["qty"])) for b in book.get("bids", [])],
        "asks": [(float(a["price"]), float(a["qty"])) for a in book.get("asks", [])],
        "timestamp": book.get("timestamp"),
        "is_snapshot": msg_type == "snapshot",
    }


def _calculate_spread_bps(bid, ask):
    """Calculate spread in basis points"""
    if not bid or not ask:
        return 0.0
    bid = float(bid)
    ask = float(ask)
    if bid <= 0:
        return 0.0
    return (ask - bid) / bid * 10000


# ======================== Ticker Tests ========================


def test_parse_ticker_message(kraken_ws_ticker_message):
    """Test parsing Kraken ticker message"""
    result = parse_kraken_ticker(kraken_ws_ticker_message)

    assert result["symbol"] == "BTC/USD"
    assert result["bid"] == 49950.0
    assert result["ask"] == 50050.0
    assert result["last"] == 50000.0
    assert result["volume"] == 123.456
    assert result["vwap"] == 49980.0

    # Spread calculation
    expected_spread = (50050.0 - 49950.0) / 49950.0 * 10000
    assert abs(result["spread_bps"] - expected_spread) < 0.01


def test_parse_ticker_handles_missing_fields():
    """Test ticker parser handles missing fields gracefully"""
    message = {
        "channel": "ticker",
        "type": "update",
        "data": [{"symbol": "BTC/USD", "bid": 50000.0}],  # Missing most fields
    }

    result = parse_kraken_ticker(message)

    assert result["symbol"] == "BTC/USD"
    assert result["bid"] == 50000.0
    assert result["ask"] == 0.0  # Default


def test_parse_ticker_empty_message():
    """Test ticker parser handles empty message"""
    message = {"channel": "ticker", "type": "update", "data": []}

    result = parse_kraken_ticker(message)

    assert result == {}


# ======================== Trade Tests ========================


def test_parse_trade_messages(kraken_ws_trade_message):
    """Test parsing Kraken trade messages"""
    trades = parse_kraken_trades(kraken_ws_trade_message)

    assert len(trades) == 2

    # First trade (buy)
    assert trades[0]["symbol"] == "BTC/USD"
    assert trades[0]["side"] == "buy"
    assert trades[0]["price"] == 50000.0
    assert trades[0]["qty"] == 0.5
    assert trades[0]["trade_id"] == 123456789

    # Second trade (sell)
    assert trades[1]["symbol"] == "BTC/USD"
    assert trades[1]["side"] == "sell"
    assert trades[1]["price"] == 50010.0
    assert trades[1]["qty"] == 0.3
    assert trades[1]["trade_id"] == 123456790


def test_parse_trades_empty_data():
    """Test trade parser handles empty data"""
    message = {"channel": "trade", "type": "update", "data": []}

    trades = parse_kraken_trades(message)

    assert trades == []


def test_parse_trades_filters_side():
    """Test filtering trades by side"""
    message = {
        "channel": "trade",
        "type": "update",
        "data": [
            {"symbol": "BTC/USD", "side": "buy", "price": 50000, "qty": 0.1},
            {"symbol": "BTC/USD", "side": "sell", "price": 50010, "qty": 0.2},
            {"symbol": "BTC/USD", "side": "buy", "price": 50005, "qty": 0.15},
        ],
    }

    trades = parse_kraken_trades(message)
    buy_trades = [t for t in trades if t["side"] == "buy"]
    sell_trades = [t for t in trades if t["side"] == "sell"]

    assert len(buy_trades) == 2
    assert len(sell_trades) == 1


# ======================== Orderbook Tests ========================


def test_parse_orderbook_snapshot(kraken_ws_orderbook_message):
    """Test parsing Kraken orderbook snapshot"""
    book = parse_kraken_orderbook(kraken_ws_orderbook_message)

    assert book["symbol"] == "BTC/USD"
    assert book["is_snapshot"] is True
    assert len(book["bids"]) == 5
    assert len(book["asks"]) == 5

    # Check bid/ask structure
    assert book["bids"][0] == (49990.0, 1.0)
    assert book["asks"][0] == (50010.0, 1.0)

    # Check bid descending order (highest first)
    bid_prices = [price for price, _ in book["bids"]]
    assert bid_prices == sorted(bid_prices, reverse=True)

    # Check ask ascending order (lowest first)
    ask_prices = [price for price, _ in book["asks"]]
    assert ask_prices == sorted(ask_prices)


def test_parse_orderbook_update(kraken_ws_orderbook_update):
    """Test parsing Kraken orderbook update"""
    book = parse_kraken_orderbook(kraken_ws_orderbook_update)

    assert book["symbol"] == "BTC/USD"
    assert book["is_snapshot"] is False
    assert len(book["bids"]) == 2  # New bid + removal
    assert len(book["asks"]) == 2  # New ask + removal

    # Check update structure
    assert (49995.0, 0.5) in book["bids"]  # New bid
    assert (49980.0, 0.0) in book["bids"]  # Removed bid (qty=0)


def test_orderbook_spread_calculation(kraken_ws_orderbook_message):
    """Test spread calculation from orderbook"""
    book = parse_kraken_orderbook(kraken_ws_orderbook_message)

    best_bid = book["bids"][0][0]
    best_ask = book["asks"][0][0]

    spread_bps = _calculate_spread_bps(best_bid, best_ask)

    expected = (50010.0 - 49990.0) / 49990.0 * 10000
    assert abs(spread_bps - expected) < 0.01


def test_orderbook_handles_empty_sides():
    """Test orderbook parser handles empty bid/ask sides"""
    message = {
        "channel": "book",
        "type": "snapshot",
        "data": [{"symbol": "BTC/USD", "bids": [], "asks": []}],
    }

    book = parse_kraken_orderbook(message)

    assert book["symbol"] == "BTC/USD"
    assert book["bids"] == []
    assert book["asks"] == []


# ======================== Error Handling Tests ========================


def test_parse_error_message(kraken_ws_error_message):
    """Test parsing Kraken error message"""
    # Parsers should handle errors gracefully
    ticker = parse_kraken_ticker(kraken_ws_error_message)
    trades = parse_kraken_trades(kraken_ws_error_message)
    book = parse_kraken_orderbook(kraken_ws_error_message)

    # All parsers should return empty/default values for error messages
    assert ticker == {}
    assert trades == []
    assert book == {}


def test_parse_malformed_json():
    """Test parsers handle malformed data"""
    malformed = {"channel": "ticker", "type": "update"}  # Missing 'data' field

    result = parse_kraken_ticker(malformed)
    assert result == {}


# ======================== Integration Tests ========================


@pytest.mark.parametrize(
    "message_type,fixture_name",
    [
        ("ticker", "kraken_ws_ticker_message"),
        ("trade", "kraken_ws_trade_message"),
        ("orderbook", "kraken_ws_orderbook_message"),
    ],
)
def test_parse_all_message_types(message_type, fixture_name, request):
    """Test parsing all Kraken message types"""
    message = request.getfixturevalue(fixture_name)

    # Verify message has required fields
    assert "channel" in message or "type" in message
    assert "data" in message or "error" in message

    # Parse based on type
    if message_type == "ticker":
        result = parse_kraken_ticker(message)
        if message.get("type") == "update":
            assert "symbol" in result
    elif message_type == "trade":
        result = parse_kraken_trades(message)
        if message.get("type") == "update":
            assert len(result) > 0
    elif message_type == "orderbook":
        result = parse_kraken_orderbook(message)
        if message.get("type") in ("snapshot", "update"):
            assert "symbol" in result


def test_orderbook_merge_snapshot_and_update(
    kraken_ws_orderbook_message, kraken_ws_orderbook_update
):
    """Test merging orderbook snapshot with updates"""
    # Parse initial snapshot
    snapshot = parse_kraken_orderbook(kraken_ws_orderbook_message)
    initial_bids = dict(snapshot["bids"])
    initial_asks = dict(snapshot["asks"])

    # Parse update
    update = parse_kraken_orderbook(kraken_ws_orderbook_update)

    # Merge update into snapshot (simplified merge logic)
    for price, qty in update["bids"]:
        if qty == 0.0:
            initial_bids.pop(price, None)  # Remove
        else:
            initial_bids[price] = qty  # Add/update

    for price, qty in update["asks"]:
        if qty == 0.0:
            initial_asks.pop(price, None)  # Remove
        else:
            initial_asks[price] = qty  # Add/update

    # Verify merge worked
    assert 49995.0 in initial_bids  # New bid added
    assert 49980.0 not in initial_bids  # Bid removed
    assert 50015.0 in initial_asks  # New ask added
    assert 50030.0 not in initial_asks  # Ask removed


# ======================== Performance Tests ========================


def test_parse_large_orderbook():
    """Test parsing large orderbook (100 levels)"""
    import time

    # Generate large orderbook
    bids = [{"price": 50000.0 - i, "qty": 1.0} for i in range(100)]
    asks = [{"price": 50000.0 + i, "qty": 1.0} for i in range(100)]

    message = {
        "channel": "book",
        "type": "snapshot",
        "data": [{"symbol": "BTC/USD", "bids": bids, "asks": asks}],
    }

    start = time.time()
    book = parse_kraken_orderbook(message)
    elapsed = time.time() - start

    assert len(book["bids"]) == 100
    assert len(book["asks"]) == 100
    assert elapsed < 0.01, f"Parsing took too long: {elapsed:.4f}s"


def test_parse_trade_batch():
    """Test parsing batch of trades"""
    import time

    # Generate 100 trades
    trades_data = [
        {
            "symbol": "BTC/USD",
            "side": "buy" if i % 2 == 0 else "sell",
            "price": 50000.0 + i * 0.1,
            "qty": 0.1,
            "trade_id": i,
        }
        for i in range(100)
    ]

    message = {"channel": "trade", "type": "update", "data": trades_data}

    start = time.time()
    trades = parse_kraken_trades(message)
    elapsed = time.time() - start

    assert len(trades) == 100
    assert elapsed < 0.01, f"Parsing took too long: {elapsed:.4f}s"
