# Core Agent Architecture with DI and Protocols

## Overview
This architecture establishes clear boundaries between modules using Protocol-based dependency injection. All modules can run with fake implementations for testing.

## Module Responsibilities

### 1. types.py ✅
- **Role**: Core data types and protocols
- **Exports**: Signal, Order, ExecutionResult, MarketData, Protocols
- **Dependencies**: None (foundational)
- **Status**: COMPLETE

### 2. signal_analyst.py ✅
- **Role**: Pure signal generation logic
- **Key Function**: `analyze(md: MarketData, context: AnalysisContext, config: AnalystConfig) -> list[Signal]`
- **I/O**: NONE - Pure functions only
- **Dependencies**: Only types.py
- **Testing**: Can test with fake MarketData
- **Status**: COMPLETE

### 3. signal_processor.py
- **Role**: Signal enrichment and routing
- **Key Functions**:
  - `enrich(signals: list[Signal]) -> list[Signal]` - Add metadata, quality scores
  - `route(signals: list[Signal]) -> dict[str, list[Signal]]` - Route by strategy
- **I/O**: None in core functions (pure)
- **Dependencies**: types.py, signal_analyst.py
- **Testing**: Can test with fake signals
- **Status**: NEEDS REFACTOR (current version has Redis embedded)

### 4. execution_agent.py
- **Role**: Order execution with dry-run support
- **Key Functions**:
  - `plan(intent: OrderIntent) -> Order` - Convert intent to order (no execution)
  - `execute(order: Order, gateway: ExchangeClientProtocol, dry_run: bool) -> ExecutionResult`
- **I/O**: Via injected ExchangeClientProtocol
- **Dependencies**: types.py
- **Testing**: Use FakeKrakenGateway
- **Status**: NEEDS REFACTOR (add plan/execute separation)

### 5. market_scanner.py
- **Role**: Schedule market data pulls
- **Key Functions**:
  - `scan(data_source: DataSourceProtocol) -> list[MarketData]`
- **I/O**: Via injected DataSourceProtocol
- **Dependencies**: types.py
- **Testing**: Use FakeDataSource
- **Status**: NEEDS REFACTOR (inject data source)

### 6. performance_monitor.py
- **Role**: Track P&L and metrics
- **Key Functions**:
  - `record(result: ExecutionResult) -> None`
  - `snapshot() -> PerformanceSnapshot` - DTO with win%, avg R, PnL
- **I/O**: None (in-memory accumulators)
- **Dependencies**: types.py
- **Testing**: Direct unit tests
- **Status**: NEEDS IMPLEMENTATION

### 7. autogen_wrappers.py
- **Role**: Minimal shim for autogen integration
- **Key Functions**: Adapter functions only, NO business logic
- **Dependencies**: All above modules
- **Status**: NEEDS CLEANUP

## Dependency Injection Pattern

```python
# Example: Execution with injected gateway
class ExecutionAgent:
    def __init__(self, gateway: ExchangeClientProtocol):
        self.gateway = gateway  # Injected, not hardcoded

    async def execute(self, order: Order, dry_run: bool) -> ExecutionResult:
        if dry_run:
            return ExecutionResult(success=True, ...)  # Simulate
        return await self.gateway.create_order(...)  # Real execution

# Testing with fake
fake_gateway = FakeKrakenGateway()
agent = ExecutionAgent(fake_gateway)
result = await agent.execute(order, dry_run=False)
```

## Testing Strategy

### Unit Tests (No Redis, No Network)
```python
# test_signal_analyst.py
def test_analyze_rsi_oversold():
    md = MarketData(symbol="BTC/USD", bid=Decimal("50000"), ...)
    ctx = AnalysisContext(rsi=25.0, ...)
    config = FakeConfig(rsi_oversold=30.0, ...)

    signals = analyze(md, ctx, config)

    assert len(signals) == 1
    assert signals[0].side == Side.BUY
```

### Integration Tests (Fake Redis + Fake Kraken)
```python
# test_integration.py
def test_end_to_end_with_fakes():
    redis = FakeRedisClient()
    kraken = FakeKrakenGateway()

    # Full pipeline with fakes
    scanner = MarketScanner(data_source=FakeDataSource())
    analyst = SignalAnalyst(...)
    processor = SignalProcessor(redis_client=redis)
    executor = ExecutionAgent(gateway=kraken)

    # Run pipeline
    market_data = scanner.scan()
    signals = analyst.analyze(market_data[0], ...)
    routed = processor.route(signals)
    result = await executor.execute(routed["scalp"][0], dry_run=False)

    assert result.success
    assert kraken.order_count == 1  # Verify fake was called
```

## Success Criteria

✅ Core logic runs with fake Kraken + fake Redis
✅ No module imports Redis directly (injected via Protocol)
✅ All functions are testable without network I/O
✅ Clear separation: analyze() → enrich() → route() → plan() → execute()

## Redis Cloud Connection (For Integration Only)

```bash
# Connection string (injected, not hardcoded)
redis-cli -u redis://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 --tls
```

## Conda Environment

```bash
conda activate crypto-bot
```
