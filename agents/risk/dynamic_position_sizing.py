"""
Dynamic Position Sizing with Auto-Throttle (agents/risk/dynamic_position_sizing.py)

Advanced position sizing module with:
- Adaptive base risk (1.0-2.0% per trade)
- Max heat cap (75% of capital)
- Daily P&L targets (+2.5%) and stops (-6%)
- Auto-throttle when drawdown >7% or Sharpe <1

For Prompt 3: Profitability Boosters
Author: Crypto AI Bot Team
Version: 2.0.0
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class PositionSizingConfig(BaseModel):
    """Configuration for dynamic position sizing."""

    # Base risk parameters
    base_risk_pct_min: float = Field(default=1.0, ge=0.1, le=5.0, description="Min risk per trade (%)")
    base_risk_pct_max: float = Field(default=2.0, ge=0.1, le=5.0, description="Max risk per trade (%)")

    # Heat management
    max_heat_pct: float = Field(default=75.0, ge=10.0, le=100.0, description="Max total exposure (%)")
    max_concurrent_positions: int = Field(default=5, ge=1, le=10, description="Max simultaneous positions")

    # Daily limits
    daily_pnl_target_pct: float = Field(default=2.5, ge=0.5, le=10.0, description="Daily profit target (%)")
    daily_stop_loss_pct: float = Field(default=-6.0, le=-1.0, description="Daily stop loss (%)")

    # Auto-throttle thresholds
    max_drawdown_threshold_pct: float = Field(default=7.0, ge=1.0, le=20.0, description="Drawdown threshold for throttle (%)")
    min_sharpe_threshold: float = Field(default=1.0, ge=0.0, le=3.0, description="Min Sharpe for full risk")

    # Throttle reduction factors
    drawdown_throttle_factor: float = Field(default=0.5, ge=0.1, le=1.0, description="Risk reduction when in drawdown")
    low_sharpe_throttle_factor: float = Field(default=0.7, ge=0.1, le=1.0, description="Risk reduction for low Sharpe")

    # Performance lookback
    sharpe_lookback_days: int = Field(default=30, ge=7, le=90, description="Days for Sharpe calculation")


@dataclass
class PositionSizeResult:
    """Result of position size calculation."""

    position_size_usd: float
    position_size_pct: float
    risk_per_trade_pct: float
    current_heat_pct: float
    throttle_active: bool
    throttle_reason: str
    can_trade: bool
    max_additional_size_usd: float


class DynamicPositionSizer:
    """
    Dynamic position sizing with auto-throttle based on performance.

    Adjusts position sizes based on:
    - Current performance (Sharpe ratio)
    - Drawdown level
    - Daily P&L
    - Total heat (exposure)
    """

    def __init__(
        self,
        config: Optional[PositionSizingConfig] = None,
        initial_capital: float = 10000.0,
    ):
        """
        Initialize position sizer.

        Args:
            config: Position sizing configuration
            initial_capital: Starting capital
        """
        self.config = config or PositionSizingConfig()
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.peak_capital = initial_capital

        # Track positions
        self.open_positions: List[Dict] = []

        # Track daily P&L
        self.daily_pnl: Dict[str, float] = {}  # {date: pnl}
        self.today_trades: List[Dict] = []

        # Track equity curve for Sharpe
        self.equity_history: List[Dict] = []  # [{timestamp, equity}]

        logger.info(
            "DynamicPositionSizer initialized (capital=$%.2f, base_risk=%.1f-%.1f%%)",
            initial_capital,
            self.config.base_risk_pct_min,
            self.config.base_risk_pct_max,
        )

    def calculate_position_size(
        self,
        entry_price: float,
        stop_loss_price: float,
        confidence: float = 1.0,
        regime_multiplier: float = 1.0,
    ) -> PositionSizeResult:
        """
        Calculate optimal position size with all constraints.

        Args:
            entry_price: Entry price
            stop_loss_price: Stop loss price
            confidence: Signal confidence (0-1, scales position size)
            regime_multiplier: Regime-based multiplier (from adaptive router)

        Returns:
            PositionSizeResult with size and throttle info
        """
        # 1. Check daily limits first
        today = datetime.now().date().isoformat()
        today_pnl_pct = (self.daily_pnl.get(today, 0.0) / self.current_capital) * 100

        # Daily target hit
        if today_pnl_pct >= self.config.daily_pnl_target_pct:
            logger.info("Daily target hit (%.2f%% >= %.2f%%), pausing trades",
                       today_pnl_pct, self.config.daily_pnl_target_pct)
            return self._no_trade_result("Daily target reached")

        # Daily stop hit
        if today_pnl_pct <= self.config.daily_stop_loss_pct:
            logger.warning("Daily stop hit (%.2f%% <= %.2f%%), pausing trades",
                          today_pnl_pct, self.config.daily_stop_loss_pct)
            return self._no_trade_result("Daily stop loss hit")

        # 2. Calculate current heat (total exposure)
        current_heat_usd = sum(pos.get("size_usd", 0.0) for pos in self.open_positions)
        current_heat_pct = (current_heat_usd / self.current_capital) * 100

        # Check max concurrent positions
        if len(self.open_positions) >= self.config.max_concurrent_positions:
            logger.debug("Max concurrent positions reached (%d)", len(self.open_positions))
            return self._no_trade_result("Max concurrent positions")

        # 3. Calculate drawdown
        drawdown_pct = ((self.peak_capital - self.current_capital) / self.peak_capital) * 100

        # 4. Calculate Sharpe ratio
        sharpe = self._calculate_sharpe_ratio()

        # 5. Determine base risk
        base_risk_pct = self._calculate_base_risk(confidence, sharpe, drawdown_pct)

        # 6. Apply throttles
        risk_pct, throttle_active, throttle_reason = self._apply_throttles(
            base_risk_pct, drawdown_pct, sharpe
        )

        # 7. Apply regime multiplier
        risk_pct *= regime_multiplier
        risk_pct = np.clip(risk_pct, 0.1, 5.0)  # Hard limits

        # 8. Calculate position size from risk
        risk_per_unit = abs(entry_price - stop_loss_price)
        if risk_per_unit == 0:
            logger.warning("Stop loss equals entry price, using 1% of price as risk")
            risk_per_unit = entry_price * 0.01

        # Position size = (Capital * Risk%) / (Risk per unit)
        risk_amount_usd = self.current_capital * (risk_pct / 100.0)
        position_size_units = risk_amount_usd / risk_per_unit
        position_size_usd = position_size_units * entry_price

        # 9. Check heat cap
        max_additional_size_usd = (self.current_capital * self.config.max_heat_pct / 100.0) - current_heat_usd
        max_additional_size_usd = max(0.0, max_additional_size_usd)

        if position_size_usd > max_additional_size_usd:
            logger.warning(
                "Position size $%.2f exceeds heat cap, reducing to $%.2f",
                position_size_usd, max_additional_size_usd
            )
            position_size_usd = max_additional_size_usd
            throttle_active = True
            throttle_reason += " | Heat cap limit"

        if position_size_usd < 10.0:  # Minimum position size
            logger.debug("Position size too small ($%.2f < $10), no trade", position_size_usd)
            return self._no_trade_result("Position size too small")

        position_size_pct = (position_size_usd / self.current_capital) * 100

        logger.info(
            "Position size: $%.2f (%.1f%% of capital) | Risk: %.2f%% | Heat: %.1f%% | Throttle: %s",
            position_size_usd, position_size_pct, risk_pct,
            current_heat_pct + position_size_pct, throttle_active
        )

        return PositionSizeResult(
            position_size_usd=position_size_usd,
            position_size_pct=position_size_pct,
            risk_per_trade_pct=risk_pct,
            current_heat_pct=current_heat_pct + position_size_pct,
            throttle_active=throttle_active,
            throttle_reason=throttle_reason if throttle_active else "None",
            can_trade=True,
            max_additional_size_usd=max_additional_size_usd,
        )

    def _calculate_base_risk(
        self,
        confidence: float,
        sharpe: float,
        drawdown_pct: float,
    ) -> float:
        """
        Calculate base risk percentage.

        Args:
            confidence: Signal confidence (0-1)
            sharpe: Current Sharpe ratio
            drawdown_pct: Current drawdown %

        Returns:
            Base risk % (before throttles)
        """
        # Start with mid-range
        base_risk = (self.config.base_risk_pct_min + self.config.base_risk_pct_max) / 2.0

        # Scale by confidence
        confidence = np.clip(confidence, 0.5, 1.5)  # Allow boost up to 1.5x
        base_risk *= confidence

        # Boost for high Sharpe
        if sharpe > 1.5:
            sharpe_boost = min(1.3, 1.0 + (sharpe - 1.5) * 0.2)
            base_risk *= sharpe_boost

        # Reduce for drawdown
        if drawdown_pct > 3.0:
            drawdown_penalty = max(0.7, 1.0 - (drawdown_pct - 3.0) / 20.0)
            base_risk *= drawdown_penalty

        # Clamp to range
        base_risk = np.clip(base_risk, self.config.base_risk_pct_min, self.config.base_risk_pct_max)

        return base_risk

    def _apply_throttles(
        self,
        base_risk_pct: float,
        drawdown_pct: float,
        sharpe: float,
    ) -> tuple[float, bool, str]:
        """
        Apply auto-throttle based on performance.

        Args:
            base_risk_pct: Base risk %
            drawdown_pct: Current drawdown %
            sharpe: Current Sharpe ratio

        Returns:
            (adjusted_risk_pct, throttle_active, reason)
        """
        risk_pct = base_risk_pct
        throttle_active = False
        reasons = []

        # Drawdown throttle
        if drawdown_pct > self.config.max_drawdown_threshold_pct:
            severity = min(1.0, drawdown_pct / self.config.max_drawdown_threshold_pct - 1.0)
            throttle_factor = max(
                self.config.drawdown_throttle_factor,
                1.0 - severity * (1.0 - self.config.drawdown_throttle_factor)
            )
            risk_pct *= throttle_factor
            throttle_active = True
            reasons.append(f"Drawdown {drawdown_pct:.1f}% (throttle: {throttle_factor:.2f}x)")
            logger.warning(
                "Drawdown throttle active: %.1f%% > %.1f%% (factor: %.2f)",
                drawdown_pct, self.config.max_drawdown_threshold_pct, throttle_factor
            )

        # Low Sharpe throttle
        if sharpe < self.config.min_sharpe_threshold and sharpe > 0:
            throttle_factor = self.config.low_sharpe_throttle_factor
            risk_pct *= throttle_factor
            throttle_active = True
            reasons.append(f"Sharpe {sharpe:.2f} < {self.config.min_sharpe_threshold} (throttle: {throttle_factor:.2f}x)")
            logger.warning(
                "Sharpe throttle active: %.2f < %.2f (factor: %.2f)",
                sharpe, self.config.min_sharpe_threshold, throttle_factor
            )

        throttle_reason = " | ".join(reasons) if reasons else "None"

        return risk_pct, throttle_active, throttle_reason

    def _calculate_sharpe_ratio(self) -> float:
        """
        Calculate rolling Sharpe ratio from equity history.

        Returns:
            Sharpe ratio (annualized)
        """
        if len(self.equity_history) < 30:  # Need at least 30 data points
            return 0.0

        # Get equity series
        df = pd.DataFrame(self.equity_history)
        df = df.sort_values("timestamp")

        # Calculate returns
        df["returns"] = df["equity"].pct_change()

        # Filter to lookback period
        cutoff = datetime.now() - timedelta(days=self.config.sharpe_lookback_days)
        df = df[df["timestamp"] >= cutoff]

        if len(df) < 30:
            return 0.0

        # Calculate Sharpe (annualized)
        returns = df["returns"].dropna()
        if len(returns) == 0 or returns.std() == 0:
            return 0.0

        # Assume 5-min bars (288 per day)
        sharpe = np.sqrt(252 * 288) * (returns.mean() / returns.std())

        return float(sharpe)

    def _no_trade_result(self, reason: str) -> PositionSizeResult:
        """Return a no-trade result."""
        current_heat_usd = sum(pos.get("size_usd", 0.0) for pos in self.open_positions)
        current_heat_pct = (current_heat_usd / self.current_capital) * 100

        return PositionSizeResult(
            position_size_usd=0.0,
            position_size_pct=0.0,
            risk_per_trade_pct=0.0,
            current_heat_pct=current_heat_pct,
            throttle_active=True,
            throttle_reason=reason,
            can_trade=False,
            max_additional_size_usd=0.0,
        )

    def add_position(
        self,
        position_id: str,
        size_usd: float,
        entry_price: float,
        stop_loss: float,
    ) -> None:
        """
        Register a new open position.

        Args:
            position_id: Unique position ID
            size_usd: Position size in USD
            entry_price: Entry price
            stop_loss: Stop loss price
        """
        self.open_positions.append({
            "id": position_id,
            "size_usd": size_usd,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "timestamp": datetime.now(),
        })

        logger.info("Position added: %s ($%.2f)", position_id, size_usd)

    def close_position(
        self,
        position_id: str,
        exit_price: float,
        pnl: float,
    ) -> None:
        """
        Close a position and update capital.

        Args:
            position_id: Position ID to close
            exit_price: Exit price
            pnl: Realized P&L
        """
        # Remove position
        self.open_positions = [p for p in self.open_positions if p["id"] != position_id]

        # Update capital
        self.current_capital += pnl

        # Update peak
        if self.current_capital > self.peak_capital:
            self.peak_capital = self.current_capital

        # Update daily P&L
        today = datetime.now().date().isoformat()
        self.daily_pnl[today] = self.daily_pnl.get(today, 0.0) + pnl

        # Add to equity history
        self.equity_history.append({
            "timestamp": datetime.now(),
            "equity": self.current_capital,
        })

        # Add to today's trades
        self.today_trades.append({
            "position_id": position_id,
            "exit_price": exit_price,
            "pnl": pnl,
            "timestamp": datetime.now(),
        })

        logger.info(
            "Position closed: %s | PnL: $%.2f | Capital: $%.2f | Daily P&L: $%.2f",
            position_id, pnl, self.current_capital, self.daily_pnl.get(today, 0.0)
        )

    def reset_daily_stats(self) -> None:
        """Reset daily stats at start of new trading day."""
        today = datetime.now().date().isoformat()

        # Archive yesterday's stats
        if today not in self.daily_pnl:
            self.daily_pnl[today] = 0.0
            self.today_trades = []
            logger.info("Daily stats reset for %s", today)

    def get_status(self) -> Dict:
        """
        Get current sizing status.

        Returns:
            Dict with current status
        """
        today = datetime.now().date().isoformat()
        today_pnl = self.daily_pnl.get(today, 0.0)
        today_pnl_pct = (today_pnl / self.current_capital) * 100

        current_heat_usd = sum(pos.get("size_usd", 0.0) for pos in self.open_positions)
        current_heat_pct = (current_heat_usd / self.current_capital) * 100

        drawdown_pct = ((self.peak_capital - self.current_capital) / self.peak_capital) * 100
        sharpe = self._calculate_sharpe_ratio()

        return {
            "current_capital": self.current_capital,
            "peak_capital": self.peak_capital,
            "drawdown_pct": drawdown_pct,
            "sharpe_ratio": sharpe,
            "open_positions": len(self.open_positions),
            "current_heat_usd": current_heat_usd,
            "current_heat_pct": current_heat_pct,
            "today_pnl": today_pnl,
            "today_pnl_pct": today_pnl_pct,
            "today_trades": len(self.today_trades),
            "can_trade": (
                today_pnl_pct < self.config.daily_pnl_target_pct and
                today_pnl_pct > self.config.daily_stop_loss_pct and
                len(self.open_positions) < self.config.max_concurrent_positions
            ),
        }


# Self-check for development/testing
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    logger.info("Running DynamicPositionSizer self-check...")

    try:
        # Create sizer
        sizer = DynamicPositionSizer(initial_capital=10000.0)

        # Simulate some trades
        logger.info("\n=== Test 1: Normal trade ===")
        result = sizer.calculate_position_size(
            entry_price=50000.0,
            stop_loss_price=49500.0,  # 1% stop
            confidence=1.0,
            regime_multiplier=1.0,
        )
        assert result.can_trade
        assert result.position_size_usd > 0
        logger.info("Position size: $%.2f (%.2f%%)", result.position_size_usd, result.position_size_pct)

        # Add position
        sizer.add_position("test_1", result.position_size_usd, 50000.0, 49500.0)

        # Close with profit
        logger.info("\n=== Test 2: Close winning trade ===")
        sizer.close_position("test_1", 50500.0, 100.0)
        status = sizer.get_status()
        logger.info("Capital after win: $%.2f", status["current_capital"])

        # Test high confidence
        logger.info("\n=== Test 3: High confidence trade ===")
        result = sizer.calculate_position_size(
            entry_price=50000.0,
            stop_loss_price=49500.0,
            confidence=1.5,  # High confidence
            regime_multiplier=1.0,
        )
        logger.info("High confidence size: $%.2f", result.position_size_usd)

        # Simulate drawdown
        logger.info("\n=== Test 4: Drawdown throttle ===")
        sizer.current_capital = 9000.0  # 10% drawdown
        result = sizer.calculate_position_size(
            entry_price=50000.0,
            stop_loss_price=49500.0,
            confidence=1.0,
            regime_multiplier=1.0,
        )
        assert result.throttle_active
        logger.info("Throttled size: $%.2f (reason: %s)", result.position_size_usd, result.throttle_reason)

        # Test daily target
        logger.info("\n=== Test 5: Daily target hit ===")
        sizer.current_capital = 10300.0  # +3% today
        today = datetime.now().date().isoformat()
        sizer.daily_pnl[today] = 300.0
        result = sizer.calculate_position_size(
            entry_price=50000.0,
            stop_loss_price=49500.0,
            confidence=1.0,
            regime_multiplier=1.0,
        )
        assert not result.can_trade
        logger.info("Daily target hit: can_trade=%s", result.can_trade)

        logger.info("\n✓ Self-check passed!")
        sys.exit(0)

    except Exception as e:
        logger.error("✗ Self-check failed: %s", e)
        import traceback
        traceback.print_exc()
        sys.exit(1)
