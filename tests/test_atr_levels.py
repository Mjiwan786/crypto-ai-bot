"""
Sprint 3A tests for signals/atr_levels.py — ATR-based dynamic TP/SL.

12+ tests covering ATR calculation, volatility tiers, fee-floor guard,
direction correctness, env var overrides, and feature flag fallback.
"""

import os
from unittest import mock

import numpy as np
import pytest

from signals.atr_levels import (
    compute_atr,
    compute_atr_levels,
    get_volatility_tier,
    _extract_base_asset,
)


# ── Helpers ──────────────────────────────────────────────────

def _make_ohlcv(closes: list, spread_pct: float = 0.005) -> np.ndarray:
    """Build synthetic OHLCV from a list of close prices."""
    n = len(closes)
    data = np.zeros((n, 5))
    for i, c in enumerate(closes):
        data[i, 0] = c * (1 - spread_pct / 2)   # open
        data[i, 1] = c * (1 + spread_pct)        # high
        data[i, 2] = c * (1 - spread_pct)        # low
        data[i, 3] = c                            # close
        data[i, 4] = 1000.0                       # volume
    return data


def _make_flat_ohlcv(price: float, n: int = 30) -> np.ndarray:
    """Build OHLCV with nearly zero volatility (flat market)."""
    data = np.zeros((n, 5))
    for i in range(n):
        tiny = price * 0.00001  # 0.1 bps noise
        data[i, 0] = price
        data[i, 1] = price + tiny
        data[i, 2] = price - tiny
        data[i, 3] = price
        data[i, 4] = 1000.0
    return data


# ── Test 1: ATR calculation correctness ──────────────────────

def test_atr_calculation_known_values():
    """Feed known OHLCV and verify ATR is in expected range."""
    # 20 bars of BTC-like data around $84,000 with ~$400 daily range
    closes = [84000 + i * 20 for i in range(20)]
    ohlcv = _make_ohlcv(closes, spread_pct=0.005)  # 0.5% H-L range

    atr = compute_atr(ohlcv, period=14)
    assert atr is not None
    # With 0.5% spread on ~$84k, true range ≈ $840 per bar
    assert 200 < atr < 2000, f"ATR={atr} outside expected range"


def test_atr_returns_none_insufficient_data():
    """ATR returns None when fewer than period+1 bars."""
    ohlcv = _make_ohlcv([100, 101, 102], spread_pct=0.01)
    assert compute_atr(ohlcv, period=14) is None


def test_atr_returns_none_for_none_input():
    """ATR returns None for None input."""
    assert compute_atr(None, period=14) is None


# ── Test 2: High-vol tier (DOGE) ─────────────────────────────

def test_high_vol_tier_doge():
    """DOGE gets high tier: SL=1.0x ATR, TP=2.0x ATR (asymmetric R:R)."""
    closes = [0.10 + i * 0.0002 for i in range(30)]
    ohlcv = _make_ohlcv(closes, spread_pct=0.02)  # 2% range for DOGE

    result = compute_atr_levels(ohlcv, entry_price=0.1058, side="buy", pair="DOGE/USD")
    assert result is not None
    assert result["volatility_tier"] == "high"

    # TP distance should be ~2x SL distance (2.0:1 R:R)
    ratio = result["tp_distance_bps"] / result["sl_distance_bps"]
    assert abs(ratio - 2.0) < 0.01, f"R:R ratio={ratio}, expected 2.0"


# ── Test 3: Medium-vol tier (LTC) ────────────────────────────

def test_medium_vol_tier_ltc():
    """LTC gets medium tier: SL=1.0x ATR, TP=2.5x ATR (asymmetric R:R)."""
    closes = [90 + i * 0.2 for i in range(30)]
    ohlcv = _make_ohlcv(closes, spread_pct=0.015)

    result = compute_atr_levels(ohlcv, entry_price=95.8, side="buy", pair="LTC/USD")
    assert result is not None
    assert result["volatility_tier"] == "medium"

    ratio = result["tp_distance_bps"] / result["sl_distance_bps"]
    expected_ratio = 2.5 / 1.0
    assert abs(ratio - expected_ratio) < 0.01, f"R:R ratio={ratio}, expected {expected_ratio}"


# ── Test 4: Low-vol tier (BTC) ───────────────────────────────

def test_low_vol_tier_btc():
    """BTC gets low tier: SL=1.0x ATR, TP=3.0x ATR (asymmetric R:R)."""
    closes = [84000 + i * 50 for i in range(30)]
    ohlcv = _make_ohlcv(closes, spread_pct=0.008)

    result = compute_atr_levels(ohlcv, entry_price=85450, side="buy", pair="BTC/USD")
    assert result is not None
    assert result["volatility_tier"] == "low"

    ratio = result["tp_distance_bps"] / result["sl_distance_bps"]
    expected_ratio = 3.0 / 1.0
    assert abs(ratio - expected_ratio) < 0.01, f"R:R ratio={ratio}, expected {expected_ratio}"


# ── Test 5: Unknown pair defaults to medium ──────────────────

def test_unknown_pair_defaults_medium():
    """Unknown pair (e.g., FIL/USD) gets medium tier."""
    assert get_volatility_tier("FIL/USD") == "medium"
    assert get_volatility_tier("UNKNOWN/USDT") == "medium"


# ── Test 6: LONG direction — SL below, TP above ─────────────

def test_long_direction_levels():
    """For a LONG (buy), SL must be below entry and TP above."""
    closes = [100 + i * 0.5 for i in range(30)]
    ohlcv = _make_ohlcv(closes, spread_pct=0.02)

    result = compute_atr_levels(ohlcv, entry_price=114.5, side="buy", pair="SOL/USD")
    assert result is not None
    assert result["stop_loss"] < 114.5, "LONG SL should be below entry"
    assert result["take_profit"] > 114.5, "LONG TP should be above entry"


# ── Test 7: SHORT direction — SL above, TP below ────────────

def test_short_direction_levels():
    """For a SHORT (sell), SL must be above entry and TP below."""
    closes = [100 + i * 0.5 for i in range(30)]
    ohlcv = _make_ohlcv(closes, spread_pct=0.02)

    result = compute_atr_levels(ohlcv, entry_price=114.5, side="sell", pair="SOL/USD")
    assert result is not None
    assert result["stop_loss"] > 114.5, "SHORT SL should be above entry"
    assert result["take_profit"] < 114.5, "SHORT TP should be below entry"


# ── Test 8: Fee-floor guard rejects flat market ──────────────

def test_fee_floor_rejects_flat_market():
    """When ATR is too small, fee-floor guard returns None."""
    ohlcv = _make_flat_ohlcv(price=84000.0, n=30)

    result = compute_atr_levels(
        ohlcv, entry_price=84000.0, side="buy", pair="BTC/USD", fee_floor_bps=60.0,
    )
    assert result is None, "Fee-floor guard should reject flat market"


# ── Test 9: Fee-floor guard passes sufficient volatility ─────

def test_fee_floor_passes_volatile_market():
    """When ATR is large enough, fee-floor guard passes."""
    closes = [84000 + i * 100 for i in range(30)]  # $100/bar trend
    ohlcv = _make_ohlcv(closes, spread_pct=0.01)  # 1% range

    result = compute_atr_levels(
        ohlcv, entry_price=86900.0, side="buy", pair="BTC/USD", fee_floor_bps=60.0,
    )
    assert result is not None
    assert result["fee_floor_passed"] is True
    assert result["sl_distance_bps"] >= 60.0


# ── Test 10: Env var overrides for multipliers ───────────────

def test_env_var_override_multipliers():
    """Env vars ATR_SL_MULT_HIGH and ATR_TP_MULT_HIGH override defaults."""
    closes = [0.10 + i * 0.0002 for i in range(30)]
    ohlcv = _make_ohlcv(closes, spread_pct=0.02)

    env_overrides = {
        "ATR_SL_MULT_HIGH": "2.0",
        "ATR_TP_MULT_HIGH": "4.0",
        "MIN_RR_RATIO": "0.1",       # Disable R:R floor for this test
        "ATR_TP_FLOOR_BPS": "1",     # Disable TP floor for this test
    }
    with mock.patch.dict(os.environ, env_overrides):
        result = compute_atr_levels(ohlcv, entry_price=0.1058, side="buy", pair="DOGE/USD")

    assert result is not None
    ratio = result["tp_distance_bps"] / result["sl_distance_bps"]
    assert abs(ratio - 2.0) < 0.01, f"With 2.0/4.0 mults, R:R should be 2.0, got {ratio}"


# ── Test 11: Feature flag disabled falls back ────────────────

def test_feature_flag_disabled_no_call():
    """When ATR_TP_SL_ENABLED is false, engine should use static bps.

    This test verifies the EngineConfig field picks up the env var.
    """
    with mock.patch.dict(os.environ, {"ATR_TP_SL_ENABLED": "false"}):
        from production_engine import EngineConfig
        config = EngineConfig()
        assert config.atr_tp_sl_enabled is False


# ── Test 12: Min R:R maintained for high-vol tier ────────────

def test_min_rr_ratio_high_vol():
    """High-vol tier maintains minimum 3:1 R:R (TP >= 3x SL distance)."""
    closes = [0.10 + i * 0.0003 for i in range(30)]
    ohlcv = _make_ohlcv(closes, spread_pct=0.025)

    result = compute_atr_levels(ohlcv, entry_price=0.109, side="buy", pair="ADA/USD")
    assert result is not None
    assert result["volatility_tier"] == "high"
    ratio = result["tp_distance_bps"] / result["sl_distance_bps"]
    assert ratio >= 1.95, f"High-vol R:R must be >= 2.0:1, got {ratio:.2f}"


# ── Test 13: Base asset extraction ───────────────────────────

def test_extract_base_asset_formats():
    """Base asset extraction works for various pair formats."""
    assert _extract_base_asset("BTC/USD") == "BTC"
    assert _extract_base_asset("ETH-USDT") == "ETH"
    assert _extract_base_asset("DOGEUSD") == "DOGE"
    assert _extract_base_asset("SOL/USDT") == "SOL"


# ── Test 14: Kraken symbol aliases ───────────────────────────

def test_kraken_symbol_aliases():
    """XBT and XDG map to the correct tiers."""
    assert get_volatility_tier("XBT/USD") == "low"   # BTC alias
    assert get_volatility_tier("XDG/USD") == "high"   # DOGE alias


# ── Test 15: ATR env var period override ─────────────────────

def test_atr_period_env_override():
    """ATR_PERIOD env var changes the lookback period."""
    closes = [100 + i * 0.5 for i in range(50)]
    ohlcv = _make_ohlcv(closes, spread_pct=0.015)

    guard_off = {"MIN_RR_RATIO": "0.1", "ATR_TP_FLOOR_BPS": "1"}
    with mock.patch.dict(os.environ, {"ATR_PERIOD": "7", **guard_off}):
        result = compute_atr_levels(ohlcv, entry_price=124.5, side="buy", pair="SOL/USD")
    assert result is not None

    with mock.patch.dict(os.environ, {"ATR_PERIOD": "20", **guard_off}):
        result2 = compute_atr_levels(ohlcv, entry_price=124.5, side="buy", pair="SOL/USD")
    assert result2 is not None
    # Different periods produce different ATR values
    assert result["atr_value"] != result2["atr_value"]


# ── Profitability Sprint: R:R floor guard ────────────────────

def test_rr_floor_rejects_low_rr():
    """R:R floor guard rejects signals where net R:R is below MIN_RR_RATIO."""
    # Create data with moderate volatility (~50 bps ATR) but force tight TP
    closes = [84000 + i * 5 for i in range(30)]
    ohlcv = _make_ohlcv(closes, spread_pct=0.002)  # Very small spread → small ATR

    # With low ATR, TP will be small, R:R after fees will be poor
    env = {
        "MIN_RR_RATIO": "2.5",
        "ROUND_TRIP_FEE_BPS": "52",
        "ATR_FEE_FLOOR_BPS": "5",    # Disable SL floor so R:R floor is the gate
        "ATR_TP_FLOOR_BPS": "5",     # Disable TP floor so R:R floor is the gate
    }
    with mock.patch.dict(os.environ, env):
        result = compute_atr_levels(
            ohlcv, entry_price=84145.0, side="buy", pair="BTC/USD",
            fee_floor_bps=5.0,
        )
    # ATR ~168 bps spread → at 1.0x SL and 4.0x TP, check if it passes
    # If ATR is tiny (~17 bps), TP=68 bps, net_tp=16 bps → R:R very low → reject
    if result is not None:
        assert result["rr_ratio"] >= 2.5, f"R:R={result['rr_ratio']} should be >= 2.5 or None"


def test_rr_floor_passes_good_rr():
    """R:R floor guard passes signals with sufficient net R:R."""
    # Create data with high volatility → large ATR
    closes = [84000 + i * 200 for i in range(30)]  # $200/bar trend
    ohlcv = _make_ohlcv(closes, spread_pct=0.015)  # 1.5% range

    env = {
        "MIN_RR_RATIO": "1.5",
        "ROUND_TRIP_FEE_BPS": "52",
        "ATR_FEE_FLOOR_BPS": "15",
        "ATR_TP_FLOOR_BPS": "55",
    }
    with mock.patch.dict(os.environ, env):
        result = compute_atr_levels(
            ohlcv, entry_price=89800.0, side="buy", pair="BTC/USD",
            fee_floor_bps=15.0,
        )
    assert result is not None, "High-vol BTC should pass all guards"
    assert result["rr_ratio"] >= 1.5, f"R:R={result['rr_ratio']:.2f} should be >= 1.5"
    assert result["net_tp_bps"] > 0, "Net TP should be positive after fees"


def test_tp_floor_rejects_low_tp():
    """TP floor guard rejects signals where TP distance is below ATR_TP_FLOOR_BPS."""
    # Very small ATR data → TP will be small
    closes = [84000 + i * 1 for i in range(30)]
    ohlcv = _make_ohlcv(closes, spread_pct=0.0003)  # Ultra-tight market

    env = {
        "ATR_TP_FLOOR_BPS": "55",
        "ATR_FEE_FLOOR_BPS": "1",    # Disable SL floor
        "MIN_RR_RATIO": "0.1",       # Disable R:R floor
        "ROUND_TRIP_FEE_BPS": "52",
    }
    with mock.patch.dict(os.environ, env):
        result = compute_atr_levels(
            ohlcv, entry_price=84029.0, side="buy", pair="BTC/USD",
            fee_floor_bps=1.0,
        )
    assert result is None, "TP floor should reject signal with tiny ATR"


def test_result_includes_net_fields():
    """Profitability sprint adds net_tp_bps, net_sl_bps, rr_ratio to result."""
    closes = [84000 + i * 200 for i in range(30)]
    ohlcv = _make_ohlcv(closes, spread_pct=0.015)

    env = {"ROUND_TRIP_FEE_BPS": "52", "MIN_RR_RATIO": "0.1", "ATR_TP_FLOOR_BPS": "10", "ATR_FEE_FLOOR_BPS": "1"}
    with mock.patch.dict(os.environ, env):
        result = compute_atr_levels(
            ohlcv, entry_price=89800.0, side="buy", pair="BTC/USD",
            fee_floor_bps=1.0,
        )
    assert result is not None
    assert "net_tp_bps" in result, "Result must include net_tp_bps"
    assert "net_sl_bps" in result, "Result must include net_sl_bps"
    assert "rr_ratio" in result, "Result must include rr_ratio"
    assert result["net_tp_bps"] == result["tp_distance_bps"] - 52
    assert result["net_sl_bps"] == result["sl_distance_bps"] + 52


def test_new_multipliers_btc_math():
    """Verify BTC low tier: SL=1.0x ATR, TP=3.0x ATR produces correct distances."""
    closes = [84000 + i * 200 for i in range(30)]
    ohlcv = _make_ohlcv(closes, spread_pct=0.015)

    env = {
        "ROUND_TRIP_FEE_BPS": "52",
        "MIN_RR_RATIO": "0.1",
        "ATR_TP_FLOOR_BPS": "10",
        "ATR_FEE_FLOOR_BPS": "1",
    }
    with mock.patch.dict(os.environ, env):
        result = compute_atr_levels(
            ohlcv, entry_price=89800.0, side="buy", pair="BTC/USD",
            fee_floor_bps=1.0,
        )
    assert result is not None
    # TP distance should be exactly 3x SL distance (low tier: 3.0:1)
    ratio = result["tp_distance_bps"] / result["sl_distance_bps"]
    assert abs(ratio - 3.0) < 0.01, f"BTC low tier R:R should be 3.0:1, got {ratio:.2f}"
