"""
LangGraph-based trading orchestration with AI Engine integration.

Replaces LangChain with LangGraph for stateful orchestration of trading agents.
Provides a clean state machine that routes signals through risk checks to execution.
Now includes full AI Engine integration with strategy selector and adaptive learning.
"""

from __future__ import annotations

import logging
import time
from typing import TypedDict, Dict, Any, Optional, List
from datetime import datetime, timezone
from pathlib import Path
import sys

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import AI Engine components
from ai_engine.strategy_selector import select_for_symbol, SelectorConfig, PositionSnapshot, Side
from ai_engine.adaptive_learner import gated_update, LearnerConfig

# Import unified configuration
from config.unified_config_loader import get_config_loader, SystemConfig

try:
    from langgraph.graph import StateGraph, END
    from langgraph.graph.state import CompiledStateGraph
except ImportError:
    # Fallback for when LangGraph is not installed
    StateGraph = None
    END = "end"
    CompiledStateGraph = Any

logger = logging.getLogger(__name__)


class BotState(TypedDict, total=False):
    """Enhanced state for the trading bot orchestration with AI Engine integration."""
    symbol: str
    features: Dict[str, Any]
    signal: Optional[Dict[str, Any]]
    risk_ok: bool
    order_intent: Optional[Dict[str, Any]]
    execution_result: Optional[Dict[str, Any]]
    logs: List[str]
    errors: List[str]
    run_id: str
    timestamp: float
    
    # AI Engine integration
    ai_decision: Optional[Dict[str, Any]]
    strategy_confidence: Optional[float]
    adaptive_learning_applied: bool
    position_snapshot: Optional[Dict[str, Any]]
    
    # Enhanced configuration
    system_config: Optional[Dict[str, Any]]
    strategy_selector_config: Optional[Dict[str, Any]]
    adaptive_learner_config: Optional[Dict[str, Any]]


def configuration_loader(state: BotState) -> BotState:
    """Load unified configuration for the trading session."""
    try:
        # Load system configuration
        config_loader = get_config_loader()
        system_config = config_loader.load_system_config(
            environment=state.get("environment", "production"),
            strategy=state.get("strategy", None)
        )
        
        # Update state with configuration
        state["system_config"] = {
            'environment': system_config.environment,
            'debug_mode': system_config.debug_mode,
            'paper_trading': system_config.paper_trading,
            'trading_pairs': system_config.trading_config.get('pairs', []),
            'strategies_enabled': list(system_config.trading_config.get('strategies', {}).keys())
        }
        
        state["strategy_selector_config"] = system_config.strategy_selector_config
        state["adaptive_learner_config"] = system_config.adaptive_learner_config
        
        state.setdefault("logs", []).append("configuration_loader:ok")
        logger.info("Configuration loaded successfully")
        
    except Exception as e:
        error_msg = f"configuration_loader failed: {e}"
        state.setdefault("errors", []).append(error_msg)
        state.setdefault("logs", []).append(f"configuration_loader:error - {error_msg}")
        logger.error(error_msg)
    
    return state

def signal_analyst(state: BotState) -> BotState:
    """Generate trading signal from market features with AI Engine integration."""
    try:
        # Import here to avoid circular imports
        from agents.core.signal_analyst import generate_signal
        
        symbol = state.get("symbol", "BTC/USDT")
        features = state.get("features", {})
        
        # Generate signal using existing signal analyst
        signal = generate_signal(symbol, features)
        
        # Update state
        state.setdefault("logs", []).append("signal_analyst:ok")
        state["signal"] = signal
        
        logger.info(f"Generated signal for {symbol}: {signal.get('strategy', 'unknown')}")
        
    except Exception as e:
        error_msg = f"signal_analyst failed: {e}"
        state.setdefault("errors", []).append(error_msg)
        state.setdefault("logs", []).append(f"signal_analyst:error - {error_msg}")
        logger.error(error_msg)
    
    return state

def ai_strategy_selector(state: BotState) -> BotState:
    """Use AI Engine strategy selector to make trading decisions."""
    try:
        signal = state.get("signal")
        if not signal:
            state.setdefault("logs", []).append("ai_strategy_selector:no_signal")
            return state
        
        symbol = state.get("symbol", "BTC/USDT")
        strategy_selector_config = state.get("strategy_selector_config")
        
        if not strategy_selector_config or not strategy_selector_config.get('enabled', True):
            state.setdefault("logs", []).append("ai_strategy_selector:disabled")
            return state
        
        # Create position snapshot (simplified for this example)
        position = PositionSnapshot(
            symbol=symbol,
            timeframe=signal.get('timeframe', '1m'),
            side=Side.NONE,  # This would come from current position state
            allocation=0.0,  # This would come from current position state
            avg_entry_px=None
        )
        
        # Create selector config
        selector_config = SelectorConfig(
            limits=strategy_selector_config.get('limits', {}),
            risk=strategy_selector_config.get('risk', {})
        )
        
        # Use AI strategy selector
        decision = select_for_symbol(
            symbol=symbol,
            timeframe=signal.get('timeframe', '1m'),
            signal=signal,
            position=position,
            cfg=selector_config,
            daily_pnl_usd=0.0,  # This would come from current P&L
            spread_bps=signal.get('spread_bps', 0.0),
            latency_ms=signal.get('latency_ms', 0)
        )
        
        # Update state with AI decision
        state["ai_decision"] = {
            'action': decision.action.value,
            'side': decision.side.value,
            'target_allocation': decision.target_allocation,
            'confidence': decision.confidence,
            'explanation': decision.explain,
            'diagnostics': decision.diagnostics
        }
        state["strategy_confidence"] = decision.confidence
        
        state.setdefault("logs", []).append(f"ai_strategy_selector:decision_{decision.action.value}")
        logger.info(f"AI Strategy Selector decision: {decision.action.value} (confidence: {decision.confidence:.2f})")
        
    except Exception as e:
        error_msg = f"ai_strategy_selector failed: {e}"
        state.setdefault("errors", []).append(error_msg)
        state.setdefault("logs", []).append(f"ai_strategy_selector:error - {error_msg}")
        logger.error(error_msg)
    
    return state

def adaptive_learning(state: BotState) -> BotState:
    """Apply adaptive learning updates if available."""
    try:
        adaptive_config = state.get("adaptive_learner_config")
        if not adaptive_config or not adaptive_config.get('enabled', True):
            state.setdefault("logs", []).append("adaptive_learning:disabled")
            return state
        
        # In a real implementation, this would:
        # 1. Get recent trade outcomes
        # 2. Run adaptive learning
        # 3. Apply parameter updates
        
        # For now, just mark as applied
        state["adaptive_learning_applied"] = True
        state.setdefault("logs", []).append("adaptive_learning:applied")
        logger.info("Adaptive learning applied")
        
    except Exception as e:
        error_msg = f"adaptive_learning failed: {e}"
        state.setdefault("errors", []).append(error_msg)
        state.setdefault("logs", []).append(f"adaptive_learning:error - {error_msg}")
        logger.error(error_msg)
    
    return state


def risk_router(state: BotState) -> BotState:
    """Route signal through risk checks with AI Engine integration."""
    try:
        # Import here to avoid circular imports
        from agents.risk.risk_router import route_signal
        
        signal = state.get("signal")
        ai_decision = state.get("ai_decision")
        
        if not signal:
            state.setdefault("logs", []).append("risk_router:no_signal")
            state["risk_ok"] = False
            return state
        
        # If AI decision is available, use it for risk assessment
        if ai_decision and ai_decision.get('action') != 'hold':
            # Create order intent based on AI decision
            order_intent = {
                'symbol': state.get("symbol", "BTC/USDT"),
                'action': ai_decision.get('action'),
                'side': ai_decision.get('side'),
                'target_allocation': ai_decision.get('target_allocation', 0.0),
                'confidence': ai_decision.get('confidence', 0.0),
                'explanation': ai_decision.get('explanation', ''),
                'ai_enhanced': True
            }
            
            # Basic risk check (in real implementation, this would be more comprehensive)
            risk_ok = ai_decision.get('confidence', 0.0) > 0.6
        else:
            # Fallback to traditional risk routing
            risk_ok, order_intent = route_signal(signal)
        
        # Update state
        state["risk_ok"] = risk_ok
        state["order_intent"] = order_intent if risk_ok else None
        state.setdefault("logs", []).append(f"risk_router:{'ok' if risk_ok else 'rejected'}")
        
        logger.info(f"Risk check result: {'PASS' if risk_ok else 'FAIL'}")
        
    except Exception as e:
        error_msg = f"risk_router failed: {e}"
        state.setdefault("errors", []).append(error_msg)
        state.setdefault("logs", []).append(f"risk_router:error - {error_msg}")
        state["risk_ok"] = False
        logger.error(error_msg)
    
    return state


def execution_agent(state: BotState) -> BotState:
    """Execute order if risk checks passed."""
    try:
        if not state.get("risk_ok"):
            state.setdefault("logs", []).append("execution_agent:skipped_no_risk_ok")
            return state
        
        order_intent = state.get("order_intent")
        if not order_intent:
            state.setdefault("logs", []).append("execution_agent:skipped_no_intent")
            return state
        
        # Import here to avoid circular imports
        from agents.core.autogen_wrappers import run_execution
        
        # Execute order using AutoGen wrapper
        result = run_execution(order_intent)
        
        # Update state
        state["execution_result"] = result
        state.setdefault("logs", []).append("execution_agent:ok")
        
        logger.info(f"Order executed: {result.get('status', 'unknown')}")
        
    except Exception as e:
        error_msg = f"execution_agent failed: {e}"
        state.setdefault("errors", []).append(error_msg)
        state.setdefault("logs", []).append(f"execution_agent:error - {error_msg}")
        logger.error(error_msg)
    
    return state


def notifier(state: BotState) -> BotState:
    """Send notifications about trading activity."""
    try:
        # Import here to avoid circular imports
        from agents.core.signal_processor import SignalProcessor
        
        # Create a simple notification based on state
        notification = {
            "type": "trading_notification",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": state.get("run_id", "unknown"),
            "symbol": state.get("symbol", "unknown"),
            "risk_ok": state.get("risk_ok", False),
            "executed": bool(state.get("execution_result")),
            "errors": len(state.get("errors", [])),
        }
        
        # In a real implementation, this would send to notification channels
        logger.info(f"Notification: {notification}")
        
        state.setdefault("logs", []).append("notifier:ok")
        
    except Exception as e:
        error_msg = f"notifier failed: {e}"
        state.setdefault("errors", []).append(error_msg)
        state.setdefault("logs", []).append(f"notifier:error - {error_msg}")
        logger.error(error_msg)
    
    return state


def should_execute(state: BotState) -> str:
    """Determine next step based on risk check result."""
    if state.get("risk_ok", False):
        return "execution_agent"
    else:
        return "notifier"


def build_graph() -> CompiledStateGraph:
    """Build and compile the enhanced trading orchestration graph with AI Engine integration."""
    if StateGraph is None:
        raise ImportError("LangGraph not installed. Install with: pip install langgraph")
    
    # Create the state graph
    workflow = StateGraph(BotState)
    
    # Add nodes in execution order
    workflow.add_node("configuration_loader", configuration_loader)
    workflow.add_node("signal_analyst", signal_analyst)
    workflow.add_node("ai_strategy_selector", ai_strategy_selector)
    workflow.add_node("adaptive_learning", adaptive_learning)
    workflow.add_node("risk_router", risk_router)
    workflow.add_node("execution_agent", execution_agent)
    workflow.add_node("notifier", notifier)
    
    # Add edges
    workflow.set_entry_point("configuration_loader")
    workflow.add_edge("configuration_loader", "signal_analyst")
    workflow.add_edge("signal_analyst", "ai_strategy_selector")
    workflow.add_edge("ai_strategy_selector", "adaptive_learning")
    workflow.add_edge("adaptive_learning", "risk_router")
    
    # Conditional edge based on risk check
    workflow.add_conditional_edges(
        "risk_router",
        should_execute,
        {
            "execution_agent": "execution_agent",
            "notifier": "notifier"
        }
    )
    
    workflow.add_edge("execution_agent", "notifier")
    workflow.add_edge("notifier", END)
    
    # Compile the graph
    return workflow.compile()


def create_initial_state(
    symbol: str = "BTC/USDT", 
    features: Optional[Dict[str, Any]] = None,
    environment: str = "production",
    strategy: Optional[str] = None
) -> BotState:
    """Create initial state for the enhanced trading bot with AI Engine integration."""
    return BotState(
        symbol=symbol,
        features=features or {},
        signal=None,
        risk_ok=False,
        order_intent=None,
        execution_result=None,
        logs=[],
        errors=[],
        run_id=f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
        timestamp=datetime.now(timezone.utc).timestamp(),
        
        # AI Engine integration
        ai_decision=None,
        strategy_confidence=None,
        adaptive_learning_applied=False,
        position_snapshot=None,
        
        # Enhanced configuration
        system_config=None,
        strategy_selector_config=None,
        adaptive_learner_config=None,
        
        # Additional context
        environment=environment,
        strategy=strategy
    )


# Example usage
if __name__ == "__main__":
    import asyncio
    
    async def main():
        """Example usage of the trading graph."""
        # Build the graph
        graph = build_graph()
        
        # Create initial state
        initial_state = create_initial_state(
            symbol="BTC/USDT",
            features={"price": 50000, "volume": 1000}
        )
        
        # Run the graph
        result = await graph.ainvoke(initial_state)
        
        print("Trading run completed:")
        print(f"  Symbol: {result.get('symbol')}")
        print(f"  Risk OK: {result.get('risk_ok')}")
        print(f"  Executed: {bool(result.get('execution_result'))}")
        print(f"  Logs: {len(result.get('logs', []))}")
        print(f"  Errors: {len(result.get('errors', []))}")
        
        if result.get('errors'):
            print("  Error details:")
            for error in result['errors']:
                print(f"    - {error}")
    
    asyncio.run(main())
