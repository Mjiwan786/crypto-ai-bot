"""
Tests for the new orchestration system.

Tests the LangGraph-based orchestration and AutoGen wrappers.
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from typing import Dict, Any

from orchestration.graph import (
    BotState, create_initial_state, signal_analyst, 
    risk_router, execution_agent, notifier
)
from agents.core.autogen_wrappers import run_execution, emit_signal, check_risk, analyze_market


class TestBotState:
    """Test BotState creation and manipulation."""
    
    def test_create_initial_state(self):
        """Test creating initial bot state."""
        state = create_initial_state("BTC/USDT", {"price": 50000})
        
        assert state["symbol"] == "BTC/USDT"
        assert state["features"]["price"] == 50000
        assert state["signal"] is None
        assert state["risk_ok"] is False
        assert state["order_intent"] is None
        assert state["execution_result"] is None
        assert isinstance(state["logs"], list)
        assert isinstance(state["errors"], list)
        assert "run_" in state["run_id"]
        assert isinstance(state["timestamp"], float)


class TestOrchestrationNodes:
    """Test individual orchestration nodes."""
    
    @patch('agents.core.signal_analyst.generate_signal')
    def test_signal_analyst_success(self, mock_generate_signal):
        """Test successful signal generation."""
        mock_signal = {
            "symbol": "BTC/USDT",
            "strategy": "momentum",
            "side": "buy",
            "timestamp": 1234567890.0
        }
        mock_generate_signal.return_value = mock_signal
        
        state = create_initial_state("BTC/USDT", {"price": 50000})
        result = signal_analyst(state)
        
        assert result["signal"] == mock_signal
        assert "signal_analyst:ok" in result["logs"]
        assert len(result["errors"]) == 0
    
    @patch('agents.core.signal_analyst.generate_signal')
    def test_signal_analyst_failure(self, mock_generate_signal):
        """Test signal generation failure handling."""
        mock_generate_signal.side_effect = Exception("Signal generation failed")
        
        state = create_initial_state("BTC/USDT", {"price": 50000})
        result = signal_analyst(state)
        
        assert result["signal"] is None
        assert "signal_analyst:error" in result["logs"][0]
        assert len(result["errors"]) == 1
        assert "Signal generation failed" in result["errors"][0]
    
    @patch('agents.risk.risk_router.route_signal')
    def test_risk_router_pass(self, mock_route_signal):
        """Test risk router passing a signal."""
        mock_route_signal.return_value = (True, {"amount": 0.001, "side": "buy"})
        
        state = create_initial_state("BTC/USDT")
        state["signal"] = {"symbol": "BTC/USDT", "strategy": "momentum"}
        result = risk_router(state)
        
        assert result["risk_ok"] is True
        assert result["order_intent"] == {"amount": 0.001, "side": "buy"}
        assert "risk_router:ok" in result["logs"]
    
    @patch('agents.risk.risk_router.route_signal')
    def test_risk_router_reject(self, mock_route_signal):
        """Test risk router rejecting a signal."""
        mock_route_signal.return_value = (False, None)
        
        state = create_initial_state("BTC/USDT")
        state["signal"] = {"symbol": "BTC/USDT", "strategy": "momentum"}
        result = risk_router(state)
        
        assert result["risk_ok"] is False
        assert result["order_intent"] is None
        assert "risk_router:rejected" in result["logs"]
    
    def test_execution_agent_skip_no_risk(self):
        """Test execution agent skipping when risk check failed."""
        state = create_initial_state("BTC/USDT")
        state["risk_ok"] = False
        result = execution_agent(state)
        
        assert "execution_agent:skipped_no_risk_ok" in result["logs"]
        assert result["execution_result"] is None
    
    def test_execution_agent_skip_no_intent(self):
        """Test execution agent skipping when no order intent."""
        state = create_initial_state("BTC/USDT")
        state["risk_ok"] = True
        state["order_intent"] = None
        result = execution_agent(state)
        
        assert "execution_agent:skipped_no_intent" in result["logs"]
        assert result["execution_result"] is None
    
    @patch('agents.core.autogen_wrappers.run_execution')
    def test_execution_agent_success(self, mock_run_execution):
        """Test successful order execution."""
        mock_result = {"status": "success", "order_id": "12345"}
        mock_run_execution.return_value = mock_result
        
        state = create_initial_state("BTC/USDT")
        state["risk_ok"] = True
        state["order_intent"] = {"amount": 0.001, "side": "buy"}
        result = execution_agent(state)
        
        assert result["execution_result"] == mock_result
        assert "execution_agent:ok" in result["logs"]
    
    def test_notifier_success(self):
        """Test notification sending."""
        state = create_initial_state("BTC/USDT")
        state["risk_ok"] = True
        state["execution_result"] = {"status": "success"}
        result = notifier(state)
        
        assert "notifier:ok" in result["logs"]
        assert len(result["errors"]) == 0


class TestAutoGenWrappers:
    """Test AutoGen wrapper functions."""
    
    @patch('agents.core.execution_agent.EnhancedExecutionAgent')
    def test_run_execution_success(self, mock_execution_agent_class):
        """Test successful order execution via AutoGen wrapper."""
        mock_agent = Mock()
        mock_result = Mock()
        mock_result.order_id = "12345"
        mock_result.fill_price = 50000.0
        mock_agent.execute_signal = AsyncMock(return_value=mock_result)
        mock_execution_agent_class.return_value = mock_agent
        
        order_intent = {"symbol": "BTC/USDT", "side": "buy", "amount": 0.001}
        result = run_execution(order_intent)
        
        assert result["status"] == "success"
        assert result["order_id"] == "12345"
        assert result["fill_price"] == 50000.0
    
    @patch('agents.core.execution_agent.EnhancedExecutionAgent')
    def test_run_execution_failure(self, mock_execution_agent_class):
        """Test order execution failure handling."""
        mock_agent = Mock()
        mock_agent.execute_signal = AsyncMock(return_value=None)
        mock_execution_agent_class.return_value = mock_agent
        
        order_intent = {"symbol": "BTC/USDT", "side": "buy", "amount": 0.001}
        result = run_execution(order_intent)
        
        assert result["status"] == "failed"
        assert "No result from execution agent" in result["error"]
    
    def test_emit_signal_success(self):
        """Test successful signal emission."""
        signal = {"symbol": "BTC/USDT", "strategy": "momentum"}
        result = emit_signal(signal)
        
        # Should return True for successful emission
        assert result is True
    
    @patch('agents.risk.risk_router.route_signal')
    def test_check_risk_success(self, mock_route_signal):
        """Test successful risk checking."""
        mock_route_signal.return_value = (True, {"amount": 0.001})
        
        signal = {"symbol": "BTC/USDT", "strategy": "momentum"}
        result = check_risk(signal)
        
        assert result["risk_ok"] is True
        assert result["order_intent"] == {"amount": 0.001}
    
    @patch('agents.core.signal_analyst.generate_signal')
    def test_analyze_market_success(self, mock_generate_signal):
        """Test successful market analysis."""
        mock_signal = {"symbol": "BTC/USDT", "strategy": "momentum"}
        mock_generate_signal.return_value = mock_signal
        
        result = analyze_market("BTC/USDT", {"price": 50000})
        
        assert result["signal"] == mock_signal
        assert "timestamp" in result


class TestIntegration:
    """Test integration between components."""
    
    @pytest.mark.asyncio
    async def test_full_orchestration_flow(self):
        """Test complete orchestration flow."""
        # Mock all external dependencies
        with patch('agents.core.signal_analyst.generate_signal') as mock_generate_signal, \
             patch('agents.risk.risk_router.route_signal') as mock_route_signal, \
             patch('agents.core.autogen_wrappers.run_execution') as mock_run_execution:
            
            # Set up mocks
            mock_generate_signal.return_value = {
                "symbol": "BTC/USDT",
                "strategy": "momentum",
                "side": "buy",
                "timestamp": 1234567890.0
            }
            mock_route_signal.return_value = (True, {"amount": 0.001, "side": "buy"})
            mock_run_execution.return_value = {"status": "success", "order_id": "12345"}
            
            # Create initial state
            state = create_initial_state("BTC/USDT", {"price": 50000})
            
            # Run through the flow
            state = signal_analyst(state)
            state = risk_router(state)
            state = execution_agent(state)
            state = notifier(state)
            
            # Verify results
            assert state["signal"] is not None
            assert state["risk_ok"] is True
            assert state["order_intent"] is not None
            assert state["execution_result"] is not None
            assert len(state["errors"]) == 0


if __name__ == "__main__":
    pytest.main([__file__])
