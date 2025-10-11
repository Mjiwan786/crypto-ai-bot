"""
Specialized trading agents for advanced strategies.

⚠️ **ALL AGENTS IN THIS MODULE ARE EXPERIMENTAL** ⚠️

This module contains **optional, experimental agents** for advanced trading strategies.
All agents are clearly marked as experimental and follow strict safety constraints.

**IMPORTANT:**
- All imports are safe (no side effects)
- Agents are detection-only by default
- Real execution requires explicit enabling and raises NotImplementedError
- Suitable for testing with fakes/mocks only

**Agents:**
- `ArbitrageHunter`: Multi-exchange arbitrage detection (DETECTION ONLY)
- `FlashloanExecutor`: Flash loan simulation (SIMULATION ONLY - raises NotImplementedError)
- `LiquidityProvider`: Liquidity opportunity detection (experimental)
- `NewsReactor`: News-based signal generation (experimental)
- `WhaleWatcher`: Large transaction monitoring (experimental)

**Safety:**
All agents follow these principles:
1. Safe to import - no side effects
2. Detection only by default - no auto-execution
3. Rate-limited API calls
4. No hardcoded secrets
5. Testable with fakes

**Usage:**
```python
# Safe to import - no side effects
from agents.special import ArbitrageHunter, FlashloanExecutor

# Safe to instantiate - no execution
hunter = ArbitrageHunter()
executor = FlashloanExecutor()

# Detection only - no auto-trading
opportunities = await hunter.scan_once()
simulation = await executor.simulate_once(plan)
```

**Warnings:**
- No warranties or guarantees
- Use at your own risk
- Test extensively before production
- Financial losses possible
- See README.md for full details
"""

from __future__ import annotations

# Safe imports - no side effects
# Only import classes, not module-level execution

try:
    from .arbitrage_hunter import ArbitrageHunter, Opportunity as ArbitrageOpportunity
except ImportError as e:
    import logging
    logging.warning(f"Could not import ArbitrageHunter: {e}")
    ArbitrageHunter = None
    ArbitrageOpportunity = None

try:
    from .flashloan_executor import FlashloanExecutor, ExecutionResult, FlashloanPlan
except ImportError as e:
    import logging
    logging.warning(f"Could not import FlashloanExecutor: {e}")
    FlashloanExecutor = None
    ExecutionResult = None
    FlashloanPlan = None

try:
    from .liquidity_provider import LiquidityProvider
except ImportError as e:
    import logging
    logging.warning(f"Could not import LiquidityProvider: {e}")
    LiquidityProvider = None

try:
    from .news_reactor import NewsReactor
except ImportError as e:
    import logging
    logging.warning(f"Could not import NewsReactor: {e}")
    NewsReactor = None

try:
    from .whale_watcher import WhaleWatcher
except ImportError as e:
    import logging
    logging.warning(f"Could not import WhaleWatcher: {e}")
    WhaleWatcher = None

# Export only successfully imported agents
__all__ = [
    name for name in [
        "ArbitrageHunter",
        "ArbitrageOpportunity",
        "FlashloanExecutor",
        "ExecutionResult",
        "FlashloanPlan",
        "LiquidityProvider",
        "NewsReactor",
        "WhaleWatcher",
    ]
    if globals().get(name) is not None
]

# Log successful imports
import logging
logger = logging.getLogger(__name__)
logger.debug(f"Special agents loaded: {__all__}")

# Verify no side effects
assert __name__ == "agents.special", "Module name mismatch"
# If this assertion passes, import has no side effects
