"""
Agent Configuration Integration Module

This module provides seamless integration between the enhanced agent configuration
and the existing crypto-ai-bot configuration system.
"""

from __future__ import annotations

import logging
import threading
from typing import Dict, Any, Optional, Union, List
from pathlib import Path
from datetime import datetime

# Import the enhanced agent configuration manager
from config.agent_config_manager import (
    AgentConfigManager, 
    get_agent_config, 
    get_agent_performance_metrics,
    validate_agent_config,
    detect_environment
)

# Import existing configuration system
from config.base_config import CryptoAIBotConfig
from config.config_loader import ConfigManager


class AgentConfigIntegrator:
    """
    Integrates enhanced agent configuration with the main configuration system.
    
    This class provides a bridge between the existing configuration system and
    the new enhanced agent configuration, ensuring backward compatibility while
    adding performance optimizations.
    """
    
    def __init__(self, main_config_path: str = "config/settings.yaml"):
        self.main_config_path = main_config_path
        self.logger = logging.getLogger(__name__)
        
        # Initialize managers
        self.main_config_manager = ConfigManager.get_instance(main_config_path)
        self.agent_config_manager = AgentConfigManager.get_instance()
        
        # Cache for merged configurations
        self._merged_config_cache: Dict[str, Any] = {}
        self._cache_lock = threading.RLock()
        
        # Performance tracking
        self._integration_metrics = {
            'merge_operations': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'validation_errors': 0,
            'last_update': datetime.now()
        }
    
    def get_merged_config(
        self, 
        strategy: Optional[str] = None, 
        environment: Optional[str] = None,
        force_reload: bool = False
    ) -> Dict[str, Any]:
        """
        Get merged configuration combining main config with agent overrides.
        
        Args:
            strategy: Strategy name for strategy-specific overrides
            environment: Environment name for environment-specific overrides
            force_reload: Force reload from files instead of using cache
            
        Returns:
            Merged configuration dictionary
        """
        cache_key = f"{strategy or 'default'}_{environment or 'default'}"
        
        with self._cache_lock:
            if not force_reload and cache_key in self._merged_config_cache:
                self._integration_metrics['cache_hits'] += 1
                return self._merged_config_cache[cache_key].copy()
            
            # Load configurations
            main_config = self.main_config_manager.get_config()
            agent_config = self.agent_config_manager.get_config(strategy, environment)
            
            # Merge configurations
            merged_config = self._merge_configurations(main_config, agent_config)
            
            # Cache the result
            self._merged_config_cache[cache_key] = merged_config.copy()
            self._integration_metrics['cache_misses'] += 1
            self._integration_metrics['merge_operations'] += 1
            self._integration_metrics['last_update'] = datetime.now()
            
            return merged_config
    
    def _merge_configurations(
        self, 
        main_config: CryptoAIBotConfig, 
        agent_config: Any
    ) -> Dict[str, Any]:
        """
        Merge main configuration with agent configuration overrides.
        
        Args:
            main_config: Main configuration object
            agent_config: Agent configuration object
            
        Returns:
            Merged configuration dictionary
        """
        # Convert main config to dictionary
        main_dict = self._config_to_dict(main_config)
        
        # Apply agent overrides
        merged = main_dict.copy()
        
        # Apply core agent settings
        if hasattr(agent_config, 'max_drawdown'):
            merged['agent'] = merged.get('agent', {})
            merged['agent']['max_drawdown'] = agent_config.max_drawdown
        
        if hasattr(agent_config, 'risk_tolerance'):
            merged['agent'] = merged.get('agent', {})
            merged['agent']['risk_tolerance'] = agent_config.risk_tolerance
        
        # Apply enhanced agent settings
        merged['agent_enhanced'] = {
            'drawdown_protection': agent_config.drawdown_protection.__dict__,
            'rolling_limits': agent_config.rolling_limits.__dict__,
            'consecutive_losses': agent_config.consecutive_losses.__dict__,
            'config_cache': agent_config.config_cache.__dict__,
            'memory': agent_config.memory.__dict__,
            'threading': agent_config.threading.__dict__,
            'health_checks': agent_config.health_checks.__dict__,
            'performance_monitoring': agent_config.performance_monitoring.__dict__,
            'alerting': agent_config.alerting.__dict__,
            'compliance': agent_config.compliance.__dict__,
            'validation': agent_config.validation.__dict__,
            'strategy_overrides': {k: v.__dict__ for k, v in agent_config.strategy_overrides.items()},
            'ml_integration': agent_config.ml_integration.__dict__,
            'adaptive_risk': agent_config.adaptive_risk.__dict__,
            'cross_asset': agent_config.cross_asset.__dict__,
            'debug': agent_config.debug.__dict__,
            'diagnostics': agent_config.diagnostics.__dict__,
            'legacy': agent_config.legacy.__dict__
        }
        
        # Apply environment-specific overrides
        if hasattr(agent_config, 'development') and agent_config.development:
            merged['agent_enhanced']['environment_overrides'] = {
                'development': agent_config.development.__dict__
            }
        
        if hasattr(agent_config, 'staging') and agent_config.staging:
            merged['agent_enhanced']['environment_overrides'] = merged['agent_enhanced'].get('environment_overrides', {})
            merged['agent_enhanced']['environment_overrides']['staging'] = agent_config.staging.__dict__
        
        if hasattr(agent_config, 'production') and agent_config.production:
            merged['agent_enhanced']['environment_overrides'] = merged['agent_enhanced'].get('environment_overrides', {})
            merged['agent_enhanced']['environment_overrides']['production'] = agent_config.production.__dict__
        
        return merged
    
    def _config_to_dict(self, config: Any) -> Dict[str, Any]:
        """Convert configuration object to dictionary."""
        if hasattr(config, 'model_dump'):
            return config.model_dump()
        elif hasattr(config, 'dict'):
            return config.dict()
        else:
            return config.__dict__
    
    def get_risk_parameters(
        self, 
        strategy: Optional[str] = None, 
        environment: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get risk parameters for the specified strategy and environment.
        
        Args:
            strategy: Strategy name
            environment: Environment name
            
        Returns:
            Dictionary of risk parameters
        """
        agent_config = self.agent_config_manager.get_config(strategy, environment)
        
        return {
            'max_drawdown': agent_config.max_drawdown,
            'risk_tolerance': agent_config.risk_tolerance,
            'drawdown_protection': {
                'enable_soft_stops': agent_config.drawdown_protection.enable_soft_stops,
                'soft_stop_thresholds': agent_config.drawdown_protection.soft_stop_thresholds,
                'hard_stop_threshold': agent_config.drawdown_protection.hard_stop_threshold,
                'cooldown_after_soft_stop': agent_config.drawdown_protection.cooldown_after_soft_stop,
                'cooldown_after_hard_stop': agent_config.drawdown_protection.cooldown_after_hard_stop
            },
            'rolling_limits': {
                'enable_rolling_windows': agent_config.rolling_limits.enable_rolling_windows,
                'windows': agent_config.rolling_limits.windows
            },
            'consecutive_losses': {
                'max_consecutive_losses': agent_config.consecutive_losses.max_consecutive_losses,
                'cooldown_after_losses': agent_config.consecutive_losses.cooldown_after_losses,
                'progressive_cooldown': agent_config.consecutive_losses.progressive_cooldown
            }
        }
    
    def get_performance_settings(
        self, 
        strategy: Optional[str] = None, 
        environment: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get performance optimization settings.
        
        Args:
            strategy: Strategy name
            environment: Environment name
            
        Returns:
            Dictionary of performance settings
        """
        agent_config = self.agent_config_manager.get_config(strategy, environment)
        
        return {
            'config_cache': {
                'enabled': agent_config.config_cache.enabled,
                'ttl_seconds': agent_config.config_cache.ttl_seconds,
                'max_cache_size': agent_config.config_cache.max_cache_size,
                'hot_reload': agent_config.config_cache.hot_reload,
                'validation_cache': agent_config.config_cache.validation_cache
            },
            'memory': {
                'max_config_history': agent_config.memory.max_config_history,
                'enable_compression': agent_config.memory.enable_compression,
                'cleanup_interval': agent_config.memory.cleanup_interval,
                'max_memory_mb': agent_config.memory.max_memory_mb
            },
            'threading': {
                'config_update_timeout': agent_config.threading.config_update_timeout,
                'max_concurrent_loads': agent_config.threading.max_concurrent_loads,
                'thread_priority': agent_config.threading.thread_priority,
                'enable_async_loading': agent_config.threading.enable_async_loading
            }
        }
    
    def get_monitoring_settings(
        self, 
        strategy: Optional[str] = None, 
        environment: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get monitoring and alerting settings.
        
        Args:
            strategy: Strategy name
            environment: Environment name
            
        Returns:
            Dictionary of monitoring settings
        """
        agent_config = self.agent_config_manager.get_config(strategy, environment)
        
        return {
            'health_checks': {
                'enabled': agent_config.health_checks.enabled,
                'interval_seconds': agent_config.health_checks.interval_seconds,
                'timeout_seconds': agent_config.health_checks.timeout_seconds,
                'enable_metrics': agent_config.health_checks.enable_metrics,
                'alert_on_failure': agent_config.health_checks.alert_on_failure
            },
            'performance_monitoring': {
                'enabled': agent_config.performance_monitoring.enabled,
                'track_config_load_times': agent_config.performance_monitoring.track_config_load_times,
                'track_validation_times': agent_config.performance_monitoring.track_validation_times,
                'track_cache_hit_rates': agent_config.performance_monitoring.track_cache_hit_rates,
                'metrics_retention_hours': agent_config.performance_monitoring.metrics_retention_hours
            },
            'alerting': {
                'config_load_timeout_ms': agent_config.alerting.config_load_timeout_ms,
                'validation_timeout_ms': agent_config.alerting.validation_timeout_ms,
                'cache_hit_rate_threshold': agent_config.alerting.cache_hit_rate_threshold,
                'memory_usage_threshold_mb': agent_config.alerting.memory_usage_threshold_mb
            }
        }
    
    def validate_configuration(
        self, 
        strategy: Optional[str] = None, 
        environment: Optional[str] = None
    ) -> List[str]:
        """
        Validate the merged configuration.
        
        Args:
            strategy: Strategy name
            environment: Environment name
            
        Returns:
            List of validation issues
        """
        try:
            agent_config = self.agent_config_manager.get_config(strategy, environment)
            issues = validate_agent_config(agent_config)
            
            if issues:
                self._integration_metrics['validation_errors'] += len(issues)
                self.logger.warning(f"Configuration validation issues: {issues}")
            
            return issues
            
        except Exception as e:
            error_msg = f"Configuration validation failed: {e}"
            self.logger.error(error_msg)
            self._integration_metrics['validation_errors'] += 1
            return [error_msg]
    
    def get_integration_metrics(self) -> Dict[str, Any]:
        """Get integration performance metrics."""
        agent_metrics = get_agent_performance_metrics()
        
        return {
            'integration': self._integration_metrics,
            'agent_config': {
                'avg_load_time': agent_metrics.avg_load_time,
                'avg_validation_time': agent_metrics.avg_validation_time,
                'cache_hit_ratio': agent_metrics.cache_hit_ratio,
                'memory_usage_mb': agent_metrics.memory_usage_mb,
                'last_update': agent_metrics.last_update.isoformat()
            }
        }
    
    def invalidate_cache(self):
        """Invalidate all caches."""
        with self._cache_lock:
            self._merged_config_cache.clear()
        
        self.agent_config_manager.invalidate_cache()
        self.logger.info("All configuration caches invalidated")
    
    def reload_configuration(self):
        """Reload all configurations from files."""
        self.invalidate_cache()
        
        # Force reload main config
        self.main_config_manager.reload_config()
        
        # Force reload agent config
        self.agent_config_manager.invalidate_cache()
        
        self.logger.info("All configurations reloaded from files")


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

# Global integrator instance
_integrator: Optional[AgentConfigIntegrator] = None
_integrator_lock = threading.RLock()

def get_integrator() -> AgentConfigIntegrator:
    """Get the global integrator instance."""
    global _integrator
    if _integrator is None:
        with _integrator_lock:
            if _integrator is None:
                _integrator = AgentConfigIntegrator()
    return _integrator

def get_merged_config(
    strategy: Optional[str] = None, 
    environment: Optional[str] = None,
    force_reload: bool = False
) -> Dict[str, Any]:
    """Get merged configuration with agent overrides."""
    return get_integrator().get_merged_config(strategy, environment, force_reload)

def get_risk_parameters(
    strategy: Optional[str] = None, 
    environment: Optional[str] = None
) -> Dict[str, Any]:
    """Get risk parameters for the specified strategy and environment."""
    return get_integrator().get_risk_parameters(strategy, environment)

def get_performance_settings(
    strategy: Optional[str] = None, 
    environment: Optional[str] = None
) -> Dict[str, Any]:
    """Get performance optimization settings."""
    return get_integrator().get_performance_settings(strategy, environment)

def get_monitoring_settings(
    strategy: Optional[str] = None, 
    environment: Optional[str] = None
) -> Dict[str, Any]:
    """Get monitoring and alerting settings."""
    return get_integrator().get_monitoring_settings(strategy, environment)

def validate_merged_configuration(
    strategy: Optional[str] = None, 
    environment: Optional[str] = None
) -> List[str]:
    """Validate the merged configuration."""
    return get_integrator().validate_configuration(strategy, environment)

def get_integration_metrics() -> Dict[str, Any]:
    """Get integration performance metrics."""
    return get_integrator().get_integration_metrics()

def reload_all_configurations():
    """Reload all configurations from files."""
    get_integrator().reload_configuration()

def invalidate_all_caches():
    """Invalidate all configuration caches."""
    get_integrator().invalidate_cache()


# =============================================================================
# BACKWARD COMPATIBILITY
# =============================================================================

def get_agent_max_drawdown(strategy: Optional[str] = None, environment: Optional[str] = None) -> float:
    """Get agent max drawdown (backward compatibility)."""
    risk_params = get_risk_parameters(strategy, environment)
    return risk_params['max_drawdown']

def get_agent_risk_tolerance(strategy: Optional[str] = None, environment: Optional[str] = None) -> str:
    """Get agent risk tolerance (backward compatibility)."""
    risk_params = get_risk_parameters(strategy, environment)
    return risk_params['risk_tolerance']

def get_agent_drawdown_protection(strategy: Optional[str] = None, environment: Optional[str] = None) -> Dict[str, Any]:
    """Get agent drawdown protection settings (backward compatibility)."""
    risk_params = get_risk_parameters(strategy, environment)
    return risk_params['drawdown_protection']


# =============================================================================
# MAIN USAGE EXAMPLE
# =============================================================================

if __name__ == "__main__":
    # Example usage
    logging.basicConfig(level=logging.INFO)
    
    # Get merged configuration
    config = get_merged_config()
    print(f"Merged config keys: {list(config.keys())}")
    
    # Get risk parameters for scalping strategy
    risk_params = get_risk_parameters(strategy="scalping")
    print(f"Scalping risk params: {risk_params}")
    
    # Get performance settings
    perf_settings = get_performance_settings()
    print(f"Performance settings: {perf_settings}")
    
    # Get monitoring settings
    monitoring_settings = get_monitoring_settings()
    print(f"Monitoring settings: {monitoring_settings}")
    
    # Validate configuration
    issues = validate_merged_configuration()
    if issues:
        print(f"Validation issues: {issues}")
    else:
        print("Configuration validation passed")
    
    # Get metrics
    metrics = get_integration_metrics()
    print(f"Integration metrics: {metrics}")
    
    # Backward compatibility
    max_dd = get_agent_max_drawdown()
    risk_tol = get_agent_risk_tolerance()
    print(f"Backward compatibility - max_drawdown: {max_dd}, risk_tolerance: {risk_tol}")
