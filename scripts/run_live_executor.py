#!/usr/bin/env python3
"""
Live Execution Consumer - Consumes signals and executes on Kraken
==================================================================

Reads signals from signals:live:{PAIR} streams and executes trades
via Kraken API with full safety gate protection.

CRITICAL: This executes REAL TRADES with REAL MONEY.

Usage:
    # Requires explicit confirmation
    export LIVE_TRADING_CONFIRMATION="I-accept-the-risk"
    python scripts/run_live_executor.py

    # With specific pairs
    python scripts/run_live_executor.py --pairs BTC/USD,ETH/USD

Environment Variables Required:
    REDIS_URL                   - Redis Cloud URL (rediss://)
    KRAKEN_API_KEY             - Kraken API key
    KRAKEN_API_SECRET          - Kraken API secret
    LIVE_TRADING_ENABLED       - Must be "true"
    LIVE_TRADING_CONFIRMATION  - Must be "I-accept-the-risk"
    ENGINE_MODE                - Must be "live"
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import sys
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp
import redis.asyncio as redis
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from protections.execution_gate import get_execution_gate, reset_execution_gate

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("live_executor")


# =============================================================================
# Kraken API Client (Simplified)
# =============================================================================

class KrakenClient:
    """Simplified Kraken API client for order execution."""

    BASE_URL = "https://api.kraken.com"

    # Kraken pair mapping (our format -> Kraken format)
    PAIR_MAP = {
        "BTC/USD": "XXBTZUSD",
        "ETH/USD": "XETHZUSD",
        "BTC/EUR": "XXBTZEUR",
        "ETH/EUR": "XETHZEUR",
        "SOL/USD": "SOLUSD",
        "ADA/USD": "ADAUSD",
        "AVAX/USD": "AVAXUSD",
        "LINK/USD": "LINKUSD",
        "MATIC/USD": "MATICUSD",
        "XRP/USD": "XXRPZUSD",
    }

    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = base64.b64decode(api_secret)
        self.session: Optional[aiohttp.ClientSession] = None
        self.nonce_offset = 0

    async def connect(self):
        """Create HTTP session."""
        if not self.session:
            self.session = aiohttp.ClientSession()

    async def close(self):
        """Close HTTP session."""
        if self.session:
            await self.session.close()
            self.session = None

    def _get_nonce(self) -> str:
        """Generate unique nonce."""
        return str(int(time.time() * 1000) + self.nonce_offset)

    def _sign(self, url_path: str, data: Dict[str, Any], nonce: str) -> str:
        """Generate Kraken API signature."""
        post_data = urllib.parse.urlencode(data)
        encoded = (nonce + post_data).encode()
        message = url_path.encode() + hashlib.sha256(encoded).digest()
        signature = hmac.new(self.api_secret, message, hashlib.sha512)
        return base64.b64encode(signature.digest()).decode()

    async def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        private: bool = False,
    ) -> Dict[str, Any]:
        """Make API request."""
        if not self.session:
            await self.connect()

        url = f"{self.BASE_URL}{endpoint}"
        headers = {}

        if private:
            nonce = self._get_nonce()
            data = data or {}
            data["nonce"] = nonce
            headers["API-Key"] = self.api_key
            headers["API-Sign"] = self._sign(endpoint, data, nonce)

        try:
            if method == "GET":
                async with self.session.get(url, params=data) as resp:
                    result = await resp.json()
            else:
                async with self.session.post(url, data=data, headers=headers) as resp:
                    result = await resp.json()

            if result.get("error") and len(result["error"]) > 0:
                raise Exception(f"Kraken API error: {result['error']}")

            return result.get("result", {})

        except Exception as e:
            logger.error(f"Kraken API request failed: {e}")
            raise

    async def get_balance(self) -> Dict[str, Decimal]:
        """Get account balances."""
        result = await self._request("POST", "/0/private/Balance", private=True)
        return {k: Decimal(v) for k, v in result.items()}

    async def get_ticker(self, pair: str) -> Dict[str, Any]:
        """Get current ticker for pair."""
        kraken_pair = self.PAIR_MAP.get(pair, pair.replace("/", ""))
        result = await self._request("GET", "/0/public/Ticker", {"pair": kraken_pair})
        return result.get(kraken_pair, {})

    async def place_order(
        self,
        pair: str,
        side: str,  # "buy" or "sell"
        order_type: str,  # "market" or "limit"
        volume: Decimal,
        price: Optional[Decimal] = None,
        validate_only: bool = False,
    ) -> Dict[str, Any]:
        """
        Place an order on Kraken.

        Returns:
            Dict with 'txid' (order IDs) and 'descr' (order description)
        """
        kraken_pair = self.PAIR_MAP.get(pair, pair.replace("/", ""))

        data = {
            "pair": kraken_pair,
            "type": side.lower(),
            "ordertype": order_type.lower(),
            "volume": str(volume),
        }

        if price and order_type.lower() == "limit":
            data["price"] = str(price)

        if validate_only:
            data["validate"] = "true"

        result = await self._request("POST", "/0/private/AddOrder", data, private=True)
        return result


# =============================================================================
# Signal Consumer
# =============================================================================

@dataclass
class TradeExecution:
    """Record of a trade execution."""
    signal_id: str
    pair: str
    side: str
    size: Decimal
    price: Decimal
    order_id: Optional[str]
    status: str  # "executed", "rejected", "error"
    reason: Optional[str]
    timestamp: str
    execution_time_ms: float


class LiveExecutor:
    """
    Live execution consumer that reads signals and executes trades.
    """

    def __init__(
        self,
        pairs: List[str],
        redis_url: str,
        redis_ca_cert: Optional[str] = None,
    ):
        self.pairs = pairs
        self.redis_url = redis_url
        self.redis_ca_cert = redis_ca_cert

        self.redis_client: Optional[redis.Redis] = None
        self.kraken_client: Optional[KrakenClient] = None
        self.gate = get_execution_gate()

        # Metrics
        self.signals_received = 0
        self.trades_executed = 0
        self.trades_rejected = 0
        self.total_notional_usd = Decimal("0")

        # Risk limits from env
        self.max_position_size_usd = Decimal(os.getenv("MAX_POSITION_SIZE_USD", "25"))
        self.max_daily_loss_usd = Decimal(os.getenv("MAX_DAILY_LOSS_USD", "2"))
        self.max_trades_per_day = int(os.getenv("MAX_TRADES_PER_DAY", "8"))

    async def connect(self) -> bool:
        """Connect to Redis and Kraken."""
        try:
            # Connect to Redis
            ssl_params = {}
            if self.redis_url.startswith("rediss://"):
                ssl_params = {
                    "ssl_cert_reqs": "required",
                    "ssl_ca_certs": self.redis_ca_cert or "config/certs/redis_ca.pem",
                }

            self.redis_client = redis.from_url(
                self.redis_url,
                decode_responses=True,
                **ssl_params,
            )
            await self.redis_client.ping()
            logger.info("[OK] Redis connected")

            # Connect to Kraken
            api_key = os.getenv("KRAKEN_API_KEY", "")
            api_secret = os.getenv("KRAKEN_API_SECRET", "")

            if not api_key or not api_secret:
                logger.error("KRAKEN_API_KEY and KRAKEN_API_SECRET required")
                return False

            self.kraken_client = KrakenClient(api_key, api_secret)
            await self.kraken_client.connect()

            # Test Kraken connection with balance check
            try:
                balance = await self.kraken_client.get_balance()
                usd_balance = balance.get("ZUSD", Decimal("0"))
                logger.info(f"[OK] Kraken connected (USD balance: ${usd_balance:.2f})")
            except Exception as e:
                logger.warning(f"Kraken balance check failed (may be permissions): {e}")

            return True

        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False

    async def close(self):
        """Close connections."""
        if self.kraken_client:
            await self.kraken_client.close()
        if self.redis_client:
            await self.redis_client.close()

    def _parse_signal(self, data: Dict[str, str]) -> Dict[str, Any]:
        """Parse signal data from Redis stream."""
        return {
            "signal_id": data.get("signal_id", ""),
            "pair": data.get("pair", ""),
            "side": data.get("side", ""),  # LONG or SHORT
            "entry_price": Decimal(data.get("entry_price", "0")),
            "stop_loss": Decimal(data.get("stop_loss", "0")),
            "take_profit": Decimal(data.get("take_profit", "0")),
            "confidence": float(data.get("confidence", "0")),
            "position_size_usd": Decimal(data.get("position_size_usd", "0")),
            "strategy": data.get("strategy", ""),
            "timestamp": data.get("timestamp", ""),
        }

    async def _execute_signal(self, signal: Dict[str, Any]) -> TradeExecution:
        """Execute a single signal."""
        start_time = time.time()

        pair = signal["pair"]
        side = signal["side"]
        entry_price = signal["entry_price"]
        position_size_usd = signal["position_size_usd"]

        # Calculate order size
        if entry_price > 0:
            volume = position_size_usd / entry_price
        else:
            # Get current price
            ticker = await self.kraken_client.get_ticker(pair)
            current_price = Decimal(ticker.get("c", [0])[0])
            volume = position_size_usd / current_price if current_price > 0 else Decimal("0")
            entry_price = current_price

        # Map side: LONG -> buy, SHORT -> sell
        order_side = "buy" if side.upper() == "LONG" else "sell"

        # Check execution gate
        gate_result = self.gate.check(position_size_usd=float(position_size_usd))

        if not gate_result.allowed:
            execution_time = (time.time() - start_time) * 1000
            logger.warning(f"[REJECTED] {pair} {side}: {gate_result.reason}")
            self.trades_rejected += 1
            return TradeExecution(
                signal_id=signal["signal_id"],
                pair=pair,
                side=side,
                size=volume,
                price=entry_price,
                order_id=None,
                status="rejected",
                reason=gate_result.reason,
                timestamp=datetime.now(timezone.utc).isoformat(),
                execution_time_ms=execution_time,
            )

        # Check if shadow mode
        if gate_result.shadow_mode:
            execution_time = (time.time() - start_time) * 1000
            logger.info(f"[SHADOW] Would execute: {order_side} {volume:.8f} {pair} @ ${entry_price:.2f}")
            return TradeExecution(
                signal_id=signal["signal_id"],
                pair=pair,
                side=side,
                size=volume,
                price=entry_price,
                order_id=f"SHADOW-{int(time.time()*1000)}",
                status="shadow",
                reason="Shadow mode - order simulated",
                timestamp=datetime.now(timezone.utc).isoformat(),
                execution_time_ms=execution_time,
            )

        # Execute real order
        try:
            logger.info(f"[EXECUTE] {order_side.upper()} {volume:.8f} {pair} @ ${entry_price:.2f}")

            result = await self.kraken_client.place_order(
                pair=pair,
                side=order_side,
                order_type="market",  # Use market orders for immediate execution
                volume=volume,
            )

            order_ids = result.get("txid", [])
            order_id = order_ids[0] if order_ids else None

            execution_time = (time.time() - start_time) * 1000

            logger.info(f"[FILLED] Order {order_id} executed in {execution_time:.1f}ms")

            self.trades_executed += 1
            self.total_notional_usd += position_size_usd

            return TradeExecution(
                signal_id=signal["signal_id"],
                pair=pair,
                side=side,
                size=volume,
                price=entry_price,
                order_id=order_id,
                status="executed",
                reason=None,
                timestamp=datetime.now(timezone.utc).isoformat(),
                execution_time_ms=execution_time,
            )

        except Exception as e:
            execution_time = (time.time() - start_time) * 1000
            logger.error(f"[ERROR] Order failed: {e}")

            return TradeExecution(
                signal_id=signal["signal_id"],
                pair=pair,
                side=side,
                size=volume,
                price=entry_price,
                order_id=None,
                status="error",
                reason=str(e),
                timestamp=datetime.now(timezone.utc).isoformat(),
                execution_time_ms=execution_time,
            )

    async def _publish_execution(self, execution: TradeExecution):
        """Publish execution result to Redis."""
        try:
            data = {
                "signal_id": execution.signal_id,
                "pair": execution.pair,
                "side": execution.side,
                "size": str(execution.size),
                "price": str(execution.price),
                "order_id": execution.order_id or "",
                "status": execution.status,
                "reason": execution.reason or "",
                "timestamp": execution.timestamp,
                "execution_time_ms": str(execution.execution_time_ms),
            }

            stream = "orders:live" if execution.status == "executed" else "orders:rejected"
            await self.redis_client.xadd(stream, data, maxlen=10000)

        except Exception as e:
            logger.error(f"Failed to publish execution: {e}")

    async def run(self):
        """Main execution loop."""
        consumer_group = "live_executor_group"
        consumer_name = "executor-1"

        # Build stream list
        streams = {f"signals:live:{pair.replace('/', '-')}": ">" for pair in self.pairs}

        # Create consumer groups
        for stream in streams.keys():
            try:
                await self.redis_client.xgroup_create(stream, consumer_group, id="0", mkstream=True)
                logger.info(f"Created consumer group for {stream}")
            except redis.ResponseError as e:
                if "BUSYGROUP" in str(e):
                    pass  # Group already exists
                else:
                    logger.warning(f"Consumer group error for {stream}: {e}")

        logger.info(f"Consuming from: {list(streams.keys())}")
        logger.info(f"Risk limits: max_position=${self.max_position_size_usd}, max_trades={self.max_trades_per_day}")
        logger.info("Waiting for signals...")

        while True:
            try:
                # Check if we've hit daily trade limit
                if self.trades_executed >= self.max_trades_per_day:
                    logger.warning(f"Daily trade limit reached ({self.max_trades_per_day})")
                    await asyncio.sleep(60)
                    continue

                # Read signals from all streams
                messages = await self.redis_client.xreadgroup(
                    consumer_group,
                    consumer_name,
                    streams,
                    count=1,
                    block=1000,
                )

                if not messages:
                    continue

                for stream_name, stream_messages in messages:
                    for message_id, fields in stream_messages:
                        self.signals_received += 1

                        # Parse signal
                        signal = self._parse_signal(fields)

                        logger.info(
                            f"[SIGNAL] {signal['pair']} {signal['side']} @ ${signal['entry_price']:.2f} "
                            f"(conf={signal['confidence']:.2f}, size=${signal['position_size_usd']:.2f})"
                        )

                        # Execute
                        execution = await self._execute_signal(signal)

                        # Publish result
                        await self._publish_execution(execution)

                        # Acknowledge
                        await self.redis_client.xack(stream_name, consumer_group, message_id)

                        # Log status
                        if self.signals_received % 10 == 0:
                            logger.info(
                                f"[STATUS] Signals: {self.signals_received}, "
                                f"Executed: {self.trades_executed}, "
                                f"Rejected: {self.trades_rejected}, "
                                f"Notional: ${self.total_notional_usd:.2f}"
                            )

            except redis.ConnectionError:
                logger.error("Redis connection lost, reconnecting...")
                await asyncio.sleep(5)
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Error in execution loop: {e}")
                await asyncio.sleep(1)


# =============================================================================
# Main
# =============================================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description="Live Execution Consumer - Executes signals on Kraken",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--pairs",
        type=str,
        default=os.getenv("TRADING_PAIRS", "BTC/USD,ETH/USD"),
        help="Comma-separated trading pairs",
    )

    parser.add_argument(
        "--env-file",
        type=Path,
        default=project_root / ".env",
        help="Environment file (default: .env)",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate configuration only, don't execute",
    )

    return parser.parse_args()


async def main():
    args = parse_args()

    # Load environment
    if args.env_file.exists():
        load_dotenv(args.env_file)
        logger.info(f"Loaded environment from: {args.env_file}")

    # Reset and get execution gate
    reset_execution_gate()
    gate = get_execution_gate()

    # Preflight checks
    print("\n" + "=" * 70)
    print("LIVE EXECUTION CONSUMER - PREFLIGHT CHECK")
    print("=" * 70)

    # Check critical settings
    checks = []

    live_enabled = os.getenv("LIVE_TRADING_ENABLED", "").lower() == "true"
    checks.append(("LIVE_TRADING_ENABLED", live_enabled, "true" if live_enabled else "false"))

    engine_mode = os.getenv("ENGINE_MODE", "paper")
    checks.append(("ENGINE_MODE", engine_mode == "live", engine_mode))

    confirmation = os.getenv("LIVE_TRADING_CONFIRMATION", "")
    checks.append(("LIVE_TRADING_CONFIRMATION", confirmation == "I-accept-the-risk", "set" if confirmation else "NOT SET"))

    shadow = os.getenv("SHADOW_EXECUTION", "").lower() == "true"
    checks.append(("SHADOW_EXECUTION", True, "true" if shadow else "false"))

    emergency = os.getenv("EMERGENCY_STOP", "").lower() == "true"
    checks.append(("EMERGENCY_STOP", not emergency, "false" if not emergency else "TRUE - BLOCKED"))

    api_key = os.getenv("KRAKEN_API_KEY", "")
    checks.append(("KRAKEN_API_KEY", bool(api_key), "set" if api_key else "NOT SET"))

    api_secret = os.getenv("KRAKEN_API_SECRET", "")
    checks.append(("KRAKEN_API_SECRET", bool(api_secret), "set" if api_secret else "NOT SET"))

    redis_url = os.getenv("REDIS_URL", "")
    checks.append(("REDIS_URL", bool(redis_url), "set" if redis_url else "NOT SET"))

    print("\nConfiguration:")
    all_ok = True
    for name, ok, value in checks:
        status = "[OK]" if ok else "[FAIL]"
        print(f"  {status} {name}: {value}")
        if not ok:
            all_ok = False

    # Log gate status
    print("\nExecution Gate Status:")
    gate.log_preflight_status()

    if not all_ok:
        print("\n[ABORT] Fix configuration before starting")
        print("=" * 70)
        sys.exit(1)

    if args.dry_run:
        print("\n[DRY-RUN] Configuration valid, exiting")
        print("=" * 70)
        sys.exit(0)

    # Parse pairs
    pairs = [p.strip() for p in args.pairs.split(",")]

    print(f"\nTrading Pairs: {pairs}")
    print(f"Shadow Mode: {shadow}")
    print("=" * 70)

    if not shadow:
        print("\n*** WARNING: LIVE EXECUTION MODE ***")
        print("*** REAL ORDERS WILL BE PLACED ***")
        print("\nPress Ctrl+C within 5 seconds to abort...")
        await asyncio.sleep(5)

    print("\nStarting execution consumer...")

    # Create and run executor
    executor = LiveExecutor(
        pairs=pairs,
        redis_url=redis_url,
        redis_ca_cert=os.getenv("REDIS_CA_CERT_PATH", "config/certs/redis_ca.pem"),
    )

    if not await executor.connect():
        logger.error("Failed to connect, exiting")
        sys.exit(1)

    try:
        await executor.run()
    except KeyboardInterrupt:
        logger.info("\nShutdown requested")
    finally:
        await executor.close()
        logger.info("Executor stopped")

        # Final stats
        print("\n" + "=" * 70)
        print("EXECUTION SUMMARY")
        print("=" * 70)
        print(f"Signals received: {executor.signals_received}")
        print(f"Trades executed: {executor.trades_executed}")
        print(f"Trades rejected: {executor.trades_rejected}")
        print(f"Total notional: ${executor.total_notional_usd:.2f}")
        print("=" * 70)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown complete")
        sys.exit(0)
