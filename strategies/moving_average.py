import pandas as pd
import talib
from config.config_loader import load_settings


class MovingAverageStrategy:
    def __init__(self):
        config = load_settings()
        self.settings = getattr(getattr(config, "strategies", {}), "moving_average", {})
        self.sma_short = self.settings.get("sma_short", 10)
        self.sma_long = self.settings.get("sma_long", 50)
        self.rsi_period = self.settings.get("rsi_period", 14)
        self.rsi_threshold = self.settings.get("rsi_trend_confirm", 50)
        self.volume_ratio = self.settings.get("volume_ratio", 1.2)

    def generate_signal(self, df: pd.DataFrame) -> dict:
        if df.empty or len(df) < max(self.sma_long, self.rsi_period):
            return {"signal": None, "reason": "insufficient data"}

        df["SMA_short"] = talib.SMA(df["close"], timeperiod=self.sma_short)
        df["SMA_long"] = talib.SMA(df["close"], timeperiod=self.sma_long)
        df["RSI"] = talib.RSI(df["close"], timeperiod=self.rsi_period)
        df["volume_avg"] = df["volume"].rolling(window=self.sma_short).mean()

        last = df.iloc[-1]
        prev = df.iloc[-2]

        crossover_up = prev["SMA_short"] < prev["SMA_long"] and last["SMA_short"] > last["SMA_long"]
        rsi_ok = last["RSI"] > self.rsi_threshold
        volume_ok = last["volume"] > last["volume_avg"] * self.volume_ratio

        if crossover_up and rsi_ok and volume_ok:
            return {
                "signal": "buy",
                "confidence": 0.7,
                "entry_price": last["close"],
                "reason": "SMA crossover + RSI trend + volume confirmation"
            }

        return {"signal": None, "reason": "No crossover or weak trend detected"}


if __name__ == "__main__":
    import ccxt

    exchange = ccxt.kraken()
    bars = exchange.fetch_ohlcv("ETH/USD", timeframe="1h", limit=100)
    df = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"])

    strategy = MovingAverageStrategy()
    signal = strategy.generate_signal(df)
    print(signal)
