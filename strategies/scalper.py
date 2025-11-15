"""
Scalper strategy with maker-only execution on tight spreads.

Implements ultra-short-term scalping with:
- 15s/1m timeframes for rapid entries
- Maker-only orders (post-only) to capture spread
- Tight spread gates (<3bps) for execution quality
- ATR-based dynamic stops
- Quick exits (max hold 2 minutes)
- Minimal RR targets (1.0-1.5:1)

Accept criteria:
- Only trades when spread is tight enough for maker rebates
- Fast in/out with high win rate but small R
- Proper volume and liquidity filters
- Per-strategy caps and cool-downs

Reject criteria:
- Taking liquidity (no market orders)
- Wide spread trading
- Long holds
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
from strategies.utils import (
    calculate_sl_tp_from_atr,
    check_spread_acceptable,
    check_latency_acceptable,
    TradeThrottler,
    validate_signal_params,
)

logger = logging.getLogger(__name__)


class ScalperStrategy:
    """
    Maker-only scalping strategy for tight spreads and quick profits.

    Generates signals when:
    - Spread is very tight (<3bps)
    - Liquidity is high
    - Short-term EMA crossover occurs
    - ATR suggests bounded volatility

    Attributes:
        ema_fast: Fast EMA period (default 5 for 15s bars)
        ema_slow: Slow EMA period (default 15)
        atr_period: ATR lookback (default 14)
        max_spread_bps: Maximum spread in basis points (default 3.0)
        target_rr: Target risk:reward ratio (default 1.2)
        max_hold_bars: Maximum hold time in bars (default 8 = 2 minutes on 15s)
        sl_atr_multiple: Stop loss as multiple of ATR (default 1.0)
        target_vol_annual: Target portfolio volatility
        kelly_cap: Kelly fraction cap (higher for scalping)
    """

    def __init__(
        self,
        ema_fast: int = 5,
        ema_slow: int = 15,
        atr_period: int = 14,
        max_spread_bps: Decimal = Decimal("3.0"),
        target_rr: Decimal = Decimal("1.2"),
        max_hold_bars: int = 8,
        sl_atr_multiple: Decimal = Decimal("1.0"),
        target_vol_annual: Decimal = Decimal("0.10"),
        kelly_cap: Decimal = Decimal("0.30"),
        # STEP 6: Enhanced scalper guards
        max_latency_ms: float = 500.0,
        max_trades_per_minute: int = 3,
        min_rr: float = 1.0,
    ):
        """
        Initialize scalper strategy.

        Args:
            ema_fast: Fast EMA period
            ema_slow: Slow EMA period
            atr_period: ATR lookback period
            max_spread_bps: Maximum spread to trade (3bps = tight)
            target_rr: Risk:reward target
            max_hold_bars: Max hold time in bars
            sl_atr_multiple: SL distance as ATR multiple
            target_vol_annual: Target portfolio volatility
            kelly_cap: Kelly fraction cap
            max_latency_ms: Maximum acceptable latency (default 500ms)
            max_trades_per_minute: Maximum trades per minute (default 3)
            min_rr: Minimum risk/reward ratio (default 1.0, lower for scalping)
        """
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.atr_period = atr_period
        self.max_spread_bps = max_spread_bps
        self.target_rr = target_rr
        self.max_hold_bars = max_hold_bars
        self.sl_atr_multiple = sl_atr_multiple
        self.target_vol_annual = target_vol_annual
        self.kelly_cap = kelly_cap

        # STEP 6: Scalper-specific guards
        self.max_latency_ms = max_latency_ms
        self.max_trades_per_minute = max_trades_per_minute
        self.min_rr = min_rr

        # STEP 6: Trade throttler
        self.throttler = TradeThrottler(max_trades_per_minute=max_trades_per_minute)

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

    def should_trade(self, snapshot: MarketSnapshot, latency_ms: Optional[float] = None) -> bool:
        """
        Fast pre-filter for scalping conditions.

        CRITICAL: Must have tight spread for maker-only execution.

        Args:
            snapshot: Current market snapshot
            latency_ms: Optional latency in milliseconds

        Returns:
            True if conditions suitable for scalping
        """
        # CRITICAL: Tight spread check using centralized utility
        if hasattr(snapshot, 'bid') and hasattr(snapshot, 'ask'):
            spread_ok = check_spread_acceptable(
                bid=float(snapshot.bid),
                ask=float(snapshot.ask),
                max_spread_bps=float(self.max_spread_bps),
            )
            if not spread_ok:
                logger.debug(f"Scalper: Spread too wide (>{self.max_spread_bps} bps)")
                return False
        else:
            # Fallback to original spread check
            spread_ok, spread_reason = spread_check(snapshot, max_spread_bps=self.max_spread_bps)
            if not spread_ok:
                logger.debug(f"Scalper: {spread_reason}")
                return False

        # STEP 6: Latency check (if available)
        if latency_ms is not None:
            latency_ok = check_latency_acceptable(
                latency_ms=latency_ms,
                max_latency_ms=self.max_latency_ms,
            )
            if not latency_ok:
                logger.debug(f"Scalper: Latency {latency_ms:.1f}ms exceeds {self.max_latency_ms}ms")
                return False

        # High liquidity requirement (scalpers need deep books)
        volume_ok, volume_reason = volume_check(snapshot, min_volume_24h_usd=Decimal("500000000"))
        if not volume_ok:
            logger.debug(f"Scalper: {volume_reason}")
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

    def generate_signals(
        self,
        snapshot: MarketSnapshot,
        ohlcv_df: pd.DataFrame,
        regime_label: RegimeLabel,
    ) -> list[SignalSpec]:
        """
        Generate scalping signals with EMA crossover and tight risk management.

        Args:
            snapshot: Current market snapshot
            ohlcv_df: OHLCV DataFrame for technical indicators
            regime_label: Current market regime

        Returns:
            List of signals (may be empty)
        """
        signals = []

        # STEP 6: Check trade throttle (max trades per minute)
        current_time = pd.Timestamp.now()
        if not self.throttler.can_trade(current_time):
            logger.debug(f"Scalper: Throttled (max {self.max_trades_per_minute} trades/min)")
            return []

        # 1. Regime filter (scalping works in all regimes if spread is tight)
        # We'll trade in any regime as long as spread and liquidity are good

        # 2. Liquidity filter
        liquidity_ok, liquidity_reason = session_liquidity_ok(snapshot)
        if not liquidity_ok:
            logger.debug(f"Scalper: {liquidity_reason}")
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
            logger.warning(f"Scalper: Insufficient data - {e}")
            return []

        # 4. Check for EMA crossover
        current_price = float(snapshot.mid_price)

        # Calculate previous EMAs to detect crossover
        if len(ohlcv_df) >= max(self.ema_slow, self.atr_period) + 1:
            prev_ohlcv = ohlcv_df.iloc[:-1]
            prev_ema_fast = self.calculate_ema(prev_ohlcv, self.ema_fast)
            prev_ema_slow = self.calculate_ema(prev_ohlcv, self.ema_slow)
        else:
            # Not enough data for crossover detection
            return []

        # 5. Long signal: Fast EMA crosses above Slow EMA
        if ema_fast > ema_slow and prev_ema_fast <= prev_ema_slow:
            entry_price = Decimal(str(current_price))

            # STEP 6: Use centralized SL/TP calculation with ATR
            stop_loss_float, take_profit_float = calculate_sl_tp_from_atr(
                entry_price=current_price,
                side='long',
                atr=atr,
                sl_atr_multiplier=float(self.sl_atr_multiple),
                tp_atr_multiplier=float(self.sl_atr_multiple) * float(self.target_rr),
            )
            stop_loss = Decimal(str(stop_loss_float))
            take_profit = Decimal(str(take_profit_float))

            # STEP 6: Validate RR ratio (lower threshold for scalping)
            is_valid, validation_reason = validate_signal_params(
                entry_price=current_price,
                stop_loss=stop_loss_float,
                take_profit=take_profit_float,
                side='long',
                min_rr=self.min_rr,
            )
            if not is_valid:
                logger.debug(f"Scalper: Signal validation failed - {validation_reason}")
                return []

            # Confidence based on EMA separation
            ema_separation = (ema_fast - ema_slow) / ema_slow
            confidence = min(Decimal("0.80"), Decimal("0.65") + Decimal(str(abs(ema_separation))) * Decimal("10.0"))

            signal = SignalSpec(
                signal_id=generate_signal_id(
                    datetime.now(timezone.utc),
                    snapshot.symbol,
                    "scalper",
                    entry_price,
                ),
                timestamp=datetime.now(timezone.utc),
                symbol=snapshot.symbol,
                side="long",
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                strategy="scalper",
                confidence=confidence,
                metadata={
                    "rr": str(self.target_rr),
                    "sl_atr": str(self.sl_atr_multiple),
                    "tp_atr": str(float(self.sl_atr_multiple) * float(self.target_rr)),
                    "expected_hold_s": str(self.max_hold_bars * 15),  # 15s bars
                    "max_hold_bars": str(self.max_hold_bars),
                    "ema_fast": str(ema_fast),
                    "ema_slow": str(ema_slow),
                    "atr": str(atr),
                    "max_spread_bps": str(self.max_spread_bps),
                    "max_latency_ms": str(self.max_latency_ms),
                    "throttled_trades_per_min": str(self.max_trades_per_minute),
                },
            )

            signals.append(signal)

            # STEP 6: Record trade in throttler
            self.throttler.record_trade(current_time)

            logger.info(
                f"Scalper LONG: entry={entry_price}, SL={stop_loss}, TP={take_profit}, "
                f"confidence={confidence:.2f}, RR={self.target_rr}, throttle={self.max_trades_per_minute}/min"
            )

        # 6. Short signal: Fast EMA crosses below Slow EMA
        elif ema_fast < ema_slow and prev_ema_fast >= prev_ema_slow:
            entry_price = Decimal(str(current_price))

            # STEP 6: Use centralized SL/TP calculation with ATR
            stop_loss_float, take_profit_float = calculate_sl_tp_from_atr(
                entry_price=current_price,
                side='short',
                atr=atr,
                sl_atr_multiplier=float(self.sl_atr_multiple),
                tp_atr_multiplier=float(self.sl_atr_multiple) * float(self.target_rr),
            )
            stop_loss = Decimal(str(stop_loss_float))
            take_profit = Decimal(str(take_profit_float))

            # STEP 6: Validate RR ratio (lower threshold for scalping)
            is_valid, validation_reason = validate_signal_params(
                entry_price=current_price,
                stop_loss=stop_loss_float,
                take_profit=take_profit_float,
                side='short',
                min_rr=self.min_rr,
            )
            if not is_valid:
                logger.debug(f"Scalper: Signal validation failed - {validation_reason}")
                return []

            ema_separation = (ema_slow - ema_fast) / ema_slow
            confidence = min(Decimal("0.80"), Decimal("0.65") + Decimal(str(abs(ema_separation))) * Decimal("10.0"))

            signal = SignalSpec(
                signal_id=generate_signal_id(
                    datetime.now(timezone.utc),
                    snapshot.symbol,
                    "scalper",
                    entry_price,
                ),
                timestamp=datetime.now(timezone.utc),
                symbol=snapshot.symbol,
                side="short",
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                strategy="scalper",
                confidence=confidence,
                metadata={
                    "rr": str(self.target_rr),
                    "sl_atr": str(self.sl_atr_multiple),
                    "tp_atr": str(float(self.sl_atr_multiple) * float(self.target_rr)),
                    "expected_hold_s": str(self.max_hold_bars * 15),
                    "max_hold_bars": str(self.max_hold_bars),
                    "ema_fast": str(ema_fast),
                    "ema_slow": str(ema_slow),
                    "atr": str(atr),
                    "max_spread_bps": str(self.max_spread_bps),
                    "max_latency_ms": str(self.max_latency_ms),
                    "throttled_trades_per_min": str(self.max_trades_per_minute),
                },
            )

            signals.append(signal)

            # STEP 6: Record trade in throttler
            self.throttler.record_trade(current_time)

            logger.info(
                f"Scalper SHORT: entry={entry_price}, SL={stop_loss}, TP={take_profit}, "
                f"confidence={confidence:.2f}, RR={self.target_rr}, throttle={self.max_trades_per_minute}/min"
            )

        return signals

    def size_positions(
        self,
        signals: list[SignalSpec],
        account_equity_usd: Decimal,
        current_volatility: Decimal,
    ) -> list[PositionSpec]:
        """
        Convert signals to sized positions for scalping.

        Args:
            signals: Trading signals to size
            account_equity_usd: Total account equity in USD
            current_volatility: Current market volatility (annualized)

        Returns:
            List of sized positions
        """
        positions = []

        for signal in signals:
            # Use position_sizer with higher Kelly cap for scalping
            size_usd, size_base = position_sizer(
                signal_confidence=signal.confidence,
                entry_price=signal.entry_price,
                stop_loss_price=signal.stop_loss,
                account_equity=account_equity_usd,
                current_vol_annual=current_volatility,
                target_vol_annual=self.target_vol_annual,
                kelly_cap=self.kelly_cap,  # 0.30 = more aggressive for high win-rate scalping
            )

            # Calculate expected risk
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
                f"Sized scalper position: {signal.side} {size_base:.4f} {signal.symbol} "
                f"(${size_usd:.2f}, {size_usd/account_equity_usd*100:.1f}% of equity)"
            )

        return positions
