# Public API Import Guide

This guide demonstrates the clean, public API surface for the crypto-ai-bot project. All packages now have explicit `__all__` exports to make navigation easy and prevent import cycles.

## Quick Start Examples

### Core Trading Agents

```python
# Import core trading agents directly
from agents.core import MarketScanner, EnhancedExecutionAgent, analyze

# Or from the top-level agents package
from agents import MarketScanner, EnhancedExecutionAgent

# Initialize market scanner
scanner = MarketScanner(exchange="kraken", symbols=["BTC/USDT"])

# Use execution agent
execution = EnhancedExecutionAgent(config=my_config)

# Analyze signals
result = analyze(context=analysis_context)
```

### Infrastructure Components

```python
# Import Redis and data pipeline components
from agents.infrastructure import RedisCloudClient, DataPipeline
from agents.infrastructure import normalize_symbol, build_stream_key

# Or from top-level
from agents import RedisCloudClient, DataPipeline

# Initialize Redis client with TLS for Redis Cloud
redis_client = RedisCloudClient(
    host="redis-12345.c1.us-east-1-2.ec2.cloud.redislabs.com",
    port=12345,
    password="your-password",
    ssl=True
)

# Create data pipeline
pipeline = DataPipeline(
    redis_client=redis_client,
    symbols=["BTC/USDT", "ETH/USDT"]
)

# Use utility functions
normalized = normalize_symbol("BTCUSDT")  # -> "BTC/USDT"
stream_key = build_stream_key("signals:{symbol}", symbol="BTC/USDT")
```

### Serialization and Contracts

```python
# Import serialization utilities
from agents.core import json_dumps, serialize_for_redis
from agents.core import SignalPayload, MetricsLatencyPayload

# Serialize with Decimal and datetime support
data = {"price": Decimal("50000.123"), "timestamp": datetime.utcnow()}
json_str = json_dumps(data)

# Prepare for Redis
redis_payload = serialize_for_redis(data)

# Use Pydantic contracts for Redis streams
signal = SignalPayload(
    signal_id="sig_123",
    pair="BTC/USDT",
    signal_type="buy",
    strength=0.85,
    timestamp=datetime.utcnow()
)
```

### Configuration Management

```python
# Import configuration loaders
from config import load_system_config, get_stream

# Load environment-specific configuration
config = load_system_config(environment="paper")

# Get Redis stream keys with formatting
signal_stream = get_stream("signals", symbol="BTC/USDT")
metrics_stream = get_stream("metrics_latency")
```

### Logging and Utilities

```python
# Import logging utilities
from utils import get_logger, Timer

# Create structured logger with secret redaction
logger = get_logger(__name__)

# Time operations
with Timer() as t:
    # Your expensive operation
    result = process_data()

logger.info(f"Processing took {t.elapsed:.2f}s")
```

### Structured Logging with Key Constants

```python
# Import centralized logging keys
from agents.core import K_COMPONENT, K_PAIR, K_SIGNAL_ID
from utils import get_logger

logger = get_logger(__name__)

# Use consistent keys across the system
logger.info(
    "Signal generated",
    extra={
        K_COMPONENT: "signal_analyst",
        K_PAIR: "BTC/USDT",
        K_SIGNAL_ID: "sig_123"
    }
)
```

## Package Organization

### `agents.core` - Core Trading Agents

**Main Classes:**
- `MarketScanner` - Market data scanning and monitoring
- `EnhancedExecutionAgent` - Advanced order execution with risk management
- `ScalpingExecutionEngine` - High-frequency scalping execution
- `OrderRequest`, `OrderFill` - Order data structures

**Analysis Functions:**
- `analyze()` - Multi-indicator signal analysis
- `analyze_batch()` - Batch signal analysis

**Serialization:**
- `json_dumps()` - JSON with Decimal/datetime support
- `serialize_for_redis()` - Prepare objects for Redis

**Contracts:**
- `SignalPayload` - Signal message contract
- `MetricsLatencyPayload` - Metrics message contract
- `HealthStatusPayload` - Health check contract

**Logging Keys:**
- `K_COMPONENT`, `K_PAIR`, `K_SIGNAL_ID`, `K_SIGNAL_TYPE`, `K_ACTION`

### `agents.infrastructure` - Infrastructure Services

**Main Classes:**
- `RedisCloudClient` - TLS-enabled Redis Cloud client
- `RedisCloudConfig` - Redis connection configuration
- `RedisHealthChecker` - Comprehensive health monitoring
- `DataPipeline` - Market data ingestion pipeline
- `CircuitBreaker` - API resilience pattern

**Utility Functions:**
- `normalize_symbol()` - Standardize trading pair symbols
- `normalize_trade()` - Normalize trade data format
- `build_stream_key()` - Build Redis stream keys
- `calc_spread_bps()` - Calculate spread in basis points

**Exceptions:**
- `PipelineDegraded` - Pipeline operating in degraded mode
- `CircuitBreakerOpen` - Circuit breaker rejecting requests

### `config` - Configuration Management

**Functions:**
- `load_system_config()` - Load unified system configuration
- `get_config_loader()` - Get singleton config loader
- `get_stream()` - Get Redis stream key with formatting
- `get_all_streams()` - Get all registered streams

### `utils` - Common Utilities

**Classes:**
- `Timer` - Context manager for timing operations
- `LoggerFactory` - Structured logging factory
- `SecretRedactionFilter` - Filter to redact secrets from logs

**Functions:**
- `get_logger()` - Get structured logger
- `get_metrics_logger()` - Get metrics-specific logger
- `setup_logging()` - Initialize logging configuration

## Import Hygiene Best Practices

### ✅ DO: Use clean, top-level imports

```python
from agents.core import MarketScanner, analyze
from agents.infrastructure import RedisCloudClient
from config import load_system_config
```

### ✅ DO: Import from public API surfaces

```python
# Good - uses public API
from agents import MarketScanner, RedisCloudClient

# Good - explicit submodule import
from agents.core import EnhancedExecutionAgent
```

### ❌ DON'T: Import from private modules

```python
# Bad - too deep, internal implementation
from agents.core.execution_agent import _internal_helper

# Bad - importing private functions
from agents.infrastructure.redis_client import _parse_url
```

### ❌ DON'T: Create circular imports

```python
# Bad - circular dependency
# In module A
from module_b import something

# In module B
from module_a import something_else
```

## Testing Imports

Run these commands to verify clean imports work:

```bash
# Activate conda environment
conda activate crypto-bot

# Test core imports
python -c "from agents.core import MarketScanner, EnhancedExecutionAgent, analyze; print('OK')"

# Test infrastructure imports
python -c "from agents.infrastructure import RedisCloudClient, DataPipeline; print('OK')"

# Test top-level imports
python -c "from agents import MarketScanner, RedisCloudClient, json_dumps; print('OK')"

# Test config imports
python -c "from config import load_system_config, get_stream; print('OK')"

# Test utils imports
python -c "from utils import get_logger, Timer; print('OK')"
```

## Integration with main.py

The main.py file demonstrates clean imports in action:

```python
#!/usr/bin/env python3
"""Main entry point with clean imports"""

# Configuration
from config import load_system_config

# Infrastructure
from agents.infrastructure import RedisCloudClient

# Core agents (when needed)
from agents.core import MarketScanner, EnhancedExecutionAgent

# Utilities
from utils import get_logger

# Initialize
logger = get_logger(__name__)
config = load_system_config(environment="paper")

# Use clean, imported APIs
redis_client = RedisCloudClient(**config.redis)
scanner = MarketScanner(exchange="kraken")
```

## Redis Cloud Connection

Example with TLS for Redis Cloud:

```python
from agents.infrastructure import RedisCloudClient
import os

# Redis Cloud typically uses TLS (rediss://)
redis_client = RedisCloudClient(
    host=os.getenv("REDIS_HOST"),
    port=int(os.getenv("REDIS_PORT", "12345")),
    password=os.getenv("REDIS_PASSWORD"),
    ssl=True,  # Enable TLS for Redis Cloud
    ssl_cert_reqs="required",
    decode_responses=True
)

# Test connection
if redis_client.ping():
    print("Connected to Redis Cloud!")
```

## Summary

With these changes, you can now:

1. **Navigate easily**: Import commonly-used components from top-level packages
2. **Avoid cycles**: Explicit `__all__` prevents accidental deep imports
3. **Discover APIs**: Docstrings in `__init__.py` show available exports
4. **Start quickly**: Examples in docstrings and this guide get you running fast

All imports have been tested and verified to work without circular dependencies.
