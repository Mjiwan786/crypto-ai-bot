import asyncio
import json
import logging
import os

from mcp.redis_manager import RedisManager
from mcp.schemas import SignalScore
from config.config_loader import load_settings
from exchange.exchange_factory import ExchangeFactory
from exchange.rate_limiter import ExchangeRateLimiter

logger = logging.getLogger(__name__)


class ExecutionAgent:
    """Exchange-agnostic execution agent.

    Uses the exchange adapter layer instead of a hardcoded CCXT instance.

    Args:
        exchange_id: Exchange to execute trades on (default: kraken).
    """

    def __init__(self, exchange_id: str = "kraken"):
        self.exchange_id = exchange_id
        api_key = os.getenv(f"{exchange_id.upper()}_API_KEY", "")
        secret = os.getenv(f"{exchange_id.upper()}_API_SECRET", "")
        passphrase = os.getenv(f"{exchange_id.upper()}_PASSPHRASE", "")

        self.adapter = ExchangeFactory.create(
            exchange_id=exchange_id,
            api_key=api_key,
            secret=secret,
            passphrase=passphrase,
            sandbox=True,
        )
        self.redis = RedisManager().connect()
        self.settings = load_settings().get("trading", {})
        self.base_position_size = self.settings.get("base_position_size", 0.15)
        self.vol_multiplier = (
            self.settings.get("dynamic_sizing", {}).get("volatility_multiplier", 1.0)
        )
        self.max_position = (
            self.settings.get("dynamic_sizing", {}).get("max_position", 0.3)
        )
        self.min_confidence = (
            self.settings.get("entry_conditions", {}).get("min_confidence", 0.75)
        )
        self._rate_limiter = ExchangeRateLimiter()

    def fetch_signals(self) -> list[SignalScore]:
        raw = self.redis.get("mcp:signal_scores")
        if not raw:
            logger.warning("No signals found.")
            return []
        try:
            data = json.loads(raw)
            return [
                SignalScore(**d)
                for d in data
                if d["total_score"] >= self.min_confidence * 100
            ]
        except Exception as e:
            logger.error("Failed to parse signal data: %s", e)
            return []

    def get_balance(self, currency: str = "USD") -> float:
        try:
            balance = self.adapter.fetch_balance()
            return balance[currency]["free"]
        except Exception as e:
            logger.error("Balance fetch error on %s: %s", self.exchange_id, e)
            return 0

    def execute_trade(self, symbol: str, score: float) -> None:
        # Rate limit gate — prevent REST API exhaustion
        if not asyncio.get_event_loop().run_until_complete(
            self._rate_limiter.acquire(self.exchange_id)
        ):
            logger.warning(
                "Rate limit budget exhausted for %s, skipping %s",
                self.exchange_id, symbol,
            )
            return

        quote_currency = symbol.split("/")[1]
        balance = self.get_balance(quote_currency)
        position_size = min(
            balance * self.base_position_size * self.vol_multiplier,
            balance * self.max_position,
        )

        try:
            price = self.adapter.fetch_ticker(symbol)["ask"]
            amount = position_size / price
            self.adapter.create_market_buy_order(symbol, amount)
            logger.info(
                "Executed BUY on %s (%s): %.4f at $%s",
                symbol, self.exchange_id, amount, price,
            )
        except Exception as e:
            logger.error("Execution failed for %s on %s: %s", symbol, self.exchange_id, e)

    def run(self) -> None:
        logger.info("Execution agent running on %s...", self.exchange_id)
        signals = self.fetch_signals()
        for signal in signals:
            logger.info("Evaluating %s: score=%s", signal.symbol, signal.total_score)
            self.execute_trade(signal.symbol, signal.total_score)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    agent = ExecutionAgent(exchange_id="kraken")
    agent.run()
