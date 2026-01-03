"""
Production-grade Kraken API gateway for scalping operations.

Handles order execution, position tracking, and market data with comprehensive
error handling, rate limiting, and performance monitoring for high-frequency
crypto trading operations.

Features:
- Low-latency order placement with retries/backoff
- Robust error handling and circuit breaker integration
- Position and balance tracking
- Configurable rate limiting
- Real-time order monitoring and status updates
- Comprehensive performance metrics
- Thread-safe operations with proper resource cleanup

This module provides the core execution capabilities for the scalping system,
enabling reliable order management and portfolio tracking on the Kraken exchange.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import time
import urllib.parse
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional

import aiohttp

from ..config_loader import KrakenScalpingConfig
from ..infra.redis_bus import RedisBus
from ..infra.state_manager import StateManager  # kept for parity; not used directly in this file


def as_decimal(x: float | str | Decimal) -> Decimal:
    """
    Convert float, string, or Decimal to Decimal for precise calculations.

    Args:
        x: Value to convert (float, str, or Decimal)

    Returns:
        Decimal representation of the input value
    """
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


# ------------------------------- DTOs -------------------------------


@dataclass
class OrderRequest:
    """Order request structure"""

    symbol: str
    side: str  # "buy" or "sell"
    order_type: str  # "limit", "market"
    size: Decimal
    price: Optional[Decimal] = None
    time_in_force: str = "GTC"  # GTC, IOC, GTD
    post_only: bool = False
    hidden: bool = False  # iceberg-like on Kraken requires displayvol; kept as flag for future
    reduce_only: bool = False  # supported on margin/derivatives; Kraken spot may ignore
    client_order_id: Optional[str] = None
    expire_time_unix: Optional[int] = None  # used if GTD (epoch seconds)


@dataclass
class OrderResponse:
    """Order response structure"""

    order_id: str
    client_order_id: Optional[str]
    symbol: str
    side: str
    order_type: str
    size: Decimal
    price: Optional[Decimal]
    status: str  # "open", "filled", "cancelled", "rejected", "unknown"
    filled_size: Decimal = Decimal("0")
    remaining_size: Decimal = Decimal("0")
    avg_fill_price: Optional[Decimal] = None
    fees: Decimal = Decimal("0")
    timestamp: float = field(default_factory=time.time)
    error_message: Optional[str] = None


@dataclass
class Position:
    """Position structure"""

    symbol: str
    size: Decimal
    avg_price: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    timestamp: float = field(default_factory=time.time)


# ------------------------------ Gateway ------------------------------


class KrakenGateway:
    """
    Production Kraken API gateway optimized for scalping.

    Features:
    - Low-latency order placement with retries/backoff
    - Robust error handling
    - Position and balance tracking
    - Configurable rate limiting
    - Circuit breaker integration hooks via RedisBus
    """

    def __init__(
        self,
        config: KrakenScalpingConfig,
        state_manager: StateManager,
        redis_bus: RedisBus,
        agent_id: str = "kraken_scalper",
    ):
        self.config = config
        self.state_manager = state_manager
        self.redis_bus = redis_bus
        self.agent_id = agent_id
        self.logger = logging.getLogger(f"{__name__}.{agent_id}")

        # Kraken API configuration
        self.api_key: str = config.kraken.api_key
        self.api_secret_b64: str = config.kraken.api_secret
        self.api_secret: bytes = base64.b64decode(self.api_secret_b64)
        self.api_url: str = config.kraken.api_url.rstrip("/")
        self.api_version: str = str(getattr(config.kraken, "api_version", "0"))

        # Session & tasks
        self.session: Optional[aiohttp.ClientSession] = None
        self._tasks: List[asyncio.Task] = []
        self._running: bool = False

        # Rate limiter (configurable)
        self.rate_limiter = KrakenRateLimiter(config)

        # Order tracking
        self.pending_orders: Dict[str, OrderRequest] = {}
        self.completed_orders: Dict[str, OrderResponse] = {}

        # Position & balance tracking
        self.positions: Dict[str, Position] = {}
        self.balances: Dict[str, float] = {}

        # Performance metrics
        self.metrics = {
            "orders_sent": 0,
            "orders_filled": 0,
            "orders_rejected": 0,
            "api_errors": 0,
            "avg_latency_ms": 0.0,
            "last_update": time.time(),
        }

        # Kraken pair mappings
        self.pair_mapping = {
            "BTC/USD": "XBTUSD",
            "ETH/USD": "ETHUSD",
            "SOL/USD": "SOLUSD",
            "ADA/USD": "ADAUSD",
        }
        self.reverse_pair_mapping = {v: k for k, v in self.pair_mapping.items()}

        self.logger.info("KrakenGateway initialized for %s", agent_id)

    # ----------------------------- Lifecycle -----------------------------

    async def start(self) -> None:
        """Start the gateway"""
        self.logger.info("Starting KrakenGateway...")

        # Create aiohttp session
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        headers = {"User-Agent": f"crypto-ai-bot/{self.agent_id}"}
        connector = aiohttp.TCPConnector(ssl=True, limit=100, enable_cleanup_closed=True)
        self.session = aiohttp.ClientSession(timeout=timeout, headers=headers, connector=connector)

        # Validate API credentials (private Balance call)
        await self._validate_credentials()

        # Load initial state (positions + balances)
        await self._load_initial_state()

        # Start background tasks
        self._running = True
        self._tasks = [
            asyncio.create_task(self._monitor_orders(), name=f"{self.agent_id}.monitor_orders"),
            asyncio.create_task(self._update_positions(), name=f"{self.agent_id}.update_positions"),
        ]

        self.logger.info("KrakenGateway started successfully")

    async def stop(self) -> None:
        """Stop the gateway and clean up resources"""
        self.logger.info("Stopping KrakenGateway...")

        self._running = False
        # Cancel background tasks
        for t in self._tasks:
            if not t.done():
                t.cancel()
        for t in self._tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
            except Exception as e:
                self.logger.error("Background task ended with error: %s", e)
        self._tasks.clear()

        # Close session
        if self.session:
            await self.session.close()
            self.session = None

        self.logger.info("KrakenGateway stopped")

    # ---------------------------- Order APIs ----------------------------

    async def place_order(self, order_request: OrderRequest) -> OrderResponse:
        """
        Place an order on Kraken.

        Returns OrderResponse with execution details.

        Uses ExecutionGate as the SINGLE CHOKE POINT for all order validation.
        Gate checks (in order):
        1. EMERGENCY_STOP=true -> reject all orders
        2. LIVE_TRADING_ENABLED=false -> log DRY-RUN, don't execute
        3. Dependency health -> must be healthy
        4. Risk limits -> position size, daily loss, trades/day
        5. MODE=live + confirmation -> final authorization
        6. SHADOW_EXECUTION=true -> simulate without API call
        """
        import os
        import uuid

        from agents.core.errors import RiskViolation

        notional_usd = float(order_request.size) * float(order_request.price or 0)

        # =====================================================================
        # EXECUTION GATE - Single choke point for all order validation
        # =====================================================================
        try:
            from protections.execution_gate import get_execution_gate

            gate = get_execution_gate()
            gate_result = gate.check(position_size_usd=notional_usd)

            # DRY-RUN MODE: Log "would place order" and return
            if gate_result.dry_run:
                gate.log_dry_run_order({
                    "symbol": order_request.symbol,
                    "side": order_request.side,
                    "size": order_request.size,
                    "price": order_request.price,
                    "order_type": order_request.order_type,
                    "client_order_id": order_request.client_order_id,
                })
                return OrderResponse(
                    order_id="",
                    client_order_id=order_request.client_order_id,
                    symbol=order_request.symbol,
                    side=order_request.side,
                    order_type=order_request.order_type,
                    size=order_request.size,
                    price=order_request.price,
                    status="dry_run",
                    error_message="DRY-RUN: order logged but not executed",
                )

            # BLOCKED: Gate rejected the order
            if not gate_result.allowed:
                self.logger.warning(
                    "Order blocked by ExecutionGate: %s (gate=%s)",
                    gate_result.reason,
                    gate_result.gate_name,
                )
                return OrderResponse(
                    order_id="",
                    client_order_id=order_request.client_order_id,
                    symbol=order_request.symbol,
                    side=order_request.side,
                    order_type=order_request.order_type,
                    size=order_request.size,
                    price=order_request.price,
                    status="rejected",
                    error_message=f"ExecutionGate: {gate_result.reason}",
                )

            # SHADOW MODE: Simulate order without API call
            # Records complete audit trail but NEVER calls Kraken private endpoints
            if gate_result.shadow_mode:
                shadow_order_id = f"SHADOW-{uuid.uuid4().hex[:12].upper()}"

                # Record complete audit trail
                try:
                    from protections.shadow_recorder import get_shadow_recorder

                    recorder = get_shadow_recorder()
                    audit_event = recorder.record_shadow_order(
                        shadow_order_id=shadow_order_id,
                        symbol=order_request.symbol,
                        side=order_request.side,
                        size=float(order_request.size),
                        price=float(order_request.price) if order_request.price else None,
                        order_type=order_request.order_type,
                        client_order_id=order_request.client_order_id,
                        reason="scalp_signal",  # Signal that triggered this order
                        risk_check_passed=True,  # Passed all risk checks to get here
                        risk_check_details={
                            "notional_usd": notional_usd,
                            "max_position_size_usd": gate.max_position_size_usd,
                            "within_limits": True,
                        },
                        gate_allowed=True,
                        gate_name=None,
                        gate_reason=gate_result.reason,
                    )
                    self.logger.info("Shadow audit recorded: %s", audit_event.shadow_order_id)
                except ImportError:
                    # Fallback logging if recorder not available
                    self.logger.info(
                        "SHADOW ORDER: %s %s %s @ %s (notional=$%.2f) -> %s",
                        order_request.side,
                        order_request.size,
                        order_request.symbol,
                        order_request.price,
                        notional_usd,
                        shadow_order_id,
                    )

                return OrderResponse(
                    order_id=shadow_order_id,
                    client_order_id=order_request.client_order_id,
                    symbol=order_request.symbol,
                    side=order_request.side,
                    order_type=order_request.order_type,
                    size=order_request.size,
                    price=order_request.price,
                    status="shadow",
                    filled_size=order_request.size,
                    avg_fill_price=order_request.price,
                    error_message=None,
                )

        except ImportError as e:
            # ExecutionGate is REQUIRED - block order if unavailable
            self.logger.error("ExecutionGate import failed - order blocked: %s", e)
            return OrderResponse(
                order_id="",
                client_order_id=order_request.client_order_id,
                symbol=order_request.symbol,
                side=order_request.side,
                order_type=order_request.order_type,
                size=order_request.size,
                price=order_request.price,
                status="rejected",
                error_message="ExecutionGate unavailable - execution blocked for safety",
            )

        # =====================================================================
        # LIVE EXECUTION - All gates passed, proceed with real order
        # =====================================================================
        start_time = time.time()

        try:
            await self.rate_limiter.acquire()

            # Pair & base params
            kraken_symbol = self.pair_mapping.get(order_request.symbol, order_request.symbol)
            params: Dict[str, Any] = {
                "pair": kraken_symbol,
                "type": order_request.side.lower(),
                "ordertype": order_request.order_type.lower(),
                "volume": str(order_request.size),
                # For spot we generally want immediate funds check
                # "validate": False  # if True, validates only without executing
            }

            # Limit price
            if order_request.order_type.lower() == "limit":
                if order_request.price is None:
                    return self._reject_from_client(
                        "Price required for limit orders", order_request
                    )
                params["price"] = str(order_request.price)

            # Time in force
            tif = (order_request.time_in_force or "GTC").upper()
            if tif in ("GTC", "IOC", "GTD"):
                params["timeinforce"] = tif
                if tif == "GTD":
                    # Kraken expects either RFC3339 or UNIX timestamp (expiretm)
                    expire = order_request.expire_time_unix or int(time.time()) + 60
                    params["expiretm"] = str(expire)

            # oflags
            oflags = []
            if order_request.post_only:
                oflags.append("post")
            # Kraken "hidden" is via iceberg ("displayvol"); we keep flag for future
            if order_request.reduce_only:
                # reduce_only for margin/derivatives; Kraken ignores on spot
                params["reduce_only"] = True
            if oflags:
                params["oflags"] = ",".join(oflags)

            # client order id
            if order_request.client_order_id:
                params["userref"] = str(order_request.client_order_id)

            # Call API with retries/backoff
            response = await self._make_request("POST", "AddOrder", params, private=True)

            # Parse Kraken error envelope
            if response.get("error"):
                error_msg = "; ".join(response["error"])
                self.logger.error("Order rejected: %s", error_msg)
                self.metrics["orders_rejected"] += 1
                return OrderResponse(
                    order_id="",
                    client_order_id=order_request.client_order_id,
                    symbol=order_request.symbol,
                    side=order_request.side,
                    order_type=order_request.order_type,
                    size=order_request.size,
                    price=order_request.price,
                    status="rejected",
                    error_message=error_msg,
                )

            result = response.get("result", {}) or {}
            txids = result.get("txid", []) or []
            order_id = txids[0] if txids else ""

            # Track pending
            if order_id:
                self.pending_orders[order_id] = order_request
            self.metrics["orders_sent"] += 1

            # Latency EMA
            latency_ms = (time.time() - start_time) * 1000.0
            self._update_latency_metric(latency_ms)

            self.logger.info(
                "Order placed: %s %s %s %.8f @ %s (latency: %.1f ms)",
                order_id,
                order_request.symbol,
                order_request.side,
                order_request.size,
                order_request.price if order_request.price is not None else "MKT",
                latency_ms,
            )

            # Broadcast order event
            await self.redis_bus.publish(
                f"orders:placed:{self.agent_id}",
                {
                    "order_id": order_id,
                    "symbol": order_request.symbol,
                    "side": order_request.side,
                    "size": float(order_request.size),
                    "price": float(order_request.price) if order_request.price else None,
                    "latency_ms": latency_ms,
                    "timestamp": time.time(),
                },
            )

            return OrderResponse(
                order_id=order_id,
                client_order_id=order_request.client_order_id,
                symbol=order_request.symbol,
                side=order_request.side,
                order_type=order_request.order_type,
                size=order_request.size,
                price=order_request.price,
                status="open",
                remaining_size=order_request.size,
            )

        except Exception as e:
            self.logger.error("Error placing order: %s", e, exc_info=True)
            self.metrics["api_errors"] += 1
            return OrderResponse(
                order_id="",
                client_order_id=order_request.client_order_id,
                symbol=order_request.symbol,
                side=order_request.side,
                order_type=order_request.order_type,
                size=order_request.size,
                price=order_request.price,
                status="rejected",
                error_message=str(e),
            )

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an order by ID"""
        try:
            await self.rate_limiter.acquire()
            response = await self._make_request(
                "POST", "CancelOrder", {"txid": order_id}, private=True
            )
            if response.get("error"):
                self.logger.error("Cancel order failed: %s", "; ".join(response["error"]))
                return False

            # Remove from pending orders
            self.pending_orders.pop(order_id, None)
            self.logger.info("Order cancelled: %s", order_id)
            return True

        except Exception as e:
            self.logger.error("Error cancelling order %s: %s", order_id, e, exc_info=True)
            return False

    async def get_order_status(self, order_id: str) -> Optional[OrderResponse]:
        """Get current status of an order"""
        try:
            await self.rate_limiter.acquire()
            response = await self._make_request(
                "POST", "QueryOrders", {"txid": order_id}, private=True
            )
            if response.get("error"):
                self.logger.error("QueryOrders error: %s", "; ".join(response["error"]))
                return None

            result = response.get("result", {}) or {}
            od = result.get(order_id)
            if not od:
                return None

            descr = od.get("descr", {}) or {}
            kraken_symbol = descr.get("pair", "")
            symbol = self.reverse_pair_mapping.get(kraken_symbol, kraken_symbol) or kraken_symbol
            side = (descr.get("type", "") or "").lower()
            order_type = (descr.get("ordertype", "") or "").lower()

            size = as_decimal(od.get("vol", 0.0) or 0.0)
            price_field = descr.get("price")
            price = as_decimal(price_field) if price_field not in (None, "", "0") else None

            status_raw = (od.get("status", "") or "").lower()
            if status_raw == "open":
                status = "open"
            elif status_raw == "closed":
                status = "filled"
            elif status_raw == "canceled":
                status = "cancelled"
            else:
                status = "unknown"

            filled_size = as_decimal(od.get("vol_exec", 0.0) or 0.0)
            remaining_size = max(Decimal("0"), size - filled_size)
            avg_fill_price_val = od.get("price", 0.0) or 0.0
            avg_fill_price = as_decimal(avg_fill_price_val) if avg_fill_price_val else None
            fees = as_decimal(od.get("fee", 0.0) or 0.0)
            userref = od.get("userref")

            return OrderResponse(
                order_id=order_id,
                client_order_id=str(userref) if userref is not None else None,
                symbol=symbol,
                side=side,
                order_type=order_type,
                size=size,
                price=price,
                status=status,
                filled_size=filled_size,
                remaining_size=remaining_size,
                avg_fill_price=avg_fill_price,
                fees=fees,
            )

        except Exception as e:
            self.logger.error("Error getting order status %s: %s", order_id, e, exc_info=True)
            return None

    # ----------------------------- Portfolio -----------------------------

    async def get_positions(self) -> Dict[str, Position]:
        """Get current positions (Kraken 'OpenPositions')."""
        try:
            await self.rate_limiter.acquire()
            response = await self._make_request("POST", "OpenPositions", {}, private=True)
            if response.get("error"):
                self.logger.error("OpenPositions error: %s", "; ".join(response["error"]))
                return {}

            result = response.get("result", {}) or {}
            positions: Dict[str, Position] = {}

            for _pos_id, pos in result.items():
                kraken_symbol = pos.get("pair", "") or ""
                symbol = (
                    self.reverse_pair_mapping.get(kraken_symbol, kraken_symbol) or kraken_symbol
                )

                vol = as_decimal(pos.get("vol", 0.0) or 0.0)
                side = (pos.get("type", "") or "").lower()
                size = vol if side == "buy" else -vol

                cost = as_decimal(pos.get("cost", 0.0) or 0.0)
                avg_price = (cost / abs(size)) if size != Decimal("0") else Decimal("0")
                unrealized_pnl = as_decimal(pos.get("net", 0.0) or 0.0)  # net P&L (Kraken naming)

                positions[symbol] = Position(
                    symbol=symbol,
                    size=size,
                    avg_price=avg_price,
                    unrealized_pnl=unrealized_pnl,
                    realized_pnl=Decimal("0"),  # separate call needed for realized P&L if desired
                )

            self.positions = positions
            return positions

        except Exception as e:
            self.logger.error("Error getting positions: %s", e, exc_info=True)
            return {}

    async def get_balances(self) -> Dict[str, float]:
        """Get account balances"""
        try:
            await self.rate_limiter.acquire()
            response = await self._make_request("POST", "Balance", {}, private=True)
            if response.get("error"):
                self.logger.error("Balance error: %s", "; ".join(response["error"]))
                return {}

            result = response.get("result", {}) or {}
            balances: Dict[str, float] = {}

            # Common mapping (extend as needed)
            currency_mapping = {
                "ZUSD": "USD",
                "ZEUR": "EUR",
                "ZJPY": "JPY",
                "ZGBP": "GBP",
                "XXBT": "BTC",
                "XETH": "ETH",
            }
            for k, v in result.items():
                std = currency_mapping.get(k, k)
                try:
                    balances[std] = float(v)
                except Exception:
                    continue

            self.balances = balances
            return balances

        except Exception as e:
            self.logger.error("Error getting balances: %s", e, exc_info=True)
            return {}

    async def get_ticker(self, symbol: str) -> Optional[Dict[str, float]]:
        """Get current ticker data for a symbol (public endpoint)"""
        try:
            if not self.session:
                return None
            kraken_symbol = self.pair_mapping.get(symbol, symbol)
            url = f"{self.api_url}/{self.api_version}/public/Ticker"
            params = {"pair": kraken_symbol}

            async with self.session.get(url, params=params) as resp:
                if resp.status != 200:
                    self.logger.error("Ticker HTTP %s for %s", resp.status, symbol)
                    return None
                data = await resp.json()

            if data.get("error"):
                self.logger.error("Ticker error for %s: %s", symbol, "; ".join(data["error"]))
                return None

            result = data.get("result", {}) or {}
            t = result.get(kraken_symbol)
            if not t:
                return None

            bid = float(t["b"][0])
            ask = float(t["a"][0])
            last = float(t["c"][0])
            volume_24h = float(t["v"][1])
            vwap_24h = float(t["p"][1])
            spread_bps = ((ask - bid) / bid) * 10_000.0 if bid > 0 else 0.0

            return {
                "bid": bid,
                "ask": ask,
                "last": last,
                "volume": volume_24h,
                "vwap": vwap_24h,
                "spread_bps": spread_bps,
            }

        except Exception as e:
            self.logger.error("Error getting ticker for %s: %s", symbol, e, exc_info=True)
            return None

    # ----------------------------- Internals -----------------------------

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        private: bool = True,
        max_retries: int = 3,
        retry_backoff_base: float = 0.25,
    ) -> Dict[str, Any]:
        """
        Make Kraken API request with HMAC signing (for private endpoints)
        and robust retry/backoff on network/server errors.
        """
        if not self.session:
            raise RuntimeError("HTTP session not initialized")

        params = params.copy() if params else {}
        url_path = (
            f"/{self.api_version}/private/{endpoint}"
            if private
            else f"/{self.api_version}/public/{endpoint}"
        )
        url = f"{self.api_url}{url_path}"

        # Prepare payload & headers
        headers: Dict[str, str] = {}
        data: Optional[str] = None

        if private:
            # nonce must increase monotonically; microseconds give plenty of headroom
            nonce = str(int(time.time() * 1_000_000))
            params["nonce"] = nonce
            postdata = urllib.parse.urlencode(params)

            # API-Sign = base64(hmac_sha512(secret, url_path + sha256(nonce+postdata)))
            sha256_digest = hashlib.sha256((nonce + postdata).encode()).digest()
            message = url_path.encode() + sha256_digest
            sig = hmac.new(self.api_secret, message, hashlib.sha512).digest()
            headers = {
                "API-Key": self.api_key,
                "API-Sign": base64.b64encode(sig).decode(),
                "Content-Type": "application/x-www-form-urlencoded",
            }
            data = postdata
        else:
            # public GET, keep params in query string
            data = None

        # Retry loop
        for attempt in range(1, max_retries + 1):
            try:
                if private:
                    async with self.session.request(
                        method, url, data=data, headers=headers
                    ) as resp:
                        j = await self._parse_json(resp)
                else:
                    async with self.session.request(method, url, params=params) as resp:
                        j = await self._parse_json(resp)

                # Kraken wraps errors in {"error": [...]} even on 200
                if j is None:
                    raise RuntimeError("Empty response")
                if isinstance(j.get("error"), list) and j["error"]:
                    # Some errors are transient; let caller decide
                    return j
                return j

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                self.metrics["api_errors"] += 1
                if attempt >= max_retries:
                    self.logger.error("HTTP error on %s %s (final): %s", method, endpoint, e)
                    raise
                delay = retry_backoff_base * (2 ** (attempt - 1))
                jitter = 0.05 * delay
                await asyncio.sleep(delay + (jitter * (0.5 - time.time() % 1)))  # small jitter

            except Exception as e:
                self.metrics["api_errors"] += 1
                if attempt >= max_retries:
                    self.logger.error(
                        "Request error on %s %s (final): %s", method, endpoint, e, exc_info=True
                    )
                    raise
                delay = retry_backoff_base * (2 ** (attempt - 1))
                await asyncio.sleep(delay)

        # Should not reach here
        return {"error": ["unreachable"]}

    async def _parse_json(self, resp: aiohttp.ClientResponse) -> Optional[Dict[str, Any]]:
        """Parse JSON and raise on non-200 HTTP."""
        if resp.status != 200:
            text = await resp.text()
            self.logger.error("HTTP %s: %s", resp.status, text[:256])
            raise RuntimeError(f"HTTP {resp.status}")
        try:
            return await resp.json()
        except Exception as e:
            text = await resp.text()
            self.logger.error("JSON parse error: %s | body: %s", e, text[:256])
            return None

    async def _validate_credentials(self) -> None:
        """Validate API credentials using a lightweight private call."""
        try:
            resp = await self._make_request("POST", "Balance", {}, private=True)
            if resp.get("error"):
                msg = "; ".join(resp["error"])
                if "Invalid key" in msg or "Invalid signature" in msg:
                    raise RuntimeError(f"Invalid Kraken API credentials: {msg}")
                self.logger.warning("API validation warning: %s", msg)
            else:
                self.logger.info("Kraken API credentials validated")
        except Exception as e:
            self.logger.error("Failed to validate Kraken credentials: %s", e, exc_info=True)
            raise

    async def _load_initial_state(self) -> None:
        """Load initial positions and balances"""
        try:
            await self.get_positions()
            await self.get_balances()
            self.logger.info(
                "Loaded %d positions and %d balances", len(self.positions), len(self.balances)
            )
        except Exception as e:
            self.logger.error("Error loading initial state: %s", e, exc_info=True)

    # --------------------------- Background Loops ---------------------------

    async def _monitor_orders(self) -> None:
        """Monitor pending orders for fills."""
        try:
            while self._running:
                if not self.pending_orders:
                    await asyncio.sleep(0.5)
                    continue

                # Iterate over a static snapshot to avoid runtime dict size change during iteration
                for order_id in list(self.pending_orders.keys()):
                    try:
                        status = await self.get_order_status(order_id)
                        if not status:
                            continue

                        if status.status in ("filled", "cancelled", "rejected"):
                            # Move to completed orders
                            self.completed_orders[order_id] = status
                            self.pending_orders.pop(order_id, None)

                            if status.status == "filled":
                                self.metrics["orders_filled"] += 1
                                await self.redis_bus.publish(
                                    f"orders:filled:{self.agent_id}",
                                    {
                                        "order_id": order_id,
                                        "symbol": status.symbol,
                                        "side": status.side,
                                        "size": float(status.filled_size),
                                        "price": (
                                            float(status.avg_fill_price)
                                            if status.avg_fill_price
                                            else None
                                        ),
                                        "fees": float(status.fees),
                                        "timestamp": time.time(),
                                    },
                                )
                    except Exception as e:
                        self.logger.error(
                            "Order monitor error for %s: %s", order_id, e, exc_info=True
                        )

                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            return
        except Exception as e:
            self.logger.error("Error in _monitor_orders loop: %s", e, exc_info=True)

    async def _update_positions(self) -> None:
        """Periodically update positions and balances and broadcast state."""
        try:
            while self._running:
                try:
                    await self.get_positions()
                    await self.get_balances()
                    await self.redis_bus.publish(
                        f"positions:update:{self.agent_id}",
                        {
                            "positions": {
                                sym: {
                                    "size": float(p.size),
                                    "avg_price": float(p.avg_price),
                                    "unrealized_pnl": float(p.unrealized_pnl),
                                }
                                for sym, p in self.positions.items()
                            },
                            "balances": self.balances,
                            "timestamp": time.time(),
                        },
                    )
                except Exception as inner_e:
                    self.logger.error("Error updating positions: %s", inner_e, exc_info=True)
                    # fall through to sleep

                await asyncio.sleep(30.0)
        except asyncio.CancelledError:
            return
        except Exception as e:
            self.logger.error("Error in _update_positions loop: %s", e, exc_info=True)

    # --------------------------- Misc Utilities ---------------------------

    def _update_latency_metric(self, latency_ms: float) -> None:
        """Update average latency metric with EMA."""
        alpha = 0.1
        self.metrics["avg_latency_ms"] = (
            alpha * latency_ms + (1 - alpha) * self.metrics["avg_latency_ms"]
        )

    @staticmethod
    def _reject_from_client(msg: str, req: OrderRequest) -> OrderResponse:
        return OrderResponse(
            order_id="",
            client_order_id=req.client_order_id,
            symbol=req.symbol,
            side=req.side,
            order_type=req.order_type,
            size=req.size,
            price=req.price,
            status="rejected",
            error_message=msg,
        )


# ------------------------------ Rate Limiter ------------------------------


class KrakenRateLimiter:
    """Simple token-bucket rate limiter for Kraken API calls"""

    def __init__(self, config: KrakenScalpingConfig):
        rl = getattr(getattr(config, "kraken", object()), "rate_limits", None)
        self.calls_per_second: float = float(getattr(rl, "calls_per_second", 1.0)) if rl else 1.0
        self.burst_size: float = float(getattr(rl, "burst_size", 2.0)) if rl else 2.0

        self.tokens: float = self.burst_size
        self.last_update: float = time.time()
        self.lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Acquire a token for API call"""
        async with self.lock:
            now = time.time()
            elapsed = now - self.last_update
            self.tokens = min(self.burst_size, self.tokens + elapsed * self.calls_per_second)
            self.last_update = now

            if self.tokens < 1.0:
                wait_time = (1.0 - self.tokens) / max(self.calls_per_second, 1e-6)
                await asyncio.sleep(wait_time)
                self.tokens = 1.0

            self.tokens -= 1.0
