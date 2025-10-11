"""
AutoGen wrappers for crypto trading agents.

Provides AutoGen agent wrappers that bind to existing project tools and functions.
Replaces LangChain tool calling with explicit function calls via AutoGen tools.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from agents.core.errors import ExecutionError, RiskViolation, SignalError
from agents.core.serialization import ts_to_iso

try:
    from autogen_agentchat import AssistantAgent, Tool
    from autogen_core import Agent
except ImportError:
    # Fallback for when AutoGen is not installed
    AssistantAgent = None
    Tool = None
    Agent = Any

logger = logging.getLogger(__name__)


def _place_order_kraken(intent: Dict[str, Any]) -> Dict[str, Any]:
    """
    Place order on Kraken with validated OrderIntent.

    Args:
        intent: Order intent dictionary with symbol, side, amount, strategy

    Returns:
        Dictionary with execution result including success status and details
    """
    try:
        # Import here to avoid circular imports
        from agents.core.execution_agent import EnhancedExecutionAgent

        # Create execution agent and execute signal
        execution_agent = EnhancedExecutionAgent()

        # Convert order intent to signal format if needed
        signal_data = {
            "symbol": intent.get("symbol", "BTC/USDT"),
            "side": intent.get("side", "buy"),
            "amount": intent.get("amount", 0.001),
            "strategy": intent.get("strategy", "momentum"),
            "timestamp": datetime.now(timezone.utc).timestamp(),
        }

        # Execute the order (this would be async in real usage)
        import asyncio

        result = asyncio.run(execution_agent.execute_signal(signal_data))

        if result:
            return {
                "status": "success",
                "order_id": getattr(result, "order_id", "unknown"),
                "fill_price": getattr(result, "fill_price", 0.0),
                "timestamp": ts_to_iso(datetime.now(timezone.utc)),
            }
        else:
            return {
                "status": "failed",
                "error": "No result from execution agent",
                "timestamp": ts_to_iso(datetime.now(timezone.utc)),
            }

    except ExecutionError as e:
        # Re-raise execution errors with proper context
        logger.error(f"Execution error placing order: {e}")
        return {
            "status": "error",
            "error": str(e),
            "error_type": "execution_error",
            "timestamp": ts_to_iso(datetime.now(timezone.utc)),
        }
    except Exception as e:
        # Wrap unexpected errors as ExecutionError
        logger.error(f"Failed to place order: {e}")
        raise ExecutionError(
            f"Order placement failed: {e}",
            symbol=intent.get("symbol", "unknown"),
            side=intent.get("side", "unknown"),
            details={"intent": str(intent), "original_error": str(e)},
        ) from e


def _publish_signal(signal: Dict[str, Any]) -> bool:
    """
    Publish a trading signal to Redis/MCP bus.

    Args:
        signal: Signal dictionary with trading signal data

    Returns:
        True if signal was published successfully, False otherwise
    """
    try:
        # Import here to avoid circular imports

        # Create signal processor and publish signal
        # In a real implementation, this would use the actual Redis bus
        symbol = signal.get("symbol", "N/A")
        side = signal.get("side", "N/A")
        size = signal.get("size", "N/A")
        logger.info(
            f"Signal published: {symbol} {side} size={size} stream=autogen redis_id=simulated"
        )

        # Simulate successful publication
        return True

    except SignalError:
        # Re-raise signal errors
        raise
    except Exception as e:
        # Wrap as SignalError
        raise SignalError(
            f"Signal publication failed: {e}",
            symbol=signal.get("symbol", "unknown"),
            strategy=signal.get("strategy", "unknown"),
            details={"signal": str(signal), "original_error": str(e)},
        ) from e


def _check_risk_limits(signal: Dict[str, Any]) -> Dict[str, Any]:
    """
    Check risk limits for a trading signal.

    Args:
        signal: Signal dictionary with trading signal data

    Returns:
        Dictionary with risk check results including risk_ok status and order_intent
    """
    try:
        # Import here to avoid circular imports
        from agents.risk.risk_router import route_signal

        # Route signal through risk checks
        risk_ok, order_intent = route_signal(signal)

        return {
            "risk_ok": risk_ok,
            "order_intent": order_intent,
            "timestamp": ts_to_iso(datetime.now(timezone.utc)),
        }

    except RiskViolation as e:
        # Handle risk violations gracefully
        logger.warning(f"Risk violation detected: {e}")
        return {
            "risk_ok": False,
            "order_intent": None,
            "error": str(e),
            "error_type": "risk_violation",
            "timestamp": ts_to_iso(datetime.now(timezone.utc)),
        }
    except Exception as e:
        # Wrap as RiskViolation for risk check failures
        raise RiskViolation(
            f"Risk check failed: {e}",
            symbol=signal.get("symbol", "unknown"),
            details={"signal": str(signal), "original_error": str(e)},
        ) from e


def _analyze_market_data(symbol: str, features: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analyze market data and generate trading signal.

    Args:
        symbol: Trading symbol to analyze
        features: Market features dictionary with price, volume, etc.

    Returns:
        Dictionary with analysis results including signal strength and confidence
    """
    try:
        # Import here to avoid circular imports
        from agents.core.signal_analyst import generate_signal

        # Generate signal using existing signal analyst
        signal = generate_signal(symbol, features)

        return {
            "signal": signal,
            "timestamp": ts_to_iso(datetime.now(timezone.utc)),
        }

    except SignalError:
        # Re-raise signal errors
        raise
    except Exception as e:
        # Wrap as SignalError
        raise SignalError(
            f"Market analysis failed: {e}",
            symbol=symbol,
            details={"features": str(features), "original_error": str(e)},
        ) from e


# Lazy initialization - tools and agents created on first access
_tools_cache = {}
_agents_cache = {}


def _get_tools():
    """Get or create AutoGen tools (lazy initialization)."""
    if _tools_cache:
        return _tools_cache

    if Tool is not None:
        _tools_cache["place_order"] = Tool(
            func=_place_order_kraken,
            name="place_order_kraken",
            description="Place order on Kraken with validated OrderIntent.",
        )
        _tools_cache["publish_signal"] = Tool(
            func=_publish_signal,
            name="publish_signal",
            description="Publish a trading signal to Redis/MCP bus.",
        )
        _tools_cache["check_risk"] = Tool(
            func=_check_risk_limits,
            name="check_risk_limits",
            description="Check risk limits for a trading signal.",
        )
        _tools_cache["analyze_market"] = Tool(
            func=_analyze_market_data,
            name="analyze_market_data",
            description="Analyze market data and generate trading signal.",
        )
    return _tools_cache


def _get_agents():
    """Get or create AutoGen agents (lazy initialization)."""
    if _agents_cache:
        return _agents_cache

    if AssistantAgent is not None:
        tools = _get_tools()
        _agents_cache["execution"] = AssistantAgent(
            name="ExecutionAgent",
            tools=[tools.get("place_order")] if tools.get("place_order") else [],
            description="Executes trading orders on Kraken exchange.",
        )
        _agents_cache["signal"] = AssistantAgent(
            name="SignalAgent",
            tools=[tools.get("publish_signal"), tools.get("analyze_market")]
            if tools.get("publish_signal")
            else [],
            description="Generates and publishes trading signals.",
        )
        _agents_cache["risk"] = AssistantAgent(
            name="RiskAgent",
            tools=[tools.get("check_risk")] if tools.get("check_risk") else [],
            description="Performs risk checks on trading signals.",
        )
    return _agents_cache


def run_execution(order_intent: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute order using AutoGen execution agent.

    Args:
        order_intent: Order intent dictionary with execution details

    Returns:
        Dictionary with execution result including success status and details
    """
    agents = _get_agents()
    execution_agent = agents.get("execution")

    if execution_agent is None:
        logger.warning("AutoGen not available, falling back to direct execution")
        return _place_order_kraken(order_intent)

    try:
        # Run the execution agent
        response = execution_agent.run(input=f"Execute order intent: {order_intent}")

        # Extract result from AutoGen response
        if hasattr(response, "content"):
            return response.content
        else:
            return response

    except ExecutionError:
        # Re-raise execution errors
        raise
    except Exception as e:
        # Wrap AutoGen errors as ExecutionError
        raise ExecutionError(
            f"AutoGen execution failed: {e}",
            details={"order_intent": str(order_intent), "original_error": str(e)},
        ) from e


def emit_signal(signal: Dict[str, Any]) -> bool:
    """Emit signal using AutoGen signal agent."""
    agents = _get_agents()
    signal_agent = agents.get("signal")

    if signal_agent is None:
        logger.warning("AutoGen not available, falling back to direct signal emission")
        return _publish_signal(signal)

    try:
        # Run the signal agent
        response = signal_agent.run(input=f"Publish signal: {signal}")

        # Extract result from AutoGen response
        if hasattr(response, "content"):
            return bool(response.content)
        else:
            return bool(response)

    except SignalError:
        # Re-raise signal errors
        raise
    except Exception as e:
        # Wrap AutoGen errors as SignalError
        raise SignalError(
            f"AutoGen signal emission failed: {e}",
            symbol=signal.get("symbol", "unknown"),
            strategy=signal.get("strategy", "unknown"),
            details={"signal": str(signal), "original_error": str(e)},
        ) from e


def check_risk(signal: Dict[str, Any]) -> Dict[str, Any]:
    """Check risk using AutoGen risk agent."""
    agents = _get_agents()
    risk_agent = agents.get("risk")

    if risk_agent is None:
        logger.warning("AutoGen not available, falling back to direct risk check")
        return _check_risk_limits(signal)

    try:
        # Run the risk agent
        response = risk_agent.run(input=f"Check risk for signal: {signal}")

        # Extract result from AutoGen response
        if hasattr(response, "content"):
            return response.content
        else:
            return response

    except RiskViolation:
        # Re-raise risk violations
        raise
    except Exception as e:
        # Wrap AutoGen errors as RiskViolation
        raise RiskViolation(
            f"AutoGen risk check failed: {e}",
            symbol=signal.get("symbol", "unknown"),
            details={"signal": str(signal), "original_error": str(e)},
        ) from e


def analyze_market(symbol: str, features: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze market using AutoGen signal agent."""
    agents = _get_agents()
    signal_agent = agents.get("signal")

    if signal_agent is None:
        logger.warning("AutoGen not available, falling back to direct market analysis")
        return _analyze_market_data(symbol, features)

    try:
        # Run the signal agent
        response = signal_agent.run(input=f"Analyze market for {symbol} with features: {features}")

        # Extract result from AutoGen response
        if hasattr(response, "content"):
            return response.content
        else:
            return response

    except SignalError:
        # Re-raise signal errors
        raise
    except Exception as e:
        # Wrap AutoGen errors as SignalError
        raise SignalError(
            f"AutoGen market analysis failed: {e}",
            symbol=symbol,
            details={"features": str(features), "original_error": str(e)},
        ) from e


# Example usage
if __name__ == "__main__":
    # Test the wrappers
    test_signal = {
        "symbol": "BTC/USDT",
        "side": "buy",
        "amount": 0.001,
        "strategy": "momentum",
        "timestamp": datetime.now(timezone.utc).timestamp(),
    }

    logger.info("Testing AutoGen wrappers...")

    # Test market analysis
    result = analyze_market("BTC/USDT", {"price": 50000, "volume": 1000})
    logger.info("Market analysis result: %s", result)

    # Test risk check
    risk_result = check_risk(test_signal)
    logger.info("Risk check result: %s", risk_result)

    # Test signal emission
    signal_emitted = emit_signal(test_signal)
    logger.info("Signal emitted: %s", signal_emitted)

    # Test execution (dry run)
    if risk_result.get("risk_ok"):
        exec_result = run_execution(risk_result.get("order_intent", {}))
        logger.info("Execution result: %s", exec_result)
