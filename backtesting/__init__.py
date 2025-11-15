"""
Backtesting framework for crypto-ai-bot.

Simulates strategy performance against historical data using the same
pure functions as live trading.

**Architecture:**

1. Data Loader: Fetch historical OHLCV from exchanges
2. Backtest Engine: Replay data through graph logic
3. Position Tracker: Simulate order fills and P&L
4. Metrics Calculator: Sharpe, drawdown, win rate, etc.

**CLI Usage:**

    # Quick backtest (1 year, default settings)
    python -m backtesting.run_backtest --symbol BTC/USD --capital 10000

    # Full backtest with custom parameters
    python -m backtesting.run_backtest \\
        --symbol BTC/USD \\
        --start-date 2022-01-01 \\
        --end-date 2024-01-01 \\
        --capital 10000 \\
        --timeframe 1h \\
        --position-size 0.02

**Python Usage:**

    from backtesting import BacktestEngine, BacktestConfig, DataLoader

    # Load data
    loader = DataLoader("kraken")
    data = loader.fetch_ohlcv("BTC/USD", "1h", "2023-01-01", "2023-12-31")

    # Configure backtest
    config = BacktestConfig(
        symbol="BTC/USD",
        start_date="2023-01-01",
        end_date="2023-12-31",
        initial_capital=10000.0,
        timeframe="1h",
    )

    # Run backtest
    engine = BacktestEngine(config)
    results = engine.run(data)

    # Print results
    results.print_summary()
    print(f"Total Return: {results.total_return_pct:.2f}%")
    print(f"Sharpe Ratio: {results.sharpe_ratio:.2f}")
"""

from __future__ import annotations

# PRD-001 Section 6.1: Import PRD-compliant data provider
from .prd_data_provider import (
    PRDBacktestDataProvider,
    get_data_provider,
    DEFAULT_PAIRS,
    SLIPPAGE_BPS,
    MAKER_FEE_BPS,
    TAKER_FEE_BPS
)

# Legacy imports (may have dependency issues)
try:
    from .data_loader import DataLoader
    from .engine import BacktestEngine, BacktestConfig
    from .metrics import BacktestResults, Trade, calculate_metrics

    __all__ = [
        # PRD-001 Section 6.1
        "PRDBacktestDataProvider",
        "get_data_provider",
        "DEFAULT_PAIRS",
        "SLIPPAGE_BPS",
        "MAKER_FEE_BPS",
        "TAKER_FEE_BPS",
        # Legacy
        "DataLoader",
        "BacktestEngine",
        "BacktestConfig",
        "BacktestResults",
        "Trade",
        "calculate_metrics",
    ]
except ImportError:
    # If legacy imports fail, only export PRD-compliant components
    __all__ = [
        "PRDBacktestDataProvider",
        "get_data_provider",
        "DEFAULT_PAIRS",
        "SLIPPAGE_BPS",
        "MAKER_FEE_BPS",
        "TAKER_FEE_BPS",
    ]
