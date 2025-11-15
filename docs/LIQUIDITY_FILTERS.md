# Liquidity & Timing Filters (24/7 Without Zombie Hours)

## Overview

Comprehensive microstructure filtering system for **24/7 trading without low-liquidity periods**. Implements intelligent entry gates while maintaining 24/7 position management:

- **Rolling 1m notional filter** - Require minimum USD volume (pair-specific)
- **Spread filter** - Skip entries if spread_bps > cap
- **Depth imbalance filter** - Avoid one-sided orderbooks
- **Time window filter** - Optional UTC hour restrictions (entries only, exits 24/7)
- **Pair-specific thresholds** - Configurable per symbol
- **CLI overrides** - Runtime configuration via `--trade_window`

## Problem Statement

24/7 crypto markets have "zombie hours" with:
- Thin liquidity (wide spreads, low volume)
- One-sided orderbooks (poor execution)
- High slippage and transaction costs
- Reduced edge from strategy signals

**Solution:** Gate new entries based on microstructure, not fixed hours. Always allow exits for risk management.

## Configuration

### YAML Drop-In (`config/settings.yaml`)

```yaml
microstructure:
  # Default liquidity thresholds (applied if pair not specified)
  default_min_notional_1m_usd: 50000.0  # Minimum 1-minute rolling volume
  default_max_spread_bps: 10.0          # Maximum spread in basis points
  default_max_depth_imbalance: 0.7      # Maximum imbalance (0.7 = 70/30 split)
  notional_window_seconds: 60           # Rolling window size

  # Pair-specific overrides
  pair_configs:
    BTC/USD:
      min_notional_1m_usd: 100000.0
      max_spread_bps: 5.0
      max_depth_imbalance: 0.65
    ETH/USD:
      min_notional_1m_usd: 75000.0
      max_spread_bps: 8.0
      max_depth_imbalance: 0.7
    BTC/USDT:
      min_notional_1m_usd: 100000.0
      max_spread_bps: 5.0
      max_depth_imbalance: 0.65

  # Time window filtering (optional - restrict entries, exits always allowed)
  time_window:
    enabled: false                      # Enable time window filtering
    start_utc_hour: 12                  # 12:00 UTC
    end_utc_hour: 22                    # 22:00 UTC
    restrict_symbols: ["*USD", "*USDT"] # Patterns: *USD, BTC*, or exact match
```

### Loading Configuration

```python
from config.microstructure_config import load_microstructure_gate_config
from strategies.microstructure import MicrostructureGate

# Load from YAML
config = load_microstructure_gate_config("config/settings.yaml")

# Create gate
gate = MicrostructureGate(config)
```

### CLI Override (--trade_window)

```bash
# Enable time window via CLI (12:00-22:00 UTC)
python scripts/start_trading_system.py --mode paper --trade_window 12-22

# Different window (14:00-20:00 UTC)
python scripts/start_trading_system.py --mode paper --trade_window 14-20

# Disable time window (use YAML default)
python scripts/start_trading_system.py --mode paper
```

**CLI Override Code:**
```python
from config.microstructure_config import (
    load_microstructure_gate_config,
    override_time_window,
    parse_trade_window_arg,
)

# Load base config
config = load_microstructure_gate_config("config/settings.yaml")

# Parse CLI argument
if args.trade_window:
    start_hour, end_hour = parse_trade_window_arg(args.trade_window)
    config = override_time_window(
        config, enabled=True, start_hour=start_hour, end_hour=end_hour
    )

# Create gate with overridden config
gate = MicrostructureGate(config)
```

## Filter Components

### 1. Rolling Notional Filter

Tracks 1-minute rolling USD volume per symbol.

**Purpose:** Prevent trading in thin markets where slippage kills edge.

**Logic:**
```python
# Add trades to rolling window
gate.add_trade("BTC/USD", notional_usd=25000.0, timestamp=now)

# Check if volume meets threshold
rolling_notional = gate.notional_filter.get_rolling_notional("BTC/USD", now)
# rolling_notional = sum of notional USD in last 60 seconds

passed, reason = gate.notional_filter.check_min_notional(
    "BTC/USD", min_notional_usd=100000.0, current_time=now
)
# passed = True if rolling_notional >= 100000.0
```

**Example:**
```python
# BTC/USD threshold: $100k/minute
# Recent trades:
#   T-50s: $15k
#   T-30s: $35k
#   T-10s: $30k
# Total: $80k < $100k -> REJECT entry
```

**Per-Pair Thresholds:**
- `BTC/USD`: $100k/min (major pair, tight liquidity required)
- `ETH/USD`: $75k/min (liquid but less than BTC)
- `SOL/USD`: $50k/min (default, more lenient)

### 2. Spread Filter

Checks bid-ask spread in basis points.

**Purpose:** Avoid wide spreads that reduce realized edge.

**Calculation:**
```python
mid = (bid + ask) / 2
spread = ask - bid
spread_bps = (spread / mid) * 10000

# Example: BTC/USD bid=50000, ask=50010
# mid = 50005, spread = 10, spread_bps = 2.0
```

**Logic:**
```python
if spread_bps > max_spread_bps:
    # REJECT: spread too wide
    return False, f"spread {spread_bps:.1f}bps > max {max_spread_bps:.1f}bps"
else:
    # ALLOW: spread acceptable
    return True, f"spread {spread_bps:.1f}bps OK"
```

**Per-Pair Limits:**
- `BTC/USD`: 5 bps (very tight, major pair)
- `ETH/USD`: 8 bps (slightly wider)
- Default: 10 bps (lenient for less liquid pairs)

### 3. Depth Imbalance Filter

Measures orderbook bid/ask balance.

**Purpose:** Avoid one-sided books with poor execution quality.

**Calculation:**
```python
imbalance = bid_volume / (bid_volume + ask_volume)

# Examples:
# bid=100, ask=100 -> imbalance = 0.50 (balanced)
# bid=70, ask=30 -> imbalance = 0.70 (bid-heavy)
# bid=20, ask=80 -> imbalance = 0.20 (ask-heavy)
```

**Logic:**
```python
max_imbalance = 0.7  # Allow up to 70/30 split

if imbalance > max_imbalance or imbalance < (1 - max_imbalance):
    # REJECT: too imbalanced (>70% bids or >70% asks)
    return False, f"imbalance {imbalance:.2f} exceeds [{1-max_imbalance:.2f}, {max_imbalance:.2f}]"
else:
    # ALLOW: reasonably balanced
    return True, f"imbalance {imbalance:.2f} OK"
```

**Thresholds:**
- `BTC/USD`: 0.65 (allow up to 65/35 split)
- `ETH/USD`: 0.70 (allow up to 70/30 split)
- Default: 0.70

### 4. Time Window Filter

Restricts entries to specific UTC hours (optional).

**Purpose:** Optionally avoid known low-liquidity periods (e.g., Asian hours for USD pairs).

**Key Behavior:**
- **Entries:** Restricted to window (e.g., 12:00-22:00 UTC)
- **Exits:** Always allowed 24/7 (risk management never blocked)

**Logic:**
```python
# Always allow exits
if not is_entry:
    return True, "exit_allowed_24_7"

# Check if enabled
if not time_window.enabled:
    return True, "time_window_disabled"

# Check if symbol restricted
if symbol not in restrict_symbols:
    return True, "symbol_not_restricted"

# Check current UTC hour
current_hour = datetime.now(timezone.utc).hour

if start_hour <= current_hour < end_hour:
    return True, f"in_time_window ({current_hour:02d}:xx UTC)"
else:
    return False, f"outside_time_window ({start_hour:02d}:00-{end_hour:02d}:00 UTC)"
```

**Pattern Matching:**
- `*USD` - Matches `BTC/USD`, `ETH/USD`, etc. (suffix match)
- `BTC*` - Matches `BTC/USD`, `BTC/EUR`, etc. (prefix match)
- `BTC/USD` - Exact match only
- Empty list - Restricts all symbols

**Example:**
```yaml
time_window:
  enabled: true
  start_utc_hour: 12
  end_utc_hour: 22
  restrict_symbols: ["*USD", "*USDT"]  # Only USD pairs restricted
```

Result:
- `BTC/USD` entries: 12:00-22:00 UTC only
- `BTC/EUR` entries: Allowed 24/7 (not in restrict_symbols)
- Any symbol exits: Allowed 24/7

## Integrated Gate

`MicrostructureGate` combines all filters:

```python
from strategies.microstructure import MicrostructureGate

gate = MicrostructureGate(config)

# Update with trade data
gate.add_trade("BTC/USD", notional_usd=25000.0, timestamp=now)

# Check if entry allowed
allowed, reasons = gate.check_can_enter(
    symbol="BTC/USD",
    bid=50000.0,
    ask=50010.0,
    bid_volume=1000.0,
    ask_volume=1000.0,
    current_time=now,
    is_entry=True,  # Set False for exits
)

if not allowed:
    logger.warning(f"Entry rejected for BTC/USD: {reasons}")
    return  # Skip signal generation

# OK to generate signal
generate_signal(...)
```

**Reasons Output:**
```python
# All checks pass
allowed = True
reasons = [
    "notional: rolling_notional=125000 OK",
    "spread: 2.0bps OK",
    "imbalance: depth_imbalance=0.50 OK",
    "time: in_time_window (15:xx UTC)"
]

# Spread check fails
allowed = False
reasons = [
    "notional: rolling_notional=125000 OK",
    "spread: 20.0bps > max=5.0bps FAIL",
    "imbalance: depth_imbalance=0.50 OK",
    "time: in_time_window (15:xx UTC)"
]
```

## Application Integration

### Initialization

```python
from config.microstructure_config import load_microstructure_gate_config
from strategies.microstructure import MicrostructureGate

# Load config (with optional CLI override)
config = load_microstructure_gate_config("config/settings.yaml")

if trade_window_arg:
    from config.microstructure_config import override_time_window, parse_trade_window_arg
    start, end = parse_trade_window_arg(trade_window_arg)
    config = override_time_window(config, enabled=True, start_hour=start, end_hour=end)

# Create gate
gate = MicrostructureGate(config)
```

### On Trade Execution

```python
# After each trade executes, update rolling notional
gate.add_trade(
    symbol=trade.symbol,
    notional_usd=abs(trade.size) * trade.price,
    timestamp=trade.timestamp
)
```

### Before Generating Signal

```python
# Get current orderbook
orderbook = await exchange.get_orderbook(symbol)

bid = orderbook.bids[0][0]
ask = orderbook.asks[0][0]
bid_volume = sum(b[1] for b in orderbook.bids[:10])  # Top 10 levels
ask_volume = sum(a[1] for a in orderbook.asks[:10])

# Check gate
allowed, reasons = gate.check_can_enter(
    symbol=symbol,
    bid=bid,
    ask=ask,
    bid_volume=bid_volume,
    ask_volume=ask_volume,
    current_time=time.time(),
    is_entry=True,
)

if not allowed:
    logger.warning(f"Microstructure gate rejected entry for {symbol}: {reasons}")
    return  # Skip signal generation

# Generate signal
signal = strategy.generate_signal(...)
```

### Before Closing Position (Exit)

```python
# Always check with is_entry=False to ensure exits allowed
allowed, reasons = gate.check_can_enter(
    symbol=symbol,
    bid=bid,
    ask=ask,
    bid_volume=bid_volume,
    ask_volume=ask_volume,
    current_time=time.time(),
    is_entry=False,  # EXIT check
)

# Should always return True (exits 24/7)
assert allowed, "Exits should never be blocked"

# Close position
await position_manager.close_position(...)
```

## Testing

Comprehensive demo script: `scripts/test_microstructure_demo.py`

```bash
python scripts/test_microstructure_demo.py
```

**Test Scenarios:**
1. Load configuration from YAML
2. Rolling notional filter (1m window)
3. Good market conditions (all checks pass)
4. Wide spread rejection
5. Depth imbalance rejection
6. Low rolling notional rejection
7. Exits always allowed (24/7)
8. Time window filtering (different UTC hours)
9. Pair-specific vs default thresholds
10. CLI argument parsing

**Expected Output:**
```
[ALLOW] BTC/USD - tight spread, balanced book, good volume
  - notional: rolling_notional=125000 OK
  - spread: 2.0bps OK
  - imbalance: depth_imbalance=0.50 OK
  - time: time_window_disabled

[REJECT] BTC/USD - wide spread (20bps > 5bps max)
  - notional: rolling_notional=125000 OK
  - spread: 20.0bps > max=5.0bps FAIL
  - imbalance: depth_imbalance=0.50 OK
  - time: time_window_disabled
```

## Benefits

### 1. Avoid Zombie Hours Without Fixed Schedules

**Traditional Approach:**
```python
# Fixed time-based filtering (brittle)
if 2 <= current_hour < 10:
    return  # Skip Asian hours for USD pairs
```

**Microstructure Approach:**
```python
# Adaptive filtering based on actual market conditions
allowed, reasons = gate.check_can_enter(...)
if not allowed:
    return  # Skip if liquidity poor, regardless of time
```

**Advantage:** Markets can be liquid at "off hours" (e.g., during major news). Microstructure captures this dynamically.

### 2. Pair-Specific Liquidity Requirements

**BTC/USD:**
- $100k/min volume, 5bps max spread, 65/35 max imbalance
- Strict thresholds (major pair, deep liquidity expected)

**SOL/USD:**
- $50k/min volume, 10bps max spread, 70/30 max imbalance
- Lenient thresholds (less liquid, more tolerant)

**Result:** Each pair has appropriate gates for its liquidity profile.

### 3. Always Allow Exits (24/7 Risk Management)

**Critical:** Risk management (stop losses, take profits) operates 24/7.

```python
# Even with terrible conditions
allowed, reasons = gate.check_can_enter(
    symbol="BTC/USD",
    bid=50000.0,
    ask=51000.0,  # 200 bps spread (terrible!)
    bid_volume=10.0,
    ask_volume=990.0,  # 99% ask-heavy (terrible!)
    is_entry=False,  # EXIT
)

# Still returns: allowed=True, reasons=["exit_allowed_24_7"]
```

**Reason:** Cannot sacrifice risk management for liquidity gates. Exits must always execute.

### 4. Reduce Slippage and Transaction Costs

**Without Filters:**
```
Signal: BUY BTC/USD
Spread: 20 bps (wide)
Notional: $30k/min (thin)
Result: -10 bps slippage, -20 bps spread -> -30 bps cost before edge
```

**With Filters:**
```
Signal: BUY BTC/USD
Check: spread=20bps > 5bps max -> REJECT
Result: Signal skipped, wait for better conditions
```

**Benefit:** Only trade when execution quality preserves edge.

### 5. CLI Flexibility

**Scenario:** Want to test different time windows without editing YAML.

```bash
# Test 14:00-20:00 UTC window
python scripts/start_trading_system.py --mode paper --trade_window 14-20

# Test 24/7 (no window)
python scripts/start_trading_system.py --mode paper
```

**Benefit:** Quick iteration for backtesting and optimization.

## Files

- **Core Module**: `strategies/microstructure.py` - Filter logic (pure, no I/O)
- **Config Loader**: `config/microstructure_config.py` - YAML → MicrostructureConfig
- **YAML Config**: `config/settings.yaml` - Configuration drop-in
- **CLI Integration**: `scripts/start_trading_system.py` - `--trade_window` flag
- **Demo Script**: `scripts/test_microstructure_demo.py` - Comprehensive tests
- **Docs**: `docs/LIQUIDITY_FILTERS.md` - This file

## Usage Examples

### Example 1: Load and Check Entry

```python
from config.microstructure_config import load_microstructure_gate_config
from strategies.microstructure import MicrostructureGate
import time

# Load config
config = load_microstructure_gate_config("config/settings.yaml")
gate = MicrostructureGate(config)

# Simulate recent trades
now = time.time()
gate.add_trade("BTC/USD", 25000.0, now - 50)
gate.add_trade("BTC/USD", 35000.0, now - 30)
gate.add_trade("BTC/USD", 50000.0, now - 10)

# Check entry
allowed, reasons = gate.check_can_enter(
    symbol="BTC/USD",
    bid=50000.0,
    ask=50010.0,
    bid_volume=1000.0,
    ask_volume=1000.0,
    current_time=now,
    is_entry=True,
)

if allowed:
    print("Entry allowed!")
else:
    print(f"Entry rejected: {reasons}")
```

### Example 2: CLI Override

```bash
# Production: No time window (24/7 with microstructure gates only)
python scripts/start_trading_system.py --mode paper

# Testing: Restrict to 12:00-22:00 UTC
python scripts/start_trading_system.py --mode paper --trade_window 12-22
```

### Example 3: Custom Pair Configuration

```yaml
# config/settings.yaml
microstructure:
  pair_configs:
    DOGE/USD:  # Meme coin, very lenient
      min_notional_1m_usd: 30000.0
      max_spread_bps: 20.0
      max_depth_imbalance: 0.8
    BTC/USD:  # Major pair, very strict
      min_notional_1m_usd: 150000.0
      max_spread_bps: 3.0
      max_depth_imbalance: 0.6
```

## References

- **PRD**: `PRD_AGENTIC.md` - System architecture
- **Existing Filters**: `strategies/filters.py` - Base filter functions
- **Risk Gates**: `docs/RISK_GATES.md` - Complementary risk protection
- **Config Schema**: `config/streams_schema.py` - Configuration validation

---

**Status**: Implemented and tested (10 test scenarios passing)

**Last Updated**: 2025-10-17

**Next Steps**: Integrate with signal generation and position management
