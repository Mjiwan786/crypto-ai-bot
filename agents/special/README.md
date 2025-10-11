# Special Agents - Experimental & Optional

⚠️ **ALL AGENTS IN THIS MODULE ARE EXPERIMENTAL** ⚠️

This directory contains **optional, experimental agents** for advanced trading strategies. These agents are clearly marked as experimental and operate with strict safety constraints.

## Safety Principles

All special agents follow these principles:

1. **✅ Safe to import** - No side effects on module import
2. **✅ Detection only (default)** - No auto-execution without explicit approval
3. **✅ Interface stubs** - Real execution raises `NotImplementedError`
4. **✅ Rate-limited** - Built-in API rate limiting and backoff
5. **✅ No hardcoded secrets** - Accept generic interfaces, no hardcoded API keys
6. **✅ Testable** - All agents can be tested with fakes/mocks

## Agent Overview

### 1. `flashloan_executor.py`
**Status:** ⚠️ SIMULATION ONLY

**What it does:**
- Flash loan planning and validation
- Gas cost estimation
- ROI calculation with fees and MEV risk
- Pre-execution simulation

**What it does NOT do:**
- Real on-chain execution (raises `NotImplementedError`)
- Smart contract interactions
- Token swaps
- Flash loan borrowing

**Safety:**
- All methods raise `NotImplementedError` for real execution
- Only supports `dry_run=True` mode
- Comprehensive warnings in docstrings
- No wallet/key access

**Usage:**
```python
from agents.special.flashloan_executor import FlashloanExecutor

# Safe to instantiate - no side effects
executor = FlashloanExecutor()

# Simulation only - does not execute
result = await executor.simulate_once(plan)

# Real execution raises NotImplementedError
try:
    await executor.execute(plan)  # plan.dry_run must be True
except NotImplementedError:
    print("Real execution not implemented for safety")
```

---

### 2. `arbitrage_hunter.py`
**Status:** ✅ DETECTION ONLY

**What it does:**
- Multi-exchange price monitoring (read-only)
- Arbitrage opportunity detection
- Fee and slippage calculation
- Emits standardized `Opportunity` DTOs

**What it does NOT do:**
- Execute trades automatically
- Access wallets or private keys
- Submit orders to exchanges

**Safety:**
- Read-only API calls with rate limiting
- No execution capability (by design)
- Opportunities expire after 30 seconds
- No credentials required (public endpoints only)

**Usage:**
```python
from agents.special.arbitrage_hunter import ArbitrageHunter, Opportunity

# Safe to instantiate - read-only mode
hunter = ArbitrageHunter()

# Detection only - returns Opportunity DTOs
opportunities: List[Opportunity] = await hunter.scan_once(publish=False)

# Review opportunities manually
for opp in opportunities:
    print(f"Detected: {opp.symbol} spread={opp.net_spread:.2%}")
    # Manual review required before any execution
```

---

### 3. `liquidity_provider.py`
**Status:** ⚠️ DETECTION ONLY (recommended updates pending)

**Current state:**
- May have auto-execution logic (UNSAFE)

**Recommended updates:**
1. Pure detection logic only
2. Emit `Opportunity` DTOs
3. No auto-execution by default
4. Add experimental warnings

**Target usage:**
```python
from agents.special.liquidity_provider import LiquidityProvider, Opportunity

provider = LiquidityProvider()
opportunities = await provider.scan_pools()  # Detection only
# Manual approval required for execution
```

---

### 4. `news_reactor.py`
**Status:** ⚠️ DETECTION ONLY (recommended updates pending)

**Current state:**
- May have auto-reaction logic (UNSAFE)
- May have hardcoded API keys (UNSAFE)

**Recommended updates:**
1. Accept generic feed interface (no hardcoded APIs)
2. Rate limits and exponential backoff
3. No auto-execution - emit signals only
4. No hardcoded API keys

**Target usage:**
```python
from agents.special.news_reactor import NewsReactor

# Accept generic feed interface
feed = YourNewsFeedImplementation()  # User provides
reactor = NewsReactor(feed=feed)

# Detection only - emits signals
signals = await reactor.analyze_news()  # No auto-trading
```

---

### 5. `whale_watcher.py`
**Status:** ⚠️ DETECTION ONLY (recommended updates pending)

**Current state:**
- May have auto-reaction logic (UNSAFE)
- May have hardcoded API keys (UNSAFE)

**Recommended updates:**
1. Accept generic blockchain scanner interface
2. Rate limits and exponential backoff
3. No auto-execution - emit alerts only
4. No hardcoded API keys

**Target usage:**
```python
from agents.special.whale_watcher import WhaleWatcher

# Accept generic scanner interface
scanner = YourBlockchainScannerImplementation()  # User provides
watcher = WhaleWatcher(scanner=scanner)

# Detection only - emits alerts
alerts = await watcher.scan_transactions()  # No auto-trading
```

---

## Standardized Opportunity DTO

All detection agents should emit a standardized `Opportunity` DTO:

```python
from pydantic import BaseModel, Field

class Opportunity(BaseModel):
    """Standardized opportunity DTO - detection only, no execution."""

    opportunity_type: str  # e.g., "arbitrage", "liquidity", "news", "whale"
    symbol: str
    action: str  # e.g., "buy", "sell", "provide_liquidity"
    estimated_profit: float
    confidence: float  # 0-1
    expiry: float  # Unix timestamp

    # Type-specific fields as needed
    metadata: dict = {}
```

**Key properties:**
- DTOs are **informational only**
- Do NOT trigger execution
- Expire after short time (30-60s)
- Require manual validation before action

---

## Testing Guidelines

All special agents must be testable with fakes:

```python
# Example test structure
import pytest
from agents.special.arbitrage_hunter import ArbitrageHunter

class FakeExchange:
    """Fake exchange for testing - no network calls."""
    async def fetch_ticker(self, symbol):
        return {"bid": 50000, "ask": 50010, "volume": 1000000}

@pytest.mark.asyncio
async def test_arbitrage_detection_with_fakes():
    """Test arbitrage detection with fake data - no side effects."""
    hunter = ArbitrageHunter()
    hunter.exchanges = {"fake": FakeExchange()}

    # Detection only - no execution
    opportunities = await hunter.scan_once(publish=False)

    # Assertions on detection logic only
    assert len(opportunities) >= 0
    for opp in opportunities:
        assert opp.confidence >= 0
        assert opp.expiry > time.time()
```

---

## Import Safety

All agents are safe to import - no side effects:

```python
# Safe - no side effects on import
from agents.special.flashloan_executor import FlashloanExecutor
from agents.special.arbitrage_hunter import ArbitrageHunter
from agents.special.liquidity_provider import LiquidityProvider
from agents.special.news_reactor import NewsReactor
from agents.special.whale_watcher import WhaleWatcher

# Safe - instantiation does not execute anything
agent = FlashloanExecutor()  # No network calls, no wallet access
```

**No side effects means:**
- No network calls on import
- No wallet/key access on import
- No database connections on import
- No auto-execution on import
- Only logging configuration

---

## Unit Test Requirements

Each agent must have unit tests that:

1. **✅ Use fakes only** - No live connections
2. **✅ Test detection logic** - Verify opportunity identification
3. **✅ Test error handling** - Verify graceful failures
4. **✅ Test rate limiting** - Verify backoff behavior
5. **✅ Verify no execution** - Ensure no auto-trading
6. **✅ Fast execution** - Tests complete in <5s each

Example test file structure:
```
agents/special/tests/
├── __init__.py
├── conftest.py              # Shared fixtures and fakes
├── test_flashloan.py        # Flashloan executor tests
├── test_arbitrage.py        # Arbitrage hunter tests
├── test_liquidity.py        # Liquidity provider tests
├── test_news_reactor.py     # News reactor tests
└── test_whale_watcher.py    # Whale watcher tests
```

---

## Rate Limiting & Backoff

All agents that make external API calls must implement:

1. **Rate limiting:**
```python
import ccxt

exchange = ccxt.binance({
    'enableRateLimit': True,  # Required
    'rateLimit': 1200,        # ms between requests
})
```

2. **Exponential backoff:**
```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10)
)
async def fetch_with_retry(self):
    # API call with automatic retry
    pass
```

3. **Circuit breakers:**
```python
if self.consecutive_errors >= 5:
    self.circuit_breaker_active = True
    # Stop making requests until cooldown
```

---

## Forbidden Patterns

❌ **DO NOT:**
- Hardcode API keys in source code
- Auto-execute trades without approval
- Make network calls on import
- Access wallets/keys without explicit permission
- Store credentials in code
- Skip rate limiting
- Ignore exponential backoff

✅ **DO:**
- Accept generic interfaces
- Emit Opportunity DTOs only
- Require manual approval for execution
- Implement rate limiting
- Use exponential backoff
- Log all operations
- Raise NotImplementedError for unsafe operations

---

## Production Checklist

Before using any special agent in production:

- [ ] Review all experimental warnings
- [ ] Understand risks (financial loss, MEV, slippage)
- [ ] Test extensively on testnets
- [ ] Implement proper key management
- [ ] Set up monitoring and alerts
- [ ] Implement emergency stop mechanisms
- [ ] Complete security audit (for on-chain agents)
- [ ] Verify no hardcoded secrets
- [ ] Test with fake data first
- [ ] Implement proper approval workflows
- [ ] Document all assumptions and limitations

---

## Support & Warnings

⚠️ **No warranties or guarantees** - Use at your own risk

All special agents are provided as reference implementations. Users assume complete responsibility for:
- Financial losses
- Security vulnerabilities
- Smart contract risks
- API failures
- MEV attacks
- Liquidations
- Slippage costs

For production use:
1. Complete professional audit
2. Extensive testnet validation
3. Proper risk management
4. Real-time monitoring
5. Emergency procedures

---

## Future Improvements

Recommended updates for remaining agents:

### `liquidity_provider.py`
- [ ] Add experimental warnings
- [ ] Convert to detection-only mode
- [ ] Emit standardized Opportunity DTOs
- [ ] Remove auto-execution logic
- [ ] Add interface stubs

### `news_reactor.py`
- [ ] Add experimental warnings
- [ ] Accept generic feed interface
- [ ] Add rate limiting and backoff
- [ ] Remove hardcoded API keys
- [ ] Convert to signal-only mode

### `whale_watcher.py`
- [ ] Add experimental warnings
- [ ] Accept generic scanner interface
- [ ] Add rate limiting and backoff
- [ ] Remove hardcoded API keys
- [ ] Convert to alert-only mode

---

## Contact & Contributions

For questions or contributions:
1. Review existing code and warnings
2. Test with fakes first
3. Follow safety principles
4. Document all assumptions
5. Submit PR with tests

**Remember:** All special agents are experimental. Always prioritize safety over functionality.
