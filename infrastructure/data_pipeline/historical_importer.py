"""
Historical data importer utilising ccxt.

This class fetches OHLCV (open, high, low, close, volume) data from a
supported exchange using the ccxt library and returns it as a Pandas
DataFrame.  The timestamps are normalised to UTC.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

try:
    import ccxt  # type: ignore
except ImportError:  # pragma: no cover
    ccxt = None  # type: ignore
import pandas as pd


class HistoricalImporter:
    """Fetch historical OHLCV data using ccxt."""

    def __init__(self, exchange_name: str) -> None:
        self.exchange_name = exchange_name.lower()
        if ccxt is None:
            raise RuntimeError("ccxt package is required for HistoricalImporter")
        try:
            exchange_class = getattr(ccxt, self.exchange_name)
        except AttributeError as exc:
            raise ValueError(f"Unsupported exchange: {exchange_name}") from exc
        self.exchange = exchange_class()
        # set rate limit enforcement to True
        self.exchange.enableRateLimit = True

    def fetch_ohlcv(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> pd.DataFrame:
        """
        Retrieve OHLCV rows between start and end datetimes.

        ccxt returns lists of [timestamp, open, high, low, close, volume].
        We convert them to a DataFrame with datetime index.
        """
        since = int(start.timestamp() * 1000)
        end_ts = int(end.timestamp() * 1000)
        ohlcv: List[List[Any]] = []
        while since < end_ts:
            batch = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=1000)
            if not batch:
                break
            ohlcv.extend(batch)
            # ccxt returns inclusive end, so increment
            since = batch[-1][0] + 1
            # break if next since is beyond requested end
            if since > end_ts:
                break
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)
        # Drop any rows beyond the desired end timestamp
        df = df[(df.index >= start) & (df.index <= end)]
        return df