import pandas as pd
import talib
from config.config_loader import load_settings


class TrendFollowingStrategy:
    def __init__(self):
        config = load_settings()
        self.settings = getattr(getattr(config, "strategies", {}), "trend_following", {})
        self.ema_short = self.settings.get("ema_short", 9)
        self.ema_long = self.settings.get("ema_long", 21)
        self.atr_period = self.settings.get("atr_period", 14)
        self.min_trend_strength = self.settings.get("min_trend_strength", 0.3)
        self.confirmation_bars = self.settings.get("entry_conditions", {}).get("confirmation_bars", 2)
        self.volume_ratio = self.settings.get("entry_conditions", {}).get("volume_ratio", 1.2)

    def generate_signal(self, df: pd.DataFrame) -> dict:
        if df.empty or len(df) < max(self.ema_long, self.atr_period + self.confirmation_bars):
            return {"signal": None, "reason": "insufficient data"}

        df["EMA_short"] = talib.EMA(df["close"], timeperiod=self.ema_short)
        df["EMA_long"] = talib.EMA(df["close"], timeperiod=self.ema_long)
        df["ATR"] = talib.ATR(df["high"], df["low"], df["close"], timeperiod=self.atr_period)
        df["Volume_MA"] = df["volume"].rolling(window=self.ema_short).mean()

        last = df.iloc[-1]
        prev = df.iloc[-2]

        trend_confirmed = prev["EMA_short"] < prev["EMA_long"] and last["EMA_short"] > last["EMA_long"]
        trend_strength = last["ATR"] / last["close"]
        volume_ok = last["volume"] > last["Volume_MA"] * self.volume_ratio

        if trend_confirmed and trend_strength > self.min_trend_strength and volume_ok:
            return {
                "signal": "buy",
                "confidence": 0.8,
                "entry_price": last["close"],
                "reason": "EMA crossover + ATR + volume confirmed"
            }

        return {"signal": None, "reason": "trend criteria not met"}


if __name__ == "__main__":
    import ccxt

    exchange = ccxt.kraken()
    bars = exchange.fetch_ohlcv("ETH/USD", timeframe="1h", limit=100)
    df = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"])

    strategy = TrendFollowingStrategy()
    signal = strategy.generate_signal(df)
    print(signal)
