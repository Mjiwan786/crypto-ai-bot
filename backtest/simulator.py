"""
Execution Simulator for Backtest.

Simulates order fills with realistic slippage and fees.
Produces canonical Trade objects with full explainability chain.
"""

from datetime import datetime, timezone
from decimal import Decimal
import logging

from shared_contracts import (
    TradeIntent,
    ExecutionDecision,
    Trade,
    TradeStatus,
    OrderFill,
    ExplainabilityChain,
    TradeSide,
)

logger = logging.getLogger(__name__)


class ExecutionSimulator:
    """
    Simulates order execution with slippage and fees.

    Produces canonical Trade objects linked to the full explainability chain.
    """

    def __init__(
        self,
        fees_bps: float = 10.0,
        slippage_bps: float = 5.0,
    ):
        """
        Initialize execution simulator.

        Args:
            fees_bps: Trading fees in basis points (default 10 = 0.1%)
            slippage_bps: Slippage in basis points (default 5 = 0.05%)
        """
        self.fees_bps = fees_bps
        self.slippage_bps = slippage_bps

    def execute(
        self,
        intent: TradeIntent,
        decision: ExecutionDecision,
        strategy_name: str = "",
        execution_time: datetime | None = None,
    ) -> Trade:
        """
        Execute an approved trade.

        Args:
            intent: The original trade intent
            decision: The approved execution decision
            strategy_name: Name of the strategy (for explainability)
            execution_time: Timestamp of execution (default: now)

        Returns:
            Trade with fills, fees, slippage, and explainability chain

        Raises:
            ValueError: If decision is not approved
        """
        if not decision.is_approved:
            raise ValueError(f"Cannot execute rejected decision: {decision.decision_id}")

        execution_time = execution_time or datetime.now(timezone.utc)

        # Calculate fill price with slippage
        entry_price = float(intent.entry_price)
        fill_price = self._apply_slippage(entry_price, intent.side)

        # Calculate quantity from position size
        position_size = float(intent.position_size_usd)
        quantity = position_size / fill_price

        # Calculate fee
        fee = self._calculate_fee(position_size)

        # Calculate slippage in basis points
        actual_slippage_bps = abs(fill_price - entry_price) / entry_price * 10000

        # Build order fill
        order_fill = OrderFill(
            price=Decimal(str(fill_price)),
            quantity=Decimal(str(quantity)),
            fee=Decimal(str(fee)),
            fee_currency="USD",
            filled_at=execution_time,
        )

        # Build explainability chain
        explainability_chain = ExplainabilityChain(
            strategy_id=intent.strategy_id,
            intent_id=intent.intent_id,
            decision_id=decision.decision_id,
            strategy_name=strategy_name,
            intent_reasons=[r.description for r in intent.reasons],
            intent_confidence=intent.confidence,
            decision_status=decision.status.value,
            risk_snapshot_summary={
                "account_equity_usd": decision.risk_snapshot.account_equity_usd,
                "daily_pnl_usd": decision.risk_snapshot.daily_pnl_usd,
                "daily_trades_count": decision.risk_snapshot.daily_trades_count,
            },
        )

        # Build trade
        return Trade(
            decision_id=decision.decision_id,
            pair=intent.pair,
            side=intent.side.value,
            requested_quantity=Decimal(str(quantity)),
            requested_price=intent.entry_price,
            status=TradeStatus.FILLED,
            fills=[order_fill],
            avg_fill_price=Decimal(str(fill_price)),
            total_filled_quantity=Decimal(str(quantity)),
            total_fees=Decimal(str(fee)),
            slippage_bps=actual_slippage_bps,
            explainability_chain=explainability_chain,
            submitted_at=execution_time,
            completed_at=execution_time,
            mode=intent.mode,
            exchange="backtest",
        )

    def _apply_slippage(self, price: float, side: TradeSide) -> float:
        """
        Apply slippage to price based on trade direction.

        For longs: price increases (buy at higher price)
        For shorts: price decreases (sell at lower price)
        """
        slippage_factor = self.slippage_bps / 10000

        if side == TradeSide.LONG:
            return price * (1 + slippage_factor)
        else:
            return price * (1 - slippage_factor)

    def _calculate_fee(self, notional: float) -> float:
        """Calculate trading fee from notional value."""
        return notional * (self.fees_bps / 10000)

    def calculate_pnl(
        self,
        entry_trade: Trade,
        exit_price: float,
        exit_time: datetime,
    ) -> tuple[float, float]:
        """
        Calculate P&L for closing a position.

        Args:
            entry_trade: The entry trade
            exit_price: Exit price (after slippage applied by caller)
            exit_time: Exit timestamp

        Returns:
            (realized_pnl, realized_pnl_pct) tuple
        """
        entry_price = float(entry_trade.avg_fill_price)
        quantity = float(entry_trade.total_filled_quantity)
        entry_fee = float(entry_trade.total_fees)

        # Apply slippage to exit
        side = TradeSide(entry_trade.side)
        if side == TradeSide.LONG:
            exit_price_with_slippage = exit_price * (1 - self.slippage_bps / 10000)
        else:
            exit_price_with_slippage = exit_price * (1 + self.slippage_bps / 10000)

        # Calculate exit fee
        exit_notional = quantity * exit_price_with_slippage
        exit_fee = self._calculate_fee(exit_notional)

        # Calculate P&L
        if side == TradeSide.LONG:
            gross_pnl = (exit_price_with_slippage - entry_price) * quantity
        else:
            gross_pnl = (entry_price - exit_price_with_slippage) * quantity

        # Net P&L after fees
        realized_pnl = gross_pnl - entry_fee - exit_fee

        # P&L percentage (based on entry notional)
        entry_notional = entry_price * quantity
        realized_pnl_pct = (realized_pnl / entry_notional) * 100 if entry_notional > 0 else 0

        return realized_pnl, realized_pnl_pct
