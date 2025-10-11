# tests/test_strategies/test_breakout.py
import math
from typing import Tuple

import numpy as np
import pandas as pd
import pytest

from strategies.breakout import (
    BreakoutStrategy,
)

# ---------------------------------------------------------------------
# Synthetic OHLCV generators (deterministic, strategy-aware)
# ---------------------------------------------------------------------

def _time_index(n: int, start: str = "2024-01-01", freq: str = "1H") -> pd.DatetimeIndex:
    return pd.date_range(start=start, periods=n, freq=freq, tz="UTC")


def _make_body_wicks(
    close: np.ndarray,
    rng: np.random.Generator | None = None,
    vol_base: float = 1_000.0,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    rng = rng or np.random.default_rng(42)
    n = len(close)
    open_ = close * (1 + rng.normal(0, 0.0007, n))
    body_hi = np.maximum(open_, close)
    body_lo = np.minimum(open_, close)
    # keep ranges modest so ATR stays realistic
    high = body_hi * (1 + np.abs(rng.normal(0, 0.0016, n)))
    low = body_lo * (1 - np.abs(rng.normal(0, 0.0016, n)))
    volume = np.full(n, vol_base) * (1 + np.abs(rng.normal(0, 0.05, n)))
    return open_, high, low, close.copy(), volume


def make_range_then_breakout_up(
    resistance_window: int = 20,
    n_range: int = 40,
    n_post: int = 10,
    level: float = 100.0,
    atr_mult_on_break: float = 2.0,   # how many ATR above prior max to close
    vol_spike_mult: float = 3.0,
    seed: int = 7,
) -> pd.DataFrame:
    """
    Build a consolidation of n_range bars, then a **guaranteed** long breakout:
    the breakout close is placed above the prior rolling highest_high by
    (atr_mult_on_break * ATR_est). This mirrors strategy logic which compares
    against highest_high on the **previous** bar.
    """
    assert n_range >= resistance_window + 1, "n_range must be > resistance_window"
    rng = np.random.default_rng(seed)
    n = n_range + n_post
    idx = _time_index(n)

    # Consolidation closes near level → small ranges
    close = np.full(n, level, dtype=float)
    close[:n_range] = level * (1 + rng.normal(0, 0.001, n_range))

    # Draft candle shapes for range phase to compute prior_max & ATR proxy
    o, h, l, c, v = _make_body_wicks(close, rng=rng)
    prior_max = float(np.max(h[:n_range]))
    # Estimate ATR like strategy’s TR-mean scale (keep conservative)
    tr_est = (h[:n_range] - l[:n_range]).mean()
    atr_est = float(max(tr_est, 0.0015 * level))  # fallback lower bound

    # Previous bar close slightly below level (within retest margin used by strategy)
    prev = n_range - 1
    c[prev] = max(min(level - 0.2 * atr_est, h[prev]), l[prev] + 1e-6)

    # Breakout bar: force close above prior_max by ATR multiple
    brk = n_range
    c[brk] = prior_max + atr_mult_on_break * atr_est

    # Drift up afterwards so confirmation checks can pass
    for i in range(brk + 1, n):
        c[i] = c[i - 1] * (1 + rng.normal(0.0006, 0.0008))

    # Rebuild wicks for the entire series based on final closes
    o, h, l, _, v = _make_body_wicks(c, rng=rng)
    # Enforce proper breakout bar geometry
    h[brk] = max(h[brk], c[brk] * 1.001)
    l[brk] = min(l[brk], min(o[brk], c[brk]) * 0.999)
    # Volume spike on breakout
    v[brk] *= vol_spike_mult

    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v}, index=idx)


def make_false_breakout_up(
    resistance_window: int = 20,
    n_range: int = 40,
    level: float = 100.0,
    wick_mult_above: float = 1.02,
    seed: int = 11,
) -> pd.DataFrame:
    """Wick above prior max with non-bullish close ⇒ should be filtered out."""
    assert n_range >= resistance_window + 1
    rng = np.random.default_rng(seed)
    n = n_range + 5
    idx = _time_index(n)

    close = np.full(n, level, dtype=float)
    close[:n_range] = level * (1 + rng.normal(0, 0.001, n_range))
    o, h, l, c, v = _make_body_wicks(close, rng=rng)

    prior_max = float(np.max(h[:n_range]))
    brk = n_range
    # Long upper wick above prior max, but close ≈ open or below (not bullish)
    h[brk] = max(h[brk], prior_max * wick_mult_above)
    c[brk] = min(o[brk], prior_max)  # closes at or below level
    v[brk] *= 3.0

    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v}, index=idx)


def make_range_then_breakdown(
    resistance_window: int = 20,
    n_range: int = 40,
    n_post: int = 10,
    level: float = 100.0,
    atr_mult_on_break: float = 2.0,
    vol_spike_mult: float = 3.0,
    seed: int = 9,
) -> pd.DataFrame:
    """Mirror: guarantee a short breakdown below prior rolling lowest_low."""
    assert n_range >= resistance_window + 1
    rng = np.random.default_rng(seed)
    n = n_range + n_post
    idx = _time_index(n)

    close = np.full(n, level, dtype=float)
    close[:n_range] = level * (1 + rng.normal(0, 0.001, n_range))
    o, h, l, c, v = _make_body_wicks(close, rng=rng)
    prior_min = float(np.min(l[:n_range]))
    tr_est = (h[:n_range] - l[:n_range]).mean()
    atr_est = float(max(tr_est, 0.0015 * level))

    prev = n_range - 1
    c[prev] = min(level + 0.2 * atr_est, h[prev] - 1e-6)

    brk = n_range
    c[brk] = prior_min - atr_mult_on_break * atr_est
    for i in range(brk + 1, n):
        c[i] = c[i - 1] * (1 - rng.normal(0.0006, 0.0008))

    o, h, l, _, v = _make_body_wicks(c, rng=rng)
    l[brk] = min(l[brk], c[brk] * 0.999)
    h[brk] = max(h[brk], max(o[brk], c[brk]) * 1.001)
    v[brk] *= vol_spike_mult

    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v}, index=idx)


# ---------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------

def _cfg(**over):
    cfg = dict(
        resistance_window=20,
        min_breakout_ratio=0.5,   # ATR multiples beyond prior level
        retest_allowed=True,
        false_breakout_filter=True,
        volume_requirement=1.5,
        min_confidence=0.5,       # relaxed so generators pass comfortably
    )
    cfg.update(over)
    return cfg


def _ctx(**over):
    ctx = dict(
        mode="backtest",
        exchange="test",
        symbol="TEST/USDT",
        account_equity_usd=10_000.0,
        base_position_size=0.02,
        volatility_multiplier=1.0,
        max_position=5_000.0,
    )
    ctx.update(over)
    return ctx


# ---------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------

def test_generate_signal_signature_works():
    df = make_range_then_breakout_up()
    brk = BreakoutStrategy(_cfg())
    sig = brk.generate_signal(df)  # context optional
    assert sig is None or hasattr(sig, "side")


def test_clean_breakout_long():
    df = make_range_then_breakout_up()
    brk = BreakoutStrategy(_cfg())
    sig = brk.generate_signal(df, context=_ctx())
    assert sig is not None, "Expected a breakout signal"
    assert sig.side in ("buy", "long")
    assert sig.confidence >= 0.5
    assert "breakout_level" in sig.meta and "volume_ratio" in sig.meta


def test_false_breakout_reject():
    df = make_false_breakout_up()
    brk = BreakoutStrategy(_cfg())
    sig = brk.generate_signal(df, context=_ctx())
    assert sig is None, "False breakout with long upper wick should be rejected"


def test_retest_allowed():
    # Wider range so confirmation bars can look back
    df = make_range_then_breakout_up(resistance_window=20, n_range=45)
    brk = BreakoutStrategy(_cfg(retest_allowed=True, confirmation_bars=1))
    sig = brk.generate_signal(df, context=_ctx())
    assert sig is not None, "Retest-enabled setup should accept valid breakout"


def test_no_volume_no_signal():
    # Create breakout but remove the spike
    df = make_range_then_breakout_up()
    df["volume"] = df["volume"].rolling(20, min_periods=1).mean()  # flatten volume
    brk = BreakoutStrategy(_cfg(volume_requirement=2.5))
    sig = brk.generate_signal(df, context=_ctx())
    assert sig is None, "Should reject breakout without required volume spike"


def test_breakout_short():
    df = make_range_then_breakdown()
    brk = BreakoutStrategy(_cfg(side="short"))
    sig = brk.generate_signal(df, context=_ctx())
    assert sig is not None
    assert sig.side in ("sell", "short")


def test_meta_fields_present():
    df = make_range_then_breakout_up()
    brk = BreakoutStrategy(_cfg())
    sig = brk.generate_signal(df, context=_ctx())
    assert sig is not None
    m = sig.meta
    for k in ("breakout_level", "entry_price", "stop_loss", "atr", "volume_ratio", "timestamp"):
        assert k in m, f"Missing meta key: {k}"


def test_config_boundary():
    # Accept both our custom message and pydantic's phrasing
    with pytest.raises(ValueError) as ei:
        BreakoutStrategy(dict(resistance_window=3))  # too small
    msg = str(ei.value).lower()
    assert ("resistance_window" in msg) and (">= 5" in msg or "greater than or equal" in msg)


def test_custom_resistance_window():
    df = make_range_then_breakout_up(resistance_window=30, n_range=50)
    brk = BreakoutStrategy(_cfg(resistance_window=30))
    sig = brk.generate_signal(df, context=_ctx())
    assert sig is not None


def test_volume_requirement_enforcement():
    df = make_range_then_breakout_up()
    brk = BreakoutStrategy(_cfg(volume_requirement=3.5))  # spike is ~3.0 ⇒ reject
    sig = brk.generate_signal(df, context=_ctx())
    assert sig is None, "Volume requirement should block the signal"


def test_idempotency_same_df_same_signal():
    df = make_range_then_breakout_up()
    brk = BreakoutStrategy(_cfg())
    s1 = brk.generate_signal(df, context=_ctx())
    s2 = brk.generate_signal(df, context=_ctx())
    assert (s1 is None and s2 is None) or (s1 is not None and s2 is not None)
    if s1 and s2:
        assert s1.side == s2.side
        assert math.isclose(s1.meta["breakout_level"], s2.meta["breakout_level"], rel_tol=1e-6)
        assert math.isclose(s1.meta["entry_price"], s2.meta["entry_price"], rel_tol=1e-6)


def test_backtest_loop_smoke():
    # Sweep rolling windows; ensure at least one signal by the time we pass breakout bar
    df = make_range_then_breakout_up(n_range=60, n_post=30)
    brk = BreakoutStrategy(_cfg())
    ctx = _ctx()
    got = 0
    for end in range(30, len(df) + 1):
        sub = df.iloc[:end]
        sig = brk.generate_signal(sub, context=ctx)
        if sig:
            got += 1
    assert got >= 1, "Expected at least one signal over the sweep"
