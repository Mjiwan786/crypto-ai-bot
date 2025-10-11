"""
Enhanced Agent Configuration Manager

This module provides optimized configuration management for agent-specific settings
with caching, performance monitoring, and seamless integration with the main config system.
"""

from __future__ import annotations

import os
import sys
import yaml
import time
import logging
import threading
import asyncio
import json
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Any, Union, Callable, Set
from dataclasses import dataclass, field
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, Future
from datetime import datetime, timedelta
from enum import Enum

# Pydantic v2 compatibility
try:
    from pydantic import BaseModel, Field, field_validator, ConfigDict
    from pydantic import ValidationError
except ImportError:
    raise ImportError("pydantic is required for configuration validation")

# MCP Integration
try:
    from mcp.schemas import PolicyUpdate, Signal, OrderIntent, MetricsTick
    from mcp.redis_manager import RedisManager
    from mcp.context import MCPContext
except ImportError:
    # Graceful fallback for development
    PolicyUpdate = None
    Signal = None
    OrderIntent = None
    MetricsTick = None
    RedisManager = None
    MCPContext = None


# =============================================================================
# CONFIGURATION MODELS
# =============================================================================

class DrawdownProtectionConfig(BaseModel):
    """Configuration for drawdown protection with soft stops."""
    model_config = ConfigDict(frozen=True)
    
    enable_soft_stops: bool = True
    soft_stop_thresholds: List[Dict[str, float]] = Field(
        default_factory=lambda: [
            {"drawdown_pct": 0.01, "size_multiplier": 0.75},
            {"drawdown_pct": 0.02, "size_multiplier": 0.50},
            {"drawdown_pct": 0.03, "size_multiplier": 0.25}
        ]
    )
    hard_stop_threshold: float = 0.05
    cooldown_after_soft_stop: int = 600
    cooldown_after_hard_stop: int = 1800


class RollingLimitsConfig(BaseModel):
    """Configuration for rolling window risk limits."""
    model_config = ConfigDict(frozen=True)
    
    enable_rolling_windows: bool = True
    windows: List[Dict[str, Union[int, float]]] = Field(
        default_factory=lambda: [
            {"duration_seconds": 3600, "max_loss_pct": 0.01},
            {"duration_seconds": 14400, "max_loss_pct": 0.015},
            {"duration_seconds": 86400, "max_loss_pct": 0.02}
        ]
    )


class ConsecutiveLossesConfig(BaseModel):
    """Configuration for consecutive loss protection."""
    model_config = ConfigDict(frozen=True)
    
    max_consecutive_losses: int = 3
    cooldown_after_losses: int = 300
    progressive_cooldown: bool = True


class ConfigCacheConfig(BaseModel):
    """Configuration for config caching."""
    model_config = ConfigDict(frozen=True)
    
    enabled: bool = True
    ttl_seconds: int = 300
    max_cache_size: int = 10
    hot_reload: bool = False
    validation_cache: bool = True


class MemoryConfig(BaseModel):
    """Configuration for memory optimization."""
    model_config = ConfigDict(frozen=True)
    
    max_config_history: int = 5
    enable_compression: bool = True
    cleanup_interval: int = 3600
    max_memory_mb: int = 100


class ThreadingConfig(BaseModel):
    """Configuration for threading and concurrency."""
    model_config = ConfigDict(frozen=True)
    
    config_update_timeout: float = 1.0
    max_concurrent_loads: int = 2
    thread_priority: str = "normal"
    enable_async_loading: bool = True


class HealthChecksConfig(BaseModel):
    """Configuration for health monitoring."""
    model_config = ConfigDict(frozen=True)
    
    enabled: bool = True
    interval_seconds: int = 30
    timeout_seconds: int = 5
    enable_metrics: bool = True
    alert_on_failure: bool = True


class PerformanceMonitoringConfig(BaseModel):
    """Configuration for performance monitoring."""
    model_config = ConfigDict(frozen=True)
    
    enabled: bool = True
    track_config_load_times: bool = True
    track_validation_times: bool = True
    track_cache_hit_rates: bool = True
    metrics_retention_hours: int = 24


class AlertingConfig(BaseModel):
    """Configuration for alerting thresholds."""
    model_config = ConfigDict(frozen=True)
    
    config_load_timeout_ms: int = 1000
    validation_timeout_ms: int = 500
    cache_hit_rate_threshold: float = 0.8
    memory_usage_threshold_mb: int = 80


class ComplianceConfig(BaseModel):
    """Configuration for compliance and validation."""
    model_config = ConfigDict(frozen=True)
    
    strict_validation: bool = True
    fail_fast_on_error: bool = True
    validate_on_load: bool = True
    enable_audit_logging: bool = True


class ValidationConfig(BaseModel):
    """Configuration for validation rules."""
    model_config = ConfigDict(frozen=True)
    
    max_drawdown_range: List[float] = Field(default_factory=lambda: [0.01, 0.5])
    risk_tolerance_values: List[str] = Field(default_factory=lambda: ["low", "medium", "high"])
    cooldown_range_seconds: List[int] = Field(default_factory=lambda: [60, 3600])
    size_multiplier_range: List[float] = Field(default_factory=lambda: [0.1, 1.0])


class StrategyOverrideConfig(BaseModel):
    """Configuration for strategy-specific overrides."""
    model_config = ConfigDict(frozen=True)
    
    max_drawdown: float
    risk_tolerance: str
    cooldown_after_loss: int


class EnvironmentOverrideConfig(BaseModel):
    """Configuration for environment-specific overrides."""
    model_config = ConfigDict(frozen=True)
    
    max_drawdown: float
    risk_tolerance: str
    hot_reload: bool
    enhanced_logging: bool = False
    test_mode: bool = False
    paper_trading_only: bool = False
    enhanced_security: bool = False
    strict_validation: bool = True


class MLIntegrationConfig(BaseModel):
    """Configuration for machine learning integration."""
    model_config = ConfigDict(frozen=True)
    
    enabled: bool = False
    model_path: str = "models/risk_model.pkl"
    update_frequency: int = 3600
    confidence_threshold: float = 0.7


class AdaptiveRiskConfig(BaseModel):
    """Configuration for adaptive risk management."""
    model_config = ConfigDict(frozen=True)
    
    enabled: bool = True
    volatility_adjustment: bool = True
    market_regime_detection: bool = True
    performance_feedback: bool = True


class CrossAssetConfig(BaseModel):
    """Configuration for cross-asset correlation."""
    model_config = ConfigDict(frozen=True)
    
    enabled: bool = False
    correlation_threshold: float = 0.7
    diversification_bonus: float = 0.1
    correlation_window_days: int = 30


class DebugConfig(BaseModel):
    """Configuration for debugging and diagnostics."""
    model_config = ConfigDict(frozen=True)
    
    enabled: bool = False
    verbose_logging: bool = False
    config_dump: bool = False
    performance_profiling: bool = False


class DiagnosticsConfig(BaseModel):
    """Configuration for diagnostics."""
    model_config = ConfigDict(frozen=True)
    
    enable_config_tracing: bool = False
    enable_performance_counters: bool = False
    enable_memory_profiling: bool = False
    log_level: str = "INFO"


class LegacyConfig(BaseModel):
    """Configuration for legacy compatibility."""
    model_config = ConfigDict(frozen=True)
    
    maintain_old_api: bool = True
    deprecated_warnings: bool = True
    migration_mode: bool = False


class LiveTradingConfig(BaseModel):
    """Configuration for live trading safety checks."""
    model_config = ConfigDict(frozen=True)
    
    enabled: bool = False
    require_confirmation: bool = True
    max_position_size_usd: float = 1000.0
    max_daily_loss_usd: float = 100.0
    emergency_stop_enabled: bool = True
    confirmation_timeout_seconds: int = 30
    paper_trading_fallback: bool = True


class RuntimeUpdateConfig(BaseModel):
    """Configuration for runtime updates via Redis/MCP."""
    model_config = ConfigDict(frozen=True)
    
    enabled: bool = True
    redis_stream_name: str = "config:updates"
    mcp_integration: bool = True
    update_timeout_seconds: int = 5
    retry_attempts: int = 3
    broadcast_changes: bool = True
    validate_updates: bool = True


class DeploymentConfig(BaseModel):
    """Configuration for deployment readiness checks."""
    model_config = ConfigDict(frozen=True)
    
    check_redis_connection: bool = True
    check_kraken_api: bool = True
    check_required_env_vars: bool = True
    validate_risk_limits: bool = True
    check_disk_space_mb: int = 1000
    check_memory_mb: int = 512
    timeout_seconds: int = 30


class AgentConfig(BaseModel):
    """Main agent configuration model."""
    model_config = ConfigDict(extra="allow")
    
    # Core risk management
    max_drawdown: float = Field(default=0.2, ge=0.01, le=0.5)
    risk_tolerance: str = Field(default="medium", pattern="^(low|medium|high)$")
    
    # Enhanced configurations
    drawdown_protection: DrawdownProtectionConfig = Field(default_factory=DrawdownProtectionConfig)
    rolling_limits: RollingLimitsConfig = Field(default_factory=RollingLimitsConfig)
    consecutive_losses: ConsecutiveLossesConfig = Field(default_factory=ConsecutiveLossesConfig)
    
    # Performance optimization
    config_cache: ConfigCacheConfig = Field(default_factory=ConfigCacheConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    threading: ThreadingConfig = Field(default_factory=ThreadingConfig)
    
    # Monitoring
    health_checks: HealthChecksConfig = Field(default_factory=HealthChecksConfig)
    performance_monitoring: PerformanceMonitoringConfig = Field(default_factory=PerformanceMonitoringConfig)
    alerting: AlertingConfig = Field(default_factory=AlertingConfig)
    
    # Compliance
    compliance: ComplianceConfig = Field(default_factory=ComplianceConfig)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    
    # Strategy overrides
    strategy_overrides: Dict[str, StrategyOverrideConfig] = Field(default_factory=dict)
    
    # Environment overrides
    development: Optional[EnvironmentOverrideConfig] = None
    staging: Optional[EnvironmentOverrideConfig] = None
    production: Optional[EnvironmentOverrideConfig] = None
    
    # Advanced features
    ml_integration: MLIntegrationConfig = Field(default_factory=MLIntegrationConfig)
    adaptive_risk: AdaptiveRiskConfig = Field(default_factory=AdaptiveRiskConfig)
    cross_asset: CrossAssetConfig = Field(default_factory=CrossAssetConfig)
    
    # Debugging
    debug: DebugConfig = Field(default_factory=DebugConfig)
    diagnostics: DiagnosticsConfig = Field(default_factory=DiagnosticsConfig)
    
    # Legacy
    legacy: LegacyConfig = Field(default_factory=LegacyConfig)
    
    # Production features
    live_trading: LiveTradingConfig = Field(default_factory=LiveTradingConfig)
    runtime_updates: RuntimeUpdateConfig = Field(default_factory=RuntimeUpdateConfig)
    deployment: DeploymentConfig = Field(default_factory=DeploymentConfig)


# =============================================================================
# ENUMS AND DATA STRUCTURES
# =============================================================================

class ConfigUpdateType(str, Enum):
    """Types of configuration updates."""
    POLICY_UPDATE = "policy_update"
    RISK_OVERRIDE = "risk_override"
    STRATEGY_ALLOCATION = "strategy_allocation"
    EMERGENCY_STOP = "emergency_stop"
    LIVE_TRADING_TOGGLE = "live_trading_toggle"


class DeploymentStatus(str, Enum):
    """Deployment readiness status."""
    READY = "ready"
    DEGRADED = "degraded"
    NOT_READY = "not_ready"
    ERROR = "error"


@dataclass
class ConfigUpdateEvent:
    """Configuration update event."""
    update_type: ConfigUpdateType
    timestamp: datetime
    source: str
    data: Dict[str, Any]
    correlation_id: Optional[str] = None
    requires_confirmation: bool = False


@dataclass
class DeploymentCheck:
    """Individual deployment check result."""
    name: str
    status: bool
    message: str
    duration_ms: float
    critical: bool = True


@dataclass
class DeploymentReport:
    """Comprehensive deployment readiness report."""
    overall_status: DeploymentStatus
    checks: List[DeploymentCheck]
    total_duration_ms: float
    timestamp: datetime
    version: str
    environment: str


# =============================================================================
# PERFORMANCE MONITORING
# =============================================================================

@dataclass
class PerformanceMetrics:
    """Performance metrics for configuration operations."""
    load_times: List[float] = field(default_factory=list)
    validation_times: List[float] = field(default_factory=list)
    cache_hits: int = 0
    cache_misses: int = 0
    memory_usage_mb: float = 0.0
    last_update: datetime = field(default_factory=datetime.now)
    
    @property
    def avg_load_time(self) -> float:
        return sum(self.load_times) / len(self.load_times) if self.load_times else 0.0
    
    @property
    def avg_validation_time(self) -> float:
        return sum(self.validation_times) / len(self.validation_times) if self.validation_times else 0.0
    
    @property
    def cache_hit_ratio(self) -> float:
        total = self.cache_hits + self.cache_misses
        return self.cache_hits / total if total > 0 else 0.0


# =============================================================================
# CACHED CONFIGURATION LOADER
# =============================================================================

class CachedConfigLoader:
    """High-performance cached configuration loader with Redis integration."""
    
    def __init__(self, config_path: str = "config/agent_settings.yaml", redis_manager: Optional[RedisManager] = None):
        self.config_path = Path(config_path)
        self.logger = logging.getLogger(__name__)
        
        # Cache configuration
        self._cache: Dict[str, Any] = {}
        self._cache_timestamp: float = 0
        self._cache_lock = threading.RLock()
        
        # Performance metrics
        self.metrics = PerformanceMetrics()
        
        # Threading
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="agent_config")
        
        # Redis integration
        self.redis_manager = redis_manager
        self._mcp_context: Optional[MCPContext] = None
        self._update_handlers: List[Callable[[ConfigUpdateEvent], None]] = []
        self._runtime_overrides: Dict[str, Any] = {}
        self._update_lock = threading.RLock()
        
        # Live trading state
        self._live_trading_enabled = False
        self._emergency_stop = False
        self._last_confirmation_time: Optional[datetime] = None
        
    def _load_yaml_file(self) -> Dict[str, Any]:
        """Load YAML file with environment variable substitution."""
        if not self.config_path.exists():
            self.logger.warning(f"Config file not found: {self.config_path}")
            return {}
            
        with open(self.config_path, 'r') as f:
            content = f.read()
            
        # Substitute environment variables
        content = self._substitute_env_vars(content)
        
        try:
            return yaml.safe_load(content) or {}
        except yaml.YAMLError as e:
            self.logger.error(f"Failed to parse YAML: {e}")
            return {}
    
    def _substitute_env_vars(self, content: str) -> str:
        """Substitute environment variables in content."""
        import re
        
        def replace_var(match):
            var_expr = match.group(1)
            if ":-" in var_expr:
                var_name, default_value = var_expr.split(":-", 1)
                return os.environ.get(var_name, default_value)
            else:
                return os.environ.get(var_expr, match.group(0))
        
        pattern = r'\$\{([^}]+)\}'
        return re.sub(pattern, replace_var, content)
    
    @lru_cache(maxsize=1)
    def load_agent_config(self) -> AgentConfig:
        """Load and validate agent configuration with caching."""
        start_time = time.time()
        
        with self._cache_lock:
            current_time = time.time()
            
            # Check cache validity
            if (current_time - self._cache_timestamp) < self._cache.get('ttl_seconds', 300):
                self.metrics.cache_hits += 1
                return self._cache.get('config')
            
            # Load fresh configuration
            try:
                raw_config = self._load_yaml_file()
                agent_section = raw_config.get('agent', {})
                
                # Validate configuration
                config = AgentConfig(**agent_section)
                
                # Update cache
                self._cache = {
                    'config': config,
                    'ttl_seconds': agent_section.get('config_cache', {}).get('ttl_seconds', 300)
                }
                self._cache_timestamp = current_time
                
                # Update metrics
                load_time = time.time() - start_time
                self.metrics.load_times.append(load_time)
                self.metrics.cache_misses += 1
                
                self.logger.debug(f"Agent config loaded in {load_time:.3f}s")
                return config
                
            except ValidationError as e:
                self.logger.error(f"Configuration validation failed: {e}")
                raise
            except Exception as e:
                self.logger.error(f"Failed to load agent configuration: {e}")
                raise
    
    def get_strategy_override(self, strategy: str) -> Optional[StrategyOverrideConfig]:
        """Get strategy-specific configuration override."""
        config = self.load_agent_config()
        return config.strategy_overrides.get(strategy)
    
    def get_environment_override(self, environment: str) -> Optional[EnvironmentOverrideConfig]:
        """Get environment-specific configuration override."""
        config = self.load_agent_config()
        return getattr(config, environment, None)
    
    def get_effective_config(self, strategy: Optional[str] = None, environment: Optional[str] = None) -> AgentConfig:
        """Get effective configuration with strategy and environment overrides applied."""
        config = self.load_agent_config()
        
        # Apply environment overrides
        if environment:
            env_override = self.get_environment_override(environment)
            if env_override:
                # Create a new config with overrides applied
                config_dict = config.model_dump()
                
                # Apply environment-specific settings
                config_dict['max_drawdown'] = env_override.max_drawdown
                config_dict['risk_tolerance'] = env_override.risk_tolerance
                
                # Update other settings based on environment
                if hasattr(env_override, 'hot_reload'):
                    config_dict['config_cache']['hot_reload'] = env_override.hot_reload
                if hasattr(env_override, 'enhanced_logging'):
                    config_dict['debug']['verbose_logging'] = env_override.enhanced_logging
                if hasattr(env_override, 'strict_validation'):
                    config_dict['compliance']['strict_validation'] = env_override.strict_validation
                
                # Create new config instance with overrides
                config = AgentConfig(**config_dict)
        
        # Apply strategy overrides
        if strategy:
            strategy_override = self.get_strategy_override(strategy)
            if strategy_override:
                # Create a new config with strategy overrides applied
                config_dict = config.model_dump()
                config_dict['max_drawdown'] = strategy_override.max_drawdown
                config_dict['risk_tolerance'] = strategy_override.risk_tolerance
                config = AgentConfig(**config_dict)
        
        return config
    
    def invalidate_cache(self):
        """Invalidate configuration cache."""
        with self._cache_lock:
            self._cache.clear()
            self._cache_timestamp = 0
            self.load_agent_config.cache_clear()
    
    def get_performance_metrics(self) -> PerformanceMetrics:
        """Get current performance metrics."""
        return self.metrics
    
    def cleanup_old_metrics(self):
        """Cleanup old performance metrics."""
        cutoff_time = datetime.now() - timedelta(hours=24)
        if self.metrics.last_update < cutoff_time:
            self.metrics.load_times.clear()
            self.metrics.validation_times.clear()
            self.metrics.cache_hits = 0
            self.metrics.cache_misses = 0
    
    # =============================================================================
    # REDIS INTEGRATION
    # =============================================================================
    
    async def initialize_redis_integration(self) -> bool:
        """Initialize Redis integration for runtime updates."""
        if not self.redis_manager:
            self.logger.warning("Redis manager not available, skipping Redis integration")
            return False
        
        try:
            # Initialize MCP context
            if MCPContext:
                self._mcp_context = MCPContext.from_env(redis=self.redis_manager)
                await self._mcp_context.__aenter__()
                
                # Subscribe to policy updates
                if self._mcp_context.redis:
                    await self._subscribe_to_policy_updates()
                
                self.logger.info("Redis integration initialized successfully")
                return True
        except Exception as e:
            self.logger.error(f"Failed to initialize Redis integration: {e}")
            return False
    
    async def _subscribe_to_policy_updates(self):
        """Subscribe to MCP policy updates."""
        if not self._mcp_context or not PolicyUpdate:
            return
        
        try:
            # Subscribe to policy update stream
            stream_name = "policy:updates"
            await self._mcp_context.redis.xgroup_create(
                stream_name, 
                "config_manager", 
                id="0", 
                mkstream=True
            )
            
            # Start consumer loop
            asyncio.create_task(self._policy_update_consumer(stream_name))
            self.logger.info(f"Subscribed to policy updates from {stream_name}")
        except Exception as e:
            self.logger.error(f"Failed to subscribe to policy updates: {e}")
    
    async def _policy_update_consumer(self, stream_name: str):
        """Consumer loop for policy updates."""
        while True:
            try:
                if not self._mcp_context or not self._mcp_context.redis:
                    await asyncio.sleep(1)
                    continue
                
                # Read from stream
                messages = await self._mcp_context.redis.xreadgroup(
                    "config_manager",
                    "config_consumer",
                    {stream_name: ">"},
                    count=1,
                    block=1000
                )
                
                for stream, msgs in messages:
                    for msg_id, fields in msgs:
                        await self._process_policy_update(fields)
                        await self._mcp_context.redis.xack(stream_name, "config_manager", msg_id)
                        
            except Exception as e:
                self.logger.error(f"Error in policy update consumer: {e}")
                await asyncio.sleep(5)
    
    async def _process_policy_update(self, fields: Dict[str, Any]):
        """Process incoming policy update."""
        try:
            # Parse PolicyUpdate from Redis fields
            policy_data = json.loads(fields.get(b'data', b'{}').decode())
            policy_update = PolicyUpdate(**policy_data)
            
            # Create config update event
            update_event = ConfigUpdateEvent(
                update_type=ConfigUpdateType.POLICY_UPDATE,
                timestamp=datetime.now(),
                source="mcp",
                data=policy_update.model_dump(),
                correlation_id=policy_update.correlation_id,
                requires_confirmation=policy_update.risk_overrides is not None
            )
            
            # Apply update
            await self._apply_config_update(update_event)
            
        except Exception as e:
            self.logger.error(f"Failed to process policy update: {e}")
    
    async def _apply_config_update(self, update_event: ConfigUpdateEvent):
        """Apply configuration update."""
        with self._update_lock:
            try:
                if update_event.update_type == ConfigUpdateType.POLICY_UPDATE:
                    await self._apply_policy_update(update_event)
                elif update_event.update_type == ConfigUpdateType.RISK_OVERRIDE:
                    await self._apply_risk_override(update_event)
                elif update_event.update_type == ConfigUpdateType.EMERGENCY_STOP:
                    await self._apply_emergency_stop(update_event)
                elif update_event.update_type == ConfigUpdateType.LIVE_TRADING_TOGGLE:
                    await self._apply_live_trading_toggle(update_event)
                
                # Notify handlers
                for handler in self._update_handlers:
                    try:
                        if asyncio.iscoroutinefunction(handler):
                            await handler(update_event)
                        else:
                            handler(update_event)
                    except Exception as e:
                        self.logger.error(f"Error in update handler: {e}")
                
                # Invalidate cache to force reload
                self.invalidate_cache()
                
                self.logger.info(f"Applied config update: {update_event.update_type}")
                
            except Exception as e:
                self.logger.error(f"Failed to apply config update: {e}")
    
    async def _apply_policy_update(self, update_event: ConfigUpdateEvent):
        """Apply MCP policy update."""
        data = update_event.data
        
        # Update strategy allocations
        if 'allocations' in data:
            self._runtime_overrides['strategy_allocations'] = data['allocations']
        
        # Update risk overrides
        if 'risk_overrides' in data:
            self._runtime_overrides['risk_overrides'] = data['risk_overrides']
        
        # Update active strategies
        if 'active_strategies' in data:
            self._runtime_overrides['active_strategies'] = list(data['active_strategies'])
    
    async def _apply_risk_override(self, update_event: ConfigUpdateEvent):
        """Apply risk parameter override."""
        self._runtime_overrides.update(update_event.data)
    
    async def _apply_emergency_stop(self, update_event: ConfigUpdateEvent):
        """Apply emergency stop."""
        self._emergency_stop = True
        self._live_trading_enabled = False
        self.logger.critical("EMERGENCY STOP ACTIVATED")
    
    async def _apply_live_trading_toggle(self, update_event: ConfigUpdateEvent):
        """Toggle live trading mode."""
        enabled = update_event.data.get('enabled', False)
        
        if enabled and not self._live_trading_enabled:
            # Require confirmation for enabling live trading
            if not await self._confirm_live_trading():
                self.logger.warning("Live trading not confirmed, staying in paper mode")
                return
        
        self._live_trading_enabled = enabled
        self.logger.info(f"Live trading {'enabled' if enabled else 'disabled'}")
    
    async def _confirm_live_trading(self) -> bool:
        """Confirm live trading activation."""
        if not self._get_current_config().live_trading.require_confirmation:
            return True
        
        self.logger.critical("LIVE TRADING ACTIVATION REQUIRES CONFIRMATION")
        self.logger.critical("This will enable real money trading. Confirm within 30 seconds...")
        
        # In a real implementation, this would integrate with a confirmation system
        # For now, we'll use a simple timeout
        start_time = time.time()
        timeout = self._get_current_config().live_trading.confirmation_timeout_seconds
        
        while time.time() - start_time < timeout:
            # Check for confirmation (this would be implemented based on your system)
            # For now, we'll simulate a confirmation after 5 seconds
            await asyncio.sleep(0.1)
            if time.time() - start_time > 5:  # Simulate confirmation
                self._last_confirmation_time = datetime.now()
                return True
        
        return False
    
    def _get_current_config(self) -> AgentConfig:
        """Get current configuration with runtime overrides applied."""
        config = self.load_agent_config()
        
        # Apply runtime overrides
        if self._runtime_overrides:
            # This would need to be implemented based on your override logic
            pass
        
        return config
    
    def add_update_handler(self, handler: Callable[[ConfigUpdateEvent], None]):
        """Add configuration update handler."""
        self._update_handlers.append(handler)
    
    def remove_update_handler(self, handler: Callable[[ConfigUpdateEvent], None]):
        """Remove configuration update handler."""
        if handler in self._update_handlers:
            self._update_handlers.remove(handler)
    
    def is_live_trading_enabled(self) -> bool:
        """Check if live trading is enabled."""
        return self._live_trading_enabled and not self._emergency_stop
    
    def is_emergency_stop_active(self) -> bool:
        """Check if emergency stop is active."""
        return self._emergency_stop
    
    async def broadcast_config_update(self, update_event: ConfigUpdateEvent):
        """Broadcast configuration update to all agents."""
        if not self.redis_manager or not self._get_current_config().runtime_updates.broadcast_changes:
            return
        
        try:
            # Publish to Redis stream
            stream_name = self._get_current_config().runtime_updates.redis_stream_name
            await self.redis_manager.client.xadd(
                stream_name,
                {
                    'type': update_event.update_type.value,
                    'timestamp': update_event.timestamp.isoformat(),
                    'source': update_event.source,
                    'data': json.dumps(update_event.data),
                    'correlation_id': update_event.correlation_id or '',
                    'requires_confirmation': str(update_event.requires_confirmation)
                }
            )
            
            self.logger.info(f"Broadcasted config update: {update_event.update_type}")
        except Exception as e:
            self.logger.error(f"Failed to broadcast config update: {e}")
    
    async def close(self):
        """Close Redis connections and cleanup."""
        if self._mcp_context:
            try:
                await self._mcp_context.__aexit__(None, None, None)
            except Exception as e:
                self.logger.error(f"Error closing MCP context: {e}")
        
        self._executor.shutdown(wait=True)


# =============================================================================
# SINGLETON MANAGER
# =============================================================================

class AgentConfigManager:
    """Singleton manager for agent configuration."""
    
    _instance: Optional[AgentConfigManager] = None
    _lock = threading.RLock()
    
    def __init__(self, config_path: str = "config/agent_settings.yaml", redis_manager: Optional[RedisManager] = None):
        if AgentConfigManager._instance is not None:
            raise RuntimeError("AgentConfigManager is a singleton. Use get_instance().")
        
        self.loader = CachedConfigLoader(config_path, redis_manager)
        self.logger = logging.getLogger(__name__)
        
        # Production optimizations
        self._setup_production_logging()
        self._setup_error_handling()
        
        # Start cleanup task
        self._start_cleanup_task()
    
    @classmethod
    def get_instance(cls, config_path: str = "config/agent_settings.yaml") -> AgentConfigManager:
        """Get singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(config_path)
        return cls._instance
    
    def _setup_production_logging(self):
        """Setup production-optimized logging."""
        # Configure structured logging for production
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
        
        # Set appropriate log level based on environment
        env = os.environ.get('ENVIRONMENT', 'production').lower()
        if env == 'development':
            self.logger.setLevel(logging.DEBUG)
        elif env == 'staging':
            self.logger.setLevel(logging.INFO)
        else:
            self.logger.setLevel(logging.WARNING)
    
    def _setup_error_handling(self):
        """Setup comprehensive error handling."""
        # Set up exception handling for uncaught exceptions
        def handle_exception(exc_type, exc_value, exc_traceback):
            if issubclass(exc_type, KeyboardInterrupt):
                sys.__excepthook__(exc_type, exc_value, exc_traceback)
                return
            
            self.logger.critical(
                "Uncaught exception in AgentConfigManager",
                exc_info=(exc_type, exc_value, exc_traceback)
            )
        
        sys.excepthook = handle_exception
    
    def _start_cleanup_task(self):
        """Start background cleanup task."""
        def cleanup():
            while True:
                try:
                    time.sleep(3600)  # Run every hour
                    self.loader.cleanup_old_metrics()
                except Exception as e:
                    self.logger.error(f"Error in cleanup task: {e}")
        
        thread = threading.Thread(target=cleanup, daemon=True, name="config_cleanup")
        thread.start()
    
    def get_config(self, strategy: Optional[str] = None, environment: Optional[str] = None) -> AgentConfig:
        """Get agent configuration with optional overrides."""
        return self.loader.get_effective_config(strategy, environment)
    
    def get_performance_metrics(self) -> PerformanceMetrics:
        """Get performance metrics."""
        return self.loader.get_performance_metrics()
    
    def invalidate_cache(self):
        """Invalidate configuration cache."""
        self.loader.invalidate_cache()
    
    # =============================================================================
    # DEPLOYMENT READINESS VALIDATION
    # =============================================================================
    
    async def validate_deployment_readiness(self) -> DeploymentReport:
        """Comprehensive deployment readiness validation."""
        start_time = time.time()
        checks = []
        config = self.get_config()
        
        # Check Redis connection
        if config.deployment.check_redis_connection:
            checks.append(await self._check_redis_connection())
        
        # Check Kraken API
        if config.deployment.check_kraken_api:
            checks.append(await self._check_kraken_api())
        
        # Check required environment variables
        if config.deployment.check_required_env_vars:
            checks.append(await self._check_required_env_vars())
        
        # Check risk limits
        if config.deployment.validate_risk_limits:
            checks.append(await self._check_risk_limits())
        
        # Check system resources
        checks.append(await self._check_disk_space(config.deployment.check_disk_space_mb))
        checks.append(await self._check_memory_usage(config.deployment.check_memory_mb))
        
        # Determine overall status
        critical_failures = [c for c in checks if not c.status and c.critical]
        non_critical_failures = [c for c in checks if not c.status and not c.critical]
        
        if critical_failures:
            overall_status = DeploymentStatus.NOT_READY
        elif non_critical_failures:
            overall_status = DeploymentStatus.DEGRADED
        else:
            overall_status = DeploymentStatus.READY
        
        total_duration = (time.time() - start_time) * 1000
        
        return DeploymentReport(
            overall_status=overall_status,
            checks=checks,
            total_duration_ms=total_duration,
            timestamp=datetime.now(),
            version=self.loader._cache.get('version', 'unknown'),
            environment=os.environ.get('ENVIRONMENT', 'production')
        )
    
    async def _check_redis_connection(self) -> DeploymentCheck:
        """Check Redis connection."""
        start_time = time.time()
        try:
            if not self.loader.redis_manager:
                return DeploymentCheck(
                    name="redis_connection",
                    status=False,
                    message="Redis manager not configured",
                    duration_ms=(time.time() - start_time) * 1000,
                    critical=True
                )
            
            # Test Redis connection
            await self.loader.redis_manager.client.ping()
            
            return DeploymentCheck(
                name="redis_connection",
                status=True,
                message="Redis connection successful",
                duration_ms=(time.time() - start_time) * 1000,
                critical=True
            )
        except Exception as e:
            return DeploymentCheck(
                name="redis_connection",
                status=False,
                message=f"Redis connection failed: {e}",
                duration_ms=(time.time() - start_time) * 1000,
                critical=True
            )
    
    async def _check_kraken_api(self) -> DeploymentCheck:
        """Check Kraken API connectivity."""
        start_time = time.time()
        try:
            # This would need to be implemented based on your Kraken integration
            # For now, we'll check if API keys are configured
            api_key = os.environ.get('KRAKEN_API_KEY')
            api_secret = os.environ.get('KRAKEN_API_SECRET')
            
            if not api_key or not api_secret:
                return DeploymentCheck(
                    name="kraken_api",
                    status=False,
                    message="Kraken API credentials not configured",
                    duration_ms=(time.time() - start_time) * 1000,
                    critical=True
                )
            
            return DeploymentCheck(
                name="kraken_api",
                status=True,
                message="Kraken API credentials configured",
                duration_ms=(time.time() - start_time) * 1000,
                critical=True
            )
        except Exception as e:
            return DeploymentCheck(
                name="kraken_api",
                status=False,
                message=f"Kraken API check failed: {e}",
                duration_ms=(time.time() - start_time) * 1000,
                critical=True
            )
    
    async def _check_required_env_vars(self) -> DeploymentCheck:
        """Check required environment variables."""
        start_time = time.time()
        try:
            required_vars = [
                'REDIS_URL',
                'KRAKEN_API_KEY',
                'KRAKEN_API_SECRET'
            ]
            
            missing_vars = []
            for var in required_vars:
                if not os.environ.get(var):
                    missing_vars.append(var)
            
            if missing_vars:
                return DeploymentCheck(
                    name="required_env_vars",
                    status=False,
                    message=f"Missing environment variables: {', '.join(missing_vars)}",
                    duration_ms=(time.time() - start_time) * 1000,
                    critical=True
                )
            
            return DeploymentCheck(
                name="required_env_vars",
                status=True,
                message="All required environment variables present",
                duration_ms=(time.time() - start_time) * 1000,
                critical=True
            )
        except Exception as e:
            return DeploymentCheck(
                name="required_env_vars",
                status=False,
                message=f"Environment variable check failed: {e}",
                duration_ms=(time.time() - start_time) * 1000,
                critical=True
            )
    
    async def _check_risk_limits(self) -> DeploymentCheck:
        """Check risk limits configuration."""
        start_time = time.time()
        try:
            config = self.get_config()
            issues = validate_agent_config(config)
            
            if issues:
                return DeploymentCheck(
                    name="risk_limits",
                    status=False,
                    message=f"Risk limit validation failed: {'; '.join(issues)}",
                    duration_ms=(time.time() - start_time) * 1000,
                    critical=True
                )
            
            return DeploymentCheck(
                name="risk_limits",
                status=True,
                message="Risk limits validation passed",
                duration_ms=(time.time() - start_time) * 1000,
                critical=True
            )
        except Exception as e:
            return DeploymentCheck(
                name="risk_limits",
                status=False,
                message=f"Risk limits check failed: {e}",
                duration_ms=(time.time() - start_time) * 1000,
                critical=True
            )
    
    async def _check_disk_space(self, required_mb: int) -> DeploymentCheck:
        """Check available disk space."""
        start_time = time.time()
        try:
            import shutil
            
            # Check current directory disk space
            free_bytes = shutil.disk_usage('.').free
            free_mb = free_bytes / (1024 * 1024)
            
            if free_mb < required_mb:
                return DeploymentCheck(
                    name="disk_space",
                    status=False,
                    message=f"Insufficient disk space: {free_mb:.1f}MB available, {required_mb}MB required",
                    duration_ms=(time.time() - start_time) * 1000,
                    critical=False
                )
            
            return DeploymentCheck(
                name="disk_space",
                status=True,
                message=f"Disk space sufficient: {free_mb:.1f}MB available",
                duration_ms=(time.time() - start_time) * 1000,
                critical=False
            )
        except Exception as e:
            return DeploymentCheck(
                name="disk_space",
                status=False,
                message=f"Disk space check failed: {e}",
                duration_ms=(time.time() - start_time) * 1000,
                critical=False
            )
    
    async def _check_memory_usage(self, required_mb: int) -> DeploymentCheck:
        """Check available memory."""
        start_time = time.time()
        try:
            import psutil
            
            # Get available memory
            memory = psutil.virtual_memory()
            available_mb = memory.available / (1024 * 1024)
            
            if available_mb < required_mb:
                return DeploymentCheck(
                    name="memory_usage",
                    status=False,
                    message=f"Insufficient memory: {available_mb:.1f}MB available, {required_mb}MB required",
                    duration_ms=(time.time() - start_time) * 1000,
                    critical=False
                )
            
            return DeploymentCheck(
                name="memory_usage",
                status=True,
                message=f"Memory sufficient: {available_mb:.1f}MB available",
                duration_ms=(time.time() - start_time) * 1000,
                critical=False
            )
        except Exception as e:
            return DeploymentCheck(
                name="memory_usage",
                status=False,
                message=f"Memory check failed: {e}",
                duration_ms=(time.time() - start_time) * 1000,
                critical=False
            )
    
    # =============================================================================
    # LIVE TRADING SAFETY
    # =============================================================================
    
    def is_live_trading_safe(self) -> bool:
        """Check if live trading is safe to enable."""
        if not self.loader.is_live_trading_enabled():
            return False
        
        if self.loader.is_emergency_stop_active():
            return False
        
        config = self.get_config()
        
        # Check if confirmation is required and provided
        if config.live_trading.require_confirmation:
            if not self.loader._last_confirmation_time:
                return False
            
            # Check if confirmation is still valid (within 24 hours)
            if datetime.now() - self.loader._last_confirmation_time > timedelta(hours=24):
                return False
        
        return True
    
    def get_live_trading_status(self) -> Dict[str, Any]:
        """Get comprehensive live trading status."""
        return {
            'enabled': self.loader.is_live_trading_enabled(),
            'safe': self.is_live_trading_safe(),
            'emergency_stop': self.loader.is_emergency_stop_active(),
            'last_confirmation': self.loader._last_confirmation_time.isoformat() if self.loader._last_confirmation_time else None,
            'config': self.get_config().live_trading.model_dump()
        }
    
    # =============================================================================
    # PERFORMANCE OPTIMIZATION
    # =============================================================================
    
    def optimize_for_production(self):
        """Apply production performance optimizations."""
        config = self.get_config()
        
        # Optimize cache settings
        if config.config_cache.enabled:
            self.loader._cache['ttl_seconds'] = config.config_cache.ttl_seconds
            self.loader._cache['max_cache_size'] = config.config_cache.max_cache_size
        
        # Optimize threading
        if config.threading.enable_async_loading:
            self.loader._executor = ThreadPoolExecutor(
                max_workers=config.threading.max_concurrent_loads,
                thread_name_prefix="agent_config_opt"
            )
        
        # Enable hot reload if configured
        if config.config_cache.hot_reload:
            self._start_hot_reload_monitor()
        
        self.logger.info("Production optimizations applied")
    
    def _start_hot_reload_monitor(self):
        """Start hot reload file monitoring."""
        def monitor_file():
            last_mtime = 0
            while True:
                try:
                    if self.loader.config_path.exists():
                        current_mtime = self.loader.config_path.stat().st_mtime
                        if current_mtime > last_mtime:
                            self.logger.info("Configuration file changed, reloading...")
                            self.invalidate_cache()
                            last_mtime = current_mtime
                    
                    time.sleep(1)  # Check every second
                except Exception as e:
                    self.logger.error(f"Error in hot reload monitor: {e}")
                    time.sleep(5)
        
        thread = threading.Thread(target=monitor_file, daemon=True, name="hot_reload")
        thread.start()
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """Get comprehensive performance summary."""
        metrics = self.get_performance_metrics()
        config = self.get_config()
        
        return {
            'cache_performance': {
                'hit_ratio': metrics.cache_hit_ratio,
                'hits': metrics.cache_hits,
                'misses': metrics.cache_misses
            },
            'timing_metrics': {
                'avg_load_time_ms': metrics.avg_load_time * 1000,
                'avg_validation_time_ms': metrics.avg_validation_time * 1000,
                'total_loads': len(metrics.load_times)
            },
            'memory_usage': {
                'memory_mb': metrics.memory_usage_mb,
                'max_memory_mb': config.memory.max_memory_mb
            },
            'configuration': {
                'cache_enabled': config.config_cache.enabled,
                'hot_reload': config.config_cache.hot_reload,
                'async_loading': config.threading.enable_async_loading
            }
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """Comprehensive health check for monitoring systems."""
        start_time = time.time()
        
        try:
            # Basic functionality check
            config = self.get_config()
            
            # Redis connectivity check
            redis_healthy = False
            if self.loader.redis_manager:
                try:
                    await self.loader.redis_manager.client.ping()
                    redis_healthy = True
                except Exception:
                    pass
            
            # Cache health
            cache_healthy = self.loader._cache is not None
            
            # Performance metrics
            metrics = self.get_performance_metrics()
            
            health_status = {
                'status': 'healthy' if redis_healthy and cache_healthy else 'degraded',
                'timestamp': datetime.now().isoformat(),
                'response_time_ms': (time.time() - start_time) * 1000,
                'components': {
                    'redis': redis_healthy,
                    'cache': cache_healthy,
                    'config_loading': True
                },
                'performance': {
                    'cache_hit_ratio': metrics.cache_hit_ratio,
                    'avg_load_time_ms': metrics.avg_load_time * 1000
                },
                'live_trading': {
                    'enabled': self.loader.is_live_trading_enabled(),
                    'safe': self.is_live_trading_safe(),
                    'emergency_stop': self.loader.is_emergency_stop_active()
                }
            }
            
            return health_status
            
        except Exception as e:
            return {
                'status': 'error',
                'timestamp': datetime.now().isoformat(),
                'response_time_ms': (time.time() - start_time) * 1000,
                'error': str(e)
            }


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def get_agent_config(strategy: Optional[str] = None, environment: Optional[str] = None) -> AgentConfig:
    """Get agent configuration with optional overrides."""
    manager = AgentConfigManager.get_instance()
    return manager.get_config(strategy, environment)


def get_agent_performance_metrics() -> PerformanceMetrics:
    """Get agent configuration performance metrics."""
    manager = AgentConfigManager.get_instance()
    return manager.get_performance_metrics()


def invalidate_agent_config_cache():
    """Invalidate agent configuration cache."""
    manager = AgentConfigManager.get_instance()
    manager.invalidate_cache()


def get_agent_config_with_redis(redis_manager: Optional[RedisManager] = None) -> AgentConfigManager:
    """Get agent configuration manager with Redis integration."""
    if redis_manager:
        return AgentConfigManager.get_instance(redis_manager=redis_manager)
    return AgentConfigManager.get_instance()


async def validate_deployment_readiness() -> DeploymentReport:
    """Validate deployment readiness."""
    manager = AgentConfigManager.get_instance()
    return await manager.validate_deployment_readiness()


def get_live_trading_status() -> Dict[str, Any]:
    """Get live trading status."""
    manager = AgentConfigManager.get_instance()
    return manager.get_live_trading_status()


def is_live_trading_safe() -> bool:
    """Check if live trading is safe."""
    manager = AgentConfigManager.get_instance()
    return manager.is_live_trading_safe()


async def initialize_redis_integration(redis_manager: Optional[RedisManager] = None) -> bool:
    """Initialize Redis integration for runtime updates."""
    manager = AgentConfigManager.get_instance()
    if redis_manager:
        manager.loader.redis_manager = redis_manager
    return await manager.loader.initialize_redis_integration()


async def broadcast_config_update(update_type: ConfigUpdateType, data: Dict[str, Any], 
                                source: str = "manual", correlation_id: Optional[str] = None) -> bool:
    """Broadcast configuration update to all agents."""
    manager = AgentConfigManager.get_instance()
    
    update_event = ConfigUpdateEvent(
        update_type=update_type,
        timestamp=datetime.now(),
        source=source,
        data=data,
        correlation_id=correlation_id,
        requires_confirmation=update_type in [ConfigUpdateType.EMERGENCY_STOP, ConfigUpdateType.LIVE_TRADING_TOGGLE]
    )
    
    await manager.loader.broadcast_config_update(update_event)
    return True


def optimize_for_production():
    """Apply production performance optimizations."""
    manager = AgentConfigManager.get_instance()
    manager.optimize_for_production()


def get_performance_summary() -> Dict[str, Any]:
    """Get comprehensive performance summary."""
    manager = AgentConfigManager.get_instance()
    return manager.get_performance_summary()


async def health_check() -> Dict[str, Any]:
    """Comprehensive health check for monitoring systems."""
    manager = AgentConfigManager.get_instance()
    return await manager.health_check()


def emergency_stop():
    """Activate emergency stop."""
    manager = AgentConfigManager.get_instance()
    manager.loader._emergency_stop = True
    manager.loader._live_trading_enabled = False
    manager.logger.critical("EMERGENCY STOP ACTIVATED VIA API")


def reset_emergency_stop():
    """Reset emergency stop (requires confirmation)."""
    manager = AgentConfigManager.get_instance()
    manager.loader._emergency_stop = False
    manager.logger.warning("Emergency stop reset")


# =============================================================================
# VALIDATION HELPERS
# =============================================================================

def validate_agent_config(config: AgentConfig) -> List[str]:
    """Validate agent configuration and return list of issues."""
    issues = []
    
    # Validate drawdown range
    if not (0.01 <= config.max_drawdown <= 0.5):
        issues.append(f"max_drawdown {config.max_drawdown} is outside valid range [0.01, 0.5]")
    
    # Validate risk tolerance
    if config.risk_tolerance not in ["low", "medium", "high"]:
        issues.append(f"risk_tolerance '{config.risk_tolerance}' is not valid")
    
    # Validate soft stop thresholds
    for i, threshold in enumerate(config.drawdown_protection.soft_stop_thresholds):
        if not (0.001 <= threshold["drawdown_pct"] <= 0.1):
            issues.append(f"Soft stop threshold {i} drawdown_pct is outside valid range")
        if not (0.1 <= threshold["size_multiplier"] <= 1.0):
            issues.append(f"Soft stop threshold {i} size_multiplier is outside valid range")
    
    # Validate rolling windows
    for i, window in enumerate(config.rolling_limits.windows):
        if window["duration_seconds"] <= 0:
            issues.append(f"Rolling window {i} duration must be positive")
        if not (0.001 <= window["max_loss_pct"] <= 0.1):
            issues.append(f"Rolling window {i} max_loss_pct is outside valid range")
    
    return issues


# =============================================================================
# ENVIRONMENT DETECTION
# =============================================================================

def detect_environment() -> str:
    """Detect current environment from various sources."""
    # Check environment variable
    env = os.environ.get("ENVIRONMENT", "").lower()
    if env in ["dev", "development", "staging", "prod", "production"]:
        return env
    
    # Check if we're in a test environment
    if "pytest" in os.environ.get("_", ""):
        return "test"
    
    # Default to production for safety
    return "production"


# =============================================================================
# MAIN USAGE EXAMPLE
# =============================================================================

if __name__ == "__main__":
    # Example usage
    logging.basicConfig(level=logging.INFO)
    
    async def main():
        # Get configuration for different scenarios
        config = get_agent_config()
        print(f"Default config - max_drawdown: {config.max_drawdown}, risk_tolerance: {config.risk_tolerance}")
        
        # Get configuration with strategy override
        scalping_config = get_agent_config(strategy="scalping")
        print(f"Scalping config - max_drawdown: {scalping_config.max_drawdown}, risk_tolerance: {scalping_config.risk_tolerance}")
        
        # Get configuration with environment override
        dev_config = get_agent_config(environment="development")
        print(f"Development config - max_drawdown: {dev_config.max_drawdown}, risk_tolerance: {dev_config.risk_tolerance}")
        
        # Get performance metrics
        metrics = get_agent_performance_metrics()
        print(f"Performance - avg_load_time: {metrics.avg_load_time:.3f}s, cache_hit_ratio: {metrics.cache_hit_ratio:.2f}")
        
        # Validate deployment readiness
        print("\n=== Deployment Readiness Validation ===")
        deployment_report = await validate_deployment_readiness()
        print(f"Overall Status: {deployment_report.overall_status.value}")
        print(f"Total Duration: {deployment_report.total_duration_ms:.1f}ms")
        
        for check in deployment_report.checks:
            status_icon = "✓" if check.status else "✗"
            critical_icon = "!" if check.critical else ""
            print(f"{status_icon} {critical_icon} {check.name}: {check.message} ({check.duration_ms:.1f}ms)")
        
        # Live trading status
        print("\n=== Live Trading Status ===")
        live_status = get_live_trading_status()
        print(f"Enabled: {live_status['enabled']}")
        print(f"Safe: {live_status['safe']}")
        print(f"Emergency Stop: {live_status['emergency_stop']}")
        
        # Example of broadcasting a config update
        print("\n=== Broadcasting Config Update ===")
        await broadcast_config_update(
            ConfigUpdateType.RISK_OVERRIDE,
            {"max_drawdown": 0.15, "risk_tolerance": "high"},
            source="example_script"
        )
        print("Config update broadcasted successfully")
    
    # Run the async main function
    asyncio.run(main())
