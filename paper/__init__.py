"""
Paper Trading Engine - Phase 1 Step 3 + Phase 2 Step 2.3.

Hardened paper trading runtime with:
- Canonical pipeline: Strategy → TradeIntent → ExecutionDecision → Trade
- Full explainability (reasons[], indicator_inputs, rejection_reasons)
- Redis streaming of ALL decisions (approved + rejected)
- Kill switches (bot, account, global)
- Non-bypassable decision logging
- Dynamic risk limits (Phase 2 Step 2.2)
- Engine heartbeat for effective state visibility (Phase 2 Step 2.3)

Usage:
    from paper import PaperEngine, AccountStateManager, DecisionPublisher
    from paper.kill_switch import KillSwitchManager, check_kill_switch
    from paper.heartbeat import HeartbeatPublisher, ENGINE_STATUS_KEY

    # Create engine
    engine = PaperEngine(redis_client, strategy, config)

    # Process market snapshot
    decision, trade = await engine.tick(market_snapshot)
"""

from paper.engine import PaperEngine, PaperEngineConfig
from paper.state import AccountStateManager
from paper.publisher import DecisionPublisher, StreamNames
from paper.kill_switch import KillSwitchManager, KillSwitchType, check_kill_switch
from paper.heartbeat import (
    HeartbeatPublisher,
    EngineHeartbeat,
    EffectiveRiskLimitsSnapshot,
    ENGINE_STATUS_KEY,
)

__all__ = [
    # Engine
    "PaperEngine",
    "PaperEngineConfig",
    # State
    "AccountStateManager",
    # Publisher
    "DecisionPublisher",
    "StreamNames",
    # Kill Switch
    "KillSwitchManager",
    "KillSwitchType",
    "check_kill_switch",
    # Heartbeat (Phase 2 Step 2.3)
    "HeartbeatPublisher",
    "EngineHeartbeat",
    "EffectiveRiskLimitsSnapshot",
    "ENGINE_STATUS_KEY",
]
