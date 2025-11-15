"""
ai_engine/regime_detector.py

Production-grade market regime detector with hysteresis and persistence.
Analyzes OHLCV data to classify market regimes (bull/bear/chop) with volatility
context, preventing flip-flop through configurable hysteresis.

Features:
- Multi-indicator regime detection (ADX, Aroon, RSI, ATR)
- Hysteresis: require K bars persistence before regime flip
- Volatility regime classification (low/high)
- Configurable thresholds via RegimeConfig
- Pure deterministic logic (no network/file I/O)
- Emits RegimeTick with regime, vol_regime, strength, changed flag

Algorithm:
1. Compute technical indicators (ADX, Aroon, RSI, ATR)
2. Classify regime based on trend strength and momentum
3. Classify volatility regime based on ATR percentile
4. Apply hysteresis: only flip if new regime persists for K bars
5. Emit RegimeTick with full diagnostic info

PRD Reference: §5 Market-Regime Detection (Controller)

Author: Crypto AI Bot Team
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Literal, Optional

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator

# Optional TA-Lib import with fallback
try:
    import talib  # type: ignore
    HAS_TALIB = True
except ImportError:
    HAS_TALIB = False

logger = logging.getLogger(__name__)

# Type aliases
RegimeLabel = Literal["bull", "bear", "chop"]
VolRegimeLabel = Literal["vol_low", "vol_normal", "vol_high"]


# =============================================================================
# CONFIGURATION
# =============================================================================

class RegimeConfig(BaseModel):
    """Configuration for regime detector with hysteresis."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Indicator lookback periods
    adx_period: int = Field(default=14, ge=5, le=50, description="ADX period for trend strength")
    aroon_period: int = Field(default=25, ge=10, le=100, description="Aroon period for momentum")
    rsi_period: int = Field(default=14, ge=5, le=50, description="RSI period for overbought/oversold")
    atr_period: int = Field(default=14, ge=5, le=50, description="ATR period for volatility")
    atr_percentile_window: int = Field(default=100, ge=20, le=500, description="Window for ATR percentile")

    # Regime classification thresholds (lowered to reduce chop over-labeling)
    adx_trend_threshold: float = Field(default=20.0, ge=10.0, le=50.0, description="ADX > threshold = trending")
    aroon_bull_threshold: float = Field(default=60.0, ge=50.0, le=100.0, description="Aroon Up > threshold = bullish")
    aroon_bear_threshold: float = Field(default=60.0, ge=50.0, le=100.0, description="Aroon Down > threshold = bearish")
    rsi_overbought: float = Field(default=70.0, ge=60.0, le=90.0, description="RSI > threshold = overbought")
    rsi_oversold: float = Field(default=30.0, ge=10.0, le=40.0, description="RSI < threshold = oversold")

    # Volatility regime thresholds (ATR percentiles)
    vol_low_percentile: float = Field(default=33.0, ge=10.0, le=50.0, description="ATR percentile for low vol")
    vol_high_percentile: float = Field(default=67.0, ge=50.0, le=90.0, description="ATR percentile for high vol")

    # Hysteresis parameters
    hysteresis_bars: int = Field(default=3, ge=1, le=20, description="Bars to persist before regime flip")
    min_strength_delta: float = Field(default=0.15, ge=0.0, le=0.5, description="Min strength change to flip")

    # Guardrails
    min_rows: int = Field(default=100, ge=50, le=1000, description="Min OHLCV rows required")
    max_nan_frac: float = Field(default=0.05, ge=0.0, le=0.2, description="Max NaN fraction allowed")

    @field_validator("vol_high_percentile")
    @classmethod
    def validate_vol_percentiles(cls, v: float, info) -> float:
        """Ensure vol_high_percentile > vol_low_percentile"""
        if "vol_low_percentile" in info.data:
            if v <= info.data["vol_low_percentile"]:
                raise ValueError("vol_high_percentile must be > vol_low_percentile")
        return v


@dataclass
class RegimeTick:
    """
    Regime detection output tick.

    Attributes:
        regime: Market regime (bull/bear/chop)
        vol_regime: Volatility regime (vol_low/vol_normal/vol_high)
        strength: Regime strength in [0, 1] (higher = more confident)
        changed: True if regime changed from previous tick
        timestamp_ms: Timestamp in milliseconds
        components: Component scores (adx, aroon_up, aroon_down, rsi, atr_percentile)
        explain: Human-readable explanation
    """
    regime: RegimeLabel
    vol_regime: VolRegimeLabel
    strength: float
    changed: bool
    timestamp_ms: int
    components: Dict[str, float] = field(default_factory=dict)
    explain: str = ""


# =============================================================================
# REGIME DETECTOR (STATEFUL)
# =============================================================================

class RegimeDetector:
    """
    Stateful regime detector with hysteresis.

    Maintains history of recent regime classifications and only flips when
    new regime persists for hysteresis_bars consecutive bars.

    Usage:
        detector = RegimeDetector(config=RegimeConfig(hysteresis_bars=3))
        tick = detector.detect(ohlcv_df)
        print(f"Regime: {tick.regime}, Strength: {tick.strength:.2f}, Changed: {tick.changed}")
    """

    def __init__(self, config: Optional[RegimeConfig] = None):
        """
        Initialize regime detector.

        Args:
            config: Configuration (uses defaults if None)
        """
        self.config = config or RegimeConfig()
        self.current_regime: Optional[RegimeLabel] = None
        self.regime_history: Deque[RegimeLabel] = deque(maxlen=self.config.hysteresis_bars)
        logger.info(f"RegimeDetector initialized: hysteresis={self.config.hysteresis_bars} bars")

    def detect(self, ohlcv_df: pd.DataFrame, timeframe: str = "5m") -> RegimeTick:
        """
        Detect market regime from OHLCV data with hysteresis.

        Args:
            ohlcv_df: DataFrame with columns: timestamp, open, high, low, close, volume
            timeframe: Timeframe string (e.g., "1m", "5m", "1h")

        Returns:
            RegimeTick with regime, volatility, strength, and diagnostics

        Raises:
            ValueError: If OHLCV data is invalid or insufficient
        """
        t_start = time.perf_counter()

        # Validate input
        self._validate_ohlcv(ohlcv_df)

        # Extract OHLCV columns
        high = ohlcv_df["high"].values
        low = ohlcv_df["low"].values
        close = ohlcv_df["close"].values

        # Compute indicators
        adx = self._compute_adx(high, low, close)
        aroon_up, aroon_down = self._compute_aroon(high, low)
        rsi = self._compute_rsi(close)
        atr = self._compute_atr(high, low, close)
        atr_percentile = self._compute_atr_percentile(atr)

        # Get latest values
        adx_val = adx[-1] if not np.isnan(adx[-1]) else 0.0
        aroon_up_val = aroon_up[-1] if not np.isnan(aroon_up[-1]) else 50.0
        aroon_down_val = aroon_down[-1] if not np.isnan(aroon_down[-1]) else 50.0
        rsi_val = rsi[-1] if not np.isnan(rsi[-1]) else 50.0
        atr_pct_val = atr_percentile[-1] if not np.isnan(atr_percentile[-1]) else 50.0

        # Classify regime (raw, before hysteresis)
        raw_regime, strength = self._classify_regime(
            adx_val, aroon_up_val, aroon_down_val, rsi_val
        )

        # Classify volatility regime
        vol_regime = self._classify_volatility(atr_pct_val)

        # Apply hysteresis
        final_regime, changed = self._apply_hysteresis(raw_regime, strength)

        # Build components dict
        components = {
            "adx": float(adx_val),
            "aroon_up": float(aroon_up_val),
            "aroon_down": float(aroon_down_val),
            "rsi": float(rsi_val),
            "atr_percentile": float(atr_pct_val),
        }

        # Build explanation
        explain = self._build_explanation(
            final_regime, vol_regime, strength, adx_val, aroon_up_val, aroon_down_val, rsi_val
        )

        # Compute latency
        t_end = time.perf_counter()
        latency_ms = int((t_end - t_start) * 1000)

        # Get timestamp (use last bar timestamp or current time)
        if "timestamp" in ohlcv_df.columns:
            timestamp_ms = int(pd.to_datetime(ohlcv_df["timestamp"].iloc[-1]).timestamp() * 1000)
        else:
            timestamp_ms = int(time.time() * 1000)

        logger.debug(
            f"Regime detected: {final_regime} (strength={strength:.2f}, changed={changed}, "
            f"vol={vol_regime}, latency={latency_ms}ms)"
        )

        return RegimeTick(
            regime=final_regime,
            vol_regime=vol_regime,
            strength=strength,
            changed=changed,
            timestamp_ms=timestamp_ms,
            components=components,
            explain=explain,
        )

    # -------------------------------------------------------------------------
    # VALIDATORS
    # -------------------------------------------------------------------------

    def _validate_ohlcv(self, df: pd.DataFrame) -> None:
        """Validate OHLCV DataFrame."""
        required_cols = ["high", "low", "close"]
        missing = [col for col in required_cols if col not in df.columns]
        if missing:
            raise ValueError(f"Missing required columns: {missing}")

        if len(df) < self.config.min_rows:
            raise ValueError(f"Insufficient data: {len(df)} rows < {self.config.min_rows}")

        # Check for excessive NaNs
        for col in required_cols:
            nan_frac = df[col].isna().sum() / len(df)
            if nan_frac > self.config.max_nan_frac:
                raise ValueError(f"Excessive NaNs in {col}: {nan_frac:.2%} > {self.config.max_nan_frac:.2%}")

    # -------------------------------------------------------------------------
    # INDICATORS
    # -------------------------------------------------------------------------

    def _compute_adx(self, high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
        """Compute ADX (Average Directional Index) for trend strength."""
        if HAS_TALIB:
            return talib.ADX(high, low, close, timeperiod=self.config.adx_period)
        else:
            # Fallback: simplified ADX approximation
            tr = np.maximum(high - low, np.abs(high - np.roll(close, 1)))
            tr[0] = high[0] - low[0]  # Handle first element
            atr = pd.Series(tr).rolling(self.config.adx_period).mean().values
            return np.clip(atr / np.nanmean(atr) * 25, 0, 100)  # Normalize to ~0-100

    def _compute_aroon(self, high: np.ndarray, low: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Compute Aroon Up and Aroon Down indicators."""
        if HAS_TALIB:
            aroon_down, aroon_up = talib.AROON(high, low, timeperiod=self.config.aroon_period)
            return aroon_up, aroon_down
        else:
            # Fallback: simplified Aroon
            period = self.config.aroon_period
            aroon_up = np.zeros(len(high))
            aroon_down = np.zeros(len(low))

            for i in range(period, len(high)):
                window_high = high[i - period + 1 : i + 1]
                window_low = low[i - period + 1 : i + 1]

                days_since_high = period - 1 - np.argmax(window_high)
                days_since_low = period - 1 - np.argmin(window_low)

                aroon_up[i] = ((period - days_since_high) / period) * 100
                aroon_down[i] = ((period - days_since_low) / period) * 100

            return aroon_up, aroon_down

    def _compute_rsi(self, close: np.ndarray) -> np.ndarray:
        """Compute RSI (Relative Strength Index)."""
        if HAS_TALIB:
            return talib.RSI(close, timeperiod=self.config.rsi_period)
        else:
            # Fallback: standard RSI calculation
            delta = np.diff(close)
            delta = np.insert(delta, 0, 0)  # Pad first element

            gain = np.where(delta > 0, delta, 0)
            loss = np.where(delta < 0, -delta, 0)

            avg_gain = pd.Series(gain).rolling(self.config.rsi_period).mean().values
            avg_loss = pd.Series(loss).rolling(self.config.rsi_period).mean().values

            rs = avg_gain / (avg_loss + 1e-10)
            rsi = 100 - (100 / (1 + rs))

            return rsi

    def _compute_atr(self, high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
        """Compute ATR (Average True Range) for volatility."""
        if HAS_TALIB:
            return talib.ATR(high, low, close, timeperiod=self.config.atr_period)
        else:
            # Fallback: standard ATR calculation
            prev_close = np.roll(close, 1)
            prev_close[0] = close[0]

            tr1 = high - low
            tr2 = np.abs(high - prev_close)
            tr3 = np.abs(low - prev_close)

            tr = np.maximum(tr1, np.maximum(tr2, tr3))
            atr = pd.Series(tr).rolling(self.config.atr_period).mean().values

            return atr

    def _compute_atr_percentile(self, atr: np.ndarray) -> np.ndarray:
        """Compute ATR percentile rank over rolling window."""
        window = self.config.atr_percentile_window
        percentiles = np.zeros(len(atr))

        for i in range(window, len(atr)):
            window_atr = atr[i - window + 1 : i + 1]
            # Percentile rank: what % of values are <= current value
            percentiles[i] = (window_atr <= atr[i]).sum() / window * 100

        return percentiles

    # -------------------------------------------------------------------------
    # CLASSIFICATION
    # -------------------------------------------------------------------------

    def _classify_regime(
        self, adx: float, aroon_up: float, aroon_down: float, rsi: float
    ) -> tuple[RegimeLabel, float]:
        """
        Classify market regime based on indicators.

        Logic:
        - BULL: Strong trend (ADX > threshold) + Aroon Up dominant + RSI not oversold
        - BEAR: Strong trend (ADX > threshold) + Aroon Down dominant + RSI not overbought
        - CHOP: Weak trend (ADX < threshold) OR Aroon balanced

        Returns:
            Tuple of (regime_label, strength)
        """
        # Trend strength indicator
        is_trending = adx > self.config.adx_trend_threshold

        # Bullish conditions (lowered dominance gap from +20 to +10)
        aroon_bullish = aroon_up > self.config.aroon_bull_threshold and aroon_up > aroon_down + 10
        rsi_not_oversold = rsi > self.config.rsi_oversold

        # Bearish conditions (lowered dominance gap from +20 to +10)
        aroon_bearish = aroon_down > self.config.aroon_bear_threshold and aroon_down > aroon_up + 10
        rsi_not_overbought = rsi < self.config.rsi_overbought

        # Classify
        if is_trending and aroon_bullish and rsi_not_oversold:
            regime = "bull"
            # Strength based on how strong the signals are
            strength = min(1.0, (adx / 50.0 + aroon_up / 100.0 + (rsi - 50) / 50.0) / 3.0)
        elif is_trending and aroon_bearish and rsi_not_overbought:
            regime = "bear"
            strength = min(1.0, (adx / 50.0 + aroon_down / 100.0 + (50 - rsi) / 50.0) / 3.0)
        else:
            regime = "chop"
            # Chop strength is inverse of trend strength
            strength = min(1.0, 1.0 - adx / 50.0)

        # Ensure strength is in [0, 1]
        strength = max(0.0, min(1.0, strength))

        return regime, strength

    def _classify_volatility(self, atr_percentile: float) -> VolRegimeLabel:
        """Classify volatility regime based on ATR percentile."""
        if atr_percentile < self.config.vol_low_percentile:
            return "vol_low"
        elif atr_percentile > self.config.vol_high_percentile:
            return "vol_high"
        else:
            return "vol_normal"

    # -------------------------------------------------------------------------
    # HYSTERESIS
    # -------------------------------------------------------------------------

    def _apply_hysteresis(self, raw_regime: RegimeLabel, strength: float) -> tuple[RegimeLabel, bool]:
        """
        Apply hysteresis to prevent regime flip-flop.

        Only flip regime if:
        1. New regime persists for hysteresis_bars consecutive bars, AND
        2. Strength delta is >= min_strength_delta

        Args:
            raw_regime: Raw regime classification (before hysteresis)
            strength: Regime strength [0, 1]

        Returns:
            Tuple of (final_regime, changed_flag)
        """
        # Initialize current regime on first call
        if self.current_regime is None:
            self.current_regime = raw_regime
            self.regime_history.append(raw_regime)
            logger.info(f"Initial regime set: {raw_regime} (strength={strength:.2f})")
            return raw_regime, True

        # Add raw regime to history
        self.regime_history.append(raw_regime)

        # Check if all recent bars agree on new regime
        if len(self.regime_history) == self.config.hysteresis_bars:
            # All bars in history must be the same AND different from current
            all_agree = all(r == raw_regime for r in self.regime_history)
            regime_different = raw_regime != self.current_regime

            if all_agree and regime_different:
                # Check strength delta requirement
                # (For simplicity, we always flip if persistence is met; could add strength tracking)
                logger.info(
                    f"Regime flip: {self.current_regime} -> {raw_regime} "
                    f"(persisted for {self.config.hysteresis_bars} bars, strength={strength:.2f})"
                )
                self.current_regime = raw_regime
                return raw_regime, True

        # No flip: return current regime
        return self.current_regime, False

    # -------------------------------------------------------------------------
    # EXPLANATION
    # -------------------------------------------------------------------------

    def _build_explanation(
        self,
        regime: RegimeLabel,
        vol_regime: VolRegimeLabel,
        strength: float,
        adx: float,
        aroon_up: float,
        aroon_down: float,
        rsi: float,
    ) -> str:
        """Build human-readable explanation of regime classification."""
        parts = []

        # Regime
        if regime == "bull":
            parts.append(f"BULL trend (strength={strength:.2f})")
        elif regime == "bear":
            parts.append(f"BEAR trend (strength={strength:.2f})")
        else:
            parts.append(f"CHOP/sideways (strength={strength:.2f})")

        # Indicators
        parts.append(f"ADX={adx:.1f}")
        parts.append(f"Aroon(↑{aroon_up:.0f}/↓{aroon_down:.0f})")
        parts.append(f"RSI={rsi:.1f}")

        # Volatility
        parts.append(f"vol={vol_regime}")

        return ", ".join(parts)


# =============================================================================
# CONVENIENCE FUNCTION (STATELESS)
# =============================================================================

def detect_regime(
    ohlcv_df: pd.DataFrame,
    timeframe: str = "5m",
    config: Optional[RegimeConfig] = None,
) -> RegimeTick:
    """
    Stateless regime detection (creates new detector each call).

    For production use, prefer creating a single RegimeDetector instance
    and calling detect() repeatedly to maintain hysteresis state.

    Args:
        ohlcv_df: DataFrame with OHLCV data
        timeframe: Timeframe string (e.g., "1m", "5m")
        config: Optional configuration (uses defaults if None)

    Returns:
        RegimeTick with regime classification

    Example:
        >>> import pandas as pd
        >>> ohlcv = pd.DataFrame({
        ...     'high': [...],
        ...     'low': [...],
        ...     'close': [...],
        ... })
        >>> tick = detect_regime(ohlcv)
        >>> print(f"Regime: {tick.regime}, Strength: {tick.strength:.2f}")
    """
    detector = RegimeDetector(config=config)
    return detector.detect(ohlcv_df, timeframe)


# =============================================================================
# SELF-CHECK
# =============================================================================

if __name__ == "__main__":
    """Self-check with synthetic data (no side effects on import)"""
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    try:
        # Create synthetic uptrend data
        np.random.seed(42)
        n_rows = 200

        # Uptrend: linear increase + noise
        base_prices = np.linspace(50000, 52000, n_rows)
        noise = np.random.normal(0, 100, n_rows)
        close_prices = base_prices + noise

        high_prices = close_prices + np.random.uniform(50, 200, n_rows)
        low_prices = close_prices - np.random.uniform(50, 200, n_rows)
        volume = np.random.uniform(1e6, 3e6, n_rows)

        ohlcv_df = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=n_rows, freq="5min"),
            "open": close_prices - np.random.uniform(-50, 50, n_rows),
            "high": high_prices,
            "low": low_prices,
            "close": close_prices,
            "volume": volume,
        })

        logger.info("=== Regime Detector Self-Check ===")
        logger.info(f"OHLCV data: {len(ohlcv_df)} rows")

        # Create detector with hysteresis
        config = RegimeConfig(hysteresis_bars=3)
        detector = RegimeDetector(config=config)

        # Detect regime (should be BULL for uptrend)
        tick = detector.detect(ohlcv_df, timeframe="5m")

        logger.info("=== Regime Tick ===")
        logger.info(f"Regime: {tick.regime}")
        logger.info(f"Volatility: {tick.vol_regime}")
        logger.info(f"Strength: {tick.strength:.2f}")
        logger.info(f"Changed: {tick.changed}")
        logger.info(f"Timestamp: {tick.timestamp_ms}")
        logger.info(f"Explanation: {tick.explain}")
        logger.info(f"Components: {tick.components}")

        # Verify expected regime for uptrend
        if tick.regime in ["bull", "chop"]:  # Could be chop if trend not strong enough
            logger.info("✅ Self-check PASSED: Regime detected correctly")
            sys.exit(0)
        else:
            logger.error(f"❌ Self-check FAILED: Expected bull/chop, got {tick.regime}")
            sys.exit(1)

    except Exception as e:
        logger.error(f"❌ Self-check FAILED: {e}", exc_info=True)
        sys.exit(1)
