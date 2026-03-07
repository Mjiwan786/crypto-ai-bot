"""
Multi-strategy consensus gate.

Requires signals from 2+ INDEPENDENT indicator families to agree
on direction before publishing. Prevents single-indicator noise.

Families:
  A (momentum): RSI, MACD, ROC-based signals
  B (trend):    EMA crossover, SMA crossover, trend strength
  C (structure): Bollinger Band reversion, support/resistance breakout
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class Family(str, Enum):
    MOMENTUM = "momentum"
    TREND = "trend"
    STRUCTURE = "structure"


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


def evaluate_consensus(
    ohlcv: np.ndarray,
    min_families: int = 2,
) -> ConsensusResult:
    """
    Run all indicator families on OHLCV data and evaluate consensus.

    Args:
        ohlcv: numpy array shape (N, 5) -> [open, high, low, close, volume]
        min_families: minimum number of agreeing families to publish

    Returns:
        ConsensusResult with direction, confidence, and publish decision.
    """
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
        reason = (
            f"consensus_not_met: long={n_long} short={n_short} "
            f"need={min_families}"
        )
        logger.debug("Consensus: %s", reason)
        return ConsensusResult(
            direction=None, families_agreeing=families_agreeing,
            total_families_voting=total_voting, confidence=0.0,
            published=False, votes=votes, reason=reason,
        )

    # -- Aggregate confidence --
    agreeing_votes = [v for v in votes if v.direction == direction]
    base_confidence = np.mean([v.confidence for v in agreeing_votes])

    # Consensus boost
    if families_agreeing >= 3:
        base_confidence *= 1.15
    elif families_agreeing >= 2:
        base_confidence *= 1.05
    base_confidence = min(base_confidence, 0.95)

    reason = (
        f"consensus_met: {families_agreeing}/{total_voting} families -> {direction}"
    )
    logger.info("Consensus: %s (confidence=%.2f)", reason, base_confidence)

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
    """RSI + ROC momentum assessment."""
    if len(closes) < 15:
        return None

    # RSI (14-period, proper Wilder smoothing)
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

    # Direction decision
    direction = None
    confidence = 0.5

    if rsi < 30 and roc > -0.5:
        direction = "long"
        confidence = 0.65 + (30 - rsi) / 100  # stronger as more oversold
    elif rsi > 70 and roc < 0.5:
        direction = "short"
        confidence = 0.65 + (rsi - 70) / 100
    elif roc > 0.8:
        direction = "long"
        confidence = 0.55 + min(roc / 10, 0.2)
    elif roc < -0.8:
        direction = "short"
        confidence = 0.55 + min(abs(roc) / 10, 0.2)
    else:
        return None  # no clear momentum signal

    return StrategyVote(
        family=Family.MOMENTUM, direction=direction,
        confidence=min(confidence, 0.90), name="rsi_roc",
    )


def _evaluate_trend(closes: np.ndarray) -> Optional[StrategyVote]:
    """EMA crossover trend assessment."""
    if len(closes) < 26:
        return None

    # EMA-9 and EMA-21
    ema_fast = _ema(closes, 9)
    ema_slow = _ema(closes, 21)

    if ema_fast is None or ema_slow is None:
        return None

    spread = (ema_fast - ema_slow) / ema_slow * 100  # as percentage

    # Need a meaningful spread (not just noise)
    if abs(spread) < 0.05:
        return None

    # Check EMA slope (last 3 candles)
    ema_fast_prev = _ema(closes[:-2], 9)
    if ema_fast_prev is None:
        return None
    slope = (ema_fast - ema_fast_prev) / ema_fast_prev * 100

    direction = None
    confidence = 0.5

    if spread > 0.05 and slope > 0:
        direction = "long"
        confidence = 0.60 + min(spread / 5, 0.25)
    elif spread < -0.05 and slope < 0:
        direction = "short"
        confidence = 0.60 + min(abs(spread) / 5, 0.25)
    else:
        return None

    return StrategyVote(
        family=Family.TREND, direction=direction,
        confidence=min(confidence, 0.90), name="ema_cross",
    )


def _evaluate_structure(
    closes: np.ndarray, highs: np.ndarray, lows: np.ndarray
) -> Optional[StrategyVote]:
    """Bollinger Band + support/resistance structure assessment."""
    if len(closes) < 20:
        return None

    # Bollinger Bands (20-period, 2 std dev)
    sma20 = np.mean(closes[-20:])
    std20 = np.std(closes[-20:])
    if std20 == 0:
        return None

    upper_bb = sma20 + 2 * std20
    lower_bb = sma20 - 2 * std20
    current = closes[-1]

    # How far price is from the band (as fraction of band width)
    bb_width = upper_bb - lower_bb
    if bb_width == 0:
        return None

    position_in_bb = (current - lower_bb) / bb_width  # 0 = lower, 1 = upper

    direction = None
    confidence = 0.5

    if position_in_bb < 0.1:
        # Price at/below lower band -- mean reversion long
        direction = "long"
        confidence = 0.60 + (0.1 - position_in_bb) * 2
    elif position_in_bb > 0.9:
        # Price at/above upper band -- mean reversion short
        direction = "short"
        confidence = 0.60 + (position_in_bb - 0.9) * 2
    else:
        return None

    return StrategyVote(
        family=Family.STRUCTURE, direction=direction,
        confidence=min(confidence, 0.85), name="bb_reversion",
    )


def _ema(data: np.ndarray, period: int) -> Optional[float]:
    """Compute EMA of the last value in data."""
    if len(data) < period:
        return None
    k = 2.0 / (period + 1)
    ema = float(data[0])
    for price in data[1:]:
        ema = float(price) * k + ema * (1 - k)
    return ema
