"""
Microreactor 5m Strategy (L1 - Intra-bar Probes)

Intra-bar probe strategy that operates within 5-minute bars:
- Monitors cumulative move vs 5m bar open using 1m sub-bars
- Places tiny maker-only probes when move exceeds ±8-10 bps
- ATR% must be within acceptable range
- Max 2 probes per 5m bar
- Minimum 45-60s spacing between probes
- Probe size factor: 0.25-0.4 of normal position size

Accept criteria:
- Only fires intra-bar (between 5m opens)
- Maker-only execution enforced
- Strict probe limits (2 per 5m bar)
- Daily probe caps enforced
- Total probe risk/day capped

Reject criteria:
- Fixed sizing (must use ATR-based risk)
- Exceeding probe limits
- Insufficient spacing between probes
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional, Dict, Any, List, Tuple

import numpy as np
import pandas as pd

from strategies.api import SignalSpec, PositionSpec, generate_signal_id

logger = logging.getLogger(__name__)


class ProbeState:
    """Track probe state within current 5m bar"""

    def __init__(self, bar_start_time: datetime):
        self.bar_start_time = bar_start_time
        self.probes_this_bar = 0
        self.last_probe_time: Optional[datetime] = None
        self.bar_open_price: Optional[float] = None

    def can_probe(
        self,
        current_time: datetime,
        min_spacing_seconds: int = 45,
    ) -> Tuple[bool, str]:
        """
        Check if new probe is allowed.

        Args:
            current_time: Current timestamp
            min_spacing_seconds: Minimum seconds between probes

        Returns:
            Tuple of (allowed, reason)
        """
        # Check max probes per bar
        if self.probes_this_bar >= 2:
            return False, "max_probes_per_bar"

        # Check spacing
        if self.last_probe_time is not None:
            elapsed = (current_time - self.last_probe_time).total_seconds()
            if elapsed < min_spacing_seconds:
                return False, f"spacing_{int(elapsed)}s"

        return True, "ok"

    def record_probe(self, timestamp: datetime) -> None:
        """Record probe execution"""
        self.probes_this_bar += 1
        self.last_probe_time = timestamp


class DailyProbeGuards:
    """L3 - Daily probe caps and risk limits"""

    def __init__(
        self,
        max_probes_per_day_per_pair: int = 50,
        max_probe_risk_pct_per_day: float = 5.0,
    ):
        """
        Initialize daily guards.

        Args:
            max_probes_per_day_per_pair: Max probes per day per pair
            max_probe_risk_pct_per_day: Max total probe risk % per day
        """
        self.max_probes_per_day_per_pair = max_probes_per_day_per_pair
        self.max_probe_risk_pct_per_day = max_probe_risk_pct_per_day

        # State (reset daily)
        self.current_day: Optional[str] = None
        self.probes_today: Dict[str, int] = {}  # pair -> count
        self.probe_risk_today_pct: float = 0.0

    def reset_if_new_day(self, timestamp: datetime) -> None:
        """Reset counters if new trading day"""
        day_str = timestamp.strftime("%Y-%m-%d")

        if self.current_day != day_str:
            logger.info(f"New trading day: {day_str}, resetting probe guards")
            self.current_day = day_str
            self.probes_today = {}
            self.probe_risk_today_pct = 0.0

    def can_probe(
        self,
        pair: str,
        probe_risk_pct: float,
        timestamp: datetime,
    ) -> Tuple[bool, str]:
        """
        Check if probe allowed under daily caps.

        Args:
            pair: Trading pair
            probe_risk_pct: Risk % for this probe
            timestamp: Current timestamp

        Returns:
            Tuple of (allowed, reason)
        """
        self.reset_if_new_day(timestamp)

        # Check pair probe count
        pair_count = self.probes_today.get(pair, 0)
        if pair_count >= self.max_probes_per_day_per_pair:
            return False, f"pair_daily_limit_{pair_count}"

        # Check total daily risk
        if self.probe_risk_today_pct + probe_risk_pct > self.max_probe_risk_pct_per_day:
            return False, f"daily_risk_limit_{self.probe_risk_today_pct:.2f}%"

        return True, "ok"

    def record_probe(self, pair: str, probe_risk_pct: float) -> None:
        """Record probe execution"""
        self.probes_today[pair] = self.probes_today.get(pair, 0) + 1
        self.probe_risk_today_pct += probe_risk_pct


class Microreactor5mStrategy:
    """
    L1 - Intra-bar probe strategy for 5m bars.

    Monitors cumulative move within 5m bar using 1m sub-bars and places
    tiny maker-only probes when thresholds exceeded.

    Attributes:
        probe_trigger_bps: Cumulative move threshold for probe (8-10 bps)
        min_atr_pct: Minimum ATR% filter (same as bar_reaction_5m)
        max_atr_pct: Maximum ATR% filter
        atr_window: ATR calculation period
        sl_atr: Stop loss as ATR multiple (scaled for probes)
        tp1_atr: First take profit as ATR multiple
        tp2_atr: Second take profit as ATR multiple
        probe_size_factor: Probe size as fraction of normal (0.25-0.4)
        risk_per_trade_pct: Base risk per trade % (probe uses probe_size_factor * this)
        maker_only: Enforce maker-only execution
        spread_bps_cap: Maximum spread in bps
        min_spacing_seconds: Minimum seconds between probes (45-60s)
        max_probes_per_bar: Max probes per 5m bar (2)
        max_probes_per_day_per_pair: Max probes per day per pair (50)
        max_probe_risk_pct_per_day: Max total probe risk % per day (5%)
    """

    def __init__(
        self,
        probe_trigger_bps: float = 10.0,
        min_atr_pct: float = 0.25,
        max_atr_pct: float = 3.0,
        atr_window: int = 14,
        sl_atr: float = 0.6,
        tp1_atr: float = 1.0,
        tp2_atr: float = 1.8,
        probe_size_factor: float = 0.3,
        risk_per_trade_pct: float = 0.6,
        maker_only: bool = True,
        spread_bps_cap: float = 8.0,
        min_spacing_seconds: int = 45,
        max_probes_per_bar: int = 2,
        max_probes_per_day_per_pair: int = 50,
        max_probe_risk_pct_per_day: float = 5.0,
        redis_client: Optional[Any] = None,
    ):
        """
        Initialize microreactor 5m strategy.

        Args:
            probe_trigger_bps: Cumulative move threshold in bps
            min_atr_pct: Minimum ATR% filter
            max_atr_pct: Maximum ATR% filter
            atr_window: ATR period
            sl_atr: Stop loss ATR multiple
            tp1_atr: First TP ATR multiple
            tp2_atr: Second TP ATR multiple
            probe_size_factor: Probe size factor (0.25-0.4)
            risk_per_trade_pct: Base risk per trade %
            maker_only: Enforce maker-only
            spread_bps_cap: Max spread in bps
            min_spacing_seconds: Min spacing between probes (45-60s)
            max_probes_per_bar: Max probes per 5m bar (2)
            max_probes_per_day_per_pair: Max probes per day per pair (50)
            max_probe_risk_pct_per_day: Max total probe risk % per day (5%)
            redis_client: Optional Redis client for state persistence
        """
        self.probe_trigger_bps = probe_trigger_bps
        self.min_atr_pct = min_atr_pct
        self.max_atr_pct = max_atr_pct
        self.atr_window = atr_window
        self.sl_atr = sl_atr
        self.tp1_atr = tp1_atr
        self.tp2_atr = tp2_atr
        self.probe_size_factor = probe_size_factor
        self.risk_per_trade_pct = risk_per_trade_pct
        self.maker_only = maker_only
        self.spread_bps_cap = spread_bps_cap
        self.min_spacing_seconds = min_spacing_seconds
        self.max_probes_per_bar = max_probes_per_bar

        # L3 Guards
        self.daily_guards = DailyProbeGuards(
            max_probes_per_day_per_pair=max_probes_per_day_per_pair,
            max_probe_risk_pct_per_day=max_probe_risk_pct_per_day,
        )

        # State tracking
        self.probe_states: Dict[str, ProbeState] = {}  # pair -> ProbeState
        self.last_5m_bar_start: Dict[str, datetime] = {}  # pair -> timestamp

        # ATR cache
        self.atr_cache: Dict[str, float] = {}  # pair -> ATR

        self.redis_client = redis_client

        logger.info(
            f"Microreactor5mStrategy initialized: "
            f"trigger={probe_trigger_bps}bps, "
            f"size_factor={probe_size_factor}, "
            f"max_probes_per_bar={max_probes_per_bar}, "
            f"spacing={min_spacing_seconds}s"
        )

    def get_5m_bar_start(self, timestamp: datetime) -> datetime:
        """
        Get start time of current 5m bar.

        Args:
            timestamp: Current timestamp

        Returns:
            5m bar start timestamp (floor to 5-minute boundary)
        """
        # Floor to 5-minute boundary
        minute = timestamp.minute
        floored_minute = (minute // 5) * 5

        return timestamp.replace(
            minute=floored_minute,
            second=0,
            microsecond=0,
        )

    def update_probe_state(self, pair: str, timestamp: datetime) -> None:
        """
        Update probe state for new 5m bar if needed.

        Args:
            pair: Trading pair
            timestamp: Current timestamp
        """
        current_bar_start = self.get_5m_bar_start(timestamp)

        last_bar_start = self.last_5m_bar_start.get(pair)

        # New 5m bar started
        if last_bar_start is None or current_bar_start > last_bar_start:
            self.probe_states[pair] = ProbeState(current_bar_start)
            self.last_5m_bar_start[pair] = current_bar_start
            logger.debug(f"New 5m bar for {pair} at {current_bar_start}")

    def check_intra_bar_probe(
        self,
        pair: str,
        current_1m_bar: pd.Series,
        bar_5m_open: float,
        atr: float,
        timestamp: datetime,
    ) -> Optional[Tuple[str, float]]:
        """
        Check if intra-bar probe should fire.

        Args:
            pair: Trading pair
            current_1m_bar: Current 1m OHLCV bar
            bar_5m_open: Open price of current 5m bar
            atr: Current ATR value
            timestamp: Current timestamp

        Returns:
            Optional tuple of (side, cumulative_move_bps) if probe triggered
        """
        current_close = current_1m_bar["close"]

        # Calculate cumulative move from 5m open
        cumulative_move_bps = ((current_close - bar_5m_open) / bar_5m_open) * 10000

        # Check trigger threshold
        if abs(cumulative_move_bps) < self.probe_trigger_bps:
            return None

        # Determine side (trend following)
        side = "long" if cumulative_move_bps > 0 else "short"

        # Check ATR% gates
        atr_pct = (atr / current_close) * 100

        if atr_pct < self.min_atr_pct:
            logger.debug(f"ATR% too low: {atr_pct:.2f}% < {self.min_atr_pct}%")
            return None

        if atr_pct > self.max_atr_pct:
            logger.debug(f"ATR% too high: {atr_pct:.2f}% > {self.max_atr_pct}%")
            return None

        return (side, cumulative_move_bps)

    def generate_probe_signal(
        self,
        pair: str,
        side: str,
        current_price: float,
        atr: float,
        timestamp: datetime,
        cumulative_move_bps: float,
    ) -> SignalSpec:
        """
        Generate probe signal.

        Args:
            pair: Trading pair
            side: "long" or "short"
            current_price: Current market price
            atr: Current ATR
            timestamp: Signal timestamp
            cumulative_move_bps: Cumulative move in bps

        Returns:
            SignalSpec for probe
        """
        # Calculate SL/TP based on ATR
        if side == "long":
            sl_price = current_price - (atr * self.sl_atr)
            tp1_price = current_price + (atr * self.tp1_atr)
            tp2_price = current_price + (atr * self.tp2_atr)
        else:  # short
            sl_price = current_price + (atr * self.sl_atr)
            tp1_price = current_price - (atr * self.tp1_atr)
            tp2_price = current_price - (atr * self.tp2_atr)

        # Generate signal ID
        signal_id = generate_signal_id(
            timestamp=timestamp,
            symbol=pair,
            strategy="microreactor_5m",
            price_level=current_price,
        )

        # Build metadata
        metadata = {
            "atr": str(atr),
            "atr_pct": str((atr / current_price) * 100),
            "sl_atr_multiple": str(self.sl_atr),
            "tp1_atr_multiple": str(self.tp1_atr),
            "tp2_atr_multiple": str(self.tp2_atr),
            "tp1_price": str(tp1_price),
            "tp2_price": str(tp2_price),
            "cumulative_move_bps": str(cumulative_move_bps),
            "probe_size_factor": str(self.probe_size_factor),
            "is_probe": "true",
        }

        signal = SignalSpec(
            signal_id=signal_id,
            timestamp=timestamp,
            symbol=pair,
            side=side,
            entry_price=Decimal(str(current_price)),
            stop_loss=Decimal(str(sl_price)),
            take_profit=Decimal(str(tp2_price)),
            strategy="microreactor_5m",
            confidence=Decimal("0.65"),  # Lower confidence for probes
            metadata=metadata,
        )

        logger.info(
            f"PROBE SIGNAL: {side.upper()} {pair} @ ${current_price:.2f} "
            f"(move={cumulative_move_bps:+.1f}bps, SL=${sl_price:.2f}, "
            f"TP1=${tp1_price:.2f}, TP2=${tp2_price:.2f}, "
            f"size_factor={self.probe_size_factor})"
        )

        return signal

    def size_probe_position(
        self,
        signal: SignalSpec,
        account_equity_usd: Decimal,
    ) -> PositionSpec:
        """
        Size probe position (smaller than normal).

        Args:
            signal: Probe signal
            account_equity_usd: Account equity in USD

        Returns:
            PositionSpec with probe-sized position
        """
        entry_price = float(signal.entry_price)
        sl_price = float(signal.stop_loss)

        # Calculate base risk (probe size factor applied)
        probe_risk_pct = self.risk_per_trade_pct * self.probe_size_factor
        risk_amount_usd = float(account_equity_usd) * (probe_risk_pct / 100.0)

        # Calculate position size based on SL distance
        sl_distance_pct = abs((entry_price - sl_price) / entry_price)

        if sl_distance_pct > 0:
            position_size_usd = risk_amount_usd / sl_distance_pct
        else:
            position_size_usd = 0.0

        # Convert to quantity
        quantity = position_size_usd / entry_price

        position = PositionSpec(
            signal_id=signal.signal_id,
            symbol=signal.symbol,
            side=signal.side,
            size=Decimal(str(quantity)),
            entry_price=signal.entry_price,
            risk_per_trade_usd=Decimal(str(risk_amount_usd)),
        )

        logger.debug(
            f"Probe position sized: {quantity:.6f} {signal.symbol} "
            f"(${position_size_usd:.2f}, risk=${risk_amount_usd:.2f}, "
            f"probe_risk={probe_risk_pct:.2f}%)"
        )

        return position

    def process_1m_tick(
        self,
        pair: str,
        current_1m_bar: pd.Series,
        bar_5m_open: float,
        atr: float,
        account_equity_usd: Decimal,
        timestamp: datetime,
    ) -> List[Tuple[SignalSpec, PositionSpec]]:
        """
        Process 1m tick for probe opportunities.

        Args:
            pair: Trading pair
            current_1m_bar: Current 1m OHLCV bar
            bar_5m_open: Open price of current 5m bar
            atr: Current ATR
            account_equity_usd: Account equity
            timestamp: Current timestamp

        Returns:
            List of (SignalSpec, PositionSpec) tuples for probes
        """
        # Update probe state for new 5m bars
        self.update_probe_state(pair, timestamp)

        probe_state = self.probe_states.get(pair)
        if probe_state is None:
            return []

        # Set bar open price on first tick
        if probe_state.bar_open_price is None:
            probe_state.bar_open_price = bar_5m_open

        # Check if probe can fire (spacing & max per bar)
        can_probe, reason = probe_state.can_probe(timestamp, self.min_spacing_seconds)
        if not can_probe:
            logger.debug(f"Probe blocked for {pair}: {reason}")
            return []

        # Check intra-bar trigger
        probe_check = self.check_intra_bar_probe(
            pair=pair,
            current_1m_bar=current_1m_bar,
            bar_5m_open=bar_5m_open,
            atr=atr,
            timestamp=timestamp,
        )

        if probe_check is None:
            return []

        side, cumulative_move_bps = probe_check

        # Check daily guards (L3)
        probe_risk_pct = self.risk_per_trade_pct * self.probe_size_factor
        can_probe_daily, reason_daily = self.daily_guards.can_probe(
            pair=pair,
            probe_risk_pct=probe_risk_pct,
            timestamp=timestamp,
        )

        if not can_probe_daily:
            logger.warning(f"Probe blocked by daily guards for {pair}: {reason_daily}")
            return []

        # Generate signal
        current_price = current_1m_bar["close"]
        signal = self.generate_probe_signal(
            pair=pair,
            side=side,
            current_price=current_price,
            atr=atr,
            timestamp=timestamp,
            cumulative_move_bps=cumulative_move_bps,
        )

        # Size position
        position = self.size_probe_position(signal, account_equity_usd)

        # Record probe
        probe_state.record_probe(timestamp)
        self.daily_guards.record_probe(pair, probe_risk_pct)

        logger.info(
            f"Probe {probe_state.probes_this_bar}/2 for {pair} this bar, "
            f"{self.daily_guards.probes_today.get(pair, 0)}/{self.daily_guards.max_probes_per_day_per_pair} today"
        )

        return [(signal, position)]
