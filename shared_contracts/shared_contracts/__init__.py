"""
Shared Contracts - Canonical trading objects for AI Predicted Signals.

This package defines the "System Law" objects that both crypto-ai-bot and signals-api
must use. These are immutable contracts that enforce:
- Single pipeline: Strategy -> TradeIntent -> ExecutionDecision -> Trade
- Full explainability: reasons, inputs, risk context
- No execution without approved ExecutionDecision

Usage:
    from shared_contracts import Strategy, TradeIntent, ExecutionDecision, Trade
    from shared_contracts.pipeline import TradingPipeline
"""

from shared_contracts.canonical.strategy import (
    Strategy,
    StrategyType,
    StrategySource,
    RiskProfile,
)
from shared_contracts.canonical.trade_intent import (
    TradeIntent,
    TradeSide,
    IntentReason,
)
from shared_contracts.canonical.execution_decision import (
    ExecutionDecision,
    DecisionStatus,
    RiskSnapshot,
    RejectionReason,
)
from shared_contracts.canonical.trade import (
    Trade,
    TradeStatus,
    OrderFill,
    ExplainabilityChain,
)
from shared_contracts.canonical.market_snapshot import (
    MarketSnapshot,
    AccountState,
)
from shared_contracts.pipeline.protocol import TradingPipeline

__version__ = "0.1.0"
__all__ = [
    # Strategy
    "Strategy",
    "StrategyType",
    "StrategySource",
    "RiskProfile",
    # TradeIntent
    "TradeIntent",
    "TradeSide",
    "IntentReason",
    # ExecutionDecision
    "ExecutionDecision",
    "DecisionStatus",
    "RiskSnapshot",
    "RejectionReason",
    # Trade
    "Trade",
    "TradeStatus",
    "OrderFill",
    "ExplainabilityChain",
    # Market/Account
    "MarketSnapshot",
    "AccountState",
    # Pipeline
    "TradingPipeline",
]
