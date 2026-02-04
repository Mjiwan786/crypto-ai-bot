"""
Deterministic Risk Evaluator for Backtest.

Produces canonical ExecutionDecision with full explainability.
Uses the same interface that paper trading will use.

Risk Rules (Phase 1 minimal):
- max_trades_per_day
- max_daily_loss_pct
- position_size_usd <= max_position_size_usd
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import logging

from shared_contracts import (
    TradeIntent,
    ExecutionDecision,
    DecisionStatus,
    RiskSnapshot,
    RejectionReason,
    AccountState,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RiskLimits:
    """Risk limits configuration."""

    max_position_size_usd: float = 1000.0
    max_trades_per_day: int = 10
    max_daily_loss_pct: float = 5.0  # Block if daily loss exceeds this %


class RiskEvaluator:
    """
    Deterministic risk evaluator for backtest and paper trading.

    Evaluates TradeIntent against AccountState and risk limits.
    Returns ExecutionDecision with full explainability.
    """

    def __init__(self, limits: RiskLimits | None = None):
        """
        Initialize risk evaluator.

        Args:
            limits: Risk limits configuration (uses defaults if None)
        """
        self.limits = limits or RiskLimits()

    def evaluate(
        self,
        intent: TradeIntent,
        account_state: AccountState,
    ) -> ExecutionDecision:
        """
        Evaluate risk for a trade intent.

        Args:
            intent: The trade intent to evaluate
            account_state: Current account state

        Returns:
            ExecutionDecision with approved/rejected status and full context
        """
        rules_evaluated: list[str] = []
        rejection_reasons: list[RejectionReason] = []

        # Build risk snapshot
        risk_snapshot = self._build_risk_snapshot(account_state)

        # Rule 1: Check position size limit
        rules_evaluated.append("position_size_limit")
        position_size = float(intent.position_size_usd)
        if position_size > self.limits.max_position_size_usd:
            rejection_reasons.append(
                RejectionReason(
                    code="POSITION_SIZE_EXCEEDED",
                    message=f"Position size ${position_size:.2f} exceeds limit ${self.limits.max_position_size_usd:.2f}",
                    details={
                        "requested": position_size,
                        "limit": self.limits.max_position_size_usd,
                    },
                )
            )

        # Rule 2: Check max trades per day
        rules_evaluated.append("max_trades_per_day")
        if account_state.trades_today >= self.limits.max_trades_per_day:
            rejection_reasons.append(
                RejectionReason(
                    code="MAX_TRADES_EXCEEDED",
                    message=f"Daily trade limit of {self.limits.max_trades_per_day} reached",
                    details={
                        "trades_today": account_state.trades_today,
                        "limit": self.limits.max_trades_per_day,
                    },
                )
            )

        # Rule 3: Check daily loss limit
        rules_evaluated.append("max_daily_loss")
        daily_loss_pct = self._calculate_daily_loss_pct(account_state)
        if daily_loss_pct >= self.limits.max_daily_loss_pct:
            rejection_reasons.append(
                RejectionReason(
                    code="DAILY_LOSS_LIMIT_EXCEEDED",
                    message=f"Daily loss {daily_loss_pct:.2f}% exceeds limit {self.limits.max_daily_loss_pct:.2f}%",
                    details={
                        "daily_loss_pct": daily_loss_pct,
                        "limit": self.limits.max_daily_loss_pct,
                    },
                )
            )

        # Rule 4: Check if trading is enabled
        rules_evaluated.append("trading_enabled")
        if not account_state.trading_enabled:
            rejection_reasons.append(
                RejectionReason(
                    code="TRADING_DISABLED",
                    message="Trading is disabled for this account",
                    details={"trading_enabled": False},
                )
            )

        # Rule 5: Check sufficient balance
        rules_evaluated.append("sufficient_balance")
        if float(account_state.available_balance_usd) < position_size:
            rejection_reasons.append(
                RejectionReason(
                    code="INSUFFICIENT_BALANCE",
                    message=f"Insufficient balance: ${float(account_state.available_balance_usd):.2f} < ${position_size:.2f}",
                    details={
                        "available": float(account_state.available_balance_usd),
                        "required": position_size,
                    },
                )
            )

        # Build decision
        if rejection_reasons:
            return ExecutionDecision.reject(
                intent_id=intent.intent_id,
                reasons=rejection_reasons,
                risk_snapshot=risk_snapshot,
                rules_evaluated=rules_evaluated,
                mode=intent.mode,
            )
        else:
            return ExecutionDecision.approve(
                intent_id=intent.intent_id,
                risk_snapshot=risk_snapshot,
                rules_evaluated=rules_evaluated,
                mode=intent.mode,
            )

    def _build_risk_snapshot(self, account_state: AccountState) -> RiskSnapshot:
        """Build risk snapshot from account state."""
        return RiskSnapshot(
            account_equity_usd=float(account_state.total_equity_usd),
            daily_pnl_usd=float(account_state.daily_pnl_usd),
            daily_trades_count=account_state.trades_today,
            open_positions_count=account_state.open_positions_count,
            open_positions_exposure_usd=float(account_state.open_positions_exposure_usd),
            max_position_size_usd=self.limits.max_position_size_usd,
            max_daily_loss_usd=float(account_state.total_equity_usd) * (self.limits.max_daily_loss_pct / 100),
            max_trades_per_day=self.limits.max_trades_per_day,
            drawdown_pct=account_state.drawdown_pct,
            trading_enabled=account_state.trading_enabled,
        )

    def _calculate_daily_loss_pct(self, account_state: AccountState) -> float:
        """Calculate daily loss as percentage of equity."""
        daily_pnl = float(account_state.daily_pnl_usd)
        equity = float(account_state.total_equity_usd)

        if equity <= 0:
            return 0.0

        if daily_pnl >= 0:
            return 0.0

        return abs(daily_pnl / equity) * 100
