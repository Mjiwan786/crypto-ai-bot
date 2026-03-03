import json
import logging
import os

import pandas as pd
import requests

from mcp.schemas import SignalScore, MarketContext
from mcp.redis_manager import RedisManager
from exchange.exchange_factory import ExchangeFactory

logger = logging.getLogger(__name__)

COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"
COINMARKETCAP_KEY = os.getenv("COINMARKETCAP_API_KEY")
CRYPTOCOMPARE_KEY = os.getenv("CRYPTOCOMPARE_API_KEY")

# USDT exchanges — pairs are converted from BTC/USD -> BTC/USDT
_USDT_EXCHANGES = frozenset({"binance", "bybit", "okx", "kucoin", "gateio"})


class SignalAnalyst:
    """Exchange-agnostic signal analyst.

    Uses the exchange adapter layer instead of hardcoded CCXT instances.
    Fetches OHLCV from a primary exchange and an optional secondary
    exchange for cross-validation.

    Args:
        exchange_id: Primary exchange to fetch data from (default: kraken).
        secondary_exchange_id: Optional secondary exchange for cross-validation.
        symbols: Trading pairs to analyse.
    """

    def __init__(
        self,
        exchange_id: str = "kraken",
        secondary_exchange_id: str | None = "kucoin",
        symbols: list[str] | None = None,
    ):
        self.exchange_id = exchange_id
        self.secondary_exchange_id = secondary_exchange_id
        self.primary = ExchangeFactory.create_public(exchange_id)
        self.secondary = (
            ExchangeFactory.create_public(secondary_exchange_id)
            if secondary_exchange_id
            else None
        )
        self.symbols = symbols or ["BTC/USD", "ETH/USD", "SOL/USD"]
        self.redis = RedisManager().connect()
        self.timeframe = "1h"
        self.lookback = 50

    def _map_pair(self, symbol: str, exchange_id: str) -> str:
        """Map USD pairs to USDT for exchanges that require it."""
        if exchange_id in _USDT_EXCHANGES:
            return symbol.replace("/USD", "/USDT")
        return symbol

    def fetch_ohlcv(self, exchange, symbol: str) -> pd.DataFrame:
        try:
            df = exchange.fetch_ohlcv(
                symbol, timeframe=self.timeframe, limit=self.lookback
            )
            df = pd.DataFrame(
                df, columns=["timestamp", "open", "high", "low", "close", "volume"]
            )
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            return df
        except Exception as e:
            ex_id = getattr(exchange, "id", getattr(exchange, "exchange_id", "unknown"))
            logger.warning("Failed to fetch OHLCV for %s from %s: %s", symbol, ex_id, e)
            return pd.DataFrame()

    def get_sentiment_score(self, symbol: str) -> float:
        try:
            base = symbol.split("/")[0]
            headers = {"X-CMC_PRO_API_KEY": COINMARKETCAP_KEY}
            cmc_resp = requests.get(
                f"https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest?symbol={base}",
                headers=headers,
                timeout=10,
            )
            cmc_score = cmc_resp.json()["data"][base]["quote"]["USD"]["percent_change_24h"]

            cg_resp = requests.get(
                f"{COINGECKO_BASE_URL}/coins/markets",
                params={"vs_currency": "usd", "ids": base.lower()},
                timeout=10,
            )
            cg_score = cg_resp.json()[0]["price_change_percentage_24h"]

            final_score = (cg_score + cmc_score) / 2
            return round(final_score, 2)
        except Exception as e:
            logger.warning("Sentiment score error for %s: %s", symbol, e)
            return 0.0

    def compute_signal_strength(self, df: pd.DataFrame) -> float:
        if df.empty:
            return 0.0
        price_change = df["close"].iloc[-1] / df["close"].iloc[0] - 1
        volume_ratio = df["volume"].iloc[-1] / df["volume"].mean()
        strength = (price_change * 100) * 0.6 + min(volume_ratio, 2.0) * 20
        return round(strength, 2)

    def analyze(self) -> list[SignalScore]:
        logger.info("Analyzing signals on %s...", self.exchange_id)
        signal_scores = []
        for symbol in self.symbols:
            primary_pair = self._map_pair(symbol, self.exchange_id)
            df_primary = self.fetch_ohlcv(self.primary, primary_pair)

            if self.secondary and self.secondary_exchange_id:
                secondary_pair = self._map_pair(symbol, self.secondary_exchange_id)
                df_secondary = self.fetch_ohlcv(self.secondary, secondary_pair)
                df_combined = (
                    pd.concat([df_primary, df_secondary])
                    .drop_duplicates()
                    .sort_values(by="timestamp")
                )
                df_combined.reset_index(drop=True, inplace=True)
            else:
                df_combined = df_primary

            tech_score = self.compute_signal_strength(df_combined)
            sentiment_score = self.get_sentiment_score(symbol)
            total_score = tech_score * 0.7 + sentiment_score * 0.3

            signal_scores.append(
                SignalScore(
                    symbol=symbol,
                    technical_score=tech_score,
                    sentiment_score=sentiment_score,
                    total_score=round(total_score, 2),
                )
            )

        self.redis.set(
            "mcp:signal_scores",
            json.dumps([s.model_dump() for s in signal_scores]),
        )
        logger.info("Signal scores pushed to Redis.")
        return signal_scores


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sa = SignalAnalyst(exchange_id="kraken", secondary_exchange_id="kucoin")
    scores = sa.analyze()
    for s in scores:
        print(
            f"{s.symbol}: total={s.total_score}, "
            f"tech={s.technical_score}, sentiment={s.sentiment_score}"
        )
