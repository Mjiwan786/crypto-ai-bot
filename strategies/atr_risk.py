"""
ATR-based risk model with partial exits and breakeven stops.

Implements sophisticated risk management to improve profit factor:
- ATR-based stop loss and take profit levels
- Partial profit taking at TP1 (50% position)
- Trailing stop to TP2 with breakeven protection
- Move stop to breakeven at +0.8R

Configuration:
    SL = a * ATR       (default a=0.6)
    TP1 = b * ATR      (default b=1.0, take 50% position)
    TP2 = c * ATR      (default c=1.8)
    Trail = d * ATR    (default d=0.8)
    Breakeven at +0.8R

Per-trade fields persisted:
- atr_value: ATR at signal generation
- sl_atr_multiple: Stop loss multiplier (a)
- tp1_atr_multiple: First take profit multiplier (b)
- tp2_atr_multiple: Second take profit multiplier (c)
- trail_atr_multiple: Trailing stop multiplier (d)
- breakeven_r: R-multiple to move stop to breakeven (default 0.8)
- tp1_size_pct: Percentage to close at TP1 (default 50%)
- entry_price: Entry price
- current_stop: Current stop loss price (updated as position moves)
- highest_price: Highest price reached (for longs) or lowest (for shorts)
- stop_moved_to_be: Boolean flag if stop moved to breakeven
- tp1_hit: Boolean flag if TP1 was hit
- remaining_size_pct: Current position size percentage

Accept criteria:
- ATR-based sizing improves with market conditions
- Partial exits lock in profits early
- Trailing stops maximize winning trades
- Breakeven protection prevents small wins from becoming losses
- All fields persisted for analysis and backtesting
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class ATRRiskConfig:
    """Configuration for ATR-based risk management."""

    # ATR multipliers
    sl_atr_multiple: Decimal = Decimal("0.6")  # Stop loss = 0.6 * ATR
    tp1_atr_multiple: Decimal = Decimal("1.0")  # First TP = 1.0 * ATR
    tp2_atr_multiple: Decimal = Decimal("1.8")  # Second TP = 1.8 * ATR
    trail_atr_multiple: Decimal = Decimal("0.8")  # Trailing stop = 0.8 * ATR

    # Partial exit configuration
    tp1_size_pct: Decimal = Decimal("0.50")  # Take 50% at TP1
    breakeven_r: Decimal = Decimal("0.8")  # Move to BE at +0.8R

    # ATR calculation
    atr_period: int = 14  # ATR lookback period

    def validate(self) -> None:
        """Validate configuration parameters."""
        if self.sl_atr_multiple <= 0:
            raise ValueError(f"sl_atr_multiple must be positive, got {self.sl_atr_multiple}")
        if self.tp1_atr_multiple <= self.sl_atr_multiple:
            raise ValueError(
                f"tp1_atr_multiple ({self.tp1_atr_multiple}) must be > "
                f"sl_atr_multiple ({self.sl_atr_multiple})"
            )
        if self.tp2_atr_multiple <= self.tp1_atr_multiple:
            raise ValueError(
                f"tp2_atr_multiple ({self.tp2_atr_multiple}) must be > "
                f"tp1_atr_multiple ({self.tp1_atr_multiple})"
            )
        if self.trail_atr_multiple <= 0:
            raise ValueError(f"trail_atr_multiple must be positive, got {self.trail_atr_multiple}")
        if not (0 < self.tp1_size_pct < 1):
            raise ValueError(f"tp1_size_pct must be in (0, 1), got {self.tp1_size_pct}")
        if self.breakeven_r <= 0:
            raise ValueError(f"breakeven_r must be positive, got {self.breakeven_r}")
        if self.atr_period < 2:
            raise ValueError(f"atr_period must be >= 2, got {self.atr_period}")


@dataclass
class ATRRiskLevels:
    """ATR-based risk levels for a trade."""

    # Core levels
    entry_price: Decimal
    stop_loss: Decimal
    tp1_price: Decimal
    tp2_price: Decimal
    breakeven_price: Decimal
    trail_distance: Decimal

    # ATR metadata
    atr_value: Decimal
    sl_atr_multiple: Decimal
    tp1_atr_multiple: Decimal
    tp2_atr_multiple: Decimal
    trail_atr_multiple: Decimal
    breakeven_r: Decimal

    # Position management
    tp1_size_pct: Decimal
    remaining_size_pct: Decimal = Decimal("1.0")

    # State tracking
    current_stop: Optional[Decimal] = None
    highest_price: Optional[Decimal] = None  # For longs
    lowest_price: Optional[Decimal] = None  # For shorts
    stop_moved_to_be: bool = False
    tp1_hit: bool = False

    def __post_init__(self):
        """Initialize current stop to initial stop loss."""
        if self.current_stop is None:
            self.current_stop = self.stop_loss

    def to_dict(self) -> dict:
        """Convert to dictionary for persistence."""
        return {
            "entry_price": float(self.entry_price),
            "stop_loss": float(self.stop_loss),
            "current_stop": float(self.current_stop) if self.current_stop else None,
            "tp1_price": float(self.tp1_price),
            "tp2_price": float(self.tp2_price),
            "breakeven_price": float(self.breakeven_price),
            "trail_distance": float(self.trail_distance),
            "atr_value": float(self.atr_value),
            "sl_atr_multiple": float(self.sl_atr_multiple),
            "tp1_atr_multiple": float(self.tp1_atr_multiple),
            "tp2_atr_multiple": float(self.tp2_atr_multiple),
            "trail_atr_multiple": float(self.trail_atr_multiple),
            "breakeven_r": float(self.breakeven_r),
            "tp1_size_pct": float(self.tp1_size_pct),
            "remaining_size_pct": float(self.remaining_size_pct),
            "highest_price": float(self.highest_price) if self.highest_price else None,
            "lowest_price": float(self.lowest_price) if self.lowest_price else None,
            "stop_moved_to_be": self.stop_moved_to_be,
            "tp1_hit": self.tp1_hit,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ATRRiskLevels":
        """Reconstruct from dictionary."""
        return cls(
            entry_price=Decimal(str(data["entry_price"])),
            stop_loss=Decimal(str(data["stop_loss"])),
            current_stop=Decimal(str(data["current_stop"])) if data.get("current_stop") else None,
            tp1_price=Decimal(str(data["tp1_price"])),
            tp2_price=Decimal(str(data["tp2_price"])),
            breakeven_price=Decimal(str(data["breakeven_price"])),
            trail_distance=Decimal(str(data["trail_distance"])),
            atr_value=Decimal(str(data["atr_value"])),
            sl_atr_multiple=Decimal(str(data["sl_atr_multiple"])),
            tp1_atr_multiple=Decimal(str(data["tp1_atr_multiple"])),
            tp2_atr_multiple=Decimal(str(data["tp2_atr_multiple"])),
            trail_atr_multiple=Decimal(str(data["trail_atr_multiple"])),
            breakeven_r=Decimal(str(data["breakeven_r"])),
            tp1_size_pct=Decimal(str(data["tp1_size_pct"])),
            remaining_size_pct=Decimal(str(data.get("remaining_size_pct", "1.0"))),
            highest_price=Decimal(str(data["highest_price"])) if data.get("highest_price") else None,
            lowest_price=Decimal(str(data["lowest_price"])) if data.get("lowest_price") else None,
            stop_moved_to_be=data.get("stop_moved_to_be", False),
            tp1_hit=data.get("tp1_hit", False),
        )


@dataclass
class ATRUpdateResult:
    """Result of updating ATR risk levels."""

    # Actions to take
    should_close_partial: bool = False  # Close partial at TP1
    should_close_full: bool = False  # Close full position (SL or TP2)
    should_update_stop: bool = False  # Update stop loss

    # New values if updating
    new_stop: Optional[Decimal] = None
    close_size_pct: Optional[Decimal] = None  # Percentage to close
    close_reason: Optional[str] = None  # "tp1", "tp2", "stop_loss", "trailing"

    # Updated levels
    updated_levels: Optional[ATRRiskLevels] = None


def calculate_atr(ohlcv_df: pd.DataFrame, period: int = 14) -> Decimal:
    """
    Calculate Average True Range.

    Args:
        ohlcv_df: OHLCV DataFrame with columns: high, low, close
        period: ATR lookback period

    Returns:
        ATR value as Decimal

    Raises:
        ValueError: If insufficient data
    """
    if len(ohlcv_df) < period + 1:
        raise ValueError(f"Insufficient data for ATR: need {period + 1}, got {len(ohlcv_df)}")

    high = ohlcv_df["high"].values
    low = ohlcv_df["low"].values
    close = ohlcv_df["close"].values

    # Calculate true range
    tr = []
    for i in range(1, len(ohlcv_df)):
        h_l = high[i] - low[i]
        h_pc = abs(high[i] - close[i - 1])
        l_pc = abs(low[i] - close[i - 1])
        tr.append(max(h_l, h_pc, l_pc))

    # Average of last N periods
    atr = np.mean(tr[-period:])

    logger.debug(f"ATR({period}): {atr:.4f}")
    return Decimal(str(atr))


def calculate_atr_risk_levels(
    side: str,
    entry_price: Decimal,
    atr_value: Decimal,
    config: ATRRiskConfig,
) -> ATRRiskLevels:
    """
    Calculate ATR-based risk levels for a trade.

    Args:
        side: "long" or "short"
        entry_price: Entry price
        atr_value: Current ATR value
        config: ATR risk configuration

    Returns:
        ATR risk levels

    Raises:
        ValueError: If invalid parameters
    """
    config.validate()

    if side.lower() not in ("long", "short"):
        raise ValueError(f"Invalid side: {side}, must be 'long' or 'short'")

    if entry_price <= 0:
        raise ValueError(f"Entry price must be positive, got {entry_price}")

    if atr_value <= 0:
        raise ValueError(f"ATR must be positive, got {atr_value}")

    # Calculate levels based on side
    if side.lower() == "long":
        # Long position
        stop_loss = entry_price - (atr_value * config.sl_atr_multiple)
        tp1_price = entry_price + (atr_value * config.tp1_atr_multiple)
        tp2_price = entry_price + (atr_value * config.tp2_atr_multiple)

        # Breakeven at +0.8R
        risk_distance = entry_price - stop_loss
        breakeven_price = entry_price + (risk_distance * config.breakeven_r)

    else:
        # Short position
        stop_loss = entry_price + (atr_value * config.sl_atr_multiple)
        tp1_price = entry_price - (atr_value * config.tp1_atr_multiple)
        tp2_price = entry_price - (atr_value * config.tp2_atr_multiple)

        # Breakeven at +0.8R
        risk_distance = stop_loss - entry_price
        breakeven_price = entry_price - (risk_distance * config.breakeven_r)

    # Trail distance
    trail_distance = atr_value * config.trail_atr_multiple

    levels = ATRRiskLevels(
        entry_price=entry_price,
        stop_loss=stop_loss,
        tp1_price=tp1_price,
        tp2_price=tp2_price,
        breakeven_price=breakeven_price,
        trail_distance=trail_distance,
        atr_value=atr_value,
        sl_atr_multiple=config.sl_atr_multiple,
        tp1_atr_multiple=config.tp1_atr_multiple,
        tp2_atr_multiple=config.tp2_atr_multiple,
        trail_atr_multiple=config.trail_atr_multiple,
        breakeven_r=config.breakeven_r,
        tp1_size_pct=config.tp1_size_pct,
    )

    logger.info(
        f"ATR risk levels ({side}): entry={entry_price:.2f}, SL={stop_loss:.2f}, "
        f"TP1={tp1_price:.2f} (take {config.tp1_size_pct*100:.0f}%), "
        f"TP2={tp2_price:.2f}, BE={breakeven_price:.2f}, trail={trail_distance:.2f}"
    )

    return levels


def update_atr_risk_levels(
    side: str,
    current_price: Decimal,
    levels: ATRRiskLevels,
) -> ATRUpdateResult:
    """
    Update ATR risk levels based on current price.

    Handles:
    - Stop loss hit
    - TP1 hit (partial exit)
    - TP2 hit (full exit)
    - Breakeven stop movement
    - Trailing stop after TP1

    Args:
        side: "long" or "short"
        current_price: Current market price
        levels: Current ATR risk levels

    Returns:
        Update result with actions to take
    """
    result = ATRUpdateResult()

    # Update highest/lowest price
    if side.lower() == "long":
        if levels.highest_price is None or current_price > levels.highest_price:
            levels.highest_price = current_price
    else:
        if levels.lowest_price is None or current_price < levels.lowest_price:
            levels.lowest_price = current_price

    # Check for stop loss hit
    if side.lower() == "long":
        if current_price <= levels.current_stop:
            result.should_close_full = True
            result.close_size_pct = levels.remaining_size_pct
            result.close_reason = "stop_loss"
            result.updated_levels = levels
            logger.info(
                f"Stop loss hit (LONG): price={current_price:.2f} <= stop={levels.current_stop:.2f}"
            )
            return result
    else:
        if current_price >= levels.current_stop:
            result.should_close_full = True
            result.close_size_pct = levels.remaining_size_pct
            result.close_reason = "stop_loss"
            result.updated_levels = levels
            logger.info(
                f"Stop loss hit (SHORT): price={current_price:.2f} >= stop={levels.current_stop:.2f}"
            )
            return result

    # Check for TP2 hit (full exit of remaining position)
    if side.lower() == "long":
        if current_price >= levels.tp2_price:
            result.should_close_full = True
            result.close_size_pct = levels.remaining_size_pct
            result.close_reason = "tp2"
            result.updated_levels = levels
            logger.info(f"TP2 hit (LONG): price={current_price:.2f} >= TP2={levels.tp2_price:.2f}")
            return result
    else:
        if current_price <= levels.tp2_price:
            result.should_close_full = True
            result.close_size_pct = levels.remaining_size_pct
            result.close_reason = "tp2"
            result.updated_levels = levels
            logger.info(f"TP2 hit (SHORT): price={current_price:.2f} <= TP2={levels.tp2_price:.2f}")
            return result

    # Check for TP1 hit (partial exit)
    if not levels.tp1_hit:
        if side.lower() == "long":
            if current_price >= levels.tp1_price:
                result.should_close_partial = True
                result.close_size_pct = levels.tp1_size_pct
                result.close_reason = "tp1"
                levels.tp1_hit = True
                levels.remaining_size_pct = Decimal("1.0") - levels.tp1_size_pct
                logger.info(
                    f"TP1 hit (LONG): price={current_price:.2f} >= TP1={levels.tp1_price:.2f}, "
                    f"closing {levels.tp1_size_pct*100:.0f}%"
                )
        else:
            if current_price <= levels.tp1_price:
                result.should_close_partial = True
                result.close_size_pct = levels.tp1_size_pct
                result.close_reason = "tp1"
                levels.tp1_hit = True
                levels.remaining_size_pct = Decimal("1.0") - levels.tp1_size_pct
                logger.info(
                    f"TP1 hit (SHORT): price={current_price:.2f} <= TP1={levels.tp1_price:.2f}, "
                    f"closing {levels.tp1_size_pct*100:.0f}%"
                )

    # Check for breakeven stop movement (only if not already moved)
    if not levels.stop_moved_to_be:
        if side.lower() == "long":
            if current_price >= levels.breakeven_price:
                levels.current_stop = levels.entry_price
                levels.stop_moved_to_be = True
                result.should_update_stop = True
                result.new_stop = levels.current_stop
                logger.info(
                    f"Moving stop to breakeven (LONG): price={current_price:.2f} >= "
                    f"BE={levels.breakeven_price:.2f}, new_stop={levels.current_stop:.2f}"
                )
        else:
            if current_price <= levels.breakeven_price:
                levels.current_stop = levels.entry_price
                levels.stop_moved_to_be = True
                result.should_update_stop = True
                result.new_stop = levels.current_stop
                logger.info(
                    f"Moving stop to breakeven (SHORT): price={current_price:.2f} <= "
                    f"BE={levels.breakeven_price:.2f}, new_stop={levels.current_stop:.2f}"
                )

    # Trailing stop (only after TP1 hit and stop moved to BE)
    if levels.tp1_hit and levels.stop_moved_to_be:
        if side.lower() == "long":
            # Trail below highest price
            new_trail_stop = levels.highest_price - levels.trail_distance
            if new_trail_stop > levels.current_stop:
                levels.current_stop = new_trail_stop
                result.should_update_stop = True
                result.new_stop = levels.current_stop
                logger.debug(
                    f"Trailing stop (LONG): high={levels.highest_price:.2f}, "
                    f"new_stop={levels.current_stop:.2f}"
                )
        else:
            # Trail above lowest price
            new_trail_stop = levels.lowest_price + levels.trail_distance
            if new_trail_stop < levels.current_stop:
                levels.current_stop = new_trail_stop
                result.should_update_stop = True
                result.new_stop = levels.current_stop
                logger.debug(
                    f"Trailing stop (SHORT): low={levels.lowest_price:.2f}, "
                    f"new_stop={levels.current_stop:.2f}"
                )

    result.updated_levels = levels
    return result


# =============================================================================
# SELF-CHECK
# =============================================================================

if __name__ == "__main__":
    """Self-check: Test ATR risk model"""
    import sys

    logging.basicConfig(level=logging.INFO)

    try:
        # Test 1: Calculate ATR
        df = pd.DataFrame(
            {
                "high": [101, 103, 105, 104, 106, 108, 107, 109, 111, 110, 112, 114, 113, 115, 117],
                "low": [99, 101, 103, 102, 104, 106, 105, 107, 109, 108, 110, 112, 111, 113, 115],
                "close": [100, 102, 104, 103, 105, 107, 106, 108, 110, 109, 111, 113, 112, 114, 116],
            }
        )
        atr = calculate_atr(df, period=14)
        assert atr > 0, f"Expected positive ATR, got {atr}"

        # Test 2: Calculate risk levels for long
        config = ATRRiskConfig()
        entry_long = Decimal("50000")
        levels_long = calculate_atr_risk_levels("long", entry_long, atr, config)

        assert levels_long.stop_loss < entry_long, "Long SL should be below entry"
        assert levels_long.tp1_price > entry_long, "Long TP1 should be above entry"
        assert levels_long.tp2_price > levels_long.tp1_price, "TP2 should be above TP1"
        assert levels_long.breakeven_price > entry_long, "BE should be above entry"

        # Test 3: Calculate risk levels for short
        entry_short = Decimal("50000")
        levels_short = calculate_atr_risk_levels("short", entry_short, atr, config)

        assert levels_short.stop_loss > entry_short, "Short SL should be above entry"
        assert levels_short.tp1_price < entry_short, "Short TP1 should be below entry"
        assert levels_short.tp2_price < levels_short.tp1_price, "TP2 should be below TP1"
        assert levels_short.breakeven_price < entry_short, "BE should be below entry"

        # Test 4: Update logic - TP1 hit (long)
        # Reset levels for clean test
        levels_long = calculate_atr_risk_levels("long", entry_long, atr, config)
        current_price = levels_long.tp1_price + Decimal("1")  # Slightly above TP1
        result = update_atr_risk_levels("long", current_price, levels_long)
        assert result.should_close_partial, "Should close partial at TP1"
        assert result.close_size_pct == config.tp1_size_pct, "Should close TP1 percentage"
        assert levels_long.tp1_hit, "TP1 flag should be set"

        # Test 5: Update logic - Breakeven movement (long)
        # Reset levels for clean test
        levels_long = calculate_atr_risk_levels("long", entry_long, atr, config)
        current_price = levels_long.breakeven_price + Decimal("1")  # Slightly above BE
        result = update_atr_risk_levels("long", current_price, levels_long)
        assert result.should_update_stop or levels_long.stop_moved_to_be, "Should move to breakeven"
        assert levels_long.current_stop >= entry_long, "Stop should be at or above entry"

        # Test 6: Serialization
        levels_dict = levels_long.to_dict()
        assert isinstance(levels_dict, dict), "Should serialize to dict"
        levels_restored = ATRRiskLevels.from_dict(levels_dict)
        assert levels_restored.entry_price == levels_long.entry_price, "Should restore correctly"

        print("\nPASS ATR Risk Model Self-Check:")
        print(f"  - ATR calculation: {atr:.2f}")
        print(f"  - Long levels: SL={levels_long.stop_loss:.2f}, TP1={levels_long.tp1_price:.2f}, TP2={levels_long.tp2_price:.2f}")
        print(f"  - Short levels: SL={levels_short.stop_loss:.2f}, TP1={levels_short.tp1_price:.2f}, TP2={levels_short.tp2_price:.2f}")
        print(f"  - TP1 partial close: {config.tp1_size_pct*100:.0f}%")
        print(f"  - Breakeven at: +{config.breakeven_r:.1f}R")
        print(f"  - Serialization: OK")

    except Exception as e:
        print(f"\nFAIL ATR Risk Model Self-Check: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
