#!/usr/bin/env python3
"""
Scan and Publish Example

Demonstrates end-to-end signal generation workflow:
1. Generate fake market data stream (trades, candles)
2. Run signal analyst to detect trading opportunities
3. Publish signals to Redis in paper mode
4. Display results in real-time

This example runs entirely in paper mode and requires only:
- REDIS_URL in .env file
- conda environment: crypto-bot

Usage:
    conda activate crypto-bot
    python -m agents.examples.scan_and_publish --pair BTC/USD --duration 60

    # With custom parameters
    python -m agents.examples.scan_and_publish \
        --pair ETH/USD \
        --duration 120 \
        --interval 5 \
        --volatility 0.002

Author: Crypto AI Bot Team
License: MIT
"""

import asyncio
import argparse
import logging
import os
import sys
import time
import random
from pathlib import Path
from typing import List, Dict
from datetime import datetime, timedelta
from dataclasses import dataclass

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Load environment
from dotenv import load_dotenv
load_dotenv()


@dataclass
class FakeMarketData:
    """Fake market data for testing"""
    timestamp: float
    pair: str
    price: float
    volume: float
    side: str  # 'buy' or 'sell'
    bid: float
    ask: float


class FakeMarketDataGenerator:
    """
    Generate realistic fake market data for testing.

    Simulates price movements using random walk with drift and volatility.
    """

    def __init__(self, pair: str, base_price: float = 50000.0, volatility: float = 0.001):
        self.pair = pair
        self.current_price = base_price
        self.volatility = volatility
        self.logger = logging.getLogger(f"{__name__}.Generator")

    def generate_trade(self) -> FakeMarketData:
        """Generate a single fake trade"""
        # Random walk with small drift
        drift = random.uniform(-0.0001, 0.0001)
        shock = random.gauss(0, self.volatility)
        price_change = self.current_price * (drift + shock)

        self.current_price += price_change
        self.current_price = max(self.current_price, 100)  # Floor at $100

        # Generate trade data
        side = random.choice(['buy', 'sell'])
        volume = random.uniform(0.01, 1.0)  # 0.01 to 1.0 BTC

        # Bid-ask spread (typically 0.01-0.05%)
        spread_pct = random.uniform(0.0001, 0.0005)
        spread = self.current_price * spread_pct

        return FakeMarketData(
            timestamp=time.time(),
            pair=self.pair,
            price=self.current_price,
            volume=volume,
            side=side,
            bid=self.current_price - spread / 2,
            ask=self.current_price + spread / 2
        )

    def generate_candle(self, num_trades: int = 10) -> Dict:
        """Generate OHLCV candle from multiple trades"""
        trades = [self.generate_trade() for _ in range(num_trades)]
        prices = [t.price for t in trades]
        volumes = [t.volume for t in trades]

        return {
            'timestamp': trades[0].timestamp,
            'pair': self.pair,
            'open': prices[0],
            'high': max(prices),
            'low': min(prices),
            'close': prices[-1],
            'volume': sum(volumes),
            'num_trades': num_trades
        }


class SimpleSignalAnalyst:
    """
    Simplified signal analyst for demo purposes.

    Uses basic technical indicators:
    - RSI (Relative Strength Index)
    - Moving average crossover
    - Volume analysis
    """

    def __init__(self):
        self.price_history: List[float] = []
        self.volume_history: List[float] = []
        self.logger = logging.getLogger(f"{__name__}.Analyst")

    def add_data(self, price: float, volume: float):
        """Add new price/volume data point"""
        self.price_history.append(price)
        self.volume_history.append(volume)

        # Keep only last 50 data points
        if len(self.price_history) > 50:
            self.price_history.pop(0)
            self.volume_history.pop(0)

    def calculate_rsi(self, period: int = 14) -> float:
        """Calculate RSI indicator"""
        if len(self.price_history) < period + 1:
            return 50.0  # Neutral

        deltas = [self.price_history[i] - self.price_history[i-1]
                  for i in range(1, len(self.price_history))]

        gains = [d if d > 0 else 0 for d in deltas[-period:]]
        losses = [-d if d < 0 else 0 for d in deltas[-period:]]

        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def calculate_ma(self, period: int) -> float:
        """Calculate moving average"""
        if len(self.price_history) < period:
            return self.price_history[-1] if self.price_history else 0.0

        return sum(self.price_history[-period:]) / period

    def generate_signal(self, current_price: float) -> Dict:
        """
        Generate trading signal based on indicators.

        Returns:
            Signal dict with action, confidence, and indicators
        """
        if len(self.price_history) < 20:
            return {
                'action': 'wait',
                'confidence': 0.0,
                'reason': 'Insufficient data',
                'indicators': {}
            }

        # Calculate indicators
        rsi = self.calculate_rsi(14)
        ma_short = self.calculate_ma(5)
        ma_long = self.calculate_ma(20)

        # Volume analysis
        avg_volume = sum(self.volume_history[-10:]) / len(self.volume_history[-10:])
        current_volume = self.volume_history[-1]
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0

        # Signal logic
        signal = {
            'timestamp': time.time(),
            'price': current_price,
            'action': 'wait',
            'confidence': 0.0,
            'reason': '',
            'indicators': {
                'rsi': round(rsi, 2),
                'ma_short': round(ma_short, 2),
                'ma_long': round(ma_long, 2),
                'volume_ratio': round(volume_ratio, 2)
            }
        }

        # Buy signals
        if rsi < 30 and ma_short > ma_long and volume_ratio > 1.2:
            signal['action'] = 'buy'
            signal['confidence'] = 0.75
            signal['reason'] = 'RSI oversold + MA crossover + high volume'
        elif rsi < 35 and ma_short > ma_long:
            signal['action'] = 'buy'
            signal['confidence'] = 0.60
            signal['reason'] = 'RSI oversold + MA crossover'

        # Sell signals
        elif rsi > 70 and ma_short < ma_long and volume_ratio > 1.2:
            signal['action'] = 'sell'
            signal['confidence'] = 0.75
            signal['reason'] = 'RSI overbought + MA crossdown + high volume'
        elif rsi > 65 and ma_short < ma_long:
            signal['action'] = 'sell'
            signal['confidence'] = 0.60
            signal['reason'] = 'RSI overbought + MA crossdown'

        return signal


async def publish_to_redis(redis_client, signal: Dict, pair: str):
    """Publish signal to Redis stream (paper mode)"""
    try:
        stream_name = f"signals:paper:{pair.replace('/', '-')}"

        # Prepare signal data for Redis
        signal_data = {
            'timestamp': str(signal['timestamp']),
            'pair': pair,
            'action': signal['action'],
            'confidence': str(signal['confidence']),
            'reason': signal['reason'],
            'price': str(signal['price']),
            'mode': 'paper',
            **{f'indicator_{k}': str(v) for k, v in signal['indicators'].items()}
        }

        # Publish to Redis stream
        await redis_client.xadd(stream_name, signal_data, maxlen=1000)

        return True
    except Exception as e:
        logging.error(f"Failed to publish to Redis: {e}")
        return False


async def main(args):
    """Main execution function"""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger(__name__)

    logger.info("=" * 70)
    logger.info("SCAN AND PUBLISH EXAMPLE")
    logger.info("=" * 70)
    logger.info(f"Pair: {args.pair}")
    logger.info(f"Duration: {args.duration}s")
    logger.info(f"Interval: {args.interval}s")
    logger.info(f"Volatility: {args.volatility}")
    logger.info(f"Mode: PAPER (safe)")
    logger.info("=" * 70)

    # Verify environment
    redis_url = os.getenv('REDIS_URL')
    if not redis_url:
        logger.error("❌ REDIS_URL not set in environment")
        logger.error("Please set REDIS_URL in .env file")
        return 1

    # Connect to Redis
    try:
        import redis.asyncio as redis
        logger.info("Connecting to Redis Cloud...")
        redis_client = redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=10
        )
        await redis_client.ping()
        logger.info("✅ Connected to Redis Cloud")
    except Exception as e:
        logger.error(f"❌ Redis connection failed: {e}")
        logger.error("Please check REDIS_URL in .env file")
        return 1

    # Initialize components
    logger.info("\nInitializing components...")
    generator = FakeMarketDataGenerator(
        pair=args.pair,
        base_price=args.base_price,
        volatility=args.volatility
    )
    analyst = SimpleSignalAnalyst()

    # Statistics
    stats = {
        'trades_generated': 0,
        'signals_generated': 0,
        'buy_signals': 0,
        'sell_signals': 0,
        'published': 0
    }

    logger.info("✅ Components initialized")
    logger.info("\n" + "=" * 70)
    logger.info("STARTING MARKET DATA STREAM (Ctrl+C to stop)")
    logger.info("=" * 70 + "\n")

    try:
        start_time = time.time()

        while (time.time() - start_time) < args.duration:
            # Generate fake trade
            trade = generator.generate_trade()
            stats['trades_generated'] += 1

            # Add to analyst
            analyst.add_data(trade.price, trade.volume)

            # Generate signal every N trades
            if stats['trades_generated'] % 5 == 0:
                signal = analyst.generate_signal(trade.price)

                if signal['action'] != 'wait':
                    stats['signals_generated'] += 1

                    if signal['action'] == 'buy':
                        stats['buy_signals'] += 1
                    elif signal['action'] == 'sell':
                        stats['sell_signals'] += 1

                    # Log signal
                    logger.info(
                        f"🎯 SIGNAL: {signal['action'].upper()} "
                        f"@ ${trade.price:.2f} "
                        f"(confidence: {signal['confidence']:.0%})"
                    )
                    logger.info(f"   Reason: {signal['reason']}")
                    logger.info(
                        f"   RSI: {signal['indicators']['rsi']:.1f}, "
                        f"Vol Ratio: {signal['indicators']['volume_ratio']:.2f}"
                    )

                    # Publish to Redis
                    published = await publish_to_redis(redis_client, signal, args.pair)
                    if published:
                        stats['published'] += 1
                        logger.info("   ✅ Published to Redis\n")
                    else:
                        logger.warning("   ⚠️  Failed to publish\n")

            # Show periodic update
            if stats['trades_generated'] % 20 == 0:
                logger.info(
                    f"📊 Progress: {stats['trades_generated']} trades, "
                    f"{stats['signals_generated']} signals, "
                    f"Price: ${trade.price:.2f}"
                )

            await asyncio.sleep(args.interval)

    except KeyboardInterrupt:
        logger.info("\n\n⏹️  Stopped by user")

    finally:
        # Cleanup
        await redis_client.aclose()

        # Print summary
        logger.info("\n" + "=" * 70)
        logger.info("SUMMARY")
        logger.info("=" * 70)
        logger.info(f"Duration: {time.time() - start_time:.1f}s")
        logger.info(f"Trades generated: {stats['trades_generated']}")
        logger.info(f"Signals generated: {stats['signals_generated']}")
        logger.info(f"  - Buy signals: {stats['buy_signals']}")
        logger.info(f"  - Sell signals: {stats['sell_signals']}")
        logger.info(f"Published to Redis: {stats['published']}")
        logger.info(f"Final price: ${generator.current_price:.2f}")
        logger.info("=" * 70)
        logger.info("✅ Example completed successfully\n")

    return 0


def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description='Generate fake market data and publish trading signals',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run for 60 seconds on BTC/USD
  python -m agents.examples.scan_and_publish --pair BTC/USD --duration 60

  # Run with custom volatility
  python -m agents.examples.scan_and_publish --pair ETH/USD --volatility 0.003

  # Quick test (30 seconds)
  python -m agents.examples.scan_and_publish --duration 30 --interval 2
        """
    )

    parser.add_argument(
        '--pair',
        type=str,
        default='BTC/USD',
        help='Trading pair (default: BTC/USD)'
    )

    parser.add_argument(
        '--duration',
        type=int,
        default=60,
        help='Duration in seconds (default: 60)'
    )

    parser.add_argument(
        '--interval',
        type=float,
        default=3.0,
        help='Seconds between trades (default: 3.0)'
    )

    parser.add_argument(
        '--base-price',
        type=float,
        default=50000.0,
        help='Starting price (default: 50000.0)'
    )

    parser.add_argument(
        '--volatility',
        type=float,
        default=0.001,
        help='Price volatility (default: 0.001 = 0.1%%)'
    )

    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()
    sys.exit(asyncio.run(main(args)))
