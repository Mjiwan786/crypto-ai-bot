"""
Read OHLCV candles from Redis streams for signal generation.

Replaces the REST spot price polling with proper candle data.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


async def read_ohlcv_candles(
    redis_client: Any,
    exchange: str,
    pair: str,
    timeframe_s: int = 60,
    lookback: int = 50,
) -> Optional[np.ndarray]:
    """
    Read recent OHLCV candles from Redis stream.

    Tries keys in order:
      1. ohlc:{tf}:{exchange}:{pair}     (per-exchange)
      2. ohlc:{tf}:any:{pair}            (cross-exchange aggregate)
      3. {exchange}:ohlc:{tf}:{dash_pair} (legacy format)

    Returns:
        numpy array shape (N, 5) with columns [open, high, low, close, volume]
        or None if insufficient data.
    """
    dash_pair = pair.replace("/", "-")

    # Build human-readable timeframe label matching the streamer's key format.
    # MultiExchangeStreamer writes: {exchange}:ohlc:{label}:{dash_pair}
    # where label is the CCXT-style string ("15s", "1m", "5m", "1h"), NOT an integer.
    _TF_LABEL: dict = {15: "15s", 60: "1m", 300: "5m", 900: "15m", 3600: "1h"}
    tf_label = _TF_LABEL.get(timeframe_s)

    keys_to_try = [
        # Aggregator format (ohlcv_aggregator.py) — per-exchange and cross-exchange
        f"ohlc:{timeframe_s}:{exchange}:{pair}",
        f"ohlc:{timeframe_s}:any:{pair}",
    ]

    if tf_label:
        # Streamer format: {exchange}:ohlc:{label}:{dash_pair}  (e.g. kraken:ohlc:1m:BTC-USD)
        keys_to_try.append(f"{exchange}:ohlc:{tf_label}:{dash_pair}")
        # Cross-exchange aggregator with label (e.g. ohlc:1m:any:BTC-USD)
        keys_to_try.append(f"ohlc:{tf_label}:any:{dash_pair}")

    # Legacy fallback: integer-minutes format that was used before label convention
    legacy_tf = timeframe_s // 60 if timeframe_s >= 60 else timeframe_s
    keys_to_try.append(f"{exchange}:ohlc:{legacy_tf}:{dash_pair}")

    # Cross-exchange fallback: if primary exchange has no OHLCV data,
    # try other exchanges that carry the same quote currency.
    # USD pairs → coinbase, bitfinex; USDT pairs → binance, okx, bybit
    _USD_FALLBACKS = ["coinbase", "bitfinex"]
    _USDT_FALLBACKS = ["binance", "okx", "bybit"]
    is_usd = dash_pair.endswith("-USD")
    fallback_exchanges = _USD_FALLBACKS if is_usd else _USDT_FALLBACKS
    if tf_label:
        for fb_ex in fallback_exchanges:
            if fb_ex != exchange:
                keys_to_try.append(f"{fb_ex}:ohlc:{tf_label}:{dash_pair}")

    for key in keys_to_try:
        try:
            raw = await _read_stream(redis_client, key, lookback)
            if raw and len(raw) >= 20:
                arr = _parse_ohlcv(raw)
                if arr is not None and len(arr) >= 20:
                    logger.info(
                        "OHLCV read: exchange=%s pair=%s tf=%ds key=%s candles=%d",
                        exchange, pair, timeframe_s, key, len(arr),
                    )
                    return arr
        except Exception as e:
            logger.debug("OHLCV read failed key=%s: %s", key, e)
            continue

    logger.debug("No OHLCV data for %s:%s tf=%ds (tried %d keys)", exchange, pair, timeframe_s, len(keys_to_try))
    return None


async def _read_stream(
    redis_client: Any, key: str, count: int
) -> List[Tuple[str, Dict[str, str]]]:
    """Read last N entries from a Redis stream via XREVRANGE."""
    try:
        client = redis_client.client
        entries = await client.xrevrange(key, count=count)
        if entries:
            entries.reverse()  # chronological order
        return entries or []
    except Exception:
        # Try sync fallback
        try:
            client = redis_client.client
            entries = client.xrevrange(key, count=count)
            if entries:
                entries.reverse()
            return entries or []
        except Exception:
            return []


def _parse_ohlcv(
    entries: List[Tuple[str, Dict[str, str]]]
) -> Optional[np.ndarray]:
    """Parse Redis stream entries into numpy OHLCV array."""
    rows = []
    for _entry_id, fields in entries:
        try:
            # Handle both string and bytes keys
            def get(k: str) -> float:
                v = fields.get(k) or fields.get(k.encode())
                if v is None:
                    return 0.0
                if isinstance(v, bytes):
                    v = v.decode()
                return float(v)

            o, h, l, c, v = get("open"), get("high"), get("low"), get("close"), get("volume")
            if c > 0:
                rows.append([o if o > 0 else c, h if h > 0 else c, l if l > 0 else c, c, v])
        except (ValueError, TypeError):
            continue

    if len(rows) < 2:
        return None
    return np.array(rows, dtype=np.float64)
