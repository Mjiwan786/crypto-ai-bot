import yaml
import ccxt
import pandas as pd

from strategies.trend_following import TrendFollowingStrategy
from strategies.breakout import BreakoutStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.momentum import MomentumStrategy
from strategies.sideways import SidewaysStrategy
from strategies.moving_average import MovingAverageStrategy

def fetch_data(symbol="ETH/USD", timeframe="1h", limit=100):
    exchange = ccxt.kraken()
    bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"])
    return df

def load_strategy_settings():
    with open("config/settings.yaml") as f:
        config = yaml.safe_load(f)
    return config["strategies"]

def run_all_strategies(df):
    settings = load_strategy_settings()
    strategies = {
        "Trend Following": TrendFollowingStrategy(settings.get("trend_following", {})),
        "Breakout": BreakoutStrategy(settings.get("breakout", {})),
        "Mean Reversion": MeanReversionStrategy(settings.get("mean_reversion", {})),
        "Momentum": MomentumStrategy(settings.get("momentum", {})),
        "Sideways": SidewaysStrategy(settings.get("sideways", {})),
        "Moving Average": MovingAverageStrategy(settings.get("moving_average", {}))
    }

    for name, strat in strategies.items():
        try:
            result = strat.generate_signal(df)
            print(f"\n🧠 {name} Strategy Result:\n{result}")
        except Exception as e:
            print(f"\n❌ Error in {name}: {e}")

if __name__ == "__main__":
    df = fetch_data()
    run_all_strategies(df)
