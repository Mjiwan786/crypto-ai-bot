"""
Tests for exchange_factory.py — factory pattern for creating adapters.
"""

from __future__ import annotations

import pytest

from exchange.base_adapter import BaseExchangeAdapter
from exchange.ccxt_adapter import CcxtAdapter
from exchange.errors import ExchangeNotAvailableError
from exchange.exchange_factory import ExchangeFactory


class TestExchangeFactoryCreate:
    """Test the ``ExchangeFactory.create`` method."""

    def test_create_kraken(self) -> None:
        adapter = ExchangeFactory.create("kraken")
        assert isinstance(adapter, BaseExchangeAdapter)
        assert isinstance(adapter, CcxtAdapter)
        assert adapter.exchange_id == "kraken"

    def test_create_coinbase(self) -> None:
        adapter = ExchangeFactory.create("coinbase")
        assert adapter.exchange_id == "coinbase"

    def test_create_binance(self) -> None:
        adapter = ExchangeFactory.create("binance")
        assert adapter.exchange_id == "binance"

    def test_create_bybit(self) -> None:
        adapter = ExchangeFactory.create("bybit")
        assert adapter.exchange_id == "bybit"

    def test_create_okx(self) -> None:
        adapter = ExchangeFactory.create("okx")
        assert adapter.exchange_id == "okx"

    def test_create_kucoin(self) -> None:
        adapter = ExchangeFactory.create("kucoin")
        assert adapter.exchange_id == "kucoin"

    def test_create_gateio(self) -> None:
        adapter = ExchangeFactory.create("gateio")
        assert adapter.exchange_id == "gateio"

    def test_create_bitfinex(self) -> None:
        adapter = ExchangeFactory.create("bitfinex")
        assert adapter.exchange_id == "bitfinex"

    def test_create_with_credentials(self) -> None:
        adapter = ExchangeFactory.create(
            "kraken",
            api_key="test_key",
            secret="test_secret",
        )
        assert isinstance(adapter, CcxtAdapter)
        assert adapter._api_key == "test_key"

    def test_create_with_passphrase(self) -> None:
        adapter = ExchangeFactory.create(
            "coinbase",
            api_key="key",
            secret="sec",
            passphrase="pass",
        )
        assert adapter._passphrase == "pass"

    def test_create_sandbox_default_true(self) -> None:
        adapter = ExchangeFactory.create("binance")
        assert adapter._sandbox is True  # default sandbox=True

    def test_create_sandbox_explicit_false(self) -> None:
        adapter = ExchangeFactory.create("binance", sandbox=False)
        assert adapter._sandbox is False

    def test_create_case_insensitive(self) -> None:
        adapter = ExchangeFactory.create("KRAKEN")
        assert adapter.exchange_id == "kraken"

    def test_create_unsupported_raises(self) -> None:
        with pytest.raises(ExchangeNotAvailableError, match="not supported"):
            ExchangeFactory.create("mt_gox")

    def test_create_empty_string_raises(self) -> None:
        with pytest.raises(ExchangeNotAvailableError):
            ExchangeFactory.create("")


class TestExchangeFactoryCreatePublic:
    """Test the ``ExchangeFactory.create_public`` method."""

    def test_create_public_kraken(self) -> None:
        adapter = ExchangeFactory.create_public("kraken")
        assert isinstance(adapter, BaseExchangeAdapter)
        assert adapter.exchange_id == "kraken"
        # Public adapters should not have credentials
        assert adapter._api_key == ""
        assert adapter._secret == ""

    def test_create_public_coinbase(self) -> None:
        adapter = ExchangeFactory.create_public("coinbase")
        assert adapter._api_key == ""

    def test_create_public_binance(self) -> None:
        adapter = ExchangeFactory.create_public("binance")
        assert adapter._api_key == ""

    def test_create_public_bybit(self) -> None:
        adapter = ExchangeFactory.create_public("bybit")
        assert adapter._api_key == ""

    def test_create_public_okx(self) -> None:
        adapter = ExchangeFactory.create_public("okx")
        assert adapter._api_key == ""

    def test_create_public_kucoin(self) -> None:
        adapter = ExchangeFactory.create_public("kucoin")
        assert adapter._api_key == ""

    def test_create_public_gateio(self) -> None:
        adapter = ExchangeFactory.create_public("gateio")
        assert adapter._api_key == ""

    def test_create_public_bitfinex(self) -> None:
        adapter = ExchangeFactory.create_public("bitfinex")
        assert adapter._api_key == ""

    def test_create_public_sandbox_disabled(self) -> None:
        """Public adapters don't need sandbox — sandbox is False."""
        adapter = ExchangeFactory.create_public("binance")
        assert adapter._sandbox is False

    def test_create_public_unsupported_raises(self) -> None:
        with pytest.raises(ExchangeNotAvailableError, match="not supported"):
            ExchangeFactory.create_public("bitconnect")

    def test_create_public_case_insensitive(self) -> None:
        adapter = ExchangeFactory.create_public("Coinbase")
        assert adapter.exchange_id == "coinbase"


class TestExchangeFactorySupportedExchanges:
    """Test the ``ExchangeFactory.supported_exchanges`` method."""

    def test_returns_list(self) -> None:
        result = ExchangeFactory.supported_exchanges()
        assert isinstance(result, list)

    def test_contains_all_eight(self) -> None:
        result = ExchangeFactory.supported_exchanges()
        for exchange_id in [
            "kraken", "coinbase", "binance", "bybit",
            "okx", "kucoin", "gateio", "bitfinex",
        ]:
            assert exchange_id in result, f"{exchange_id} missing from supported exchanges"

    def test_sorted(self) -> None:
        result = ExchangeFactory.supported_exchanges()
        assert result == sorted(result)

    def test_length(self) -> None:
        result = ExchangeFactory.supported_exchanges()
        assert len(result) == 8

    def test_all_lowercase(self) -> None:
        for name in ExchangeFactory.supported_exchanges():
            assert name == name.lower()
