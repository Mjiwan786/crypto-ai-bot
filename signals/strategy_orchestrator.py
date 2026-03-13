"""
Strategy Orchestrator — Sprint 2 (P0-B)

Detects market regime from OHLCV data, routes to appropriate strategies,
and aggregates multi-strategy signals into a single direction + confidence.

Pipeline:
  OHLCV (numpy N x 5) → regime detection → strategy routing → aggregation → result dict

Regime detection is internal (EMA crossover + volatility + ROC) — no Redis dependency.
Strategies are sync (use talib), so they run in ThreadPoolExecutor.

Feature flag: STRATEGY_ORCHESTRATOR_ENABLED (default true)
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Regime classification ────────────────────────────────────────────
REGIMES = ("bull", "bear", "sideways", "neutral")

# Strategy → regime routing table
REGIME_STRATEGIES: Dict[str, List[str]] = {
    "bull":     ["TrendFollowing", "Breakout", "Momentum"],
    "bear":     ["MeanReversion", "MovingAverage"],
    "sideways": ["Sideways", "MeanReversion"],
    "neutral":  ["Momentum", "MovingAverage", "TrendFollowing"],
}

# Strategy weight in confidence aggregation (higher = more influence)
STRATEGY_WEIGHTS: Dict[str, float] = {
    "TrendFollowing": 1.0,
    "Breakout":       0.9,
    "Momentum":       1.0,
    "MeanReversion":  0.85,
    "MovingAverage":  0.8,
    "Sideways":       0.7,
}

# Thread pool shared across orchestrator instances (strategies use talib = sync)
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="strategy")


def detect_regime(ohlcv: np.ndarray) -> str:
    """
    Classify market regime from OHLCV data.

    Uses EMA-9/21 spread + 20-bar volatility + 10-bar ROC.
    Returns: "bull", "bear", "sideways", or "neutral".
    """
    closes = ohlcv[:, 3]
    if len(closes) < 26:
        return "neutral"

    # EMA-9 and EMA-21
    ema9 = _ema(closes, 9)
    ema21 = _ema(closes, 21)
    spread_pct = (ema9 - ema21) / ema21 * 100  # signed percentage

    # 20-bar volatility (std / mean)
    vol = float(np.std(closes[-20:]) / np.mean(closes[-20:])) if len(closes) >= 20 else 0.02

    # 10-bar ROC
    roc = float((closes[-1] - closes[-11]) / closes[-11] * 100) if len(closes) >= 11 else 0.0

    # Classification
    if vol > 0.04:
        # High volatility — treat as trending if directional, else neutral
        if abs(roc) > 1.5:
            return "bull" if roc > 0 else "bear"
        return "neutral"

    if spread_pct > 0.08 and roc > 0.3:
        return "bull"
    elif spread_pct < -0.08 and roc < -0.3:
        return "bear"
    elif abs(spread_pct) < 0.04 and abs(roc) < 0.3 and vol < 0.015:
        return "sideways"
    else:
        return "neutral"


def _ema(data: np.ndarray, period: int) -> float:
    """Compute EMA of last value."""
    k = 2.0 / (period + 1)
    ema = float(data[0])
    for price in data[1:]:
        ema = float(price) * k + ema * (1 - k)
    return ema


# ── Strategy loading (lazy, cached) ─────────────────────────────────
_strategy_cache: Dict[str, Any] = {}


def _load_strategy(name: str) -> Optional[Any]:
    """Load a strategy class by name. Returns instance or None on failure."""
    if name in _strategy_cache:
        return _strategy_cache[name]

    try:
        if name == "TrendFollowing":
            from strategies.trend_following import TrendFollowingStrategy
            inst = TrendFollowingStrategy()
        elif name == "Breakout":
            from strategies.breakout import BreakoutStrategy
            inst = BreakoutStrategy()
        elif name == "MeanReversion":
            from strategies.mean_reversion import MeanReversionStrategy
            inst = MeanReversionStrategy()
        elif name == "Momentum":
            from strategies.momentum import MomentumStrategy
            inst = MomentumStrategy()
        elif name == "MovingAverage":
            from strategies.moving_average import MovingAverageStrategy
            inst = MovingAverageStrategy()
        elif name == "Sideways":
            from strategies.sideways import SidewaysStrategy
            inst = SidewaysStrategy()
        else:
            logger.warning("[ORCHESTRATOR] Unknown strategy: %s", name)
            return None
        _strategy_cache[name] = inst
        return inst
    except Exception as e:
        logger.warning("[ORCHESTRATOR] Failed to load strategy %s: %s", name, e)
        _strategy_cache[name] = None
        return None


def _run_strategy_sync(name: str, df: pd.DataFrame) -> Dict[str, Any]:
    """Run a single strategy (sync, for ThreadPoolExecutor)."""
    strategy = _load_strategy(name)
    if strategy is None:
        return {"signal": None, "reason": f"{name}_load_failed"}
    try:
        result = strategy.generate_signal(df)
        return result
    except Exception as e:
        logger.warning("[ORCHESTRATOR] Strategy %s raised: %s", name, e)
        return {"signal": None, "reason": f"{name}_error: {e}"}


# ── Orchestrator ─────────────────────────────────────────────────────

class StrategyOrchestrator:
    """
    Receives OHLCV numpy array, detects regime, routes to strategies,
    and aggregates into a single signal dict.
    """

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    async def generate_signal(self, ohlcv: np.ndarray, pair: str = "") -> Dict[str, Any]:
        """
        Main entry point.

        Args:
            ohlcv: numpy (N, 5) — open, high, low, close, volume
            pair: trading pair for logging (e.g. "BTC/USD")

        Returns:
            dict with keys: signal ("buy"/"sell"/None), confidence, source, regime, etc.
        """
        if not self.enabled:
            return {"signal": None, "reason": "orchestrator_disabled"}

        if ohlcv is None or len(ohlcv) < 30:
            return {"signal": None, "reason": "insufficient_data"}

        t0 = time.time()

        # 1. Detect regime
        regime = detect_regime(ohlcv)

        # 2. Get strategies for this regime
        strategy_names = REGIME_STRATEGIES.get(regime, REGIME_STRATEGIES["neutral"])

        # 3. Build DataFrame for strategies (they expect df["close"], df["high"], etc.)
        df = pd.DataFrame(ohlcv, columns=["open", "high", "low", "close", "volume"])

        # 4. Run strategies in thread pool (talib is sync)
        loop = asyncio.get_event_loop()
        results: Dict[str, Dict[str, Any]] = {}
        tasks = []
        for name in strategy_names:
            tasks.append((name, loop.run_in_executor(_executor, _run_strategy_sync, name, df.copy())))

        for name, fut in tasks:
            try:
                result = await fut
                results[name] = result
            except Exception as e:
                logger.warning("[ORCHESTRATOR] %s executor error: %s", name, e)
                results[name] = {"signal": None, "reason": str(e)}

        # 5. Aggregate signals
        buy_votes: List[tuple] = []   # (name, confidence)
        sell_votes: List[tuple] = []
        for name, res in results.items():
            sig = res.get("signal")
            conf = res.get("confidence", 0.5)
            if sig == "buy":
                buy_votes.append((name, conf))
            elif sig == "sell":
                sell_votes.append((name, conf))

        total_voting = len(buy_votes) + len(sell_votes)
        elapsed_ms = int((time.time() - t0) * 1000)

        # Determine majority
        if not buy_votes and not sell_votes:
            logger.info(
                "[ORCHESTRATOR] %s regime=%s: no signals from %s (%dms)",
                pair, regime, ", ".join(strategy_names), elapsed_ms,
            )
            return {
                "signal": None,
                "reason": "no_strategy_signals",
                "regime": regime,
                "strategies_run": strategy_names,
            }

        if len(buy_votes) > len(sell_votes):
            direction = "buy"
            winning_votes = buy_votes
        elif len(sell_votes) > len(buy_votes):
            direction = "sell"
            winning_votes = sell_votes
        else:
            # Tied — pick by weighted confidence
            buy_wc = sum(STRATEGY_WEIGHTS.get(n, 0.8) * c for n, c in buy_votes)
            sell_wc = sum(STRATEGY_WEIGHTS.get(n, 0.8) * c for n, c in sell_votes)
            if buy_wc >= sell_wc:
                direction = "buy"
                winning_votes = buy_votes
            else:
                direction = "sell"
                winning_votes = sell_votes

        # Weighted average confidence with agreement boost
        total_weight = sum(STRATEGY_WEIGHTS.get(n, 0.8) for n, _ in winning_votes)
        if total_weight > 0:
            confidence = sum(
                STRATEGY_WEIGHTS.get(n, 0.8) * c for n, c in winning_votes
            ) / total_weight
        else:
            confidence = 0.5

        # Agreement boost: more strategies agreeing → higher confidence
        agreement_ratio = len(winning_votes) / max(len(strategy_names), 1)
        if agreement_ratio >= 0.67:
            confidence *= 1.10
        elif agreement_ratio >= 0.5:
            confidence *= 1.05
        confidence = min(confidence, 0.95)

        agreeing_names = [n for n, _ in winning_votes]

        logger.info(
            "[ORCHESTRATOR] %s regime=%s: %s conf=%.2f strategies=%s (%d/%d vote, %dms)",
            pair, regime, direction, confidence,
            ",".join(agreeing_names), len(winning_votes), total_voting, elapsed_ms,
        )

        return {
            "signal": direction,
            "confidence": confidence,
            "source": "strategy_orchestrator",
            "regime": regime,
            "strategies_agreeing": agreeing_names,
            "strategies_run": strategy_names,
            "agreement_ratio": agreement_ratio,
            "latency_ms": elapsed_ms,
        }


# ── Self-test ────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    print("=" * 60)
    print("Strategy Orchestrator — Self-Test (mock data)")
    print("=" * 60)

    # Generate synthetic OHLCV: 60 candles, trending up
    np.random.seed(42)
    n = 60
    base = 68000.0
    noise = np.random.randn(n) * 50
    trend = np.linspace(0, 800, n)  # uptrend
    closes = base + trend + noise
    opens = closes - np.random.rand(n) * 30
    highs = np.maximum(opens, closes) + np.abs(np.random.randn(n)) * 20
    lows = np.minimum(opens, closes) - np.abs(np.random.randn(n)) * 20
    volumes = np.random.rand(n) * 100 + 50

    ohlcv = np.column_stack([opens, highs, lows, closes, volumes])

    # Test regime detection
    regime = detect_regime(ohlcv)
    print(f"\nRegime detected: {regime}")

    # Test orchestrator
    orchestrator = StrategyOrchestrator(enabled=True)
    result = asyncio.run(orchestrator.generate_signal(ohlcv, pair="BTC/USD"))

    print(f"\nOrchestrator result:")
    for k, v in result.items():
        print(f"  {k}: {v}")

    # Test disabled
    orchestrator_off = StrategyOrchestrator(enabled=False)
    result_off = asyncio.run(orchestrator_off.generate_signal(ohlcv))
    assert result_off["signal"] is None
    assert result_off["reason"] == "orchestrator_disabled"
    print("\nDisabled test: PASS")

    # Test insufficient data
    result_small = asyncio.run(orchestrator.generate_signal(ohlcv[:5]))
    assert result_small["signal"] is None
    print("Insufficient data test: PASS")

    print("\n" + "=" * 60)
    print("ALL SELF-TESTS PASSED")
    print("=" * 60)
