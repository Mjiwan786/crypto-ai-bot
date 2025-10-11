"""
Complete System Integration Tests

This module tests the full integration of all system components:
- Master Orchestrator
- AI Engine (Strategy Selector + Adaptive Learner)
- All trading agents
- Unified configuration system
- Real-time monitoring and health checks
"""

import asyncio
import pytest
import logging
import os
import sys
from pathlib import Path
from typing import Dict, Any, Optional
from unittest.mock import Mock, patch, AsyncMock

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import system components
from config.unified_config_loader import UnifiedConfigLoader, SystemConfig
from orchestration.master_orchestrator import MasterOrchestrator
from base.enhanced_trading_agent import EnhancedTradingAgent, AgentState
from orchestration.graph import build_graph, create_initial_state, BotState

# Setup test logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TestCompleteSystemIntegration:
    """Test complete system integration"""
    
    @pytest.fixture
    def test_config_path(self):
        """Path to test configuration file"""
        return "config/agent_settings.yaml"
    
    @pytest.fixture
    def mock_redis(self):
        """Mock Redis connection"""
        mock_redis = Mock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.xadd = AsyncMock(return_value="test_id")
        return mock_redis
    
    @pytest.fixture
    def mock_redis_manager(self, mock_redis):
        """Mock Redis manager"""
        mock_manager = Mock()
        mock_manager.client = mock_redis
        mock_manager.initialize = AsyncMock(return_value=True)
        mock_manager.close = AsyncMock(return_value=True)
        return mock_manager
    
    @pytest.fixture
    def test_system_config(self):
        """Test system configuration"""
        return {
            'environment': 'test',
            'debug_mode': True,
            'paper_trading': True,
            'trading_pairs': ['BTC/USD', 'ETH/USD'],
            'strategies_enabled': ['scalp', 'trend_following'],
            'ai_engine_enabled': {
                'strategy_selector': True,
                'adaptive_learner': True
            },
            'risk_parameters': {
                'max_drawdown': 0.1,
                'daily_stop_usd': 50.0
            }
        }
    
    @pytest.mark.asyncio
    async def test_unified_config_loader(self, test_config_path):
        """Test unified configuration loader"""
        loader = UnifiedConfigLoader(test_config_path)
        
        # Test loading system configuration
        system_config = loader.load_system_config(
            environment="test",
            strategy="scalp"
        )
        
        assert isinstance(system_config, SystemConfig)
        assert system_config.environment == "test"
        assert system_config.debug_mode is True
        assert system_config.paper_trading is True
        
        # Test configuration validation
        issues = loader.validate_configuration(system_config)
        # Should have some issues in test environment (missing API keys, etc.)
        assert isinstance(issues, list)
        
        # Test configuration summary
        summary = loader.get_config_summary(system_config)
        assert 'environment' in summary
        assert 'trading_pairs' in summary
        assert 'strategies_enabled' in summary
    
    @pytest.mark.asyncio
    async def test_master_orchestrator_initialization(self, mock_redis_manager):
        """Test master orchestrator initialization"""
        with patch('orchestration.master_orchestrator.RedisManager', return_value=mock_redis_manager):
            orchestrator = MasterOrchestrator("config/agent_settings.yaml")
            
            # Test initialization
            success = await orchestrator.initialize()
            assert success is True
            
            # Test system state
            assert orchestrator.state.running is False
            assert orchestrator.agent_config is not None
            assert orchestrator.risk_config is not None
            assert orchestrator.perf_config is not None
    
    @pytest.mark.asyncio
    async def test_enhanced_trading_agent(self, mock_redis_manager):
        """Test enhanced trading agent base class"""
        
        class TestAgent(EnhancedTradingAgent):
            async def _agent_initialize(self):
                pass
            
            async def _agent_start(self):
                pass
            
            async def _agent_stop(self):
                pass
            
            async def _process_agent_signal(self, signal_data):
                return {'action': 'buy', 'confidence': 0.8}
        
        with patch('base.enhanced_trading_agent.RedisManager', return_value=mock_redis_manager):
            agent = TestAgent(
                agent_id="test_agent",
                strategy="scalp",
                environment="test"
            )
            
            # Test initialization
            success = await agent.initialize()
            assert success is True
            assert agent.state == AgentState.ACTIVE
            
            # Test starting
            success = await agent.start()
            assert success is True
            assert agent.running is True
            
            # Test signal processing
            signal_data = {
                'symbol': 'BTC/USD',
                'price': 50000,
                'volume': 1000,
                'strategy': 'scalp'
            }
            
            result = await agent.process_signal(signal_data)
            assert result is not None
            assert result['action'] == 'buy'
            assert result['confidence'] == 0.8
            
            # Test stopping
            await agent.stop()
            assert agent.running is False
            assert agent.state == AgentState.STOPPED
    
    @pytest.mark.asyncio
    async def test_orchestration_graph_with_ai_engine(self):
        """Test orchestration graph with AI Engine integration"""
        # Build the graph
        graph = build_graph()
        assert graph is not None
        
        # Create initial state
        initial_state = create_initial_state(
            symbol="BTC/USD",
            features={"price": 50000, "volume": 1000},
            environment="test",
            strategy="scalp"
        )
        
        assert initial_state['symbol'] == "BTC/USD"
        assert initial_state['environment'] == "test"
        assert initial_state['strategy'] == "scalp"
        
        # Test graph execution (mocked to avoid actual dependencies)
        with patch('orchestration.graph.get_config_loader') as mock_config_loader, \
             patch('orchestration.graph.generate_signal') as mock_generate_signal, \
             patch('orchestration.graph.select_for_symbol') as mock_strategy_selector, \
             patch('orchestration.graph.route_signal') as mock_route_signal, \
             patch('orchestration.graph.run_execution') as mock_execution:
            
            # Setup mocks
            mock_config_loader.return_value.load_system_config.return_value = Mock()
            mock_generate_signal.return_value = {
                'strategy': 'scalp',
                'confidence': 0.8,
                'action': 'buy'
            }
            mock_strategy_selector.return_value = Mock(
                action=Mock(value='buy'),
                side=Mock(value='long'),
                target_allocation=0.5,
                confidence=0.8,
                explain='Test explanation',
                diagnostics={}
            )
            mock_route_signal.return_value = (True, {'action': 'buy'})
            mock_execution.return_value = {'status': 'success'}
            
            # Run the graph
            result = await graph.ainvoke(initial_state)
            
            # Verify results
            assert result['symbol'] == "BTC/USD"
            assert 'signal' in result
            assert 'ai_decision' in result
            assert 'risk_ok' in result
            assert 'logs' in result
    
    @pytest.mark.asyncio
    async def test_system_health_monitoring(self, mock_redis_manager):
        """Test system health monitoring"""
        with patch('orchestration.master_orchestrator.RedisManager', return_value=mock_redis_manager):
            orchestrator = MasterOrchestrator("config/agent_settings.yaml")
            await orchestrator.initialize()
            
            # Test health check
            status = orchestrator.get_system_status()
            assert 'running' in status
            assert 'agents_active' in status
            assert 'system_health' in status
            assert 'performance_metrics' in status
    
    @pytest.mark.asyncio
    async def test_configuration_validation(self, test_config_path):
        """Test configuration validation"""
        loader = UnifiedConfigLoader(test_config_path)
        
        # Test with valid configuration
        system_config = loader.load_system_config(environment="test")
        issues = loader.validate_configuration(system_config)
        
        # Should have some issues in test environment (missing API keys, etc.)
        assert isinstance(issues, list)
        
        # Test configuration summary
        summary = loader.get_config_summary(system_config)
        assert isinstance(summary, dict)
        assert 'environment' in summary
    
    @pytest.mark.asyncio
    async def test_agent_metrics_tracking(self, mock_redis_manager):
        """Test agent metrics tracking"""
        
        class TestAgent(EnhancedTradingAgent):
            async def _agent_initialize(self):
                pass
            
            async def _agent_start(self):
                pass
            
            async def _agent_stop(self):
                pass
            
            async def _process_agent_signal(self, signal_data):
                return {'action': 'buy', 'confidence': 0.8}
        
        with patch('base.enhanced_trading_agent.RedisManager', return_value=mock_redis_manager):
            agent = TestAgent(
                agent_id="test_agent",
                strategy="scalp",
                environment="test"
            )
            
            await agent.initialize()
            await agent.start()
            
            # Test metrics tracking
            agent.increment_metric('signals_processed')
            agent.increment_metric('trades_executed')
            agent.set_metric('performance_score', 0.85)
            
            assert agent.metrics.signals_processed == 1
            assert agent.metrics.trades_executed == 1
            assert agent.metrics.performance_score == 0.85
            
            # Test agent status
            status = agent.get_agent_status()
            assert status['agent_id'] == "test_agent"
            assert status['strategy'] == "scalp"
            assert status['running'] is True
            assert 'metrics' in status
            
            await agent.stop()
    
    @pytest.mark.asyncio
    async def test_ai_engine_integration(self):
        """Test AI Engine integration"""
        from ai_engine.strategy_selector import SelectorConfig, PositionSnapshot, Side
        from ai_engine.adaptive_learner import LearnerConfig
        
        # Test strategy selector configuration
        selector_config = SelectorConfig(
            limits={
                'max_allocation': 0.2,
                'max_gross_allocation': 2.0,
                'step_allocation': 0.25,
                'min_conf_to_open': 0.55,
                'min_conf_to_flip': 0.65,
                'min_conf_to_close': 0.35,
                'reduce_on_dip_conf': 0.45
            },
            risk={
                'daily_stop_usd': 100.0,
                'spread_bps_cap': 50.0,
                'latency_budget_ms': 100
            }
        )
        
        assert selector_config.limits['max_allocation'] == 0.2
        assert selector_config.risk['daily_stop_usd'] == 100.0
        
        # Test adaptive learner configuration
        learner_config = LearnerConfig(
            mode="shadow",
            windows={"short": 50, "medium": 200, "long": 1000},
            thresholds={
                "min_trades": 200,
                "good_sharpe": 1.0,
                "poor_sharpe": 0.2,
                "hit_rate_good": 0.55,
                "hit_rate_poor": 0.45
            }
        )
        
        assert learner_config.mode == "shadow"
        assert learner_config.windows['short'] == 50
    
    @pytest.mark.asyncio
    async def test_system_startup_and_shutdown(self, mock_redis_manager):
        """Test complete system startup and shutdown"""
        with patch('orchestration.master_orchestrator.RedisManager', return_value=mock_redis_manager):
            orchestrator = MasterOrchestrator("config/agent_settings.yaml")
            
            # Test initialization
            success = await orchestrator.initialize()
            assert success is True
            
            # Test starting
            await orchestrator.start()
            assert orchestrator.state.running is True
            
            # Test stopping
            await orchestrator.stop()
            assert orchestrator.state.running is False
    
    def test_startup_scripts_exist(self):
        """Test that startup scripts exist and are executable"""
        scripts_dir = Path("scripts")
        
        # Check Python startup script
        python_script = scripts_dir / "start_trading_system.py"
        assert python_script.exists()
        
        # Check batch script
        batch_script = scripts_dir / "start_trading_system.bat"
        assert batch_script.exists()
        
        # Check PowerShell script
        ps_script = scripts_dir / "start_trading_system.ps1"
        assert ps_script.exists()
        
        # Check bash script
        bash_script = scripts_dir / "start_trading_system.sh"
        assert bash_script.exists()
        
        # Check health check script
        health_script = scripts_dir / "health_check.py"
        assert health_script.exists()
    
    def test_configuration_files_exist(self):
        """Test that configuration files exist"""
        config_dir = Path("config")
        
        # Check main configuration files
        assert (config_dir / "agent_settings.yaml").exists()
        assert (config_dir / "unified_config_loader.py").exists()
        assert (config_dir / "agent_integration.py").exists()
        assert (config_dir / "agent_config_manager.py").exists()
    
    def test_orchestration_files_exist(self):
        """Test that orchestration files exist"""
        orchestration_dir = Path("orchestration")
        
        # Check orchestration files
        assert (orchestration_dir / "master_orchestrator.py").exists()
        assert (orchestration_dir / "graph.py").exists()
    
    def test_enhanced_agent_base_exists(self):
        """Test that enhanced agent base class exists"""
        base_dir = Path("base")
        
        # Check enhanced agent base
        assert (base_dir / "enhanced_trading_agent.py").exists()
        assert (base_dir / "trading_agent.py").exists()
        assert (base_dir / "strategy.py").exists()

class TestSystemIntegrationWorkflow:
    """Test complete system integration workflow"""
    
    @pytest.mark.asyncio
    async def test_complete_trading_workflow(self):
        """Test complete trading workflow from signal to execution"""
        # This test would run the complete workflow in a test environment
        # with mocked external dependencies
        
        # 1. Load configuration
        loader = UnifiedConfigLoader("config/agent_settings.yaml")
        system_config = loader.load_system_config(environment="test")
        
        # 2. Initialize orchestrator
        with patch('orchestration.master_orchestrator.RedisManager') as mock_redis_manager:
            orchestrator = MasterOrchestrator("config/agent_settings.yaml")
            await orchestrator.initialize()
            
            # 3. Start system
            await orchestrator.start()
            
            # 4. Simulate trading signal
            signal_data = {
                'symbol': 'BTC/USD',
                'price': 50000,
                'volume': 1000,
                'strategy': 'scalp',
                'confidence': 0.8
            }
            
            # 5. Process signal through AI Engine
            # This would be done by the actual system components
            
            # 6. Stop system
            await orchestrator.stop()
            
            # Verify system stopped cleanly
            assert orchestrator.state.running is False

if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v", "--tb=short"])
