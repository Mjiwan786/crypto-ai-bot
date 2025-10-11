# Enhanced Scalper Agent - Testing and Backtesting Guide

## Overview

This guide provides comprehensive instructions for testing and backtesting the enhanced scalper agent. The testing suite includes unit tests, integration tests, performance tests, stress tests, and historical backtesting.

## Quick Start

### Windows Users
```bash
# Run all tests and backtests
run_enhanced_scalper_tests.bat

# Or using PowerShell
.\run_enhanced_scalper_tests.ps1
```

### Linux/Mac Users
```bash
# Run all tests and backtests
conda run -n crypto-bot python scripts/run_all_tests_and_backtests.py
```

## Test Suite Components

### 1. Unit Tests (`scripts/test_enhanced_scalper.py`)
Comprehensive unit tests for all components:

```bash
# Run unit tests
conda run -n crypto-bot python scripts/test_enhanced_scalper.py

# Run specific test suite
conda run -n crypto-bot python scripts/test_enhanced_scalper.py --suite performance
```

**Test Categories:**
- Configuration Tests
- Agent Initialization Tests
- Strategy Integration Tests
- Signal Generation Tests
- Signal Filtering Tests
- Regime Detection Tests
- Parameter Adaptation Tests
- Risk Management Tests
- Performance Tests
- Stress Tests
- Integration Tests

### 2. Integration Tests (`scripts/test_enhanced_integration.py`)
Tests the integration between different components:

```bash
# Run integration tests
conda run -n crypto-bot python scripts/test_enhanced_integration.py
```

**Integration Tests:**
- Basic Integration
- Regime Detection
- Strategy Alignment
- Signal Filtering
- Parameter Adaptation
- Confidence Weighting
- Performance Comparison
- Risk Management

### 3. Backtesting (`scripts/backtest_enhanced_scalper.py`)
Historical backtesting with comprehensive analysis:

```bash
# Short backtest (1 week)
conda run -n crypto-bot python scripts/backtest_enhanced_scalper.py --start-date 2024-01-01 --end-date 2024-01-07 --pairs BTC/USD ETH/USD --capital 10000

# Medium backtest (1 month)
conda run -n crypto-bot python scripts/backtest_enhanced_scalper.py --start-date 2024-01-01 --end-date 2024-01-31 --pairs BTC/USD ETH/USD --capital 10000

# Long backtest (3 months)
conda run -n crypto-bot python scripts/backtest_enhanced_scalper.py --start-date 2024-01-01 --end-date 2024-03-31 --pairs BTC/USD ETH/USD --capital 10000
```

**Backtest Features:**
- Historical data generation
- Signal generation and execution
- Performance analysis
- Risk metrics calculation
- Regime analysis
- Strategy comparison
- Comprehensive reporting

### 4. Demo (`scripts/demo_enhanced_scalper.py`)
Live demo with simulated market data:

```bash
# Run 5-minute demo
conda run -n crypto-bot python scripts/demo_enhanced_scalper.py --duration 5

# Run with specific pairs
conda run -n crypto-bot python scripts/demo_enhanced_scalper.py --duration 10 --pairs BTC/USD ETH/USD ADA/USD
```

## Test Configuration

### Environment Setup
Ensure the `crypto-bot` conda environment is properly set up:

```bash
# Create environment
conda create -n crypto-bot python=3.10

# Activate environment
conda activate crypto-bot

# Install dependencies
pip install -r requirements_enhanced_scalper.txt
```

### Configuration Files
- **Main Config**: `config/enhanced_scalper_config.yaml`
- **Test Config**: Uses main config with test-specific overrides
- **Backtest Config**: Configurable via command line arguments

## Test Results and Reports

### Output Locations
- **Test Logs**: `logs/enhanced_scalper_test.log`
- **Backtest Logs**: `logs/enhanced_scalper_backtest.log`
- **Test Results**: `logs/enhanced_scalper_test_results.json`
- **Backtest Results**: `reports/enhanced_scalper_backtest/`

### Report Contents
- **Performance Metrics**: Win rate, Sharpe ratio, max drawdown
- **Risk Metrics**: VaR, Expected Shortfall, consecutive losses
- **Regime Analysis**: Performance by market regime
- **Strategy Comparison**: Enhanced vs basic scalper
- **Charts**: Equity curve, performance charts, regime analysis

## Performance Benchmarks

### Expected Performance (Based on Backtests)
- **Win Rate**: 60-80% (depending on market conditions)
- **Sharpe Ratio**: 1.5-2.5
- **Max Drawdown**: <10%
- **Annual Return**: 15-30%
- **Signal Alignment Rate**: 70-85%

### Key Metrics Tracked
- Total trades executed
- Win/loss ratio
- Average profit per trade
- Maximum consecutive losses
- Regime adaptation frequency
- Strategy alignment rate
- Signal filter rate

## Troubleshooting

### Common Issues

#### 1. Conda Environment Not Found
```bash
# Create the environment
conda create -n crypto-bot python=3.10

# Activate it
conda activate crypto-bot

# Install dependencies
pip install -r requirements_enhanced_scalper.txt
```

#### 2. Import Errors
```bash
# Check if packages are installed
conda run -n crypto-bot python -c "import pandas, numpy, asyncio, ccxt, pydantic, redis"

# Install missing packages
conda run -n crypto-bot pip install <missing_package>
```

#### 3. Configuration Errors
```bash
# Validate configuration
conda run -n crypto-bot python -c "from config.enhanced_scalper_loader import load_enhanced_scalper_config; load_enhanced_scalper_config()"
```

#### 4. Test Failures
```bash
# Run tests with verbose output
conda run -n crypto-bot python -m pytest tests/test_enhanced_scalper.py -v -s

# Check specific test
conda run -n crypto-bot python scripts/test_enhanced_scalper.py --suite <test_name>
```

### Debug Mode
Enable debug logging for detailed information:

```yaml
# In config/enhanced_scalper_config.yaml
logging:
  level: "DEBUG"
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
```

## Advanced Usage

### Custom Test Scenarios

#### 1. Custom Backtest Period
```bash
conda run -n crypto-bot python scripts/backtest_enhanced_scalper.py \
  --start-date 2024-06-01 \
  --end-date 2024-08-31 \
  --pairs BTC/USD ETH/USD ADA/USD SOL/USD \
  --capital 50000
```

#### 2. Stress Testing
```bash
# Run stress tests
conda run -n crypto-bot python scripts/test_enhanced_scalper.py --suite stress

# High-frequency demo
conda run -n crypto-bot python scripts/demo_enhanced_scalper.py --duration 30
```

#### 3. Performance Profiling
```bash
# Run with profiling
conda run -n crypto-bot python -m cProfile -o profile.stats scripts/backtest_enhanced_scalper.py

# Analyze profile
conda run -n crypto-bot python -c "import pstats; pstats.Stats('profile.stats').sort_stats('cumulative').print_stats(20)"
```

### Custom Configuration

#### 1. Test-Specific Configuration
```yaml
# Create test_config.yaml
scalper:
  pairs: ["BTC/USD", "ETH/USD"]
  target_bps: 8
  stop_loss_bps: 4
  max_trades_per_minute: 6

signal_filtering:
  min_alignment_confidence: 0.4
  require_alignment: true
```

#### 2. Run with Custom Config
```bash
conda run -n crypto-bot python scripts/backtest_enhanced_scalper.py --config test_config.yaml
```

## Continuous Integration

### GitHub Actions Example
```yaml
name: Enhanced Scalper Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v2
    - name: Set up Python
      uses: actions/setup-python@v2
      with:
        python-version: 3.10
    - name: Install dependencies
      run: |
        pip install -r requirements_enhanced_scalper.txt
    - name: Run tests
      run: |
        python scripts/test_enhanced_scalper.py
        python scripts/test_enhanced_integration.py
    - name: Run backtest
      run: |
        python scripts/backtest_enhanced_scalper.py --start-date 2024-01-01 --end-date 2024-01-07
```

## Best Practices

### 1. Test Before Deployment
- Always run the complete test suite before deploying
- Verify backtest results match expectations
- Check performance metrics against benchmarks

### 2. Regular Testing
- Run tests after any configuration changes
- Perform weekly backtests to monitor performance
- Update tests when adding new features

### 3. Monitor Results
- Review test logs regularly
- Track performance metrics over time
- Investigate any test failures immediately

### 4. Documentation
- Document any custom test scenarios
- Keep test results for historical reference
- Update this guide when adding new tests

## Support

For questions and support:

1. **Check the logs**: Review test logs for detailed error information
2. **Run individual tests**: Isolate issues by running specific test phases
3. **Review configuration**: Ensure all configuration parameters are correct
4. **Check dependencies**: Verify all required packages are installed

## Conclusion

The enhanced scalper agent testing suite provides comprehensive validation of all components and integrations. Regular testing ensures the system remains reliable and performs as expected in production environments.

For more information, see:
- `docs/ENHANCED_SCALPER_README.md` - Main documentation
- `ENHANCED_SCALPER_INTEGRATION_SUMMARY.md` - Integration summary
- `config/enhanced_scalper_config.yaml` - Configuration reference

