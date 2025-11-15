#!/usr/bin/env python3
"""
Simplified Paper Trading for bar_reaction_5m Strategy

This script runs the bar_reaction_5m strategy in paper trading mode without
full infrastructure dependencies. It generates signals based on live market
data and tracks performance metrics.

Usage:
    python out/run_bar_reaction_paper.py

Requirements:
    - .env.paper configured
    - Redis connection working
    - bar_reaction_5m.yaml strategy config
"""

import os
import sys
import time
import logging
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv
import pandas as pd
import redis
import yaml
import ccxt

# Load paper trading environment
load_dotenv('.env.paper')

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f'logs/paper_trial_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    ]
)
logger = logging.getLogger(__name__)

# Create logs directory
Path('logs').mkdir(exist_ok=True)

class SimpleBarReactionPaperTrader:
    """Simple paper trader for bar_reaction_5m strategy"""

    def __init__(self):
        # Load configuration
        self.redis_url = os.getenv('REDIS_URL')
        self.ca_cert = os.getenv('REDIS_CA_CERT')
        self.symbol = 'BTC/USD'
        self.timeframe = '5m'
        self.initial_capital = float(os.getenv('INITIAL_EQUITY_USD', '10000.0'))

        # Initialize equity
        self.equity = self.initial_capital
        self.trades = []
        self.current_position = None

        # Load strategy config
        config_path = Path(os.getenv('STRATEGY_CONFIG', 'config/bar_reaction_5m.yaml'))
        with open(config_path) as f:
            self.strategy_config = yaml.safe_load(f)['strategy']

        logger.info(f"Loaded strategy config from {config_path}")
        logger.info(f"Trigger thresholds: {self.strategy_config['trigger_bps_up']} bps")
        logger.info(f"Risk per trade: {self.strategy_config['risk_per_trade_pct']}%")

        # Initialize Redis client
        try:
            self.redis_client = redis.from_url(
                self.redis_url,
                ssl_ca_certs=self.ca_cert,
                ssl_cert_reqs='required',
                decode_responses=True
            )
            self.redis_client.ping()
            logger.info("Redis connection successful")
        except Exception as e:
            logger.error(f"Redis connection failed: {e}")
            sys.exit(1)

        # Initialize exchange (for market data only, no trading)
        self.exchange = ccxt.kraken()
        logger.info("Initialized Kraken exchange for market data")

        # Performance tracking
        self.signals_generated = 0
        self.signals_taken = 0
        self.signals_skipped = 0

    def fetch_ohlcv(self, limit=200):
        """Fetch recent OHLCV data"""
        try:
            ohlcv = self.exchange.fetch_ohlcv(self.symbol, self.timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            logger.error(f"Failed to fetch OHLCV: {e}")
            return None

    def calculate_atr(self, df, window=14):
        """Calculate ATR"""
        high_low = df['high'] - df['low']
        high_close = abs(df['high'] - df['close'].shift())
        low_close = abs(df['low'] - df['close'].shift())
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = true_range.rolling(window).mean()
        return atr

    def check_signal(self, df):
        """Check if bar_reaction_5m signal is triggered"""
        if len(df) < 50:
            return None, None

        # Get latest bar
        latest = df.iloc[-1]
        close = latest['close']

        # Calculate move from open to close in bps
        move_bps = ((close - latest['open']) / latest['open']) * 10000

        # Calculate ATR
        atr = self.calculate_atr(df).iloc[-1]
        atr_pct = (atr / close) * 100

        # Check volatility gates
        min_atr = self.strategy_config['min_atr_pct']
        max_atr = self.strategy_config['max_atr_pct']

        if atr_pct < min_atr or atr_pct > max_atr:
            return None, None

        # Check trigger thresholds
        trigger_up = self.strategy_config['trigger_bps_up']
        trigger_down = self.strategy_config['trigger_bps_down']

        if move_bps >= trigger_up:
            return 'LONG', {'price': close, 'move_bps': move_bps, 'atr_pct': atr_pct}
        elif move_bps <= -trigger_down:
            return 'SHORT', {'price': close, 'move_bps': move_bps, 'atr_pct': atr_pct}

        return None, None

    def execute_signal(self, signal_type, signal_data):
        """Execute paper trade"""
        self.signals_generated += 1

        # Check if we can trade
        if self.current_position is not None:
            logger.info(f"Signal {signal_type} skipped - already in position")
            self.signals_skipped += 1
            return

        # Calculate position size
        risk_pct = self.strategy_config['risk_per_trade_pct']
        position_size_usd = self.equity * (risk_pct / 100)

        # Check minimum position size
        if position_size_usd < 50:
            logger.info(f"Signal {signal_type} skipped - position too small (${position_size_usd:.2f})")
            self.signals_skipped += 1
            return

        # Open position
        price = signal_data['price']
        self.current_position = {
            'type': signal_type,
            'entry_price': price,
            'entry_time': datetime.now(),
            'size_usd': position_size_usd,
            'move_bps': signal_data['move_bps'],
            'atr_pct': signal_data['atr_pct']
        }

        self.signals_taken += 1

        logger.info(f"✅ OPENED {signal_type} POSITION")
        logger.info(f"   Entry Price: ${price:.2f}")
        logger.info(f"   Position Size: ${position_size_usd:.2f}")
        logger.info(f"   Move: {signal_data['move_bps']:+.2f} bps")
        logger.info(f"   ATR: {signal_data['atr_pct']:.3f}%")

        # Publish to Redis
        try:
            self.redis_client.xadd(
                'signals:paper',
                {
                    'timestamp': datetime.now().isoformat(),
                    'symbol': self.symbol,
                    'signal': signal_type,
                    'price': price,
                    'size_usd': position_size_usd,
                    'move_bps': signal_data['move_bps'],
                    'atr_pct': signal_data['atr_pct']
                }
            )
        except Exception as e:
            logger.warning(f"Failed to publish to Redis: {e}")

    def check_exit(self, df):
        """Check if position should be closed"""
        if self.current_position is None:
            return

        latest_price = df.iloc[-1]['close']
        entry_price = self.current_position['entry_price']
        position_type = self.current_position['type']

        # Calculate current P&L
        if position_type == 'LONG':
            pnl_pct = ((latest_price - entry_price) / entry_price) * 100
        else:  # SHORT
            pnl_pct = ((entry_price - latest_price) / entry_price) * 100

        # Simple exit logic: close after 5 bars or 1% profit/loss
        duration = datetime.now() - self.current_position['entry_time']

        should_close = False
        reason = None

        if pnl_pct >= 1.0:
            should_close = True
            reason = "take_profit"
        elif pnl_pct <= -1.0:
            should_close = True
            reason = "stop_loss"
        elif duration > timedelta(minutes=30):
            should_close = True
            reason = "time_exit"

        if should_close:
            # Calculate P&L
            pnl_usd = self.current_position['size_usd'] * (pnl_pct / 100)
            self.equity += pnl_usd

            trade = {
                'entry_time': self.current_position['entry_time'],
                'exit_time': datetime.now(),
                'type': position_type,
                'entry_price': entry_price,
                'exit_price': latest_price,
                'size_usd': self.current_position['size_usd'],
                'pnl_usd': pnl_usd,
                'pnl_pct': pnl_pct,
                'reason': reason,
                'duration_minutes': duration.total_seconds() / 60
            }
            self.trades.append(trade)

            logger.info(f"❌ CLOSED {position_type} POSITION ({reason})")
            logger.info(f"   Exit Price: ${latest_price:.2f}")
            logger.info(f"   P&L: ${pnl_usd:+.2f} ({pnl_pct:+.2f}%)")
            logger.info(f"   Duration: {duration.total_seconds()/60:.1f} minutes")
            logger.info(f"   New Equity: ${self.equity:.2f}")

            self.current_position = None

            # Publish to Redis
            try:
                self.redis_client.xadd(
                    'trades:paper',
                    {
                        'timestamp': datetime.now().isoformat(),
                        'symbol': self.symbol,
                        'type': position_type,
                        'entry_price': entry_price,
                        'exit_price': latest_price,
                        'pnl_usd': pnl_usd,
                        'pnl_pct': pnl_pct,
                        'reason': reason
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to publish trade to Redis: {e}")

    def print_status(self):
        """Print current status"""
        total_return_pct = ((self.equity - self.initial_capital) / self.initial_capital) * 100

        logger.info("=" * 80)
        logger.info("PAPER TRADING STATUS")
        logger.info("=" * 80)
        logger.info(f"Initial Capital: ${self.initial_capital:.2f}")
        logger.info(f"Current Equity: ${self.equity:.2f}")
        logger.info(f"Total Return: {total_return_pct:+.2f}%")
        logger.info(f"Signals Generated: {self.signals_generated}")
        logger.info(f"Signals Taken: {self.signals_taken}")
        logger.info(f"Signals Skipped: {self.signals_skipped}")
        logger.info(f"Trades Completed: {len(self.trades)}")

        if len(self.trades) > 0:
            winning_trades = sum(1 for t in self.trades if t['pnl_usd'] > 0)
            win_rate = (winning_trades / len(self.trades)) * 100
            avg_pnl = sum(t['pnl_usd'] for t in self.trades) / len(self.trades)

            logger.info(f"Win Rate: {win_rate:.1f}%")
            logger.info(f"Avg P&L per trade: ${avg_pnl:+.2f}")

        if self.current_position:
            logger.info(f"Current Position: {self.current_position['type']} @ ${self.current_position['entry_price']:.2f}")
        else:
            logger.info("Current Position: None")

        logger.info("=" * 80)

    def run(self):
        """Main trading loop"""
        logger.info("\n" + "=" * 80)
        logger.info("STARTING PAPER TRADING - bar_reaction_5m Strategy")
        logger.info("=" * 80)
        logger.info(f"Symbol: {self.symbol}")
        logger.info(f"Timeframe: {self.timeframe}")
        logger.info(f"Initial Capital: ${self.initial_capital:.2f}")
        logger.info("=" * 80 + "\n")

        iteration = 0
        while True:
            try:
                iteration += 1

                # Fetch latest market data
                df = self.fetch_ohlcv()
                if df is None:
                    time.sleep(60)
                    continue

                # Check for exit if in position
                self.check_exit(df)

                # Check for new signals
                signal_type, signal_data = self.check_signal(df)
                if signal_type and signal_data:
                    self.execute_signal(signal_type, signal_data)

                # Print status every 10 iterations
                if iteration % 10 == 0:
                    self.print_status()

                # Wait for next bar
                logger.info(f"Iteration {iteration} complete. Waiting 60s for next check...")
                time.sleep(60)

            except KeyboardInterrupt:
                logger.info("\n\nShutting down paper trading...")
                self.print_status()
                logger.info("\nPaper trading stopped by user")
                break
            except Exception as e:
                logger.error(f"Error in trading loop: {e}", exc_info=True)
                time.sleep(60)

if __name__ == "__main__":
    trader = SimpleBarReactionPaperTrader()
    trader.run()
