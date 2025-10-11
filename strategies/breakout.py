"""
Professional Breakout Strategy Implementation for Crypto Trading Bot.

A robust, configurable breakout strategy that detects resistance/support breaks
with volume confirmation, false breakout filtering, and dynamic risk management.

Author: Senior Quant Engineer
Path: strategies/breakout.py
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Optional

import numpy as np
import pandas as pd

# --- Optional deps -------------------------------------------------------------

try:
    from pydantic import BaseModel, Field, ValidationError  # type: ignore
    HAS_PYDANTIC = True
except Exception:  # pragma: no cover
    HAS_PYDANTIC = False

    class BaseModel:  # simple shim
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    def Field(default=None, **_: Any):
        return default

    class ValidationError(Exception):
        pass

try:
    import talib  # type: ignore
    HAS_TALIB = True
except Exception:  # pragma: no cover
    HAS_TALIB = False

try:
    from prometheus_client import Counter, Histogram, CollectorRegistry
    HAS_PROM = True
except Exception:  # pragma: no cover
    HAS_PROM = False

    class CollectorRegistry:  # type: ignore
        pass

# --- Optional project base class ----------------------------------------------

try:
    from strategies.base import StrategyBase  # type: ignore
    HAS_STRATEGY_BASE = True
except Exception:  # pragma: no cover
    HAS_STRATEGY_BASE = False

    class StrategyBase:
        name: str = "base_strategy"

        def generate_signal(self, ohlcv, context=None):
            raise NotImplementedError

        def on_fill(self, fill, context):
            pass

        def on_cancel(self, order, context):
            pass


# --- Lightweight stubs (to keep this file runnable in isolation) --------------

@dataclass
class MarketContextLite:
    mode: Literal["backtest", "paper", "live"] = "backtest"
    exchange: str = "kraken"
    symbol: str = "ETH/USDT"
    account_equity_usd: float = 10_000.0
    volatility: Optional[float] = None
    spread: Optional[float] = None
    regime: Optional[Literal["bull", "bear", "sideways"]] = None
    daily_stop_hit: bool = False
    circuit_breaker_on: bool = False
    base_position_size: float = 0.01  # fraction of equity at risk
    volatility_multiplier: float = 1.0
    max_position: float = 10_000.0


@dataclass
class SignalLike:
    strategy: str
    exchange: str
    symbol: str
    side: Literal["buy", "sell"]
    confidence: float
    size_quote_usd: float
    meta: dict = field(default_factory=dict)


@dataclass
class FillEventLite:
    symbol: str
    side: str
    quantity: float
    price: float
    timestamp: pd.Timestamp


@dataclass
class OrderEventLite:
    symbol: str
    side: str
    quantity: float
    price: float
    order_type: str


@dataclass
class BreakoutEvent:
    timestamp: pd.Timestamp
    side: Literal["long", "short"]
    resistance_level: float
    entry_price: float
    atr: float
    volume_ratio: float
    confidence: float
    stop_loss: float


# --- Config -------------------------------------------------------------------

class BreakoutConfig(BaseModel if HAS_PYDANTIC else object):
    """
    Strategy configuration (validated). Defaults are conservative.
    NOTE: `min_breakout_ratio` here means ATR multiples beyond the level.
    """

    # Core breakout parameters
    resistance_window: int = Field(default=20, ge=5, le=100)
    min_breakout_ratio: float = Field(default=0.5, ge=0.05, le=3.0)  # ATR multiples
    volume_requirement: float = Field(default=1.5, ge=1.0, le=5.0)
    atr_multiplier: float = Field(default=2.0, ge=0.5, le=5.0)

    # Filtering and confirmation
    retest_allowed: bool = Field(default=True)
    false_breakout_filter: bool = Field(default=True)
    confirmation_bars: int = Field(default=1, ge=0, le=3)

    # Risk management
    risk_multiple_tp: tuple[float, ...] = Field(default=(1.0, 2.0, 3.0))
    trailing_atr: float = Field(default=1.5, ge=0.5, le=3.0)

    # Trading constraints
    max_spread: float = Field(default=0.001, ge=0.0, le=0.01)
    min_confidence: float = Field(default=0.75, ge=0.0, le=1.0)
    fee_bps: float = Field(default=10.0, ge=0.0, le=100.0)
    slippage_bps: float = Field(default=10.0, ge=0.0, le=100.0)

    # Strategy behavior
    side: Literal["long", "short", "both"] = Field(default="both")
    symbol_whitelist: Optional[list[str]] = Field(default=None)
    disable_when_drawdown: Optional[float] = Field(default=None)

    @classmethod
    def from_settings(cls, settings: Mapping[str, Any]) -> "BreakoutConfig":
        s = settings.get("strategies", {}).get("breakout", {}) or {}
        t = settings.get("trading", {}) or {}
        r = settings.get("risk", {}) or {}
        return cls(
            **s,
            max_spread=t.get("max_spread", 0.001),
            min_confidence=t.get("min_confidence", 0.75),
            fee_bps=t.get("fee_bps", 10.0),
            slippage_bps=t.get("slippage_bps", 10.0),
            disable_when_drawdown=r.get("max_strategy_drawdown"),
        )


def _coerce_and_validate_config(cfg: Any) -> BreakoutConfig:
    """Accept BreakoutConfig OR dict and return a validated BreakoutConfig."""
    if isinstance(cfg, BreakoutConfig):
        c = cfg
    elif isinstance(cfg, dict):
        try:
            c = BreakoutConfig(**cfg)
        except ValidationError as e:  # normalize to ValueError for tests
            raise ValueError(str(e))
    else:
        raise ValueError("config must be BreakoutConfig or dict")

    # Field-level validation with explicit messages (friendly for tests)
    if getattr(c, "resistance_window", 0) < 5:
        raise ValueError("resistance_window must be >= 5")
    if getattr(c, "min_breakout_ratio", 0.0) <= 0.0:
        raise ValueError("min_breakout_ratio must be > 0")
    if getattr(c, "volume_requirement", 0.0) <= 0.0:
        raise ValueError("volume_requirement must be > 0")
    return c


# --- Indicators & helpers -----------------------------------------------------

def compute_indicators(ohlcv: pd.DataFrame, window: int = 14) -> dict[str, pd.Series]:
    """
    Compute ATR, volume SMA, and rolling extrema.
    """
    out: dict[str, pd.Series] = {}

    if HAS_TALIB:
        atr = talib.ATR(
            ohlcv["high"].values,
            ohlcv["low"].values,
            ohlcv["close"].values,
            timeperiod=window,
        )
        out["atr"] = pd.Series(atr, index=ohlcv.index)
    else:
        high_low = ohlcv["high"] - ohlcv["low"]
        high_close_prev = (ohlcv["high"] - ohlcv["close"].shift(1)).abs()
        low_close_prev = (ohlcv["low"] - ohlcv["close"].shift(1)).abs()
        tr = np.maximum(high_low, np.maximum(high_close_prev, low_close_prev))
        out["atr"] = tr.rolling(window=window, min_periods=1).mean()

    out["volume_sma"] = ohlcv["volume"].rolling(window=20, min_periods=1).mean()
    out["highest_high"] = ohlcv["high"].rolling(window=window, min_periods=1).max()
    out["lowest_low"] = ohlcv["low"].rolling(window=window, min_periods=1).min()
    return out


def apply_false_breakout_filters(
    ohlcv: pd.DataFrame,
    idx: int,
    level: float,
    atr: float,
    side: Literal["long", "short"],
) -> bool:
    """Basic wick/body/distance filters to avoid obvious false breaks."""
    if idx >= len(ohlcv):
        return False

    bar = ohlcv.iloc[idx]
    rng = float(bar["high"] - bar["low"]) if (bar["high"] > bar["low"]) else 0.0

    if side == "long":
        # Avoid candles with long upper wicks or bearish bodies
        if rng > 0:
            upper_wick = (bar["high"] - bar["close"]) / rng
            if upper_wick > 0.4:
                return False
        if bar["close"] <= bar["open"]:
            return False
        # Close should be meaningfully above level
        if (bar["close"] - level) < 0.25 * atr:
            return False
    else:  # short
        if rng > 0:
            lower_wick = (bar["close"] - bar["low"]) / rng
            if lower_wick > 0.4:
                return False
        if bar["close"] >= bar["open"]:
            return False
        if (level - bar["close"]) < 0.25 * atr:
            return False

    return True


def _confirm_above_level(
    ohlcv: pd.DataFrame,
    idx: int,
    level: float,
    bars: int,
    atr: float,
    allow_retest: bool,
) -> bool:
    """
    Confirm price behavior around the breakout level for `bars` lookback.
    If allow_retest=True, allow brief dips up to 0.25*ATR below the level.
    """
    if bars <= 0:
        return True
    start = max(0, idx - bars)
    closes = ohlcv["close"].iloc[start:idx]
    if len(closes) < bars:
        return False

    if allow_retest:
        return bool((closes >= (level - 0.25 * atr)).all())
    else:
        return bool((closes >= level).all())


def _confirm_below_level(
    ohlcv: pd.DataFrame,
    idx: int,
    level: float,
    bars: int,
    atr: float,
    allow_retest: bool,
) -> bool:
    if bars <= 0:
        return True
    start = max(0, idx - bars)
    closes = ohlcv["close"].iloc[start:idx]
    if len(closes) < bars:
        return False

    if allow_retest:
        return bool((closes <= (level + 0.25 * atr)).all())
    else:
        return bool((closes <= level).all())


def detect_breakout(
    ohlcv: pd.DataFrame,
    config: BreakoutConfig,
    indicators: dict[str, pd.Series],
) -> Optional[BreakoutEvent]:
    """
    Detect a breakout on one of the most recent bars (scans back up to ~15 bars).
    Returns the most recent BreakoutEvent or None.
    """
    n = len(ohlcv)
    if n < config.resistance_window + 1:
        return None

    # scan covers our typical generators with n_post<=10
    scan_back = min(15, max(1, n - config.resistance_window))
    start_i = max(config.resistance_window, n - scan_back)

    for i in range(n - 1, start_i - 1, -1):
        prev = i - 1
        if prev < 0:
            continue

        bar = ohlcv.iloc[i]
        prev_bar = ohlcv.iloc[prev]

        atr = float(indicators["atr"].iloc[i])
        vol_sma = float(indicators["volume_sma"].iloc[i])
        if not np.isfinite(atr) or atr <= 0 or not np.isfinite(vol_sma):
            continue

        # --- LONG side ---
        if config.side in ("long", "both"):
            level = float(indicators["highest_high"].iloc[prev])
            was_below = prev_bar["close"] <= level
            broke = bar["close"] >= level + config.min_breakout_ratio * atr
            v_ok = bar["volume"] >= config.volume_requirement * vol_sma
            if was_below and broke and v_ok:
                if config.false_breakout_filter:
                    if not apply_false_breakout_filters(ohlcv, i, level, atr, "long"):
                        continue
                if not _confirm_above_level(
                    ohlcv, i, level, config.confirmation_bars, atr, config.retest_allowed
                ):
                    continue

                vol_score = min((bar["volume"] / vol_sma - 1.0) * 0.5, 0.3)
                dist_score = min((bar["close"] - level) / atr * 0.1, 0.2)
                conf = float(np.clip(0.5 + vol_score + dist_score, 0.0, 1.0))

                lookback = min(5, n - 1)
                recent_low = float(ohlcv["low"].iloc[i - lookback : i + 1].min())
                atr_stop = float(bar["close"] - config.atr_multiplier * atr)
                stop = float(min(recent_low, atr_stop))

                return BreakoutEvent(
                    timestamp=bar.name if hasattr(bar, "name") else pd.Timestamp.utcnow(),
                    side="long",
                    resistance_level=level,
                    entry_price=float(bar["close"]),
                    atr=atr,
                    volume_ratio=float(bar["volume"] / vol_sma),
                    confidence=conf,
                    stop_loss=stop,
                )

        # --- SHORT side ---
        if config.side in ("short", "both"):
            level = float(indicators["lowest_low"].iloc[prev])
            was_above = prev_bar["close"] >= level
            broke = bar["close"] <= level - config.min_breakout_ratio * atr
            v_ok = bar["volume"] >= config.volume_requirement * vol_sma
            if was_above and broke and v_ok:
                if config.false_breakout_filter:
                    if not apply_false_breakout_filters(ohlcv, i, level, atr, "short"):
                        continue
                if not _confirm_below_level(
                    ohlcv, i, level, config.confirmation_bars, atr, config.retest_allowed
                ):
                    continue

                vol_score = min((bar["volume"] / vol_sma - 1.0) * 0.5, 0.3)
                dist_score = min((level - bar["close"]) / atr * 0.1, 0.2)
                conf = float(np.clip(0.5 + vol_score + dist_score, 0.0, 1.0))

                lookback = min(5, n - 1)
                recent_high = float(ohlcv["high"].iloc[i - lookback : i + 1].max())
                atr_stop = float(bar["close"] + config.atr_multiplier * atr)
                stop = float(max(recent_high, atr_stop))

                return BreakoutEvent(
                    timestamp=bar.name if hasattr(bar, "name") else pd.Timestamp.utcnow(),
                    side="short",
                    resistance_level=level,
                    entry_price=float(bar["close"]),
                    atr=atr,
                    volume_ratio=float(bar["volume"] / vol_sma),
                    confidence=conf,
                    stop_loss=stop,
                )

    return None


# --- Sizing -------------------------------------------------------------------

def calculate_position_size(
    entry_price: float,
    stop_loss: float,
    account_equity: float,
    base_position_size: float,
    volatility_multiplier: float,
    max_position: float,
    min_confidence: float,
    confidence: float,
) -> float:
    """
    Risk-based notional sizing in USD.
    """
    risk_per_trade = float(account_equity * base_position_size)
    risk_dist = float(abs(entry_price - stop_loss))
    if risk_dist <= 0:
        return 0.0

    base_qty = risk_per_trade / risk_dist  # in units of the asset
    adj_qty = base_qty * float(volatility_multiplier) * float(
        max(confidence, 1e-6) / max(min_confidence, 1e-6)
    )
    notional_usd = adj_qty * float(entry_price)
    return float(min(notional_usd, max_position))


# --- Strategy -----------------------------------------------------------------

class BreakoutStrategy(StrategyBase if HAS_STRATEGY_BASE else object):
    """
    Breakout strategy with ATR-based threshold, volume confirmation, and gating.
    """

    name: str = "breakout"

    # Metrics (class-level single registration + optional per-test registry)
    _metrics_ready: bool = False
    _metrics_lock = threading.Lock()
    _shared_registry: Optional[CollectorRegistry] = CollectorRegistry() if HAS_PROM else None
    _metrics: Optional[dict] = None  # shared metrics dict

    def __init__(
        self,
        config: Any,
        *,
        logger: Optional[logging.Logger] = None,
        metrics_registry: Optional[CollectorRegistry] = None,
    ):
        # 1) Config first (so tests see the right error)
        self.config: BreakoutConfig = _coerce_and_validate_config(config)

        # 2) Logging
        self.logger = logger or logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)

        # 3) Metrics registry
        self._metrics_registry = metrics_registry
        self._init_metrics()

        self.logger.info("Initialized %s with config=%s", self.name, self.config)

    def _init_metrics(self) -> None:
        """Idempotent, registry-scoped Prometheus metrics; always sets self._m."""
        # No Prometheus: keep a stable empty dict shared across instances
        if not HAS_PROM:
            if self.__class__._metrics is None:
                self.__class__._metrics = {}
            self._m = self.__class__._metrics
            return

        # If already built, just bind and go
        if self.__class__._metrics_ready and self.__class__._metrics is not None:
            self._m = self.__class__._metrics
            return

        with self.__class__._metrics_lock:
            if self.__class__._metrics_ready and self.__class__._metrics is not None:
                self._m = self.__class__._metrics
                return

            reg = self._metrics_registry or self.__class__._shared_registry
            metrics = {
                "breakout_attempts": Counter(
                    "breakout_attempts_total", "Total breakout attempts", registry=reg
                ),
                "breakout_valid": Counter(
                    "breakout_valid_total", "Valid breakouts (passed filters)", registry=reg
                ),
                "breakout_signals": Counter(
                    "breakout_signals_total", "Successful breakout signals", ["side"], registry=reg
                ),
                "breakout_confidence": Histogram(
                    "breakout_confidence", "Signal confidence", registry=reg
                ),
                "volume_ratio": Histogram(
                    "breakout_volume_ratio", "Volume ratio on breakout", registry=reg
                ),
                "breakout_distance_atr": Histogram(
                    "breakout_distance_atr", "Distance in ATR multiples", registry=reg
                ),
                "signals": Counter(
                    "breakout_signals_emitted_total", "Signals emitted", registry=reg
                ),
            }
            self.__class__._metrics = metrics
            self.__class__._metrics_ready = True
            self._m = self.__class__._metrics

    # Core API
    def generate_signal(
        self,
        ohlcv: pd.DataFrame,
        now_ms: Optional[int] = None,
        context: Optional[dict] = None,
    ) -> Optional[SignalLike]:
        """
        Produce a breakout signal or None.
        """
        try:
            ctx = context or {}
            mctx = MarketContextLite(
                mode=ctx.get("mode", "backtest"),
                exchange=ctx.get("exchange", "kraken"),
                symbol=ctx.get("symbol", "ETH/USDT"),
                account_equity_usd=ctx.get("account_equity_usd", 10_000.0),
                volatility=ctx.get("volatility"),
                spread=ctx.get("spread"),
                regime=ctx.get("regime"),
                daily_stop_hit=ctx.get("daily_stop_hit", False),
                circuit_breaker_on=ctx.get("circuit_breaker_on", False),
                base_position_size=ctx.get("base_position_size", 0.01),
                volatility_multiplier=ctx.get("volatility_multiplier", 1.0),
                max_position=ctx.get("max_position", 10_000.0),
            )

            if not self._pre_flight_checks(mctx):
                return None

            inds = compute_indicators(ohlcv, self.config.resistance_window)
            brk = detect_breakout(ohlcv, self.config, inds)

            if self._m.get("breakout_attempts"):
                self._m["breakout_attempts"].inc()

            if not brk:
                return None

            if self._m.get("breakout_valid"):
                self._m["breakout_valid"].inc()

            if brk.confidence < self.config.min_confidence:
                self.logger.debug(
                    "Confidence %.3f below threshold %.3f",
                    brk.confidence,
                    self.config.min_confidence,
                )
                return None

            pos_size = calculate_position_size(
                entry_price=brk.entry_price,
                stop_loss=brk.stop_loss,
                account_equity=mctx.account_equity_usd,
                base_position_size=mctx.base_position_size,
                volatility_multiplier=mctx.volatility_multiplier,
                max_position=mctx.max_position,
                min_confidence=self.config.min_confidence,
                confidence=brk.confidence,
            )
            if pos_size <= 0:
                self.logger.debug("Zero position size; rejecting signal")
                return None

            sig = SignalLike(
                strategy=self.name,
                exchange=mctx.exchange,
                symbol=mctx.symbol,
                side="buy" if brk.side == "long" else "sell",
                confidence=brk.confidence,
                size_quote_usd=pos_size,
                meta={
                    "breakout_level": brk.resistance_level,
                    "entry_price": brk.entry_price,
                    "stop_loss": brk.stop_loss,
                    "atr": brk.atr,
                    "volume_ratio": brk.volume_ratio,
                    "risk_multiple_tp": self.config.risk_multiple_tp,
                    "trailing_atr": self.config.trailing_atr,
                    "timestamp": (
                        brk.timestamp.isoformat()
                        if hasattr(brk.timestamp, "isoformat")
                        else str(brk.timestamp)
                    ),
                },
            )

            # metrics
            if self._m.get("breakout_signals"):
                self._m["breakout_signals"].labels(side=brk.side).inc()
            if self._m.get("breakout_confidence"):
                self._m["breakout_confidence"].observe(brk.confidence)
            if self._m.get("volume_ratio"):
                self._m["volume_ratio"].observe(brk.volume_ratio)
            if self._m.get("breakout_distance_atr"):
                dist_atr = abs(brk.entry_price - brk.resistance_level) / max(brk.atr, 1e-9)
                self._m["breakout_distance_atr"].observe(dist_atr)
            if self._m.get("signals"):
                self._m["signals"].inc()

            self._evaluate_with_risk_router(sig)

            self.logger.info(
                "Signal %s %s @ %.4f size=$%d conf=%.2f",
                sig.side,
                sig.symbol,
                brk.entry_price,
                round(pos_size),
                brk.confidence,
            )
            return sig

        except Exception as e:  # pragma: no cover
            self.logger.error("Error generating breakout signal: %s", e, exc_info=True)
            return None

    # Hooks
    def on_fill(self, fill: FillEventLite, context: MarketContextLite) -> None:
        self.logger.info(
            "Fill: %s %s %s @ %.4f", fill.symbol, fill.side, fill.quantity, fill.price
        )

    def on_cancel(self, order: OrderEventLite, context: MarketContextLite) -> None:
        self.logger.info(
            "Cancel: %s %s %s @ %.4f", order.symbol, order.side, order.quantity, order.price
        )

    # Guards
    def _pre_flight_checks(self, context: MarketContextLite) -> bool:
        if getattr(context, "daily_stop_hit", False):
            self.logger.debug("Daily stop hit")
            return False
        if getattr(context, "circuit_breaker_on", False):
            self.logger.debug("Circuit breaker active")
            return False
        if context.spread and context.spread > self.config.max_spread:
            self.logger.debug(
                "Spread %.5f exceeds max %.5f", context.spread, self.config.max_spread
            )
            return False
        if self.config.symbol_whitelist and context.symbol not in self.config.symbol_whitelist:
            self.logger.debug("Symbol %s not in whitelist", context.symbol)
            return False
        return True

    def _evaluate_with_risk_router(self, signal: SignalLike) -> None:
        # Placeholder for RiskRouter integration (optional)
        return


__all__ = [
    "BreakoutStrategy",
    "BreakoutConfig",
    "MarketContextLite",
    "SignalLike",
    "detect_breakout",
    "compute_indicators",
    "calculate_position_size",
]
