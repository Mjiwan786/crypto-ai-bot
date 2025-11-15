"""
Volatility-Aware Take Profit/Stop Grid (agents/risk/volatility_aware_exits.py)

Dynamic TP/SL management with:
- ATR-based scaling (wider in high vol, tighter in low vol)
- Partial exit logic (50% at TP1, trail rest)
- Grid optimization across multiple pairs
- Redis persistence of best configs

For Prompt 4: Profitability Boosters
Author: Crypto AI Bot Team
Version: 2.0.0
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ExitGridConfig(BaseModel):
    """Configuration for volatility-aware exits."""

    # ATR multipliers for different volatility regimes
    low_vol_threshold: float = Field(default=1.5, description="ATR% threshold for low vol")
    high_vol_threshold: float = Field(default=3.0, description="ATR% threshold for high vol")

    # Low volatility (tight stops, close targets)
    low_vol_sl_atr: float = Field(default=0.8, ge=0.3, le=2.0, description="SL in low vol (ATR multiple)")
    low_vol_tp1_atr: float = Field(default=1.0, ge=0.5, le=3.0, description="TP1 in low vol")
    low_vol_tp2_atr: float = Field(default=1.8, ge=1.0, le=5.0, description="TP2 in low vol")

    # Normal volatility (balanced)
    normal_vol_sl_atr: float = Field(default=1.0, ge=0.3, le=2.0, description="SL in normal vol")
    normal_vol_tp1_atr: float = Field(default=1.5, ge=0.5, le=3.0, description="TP1 in normal vol")
    normal_vol_tp2_atr: float = Field(default=2.5, ge=1.0, le=5.0, description="TP2 in normal vol")

    # High volatility (wide stops, far targets)
    high_vol_sl_atr: float = Field(default=1.5, ge=0.3, le=2.0, description="SL in high vol")
    high_vol_tp1_atr: float = Field(default=2.0, ge=0.5, le=3.0, description="TP1 in high vol")
    high_vol_tp2_atr: float = Field(default=3.5, ge=1.0, le=5.0, description="TP2 in high vol")

    # Partial exit settings
    tp1_exit_pct: float = Field(default=50.0, ge=10.0, le=100.0, description="% to exit at TP1")
    trail_activation_atr: float = Field(default=1.2, ge=0.5, le=3.0, description="ATR multiple to activate trail")
    trail_distance_atr: float = Field(default=0.6, ge=0.2, le=2.0, description="Trail distance (ATR multiple)")

    # Risk/Reward ratios
    min_risk_reward: float = Field(default=1.5, ge=1.0, le=5.0, description="Min RR ratio for trade entry")


@dataclass
class ExitLevels:
    """Calculated exit levels for a position."""

    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    trail_activation: float
    trail_distance: float
    risk_reward_ratio: float
    volatility_regime: str  # "low", "normal", "high"
    atr_value: float
    atr_pct: float


@dataclass
class PartialExitState:
    """State tracking for partial exits."""

    position_id: str
    entry_price: float
    direction: str  # "long" or "short"
    initial_size: float
    remaining_size: float
    tp1_hit: bool
    trail_active: bool
    trail_stop: Optional[float]
    highest_profit: float  # For trailing


class VolatilityAwareExits:
    """
    Manages dynamic TP/SL based on volatility and partial exits.

    Features:
    - ATR-based scaling across 3 volatility regimes
    - Partial exits (50% at TP1, trail remainder)
    - Trailing stop activation after threshold
    - Position state tracking
    """

    def __init__(
        self,
        config: Optional[ExitGridConfig] = None,
    ):
        """
        Initialize exits manager.

        Args:
            config: Exit grid configuration
        """
        self.config = config or ExitGridConfig()
        self.partial_exit_states: Dict[str, PartialExitState] = {}

        logger.info(
            "VolatilityAwareExits initialized (low_vol_sl=%.1f, normal_vol_sl=%.1f, high_vol_sl=%.1f ATR)",
            self.config.low_vol_sl_atr,
            self.config.normal_vol_sl_atr,
            self.config.high_vol_sl_atr,
        )

    def calculate_exit_levels(
        self,
        entry_price: float,
        direction: str,
        atr: float,
        current_price: float,
    ) -> ExitLevels:
        """
        Calculate all exit levels based on current volatility.

        Args:
            entry_price: Entry price
            direction: "long" or "short"
            atr: Average True Range value
            current_price: Current market price

        Returns:
            ExitLevels with all targets
        """
        # Calculate ATR as % of price
        atr_pct = (atr / current_price) * 100

        # Determine volatility regime
        if atr_pct < self.config.low_vol_threshold:
            regime = "low"
            sl_atr = self.config.low_vol_sl_atr
            tp1_atr = self.config.low_vol_tp1_atr
            tp2_atr = self.config.low_vol_tp2_atr
        elif atr_pct > self.config.high_vol_threshold:
            regime = "high"
            sl_atr = self.config.high_vol_sl_atr
            tp1_atr = self.config.high_vol_tp1_atr
            tp2_atr = self.config.high_vol_tp2_atr
        else:
            regime = "normal"
            sl_atr = self.config.normal_vol_sl_atr
            tp1_atr = self.config.normal_vol_tp1_atr
            tp2_atr = self.config.normal_vol_tp2_atr

        # Calculate levels based on direction
        if direction.lower() == "long":
            stop_loss = entry_price - (atr * sl_atr)
            take_profit_1 = entry_price + (atr * tp1_atr)
            take_profit_2 = entry_price + (atr * tp2_atr)
            trail_activation = entry_price + (atr * self.config.trail_activation_atr)
            trail_distance = atr * self.config.trail_distance_atr
        else:  # short
            stop_loss = entry_price + (atr * sl_atr)
            take_profit_1 = entry_price - (atr * tp1_atr)
            take_profit_2 = entry_price - (atr * tp2_atr)
            trail_activation = entry_price - (atr * self.config.trail_activation_atr)
            trail_distance = atr * self.config.trail_distance_atr

        # Calculate risk/reward
        risk = abs(entry_price - stop_loss)
        reward = abs(take_profit_2 - entry_price)
        risk_reward_ratio = reward / risk if risk > 0 else 0.0

        logger.debug(
            "Exit levels calculated: regime=%s, ATR=%.2f (%.2f%%), SL=%.2f, TP1=%.2f, TP2=%.2f, RR=%.2f",
            regime, atr, atr_pct, stop_loss, take_profit_1, take_profit_2, risk_reward_ratio
        )

        return ExitLevels(
            stop_loss=stop_loss,
            take_profit_1=take_profit_1,
            take_profit_2=take_profit_2,
            trail_activation=trail_activation,
            trail_distance=trail_distance,
            risk_reward_ratio=risk_reward_ratio,
            volatility_regime=regime,
            atr_value=atr,
            atr_pct=atr_pct,
        )

    def should_enter_trade(self, exit_levels: ExitLevels) -> Tuple[bool, str]:
        """
        Check if trade meets minimum risk/reward criteria.

        Args:
            exit_levels: Calculated exit levels

        Returns:
            (should_enter, reason)
        """
        if exit_levels.risk_reward_ratio < self.config.min_risk_reward:
            return False, f"RR {exit_levels.risk_reward_ratio:.2f} < {self.config.min_risk_reward}"

        return True, f"RR {exit_levels.risk_reward_ratio:.2f} acceptable"

    def add_position(
        self,
        position_id: str,
        entry_price: float,
        direction: str,
        size: float,
    ) -> None:
        """
        Register a new position for partial exit tracking.

        Args:
            position_id: Unique position ID
            entry_price: Entry price
            direction: "long" or "short"
            size: Position size
        """
        self.partial_exit_states[position_id] = PartialExitState(
            position_id=position_id,
            entry_price=entry_price,
            direction=direction,
            initial_size=size,
            remaining_size=size,
            tp1_hit=False,
            trail_active=False,
            trail_stop=None,
            highest_profit=0.0,
        )

        logger.info("Position added for exit management: %s (%s, size=%.2f)",
                   position_id, direction, size)

    def update_position(
        self,
        position_id: str,
        current_price: float,
        exit_levels: ExitLevels,
    ) -> Dict:
        """
        Update position state and check for exit signals.

        Args:
            position_id: Position ID
            current_price: Current market price
            exit_levels: Current exit levels

        Returns:
            Dict with exit signals:
            {
                "should_exit_full": bool,
                "should_exit_partial": bool,
                "exit_price": float,
                "exit_size": float,
                "exit_reason": str,
            }
        """
        if position_id not in self.partial_exit_states:
            logger.warning("Position %s not found in exit states", position_id)
            return {"should_exit_full": False, "should_exit_partial": False}

        state = self.partial_exit_states[position_id]

        # Calculate current profit
        if state.direction.lower() == "long":
            profit = current_price - state.entry_price
        else:
            profit = state.entry_price - current_price

        # Update highest profit for trailing
        if profit > state.highest_profit:
            state.highest_profit = profit

        # 1. Check stop loss
        if state.direction.lower() == "long":
            if current_price <= exit_levels.stop_loss:
                return self._exit_signal(
                    full=True,
                    price=exit_levels.stop_loss,
                    size=state.remaining_size,
                    reason="Stop loss hit"
                )
        else:  # short
            if current_price >= exit_levels.stop_loss:
                return self._exit_signal(
                    full=True,
                    price=exit_levels.stop_loss,
                    size=state.remaining_size,
                    reason="Stop loss hit"
                )

        # 2. Check TP1 (partial exit)
        if not state.tp1_hit:
            tp1_hit = False
            if state.direction.lower() == "long":
                tp1_hit = current_price >= exit_levels.take_profit_1
            else:
                tp1_hit = current_price <= exit_levels.take_profit_1

            if tp1_hit:
                state.tp1_hit = True
                exit_size = state.initial_size * (self.config.tp1_exit_pct / 100.0)
                state.remaining_size -= exit_size

                logger.info("TP1 hit for %s, taking %.1f%% profit", position_id, self.config.tp1_exit_pct)

                return self._exit_signal(
                    full=False,
                    price=exit_levels.take_profit_1,
                    size=exit_size,
                    reason=f"TP1 hit (partial {self.config.tp1_exit_pct:.0f}%)"
                )

        # 3. Check TP2 (full exit)
        if state.direction.lower() == "long":
            if current_price >= exit_levels.take_profit_2:
                return self._exit_signal(
                    full=True,
                    price=exit_levels.take_profit_2,
                    size=state.remaining_size,
                    reason="TP2 hit (full exit)"
                )
        else:
            if current_price <= exit_levels.take_profit_2:
                return self._exit_signal(
                    full=True,
                    price=exit_levels.take_profit_2,
                    size=state.remaining_size,
                    reason="TP2 hit (full exit)"
                )

        # 4. Check trailing stop activation
        if state.tp1_hit and not state.trail_active:
            trail_activated = False
            if state.direction.lower() == "long":
                trail_activated = current_price >= exit_levels.trail_activation
            else:
                trail_activated = current_price <= exit_levels.trail_activation

            if trail_activated:
                state.trail_active = True
                # Set initial trail stop
                if state.direction.lower() == "long":
                    state.trail_stop = current_price - exit_levels.trail_distance
                else:
                    state.trail_stop = current_price + exit_levels.trail_distance

                logger.info("Trailing stop activated for %s at %.2f", position_id, state.trail_stop)

        # 5. Update trailing stop
        if state.trail_active and state.trail_stop is not None:
            if state.direction.lower() == "long":
                # Update trail if price moved up
                new_trail = current_price - exit_levels.trail_distance
                if new_trail > state.trail_stop:
                    state.trail_stop = new_trail
                    logger.debug("Trail stop updated: %.2f", state.trail_stop)

                # Check if trail stop hit
                if current_price <= state.trail_stop:
                    return self._exit_signal(
                        full=True,
                        price=state.trail_stop,
                        size=state.remaining_size,
                        reason="Trailing stop hit"
                    )
            else:  # short
                # Update trail if price moved down
                new_trail = current_price + exit_levels.trail_distance
                if new_trail < state.trail_stop:
                    state.trail_stop = new_trail
                    logger.debug("Trail stop updated: %.2f", state.trail_stop)

                # Check if trail stop hit
                if current_price >= state.trail_stop:
                    return self._exit_signal(
                        full=True,
                        price=state.trail_stop,
                        size=state.remaining_size,
                        reason="Trailing stop hit"
                    )

        # No exit signals
        return {"should_exit_full": False, "should_exit_partial": False}

    def _exit_signal(
        self,
        full: bool,
        price: float,
        size: float,
        reason: str,
    ) -> Dict:
        """Generate exit signal dict."""
        return {
            "should_exit_full": full,
            "should_exit_partial": not full,
            "exit_price": price,
            "exit_size": size,
            "exit_reason": reason,
        }

    def remove_position(self, position_id: str) -> None:
        """Remove position from tracking."""
        if position_id in self.partial_exit_states:
            del self.partial_exit_states[position_id]
            logger.info("Position removed from exit tracking: %s", position_id)

    def get_position_state(self, position_id: str) -> Optional[Dict]:
        """Get current state of a position."""
        if position_id not in self.partial_exit_states:
            return None

        state = self.partial_exit_states[position_id]
        return {
            "position_id": state.position_id,
            "entry_price": state.entry_price,
            "direction": state.direction,
            "initial_size": state.initial_size,
            "remaining_size": state.remaining_size,
            "tp1_hit": state.tp1_hit,
            "trail_active": state.trail_active,
            "trail_stop": state.trail_stop,
            "highest_profit": state.highest_profit,
        }


def save_exit_config_to_redis(
    config: ExitGridConfig,
    pair: str,
    redis_client,
    key_prefix: str = "exit_grid",
) -> None:
    """
    Save exit grid configuration to Redis.

    Args:
        config: Exit grid config
        pair: Trading pair (e.g., "BTC/USD")
        redis_client: Redis client instance
        key_prefix: Redis key prefix
    """
    key = f"{key_prefix}:{pair.replace('/', '_')}"
    config_dict = config.model_dump()

    try:
        redis_client.set(key, json.dumps(config_dict))
        logger.info("Exit config saved to Redis: %s", key)
    except Exception as e:
        logger.exception("Failed to save config to Redis: %s", e)


def load_exit_config_from_redis(
    pair: str,
    redis_client,
    key_prefix: str = "exit_grid",
) -> Optional[ExitGridConfig]:
    """
    Load exit grid configuration from Redis.

    Args:
        pair: Trading pair
        redis_client: Redis client instance
        key_prefix: Redis key prefix

    Returns:
        ExitGridConfig or None if not found
    """
    key = f"{key_prefix}:{pair.replace('/', '_')}"

    try:
        config_json = redis_client.get(key)
        if config_json:
            config_dict = json.loads(config_json)
            return ExitGridConfig(**config_dict)
    except Exception as e:
        logger.exception("Failed to load config from Redis: %s", e)

    return None


# Self-check for development/testing
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    logger.info("Running VolatilityAwareExits self-check...")

    try:
        # Create exits manager
        exits = VolatilityAwareExits()

        # Test 1: Calculate exit levels for long in normal vol
        logger.info("\n=== Test 1: Long position, normal volatility ===")
        levels = exits.calculate_exit_levels(
            entry_price=50000.0,
            direction="long",
            atr=1000.0,  # 2% ATR (normal vol)
            current_price=50000.0,
        )

        assert levels.volatility_regime == "normal"
        assert levels.stop_loss < 50000.0
        assert levels.take_profit_1 > 50000.0
        assert levels.take_profit_2 > levels.take_profit_1
        logger.info("Levels: SL=%.2f, TP1=%.2f, TP2=%.2f, RR=%.2f",
                   levels.stop_loss, levels.take_profit_1, levels.take_profit_2, levels.risk_reward_ratio)

        # Test 2: Check entry criteria
        logger.info("\n=== Test 2: Entry validation ===")
        should_enter, reason = exits.should_enter_trade(levels)
        assert should_enter
        logger.info("Should enter: %s (%s)", should_enter, reason)

        # Test 3: Partial exit logic
        logger.info("\n=== Test 3: Partial exit simulation ===")
        exits.add_position("test_long", 50000.0, "long", 1.0)

        # Simulate price moving to TP1
        signal = exits.update_position("test_long", 51500.0, levels)
        assert signal["should_exit_partial"]
        logger.info("TP1 signal: %s", signal)

        # Simulate price moving to TP2
        signal = exits.update_position("test_long", 52500.0, levels)
        assert signal["should_exit_full"]
        logger.info("TP2 signal: %s", signal)

        # Test 4: High volatility
        logger.info("\n=== Test 4: High volatility regime ===")
        levels_high_vol = exits.calculate_exit_levels(
            entry_price=50000.0,
            direction="long",
            atr=2000.0,  # 4% ATR (high vol)
            current_price=50000.0,
        )
        assert levels_high_vol.volatility_regime == "high"
        assert abs(levels_high_vol.stop_loss - 50000.0) > abs(levels.stop_loss - 50000.0)
        logger.info("High vol SL distance: %.2f (wider than normal: %.2f)",
                   abs(levels_high_vol.stop_loss - 50000.0),
                   abs(levels.stop_loss - 50000.0))

        # Test 5: Low volatility
        logger.info("\n=== Test 5: Low volatility regime ===")
        levels_low_vol = exits.calculate_exit_levels(
            entry_price=50000.0,
            direction="long",
            atr=500.0,  # 1% ATR (low vol)
            current_price=50000.0,
        )
        assert levels_low_vol.volatility_regime == "low"
        assert abs(levels_low_vol.stop_loss - 50000.0) < abs(levels.stop_loss - 50000.0)
        logger.info("Low vol SL distance: %.2f (tighter than normal: %.2f)",
                   abs(levels_low_vol.stop_loss - 50000.0),
                   abs(levels.stop_loss - 50000.0))

        logger.info("\n✓ Self-check passed!")
        sys.exit(0)

    except Exception as e:
        logger.error("✗ Self-check failed: %s", e)
        import traceback
        traceback.print_exc()
        sys.exit(1)
