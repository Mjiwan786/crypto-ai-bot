import ccxt
import pandas as pd
import requests
import redis
import os
from datetime import datetime
from mcp.schemas import SignalScore, MarketContext
from mcp.redis_manager import RedisManager

COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"
COINMARKETCAP_KEY = os.getenv("COINMARKETCAP_API_KEY")
CRYPTOCOMPARE_KEY = os.getenv("CRYPTOCOMPARE_API_KEY")


class SignalAnalyst:
    def __init__(self, symbols=None):
        self.kraken = ccxt.kraken()
        self.kucoin = ccxt.kucoin()
        self.symbols = symbols if symbols else ['BTC/USD', 'ETH/USD', 'SOL/USD']
        self.redis = RedisManager().connect()
        self.timeframe = '1h'
        self.lookback = 50

    def fetch_ohlcv(self, exchange, symbol):
        try:
            df = exchange.fetch_ohlcv(symbol, timeframe=self.timeframe, limit=self.lookback)
            df = pd.DataFrame(df, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            print(f"[❌] Failed to fetch OHLCV for {symbol} from {exchange.id}: {e}")
            return pd.DataFrame()

    def get_sentiment_score(self, symbol):
        try:
            headers = {"X-CMC_PRO_API_KEY": COINMARKETCAP_KEY}
            cmc_resp = requests.get(f"https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest?symbol={symbol.split('/')[0]}", headers=headers)
            cmc_score = cmc_resp.json()['data'][symbol.split('/')[0]]['quote']['USD']['percent_change_24h']

            cg_resp = requests.get(f"{COINGECKO_BASE_URL}/coins/markets", params={"vs_currency": "usd", "ids": symbol.split('/')[0].lower()})
            cg_score = cg_resp.json()[0]['price_change_percentage_24h']

            cc_resp = requests.get(f"https://min-api.cryptocompare.com/data/social/coin/latest?coinId=1182&api_key={CRYPTOCOMPARE_KEY}")
            cc_score = cc_resp.json()['Data']['Twitter']['followers']

            # Normalize the scores
            final_score = (cg_score + cmc_score) / 2
            return round(final_score, 2)
        except Exception as e:
            print(f"[⚠️] Sentiment score error for {symbol}: {e}")
            return 0.0

    def compute_signal_strength(self, df):
        if df.empty:
            return 0.0
        price_change = df['close'].iloc[-1] / df['close'].iloc[0] - 1
        volume_ratio = df['volume'].iloc[-1] / df['volume'].mean()
        strength = (price_change * 100) * 0.6 + min(volume_ratio, 2.0) * 20
        return round(strength, 2)

    def analyze(self):
        print("[📡] Analyzing signals...")
        signal_scores = []
        for symbol in self.symbols:
            df_k = self.fetch_ohlcv(self.kraken, symbol)
            df_kc = self.fetch_ohlcv(self.kucoin, symbol.replace("USD", "USDT"))

            df_combined = pd.concat([df_k, df_kc]).drop_duplicates().sort_values(by='timestamp')
            df_combined.reset_index(drop=True, inplace=True)

            tech_score = self.compute_signal_strength(df_combined)
            sentiment_score = self.get_sentiment_score(symbol)
            total_score = tech_score * 0.7 + sentiment_score * 0.3

            signal_scores.append(SignalScore(
                symbol=symbol,
                technical_score=tech_score,
                sentiment_score=sentiment_score,
                total_score=round(total_score, 2)
            ))

        self.redis.set("mcp:signal_scores", json.dumps([s.model_dump() for s in signal_scores]))
        print("[✅] Signal scores pushed to Redis.")
        return signal_scores


if __name__ == "__main__":
    sa = SignalAnalyst()
    scores = sa.analyze()
    for s in scores:
        print(f"{s.symbol}: total={s.total_score}, tech={s.technical_score}, sentiment={s.sentiment_score}")
