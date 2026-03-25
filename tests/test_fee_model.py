"""Tests for per-exchange fee model."""

import os
import pytest
from signals.fee_model import (
    get_round_trip_fee_bps,
    get_fee_for_venue,
    EXCHANGE_FEES,
    ExchangeFees,
)


def test_all_supported_exchanges_have_fees():
    """Every exchange in the platform should have a fee entry."""
    expected = {"bitfinex", "binance", "okx", "kucoin", "gateio", "bybit", "kraken", "coinbase"}
    assert set(EXCHANGE_FEES.keys()) == expected


def test_bitfinex_zero_fees():
    """Bitfinex should have zero fees."""
    assert get_round_trip_fee_bps("bitfinex") == 0.0


def test_binance_with_token_discount():
    """Binance with BNB discount should be 15 bps round-trip."""
    fee = get_round_trip_fee_bps("binance", use_token_discount=True)
    assert fee == 15.0  # (10 + 10) * 0.75


def test_binance_without_token_discount():
    """Binance without BNB discount should be 20 bps round-trip."""
    fee = get_round_trip_fee_bps("binance", use_token_discount=False)
    assert fee == 20.0  # 10 + 10


def test_kraken_fees():
    """Kraken has highest fees."""
    fee = get_round_trip_fee_bps("kraken")
    assert fee == 65.0  # 25 + 40, no discount


def test_unknown_exchange_uses_default():
    """Unknown exchange should fall back to env var default."""
    fee = get_round_trip_fee_bps("some_unknown_exchange")
    assert fee == float(os.getenv("ROUND_TRIP_FEE_BPS", "20"))


def test_default_venue_reads_env(monkeypatch):
    """Default venue should read ROUND_TRIP_FEE_BPS env var."""
    monkeypatch.setenv("ROUND_TRIP_FEE_BPS", "25")
    assert get_round_trip_fee_bps(None) == 25.0


def test_get_fee_for_venue_reads_execution_venue(monkeypatch):
    """get_fee_for_venue should read EXECUTION_VENUE env var."""
    monkeypatch.setenv("EXECUTION_VENUE", "bitfinex")
    assert get_fee_for_venue() == 0.0


def test_case_insensitive():
    """Exchange lookup should be case-insensitive."""
    assert get_round_trip_fee_bps("Binance") == get_round_trip_fee_bps("binance")
    assert get_round_trip_fee_bps("KRAKEN") == get_round_trip_fee_bps("kraken")


def test_exchange_fees_are_frozen():
    """Fee dataclass should be immutable."""
    fees = EXCHANGE_FEES["binance"]
    with pytest.raises(AttributeError):
        fees.maker_bps = 999
