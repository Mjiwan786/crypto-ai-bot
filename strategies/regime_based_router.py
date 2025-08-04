import json
import pandas as pd
from mcp.redis_manager import RedisManager
from strategies.trend_following import TrendFollowingStrategy
from strategies.breakout import BreakoutStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.momentum import MomentumStrategy
from strategies.sideways import SidewaysStrategy
from strategies.moving_average import MovingAverageStrategy


class RegimeBasedRouter:
    def __init__(self):
        self.redis = RedisManager().connect()
        self.context_key = "mcp:market_context"

        self.strategies = {
            "bull": [TrendFollowingStrategy(), BreakoutStrategy()],
            "bear": [MeanReversionStrategy(), MovingAverageStrategy()],
            "sideways": [SidewaysStrategy()],
            "neutral": [MomentumStrategy(), MovingAverageStrategy()]
        }

    def fetch_regime(self):
        raw = self.redis.get(self.context_key)
        if not raw:
            return "neutral"
        try:
            context = json.loads(raw)
            return context.get("regime_state", "neutral")
        except Exception as e:
            print(f"[❌] Failed to decode market context: {e}")
            return "neutral"

    def route(self, df: pd.DataFrame):
        regime = self.fetch_regime()
        chosen_strategies = self.strategies.get(regime, [])
        print(f"[🔁] Routing regime: {regime} to {len(chosen_strategies)} strategies")

        signals = []
        for strat in chosen_strategies:
            try:
                result = strat.generate_signal(df)
                if result["signal"]:
                    signals.append(result)
            except Exception as e:
                print(f"[⚠️] Error in strategy {strat.__class__.__name__}: {e}")

        return signals


if __name__ == "__main__":
    import ccxt
    exchange = ccxt.kraken()
    bars = exchange.fetch_ohlcv("ETH/USD", timeframe="1h", limit=60)
    df = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"])

    router = RegimeBasedRouter()
    decisions = router.route(df)
    for d in decisions:
        print(d)
