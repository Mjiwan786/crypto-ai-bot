"""
agents/scalper/risk/limits.py

Risk limit definitions and calculations for the scalping system.
All monetary values here are normalized to USD for consistency with RiskManager.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from ..config_loader import KrakenScalpingConfig

# ------------------------------- Position Limits -------------------------------


@dataclass
class PositionLimits:
    """
    Position-level risk limits.

    Resolution order for max position size (in UNITS of the base asset):
    1) Explicit per-pair limit in `pair_limits[symbol]["max_size"]`
    2) Derived from exposure-per-symbol (USD) divided by a reference price:
       max_units = (per_symbol_max_exposure * max_total_exposure_usd) / reference_price
       where reference_price is taken from:
         - config.risk.reference_prices[symbol] if present
         - config.risk.default_reference_price_usd or 1000.0 fallback
    """

    def __init__(self, config: KrakenScalpingConfig):
        self.config = config

        # Base exposure constraints from config
        # per_symbol_max_exposure is expected as a ratio in [0,1]
        # (e.g., 0.2 == 20% of total exposure)
        self.max_position_pct: float = float(getattr(config.risk, "per_symbol_max_exposure", 0.2))
        self.max_total_exposure_usd: float = float(
            getattr(config.risk, "max_total_exposure_usd", 10_000.0)
        )

        # Reference prices (optional) for converting USD caps to units
        self.reference_prices: Dict[str, float] = dict(
            getattr(config.risk, "reference_prices", {}) or {}
        )
        self.default_reference_price_usd: float = float(
            getattr(config.risk, "default_reference_price_usd", 1000.0)
        )

        # Pair-specific hard caps (units & notional) – override everything else if present
        # Consider moving these to config if you want runtime control.
        self.pair_limits: Dict[str, Dict[str, float]] = {
            "BTC/USD": {"max_size": 0.1, "max_notional": 5000.0},
            "ETH/USD": {"max_size": 2.0, "max_notional": 4000.0},
            "SOL/USD": {"max_size": 50.0, "max_notional": 3000.0},
            "ADA/USD": {"max_size": 1000.0, "max_notional": 2000.0},
            # Add/override via config by mutating this dict in your bootstrap if desired.
        }

    def get_max_position_size(self, symbol: str) -> float:
        """
        Maximum position size in UNITS for the given symbol.
        Uses explicit per-pair 'max_size' when available; otherwise derives from USD caps
        and a reference price.
        """
        if symbol in self.pair_limits and "max_size" in self.pair_limits[symbol]:
            return float(self.pair_limits[symbol]["max_size"])

        # Derive from per-symbol exposure cap in USD and a reference price
        per_symbol_usd_cap = float(
            self.max_total_exposure_usd * max(0.0, min(1.0, self.max_position_pct))
        )
        ref_price = float(self.reference_prices.get(symbol, self.default_reference_price_usd))
        ref_price = max(ref_price, 1e-9)  # guard against zero/neg
        return per_symbol_usd_cap / ref_price

    def get_max_notional(self, symbol: str) -> float:
        """
        Maximum notional (USD) for the given symbol.
        Uses explicit per-pair 'max_notional' when available; otherwise uses per-symbol
        exposure cap.
        """
        if symbol in self.pair_limits and "max_notional" in self.pair_limits[symbol]:
            return float(self.pair_limits[symbol]["max_notional"])

        return float(self.max_total_exposure_usd * max(0.0, min(1.0, self.max_position_pct)))


# ------------------------------- Portfolio Limits -------------------------------


@dataclass
class RiskLimits:
    """
    Portfolio-level risk limits, normalized to USD where applicable.

    - max_daily_loss (USD, negative): if daily P&L < max_daily_loss → breach.
    - max_daily_drawdown (USD, positive): if drawdown_amount > max_daily_drawdown → breach.
    - max_total_exposure (USD, positive): total absolute notional exposure cap.
    - max_concentration_ratio (0..1): largest position % of total exposure cap.
    """

    def __init__(self, config: KrakenScalpingConfig):
        self.config = config

        # ----- Account context used for %→USD normalization -----
        equity_usd = float(getattr(getattr(config, "account", object()), "equity_usd", 0.0) or 0.0)
        # Provide conservative fallback equity if % inputs are used without equity defined
        if equity_usd <= 0:
            equity_usd = float(getattr(config.risk, "equity_usd_fallback", 10_000.0))

        # ----- Daily stop loss -----
        # Accept either USD (e.g., -100.0) or ratio (e.g., -0.02 for -2%).
        raw_daily_sl = getattr(config.risk, "daily_stop_loss", -100.0)
        self.max_daily_loss: float = self._normalize_loss_to_usd(raw_daily_sl, equity_usd)

        # ----- Daily drawdown cap -----
        # Accept USD (e.g., 300.0) or ratio (e.g., 0.05 for 5%).
        raw_dd = getattr(config.risk, "max_daily_drawdown", 0.0)
        self.max_daily_drawdown: float = self._normalize_drawdown_to_usd(raw_dd, equity_usd)

        # Historical/overall max drawdown ratio (optional; not directly used by daily checks)
        self.max_drawdown_ratio: float = float(getattr(config.risk, "global_max_drawdown", 0.0))

        # Daily target (ratio, optional informational)
        self.daily_target_ratio: float = float(getattr(config.risk, "daily_target", 0.0))

        # ----- Exposure & concentration -----
        self.max_total_exposure: float = float(
            getattr(config.risk, "max_total_exposure_usd", 10_000.0)
        )
        self.max_concurrent_positions: int = int(
            getattr(config.risk, "max_concurrent_positions", 10)
        )
        self.max_concentration_ratio: float = float(
            getattr(config.risk, "max_concentration_ratio", 1.0)
        )

        # ----- Frequency limits -----
        self.max_trades_per_minute: int = int(getattr(config.scalp, "max_trades_per_minute", 20))
        self.max_trades_per_hour: int = int(getattr(config.scalp, "max_trades_per_hour", 200))
        self.max_trades_per_day: int = int(getattr(config.scalp, "daily_trade_limit", 1000))

        # ----- Market condition limits / circuit breakers -----
        self.max_spread_bps: float = float(getattr(config.scalp, "max_spread_bps", 50.0))
        # `risk.circuit_breakers.latency_ms_max` may be a plain attribute or dict-like
        cb = getattr(config.risk, "circuit_breakers", None)
        self.max_latency_ms: float = 500.0
        if cb is not None:
            self.max_latency_ms = float(
                getattr(
                    cb,
                    "latency_ms_max",
                    getattr(cb, "get", lambda *_: 500)("latency_ms_max", 500),
                )
            )

        # ----- Position sizing modifiers -----
        # External modules (sizing) can read this for a global dampener/booster
        trading = getattr(config, "trading", None)
        pos_sizing = getattr(trading, "position_sizing", None) if trading else None
        self.volatility_multiplier: float = float(
            getattr(pos_sizing, "volatility_multiplier", 0.75)
        )

    # --- helpers ---

    @staticmethod
    def _normalize_loss_to_usd(raw: float, equity_usd: float) -> float:
        """
        Normalize daily stop loss to USD (negative).
        If |raw| < 1.0 → interpret as ratio (e.g., -0.02 = -2% of equity).
        Otherwise assume USD.
        """
        try:
            val = float(raw)
        except Exception:
            val = -100.0
        if -1.0 < val < 1.0:
            return -abs(val) * equity_usd  # convert %-loss to negative USD
        # Ensure it's negative (loss threshold)
        return -abs(val)

    @staticmethod
    def _normalize_drawdown_to_usd(raw: float, equity_usd: float) -> float:
        """
        Normalize daily drawdown to USD (positive cap).
        If raw in (0,1) → interpret as ratio (e.g., 0.05 = 5% of equity).
        Otherwise assume USD (absolute, positive).
        """
        try:
            val = float(raw)
        except Exception:
            val = 0.0
        if 0.0 < val < 1.0:
            return abs(val) * equity_usd
        return abs(val)

    # --- convenience predicates used by guards/tests ---

    def get_adjusted_position_size(
        self,
        base_size: float,
        volatility_factor: float = 1.0,
        confidence: float = 1.0,
    ) -> float:
        """
        Calculate risk-adjusted position size (units or USD depending on caller's base_size
        semantics). This applies a global volatility multiplier and a simple banded adjustment
        on recent volatility.
        """
        adjusted_size = (
            float(base_size) * float(self.volatility_multiplier) * max(0.0, min(1.0, confidence))
        )

        # Volatility banding (conservative scaling)
        if volatility_factor > 1.5:  # High vol → shrink
            adjusted_size *= 0.7
        elif volatility_factor < 0.8:  # Low vol → allow a bit more
            adjusted_size *= 1.2

        return adjusted_size

    def is_within_daily_limits(self, current_pnl_usd: float) -> bool:
        """
        True if daily P&L (USD) is above the max_daily_loss threshold (negative).
        Example: max_daily_loss = -200.0, current_pnl_usd = -150.0 → True (still within)
        """
        return float(current_pnl_usd) > float(self.max_daily_loss)

    def is_within_exposure_limits(self, current_exposure_usd: float) -> bool:
        """True if current absolute exposure (USD) is ≤ cap."""
        return float(current_exposure_usd) <= float(self.max_total_exposure)


# ---------------------------- Dynamic Risk Adjuster ----------------------------


class DynamicRiskAdjuster:
    """
    Dynamically adjust select risk limits based on recent performance.
    Inputs/outputs are in USD for loss metrics to align with RiskManager.
    """

    def __init__(self, config: KrakenScalpingConfig):
        self.config = config
        self.base_limits = RiskLimits(config)

        # Performance tracking thresholds
        self.win_rate_threshold: float = 0.60
        self.min_trades_for_adjustment: int = 20

        # Adjustment multipliers
        self.good_performance_multiplier: float = 1.20  # +20%
        self.poor_performance_multiplier: float = 0.80  # -20%

    def calculate_adjusted_limits(self, trade_history: list[Dict]) -> Dict[str, float]:
        """
        Calculate dynamically adjusted risk limits based on recent performance.
        Returns a small dict of knobs you can apply to your live config/strategy.
        """
        if len(trade_history) < self.min_trades_for_adjustment:
            return self._get_base_limits_dict()

        recent_trades = trade_history[-self.min_trades_for_adjustment :]
        wins = sum(1 for t in recent_trades if float(t.get("pnl", 0.0)) > 0.0)
        win_rate = wins / len(recent_trades)
        avg_profit = sum(float(t.get("pnl", 0.0)) for t in recent_trades) / len(recent_trades)

        if win_rate >= self.win_rate_threshold and avg_profit > 0.0:
            factor = self.good_performance_multiplier
        elif win_rate < 0.40 or avg_profit < -0.01:  # <40% WR or avg loss worse than -$0.01
            factor = self.poor_performance_multiplier
        else:
            factor = 1.0

        adjusted = {
            # Max per-position USD proxy (10% of max exposure scaled by factor)
            "max_position_size_usd": self.base_limits.max_total_exposure * 0.10 * factor,
            # Daily stop loss (more negative with factor < 1 increases protection;
            # factor > 1 relaxes)
            "max_daily_loss_usd": self.base_limits.max_daily_loss * factor,
            # Trades per hour ceiling
            "max_trades_per_hour": int(self.base_limits.max_trades_per_hour * factor),
            "adjustment_factor": factor,
            "win_rate": win_rate,
            "avg_profit": avg_profit,
        }
        return adjusted

    def _get_base_limits_dict(self) -> Dict[str, float]:
        """Return base limits as a dictionary for warm-up/insufficient data cases."""
        return {
            "max_position_size_usd": self.base_limits.max_total_exposure * 0.10,
            "max_daily_loss_usd": self.base_limits.max_daily_loss,
            "max_trades_per_hour": self.base_limits.max_trades_per_hour,
            "adjustment_factor": 1.0,
            "win_rate": 0.0,
            "avg_profit": 0.0,
        }


__all__ = ["PositionLimits", "RiskLimits", "DynamicRiskAdjuster"]
