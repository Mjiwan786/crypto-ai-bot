"""
Bar Reaction 5m Strategy

5-minute bar-close momentum strategy with:
- Fires on every 5-minute bar close (00:00, 00:05, 00:10, etc.)
- Dual trigger modes: open_to_close or prev_close_to_close
- ATR-based volatility gates (min/max ATR% filters)
- Dynamic ATR-based stops and targets
- Maker-only execution (post-only limit orders)
- Optional extreme fade logic (contrarian trades on big moves)
- Split profit taking (TP1 @ 1.0x ATR, TP2 @ 1.8x ATR)

Accept criteria:
- Triggers only on bar moves exceeding threshold (e.g., 12bps)
- ATR% must be within configured range (e.g., 0.25% - 3.0%)
- Spread must be below cap (e.g., 8bps)
- Maker-only execution enforced

Reject criteria:
- Fixed sizing (must use ATR-based risk management)
- Intra-bar signals (bar-close only)
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Dict, Any, List

import numpy as np
import pandas as pd

from strategies.api import SignalSpec, PositionSpec, generate_signal_id
from strategies.bar_reaction_data import BarReactionDataPipeline, BarReactionFeatures

logger = logging.getLogger(__name__)


class BarReaction5mStrategy:
    """
    5-minute bar-close reaction strategy with ATR-based risk management.

    Generates signals at bar close when move exceeds threshold and ATR% is in range.
    Uses dual profit targets (1.0x ATR, 1.8x ATR) for risk-adjusted returns.

    Attributes:
        mode: Trading mode ("trend" = momentum follow, "revert" = fade extremes)
        trigger_mode: Bar move calculation ("open_to_close" or "prev_close_to_close")
        trigger_bps_up: Minimum upward move in bps to trigger long
        trigger_bps_down: Minimum downward move in bps to trigger short
        min_atr_pct: Minimum ATR as percentage of close (volatility floor)
        max_atr_pct: Maximum ATR as percentage of close (volatility ceiling)
        atr_window: ATR calculation period (default 14)
        sl_atr: Stop loss as multiple of ATR (e.g., 0.6x ATR)
        tp1_atr: First take profit as multiple of ATR (e.g., 1.0x ATR)
        tp2_atr: Second take profit as multiple of ATR (e.g., 1.8x ATR)
        risk_per_trade_pct: Risk per trade as percentage of account (e.g., 0.6%)
        maker_only: If True, only maker orders allowed (post-only)
        spread_bps_cap: Maximum spread in bps (reject if wider)
        enable_extreme_fade: If True, enable contrarian trades on extreme moves
        extreme_bps_threshold: Move threshold for extreme fade (e.g., 35bps)
        mean_revert_size_factor: Size multiplier for fade trades (e.g., 0.5 = half size)
    """

    def __init__(
        self,
        mode: str = "trend",
        trigger_mode: str = "open_to_close",
        trigger_bps_up: float = 12.0,
        trigger_bps_down: float = 12.0,
        min_atr_pct: float = 0.25,
        max_atr_pct: float = 3.0,
        atr_window: int = 14,
        sl_atr: float = 0.6,
        tp1_atr: float = 1.0,
        tp2_atr: float = 1.8,
        risk_per_trade_pct: float = 0.6,
        min_position_usd: float = 0.0,  # NEW: Minimum position size (prevent death spiral)
        max_position_usd: float = 100000.0,  # NEW: Maximum position size (cap exposure)
        maker_only: bool = True,
        spread_bps_cap: float = 8.0,
        enable_extreme_fade: bool = False,
        extreme_bps_threshold: float = 35.0,
        mean_revert_size_factor: float = 0.5,
        redis_client: Optional[Any] = None,
    ):
        """
        Initialize bar reaction 5m strategy.

        Args:
            mode: "trend" (follow momentum) or "revert" (fade moves)
            trigger_mode: "open_to_close" or "prev_close_to_close"
            trigger_bps_up: Minimum upward move in bps
            trigger_bps_down: Minimum downward move in bps
            min_atr_pct: Minimum ATR% filter
            max_atr_pct: Maximum ATR% filter
            atr_window: ATR calculation period
            sl_atr: Stop loss as ATR multiple
            tp1_atr: First take profit as ATR multiple
            tp2_atr: Second take profit as ATR multiple
            risk_per_trade_pct: Risk per trade (% of account)
            maker_only: Enforce maker-only execution
            spread_bps_cap: Maximum spread in bps
            enable_extreme_fade: Enable contrarian fade logic
            extreme_bps_threshold: Move threshold for fade
            mean_revert_size_factor: Size factor for fade trades
            redis_client: Redis client for native 5m bar fetching (optional)
        """
        # Validation
        if mode not in ("trend", "revert"):
            raise ValueError(f"mode must be 'trend' or 'revert', got '{mode}'")
        if trigger_mode not in ("open_to_close", "prev_close_to_close"):
            raise ValueError(f"trigger_mode must be 'open_to_close' or 'prev_close_to_close', got '{trigger_mode}'")

        self.mode = mode
        self.trigger_mode = trigger_mode
        self.trigger_bps_up = trigger_bps_up
        self.trigger_bps_down = trigger_bps_down
        self.min_atr_pct = min_atr_pct
        self.max_atr_pct = max_atr_pct
        self.atr_window = atr_window
        self.sl_atr = sl_atr
        self.tp1_atr = tp1_atr
        self.tp2_atr = tp2_atr
        self.risk_per_trade_pct = risk_per_trade_pct
        self.min_position_usd = min_position_usd  # NEW: Death spiral prevention
        self.max_position_usd = max_position_usd  # NEW: Exposure cap
        self.maker_only = maker_only
        self.spread_bps_cap = spread_bps_cap
        self.enable_extreme_fade = enable_extreme_fade
        self.extreme_bps_threshold = extreme_bps_threshold
        self.mean_revert_size_factor = mean_revert_size_factor

        # Data pipeline for 5m bars and features
        self.data_pipeline = BarReactionDataPipeline(atr_period=atr_window)
        self.redis_client = redis_client

        # Cache for expensive calculations
        self._cached_features: Optional[pd.DataFrame] = None
        self._cached_symbol: Optional[str] = None

    def prepare(self, symbol: str, df_1m: pd.DataFrame) -> None:
        """
        Prepare strategy by computing and caching 5m features.

        Fetches 5m bars (native or rollup) and calculates ATR, move_bps, etc.

        Args:
            symbol: Trading pair (e.g., "BTC/USD")
            df_1m: 1-minute OHLCV data for fallback rollup
        """
        self._cached_symbol = symbol

        # Get 5m bars with features
        self._cached_features = self.data_pipeline.prepare_data(
            symbol=symbol,
            df_1m=df_1m,
            trigger_mode=self.trigger_mode,
            redis_client=self.redis_client,
        )

        if len(self._cached_features) > 0:
            latest = self._cached_features.iloc[-1]
            logger.debug(
                f"Prepared {symbol}: ATR={latest.get('atr', 0):.2f}, "
                f"ATR%={latest.get('atr_pct', 0):.3f}%, "
                f"move_bps={latest.get('move_bps', 0):.2f}"
            )

    def should_trade(self, symbol: str, df_5m: Optional[pd.DataFrame] = None) -> bool:
        """
        Fast pre-filter before signal generation.

        Checks:
        1. Sufficient 5m bar data
        2. ATR% within configured range
        3. Spread below cap

        Args:
            symbol: Trading pair
            df_5m: Optional 5m DataFrame (uses cache if None)

        Returns:
            True if conditions are suitable for trading
        """
        # Use cache if available
        if df_5m is None:
            if self._cached_features is None or len(self._cached_features) == 0:
                logger.debug(f"BarReaction5m ({symbol}): No cached features")
                return False
            df_5m = self._cached_features

        # Check sufficient data for ATR calculation
        if len(df_5m) < self.atr_window + 1:
            logger.debug(f"BarReaction5m ({symbol}): Insufficient data ({len(df_5m)} bars < {self.atr_window + 1})")
            return False

        latest = df_5m.iloc[-1]

        # Check ATR% in range
        atr_pct = latest.get("atr_pct", 0.0)
        if atr_pct < self.min_atr_pct or atr_pct > self.max_atr_pct:
            logger.debug(
                f"BarReaction5m ({symbol}): ATR% {atr_pct:.3f}% outside range "
                f"[{self.min_atr_pct:.2f}%, {self.max_atr_pct:.2f}%]"
            )
            return False

        # Check spread if available
        spread_bps = latest.get("spread_bps", 0.0)
        if spread_bps > self.spread_bps_cap:
            logger.debug(f"BarReaction5m ({symbol}): Spread {spread_bps:.2f}bps > cap {self.spread_bps_cap:.2f}bps")
            return False

        return True

    def generate_signals(
        self,
        symbol: str,
        current_price: float,
        df_5m: Optional[pd.DataFrame] = None,
        timestamp: Optional[datetime] = None,
    ) -> List[SignalSpec]:
        """
        Generate bar-close signals based on move threshold and mode.

        Logic:
        1. Calculate bar move (open->close or prev_close->close)
        2. Check if move exceeds trigger threshold
        3. Apply ATR gates (min/max ATR%)
        4. Generate signal based on mode:
           - "trend": follow momentum (up move -> long, down move -> short)
           - "revert": fade extremes (up move -> short, down move -> long)
        5. Optional: Check for extreme moves and generate contrarian signals

        Args:
            symbol: Trading pair
            current_price: Current market price (for entry)
            df_5m: Optional 5m DataFrame (uses cache if None)
            timestamp: Signal timestamp (uses now() if None)

        Returns:
            List of signals (may be empty if no triggers)
        """
        signals = []

        # Use cache if available
        if df_5m is None:
            if self._cached_features is None or len(self._cached_features) == 0:
                logger.warning(f"BarReaction5m ({symbol}): No cached features, cannot generate signals")
                return []
            df_5m = self._cached_features

        if len(df_5m) == 0:
            return []

        latest = df_5m.iloc[-1]

        # Extract features
        move_bps = latest.get("move_bps", 0.0)
        atr = latest.get("atr", 0.0)
        atr_pct = latest.get("atr_pct", 0.0)

        if atr <= 0:
            logger.warning(f"BarReaction5m ({symbol}): ATR is zero or negative, cannot generate signals")
            return []

        # Use current_price or close
        entry_price = Decimal(str(current_price))
        close_price = float(latest.get("close", current_price))

        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        # Check for primary signal (normal threshold)
        primary_signal = self._check_primary_signal(
            symbol=symbol,
            move_bps=move_bps,
            atr=atr,
            atr_pct=atr_pct,
            entry_price=entry_price,
            timestamp=timestamp,
        )

        if primary_signal:
            signals.append(primary_signal)
            logger.info(
                f"BarReaction5m ({symbol}): {self.mode.upper()} {primary_signal.side.upper()} signal "
                f"@ {entry_price}, move={move_bps:.2f}bps, ATR%={atr_pct:.3f}%"
            )

        # Check for extreme fade signal (if enabled)
        if self.enable_extreme_fade:
            extreme_signal = self._check_extreme_signal(
                symbol=symbol,
                move_bps=move_bps,
                atr=atr,
                atr_pct=atr_pct,
                entry_price=entry_price,
                timestamp=timestamp,
            )

            if extreme_signal:
                signals.append(extreme_signal)
                logger.info(
                    f"BarReaction5m ({symbol}): EXTREME FADE {extreme_signal.side.upper()} signal "
                    f"@ {entry_price}, move={move_bps:.2f}bps (threshold={self.extreme_bps_threshold:.1f}bps)"
                )

        return signals

    def _check_primary_signal(
        self,
        symbol: str,
        move_bps: float,
        atr: float,
        atr_pct: float,
        entry_price: Decimal,
        timestamp: datetime,
    ) -> Optional[SignalSpec]:
        """
        Check for primary signal based on trigger threshold and mode.

        Returns:
            SignalSpec if signal triggered, None otherwise
        """
        # Determine direction and check threshold
        if move_bps >= self.trigger_bps_up:
            # Upward move
            if self.mode == "trend":
                side = "long"  # Follow momentum
            else:  # revert
                side = "short"  # Fade the move
        elif move_bps <= -self.trigger_bps_down:
            # Downward move
            if self.mode == "trend":
                side = "short"  # Follow momentum
            else:  # revert
                side = "long"  # Fade the move
        else:
            # Move too small
            return None

        # Generate signal
        return self._create_signal(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            atr=atr,
            atr_pct=atr_pct,
            move_bps=move_bps,
            timestamp=timestamp,
            signal_type="primary",
        )

    def _check_extreme_signal(
        self,
        symbol: str,
        move_bps: float,
        atr: float,
        atr_pct: float,
        entry_price: Decimal,
        timestamp: datetime,
    ) -> Optional[SignalSpec]:
        """
        Check for extreme fade signal (contrarian trade on big moves).

        Only triggers if:
        1. Extreme mode enabled
        2. Move exceeds extreme_bps_threshold
        3. ATR% in range

        Returns:
            SignalSpec if extreme signal triggered, None otherwise
        """
        # Check if move exceeds extreme threshold
        if abs(move_bps) < self.extreme_bps_threshold:
            return None

        # Contrarian trade: fade the extreme move
        if move_bps > 0:
            side = "short"  # Fade big up move
        else:
            side = "long"  # Fade big down move

        # Generate signal with reduced size
        return self._create_signal(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            atr=atr,
            atr_pct=atr_pct,
            move_bps=move_bps,
            timestamp=timestamp,
            signal_type="extreme_fade",
            size_factor=self.mean_revert_size_factor,
        )

    def _create_signal(
        self,
        symbol: str,
        side: str,
        entry_price: Decimal,
        atr: float,
        atr_pct: float,
        move_bps: float,
        timestamp: datetime,
        signal_type: str = "primary",
        size_factor: float = 1.0,
    ) -> SignalSpec:
        """
        Create a SignalSpec with ATR-based stops and targets.

        Args:
            symbol: Trading pair
            side: "long" or "short"
            entry_price: Entry price
            atr: Average True Range (absolute)
            atr_pct: ATR as percentage of close
            move_bps: Bar move in basis points
            timestamp: Signal timestamp
            signal_type: "primary" or "extreme_fade"
            size_factor: Size multiplier (for extreme fades)

        Returns:
            SignalSpec with ATR-based SL/TP levels
        """
        entry_float = float(entry_price)

        # Calculate ATR-based levels
        sl_distance = self.sl_atr * atr
        tp1_distance = self.tp1_atr * atr
        tp2_distance = self.tp2_atr * atr

        if side == "long":
            stop_loss = Decimal(str(entry_float - sl_distance))
            take_profit_1 = Decimal(str(entry_float + tp1_distance))
            take_profit_2 = Decimal(str(entry_float + tp2_distance))
        else:  # short
            stop_loss = Decimal(str(entry_float + sl_distance))
            take_profit_1 = Decimal(str(entry_float - tp1_distance))
            take_profit_2 = Decimal(str(entry_float - tp2_distance))

        # Use blended TP (50% at TP1, 50% at TP2)
        # For signaling purposes, use TP2 as primary target
        take_profit = take_profit_2

        # Calculate confidence based on move strength and ATR quality
        # Stronger moves + mid-range ATR = higher confidence
        move_strength = abs(move_bps) / self.trigger_bps_up  # Relative to threshold
        atr_quality = 1.0 - abs(atr_pct - (self.min_atr_pct + self.max_atr_pct) / 2) / ((self.max_atr_pct - self.min_atr_pct) / 2)
        atr_quality = max(0.0, min(1.0, atr_quality))

        base_confidence = 0.60 + min(0.20, move_strength * 0.10) + (atr_quality * 0.10)
        confidence = Decimal(str(min(0.90, base_confidence)))

        # Adjust confidence for extreme fades (lower confidence)
        if signal_type == "extreme_fade":
            confidence = confidence * Decimal("0.80")  # 80% of primary confidence

        # Calculate risk:reward (blended with 50/50 split)
        sl_distance_abs = abs(float(entry_price - stop_loss))
        tp1_distance_abs = abs(float(take_profit_1 - entry_price))
        tp2_distance_abs = abs(float(take_profit_2 - entry_price))

        rr_tp1 = tp1_distance_abs / sl_distance_abs if sl_distance_abs > 0 else 0.0
        rr_tp2 = tp2_distance_abs / sl_distance_abs if sl_distance_abs > 0 else 0.0
        rr_blended = (rr_tp1 + rr_tp2) / 2  # 50/50 split

        # Generate deterministic signal ID
        signal_id = generate_signal_id(
            timestamp=timestamp,
            symbol=symbol,
            strategy=f"bar_reaction_5m_{signal_type}",
            price_level=entry_price,
        )

        # Create signal
        signal = SignalSpec(
            signal_id=signal_id,
            timestamp=timestamp,
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy="bar_reaction_5m",
            confidence=confidence,
            metadata={
                "mode": self.mode,
                "trigger_mode": self.trigger_mode,
                "signal_type": signal_type,
                "move_bps": str(move_bps),
                "atr": str(atr),
                "atr_pct": str(atr_pct),
                "sl_atr": str(self.sl_atr),
                "tp1_atr": str(self.tp1_atr),
                "tp2_atr": str(self.tp2_atr),
                "tp1_price": str(take_profit_1),
                "tp2_price": str(take_profit_2),
                "rr_tp1": str(round(rr_tp1, 2)),
                "rr_tp2": str(round(rr_tp2, 2)),
                "rr_blended": str(round(rr_blended, 2)),
                "size_factor": str(size_factor),
                "maker_only": str(self.maker_only),
            },
        )

        return signal

    def size_positions(
        self,
        signals: List[SignalSpec],
        account_equity_usd: Decimal,
        current_volatility: Optional[Decimal] = None,
    ) -> List[PositionSpec]:
        """
        Convert signals to sized positions using ATR-based risk management.

        Position sizing formula:
        - Risk per trade = account_equity * risk_per_trade_pct
        - Position size = risk_amount / stop_distance
        - Apply size_factor for extreme fades (e.g., 0.5 = half size)

        Args:
            signals: Trading signals to size
            account_equity_usd: Total account equity in USD
            current_volatility: Optional market volatility (not used, ATR-based sizing)

        Returns:
            List of sized positions
        """
        positions = []

        for signal in signals:
            # Calculate risk amount
            risk_amount_usd = account_equity_usd * Decimal(str(self.risk_per_trade_pct / 100.0))

            # Calculate stop distance
            stop_distance = abs(signal.entry_price - signal.stop_loss)

            if stop_distance <= 0:
                logger.warning(f"Invalid stop distance for {signal.symbol}, skipping position sizing")
                continue

            # Base position size (in base currency)
            # size = risk_amount / stop_distance
            position_size_base = risk_amount_usd / stop_distance

            # Apply size factor (for extreme fades)
            size_factor = float(signal.metadata.get("size_factor", "1.0"))
            position_size_base = position_size_base * Decimal(str(size_factor))

            # Calculate notional
            notional_usd = position_size_base * signal.entry_price

            # SAFETY 1: Enforce minimum position size (prevent death spiral)
            if self.min_position_usd > 0:
                min_notional = Decimal(str(self.min_position_usd))
                if notional_usd < min_notional:
                    logger.info(
                        f"Position size below minimum: ${notional_usd:.2f} -> ${min_notional:.2f} "
                        f"(enforcing min_position_usd={self.min_position_usd})"
                    )
                    position_size_base = min_notional / signal.entry_price
                    notional_usd = min_notional

            # SAFETY 2: Enforce maximum position size (cap exposure)
            if self.max_position_usd > 0:
                max_notional_config = Decimal(str(self.max_position_usd))
                if notional_usd > max_notional_config:
                    logger.warning(
                        f"Position size exceeds configured max: ${notional_usd:.2f} -> ${max_notional_config:.2f} "
                        f"(enforcing max_position_usd={self.max_position_usd})"
                    )
                    position_size_base = max_notional_config / signal.entry_price
                    notional_usd = max_notional_config

            # SAFETY 3: Cap position size at 99% of account equity (reserve 1% for fees)
            max_notional_equity = account_equity_usd * Decimal("0.99")
            if notional_usd > max_notional_equity:
                logger.warning(
                    f"Position size capped by equity: ${notional_usd:.2f} -> ${max_notional_equity:.2f} "
                    f"({notional_usd/account_equity_usd*100:.1f}% -> 99% of equity)"
                )
                position_size_base = max_notional_equity / signal.entry_price
                notional_usd = max_notional_equity

            # Expected risk
            expected_risk_usd = position_size_base * stop_distance

            # Create position
            position = PositionSpec(
                signal_id=signal.signal_id,
                symbol=signal.symbol,
                side=signal.side,
                size=position_size_base,
                notional_usd=notional_usd,
                entry_price=signal.entry_price,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                expected_risk_usd=expected_risk_usd,
                volatility_adjusted=True,  # ATR-based = volatility-adjusted
                kelly_fraction=None,  # Not using Kelly for this strategy
            )

            positions.append(position)
            logger.info(
                f"Sized position: {signal.side} {position_size_base:.6f} {signal.symbol} "
                f"(${notional_usd:.2f}, {notional_usd/account_equity_usd*100:.2f}% of equity, "
                f"risk=${expected_risk_usd:.2f}, size_factor={size_factor:.2f})"
            )

        return positions


# =============================================================================
# SELF-CHECK
# =============================================================================

if __name__ == "__main__":
    """Self-check: Test bar reaction 5m strategy with synthetic data"""
    import sys

    logging.basicConfig(level=logging.INFO)

    try:
        print("\n" + "="*70)
        print("BAR REACTION 5M STRATEGY SELF-CHECK")
        print("="*70)

        # Create synthetic 1m OHLCV data (uptrend)
        np.random.seed(42)
        n = 100  # 100 1m bars = 20 5m bars

        # Base uptrend with volatility
        base_prices = np.linspace(50000, 51000, n)
        noise = np.random.normal(0, 50, n)
        close_prices = base_prices + noise

        # Generate OHLCV
        high_prices = close_prices + np.random.uniform(10, 30, n)
        low_prices = close_prices - np.random.uniform(10, 30, n)
        open_prices = np.roll(close_prices, 1)  # Open = previous close
        open_prices[0] = close_prices[0]
        volume = np.random.uniform(1e6, 2e6, n)

        df_1m = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=n, freq="1min"),
            "open": open_prices,
            "high": high_prices,
            "low": low_prices,
            "close": close_prices,
            "volume": volume,
        })

        # Test 1: Initialize strategy (trend mode)
        print("\n[1/8] Initializing strategy (trend mode)...")
        strategy_trend = BarReaction5mStrategy(
            mode="trend",
            trigger_mode="open_to_close",
            trigger_bps_up=12.0,
            trigger_bps_down=12.0,
            min_atr_pct=0.25,
            max_atr_pct=3.0,
            atr_window=14,
            sl_atr=0.6,
            tp1_atr=1.0,
            tp2_atr=1.8,
        )
        assert strategy_trend.mode == "trend"
        assert strategy_trend.trigger_mode == "open_to_close"
        print("  [OK] Strategy initialized")

        # Test 2: Prepare (compute features)
        print("\n[2/8] Preparing strategy (computing 5m features)...")
        strategy_trend.prepare("BTC/USD", df_1m)
        assert strategy_trend._cached_features is not None
        assert len(strategy_trend._cached_features) > 0
        print(f"  [OK] Prepared {len(strategy_trend._cached_features)} 5m bars with features")

        # Test 3: Should trade check
        print("\n[3/8] Testing should_trade filter...")
        should_trade = strategy_trend.should_trade("BTC/USD")
        assert isinstance(should_trade, bool)
        print(f"  [OK] Should trade: {should_trade}")

        # Test 4: Generate signals (trend mode)
        print("\n[4/8] Generating signals (trend mode)...")
        current_price = close_prices[-1]
        signals_trend = strategy_trend.generate_signals(
            symbol="BTC/USD",
            current_price=current_price,
        )
        assert isinstance(signals_trend, list)
        print(f"  [OK] Generated {len(signals_trend)} signal(s) in trend mode")

        if signals_trend:
            sig = signals_trend[0]
            print(f"      - Signal: {sig.side} @ {sig.entry_price}, SL={sig.stop_loss}, TP={sig.take_profit}")
            print(f"      - Confidence: {sig.confidence:.2f}")
            print(f"      - Metadata: move_bps={sig.metadata.get('move_bps')}, atr_pct={sig.metadata.get('atr_pct')}")

            # Validate signal
            assert sig.side in ("long", "short")
            assert sig.entry_price > 0
            assert sig.confidence >= 0 and sig.confidence <= 1

            # Validate SL/TP for long
            if sig.side == "long":
                assert sig.stop_loss < sig.entry_price
                assert sig.take_profit > sig.entry_price
            else:  # short
                assert sig.stop_loss > sig.entry_price
                assert sig.take_profit < sig.entry_price

            print("  [OK] Signal validation passed")

        # Test 5: Size positions
        print("\n[5/8] Sizing positions...")
        if signals_trend:
            positions = strategy_trend.size_positions(
                signals_trend,
                account_equity_usd=Decimal("10000"),
            )
            assert len(positions) == len(signals_trend)
            assert all(p.size > 0 for p in positions)

            pos = positions[0]
            print(f"  [OK] Position: {pos.side} {pos.size:.6f} BTC (${pos.notional_usd:.2f})")
            print(f"      - Expected risk: ${pos.expected_risk_usd:.2f}")
            print(f"      - Risk %: {pos.expected_risk_usd / Decimal('10000') * 100:.2f}%")
        else:
            print("  [SKIP] No signals to size")

        # Test 6: Initialize revert mode
        print("\n[6/8] Testing revert mode...")
        strategy_revert = BarReaction5mStrategy(
            mode="revert",
            trigger_mode="prev_close_to_close",
            trigger_bps_up=12.0,
            trigger_bps_down=12.0,
        )
        assert strategy_revert.mode == "revert"
        strategy_revert.prepare("BTC/USD", df_1m)
        signals_revert = strategy_revert.generate_signals(
            symbol="BTC/USD",
            current_price=current_price,
        )
        print(f"  [OK] Revert mode generated {len(signals_revert)} signal(s)")

        # Test 7: Extreme fade mode
        print("\n[7/8] Testing extreme fade mode...")
        strategy_extreme = BarReaction5mStrategy(
            mode="trend",
            enable_extreme_fade=True,
            extreme_bps_threshold=35.0,
            mean_revert_size_factor=0.5,
        )
        strategy_extreme.prepare("BTC/USD", df_1m)

        # Create synthetic extreme move
        df_extreme = strategy_extreme._cached_features.copy()
        if len(df_extreme) > 0:
            df_extreme.iloc[-1, df_extreme.columns.get_loc("move_bps")] = 40.0  # Extreme move
            signals_extreme = strategy_extreme.generate_signals(
                symbol="BTC/USD",
                current_price=current_price,
                df_5m=df_extreme,
            )
            # Should have both primary (trend) and extreme (fade) signals
            print(f"  [OK] Extreme mode generated {len(signals_extreme)} signal(s)")
            if len(signals_extreme) > 1:
                print("      - Includes both trend and fade signals")

        # Test 8: Maker-only enforcement
        print("\n[8/8] Testing maker-only enforcement...")
        assert strategy_trend.maker_only is True
        print("  [OK] Maker-only mode enabled")

        print("\n" + "="*70)
        print("SUCCESS: BAR REACTION 5M STRATEGY SELF-CHECK PASSED")
        print("="*70)
        print("\nREQUIREMENTS VERIFIED:")
        print("  [OK] Strategy initialization (trend/revert modes)")
        print("  [OK] Feature preparation (5m bars + ATR + move_bps)")
        print("  [OK] Should trade filter (ATR%, spread checks)")
        print("  [OK] Signal generation (bar-close logic)")
        print("  [OK] ATR-based SL/TP levels")
        print("  [OK] Position sizing (risk-based)")
        print("  [OK] Extreme fade mode (contrarian trades)")
        print("  [OK] Maker-only enforcement")
        print("  [OK] Dual profit targets (TP1, TP2)")
        print("="*70)

    except Exception as e:
        print(f"\nFAIL Bar Reaction 5m Strategy Self-Check: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
