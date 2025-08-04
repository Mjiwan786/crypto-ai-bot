import ccxt
import pandas as pd
import time
import redis
import json
from datetime import datetime
from mcp.schemas import MarketContext
from mcp.redis_manager import RedisManager


class MarketScanner:
    def __init__(self, symbols=None):
        self.exchange = ccxt.kraken()
        self.timeframe = '1h'
        self.lookback = 50
        self.symbols = symbols if symbols else ['BTC/USD', 'ETH/USD', 'SOL/USD']
        self.redis = RedisManager().connect()

    def fetch_ohlcv(self, symbol: str) -> pd.DataFrame:
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=self.timeframe, limit=self.lookback)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            print(f"[❌] Failed to fetch OHLCV for {symbol}: {e}")
            return pd.DataFrame()

    def score_symbol(self, df: pd.DataFrame) -> float:
        if df.empty or len(df) < 2:
            return 0.0

        latest_volume = df['volume'].iloc[-1]
        avg_volume = df['volume'].mean()
        price_change = df['close'].iloc[-1] / df['close'].iloc[0] - 1
        volatility = (df['high'] - df['low']).mean() / df['close'].mean()

        volume_score = min(latest_volume / avg_volume, 2.0)
        momentum_score = max(min(price_change * 100, 10), -10)
        volatility_score = max(min(volatility * 100, 5), 0)

        score = volume_score * 0.4 + momentum_score * 0.4 + volatility_score * 0.2
        return round(score, 3)

    def publish_to_redis(self, market_scores):
        context = MarketContext(
            timestamp=datetime.utcnow().isoformat(),
            market_opportunities=market_scores
        )
        self.redis.set("mcp:market_context", context.model_dump_json())
        print("[✅] MarketContext pushed to Redis")

    def scan(self):
        print("[📡] Scanning market...")
        scores = []
        for symbol in self.symbols:
            df = self.fetch_ohlcv(symbol)
            score = self.score_symbol(df)
            scores.append({'symbol': symbol, 'score': score})
            time.sleep(self.exchange.rateLimit / 1000)
        ranked = sorted(scores, key=lambda x: x['score'], reverse=True)
        self.publish_to_redis(ranked)
        return ranked


if __name__ == "__main__":
    scanner = MarketScanner()
    results = scanner.scan()
    print("Top Ranked Pairs:")
    for r in results:
        print(f"{r['symbol']}: {r['score']}")
