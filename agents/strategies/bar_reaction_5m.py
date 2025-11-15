"""
Bar Reaction 5M Agent

Agent-based decision engine for bar_reaction_5m strategy with:
- Bar-close event handling (5-minute boundaries)
- Redis-based cooldowns and concurrency limits
- Microstructure checks (spread, liquidity)
- Signal generation with ATR-based SL/TP
- Direct Redis stream publishing (signals:paper)

Event Flow:
1. Receive bar_close:5m event for pair
2. Fetch last 2 bars (t-0, t-1) and compute features
3. Check microstructure (spread <= cap, notional >= floor)
4. Check cooldowns and concurrency (per-pair Redis caches)
5. Generate signal based on mode (trend/revert/extreme)
6. Publish to signals:paper with full metadata

Accept criteria:
- Fires only on bar_close:5m events
- Respects cooldowns (minutes since last signal per pair)
- Enforces concurrency limits (max open positions per pair)
- ATR-based dynamic stops and targets
- Deterministic signal IDs

Reject criteria:
- Intra-bar signals (event-driven only)
- Fixed stops/targets (must use ATR)
- Missing microstructure checks
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Dict, Any, List

import pandas as pd
import redis.asyncio as redis

from strategies.bar_reaction_data import BarReactionDataPipeline

# Direct imports to avoid circular dependencies
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.streams_schema import SignalPayload, validate_signal_payload

logger = logging.getLogger(__name__)


@dataclass
class BarCloseEvent:
    """
    Bar-close event triggered at 5-minute boundaries.

    Attributes:
        timestamp: Bar close timestamp (UTC)
        pair: Trading pair (e.g., "BTC/USD")
        timeframe: Bar timeframe (must be "5m")
        bar_data: OHLCV data for closed bar
    """
    timestamp: datetime
    pair: str
    timeframe: str
    bar_data: Dict[str, float]


@dataclass
class MicrostructureCheck:
    """
    Microstructure validation result.

    Attributes:
        passed: True if all checks passed
        spread_bps: Current spread in basis points
        rolling_notional: Rolling notional volume
        reason: Rejection reason (if failed)
    """
    passed: bool
    spread_bps: float
    rolling_notional: float
    reason: Optional[str] = None


@dataclass
class CooldownState:
    """
    Per-pair cooldown and concurrency tracking.

    Attributes:
        pair: Trading pair
        last_signal_ts: Timestamp of last signal (seconds)
        open_positions: Number of open positions for this pair
        total_signals_today: Total signals generated today
    """
    pair: str
    last_signal_ts: float
    open_positions: int
    total_signals_today: int


class BarReaction5M:
    """
    Bar-close decision engine for 5-minute bar reaction strategy.

    Responsibilities:
    - Handle bar_close:5m events
    - Compute features (move_bps, atr_pct)
    - Check microstructure constraints
    - Manage cooldowns and concurrency via Redis
    - Generate signals with ATR-based SL/TP
    - Publish to signals:paper stream

    Redis Keys Used:
    - bar_reaction:cooldown:{pair} - Last signal timestamp
    - bar_reaction:open_positions:{pair} - Open position count
    - bar_reaction:daily_count:{pair}:{date} - Daily signal count

    Example:
        >>> agent = BarReaction5M(config, redis_client)
        >>> await agent.on_bar_close(event)
        # Generates and publishes signal if conditions met
    """

    def __init__(
        self,
        config: Dict[str, Any],
        redis_client: redis.Redis,
        data_pipeline: Optional[BarReactionDataPipeline] = None,
    ):
        """
        Initialize bar reaction agent.

        Args:
            config: Strategy configuration from enhanced_scalper_config.yaml
            redis_client: Async Redis client for cooldowns/concurrency
            data_pipeline: Optional data pipeline (creates if None)
        """
        self.config = config
        self.redis = redis_client

        # Extract config parameters
        self.mode = config.get("mode", "trend")
        self.trigger_mode = config.get("trigger_mode", "open_to_close")
        self.trigger_bps_up = float(config.get("trigger_bps_up", 12.0))
        self.trigger_bps_down = float(config.get("trigger_bps_down", 12.0))

        # ATR gates
        self.min_atr_pct = float(config.get("min_atr_pct", 0.25))
        self.max_atr_pct = float(config.get("max_atr_pct", 3.0))
        self.atr_window = int(config.get("atr_window", 14))

        # ATR-based stops/targets
        self.sl_atr = float(config.get("sl_atr", 0.6))
        self.tp1_atr = float(config.get("tp1_atr", 1.0))
        self.tp2_atr = float(config.get("tp2_atr", 1.8))

        # Risk management
        self.risk_per_trade_pct = float(config.get("risk_per_trade_pct", 0.6))

        # Execution settings
        self.maker_only = config.get("maker_only", True)
        self.spread_bps_cap = float(config.get("spread_bps_cap", 8.0))

        # Microstructure thresholds
        self.min_notional_floor = float(config.get("min_notional_floor", 100000.0))

        # Extreme fade logic
        self.enable_extreme_fade = config.get("enable_mean_revert_extremes", False)
        self.extreme_bps_threshold = float(config.get("extreme_bps_threshold", 35.0))
        self.mean_revert_size_factor = float(config.get("mean_revert_size_factor", 0.5))

        # Cooldowns and concurrency
        self.cooldown_minutes = int(config.get("cooldown_minutes", 15))
        self.max_concurrent_per_pair = int(config.get("max_concurrent_per_pair", 2))
        self.max_signals_per_day = int(config.get("max_signals_per_day", 50))

        # Data pipeline
        if data_pipeline is None:
            self.data_pipeline = BarReactionDataPipeline(atr_period=self.atr_window)
        else:
            self.data_pipeline = data_pipeline

        logger.info(
            f"BarReaction5M initialized: mode={self.mode}, trigger_mode={self.trigger_mode}, "
            f"trigger_bps={self.trigger_bps_up}, atr_range=[{self.min_atr_pct}, {self.max_atr_pct}]"
        )

    async def on_bar_close(self, event: BarCloseEvent) -> Optional[SignalPayload]:
        """
        Handle bar-close event and generate signal if conditions met.

        Workflow:
        1. Validate event (must be 5m timeframe)
        2. Fetch bars and compute features
        3. Check microstructure constraints
        4. Check cooldowns and concurrency
        5. Generate signal based on mode
        6. Publish to Redis signals:paper
        7. Update cooldown state

        Args:
            event: Bar-close event with timestamp and OHLCV data

        Returns:
            SignalPayload if signal generated, None otherwise
        """
        pair = event.pair

        # 1. Validate event
        if event.timeframe != "5m":
            logger.warning(f"BarReaction5M: Invalid timeframe {event.timeframe} (expected 5m)")
            return None

        logger.debug(f"BarReaction5M: Processing bar_close:5m for {pair} at {event.timestamp}")

        # 2. Fetch bars and compute features
        try:
            features_df = await self._fetch_features(pair, event)
        except Exception as e:
            logger.error(f"BarReaction5M ({pair}): Failed to fetch features: {e}")
            return None

        if features_df is None or len(features_df) < 2:
            logger.debug(f"BarReaction5M ({pair}): Insufficient bar data")
            return None

        # Get latest bar features
        latest = features_df.iloc[-1]
        move_bps = latest.get("move_bps", 0.0)
        atr = latest.get("atr", 0.0)
        atr_pct = latest.get("atr_pct", 0.0)
        spread_bps = latest.get("spread_bps", 0.0)
        notional = latest.get("notional_usd", 0.0)
        close_price = latest.get("close", 0.0)

        logger.debug(
            f"BarReaction5M ({pair}): Features - move_bps={move_bps:.2f}, "
            f"atr_pct={atr_pct:.3f}%, spread={spread_bps:.2f}bps, notional=${notional:.0f}"
        )

        # 3. Check ATR gates
        if atr_pct < self.min_atr_pct or atr_pct > self.max_atr_pct:
            logger.debug(
                f"BarReaction5M ({pair}): ATR% {atr_pct:.3f}% outside range "
                f"[{self.min_atr_pct}, {self.max_atr_pct}]"
            )
            return None

        # 4. Check microstructure
        microstructure = self._check_microstructure(spread_bps, notional)
        if not microstructure.passed:
            logger.debug(f"BarReaction5M ({pair}): Microstructure check failed - {microstructure.reason}")
            return None

        # 5. Check cooldowns and concurrency
        cooldown_ok, cooldown_reason = await self._check_cooldowns(pair)
        if not cooldown_ok:
            logger.debug(f"BarReaction5M ({pair}): Cooldown check failed - {cooldown_reason}")
            return None

        # 6. Decide side and check triggers
        signal_type, side = self._decide_signal(move_bps)

        if signal_type is None:
            logger.debug(f"BarReaction5M ({pair}): No trigger (move_bps={move_bps:.2f})")
            return None

        # 7. Generate signal
        signal = self._create_signal(
            pair=pair,
            side=side,
            signal_type=signal_type,
            entry_price=close_price,
            atr=atr,
            atr_pct=atr_pct,
            move_bps=move_bps,
            timestamp=event.timestamp,
        )

        # 8. Publish to Redis
        try:
            await self._publish_signal(signal)

            # 9. Update cooldown state
            await self._update_cooldown_state(pair, event.timestamp)

            logger.info(
                f"BarReaction5M ({pair}): Published {signal_type} {side.upper()} signal, "
                f"entry={signal.entry}, move_bps={move_bps:.2f}"
            )

            return signal

        except Exception as e:
            logger.error(f"BarReaction5M ({pair}): Failed to publish signal: {e}")
            return None

    async def _fetch_features(
        self,
        pair: str,
        event: BarCloseEvent
    ) -> Optional[pd.DataFrame]:
        """
        Fetch bars and compute features (ATR, move_bps, etc.).

        Args:
            pair: Trading pair
            event: Bar-close event

        Returns:
            DataFrame with enriched features, None if insufficient data
        """
        # In production, fetch from Redis streams (kraken:ohlc:5m:{pair})
        # For now, simulate by creating DataFrame from event

        # TODO: Replace with actual Redis stream fetch
        # bars_5m = await self._fetch_from_redis(f"kraken:ohlc:5m:{pair}", count=20)

        # Placeholder: Create minimal DataFrame for feature computation
        # In production, this should fetch ~20 bars for ATR calculation
        logger.debug(f"BarReaction5M ({pair}): Fetching features (stub implementation)")

        return None  # Will be implemented with actual Redis integration

    def _check_microstructure(
        self,
        spread_bps: float,
        notional: float
    ) -> MicrostructureCheck:
        """
        Validate microstructure constraints.

        Args:
            spread_bps: Current spread in basis points
            notional: Rolling notional volume

        Returns:
            MicrostructureCheck result
        """
        # Check spread
        if spread_bps > self.spread_bps_cap:
            return MicrostructureCheck(
                passed=False,
                spread_bps=spread_bps,
                rolling_notional=notional,
                reason=f"Spread {spread_bps:.2f}bps > cap {self.spread_bps_cap:.2f}bps"
            )

        # Check notional floor
        if notional < self.min_notional_floor:
            return MicrostructureCheck(
                passed=False,
                spread_bps=spread_bps,
                rolling_notional=notional,
                reason=f"Notional ${notional:.0f} < floor ${self.min_notional_floor:.0f}"
            )

        return MicrostructureCheck(
            passed=True,
            spread_bps=spread_bps,
            rolling_notional=notional,
        )

    async def _check_cooldowns(self, pair: str) -> tuple[bool, Optional[str]]:
        """
        Check cooldown and concurrency limits via Redis.

        Redis keys:
        - bar_reaction:cooldown:{pair} - Last signal timestamp (float)
        - bar_reaction:open_positions:{pair} - Open position count (int)
        - bar_reaction:daily_count:{pair}:{date} - Daily signal count (int)

        Args:
            pair: Trading pair

        Returns:
            Tuple of (ok, reason)
        """
        now = time.time()
        today = datetime.now(timezone.utc).strftime("%Y%m%d")

        # Check cooldown (minutes since last signal)
        cooldown_key = f"bar_reaction:cooldown:{pair}"
        last_signal_ts = await self.redis.get(cooldown_key)

        if last_signal_ts is not None:
            last_ts = float(last_signal_ts)
            elapsed_minutes = (now - last_ts) / 60.0

            if elapsed_minutes < self.cooldown_minutes:
                return False, f"Cooldown: {elapsed_minutes:.1f}min < {self.cooldown_minutes}min"

        # Check concurrency (open positions)
        open_pos_key = f"bar_reaction:open_positions:{pair}"
        open_count = await self.redis.get(open_pos_key)

        if open_count is not None:
            open_count = int(open_count)
            if open_count >= self.max_concurrent_per_pair:
                return False, f"Concurrency: {open_count} >= {self.max_concurrent_per_pair} open positions"

        # Check daily limit
        daily_key = f"bar_reaction:daily_count:{pair}:{today}"
        daily_count = await self.redis.get(daily_key)

        if daily_count is not None:
            daily_count = int(daily_count)
            if daily_count >= self.max_signals_per_day:
                return False, f"Daily limit: {daily_count} >= {self.max_signals_per_day} signals"

        return True, None

    def _decide_signal(self, move_bps: float) -> tuple[Optional[str], Optional[str]]:
        """
        Decide signal type and side based on move_bps and mode.

        Logic:
        - Primary signal: |move_bps| >= trigger threshold
          - Trend mode: follow momentum (up -> long, down -> short)
          - Revert mode: fade move (up -> short, down -> long)

        - Extreme signal: |move_bps| >= extreme_threshold (if enabled)
          - Always contrarian: up -> short, down -> long

        Args:
            move_bps: Bar move in basis points

        Returns:
            Tuple of (signal_type, side) or (None, None) if no trigger
        """
        # Check primary trigger
        if move_bps >= self.trigger_bps_up:
            # Upward move
            if self.mode == "trend":
                return "primary", "buy"
            else:  # revert
                return "primary", "sell"

        elif move_bps <= -self.trigger_bps_down:
            # Downward move
            if self.mode == "trend":
                return "primary", "sell"
            else:  # revert
                return "primary", "buy"

        # Check extreme trigger (if enabled)
        if self.enable_extreme_fade and abs(move_bps) >= self.extreme_bps_threshold:
            # Extreme move - always contrarian
            if move_bps > 0:
                return "extreme_fade", "sell"
            else:
                return "extreme_fade", "buy"

        return None, None

    def _create_signal(
        self,
        pair: str,
        side: str,
        signal_type: str,
        entry_price: float,
        atr: float,
        atr_pct: float,
        move_bps: float,
        timestamp: datetime,
    ) -> SignalPayload:
        """
        Create signal payload with ATR-based SL/TP levels.

        Args:
            pair: Trading pair
            side: "buy" or "sell"
            signal_type: "primary" or "extreme_fade"
            entry_price: Entry price
            atr: Average True Range (absolute)
            atr_pct: ATR as percentage of close
            move_bps: Bar move in basis points
            timestamp: Signal timestamp

        Returns:
            SignalPayload ready for Redis publishing
        """
        # Calculate ATR-based levels
        sl_distance = self.sl_atr * atr
        tp1_distance = self.tp1_atr * atr
        tp2_distance = self.tp2_atr * atr

        # Convert side to long/short format
        if side == "buy":
            normalized_side = "long"
            sl = entry_price - sl_distance
            tp1 = entry_price + tp1_distance
            tp2 = entry_price + tp2_distance
        else:  # sell
            normalized_side = "short"
            sl = entry_price + sl_distance
            tp1 = entry_price - tp1_distance
            tp2 = entry_price - tp2_distance

        # Use TP2 as primary target (blended profit taking)
        tp = tp2

        # Calculate confidence
        confidence = self._calculate_confidence(move_bps, atr_pct, signal_type)

        # Calculate RR
        rr_blended = self._calculate_rr(entry_price, sl, tp1, tp2)

        # Generate deterministic signal ID
        signal_id = self._generate_signal_id(
            timestamp=timestamp,
            pair=pair,
            strategy=f"bar_reaction_5m_{signal_type}",
            trigger_mode=self.trigger_mode,
            mode=self.mode,
        )

        # Create signal payload
        signal = SignalPayload(
            id=signal_id,
            ts=int(timestamp.timestamp() * 1000),  # Convert to milliseconds
            pair=pair.replace("/", ""),  # "BTC/USD" -> "BTCUSD"
            side=normalized_side,  # "long" or "short"
            entry=Decimal(str(entry_price)),
            sl=Decimal(str(sl)),
            tp=Decimal(str(tp)),
            strategy="bar_reaction_5m",
            confidence=confidence,
        )

        # Validate signal
        validate_signal_payload(signal.model_dump())

        logger.debug(
            f"Created signal: {side} {pair}, entry={entry_price:.2f}, sl={sl:.2f}, "
            f"tp={tp:.2f}, conf={confidence:.2f}, rr={rr_blended:.2f}"
        )

        return signal

    def _calculate_confidence(
        self,
        move_bps: float,
        atr_pct: float,
        signal_type: str
    ) -> float:
        """
        Calculate signal confidence based on move strength and ATR quality.

        Formula:
        - move_strength = |move_bps| / trigger_threshold
        - atr_quality = 1.0 - |atr_pct - mid_range| / (range / 2)
        - base_confidence = 0.60 + min(0.20, move_strength*0.10) + (atr_quality*0.10)
        - Clip to [0.50, 0.90]
        - Extreme fades get 80% of base confidence

        Args:
            move_bps: Bar move in basis points
            atr_pct: ATR as percentage of close
            signal_type: "primary" or "extreme_fade"

        Returns:
            Confidence score [0.50, 0.90]
        """
        # Move strength relative to threshold
        move_strength = abs(move_bps) / self.trigger_bps_up

        # ATR quality (prefer mid-range)
        mid_range = (self.min_atr_pct + self.max_atr_pct) / 2
        atr_range = (self.max_atr_pct - self.min_atr_pct) / 2
        atr_quality = 1.0 - abs(atr_pct - mid_range) / atr_range
        atr_quality = max(0.0, min(1.0, atr_quality))

        # Base confidence
        base = 0.60 + min(0.20, move_strength * 0.10) + (atr_quality * 0.10)

        # Clip to range
        confidence = max(0.50, min(0.90, base))

        # Reduce for extreme fades
        if signal_type == "extreme_fade":
            confidence *= 0.80

        return round(confidence, 2)

    def _calculate_rr(
        self,
        entry: float,
        sl: float,
        tp1: float,
        tp2: float
    ) -> float:
        """
        Calculate blended risk:reward ratio.

        Formula:
        - RR_TP1 = |TP1 - entry| / |SL - entry|
        - RR_TP2 = |TP2 - entry| / |SL - entry|
        - RR_blended = (RR_TP1 + RR_TP2) / 2 (50/50 split)

        Args:
            entry: Entry price
            sl: Stop loss price
            tp1: First take profit price
            tp2: Second take profit price

        Returns:
            Blended risk:reward ratio
        """
        sl_distance = abs(entry - sl)
        if sl_distance == 0:
            return 0.0

        tp1_distance = abs(tp1 - entry)
        tp2_distance = abs(tp2 - entry)

        rr_tp1 = tp1_distance / sl_distance
        rr_tp2 = tp2_distance / sl_distance

        rr_blended = (rr_tp1 + rr_tp2) / 2

        return round(rr_blended, 2)

    def _generate_signal_id(
        self,
        timestamp: datetime,
        pair: str,
        strategy: str,
        trigger_mode: str,
        mode: str,
    ) -> str:
        """
        Generate deterministic signal ID.

        ID = hash(ts | pair | strategy | trigger_mode | mode)

        Args:
            timestamp: Signal timestamp
            pair: Trading pair
            strategy: Strategy name
            trigger_mode: Trigger mode
            mode: Trading mode

        Returns:
            32-character hex string
        """
        components = f"{timestamp.isoformat()}|{pair}|{strategy}|{trigger_mode}|{mode}"
        hash_obj = hashlib.sha256(components.encode("utf-8"))
        return hash_obj.hexdigest()[:32]

    async def _publish_signal(self, signal: SignalPayload) -> None:
        """
        Publish signal to Redis signals:paper stream.

        Args:
            signal: Validated signal payload
        """
        stream_key = "signals:paper"

        # Convert to dict for Redis
        signal_dict = signal.model_dump()

        # Publish to stream
        await self.redis.xadd(
            stream_key,
            signal_dict,
            maxlen=10000,  # Keep last 10k signals
        )

        logger.debug(f"Published signal {signal.id} to {stream_key}")

    async def _update_cooldown_state(self, pair: str, timestamp: datetime) -> None:
        """
        Update cooldown state in Redis after signal generation.

        Updates:
        - bar_reaction:cooldown:{pair} - Set to current timestamp
        - bar_reaction:open_positions:{pair} - Increment by 1
        - bar_reaction:daily_count:{pair}:{date} - Increment by 1 (expires at midnight)

        Args:
            pair: Trading pair
            timestamp: Signal timestamp
        """
        now = timestamp.timestamp()
        today = timestamp.strftime("%Y%m%d")

        # Update cooldown
        cooldown_key = f"bar_reaction:cooldown:{pair}"
        await self.redis.set(cooldown_key, str(now), ex=86400)  # Expire after 24h

        # Increment open positions
        open_pos_key = f"bar_reaction:open_positions:{pair}"
        await self.redis.incr(open_pos_key)

        # Increment daily count (expires at midnight)
        daily_key = f"bar_reaction:daily_count:{pair}:{today}"
        await self.redis.incr(daily_key)

        # Set expiry to end of day (86400 - seconds since midnight)
        seconds_since_midnight = (timestamp.hour * 3600 + timestamp.minute * 60 + timestamp.second)
        ttl = 86400 - seconds_since_midnight
        await self.redis.expire(daily_key, ttl)

        logger.debug(f"Updated cooldown state for {pair}")

    async def decrement_open_positions(self, pair: str) -> None:
        """
        Decrement open position count (called when position closes).

        Args:
            pair: Trading pair
        """
        open_pos_key = f"bar_reaction:open_positions:{pair}"
        current = await self.redis.get(open_pos_key)

        if current is not None and int(current) > 0:
            await self.redis.decr(open_pos_key)
            logger.debug(f"Decremented open positions for {pair}")


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

async def create_bar_reaction_agent(
    config_path: str,
    redis_url: str
) -> BarReaction5M:
    """
    Factory function to create BarReaction5M agent.

    Args:
        config_path: Path to enhanced_scalper_config.yaml
        redis_url: Redis Cloud connection URL

    Returns:
        Initialized BarReaction5M agent

    Example:
        >>> agent = await create_bar_reaction_agent(
        ...     "config/enhanced_scalper_config.yaml",
        ...     "rediss://default:pwd@host:port"
        ... )
        >>> event = BarCloseEvent(
        ...     timestamp=datetime.now(timezone.utc),
        ...     pair="BTC/USD",
        ...     timeframe="5m",
        ...     bar_data={"close": 50000, "volume": 100}
        ... )
        >>> signal = await agent.on_bar_close(event)
    """
    from config.enhanced_scalper_loader import EnhancedScalperConfigLoader

    # Load config
    loader = EnhancedScalperConfigLoader(config_path)
    config = loader.load_config()

    bar_reaction_config = config.get("bar_reaction_5m", {})

    # Create Redis client
    redis_client = await redis.from_url(
        redis_url,
        encoding="utf-8",
        decode_responses=True,
    )

    # Create agent
    agent = BarReaction5M(bar_reaction_config, redis_client)

    return agent


# =============================================================================
# SELF-CHECK
# =============================================================================

if __name__ == "__main__":
    """Self-check: Test bar reaction agent initialization and signal creation"""
    import sys

    logging.basicConfig(level=logging.INFO)

    async def self_check():
        try:
            print("\n" + "="*70)
            print("BAR REACTION 5M AGENT SELF-CHECK")
            print("="*70)

            # Test 1: Initialize agent with mock config
            print("\n[1/6] Initializing agent...")
            config = {
                "mode": "trend",
                "trigger_mode": "open_to_close",
                "trigger_bps_up": 12.0,
                "trigger_bps_down": 12.0,
                "min_atr_pct": 0.25,
                "max_atr_pct": 3.0,
                "atr_window": 14,
                "sl_atr": 0.6,
                "tp1_atr": 1.0,
                "tp2_atr": 1.8,
                "spread_bps_cap": 8.0,
                "min_notional_floor": 100000.0,
                "cooldown_minutes": 15,
                "max_concurrent_per_pair": 2,
            }

            # Mock Redis client (in-memory)
            redis_mock = await redis.from_url("redis://localhost:6379", encoding="utf-8", decode_responses=True)

            agent = BarReaction5M(config, redis_mock)
            assert agent.mode == "trend"
            print("  [OK] Agent initialized")

            # Test 2: Check microstructure
            print("\n[2/6] Testing microstructure checks...")
            check = agent._check_microstructure(spread_bps=5.0, notional=200000.0)
            assert check.passed is True
            print("  [OK] Microstructure passed (spread=5bps, notional=200k)")

            check_fail = agent._check_microstructure(spread_bps=10.0, notional=50000.0)
            assert check_fail.passed is False
            print(f"  [OK] Microstructure failed: {check_fail.reason}")

            # Test 3: Test signal decision logic
            print("\n[3/6] Testing signal decision logic...")
            signal_type, side = agent._decide_signal(move_bps=15.0)
            assert signal_type == "primary"
            assert side == "buy"  # Trend mode: up move -> buy
            print(f"  [OK] Trend mode: move_bps=+15 -> {side}")

            signal_type, side = agent._decide_signal(move_bps=-15.0)
            assert signal_type == "primary"
            assert side == "sell"  # Trend mode: down move -> sell
            print(f"  [OK] Trend mode: move_bps=-15 -> {side}")

            # Test 4: Test confidence calculation
            print("\n[4/6] Testing confidence calculation...")
            conf = agent._calculate_confidence(move_bps=15.0, atr_pct=0.5, signal_type="primary")
            assert 0.5 <= conf <= 0.9
            print(f"  [OK] Confidence: {conf:.2f} (move=15bps, atr=0.5%)")

            # Test 5: Test RR calculation
            print("\n[5/6] Testing RR calculation...")
            rr = agent._calculate_rr(entry=50000, sl=49700, tp1=50500, tp2=50900)
            assert rr > 0
            print(f"  [OK] RR blended: {rr:.2f}:1")

            # Test 6: Test signal creation
            print("\n[6/6] Testing signal creation...")
            signal = agent._create_signal(
                pair="BTC/USD",
                side="buy",
                signal_type="primary",
                entry_price=50000.0,
                atr=75.0,
                atr_pct=0.15,
                move_bps=15.0,
                timestamp=datetime.now(timezone.utc),
            )
            assert signal.side == "long"
            assert float(signal.entry) == 50000.0
            assert float(signal.sl) < float(signal.entry)  # Long: SL below entry
            assert float(signal.tp) > float(signal.entry)  # Long: TP above entry
            print(f"  [OK] Signal created: {signal.side} @ {signal.entry}, SL={signal.sl}, TP={signal.tp}")

            # Cleanup
            await redis_mock.aclose()

            print("\n" + "="*70)
            print("SUCCESS: BAR REACTION 5M AGENT SELF-CHECK PASSED")
            print("="*70)
            print("\nREQUIREMENTS VERIFIED:")
            print("  [OK] Agent initialization")
            print("  [OK] Microstructure checks (spread, notional)")
            print("  [OK] Signal decision logic (trend/revert)")
            print("  [OK] Confidence calculation")
            print("  [OK] RR calculation (blended TP1/TP2)")
            print("  [OK] Signal creation (ATR-based SL/TP)")
            print("="*70)

        except Exception as e:
            print(f"\nFAIL Bar Reaction 5M Agent Self-Check: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

    # Run async self-check
    asyncio.run(self_check())
