# Log Keys Migration Guide

## Overview

Created centralized logging key constants in `agents/core/log_keys.py` to replace magic strings throughout the codebase. This improves maintainability, enables IDE autocomplete, and prevents typos in structured logging.

## What Was Created

### agents/core/log_keys.py (NEW)

Comprehensive module with 150+ logging key constants organized into categories:

- **Trading Keys**: K_SYMBOL, K_PAIR, K_ORDER_ID, K_SIDE, K_PRICE, K_QUANTITY, etc.
- **System Keys**: K_COMPONENT, K_MODULE, K_SESSION_ID, K_REQUEST_ID, etc.
- **Performance Keys**: K_LATENCY_MS, K_DURATION_MS, K_LAT_P95, K_OPERATION, etc.
- **Error Keys**: K_ERROR, K_ERROR_TYPE, K_ORIGINAL_ERROR, K_TRACEBACK, etc.
- **Risk Keys**: K_RISK_TYPE, K_CURRENT_VALUE, K_LIMIT_VALUE, etc.
- **Network Keys**: K_STREAM, K_ENDPOINT, K_API_METHOD, K_HTTP_STATUS, etc.

## Migration Pattern

### Before (Magic Strings)
```python
logger.info("Trade executed", extra={
    "component": "execution_agent",
    "pair": "BTC/USD",
    "strategy": "scalp",
    "order_id": "123",
    "latency_ms": 45.2
})

details = {
    "symbol": symbol,
    "original_error": str(e),
    "config_key": "redis_url"
}
```

### After (Constants)
```python
from agents.core.log_keys import (
    K_COMPONENT, K_PAIR, K_STRATEGY,
    K_ORDER_ID, K_LATENCY_MS
)

logger.info("Trade executed", extra={
    K_COMPONENT: "execution_agent",
    K_PAIR: "BTC/USD",
    K_STRATEGY: "scalp",
    K_ORDER_ID: "123",
    K_LATENCY_MS: 45.2
})

from agents.core.log_keys import K_SYMBOL, K_ORIGINAL_ERROR, K_CONFIG_KEY

details = {
    K_SYMBOL: symbol,
    K_ORIGINAL_ERROR: str(e),
    K_CONFIG_KEY: "redis_url"
}
```

## Files Requiring Migration

### Priority 1: High-frequency logging files

#### agents/scalper/infra/logger.py (764 lines)

**Patterns to replace:**
- `"category":` → `K_CATEGORY` (8 occurrences)
- `"event_type":` → `K_EVENT_TYPE` (6 occurrences)
- `"trade_data":` → `K_TRADE_DATA` (3 occurrences)
- `"risk_data":` → `K_RISK_DATA` (3 occurrences)
- `"system_data":` → `K_SYSTEM_DATA` (2 occurrences)
- `"timestamp_ms":` → `K_TIMESTAMP_MS` (6 occurrences)
- `"component":` → `K_COMPONENT` (2 occurrences)
- `"operation":` → `K_OPERATION` (2 occurrences)
- `"duration_ms":` → `K_DURATION_MS` (2 occurrences)
- `"pair":` → `K_PAIR` (multiple)
- `"side":` → `K_SIDE` (multiple)
- `"size":` → `K_SIZE` (multiple)
- `"price":` → `K_PRICE` (multiple)
- `"notional":` → `K_NOTIONAL` (1 occurrence)
- `"order_id":` → `K_ORDER_ID` (multiple)
- `"risk_type":` → `K_RISK_TYPE` (2 occurrences)
- `"current_value":` → `K_CURRENT_VALUE` (2 occurrences)
- `"limit":` → `K_LIMIT` (2 occurrences)
- `"breach_amount":` → `K_BREACH_AMOUNT` (2 occurrences)
- `"action_taken":` → `K_ACTION_TAKEN` (2 occurrences)
- `"version":` → `K_VERSION` (2 occurrences)
- `"config":` → `K_CONFIG` (2 occurrences)
- `"strategy":` → `K_STRATEGY` (multiple)

**Lines to update:**
- 276, 277, 278, 279 (log_trade_event)
- 288, 289, 290, 291 (log_risk_event)
- 300, 301, 302, 303 (log_system_event)
- 471 (log_trade)
- 484-487 (log_performance)
- 494 (log_market_data)
- 499 (log_execution)
- 505 (log_risk)
- 398-405 (log_trade_execution function)
- 419-424 (log_risk_breach function)
- 441-445 (log_system_startup function)

#### agents/scalper/infra/metrics.py

**Pattern to replace:**
- Line 1827: `{"component": "execution"}` → `{K_COMPONENT: "execution"}`

### Priority 2: Error handling in agents/core/*.py

#### agents/core/errors.py

No changes needed - this module defines the exception classes that use details dicts, but doesn't log.

#### agents/core/execution_agent.py

**Patterns to replace in exception details:**
- `"intent":`  → `K_ORDER_INTENT`
- `"original_error":` → `K_ORIGINAL_ERROR`
- `"reason":` → `K_REJECTION_REASON`

**Lines:** 89, 159, 470

#### agents/core/market_scanner.py

**Patterns to replace in exception details:**
- `"missing_package":` → `K_MISSING_PACKAGE`
- `"install_command":` → `K_INSTALL_COMMAND`
- `"config_path":` → `K_CONFIG_PATH`
- `"pairs_found":` → `K_PAIRS_FOUND`
- `"original_error":` → `K_ORIGINAL_ERROR`
- `"symbol":` → `K_SYMBOL`
- `"bid":` → `K_BID`
- `"ask":` → `K_ASK`
- `"last":` → `K_LAST_PRICE`
- `"timeframe":` → `K_TIMEFRAME`
- `"required_bars":` → `K_REQUIRED_BARS`
- `"actual_bars":` → `K_ACTUAL_BARS`

**Lines:** 36, 93, 139-140, 149, 162, 190, 202, 223, 232

#### agents/core/signal_processor.py (1435 lines)

**Patterns to replace in Redis/error details:**
- `"env_var":` → leave as-is (config specific)
- `"redis_url":` → `K_REDIS_URL`
- `"original_error":` → `K_ORIGINAL_ERROR`

**Lines:** 462, 499, 505

#### agents/core/autogen_wrappers.py

**Patterns to replace:**
- `"error_type":` → `K_ERROR_TYPE`
- `"intent":` → `K_ORDER_INTENT`
- `"original_error":` → `K_ORIGINAL_ERROR`
- `"signal":` → leave as-is or create K_SIGNAL
- `"features":` → `K_FEATURES`
- `"symbol":` → `K_SYMBOL`
- `"strategy":` → `K_STRATEGY`

**Lines:** 79, 89, 127, 161-162, 169, 204-205, 335, 366, 397

## Migration Steps

### Step 1: Import the constants

Add to the top of each file:

```python
from agents.core.log_keys import (
    K_CATEGORY, K_COMPONENT, K_EVENT_TYPE,
    K_TRADE_DATA, K_RISK_DATA, K_SYSTEM_DATA,
    K_TIMESTAMP_MS, K_OPERATION, K_DURATION_MS,
    K_PAIR, K_SIDE, K_SIZE, K_PRICE, K_ORDER_ID,
    K_SYMBOL, K_ORIGINAL_ERROR, K_CONFIG_KEY,
    # Add others as needed
)
```

### Step 2: Replace magic strings

Use find-and-replace or sed:

```bash
# Example for agents/scalper/infra/logger.py
sed -i 's/"category":/K_CATEGORY:/g' agents/scalper/infra/logger.py
sed -i 's/"event_type":/K_EVENT_TYPE:/g' agents/scalper/infra/logger.py
sed -i 's/"trade_data":/K_TRADE_DATA:/g' agents/scalper/infra/logger.py
# ... etc
```

**IMPORTANT**: Be careful with replacements in:
- Docstrings (keep human-readable)
- Comments (keep human-readable)
- Dict keys in serialization (keep as strings for JSON compatibility)

### Step 3: Verify with grep

```bash
# Should return 0 matches
grep -R '"component":' agents/core/ agents/scalper/infra/
grep -R '"category":' agents/scalper/infra/
grep -R '"original_error":' agents/core/
```

### Step 4: Run tests

```bash
python -m pytest tests/ -v
python test_exports.py
```

## Benefits After Migration

1. **IDE Autocomplete**: Type `K_` and see all available keys
2. **Type Safety**: Typos caught at import time, not runtime
3. **Refactoring**: Change a key name once, update everywhere
4. **Documentation**: Constants are self-documenting
5. **Searchability**: Find all uses of a key with "Find References"

## Special Cases

### JSON Serialization

When serializing to JSON/Redis, the keys will still be strings:

```python
# Dict uses constants
log_data = {
    K_PAIR: "BTC/USD",
    K_PRICE: 50000.0
}

# But JSON output is still strings
# {"pair": "BTC/USD", "price": 50000.0}
```

This works because Python dict keys are evaluated:
```python
K_PAIR = "pair"  # The constant value
{K_PAIR: "value"}  # Becomes {"pair": "value"}
```

### Dataclass to_dict() Methods

In `agents/core/types.py`, the `to_dict()` methods use hardcoded strings for JSON compatibility. This is intentional and should NOT be changed, as these are part of the public API contract.

## Verification Script

Create `verify_log_keys.py`:

```python
#!/usr/bin/env python3
"""Verify no magic string keys remain."""

import subprocess
import sys

PATTERNS = [
    ('"component":', 'K_COMPONENT'),
    ('"category":', 'K_CATEGORY'),
    ('"original_error":', 'K_ORIGINAL_ERROR'),
    ('"symbol":', 'K_SYMBOL'),
    ('"pair":', 'K_PAIR'),
    ('"strategy":', 'K_STRATEGY'),
]

PATHS = [
    "agents/core/execution_agent.py",
    "agents/core/market_scanner.py",
    "agents/core/signal_processor.py",
    "agents/core/autogen_wrappers.py",
    "agents/scalper/infra/logger.py",
]

failed = []

for pattern, constant in PATTERNS:
    for path in PATHS:
        result = subprocess.run(
            ["grep", "-n", pattern, path],
            capture_output=True,
            text=True
        )
        if result.stdout:
            failed.append(f"{path}: Found {pattern} (should use {constant})")
            print(f"FAIL: {path} still has {pattern}")
            print(result.stdout)

if failed:
    print(f"\nFailed: {len(failed)} patterns still use magic strings")
    sys.exit(1)
else:
    print("SUCCESS: All magic strings replaced with constants")
    sys.exit(0)
```

## Current Status

✅ **Completed**:
- Created `agents/core/log_keys.py` with 150+ constants
- Added `log_keys` to `agents/core/__all__` exports
- Verified module imports correctly
- Documented all patterns and locations

⏳ **Remaining Work**:
- Import constants in each file (5 files)
- Replace magic strings with constants (~100 replacements)
- Run verification script
- Test all affected modules

## Estimated Effort

- **Time**: 30-45 minutes for careful find-and-replace
- **Risk**: Low (constants evaluate to same strings)
- **Testing**: Run existing tests to verify no breakage

---

**Created**: 2025-10-11
**Status**: Module created, migration pending
**Files**: log_keys.py (431 lines), migration targets (5 files)
