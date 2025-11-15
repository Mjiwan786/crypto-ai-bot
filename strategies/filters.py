"""
Universal trade filters to avoid unfavorable conditions.

Implements pure, deterministic filters for:
- ATR cooldown (avoid trading during low volatility)
- Session liquidity (avoid illiquid trading sessions)
- Regime checks (only trade in favorable market regimes)
- News shock blocking (avoid trading during major news events)

Accept criteria:
- Deterministic (no network calls)
- Easy to unit test
- Pure functions
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal
from typing import Optional

import pandas as pd

from ai_engine.schemas import MarketSnapshot, RegimeLabel

logger = logging.getLogger(__name__)


def atr_cooldown(
    snapshot: MarketSnapshot,
    ohlcv_df: pd.DataFrame,
    lookback: int = 14,
    min_atr_pct: Decimal = Decimal("0.005"),
) -> tuple[bool, str]:
    """
    Check if ATR (volatility) is sufficient for trading.

    Avoids trading during extremely low volatility periods where
    spreads dominate profits.

    Args:
        snapshot: Current market snapshot
        ohlcv_df: OHLCV DataFrame for ATR calculation
        lookback: ATR lookback period (default 14)
        min_atr_pct: Minimum ATR as % of price (default 0.5%)

    Returns:
        Tuple of (should_trade, reason)

    Example:
        >>> should_trade, reason = atr_cooldown(snapshot, df)
        >>> if not should_trade:
        ...     print(f"Skipping trade: {reason}")
        Skipping trade: ATR too low (0.3% < 0.5% threshold)
    """
    if len(ohlcv_df) < lookback:
        return False, f"Insufficient data for ATR ({len(ohlcv_df)} < {lookback})"

    # Calculate True Range
    high = ohlcv_df["high"].values
    low = ohlcv_df["low"].values
    close = ohlcv_df["close"].values

    tr = []
    for i in range(1, len(ohlcv_df)):
        h_l = high[i] - low[i]
        h_pc = abs(high[i] - close[i-1])
        l_pc = abs(low[i] - close[i-1])
        tr.append(max(h_l, h_pc, l_pc))

    # ATR (simple moving average of TR)
    if len(tr) < lookback:
        return False, f"Insufficient TR data ({len(tr)} < {lookback})"

    atr = sum(tr[-lookback:]) / lookback

    # ATR as percentage of current price
    atr_pct = Decimal(str(atr)) / Decimal(str(snapshot.mid_price))

    # Check if ATR meets minimum
    if atr_pct < min_atr_pct:
        return False, f"ATR too low ({atr_pct*100:.2f}% < {min_atr_pct*100:.1f}% threshold)"

    logger.debug(f"ATR check passed: {atr_pct*100:.2f}% (threshold: {min_atr_pct*100:.1f}%)")
    return True, "ATR sufficient"


def session_liquidity_ok(
    snapshot: MarketSnapshot,
    illiquid_hours: Optional[list[tuple[time, time]]] = None,
) -> tuple[bool, str]:
    """
    Check if current time is in liquid trading session.

    Avoids trading during illiquid hours (e.g., Asian session for USD pairs).

    Args:
        snapshot: Current market snapshot
        illiquid_hours: List of (start_time, end_time) tuples for illiquid periods
                       (default: 00:00-06:00 UTC for crypto)

    Returns:
        Tuple of (is_liquid, reason)

    Example:
        >>> should_trade, reason = session_liquidity_ok(snapshot)
        >>> if not should_trade:
        ...     print(f"Skipping trade: {reason}")
        Skipping trade: Illiquid session (02:00 UTC is in 00:00-06:00 range)
    """
    # Default illiquid hours (UTC): 00:00-06:00
    if illiquid_hours is None:
        illiquid_hours = [(time(0, 0), time(6, 0))]

    # Get current time from snapshot
    current_time = datetime.fromtimestamp(snapshot.timestamp_ms / 1000).time()

    # Check if current time falls in any illiquid period
    for start, end in illiquid_hours:
        # Handle periods that cross midnight
        if start <= end:
            # Normal period (e.g., 00:00-06:00)
            if start <= current_time <= end:
                return False, f"Illiquid session ({current_time.strftime('%H:%M')} UTC is in {start.strftime('%H:%M')}-{end.strftime('%H:%M')} range)"
        else:
            # Period crosses midnight (e.g., 22:00-02:00)
            if current_time >= start or current_time <= end:
                return False, f"Illiquid session ({current_time.strftime('%H:%M')} UTC crosses midnight)"

    logger.debug(f"Liquidity check passed: {current_time.strftime('%H:%M')} UTC is liquid")
    return True, "Liquid session"


def regime_check(
    regime_label: RegimeLabel,
    allowed_regimes: list[RegimeLabel],
) -> tuple[bool, str]:
    """
    Check if current regime is favorable for trading.

    Args:
        regime_label: Current market regime
        allowed_regimes: List of regimes where strategy should trade

    Returns:
        Tuple of (regime_ok, reason)

    Example:
        >>> should_trade, reason = regime_check(
        ...     RegimeLabel.CHOP,
        ...     [RegimeLabel.BULL, RegimeLabel.BEAR]
        ... )
        >>> if not should_trade:
        ...     print(f"Skipping trade: {reason}")
        Skipping trade: Unfavorable regime (chop not in [bull, bear])
    """
    if regime_label in allowed_regimes:
        logger.debug(f"Regime check passed: {regime_label.value} is in {[r.value for r in allowed_regimes]}")
        return True, f"Favorable regime ({regime_label.value})"

    return False, f"Unfavorable regime ({regime_label.value} not in {[r.value for r in allowed_regimes]})"


def news_shock_block(
    snapshot: MarketSnapshot,
    news_shock_flag: bool = False,
    cooldown_seconds: int = 300,
) -> tuple[bool, str]:
    """
    Block trading during major news shocks.

    Uses news_shock_flag from snapshot (populated by upstream systems).
    Pure logic - doesn't fetch news directly.

    Args:
        snapshot: Current market snapshot
        news_shock_flag: Whether a news shock is detected (from snapshot metadata)
        cooldown_seconds: Seconds to wait after news shock (default 300 = 5 minutes)

    Returns:
        Tuple of (can_trade, reason)

    Note:
        In production, news_shock_flag would be populated by a news monitor
        that watches economic calendars, crypto news, etc.

    Example:
        >>> should_trade, reason = news_shock_block(snapshot, news_shock_flag=True)
        >>> if not should_trade:
        ...     print(f"Skipping trade: {reason}")
        Skipping trade: News shock detected, waiting for cooldown (5 min)
    """
    if news_shock_flag:
        return False, f"News shock detected, waiting for cooldown ({cooldown_seconds}s)"

    # Could also check snapshot metadata for recent shocks
    # (implementation would depend on how shock timestamps are stored)

    logger.debug("News shock check passed: no active shocks")
    return True, "No news shocks"


def spread_check(
    snapshot: MarketSnapshot,
    max_spread_bps: Decimal = Decimal("20.0"),
) -> tuple[bool, str]:
    """
    Check if bid-ask spread is acceptable.

    Wide spreads eat into profits, especially for scalping strategies.

    Args:
        snapshot: Current market snapshot
        max_spread_bps: Maximum acceptable spread in basis points (default 20 bps)

    Returns:
        Tuple of (spread_ok, reason)

    Example:
        >>> should_trade, reason = spread_check(snapshot)
        >>> if not should_trade:
        ...     print(f"Skipping trade: {reason}")
        Skipping trade: Spread too wide (35 bps > 20 bps threshold)
    """
    spread_bps = Decimal(str(snapshot.spread_bps))

    if spread_bps > max_spread_bps:
        return False, f"Spread too wide ({spread_bps:.1f} bps > {max_spread_bps:.0f} bps threshold)"

    logger.debug(f"Spread check passed: {spread_bps:.1f} bps (threshold: {max_spread_bps:.0f} bps)")
    return True, "Spread acceptable"


def volume_check(
    snapshot: MarketSnapshot,
    min_volume_24h_usd: Decimal = Decimal("100000000"),  # $100M default
) -> tuple[bool, str]:
    """
    Check if 24h volume is sufficient for trading.

    Low volume pairs have poor liquidity and high slippage.

    Args:
        snapshot: Current market snapshot
        min_volume_24h_usd: Minimum 24h volume in USD (default $100M)

    Returns:
        Tuple of (volume_ok, reason)

    Example:
        >>> should_trade, reason = volume_check(snapshot)
        >>> if not should_trade:
        ...     print(f"Skipping trade: {reason}")
        Skipping trade: Low volume ($50M < $100M threshold)
    """
    volume_24h = Decimal(str(snapshot.volume_24h))

    if volume_24h < min_volume_24h_usd:
        return False, f"Low volume (${float(volume_24h)/1e6:.1f}M < ${float(min_volume_24h_usd)/1e6:.0f}M threshold)"

    logger.debug(f"Volume check passed: ${float(volume_24h)/1e6:.1f}M (threshold: ${float(min_volume_24h_usd)/1e6:.0f}M)")
    return True, "Volume sufficient"


def apply_all_filters(
    snapshot: MarketSnapshot,
    ohlcv_df: pd.DataFrame,
    regime_label: RegimeLabel,
    allowed_regimes: list[RegimeLabel],
    news_shock_flag: bool = False,
) -> tuple[bool, list[str]]:
    """
    Apply all trade filters in sequence.

    Returns early on first failure for efficiency.

    Args:
        snapshot: Current market snapshot
        ohlcv_df: OHLCV DataFrame for technical filters
        regime_label: Current market regime
        allowed_regimes: List of acceptable regimes
        news_shock_flag: Whether news shock is detected

    Returns:
        Tuple of (all_passed, list_of_reasons)

    Example:
        >>> passed, reasons = apply_all_filters(
        ...     snapshot, df, RegimeLabel.BULL, [RegimeLabel.BULL]
        ... )
        >>> if not passed:
        ...     print(f"Filters failed: {', '.join(reasons)}")
    """
    reasons = []

    # 1. Regime check (fastest, check first)
    regime_ok, regime_reason = regime_check(regime_label, allowed_regimes)
    if not regime_ok:
        reasons.append(regime_reason)
        return False, reasons

    # 2. News shock check (fast, no computation)
    news_ok, news_reason = news_shock_block(snapshot, news_shock_flag)
    if not news_ok:
        reasons.append(news_reason)
        return False, reasons

    # 3. Spread check (fast)
    spread_ok, spread_reason = spread_check(snapshot)
    if not spread_ok:
        reasons.append(spread_reason)
        return False, reasons

    # 4. Volume check (fast)
    volume_ok, volume_reason = volume_check(snapshot)
    if not volume_ok:
        reasons.append(volume_reason)
        return False, reasons

    # 5. Session liquidity check (fast)
    liquidity_ok, liquidity_reason = session_liquidity_ok(snapshot)
    if not liquidity_ok:
        reasons.append(liquidity_reason)
        return False, reasons

    # 6. ATR check (slower, requires computation)
    atr_ok, atr_reason = atr_cooldown(snapshot, ohlcv_df)
    if not atr_ok:
        reasons.append(atr_reason)
        return False, reasons

    # All filters passed
    reasons.append("All filters passed")
    return True, reasons


# =============================================================================
# SELF-CHECK
# =============================================================================

if __name__ == "__main__":
    """Self-check: Test trade filters"""
    import sys
    import numpy as np

    logging.basicConfig(level=logging.INFO)

    try:
        # Create test snapshot
        snapshot = MarketSnapshot(
            symbol="BTC/USD",
            timeframe="1h",
            timestamp_ms=1704067200000,  # 2024-01-01 00:00:00 UTC
            mid_price=50000.0,
            spread_bps=10.0,
            volume_24h=500000000.0,  # $500M
        )

        # Create test OHLCV data
        np.random.seed(42)
        n = 100
        ohlcv_df = pd.DataFrame({
            "high": np.random.normal(50500, 500, n),
            "low": np.random.normal(49500, 500, n),
            "close": np.random.normal(50000, 500, n),
        })

        # Test 1: ATR check
        atr_ok, atr_reason = atr_cooldown(snapshot, ohlcv_df)
        assert isinstance(atr_ok, bool), "ATR check should return bool"

        # Test 2: Session liquidity (should fail during illiquid hours)
        liquid_ok, liquid_reason = session_liquidity_ok(snapshot)
        assert isinstance(liquid_ok, bool), "Liquidity check should return bool"

        # Test 3: Regime check (favorable)
        regime_ok, regime_reason = regime_check(
            RegimeLabel.BULL,
            [RegimeLabel.BULL, RegimeLabel.BEAR]
        )
        assert regime_ok is True, "Bull should be in allowed regimes"

        # Test 4: Regime check (unfavorable)
        regime_bad, regime_bad_reason = regime_check(
            RegimeLabel.CHOP,
            [RegimeLabel.BULL, RegimeLabel.BEAR]
        )
        assert regime_bad is False, "Chop should not be in allowed regimes"

        # Test 5: News shock check
        news_ok, news_reason = news_shock_block(snapshot, news_shock_flag=False)
        assert news_ok is True, "Should trade when no news shock"

        news_blocked, news_blocked_reason = news_shock_block(snapshot, news_shock_flag=True)
        assert news_blocked is False, "Should not trade during news shock"

        # Test 6: Spread check
        spread_ok, spread_reason = spread_check(snapshot, max_spread_bps=Decimal("20.0"))
        assert spread_ok is True, "10 bps spread should pass 20 bps threshold"

        # Test 7: Volume check
        volume_ok, volume_reason = volume_check(snapshot, min_volume_24h_usd=Decimal("100000000"))
        assert volume_ok is True, "$500M should pass $100M threshold"

        # Test 8: Apply all filters
        all_ok, all_reasons = apply_all_filters(
            snapshot,
            ohlcv_df,
            RegimeLabel.BULL,
            [RegimeLabel.BULL],
            news_shock_flag=False,
        )
        assert isinstance(all_ok, bool), "Combined filters should return bool"

        print("\nPASS Trade Filters Self-Check:")
        print(f"  - ATR check: {atr_reason}")
        print(f"  - Liquidity check: {liquid_reason}")
        print(f"  - Regime check (favorable): {regime_reason}")
        print(f"  - Regime check (unfavorable): {regime_bad_reason}")
        print(f"  - News shock (no shock): {news_reason}")
        print(f"  - News shock (active): {news_blocked_reason}")
        print(f"  - Spread check: {spread_reason}")
        print(f"  - Volume check: {volume_reason}")
        print(f"  - Combined filters: {', '.join(all_reasons)}")

    except Exception as e:
        print(f"\nFAIL Trade Filters Self-Check: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


# =============================================================================
# REGIME DETECTION FILTERS (24/7 THROTTLING)
# =============================================================================


@dataclass
class RegimeMetrics:
    """Regime detection metrics"""

    ema50: float
    ema200: float
    atr14: float
    close: float
    trend_strength_pct: float  # |EMA50 - EMA200| / close * 100
    atr_pct: float  # ATR / close * 100
    volume_ratio: float  # Current volume / avg volume
    bars_total: int
    bars_passed: int
    pass_rate: float  # bars_passed / bars_total


class RegimeGate:
    """
    Base regime gate with EMA50/EMA200 and ATR(14) calculations.

    Philosophy: Never "sleep" (24/7), but throttle by passing fewer bars.
    """

    def __init__(
        self,
        k: float = 1.5,
        min_atr_pct: float = 0.4,
        max_atr_pct: float = 3.0,
        min_volume_ratio: float = 0.5,
        lookback_periods: int = 100,
    ):
        """
        Initialize regime gate.

        Args:
            k: Trend strength multiplier (higher = stricter trend requirement)
            min_atr_pct: Minimum ATR% to pass (volatility floor)
            max_atr_pct: Maximum ATR% to pass (volatility ceiling)
            min_volume_ratio: Minimum volume ratio vs average
            lookback_periods: Periods for volume average calculation
        """
        self.k = k
        self.min_atr_pct = min_atr_pct
        self.max_atr_pct = max_atr_pct
        self.min_volume_ratio = min_volume_ratio
        self.lookback_periods = lookback_periods

        # Metrics tracking
        self.bars_total = 0
        self.bars_passed = 0
        self.last_metrics: Optional[RegimeMetrics] = None

        logger.info(
            f"RegimeGate initialized: k={k}, "
            f"atr_range=[{min_atr_pct:.1f}%, {max_atr_pct:.1f}%], "
            f"min_vol_ratio={min_volume_ratio:.1f}"
        )

    def calculate_metrics(self, ohlcv_df: pd.DataFrame) -> Optional[RegimeMetrics]:
        """
        Calculate regime metrics from OHLCV data.

        Args:
            ohlcv_df: DataFrame with OHLCV data

        Returns:
            RegimeMetrics or None if insufficient data
        """
        if len(ohlcv_df) < 200:
            logger.debug(f"Insufficient data: {len(ohlcv_df)} bars, need 200")
            return None

        try:
            # Calculate EMAs
            ema50 = ohlcv_df["close"].ewm(span=50, adjust=False).mean().iloc[-1]
            ema200 = ohlcv_df["close"].ewm(span=200, adjust=False).mean().iloc[-1]

            # Calculate ATR(14)
            import numpy as np

            high_low = ohlcv_df["high"] - ohlcv_df["low"]
            high_close = np.abs(ohlcv_df["high"] - ohlcv_df["close"].shift())
            low_close = np.abs(ohlcv_df["low"] - ohlcv_df["close"].shift())

            true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
            atr14 = true_range.rolling(window=14).mean().iloc[-1]

            # Current close
            close = ohlcv_df["close"].iloc[-1]

            # Trend strength: |EMA50 - EMA200| / close * 100
            trend_strength_pct = (abs(ema50 - ema200) / close) * 100

            # ATR percentage: ATR / close * 100
            atr_pct = (atr14 / close) * 100

            # Volume ratio: current volume / average volume
            avg_volume = ohlcv_df["volume"].tail(self.lookback_periods).mean()
            current_volume = ohlcv_df["volume"].iloc[-1]
            volume_ratio = current_volume / max(avg_volume, 1e-9)

            # Pass rate
            pass_rate = (self.bars_passed / max(self.bars_total, 1)) * 100

            metrics = RegimeMetrics(
                ema50=ema50,
                ema200=ema200,
                atr14=atr14,
                close=close,
                trend_strength_pct=trend_strength_pct,
                atr_pct=atr_pct,
                volume_ratio=volume_ratio,
                bars_total=self.bars_total,
                bars_passed=self.bars_passed,
                pass_rate=pass_rate,
            )

            self.last_metrics = metrics
            return metrics

        except Exception as e:
            logger.error(f"Error calculating regime metrics: {e}")
            return None

    def should_trade(self, ohlcv_df: pd.DataFrame) -> bool:
        """Override in subclasses"""
        raise NotImplementedError("Subclasses must implement should_trade()")

    def get_metrics(self) -> Optional[RegimeMetrics]:
        """Get last calculated metrics"""
        return self.last_metrics

    def reset_stats(self) -> None:
        """Reset bars_total and bars_passed counters"""
        self.bars_total = 0
        self.bars_passed = 0


class TrendGate(RegimeGate):
    """
    Trend gate for momentum/breakout strategies.

    Gate Logic:
        PASS if (|EMA50-EMA200|/close) > k * (ATR/close)
            AND min_atr_pct <= ATR% <= max_atr_pct
            AND volume_ratio >= min_volume_ratio
    """

    def should_trade(self, ohlcv_df: pd.DataFrame) -> bool:
        """Check if bar passes trend gate"""
        self.bars_total += 1

        metrics = self.calculate_metrics(ohlcv_df)
        if not metrics:
            return False

        # Gate 1: Trend strength > k * ATR
        trend_gate = metrics.trend_strength_pct > (self.k * metrics.atr_pct)

        # Gate 2: ATR range check
        atr_gate = self.min_atr_pct <= metrics.atr_pct <= self.max_atr_pct

        # Gate 3: Volume check
        volume_gate = metrics.volume_ratio >= self.min_volume_ratio

        passed = trend_gate and atr_gate and volume_gate

        if passed:
            self.bars_passed += 1

        # Log every 100 bars
        if self.bars_total % 100 == 0:
            logger.info(
                f"TrendGate: {self.bars_passed}/{self.bars_total} bars passed "
                f"({metrics.pass_rate:.1f}%)"
            )

        return passed


class ChopGate(RegimeGate):
    """
    Chop gate for mean reversion strategies.

    Gate Logic (INVERTED from trend):
        PASS if (|EMA50-EMA200|/close) <= k * (ATR/close)
            AND ATR% <= max_atr_pct
            AND volume_ratio >= min_volume_ratio
    """

    def __init__(
        self,
        k: float = 1.0,
        max_atr_pct: float = 1.5,
        min_volume_ratio: float = 0.5,
        lookback_periods: int = 100,
    ):
        super().__init__(
            k=k,
            min_atr_pct=0.0,  # No minimum for chop
            max_atr_pct=max_atr_pct,
            min_volume_ratio=min_volume_ratio,
            lookback_periods=lookback_periods,
        )

    def should_trade(self, ohlcv_df: pd.DataFrame) -> bool:
        """Check if bar passes chop gate (inverted trend logic)"""
        self.bars_total += 1

        metrics = self.calculate_metrics(ohlcv_df)
        if not metrics:
            return False

        # Gate 1: Chop check (INVERTED)
        chop_gate = metrics.trend_strength_pct <= (self.k * metrics.atr_pct)

        # Gate 2: Low ATR
        atr_gate = metrics.atr_pct <= self.max_atr_pct

        # Gate 3: Volume
        volume_gate = metrics.volume_ratio >= self.min_volume_ratio

        passed = chop_gate and atr_gate and volume_gate

        if passed:
            self.bars_passed += 1

        # Log every 100 bars
        if self.bars_total % 100 == 0:
            logger.info(
                f"ChopGate: {self.bars_passed}/{self.bars_total} bars passed "
                f"({metrics.pass_rate:.1f}%)"
            )

        return passed
