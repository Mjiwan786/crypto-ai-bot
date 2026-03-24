"""
Read OHLCV candles from Redis streams for signal generation.

Supports two modes:
  1. Scorer-driven: ExchangeScorer ranks exchanges, reader fetches from best.
  2. Legacy fallback: tries ALL known exchange key formats (USDT variants, multiple tf formats).
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from signals.exchange_scorer import ExchangeScorer

logger = logging.getLogger(__name__)

# Timeframe seconds → CCXT-style label
_TF_LABEL: dict = {15: "15s", 60: "1m", 300: "5m", 900: "15m", 3600: "1h"}

# All exchanges the streamer publishes data for
_ALL_EXCHANGES = ["binance", "bybit", "okx", "kucoin", "gateio", "coinbase", "bitfinex", "kraken"]
_USDT_EXCHANGES = frozenset({"binance", "bybit", "okx", "kucoin", "gateio"})
_USD_EXCHANGES = frozenset({"kraken", "coinbase", "bitfinex"})

# Multiple timeframe format variants per CCXT label
_TF_VARIANTS: dict = {
    "15s": ["15s", "15"],
    "1m": ["1m", "1", "60"],
    "5m": ["5m", "5", "300"],
    "15m": ["15m", "15", "900"],
    "1h": ["1h", "60", "3600"],
}

# Minimum candles required (reduced from 50 for faster warmup)
_MIN_CANDLES = 20


async def read_ohlcv_candles(
    redis_client: Any,
    exchange: str,
    pair: str,
    timeframe_s: int = 60,
    lookback: int = 50,
    scorer: Optional["ExchangeScorer"] = None,
) -> Optional[np.ndarray]:
    """
    Read recent OHLCV candles from Redis stream.

    When scorer is provided, uses quality-scored exchange selection.
    When scorer is None, falls back to legacy key scanning.

    Returns:
        numpy array shape (N, 5) with columns [open, high, low, close, volume]
        or None if insufficient data.
    """
    # Convert timeframe_s to label
    tf_label = _TF_LABEL.get(timeframe_s)
    if tf_label is None:
        if timeframe_s >= 3600:
            tf_label = f"{timeframe_s // 3600}h"
        elif timeframe_s >= 60:
            tf_label = f"{timeframe_s // 60}m"
        else:
            tf_label = f"{timeframe_s}s"

    # ── Scorer-driven selection ──
    if scorer is not None:
        ranked = await scorer.score_all(redis_client, pair, tf_label, lookback)
        for ex, score in ranked:
            if not score.available:
                continue
            dash_pair = pair.replace("/", "-")
            keys = scorer._build_key_candidates(ex, pair, dash_pair, tf_label)
            for key in keys:
                try:
                    raw = await _read_stream(redis_client, key, lookback)
                    if raw and len(raw) >= _MIN_CANDLES:
                        arr = _parse_ohlcv(raw)
                        if arr is not None and len(arr) >= _MIN_CANDLES:
                            logger.info(
                                "OHLCV read: exchange=%s pair=%s tf=%s key=%s candles=%d (score=%.2f)",
                                ex, pair, tf_label, key, len(arr), score.total_score,
                            )
                            return arr
                except Exception:
                    continue
        logger.warning("OHLCV: No data from any scored exchange for %s %s", pair, tf_label)
        return None

    # ── Legacy fallback (scorer=None) ──
    # Build comprehensive list of key candidates across ALL exchanges and formats
    keys_to_try = _build_all_candidates(exchange, pair, tf_label, timeframe_s)

    for key in keys_to_try:
        try:
            raw = await _read_stream(redis_client, key, lookback)
            if raw and len(raw) >= _MIN_CANDLES:
                arr = _parse_ohlcv(raw)
                if arr is not None and len(arr) >= _MIN_CANDLES:
                    logger.info(
                        "OHLCV hit: pair=%s tf=%s key=%s candles=%d",
                        pair, tf_label, key, len(arr),
                    )
                    return arr
        except Exception as e:
            logger.debug("OHLCV read failed key=%s: %s", key, e)
            continue

    logger.warning(
        "OHLCV miss: pair=%s tf=%s tried %d keys (no data >= %d candles)",
        pair, tf_label, len(keys_to_try), _MIN_CANDLES,
    )
    return None


def _build_all_candidates(
    exchange: str, pair: str, tf_label: str, timeframe_s: int
) -> List[str]:
    """
    Build ALL possible Redis key format candidates.

    Tries every exchange × every timeframe format × both USD and USDT pair variants.
    This ensures we find data regardless of which exchange/format the streamer used.
    """
    keys: List[str] = []
    dash_pair = pair.replace("/", "-")

    # Determine pair variants: if pair is BTC-USD, also try BTC-USDT and vice versa
    is_usd = dash_pair.endswith("-USD") and not dash_pair.endswith("-USDT")
    usdt_pair = dash_pair + "T" if is_usd else dash_pair
    usd_pair = dash_pair[:-1] if dash_pair.endswith("-USDT") else dash_pair

    # Get all timeframe format variants for the requested timeframe
    tf_variants = _TF_VARIANTS.get(tf_label, [tf_label])
    # Also include the raw seconds value as a variant
    sec_str = str(timeframe_s)
    if sec_str not in tf_variants:
        tf_variants = list(tf_variants) + [sec_str]

    # Determine exchange priority order: requested exchange first, then all others
    exchanges_ordered = []
    if exchange and exchange != "any" and exchange in _ALL_EXCHANGES:
        exchanges_ordered.append(exchange)
    for ex in _ALL_EXCHANGES:
        if ex not in exchanges_ordered:
            exchanges_ordered.append(ex)

    # For each exchange, generate key candidates with correct pair format
    for ex in exchanges_ordered:
        if ex in _USDT_EXCHANGES:
            pair_to_use = usdt_pair
        else:
            pair_to_use = usd_pair

        for tf in tf_variants:
            keys.append(f"{ex}:ohlc:{tf}:{pair_to_use}")

    # Aggregator format candidates (cross-exchange)
    slash_pair = pair if "/" in pair else pair.replace("-", "/")
    for tf in tf_variants:
        keys.append(f"ohlc:{tf}:any:{dash_pair}")
        keys.append(f"ohlc:{tf}:any:{slash_pair}")

    # Legacy Kraken integer-minutes format
    legacy_tf = timeframe_s // 60 if timeframe_s >= 60 else timeframe_s
    keys.append(f"kraken:ohlc:{legacy_tf}:{usd_pair}")

    return keys


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
