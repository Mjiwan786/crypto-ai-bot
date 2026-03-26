"""
Sprint 3B: Structured exit hierarchy with trailing stop, breakeven stop,
time-based exit, and confidence-gated signal flips.

Priority order:
  1. SL hit (highest — always respected)
  2. TP hit
  3. Trailing stop (activates at +1.0 ATR, trails at 0.75 ATR from peak)
  4. Breakeven stop (activates at +0.5 ATR, moves SL to entry + fees)
  5. Time-based exit (max hold 4 hours)
  6. Signal flip (only if new signal confidence > 0.80)
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


class ExitManager:
    """Priority-ordered exit system for paper/live position management."""

    def __init__(
        self,
        fee_bps: float = 52.0,
        max_hold_seconds: int = None,
        signal_flip_min_confidence: float = None,
        trailing_activation_atr: float = None,
        trailing_distance_atr: float = None,
        breakeven_activation_atr: float = None,
        trailing_enabled: bool = None,
        breakeven_enabled: bool = None,
        time_based_enabled: bool = None,
    ):
        self.fee_bps = fee_bps

        if max_hold_seconds is None:
            max_hold_seconds = int(os.getenv("EXIT_MAX_HOLD_SECONDS", "14400"))
        self.max_hold_seconds = max_hold_seconds

        if signal_flip_min_confidence is None:
            signal_flip_min_confidence = float(os.getenv("EXIT_SIGNAL_FLIP_MIN_CONFIDENCE", "0.80"))
        self.signal_flip_min_confidence = signal_flip_min_confidence

        if trailing_activation_atr is None:
            trailing_activation_atr = float(os.getenv("EXIT_TRAILING_ACTIVATION_ATR", "1.5"))
        self.trailing_activation_atr = trailing_activation_atr

        if trailing_distance_atr is None:
            trailing_distance_atr = float(os.getenv("EXIT_TRAILING_DISTANCE_ATR", "1.0"))
        self.trailing_distance_atr = trailing_distance_atr

        if breakeven_activation_atr is None:
            breakeven_activation_atr = float(os.getenv("EXIT_BREAKEVEN_ACTIVATION_ATR", "2.0"))
        self.breakeven_activation_atr = breakeven_activation_atr

        if trailing_enabled is None:
            trailing_enabled = os.getenv("EXIT_TRAILING_ENABLED", "true").lower() == "true"
        self.trailing_enabled = trailing_enabled

        if breakeven_enabled is None:
            breakeven_enabled = os.getenv("EXIT_BREAKEVEN_ENABLED", "true").lower() == "true"
        self.breakeven_enabled = breakeven_enabled

        if time_based_enabled is None:
            time_based_enabled = os.getenv("EXIT_TIME_BASED_ENABLED", "true").lower() == "true"
        self.time_based_enabled = time_based_enabled

    def evaluate_exit(
        self,
        position: dict,
        current_price: float,
        current_time: float,
        highest_since_entry: float,
        lowest_since_entry: float,
        new_signal: Optional[dict] = None,
    ) -> Optional[dict]:
        """
        Evaluate whether a position should be exited.

        Args:
            position: {side, entry_price, stop_loss, take_profit, atr_value, open_time}
            current_price: latest market price
            current_time: time.time()
            highest_since_entry: highest price observed since position opened
            lowest_since_entry: lowest price observed since position opened
            new_signal: opposing signal dict with 'confidence' key, or None

        Returns:
            {"exit": True, "exit_price": float, "exit_reason": str, "details": str}
            or None to keep position open.
        """
        side = position["side"]
        entry = position["entry_price"]
        sl = position["stop_loss"]
        tp = position["take_profit"]
        atr = position.get("atr_value", 0)
        open_time = position["open_time"]
        pair = position.get("pair", "")

        is_long = side in ("LONG", "buy")

        # ── Priority 1: SL hit ──────────────────────────────────
        if sl > 0:
            if is_long and current_price <= sl:
                return {
                    "exit": True,
                    "exit_price": current_price,
                    "exit_reason": "sl_hit",
                    "details": f"SL={sl:.6g} hit at {current_price:.6g}",
                }
            if not is_long and current_price >= sl:
                return {
                    "exit": True,
                    "exit_price": current_price,
                    "exit_reason": "sl_hit",
                    "details": f"SL={sl:.6g} hit at {current_price:.6g}",
                }

        # ── Priority 2: TP hit ──────────────────────────────────
        if tp > 0:
            if is_long and current_price >= tp:
                return {
                    "exit": True,
                    "exit_price": current_price,
                    "exit_reason": "tp_hit",
                    "details": f"TP={tp:.6g} hit at {current_price:.6g}",
                }
            if not is_long and current_price <= tp:
                return {
                    "exit": True,
                    "exit_price": current_price,
                    "exit_reason": "tp_hit",
                    "details": f"TP={tp:.6g} hit at {current_price:.6g}",
                }

        # ── Priority 3: Trailing stop ──────────────────────────
        if self.trailing_enabled and atr > 0:
            activation_distance = atr * self.trailing_activation_atr
            trail_distance = atr * self.trailing_distance_atr

            if is_long:
                unrealized = highest_since_entry - entry
                if unrealized >= activation_distance:
                    trail_stop = highest_since_entry - trail_distance
                    if current_price <= trail_stop:
                        logger.info(
                            "[EXIT_MGR] %s LONG: trailing stop triggered at %.6g "
                            "(peak=%.6g, trail=%.6g)",
                            pair, current_price, highest_since_entry, trail_stop,
                        )
                        return {
                            "exit": True,
                            "exit_price": current_price,
                            "exit_reason": "trailing_stop",
                            "details": (
                                f"Peak={highest_since_entry:.6g}, "
                                f"trail_stop={trail_stop:.6g}, "
                                f"price={current_price:.6g}"
                            ),
                        }
            else:
                unrealized = entry - lowest_since_entry
                if unrealized >= activation_distance:
                    trail_stop = lowest_since_entry + trail_distance
                    if current_price >= trail_stop:
                        logger.info(
                            "[EXIT_MGR] %s SHORT: trailing stop triggered at %.6g "
                            "(trough=%.6g, trail=%.6g)",
                            pair, current_price, lowest_since_entry, trail_stop,
                        )
                        return {
                            "exit": True,
                            "exit_price": current_price,
                            "exit_reason": "trailing_stop",
                            "details": (
                                f"Trough={lowest_since_entry:.6g}, "
                                f"trail_stop={trail_stop:.6g}, "
                                f"price={current_price:.6g}"
                            ),
                        }

        # ── Priority 4: Breakeven stop ─────────────────────────
        if self.breakeven_enabled and atr > 0:
            be_activation = atr * self.breakeven_activation_atr
            fee_offset = entry * (self.fee_bps / 10000)

            if is_long:
                unrealized = current_price - entry
                if unrealized >= be_activation:
                    be_stop = entry + fee_offset
                    if current_price <= be_stop:
                        logger.info(
                            "[EXIT_MGR] %s LONG: breakeven stop hit at %.6g (BE=%.6g)",
                            pair, current_price, be_stop,
                        )
                        return {
                            "exit": True,
                            "exit_price": current_price,
                            "exit_reason": "breakeven_stop",
                            "details": f"Breakeven stop at {be_stop:.6g} (+{self.fee_bps} bps above entry)",
                        }
            else:
                unrealized = entry - current_price
                if unrealized >= be_activation:
                    be_stop = entry - fee_offset
                    if current_price >= be_stop:
                        logger.info(
                            "[EXIT_MGR] %s SHORT: breakeven stop hit at %.6g (BE=%.6g)",
                            pair, current_price, be_stop,
                        )
                        return {
                            "exit": True,
                            "exit_price": current_price,
                            "exit_reason": "breakeven_stop",
                            "details": f"Breakeven stop at {be_stop:.6g} (-{self.fee_bps} bps below entry)",
                        }

        # ── Priority 5: Time-based exit ────────────────────────
        if self.time_based_enabled:
            hold_seconds = current_time - open_time
            if hold_seconds >= self.max_hold_seconds:
                hours = int(hold_seconds // 3600)
                mins = int((hold_seconds % 3600) // 60)
                logger.info(
                    "[EXIT_MGR] %s %s: time exit at %dh%dm (max hold exceeded)",
                    pair, side, hours, mins,
                )
                return {
                    "exit": True,
                    "exit_price": current_price,
                    "exit_reason": "time_exit",
                    "details": f"Max hold {self.max_hold_seconds}s exceeded ({hours}h{mins}m)",
                }

        # ── Priority 6: Signal flip (confidence-gated) ─────────
        if new_signal is not None:
            conf = float(new_signal.get("confidence", 0))
            if conf >= self.signal_flip_min_confidence:
                logger.info(
                    "[EXIT_MGR] %s: signal flip accepted (conf=%.2f >= %.2f)",
                    pair, conf, self.signal_flip_min_confidence,
                )
                return {
                    "exit": True,
                    "exit_price": current_price,
                    "exit_reason": "signal_flip",
                    "details": f"Opposing signal conf={conf:.2f} >= {self.signal_flip_min_confidence:.2f}",
                }
            else:
                logger.info(
                    "[EXIT_MGR] %s: ignoring weak signal flip (conf=%.2f < %.2f)",
                    pair, conf, self.signal_flip_min_confidence,
                )

        return None
