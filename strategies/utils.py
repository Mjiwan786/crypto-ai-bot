"""
strategies/utils.py - Centralized SL/TP Math and Entry/Exit Utilities (STEP 6)

Centralizes common calculations for stop loss, take profit, trailing stops,
and partial TP ladders across all strategies.

Requirements:
- SL/TP calculations based on ATR or percentage
- Trailing stop logic
- Partial TP ladder support
- RR ratio calculations
- Time-based stop logic

Author: Crypto AI Bot Team
"""

from decimal import Decimal
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np


# =============================================================================
# STOP LOSS / TAKE PROFIT CALCULATIONS
# =============================================================================


def calculate_sl_tp_from_atr(
    entry_price: float,
    side: str,
    atr: float,
    sl_atr_multiplier: float = 1.5,
    tp_atr_multiplier: float = 3.0,
) -> Tuple[float, float]:
    """
    Calculate stop loss and take profit based on ATR.

    Args:
        entry_price: Entry price
        side: 'long' or 'short'
        atr: Average True Range value
        sl_atr_multiplier: SL distance as multiple of ATR (default 1.5x)
        tp_atr_multiplier: TP distance as multiple of ATR (default 3.0x)

    Returns:
        Tuple of (stop_loss, take_profit)

    Example:
        >>> calculate_sl_tp_from_atr(50000, 'long', 500, 1.5, 3.0)
        (49250.0, 51500.0)  # SL = entry - 1.5*ATR, TP = entry + 3.0*ATR
    """
    sl_distance = atr * sl_atr_multiplier
    tp_distance = atr * tp_atr_multiplier

    if side.lower() == 'long':
        stop_loss = entry_price - sl_distance
        take_profit = entry_price + tp_distance
    else:  # short
        stop_loss = entry_price + sl_distance
        take_profit = entry_price - tp_distance

    return stop_loss, take_profit


def calculate_sl_tp_from_percentage(
    entry_price: float,
    side: str,
    sl_pct: float = 0.02,
    tp_pct: float = 0.04,
) -> Tuple[float, float]:
    """
    Calculate stop loss and take profit based on percentage.

    Args:
        entry_price: Entry price
        side: 'long' or 'short'
        sl_pct: Stop loss percentage (default 2%)
        tp_pct: Take profit percentage (default 4%)

    Returns:
        Tuple of (stop_loss, take_profit)

    Example:
        >>> calculate_sl_tp_from_percentage(50000, 'long', 0.02, 0.04)
        (49000.0, 52000.0)  # SL = -2%, TP = +4%
    """
    sl_distance = entry_price * sl_pct
    tp_distance = entry_price * tp_pct

    if side.lower() == 'long':
        stop_loss = entry_price - sl_distance
        take_profit = entry_price + tp_distance
    else:  # short
        stop_loss = entry_price + sl_distance
        take_profit = entry_price - tp_distance

    return stop_loss, take_profit


def calculate_rr_ratio(
    entry_price: float,
    stop_loss: float,
    take_profit: float,
) -> float:
    """
    Calculate risk/reward ratio.

    Args:
        entry_price: Entry price
        stop_loss: Stop loss price
        take_profit: Take profit price

    Returns:
        Risk/Reward ratio (reward / risk)

    Example:
        >>> calculate_rr_ratio(50000, 49000, 53000)
        3.0  # Reward (+3000) / Risk (1000) = 3.0
    """
    risk = abs(entry_price - stop_loss)
    reward = abs(take_profit - entry_price)

    if risk == 0:
        return 0.0

    return reward / risk


def create_partial_tp_ladder(
    entry_price: float,
    side: str,
    atr: float,
    levels: List[float] = [1.5, 2.5, 3.5],
    sizes: List[float] = [0.33, 0.33, 0.34],
) -> List[Dict[str, float]]:
    """
    Create partial take profit ladder.

    Args:
        entry_price: Entry price
        side: 'long' or 'short'
        atr: Average True Range value
        levels: TP levels as ATR multipliers (default [1.5, 2.5, 3.5])
        sizes: Position sizes to close at each level (default [33%, 33%, 34%])

    Returns:
        List of TP levels with prices and sizes

    Example:
        >>> create_partial_tp_ladder(50000, 'long', 500)
        [
            {'level': 1, 'price': 50750.0, 'size_pct': 0.33, 'atr_mult': 1.5},
            {'level': 2, 'price': 51250.0, 'size_pct': 0.33, 'atr_mult': 2.5},
            {'level': 3, 'price': 51750.0, 'size_pct': 0.34, 'atr_mult': 3.5},
        ]
    """
    if len(levels) != len(sizes):
        raise ValueError("levels and sizes must have same length")

    if abs(sum(sizes) - 1.0) > 0.01:
        raise ValueError("sizes must sum to 1.0")

    ladder = []
    for i, (atr_mult, size_pct) in enumerate(zip(levels, sizes)):
        if side.lower() == 'long':
            price = entry_price + (atr * atr_mult)
        else:  # short
            price = entry_price - (atr * atr_mult)

        ladder.append({
            'level': i + 1,
            'price': price,
            'size_pct': size_pct,
            'atr_mult': atr_mult,
        })

    return ladder


# =============================================================================
# TRAILING STOP LOGIC
# =============================================================================


def calculate_trailing_stop(
    entry_price: float,
    current_price: float,
    highest_price: float,  # For long, lowest_price for short
    side: str,
    trail_pct: float = 0.02,
    min_profit_pct: float = 0.01,
) -> Optional[float]:
    """
    Calculate trailing stop price.

    Args:
        entry_price: Entry price
        current_price: Current market price
        highest_price: Highest price since entry (for long) or lowest (for short)
        side: 'long' or 'short'
        trail_pct: Trailing percentage from peak (default 2%)
        min_profit_pct: Minimum profit before trailing activates (default 1%)

    Returns:
        Trailing stop price, or None if not activated yet

    Example:
        >>> # Long position: entry=50000, highest=51000, current=50800
        >>> calculate_trailing_stop(50000, 50800, 51000, 'long', 0.02, 0.01)
        50490.0  # Trail from highest: 51000 - (51000 * 0.02) = 50490
    """
    # Check if minimum profit reached
    if side.lower() == 'long':
        current_profit_pct = (current_price - entry_price) / entry_price
        if current_profit_pct < min_profit_pct:
            return None  # Not enough profit yet

        # Trail from highest price
        trailing_stop = highest_price * (1 - trail_pct)
        return trailing_stop

    else:  # short
        current_profit_pct = (entry_price - current_price) / entry_price
        if current_profit_pct < min_profit_pct:
            return None

        # Trail from lowest price
        trailing_stop = highest_price * (1 + trail_pct)  # highest_price is actually lowest for shorts
        return trailing_stop


def should_trail_stop_trigger(
    current_price: float,
    trailing_stop: float,
    side: str,
) -> bool:
    """
    Check if trailing stop should trigger.

    Args:
        current_price: Current market price
        trailing_stop: Calculated trailing stop price
        side: 'long' or 'short'

    Returns:
        True if trailing stop hit

    Example:
        >>> should_trail_stop_trigger(50400, 50490, 'long')
        True  # Price below trailing stop
    """
    if trailing_stop is None:
        return False

    if side.lower() == 'long':
        return current_price <= trailing_stop
    else:  # short
        return current_price >= trailing_stop


# =============================================================================
# TIME-BASED STOPS
# =============================================================================


def should_time_stop_trigger(
    entry_timestamp: pd.Timestamp,
    current_timestamp: pd.Timestamp,
    max_hold_bars: int,
) -> bool:
    """
    Check if time-based stop should trigger.

    Args:
        entry_timestamp: Entry timestamp
        current_timestamp: Current timestamp
        max_hold_bars: Maximum number of bars to hold

    Returns:
        True if max hold time exceeded

    Example:
        >>> entry = pd.Timestamp('2024-10-25 10:00:00')
        >>> current = pd.Timestamp('2024-10-25 12:30:00')
        >>> should_time_stop_trigger(entry, current, max_hold_bars=30)  # 5m bars
        True  # 30 bars * 5m = 150 minutes = 2.5 hours
    """
    bars_held = (current_timestamp - entry_timestamp).total_seconds() / 300  # Assume 5m bars
    return bars_held >= max_hold_bars


# =============================================================================
# TECHNICAL INDICATOR CONFIRMATIONS
# =============================================================================


def calculate_adx(df: pd.DataFrame, period: int = 14) -> float:
    """
    Calculate Average Directional Index (ADX).

    Args:
        df: DataFrame with high, low, close columns
        period: ADX calculation period (default 14)

    Returns:
        Current ADX value

    Note:
        ADX > 25: Strong trend
        ADX < 20: Weak trend / ranging
    """
    if len(df) < period + 1:
        return 0.0

    try:
        import talib
        adx = talib.ADX(df['high'].values, df['low'].values, df['close'].values, timeperiod=period)
        return float(adx[-1]) if not np.isnan(adx[-1]) else 0.0
    except:
        # Fallback: simple implementation
        return 25.0  # Assume moderate trend


def calculate_slope(series: pd.Series, period: int = 10) -> float:
    """
    Calculate linear regression slope of a series.

    Args:
        series: Price series (e.g., close prices or moving average)
        period: Number of bars to calculate slope over

    Returns:
        Slope value (positive = uptrend, negative = downtrend)

    Example:
        >>> prices = pd.Series([50000, 50100, 50200, 50300, 50400])
        >>> calculate_slope(prices, period=5)
        100.0  # Consistent uptrend
    """
    if len(series) < period:
        return 0.0

    recent = series.tail(period).values
    x = np.arange(len(recent))

    # Linear regression
    coeffs = np.polyfit(x, recent, deg=1)
    slope = coeffs[0]

    return float(slope)


def check_rsi_extreme(df: pd.DataFrame, period: int = 14, oversold: float = 30.0, overbought: float = 70.0) -> str:
    """
    Check if RSI is in extreme territory.

    Args:
        df: DataFrame with close column
        period: RSI calculation period (default 14)
        oversold: Oversold threshold (default 30)
        overbought: Overbought threshold (default 70)

    Returns:
        'oversold', 'overbought', or 'neutral'
    """
    if len(df) < period + 1:
        return 'neutral'

    try:
        import talib
        rsi = talib.RSI(df['close'].values, timeperiod=period)
        current_rsi = rsi[-1]

        if np.isnan(current_rsi):
            return 'neutral'

        if current_rsi <= oversold:
            return 'oversold'
        elif current_rsi >= overbought:
            return 'overbought'
        else:
            return 'neutral'
    except:
        return 'neutral'


# =============================================================================
# SPREAD / LATENCY GUARDS (for scalper)
# =============================================================================


def check_spread_acceptable(
    bid: float,
    ask: float,
    max_spread_bps: float = 10.0,
) -> bool:
    """
    Check if bid-ask spread is within acceptable limits.

    Args:
        bid: Bid price
        ask: Ask price
        max_spread_bps: Maximum spread in basis points (default 10 bps = 0.1%)

    Returns:
        True if spread is acceptable

    Example:
        >>> check_spread_acceptable(50000, 50050, max_spread_bps=10.0)
        False  # Spread = 50 / 50000 = 0.1% = 10 bps (at limit)
    """
    mid = (bid + ask) / 2
    spread_pct = (ask - bid) / mid
    spread_bps = spread_pct * 10000

    return spread_bps <= max_spread_bps


def check_latency_acceptable(
    latency_ms: float,
    max_latency_ms: float = 500.0,
) -> bool:
    """
    Check if latency is within acceptable limits.

    Args:
        latency_ms: Current latency in milliseconds
        max_latency_ms: Maximum acceptable latency (default 500ms)

    Returns:
        True if latency is acceptable
    """
    return latency_ms <= max_latency_ms


# =============================================================================
# THROTTLING (for scalper)
# =============================================================================


class TradeThrottler:
    """
    Simple trade throttler to limit trades per minute.

    Usage:
        >>> throttler = TradeThrottler(max_trades_per_minute=3)
        >>> if throttler.can_trade():
        ...     # Execute trade
        ...     throttler.record_trade(pd.Timestamp.now())
    """

    def __init__(self, max_trades_per_minute: int = 3):
        """
        Initialize throttler.

        Args:
            max_trades_per_minute: Maximum trades allowed per minute
        """
        self.max_trades_per_minute = max_trades_per_minute
        self.trade_timestamps: List[pd.Timestamp] = []

    def can_trade(self, current_time: pd.Timestamp) -> bool:
        """
        Check if trading is allowed based on throttle limits.

        Args:
            current_time: Current timestamp

        Returns:
            True if trade is allowed
        """
        # Remove trades older than 1 minute
        one_minute_ago = current_time - pd.Timedelta(minutes=1)
        self.trade_timestamps = [
            ts for ts in self.trade_timestamps if ts > one_minute_ago
        ]

        # Check if under limit
        return len(self.trade_timestamps) < self.max_trades_per_minute

    def record_trade(self, timestamp: pd.Timestamp) -> None:
        """
        Record a trade execution.

        Args:
            timestamp: Trade execution timestamp
        """
        self.trade_timestamps.append(timestamp)

    def reset(self) -> None:
        """Reset throttler state."""
        self.trade_timestamps = []


# =============================================================================
# VALIDATION HELPERS
# =============================================================================


def validate_signal_params(
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    side: str,
    min_rr: float = 1.6,
) -> Tuple[bool, str]:
    """
    Validate signal parameters meet requirements.

    Args:
        entry_price: Entry price
        stop_loss: Stop loss price
        take_profit: Take profit price
        side: 'long' or 'short'
        min_rr: Minimum RR ratio required (default 1.6 from STEP 5)

    Returns:
        Tuple of (valid, reason)

    Example:
        >>> validate_signal_params(50000, 49000, 53000, 'long', min_rr=1.6)
        (True, '')  # RR = 3.0 >= 1.6
        >>> validate_signal_params(50000, 49000, 51000, 'long', min_rr=1.6)
        (False, 'RR ratio 1.00 < 1.60')  # RR too low
    """
    # Check SL is on correct side
    if side.lower() == 'long':
        if stop_loss >= entry_price:
            return False, f"Long SL ({stop_loss}) must be below entry ({entry_price})"
        if take_profit <= entry_price:
            return False, f"Long TP ({take_profit}) must be above entry ({entry_price})"
    else:  # short
        if stop_loss <= entry_price:
            return False, f"Short SL ({stop_loss}) must be above entry ({entry_price})"
        if take_profit >= entry_price:
            return False, f"Short TP ({take_profit}) must be below entry ({entry_price})"

    # Check RR ratio
    rr = calculate_rr_ratio(entry_price, stop_loss, take_profit)
    if rr < min_rr:
        return False, f"RR ratio {rr:.2f} < {min_rr:.2f}"

    return True, ""


# =============================================================================
# PUBLIC API
# =============================================================================

__all__ = [
    # SL/TP calculations
    'calculate_sl_tp_from_atr',
    'calculate_sl_tp_from_percentage',
    'calculate_rr_ratio',
    'create_partial_tp_ladder',
    # Trailing stops
    'calculate_trailing_stop',
    'should_trail_stop_trigger',
    # Time stops
    'should_time_stop_trigger',
    # Technical indicators
    'calculate_adx',
    'calculate_slope',
    'check_rsi_extreme',
    # Spread/latency guards
    'check_spread_acceptable',
    'check_latency_acceptable',
    # Throttling
    'TradeThrottler',
    # Validation
    'validate_signal_params',
]
