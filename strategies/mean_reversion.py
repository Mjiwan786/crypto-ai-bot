import pandas as pd
import talib
from config.config_loader import load_settings


class MeanReversionStrategy:
    def __init__(self):
        config = load_settings()
        self.settings = getattr(getattr(config, "strategies", {}), "mean_reversion", {})
        self.boll_window = self.settings.get("bollinger_window", 20)
        self.std_dev = self.settings.get("std_dev", 2.0)
        self.oversold = self.settings.get("entry_zones", {}).get("oversold", 0.3)
        self.overbought = self.settings.get("entry_zones", {}).get("overbought", 0.7)
        self.exit_at_mean = self.settings.get("exit_at_mean", True)

    def generate_signal(self, df: pd.DataFrame) -> dict:
        if df.empty or len(df) < self.boll_window:
            return {"signal": None, "reason": "insufficient data"}

        upper, middle, lower = talib.BBANDS(df["close"], timeperiod=self.boll_window, nbdevup=self.std_dev, nbdevdn=self.std_dev)
        df["upper"] = upper
        df["lower"] = lower
        df["middle"] = middle

        last = df.iloc[-1]
        if last["close"] < last["lower"]:
            return {
                "signal": "buy",
                "confidence": 0.65,
                "entry_price": last["close"],
                "reason": "price below lower Bollinger Band"
            }
        elif last["close"] > last["upper"]:
            return {
                "signal": "sell",
                "confidence": 0.65,
                "entry_price": last["close"],
                "reason": "price above upper Bollinger Band"
            }

        return {"signal": None, "reason": "within Bollinger Band"}


if __name__ == "__main__":
    import ccxt

    exchange = ccxt.kraken()
    bars = exchange.fetch_ohlcv("ETH/USD", timeframe="1h", limit=100)
    df = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"])

    strategy = MeanReversionStrategy()
    signal = strategy.generate_signal(df)
    print(signal)
