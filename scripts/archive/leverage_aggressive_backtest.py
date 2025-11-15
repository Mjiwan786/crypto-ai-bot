#!/usr/bin/env python3
"""
Leverage Aggressive Crypto Trading Bot Backtest
Goal: Turn $500 into $2000 (300% return) using simulated leverage and high-frequency trading
"""

import argparse
import json
import logging
import math
import random
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1] if Path(__file__).parent.name == "scripts" else Path.cwd()
OUT_DIR = ROOT / "reports" / "leverage_aggressive_backtest"
OUT_DIR.mkdir(parents=True, exist_ok=True)

def fix_seeds(seed: int = 42):
    random.seed(seed)
    np.random.seed(seed)

@dataclass
class Signal:
    strategy: str
    exchange: str
    symbol: str
    side: str
    confidence: float
    size_quote_usd: float
    leverage: float = 1.0
    meta: Dict[str, Any] = field(default_factory=dict)

class LeveragePortfolio:
    def __init__(self, start_balance: float, max_leverage: float = 5.0):
        self.start_balance = float(start_balance)
        self.cash = float(start_balance)
        self.positions = {}
        self.equity = float(start_balance)
        self.max_equity = float(start_balance)
        self.history = []
        self.trades = []
        self.signals = []
        self.max_leverage = max_leverage
        self.max_drawdown = 0.0
        self.consecutive_losses = 0
        self.consecutive_wins = 0
        self.total_leverage_used = 0.0

    def mark(self, prices: Dict[str, float], timestamp):
        equity = self.cash
        total_leverage = 0.0
        
        for symbol, position in self.positions.items():
            if symbol in prices and position['qty'] != 0:
                position_value = position['qty'] * prices[symbol]
                equity += position_value
                total_leverage += position['leverage']
        
        self.equity = float(equity)
        self.max_equity = max(self.max_equity, self.equity)
        self.total_leverage_used = total_leverage
        
        # Calculate current drawdown
        current_dd = (self.equity / self.max_equity) - 1.0
        self.max_drawdown = min(self.max_drawdown, current_dd)
        
        self.history.append({
            "datetime": timestamp.isoformat(),
            "equity": self.equity,
            "cash": self.cash,
            "drawdown": current_dd,
            "leverage": total_leverage
        })

    def execute_trade(self, symbol: str, side: str, qty: float, price: float, fee: float, strategy: str, leverage: float = 1.0):
        if side == "buy":
            cost = qty * price + fee
            if cost <= self.cash:
                self.cash -= cost
                self.positions[symbol] = {
                    'qty': self.positions.get(symbol, {}).get('qty', 0) + qty,
                    'leverage': leverage,
                    'entry_price': price,
                    'entry_time': datetime.now()
                }
                self.trades.append({
                    "symbol": symbol,
                    "side": side,
                    "qty": qty,
                    "price": price,
                    "fee": fee,
                    "strategy": strategy,
                    "leverage": leverage,
                    "cost": cost
                })
                return True
        elif side == "sell":
            current_position = self.positions.get(symbol, {})
            current_qty = current_position.get('qty', 0)
            if current_qty >= qty:
                proceeds = qty * price - fee
                self.cash += proceeds
                self.positions[symbol]['qty'] -= qty
                
                # If position is closed, remove it
                if self.positions[symbol]['qty'] <= 0:
                    del self.positions[symbol]
                
                self.trades.append({
                    "symbol": symbol,
                    "side": side,
                    "qty": qty,
                    "price": price,
                    "fee": fee,
                    "strategy": strategy,
                    "leverage": current_position.get('leverage', 1.0),
                    "proceeds": proceeds
                })
                
                # Update win/loss streaks
                if len(self.trades) >= 2:
                    last_trade = self.trades[-2]
                    if last_trade['side'] == 'buy' and last_trade['symbol'] == symbol:
                        if proceeds > last_trade['cost']:
                            self.consecutive_wins += 1
                            self.consecutive_losses = 0
                        else:
                            self.consecutive_losses += 1
                            self.consecutive_wins = 0
                
                return True
        return False

class HighFrequencyStrategy:
    def __init__(self):
        self.name = "high_frequency"
        self.positions = {}
        self.last_signal_time = {}
        self.price_history = {}
    
    def calculate_indicators(self, df):
        """Calculate technical indicators"""
        df_copy = df.copy()
        
        # Moving averages
        df_copy['sma_5'] = df_copy['close'].rolling(5).mean()
        df_copy['sma_10'] = df_copy['close'].rolling(10).mean()
        df_copy['sma_20'] = df_copy['close'].rolling(20).mean()
        
        # EMAs
        df_copy['ema_8'] = df_copy['close'].ewm(span=8).mean()
        df_copy['ema_21'] = df_copy['close'].ewm(span=21).mean()
        
        # RSI
        delta = df_copy['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df_copy['rsi'] = 100 - (100 / (1 + rs))
        
        # MACD
        df_copy['ema_12'] = df_copy['close'].ewm(span=12).mean()
        df_copy['ema_26'] = df_copy['close'].ewm(span=26).mean()
        df_copy['macd'] = df_copy['ema_12'] - df_copy['ema_26']
        df_copy['macd_signal'] = df_copy['macd'].ewm(span=9).mean()
        
        # Bollinger Bands
        df_copy['bb_middle'] = df_copy['close'].rolling(20).mean()
        df_copy['bb_std'] = df_copy['close'].rolling(20).std()
        df_copy['bb_upper'] = df_copy['bb_middle'] + (df_copy['bb_std'] * 2)
        df_copy['bb_lower'] = df_copy['bb_middle'] - (df_copy['bb_std'] * 2)
        
        # Volume indicators
        df_copy['volume_sma'] = df_copy['volume'].rolling(10).mean()
        df_copy['volume_ratio'] = df_copy['volume'] / df_copy['volume_sma']
        
        # Price momentum
        df_copy['price_change_1'] = df_copy['close'].pct_change(1)
        df_copy['price_change_3'] = df_copy['close'].pct_change(3)
        df_copy['price_change_5'] = df_copy['close'].pct_change(5)
        
        return df_copy
    
    def generate_signal(self, df, context=None):
        if len(df) < 20:
            return None
        
        context = context or {}
        symbol = context.get('symbol', 'UNKNOWN')
        max_position = context.get('max_position', 1000.0)
        current_price = df.iloc[-1]['close']
        current_time = df.index[-1]
        
        # Avoid too frequent signals (minimum 30 minutes between signals)
        if symbol in self.last_signal_time:
            time_diff = (current_time - self.last_signal_time[symbol]).total_seconds()
            if time_diff < 1800:  # 30 minutes
                return None
        
        # Calculate indicators
        df_with_indicators = self.calculate_indicators(df)
        current = df_with_indicators.iloc[-1]
        prev = df_with_indicators.iloc[-2]
        
        # Store price history for trend analysis
        if symbol not in self.price_history:
            self.price_history[symbol] = []
        self.price_history[symbol].append(current_price)
        if len(self.price_history[symbol]) > 50:
            self.price_history[symbol] = self.price_history[symbol][-50:]
        
        # Check for exit conditions first
        if symbol in self.positions:
            position = self.positions[symbol]
            entry_price = position['entry_price']
            profit_pct = (current_price - entry_price) / entry_price
            
            # Dynamic take profit and stop loss based on leverage
            leverage = position.get('leverage', 1.0)
            base_tp = 0.02  # 2% base take profit
            base_sl = 0.01  # 1% base stop loss
            
            # Adjust based on leverage
            dynamic_tp = base_tp * leverage
            dynamic_sl = base_sl * leverage
            
            # Take profit
            if profit_pct >= dynamic_tp:
                del self.positions[symbol]
                self.last_signal_time[symbol] = current_time
                return Signal(
                    strategy=self.name,
                    exchange="kraken",
                    symbol=symbol,
                    side='sell',
                    confidence=0.9,
                    size_quote_usd=position['qty'] * current_price,
                    leverage=leverage,
                    meta={'signal_type': 'take_profit', 'profit_pct': profit_pct, 'dynamic_tp': dynamic_tp}
                )
            
            # Stop loss
            if profit_pct <= -dynamic_sl:
                del self.positions[symbol]
                self.last_signal_time[symbol] = current_time
                return Signal(
                    strategy=self.name,
                    exchange="kraken",
                    symbol=symbol,
                    side='sell',
                    confidence=0.9,
                    size_quote_usd=position['qty'] * current_price,
                    leverage=leverage,
                    meta={'signal_type': 'stop_loss', 'loss_pct': profit_pct, 'dynamic_sl': dynamic_sl}
                )
            
            # Exit on trend reversal
            if current['ema_8'] < current['ema_21'] or current['macd'] < current['macd_signal']:
                del self.positions[symbol]
                self.last_signal_time[symbol] = current_time
                return Signal(
                    strategy=self.name,
                    exchange="kraken",
                    symbol=symbol,
                    side='sell',
                    confidence=0.7,
                    size_quote_usd=position['qty'] * current_price,
                    leverage=leverage,
                    meta={'signal_type': 'trend_reversal'}
                )
        
        # Entry conditions (more aggressive)
        if symbol not in self.positions:
            # Multiple confirmation signals
            ema_bullish = current['ema_8'] > current['ema_21'] > current['sma_20']
            ema_rising = current['ema_8'] > prev['ema_8'] and current['ema_21'] > prev['ema_21']
            price_above_ema = current['close'] > current['ema_8']
            
            # RSI conditions
            rsi_ok = 30 < current['rsi'] < 75
            
            # MACD bullish
            macd_bullish = current['macd'] > current['macd_signal'] and current['macd'] > prev['macd']
            
            # Volume confirmation
            volume_ok = current['volume_ratio'] > 1.1
            
            # Price momentum
            momentum_ok = current['price_change_1'] > 0 and current['price_change_3'] > 0.005
            
            # Bollinger Band position
            bb_position = (current['close'] - current['bb_lower']) / (current['bb_upper'] - current['bb_lower'])
            bb_ok = 0.2 < bb_position < 0.8  # Not too close to bands
            
            # All conditions must be met
            if (ema_bullish and ema_rising and price_above_ema and 
                rsi_ok and macd_bullish and volume_ok and momentum_ok and bb_ok):
                
                # Dynamic leverage based on market conditions
                base_leverage = 2.0
                if current['rsi'] < 50 and current['price_change_3'] > 0.01:
                    leverage = min(4.0, base_leverage * 1.5)  # Higher leverage for strong momentum
                elif current['rsi'] < 60 and current['price_change_1'] > 0.005:
                    leverage = min(3.0, base_leverage * 1.2)  # Moderate leverage
                else:
                    leverage = base_leverage
                
                # Position sizing with leverage
                base_size = max_position * 0.6  # 60% base allocation
                leverage_multiplier = leverage
                position_size = base_size * leverage_multiplier
                position_size = min(position_size, max_position * 0.9)  # Max 90% of portfolio
                
                qty = position_size / current_price
                
                # Track the position
                self.positions[symbol] = {
                    'qty': qty,
                    'leverage': leverage,
                    'entry_price': current_price,
                    'entry_time': current_time
                }
                
                self.last_signal_time[symbol] = current_time
                
                return Signal(
                    strategy=self.name,
                    exchange="kraken",
                    symbol=symbol,
                    side='buy',
                    confidence=min(0.95, 0.7 + leverage * 0.1),
                    size_quote_usd=position_size,
                    leverage=leverage,
                    meta={
                        'signal_type': 'high_frequency_bullish',
                        'leverage': leverage,
                        'rsi': current['rsi'],
                        'macd': current['macd'],
                        'bb_position': bb_position
                    }
                )
        
        return None

class ScalpingStrategy:
    def __init__(self):
        self.name = "scalping"
        self.positions = {}
        self.last_signal_time = {}
    
    def calculate_rsi(self, prices, period=14):
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))
    
    def generate_signal(self, df, context=None):
        if len(df) < 14:
            return None
        
        context = context or {}
        symbol = context.get('symbol', 'UNKNOWN')
        max_position = context.get('max_position', 1000.0)
        current_price = df.iloc[-1]['close']
        current_time = df.index[-1]
        
        # Avoid too frequent signals (minimum 15 minutes between signals)
        if symbol in self.last_signal_time:
            time_diff = (current_time - self.last_signal_time[symbol]).total_seconds()
            if time_diff < 900:  # 15 minutes
                return None
        
        df_copy = df.copy()
        df_copy['rsi'] = self.calculate_rsi(df_copy['close'])
        df_copy['price_change'] = df_copy['close'].pct_change()
        df_copy['volume_ma'] = df_copy['volume'].rolling(10).mean()
        df_copy['volume_ratio'] = df_copy['volume'] / df_copy['volume_ma']
        
        current = df_copy.iloc[-1]
        
        # Check for exit conditions first
        if symbol in self.positions:
            position = self.positions[symbol]
            entry_price = position['entry_price']
            profit_pct = (current_price - entry_price) / entry_price
            
            # Quick take profit and stop loss for scalping
            leverage = position.get('leverage', 1.0)
            dynamic_tp = 0.01 * leverage  # 1% per leverage level
            dynamic_sl = 0.005 * leverage  # 0.5% per leverage level
            
            # Take profit
            if profit_pct >= dynamic_tp:
                del self.positions[symbol]
                self.last_signal_time[symbol] = current_time
                return Signal(
                    strategy=self.name,
                    exchange="kraken",
                    symbol=symbol,
                    side='sell',
                    confidence=0.9,
                    size_quote_usd=position['qty'] * current_price,
                    leverage=leverage,
                    meta={'signal_type': 'scalp_take_profit', 'profit_pct': profit_pct}
                )
            
            # Stop loss
            if profit_pct <= -dynamic_sl:
                del self.positions[symbol]
                self.last_signal_time[symbol] = current_time
                return Signal(
                    strategy=self.name,
                    exchange="kraken",
                    symbol=symbol,
                    side='sell',
                    confidence=0.9,
                    size_quote_usd=position['qty'] * current_price,
                    leverage=leverage,
                    meta={'signal_type': 'scalp_stop_loss', 'loss_pct': profit_pct}
                )
            
            # Time-based exit (max hold 2 hours)
            if hasattr(position, 'entry_time'):
                hold_seconds = (current_time - position['entry_time']).total_seconds()
                if hold_seconds > 7200:  # 2 hours
                    del self.positions[symbol]
                    self.last_signal_time[symbol] = current_time
                    return Signal(
                        strategy=self.name,
                        exchange="kraken",
                        symbol=symbol,
                        side='sell',
                        confidence=0.8,
                        size_quote_usd=position['qty'] * current_price,
                        leverage=leverage,
                        meta={'signal_type': 'time_exit', 'hold_seconds': hold_seconds}
                    )
        
        # Entry conditions (scalping)
        if symbol not in self.positions:
            # Scalping entry conditions
            rsi_oversold = 25 < current['rsi'] < 40
            price_momentum = current['price_change'] > 0.001
            volume_surge = current['volume_ratio'] > 1.3
            
            if rsi_oversold and price_momentum and volume_surge:
                # High leverage for scalping
                leverage = 3.0
                
                # Smaller position size for scalping
                position_size = max_position * 0.3  # 30% allocation
                position_size = position_size * leverage  # Apply leverage
                position_size = min(position_size, max_position * 0.8)  # Max 80% of portfolio
                
                qty = position_size / current_price
                
                # Track the position
                self.positions[symbol] = {
                    'qty': qty,
                    'leverage': leverage,
                    'entry_price': current_price,
                    'entry_time': current_time
                }
                
                self.last_signal_time[symbol] = current_time
                
                return Signal(
                    strategy=self.name,
                    exchange="kraken",
                    symbol=symbol,
                    side='buy',
                    confidence=0.8,
                    size_quote_usd=position_size,
                    leverage=leverage,
                    meta={'signal_type': 'scalp_buy', 'rsi': current['rsi']}
                )
        
        return None

def fetch_ohlcv_data(exchange_id: str, pair: str, timeframe: str, since_ms: Optional[int], limit: int):
    """Fetch OHLCV data from exchange"""
    try:
        import ccxt
        exchange = getattr(ccxt, exchange_id)()
        exchange.load_markets()
        
        # Handle Kraken BTC/USD mapping
        if pair not in exchange.symbols and pair == "BTC/USD" and "XBT/USD" in exchange.symbols:
            pair = "XBT/USD"
        
        data = exchange.fetch_ohlcv(pair, timeframe=timeframe, since=since_ms, limit=limit)
        df = pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("datetime", inplace=True, drop=True)
        return df[["open", "high", "low", "close", "volume"]]
        
    except Exception as e:
        logger.error(f"Failed to fetch data for {pair}: {e}")
        return pd.DataFrame()

def compute_performance_metrics(equity_series):
    """Calculate performance metrics"""
    if len(equity_series) < 2:
        return {}
    
    returns = equity_series.pct_change().fillna(0.0)
    total_return = (equity_series.iloc[-1] / equity_series.iloc[0]) - 1.0
    
    # Risk metrics
    if len(returns) > 1:
        volatility = returns.std() * math.sqrt(252 * 24)
        sharpe = returns.mean() / (volatility + 1e-9) * math.sqrt(252 * 24)
    else:
        volatility = 0
        sharpe = 0
    
    max_drawdown = (equity_series / equity_series.cummax() - 1.0).min()
    
    return {
        "total_return": round(total_return * 100, 2),
        "sharpe_ratio": round(sharpe, 3),
        "max_drawdown": round(max_drawdown * 100, 2),
        "final_equity": round(float(equity_series.iloc[-1]), 2),
        "start_value": round(float(equity_series.iloc[0]), 2),
        "volatility": round(volatility * 100, 2)
    }

def run_leverage_aggressive_backtest(args):
    """Main leverage aggressive backtest execution"""
    fix_seeds(42)
    
    # Initialize strategies
    strategies = [
        ("high_frequency", HighFrequencyStrategy()),
        ("scalping", ScalpingStrategy())
    ]
    
    # Fetch market data
    logger.info("📊 Fetching market data...")
    market_data = {}
    
    # Calculate date range
    if args.days > 0:
        since_ms = int((datetime.utcnow() - timedelta(days=args.days + 50)).timestamp() * 1000)
    else:
        since_ms = None
    
    for pair in args.pairs:
        df = fetch_ohlcv_data(args.exchange, pair, args.timeframe, since_ms, args.limit)
        if not df.empty:
            market_data[pair] = df
            logger.info(f"📈 Loaded {len(df)} candles for {pair}")
    
    if not market_data:
        logger.error("❌ No market data loaded")
        return
    
    # Align data
    common_index = None
    for df in market_data.values():
        common_index = df.index if common_index is None else common_index.intersection(df.index)
    
    # Limit to test period
    if args.days > 0:
        end_date = common_index[-1]
        start_date = end_date - pd.Timedelta(days=args.days)
        test_index = common_index[common_index >= start_date]
    else:
        test_index = common_index[-min(len(common_index), 1000):]
    
    logger.info(f"🔍 Leverage Aggressive Backtesting {len(test_index)} periods")
    
    # Initialize portfolio with leverage
    portfolio = LeveragePortfolio(args.start, max_leverage=5.0)
    
    # Aggressive trading parameters
    fee_rate = 0.0026  # Kraken fees
    slippage = 0.001   # 0.1% slippage
    min_confidence = 0.6  # Lower confidence threshold for more trades
    
    signal_count = 0
    trade_count = 0
    
    # Main backtest loop
    for i, timestamp in enumerate(test_index):
        if i % 100 == 0:
            logger.info(f"⚙️ Processing {i}/{len(test_index)} - Signals: {signal_count}, Trades: {trade_count}")
        
        # Get current prices
        current_prices = {}
        for symbol, df in market_data.items():
            if timestamp in df.index:
                current_prices[symbol] = float(df.at[timestamp, "close"])
        
        # Update portfolio valuation
        portfolio.mark(current_prices, timestamp)
        
        # Generate and process signals
        for strategy_name, strategy in strategies:
            for symbol, df in market_data.items():
                if timestamp not in df.index:
                    continue
                
                # Get data up to current time
                historical_data = df.loc[:timestamp]
                if len(historical_data) < 10:
                    continue
                
                # Generate signal
                context = {
                    "symbol": symbol,
                    "max_position": portfolio.equity * 0.5  # 50% max position per trade
                }
                
                try:
                    signal = strategy.generate_signal(historical_data, context)
                    if signal:
                        signal_count += 1
                        
                        # Store signal info
                        portfolio.signals.append({
                            "timestamp": timestamp.isoformat(),
                            "strategy": strategy_name,
                            "symbol": symbol,
                            "side": signal.side,
                            "confidence": signal.confidence,
                            "size_quote_usd": signal.size_quote_usd,
                            "leverage": signal.leverage
                        })
                        
                        # Execute trade
                        if signal.confidence >= min_confidence and symbol in current_prices:
                            price = current_prices[symbol]
                            
                            if signal.side == "buy":
                                adjusted_price = price * (1 + slippage)
                                qty = signal.size_quote_usd / adjusted_price
                                fee = signal.size_quote_usd * fee_rate
                                
                                if portfolio.execute_trade(symbol, "buy", qty, adjusted_price, fee, strategy_name, signal.leverage):
                                    trade_count += 1
                            
                            elif signal.side == "sell":
                                # Only sell if we have positions
                                if symbol in portfolio.positions and portfolio.positions[symbol]['qty'] > 0:
                                    adjusted_price = price * (1 - slippage)
                                    available_qty = portfolio.positions[symbol]['qty']
                                    sell_qty = min(signal.size_quote_usd / adjusted_price, available_qty)
                                    fee = sell_qty * adjusted_price * fee_rate
                                    
                                    if sell_qty > 0 and portfolio.execute_trade(symbol, "sell", sell_qty, adjusted_price, fee, strategy_name, signal.leverage):
                                        trade_count += 1
                                
                except Exception as e:
                    logger.debug(f"Strategy {strategy_name} error: {e}")
                    continue
    
    # Final portfolio valuation
    final_prices = {}
    for symbol, df in market_data.items():
        final_prices[symbol] = float(df.iloc[-1]["close"])
    portfolio.mark(final_prices, test_index[-1])
    
    logger.info(f"📊 Generated {signal_count} signals, executed {trade_count} trades")
    
    # Calculate results
    if portfolio.history:
        equity_df = pd.DataFrame(portfolio.history)
        equity_df["datetime"] = pd.to_datetime(equity_df["datetime"])
        equity_df.set_index("datetime", inplace=True)
        
        metrics = compute_performance_metrics(equity_df["equity"])
        metrics["total_trades"] = len(portfolio.trades)
        metrics["total_signals"] = len(portfolio.signals)
        metrics["signal_to_trade_ratio"] = round(trade_count / max(signal_count, 1), 3)
        metrics["max_drawdown"] = round(portfolio.max_drawdown * 100, 2)
        metrics["avg_leverage"] = round(portfolio.total_leverage_used / max(len(portfolio.history), 1), 2)
        
        # Calculate win rate
        if portfolio.trades:
            profitable_trades = 0
            for i in range(0, len(portfolio.trades), 2):  # Pair buy/sell trades
                if i + 1 < len(portfolio.trades):
                    buy_trade = portfolio.trades[i]
                    sell_trade = portfolio.trades[i + 1]
                    if (buy_trade['side'] == 'buy' and sell_trade['side'] == 'sell' and 
                        sell_trade['price'] > buy_trade['price']):
                        profitable_trades += 1
            
            metrics["win_rate"] = round(profitable_trades / max(len(portfolio.trades) // 2, 1) * 100, 1)
        else:
            metrics["win_rate"] = 0
        
        # Save files
        equity_df.to_csv(OUT_DIR / "leverage_equity_curve.csv")
        
        with open(OUT_DIR / "leverage_results.json", "w") as f:
            json.dump(metrics, f, indent=2)
        
        if portfolio.trades:
            trades_df = pd.DataFrame(portfolio.trades)
            trades_df.to_csv(OUT_DIR / "leverage_trades.csv", index=False)
        
        if portfolio.signals:
            signals_df = pd.DataFrame(portfolio.signals)
            signals_df.to_csv(OUT_DIR / "leverage_signals.csv", index=False)
        
        # Print results
        print("\n" + "="*60)
        print("⚡ LEVERAGE AGGRESSIVE BACKTEST RESULTS")
        print("="*60)
        print(f"💰 Total Return: {metrics.get('total_return', 0):.2f}%")
        print(f"📊 Sharpe Ratio: {metrics.get('sharpe_ratio', 0):.3f}")
        print(f"📉 Max Drawdown: {metrics.get('max_drawdown', 0):.2f}%")
        print(f"🎯 Win Rate: {metrics.get('win_rate', 0):.1f}%")
        print(f"🔄 Total Trades: {metrics.get('total_trades', 0)}")
        print(f"📡 Total Signals: {metrics.get('total_signals', 0)}")
        print(f"⚡ Signal→Trade Ratio: {metrics.get('signal_to_trade_ratio', 0):.3f}")
        print(f"💵 Final Equity: ${metrics.get('final_equity', 0):.2f}")
        print(f"📈 Volatility: {metrics.get('volatility', 0):.2f}%")
        print(f"🔗 Average Leverage: {metrics.get('avg_leverage', 0):.2f}x")
        
        # Goal achievement check
        target_return = 300.0  # 300% return goal
        if metrics.get('total_return', 0) >= target_return:
            print(f"🎉 GOAL ACHIEVED! Target: {target_return}%, Actual: {metrics.get('total_return', 0):.2f}%")
        else:
            print(f"🎯 Goal Progress: {metrics.get('total_return', 0):.2f}% / {target_return}% ({(metrics.get('total_return', 0)/target_return)*100:.1f}%)")
        
        print(f"\n📁 Results saved to: {OUT_DIR}")
        
        logger.info("✅ Leverage aggressive backtest completed successfully")
    else:
        logger.error("❌ No portfolio history generated")

def parse_args():
    parser = argparse.ArgumentParser(description="Leverage Aggressive Crypto Trading Bot Backtest")
    parser.add_argument("--exchange", default="kraken", help="Exchange ID")
    parser.add_argument("--pairs", nargs="+", default=["BTC/USD"], help="Trading pairs")
    parser.add_argument("--timeframe", default="1h", help="Timeframe")
    parser.add_argument("--days", type=int, default=180, help="Days to backtest")
    parser.add_argument("--limit", type=int, default=2000, help="Max candles")
    parser.add_argument("--start", type=float, default=500.0, help="Starting capital")
    parser.add_argument("--redis-url", help="Redis Cloud URL")
    return parser.parse_args()

if __name__ == "__main__":
    try:
        args = parse_args()
        run_leverage_aggressive_backtest(args)
    except KeyboardInterrupt:
        print("\nLeverage aggressive backtest interrupted")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Leverage aggressive backtest failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

