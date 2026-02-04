"""
Trading Pipeline Protocol.

This defines the canonical pipeline interface that ALL execution paths must follow:
    Strategy -> TradeIntent -> ExecutionDecision -> Trade

Both backtest and paper/live execution MUST implement this protocol to ensure:
- Parity between backtest and real execution
- No execution without approved ExecutionDecision
- Full explainability at every step

This is a typing.Protocol only - no implementation here.
"""

from typing import Protocol, runtime_checkable

from shared_contracts.canonical.strategy import Strategy
from shared_contracts.canonical.trade_intent import TradeIntent
from shared_contracts.canonical.execution_decision import ExecutionDecision
from shared_contracts.canonical.trade import Trade
from shared_contracts.canonical.market_snapshot import MarketSnapshot, AccountState


@runtime_checkable
class IntentGenerator(Protocol):
    """
    Protocol for generating trade intents from strategy + market data.

    Implementations should be deterministic: same inputs -> same outputs.
    """

    def generate_trade_intent(
        self,
        strategy: Strategy,
        market_snapshot: MarketSnapshot,
    ) -> TradeIntent | None:
        """
        Generate a trade intent from strategy and market data.

        Args:
            strategy: The strategy configuration
            market_snapshot: Current market state

        Returns:
            TradeIntent if strategy signals a trade, None otherwise

        Note:
            - Must be deterministic (same inputs -> same outputs)
            - Must include at least one reason in the intent
            - Must populate indicator_inputs for explainability
        """
        ...


@runtime_checkable
class RiskEvaluator(Protocol):
    """
    Protocol for evaluating risk on trade intents.

    CRITICAL: All trades must pass through risk evaluation.
    """

    def evaluate_risk(
        self,
        trade_intent: TradeIntent,
        account_state: AccountState,
    ) -> ExecutionDecision:
        """
        Evaluate risk for a trade intent.

        Args:
            trade_intent: The intent to evaluate
            account_state: Current account state

        Returns:
            ExecutionDecision with approved/rejected status and full context

        Note:
            - Must ALWAYS return a decision (never throw for normal operations)
            - Rejected decisions must include rejection_reasons
            - risk_snapshot must capture state at decision time
            - rules_evaluated should list all checks performed
        """
        ...


@runtime_checkable
class TradeExecutor(Protocol):
    """
    Protocol for executing approved trades.

    CRITICAL: Only approved ExecutionDecisions can be executed.
    """

    def execute(
        self,
        decision: ExecutionDecision,
    ) -> Trade:
        """
        Execute an approved trade.

        Args:
            decision: The approved ExecutionDecision

        Returns:
            Trade record with execution details and explainability chain

        Raises:
            ValueError: If decision is not approved

        Note:
            - Must verify decision.is_approved before executing
            - Must populate explainability_chain
            - Must track slippage and fees
        """
        ...


@runtime_checkable
class TradingPipeline(Protocol):
    """
    Complete trading pipeline protocol.

    This combines all three stages into a single interface.
    Implementations must ensure:
    1. generate_trade_intent is deterministic
    2. evaluate_risk runs BEFORE execution
    3. execute only accepts approved decisions
    4. Full explainability is maintained throughout

    Both backtest and paper/live runners must implement this protocol
    to ensure parity.
    """

    def generate_trade_intent(
        self,
        strategy: Strategy,
        market_snapshot: MarketSnapshot,
    ) -> TradeIntent | None:
        """Generate a trade intent from strategy and market data."""
        ...

    def evaluate_risk(
        self,
        trade_intent: TradeIntent,
        account_state: AccountState,
    ) -> ExecutionDecision:
        """Evaluate risk for a trade intent."""
        ...

    def execute(
        self,
        decision: ExecutionDecision,
    ) -> Trade:
        """Execute an approved trade."""
        ...

    def run_pipeline(
        self,
        strategy: Strategy,
        market_snapshot: MarketSnapshot,
        account_state: AccountState,
    ) -> Trade | None:
        """
        Run the complete pipeline: intent -> risk -> execute.

        This is a convenience method that chains all three stages.

        Args:
            strategy: The strategy configuration
            market_snapshot: Current market state
            account_state: Current account state

        Returns:
            Trade if executed successfully, None if no intent or rejected

        Note:
            Default implementation should be:
            1. intent = generate_trade_intent(strategy, market_snapshot)
            2. if intent is None: return None
            3. decision = evaluate_risk(intent, account_state)
            4. if not decision.is_approved: return None (log rejection)
            5. return execute(decision)
        """
        ...
