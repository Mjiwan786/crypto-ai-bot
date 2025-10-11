"""
Synthetic OHLCV data generators for unit tests and smoke scripts.

Provides deterministic generators for various market scenarios including
breakouts, false breakouts, retests, and trends. All functions return
Pandas DataFrames with standardized OHLCV format.
"""

from typing import Union, Optional, List
import numpy as np
import pandas as pd


__all__ = [
    "make_range_then_breakout_up",
    "make_false_breakout_up", 
    "make_breakout_with_retest",
    "make_range_then_breakdown",
    "make_trend_up",
    "make_sideways_noise",
    "timeframe_to_ms",
    "make_time_index",
    "ensure_ohlcv_integrity",
    "with_volume_pattern",
    "to_ccxt_list",
    "set_seed",
    "_smoke_all",
    "_is_breakout_bar",
]


def timeframe_to_ms(tf: str) -> int:
    """
    Convert timeframe string to milliseconds.
    
    Parameters
    ----------
    tf : str
        Timeframe string, one of {"1m", "5m", "15m", "1h", "4h", "1d"}
    
    Returns
    -------
    int
        Timeframe in milliseconds
        
    Raises
    ------
    ValueError
        If timeframe is not supported
    """
    mapping = {
        "1m": 60 * 1000,
        "5m": 5 * 60 * 1000,
        "15m": 15 * 60 * 1000,
        "1h": 60 * 60 * 1000,
        "4h": 4 * 60 * 60 * 1000,
        "1d": 24 * 60 * 60 * 1000,
    }
    if tf not in mapping:
        raise ValueError(f"Unsupported timeframe: {tf}. "
                        f"Must be one of {list(mapping.keys())}")
    return mapping[tf]


def set_seed(seed: Optional[int]) -> np.random.Generator:
    """
    Create numpy random generator with specified seed.
    
    Parameters
    ----------
    seed : int or None
        Random seed for reproducibility
        
    Returns
    -------
    np.random.Generator
        Configured random number generator
    """
    if seed is None:
        return np.random.default_rng()
    return np.random.default_rng(np.random.PCG64(seed))


def make_time_index(
    n: int, 
    start: Union[str, pd.Timestamp], 
    tf_ms: int
) -> pd.Series:
    """
    Generate monotonic timestamp series in UTC milliseconds.
    
    Parameters
    ----------
    n : int
        Number of timestamps to generate
    start : str or pd.Timestamp
        Start time in UTC
    tf_ms : int
        Timeframe interval in milliseconds
        
    Returns
    -------
    pd.Series
        Series of UTC timestamps in milliseconds (int64)
    """
    if isinstance(start, str):
        start_ts = pd.Timestamp(start, tz="UTC")
    else:
        start_ts = start
    
    start_ms = int(start_ts.timestamp() * 1000)
    timestamps = start_ms + np.arange(n, dtype=np.int64) * tf_ms
    return pd.Series(timestamps, name="timestamp")


def ensure_ohlcv_integrity(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure OHLCV data integrity and proper column order.
    
    Parameters
    ----------
    df : pd.DataFrame
        OHLCV DataFrame to validate
        
    Returns
    -------
    pd.DataFrame
        Validated DataFrame with proper constraints
    """
    # Ensure column order
    required_cols = ["timestamp", "open", "high", "low", "close", "volume"]
    df = df[required_cols].copy()
    
    # Ensure timestamps are monotonic
    df = df.sort_values("timestamp").reset_index(drop=True)
    
    # Ensure price constraints: low <= open,close <= high
    df["low"] = np.minimum(df["low"], np.minimum(df["open"], df["close"]))
    df["high"] = np.maximum(df["high"], np.maximum(df["open"], df["close"]))
    
    # Ensure positive values
    price_cols = ["open", "high", "low", "close"]
    df[price_cols] = np.maximum(df[price_cols], 0.001)
    df["volume"] = np.maximum(df["volume"], 0.1)
    
    return df


def with_volume_pattern(
    df: pd.DataFrame,
    base: float,
    pattern: str = "flat",
    spike_at: Optional[int] = None,
    spike_mult: float = 2.0
) -> pd.DataFrame:
    """
    Apply volume pattern to OHLCV DataFrame.
    
    Parameters
    ----------
    df : pd.DataFrame
        OHLCV DataFrame
    base : float
        Base volume level
    pattern : str
        Volume pattern: "flat", "uptrend", "downtrend", "spike"
    spike_at : int or None
        Index for volume spike (if applicable)
    spike_mult : float
        Volume spike multiplier
        
    Returns
    -------
    pd.DataFrame
        DataFrame with updated volume column
    """
    n = len(df)
    rng = np.random.default_rng(42)
    
    if pattern == "flat":
        volumes = base * (1 + rng.normal(0, 0.1, n))
    elif pattern == "uptrend":
        trend = np.linspace(0.8, 1.2, n)
        volumes = base * trend * (1 + rng.normal(0, 0.1, n))
    elif pattern == "downtrend":
        trend = np.linspace(1.2, 0.8, n)
        volumes = base * trend * (1 + rng.normal(0, 0.1, n))
    elif pattern == "spike":
        volumes = base * (1 + rng.normal(0, 0.1, n))
        if spike_at is not None and 0 <= spike_at < n:
            volumes[spike_at] *= spike_mult
    else:
        volumes = base * (1 + rng.normal(0, 0.1, n))
    
    df = df.copy()
    df["volume"] = np.maximum(volumes, 0.1)
    return df


def to_ccxt_list(df: pd.DataFrame) -> List[List[float]]:
    """
    Convert OHLCV DataFrame to CCXT format list.
    
    Parameters
    ----------
    df : pd.DataFrame
        OHLCV DataFrame
        
    Returns
    -------
    List[List[float]]
        List of [timestamp, open, high, low, close, volume] sublists
    """
    return df[["timestamp", "open", "high", "low", "close", "volume"]].values.tolist()


def make_range_then_breakout_up(
    n_range: int = 40,
    n_post: int = 20,
    level: float = 100.0,
    breakout_ratio: float = 1.02,
    noise: float = 0.001,
    volume_base: float = 1000.0,
    volume_spike: float = 2.0,
    start: Union[str, pd.Timestamp] = "2024-01-01 00:00:00Z",
    timeframe: str = "1h",
    seed: Optional[int] = 42
) -> pd.DataFrame:
    """
    Generate range-bound data followed by upward breakout.
    
    Creates a consolidation pattern around a specified level, followed by
    a clear breakout above the range with volume spike.
    
    Parameters
    ----------
    n_range : int, default 40
        Number of bars in the ranging phase
    n_post : int, default 20
        Number of bars after breakout
    level : float, default 100.0
        Center level for ranging phase
    breakout_ratio : float, default 1.02
        Ratio above range high for breakout close
    noise : float, default 0.001
        Noise level for price generation (as fraction of level)
    volume_base : float, default 1000.0
        Base volume level
    volume_spike : float, default 2.0
        Volume multiplier for breakout bar
    start : str or pd.Timestamp, default "2024-01-01 00:00:00Z"
        Start timestamp
    timeframe : str, default "1h"
        Timeframe for bars
    seed : int or None, default 42
        Random seed for reproducibility
        
    Returns
    -------
    pd.DataFrame
        OHLCV DataFrame with breakout pattern
    """
    rng = set_seed(seed)
    tf_ms = timeframe_to_ms(timeframe)
    n_total = n_range + n_post
    
    # Generate timestamps
    timestamps = make_time_index(n_total, start, tf_ms)
    
    # Range phase: oscillate around level
    range_noise = noise * level
    range_closes = level + rng.normal(0, range_noise, n_range)
    
    # Calculate range boundaries for breakout detection
    range_high = np.max(range_closes + range_noise)
    breakout_target = range_high * breakout_ratio
    
    # Post-breakout phase
    post_closes = np.zeros(n_post)
    post_closes[0] = breakout_target  # First bar breaks out
    
    # Subsequent bars trend higher with some noise
    for i in range(1, n_post):
        drift = rng.normal(0.0005, 0.002) * level
        post_closes[i] = post_closes[i-1] + drift
    
    # Combine phases
    closes = np.concatenate([range_closes, post_closes])
    
    # Generate opens near closes with small jitter
    open_jitter = range_noise * 0.5
    opens = closes + rng.normal(0, open_jitter, n_total)
    
    # Generate wicks
    wick_size = range_noise * 0.8
    highs = np.maximum(opens, closes) + np.abs(rng.normal(0, wick_size, n_total))
    lows = np.minimum(opens, closes) - np.abs(rng.normal(0, wick_size, n_total))
    
    # Create base volumes
    volumes = volume_base * (1 + rng.normal(0, 0.15, n_total))
    volumes[n_range] *= volume_spike  # Spike on breakout bar
    
    # Create DataFrame
    df = pd.DataFrame({
        "timestamp": timestamps,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes
    })
    
    # Add metadata
    df.attrs = {
        "pattern": "range_breakout_up",
        "level": level,
        "breakout_ratio": breakout_ratio,
        "seed": seed,
        "timeframe_ms": tf_ms
    }
    
    return ensure_ohlcv_integrity(df)


def make_false_breakout_up(
    n_range: int = 40,
    n_post: int = 20,
    level: float = 100.0,
    breakout_wick_ratio: float = 1.02,
    close_back_in_ratio: float = 0.998,
    noise: float = 0.001,
    volume_base: float = 1000.0,
    volume_spike: float = 2.0,
    start: Union[str, pd.Timestamp] = "2024-01-01 00:00:00Z",
    timeframe: str = "1h",
    seed: Optional[int] = 42
) -> pd.DataFrame:
    """
    Generate false breakout pattern.
    
    Creates a ranging phase followed by a bar that wicks above resistance
    but closes back within the range, invalidating the breakout.
    
    Parameters
    ----------
    n_range : int, default 40
        Number of bars in ranging phase
    n_post : int, default 20
        Number of bars after false breakout
    level : float, default 100.0
        Center level for ranging phase
    breakout_wick_ratio : float, default 1.02
        Ratio for wick above range high
    close_back_in_ratio : float, default 0.998
        Ratio for close back within range (relative to range high)
    noise : float, default 0.001
        Noise level for price generation
    volume_base : float, default 1000.0
        Base volume level
    volume_spike : float, default 2.0
        Volume multiplier for false breakout bar
    start : str or pd.Timestamp, default "2024-01-01 00:00:00Z"
        Start timestamp
    timeframe : str, default "1h"
        Timeframe for bars
    seed : int or None, default 42
        Random seed
        
    Returns
    -------
    pd.DataFrame
        OHLCV DataFrame with false breakout pattern
    """
    rng = set_seed(seed)
    tf_ms = timeframe_to_ms(timeframe)
    n_total = n_range + n_post
    
    timestamps = make_time_index(n_total, start, tf_ms)
    
    # Range phase
    range_noise = noise * level
    range_closes = level + rng.normal(0, range_noise, n_range)
    range_high = np.max(range_closes + range_noise)
    
    # False breakout phase
    post_closes = np.zeros(n_post)
    post_closes[0] = range_high * close_back_in_ratio  # Close back in range
    
    # Subsequent bars continue range or decline
    for i in range(1, n_post):
        drift = rng.normal(-0.0002, 0.0015) * level
        post_closes[i] = post_closes[i-1] + drift
    
    closes = np.concatenate([range_closes, post_closes])
    
    # Generate opens
    opens = closes + rng.normal(0, range_noise * 0.5, n_total)
    
    # Generate highs and lows
    wick_size = range_noise * 0.8
    highs = np.maximum(opens, closes) + np.abs(rng.normal(0, wick_size, n_total))
    lows = np.minimum(opens, closes) - np.abs(rng.normal(0, wick_size, n_total))
    
    # Force false breakout wick on first post bar
    highs[n_range] = range_high * breakout_wick_ratio
    
    volumes = volume_base * (1 + rng.normal(0, 0.15, n_total))
    volumes[n_range] *= volume_spike
    
    df = pd.DataFrame({
        "timestamp": timestamps,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes
    })
    
    df.attrs = {
        "pattern": "false_breakout_up",
        "level": level,
        "breakout_wick_ratio": breakout_wick_ratio,
        "close_back_in_ratio": close_back_in_ratio,
        "seed": seed,
        "timeframe_ms": tf_ms
    }
    
    return ensure_ohlcv_integrity(df)


def make_breakout_with_retest(
    n_range: int = 40,
    n_retest_gap: int = 3,
    level: float = 100.0,
    breakout_ratio: float = 1.02,
    hold_above_ratio: float = 1.001,
    noise: float = 0.001,
    volume_base: float = 1000.0,
    volume_spike: float = 2.0,
    start: Union[str, pd.Timestamp] = "2024-01-01 00:00:00Z",
    timeframe: str = "1h",
    seed: Optional[int] = 42
) -> pd.DataFrame:
    """
    Generate breakout with successful retest pattern.
    
    Creates a breakout followed by a pullback that retests the former
    resistance as support and holds above it.
    
    Parameters
    ----------
    n_range : int, default 40
        Number of bars in ranging phase
    n_retest_gap : int, default 3
        Bars between breakout and retest
    level : float, default 100.0
        Center level for ranging phase
    breakout_ratio : float, default 1.02
        Breakout close ratio above range high
    hold_above_ratio : float, default 1.001
        Minimum ratio above range high for retest low
    noise : float, default 0.001
        Noise level for price generation
    volume_base : float, default 1000.0
        Base volume level
    volume_spike : float, default 2.0
        Volume multiplier for breakout bar
    start : str or pd.Timestamp, default "2024-01-01 00:00:00Z"
        Start timestamp
    timeframe : str, default "1h"
        Timeframe for bars
    seed : int or None, default 42
        Random seed
        
    Returns
    -------
    pd.DataFrame
        OHLCV DataFrame with breakout retest pattern
    """
    rng = set_seed(seed)
    tf_ms = timeframe_to_ms(timeframe)
    n_post = 20
    n_total = n_range + n_post
    
    timestamps = make_time_index(n_total, start, tf_ms)
    
    # Range phase
    range_noise = noise * level
    range_closes = level + rng.normal(0, range_noise, n_range)
    range_high = np.max(range_closes + range_noise)
    
    # Post-breakout phase
    post_closes = np.zeros(n_post)
    post_closes[0] = range_high * breakout_ratio  # Initial breakout
    
    # Build up to higher level before retest
    retest_peak = post_closes[0] * 1.015
    for i in range(1, n_retest_gap):
        if i < n_post:
            post_closes[i] = post_closes[i-1] + rng.normal(0.003, 0.002) * level
    
    # Retest bar - pull back to just above former resistance
    if n_retest_gap < n_post:
        retest_level = range_high * hold_above_ratio
        post_closes[n_retest_gap] = retest_level + rng.normal(0, range_noise * 0.3)
        
        # Continue upward after successful retest
        for i in range(n_retest_gap + 1, n_post):
            drift = rng.normal(0.002, 0.002) * level
            post_closes[i] = post_closes[i-1] + drift
    
    closes = np.concatenate([range_closes, post_closes])
    
    # Generate other OHLC components
    opens = closes + rng.normal(0, range_noise * 0.5, n_total)
    
    wick_size = range_noise * 0.8
    highs = np.maximum(opens, closes) + np.abs(rng.normal(0, wick_size, n_total))
    lows = np.minimum(opens, closes) - np.abs(rng.normal(0, wick_size, n_total))
    
    # Ensure retest bar touches but doesn't break support
    if n_retest_gap < n_post:
        retest_idx = n_range + n_retest_gap
        lows[retest_idx] = range_high * (1 - noise * 0.5)
    
    volumes = volume_base * (1 + rng.normal(0, 0.15, n_total))
    volumes[n_range] *= volume_spike  # Volume spike on breakout
    
    df = pd.DataFrame({
        "timestamp": timestamps,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes
    })
    
    df.attrs = {
        "pattern": "breakout_with_retest",
        "level": level,
        "breakout_ratio": breakout_ratio,
        "hold_above_ratio": hold_above_ratio,
        "seed": seed,
        "timeframe_ms": tf_ms
    }
    
    return ensure_ohlcv_integrity(df)


def make_range_then_breakdown(
    n_range: int = 40,
    n_post: int = 20,
    level: float = 100.0,
    breakdown_ratio: float = 0.98,
    noise: float = 0.001,
    volume_base: float = 1000.0,
    volume_spike: float = 2.0,
    start: Union[str, pd.Timestamp] = "2024-01-01 00:00:00Z",
    timeframe: str = "1h",
    seed: Optional[int] = 42
) -> pd.DataFrame:
    """
    Generate range-bound data followed by downward breakdown.
    
    Mirror of breakout pattern but with downward movement below support.
    
    Parameters
    ----------
    n_range : int, default 40
        Number of bars in ranging phase
    n_post : int, default 20
        Number of bars after breakdown
    level : float, default 100.0
        Center level for ranging phase
    breakdown_ratio : float, default 0.98
        Ratio below range low for breakdown close
    noise : float, default 0.001
        Noise level for price generation
    volume_base : float, default 1000.0
        Base volume level
    volume_spike : float, default 2.0
        Volume multiplier for breakdown bar
    start : str or pd.Timestamp, default "2024-01-01 00:00:00Z"
        Start timestamp
    timeframe : str, default "1h"
        Timeframe for bars
    seed : int or None, default 42
        Random seed
        
    Returns
    -------
    pd.DataFrame
        OHLCV DataFrame with breakdown pattern
    """
    rng = set_seed(seed)
    tf_ms = timeframe_to_ms(timeframe)
    n_total = n_range + n_post
    
    timestamps = make_time_index(n_total, start, tf_ms)
    
    # Range phase
    range_noise = noise * level
    range_closes = level + rng.normal(0, range_noise, n_range)
    range_low = np.min(range_closes - range_noise)
    
    # Post-breakdown phase
    post_closes = np.zeros(n_post)
    post_closes[0] = range_low * breakdown_ratio  # Initial breakdown
    
    # Continue downward trend
    for i in range(1, n_post):
        drift = rng.normal(-0.0005, 0.002) * level
        post_closes[i] = post_closes[i-1] + drift
    
    closes = np.concatenate([range_closes, post_closes])
    
    opens = closes + rng.normal(0, range_noise * 0.5, n_total)
    
    wick_size = range_noise * 0.8
    highs = np.maximum(opens, closes) + np.abs(rng.normal(0, wick_size, n_total))
    lows = np.minimum(opens, closes) - np.abs(rng.normal(0, wick_size, n_total))
    
    volumes = volume_base * (1 + rng.normal(0, 0.15, n_total))
    volumes[n_range] *= volume_spike
    
    df = pd.DataFrame({
        "timestamp": timestamps,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes
    })
    
    df.attrs = {
        "pattern": "range_breakdown",
        "level": level,
        "breakdown_ratio": breakdown_ratio,
        "seed": seed,
        "timeframe_ms": tf_ms
    }
    
    return ensure_ohlcv_integrity(df)


def make_trend_up(
    n: int = 120,
    start_price: float = 100.0,
    drift: float = 0.0015,
    vol: float = 0.004,
    volume_base: float = 1000.0,
    start: Union[str, pd.Timestamp] = "2024-01-01 00:00:00Z",
    timeframe: str = "1h",
    seed: Optional[int] = 42
) -> pd.DataFrame:
    """
    Generate upward trending data using geometric random walk.
    
    Parameters
    ----------
    n : int, default 120
        Number of bars to generate
    start_price : float, default 100.0
        Starting price level
    drift : float, default 0.0015
        Upward drift per bar (as fraction)
    vol : float, default 0.004
        Volatility (standard deviation of returns)
    volume_base : float, default 1000.0
        Base volume level
    start : str or pd.Timestamp, default "2024-01-01 00:00:00Z"
        Start timestamp
    timeframe : str, default "1h"
        Timeframe for bars
    seed : int or None, default 42
        Random seed
        
    Returns
    -------
    pd.DataFrame
        OHLCV DataFrame with upward trend
    """
    rng = set_seed(seed)
    tf_ms = timeframe_to_ms(timeframe)
    
    timestamps = make_time_index(n, start, tf_ms)
    
    # Generate log returns
    returns = rng.normal(drift, vol, n)
    log_prices = np.cumsum(np.log(start_price) + returns)
    closes = np.exp(log_prices)
    
    # Generate opens near previous close
    opens = np.zeros(n)
    opens[0] = start_price
    for i in range(1, n):
        opens[i] = closes[i-1] * (1 + rng.normal(0, vol * 0.2))
    
    # Generate wicks
    wick_vol = vol * 0.6
    high_wicks = np.abs(rng.normal(0, wick_vol, n))
    low_wicks = np.abs(rng.normal(0, wick_vol, n))
    
    highs = np.maximum(opens, closes) * (1 + high_wicks)
    lows = np.minimum(opens, closes) * (1 - low_wicks)
    
    # Volume with slight upward bias
    volume_trend = np.linspace(0.9, 1.1, n)
    volumes = volume_base * volume_trend * (1 + rng.normal(0, 0.2, n))
    
    df = pd.DataFrame({
        "timestamp": timestamps,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes
    })
    
    df.attrs = {
        "pattern": "trend_up",
        "start_price": start_price,
        "drift": drift,
        "vol": vol,
        "seed": seed,
        "timeframe_ms": tf_ms
    }
    
    return ensure_ohlcv_integrity(df)


def make_sideways_noise(
    n: int = 120,
    center: float = 100.0,
    band: float = 0.01,
    volume_base: float = 1000.0,
    start: Union[str, pd.Timestamp] = "2024-01-01 00:00:00Z",
    timeframe: str = "1h",
    seed: Optional[int] = 42
) -> pd.DataFrame:
    """
    Generate sideways/stationary price series for non-trend tests.
    
    Parameters
    ----------
    n : int, default 120
        Number of bars to generate
    center : float, default 100.0
        Center price level
    band : float, default 0.01
        Band width as fraction of center price
    volume_base : float, default 1000.0
        Base volume level
    start : str or pd.Timestamp, default "2024-01-01 00:00:00Z"
        Start timestamp
    timeframe : str, default "1h"
        Timeframe for bars
    seed : int or None, default 42
        Random seed
        
    Returns
    -------
    pd.DataFrame
        OHLCV DataFrame with sideways movement
    """
    rng = set_seed(seed)
    tf_ms = timeframe_to_ms(timeframe)
    
    timestamps = make_time_index(n, start, tf_ms)
    
    # Mean-reverting process around center
    noise_level = band * center
    closes = np.zeros(n)
    closes[0] = center
    
    for i in range(1, n):
        # Mean reversion with noise
        reversion = -0.1 * (closes[i-1] - center)
        noise = rng.normal(0, noise_level)
        closes[i] = closes[i-1] + reversion + noise
    
    # Generate opens
    opens = closes + rng.normal(0, noise_level * 0.3, n)
    
    # Generate wicks
    wick_size = noise_level * 0.7
    highs = np.maximum(opens, closes) + np.abs(rng.normal(0, wick_size, n))
    lows = np.minimum(opens, closes) - np.abs(rng.normal(0, wick_size, n))
    
    # Flat volume pattern
    volumes = volume_base * (1 + rng.normal(0, 0.15, n))
    
    df = pd.DataFrame({
        "timestamp": timestamps,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes
    })
    
    df.attrs = {
        "pattern": "sideways_noise",
        "center": center,
        "band": band,
        "seed": seed,
        "timeframe_ms": tf_ms
    }
    
    return ensure_ohlcv_integrity(df)


def _is_breakout_bar(df: pd.DataFrame, window: int = 20) -> Optional[int]:
    """
    Find first bar where close exceeds rolling maximum of previous window.
    
    Parameters
    ----------
    df : pd.DataFrame
        OHLCV DataFrame
    window : int, default 20
        Lookback window for rolling maximum
        
    Returns
    -------
    int or None
        Index of first breakout bar, or None if not found
    """
    if len(df) <= window:
        return None
    
    closes = df["close"].values
    
    for i in range(window, len(closes)):
        prev_max = np.max(closes[i-window:i])
        if closes[i] > prev_max:
            return i
    
    return None


def _smoke_all() -> bool:
    """
    Run smoke test on all generator functions.
    
    Returns
    -------
    bool
        True if all generators pass integrity checks
    """
    try:
        # Test each generator with default parameters
        generators = [
            make_range_then_breakout_up,
            make_false_breakout_up,
            make_breakout_with_retest,
            make_range_then_breakdown,
            make_trend_up,
            make_sideways_noise,
        ]
        
        for gen_func in generators:
            df = gen_func(seed=123)  # Use consistent seed
            df_clean = ensure_ohlcv_integrity(df)
            
            # Basic checks
            assert len(df_clean) > 0, f"{gen_func.__name__} produced empty DataFrame"
            assert list(df_clean.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
            assert df_clean["timestamp"].is_monotonic_increasing
            assert (df_clean["high"] >= df_clean["open"]).all()
            assert (df_clean["high"] >= df_clean["close"]).all()
            assert (df_clean["low"] <= df_clean["open"]).all()
            assert (df_clean["low"] <= df_clean["close"]).all()
            assert (df_clean["volume"] > 0).all()
        
        return True
        
    except Exception as e:
        print(f"Smoke test failed: {e}")
        return False


def _plot(df: pd.DataFrame, title: str = "") -> None:
    """
    Plot OHLCV data using matplotlib if available.
    
    Parameters
    ----------
    df : pd.DataFrame
        OHLCV DataFrame to plot
    title : str, default ""
        Plot title
    """
    try:
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from datetime import datetime
        
        # Convert timestamps to datetime
        dates = [datetime.fromtimestamp(ts/1000) for ts in df["timestamp"]]
        
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True,
                                       gridspec_kw={'height_ratios': [3, 1]})
        
        # Price plot
        ax1.plot(dates, df["close"], label="Close", linewidth=1.5)
        ax1.fill_between(dates, df["low"], df["high"], alpha=0.3, label="Range")
        ax1.set_ylabel("Price")
        ax1.set_title(title or f"OHLCV Data ({df.attrs.get('pattern', 'Unknown')})")
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        
        # Volume plot
        ax2.bar(dates, df["volume"], alpha=0.7, width=0.8)
        ax2.set_ylabel("Volume")
        ax2.set_xlabel("Time")
        ax2.grid(True, alpha=0.3)
        
        # Format x-axis
        ax2.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d %H:%M'))
        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.show()
        
    except ImportError:
        print("Matplotlib not available for plotting")


def save_csv(df: pd.DataFrame, path: str) -> str:
    """
    Save DataFrame to CSV file for debugging.
    
    Parameters
    ----------
    df : pd.DataFrame
        DataFrame to save
    path : str
        Output file path
        
    Returns
    -------
    str
        Path to saved file
    """
    df.to_csv(path, index=False)
    return path


if __name__ == "__main__":
    print("=== Synthetic OHLCV Generator Demo ===\n")
    
    # Test each generator
    generators = [
        ("Range Breakout Up", make_range_then_breakout_up),
        ("False Breakout Up", make_false_breakout_up),
        ("Breakout with Retest", make_breakout_with_retest),
        ("Range Breakdown", make_range_then_breakdown),
        ("Upward Trend", make_trend_up),
        ("Sideways Noise", make_sideways_noise),
    ]
    
    for name, gen_func in generators:
        print(f"\n--- {name} ---")
        df = gen_func(seed=42)
        
        print(f"Shape: {df.shape}")
        print(f"Pattern: {df.attrs.get('pattern', 'N/A')}")
        print(f"Timeframe: {df.attrs.get('timeframe_ms', 'N/A')}ms")
        
        print("\nFirst 3 rows:")
        print(df.head(3).to_string(index=False))
        
        print("\nLast 3 rows:")
        print(df.tail(3).to_string(index=False))
        
        print(f"\nPrice range: {df['close'].min():.2f} - {df['close'].max():.2f}")
        print(f"Volume range: {df['volume'].min():.0f} - {df['volume'].max():.0f}")
        
        # Check for breakout if applicable
        if "breakout" in df.attrs.get("pattern", ""):
            breakout_idx = _is_breakout_bar(df, window=20)
            if breakout_idx is not None:
                print(f"Breakout detected at index {breakout_idx}")
        
        # Optional plotting
        try:
            _plot(df, name)
        except ImportError:
            pass
    
    # Run smoke test
    print("\n--- Smoke Test ---")
    smoke_result = _smoke_all()
    print(f"All generators passed: {smoke_result}")
    
    # Demo utility functions
    print("\n--- Utility Demo ---")
    sample_df = make_range_then_breakout_up(n_range=10, n_post=5, seed=123)
    
    print("Timeframe conversions:")
    for tf in ["1m", "5m", "15m", "1h", "4h", "1d"]:
        print(f"  {tf} = {timeframe_to_ms(tf):,}ms")
    
    print("\nCCXT format sample:")
    ccxt_data = to_ccxt_list(sample_df.head(3))
    for row in ccxt_data:
        print(f"  {row}")
    
    print("\nVolume pattern demo:")
    vol_df = with_volume_pattern(sample_df, base=1000, pattern="spike", 
                                spike_at=10, spike_mult=3.0)
    print(f"  Volume at spike: {vol_df.iloc[10]['volume']:.0f}")
    
    print("\n=== Demo Complete ===")