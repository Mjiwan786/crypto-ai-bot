import pandas as pd
import talib
from config.config_loader import load_settings


class MomentumStrategy:
    def __init__(self):
        config = load_settings()
        self.settings = getattr(getattr(config, "strategies", {}), "momentum", {})
        self.rsi_period = self.settings.get("rsi_period", 14)
        self.vwap_window = self.settings.get("vwap_window", 20)
        self.rsi_oversold = self.settings.get("entry_signals", {}).get("rsi_oversold", 30)
        self.rsi_overbought = self.settings.get("entry_signals", {}).get("rsi_overbought", 70)
        self.vwap_gap = self.settings.get("entry_signals", {}).get("vwap_gap", 0.015)
        self.exit_after_bars = self.settings.get("exit_after_bars", 6)

    def generate_signal(self, df: pd.DataFrame) -> dict:
        if df.empty or len(df) < max(self.rsi_period, self.vwap_window):
            return {"signal": None, "reason": "insufficient data"}

        df["RSI"] = talib.RSI(df["close"], timeperiod=self.rsi_period)
        df["VWAP"] = (df["close"] * df["volume"]).rolling(window=self.vwap_window).sum() / df["volume"].rolling(window=self.vwap_window).sum()

        last = df.iloc[-1]
        rsi_ok = last["RSI"] < self.rsi_oversold or last["RSI"] > self.rsi_overbought
        vwap_ok = abs(last["close"] - last["VWAP"]) / last["VWAP"] > self.vwap_gap

        if rsi_ok and vwap_ok:
            direction = "buy" if last["RSI"] < self.rsi_oversold else "sell"
            return {
                "signal": direction,
                "confidence": 0.7,
                "entry_price": last["close"],
                "reason": "RSI and VWAP gap aligned"
            }

        return {"signal": None, "reason": "RSI/VWAP thresholds not met"}


if __name__ == "__main__":
    import ccxt

    exchange = ccxt.kraken()
    bars = exchange.fetch_ohlcv("ETH/USD", timeframe="1h", limit=100)
    df = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"])

    strategy = MomentumStrategy()
    signal = strategy.generate_signal(df)
    print(signal)
