import pandas as pd
import numpy as np
from config.config_loader import load_settings


class BreakoutStrategy:
    def __init__(self):
        config = load_settings()
        self.settings = getattr(getattr(config, "strategies", {}), "breakout", {})
        self.resistance_window = self.settings.get("resistance_window", 20)
        self.min_breakout_ratio = self.settings.get("min_breakout_ratio", 1.5)
        self.retest_allowed = self.settings.get("retest_allowed", True)
        self.false_breakout_filter = self.settings.get("false_breakout_filter", True)
        self.volume_requirement = self.settings.get("volume_requirement", 1.5)

    def generate_signal(self, df: pd.DataFrame) -> dict:
        if df.empty or len(df) < self.resistance_window:
            return {"signal": None, "reason": "insufficient data"}

        recent_highs = df["high"].rolling(window=self.resistance_window).max()
        df["resistance"] = recent_highs
        last = df.iloc[-1]
        prev = df.iloc[-2]

        breakout = prev["close"] <= prev["resistance"] and last["close"] > last["resistance"]
        strong_breakout = last["close"] / last["resistance"] > self.min_breakout_ratio
        volume_ok = last["volume"] > df["volume"].rolling(window=self.resistance_window).mean().iloc[-1] * self.volume_requirement

        if breakout and strong_breakout and volume_ok:
            return {
                "signal": "buy",
                "confidence": 0.75,
                "entry_price": last["close"],
                "reason": "Breakout above resistance with volume"
            }

        return {"signal": None, "reason": "no breakout confirmed"}


if __name__ == "__main__":
    import ccxt

    exchange = ccxt.kraken()
    bars = exchange.fetch_ohlcv("ETH/USD", timeframe="1h", limit=100)
    df = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"])

    strategy = BreakoutStrategy()
    signal = strategy.generate_signal(df)
    print(signal)
