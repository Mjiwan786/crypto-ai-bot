"""
Sprint 3A: ATR-based dynamic TP/SL calculator with fee-floor guard.

Replaces static bps TP/SL with volatility-calibrated levels using Wilder's
True Range method. Includes a fee-floor guard that vetoes trades where ATR
is too small to overcome round-trip fees.
"""

import logging
import os
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ── Volatility Tier Mapping ──────────────────────────────────
# Determines SL/TP multipliers based on asset volatility profile.
# Key = normalized base asset (uppercase, no quote), Value = tier name.
VOLATILITY_TIERS = {
    # High volatility — tight SL, 2:1 R:R
    "DOGE": "high", "ADA": "high", "SHIB": "high", "ALGO": "high",
    "XDG": "high",   # Kraken symbol for DOGE
    # Medium volatility — moderate SL, 1.67:1 R:R
    "SOL": "high", "DOT": "high", "AVAX": "medium", "NEAR": "medium",
    "LTC": "medium", "MATIC": "medium", "POL": "medium",
    # Low volatility — wide SL, 2:1 R:R
    "BTC": "low", "XBT": "low",  # Kraken symbol for BTC
    "ETH": "low", "XRP": "low", "LINK": "low",
}

# Default multipliers per tier — overridable via env vars
_TIER_DEFAULTS = {
    "high":  {"sl_mult": 1.0, "tp_mult": 3.0},
    "medium": {"sl_mult": 1.0, "tp_mult": 3.5},
    "low":   {"sl_mult": 1.0, "tp_mult": 4.0},
}


def _get_tier_multipliers(tier: str) -> tuple:
    """Return (sl_multiplier, tp_multiplier) for the given tier, with env var overrides."""
    if tier == "high":
        sl = float(os.getenv("ATR_SL_MULT_HIGH", str(_TIER_DEFAULTS["high"]["sl_mult"])))
        tp = float(os.getenv("ATR_TP_MULT_HIGH", str(_TIER_DEFAULTS["high"]["tp_mult"])))
    elif tier == "low":
        sl = float(os.getenv("ATR_SL_MULT_LOW", str(_TIER_DEFAULTS["low"]["sl_mult"])))
        tp = float(os.getenv("ATR_TP_MULT_LOW", str(_TIER_DEFAULTS["low"]["tp_mult"])))
    else:  # medium (default)
        sl = float(os.getenv("ATR_SL_MULT_MED", str(_TIER_DEFAULTS["medium"]["sl_mult"])))
        tp = float(os.getenv("ATR_TP_MULT_MED", str(_TIER_DEFAULTS["medium"]["tp_mult"])))
    return sl, tp


def _extract_base_asset(pair: str) -> str:
    """Extract the base asset from a pair like 'BTC/USD', 'BTC-USD', or 'BTCUSD'."""
    for sep in ["/", "-"]:
        if sep in pair:
            return pair.split(sep)[0].upper()
    # No separator — assume last 3-4 chars are quote (USD, USDT)
    upper = pair.upper()
    if upper.endswith("USDT"):
        return upper[:-4]
    if upper.endswith("USD"):
        return upper[:-3]
    return upper


def get_volatility_tier(pair: str) -> str:
    """Classify a pair into a volatility tier based on the base asset."""
    base = _extract_base_asset(pair)
    return VOLATILITY_TIERS.get(base, "medium")


def compute_atr(ohlcv: np.ndarray, period: int = 14) -> Optional[float]:
    """
    Compute ATR using Wilder's True Range method.

    Args:
        ohlcv: shape (N, 5) — open, high, low, close, volume
        period: EMA period for ATR (default 14)

    Returns:
        ATR value as float, or None if insufficient data.
    """
    if ohlcv is None or len(ohlcv) < period + 1:
        return None

    highs = ohlcv[:, 1]
    lows = ohlcv[:, 2]
    closes = ohlcv[:, 3]

    # True Range: max(H-L, |H-prevC|, |L-prevC|)
    prev_closes = np.roll(closes, 1)
    prev_closes[0] = closes[0]  # First bar: use own close

    tr1 = highs - lows
    tr2 = np.abs(highs - prev_closes)
    tr3 = np.abs(lows - prev_closes)
    true_range = np.maximum(tr1, np.maximum(tr2, tr3))

    # Wilder's EMA (equivalent to EMA with alpha = 1/period)
    alpha = 1.0 / period
    atr = float(true_range[1])  # Start from index 1 (first valid TR)
    for i in range(2, len(true_range)):
        atr = alpha * float(true_range[i]) + (1.0 - alpha) * atr

    return atr


def compute_atr_levels(
    ohlcv: np.ndarray,
    entry_price: float,
    side: str,
    pair: str = "",
    atr_period: int = None,
    sl_multiplier: float = None,
    tp_multiplier: float = None,
    fee_floor_bps: float = None,
) -> Optional[dict]:
    """
    Compute ATR-based TP/SL levels with fee-floor guard.

    Args:
        ohlcv: shape (N, 5) — open, high, low, close, volume
        entry_price: current price at signal generation
        side: "buy" or "sell"
        pair: trading pair (e.g. "BTC/USD") for volatility tier lookup
        atr_period: ATR lookback period (default from env or 14)
        sl_multiplier: override SL multiplier (default from tier)
        tp_multiplier: override TP multiplier (default from tier)
        fee_floor_bps: minimum SL distance in bps (default from env or 60)

    Returns:
        dict with stop_loss, take_profit, atr_value, distances, tier info
        or None if fee-floor guard rejects (insufficient volatility)
    """
    if atr_period is None:
        atr_period = int(os.getenv("ATR_PERIOD", "14"))
    if fee_floor_bps is None:
        fee_floor_bps = float(os.getenv("ATR_FEE_FLOOR_BPS", "60.0"))

    atr_value = compute_atr(ohlcv, period=atr_period)
    if atr_value is None or atr_value <= 0:
        logger.info("[ATR] %s: No ATR computed (insufficient data or zero ATR)", pair)
        return None

    # Determine volatility tier and multipliers
    tier = get_volatility_tier(pair)
    if sl_multiplier is None or tp_multiplier is None:
        tier_sl, tier_tp = _get_tier_multipliers(tier)
        if sl_multiplier is None:
            sl_multiplier = tier_sl
        if tp_multiplier is None:
            tp_multiplier = tier_tp

    # R:R floor and TP floor parameters
    round_trip_fee_bps = float(os.getenv("ROUND_TRIP_FEE_BPS", "52"))
    min_rr_ratio = float(os.getenv("MIN_RR_RATIO", "2.5"))
    tp_floor_bps = float(os.getenv("ATR_TP_FLOOR_BPS", "80"))

    sl_distance = atr_value * sl_multiplier
    tp_distance = atr_value * tp_multiplier

    # Compute price levels
    if side == "buy":
        stop_loss = entry_price - sl_distance
        take_profit = entry_price + tp_distance
    else:
        stop_loss = entry_price + sl_distance
        take_profit = entry_price - tp_distance

    # Compute distances in bps
    sl_distance_bps = (sl_distance / entry_price) * 10000
    tp_distance_bps = (tp_distance / entry_price) * 10000

    # Fee-floor guard: reject if SL distance < fee floor (secondary check)
    if sl_distance_bps < fee_floor_bps:
        logger.info(
            "[ATR] %s: SKIP — ATR SL=%.1f bps < fee floor %.0f bps (ATR=%.6f, tier=%s)",
            pair, sl_distance_bps, fee_floor_bps, atr_value, tier,
        )
        return None

    # TP floor guard: reject if TP target is too small
    if tp_distance_bps < tp_floor_bps:
        logger.info(
            "[ATR] %s: SKIP — TP=%.1f bps < TP floor %.0f bps (ATR=%.6f, tier=%s)",
            pair, tp_distance_bps, tp_floor_bps, atr_value, tier,
        )
        return None

    # R:R floor guard: reject if risk-reward ratio after fees is too low
    net_tp = tp_distance_bps - round_trip_fee_bps
    net_sl = sl_distance_bps + round_trip_fee_bps
    rr_ratio = net_tp / net_sl if net_sl > 0 else 0
    if net_tp <= 0 or rr_ratio < min_rr_ratio:
        logger.info(
            "[ATR] %s: SKIP — R:R floor — net_tp=%.1f bps, net_sl=%.1f bps, R:R=%.2f < %.1f (tier=%s)",
            pair, net_tp, net_sl, rr_ratio, min_rr_ratio, tier,
        )
        return None

    fee_floor_passed = True

    return {
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "atr_value": atr_value,
        "sl_distance_bps": sl_distance_bps,
        "tp_distance_bps": tp_distance_bps,
        "fee_floor_passed": fee_floor_passed,
        "volatility_tier": tier,
        "net_tp_bps": net_tp,
        "net_sl_bps": net_sl,
        "rr_ratio": rr_ratio,
    }
