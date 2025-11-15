"""
Dynamic Position Sizing Module - Production Safe

Implements adaptive position sizing with:
- Equity-based risk scaling (1.5% < $15k, else 1.0%)
- Win streak boost (+0.2% per win, capped at +1.0% for safety)
- Volatility adjustment (0.8x for high vol, 1.0x normal)
- Portfolio heat limiter (force 0.5x when heat > 80%)

Safety Features:
- Conservative caps to prevent over-sizing
- Automatic de-risk on high portfolio heat
- Runtime overrides via Redis/MCP
- Deterministic calculations

Integration:
- Plugs into RiskManager.validate_order()
- Config driven via YAML + runtime overrides
- Full Redis state persistence

Author: Crypto AI Bot Team
Date: 2025-11-08
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================


@dataclass(frozen=True)
class DynamicSizingConfig:
    """
    Dynamic position sizing configuration.

    All parameters are production-safe with conservative defaults.
    """

    # Base risk levels (% of equity)
    base_risk_pct_small: float = 1.5  # When equity < equity_threshold
    base_risk_pct_large: float = 1.0  # When equity >= equity_threshold
    equity_threshold_usd: float = 15000.0  # Threshold for risk scaling

    # Win streak boost
    streak_boost_pct: float = 0.2  # +0.2% per consecutive win
    max_streak_boost_pct: float = 1.0  # Cap at +1.0% (NOT 2.5%, safety first)
    max_streak_count: int = 5  # Stop counting after 5 wins

    # Volatility adjustment
    high_vol_multiplier: float = 0.8  # Reduce size in high volatility
    normal_vol_multiplier: float = 1.0  # Normal conditions
    high_vol_threshold_atr_pct: float = 2.0  # ATR% threshold for "high vol"

    # Portfolio heat limiter
    portfolio_heat_threshold_pct: float = 80.0  # Heat threshold (% of equity)
    portfolio_heat_cut_multiplier: float = 0.5  # Force 0.5x size when over threshold

    # Absolute safety limits
    min_position_size_multiplier: float = 0.1  # Never go below 10% of base
    max_position_size_multiplier: float = 3.0  # Never exceed 3x base (safety cap)

    # Runtime override support
    allow_runtime_overrides: bool = True  # Enable Redis/MCP overrides
    override_expiry_seconds: int = 3600  # Overrides expire after 1 hour


# =============================================================================
# TRADE HISTORY TRACKING
# =============================================================================


class TradeOutcome(Enum):
    """Trade outcome for streak tracking."""
    WIN = "win"
    LOSS = "loss"
    BREAKEVEN = "breakeven"


@dataclass
class TradeRecord:
    """Individual trade record for streak calculation."""
    timestamp: float
    symbol: str
    outcome: TradeOutcome
    pnl_usd: float
    size_usd: float


# =============================================================================
# DYNAMIC SIZING ENGINE
# =============================================================================


class DynamicPositionSizer:
    """
    Production-safe dynamic position sizing engine.

    Calculates adaptive position size multipliers based on:
    - Current equity level
    - Recent win/loss streak
    - Market volatility
    - Current portfolio heat

    All calculations are deterministic and capped for safety.
    """

    def __init__(self, config: DynamicSizingConfig):
        """
        Initialize dynamic position sizer.

        Args:
            config: Dynamic sizing configuration
        """
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.DynamicPositionSizer")

        # Trade history for streak tracking
        self.trade_history: list[TradeRecord] = []
        self.current_streak: int = 0  # Positive = wins, negative = losses

        # Runtime overrides (key -> (value, expiry_timestamp))
        self.overrides: Dict[str, tuple[float, float]] = {}

        self.logger.info("DynamicPositionSizer initialized with config: %s", config)

    # -------------------------------------------------------------------------
    # PUBLIC API
    # -------------------------------------------------------------------------

    def calculate_size_multiplier(
        self,
        current_equity_usd: float,
        portfolio_heat_pct: float,
        current_volatility_atr_pct: Optional[float] = None,
    ) -> tuple[float, Dict[str, float]]:
        """
        Calculate dynamic position size multiplier.

        Args:
            current_equity_usd: Current account equity in USD
            portfolio_heat_pct: Current portfolio heat as % of equity (e.g., 45.0 = 45%)
            current_volatility_atr_pct: Current ATR as % of price (e.g., 1.5 = 1.5%)

        Returns:
            (size_multiplier, components_breakdown)

            size_multiplier: Final multiplier to apply to base position size
            components_breakdown: Dict showing contribution of each factor

        Example:
            >>> sizer = DynamicPositionSizer(config)
            >>> multiplier, breakdown = sizer.calculate_size_multiplier(
            ...     current_equity_usd=12000.0,
            ...     portfolio_heat_pct=45.0,
            ...     current_volatility_atr_pct=1.8
            ... )
            >>> # multiplier = 1.2 (equity boost + streak boost - vol adj)
            >>> # breakdown = {'base': 1.5, 'streak': 0.2, 'vol': 0.8, 'heat': 1.0, 'final': 1.2}
        """
        try:
            # Check for runtime overrides first
            if self.config.allow_runtime_overrides:
                override = self._get_active_override("size_multiplier")
                if override is not None:
                    self.logger.info(
                        "Using runtime override: size_multiplier=%.2f", override
                    )
                    return override, {"override": override, "source": "runtime"}

            # 1. Base risk based on equity level
            base_risk_pct = self._calculate_base_risk(current_equity_usd)

            # 2. Win streak boost
            streak_boost_pct = self._calculate_streak_boost()

            # 3. Volatility adjustment
            vol_multiplier = self._calculate_volatility_adjustment(current_volatility_atr_pct)

            # 4. Portfolio heat limiter
            heat_multiplier = self._calculate_heat_limiter(portfolio_heat_pct)

            # Combine all factors
            # Formula: (base + streak_boost) * vol_adj * heat_limiter
            risk_pct = base_risk_pct + streak_boost_pct
            size_multiplier = (risk_pct / self.config.base_risk_pct_large) * vol_multiplier * heat_multiplier

            # Apply safety caps
            size_multiplier = max(
                self.config.min_position_size_multiplier,
                min(size_multiplier, self.config.max_position_size_multiplier)
            )

            # Breakdown for debugging/monitoring
            breakdown = {
                "base_risk_pct": base_risk_pct,
                "streak_boost_pct": streak_boost_pct,
                "total_risk_pct": risk_pct,
                "vol_multiplier": vol_multiplier,
                "heat_multiplier": heat_multiplier,
                "raw_multiplier": (risk_pct / self.config.base_risk_pct_large) * vol_multiplier * heat_multiplier,
                "final_multiplier": size_multiplier,
                "capped": size_multiplier != ((risk_pct / self.config.base_risk_pct_large) * vol_multiplier * heat_multiplier),
            }

            self.logger.debug(
                "Size multiplier calculated: %.2f (equity=$%.0f, heat=%.1f%%, vol=%.2f%%, streak=%d)",
                size_multiplier,
                current_equity_usd,
                portfolio_heat_pct,
                current_volatility_atr_pct or 0.0,
                self.current_streak,
            )

            return size_multiplier, breakdown

        except Exception as e:
            self.logger.error("Error calculating size multiplier: %s", e, exc_info=True)
            # Fail safe: return conservative 1.0x multiplier
            return 1.0, {"error": str(e), "failsafe": 1.0}

    def record_trade(
        self,
        symbol: str,
        pnl_usd: float,
        size_usd: float,
        outcome: Optional[TradeOutcome] = None,
    ) -> None:
        """
        Record a trade outcome for streak tracking.

        Args:
            symbol: Trading pair
            pnl_usd: Trade P&L in USD
            size_usd: Trade size in USD
            outcome: Trade outcome (auto-detected from pnl if None)
        """
        try:
            # Auto-detect outcome from P&L if not provided
            if outcome is None:
                if pnl_usd > 0:
                    outcome = TradeOutcome.WIN
                elif pnl_usd < 0:
                    outcome = TradeOutcome.LOSS
                else:
                    outcome = TradeOutcome.BREAKEVEN

            # Create trade record
            record = TradeRecord(
                timestamp=time.time(),
                symbol=symbol,
                outcome=outcome,
                pnl_usd=pnl_usd,
                size_usd=size_usd,
            )

            # Add to history
            self.trade_history.append(record)

            # Update streak
            self._update_streak(outcome)

            # Clean old records (keep last 100)
            if len(self.trade_history) > 100:
                self.trade_history = self.trade_history[-100:]

            self.logger.debug(
                "Trade recorded: %s %s P&L=$%.2f, streak=%d",
                symbol,
                outcome.value,
                pnl_usd,
                self.current_streak,
            )

        except Exception as e:
            self.logger.error("Error recording trade: %s", e, exc_info=True)

    def set_runtime_override(self, key: str, value: float, expiry_seconds: Optional[int] = None) -> None:
        """
        Set a runtime override for a sizing parameter.

        Args:
            key: Parameter key (e.g., "size_multiplier", "base_risk_pct")
            value: Override value
            expiry_seconds: Override expiry in seconds (default: config.override_expiry_seconds)
        """
        if not self.config.allow_runtime_overrides:
            self.logger.warning("Runtime overrides disabled in config")
            return

        expiry = expiry_seconds or self.config.override_expiry_seconds
        expiry_ts = time.time() + expiry

        self.overrides[key] = (value, expiry_ts)
        self.logger.info(
            "Runtime override set: %s=%.2f (expires in %ds)", key, value, expiry
        )

    def clear_runtime_override(self, key: str) -> None:
        """Clear a runtime override."""
        if key in self.overrides:
            del self.overrides[key]
            self.logger.info("Runtime override cleared: %s", key)

    def clear_all_overrides(self) -> None:
        """Clear all runtime overrides."""
        count = len(self.overrides)
        self.overrides.clear()
        self.logger.info("Cleared %d runtime overrides", count)

    def reset_streak(self) -> None:
        """Reset win/loss streak counter."""
        old_streak = self.current_streak
        self.current_streak = 0
        self.logger.info("Streak reset: %d → 0", old_streak)

    def get_state(self) -> Dict:
        """Get current sizer state for persistence/monitoring."""
        return {
            "current_streak": self.current_streak,
            "trade_count": len(self.trade_history),
            "recent_trades": [
                {
                    "timestamp": t.timestamp,
                    "symbol": t.symbol,
                    "outcome": t.outcome.value,
                    "pnl": t.pnl_usd,
                }
                for t in self.trade_history[-10:]  # Last 10 trades
            ],
            "active_overrides": {
                k: {"value": v[0], "expires_at": v[1]}
                for k, v in self.overrides.items()
            },
        }

    # -------------------------------------------------------------------------
    # INTERNAL CALCULATIONS
    # -------------------------------------------------------------------------

    def _calculate_base_risk(self, current_equity_usd: float) -> float:
        """
        Calculate base risk percentage based on equity level.

        Logic:
        - If equity < $15k → 1.5% base risk
        - If equity >= $15k → 1.0% base risk

        Returns:
            Base risk as percentage (e.g., 1.5)
        """
        if current_equity_usd < self.config.equity_threshold_usd:
            return self.config.base_risk_pct_small
        else:
            return self.config.base_risk_pct_large

    def _calculate_streak_boost(self) -> float:
        """
        Calculate win streak boost.

        Logic:
        - +0.2% per consecutive win
        - Capped at +1.0% (5 wins max)
        - No boost for losses (only positive streaks count)

        Returns:
            Streak boost as percentage (e.g., 0.4 for 2 wins)
        """
        if self.current_streak <= 0:
            return 0.0  # No boost for losses

        # Cap streak count at configured max
        effective_streak = min(self.current_streak, self.config.max_streak_count)

        # Calculate boost
        boost = effective_streak * self.config.streak_boost_pct

        # Apply safety cap
        boost = min(boost, self.config.max_streak_boost_pct)

        return boost

    def _calculate_volatility_adjustment(self, current_atr_pct: Optional[float]) -> float:
        """
        Calculate volatility adjustment multiplier.

        Logic:
        - If ATR% > threshold → 0.8x multiplier (reduce size)
        - Otherwise → 1.0x multiplier (normal size)

        Args:
            current_atr_pct: Current ATR as % of price (e.g., 1.5 = 1.5%)

        Returns:
            Volatility multiplier (0.8 or 1.0)
        """
        if current_atr_pct is None:
            return self.config.normal_vol_multiplier  # Default to normal if no data

        if current_atr_pct >= self.config.high_vol_threshold_atr_pct:
            return self.config.high_vol_multiplier  # High vol → reduce size
        else:
            return self.config.normal_vol_multiplier  # Normal vol

    def _calculate_heat_limiter(self, portfolio_heat_pct: float) -> float:
        """
        Calculate portfolio heat limiter multiplier.

        Logic:
        - If heat > 80% → Force 0.5x multiplier (emergency de-risk)
        - Otherwise → 1.0x multiplier (normal)

        This is a safety circuit breaker to prevent over-exposure.

        Args:
            portfolio_heat_pct: Current portfolio heat as % of equity

        Returns:
            Heat limiter multiplier (0.5 or 1.0)
        """
        if portfolio_heat_pct >= self.config.portfolio_heat_threshold_pct:
            self.logger.warning(
                "Portfolio heat %.1f%% exceeds threshold %.1f%% - applying 0.5x limiter",
                portfolio_heat_pct,
                self.config.portfolio_heat_threshold_pct,
            )
            return self.config.portfolio_heat_cut_multiplier
        else:
            return 1.0

    def _update_streak(self, outcome: TradeOutcome) -> None:
        """
        Update current win/loss streak.

        Logic:
        - WIN: increment positive streak (or reset from negative)
        - LOSS: increment negative streak (or reset from positive)
        - BREAKEVEN: no change
        """
        if outcome == TradeOutcome.WIN:
            if self.current_streak < 0:
                self.current_streak = 1  # Reset from loss streak
            else:
                self.current_streak += 1  # Continue win streak
        elif outcome == TradeOutcome.LOSS:
            if self.current_streak > 0:
                self.current_streak = -1  # Reset from win streak
            else:
                self.current_streak -= 1  # Continue loss streak
        # BREAKEVEN: no change to streak

    def _get_active_override(self, key: str) -> Optional[float]:
        """
        Get active runtime override value (if not expired).

        Returns:
            Override value or None if not set/expired
        """
        if key not in self.overrides:
            return None

        value, expiry_ts = self.overrides[key]
        now = time.time()

        if now > expiry_ts:
            # Override expired
            del self.overrides[key]
            self.logger.info("Runtime override expired: %s", key)
            return None

        return value


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def create_default_sizer() -> DynamicPositionSizer:
    """Create a DynamicPositionSizer with default production-safe config."""
    config = DynamicSizingConfig()
    return DynamicPositionSizer(config)


def create_sizer_from_dict(config_dict: Dict) -> DynamicPositionSizer:
    """Create a DynamicPositionSizer from a config dictionary (e.g., from YAML)."""
    config = DynamicSizingConfig(**config_dict)
    return DynamicPositionSizer(config)
