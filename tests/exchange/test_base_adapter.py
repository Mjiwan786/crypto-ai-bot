"""
Tests for base_adapter.py — abstract interface, dataclasses, enums,
and verification that CcxtAdapter implements all abstract methods.
"""

from __future__ import annotations

import inspect
import pytest
from datetime import datetime, timezone

from exchange.base_adapter import (
    Balance,
    BaseExchangeAdapter,
    ExchangeLimits,
    OHLCV,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
    Ticker,
)
from exchange.ccxt_adapter import CcxtAdapter
from exchange.exchange_factory import ExchangeFactory
from exchange.exchange_registry import ExchangeRegistry


# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------

class TestOrderEnums:
    """Verify enum members and string coercion."""

    def test_order_side_values(self) -> None:
        assert OrderSide.BUY.value == "buy"
        assert OrderSide.SELL.value == "sell"

    def test_order_type_values(self) -> None:
        assert OrderType.MARKET.value == "market"
        assert OrderType.LIMIT.value == "limit"
        assert OrderType.STOP_LOSS.value == "stop_loss"
        assert OrderType.TAKE_PROFIT.value == "take_profit"

    def test_order_status_values(self) -> None:
        assert OrderStatus.OPEN.value == "open"
        assert OrderStatus.CLOSED.value == "closed"
        assert OrderStatus.CANCELED.value == "canceled"
        assert OrderStatus.EXPIRED.value == "expired"
        assert OrderStatus.REJECTED.value == "rejected"
        assert OrderStatus.PENDING.value == "pending"

    def test_order_side_is_str(self) -> None:
        """OrderSide is a str enum — usable as a plain string."""
        assert isinstance(OrderSide.BUY, str)

    def test_order_type_is_str(self) -> None:
        assert isinstance(OrderType.MARKET, str)


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------

class TestDataclasses:
    """Verify dataclass construction and immutability."""

    def test_ticker_creation(self) -> None:
        ts = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
        t = Ticker(
            symbol="BTC/USD",
            bid=95000.0,
            ask=95001.0,
            last=95000.5,
            volume_24h=1234.5,
            timestamp=ts,
        )
        assert t.symbol == "BTC/USD"
        assert t.bid == 95000.0
        assert t.ask == 95001.0
        assert t.last == 95000.5
        assert t.volume_24h == 1234.5
        assert t.timestamp == ts
        assert t.raw == {}

    def test_ticker_is_frozen(self) -> None:
        t = Ticker(
            symbol="ETH/USD",
            bid=3000.0,
            ask=3001.0,
            last=3000.5,
            volume_24h=100.0,
            timestamp=datetime.now(timezone.utc),
        )
        with pytest.raises(AttributeError):
            t.bid = 9999.0  # type: ignore[misc]

    def test_ohlcv_creation(self) -> None:
        candle = OHLCV(
            timestamp=datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc),
            open=95000.0,
            high=95500.0,
            low=94900.0,
            close=95200.0,
            volume=500.0,
        )
        assert candle.open == 95000.0
        assert candle.close == 95200.0

    def test_order_result_defaults(self) -> None:
        order = OrderResult(
            order_id="abc123",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            status=OrderStatus.CLOSED,
            price=95000.0,
            amount=0.01,
            filled=0.01,
            remaining=0.0,
            cost=950.0,
        )
        assert order.fee == 0.0
        assert order.fee_currency == ""
        assert order.timestamp is None
        assert order.raw == {}

    def test_balance_creation(self) -> None:
        b = Balance(currency="USD", free=1000.0, used=200.0, total=1200.0)
        assert b.currency == "USD"
        assert b.free == 1000.0
        assert b.total == 1200.0

    def test_exchange_limits_creation(self) -> None:
        lim = ExchangeLimits(
            min_order_amount=0.0001,
            max_order_amount=100.0,
            min_order_cost=10.0,
            price_precision=2,
            amount_precision=8,
            maker_fee=0.0016,
            taker_fee=0.0026,
        )
        assert lim.min_order_amount == 0.0001
        assert lim.maker_fee == 0.0016


# ---------------------------------------------------------------------------
# Abstract base class contract
# ---------------------------------------------------------------------------

class TestBaseAdapterContract:
    """Verify that CcxtAdapter implements all abstract methods."""

    def test_ccxt_adapter_is_subclass(self) -> None:
        assert issubclass(CcxtAdapter, BaseExchangeAdapter)

    def test_ccxt_adapter_instantiates(self) -> None:
        """CcxtAdapter can be instantiated (no missing abstract methods)."""
        adapter = CcxtAdapter(exchange_id="kraken")
        assert adapter.exchange_id == "kraken"

    def test_all_abstract_methods_implemented(self) -> None:
        """Every abstract method in BaseExchangeAdapter must exist on CcxtAdapter."""
        abstract_methods = set()
        for name, method in inspect.getmembers(BaseExchangeAdapter):
            if getattr(method, "__isabstractmethod__", False):
                abstract_methods.add(name)

        for method_name in abstract_methods:
            assert hasattr(CcxtAdapter, method_name), (
                f"CcxtAdapter is missing abstract method: {method_name}"
            )

    def test_abstract_properties_implemented(self) -> None:
        adapter = CcxtAdapter(exchange_id="kraken")
        assert isinstance(adapter.exchange_id, str)
        assert isinstance(adapter.display_name, str)


# ---------------------------------------------------------------------------
# Factory creates correct types
# ---------------------------------------------------------------------------

class TestFactoryTypes:
    """Verify the factory creates the right adapter types."""

    def test_factory_create_returns_base_adapter(self) -> None:
        adapter = ExchangeFactory.create("kraken")
        assert isinstance(adapter, BaseExchangeAdapter)
        assert isinstance(adapter, CcxtAdapter)

    def test_factory_create_public_returns_base_adapter(self) -> None:
        adapter = ExchangeFactory.create_public("kraken")
        assert isinstance(adapter, BaseExchangeAdapter)

    def test_factory_supported_exchanges(self) -> None:
        supported = ExchangeFactory.supported_exchanges()
        assert "kraken" in supported
        assert "coinbase" in supported
        assert "binance" in supported
        assert "bybit" in supported
        assert isinstance(supported, list)
        assert supported == sorted(supported)  # should be sorted


# ---------------------------------------------------------------------------
# Registry loads YAML configs
# ---------------------------------------------------------------------------

class TestRegistryLoadsConfigs:
    """Verify the registry discovers and parses YAML configs."""

    def test_registry_loads_from_default_dir(self) -> None:
        registry = ExchangeRegistry()
        configs = registry.list_exchanges()
        assert len(configs) >= 2, "Should load at least kraken and coinbase"

    def test_registry_has_kraken(self) -> None:
        registry = ExchangeRegistry()
        assert registry.is_supported("kraken")
        config = registry.get_config("kraken")
        assert config.exchange_id == "kraken"
        assert config.display_name  # non-empty

    def test_registry_has_coinbase(self) -> None:
        registry = ExchangeRegistry()
        assert registry.is_supported("coinbase")
        config = registry.get_config("coinbase")
        assert config.display_name == "Coinbase"

    def test_registry_has_binance(self) -> None:
        registry = ExchangeRegistry()
        assert registry.is_supported("binance")
        config = registry.get_config("binance")
        assert config.display_name == "Binance"

    def test_registry_unsupported_exchange_raises(self) -> None:
        registry = ExchangeRegistry()
        with pytest.raises(KeyError, match="not found"):
            registry.get_config("nonexistent_exchange")

    def test_registry_is_supported_false_for_unknown(self) -> None:
        registry = ExchangeRegistry()
        assert not registry.is_supported("mt_gox")

    def test_registry_coinbase_has_pairs(self) -> None:
        registry = ExchangeRegistry()
        pairs = registry.get_pairs_for_exchange("coinbase")
        assert len(pairs) > 0
        assert "BTC/USD" in pairs

    def test_registry_binance_has_pairs(self) -> None:
        registry = ExchangeRegistry()
        pairs = registry.get_pairs_for_exchange("binance")
        assert len(pairs) > 0
        assert "BTC/USDT" in pairs
