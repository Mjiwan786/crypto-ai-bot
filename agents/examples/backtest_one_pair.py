#!/usr/bin/env python3
"""
Backtest One Pair Example

Demonstrates backtesting workflow:
1. Load historical price data (CSV or generate fake data)
2. Run simple trading strategy
3. Calculate performance metrics
4. Generate and save equity curve chart

This example requires only:
- conda environment: crypto-bot
- Optional: CSV file with OHLCV data

Usage:
    conda activate crypto-bot

    # With CSV data
    python -m agents.examples.backtest_one_pair \
        --data data/BTC_USD_1h.csv \
        --pair BTC/USD \
        --strategy ma_crossover

    # Generate fake data (no CSV needed)
    python -m agents.examples.backtest_one_pair \
        --generate-data \
        --bars 1000 \
        --pair BTC/USD

    # Quick test with defaults
    python -m agents.examples.backtest_one_pair --generate-data

Author: Crypto AI Bot Team
License: MIT
"""

import argparse
import logging
import sys
import os
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
import random

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


@dataclass
class OHLCV:
    """OHLCV candlestick data"""
    timestamp: float
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Trade:
    """Backtest trade record"""
    timestamp: float
    action: str  # 'buy' or 'sell'
    price: float
    size: float
    pnl: float = 0.0


@dataclass
class BacktestResult:
    """Backtest results and metrics"""
    initial_equity: float
    final_equity: float
    total_return_pct: float
    num_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    max_drawdown_pct: float
    sharpe_ratio: float
    trades: List[Trade]
    equity_curve: List[float]


class DataGenerator:
    """Generate fake OHLCV data for testing"""

    @staticmethod
    def generate_ohlcv(
        num_bars: int = 1000,
        base_price: float = 50000.0,
        volatility: float = 0.02,
        trend: float = 0.0001
    ) -> List[OHLCV]:
        """
        Generate fake OHLCV candlestick data.

        Args:
            num_bars: Number of bars to generate
            base_price: Starting price
            volatility: Price volatility (0.02 = 2%)
            trend: Upward/downward drift (0.0001 = 0.01% per bar)
        """
        bars = []
        current_price = base_price
        current_time = datetime.now() - timedelta(hours=num_bars)

        for i in range(num_bars):
            # Price movement
            drift = current_price * trend
            shock = current_price * random.gauss(0, volatility)
            price_change = drift + shock

            open_price = current_price
            close_price = current_price + price_change

            # High/low with some variance
            high_price = max(open_price, close_price) * (1 + abs(random.gauss(0, volatility/2)))
            low_price = min(open_price, close_price) * (1 - abs(random.gauss(0, volatility/2)))

            # Volume
            volume = random.uniform(10, 100)

            bars.append(OHLCV(
                timestamp=current_time.timestamp(),
                open=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                volume=volume
            ))

            current_price = close_price
            current_time += timedelta(hours=1)

        return bars


class SimpleStrategy:
    """
    Simple moving average crossover strategy.

    Buy when fast MA crosses above slow MA.
    Sell when fast MA crosses below slow MA.
    """

    def __init__(self, fast_period: int = 10, slow_period: int = 30):
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.position = 0.0  # Current position size

    def calculate_ma(self, prices: List[float], period: int) -> float:
        """Calculate moving average"""
        if len(prices) < period:
            return prices[-1] if prices else 0.0
        return sum(prices[-period:]) / period

    def generate_signal(self, prices: List[float]) -> str:
        """
        Generate trading signal.

        Returns: 'buy', 'sell', or 'hold'
        """
        if len(prices) < self.slow_period:
            return 'hold'

        fast_ma = self.calculate_ma(prices, self.fast_period)
        slow_ma = self.calculate_ma(prices, self.slow_period)

        # Previous MAs for crossover detection
        if len(prices) < self.slow_period + 1:
            return 'hold'

        prev_fast = self.calculate_ma(prices[:-1], self.fast_period)
        prev_slow = self.calculate_ma(prices[:-1], self.slow_period)

        # Crossover signals
        if prev_fast <= prev_slow and fast_ma > slow_ma and self.position == 0:
            return 'buy'
        elif prev_fast >= prev_slow and fast_ma < slow_ma and self.position > 0:
            return 'sell'

        return 'hold'


class SimpleBacktester:
    """Simple backtesting engine"""

    def __init__(
        self,
        initial_equity: float = 10000.0,
        trade_size: float = 1.0,
        commission_pct: float = 0.001
    ):
        self.initial_equity = initial_equity
        self.trade_size = trade_size
        self.commission_pct = commission_pct

        self.equity = initial_equity
        self.position = 0.0
        self.entry_price = 0.0

        self.trades: List[Trade] = []
        self.equity_curve: List[float] = []

    def execute_trade(self, action: str, price: float, timestamp: float):
        """Execute a trade"""
        if action == 'buy' and self.position == 0:
            # Buy
            cost = self.trade_size * price
            commission = cost * self.commission_pct

            if self.equity >= (cost + commission):
                self.position = self.trade_size
                self.entry_price = price
                self.equity -= (cost + commission)

                self.trades.append(Trade(
                    timestamp=timestamp,
                    action='buy',
                    price=price,
                    size=self.trade_size
                ))

        elif action == 'sell' and self.position > 0:
            # Sell
            proceeds = self.position * price
            commission = proceeds * self.commission_pct
            pnl = proceeds - (self.position * self.entry_price) - commission

            self.equity += proceeds - commission
            self.position = 0.0

            self.trades.append(Trade(
                timestamp=timestamp,
                action='sell',
                price=price,
                size=self.trade_size,
                pnl=pnl
            ))

    def calculate_equity(self, current_price: float) -> float:
        """Calculate current total equity"""
        if self.position > 0:
            return self.equity + (self.position * current_price)
        return self.equity

    def run(self, data: List[OHLCV], strategy: SimpleStrategy) -> BacktestResult:
        """
        Run backtest.

        Args:
            data: List of OHLCV bars
            strategy: Trading strategy

        Returns:
            BacktestResult with metrics and trades
        """
        logger = logging.getLogger(__name__)
        logger.info(f"Running backtest on {len(data)} bars...")

        prices = []

        for i, bar in enumerate(data):
            prices.append(bar.close)

            # Generate signal
            signal = strategy.generate_signal(prices)

            # Execute trade
            if signal in ['buy', 'sell']:
                self.execute_trade(signal, bar.close, bar.timestamp)

            # Record equity
            equity = self.calculate_equity(bar.close)
            self.equity_curve.append(equity)

            # Progress
            if (i + 1) % 100 == 0:
                logger.info(f"  Progress: {i+1}/{len(data)} bars, Equity: ${equity:,.2f}")

        # Close any open position at end
        if self.position > 0:
            last_price = data[-1].close
            self.execute_trade('sell', last_price, data[-1].timestamp)

        # Calculate metrics
        result = self._calculate_metrics()
        logger.info(f"✅ Backtest complete: {result.num_trades} trades")

        return result

    def _calculate_metrics(self) -> BacktestResult:
        """Calculate performance metrics"""
        final_equity = self.equity_curve[-1] if self.equity_curve else self.initial_equity
        total_return_pct = ((final_equity - self.initial_equity) / self.initial_equity) * 100

        # Trade statistics
        winning_trades = len([t for t in self.trades if t.pnl > 0])
        losing_trades = len([t for t in self.trades if t.pnl < 0])
        win_rate = (winning_trades / len(self.trades) * 100) if self.trades else 0

        # Max drawdown
        max_drawdown_pct = self._calculate_max_drawdown()

        # Sharpe ratio (simplified)
        sharpe_ratio = self._calculate_sharpe_ratio()

        return BacktestResult(
            initial_equity=self.initial_equity,
            final_equity=final_equity,
            total_return_pct=total_return_pct,
            num_trades=len(self.trades),
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            max_drawdown_pct=max_drawdown_pct,
            sharpe_ratio=sharpe_ratio,
            trades=self.trades,
            equity_curve=self.equity_curve
        )

    def _calculate_max_drawdown(self) -> float:
        """Calculate maximum drawdown percentage"""
        if not self.equity_curve:
            return 0.0

        peak = self.equity_curve[0]
        max_dd = 0.0

        for equity in self.equity_curve:
            if equity > peak:
                peak = equity
            dd = ((peak - equity) / peak) * 100
            max_dd = max(max_dd, dd)

        return max_dd

    def _calculate_sharpe_ratio(self) -> float:
        """Calculate Sharpe ratio (simplified)"""
        if len(self.equity_curve) < 2:
            return 0.0

        returns = []
        for i in range(1, len(self.equity_curve)):
            ret = (self.equity_curve[i] - self.equity_curve[i-1]) / self.equity_curve[i-1]
            returns.append(ret)

        if not returns:
            return 0.0

        avg_return = sum(returns) / len(returns)
        std_return = (sum((r - avg_return)**2 for r in returns) / len(returns)) ** 0.5

        if std_return == 0:
            return 0.0

        # Annualized (assuming hourly bars)
        sharpe = (avg_return / std_return) * (365 * 24) ** 0.5
        return sharpe


def save_equity_chart(result: BacktestResult, output_path: str, pair: str):
    """
    Save equity curve chart as PNG.

    Requires matplotlib (optional dependency).
    """
    try:
        import matplotlib
        matplotlib.use('Agg')  # Non-interactive backend
        import matplotlib.pyplot as plt
    except ImportError:
        logging.warning("matplotlib not installed, skipping chart generation")
        logging.info("Install with: pip install matplotlib")
        return False

    try:
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))

        # Equity curve
        ax1.plot(result.equity_curve, linewidth=2, color='#2E86AB')
        ax1.axhline(y=result.initial_equity, color='gray', linestyle='--', alpha=0.5)
        ax1.set_title(f'Equity Curve - {pair}', fontsize=14, fontweight='bold')
        ax1.set_xlabel('Bar')
        ax1.set_ylabel('Equity ($)')
        ax1.grid(True, alpha=0.3)
        ax1.set_ylim(bottom=0)

        # Add return annotation
        return_text = f'{result.total_return_pct:+.2f}%'
        ax1.text(
            0.02, 0.98, return_text,
            transform=ax1.transAxes,
            fontsize=12,
            verticalalignment='top',
            bbox=dict(boxstyle='round', facecolor='white', alpha=0.8)
        )

        # Trade markers
        buy_trades = [t for t in result.trades if t.action == 'buy']
        sell_trades = [t for t in result.trades if t.action == 'sell']

        if buy_trades:
            buy_indices = [i for i, t in enumerate(result.trades) if t.action == 'buy']
            buy_equities = [result.equity_curve[min(i, len(result.equity_curve)-1)] for i in buy_indices]
            ax1.scatter(buy_indices, buy_equities, marker='^', color='green', s=100, label='Buy', zorder=5)

        if sell_trades:
            sell_indices = [i for i, t in enumerate(result.trades) if t.action == 'sell']
            sell_equities = [result.equity_curve[min(i, len(result.equity_curve)-1)] for i in sell_indices]
            ax1.scatter(sell_indices, sell_equities, marker='v', color='red', s=100, label='Sell', zorder=5)

        ax1.legend()

        # Metrics table
        metrics_text = f"""
Backtest Metrics
{'='*40}
Initial Equity: ${result.initial_equity:,.2f}
Final Equity:   ${result.final_equity:,.2f}
Total Return:   {result.total_return_pct:+.2f}%
{'='*40}
Total Trades:   {result.num_trades}
Winning:        {result.winning_trades}
Losing:         {result.losing_trades}
Win Rate:       {result.win_rate:.1f}%
{'='*40}
Max Drawdown:   {result.max_drawdown_pct:.2f}%
Sharpe Ratio:   {result.sharpe_ratio:.2f}
"""

        ax2.text(0.1, 0.5, metrics_text, fontsize=10, family='monospace',
                 verticalalignment='center', transform=ax2.transAxes)
        ax2.axis('off')

        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()

        logging.info(f"✅ Equity chart saved to: {output_path}")
        return True

    except Exception as e:
        logging.error(f"Failed to save chart: {e}")
        return False


def load_csv_data(file_path: str) -> List[OHLCV]:
    """
    Load OHLCV data from CSV file.

    Expected CSV format:
    timestamp,open,high,low,close,volume
    """
    import csv

    data = []
    with open(file_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            data.append(OHLCV(
                timestamp=float(row['timestamp']),
                open=float(row['open']),
                high=float(row['high']),
                low=float(row['low']),
                close=float(row['close']),
                volume=float(row['volume'])
            ))

    return data


def main(args):
    """Main execution function"""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger(__name__)

    logger.info("=" * 70)
    logger.info("BACKTEST ONE PAIR EXAMPLE")
    logger.info("=" * 70)
    logger.info(f"Pair: {args.pair}")
    logger.info(f"Strategy: {args.strategy}")
    logger.info(f"Initial Equity: ${args.equity:,.2f}")
    logger.info("=" * 70)

    # Load or generate data
    if args.generate_data:
        logger.info(f"Generating {args.bars} fake OHLCV bars...")
        data = DataGenerator.generate_ohlcv(
            num_bars=args.bars,
            base_price=args.base_price,
            volatility=args.volatility
        )
        logger.info(f"✅ Generated {len(data)} bars")
    elif args.data:
        logger.info(f"Loading data from {args.data}...")
        try:
            data = load_csv_data(args.data)
            logger.info(f"✅ Loaded {len(data)} bars from CSV")
        except Exception as e:
            logger.error(f"❌ Failed to load CSV: {e}")
            return 1
    else:
        logger.error("❌ Must specify --data or --generate-data")
        return 1

    # Initialize strategy
    logger.info(f"\nInitializing {args.strategy} strategy...")
    if args.strategy == 'ma_crossover':
        strategy = SimpleStrategy(fast_period=args.fast_ma, slow_period=args.slow_ma)
        logger.info(f"  Fast MA: {args.fast_ma}, Slow MA: {args.slow_ma}")
    else:
        logger.error(f"Unknown strategy: {args.strategy}")
        return 1

    # Initialize backtester
    backtester = SimpleBacktester(
        initial_equity=args.equity,
        trade_size=args.trade_size,
        commission_pct=args.commission / 10000  # bps to decimal
    )

    # Run backtest
    logger.info("\n" + "=" * 70)
    logger.info("RUNNING BACKTEST")
    logger.info("=" * 70)

    result = backtester.run(data, strategy)

    # Print results
    logger.info("\n" + "=" * 70)
    logger.info("BACKTEST RESULTS")
    logger.info("=" * 70)
    logger.info(f"Initial Equity:  ${result.initial_equity:,.2f}")
    logger.info(f"Final Equity:    ${result.final_equity:,.2f}")
    logger.info(f"Total Return:    {result.total_return_pct:+.2f}%")
    logger.info("=" * 70)
    logger.info(f"Total Trades:    {result.num_trades}")
    logger.info(f"Winning Trades:  {result.winning_trades}")
    logger.info(f"Losing Trades:   {result.losing_trades}")
    logger.info(f"Win Rate:        {result.win_rate:.1f}%")
    logger.info("=" * 70)
    logger.info(f"Max Drawdown:    {result.max_drawdown_pct:.2f}%")
    logger.info(f"Sharpe Ratio:    {result.sharpe_ratio:.2f}")
    logger.info("=" * 70)

    # Save equity chart
    if args.output:
        output_path = args.output
    else:
        output_path = f"backtest_{args.pair.replace('/', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"

    logger.info(f"\nSaving equity chart to {output_path}...")
    save_equity_chart(result, output_path, args.pair)

    logger.info("\n✅ Backtest example completed successfully\n")
    return 0


def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description='Run backtest on a single trading pair',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate fake data and backtest
  python -m agents.examples.backtest_one_pair --generate-data --bars 1000

  # Load from CSV
  python -m agents.examples.backtest_one_pair --data data/BTC_USD_1h.csv

  # Custom strategy parameters
  python -m agents.examples.backtest_one_pair --generate-data --fast-ma 5 --slow-ma 20

  # Save chart to specific location
  python -m agents.examples.backtest_one_pair --generate-data --output my_backtest.png
        """
    )

    # Data source
    data_group = parser.add_mutually_exclusive_group()
    data_group.add_argument(
        '--data',
        type=str,
        help='Path to CSV file with OHLCV data'
    )
    data_group.add_argument(
        '--generate-data',
        action='store_true',
        help='Generate fake OHLCV data'
    )

    # Data generation options
    parser.add_argument(
        '--bars',
        type=int,
        default=1000,
        help='Number of bars to generate (default: 1000)'
    )
    parser.add_argument(
        '--base-price',
        type=float,
        default=50000.0,
        help='Starting price for generated data (default: 50000)'
    )
    parser.add_argument(
        '--volatility',
        type=float,
        default=0.02,
        help='Volatility for generated data (default: 0.02)'
    )

    # Trading parameters
    parser.add_argument(
        '--pair',
        type=str,
        default='BTC/USD',
        help='Trading pair (default: BTC/USD)'
    )
    parser.add_argument(
        '--equity',
        type=float,
        default=10000.0,
        help='Initial equity (default: 10000)'
    )
    parser.add_argument(
        '--trade-size',
        type=float,
        default=1.0,
        help='Trade size (default: 1.0)'
    )
    parser.add_argument(
        '--commission',
        type=float,
        default=10.0,
        help='Commission in basis points (default: 10 bps)'
    )

    # Strategy parameters
    parser.add_argument(
        '--strategy',
        type=str,
        default='ma_crossover',
        choices=['ma_crossover'],
        help='Trading strategy (default: ma_crossover)'
    )
    parser.add_argument(
        '--fast-ma',
        type=int,
        default=10,
        help='Fast MA period (default: 10)'
    )
    parser.add_argument(
        '--slow-ma',
        type=int,
        default=30,
        help='Slow MA period (default: 30)'
    )

    # Output
    parser.add_argument(
        '--output',
        type=str,
        help='Output path for equity chart (default: auto-generated)'
    )

    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()
    sys.exit(main(args))
