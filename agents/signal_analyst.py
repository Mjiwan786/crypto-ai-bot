# agents/core/signal_analyst.py

import talib
import numpy as np

def generate_signal(prices):
    """
    Generates a trading signal using basic RSI and MACD.
    Input: prices - list or array of recent price floats
    Output: "BUY", "SELL", or "HOLD"
    """
    prices = np.array(prices, dtype='float64')

    if len(prices) < 35:  # Ensure enough data
        return "HOLD"

    rsi = talib.RSI(prices, timeperiod=14)
    macd, signal, hist = talib.MACD(prices)

    if rsi[-1] < 30 and macd[-1] > signal[-1]:
        return "BUY"
    elif rsi[-1] > 70 and macd[-1] < signal[-1]:
        return "SELL"
    return "HOLD"
