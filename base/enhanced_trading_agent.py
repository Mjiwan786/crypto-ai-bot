"""
Enhanced Trading Agent Base Class

All agents inherit from this class to ensure consistent integration
with the AI engine, configuration system, and monitoring.
"""

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import sys

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import unified configuration
from config.agent_integration import (
    get_merged_config,
    get_risk_parameters,
    get_performance_settings
)

# Import AI engine components
from ai_engine.strategy_selector import select_for_symbol, SelectorConfig
from ai_engine.adaptive_learner import gated_update, LearnerConfig

# Import MCP components
try:
    from mcp.redis_manager import RedisManager
    from mcp.context import MCPContext
    HAS_MCP = True
except ImportError:
    HAS_MCP = False
    RedisManager = None
    MCPContext = None

class AgentState(Enum):
    """Agent state enumeration"""
    INITIALIZING = "initializing"
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"
    SHUTTING_DOWN = "shutting_down"
    STOPPED = "stopped"

@dataclass
class AgentMetrics:
    """Standardized agent metrics"""
    signals_processed: int = 0
    trades_executed: int = 0
    errors_count: int = 0
    last_activity: float = 0.0
    performance_score: float = 0.0

class EnhancedTradingAgent(ABC):
    """
    Enhanced base class for all trading agents with full system integration
    """
    
    def __init__(
        self,
        agent_id: str,
        strategy: str,
        environment: str = "production",
        config_path: Optional[str] = None
    ):
        self.agent_id = agent_id
        self.strategy = strategy
        self.environment = environment
        self.config_path = config_path
        
        # Setup logging
        self.logger = logging.getLogger(f"agent.{agent_id}")
        
        # State management
        self.state = AgentState.INITIALIZING
        self.metrics = AgentMetrics()
        self.running = False
        
        # Configuration (loaded in initialize)
        self.config: Optional[Dict[str, Any]] = None
        self.risk_config: Optional[Dict[str, Any]] = None
        self.perf_config: Optional[Dict[str, Any]] = None
        
        # AI Engine components
        self.strategy_selector_config: Optional[SelectorConfig] = None
        self.adaptive_learner_config: Optional[LearnerConfig] = None
        
        # Infrastructure
        self.redis_manager: Optional[RedisManager] = None
        self.mcp_context: Optional[MCPContext] = None
        
        # Background tasks
        self.tasks: List[asyncio.Task] = []
        
        self.logger.info(f"Enhanced agent {agent_id} initialized for strategy {strategy}")
    
    async def initialize(self) -> bool:
        """Initialize the agent with full system integration"""
        try:
            self.logger.info(f"🔧 Initializing agent {self.agent_id}...")
            
            # 1. Load unified configuration
            await self._load_configuration()
            
            # 2. Initialize AI engine components
            await self._initialize_ai_engine()
            
            # 3. Initialize infrastructure
            await self._initialize_infrastructure()
            
            # 4. Agent-specific initialization
            await self._agent_initialize()
            
            self.state = AgentState.ACTIVE
            self.logger.info(f"✅ Agent {self.agent_id} initialized successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize agent {self.agent_id}: {e}")
            self.state = AgentState.ERROR
            return False
    
    async def _load_configuration(self):
        """Load unified configuration for this agent"""
        from config.agent_integration import AgentConfigIntegrator
        
        integrator = AgentConfigIntegrator(self.config_path)
        
        # Load merged configuration
        self.config = integrator.get_merged_config(
            strategy=self.strategy,
            environment=self.environment
        )
        
        # Load risk parameters
        self.risk_config = integrator.get_risk_parameters(
            strategy=self.strategy,
            environment=self.environment
        )
        
        # Load performance settings
        self.perf_config = integrator.get_performance_settings(
            strategy=self.strategy,
            environment=self.environment
        )
        
        self.logger.debug(f"Configuration loaded for {self.strategy} in {self.environment}")
    
    async def _initialize_ai_engine(self):
        """Initialize AI engine components"""
        # Strategy selector configuration
        self.strategy_selector_config = SelectorConfig(
            limits={
                'max_allocation': self.risk_config.get('max_drawdown', 0.2),
                'max_gross_allocation': 2.0,
                'step_allocation': 0.25,
                'min_conf_to_open': 0.55,
                'min_conf_to_flip': 0.65,
                'min_conf_to_close': 0.35,
                'reduce_on_dip_conf': 0.45
            },
            risk={
                'daily_stop_usd': self.risk_config.get('daily_stop_usd', 100.0),
                'spread_bps_cap': 50.0,
                'latency_budget_ms': 100
            }
        )
        
        # Adaptive learner configuration
        self.adaptive_learner_config = LearnerConfig(
            mode="shadow",  # Start in shadow mode
            windows={"short": 50, "medium": 200, "long": 1000}
        )
        
        self.logger.debug("AI engine components initialized")
    
    async def _initialize_infrastructure(self):
        """Initialize Redis and MCP infrastructure"""
        if not HAS_MCP:
            self.logger.warning("MCP not available, running without Redis integration")
            return
        
        try:
            # Initialize Redis
            redis_url = self.config.get('redis', {}).get('url', 'redis://localhost:6379')
            self.redis_manager = RedisManager(url=redis_url)
            await self.redis_manager.initialize()
            
            # Initialize MCP context
            self.mcp_context = MCPContext.from_env(redis=self.redis_manager)
            await self.mcp_context.__aenter__()
            
            self.logger.debug("Infrastructure initialized")
            
        except Exception as e:
            self.logger.warning(f"Infrastructure initialization failed: {e}")
            self.redis_manager = None
            self.mcp_context = None
    
    @abstractmethod
    async def _agent_initialize(self):
        """Agent-specific initialization - must be implemented by subclasses"""
        pass
    
    async def start(self) -> bool:
        """Start the agent"""
        if self.state != AgentState.ACTIVE:
            self.logger.error(f"Agent {self.agent_id} not in ACTIVE state")
            return False
        
        try:
            self.logger.info(f"🚀 Starting agent {self.agent_id}")
            self.running = True
            
            # Start agent-specific logic
            await self._agent_start()
            
            # Start background tasks
            await self._start_background_tasks()
            
            self.logger.info(f"✅ Agent {self.agent_id} started successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to start agent {self.agent_id}: {e}")
            self.state = AgentState.ERROR
            return False
    
    @abstractmethod
    async def _agent_start(self):
        """Agent-specific start logic - must be implemented by subclasses"""
        pass
    
    async def _start_background_tasks(self):
        """Start background monitoring tasks"""
        # Performance monitoring
        self.tasks.append(asyncio.create_task(
            self._performance_monitoring_task(),
            name=f"{self.agent_id}_performance"
        ))
        
        # Adaptive learning
        self.tasks.append(asyncio.create_task(
            self._adaptive_learning_task(),
            name=f"{self.agent_id}_adaptive"
        ))
    
    async def _performance_monitoring_task(self):
        """Monitor agent performance"""
        while self.running:
            try:
                # Update metrics
                self.metrics.last_activity = time.time()
                
                # Publish metrics to Redis
                if self.redis_manager:
                    await self.redis_manager.client.xadd(
                        f"agent:{self.agent_id}:metrics",
                        {
                            'signals_processed': self.metrics.signals_processed,
                            'trades_executed': self.metrics.trades_executed,
                            'errors_count': self.metrics.errors_count,
                            'performance_score': self.metrics.performance_score,
                            'timestamp': str(time.time())
                        }
                    )
                
                await asyncio.sleep(30)  # Every 30 seconds
                
            except Exception as e:
                self.logger.error(f"Performance monitoring error: {e}")
                await asyncio.sleep(60)
    
    async def _adaptive_learning_task(self):
        """Run adaptive learning for this agent"""
        while self.running:
            try:
                # Get recent outcomes for this agent
                outcomes_df = await self._get_agent_outcomes()
                
                if not outcomes_df.empty:
                    # Run adaptive learning
                    current_params = self.config.get('trading', {}).get('parameters', {})
                    
                    update_result = gated_update(
                        outcomes_df=outcomes_df,
                        current_params=current_params,
                        timeframe="1m",
                        config=self.adaptive_learner_config,
                        context_meta={
                            'latency_ms': 0,
                            'agent_id': self.agent_id,
                            'strategy': self.strategy
                        }
                    )
                    
                    if update_result.mode == "active" and update_result.confidence > 0.6:
                        # Apply parameter updates
                        await self._apply_parameter_updates(update_result.new_params)
                        self.logger.info(f"Applied adaptive update: {update_result.reason}")
                
                await asyncio.sleep(3600)  # Every hour
                
            except Exception as e:
                self.logger.error(f"Adaptive learning error: {e}")
                await asyncio.sleep(600)
    
    async def _get_agent_outcomes(self):
        """Get recent trade outcomes for this agent"""
        # This would be implemented based on your trade storage
        import pandas as pd
        return pd.DataFrame()
    
    async def _apply_parameter_updates(self, new_params: Dict[str, float]):
        """Apply parameter updates to this agent"""
        try:
            # Update agent configuration
            if 'trading' not in self.config:
                self.config['trading'] = {}
            if 'parameters' not in self.config['trading']:
                self.config['trading']['parameters'] = {}
            
            self.config['trading']['parameters'].update(new_params)
            
            # Notify agent of changes
            await self._on_parameter_update(new_params)
            
            self.logger.info(f"Applied parameter updates: {new_params}")
            
        except Exception as e:
            self.logger.error(f"Failed to apply parameter updates: {e}")
    
    async def _on_parameter_update(self, new_params: Dict[str, float]):
        """Called when parameters are updated - can be overridden by subclasses"""
        pass
    
    async def stop(self):
        """Stop the agent"""
        if not self.running:
            return
        
        self.logger.info(f"🛑 Stopping agent {self.agent_id}")
        self.running = False
        self.state = AgentState.SHUTTING_DOWN
        
        try:
            # Cancel background tasks
            for task in self.tasks:
                if not task.done():
                    task.cancel()
            
            # Wait for tasks to complete
            if self.tasks:
                await asyncio.gather(*self.tasks, return_exceptions=True)
            
            # Agent-specific stop logic
            await self._agent_stop()
            
            # Close infrastructure
            if self.mcp_context:
                await self.mcp_context.__aexit__(None, None, None)
            
            if self.redis_manager:
                await self.redis_manager.close()
            
            self.state = AgentState.STOPPED
            self.logger.info(f"✅ Agent {self.agent_id} stopped")
            
        except Exception as e:
            self.logger.error(f"Error stopping agent {self.agent_id}: {e}")
    
    @abstractmethod
    async def _agent_stop(self):
        """Agent-specific stop logic - must be implemented by subclasses"""
        pass
    
    def get_agent_status(self) -> Dict[str, Any]:
        """Get current agent status"""
        return {
            'agent_id': self.agent_id,
            'strategy': self.strategy,
            'environment': self.environment,
            'state': self.state.value,
            'running': self.running,
            'metrics': {
                'signals_processed': self.metrics.signals_processed,
                'trades_executed': self.metrics.trades_executed,
                'errors_count': self.metrics.errors_count,
                'performance_score': self.metrics.performance_score,
                'last_activity': self.metrics.last_activity
            }
        }
    
    def increment_metric(self, metric_name: str, value: int = 1):
        """Increment a metric value"""
        if hasattr(self.metrics, metric_name):
            current_value = getattr(self.metrics, metric_name)
            setattr(self.metrics, metric_name, current_value + value)
    
    def set_metric(self, metric_name: str, value: Any):
        """Set a metric value"""
        if hasattr(self.metrics, metric_name):
            setattr(self.metrics, metric_name, value)
    
    async def process_signal(self, signal_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Process a trading signal using AI engine integration
        
        Args:
            signal_data: Signal data from market analysis
            
        Returns:
            Processed signal or None if rejected
        """
        try:
            # Update metrics
            self.increment_metric('signals_processed')
            self.metrics.last_activity = time.time()
            
            # Use AI engine strategy selector if available
            if self.strategy_selector_config:
                # Create position snapshot
                position = PositionSnapshot(
                    symbol=signal_data.get('symbol', 'BTC/USD'),
                    timeframe=signal_data.get('timeframe', '1m'),
                    side=Side.NONE,  # This would come from current position state
                    allocation=0.0,  # This would come from current position state
                    avg_entry_px=None
                )
                
                # Use strategy selector
                decision = select_for_symbol(
                    symbol=signal_data.get('symbol', 'BTC/USD'),
                    timeframe=signal_data.get('timeframe', '1m'),
                    signal=signal_data,
                    position=position,
                    cfg=self.strategy_selector_config,
                    daily_pnl_usd=0.0,  # This would come from current P&L
                    spread_bps=signal_data.get('spread_bps'),
                    latency_ms=signal_data.get('latency_ms')
                )
                
                # Process decision
                if decision.action.value != 'hold':
                    self.increment_metric('trades_executed')
                    return {
                        'action': decision.action.value,
                        'side': decision.side.value,
                        'target_allocation': decision.target_allocation,
                        'confidence': decision.confidence,
                        'explanation': decision.explain,
                        'diagnostics': decision.diagnostics
                    }
            
            # Fallback to agent-specific signal processing
            return await self._process_agent_signal(signal_data)
            
        except Exception as e:
            self.logger.error(f"Error processing signal: {e}")
            self.increment_metric('errors_count')
            return None
    
    @abstractmethod
    async def _process_agent_signal(self, signal_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Agent-specific signal processing - must be implemented by subclasses"""
        pass
