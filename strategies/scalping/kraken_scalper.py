"""
strategies/scalping/kraken_scalper.py

Kraken-specific scalping strategy implementation, integrated with the
project's config system and the OrderFlowAnalyzer (multi-timeframe order flow).
- Reads thresholds from YAML/.env via OrderFlowConfig
- Uses dynamic timeframes (e.g., ["15s","1m","3m","5m"])
- Maker-first with optional post-only preference
- Rate-limited per pair with cooldowns
- Emits compact execution-ready signals

Dependencies within project:
    - strategies.order_flow: OrderFlowAnalyzer, OrderFlowConfig, filter_scalping_opportunities
    - data.market_store.TickRecord (or equivalent tick type with timestamp/price/volume/side)
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional

# Local imports: adjust if your package layout differs
try:
    from agents.scalper.analysis.order_flow import (
        OrderFlowAnalyzer,
        OrderFlowConfig,
        filter_scalping_opportunities,
    )
except Exception as _e:
    # Allow importing directly when running this file in isolation
    from strategies.order_flow import (  # type: ignore
        OrderFlowAnalyzer,
        OrderFlowConfig,
        filter_scalping_opportunities,
    )

# If you have a canonical TickRecord, import it; else define a light fallback
try:
    from agents.scalper.data.market_store import TickRecord
except Exception:
    @dataclass
    class TickRecord:  # minimal fallback for testing
        timestamp: float
        price: float
        volume: float
        side: str  # "buy" | "sell"


# ---------- Helpers ----------

def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default

def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default

def _now_ts() -> float:
    return time.time()


# ---------- Strategy ----------

class KrakenScalpingStrategy:
    """
    Kraken-optimized scalping strategy backed by OrderFlowAnalyzer.

    Features:
    - Dynamic timeframes from config (no hardcoding)
    - Order-flow imbalance + momentum + aggression
    - Maker-first entries (post-only optional)
    - Per-pair rate limiting & cooldowns
    - Configurable targets/stops in basis points (bps)
    """

    def __init__(
        self,
        pairs: List[str],
        *,
        target_bps: Optional[int] = None,
        stop_loss_bps: Optional[int] = None,
        timeframe: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        system_config: Optional[Any] = None,  # pass your validated ScalpConfig or dict here
    ):
        """
        Args:
            pairs: List of trading pairs, e.g. ["BTC/USD", "ETH/USD"]
            target_bps: Desired take-profit distance in bps (fallback to env)
            stop_loss_bps: Stop distance in bps (fallback to env)
            timeframe: Optional hint for UI/status only (analyzer uses dynamic TFs)
            config: Legacy/dict config overrides (optional)
            system_config: Your validated config object or dict (preferred)
        """
        self.logger = logging.getLogger(f"{__name__}.KrakenScalpingStrategy")

        self.pairs = list(pairs)
        self._raw_cfg = config or {}

        # Build a config wrapper that understands YAML/.env (with overrides)
        self.of_cfg = (
            OrderFlowConfig.from_config(system_config or self._raw_cfg)
            if not isinstance(system_config, OrderFlowConfig)
            else system_config
        )

        # Targets/stops – prefer explicit args, then env, then sane defaults
        self.target_bps = int(
            target_bps
            if target_bps is not None
            else _env_int("SCALP_TARGET_BPS", 10)
        )
        self.stop_loss_bps = int(
            stop_loss_bps
            if stop_loss_bps is not None
            else _env_int("SCALP_STOP_LOSS_BPS", 5)
        )
        self.timeframe = timeframe or os.getenv("SCALP_TIMEFRAME", "15s")

        # Maker preferences / order defaults
        self.preferred_order_type = os.getenv("SCALP_PREFERRED_ORDER_TYPE", "limit").lower()
        self.post_only = _env_bool("SCALP_POST_ONLY", True)
        self.hidden_orders = _env_bool("SCALP_HIDDEN_ORDERS", False)
        self.max_slippage_bps = _env_int("SCALP_MAX_SLIPPAGE_BPS", 4)

        # Rate limiting & safety
        self.max_trades_per_min = _env_int("SCALP_MAX_TRADES_PER_MINUTE", 4)
        self.cooldown_after_loss_sec = _env_int("SCALP_COOLDOWN_AFTER_LOSS_SECONDS", 90)
        self.daily_trade_limit = _env_int("SCALP_DAILY_TRADE_LIMIT", 150)
        self.max_hold_seconds = _env_int("SCALP_MAX_HOLD_SECONDS", 120)

        # Microstructure bounds
        self.max_spread_bps = _env_float("SCALP_MAX_SPREAD_BPS", 3.0)
        self.min_volume_quote = _env_float("SCALP_MIN_LIQUIDITY_USD", 1_000_000.0)

        # Internal state
        self._analyzers: Dict[str, OrderFlowAnalyzer] = {
            sym: OrderFlowAnalyzer(self.of_cfg, symbol=sym) for sym in self.pairs
        }
        self._last_signal_ts: Dict[str, float] = {}
        self._last_loss_ts: Dict[str, float] = {}
        self._trade_counts_min_window: Dict[str, List[float]] = {sym: [] for sym in self.pairs}
        self._daily_trade_count: int = 0

        # Regime (optional AI inputs)
        self.current_regime: str = "unknown"
        self.regime_confidence: float = 0.5
        self.scalping_suitability: float = 0.5

        # Stats
        self.signals_generated = 0
        self.signals_executed = 0

        self.logger.info(
            "Scalper initialized | pairs=%s | tf=%s | target=%dbps | stop=%dbps | post_only=%s",
            self.pairs, self.timeframe, self.target_bps, self.stop_loss_bps, self.post_only,
        )

    # -------- Public API --------

    async def initialize(self) -> None:
        """One-time init hook for parity with your agent lifecycle."""
        pass

    async def update_regime(
        self, regime: str, confidence: float, scalping_suitability: float
    ) -> None:
        """Optional: accept regime signals from your AI engine."""
        self.current_regime = regime
        self.regime_confidence = confidence
        self.scalping_suitability = scalping_suitability

        # Gentle auto-tuning
        if regime == "volatile" and scalping_suitability < 0.4:
            self.target_bps = max(self.target_bps, int(self.target_bps * 1.2))
            self.stop_loss_bps = max(self.stop_loss_bps, int(self.stop_loss_bps * 1.2))
        elif regime == "calm" and scalping_suitability > 0.8:
            self.target_bps = max(6, int(self.target_bps * 0.9))
            self.stop_loss_bps = max(3, int(self.stop_loss_bps * 0.9))

    def on_tick(self, pair: str, tick: TickRecord) -> None:
        """
        Feed a new trade tick to the analyzer. Call from your data consumer
        (e.g., Kraken WS callback or Redis stream reader).
        """
        if pair not in self._analyzers:
            # Lazy-add analyzer if a new symbol appears
            self._analyzers[pair] = OrderFlowAnalyzer(self.of_cfg, symbol=pair)
            self._trade_counts_min_window[pair] = []
        self._analyzers[pair].add_tick(tick)

    async def generate_signal(
        self,
        pair: str,
        *,
        best_bid: Optional[float],
        best_ask: Optional[float],
        last_price: Optional[float] = None,
        quote_liquidity_usd: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Generate a scalping signal, combining order-flow metrics and top-of-book data.

        Args:
            pair: e.g. "BTC/USD"
            best_bid: top-of-book best bid (float)
            best_ask: top-of-book best ask (float)
            last_price: fallback for current_price if needed
            quote_liquidity_usd: quick liquidity sanity-check (e.g. from recent volume*price)

        Returns:
            Executable signal dict or None.
        """
        if pair not in self.pairs:
            return None

        # Per-pair basic throttles
        if not self._should_generate(pair):
            return None

        # Sanity checks on book + spread
        if not best_bid or not best_ask or best_bid <= 0 or best_ask <= 0:
            return None
        mid = (best_bid + best_ask) / 2.0
        spread_bps = ((best_ask - best_bid) / best_bid) * 10_000.0
        if spread_bps > self.max_spread_bps:
            return None
        if quote_liquidity_usd is not None and quote_liquidity_usd < self.min_volume_quote:
            return None

        # Analyze order flow for this pair
        analyzer = self._analyzers.get(pair)
        if analyzer is None:
            analyzer = OrderFlowAnalyzer(self.of_cfg, symbol=pair)
            self._analyzers[pair] = analyzer

        current_price = float(last_price or mid)
        metrics = analyzer.analyze(current_price)

        # Gate with config-aware filters
        ok, reason = filter_scalping_opportunities(metrics, self.of_cfg, symbol=pair)
        if not ok:
            self._debug(pair, f"filter_reject: {reason}")
            return None

        # Direction from order-flow signal
        side = metrics.entry_signal  # "buy" | "sell"
        if side not in ("buy", "sell"):
            return None

        # Maker-first entry price (try to rest at the favorable side of the spread)
        if side == "buy":
            entry_price = Decimal(str(best_bid))  # aim to make at bid
            tp = entry_price * (Decimal(1) + Decimal(self.target_bps) / Decimal(10_000))
            sl = entry_price * (Decimal(1) - Decimal(self.stop_loss_bps) / Decimal(10_000))
        else:
            entry_price = Decimal(str(best_ask))  # aim to make at ask
            tp = entry_price * (Decimal(1) - Decimal(self.target_bps) / Decimal(10_000))
            sl = entry_price * (Decimal(1) + Decimal(self.stop_loss_bps) / Decimal(10_000))

        # Position sizing: start small, scale with strength/confidence
        base_usd = Decimal("200")  # base clip
        size_mult = Decimal(str(
            max(0.1, min(2.0, metrics.signal_strength * (0.5 + metrics.confidence)))
        ))
        size_usd = base_usd * size_mult

        # Build signal payload
        sig = self._build_signal(
            pair=pair,
            side=side,
            entry_price=entry_price,
            take_profit=tp,
            stop_loss=sl,
            strength=metrics.signal_strength,
            confidence=metrics.confidence,
            spread_bps=spread_bps,
            mid_price=Decimal(str(mid)),
            vwap=Decimal(str(metrics.volume_weighted_price or 0.0)),
            aggression=float(metrics.aggression_ratio),
            volatility=float(metrics.volatility),
            trade_intensity=float(metrics.trade_intensity),
            order_type=self.preferred_order_type,
            post_only=self.post_only,
            hidden=self.hidden_orders,
            max_slippage_bps=self.max_slippage_bps,
            timeframe_hint=self.timeframe,
        )

        # Update throttles and stats
        self._mark_signal(pair)
        self.signals_generated += 1

        self.logger.info(
            "scalp %s %s | str=%.2f conf=%.2f | spread=%.2fbps | entry=%s tp=%s sl=%s",
            pair, side, metrics.signal_strength, metrics.confidence, spread_bps, entry_price, tp, sl
        )
        return sig

    async def validate_signal(self, signal: Dict[str, Any]) -> bool:
        """
        Final pre-execution sanity checks. Keep it fast—heavy risk rules should live in the
        centralized risk manager.
        """
        try:
            for key in ("pair", "side", "entry_price", "take_profit", "stop_loss", "size_usd"):
                if key not in signal:
                    self.logger.error("Signal missing key: %s", key)
                    return False

            if signal["side"] not in ("buy", "sell"):
                return False

            # Logical TP/SL relationships
            ep = Decimal(str(signal["entry_price"]))
            tp = Decimal(str(signal["take_profit"]))
            sl = Decimal(str(signal["stop_loss"]))
            if signal["side"] == "buy" and not (tp > ep > sl):
                return False
            if signal["side"] == "sell" and not (tp < ep < sl):
                return False

            # Sensible size
            size_usd = Decimal(str(signal["size_usd"]))
            if size_usd <= 0 or size_usd > Decimal("1000"):
                return False

            # Honor configured slippage bound
            mx = int(signal.get("max_slippage_bps", self.max_slippage_bps))
            if mx < 0 or mx > 50:
                return False

            return True
        except Exception as e:
            self.logger.error("validate_signal error: %s", e)
            return False

    async def get_strategy_status(self) -> Dict[str, Any]:
        return {
            "strategy_name": "kraken_scalping",
            "pairs": self.pairs,
            "target_bps": self.target_bps,
            "stop_loss_bps": self.stop_loss_bps,
            "timeframe_hint": self.timeframe,
            "current_regime": self.current_regime,
            "regime_confidence": self.regime_confidence,
            "scalping_suitability": self.scalping_suitability,
            "signals_generated": self.signals_generated,
            "signals_executed": self.signals_executed,
            "signal_execution_rate": (
                (self.signals_executed / self.signals_generated) 
                if self.signals_generated else 0.0
            ),
        }

    # -------- Internals --------

    def _should_generate(self, pair: str) -> bool:
        """Simple per-pair spam guard + loss cooldown + global daily cap."""
        now = _now_ts()

        # Daily cap
        if self._daily_trade_count >= self.daily_trade_limit:
            return False

        # Cooldown after loss (if agent records it via notify_trade_result)
        last_loss = self._last_loss_ts.get(pair)
        if last_loss and now - last_loss < self.cooldown_after_loss_sec:
            return False

        # Per-minute rate limit window
        window = self._trade_counts_min_window.get(pair, [])
        # drop entries older than 60s
        window = [t for t in window if now - t < 60.0]
        self._trade_counts_min_window[pair] = window
        if len(window) >= self.max_trades_per_min:
            return False

        # Per-signal spacing (min ~20s between signals on same pair)
        last_sig = self._last_signal_ts.get(pair, 0.0)
        if now - last_sig < 20.0:
            return False

        return True

    def _mark_signal(self, pair: str) -> None:
        now = _now_ts()
        self._last_signal_ts[pair] = now
        self._trade_counts_min_window[pair].append(now)
        self._daily_trade_count += 1

    def notify_trade_result(self, pair: str, pnl_usd: float) -> None:
        """
        Optional hook for the execution agent to report realized PnL.
        Used to apply short cooldowns after losses to cut chop.
        """
        if pnl_usd < 0:
            self._last_loss_ts[pair] = _now_ts()

    def _build_signal(
        self,
        *,
        pair: str,
        side: str,
        entry_price: Decimal,
        take_profit: Decimal,
        stop_loss: Decimal,
        strength: float,
        confidence: float,
        spread_bps: float,
        mid_price: Decimal,
        vwap: Decimal,
        aggression: float,
        volatility: float,
        trade_intensity: float,
        order_type: str,
        post_only: bool,
        hidden: bool,
        max_slippage_bps: int,
        timeframe_hint: str,
    ) -> Dict[str, Any]:
        """
        Construct a compact, execution-ready payload for your Execution Agent.
        """
        ts = int(_now_ts())
        size_usd = self._suggest_size_usd(strength, confidence)

        return {
            "strategy": "scalper",
            "exchange": "kraken",
            "pair": pair,
            "side": side,
            "entry_price": str(entry_price),
            "take_profit": str(take_profit),
            "stop_loss": str(stop_loss),
            "size_quote_usd": str(size_usd),  # sizing left to execution agent if you prefer
            "order_type": order_type,         # "limit" by default
            "time_in_force": "PO" if post_only else "IOC",
            "post_only": bool(post_only),
            "hidden": bool(hidden),
            "max_slippage_bps": int(max_slippage_bps),
            "timeframe": timeframe_hint,
            "ts": ts,
            # Diagnostics/telemetry
            "meta": {
                "strength": round(float(strength), 4),
                "confidence": round(float(confidence), 4),
                "spread_bps": round(float(spread_bps), 2),
                "mid": str(mid_price),
                "vwap": str(vwap),
                "aggression": round(float(aggression), 4),
                "volatility": round(float(volatility), 6),
                "trade_intensity": round(float(trade_intensity), 4),
                "regime": self.current_regime,
                "regime_conf": round(float(self.regime_confidence), 3),
                "scalp_suit": round(float(self.scalping_suitability), 3),
            },
            # Deterministic-ish id for downstream tracing
            "signal_id": f"kraken_scalp:{pair.replace('/', '-')}.{side}.{ts}",
        }

    def _suggest_size_usd(self, strength: float, confidence: float) -> Decimal:
        """
        Very simple sizing heuristic for scalps; keep most logic in your Risk/Portfolio agents.
        """
        base = Decimal("200")
        mult = max(0.25, min(2.0, strength * (0.5 + confidence)))
        return base * Decimal(str(mult))

    def _debug(self, pair: str, msg: str) -> None:
        self.logger.debug("[%-8s] %s", pair, msg)
