"""
Run Backtest with Latest Market Data

This script demonstrates how to run backtests using the most recent market prices.

Features:
- Fetches latest OHLCV data up to current time
- Automatically refreshes stale cached data (>24h old)
- Uses PRD-001 compliant data provider, metrics calculator, and acceptance criteria
- Generates backtest report with all PRD metrics

Usage:
    # Run backtest with latest BTC/USD data
    python scripts/run_backtest_with_latest_data.py --pair BTC/USD --days 365

    # Force refresh cached data
    python scripts/run_backtest_with_latest_data.py --pair ETH/USD --force-refresh

    # Use custom cache age threshold
    python scripts/run_backtest_with_latest_data.py --pair SOL/USD --max-cache-age 12

Author: Crypto AI Bot Team
"""

import argparse
import logging
from datetime import datetime
from pathlib import Path

from backtesting.prd_data_provider import PRDBacktestDataProvider
from backtesting.prd_metrics_calculator import PRDMetricsCalculator
from backtesting.prd_acceptance_criteria import PRDAcceptanceCriteria

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_backtest_with_latest_data(
    pair: str = "BTC/USD",
    days: int = 365,
    timeframe: str = "1h",
    force_refresh: bool = False,
    max_cache_age_hours: int = 24
):
    """
    Run backtest with latest market data.

    Args:
        pair: Trading pair (e.g., "BTC/USD")
        days: Number of days of historical data
        timeframe: Candle timeframe
        force_refresh: Force refresh cached data
        max_cache_age_hours: Max cache age before refresh

    Returns:
        Backtest metrics and acceptance result
    """
    logger.info("="*80)
    logger.info(f"BACKTEST WITH LATEST MARKET DATA: {pair}")
    logger.info("="*80)

    # Initialize PRD-compliant components
    data_provider = PRDBacktestDataProvider()
    metrics_calculator = PRDMetricsCalculator()
    acceptance_criteria = PRDAcceptanceCriteria()

    # Fetch latest OHLCV data
    logger.info(f"\n[STEP 1] Fetching latest {pair} data...")
    if force_refresh:
        logger.info("Force refresh enabled - fetching fresh data from Kraken")
        ohlcv_data = data_provider.fetch_ohlcv(
            pair=pair,
            days=days,
            timeframe=timeframe,
            force_refresh=True
        )
    else:
        logger.info(f"Auto-refresh if cache older than {max_cache_age_hours}h")
        ohlcv_data = data_provider.fetch_latest_ohlcv(
            pair=pair,
            days=days,
            timeframe=timeframe,
            max_cache_age_hours=max_cache_age_hours
        )

    logger.info(f"✓ Loaded {len(ohlcv_data)} candles")
    logger.info(f"  Period: {ohlcv_data['timestamp'].min()} to {ohlcv_data['timestamp'].max()}")

    # Calculate how recent the data is
    latest_timestamp = ohlcv_data['timestamp'].max()
    hours_old = (datetime.now() - latest_timestamp).total_seconds() / 3600
    logger.info(f"  Latest data: {hours_old:.1f} hours old")

    # Run simple buy-and-hold backtest (placeholder)
    logger.info(f"\n[STEP 2] Running backtest...")
    initial_capital = 10000.0
    entry_price = ohlcv_data['close'].iloc[0]
    exit_price = ohlcv_data['close'].iloc[-1]

    # Simulate single trade
    position_size_usd = initial_capital

    # Calculate fill with slippage and fees (market order)
    entry_fill_price, entry_fee, entry_cost = data_provider.simulate_order_fill(
        price=entry_price,
        size_usd=position_size_usd,
        side="buy",
        order_type="market"
    )

    exit_fill_price, exit_fee, exit_proceeds = data_provider.simulate_order_fill(
        price=exit_price,
        size_usd=position_size_usd,
        side="sell",
        order_type="market"
    )

    # Calculate PnL
    pnl = exit_proceeds - entry_cost
    final_equity = initial_capital + pnl

    # Calculate trade duration
    trade_duration_hours = (
        ohlcv_data['timestamp'].iloc[-1] - ohlcv_data['timestamp'].iloc[0]
    ).total_seconds() / 3600

    # Create trades list
    trades = [{
        'pnl': pnl,
        'duration_hours': trade_duration_hours,
        'entry_price': entry_fill_price,
        'exit_price': exit_fill_price,
        'entry_fee': entry_fee,
        'exit_fee': exit_fee
    }]

    # Create simple equity curve
    equity_curve = [initial_capital, final_equity]

    logger.info(f"✓ Backtest complete: {len(trades)} trade(s)")
    logger.info(f"  Entry: ${entry_fill_price:,.2f} (fee: ${entry_fee:.2f})")
    logger.info(f"  Exit:  ${exit_fill_price:,.2f} (fee: ${exit_fee:.2f})")
    logger.info(f"  PnL:   ${pnl:,.2f}")

    # Calculate metrics
    logger.info(f"\n[STEP 3] Calculating PRD metrics...")
    metrics = metrics_calculator.calculate_metrics(
        trades=trades,
        equity_curve=equity_curve,
        initial_capital=initial_capital
    )

    logger.info(f"✓ Metrics calculated:")
    logger.info(f"  Total Return:     {metrics.total_return_pct:>7.2f}%")
    logger.info(f"  Sharpe Ratio:     {metrics.sharpe_ratio:>7.2f}")
    logger.info(f"  Max Drawdown:     {metrics.max_drawdown_pct:>7.2f}%")
    logger.info(f"  Win Rate:         {metrics.win_rate:>7.2f}%")
    logger.info(f"  Profit Factor:    {metrics.profit_factor:>7.2f}")
    logger.info(f"  Avg Trade Hours:  {metrics.avg_trade_duration_hours:>7.2f}")
    logger.info(f"  Total Trades:     {metrics.total_trades:>7}")

    # Check acceptance criteria
    logger.info(f"\n[STEP 4] Checking acceptance criteria...")
    result = acceptance_criteria.check_acceptance(metrics)

    if result.passed:
        logger.info("✓ ACCEPTANCE PASSED - Ready for production")
    else:
        logger.warning("✗ ACCEPTANCE FAILED - Not ready for production")
        logger.warning("Failures:")
        for failure in result.failures:
            logger.warning(f"  - {failure}")

    # Save metrics
    logger.info(f"\n[STEP 5] Saving metrics...")
    output_path = metrics_calculator.save_metrics(
        metrics=metrics,
        strategy=f"{pair.replace('/', '_')}_latest",
        output_dir=Path("out/backtests")
    )
    logger.info(f"✓ Metrics saved to: {output_path}")

    logger.info("\n" + "="*80)
    logger.info("BACKTEST COMPLETE")
    logger.info("="*80)

    return metrics, result


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Run backtest with latest market data"
    )
    parser.add_argument(
        '--pair',
        type=str,
        default='BTC/USD',
        help='Trading pair (default: BTC/USD)'
    )
    parser.add_argument(
        '--days',
        type=int,
        default=365,
        help='Number of days of historical data (default: 365)'
    )
    parser.add_argument(
        '--timeframe',
        type=str,
        default='1h',
        help='Candle timeframe (default: 1h)'
    )
    parser.add_argument(
        '--force-refresh',
        action='store_true',
        help='Force refresh cached data'
    )
    parser.add_argument(
        '--max-cache-age',
        type=int,
        default=24,
        help='Max cache age in hours before refresh (default: 24)'
    )

    args = parser.parse_args()

    try:
        metrics, result = run_backtest_with_latest_data(
            pair=args.pair,
            days=args.days,
            timeframe=args.timeframe,
            force_refresh=args.force_refresh,
            max_cache_age_hours=args.max_cache_age
        )

        # Exit with error code if acceptance failed
        if not result.passed:
            exit(1)

    except Exception as e:
        logger.error(f"Backtest failed: {e}", exc_info=True)
        exit(1)


if __name__ == "__main__":
    main()
