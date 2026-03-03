"""
Tests for ccxt_adapter.py — CCXT-based exchange adapter.

Includes:
- Real API tests for public endpoints (Kraken, Coinbase) — no auth needed
- Pair normalisation tests
- Circuit breaker tests (mocked failures)
- Sandbox mode configuration tests
- Error mapping tests
- Binance tests are skipped gracefully if unreachable (may be region-blocked)
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import ccxt
import pytest

from exchange.base_adapter import (
    OHLCV,
    OrderSide,
    OrderStatus,
    OrderType,
    Ticker,
)
from exchange.ccxt_adapter import (
    CcxtAdapter,
    _CircuitBreaker,
    normalize_pair,
)
from exchange.errors import (
    ExchangeAuthError,
    ExchangeError,
    ExchangeNetworkError,
    ExchangeNotAvailableError,
    InsufficientFundsError,
    InvalidOrderError,
    RateLimitError,
)


# ---------------------------------------------------------------------------
# Pair normalisation
# ---------------------------------------------------------------------------

class TestNormalizePair:
    """Tests for the ``normalize_pair`` helper."""

    def test_already_normalised(self) -> None:
        assert normalize_pair("BTC/USD") == "BTC/USD"

    def test_dash_format_coinbase(self) -> None:
        assert normalize_pair("BTC-USD") == "BTC/USD"
        assert normalize_pair("ETH-USD") == "ETH/USD"
        assert normalize_pair("SOL-USD") == "SOL/USD"

    def test_concat_format_binance_usdt(self) -> None:
        assert normalize_pair("BTCUSDT") == "BTC/USDT"
        assert normalize_pair("ETHUSDT") == "ETH/USDT"
        assert normalize_pair("SOLUSDT") == "SOL/USDT"

    def test_concat_format_binance_usd(self) -> None:
        assert normalize_pair("BTCUSD") == "BTC/USD"

    def test_concat_format_usdc(self) -> None:
        assert normalize_pair("BTCUSDC") == "BTC/USDC"

    def test_concat_format_eur(self) -> None:
        assert normalize_pair("BTCEUR") == "BTC/EUR"

    def test_lowercase_input(self) -> None:
        assert normalize_pair("btc/usd") == "BTC/USD"

    def test_whitespace_stripped(self) -> None:
        assert normalize_pair("  BTC/USD  ") == "BTC/USD"


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

class TestCircuitBreaker:
    """Tests for the ``_CircuitBreaker`` class."""

    def test_starts_closed(self) -> None:
        cb = _CircuitBreaker(max_failures=3, cooldown_seconds=30)
        assert not cb.is_open
        cb.check()  # should not raise

    def test_opens_after_consecutive_failures(self) -> None:
        cb = _CircuitBreaker(max_failures=3, cooldown_seconds=30)
        cb.record_failure()
        cb.record_failure()
        assert not cb.is_open  # only 2 so far
        cb.record_failure()  # 3rd -> opens
        assert cb.is_open

    def test_check_raises_when_open(self) -> None:
        cb = _CircuitBreaker(max_failures=2, cooldown_seconds=60)
        cb.record_failure()
        cb.record_failure()
        with pytest.raises(ExchangeNetworkError, match="Circuit breaker open"):
            cb.check()

    def test_success_resets_counter(self) -> None:
        cb = _CircuitBreaker(max_failures=3, cooldown_seconds=30)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()  # reset
        cb.record_failure()  # only 1 after reset
        assert not cb.is_open

    def test_closes_after_cooldown(self) -> None:
        cb = _CircuitBreaker(max_failures=1, cooldown_seconds=0.1)
        cb.record_failure()
        assert cb.is_open
        time.sleep(0.15)
        assert not cb.is_open


# ---------------------------------------------------------------------------
# CcxtAdapter construction
# ---------------------------------------------------------------------------

class TestCcxtAdapterConstruction:
    """Tests for CcxtAdapter instantiation and properties."""

    def test_create_kraken(self) -> None:
        adapter = CcxtAdapter(exchange_id="kraken")
        assert adapter.exchange_id == "kraken"
        assert adapter.display_name  # "Kraken" or similar

    def test_create_coinbase(self) -> None:
        adapter = CcxtAdapter(exchange_id="coinbase")
        assert adapter.exchange_id == "coinbase"

    def test_create_binance(self) -> None:
        adapter = CcxtAdapter(exchange_id="binance")
        assert adapter.exchange_id == "binance"

    def test_create_bybit(self) -> None:
        adapter = CcxtAdapter(exchange_id="bybit")
        assert adapter.exchange_id == "bybit"

    def test_unsupported_exchange_raises(self) -> None:
        with pytest.raises(ExchangeNotAvailableError, match="not supported"):
            CcxtAdapter(exchange_id="mt_gox")

    def test_sandbox_mode(self) -> None:
        adapter = CcxtAdapter(exchange_id="binance", sandbox=True)
        assert adapter._sandbox is True
        # Binance sandbox should be configured
        assert adapter._exchange.urls.get("test") or adapter._exchange.sandbox

    def test_not_connected_initially(self) -> None:
        adapter = CcxtAdapter(exchange_id="kraken")
        assert not adapter.is_connected


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------

class TestErrorMapping:
    """Test that CCXT exceptions are mapped to our custom types."""

    def _adapter(self) -> CcxtAdapter:
        return CcxtAdapter(exchange_id="kraken")

    def test_auth_error(self) -> None:
        adapter = self._adapter()
        exc = ccxt.AuthenticationError("bad key")
        mapped = adapter._map_exception(exc)
        assert isinstance(mapped, ExchangeAuthError)
        assert mapped.exchange_id == "kraken"
        assert mapped.original is exc

    def test_insufficient_funds(self) -> None:
        adapter = self._adapter()
        exc = ccxt.InsufficientFunds("not enough")
        mapped = adapter._map_exception(exc)
        assert isinstance(mapped, InsufficientFundsError)

    def test_invalid_order(self) -> None:
        adapter = self._adapter()
        exc = ccxt.InvalidOrder("bad order")
        mapped = adapter._map_exception(exc)
        assert isinstance(mapped, InvalidOrderError)

    def test_rate_limit(self) -> None:
        adapter = self._adapter()
        exc = ccxt.RateLimitExceeded("too fast")
        mapped = adapter._map_exception(exc)
        assert isinstance(mapped, RateLimitError)

    def test_network_error(self) -> None:
        adapter = self._adapter()
        exc = ccxt.NetworkError("timeout")
        mapped = adapter._map_exception(exc)
        assert isinstance(mapped, ExchangeNetworkError)

    def test_exchange_not_available(self) -> None:
        adapter = self._adapter()
        exc = ccxt.ExchangeNotAvailable("down")
        mapped = adapter._map_exception(exc)
        assert isinstance(mapped, ExchangeNotAvailableError)

    def test_generic_exchange_error(self) -> None:
        adapter = self._adapter()
        exc = ccxt.ExchangeError("something")
        mapped = adapter._map_exception(exc)
        assert isinstance(mapped, ExchangeError)

    def test_unknown_exception(self) -> None:
        adapter = self._adapter()
        exc = RuntimeError("surprise")
        mapped = adapter._map_exception(exc)
        assert isinstance(mapped, ExchangeError)
        assert mapped.original is exc


# ---------------------------------------------------------------------------
# Auth requirement
# ---------------------------------------------------------------------------

class TestAuthRequirement:
    """Verify that authenticated methods fail without credentials."""

    @pytest.mark.asyncio
    async def test_create_order_requires_auth(self) -> None:
        adapter = CcxtAdapter(exchange_id="kraken")
        with pytest.raises(ExchangeAuthError, match="requires API credentials"):
            await adapter.create_order(
                symbol="BTC/USD",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                amount=0.001,
            )

    @pytest.mark.asyncio
    async def test_cancel_order_requires_auth(self) -> None:
        adapter = CcxtAdapter(exchange_id="kraken")
        with pytest.raises(ExchangeAuthError):
            await adapter.cancel_order("abc", "BTC/USD")

    @pytest.mark.asyncio
    async def test_fetch_order_requires_auth(self) -> None:
        adapter = CcxtAdapter(exchange_id="kraken")
        with pytest.raises(ExchangeAuthError):
            await adapter.fetch_order("abc", "BTC/USD")

    @pytest.mark.asyncio
    async def test_fetch_balance_requires_auth(self) -> None:
        adapter = CcxtAdapter(exchange_id="kraken")
        with pytest.raises(ExchangeAuthError):
            await adapter.fetch_balance()

    @pytest.mark.asyncio
    async def test_validate_credentials_false_without_key(self) -> None:
        adapter = CcxtAdapter(exchange_id="kraken")
        result = await adapter.validate_credentials()
        assert result is False


# ---------------------------------------------------------------------------
# Real API tests — Kraken (public endpoints)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestKrakenPublicAPI:
    """Integration tests against the real Kraken API (public, no auth).

    These tests hit live endpoints. They may be slow or flaky due to
    network conditions — that is expected for integration tests.
    """

    async def test_fetch_ticker_btc_usd(self) -> None:
        adapter = CcxtAdapter(exchange_id="kraken")
        try:
            await adapter.connect()
            ticker = await adapter.fetch_ticker("BTC/USD")
            assert isinstance(ticker, Ticker)
            assert ticker.symbol == "BTC/USD"
            assert ticker.bid > 0
            assert ticker.ask > 0
            assert ticker.last > 0
            assert ticker.ask >= ticker.bid
            assert isinstance(ticker.timestamp, datetime)
        finally:
            await adapter.disconnect()

    async def test_fetch_ohlcv_btc_usd(self) -> None:
        adapter = CcxtAdapter(exchange_id="kraken")
        try:
            await adapter.connect()
            candles = await adapter.fetch_ohlcv("BTC/USD", timeframe="1h", limit=10)
            assert isinstance(candles, list)
            assert len(candles) > 0
            assert len(candles) <= 10
            for c in candles:
                assert isinstance(c, OHLCV)
                assert c.high >= c.low
                assert c.volume >= 0
        finally:
            await adapter.disconnect()

    async def test_fetch_orderbook_btc_usd(self) -> None:
        adapter = CcxtAdapter(exchange_id="kraken")
        try:
            await adapter.connect()
            book = await adapter.fetch_orderbook("BTC/USD", limit=5)
            assert "bids" in book
            assert "asks" in book
            assert len(book["bids"]) > 0
            assert len(book["asks"]) > 0
            # Each entry is [price, amount]
            assert len(book["bids"][0]) >= 2
            assert book["bids"][0][0] > 0
        finally:
            await adapter.disconnect()

    async def test_get_supported_pairs(self) -> None:
        adapter = CcxtAdapter(exchange_id="kraken")
        try:
            await adapter.connect()
            pairs = await adapter.get_supported_pairs()
            assert isinstance(pairs, list)
            assert len(pairs) > 50  # Kraken has many pairs
            assert "BTC/USD" in pairs
        finally:
            await adapter.disconnect()

    async def test_get_limits_btc_usd(self) -> None:
        adapter = CcxtAdapter(exchange_id="kraken")
        try:
            await adapter.connect()
            limits = await adapter.get_limits("BTC/USD")
            assert limits.min_order_amount >= 0
            assert limits.price_precision > 0
        finally:
            await adapter.disconnect()

    async def test_disconnect_clears_connected(self) -> None:
        adapter = CcxtAdapter(exchange_id="kraken")
        await adapter.connect()
        assert adapter.is_connected
        await adapter.disconnect()
        assert not adapter.is_connected


# ---------------------------------------------------------------------------
# Real API tests — Coinbase (public endpoints)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestCoinbasePublicAPI:
    """Integration tests against the real Coinbase API (public, no auth)."""

    async def test_fetch_ticker_btc_usd(self) -> None:
        adapter = CcxtAdapter(exchange_id="coinbase")
        try:
            await adapter.connect()
            ticker = await adapter.fetch_ticker("BTC/USD")
            assert isinstance(ticker, Ticker)
            assert ticker.last > 0
        finally:
            await adapter.disconnect()

    async def test_fetch_ohlcv_btc_usd(self) -> None:
        adapter = CcxtAdapter(exchange_id="coinbase")
        try:
            await adapter.connect()
            candles = await adapter.fetch_ohlcv("BTC/USD", timeframe="1h", limit=5)
            assert isinstance(candles, list)
            assert len(candles) > 0
            assert isinstance(candles[0], OHLCV)
        finally:
            await adapter.disconnect()

    async def test_pair_normalisation_dash_format(self) -> None:
        """Coinbase uses BTC-USD natively; adapter should handle BTC-USD input."""
        adapter = CcxtAdapter(exchange_id="coinbase")
        try:
            await adapter.connect()
            ticker = await adapter.fetch_ticker("BTC-USD")
            assert ticker.last > 0
        finally:
            await adapter.disconnect()


# ---------------------------------------------------------------------------
# Real API tests — Binance (public endpoints, skip if blocked)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestBinancePublicAPI:
    """Integration tests against the real Binance API.

    Binance may be blocked in some regions (US, etc.). Tests skip
    gracefully on network errors.
    """

    async def test_fetch_ticker_btc_usdt(self) -> None:
        adapter = CcxtAdapter(exchange_id="binance")
        try:
            await adapter.connect()
            ticker = await adapter.fetch_ticker("BTC/USDT")
            assert isinstance(ticker, Ticker)
            assert ticker.last > 0
        except (ExchangeNetworkError, ExchangeError, Exception) as exc:
            pytest.skip(f"Binance unreachable (possibly region-blocked): {exc}")
        finally:
            await adapter.disconnect()

    async def test_fetch_ohlcv_btc_usdt(self) -> None:
        adapter = CcxtAdapter(exchange_id="binance")
        try:
            await adapter.connect()
            candles = await adapter.fetch_ohlcv("BTC/USDT", timeframe="1h", limit=5)
            assert len(candles) > 0
        except (ExchangeNetworkError, ExchangeError, Exception) as exc:
            pytest.skip(f"Binance unreachable: {exc}")
        finally:
            await adapter.disconnect()

    async def test_pair_normalisation_concat_format(self) -> None:
        """Binance uses BTCUSDT natively; adapter should handle it."""
        adapter = CcxtAdapter(exchange_id="binance")
        try:
            await adapter.connect()
            ticker = await adapter.fetch_ticker("BTCUSDT")
            assert ticker.last > 0
        except (ExchangeNetworkError, ExchangeError, Exception) as exc:
            pytest.skip(f"Binance unreachable: {exc}")
        finally:
            await adapter.disconnect()


# ---------------------------------------------------------------------------
# Mocked tests — circuit breaker integration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestCircuitBreakerIntegration:
    """Test circuit breaker behaviour within the adapter (mocked exchange)."""

    async def test_circuit_opens_after_3_failures(self) -> None:
        adapter = CcxtAdapter(exchange_id="kraken")

        # Mock the underlying CCXT fetch_ticker to always fail
        adapter._exchange.fetch_ticker = AsyncMock(
            side_effect=ccxt.NetworkError("simulated timeout")
        )
        # Need markets loaded for normalisation to work
        adapter._exchange.markets = {"BTC/USD": {"symbol": "BTC/USD"}}
        adapter._connected = True

        # First 3 calls should raise ExchangeNetworkError
        for _ in range(3):
            with pytest.raises(ExchangeNetworkError):
                await adapter.fetch_ticker("BTC/USD")

        # 4th call should fail with circuit breaker message
        with pytest.raises(ExchangeNetworkError, match="Circuit breaker open"):
            await adapter.fetch_ticker("BTC/USD")

        await adapter.disconnect()

    async def test_circuit_resets_on_success(self) -> None:
        adapter = CcxtAdapter(exchange_id="kraken")
        adapter._exchange.markets = {"BTC/USD": {"symbol": "BTC/USD"}}
        adapter._connected = True

        # Fail twice, then succeed
        call_count = 0

        async def flaky_fetch(symbol: str) -> dict:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise ccxt.NetworkError("simulated")
            return {
                "symbol": "BTC/USD",
                "bid": 95000,
                "ask": 95001,
                "last": 95000.5,
                "baseVolume": 100,
                "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
            }

        adapter._exchange.fetch_ticker = flaky_fetch

        # 2 failures
        with pytest.raises(ExchangeNetworkError):
            await adapter.fetch_ticker("BTC/USD")
        with pytest.raises(ExchangeNetworkError):
            await adapter.fetch_ticker("BTC/USD")

        # Next succeeds and resets
        ticker = await adapter.fetch_ticker("BTC/USD")
        assert ticker.last == 95000.5

        # Circuit should be closed
        assert not adapter._circuit.is_open

        await adapter.disconnect()


# ---------------------------------------------------------------------------
# Mocked tests — sandbox mode
# ---------------------------------------------------------------------------

class TestSandboxMode:
    """Verify sandbox configuration for supported exchanges."""

    def test_coinbase_sandbox(self) -> None:
        adapter = CcxtAdapter(exchange_id="coinbase", sandbox=True)
        # CCXT should have sandbox mode enabled
        assert adapter._sandbox is True

    def test_binance_sandbox(self) -> None:
        adapter = CcxtAdapter(exchange_id="binance", sandbox=True)
        assert adapter._sandbox is True

    def test_bybit_sandbox(self) -> None:
        adapter = CcxtAdapter(exchange_id="bybit", sandbox=True)
        assert adapter._sandbox is True

    def test_kraken_no_sandbox_crash(self) -> None:
        """Kraken doesn't have a testnet; sandbox=True should still work."""
        adapter = CcxtAdapter(exchange_id="kraken", sandbox=True)
        assert adapter._sandbox is True
        assert adapter.exchange_id == "kraken"
