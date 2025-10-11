# Quick Reference Card - Clean Imports

## Most Common Imports

### Starting a New Script

```python
#!/usr/bin/env python3
"""Your script description"""

# Configuration
from config import load_system_config, get_stream

# Infrastructure
from agents.infrastructure import RedisCloudClient, DataPipeline

# Core agents
from agents.core import MarketScanner, EnhancedExecutionAgent, analyze

# Utilities
from utils import get_logger, Timer

# Logging keys
from agents.core import K_COMPONENT, K_PAIR, K_SIGNAL_ID

# Serialization
from agents.core import json_dumps, serialize_for_redis

# Contracts
from agents.core import SignalPayload, MetricsLatencyPayload
```

### Even Simpler - Top-Level Imports

```python
# Import everything from top-level packages
from agents import (
    MarketScanner,
    EnhancedExecutionAgent,
    RedisCloudClient,
    DataPipeline,
    json_dumps,
    SignalPayload,
)
from config import load_system_config, get_stream
from utils import get_logger, Timer
```

## Common Patterns

### Initialize Logger
```python
from utils import get_logger
logger = get_logger(__name__)
```

### Load Configuration
```python
from config import load_system_config
config = load_system_config(environment="paper")
```

### Connect to Redis Cloud
```python
from agents.infrastructure import RedisCloudClient
import os

client = RedisCloudClient(
    host=os.getenv("REDIS_HOST"),
    port=int(os.getenv("REDIS_PORT", "12345")),
    password=os.getenv("REDIS_PASSWORD"),
    ssl=True,  # Redis Cloud uses TLS
)
```

### Get Stream Keys
```python
from config import get_stream
from agents.infrastructure import normalize_symbol

symbol = normalize_symbol("BTCUSDT")  # -> "BTC/USDT"
stream = get_stream("signals", symbol=symbol)
```

### Structured Logging
```python
from utils import get_logger
from agents.core import K_COMPONENT, K_PAIR

logger = get_logger(__name__)
logger.info(
    "Processing signal",
    extra={
        K_COMPONENT: "signal_processor",
        K_PAIR: "BTC/USDT"
    }
)
```

### Timing Operations
```python
from utils import Timer

with Timer() as t:
    result = expensive_operation()

print(f"Took {t.elapsed:.2f}s")
```

### Serialize for Redis
```python
from agents.core import json_dumps, serialize_for_redis
from decimal import Decimal
from datetime import datetime

data = {
    "price": Decimal("50000.123"),
    "timestamp": datetime.utcnow()
}

# For JSON API responses
json_str = json_dumps(data)

# For Redis storage
redis_payload = serialize_for_redis(data)
```

### Signal Analysis
```python
from agents.core import analyze, AnalysisContext
from datetime import datetime

context = AnalysisContext(
    pair="BTC/USDT",
    close_prices=[50000.0, 50100.0, 50200.0],
    volumes=[100.0, 110.0, 105.0],
    timestamp=datetime.utcnow()
)

signals = analyze(context=context)
```

## Package Quick Reference

| Package | Import From | What You Get |
|---------|-------------|--------------|
| **agents** | `from agents import ...` | All core agents + infrastructure (top-level) |
| **agents.core** | `from agents.core import ...` | Trading agents, analysis, serialization, contracts |
| **agents.infrastructure** | `from agents.infrastructure import ...` | Redis, data pipeline, health checks |
| **config** | `from config import ...` | Configuration loading, stream registry |
| **utils** | `from utils import ...` | Logging, timing, utilities |

## Testing Your Imports

```bash
# Activate conda environment
conda activate crypto-bot

# Test all imports
python -c "
from agents import MarketScanner, RedisCloudClient, json_dumps
from config import load_system_config, get_stream
from utils import get_logger, Timer
print('All imports OK!')
"
```

## Environment Setup

```bash
# Set Redis Cloud credentials
export REDIS_HOST="your-redis-host.cloud.redislabs.com"
export REDIS_PORT="12345"
export REDIS_PASSWORD="your-password"
export REDIS_URL="rediss://:your-password@your-redis-host:12345/0"

# Activate conda environment
conda activate crypto-bot

# Run main application
python -m main run --mode paper

# Run health check
python -m main health
```

## Need More Help?

- **Full guide**: Read `IMPORT_GUIDE.md`
- **Examples**: Check `examples/quick_start_clean_imports.py`
- **Summary**: See `API_SURFACE_IMPROVEMENTS.md`
- **Package docs**: `help(agents.core)` in Python REPL

## Common Gotchas

❌ **Don't do this:**
```python
# Too deep - internal implementation
from agents.core.execution_agent import _internal_function

# Wildcard imports hide what you're using
from agents.core import *
```

✅ **Do this instead:**
```python
# Use public API
from agents.core import EnhancedExecutionAgent

# Be explicit about what you import
from agents.core import MarketScanner, analyze, json_dumps
```

---

**Remember**: All packages have `__all__` defined, so you can trust top-level imports!
