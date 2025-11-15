"""
Micro-trend strategy for capturing short-term drift on 3m/5m timeframes.

Implements trend-following on micro timeframes with:
- EMA crossovers (9/21 on 3m/5m bars)
- ATR gates to avoid choppy periods
- Trend strength filters
- Medium RR targets (1.5-2.0:1)
- Moderate hold times (5-15 minutes)

Accept criteria:
- Trades only when clear micro-trend detected
- ATR filter prevents whipsaw in chop
- Proper spread and volume gates
- Designed for "drift days" with sustained directional moves

Reject criteria:
- Trading in high-ATR chaos
- No trend confirmation
- Ignoring regime context
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import numpy as np
import pandas as pd

from ai_engine.schemas import MarketSnapshot, RegimeLabel
from strategies.api import SignalSpec, PositionSpec, generate_signal_id
from strategies.filters import regime_check, session_liquidity_ok, spread_check, volume_check
from strategies.sizing import position_sizer

logger = logging.getLogger(__name__)


class MicroTrendStrategy:
    """
    Micro-trend strategy for 3m/5m drift capture.

    Generates signals when:
    - EMA crossover occurs (9 crosses 21)
    - ATR is in acceptable range (not too choppy, not dead)
    - Trend strength exceeds threshold
    - Volume and spread are acceptable

    Attributes:
        ema_fast: Fast EMA period (default 9)
        ema_slow: Slow EMA period (default 21)
        atr_period: ATR lookback (default 14)
        min_trend_strength: Minimum EMA separation for signal (default 0.003 = 0.3%)
        max_atr_pct: Maximum ATR as % of price (default 0.015 = 1.5%)
        min_atr_pct: Minimum ATR as % of price (default 0.003 = 0.3%)
        target_rr: Target risk:reward ratio (default 1.8)
        sl_atr_multiple: Stop loss as multiple of ATR (default 1.5)
        target_vol_annual: Target portfolio volatility
        kelly_cap: Kelly fraction cap
    """

    def __init__(
        self,
        ema_fast: int = 9,
        ema_slow: int = 21,
        atr_period: int = 14,
        min_trend_strength: Decimal = Decimal("0.003"),
        max_atr_pct: Decimal = Decimal("0.015"),
        min_atr_pct: Decimal = Decimal("0.003"),
        target_rr: Decimal = Decimal("1.8"),
        sl_atr_multiple: Decimal = Decimal("1.5"),
        target_vol_annual: Decimal = Decimal("0.10"),
        kelly_cap: Decimal = Decimal("0.25"),
    ):
        """
        Initialize micro-trend strategy.

        Args:
            ema_fast: Fast EMA period
            ema_slow: Slow EMA period
            atr_period: ATR lookback period
            min_trend_strength: Minimum EMA separation (as fraction)
            max_atr_pct: Maximum ATR as % of price
            min_atr_pct: Minimum ATR as % of price
            target_rr: Risk:reward target
            sl_atr_multiple: SL distance as ATR multiple
            target_vol_annual: Target portfolio volatility
            kelly_cap: Kelly fraction cap
        """
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.atr_period = atr_period
        self.min_trend_strength = min_trend_strength
        self.max_atr_pct = max_atr_pct
        self.min_atr_pct = min_atr_pct
        self.target_rr = target_rr
        self.sl_atr_multiple = sl_atr_multiple
        self.target_vol_annual = target_vol_annual
        self.kelly_cap = kelly_cap

        # Cache
        self._cached_ema_fast: Optional[float] = None
        self._cached_ema_slow: Optional[float] = None
        self._cached_atr: Optional[float] = None

    def prepare(self, snapshot: MarketSnapshot, ohlcv_df: pd.DataFrame) -> None:
        """
        Prepare strategy by caching expensive calculations.

        Args:
            snapshot: Current market snapshot
            ohlcv_df: OHLCV DataFrame for calculations
        """
        self._cached_ema_fast = None
        self._cached_ema_slow = None
        self._cached_atr = None

        if len(ohlcv_df) >= max(self.ema_slow, self.atr_period):
            self._cached_ema_fast = self.calculate_ema(ohlcv_df, self.ema_fast)
            self._cached_ema_slow = self.calculate_ema(ohlcv_df, self.ema_slow)
            self._cached_atr = self.calculate_atr(ohlcv_df)

    def should_trade(self, snapshot: MarketSnapshot) -> bool:
        """
        Fast pre-filter for micro-trend conditions.

        Args:
            snapshot: Current market snapshot

        Returns:
            True if conditions suitable for trend trading
        """
        # Spread check (looser than scalper, but still reasonable)
        spread_ok, spread_reason = spread_check(snapshot, max_spread_bps=Decimal("15.0"))
        if not spread_ok:
            logger.debug(f"Micro-trend: {spread_reason}")
            return False

        # Volume check
        volume_ok, volume_reason = volume_check(snapshot, min_volume_24h_usd=Decimal("200000000"))
        if not volume_ok:
            logger.debug(f"Micro-trend: {volume_reason}")
            return False

        return True

    def calculate_ema(self, ohlcv_df: pd.DataFrame, period: int) -> float:
        """
        Calculate Exponential Moving Average.

        Args:
            ohlcv_df: OHLCV DataFrame
            period: EMA period

        Returns:
            Current EMA value
        """
        if len(ohlcv_df) < period:
            raise ValueError(f"Insufficient data: need {period}, got {len(ohlcv_df)}")

        close = ohlcv_df["close"].values
        ema = pd.Series(close).ewm(span=period, adjust=False).mean().values[-1]

        logger.debug(f"EMA({period}): {ema:.2f}")
        return float(ema)

    def calculate_atr(self, ohlcv_df: pd.DataFrame) -> float:
        """
        Calculate Average True Range.

        Args:
            ohlcv_df: OHLCV DataFrame

        Returns:
            ATR value
        """
        if len(ohlcv_df) < self.atr_period + 1:
            raise ValueError(f"Insufficient data: need {self.atr_period + 1}, got {len(ohlcv_df)}")

        high = ohlcv_df["high"].values
        low = ohlcv_df["low"].values
        close = ohlcv_df["close"].values

        tr = []
        for i in range(1, len(ohlcv_df)):
            h_l = high[i] - low[i]
            h_pc = abs(high[i] - close[i-1])
            l_pc = abs(low[i] - close[i-1])
            tr.append(max(h_l, h_pc, l_pc))

        atr = np.mean(tr[-self.atr_period:])
        logger.debug(f"ATR({self.atr_period}): {atr:.2f}")
        return float(atr)

    def check_atr_range(self, atr: float, current_price: float) -> tuple[bool, str]:
        """
        Check if ATR is in acceptable range (not too choppy, not too dead).

        Args:
            atr: Current ATR value
            current_price: Current market price

        Returns:
            Tuple of (is_acceptable, reason)
        """
        atr_pct = atr / current_price

        if atr_pct > float(self.max_atr_pct):
            return False, f"ATR too high ({atr_pct*100:.2f}% > {float(self.max_atr_pct)*100:.2f}%)"

        if atr_pct < float(self.min_atr_pct):
            return False, f"ATR too low ({atr_pct*100:.2f}% < {float(self.min_atr_pct)*100:.2f}%)"

        return True, f"ATR in range ({atr_pct*100:.2f}%)"

    def calculate_trend_strength(self, ema_fast: float, ema_slow: float) -> float:
        """
        Calculate trend strength as EMA separation.

        Args:
            ema_fast: Fast EMA value
            ema_slow: Slow EMA value

        Returns:
            Trend strength (separation as fraction)
        """
        return abs(ema_fast - ema_slow) / ema_slow

    def generate_signals(
        self,
        snapshot: MarketSnapshot,
        ohlcv_df: pd.DataFrame,
        regime_label: RegimeLabel,
    ) -> list[SignalSpec]:
        """
        Generate micro-trend signals with EMA crossover and ATR gates.

        Args:
            snapshot: Current market snapshot
            ohlcv_df: OHLCV DataFrame for technical indicators
            regime_label: Current market regime

        Returns:
            List of signals (may be empty)
        """
        signals = []

        # 1. Regime filter (works best in trending regimes)
        regime_ok, regime_reason = regime_check(regime_label, [RegimeLabel.BULL, RegimeLabel.BEAR])
        if not regime_ok:
            logger.debug(f"Micro-trend: {regime_reason}")
            return []

        # 2. Liquidity filter
        liquidity_ok, liquidity_reason = session_liquidity_ok(snapshot)
        if not liquidity_ok:
            logger.debug(f"Micro-trend: {liquidity_reason}")
            return []

        # 3. Calculate indicators (use cache if available)
        try:
            if self._cached_ema_fast is not None:
                ema_fast = self._cached_ema_fast
            else:
                ema_fast = self.calculate_ema(ohlcv_df, self.ema_fast)

            if self._cached_ema_slow is not None:
                ema_slow = self._cached_ema_slow
            else:
                ema_slow = self.calculate_ema(ohlcv_df, self.ema_slow)

            if self._cached_atr is not None:
                atr = self._cached_atr
            else:
                atr = self.calculate_atr(ohlcv_df)
        except ValueError as e:
            logger.warning(f"Micro-trend: Insufficient data - {e}")
            return []

        # 4. ATR gate (must be in acceptable range)
        current_price = float(snapshot.mid_price)
        atr_ok, atr_reason = self.check_atr_range(atr, current_price)
        if not atr_ok:
            logger.debug(f"Micro-trend: {atr_reason}")
            return []

        # 5. Check trend strength
        trend_strength = self.calculate_trend_strength(ema_fast, ema_slow)
        if trend_strength < float(self.min_trend_strength):
            logger.debug(f"Micro-trend: Trend too weak ({trend_strength*100:.2f}% < {float(self.min_trend_strength)*100:.2f}%)")
            return []

        # 6. Calculate previous EMAs to detect crossover
        if len(ohlcv_df) >= max(self.ema_slow, self.atr_period) + 1:
            prev_ohlcv = ohlcv_df.iloc[:-1]
            prev_ema_fast = self.calculate_ema(prev_ohlcv, self.ema_fast)
            prev_ema_slow = self.calculate_ema(prev_ohlcv, self.ema_slow)
        else:
            return []

        # 7. Long signal: Fast EMA crosses above Slow EMA
        if ema_fast > ema_slow and prev_ema_fast <= prev_ema_slow:
            entry_price = Decimal(str(current_price))

            # Stop loss based on ATR
            stop_loss = Decimal(str(current_price - atr * float(self.sl_atr_multiple)))

            # Target profit based on RR ratio
            risk_distance = float(entry_price - stop_loss)
            take_profit = Decimal(str(current_price + risk_distance * float(self.target_rr)))

            # Confidence based on trend strength
            confidence = min(
                Decimal("0.85"),
                Decimal("0.60") + Decimal(str(trend_strength)) * Decimal("50.0")
            )

            signal = SignalSpec(
                signal_id=generate_signal_id(
                    datetime.now(timezone.utc),
                    snapshot.symbol,
                    "micro_trend",
                    entry_price,
                ),
                timestamp=datetime.now(timezone.utc),
                symbol=snapshot.symbol,
                side="long",
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                strategy="micro_trend",
                confidence=confidence,
                metadata={
                    "rr": str(self.target_rr),
                    "sl_atr": str(self.sl_atr_multiple),
                    "tp_atr": str(float(self.sl_atr_multiple) * float(self.target_rr)),
                    "expected_hold_s": str(300),  # ~5 minutes expected
                    "trend_strength": str(trend_strength),
                    "atr_pct": str(atr / current_price),
                },
            )

            signals.append(signal)
            logger.info(
                f"Micro-trend LONG: entry={entry_price}, SL={stop_loss}, TP={take_profit}, "
                f"confidence={confidence:.2f}, trend_strength={trend_strength*100:.2f}%"
            )

        # 8. Short signal: Fast EMA crosses below Slow EMA
        elif ema_fast < ema_slow and prev_ema_fast >= prev_ema_slow:
            entry_price = Decimal(str(current_price))

            stop_loss = Decimal(str(current_price + atr * float(self.sl_atr_multiple)))

            risk_distance = float(stop_loss - entry_price)
            take_profit = Decimal(str(current_price - risk_distance * float(self.target_rr)))

            confidence = min(
                Decimal("0.85"),
                Decimal("0.60") + Decimal(str(trend_strength)) * Decimal("50.0")
            )

            signal = SignalSpec(
                signal_id=generate_signal_id(
                    datetime.now(timezone.utc),
                    snapshot.symbol,
                    "micro_trend",
                    entry_price,
                ),
                timestamp=datetime.now(timezone.utc),
                symbol=snapshot.symbol,
                side="short",
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                strategy="micro_trend",
                confidence=confidence,
                metadata={
                    "rr": str(self.target_rr),
                    "sl_atr": str(self.sl_atr_multiple),
                    "tp_atr": str(float(self.sl_atr_multiple) * float(self.target_rr)),
                    "expected_hold_s": str(300),
                    "trend_strength": str(trend_strength),
                    "atr_pct": str(atr / current_price),
                },
            )

            signals.append(signal)
            logger.info(
                f"Micro-trend SHORT: entry={entry_price}, SL={stop_loss}, TP={take_profit}, "
                f"confidence={confidence:.2f}, trend_strength={trend_strength*100:.2f}%"
            )

        return signals

    def size_positions(
        self,
        signals: list[SignalSpec],
        account_equity_usd: Decimal,
        current_volatility: Decimal,
    ) -> list[PositionSpec]:
        """
        Convert signals to sized positions.

        Args:
            signals: Trading signals to size
            account_equity_usd: Total account equity in USD
            current_volatility: Current market volatility (annualized)

        Returns:
            List of sized positions
        """
        positions = []

        for signal in signals:
            size_usd, size_base = position_sizer(
                signal_confidence=signal.confidence,
                entry_price=signal.entry_price,
                stop_loss_price=signal.stop_loss,
                account_equity=account_equity_usd,
                current_vol_annual=current_volatility,
                target_vol_annual=self.target_vol_annual,
                kelly_cap=self.kelly_cap,
            )

            price_distance = abs(signal.entry_price - signal.stop_loss)
            expected_risk_usd = size_base * price_distance

            position = PositionSpec(
                signal_id=signal.signal_id,
                symbol=signal.symbol,
                side=signal.side,
                size=size_base,
                notional_usd=size_usd,
                entry_price=signal.entry_price,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                expected_risk_usd=expected_risk_usd,
                volatility_adjusted=True,
                kelly_fraction=None,
            )

            positions.append(position)
            logger.info(
                f"Sized micro-trend position: {signal.side} {size_base:.4f} {signal.symbol} "
                f"(${size_usd:.2f}, {size_usd/account_equity_usd*100:.1f}% of equity)"
            )

        return positions
