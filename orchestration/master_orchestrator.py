"""
Master Orchestrator for Complete System Integration

This orchestrator ties together:
- All agents with unified configuration
- AI engine components (strategy selector, adaptive learner)
- Real-time data pipeline
- Risk management
- Performance monitoring
- Redis/MCP integration
"""

import asyncio
import logging
import os
import time
from typing import Dict, Any, Optional, List, Set
from dataclasses import dataclass
from datetime import datetime, timezone
import signal
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Set up module-level logging to debug import hangs
_logger = logging.getLogger("MasterOrchestrator")
_logger.info("🔍 Starting MasterOrchestrator module imports...")

# Core imports
_logger.info("→ Importing config.agent_integration...")
from config.agent_integration import (
    get_merged_config,
    get_risk_parameters,
    get_performance_settings,
    get_monitoring_settings,
    AgentConfigIntegrator
)
_logger.info("✅ config.agent_integration imported")

# AI Engine imports
_logger.info("→ Importing ai_engine modules...")
from ai_engine.strategy_selector import (
    SelectorConfig,
    select_for_symbol,
    plan_for_universe,
    PositionSnapshot,
    Side
)
from ai_engine.adaptive_learner import (
    LearnerConfig,
    gated_update,
    compute_metrics
)
_logger.info("✅ ai_engine modules imported")

# Agent imports - DEFERRED TO AVOID BLOCKING
# Import these modules lazily when actually needed to avoid import-time blocking I/O
_logger.info("→ Agent modules will be imported lazily when needed")
_logger.info("✅ Using lazy imports for agent and infrastructure modules")

# Type placeholders for IDE support
SignalAnalyst = None
SignalAnalystManager = None
SignalProcessor = None
EnhancedExecutionAgent = None
RiskRouter = None
EnhancedScalperAgent = None
DataPipeline = None
DataPipelineConfig = None
RedisClient = None

# MCP imports with fallback
_logger.info("→ Importing MCP modules...")
try:
    from mcp.redis_manager import AsyncRedisManager
    from mcp.context import MCPContext
    HAS_MCP = True
    _logger.info("✅ MCP modules imported")
except ImportError:
    HAS_MCP = False
    AsyncRedisManager = None
    MCPContext = None
    _logger.warning("⚠️ MCP modules not available")

# Strategy imports
_logger.info("→ Importing strategy modules...")
from strategies.regime_based_router import RegimeRouter, MarketContext
from strategies.breakout import BreakoutStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.momentum_strategy import MomentumStrategy
from strategies.trend_following import TrendFollowingStrategy
_logger.info("✅ strategy modules imported")

@dataclass
class SystemState:
    """Complete system state tracking"""
    running: bool = False
    agents_active: Set[str] = None
    last_signal_time: float = 0.0
    last_adaptive_update: float = 0.0
    total_trades: int = 0
    total_pnl: float = 0.0
    system_health: str = "unknown"
    start_time: float = 0.0

    def __post_init__(self):
        if self.agents_active is None:
            self.agents_active = set()
        if self.start_time == 0.0:
            self.start_time = time.time()

class MasterOrchestrator:
    """
    Master orchestrator that integrates all system components
    """
    
    def __init__(self, config_path: str = "config/settings.yaml"):
        self.config_path = config_path
        self.logger = logging.getLogger("MasterOrchestrator")
        
        # System state
        self.state = SystemState()
        
        # Configuration
        self.config_integrator = AgentConfigIntegrator(config_path)
        self.agent_config = None
        self.risk_config = None
        self.perf_config = None
        self.monitoring_config = None
        
        # Core components
        self.redis_manager: Optional[RedisManager] = None
        self.mcp_context: Optional[MCPContext] = None
        self.data_pipeline: Optional[DataPipeline] = None
        
        # AI Engine components
        self.strategy_selector_config: Optional[SelectorConfig] = None
        self.adaptive_learner_config: Optional[LearnerConfig] = None
        self.regime_router: Optional[RegimeRouter] = None
        
        # Agents
        self.signal_analyst_manager: Optional = None  # TODO: Refactor to use new pure function API
        self.signal_processor: Optional[SignalProcessor] = None
        self.execution_agent: Optional[EnhancedExecutionAgent] = None
        self.risk_router: Optional[RiskRouter] = None
        self.enhanced_scalper: Optional[EnhancedScalperAgent] = None
        
        # Background tasks
        self.tasks: List[asyncio.Task] = []
        
        # Performance tracking
        self.performance_metrics = {
            'signals_generated': 0,
            'trades_executed': 0,
            'risk_rejections': 0,
            'adaptive_updates': 0,
            'system_errors': 0
        }
    
    async def initialize(self) -> bool:
        """Initialize all system components"""
        try:
            self.logger.info("🚀 Initializing Master Orchestrator...")
            
            # 1. Load unified configuration
            await self._load_configuration()
            
            # 2. Initialize infrastructure
            await self._initialize_infrastructure()
            
            # 3. Initialize AI Engine components
            await self._initialize_ai_engine()
            
            # 4. Initialize agents
            await self._initialize_agents()
            
            # 5. Setup signal handlers
            self._setup_signal_handlers()
            
            self.logger.info("✅ Master Orchestrator initialized successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize Master Orchestrator: {e}")
            return False
    
    async def _load_configuration(self):
        """Load and validate all configuration"""
        self.logger.info("📋 Loading unified configuration...")
        
        # Load merged configuration
        self.agent_config = self.config_integrator.get_merged_config()
        self.risk_config = self.config_integrator.get_risk_parameters()
        self.perf_config = self.config_integrator.get_performance_settings()
        self.monitoring_config = self.config_integrator.get_monitoring_settings()
        
        # Validate configuration
        issues = self.config_integrator.validate_configuration()
        if issues:
            self.logger.warning(f"Configuration issues: {issues}")
        
        self.logger.info("✅ Configuration loaded successfully")
    
    async def _initialize_infrastructure(self):
        """
        Initialize Redis, MCP, and data pipeline.

        IMPORTANT: Redis connection failures are NEVER fatal - app will start anyway
        and degrade gracefully if Redis is unavailable.
        """
        self.logger.info("🔧 Initializing infrastructure...")

        # Initialize Redis with graceful degradation
        redis_connected = False
        try:
            redis_url = self.agent_config.get('redis', {}).get('url', 'redis://localhost:6379')
            if not redis_url:
                self.logger.warning("⚠️ Redis URL not configured - app will start without Redis")
                self.redis_manager = None
            elif HAS_MCP:
                self.redis_manager = AsyncRedisManager(url=redis_url)
                redis_connected = await self.redis_manager.aconnect()
                if redis_connected:
                    self.logger.info("✅ Redis connected successfully")
                else:
                    self.logger.warning("⚠️ Redis unavailable - app starting anyway (degraded mode)")
                    self.logger.warning("   Redis-dependent features will be disabled until connection is restored")
                    # Keep manager instance for potential auto-reconnect
            else:
                self.logger.warning("⚠️ MCP not available, using fallback mode")
                self.redis_manager = None
        except Exception as e:
            # Catch any unexpected errors from manager initialization itself
            self.logger.warning(f"⚠️ Redis initialization error: {e}")
            self.logger.warning("   App will start anyway - Redis-dependent features disabled")
            self.redis_manager = None
            redis_connected = False
        
        # Initialize MCP context (only if Redis connected)
        if HAS_MCP and self.redis_manager and redis_connected:
            try:
                self.mcp_context = MCPContext.from_env(redis=self.redis_manager)
                await self.mcp_context.__aenter__()
                self.logger.info("✅ MCP context initialized")
            except Exception as e:
                self.logger.warning(f"⚠️ MCP context initialization failed: {e}")
                self.logger.warning("   Continuing without MCP context")
                self.mcp_context = None
        else:
            self.logger.info("⚠️ Skipping MCP context (Redis not available)")
            self.mcp_context = None

        # Initialize data pipeline with graceful degradation
        try:
            # Lazy import to avoid blocking at module load time
            from agents.infrastructure.data_pipeline import DataPipeline, DataPipelineConfig

            pipeline_config = DataPipelineConfig(
                pairs=self.agent_config.get('trading', {}).get('pairs', ['BTC/USD']),
                redis_url=redis_url if redis_connected else None,
                create_consumer_groups=redis_connected  # Only create groups if Redis is up
            )
            self.data_pipeline = DataPipeline(
                cfg=pipeline_config,
                redis_client=self.redis_manager.client if (self.redis_manager and redis_connected) else None,
                http=None  # Will be created internally
            )
            if redis_connected:
                self.logger.info("✅ Data pipeline configured with Redis")
            else:
                self.logger.warning("⚠️ Data pipeline configured in offline mode (no Redis)")
                self.logger.warning("   Live data streaming will be unavailable")
        except Exception as e:
            # Data pipeline failure is not fatal - app can run without it
            self.logger.warning(f"⚠️ Data pipeline setup failed: {e}")
            self.logger.warning("   Continuing without data pipeline - manual data sources only")
            self.data_pipeline = None
    
    async def _initialize_ai_engine(self):
        """Initialize AI engine components"""
        self.logger.info("🧠 Initializing AI Engine...")
        
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
            windows={"short": 50, "medium": 200, "long": 1000},
            thresholds={
                "min_trades": 200,
                "good_sharpe": 1.0,
                "poor_sharpe": 0.2,
                "hit_rate_good": 0.55,
                "hit_rate_poor": 0.45
            }
        )
        
        # Regime router
        self.regime_router = RegimeRouter(self.agent_config.get('strategies', {}))
        
        self.logger.info("✅ AI Engine initialized")
    
    async def _initialize_agents(self):
        """Initialize all trading agents"""
        self.logger.info("🤖 Initializing agents...")

        # Lazy imports to avoid blocking at module load time
        try:
            from agents.core.signal_processor import SignalProcessor
            from agents.core.execution_agent import EnhancedExecutionAgent
            from agents.risk.risk_router import RiskRouter
            from agents.scalper.enhanced_scalper_agent import EnhancedScalperAgent

            # Signal Analyst Manager
            # self.signal_analyst_manager = SignalAnalystManager(self.redis_manager)  # TODO: Refactor to use new pure function API

            # Signal Processor (uses shared redis_manager for Redis Cloud SSL connection)
            self.signal_processor = SignalProcessor(
                config_path=self.config_path,
                redis_manager=self.redis_manager
            )

            # Execution Agent
            self.execution_agent = EnhancedExecutionAgent(self.agent_config)

            # Risk Router (TODO: Provide proper dependencies - config, compliance, drawdown)
            # self.risk_router = RiskRouter(config=..., compliance=..., drawdown=...)

            # Enhanced Scalper (check if it needs redis_manager or not)
            # self.enhanced_scalper = EnhancedScalperAgent(
            #     config=self.agent_config,
            #     redis_manager=self.redis_manager
            # )

            self.logger.info("✅ All agents initialized")
        except ImportError as e:
            self.logger.error(f"❌ Failed to import agent modules: {e}")
            raise
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize agents: {e}")
            raise
    
    def _setup_signal_handlers(self):
        """Setup graceful shutdown handlers"""
        def signal_handler(signum, frame):
            self.logger.info(f"Received signal {signum}, initiating graceful shutdown...")
            asyncio.create_task(self.stop())
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    async def start(self):
        """Start the complete trading system"""
        if self.state.running:
            self.logger.warning("System already running")
            return
        
        self.logger.info("🚀 Starting complete trading system...")
        self.state.running = True
        
        try:
            # Start data pipeline
            if self.data_pipeline:
                await self.data_pipeline.start()
                self.state.agents_active.add("data_pipeline")
            
            # Start signal analysts for each symbol
            if self.signal_analyst_manager:
                symbols = self.agent_config.get('trading', {}).get('pairs', ['BTC/USD'])
                for symbol in symbols:
                    analyst = await self.signal_analyst_manager.start_analyst(
                        symbol=symbol,
                        strategy="scalp",
                        config=self.agent_config
                    )
                    self.state.agents_active.add(f"signal_analyst_{symbol}")
            
            # Start signal processor
            if self.signal_processor:
                await self.signal_processor.initialize()
                await self.signal_processor.start()
                self.state.agents_active.add("signal_processor")
            
            # Start enhanced scalper
            if self.enhanced_scalper:
                await self.enhanced_scalper.initialize()
                self.state.agents_active.add("enhanced_scalper")
            
            # Start background tasks
            await self._start_background_tasks()
            
            self.state.system_health = "healthy"
            self.logger.info("✅ Complete trading system started successfully")
            
        except Exception as e:
            self.logger.error(f"❌ Failed to start system: {e}")
            await self.stop()
            raise
    
    async def _start_background_tasks(self):
        """Start background monitoring and maintenance tasks"""
        
        # Performance monitoring task
        self.tasks.append(asyncio.create_task(
            self._performance_monitoring_task(),
            name="performance_monitoring"
        ))
        
        # Adaptive learning task
        self.tasks.append(asyncio.create_task(
            self._adaptive_learning_task(),
            name="adaptive_learning"
        ))
        
        # Health check task
        self.tasks.append(asyncio.create_task(
            self._health_check_task(),
            name="health_check"
        ))
        
        # Configuration update task
        self.tasks.append(asyncio.create_task(
            self._config_update_task(),
            name="config_update"
        ))

        # Heartbeat publishing task
        self.tasks.append(asyncio.create_task(
            self._heartbeat_publishing_task(),
            name="heartbeat_publisher"
        ))

        # PnL equity publishing task
        self.tasks.append(asyncio.create_task(
            self._pnl_equity_publishing_task(),
            name="pnl_equity_publisher"
        ))
    
    async def _performance_monitoring_task(self):
        """Monitor system performance and metrics with stream sizes & Redis lag"""
        while self.state.running:
            try:
                # Collect performance metrics
                current_time = time.time()

                # Get stream sizes if Redis is available
                stream_sizes = {}
                redis_lag_ms = 0.0
                if self.redis_manager and self.redis_manager.client:
                    try:
                        # Measure Redis lag
                        redis_start = time.time()
                        await self.redis_manager.client.ping()
                        redis_lag_ms = (time.time() - redis_start) * 1000

                        # Get sizes of key streams
                        key_streams = [
                            'signals:paper',
                            'signals:live',
                            'kraken:health',
                            'ops:heartbeat',
                            'metrics:pnl:equity',
                            'system:metrics'
                        ]
                        for stream_name in key_streams:
                            try:
                                stream_len = await self.redis_manager.client.xlen(stream_name)
                                stream_sizes[stream_name.replace(':', '_')] = stream_len
                            except Exception:
                                pass
                    except Exception as e:
                        self.logger.debug(f"Error collecting Redis metrics: {e}")

                # Get last signal time from signal processor
                last_signal_time = 0.0
                if self.signal_processor and hasattr(self.signal_processor, 'resilient_publisher'):
                    publisher = self.signal_processor.resilient_publisher
                    if publisher and publisher.last_publish_time > 0:
                        last_signal_time = current_time - publisher.last_publish_time

                metrics = {
                    'timestamp': str(current_time),
                    'agents_active': str(len(self.state.agents_active)),
                    'total_trades': str(self.performance_metrics['trades_executed']),
                    'total_pnl': str(round(self.state.total_pnl, 2)),
                    'system_health': self.state.system_health,
                    'redis_lag_ms': str(round(redis_lag_ms, 2)),
                    'last_signal_seconds_ago': str(round(last_signal_time, 2)),
                    **{f'stream_size_{k}': str(v) for k, v in stream_sizes.items()}
                }

                # Publish metrics to Redis
                if self.redis_manager:
                    await self.redis_manager.client.xadd(
                        "system:metrics",
                        metrics,
                        maxlen=5000
                    )

                await asyncio.sleep(30)  # Every 30 seconds

            except Exception as e:
                self.logger.error(f"Performance monitoring error: {e}")
                await asyncio.sleep(60)
    
    async def _adaptive_learning_task(self):
        """Run adaptive learning updates"""
        while self.state.running:
            try:
                # Check if enough time has passed since last update
                now = time.time()
                if now - self.state.last_adaptive_update < 3600:  # 1 hour
                    await asyncio.sleep(300)  # Check every 5 minutes
                    continue
                
                # Get recent trade outcomes
                outcomes_df = await self._get_recent_outcomes()
                
                if not outcomes_df.empty:
                    # Run adaptive learning
                    current_params = self.agent_config.get('trading', {}).get('parameters', {})
                    
                    update_result = gated_update(
                        outcomes_df=outcomes_df,
                        current_params=current_params,
                        timeframe="1m",
                        config=self.adaptive_learner_config,
                        context_meta={
                            'latency_ms': 0,
                            'rolling_pnl_day_usd': self.state.total_pnl,
                            'avg_spread_bps': 2.5
                        }
                    )
                    
                    if update_result.mode == "active" and update_result.confidence > 0.6:
                        # Apply parameter updates
                        await self._apply_parameter_updates(update_result.new_params)
                        self.performance_metrics['adaptive_updates'] += 1
                        self.logger.info(f"Applied adaptive update: {update_result.reason}")
                    
                    self.state.last_adaptive_update = now
                
                await asyncio.sleep(300)  # Check every 5 minutes
                
            except Exception as e:
                self.logger.error(f"Adaptive learning error: {e}")
                await asyncio.sleep(600)
    
    async def _health_check_task(self):
        """Monitor system health"""
        while self.state.running:
            try:
                health_status = "healthy"
                
                # Check Redis connection
                if self.redis_manager:
                    try:
                        await self.redis_manager.client.ping()
                    except Exception:
                        health_status = "degraded"
                
                # Check agent health
                if len(self.state.agents_active) < 3:  # Minimum expected agents
                    health_status = "degraded"
                
                # Check for recent errors
                if self.performance_metrics['system_errors'] > 10:
                    health_status = "unhealthy"
                
                self.state.system_health = health_status
                
                # Log health status
                if health_status != "healthy":
                    self.logger.warning(f"System health: {health_status}")
                
                await asyncio.sleep(60)  # Check every minute
                
            except Exception as e:
                self.logger.error(f"Health check error: {e}")
                await asyncio.sleep(60)
    
    async def _config_update_task(self):
        """Monitor for configuration updates"""
        while self.state.running:
            try:
                # Check for configuration updates via Redis
                if self.redis_manager:
                    # Listen for config update events
                    # This would need to be implemented based on your config update mechanism
                    pass
                
                await asyncio.sleep(30)  # Check every 30 seconds
                
            except Exception as e:
                self.logger.error(f"Config update monitoring error: {e}")
                await asyncio.sleep(60)

    async def _heartbeat_publishing_task(self):
        """Publish heartbeat to ops:heartbeat stream every 15s"""
        # Load maxlen from environment
        maxlen_heartbeat = int(os.getenv('STREAM_MAXLEN_HEARTBEAT', '1000'))

        while self.state.running:
            try:
                if self.redis_manager:
                    heartbeat_data = {
                        'ts': str(int(time.time() * 1000)),
                        'status': self.state.system_health,
                        'agents_active': str(len(self.state.agents_active)),
                        'uptime_seconds': str(int(time.time() - self.state.start_time))
                    }

                    # Publish with XTRIM to keep stream bounded
                    await self.redis_manager.client.xadd(
                        'ops:heartbeat',
                        heartbeat_data,
                        maxlen=maxlen_heartbeat  # Configurable via STREAM_MAXLEN_HEARTBEAT
                    )

                await asyncio.sleep(15)  # Every 15 seconds

            except Exception as e:
                self.logger.error(f"Heartbeat publishing error: {e}")
                await asyncio.sleep(15)

    async def _pnl_equity_publishing_task(self):
        """Publish PnL equity points to metrics:pnl:equity stream"""
        # Load maxlen from environment
        maxlen_pnl = int(os.getenv('STREAM_MAXLEN_PNL', '5000'))
        last_ts = 0

        while self.state.running:
            try:
                if self.redis_manager:
                    current_ts = int(time.time() * 1000)

                    # Ensure monotonic timestamps
                    if current_ts <= last_ts:
                        current_ts = last_ts + 1

                    pnl_data = {
                        'ts': str(current_ts),
                        'equity': str(round(self.state.total_pnl + 10000.0, 2)),  # Starting equity + PnL
                        'pnl': str(round(self.state.total_pnl, 2)),
                        'trades_count': str(self.performance_metrics['trades_executed'])
                    }

                    # Publish with XTRIM to keep stream bounded
                    await self.redis_manager.client.xadd(
                        'metrics:pnl:equity',
                        pnl_data,
                        maxlen=maxlen_pnl  # Configurable via STREAM_MAXLEN_PNL (default: 5000)
                    )

                    last_ts = current_ts

                await asyncio.sleep(60)  # Every 60 seconds

            except Exception as e:
                self.logger.error(f"PnL equity publishing error: {e}")
                await asyncio.sleep(60)

    async def _get_recent_outcomes(self):
        """Get recent trade outcomes for adaptive learning"""
        # This would need to be implemented based on your trade storage
        # For now, return empty DataFrame
        import pandas as pd
        return pd.DataFrame()
    
    async def _apply_parameter_updates(self, new_params: Dict[str, float]):
        """Apply parameter updates to the system"""
        try:
            # Update configuration
            if 'trading' not in self.agent_config:
                self.agent_config['trading'] = {}
            if 'parameters' not in self.agent_config['trading']:
                self.agent_config['trading']['parameters'] = {}
            
            self.agent_config['trading']['parameters'].update(new_params)
            
            # Notify agents of parameter changes
            if self.redis_manager:
                await self.redis_manager.client.xadd(
                    "system:config_updates",
                    {
                        "type": "parameter_update",
                        "parameters": str(new_params),
                        "timestamp": str(time.time())
                    }
                )
            
            self.logger.info(f"Applied parameter updates: {new_params}")
            
        except Exception as e:
            self.logger.error(f"Failed to apply parameter updates: {e}")
    
    async def stop(self):
        """Stop the complete trading system"""
        if not self.state.running:
            return
        
        self.logger.info("🛑 Stopping complete trading system...")
        self.state.running = False
        
        try:
            # Cancel all background tasks
            for task in self.tasks:
                if not task.done():
                    task.cancel()
            
            # Wait for tasks to complete
            if self.tasks:
                await asyncio.gather(*self.tasks, return_exceptions=True)
            
            # Stop agents
            if self.signal_analyst_manager:
                await self.signal_analyst_manager.stop_all()
            
            if self.signal_processor:
                await self.signal_processor.stop()
            
            if self.data_pipeline:
                await self.data_pipeline.stop()
            
            # Close connections
            if self.mcp_context:
                await self.mcp_context.__aexit__(None, None, None)
            
            if self.redis_manager:
                await self.redis_manager.close()
            
            self.logger.info("✅ Complete trading system stopped")
            
        except Exception as e:
            self.logger.error(f"Error during shutdown: {e}")
    
    def get_system_status(self) -> Dict[str, Any]:
        """Get current system status"""
        return {
            'running': self.state.running,
            'agents_active': list(self.state.agents_active),
            'system_health': self.state.system_health,
            'performance_metrics': self.performance_metrics.copy(),
            'total_trades': self.state.total_trades,
            'total_pnl': self.state.total_pnl
        }

# Global orchestrator instance
_orchestrator: Optional[MasterOrchestrator] = None

async def get_orchestrator() -> MasterOrchestrator:
    """Get the global orchestrator instance"""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = MasterOrchestrator()
        await _orchestrator.initialize()
    return _orchestrator

async def start_system():
    """Start the complete trading system"""
    orchestrator = await get_orchestrator()
    await orchestrator.start()
    return orchestrator

async def stop_system():
    """Stop the complete trading system"""
    global _orchestrator
    if _orchestrator:
        await _orchestrator.stop()
        _orchestrator = None
