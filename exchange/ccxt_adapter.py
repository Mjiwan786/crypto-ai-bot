"""
CCXT-based implementation of BaseExchangeAdapter.

Supports: kraken, coinbase, binance, bybit
Uses ``ccxt.async_support`` for non-blocking I/O.
Includes automatic rate limiting, pair normalisation, circuit breaker,
sandbox support, and graceful error mapping.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

import ccxt.async_support as ccxt_async

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
from exchange.errors import (
    ExchangeAuthError,
    ExchangeError,
    ExchangeNetworkError,
    ExchangeNotAvailableError,
    InsufficientFundsError,
    InvalidOrderError,
    RateLimitError,
)

logger = logging.getLogger(__name__)

# Exchanges for which CCXT has a class
_SUPPORTED_EXCHANGES: set[str] = {"kraken", "coinbase", "binance", "bybit"}

# Sandbox / testnet overrides.
# Only exchanges that have a CCXT sandbox URL are listed here.
# Kraken and Coinbase do NOT have testnet URLs in CCXT.
_SANDBOX_OVERRIDES: dict[str, dict[str, Any]] = {
    "binance": {"sandbox": True},
    "bybit": {"sandbox": True},
}

# ---------------------------------------------------------------------------
# Pair normalisation helpers
# ---------------------------------------------------------------------------

# Pattern: BTC-USD  ->  BTC/USD
_DASH_PAIR_RE = re.compile(r"^([A-Z0-9]+)-([A-Z0-9]+)$")
# Pattern: BTCUSDT  ->  BTC/USDT  (known quote suffixes)
_CONCAT_QUOTES = ("USDT", "USDC", "BUSD", "USD", "EUR", "GBP", "BTC", "ETH")


def normalize_pair(pair: str) -> str:
    """Convert exchange-native pair formats to CCXT standard ``BASE/QUOTE``.

    Examples:
        >>> normalize_pair("BTC-USD")
        'BTC/USD'
        >>> normalize_pair("BTCUSDT")
        'BTC/USDT'
        >>> normalize_pair("BTC/USD")
        'BTC/USD'
    """
    pair = pair.strip().upper()

    # Already normalised
    if "/" in pair:
        return pair

    # Hyphen format  (Coinbase)
    m = _DASH_PAIR_RE.match(pair)
    if m:
        return f"{m.group(1)}/{m.group(2)}"

    # Concatenated format (Binance)
    for quote in _CONCAT_QUOTES:
        if pair.endswith(quote) and len(pair) > len(quote):
            base = pair[: -len(quote)]
            return f"{base}/{quote}"

    # Fallback — return as-is (CCXT will validate)
    return pair


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

class _CircuitBreaker:
    """Simple consecutive-failure circuit breaker.

    After ``max_failures`` consecutive failures the breaker opens for
    ``cooldown_seconds``.  Public callers use ``check()`` before each
    request and ``record_success()`` / ``record_failure()`` after.
    """

    def __init__(self, max_failures: int = 3, cooldown_seconds: float = 30.0) -> None:
        self._max_failures = max_failures
        self._cooldown_seconds = cooldown_seconds
        self._consecutive_failures = 0
        self._open_until: float = 0.0  # monotonic timestamp

    @property
    def is_open(self) -> bool:
        """Return ``True`` if the breaker is currently open (blocking)."""
        if self._consecutive_failures >= self._max_failures:
            return time.monotonic() < self._open_until
        return False

    def check(self) -> None:
        """Raise if the circuit is open."""
        if self.is_open:
            remaining = self._open_until - time.monotonic()
            raise ExchangeNetworkError(
                f"Circuit breaker open — retry in {remaining:.0f}s"
            )

    def record_success(self) -> None:
        """Reset the failure counter on a successful request."""
        self._consecutive_failures = 0

    def record_failure(self) -> None:
        """Increment the failure counter; open the breaker if threshold reached."""
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._max_failures:
            self._open_until = time.monotonic() + self._cooldown_seconds
            logger.warning(
                "Circuit breaker opened after %d consecutive failures — "
                "cooldown %.0fs",
                self._consecutive_failures,
                self._cooldown_seconds,
            )


# ---------------------------------------------------------------------------
# CCXT status -> our OrderStatus
# ---------------------------------------------------------------------------

_STATUS_MAP: dict[str, OrderStatus] = {
    "open": OrderStatus.OPEN,
    "closed": OrderStatus.CLOSED,
    "canceled": OrderStatus.CANCELED,
    "cancelled": OrderStatus.CANCELED,
    "expired": OrderStatus.EXPIRED,
    "rejected": OrderStatus.REJECTED,
}


def _map_order_status(raw_status: str) -> OrderStatus:
    return _STATUS_MAP.get(raw_status.lower(), OrderStatus.PENDING)


# ---------------------------------------------------------------------------
# CcxtAdapter
# ---------------------------------------------------------------------------

class CcxtAdapter(BaseExchangeAdapter):
    """Concrete exchange adapter backed by CCXT ``async_support``.

    Args:
        exchange_id: Lowercase exchange name (``"kraken"``, ``"coinbase"``,
            ``"binance"``, ``"bybit"``).
        api_key: API key (empty string for public-only access).
        secret: API secret.
        passphrase: Passphrase (Coinbase Advanced Trade).
        sandbox: If ``True``, use the exchange's testnet/sandbox
            environment where available.
    """

    def __init__(
        self,
        exchange_id: str,
        api_key: str = "",
        secret: str = "",
        passphrase: str = "",
        sandbox: bool = False,
    ) -> None:
        exchange_id = exchange_id.lower()
        if exchange_id not in _SUPPORTED_EXCHANGES:
            raise ExchangeNotAvailableError(
                f"Exchange '{exchange_id}' is not supported. "
                f"Supported: {sorted(_SUPPORTED_EXCHANGES)}",
                exchange_id=exchange_id,
            )

        self._exchange_id = exchange_id
        self._sandbox = sandbox
        self._api_key = api_key
        self._secret = secret
        self._passphrase = passphrase
        self._connected = False
        self._circuit = _CircuitBreaker()

        # Build CCXT config
        config: dict[str, Any] = {
            "enableRateLimit": True,
        }
        if api_key:
            config["apiKey"] = api_key
        if secret:
            config["secret"] = secret
        if passphrase:
            config["password"] = passphrase

        # Sandbox overrides
        if sandbox and exchange_id in _SANDBOX_OVERRIDES:
            config.update(_SANDBOX_OVERRIDES[exchange_id])

        # Instantiate the CCXT exchange class
        exchange_class = getattr(ccxt_async, exchange_id, None)
        if exchange_class is None:
            raise ExchangeNotAvailableError(
                f"CCXT does not have a class for '{exchange_id}'",
                exchange_id=exchange_id,
            )
        self._exchange: ccxt_async.Exchange = exchange_class(config)

    # -- Properties ----------------------------------------------------------

    @property
    def exchange_id(self) -> str:
        return self._exchange_id

    @property
    def display_name(self) -> str:
        return self._exchange.name

    @property
    def is_connected(self) -> bool:
        """Whether ``connect()`` has been called successfully."""
        return self._connected

    # -- Connection ----------------------------------------------------------

    async def connect(self) -> None:
        """Load markets from the exchange (required before most operations)."""
        try:
            await self._exchange.load_markets()
            self._connected = True
            logger.info("Connected to %s (%d markets loaded)", self.display_name, len(self._exchange.markets))
        except Exception as exc:
            raise self._map_exception(exc) from exc

    async def disconnect(self) -> None:
        """Close the underlying CCXT session."""
        try:
            await self._exchange.close()
        except Exception:
            pass  # best-effort
        finally:
            self._connected = False
            logger.info("Disconnected from %s", self.display_name)

    # -- Market data (public) ------------------------------------------------

    async def fetch_ticker(self, symbol: str) -> Ticker:
        """Fetch the latest ticker for *symbol*."""
        symbol = normalize_pair(symbol)
        self._circuit.check()
        try:
            raw = await self._exchange.fetch_ticker(symbol)
            self._circuit.record_success()
            ts = datetime.fromtimestamp(
                (raw.get("timestamp") or 0) / 1000, tz=timezone.utc
            )
            return Ticker(
                symbol=raw.get("symbol", symbol),
                bid=float(raw.get("bid") or 0),
                ask=float(raw.get("ask") or 0),
                last=float(raw.get("last") or 0),
                volume_24h=float(raw.get("baseVolume") or 0),
                timestamp=ts,
                raw=raw,
            )
        except Exception as exc:
            self._circuit.record_failure()
            raise self._map_exception(exc) from exc

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1m",
        limit: int = 100,
    ) -> list[OHLCV]:
        """Fetch OHLCV candles, oldest first."""
        symbol = normalize_pair(symbol)
        self._circuit.check()
        try:
            raw_candles = await self._exchange.fetch_ohlcv(
                symbol, timeframe=timeframe, limit=limit,
            )
            self._circuit.record_success()
            result: list[OHLCV] = []
            for c in raw_candles:
                result.append(
                    OHLCV(
                        timestamp=datetime.fromtimestamp(c[0] / 1000, tz=timezone.utc),
                        open=float(c[1]),
                        high=float(c[2]),
                        low=float(c[3]),
                        close=float(c[4]),
                        volume=float(c[5]),
                    )
                )
            return result
        except Exception as exc:
            self._circuit.record_failure()
            raise self._map_exception(exc) from exc

    async def fetch_orderbook(
        self,
        symbol: str,
        limit: int = 25,
    ) -> dict[str, Any]:
        """Fetch the order book for *symbol*."""
        symbol = normalize_pair(symbol)
        self._circuit.check()
        try:
            raw = await self._exchange.fetch_order_book(symbol, limit=limit)
            self._circuit.record_success()
            return {
                "bids": raw.get("bids", []),
                "asks": raw.get("asks", []),
                "timestamp": raw.get("timestamp"),
                "nonce": raw.get("nonce"),
            }
        except Exception as exc:
            self._circuit.record_failure()
            raise self._map_exception(exc) from exc

    # -- Trading (auth required) ---------------------------------------------

    async def create_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        amount: float,
        price: float | None = None,
    ) -> OrderResult:
        """Place an order on the exchange."""
        self._require_auth()
        symbol = normalize_pair(symbol)
        self._circuit.check()

        ccxt_type = order_type.value
        if order_type == OrderType.STOP_LOSS:
            ccxt_type = "stop"
        elif order_type == OrderType.TAKE_PROFIT:
            ccxt_type = "takeProfit"

        try:
            raw = await self._exchange.create_order(
                symbol=symbol,
                type=ccxt_type,
                side=side.value,
                amount=amount,
                price=price,
            )
            self._circuit.record_success()
            return self._parse_order(raw)
        except Exception as exc:
            self._circuit.record_failure()
            raise self._map_exception(exc) from exc

    async def cancel_order(self, order_id: str, symbol: str) -> OrderResult:
        """Cancel an open order."""
        self._require_auth()
        symbol = normalize_pair(symbol)
        self._circuit.check()
        try:
            raw = await self._exchange.cancel_order(order_id, symbol)
            self._circuit.record_success()
            return self._parse_order(raw)
        except Exception as exc:
            self._circuit.record_failure()
            raise self._map_exception(exc) from exc

    async def fetch_order(self, order_id: str, symbol: str) -> OrderResult:
        """Retrieve current state of an order."""
        self._require_auth()
        symbol = normalize_pair(symbol)
        self._circuit.check()
        try:
            raw = await self._exchange.fetch_order(order_id, symbol)
            self._circuit.record_success()
            return self._parse_order(raw)
        except Exception as exc:
            self._circuit.record_failure()
            raise self._map_exception(exc) from exc

    # -- Account (auth required) ---------------------------------------------

    async def fetch_balance(self) -> list[Balance]:
        """Fetch all non-zero account balances."""
        self._require_auth()
        self._circuit.check()
        try:
            raw = await self._exchange.fetch_balance()
            self._circuit.record_success()
            balances: list[Balance] = []
            total_dict: dict[str, Any] = raw.get("total", {})
            free_dict: dict[str, Any] = raw.get("free", {})
            used_dict: dict[str, Any] = raw.get("used", {})
            for currency, total_val in total_dict.items():
                total_f = float(total_val or 0)
                if total_f > 0:
                    balances.append(
                        Balance(
                            currency=currency,
                            free=float(free_dict.get(currency) or 0),
                            used=float(used_dict.get(currency) or 0),
                            total=total_f,
                        )
                    )
            return balances
        except Exception as exc:
            self._circuit.record_failure()
            raise self._map_exception(exc) from exc

    # -- Exchange info -------------------------------------------------------

    async def get_supported_pairs(self) -> list[str]:
        """Return all tradable pairs in normalised ``BASE/QUOTE`` format."""
        if not self._exchange.markets:
            await self._exchange.load_markets()
        return sorted(self._exchange.markets.keys())

    async def get_limits(self, symbol: str) -> ExchangeLimits:
        """Return trading limits / precision for *symbol*."""
        symbol = normalize_pair(symbol)
        if not self._exchange.markets:
            await self._exchange.load_markets()

        market = self._exchange.market(symbol)
        limits = market.get("limits", {})
        precision = market.get("precision", {})

        # Extract limits with safe defaults
        amount_limits = limits.get("amount", {})
        cost_limits = limits.get("cost", {})

        # Fee extraction — CCXT stores fees in varying structures
        maker_fee = float(market.get("maker", 0) or 0)
        taker_fee = float(market.get("taker", 0) or 0)

        # Precision: CCXT may store as integer (decimal places) or
        # float (tick size). Convert tick size to decimal places.
        price_prec = self._precision_to_dp(precision.get("price"))
        amount_prec = self._precision_to_dp(precision.get("amount"))

        return ExchangeLimits(
            min_order_amount=float(amount_limits.get("min") or 0),
            max_order_amount=float(amount_limits.get("max") or 0),
            min_order_cost=float(cost_limits.get("min") or 0),
            price_precision=price_prec,
            amount_precision=amount_prec,
            maker_fee=maker_fee,
            taker_fee=taker_fee,
        )

    async def validate_credentials(self) -> bool:
        """Test API credentials by calling fetch_balance."""
        if not self._api_key:
            return False
        try:
            await self.fetch_balance()
            return True
        except ExchangeAuthError:
            return False
        except ExchangeError:
            # Other errors (network, rate limit) don't mean creds are bad
            return False

    # -- Internal helpers ----------------------------------------------------

    @staticmethod
    def _precision_to_dp(value: Any) -> int:
        """Convert a CCXT precision value to number of decimal places.

        CCXT stores precision in two formats depending on the exchange:
        - Integer: already the number of decimal places (e.g. 2 -> 2 dp)
        - Float (tick size): e.g. 0.1 -> 1 dp, 0.01 -> 2 dp, 1e-08 -> 8 dp

        Returns a sensible default of 8 if the value is None or zero.
        """
        if value is None:
            return 8
        fval = float(value)
        if fval <= 0:
            return 8
        # If it looks like an integer >= 1, treat as number-of-decimal-places
        if fval >= 1 and fval == int(fval):
            return int(fval)
        # Otherwise it is a tick size — convert to decimal places
        import math
        return max(0, int(round(-math.log10(fval))))

    def _require_auth(self) -> None:
        """Raise ``ExchangeAuthError`` if no credentials were provided."""
        if not self._api_key:
            raise ExchangeAuthError(
                "This operation requires API credentials. "
                "Create the adapter with api_key and secret.",
                exchange_id=self._exchange_id,
            )

    def _parse_order(self, raw: dict[str, Any]) -> OrderResult:
        """Convert a CCXT order dict to ``OrderResult``."""
        fee_info = raw.get("fee") or {}
        ts_raw = raw.get("timestamp")
        ts = (
            datetime.fromtimestamp(ts_raw / 1000, tz=timezone.utc)
            if ts_raw
            else None
        )

        # Map order type
        raw_type = (raw.get("type") or "market").lower()
        otype = OrderType.MARKET
        if "limit" in raw_type:
            otype = OrderType.LIMIT
        elif "stop" in raw_type:
            otype = OrderType.STOP_LOSS

        return OrderResult(
            order_id=str(raw.get("id", "")),
            symbol=raw.get("symbol", ""),
            side=OrderSide(raw.get("side", "buy").lower()),
            order_type=otype,
            status=_map_order_status(raw.get("status", "open")),
            price=float(raw.get("price") or raw.get("average") or 0),
            amount=float(raw.get("amount") or 0),
            filled=float(raw.get("filled") or 0),
            remaining=float(raw.get("remaining") or 0),
            cost=float(raw.get("cost") or 0),
            fee=float(fee_info.get("cost") or 0),
            fee_currency=str(fee_info.get("currency") or ""),
            timestamp=ts,
            raw=raw,
        )

    def _map_exception(self, exc: Exception) -> ExchangeError:
        """Map a CCXT exception to our custom hierarchy.

        NOTE: Order matters! CCXT exception hierarchy has subclass
        relationships (e.g. ExchangeNotAvailable extends NetworkError),
        so more specific types must be checked first.
        """
        import ccxt as ccxt_sync  # for exception types (shared with async)

        msg = str(exc)
        eid = self._exchange_id

        if isinstance(exc, ccxt_sync.AuthenticationError):
            return ExchangeAuthError(msg, exchange_id=eid, original=exc)
        if isinstance(exc, ccxt_sync.InsufficientFunds):
            return InsufficientFundsError(msg, exchange_id=eid, original=exc)
        if isinstance(exc, ccxt_sync.InvalidOrder):
            return InvalidOrderError(msg, exchange_id=eid, original=exc)
        if isinstance(exc, ccxt_sync.RateLimitExceeded):
            return RateLimitError(msg, exchange_id=eid, original=exc)
        # ExchangeNotAvailable is a subclass of NetworkError — check first
        if isinstance(exc, ccxt_sync.ExchangeNotAvailable):
            return ExchangeNotAvailableError(msg, exchange_id=eid, original=exc)
        if isinstance(exc, ccxt_sync.NetworkError):
            return ExchangeNetworkError(msg, exchange_id=eid, original=exc)
        if isinstance(exc, ccxt_sync.ExchangeError):
            return ExchangeError(msg, exchange_id=eid, original=exc)
        # Unknown — wrap generically
        if isinstance(exc, ExchangeError):
            return exc
        return ExchangeError(msg, exchange_id=eid, original=exc)
