"""
On-Chain Feature Pipeline — Sprint 3

Transforms raw cached derivatives/macro data into normalized signals
for Family D of the consensus gate.

All rules are rule-based (no ML). Signal logic is contrarian:
- High funding → overleveraged longs → bearish
- Crowded L/S → contrarian → opposite direction
- Extreme sentiment → suppress piling on
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


def evaluate_derivatives_signal(
    derivatives: Optional[dict],
    positioning: Optional[dict],
    macro: Optional[dict],
    sentiment: Optional[dict],
) -> Optional[Tuple[str, float, List[str]]]:
    """
    Evaluate on-chain/derivatives data and return (direction, confidence, reasons).

    Returns None to abstain (insufficient data or conflicting signals).

    Sub-signals and weights:
      1. Funding Rate Contrarian  (0.30)
      2. OI-Price Divergence      (0.25) — uses OI change only (no live price here)
      3. Long-Short Ratio Extreme (0.20)
      4. Taker Buy/Sell Imbalance (0.15)
      5. Sentiment Veto           (gate, not a vote)
    """
    if derivatives is None:
        return None

    votes: List[Tuple[str, float, str]] = []  # (direction, weight, reason)

    # ── 1. FUNDING RATE CONTRARIAN (weight 0.30) ──
    funding = derivatives.get("funding_rate")
    if funding is not None:
        try:
            fr = float(funding)
            if fr > 0.0005:  # >0.05% per 8h
                votes.append(("short", 0.30, f"funding_bearish({fr:.4f})"))
            elif fr < -0.0005:  # <-0.05% per 8h
                votes.append(("long", 0.30, f"funding_bullish({fr:.4f})"))
        except (ValueError, TypeError):
            pass

    # ── 2. OI CHANGE (weight 0.25) ──
    oi_change = derivatives.get("oi_change_1h_pct")
    if oi_change is not None:
        try:
            oic = float(oi_change)
            if oic > 5.0:
                # OI surging = overleveraged, likely liquidation cascade coming
                votes.append(("short", 0.25, f"oi_surge_bearish({oic:.1f}%)"))
            elif oic < -5.0:
                # OI dropping fast = deleveraging done, bounce likely
                votes.append(("long", 0.25, f"oi_drop_bullish({oic:.1f}%)"))
        except (ValueError, TypeError):
            pass

    # ── 3. LONG-SHORT RATIO EXTREME (weight 0.20) ──
    if positioning is not None:
        ls_ratio = positioning.get("long_short_ratio")
        if ls_ratio is not None:
            try:
                lsr = float(ls_ratio)
                if lsr > 2.0:
                    votes.append(("short", 0.20, f"ls_crowded_longs({lsr:.2f})"))
                elif lsr < 0.5:
                    votes.append(("long", 0.20, f"ls_crowded_shorts({lsr:.2f})"))
            except (ValueError, TypeError):
                pass

    # ── 4. TAKER BUY/SELL IMBALANCE (weight 0.15) ──
    if positioning is not None:
        taker_ratio = positioning.get("taker_buy_sell_ratio")
        if taker_ratio is not None:
            try:
                tr = float(taker_ratio)
                if tr > 1.3:
                    votes.append(("long", 0.15, f"taker_buying({tr:.2f})"))
                elif tr < 0.7:
                    votes.append(("short", 0.15, f"taker_selling({tr:.2f})"))
            except (ValueError, TypeError):
                pass

    # Need at least 2 sub-signals to produce a direction
    if len(votes) < 2:
        return None

    # Tally
    long_weight = sum(w for d, w, _ in votes if d == "long")
    short_weight = sum(w for d, w, _ in votes if d == "short")

    if long_weight > short_weight and long_weight >= 0.30:
        direction = "long"
        weight = long_weight
    elif short_weight > long_weight and short_weight >= 0.30:
        direction = "short"
        weight = short_weight
    else:
        return None  # Conflicting

    # Confidence: base 0.50 + weight contribution (cap 0.80)
    confidence = min(0.80, 0.50 + weight * 0.30)

    reasons = [r for d, _, r in votes if d == direction]

    # ── 5. SENTIMENT VETO (gate, not a vote) ──
    if sentiment is not None:
        fgi = sentiment.get("fear_greed_index")
        if fgi is not None:
            try:
                idx = int(fgi)
                if idx > 80 and direction == "long":
                    # Extreme Greed — don't pile on longs
                    return None
                if idx < 20 and direction == "short":
                    # Extreme Fear — don't pile on shorts
                    return None
            except (ValueError, TypeError):
                pass

    return (direction, confidence, reasons)
