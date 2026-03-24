"""
AI Predicted Signals — Signal Generator

Orchestrates signal computation: OHLCV data + technical indicators
→ strategy evaluation → consensus gate → TradingSignal output.
Central coordination point for the signal pipeline.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import logging
import os

import numpy as np

from indicators.rsi import compute_rsi
from indicators.macd import compute_macd
from indicators.ema import compute_ema
from indicators.atr import compute_atr
from indicators.bollinger_bands import compute_bollinger_bands
from indicators.volume_profile import compute_volume_sma

from strategies import ALL_STRATEGIES, FAMILY_MAP
from strategies.base_strategy import StrategyResult
from strategies.trend_following_strategy import compute_adx

logger = logging.getLogger(__name__)

MIN_SIGNAL_CONFIDENCE = float(os.getenv("MIN_SIGNAL_CONFIDENCE", "0.50")) * 100  # 0-100 scale


@dataclass
class TradingSignal:
    direction: str  # "long" | "short" | "neutral"
    confidence: float  # 0-100
    pair: str
    exchange: str
    strategy: str
    regime: str
    metadata: dict = field(default_factory=dict)


class SignalGenerator:
    """Generates trading signals from market data using 8 TA strategies."""

    def __init__(self, strategies: list = None, scorer: object = None, min_families: int = None) -> None:
        self._strategies = strategies or ALL_STRATEGIES
        self._scorer = scorer
        self._min_families = min_families if min_families is not None else int(os.getenv("MIN_CONSENSUS_FAMILIES", "2"))

    async def generate(
        self, exchange: str, pair: str, ohlcv: np.ndarray
    ) -> Optional[TradingSignal]:
        """Generate a signal for a given pair using all strategies.

        Pipeline:
          1. Compute all indicators from OHLCV
          2. Run each strategy, collect StrategyResults
          3. Evaluate consensus across families (momentum/trend/structure)
          4. Return TradingSignal if confidence >= threshold
        """
        if ohlcv is None or len(ohlcv) < 30:
            return None

        indicators = self._compute_features(ohlcv)

        # Run all strategies
        results: List[StrategyResult] = []
        for strategy in self._strategies:
            try:
                result = strategy.compute_signal(ohlcv, indicators)
                results.append(result)
            except Exception as e:
                logger.warning("Strategy %s failed: %s", strategy.name, e)

        # Filter to directional signals (not neutral)
        active = [r for r in results if r.direction in ("long", "short")]
        if not active:
            return None

        # Consensus: group by family and check agreement
        family_directions: Dict[str, Dict[str, List[StrategyResult]]] = {}
        for r in active:
            family = FAMILY_MAP.get(r.strategy_name, "unknown")
            if family not in family_directions:
                family_directions[family] = {}
            direction = r.direction
            if direction not in family_directions[family]:
                family_directions[family][direction] = []
            family_directions[family][direction].append(r)

        # Count families per direction
        long_families = set()
        short_families = set()
        for family, dir_map in family_directions.items():
            if "long" in dir_map:
                long_families.add(family)
            if "short" in dir_map:
                short_families.add(family)

        n_long = len(long_families)
        n_short = len(short_families)

        # Need min_families+ families agreeing (configurable via MIN_CONSENSUS_FAMILIES)
        min_fam = self._min_families
        if n_long >= min_fam and n_long > n_short:
            direction = "long"
            agreeing = [r for r in active if r.direction == "long"]
        elif n_short >= min_fam and n_short > n_long:
            direction = "short"
            agreeing = [r for r in active if r.direction == "short"]
        else:
            logger.debug(
                "Consensus not met: long_families=%d short_families=%d",
                n_long, n_short,
            )
            return None

        # Aggregate confidence (average of agreeing strategies, 0-100 scale)
        avg_confidence = float(np.mean([r.confidence for r in agreeing]))

        # Consensus boost
        n_families = n_long if direction == "long" else n_short
        if n_families >= 3:
            avg_confidence *= 1.15
        elif n_families >= 2:
            avg_confidence *= 1.05
        avg_confidence = min(avg_confidence, 95.0)

        if avg_confidence < MIN_SIGNAL_CONFIDENCE:
            logger.debug(
                "Confidence %.1f below threshold %.1f",
                avg_confidence, MIN_SIGNAL_CONFIDENCE,
            )
            return None

        # Configurable consensus confidence floor (0-100 scale, e.g. 60 = 0.60 normalized)
        min_consensus_conf = float(os.getenv("MIN_CONSENSUS_CONFIDENCE", "0")) * 100
        if min_consensus_conf > 0 and avg_confidence < min_consensus_conf:
            logger.info(
                "Consensus confidence %.1f below floor %.1f (MIN_CONSENSUS_CONFIDENCE)",
                avg_confidence, min_consensus_conf,
            )
            return None

        # Build metadata from all agreeing strategies
        metadata = {
            "families_agreeing": n_families,
            "strategies_agreeing": [r.strategy_name for r in agreeing],
            "all_votes": [
                {"name": r.strategy_name, "dir": r.direction, "conf": r.confidence}
                for r in active
            ],
        }
        # Merge indicator snapshots
        for r in agreeing:
            for k, v in r.metadata.items():
                metadata[f"{r.strategy_name}_{k}"] = v

        # Add top-level indicator values for trade journal
        close = ohlcv[:, 3]
        rsi_arr = indicators.get("rsi")
        metadata["rsi"] = round(float(rsi_arr[-1]), 2) if rsi_arr is not None and not np.isnan(rsi_arr[-1]) else None
        metadata["ema_spread_bps"] = round(
            (float(indicators["ema_fast"][-1]) - float(indicators["ema_slow"][-1]))
            / float(indicators["ema_slow"][-1]) * 10000, 1
        ) if not np.isnan(indicators["ema_fast"][-1]) and not np.isnan(indicators["ema_slow"][-1]) else None
        metadata["volume_ratio"] = round(
            float(ohlcv[-1, 4] / np.mean(ohlcv[-21:-1, 4])), 2
        ) if len(ohlcv) >= 21 else None

        return TradingSignal(
            direction=direction,
            confidence=avg_confidence,
            pair=pair,
            exchange=exchange,
            strategy=",".join(r.strategy_name for r in agreeing),
            regime="unknown",
            metadata=metadata,
        )

    def _compute_features(self, ohlcv: np.ndarray) -> Dict[str, Any]:
        """Extract all indicator features from OHLCV data.

        Returns dict of numpy arrays keyed by indicator name.
        """
        close = ohlcv[:, 3]
        high = ohlcv[:, 1]
        low = ohlcv[:, 2]
        volume = ohlcv[:, 4]

        rsi = compute_rsi(close, 14)
        macd_line, macd_signal, macd_hist = compute_macd(close)
        ema_fast = compute_ema(close, 9)
        ema_slow = compute_ema(close, 21)
        ema_14 = compute_ema(close, 14)
        atr = compute_atr(high, low, close, 14)
        bb_upper, bb_middle, bb_lower = compute_bollinger_bands(close)
        vol_sma = compute_volume_sma(volume, 20)

        # ADX / DI
        adx, plus_di, minus_di = compute_adx(high, low, close, 14)

        return {
            "rsi": rsi,
            "macd_line": macd_line,
            "macd_signal": macd_signal,
            "macd_histogram": macd_hist,
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "ema_14": ema_14,
            "atr": atr,
            "bb_upper": bb_upper,
            "bb_middle": bb_middle,
            "bb_lower": bb_lower,
            "volume_sma": vol_sma,
            "adx": adx,
            "plus_di": plus_di,
            "minus_di": minus_di,
        }

    def _apply_model(self, features: dict) -> dict:
        """Apply ML model for signal enhancement (future).

        # Sprint 3: LSTM confidence boost goes here
        """
        return features
