# Enhanced Scalper Agent with Multi-Strategy Integration

## Overview

The Enhanced Scalper Agent represents a significant evolution of the original Kraken scalping strategy, integrating multiple trading strategies to achieve superior performance through:

- **Regime-based market condition detection**
- **Multi-strategy signal alignment**
- **Dynamic parameter adaptation**
- **Enhanced risk management**
- **Confidence weighting system**

## Architecture

### Core Components

1. **Enhanced Scalper Agent** (`agents/scalper/enhanced_scalper_agent.py`)
   - Main integration layer combining scalping with other strategies
   - Manages signal alignment and filtering
   - Handles regime-based parameter adaptation

2. **Strategy Router** (`strategies/regime_based_router.py`)
   - Detects market regimes (bull, bear, sideways)
   - Routes to appropriate strategies based on market conditions
   - Provides fallback mechanisms

3. **Individual Strategies**
   - **Breakout Strategy**: Detects resistance/support breaks
   - **Mean Reversion**: Uses Bollinger Bands and RSI
   - **Momentum Strategy**: RSI, VWAP, and trailing stops
   - **Trend Following**: EMA crossovers with ATR
   - **Sideways Strategy**: Grid trading for range-bound markets

4. **Configuration System** (`config/enhanced_scalper_loader.py`)
   - Loads and validates configuration
   - Supports environment variable overrides
   - Provides default configurations

## Key Features

### 1. Regime-Based Trading

The agent automatically detects market regimes and adapts its behavior:

```python
# Bull market: Focus on long scalps, increase targets
if regime == 'bull':
    target_bps = 12
    stop_loss_bps = 6
    max_trades_per_min = 4

# Sideways market: Increase frequency, reduce targets
elif regime == 'sideways':
    target_bps = 8
    stop_loss_bps = 4
    max_trades_per_min = 6
```

### 2. Strategy Alignment

Signals are enhanced by checking alignment with other strategies:

```python
# Check if scalping signal aligns with strategy signals
is_aligned, confidence, reason = agent._check_strategy_alignment(
    scalping_signal, strategy_signals
)

# Boost confidence for aligned signals
if is_aligned:
    enhanced_confidence = base_confidence * 1.3
```

### 3. Signal Filtering

Multiple layers of filtering ensure only high-quality signals are executed:

- **Strategy alignment filtering**: Requires minimum alignment confidence
- **Regime confidence filtering**: Filters based on regime detection confidence
- **Scalping confidence filtering**: Ensures minimum scalping signal quality
- **Risk management filtering**: Additional risk checks

### 4. Dynamic Parameter Adaptation

Parameters automatically adjust based on market conditions:

```yaml
regime_adaptation:
  sideways_target_bps: 8
  sideways_stop_bps: 4
  sideways_max_trades: 6
  bull_target_bps: 12
  bull_stop_bps: 6
  bull_max_trades: 4
```

## Configuration

### Basic Configuration

```yaml
# Enhanced scalper configuration
scalper:
  pairs: ["BTC/USD", "ETH/USD", "ADA/USD", "SOL/USD"]
  target_bps: 10
  stop_loss_bps: 5
  timeframe: "15s"
  preferred_order_type: "limit"
  post_only: true

# Strategy router configuration
strategy_router:
  strategy_allocations:
    breakout: 0.25
    mean_reversion: 0.20
    momentum: 0.25
    trend_following: 0.30
    sideways: 0.15

# Signal filtering
signal_filtering:
  min_alignment_confidence: 0.3
  min_strategy_alignment: 0.6
  require_alignment: false
  min_regime_confidence: 0.3
  min_scalping_confidence: 0.5
```

### Environment Variables

```bash
# Scalper configuration
export SCALPER_PAIRS="BTC/USD,ETH/USD"
export SCALPER_TARGET_BPS=10
export SCALPER_STOP_LOSS_BPS=5

# Redis configuration
export REDIS_HOST=localhost
export REDIS_PORT=6379

# AI Engine configuration
export AI_ENGINE_MODE=hypergrowth

# Signal filtering
export MIN_ALIGNMENT_CONFIDENCE=0.3
export REQUIRE_ALIGNMENT=false
```

## Usage

### Basic Usage

```python
import asyncio
from agents.scalper.enhanced_scalper_agent import EnhancedScalperAgent
from config.enhanced_scalper_loader import load_enhanced_scalper_config

async def main():
    # Load configuration
    config = load_enhanced_scalper_config()
    
    # Initialize agent
    agent = EnhancedScalperAgent(config)
    await agent.initialize()
    
    # Generate enhanced signal
    signal = await agent.generate_enhanced_signal(
        pair='BTC/USD',
        best_bid=49995.0,
        best_ask=50005.0,
        last_price=50000.0,
        quote_liquidity_usd=2000000.0,
        market_data=market_data
    )
    
    if signal:
        print(f"Enhanced signal: {signal.side} confidence={signal.confidence:.3f}")
        print(f"Strategy alignment: {signal.strategy_alignment}")
        print(f"Market regime: {signal.regime_state}")

asyncio.run(main())
```

### Running the Demo

```bash
# Run enhanced scalper demo
python scripts/run_enhanced_scalper.py --duration 10 --pairs BTC/USD ETH/USD

# Run with custom configuration
python scripts/run_enhanced_scalper.py --config config/my_config.yaml --duration 30
```

### Running Integration Tests

```bash
# Run comprehensive integration tests
python scripts/test_enhanced_integration.py

# Run with verbose output
python -m pytest tests/test_enhanced_scalper.py -v
```

## Expected Benefits

### 1. Higher Win Rate
- **Strategy alignment** improves signal quality by filtering out conflicting signals
- **Regime awareness** ensures trades are taken in favorable market conditions
- **Confidence weighting** prioritizes high-quality signals

### 2. Better Risk Management
- **Regime-aware position sizing** adjusts position sizes based on market conditions
- **Multi-layer filtering** prevents low-quality trades
- **Dynamic parameter adaptation** reduces risk during unfavorable regimes

### 3. Adaptive Performance
- **Automatic regime detection** adapts to changing market conditions
- **Strategy selection** chooses appropriate strategies for current market regime
- **Parameter optimization** continuously adjusts based on performance

### 4. Reduced Drawdowns
- **Signal filtering** eliminates trades during unfavorable conditions
- **Regime-based pausing** stops trading during high-risk periods
- **Confidence thresholds** ensure only high-probability trades are executed

### 5. Enhanced Profitability
- **Strategy combination** leverages multiple approaches for better performance
- **Regime adaptation** maximizes profits in different market conditions
- **Risk-adjusted returns** provides better risk-reward ratios

## Performance Metrics

The enhanced scalper tracks comprehensive performance metrics:

```python
{
    'total_signals': 150,
    'aligned_signals': 120,
    'filtered_signals': 30,
    'regime_adaptations': 5,
    'avg_confidence': 0.75,
    'signal_alignment_rate': 0.80,
    'signal_filter_rate': 0.20
}
```

## Monitoring and Observability

### Prometheus Metrics

- `enhanced_scalper_signals_generated_total`
- `enhanced_scalper_signals_aligned_total`
- `enhanced_scalper_signals_filtered_total`
- `enhanced_scalper_regime_adaptations_total`
- `enhanced_scalper_strategy_confidence_histogram`
- `enhanced_scalper_enhanced_confidence_histogram`

### Redis Streams

- `stream:enhanced_scalper:signals` - Generated signals
- `stream:enhanced_scalper:metrics` - Performance metrics
- `stream:enhanced_scalper:regime` - Regime updates

### Logging

Structured logging with configurable levels:

```python
{
    "timestamp": "2024-01-01T12:00:00Z",
    "level": "INFO",
    "message": "Enhanced signal generated",
    "pair": "BTC/USD",
    "side": "buy",
    "confidence": 0.85,
    "strategy_alignment": true,
    "regime_state": "bull"
}
```

## Testing

### Unit Tests

```bash
# Run unit tests
pytest tests/test_enhanced_scalper.py -v

# Run with coverage
pytest tests/test_enhanced_scalper.py --cov=agents.scalper --cov-report=html
```

### Integration Tests

```bash
# Run integration tests
python scripts/test_enhanced_integration.py

# Run specific test
pytest tests/test_enhanced_scalper.py::TestEnhancedScalperAgent::test_strategy_alignment -v
```

### Performance Tests

```bash
# Run performance comparison
python scripts/run_enhanced_scalper.py --duration 60 --pairs BTC/USD ETH/USD ADA/USD
```

## Troubleshooting

### Common Issues

1. **Strategy Import Errors**
   ```bash
   # Ensure all strategy modules are available
   pip install -r requirements_enhanced_scalper.txt
   ```

2. **Redis Connection Issues**
   ```bash
   # Check Redis is running
   redis-cli ping
   
   # Update Redis configuration
   export REDIS_HOST=your_redis_host
   export REDIS_PORT=6379
   ```

3. **Configuration Validation Errors**
   ```bash
   # Validate configuration
   python -c "from config.enhanced_scalper_loader import load_enhanced_scalper_config; load_enhanced_scalper_config()"
   ```

### Debug Mode

Enable debug logging for detailed information:

```yaml
logging:
  level: "DEBUG"
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
```

## Contributing

### Development Setup

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -r requirements_enhanced_scalper.txt
   ```
3. Run tests:
   ```bash
   pytest tests/test_enhanced_scalper.py -v
   ```

### Code Style

- Follow PEP 8 guidelines
- Use type hints
- Write comprehensive docstrings
- Include unit tests for new features

### Pull Request Process

1. Create feature branch
2. Implement changes with tests
3. Run full test suite
4. Submit pull request with description

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For questions and support:

- Create an issue on GitHub
- Check the documentation
- Review the test cases for examples

## Changelog

### Version 1.0.0
- Initial release of enhanced scalper agent
- Multi-strategy integration
- Regime-based trading
- Signal alignment and filtering
- Comprehensive testing suite

