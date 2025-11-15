"""
Adaptive Regime-Based Strategy Router with Performance Feedback

Implements dynamic strategy blending based on:
- Market regime detection (hyper_bull, bull, bear, sideways, extreme_vol)
- Historical performance (90-day Sharpe, PF, win rate)
- Probabilistic regime transitions with smoothing

Key Features:
- Loads strategy preferences from config/regime_map.yaml
- Tracks per-strategy performance in Redis
- Dynamically adjusts strategy weights based on recent performance
- Smooth regime transitions (no hard switches)
- Risk scaling per regime
- Automatic strategy disabling if underperforming

Author: Crypto AI Bot Team
Date: 2025-11-08
"""

from __future__ import annotations

import logging
import os
import time
from collections import deque, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import yaml
import numpy as np

# Redis for performance tracking
try:
    import redis.asyncio as aioredis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class RegimeState:
    """Current regime state with probabilities."""
    dominant_regime: str  # hyper_bull, bull, bear, sideways, extreme_vol
    probabilities: Dict[str, float]  # {regime: probability}
    confidence: float  # Confidence in dominant regime (0-1)
    volatility_index: float  # Crypto VIX score (0-100)
    trend_strength: float  # Trend strength (0-1)
    funding_rate: float  # Perp funding rate
    timestamp: int

@dataclass
class StrategyPerformance:
    """Historical performance metrics for a strategy."""
    strategy_name: str
    sharpe_ratio: float
    profit_factor: float
    win_rate_pct: float
    total_trades: int
    last_updated: int  # Unix timestamp
    lookback_days: int = 90

@dataclass
class StrategyWeight:
    """Weighted strategy allocation."""
    strategy_name: str
    base_weight: float  # From regime_map.yaml
    performance_multiplier: float  # From recent performance
    final_weight: float  # base_weight * performance_multiplier
    config: Dict[str, Any]  # Strategy-specific config


# =============================================================================
# ADAPTIVE REGIME ROUTER
# =============================================================================

class AdaptiveRegimeRouter:
    """
    Adaptive strategy router with performance feedback and probabilistic regimes.

    Usage:
        # Initialize with config and Redis
        router = AdaptiveRegimeRouter(
            config_path="config/regime_map.yaml",
            redis_url="rediss://..."
        )

        # Detect regime
        regime_state = router.detect_regime(ohlcv_df, funding_rate)

        # Get weighted strategies for current regime
        strategies = router.get_weighted_strategies(regime_state)

        # Generate signals from all strategies
        all_signals = []
        for strategy_weight in strategies:
            signals = strategy_weight.strategy.generate_signals(...)
            # Weight signals by final_weight
            for signal in signals:
                signal.confidence *= strategy_weight.final_weight
                all_signals.append(signal)

        # Update performance after trades
        router.update_strategy_performance("momentum", sharpe=1.2, pf=1.5, win_rate=55.0)
    """

    def __init__(
        self,
        config_path: str = "config/regime_map.yaml",
        redis_url: Optional[str] = None,
        redis_ca_cert: Optional[str] = None
    ):
        """
        Initialize adaptive regime router.

        Args:
            config_path: Path to regime_map.yaml configuration
            redis_url: Redis connection URL (for performance tracking)
            redis_ca_cert: Path to Redis TLS CA certificate
        """
        self.config_path = config_path
        self.redis_url = redis_url or os.getenv("REDIS_URL")
        self.redis_ca_cert = redis_ca_cert or os.getenv("REDIS_SSL_CA_CERT")

        # Load configuration
        self.config = self._load_config()
        self.regimes = self.config.get("regimes", {})
        self.adaptive_config = self.config.get("adaptive_blending", {})
        self.risk_config = self.config.get("risk_management", {})

        # Performance tracking
        self.performance_cache: Dict[str, StrategyPerformance] = {}
        self.performance_update_interval = self.adaptive_config.get("update_frequency_minutes", 60) * 60  # seconds
        self.last_performance_update = 0

        # Regime state history (for smoothing)
        self.regime_history: deque = deque(maxlen=10)

        # Redis client (async)
        self.redis_client: Optional[aioredis.Redis] = None

        logger.info(f"AdaptiveRegimeRouter initialized from {config_path}")
        logger.info(f"Loaded {len(self.regimes)} regime configurations")
        logger.info(f"Adaptive blending: {self.adaptive_config.get('enabled', False)}")

    # -------------------------------------------------------------------------
    # CONFIGURATION
    # -------------------------------------------------------------------------

    def _load_config(self) -> Dict[str, Any]:
        """Load regime_map.yaml configuration."""
        try:
            with open(self.config_path, 'r') as f:
                config = yaml.safe_load(f)
            logger.info(f"Loaded configuration from {self.config_path}")
            return config
        except Exception as e:
            logger.error(f"Failed to load config from {self.config_path}: {e}")
            # Return minimal default config
            return {
                "regimes": {},
                "adaptive_blending": {"enabled": False},
                "risk_management": {}
            }

    # -------------------------------------------------------------------------
    # REGIME DETECTION
    # -------------------------------------------------------------------------

    def detect_regime(
        self,
        ohlcv_df: pd.DataFrame,
        funding_rate: float = 0.0,
        sentiment: float = 0.0
    ) -> RegimeState:
        """
        Detect current market regime with probabilities.

        Args:
            ohlcv_df: OHLCV dataframe (must have ATR, BB, EMA columns)
            funding_rate: Perpetual futures funding rate
            sentiment: Twitter/Reddit sentiment score (-1 to +1)

        Returns:
            RegimeState with probabilities for each regime
        """
        # Calculate components
        volatility_index = self._calculate_volatility_index(ohlcv_df)
        trend_strength = self._calculate_trend_strength(ohlcv_df)

        # Get detection thresholds from config
        detection = self.config.get("detection", {})
        vol_thresholds = detection.get("volatility", {})
        trend_thresholds = detection.get("trend", {})
        funding_thresholds = detection.get("funding", {})

        # Calculate regime probabilities
        probs = {}

        # Hyper Bull: Strong uptrend + high vol + bullish funding
        hyper_bull_score = 0.0
        if trend_strength >= trend_thresholds.get("strong_bull", 0.7):
            hyper_bull_score += 0.4
        if volatility_index >= vol_thresholds.get("elevated_max", 60):
            hyper_bull_score += 0.3
        if funding_rate >= funding_thresholds.get("bullish", 0.00005):
            hyper_bull_score += 0.3
        probs["hyper_bull"] = hyper_bull_score

        # Bull: Moderate uptrend + normal vol
        bull_score = 0.0
        if 0.4 <= trend_strength < 0.7:
            bull_score += 0.5
        if vol_thresholds.get("low_threshold", 20) <= volatility_index < vol_thresholds.get("elevated_max", 60):
            bull_score += 0.3
        if funding_rate >= 0:
            bull_score += 0.2
        probs["bull"] = bull_score

        # Bear: Downtrend + negative funding
        bear_score = 0.0
        if trend_strength < trend_thresholds.get("moderate_bear", 0.3):
            bear_score += 0.5
        if funding_rate < 0:
            bear_score += 0.3
        if sentiment < 0:
            bear_score += 0.2
        probs["bear"] = bear_score

        # Sideways: Narrow trend + low vol
        sideways_score = 0.0
        if trend_thresholds.get("moderate_bear", 0.3) <= trend_strength < trend_thresholds.get("moderate_bull", 0.4):
            sideways_score += 0.5
        if volatility_index < vol_thresholds.get("normal_max", 40):
            sideways_score += 0.5
        probs["sideways"] = sideways_score

        # Extreme Volatility: Very high vol (overrides others)
        extreme_vol_score = 0.0
        if volatility_index >= vol_thresholds.get("high_max", 80):
            extreme_vol_score = 1.0  # Dominates
        probs["extreme_volatility"] = extreme_vol_score

        # Normalize probabilities to sum to 1.0
        total = sum(probs.values())
        if total > 0:
            probs = {k: v / total for k, v in probs.items()}
        else:
            # Default to sideways if no clear regime
            probs = {"sideways": 1.0}

        # Find dominant regime
        dominant_regime = max(probs, key=probs.get)
        confidence = probs[dominant_regime]

        # Create regime state
        regime_state = RegimeState(
            dominant_regime=dominant_regime,
            probabilities=probs,
            confidence=confidence,
            volatility_index=volatility_index,
            trend_strength=trend_strength,
            funding_rate=funding_rate,
            timestamp=int(time.time() * 1000)
        )

        # Add to history
        self.regime_history.append(regime_state)

        # Apply smoothing if enabled
        if self.config.get("transitions", {}).get("smoothing_enabled", False):
            regime_state = self._smooth_regime_transition(regime_state)

        logger.info(
            f"Regime detected: {regime_state.dominant_regime} "
            f"(confidence={confidence:.2f}, VIX={volatility_index:.1f}, "
            f"trend={trend_strength:.2f}, funding={funding_rate:.5f})"
        )

        return regime_state

    def _calculate_volatility_index(self, df: pd.DataFrame) -> float:
        """
        Calculate crypto VIX-style volatility index (0-100 scale).

        Uses ATR%, BB width%, and daily range%.
        """
        try:
            # Ensure we have required columns
            if 'atr' not in df.columns or 'close' not in df.columns:
                logger.warning("Missing ATR or close columns, returning default VIX=50")
                return 50.0

            # ATR as % of price (30-period average)
            lookback = min(30, len(df))
            atr_pct = (df['atr'] / df['close']) * 100
            atr_avg = atr_pct.tail(lookback).mean()

            # BB Width as % of price (if available)
            if 'bb_upper' in df.columns and 'bb_lower' in df.columns:
                bb_width_pct = ((df['bb_upper'] - df['bb_lower']) / df['close']) * 100
                bb_avg = bb_width_pct.tail(lookback).mean()
            else:
                bb_avg = atr_avg  # Use ATR as fallback

            # Daily range % (if available)
            if 'high' in df.columns and 'low' in df.columns:
                range_pct = ((df['high'] - df['low']) / df['close']) * 100
                range_avg = range_pct.tail(lookback).mean()
            else:
                range_avg = atr_avg

            # Weighted combination
            vix_score = (
                atr_avg * 0.4 +
                bb_avg * 0.4 +
                range_avg * 0.2
            )

            # Normalize to 0-100 (assume 10% daily vol = 100 VIX)
            vix_normalized = min(100, (vix_score / 10.0) * 100)

            return vix_normalized

        except Exception as e:
            logger.error(f"Failed to calculate VIX: {e}")
            return 50.0  # Default to middle

    def _calculate_trend_strength(self, df: pd.DataFrame) -> float:
        """
        Calculate trend strength (0-1 scale).

        Uses EMA crossovers and slope.
        Returns: 0 = strong downtrend, 0.5 = no trend, 1.0 = strong uptrend
        """
        try:
            # Use EMA crossover if available
            if 'ema_50' in df.columns and 'ema_200' in df.columns:
                latest = df.iloc[-1]
                ema_50 = latest['ema_50']
                ema_200 = latest['ema_200']

                # Trend strength based on EMA distance
                if ema_200 > 0:
                    distance_pct = (ema_50 - ema_200) / ema_200
                    # Map -10% to +10% distance to 0-1 scale
                    trend_strength = (distance_pct / 0.1) * 0.5 + 0.5
                    trend_strength = max(0.0, min(1.0, trend_strength))
                    return trend_strength

            # Fallback: Use price slope
            if len(df) >= 20:
                prices = df['close'].tail(20).values
                x = np.arange(len(prices))
                slope = np.polyfit(x, prices, 1)[0]

                # Normalize slope to -1 to +1 range (assume 5% move over 20 bars = strong)
                price_change_pct = (slope * 20) / prices[0]
                trend_strength = (price_change_pct / 0.05) * 0.5 + 0.5
                trend_strength = max(0.0, min(1.0, trend_strength))
                return trend_strength

            return 0.5  # Neutral default

        except Exception as e:
            logger.error(f"Failed to calculate trend strength: {e}")
            return 0.5

    def _smooth_regime_transition(self, current_state: RegimeState) -> RegimeState:
        """
        Smooth regime transitions using recent history.

        Prevents rapid regime switches by averaging probabilities over N periods.
        """
        smoothing_periods = self.config.get("transitions", {}).get("smoothing_periods", 3)

        if len(self.regime_history) < smoothing_periods:
            return current_state  # Not enough history yet

        # Get last N regime states
        recent_states = list(self.regime_history)[-smoothing_periods:]

        # Average probabilities across periods
        smoothed_probs = defaultdict(float)
        for state in recent_states:
            for regime, prob in state.probabilities.items():
                smoothed_probs[regime] += prob / len(recent_states)

        # Find new dominant regime
        dominant_regime = max(smoothed_probs, key=smoothed_probs.get)
        confidence = smoothed_probs[dominant_regime]

        # Create smoothed state
        smoothed_state = RegimeState(
            dominant_regime=dominant_regime,
            probabilities=dict(smoothed_probs),
            confidence=confidence,
            volatility_index=current_state.volatility_index,
            trend_strength=current_state.trend_strength,
            funding_rate=current_state.funding_rate,
            timestamp=current_state.timestamp
        )

        return smoothed_state

    # -------------------------------------------------------------------------
    # STRATEGY WEIGHTING
    # -------------------------------------------------------------------------

    def get_weighted_strategies(self, regime_state: RegimeState) -> List[StrategyWeight]:
        """
        Get weighted list of strategies for current regime.

        Applies:
        1. Base weights from regime_map.yaml
        2. Performance multipliers from recent 90-day performance
        3. Minimum probability thresholds

        Args:
            regime_state: Current regime state with probabilities

        Returns:
            List of StrategyWeight sorted by final_weight (descending)
        """
        weighted_strategies = []

        # Get minimum probability threshold
        min_prob = self.config.get("transitions", {}).get("min_probability", 0.4)

        # Iterate over all regimes with significant probability
        for regime_name, prob in regime_state.probabilities.items():
            if prob < min_prob:
                continue  # Skip low-probability regimes

            # Get regime config
            regime_config = self.regimes.get(regime_name)
            if not regime_config:
                logger.warning(f"No config for regime: {regime_name}")
                continue

            # Get primary strategies for this regime
            primary_strategies = regime_config.get("strategies", {}).get("primary", [])

            for strategy_def in primary_strategies:
                strategy_name = strategy_def.get("name")
                base_weight = strategy_def.get("weight", 1.0)
                config = strategy_def.get("config", {})

                # Get performance multiplier
                perf_multiplier = self._get_performance_multiplier(strategy_name)

                # Calculate final weight (regime_prob * base_weight * perf_multiplier)
                final_weight = prob * base_weight * perf_multiplier

                weighted_strategies.append(StrategyWeight(
                    strategy_name=strategy_name,
                    base_weight=base_weight,
                    performance_multiplier=perf_multiplier,
                    final_weight=final_weight,
                    config=config
                ))

        # Sort by final weight (descending)
        weighted_strategies.sort(key=lambda x: x.final_weight, reverse=True)

        # Normalize weights to sum to 1.0
        total_weight = sum(s.final_weight for s in weighted_strategies)
        if total_weight > 0:
            for strategy in weighted_strategies:
                strategy.final_weight /= total_weight

        logger.info(
            f"Weighted strategies for {regime_state.dominant_regime}: "
            f"{[(s.strategy_name, f'{s.final_weight:.2f}') for s in weighted_strategies[:3]]}"
        )

        return weighted_strategies

    def _get_performance_multiplier(self, strategy_name: str) -> float:
        """
        Get performance-based multiplier for a strategy.

        Uses recent Sharpe, PF, win rate to adjust base weight.
        Returns: 0.0 (disabled) to 1.5 (excellent)
        """
        if not self.adaptive_config.get("enabled", False):
            return 1.0  # No adjustment if adaptive blending disabled

        # Check performance cache
        perf = self.performance_cache.get(strategy_name)
        if not perf:
            # No performance data yet, use neutral multiplier
            return 1.0

        # Check minimum thresholds
        thresholds = self.adaptive_config.get("thresholds", {})
        min_sharpe = thresholds.get("min_sharpe", 0.5)
        min_pf = thresholds.get("min_profit_factor", 1.0)
        min_trades = thresholds.get("min_trades", 10)

        # Disable if below thresholds
        if perf.sharpe_ratio < min_sharpe:
            logger.warning(f"{strategy_name} disabled: Sharpe {perf.sharpe_ratio:.2f} < {min_sharpe}")
            return 0.0
        if perf.profit_factor < min_pf:
            logger.warning(f"{strategy_name} disabled: PF {perf.profit_factor:.2f} < {min_pf}")
            return 0.0
        if perf.total_trades < min_trades:
            logger.warning(f"{strategy_name} disabled: {perf.total_trades} trades < {min_trades}")
            return 0.0

        # Calculate performance score
        metrics = self.adaptive_config.get("metrics", {})
        sharpe_weight = metrics.get("sharpe_weight", 0.4)
        pf_weight = metrics.get("profit_factor_weight", 0.4)
        win_rate_weight = metrics.get("win_rate_weight", 0.2)

        # Normalize metrics to 0-1 scale (assume Sharpe 1.5, PF 1.5, Win Rate 55% = 1.0)
        sharpe_norm = min(1.0, perf.sharpe_ratio / 1.5)
        pf_norm = min(1.0, perf.profit_factor / 1.5)
        win_rate_norm = min(1.0, perf.win_rate_pct / 55.0)

        # Weighted score
        performance_score = (
            sharpe_norm * sharpe_weight +
            pf_norm * pf_weight +
            win_rate_norm * win_rate_weight
        )

        # Map to multiplier (0.5 to 1.5 range)
        multipliers = self.adaptive_config.get("performance_multiplier", {})

        if performance_score >= 1.0 and perf.sharpe_ratio > 1.5 and perf.profit_factor > 2.0:
            multiplier = multipliers.get("excellent", 1.5)
        elif performance_score >= 0.8 and perf.sharpe_ratio > 1.0 and perf.profit_factor > 1.5:
            multiplier = multipliers.get("good", 1.2)
        elif performance_score >= 0.5:
            multiplier = multipliers.get("average", 1.0)
        else:
            multiplier = multipliers.get("poor", 0.5)

        logger.debug(
            f"{strategy_name} performance multiplier: {multiplier:.2f} "
            f"(Sharpe={perf.sharpe_ratio:.2f}, PF={perf.profit_factor:.2f}, WR={perf.win_rate_pct:.1f}%)"
        )

        return multiplier

    # -------------------------------------------------------------------------
    # PERFORMANCE TRACKING
    # -------------------------------------------------------------------------

    async def update_strategy_performance(
        self,
        strategy_name: str,
        sharpe: float,
        profit_factor: float,
        win_rate: float,
        total_trades: int
    ) -> None:
        """
        Update performance metrics for a strategy.

        Stores in Redis and local cache.

        Args:
            strategy_name: Strategy name
            sharpe: Sharpe ratio
            profit_factor: Profit factor
            win_rate: Win rate percentage
            total_trades: Number of trades in period
        """
        perf = StrategyPerformance(
            strategy_name=strategy_name,
            sharpe_ratio=sharpe,
            profit_factor=profit_factor,
            win_rate_pct=win_rate,
            total_trades=total_trades,
            last_updated=int(time.time()),
            lookback_days=self.adaptive_config.get("lookback_days", 90)
        )

        # Update local cache
        self.performance_cache[strategy_name] = perf

        # Update Redis if available
        if self.redis_client and REDIS_AVAILABLE:
            try:
                redis_key = f"strategy:performance:{strategy_name}"
                perf_data = {
                    "sharpe_ratio": sharpe,
                    "profit_factor": profit_factor,
                    "win_rate_pct": win_rate,
                    "total_trades": total_trades,
                    "last_updated": perf.last_updated
                }
                await self.redis_client.hset(redis_key, mapping=perf_data)
                await self.redis_client.expire(redis_key, 86400 * 180)  # Retain for 180 days
                logger.info(f"Updated {strategy_name} performance in Redis")
            except Exception as e:
                logger.error(f"Failed to update performance in Redis: {e}")

        logger.info(
            f"Updated {strategy_name} performance: Sharpe={sharpe:.2f}, PF={profit_factor:.2f}, "
            f"WR={win_rate:.1f}%, Trades={total_trades}"
        )

    async def load_performance_from_redis(self) -> None:
        """Load all strategy performance data from Redis."""
        if not self.redis_client or not REDIS_AVAILABLE:
            logger.warning("Redis not available, skipping performance load")
            return

        try:
            # Scan for performance keys
            keys = []
            async for key in self.redis_client.scan_iter(match="strategy:performance:*"):
                keys.append(key)

            logger.info(f"Loading performance for {len(keys)} strategies from Redis")

            for key in keys:
                strategy_name = key.split(":")[-1]
                perf_data = await self.redis_client.hgetall(key)

                if perf_data:
                    perf = StrategyPerformance(
                        strategy_name=strategy_name,
                        sharpe_ratio=float(perf_data.get("sharpe_ratio", 0)),
                        profit_factor=float(perf_data.get("profit_factor", 0)),
                        win_rate_pct=float(perf_data.get("win_rate_pct", 0)),
                        total_trades=int(perf_data.get("total_trades", 0)),
                        last_updated=int(perf_data.get("last_updated", 0))
                    )
                    self.performance_cache[strategy_name] = perf

            logger.info(f"Loaded {len(self.performance_cache)} strategy performance records")

        except Exception as e:
            logger.error(f"Failed to load performance from Redis: {e}")

    # -------------------------------------------------------------------------
    # RISK SCALING
    # -------------------------------------------------------------------------

    def get_risk_multiplier(self, regime_state: RegimeState) -> float:
        """
        Get position size multiplier based on regime.

        Returns: 0.3 (extreme vol) to 1.2 (hyper bull)
        """
        regime_name = regime_state.dominant_regime
        risk_config = self.risk_config.get(regime_name, {})

        multiplier = risk_config.get("position_size_multiplier", 1.0)

        logger.debug(f"Risk multiplier for {regime_name}: {multiplier:.2f}")
        return multiplier

    def get_max_position_pct(self, regime_state: RegimeState) -> float:
        """
        Get maximum position size as % of capital for current regime.

        Returns: 10% (extreme vol) to 30% (hyper bull)
        """
        regime_name = regime_state.dominant_regime
        risk_config = self.risk_config.get(regime_name, {})

        max_pct = risk_config.get("max_position_pct", 25)

        return max_pct

    def get_max_concurrent_signals(self, regime_state: RegimeState) -> int:
        """
        Get maximum number of concurrent signals for current regime.

        Returns: 2 (extreme vol) to 5 (hyper bull)
        """
        regime_name = regime_state.dominant_regime
        risk_config = self.risk_config.get(regime_name, {})

        max_signals = risk_config.get("max_concurrent_signals", 4)

        return max_signals


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def create_default_adaptive_router(
    config_path: str = "config/regime_map.yaml",
    redis_url: Optional[str] = None
) -> AdaptiveRegimeRouter:
    """
    Create adaptive router with default configuration.

    Args:
        config_path: Path to regime_map.yaml
        redis_url: Redis URL for performance tracking

    Returns:
        Configured AdaptiveRegimeRouter instance
    """
    router = AdaptiveRegimeRouter(
        config_path=config_path,
        redis_url=redis_url
    )

    logger.info("Created adaptive regime router with default config")
    return router


# =============================================================================
# SELF-CHECK
# =============================================================================

if __name__ == "__main__":
    """Self-check with sample data"""
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    try:
        logger.info("=== Adaptive Regime Router Self-Check ===\n")

        # Create router
        router = AdaptiveRegimeRouter(config_path="config/regime_map.yaml")

        # Create sample OHLCV data
        dates = pd.date_range("2024-01-01", periods=100, freq="5min")
        ohlcv_df = pd.DataFrame({
            "timestamp": dates,
            "open": np.linspace(45000, 50000, 100),
            "high": np.linspace(45100, 50100, 100),
            "low": np.linspace(44900, 49900, 100),
            "close": np.linspace(45000, 50000, 100),
            "volume": [1000] * 100
        })

        # Add required technical indicators
        ohlcv_df['atr'] = ohlcv_df['close'] * 0.02  # 2% ATR
        ohlcv_df['ema_50'] = ohlcv_df['close'].ewm(span=50).mean()
        ohlcv_df['ema_200'] = ohlcv_df['close'].ewm(span=200).mean()
        ohlcv_df['bb_upper'] = ohlcv_df['close'] * 1.02
        ohlcv_df['bb_lower'] = ohlcv_df['close'] * 0.98

        # Detect regime
        regime_state = router.detect_regime(
            ohlcv_df,
            funding_rate=0.0001,  # Bullish funding
            sentiment=0.3  # Slightly bullish sentiment
        )

        logger.info(f"\nDetected regime: {regime_state.dominant_regime}")
        logger.info(f"Confidence: {regime_state.confidence:.2f}")
        logger.info(f"Probabilities: {regime_state.probabilities}")
        logger.info(f"VIX: {regime_state.volatility_index:.1f}")
        logger.info(f"Trend Strength: {regime_state.trend_strength:.2f}")

        # Get weighted strategies
        strategies = router.get_weighted_strategies(regime_state)

        logger.info(f"\nWeighted strategies ({len(strategies)}):")
        for strategy in strategies:
            logger.info(
                f"  - {strategy.strategy_name}: "
                f"weight={strategy.final_weight:.3f} "
                f"(base={strategy.base_weight:.2f}, perf={strategy.performance_multiplier:.2f})"
            )

        # Get risk parameters
        risk_mult = router.get_risk_multiplier(regime_state)
        max_pos_pct = router.get_max_position_pct(regime_state)
        max_signals = router.get_max_concurrent_signals(regime_state)

        logger.info(f"\nRisk parameters:")
        logger.info(f"  - Position size multiplier: {risk_mult:.2f}")
        logger.info(f"  - Max position %: {max_pos_pct:.1f}%")
        logger.info(f"  - Max concurrent signals: {max_signals}")

        logger.info("\n✅ Self-check PASSED")
        sys.exit(0)

    except Exception as e:
        logger.error(f"❌ Self-check FAILED: {e}", exc_info=True)
        sys.exit(1)
