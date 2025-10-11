# Scalper Agent Test Suite

Hermetic test suite for the scalper trading agent with **no live network calls, no Redis, no file I/O**.

## Quick Start

```bash
# Activate conda environment
conda activate crypto-bot

# Run all tests (should complete in <60s)
pytest agents/scalper/tests -q

# Run with verbose output
pytest agents/scalper/tests -v

# Run specific test file
pytest agents/scalper/tests/test_backtest_smoke.py -v

# Run tests by marker
pytest agents/scalper/tests -m "smoke" -v
pytest agents/scalper/tests -m "not slow" -v
```

## Test Files

### `conftest.py` (437 lines)
Pytest fixtures for hermetic testing. All fixtures are **self-contained** with no external dependencies.

**Fixtures provided:**
- `sample_config_dict()`: Scalper configuration dictionary
- `sample_btcusdt_1m()`: 100 bars of BTC/USD 1-minute OHLCV data (deterministic seed=42)
- `sample_ethusdt_1m()`: 100 bars of ETH/USD 1-minute OHLCV data (deterministic seed=43)
- `kraken_ws_ticker_message()`: Sample Kraken WebSocket ticker message
- `kraken_ws_trade_message()`: Sample Kraken WebSocket trade message (2 trades)
- `kraken_ws_orderbook_message()`: Sample Kraken orderbook snapshot (5 levels)
- `kraken_ws_orderbook_update()`: Sample Kraken orderbook update message
- `kraken_ws_error_message()`: Sample Kraken error message
- `sample_trades()`: List of 4 sample trades for analysis
- `mock_order_response()`: Sample order response from exchange
- `mock_fill_response()`: Sample fill response from exchange
- `mock_balance_response()`: Sample balance response from exchange

**Helper functions:**
- `generate_price_series()`: Generate realistic price series with trend and volatility
- `generate_ohlcv_from_prices()`: Generate OHLCV DataFrame from price array

### `test_backtest_smoke.py` (359 lines)
Smoke tests for backtest engine with realistic trade generation.

**Key tests:**
- `test_backtest_smoke_btcusdt_1m_produces_trades()`: Main smoke test
  - Uses 100 bars of BTCUSDT data
  - Generates realistic scalping trades
  - Analyzes with BacktestAnalyzer
  - Verifies: trades produced, valid metrics, completes in <10s
- `test_backtest_analyzer_handles_empty_trades()`: Edge case testing
- `test_backtest_analyzer_handles_single_trade()`: Single trade analysis
- `test_backtest_with_multiple_symbols()`: Multi-symbol trading
- `test_backtest_metrics_consistency()`: Verify metrics are self-consistent
- `test_replay_feeder_synchronous_mode()`: Replay engine synchronous mode
- `test_replay_feeder_fast_mode_skips_bars()`: Fast replay mode (skips 80% bars)
- `test_replay_feeder_multi_symbol()`: Multi-symbol replay with chronological ordering
- `test_backtest_performance_scaling()`: Performance tests (100/500/1000 bars)

**Mock trade generator:**
- `_generate_mock_scalp_trades()`: Generates realistic scalping trades
  - Simulates mean-reversion strategy
  - 10 bps profit target, 5 bps stop loss
  - Configurable win rate (default 60%)
  - Deterministic (seed=42)

### `test_ws_parse.py` (403 lines)
WebSocket message parsing tests with Kraken fixtures.

**Mock parsers provided:**
- `parse_kraken_ticker()`: Parse ticker messages, calculate spread
- `parse_kraken_trades()`: Parse trade messages
- `parse_kraken_orderbook()`: Parse orderbook snapshots/updates

**Test coverage:**
- **Ticker**: Parsing, missing fields, empty messages, spread calculation
- **Trades**: Parsing, filtering by side, empty data handling
- **Orderbook**: Snapshot parsing, update parsing, spread calculation, empty sides
- **Error handling**: Malformed JSON, error messages
- **Integration**: Parametrized tests for all message types, orderbook merging
- **Performance**: Large orderbook (100 levels), trade batches (100 trades)

### `test_execution_mock.py` (442 lines)
Execution tests with mock gateway roundtrip.

**Mock implementations:**
- `MockGateway`: Mock exchange gateway
  - `place_order()`: Place order with configurable slippage
  - `fill_order()`: Simulate instant fill
  - `cancel_order()`: Cancel order
  - `get_order_status()`: Query order status
  - `get_balance()`: Get mock balance
- `MockPositionManager`: Track positions and P&L
  - `update_position()`: Update position from fill, calculate realized P&L
  - `get_position()`: Get current position size
  - Supports long/short, partial closes, multiple symbols

**Test scenarios:**
- `test_mock_gateway_place_order()`: Basic order placement
- `test_mock_gateway_fill_order()`: Order fill simulation
- `test_optimizer_gateway_roundtrip()`: Full flow (optimizer → gateway → position manager)
- `test_full_trade_cycle()`: Open → close with P&L verification
- `test_partial_position_close()`: Partial position closure
- `test_market_order_with_slippage()`: Market order slippage application
- `test_multiple_symbols()`: Multi-symbol trading
- `test_order_cancel()`: Order cancellation
- `test_high_frequency_orders()`: Performance test (100 orders)
- `test_concurrent_position_updates()`: Rapid position updates (50 updates)
- `test_complete_scalping_scenario()`: Integration test with multiple round-trip trades

## Test Principles

### 1. Hermetic Testing
**No external dependencies:**
- ❌ No live network calls to Kraken or other exchanges
- ❌ No Redis connections
- ❌ No file I/O (except reading source code)
- ✅ All data from fixtures and mocks
- ✅ Deterministic random seeds (42, 43)
- ✅ Self-contained test execution

### 2. Realistic Data
**All fixtures use realistic values:**
- OHLCV data with proper relationships (L ≤ O,C ≤ H)
- Realistic price trends and volatility
- Realistic trade sizes (0.01-1.0 BTC)
- Realistic fees (Kraken: 0.16% maker, 0.26% taker)
- Realistic slippage (2-3 bps)

### 3. Fast Execution
**Performance targets:**
- Full test suite: <60s
- Individual smoke test: <10s
- Unit tests: <1s each
- Use `pytest -m "not slow"` to skip performance tests

### 4. Comprehensive Coverage
**Test categories:**
- ✅ Smoke tests (quick sanity checks)
- ✅ Unit tests (individual functions/classes)
- ✅ Integration tests (multi-component flows)
- ✅ Performance tests (scaling, throughput)
- ✅ Edge cases (empty data, single trade, errors)
- ✅ Error handling (malformed data, API errors)

## Running Tests

### Basic Usage

```bash
# Run all tests quietly (default)
pytest agents/scalper/tests -q

# Run with verbose output
pytest agents/scalper/tests -v

# Run with extra verbose output (show test docstrings)
pytest agents/scalper/tests -vv

# Run single test file
pytest agents/scalper/tests/test_backtest_smoke.py

# Run specific test
pytest agents/scalper/tests/test_backtest_smoke.py::test_backtest_smoke_btcusdt_1m_produces_trades -v
```

### Filtering Tests

```bash
# Run only smoke tests
pytest agents/scalper/tests -m "smoke" -v

# Run only unit tests
pytest agents/scalper/tests -m "unit" -v

# Skip slow tests
pytest agents/scalper/tests -m "not slow" -v

# Run integration tests only
pytest agents/scalper/tests -m "integration" -v

# Combine markers
pytest agents/scalper/tests -m "smoke or unit" -v
```

### Performance and Debugging

```bash
# Show duration of slowest 10 tests
pytest agents/scalper/tests --durations=10

# Stop on first failure
pytest agents/scalper/tests -x

# Run last failed tests
pytest agents/scalper/tests --lf

# Run failed tests first, then all
pytest agents/scalper/tests --ff

# Show local variables on failure
pytest agents/scalper/tests --showlocals

# Drop into debugger on failure
pytest agents/scalper/tests --pdb
```

### Coverage

```bash
# Run with coverage report
pytest agents/scalper/tests --cov=agents.scalper --cov-report=term-missing

# Generate HTML coverage report
pytest agents/scalper/tests --cov=agents.scalper --cov-report=html
# Open htmlcov/index.html in browser

# Coverage for specific module
pytest agents/scalper/tests --cov=agents.scalper.backtest
```

### Async Tests

All async tests use `pytest-asyncio` with `asyncio_mode = auto` (configured in pytest.ini).

```python
@pytest.mark.asyncio
async def test_my_async_function():
    result = await my_async_function()
    assert result == expected
```

### Parametrized Tests

Use `@pytest.mark.parametrize` for testing multiple scenarios:

```python
@pytest.mark.parametrize("num_bars", [100, 500, 1000])
def test_backtest_performance_scaling(num_bars):
    # Test scales with num_bars
```

## Test Markers

Markers are defined in `pytest.ini` and `conftest.py`:

- `@pytest.mark.unit`: Unit tests (fast, no I/O)
- `@pytest.mark.integration`: Integration tests (multiple components)
- `@pytest.mark.slow`: Slow tests (>1s execution)
- `@pytest.mark.smoke`: Smoke tests (quick sanity checks)
- `@pytest.mark.performance`: Performance/benchmark tests

## Dependencies

**Required packages:**
```
pytest>=7.0
pytest-asyncio>=0.21.0
pytest-cov>=4.0.0
pytest-timeout>=2.1.0
pandas>=2.0.0
numpy>=1.24.0
```

**Install all dependencies:**
```bash
conda activate crypto-bot
pip install pytest pytest-asyncio pytest-cov pytest-timeout
```

## Continuous Integration

### GitHub Actions Example

```yaml
name: Test Scalper Agent

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Set up Python 3.10
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-asyncio pytest-cov
      - name: Run tests
        run: pytest agents/scalper/tests -q --cov=agents.scalper
      - name: Check test duration
        run: |
          duration=$(pytest agents/scalper/tests -q --durations=0 | grep "seconds" | awk '{print $1}')
          if (( $(echo "$duration > 60" | bc -l) )); then
            echo "Tests took ${duration}s (>60s limit)"
            exit 1
          fi
```

## Troubleshooting

### Import Errors

If you encounter import errors:

```bash
# Ensure PYTHONPATH includes project root
export PYTHONPATH="${PYTHONPATH}:/path/to/crypto_ai_bot"

# Or run from project root
cd /path/to/crypto_ai_bot
pytest agents/scalper/tests -v
```

### Missing Modules

If backtest or risk modules are missing:

```bash
# Check module structure
ls -la agents/scalper/backtest/
ls -la agents/risk/

# Ensure __init__.py files exist
touch agents/scalper/backtest/__init__.py
touch agents/risk/__init__.py
```

### Async Test Issues

If async tests fail with "coroutine was never awaited":

```bash
# Ensure pytest-asyncio is installed
pip install pytest-asyncio

# Check asyncio_mode in pytest.ini
grep asyncio_mode agents/scalper/tests/pytest.ini
# Should show: asyncio_mode = auto
```

### Slow Tests

If tests take >60s:

```bash
# Run with durations report
pytest agents/scalper/tests --durations=10

# Skip slow tests
pytest agents/scalper/tests -m "not slow" -v

# Profile individual test
pytest agents/scalper/tests/test_backtest_smoke.py::test_backtest_smoke_btcusdt_1m_produces_trades -v --profile
```

## Best Practices

### Writing New Tests

1. **Use existing fixtures**: Reuse fixtures from `conftest.py`
2. **Keep tests hermetic**: No network calls, no file I/O
3. **Use deterministic seeds**: `np.random.seed(42)` for reproducibility
4. **Add markers**: Mark tests appropriately (`@pytest.mark.unit`, etc.)
5. **Test edge cases**: Empty data, single item, errors
6. **Assert thoroughly**: Check all relevant outputs
7. **Add docstrings**: Explain what the test validates

### Example Test Structure

```python
@pytest.mark.unit
def test_my_function_with_valid_input(sample_btcusdt_1m):
    """
    Test my_function with valid OHLCV input.

    Validates:
    - Function returns expected output type
    - Output values are within expected range
    - Edge cases are handled correctly
    """
    # Arrange
    data = sample_btcusdt_1m
    expected_length = 100

    # Act
    result = my_function(data)

    # Assert
    assert len(result) == expected_length
    assert all(isinstance(x, float) for x in result)
    assert all(x > 0 for x in result)
```

## Success Criteria

✅ **All tests pass**: `pytest agents/scalper/tests -q` exits with code 0
✅ **Fast execution**: Full test suite completes in <60s
✅ **High coverage**: >80% code coverage for tested modules
✅ **No warnings**: No deprecation or runtime warnings
✅ **Hermetic**: No network calls, no Redis, no file I/O
✅ **Deterministic**: Same results on every run

## Related Documentation

- [Backtest Analysis](../backtest/BACKTEST_ANALYSIS.md): Analysis of backtest modules
- [Integration Guide](../protections/INTEGRATION_GUIDE.md): Protections & risk integration
- [Replay Enhanced](../backtest/replay_enhanced.py): Enhanced replay feeder documentation

## Contributing

When adding new tests:

1. Add fixtures to `conftest.py` if reusable
2. Use existing fixtures where possible
3. Keep tests hermetic (no external dependencies)
4. Add appropriate markers
5. Ensure fast execution (<1s per unit test)
6. Update this README if adding new test categories

## Questions?

For issues with the test suite, check:
1. This README's Troubleshooting section
2. Test file docstrings for specific guidance
3. Fixture documentation in `conftest.py`
