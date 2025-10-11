# Enhanced Agent Configuration Manager

## Overview

The Enhanced Agent Configuration Manager (`agent_config_manager.py`) is a production-ready, feature-complete configuration management system for the crypto AI bot. It provides centralized configuration management, real-time updates via Redis/MCP, comprehensive validation, and deployment readiness checks.

## Key Features

### ✅ Centralized Agent Config Management
- Loads agent configurations from `.env`, `settings.yaml`, or `agent_settings.yaml`
- Normalizes configs into a standard schema for all agents
- Supports strategy-specific and environment-specific overrides
- Thread-safe singleton pattern with caching

### ✅ Validation & Safety Checks
- Comprehensive Pydantic v2 validation
- Prevents dangerous defaults (live trading without confirmation, invalid allocations)
- Risk parameter validation with configurable ranges
- Deployment readiness validation

### ✅ Runtime Updates
- **Redis Streams Integration**: Real-time config updates via Redis streams
- **MCP Integration**: Handles `PolicyUpdate`, `Signal`, and other MCP events
- **Dynamic Propagation**: Broadcasts config changes to all agents
- **Hot Reload**: File-based configuration changes without restart

### ✅ Agent Isolation
- Each agent requests its configuration slice through the manager
- Strategy-specific overrides (scalping, trend following, etc.)
- Environment-specific overrides (development, staging, production)
- Clean separation of config logic from trading logic

### ✅ Live Trading Safety
- **Confirmation Required**: Live trading requires explicit confirmation
- **Emergency Stop**: Instant emergency stop capability
- **Safety Checks**: Comprehensive safety validation before enabling live trading
- **Paper Trading Fallback**: Automatic fallback to paper trading mode

### ✅ Deployment Readiness
- **Comprehensive Checks**: Redis, Kraken API, environment variables, risk limits
- **System Resources**: Disk space, memory usage validation
- **Health Monitoring**: Real-time health checks for monitoring systems
- **Performance Metrics**: Detailed performance monitoring and optimization

## Usage Examples

### Basic Configuration Access

```python
from config.agent_config_manager import get_agent_config

# Get default configuration
config = get_agent_config()

# Get configuration with strategy override
scalping_config = get_agent_config(strategy="scalping")

# Get configuration with environment override
dev_config = get_agent_config(environment="development")
```

### Redis Integration and Runtime Updates

```python
import asyncio
from config.agent_config_manager import (
    initialize_redis_integration, 
    broadcast_config_update,
    ConfigUpdateType
)

async def setup_runtime_updates():
    # Initialize Redis integration
    success = await initialize_redis_integration(redis_manager)
    
    if success:
        # Broadcast a risk override update
        await broadcast_config_update(
            ConfigUpdateType.RISK_OVERRIDE,
            {"max_drawdown": 0.20, "risk_tolerance": "high"},
            source="risk_manager"
        )

# Run the setup
asyncio.run(setup_runtime_updates())
```

### Deployment Readiness Validation

```python
import asyncio
from config.agent_config_manager import validate_deployment_readiness

async def check_deployment():
    report = await validate_deployment_readiness()
    
    print(f"Deployment Status: {report.overall_status.value}")
    print(f"Total Duration: {report.total_duration_ms:.1f}ms")
    
    for check in report.checks:
        status = "✓" if check.status else "✗"
        critical = "!" if check.critical else ""
        print(f"{status} {critical} {check.name}: {check.message}")

asyncio.run(check_deployment())
```

### Live Trading Safety

```python
from config.agent_config_manager import (
    get_live_trading_status,
    is_live_trading_safe,
    emergency_stop
)

# Check live trading status
status = get_live_trading_status()
print(f"Live Trading Enabled: {status['enabled']}")
print(f"Safe to Trade: {status['safe']}")
print(f"Emergency Stop Active: {status['emergency_stop']}")

# Check if live trading is safe
if is_live_trading_safe():
    print("Live trading is safe to proceed")
else:
    print("Live trading is not safe - check configuration")

# Emergency stop (if needed)
emergency_stop()
```

### Performance Monitoring

```python
from config.agent_config_manager import (
    get_performance_summary,
    health_check,
    optimize_for_production
)

# Apply production optimizations
optimize_for_production()

# Get performance summary
perf = get_performance_summary()
print(f"Cache Hit Ratio: {perf['cache_performance']['hit_ratio']:.2%}")
print(f"Avg Load Time: {perf['timing_metrics']['avg_load_time_ms']:.1f}ms")

# Health check
import asyncio
async def monitor_health():
    health = await health_check()
    print(f"System Status: {health['status']}")
    print(f"Response Time: {health['response_time_ms']:.1f}ms")

asyncio.run(monitor_health())
```

## Configuration Schema

The configuration system supports a comprehensive schema with the following main sections:

### Core Risk Management
- `max_drawdown`: Maximum allowed drawdown (0.01-0.5)
- `risk_tolerance`: Risk tolerance level (low/medium/high)
- `drawdown_protection`: Soft stops and hard stops
- `rolling_limits`: Rolling window risk limits
- `consecutive_losses`: Consecutive loss protection

### Performance Optimization
- `config_cache`: Caching configuration
- `memory`: Memory management settings
- `threading`: Threading and concurrency settings
- `hot_reload`: File-based hot reloading

### Monitoring & Alerting
- `health_checks`: Health monitoring configuration
- `performance_monitoring`: Performance tracking
- `alerting`: Alert thresholds and settings

### Production Features
- `live_trading`: Live trading safety configuration
- `runtime_updates`: Redis/MCP integration settings
- `deployment`: Deployment readiness checks

### Environment Overrides
- `development`: Development environment settings
- `staging`: Staging environment settings
- `production`: Production environment settings

## MCP Integration

The system integrates with the Model Context Protocol (MCP) for real-time policy updates:

### Supported MCP Events
- **PolicyUpdate**: Strategy allocations and risk overrides
- **Signal**: Trading signals from analysts
- **OrderIntent**: Order execution requests
- **MetricsTick**: Performance metrics

### Redis Streams
- **Policy Updates**: `policy:updates` stream
- **Config Updates**: `config:updates` stream
- **Health Checks**: `health:checks` stream

## Deployment Checklist

Before deploying to production:

1. **Environment Variables**: Set required environment variables
   ```bash
   export REDIS_URL="redis://localhost:6379"
   export KRAKEN_API_KEY="your_api_key"
   export KRAKEN_API_SECRET="your_api_secret"
   export ENVIRONMENT="production"
   ```

2. **Configuration File**: Ensure `config/agent_settings.yaml` exists and is valid

3. **Redis Connection**: Verify Redis is accessible and configured

4. **Deployment Validation**: Run deployment readiness check
   ```python
   import asyncio
   from config.agent_config_manager import validate_deployment_readiness
   
   async def main():
       report = await validate_deployment_readiness()
       if report.overall_status.value != "ready":
           print("Deployment not ready - fix issues first")
           return
       print("Deployment ready!")
   
   asyncio.run(main())
   ```

5. **Live Trading**: If enabling live trading, ensure proper confirmation flow

## Error Handling

The system includes comprehensive error handling:

- **Graceful Degradation**: Falls back to safe defaults on errors
- **Structured Logging**: Production-optimized logging with appropriate levels
- **Exception Handling**: Uncaught exception handling and reporting
- **Validation Errors**: Clear validation error messages with context

## Performance Considerations

- **Caching**: LRU cache with configurable TTL
- **Async Loading**: Asynchronous configuration loading
- **Thread Safety**: Thread-safe operations with proper locking
- **Memory Management**: Configurable memory limits and cleanup
- **Hot Reload**: File monitoring for configuration changes

## Security Features

- **Live Trading Confirmation**: Requires explicit confirmation for live trading
- **Emergency Stop**: Instant emergency stop capability
- **Validation**: Comprehensive input validation and sanitization
- **Audit Logging**: Configurable audit logging for compliance
- **Environment Isolation**: Separate configurations for different environments

## Monitoring and Observability

- **Health Checks**: Comprehensive health monitoring
- **Performance Metrics**: Detailed performance tracking
- **Structured Logging**: JSON-structured logs for monitoring systems
- **Alerting**: Configurable alerting thresholds
- **Metrics Export**: Performance metrics for external monitoring

## Migration from Legacy

The system maintains backward compatibility:

- **Legacy API**: Maintains old API for gradual migration
- **Deprecation Warnings**: Warns about deprecated features
- **Migration Mode**: Special mode for configuration migration

## Troubleshooting

### Common Issues

1. **Redis Connection Failed**
   - Check Redis URL and connectivity
   - Verify Redis server is running
   - Check network connectivity

2. **Configuration Validation Failed**
   - Check YAML syntax
   - Verify required fields are present
   - Check value ranges and types

3. **Live Trading Not Safe**
   - Check emergency stop status
   - Verify confirmation requirements
   - Check risk parameter validation

4. **Performance Issues**
   - Check cache hit ratios
   - Monitor memory usage
   - Review threading configuration

### Debug Mode

Enable debug mode for detailed logging:

```yaml
agent:
  debug:
    enabled: true
    verbose_logging: true
    config_dump: true
    performance_profiling: true
```

## API Reference

### Core Functions
- `get_agent_config(strategy, environment)`: Get configuration
- `validate_deployment_readiness()`: Validate deployment
- `initialize_redis_integration(redis_manager)`: Setup Redis
- `broadcast_config_update(type, data, source)`: Broadcast updates

### Safety Functions
- `is_live_trading_safe()`: Check trading safety
- `get_live_trading_status()`: Get trading status
- `emergency_stop()`: Activate emergency stop
- `reset_emergency_stop()`: Reset emergency stop

### Monitoring Functions
- `health_check()`: System health check
- `get_performance_summary()`: Performance metrics
- `optimize_for_production()`: Apply optimizations

This enhanced configuration manager provides a robust, production-ready foundation for managing agent configurations with real-time updates, comprehensive validation, and safety features.




