"""
Unified Configuration Loader

This module provides a single entry point for all configuration needs
across the entire trading system, integrating agent configs, AI engine
settings, and infrastructure configuration.
"""

import os
import yaml
import logging
from typing import Dict, Any, Optional, Union
from pathlib import Path
from dataclasses import dataclass

# Import existing configuration components
from config.agent_integration import AgentConfigIntegrator
from config.base_config import CryptoAIBotConfig
from config.config_loader import ConfigManager

@dataclass
class SystemConfig:
    """Complete system configuration container"""
    # Core configurations
    agent_config: Dict[str, Any]
    risk_config: Dict[str, Any]
    performance_config: Dict[str, Any]
    monitoring_config: Dict[str, Any]
    
    # AI Engine configurations
    strategy_selector_config: Dict[str, Any]
    adaptive_learner_config: Dict[str, Any]
    
    # Infrastructure configurations
    redis_config: Dict[str, Any]
    kraken_config: Dict[str, Any]
    data_pipeline_config: Dict[str, Any]
    
    # Trading configurations
    trading_config: Dict[str, Any]
    risk_management_config: Dict[str, Any]
    
    # Environment settings
    environment: str
    debug_mode: bool
    paper_trading: bool

class UnifiedConfigLoader:
    """
    Unified configuration loader that integrates all system components
    """
    
    def __init__(self, config_path: str = "config/settings.yaml"):
        self.config_path = config_path
        self.logger = logging.getLogger("UnifiedConfigLoader")
        
        # Initialize configuration integrator
        self.agent_integrator = AgentConfigIntegrator(config_path)
        
        # Load main configuration
        self.main_config_manager = ConfigManager.get_instance(config_path)
        
        # Cache for loaded configurations
        self._config_cache: Dict[str, Any] = {}
        self._last_load_time: float = 0.0
        
        self.logger.info("Unified configuration loader initialized")
    
    def load_system_config(
        self, 
        environment: str = "production",
        strategy: Optional[str] = None,
        force_reload: bool = False
    ) -> SystemConfig:
        """
        Load complete system configuration
        
        Args:
            environment: Environment (development, staging, production)
            strategy: Specific strategy to load overrides for
            force_reload: Force reload from files
            
        Returns:
            Complete system configuration
        """
        cache_key = f"{environment}_{strategy or 'default'}"
        
        # Check cache if not forcing reload
        if not force_reload and cache_key in self._config_cache:
            return self._config_cache[cache_key]
        
        self.logger.info(f"Loading system configuration for {environment} environment")
        
        try:
            # Load agent configuration
            agent_config = self.agent_integrator.get_merged_config(
                strategy=strategy,
                environment=environment,
                force_reload=force_reload
            )
            
            # Load risk parameters
            risk_config = self.agent_integrator.get_risk_parameters(
                strategy=strategy,
                environment=environment
            )
            
            # Load performance settings
            performance_config = self.agent_integrator.get_performance_settings(
                strategy=strategy,
                environment=environment
            )
            
            # Load monitoring settings
            monitoring_config = self.agent_integrator.get_monitoring_settings(
                strategy=strategy,
                environment=environment
            )
            
            # Load AI engine configurations
            strategy_selector_config = self._load_strategy_selector_config(agent_config)
            adaptive_learner_config = self._load_adaptive_learner_config(agent_config)
            
            # Load infrastructure configurations
            redis_config = self._load_redis_config(agent_config)
            kraken_config = self._load_kraken_config(agent_config)
            data_pipeline_config = self._load_data_pipeline_config(agent_config)
            
            # Load trading configurations
            trading_config = self._load_trading_config(agent_config)
            risk_management_config = self._load_risk_management_config(agent_config)
            
            # Create system config
            system_config = SystemConfig(
                agent_config=agent_config,
                risk_config=risk_config,
                performance_config=performance_config,
                monitoring_config=monitoring_config,
                strategy_selector_config=strategy_selector_config,
                adaptive_learner_config=adaptive_learner_config,
                redis_config=redis_config,
                kraken_config=kraken_config,
                data_pipeline_config=data_pipeline_config,
                trading_config=trading_config,
                risk_management_config=risk_management_config,
                environment=environment,
                debug_mode=environment in ["development", "staging"],
                paper_trading=environment != "production"
            )
            
            # Cache the configuration
            self._config_cache[cache_key] = system_config
            self._last_load_time = os.path.getmtime(self.config_path) if os.path.exists(self.config_path) else 0.0
            
            self.logger.info("System configuration loaded successfully")
            return system_config
            
        except Exception as e:
            self.logger.error(f"Failed to load system configuration: {e}")
            raise
    
    def _load_strategy_selector_config(self, agent_config: Dict[str, Any]) -> Dict[str, Any]:
        """Load strategy selector configuration"""
        ai_engine_config = agent_config.get('ai_engine', {}).get('strategy_selector', {})
        
        return {
            'enabled': ai_engine_config.get('enabled', True),
            'update_interval': ai_engine_config.get('update_interval', 300),
            'confidence_threshold': ai_engine_config.get('confidence_threshold', 0.6),
            'max_gross_allocation': ai_engine_config.get('max_gross_allocation', 2.0),
            'step_allocation': ai_engine_config.get('step_allocation', 0.25),
            'limits': {
                'max_allocation': agent_config.get('agent', {}).get('max_drawdown', 0.2),
                'max_gross_allocation': ai_engine_config.get('max_gross_allocation', 2.0),
                'step_allocation': ai_engine_config.get('step_allocation', 0.25),
                'min_conf_to_open': 0.55,
                'min_conf_to_flip': 0.65,
                'min_conf_to_close': 0.35,
                'reduce_on_dip_conf': 0.45
            },
            'risk': {
                'daily_stop_usd': agent_config.get('risk_management', {}).get('daily_stop_usd', 100.0),
                'spread_bps_cap': 50.0,
                'latency_budget_ms': 100
            }
        }
    
    def _load_adaptive_learner_config(self, agent_config: Dict[str, Any]) -> Dict[str, Any]:
        """Load adaptive learner configuration"""
        ai_engine_config = agent_config.get('ai_engine', {}).get('adaptive_learner', {})
        
        return {
            'enabled': ai_engine_config.get('enabled', True),
            'mode': ai_engine_config.get('mode', 'shadow'),
            'update_interval': ai_engine_config.get('update_interval', 3600),
            'min_trades': ai_engine_config.get('min_trades', 200),
            'confidence_threshold': ai_engine_config.get('confidence_threshold', 0.6),
            'windows': ai_engine_config.get('windows', {
                'short': 50,
                'medium': 200,
                'long': 1000
            }),
            'thresholds': ai_engine_config.get('thresholds', {
                'good_sharpe': 1.0,
                'poor_sharpe': 0.2,
                'hit_rate_good': 0.55,
                'hit_rate_poor': 0.45
            })
        }
    
    def _load_redis_config(self, agent_config: Dict[str, Any]) -> Dict[str, Any]:
        """Load Redis configuration"""
        redis_config = agent_config.get('redis', {})
        
        return {
            'url': redis_config.get('url', os.getenv('REDIS_URL', 'redis://localhost:6379')),
            'max_connections': redis_config.get('max_connections', 10),
            'retry_on_timeout': redis_config.get('retry_on_timeout', True),
            'health_check_interval': redis_config.get('health_check_interval', 30)
        }
    
    def _load_kraken_config(self, agent_config: Dict[str, Any]) -> Dict[str, Any]:
        """Load Kraken configuration"""
        kraken_config = agent_config.get('kraken', {})
        
        return {
            'api_key': kraken_config.get('api_key', os.getenv('KRAKEN_API_KEY')),
            'api_secret': kraken_config.get('api_secret', os.getenv('KRAKEN_API_SECRET')),
            'sandbox': kraken_config.get('sandbox', False),
            'rate_limit': kraken_config.get('rate_limit', 1.0)
        }
    
    def _load_data_pipeline_config(self, agent_config: Dict[str, Any]) -> Dict[str, Any]:
        """Load data pipeline configuration"""
        pipeline_config = agent_config.get('data_pipeline', {})
        
        return {
            'pairs': pipeline_config.get('pairs', ['BTC/USD']),
            'redis_url': pipeline_config.get('redis_url', os.getenv('REDIS_URL', 'redis://localhost:6379')),
            'create_consumer_groups': pipeline_config.get('create_consumer_groups', True),
            'startup_backfill_enabled': pipeline_config.get('startup_backfill_enabled', True),
            'compression_enabled': pipeline_config.get('compression_enabled', True),
            'batch_size': pipeline_config.get('batch_size', 100),
            'flush_interval': pipeline_config.get('flush_interval', 1.0)
        }
    
    def _load_trading_config(self, agent_config: Dict[str, Any]) -> Dict[str, Any]:
        """Load trading configuration"""
        trading_config = agent_config.get('trading', {})
        
        return {
            'pairs': trading_config.get('pairs', ['BTC/USD']),
            'parameters': trading_config.get('parameters', {
                'position_size_pct': 0.5,
                'sl_multiplier': 1.2,
                'tp_multiplier': 1.8,
                'cooldown_s': 30.0,
                'max_concurrent': 2
            }),
            'strategies': trading_config.get('strategies', {})
        }
    
    def _load_risk_management_config(self, agent_config: Dict[str, Any]) -> Dict[str, Any]:
        """Load risk management configuration"""
        risk_config = agent_config.get('risk_management', {})
        
        return {
            'daily_stop_usd': risk_config.get('daily_stop_usd', 100.0),
            'max_spread_bps': risk_config.get('max_spread_bps', 50.0),
            'max_latency_ms': risk_config.get('max_latency_ms', 100),
            'position_limits': risk_config.get('position_limits', {
                'max_position_usd': 10000.0,
                'max_concurrent_positions': 5,
                'max_correlation': 0.7
            }),
            'circuit_breakers': risk_config.get('circuit_breakers', {
                'max_daily_loss': 0.05,
                'max_consecutive_losses': 3,
                'max_drawdown': 0.15,
                'cooldown_after_trigger': 3600
            })
        }
    
    def get_agent_config(self, agent_id: str, strategy: str, environment: str = "production") -> Dict[str, Any]:
        """Get configuration for a specific agent"""
        system_config = self.load_system_config(environment=environment, strategy=strategy)
        
        # Extract agent-specific configuration
        agent_config = {
            'agent_id': agent_id,
            'strategy': strategy,
            'environment': environment,
            'debug_mode': system_config.debug_mode,
            'paper_trading': system_config.paper_trading,
            'trading': system_config.trading_config,
            'risk': system_config.risk_config,
            'performance': system_config.performance_config,
            'monitoring': system_config.monitoring_config,
            'redis': system_config.redis_config,
            'kraken': system_config.kraken_config,
            'ai_engine': {
                'strategy_selector': system_config.strategy_selector_config,
                'adaptive_learner': system_config.adaptive_learner_config
            }
        }
        
        # Add strategy-specific overrides
        strategy_config = system_config.trading_config.get('strategies', {}).get(strategy, {})
        if strategy_config:
            agent_config['strategy_config'] = strategy_config
        
        return agent_config
    
    def validate_configuration(self, system_config: SystemConfig) -> list:
        """Validate system configuration and return list of issues"""
        issues = []
        
        # Validate required fields
        if not system_config.redis_config.get('url'):
            issues.append("Redis URL not configured")
        
        if not system_config.kraken_config.get('api_key'):
            issues.append("Kraken API key not configured")
        
        if not system_config.kraken_config.get('api_secret'):
            issues.append("Kraken API secret not configured")
        
        # Validate trading pairs
        pairs = system_config.trading_config.get('pairs', [])
        if not pairs:
            issues.append("No trading pairs configured")
        
        # Validate risk parameters
        max_drawdown = system_config.risk_config.get('max_drawdown', 0.2)
        if max_drawdown <= 0 or max_drawdown > 1:
            issues.append(f"Invalid max_drawdown: {max_drawdown}")
        
        # Validate AI engine configuration
        if system_config.strategy_selector_config.get('enabled', True):
            if system_config.strategy_selector_config.get('confidence_threshold', 0.6) < 0 or system_config.strategy_selector_config.get('confidence_threshold', 0.6) > 1:
                issues.append("Invalid strategy selector confidence threshold")
        
        return issues
    
    def reload_configuration(self):
        """Reload all configurations from files"""
        self._config_cache.clear()
        self.agent_integrator.invalidate_cache()
        self.main_config_manager.reload_config()
        self.logger.info("All configurations reloaded from files")
    
    def get_config_summary(self, system_config: SystemConfig) -> Dict[str, Any]:
        """Get a summary of the loaded configuration"""
        return {
            'environment': system_config.environment,
            'debug_mode': system_config.debug_mode,
            'paper_trading': system_config.paper_trading,
            'trading_pairs': system_config.trading_config.get('pairs', []),
            'strategies_enabled': list(system_config.trading_config.get('strategies', {}).keys()),
            'ai_engine_enabled': {
                'strategy_selector': system_config.strategy_selector_config.get('enabled', True),
                'adaptive_learner': system_config.adaptive_learner_config.get('enabled', True)
            },
            'risk_parameters': {
                'max_drawdown': system_config.risk_config.get('max_drawdown', 0.2),
                'daily_stop_usd': system_config.risk_management_config.get('daily_stop_usd', 100.0)
            },
            'monitoring_enabled': system_config.monitoring_config.get('health_checks', {}).get('enabled', True)
        }

# Global configuration loader instance
_config_loader: Optional[UnifiedConfigLoader] = None

def get_config_loader() -> UnifiedConfigLoader:
    """Get the global configuration loader instance"""
    global _config_loader
    if _config_loader is None:
        _config_loader = UnifiedConfigLoader()
    return _config_loader

def load_system_config(
    environment: str = "production",
    strategy: Optional[str] = None,
    force_reload: bool = False
) -> SystemConfig:
    """Load complete system configuration"""
    loader = get_config_loader()
    return loader.load_system_config(environment, strategy, force_reload)

def get_agent_config(
    agent_id: str,
    strategy: str,
    environment: str = "production"
) -> Dict[str, Any]:
    """Get configuration for a specific agent"""
    loader = get_config_loader()
    return loader.get_agent_config(agent_id, strategy, environment)
