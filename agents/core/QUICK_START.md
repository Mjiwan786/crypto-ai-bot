# Quick Start: Clean DI Architecture

## 🎯 What Was Built

A clean, testable architecture with:
- ✅ Pure signal logic (no I/O)
- ✅ Protocol-based dependency injection
- ✅ Fake implementations for testing
- ✅ No direct Redis/Kraken imports in core logic

## 📁 File Structure

```
agents/core/
├── types.py                      # Protocols & types (EXISTING ✅)
├── signal_analyst.py             # Pure analyze() (REFACTORED ✅)
├── signal_processor_v2.py        # Pure enrich() + route() (NEW ✅)
├── execution_agent_v2.py         # plan() + execute() with DI (NEW ✅)
├── market_scanner_v2.py          # Scanner with DI (NEW ✅)
├── performance_monitor_v2.py     # In-memory metrics (NEW ✅)
├── test_fakes.py                 # Fake Kraken + Redis (NEW ✅)
├── ARCHITECTURE.md               # Full architecture doc
├── DI_IMPLEMENTATION_SUMMARY.md  # Complete summary
└── QUICK_START.md                # This file

tests/
└── test_core_di_integration.py   # Integration test (NEW ✅)
```

## 🚀 Run Tests Immediately

```bash
# Activate environment
conda activate crypto-bot

# Run integration test
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot
python tests/test_core_di_integration.py
```

## 📝 Quick Examples

### 1. Analyze Market Data (Pure Function)

```python
from agents.core.signal_analyst import analyze, AnalysisContext
from agents.core.types import MarketData
from decimal import Decimal

md = MarketData(
    symbol="BTC/USD",
    timestamp=time.time(),
    bid=Decimal("50000"),
    ask=Decimal("50020"),
    last_price=Decimal("50010"),
    volume=Decimal("1000"),
)

context = AnalysisContext(rsi=28.0, regime="uptrend")
signals = analyze(md, context, config)  # Pure function - no I/O!
```

### 2. Execute Order (With DI)

```python
from agents.core.execution_agent_v2 import ExecutionAgent
from agents.core.test_fakes import FakeKrakenGateway

# For testing: inject fake
fake_gateway = FakeKrakenGateway()
agent = ExecutionAgent(gateway=fake_gateway, default_dry_run=False)

# For production: inject real
# real_gateway = KrakenGateway(api_key=..., api_secret=...)
# agent = ExecutionAgent(gateway=real_gateway)

order = agent.plan(intent)
result = await agent.execute(order, dry_run=False)
```

### 3. Process Signals (Pure Function)

```python
from agents.core.signal_processor_v2 import process, SimpleConfig

config = SimpleConfig(min_confidence=0.6)
routed = process(signals, config)  # Pure function - no I/O!

# routed = {"scalp": [sig1], "trend_following": [sig2]}
```

## 🧪 Testing Philosophy

**Unit Tests (No I/O)**
```python
# Test pure logic with fake data
def test_analyze():
    md = MarketData(...)
    ctx = AnalysisContext(rsi=25.0)
    signals = analyze(md, ctx, config)
    assert len(signals) > 0  # Fast, deterministic
```

**Integration Tests (With Fakes)**
```python
# Test full pipeline with fakes
async def test_pipeline():
    fake_kraken = FakeKrakenGateway()
    fake_redis = FakeRedisClient()

    # Run full pipeline
    result = await execute_pipeline(fake_kraken, fake_redis)

    assert result.success
    assert fake_kraken.order_count == 1  # Verify fake was used
```

## 🔌 Dependency Injection Pattern

**Instead of this (bad):**
```python
class ExecutionAgent:
    def __init__(self):
        self.gateway = KrakenGateway()  # ❌ Hardcoded!
```

**Do this (good):**
```python
class ExecutionAgent:
    def __init__(self, gateway: ExchangeClientProtocol):
        self.gateway = gateway  # ✅ Injected!
```

Now you can inject either:
- `FakeKrakenGateway()` for testing
- `RealKrakenGateway()` for production

## ✅ Success Criteria

Run the test to verify:
```bash
python tests/test_core_di_integration.py
```

Expected output:
```
Running Core DI Integration Tests...
1. Testing pure signal analyst... PASSED
2. Testing pure signal processor... PASSED
3. Testing pure execution planning... PASSED
4. Testing performance monitor... PASSED
5. Testing market scanner with fake source... PASSED
6. Testing execution with fake gateway... PASSED
7. Testing dry-run mode... PASSED
8. Running end-to-end pipeline... PASSED

ALL TESTS PASSED!

Architecture Validation:
✅ Pure functions tested without I/O
✅ All dependencies injected via Protocols
✅ No direct Redis imports in core modules
✅ Fake implementations enable fast testing
✅ Ready for production with real Kraken/Redis
```

## 📚 Learn More

- **Full architecture**: See `ARCHITECTURE.md`
- **Complete summary**: See `DI_IMPLEMENTATION_SUMMARY.md`
- **Integration test**: See `tests/test_core_di_integration.py`

## 🎉 Next Steps

1. ✅ Run tests to verify everything works
2. Create real implementations:
   - `RealKrakenGateway` (implementing `ExchangeClientProtocol`)
   - `RealRedisClient` (implementing `RedisClientProtocol`)
3. Update production code to use DI pattern
4. Gradually migrate from old modules to new v2 modules

## 💡 Key Takeaway

The entire pipeline now works with **fake Kraken + fake Redis**:
- No network calls
- Fast tests
- Deterministic results
- Easy debugging

Simply swap in real implementations for production! 🚀
