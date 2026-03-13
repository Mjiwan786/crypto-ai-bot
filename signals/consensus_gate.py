"""
Multi-strategy consensus gate.

Requires signals from 2+ INDEPENDENT indicator families to agree
on direction before publishing. Prevents single-indicator noise.

Families:
  A (momentum):  RSI, MACD, ROC-based signals
  B (trend):     EMA crossover, SMA crossover, trend strength
  C (structure): Bollinger Band reversion, support/resistance breakout
  D (onchain):   Derivatives + positioning data (optional, cached from Redis)

Sprint 2 changes:
  - Relaxed thresholds: moderate signals now vote at lower confidence
  - min_families configurable via MIN_CONSENSUS_FAMILIES env var
  - Family D (on-chain) optional — abstains if disabled or data unavailable
  - Per-vote logging for observability

Sprint 3 changes:
  - Family D upgraded: reads pre-computed signal from feature_pipeline via Redis
  - evaluate_consensus() now async to support Redis reads for Family D
  - New data sources: Coinalyze, Binance Futures, DefiLlama, Fear & Greed
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Default from env var; can be overridden per-call
_DEFAULT_MIN_FAMILIES = int(os.getenv("MIN_CONSENSUS_FAMILIES", "2"))


class Family(str, Enum):
    MOMENTUM = "momentum"
    TREND = "trend"
    STRUCTURE = "structure"
    ONCHAIN = "onchain"


@dataclass
class StrategyVote:
    """A single strategy's directional vote."""
    family: Family
    direction: str          # "long" or "short"
    confidence: float       # 0.0 - 1.0
    name: str               # strategy name for logging


@dataclass
class ConsensusResult:
    """Result of consensus evaluation."""
    direction: Optional[str]        # "long", "short", or None
    families_agreeing: int          # how many families agree
    total_families_voting: int      # how many families voted at all
    confidence: float               # aggregated confidence
    published: bool                 # whether signal passes gate
    votes: List[StrategyVote]       # all votes for logging
    reason: str                     # human-readable explanation


async def evaluate_consensus(
    ohlcv: np.ndarray,
    min_families: Optional[int] = None,
    pair: str = "",
    redis_client: Any = None,
) -> ConsensusResult:
    """
    Run all indicator families on OHLCV data and evaluate consensus.

    Args:
        ohlcv: numpy array shape (N, 5) -> [open, high, low, close, volume]
        min_families: minimum agreeing families to publish (None = read env var)
        pair: trading pair for logging (e.g. "BTC/USD")
        redis_client: optional RedisCloudClient for on-chain family D

    Returns:
        ConsensusResult with direction, confidence, and publish decision.
    """
    if min_families is None:
        min_families = _DEFAULT_MIN_FAMILIES

    if ohlcv is None or len(ohlcv) < 30:
        return ConsensusResult(
            direction=None, families_agreeing=0, total_families_voting=0,
            confidence=0.0, published=False, votes=[], reason="insufficient_data",
        )

    closes = ohlcv[:, 3]
    highs = ohlcv[:, 1]
    lows = ohlcv[:, 2]
    volumes = ohlcv[:, 4]

    votes: List[StrategyVote] = []

    # -- Family A: Momentum --
    momentum_vote = _evaluate_momentum(closes)
    if momentum_vote:
        votes.append(momentum_vote)

    # -- Family B: Trend --
    trend_vote = _evaluate_trend(closes)
    if trend_vote:
        votes.append(trend_vote)

    # -- Family C: Structure --
    structure_vote = _evaluate_structure(closes, highs, lows)
    if structure_vote:
        votes.append(structure_vote)

    # -- Family D: On-chain (optional) --
    onchain_enabled = os.getenv("ONCHAIN_FAMILY_ENABLED", "false").lower() == "true"
    if onchain_enabled and redis_client is not None:
        onchain_vote = await _evaluate_onchain_family(pair, redis_client)
        if onchain_vote:
            votes.append(onchain_vote)

    # -- Build vote summary string for logging --
    vote_strs = []
    for fam in [Family.MOMENTUM, Family.TREND, Family.STRUCTURE, Family.ONCHAIN]:
        fam_votes = [v for v in votes if v.family == fam]
        if fam_votes:
            v = fam_votes[0]
            vote_strs.append(f"{fam.value}={v.direction}({v.confidence:.2f})")
        else:
            if fam == Family.ONCHAIN and not onchain_enabled:
                continue  # Don't log disabled family
            vote_strs.append(f"{fam.value}=abstain")

    # -- Tally votes by direction --
    long_families = set()
    short_families = set()
    for v in votes:
        if v.direction == "long":
            long_families.add(v.family)
        elif v.direction == "short":
            short_families.add(v.family)

    n_long = len(long_families)
    n_short = len(short_families)
    total_voting = len(set(v.family for v in votes))

    if n_long >= min_families and n_long > n_short:
        direction = "long"
        families_agreeing = n_long
    elif n_short >= min_families and n_short > n_long:
        direction = "short"
        families_agreeing = n_short
    else:
        direction = None
        families_agreeing = max(n_long, n_short)
        vote_summary = ", ".join(vote_strs)
        reason = (
            f"consensus_not_met: long={n_long} short={n_short} "
            f"need={min_families}"
        )
        logger.info(
            "[CONSENSUS] %s: %s -> NO SIGNAL (%d/%d need %d)",
            pair or "?", vote_summary,
            families_agreeing, total_voting, min_families,
        )
        return ConsensusResult(
            direction=None, families_agreeing=families_agreeing,
            total_families_voting=total_voting, confidence=0.0,
            published=False, votes=votes, reason=reason,
        )

    # -- Aggregate confidence --
    agreeing_votes = [v for v in votes if v.direction == direction]
    base_confidence = float(np.mean([v.confidence for v in agreeing_votes]))

    # Consensus boost
    if families_agreeing >= 3:
        base_confidence *= 1.15
    elif families_agreeing >= 2:
        base_confidence *= 1.05
    base_confidence = min(base_confidence, 0.95)

    vote_summary = ", ".join(vote_strs)
    reason = (
        f"consensus_met: {families_agreeing}/{total_voting} families -> {direction}"
    )
    logger.info(
        "[CONSENSUS] %s: %s -> %s (%d/%d, conf=%.2f)",
        pair or "?", vote_summary,
        direction.upper(), families_agreeing, total_voting, base_confidence,
    )

    return ConsensusResult(
        direction=direction,
        families_agreeing=families_agreeing,
        total_families_voting=total_voting,
        confidence=float(base_confidence),
        published=True,
        votes=votes,
        reason=reason,
    )


# =================================================================
# Family evaluators
# =================================================================

def _evaluate_momentum(closes: np.ndarray) -> Optional[StrategyVote]:
    """
    RSI + ROC momentum assessment.

    Relaxed thresholds (Sprint 2):
      - Moderate RSI (30-40 / 60-70) votes at lower confidence (0.52)
      - Moderate ROC (±0.5-0.8%) votes at lower confidence (0.53)
      - Extreme levels keep original higher confidence
    """
    if len(closes) < 15:
        return None

    # RSI (14-period)
    deltas = np.diff(closes[-15:])
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.mean(gains)
    avg_loss = max(np.mean(losses), 1e-10)
    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))

    # ROC over last 10 candles
    if len(closes) >= 11:
        roc = (closes[-1] - closes[-11]) / closes[-11] * 100
    else:
        roc = 0.0

    direction = None
    confidence = 0.5

    # ── Extreme RSI (original thresholds, higher confidence) ──
    if rsi < 30 and roc > -0.5:
        direction = "long"
        confidence = 0.65 + (30 - rsi) / 100
    elif rsi > 70 and roc < 0.5:
        direction = "short"
        confidence = 0.65 + (rsi - 70) / 100
    # ── Moderate RSI (new relaxed band) ──
    elif rsi < 40 and roc > -0.3:
        direction = "long"
        confidence = 0.52 + (40 - rsi) / 200  # 0.52-0.57
    elif rsi > 60 and roc < 0.3:
        direction = "short"
        confidence = 0.52 + (rsi - 60) / 200  # 0.52-0.57
    # ── Strong ROC (original) ──
    elif roc > 0.8:
        direction = "long"
        confidence = 0.55 + min(roc / 10, 0.2)
    elif roc < -0.8:
        direction = "short"
        confidence = 0.55 + min(abs(roc) / 10, 0.2)
    # ── Moderate ROC (new relaxed band) ──
    elif roc > 0.5:
        direction = "long"
        confidence = 0.53
    elif roc < -0.5:
        direction = "short"
        confidence = 0.53
    else:
        return None

    return StrategyVote(
        family=Family.MOMENTUM, direction=direction,
        confidence=min(confidence, 0.90), name="rsi_roc",
    )


def _evaluate_trend(closes: np.ndarray) -> Optional[StrategyVote]:
    """
    EMA crossover trend assessment.

    Relaxed thresholds (Sprint 2):
      - Moderate spread (0.03-0.05%) votes at lower confidence (0.55)
      - Strong spread (>0.05%) keeps original confidence (0.60+)
    """
    if len(closes) < 26:
        return None

    ema_fast = _ema(closes, 9)
    ema_slow = _ema(closes, 21)

    if ema_fast is None or ema_slow is None:
        return None

    spread = (ema_fast - ema_slow) / ema_slow * 100  # as percentage

    # Need at least a minimal spread (reduced from 0.05% to 0.03%)
    if abs(spread) < 0.03:
        return None

    # Check EMA slope (last 3 candles)
    ema_fast_prev = _ema(closes[:-2], 9)
    if ema_fast_prev is None:
        return None
    slope = (ema_fast - ema_fast_prev) / ema_fast_prev * 100

    direction = None
    confidence = 0.5

    # ── Strong spread (original thresholds) ──
    if spread > 0.05 and slope > 0:
        direction = "long"
        confidence = 0.60 + min(spread / 5, 0.25)
    elif spread < -0.05 and slope < 0:
        direction = "short"
        confidence = 0.60 + min(abs(spread) / 5, 0.25)
    # ── Moderate spread (new relaxed band: 0.03-0.05%) ──
    elif spread > 0.03 and slope > 0:
        direction = "long"
        confidence = 0.55
    elif spread < -0.03 and slope < 0:
        direction = "short"
        confidence = 0.55
    else:
        return None

    return StrategyVote(
        family=Family.TREND, direction=direction,
        confidence=min(confidence, 0.90), name="ema_cross",
    )


def _evaluate_structure(
    closes: np.ndarray, highs: np.ndarray, lows: np.ndarray
) -> Optional[StrategyVote]:
    """
    Bollinger Band structure assessment.

    Relaxed thresholds (Sprint 2):
      - Moderate BB position (10-20% / 80-90%) votes at lower confidence (0.53)
      - Extreme BB position (<10% / >90%) keeps original confidence (0.60+)
    """
    if len(closes) < 20:
        return None

    sma20 = np.mean(closes[-20:])
    std20 = np.std(closes[-20:])
    if std20 == 0:
        return None

    upper_bb = sma20 + 2 * std20
    lower_bb = sma20 - 2 * std20
    current = closes[-1]

    bb_width = upper_bb - lower_bb
    if bb_width == 0:
        return None

    position_in_bb = (current - lower_bb) / bb_width  # 0 = lower, 1 = upper

    direction = None
    confidence = 0.5

    # ── Extreme BB position (original thresholds) ──
    if position_in_bb < 0.1:
        direction = "long"
        confidence = 0.60 + (0.1 - position_in_bb) * 2
    elif position_in_bb > 0.9:
        direction = "short"
        confidence = 0.60 + (position_in_bb - 0.9) * 2
    # ── Moderate BB position (new relaxed band: 10-20% / 80-90%) ──
    elif position_in_bb < 0.2:
        direction = "long"
        confidence = 0.53 + (0.2 - position_in_bb) * 0.5  # 0.53-0.58
    elif position_in_bb > 0.8:
        direction = "short"
        confidence = 0.53 + (position_in_bb - 0.8) * 0.5  # 0.53-0.58
    else:
        return None

    return StrategyVote(
        family=Family.STRUCTURE, direction=direction,
        confidence=min(confidence, 0.85), name="bb_reversion",
    )


async def _evaluate_onchain_family(pair: str, redis_client: Any) -> Optional[StrategyVote]:
    """
    On-chain data family (Family D) — Sprint 3 upgrade.

    Reads PRE-COMPUTED signal from Redis (written by signal_computer.py).
    The data_fetcher.py background task refreshes raw data from free APIs,
    and signal_computer.py transforms it into a direction + confidence.

    Returns StrategyVote or None to abstain.
    """
    if redis_client is None:
        return None

    try:
        asset = pair.split("/")[0] if "/" in pair else "BTC"
        key = f"onchain:{asset}:signal"

        client = redis_client.client if hasattr(redis_client, "client") else redis_client
        raw = await client.get(key)

        if not raw:
            return None

        signal = json.loads(raw) if isinstance(raw, str) else json.loads(raw.decode())
        direction = signal.get("direction")
        confidence = signal.get("confidence", 0.0)

        if direction not in ("long", "short") or confidence < 0.40:
            return None

        return StrategyVote(
            family=Family.ONCHAIN,
            direction=direction,
            confidence=min(confidence, 0.80),
            name="onchain_derivatives",
        )

    except Exception as e:
        logger.debug("[CONSENSUS] On-chain family error: %s", e)
        return None


def _ema(data: np.ndarray, period: int) -> Optional[float]:
    """Compute EMA of the last value in data."""
    if len(data) < period:
        return None
    k = 2.0 / (period + 1)
    ema = float(data[0])
    for price in data[1:]:
        ema = float(price) * k + ema * (1 - k)
    return ema
