"""
Data export utilities for ML training pipeline.

Exports OHLCV candles and trade outcomes from Redis to CSV files,
and provides utilities for loading them back. Also includes synthetic
data generation for development/testing when Redis data is unavailable.

The candle labeler assigns binary labels (profitable=1, not=0) to each
candle based on simulated forward-looking trades, accounting for the
52 bps round-trip fee floor.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from utils.logger import get_logger

logger = get_logger(__name__)

# Timeframe second → human label mapping (matches ohlcv_reader.py)
_TF_LABELS = {15: "15s", 60: "1m", 300: "5m", 900: "15m"}


class DataExporter:
    """Export training data from Redis streams to CSV."""

    async def export_ohlcv(
        self,
        redis_client,
        pair: str,
        timeframe_s: int = 60,
        output_path: str = "data/ohlcv_{pair}_{tf}.csv",
        max_entries: int = 50000,
    ) -> str:
        """
        Export OHLCV candles from Redis to CSV.

        Tries multiple Redis key formats matching ohlcv_reader.py conventions.

        Returns:
            The output file path.
        """
        dash_pair = pair.replace("/", "-")
        label = _TF_LABELS.get(timeframe_s, f"{timeframe_s}s")
        output_path = output_path.replace("{pair}", pair.replace("/", "_")).replace("{tf}", label)

        # Key formats to try (priority order)
        key_candidates = [
            f"ohlc:{timeframe_s}:any:{dash_pair}",
            f"kraken:ohlc:{label}:{dash_pair}",
            f"ohlc:{label}:any:{dash_pair}",
        ]

        client = redis_client.client if hasattr(redis_client, "client") else redis_client
        entries = []

        for key in key_candidates:
            try:
                raw = await client.xrevrange(key, count=max_entries)
                if raw:
                    logger.info("Found %d entries in %s", len(raw), key)
                    for entry_id, fields in reversed(raw):
                        ts = entry_id if isinstance(entry_id, str) else entry_id.decode()
                        row = {k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v for k, v in fields.items()}
                        entries.append({
                            "timestamp": ts.split("-")[0],
                            "open": float(row.get("open", row.get("o", 0))),
                            "high": float(row.get("high", row.get("h", 0))),
                            "low": float(row.get("low", row.get("l", 0))),
                            "close": float(row.get("close", row.get("c", 0))),
                            "volume": float(row.get("volume", row.get("v", 0))),
                        })
                    break
            except Exception as e:
                logger.debug("Key %s failed: %s", key, e)

        if not entries:
            logger.warning("No OHLCV data found for %s", pair)
            return output_path

        df = pd.DataFrame(entries)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_path, index=False)
        logger.info("Exported %d candles to %s", len(df), output_path)
        return output_path

    async def export_trade_outcomes(
        self,
        redis_client,
        pair: str,
        output_path: str = "data/trades_{pair}.csv",
        max_entries: int = 10000,
    ) -> str:
        """Export paper trade results from Redis to CSV."""
        dash_pair = pair.replace("/", "-")
        output_path = output_path.replace("{pair}", pair.replace("/", "_"))
        key = f"trades:paper:{dash_pair}"

        client = redis_client.client if hasattr(redis_client, "client") else redis_client
        entries = []

        try:
            raw = await client.xrevrange(key, count=max_entries)
            if raw:
                for entry_id, fields in reversed(raw):
                    ts = entry_id if isinstance(entry_id, str) else entry_id.decode()
                    row = {k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v for k, v in fields.items()}
                    entries.append({
                        "timestamp": ts.split("-")[0],
                        "pair": pair,
                        "side": row.get("side", ""),
                        "entry_price": float(row.get("entry_price", 0)),
                        "exit_price": float(row.get("exit_price", 0)),
                        "pnl_pct": float(row.get("pnl_pct", 0)),
                        "duration_s": float(row.get("duration_s", 0)),
                        "model_version": row.get("model_version", ""),
                    })
        except Exception as e:
            logger.warning("Failed to read trades for %s: %s", pair, e)

        if not entries:
            logger.warning("No trade data found for %s", pair)
            return output_path

        df = pd.DataFrame(entries)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_path, index=False)
        logger.info("Exported %d trades to %s", len(df), output_path)
        return output_path

    @staticmethod
    def load_ohlcv_csv(path: str) -> np.ndarray:
        """Load OHLCV CSV back into numpy array (N, 5). Drops timestamp column."""
        df = pd.read_csv(path)
        cols = ["open", "high", "low", "close", "volume"]
        return df[cols].values.astype(np.float64)

    @staticmethod
    def load_trades_csv(path: str) -> pd.DataFrame:
        """Load trade outcomes CSV into DataFrame."""
        return pd.read_csv(path)


def label_candles(
    ohlcv: np.ndarray,
    lookahead_candles: int = 15,
    tp_bps: float = 100.0,
    sl_bps: float = 75.0,
    fee_bps: float = 52.0,
) -> np.ndarray:
    """
    Label each candle with the outcome of a hypothetical trade.

    For each candle at index i, simulates both LONG and SHORT entries
    at close[i] and checks whether TP or SL is hit within the next
    ``lookahead_candles``. The best direction wins.

    Fee floor: a gross move of +40 bps is a LOSS after 52 bps RT fees.

    Labels:
        1  = profitable (at least one direction nets positive after fees)
        0  = unprofitable (neither direction profitable)
       -1  = unknown (last ``lookahead_candles`` rows, exclude from training)

    Returns:
        1D int array, same length as ohlcv.
    """
    n = len(ohlcv)
    closes = ohlcv[:, 3]
    highs = ohlcv[:, 1]
    lows = ohlcv[:, 2]
    labels = np.full(n, -1, dtype=np.int32)

    tp_mult = tp_bps / 10000.0
    sl_mult = sl_bps / 10000.0

    for i in range(n - lookahead_candles):
        entry = closes[i]
        if entry <= 0:
            labels[i] = 0
            continue

        long_profitable = False
        short_profitable = False

        # --- Simulate LONG ---
        long_tp = entry * (1.0 + tp_mult)
        long_sl = entry * (1.0 - sl_mult)
        long_resolved = False
        for j in range(i + 1, min(i + 1 + lookahead_candles, n)):
            # Check SL first (conservative — same-candle ambiguity)
            if lows[j] <= long_sl:
                long_resolved = True
                break
            if highs[j] >= long_tp:
                # Gross profit = tp_bps, net = tp_bps - fee_bps
                if tp_bps > fee_bps:
                    long_profitable = True
                long_resolved = True
                break
        if not long_resolved:
            # Time exit: check final PnL
            final_j = min(i + lookahead_candles, n - 1)
            gross_bps = (closes[final_j] - entry) / entry * 10000.0
            if gross_bps - fee_bps > 0:
                long_profitable = True

        # --- Simulate SHORT ---
        short_tp = entry * (1.0 - tp_mult)
        short_sl = entry * (1.0 + sl_mult)
        short_resolved = False
        for j in range(i + 1, min(i + 1 + lookahead_candles, n)):
            if highs[j] >= short_sl:
                short_resolved = True
                break
            if lows[j] <= short_tp:
                if tp_bps > fee_bps:
                    short_profitable = True
                short_resolved = True
                break
        if not short_resolved:
            final_j = min(i + lookahead_candles, n - 1)
            gross_bps = (entry - closes[final_j]) / entry * 10000.0
            if gross_bps - fee_bps > 0:
                short_profitable = True

        labels[i] = 1 if (long_profitable or short_profitable) else 0

    return labels


def generate_synthetic_ohlcv(
    n_candles: int = 5000,
    start_price: float = 100.0,
    volatility: float = 0.02,
    trend: float = 0.0001,
    seed: int = 42,
) -> np.ndarray:
    """
    Generate realistic synthetic OHLCV for training pipeline development.

    Uses Geometric Brownian Motion for close prices, with proper OHLCV
    structure and volume correlated with price movement magnitude.

    Returns:
        numpy array shape (n_candles, 5) = [open, high, low, close, volume]
    """
    rng = np.random.RandomState(seed)

    # Close prices via GBM
    returns = rng.normal(trend, volatility, n_candles)
    closes = start_price * np.exp(np.cumsum(returns))

    # Open = previous close with small gap
    opens = np.empty(n_candles)
    opens[0] = start_price
    opens[1:] = closes[:-1] * (1.0 + rng.normal(0, 0.001, n_candles - 1))

    # High and low (intra-candle volatility)
    intra_vol = np.abs(rng.normal(0, volatility * 0.5, n_candles))
    highs = np.maximum(opens, closes) * (1.0 + intra_vol)
    lows = np.minimum(opens, closes) * (1.0 - intra_vol)

    # Volume (higher on big moves)
    base_volume = 1000.0
    move_mag = np.abs(returns)
    volumes = base_volume * (1.0 + move_mag * 10.0) * rng.lognormal(0, 0.5, n_candles)

    return np.column_stack([opens, highs, lows, closes, volumes])
