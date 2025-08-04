import pandas as pd
from config.config_loader import load_settings


class SidewaysStrategy:
    def __init__(self):
        config = load_settings()
        self.settings = getattr(getattr(config, "strategies", {}), "sideways", {})
        self.grid_size = self.settings.get("grid_size", 0.005)
        self.max_grid_levels = self.settings.get("max_grid_levels", 10)
        self.position_size = self.settings.get("position_size", 0.05)
        self.volatility_cutoff = self.settings.get("volatility_cutoff", 0.01)

    def generate_signal(self, df: pd.DataFrame) -> dict:
        if df.empty or len(df) < 20:
            return {"signal": None, "reason": "insufficient data"}

        recent_range = df["high"].rolling(window=20).max() - df["low"].rolling(window=20).min()
        current_volatility = recent_range.iloc[-1] / df["close"].iloc[-1]

        if current_volatility > self.volatility_cutoff:
            return {"signal": None, "reason": "market too volatile for grid"}

        last_close = df["close"].iloc[-1]
        middle_price = (df["high"].rolling(window=20).max().iloc[-1] + df["low"].rolling(window=20).min().iloc[-1]) / 2
        distance = (last_close - middle_price) / middle_price

        if abs(distance) < self.grid_size:
            return {
                "signal": "buy",
                "confidence": 0.6,
                "entry_price": last_close,
                "reason": "price near grid center"
            }

        return {"signal": None, "reason": "not within grid buy zone"}


if __name__ == "__main__":
    import ccxt

    exchange = ccxt.kraken()
    bars = exchange.fetch_ohlcv("ETH/USD", timeframe="1h", limit=100)
    df = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"])

    strategy = SidewaysStrategy()
    signal = strategy.generate_signal(df)
    print(signal)
