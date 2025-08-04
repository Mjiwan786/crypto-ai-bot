# Technical analysis for regime detection.

def analyse_prices(prices: list[float]) -> dict:
    """Analyse a sequence of prices and return technical indicators.

    Args:
        prices: A list of historical prices.

    Returns:
        A dictionary of dummy technical indicator values.
    """
    # TODO: compute real indicators such as RSI, MACD, Bollinger Bands
    return {"rsi": 50, "macd": 0, "bollinger": (0, 0)}