#!/usr/bin/env python3
"""
Smart Aggressive Crypto Trading Bot Backtest
Goal: Turn $500 into $2000 (300% return) with intelligent position sizing and risk management
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
OUT_DIR = ROOT / "reports" / "smart_aggressive_backtest"
OUT_DIR.mkdir(parents=True, exist_ok=True)

class SmartMarketRegimeDetector:
    """Smart market regime detection with trend strength analysis"""
    
    def __init__(self):
        self.regime_history = []
    
    def detect_regime(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Detect market regime with trend strength analysis"""
        if len(df) < 30:
            return {"regime": "trending", "confidence": 0.7, "volatility": "medium", "trend_strength": 0.5}
        
        df_copy = df.copy()
        df_copy['sma_10'] = df_copy['close'].rolling(10).mean()
        df_copy['sma_20'] = df_copy['close'].rolling(20).mean()
        df_copy['sma_50'] = df_copy['close'].rolling(50).mean()
        df_copy['atr'] = self.calculate_atr(df_copy, 14)
        df_copy['rsi'] = self.calculate_rsi(df_copy['close'], 14)
        df_copy['price_change'] = df_copy['close'].pct_change()
        
        current = df_copy.iloc[-1]
        
        # Multi-timeframe trend analysis
        short_trend = (current['sma_10'] - current['sma_20']) / current['sma_20']
        medium_trend = (current['sma_20'] - current['sma_50']) / current['sma_50']
        long_trend = (current['close'] - current['sma_50']) / current['sma_50']
        
        # Trend strength calculation
        trend_strength = (abs(short_trend) + abs(medium_trend) + abs(long_trend)) / 3
        
        # Volatility analysis
        atr_pct = current['atr'] / current['close']
        volatility = "high" if atr_pct > 0.03 else "low" if atr_pct < 0.01 else "medium"
        
        # Regime classification
        if trend_strength > 0.02 and short_trend > 0 and medium_trend > 0:
            regime = "strong_uptrend"
            confidence = min(0.95, trend_strength * 20)
        elif trend_strength > 0.02 and short_trend < 0 and medium_trend < 0:
            regime = "strong_downtrend"
            confidence = min(0.95, trend_strength * 20)
        elif trend_strength > 0.01:
            regime = "trending"
            confidence = min(0.8, trend_strength * 15)
        else:
            regime = "sideways"
            confidence = 0.6
        
        return {
            "regime": regime,
            "confidence": confidence,
            "volatility": volatility,
            "trend_strength": trend_strength,
            "short_trend": short_trend,
            "medium_trend": medium_trend,
            "long_trend": long_trend,
            "atr_pct": atr_pct,
            "rsi": current['rsi']
        }
    
    def calculate_atr(self, df: pd.DataFrame, period: int) -> pd.Series:
        """Calculate Average True Range"""
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        
        true_range = np.maximum(high_low, np.maximum(high_close, low_close))
        return true_range.rolling(period).mean()
    
    def calculate_rsi(self, prices: pd.Series, period: int) -> pd.Series:
        """Calculate RSI"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

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
    meta: Dict[str, Any] = field(default_factory=dict)

class SmartPortfolio:
    def __init__(self, start_balance: float):
        self.start_balance = float(start_balance)
        self.cash = float(start_balance)
        self.positions = {}
        self.equity = float(start_balance)
        self.max_equity = float(start_balance)
        self.history = []
        self.trades = []
        self.signals = []
        self.max_drawdown = 0.0
        self.consecutive_losses = 0
        self.consecutive_wins = 0

    def mark(self, prices: Dict[str, float], timestamp):
        equity = self.cash
        for symbol, qty in self.positions.items():
            if symbol in prices and qty != 0:
                equity += qty * prices[symbol]
        self.equity = float(equity)
        self.max_equity = max(self.max_equity, self.equity)
        
        # Calculate current drawdown
        current_dd = (self.equity / self.max_equity) - 1.0
        self.max_drawdown = min(self.max_drawdown, current_dd)
        
        self.history.append({
            "datetime": timestamp.isoformat(),
            "equity": self.equity,
            "cash": self.cash,
            "drawdown": current_dd
        })

    def execute_trade(self, symbol: str, side: str, qty: float, price: float, fee: float, strategy: str):
        if side == "buy":
            cost = qty * price + fee
            if cost <= self.cash:
                self.cash -= cost
                self.positions[symbol] = self.positions.get(symbol, 0) + qty
                self.trades.append({
                    "symbol": symbol,
                    "side": side,
                    "qty": qty,
                    "price": price,
                    "fee": fee,
                    "strategy": strategy,
                    "cost": cost
                })
                return True
        elif side == "sell":
            current_position = self.positions.get(symbol, 0)
            if current_position >= qty:
                proceeds = qty * price - fee
                self.cash += proceeds
                self.positions[symbol] -= qty
                self.trades.append({
                    "symbol": symbol,
                    "side": side,
                    "qty": qty,
                    "price": price,
                    "fee": fee,
                    "strategy": strategy,
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

class SmartTrendFollowingStrategy:
    def __init__(self):
        self.name = "smart_trend_following"
        self.positions = {}
        self.regime_detector = SmartMarketRegimeDetector()
        self.last_signal_time = {}
    
    def generate_signal(self, df, context=None):
        if len(df) < 30:
            return None
        
        context = context or {}
        symbol = context.get('symbol', 'UNKNOWN')
        max_position = context.get('max_position', 1000.0)
        current_price = df.iloc[-1]['close']
        current_time = df.index[-1]
        
        # Avoid too frequent signals
        if symbol in self.last_signal_time:
            time_diff = (current_time - self.last_signal_time[symbol]).total_seconds()
            if time_diff < 3600:  # 1 hour minimum between signals
                return None
        
        # Market regime detection
        regime = self.regime_detector.detect_regime(df)
        
        # Only trade in strong trends
        if regime['regime'] not in ['strong_uptrend', 'trending'] or regime['confidence'] < 0.7:
            return None
        
        # Calculate EMAs
        df_copy = df.copy()
        df_copy['ema_8'] = df_copy['close'].ewm(span=8).mean()
        df_copy['ema_21'] = df_copy['close'].ewm(span=21).mean()
        df_copy['ema_50'] = df_copy['close'].ewm(span=50).mean()
        df_copy['volume_ma'] = df_copy['volume'].rolling(20).mean()
        df_copy['atr'] = self.regime_detector.calculate_atr(df_copy, 14)
        df_copy['rsi'] = self.regime_detector.calculate_rsi(df_copy['close'], 14)
        
        current = df_copy.iloc[-1]
        prev = df_copy.iloc[-2]
        
        # Check for exit conditions first
        if symbol in self.positions:
            position = self.positions[symbol]
            entry_price = position['entry_price']
            profit_pct = (current_price - entry_price) / entry_price
            
            # Smart take profit and stop loss based on trend strength
            atr_pct = current['atr'] / current_price
            trend_strength = regime['trend_strength']
            
            # Dynamic targets based on trend strength
            if trend_strength > 0.03:  # Strong trend
                dynamic_tp = max(0.08, min(0.20, atr_pct * 4))  # 8-20%
                dynamic_sl = max(0.03, min(0.08, atr_pct * 2))  # 3-8%
            else:  # Moderate trend
                dynamic_tp = max(0.05, min(0.12, atr_pct * 3))  # 5-12%
                dynamic_sl = max(0.02, min(0.06, atr_pct * 1.5))  # 2-6%
            
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
                    meta={'signal_type': 'stop_loss', 'loss_pct': profit_pct, 'dynamic_sl': dynamic_sl}
                )
            
            # Exit on trend reversal
            if current['ema_8'] < current['ema_21'] or regime['regime'] == 'strong_downtrend':
                del self.positions[symbol]
                self.last_signal_time[symbol] = current_time
                return Signal(
                    strategy=self.name,
                    exchange="kraken",
                    symbol=symbol,
                    side='sell',
                    confidence=0.7,
                    size_quote_usd=position['qty'] * current_price,
                    meta={'signal_type': 'trend_reversal'}
                )
        
        # Entry conditions (only if no position)
        if symbol not in self.positions:
            # Multiple confirmation signals
            ema_alignment = current['ema_8'] > current['ema_21'] > current['ema_50']
            ema_8_rising = current['ema_8'] > prev['ema_8']
            ema_21_rising = current['ema_21'] > prev['ema_21']
            price_above_ema8 = current['close'] > current['ema_8']
            volume_confirmation = current['volume'] > current['volume_ma'] * 1.2
            
            # RSI not overbought
            rsi_ok = 30 < current['rsi'] < 75
            
            # Price momentum
            price_momentum = (current['close'] - prev['close']) / prev['close'] > 0.001
            
            # All conditions must be met
            if (ema_alignment and ema_8_rising and ema_21_rising and 
                price_above_ema8 and volume_confirmation and rsi_ok and price_momentum):
                
                # Smart position sizing based on trend strength and confidence
                base_size = max_position * 0.4  # 40% base allocation
                trend_multiplier = min(2.5, regime['trend_strength'] * 50)  # Scale with trend strength
                confidence_multiplier = regime['confidence']  # Scale with confidence
                
                position_size = base_size * trend_multiplier * confidence_multiplier
                position_size = min(position_size, max_position * 0.8)  # Max 80% of portfolio
                
                qty = position_size / current_price
                
                # Track the position
                self.positions[symbol] = {
                    'entry_price': current_price,
                    'entry_time': current_time,
                    'qty': qty
                }
                
                self.last_signal_time[symbol] = current_time
                
                return Signal(
                    strategy=self.name,
                    exchange="kraken",
                    symbol=symbol,
                    side='buy',
                    confidence=regime['confidence'],
                    size_quote_usd=position_size,
                    meta={
                        'signal_type': 'trend_bullish',
                        'trend_strength': regime['trend_strength'],
                        'regime': regime['regime'],
                        'confidence': regime['confidence']
                    }
                )
        
        return None

class SmartMomentumStrategy:
    def __init__(self):
        self.name = "smart_momentum"
        self.positions = {}
        self.regime_detector = SmartMarketRegimeDetector()
        self.last_signal_time = {}
    
    def calculate_rsi(self, prices, period=14):
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))
    
    def generate_signal(self, df, context=None):
        if len(df) < 20:
            return None
        
        context = context or {}
        symbol = context.get('symbol', 'UNKNOWN')
        max_position = context.get('max_position', 1000.0)
        current_price = df.iloc[-1]['close']
        current_time = df.index[-1]
        
        # Avoid too frequent signals
        if symbol in self.last_signal_time:
            time_diff = (current_time - self.last_signal_time[symbol]).total_seconds()
            if time_diff < 7200:  # 2 hours minimum between signals
                return None
        
        # Market regime detection
        regime = self.regime_detector.detect_regime(df)
        
        # Only trade in trending markets
        if regime['regime'] not in ['strong_uptrend', 'trending'] or regime['confidence'] < 0.6:
            return None
        
        df_copy = df.copy()
        df_copy['rsi'] = self.calculate_rsi(df_copy['close'])
        df_copy['price_change_3'] = df_copy['close'].pct_change(3)
        df_copy['price_change_7'] = df_copy['close'].pct_change(7)
        df_copy['price_change_14'] = df_copy['close'].pct_change(14)
        df_copy['volume_ratio'] = df_copy['volume'] / df_copy['volume'].rolling(20).mean()
        
        current = df_copy.iloc[-1]
        
        # Check for exit conditions first
        if symbol in self.positions:
            position = self.positions[symbol]
            entry_price = position['entry_price']
            profit_pct = (current_price - entry_price) / entry_price
            
            # Smart take profit and stop loss
            if profit_pct >= 0.12:  # 12% take profit
                del self.positions[symbol]
                self.last_signal_time[symbol] = current_time
                return Signal(
                    strategy=self.name,
                    exchange="kraken",
                    symbol=symbol,
                    side='sell',
                    confidence=0.9,
                    size_quote_usd=position['qty'] * current_price,
                    meta={'signal_type': 'take_profit', 'profit_pct': profit_pct}
                )
            
            if profit_pct <= -0.06:  # 6% stop loss
                del self.positions[symbol]
                self.last_signal_time[symbol] = current_time
                return Signal(
                    strategy=self.name,
                    exchange="kraken",
                    symbol=symbol,
                    side='sell',
                    confidence=0.9,
                    size_quote_usd=position['qty'] * current_price,
                    meta={'signal_type': 'stop_loss', 'loss_pct': profit_pct}
                )
            
            # Exit on momentum reversal
            if current['rsi'] > 80 or current['price_change_3'] < -0.03:
                del self.positions[symbol]
                self.last_signal_time[symbol] = current_time
                return Signal(
                    strategy=self.name,
                    exchange="kraken",
                    symbol=symbol,
                    side='sell',
                    confidence=0.8,
                    size_quote_usd=position['qty'] * current_price,
                    meta={'signal_type': 'momentum_reversal', 'rsi': current['rsi']}
                )
        
        # Entry conditions (more selective)
        if symbol not in self.positions:
            # Multiple momentum confirmations
            rsi_ok = 40 < current['rsi'] < 70  # Not overbought or oversold
            momentum_3d = current['price_change_3'] > 0.02  # Strong 3-day momentum
            momentum_7d = current['price_change_7'] > 0.03  # Strong 7-day momentum
            momentum_14d = current['price_change_14'] > 0.05  # Strong 14-day momentum
            volume_confirmation = current['volume_ratio'] > 1.5  # High volume
            
            # All conditions must be met
            if (rsi_ok and momentum_3d and momentum_7d and momentum_14d and volume_confirmation):
                
                # Smart position sizing
                base_size = max_position * 0.3  # 30% base allocation
                momentum_multiplier = min(2.0, current['price_change_7'] * 20)  # Scale with momentum
                confidence_multiplier = regime['confidence']
                
                position_size = base_size * momentum_multiplier * confidence_multiplier
                position_size = min(position_size, max_position * 0.6)  # Max 60% of portfolio
                
                qty = position_size / current_price
                
                # Track the position
                self.positions[symbol] = {
                    'entry_price': current_price,
                    'entry_time': current_time,
                    'qty': qty
                }
                
                self.last_signal_time[symbol] = current_time
                
                return Signal(
                    strategy=self.name,
                    exchange="kraken",
                    symbol=symbol,
                    side='buy',
                    confidence=min(0.9, regime['confidence'] + 0.1),
                    size_quote_usd=position_size,
                    meta={
                        'signal_type': 'momentum_bullish',
                        'rsi': current['rsi'],
                        'momentum_7d': current['price_change_7'],
                        'regime': regime['regime']
                    }
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

def run_smart_aggressive_backtest(args):
    """Main smart aggressive backtest execution"""
    fix_seeds(42)
    
    # Initialize smart strategies
    strategies = [
        ("smart_trend_following", SmartTrendFollowingStrategy()),
        ("smart_momentum", SmartMomentumStrategy())
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
    
    logger.info(f"🔍 Smart Aggressive Backtesting {len(test_index)} periods")
    
    # Initialize portfolio
    portfolio = SmartPortfolio(args.start)
    
    # Smart trading parameters
    fee_rate = 0.0026  # Kraken fees
    slippage = 0.001   # 0.1% slippage
    min_confidence = 0.7  # Higher confidence threshold for quality trades
    
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
                if len(historical_data) < 20:
                    continue
                
                # Generate signal
                context = {
                    "symbol": symbol,
                    "max_position": portfolio.equity * 0.4  # 40% max position per trade
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
                            "size_quote_usd": signal.size_quote_usd
                        })
                        
                        # Execute trade with higher confidence threshold
                        if signal.confidence >= min_confidence and symbol in current_prices:
                            price = current_prices[symbol]
                            
                            if signal.side == "buy":
                                adjusted_price = price * (1 + slippage)
                                qty = signal.size_quote_usd / adjusted_price
                                fee = signal.size_quote_usd * fee_rate
                                
                                if portfolio.execute_trade(symbol, "buy", qty, adjusted_price, fee, strategy_name):
                                    trade_count += 1
                            
                            elif signal.side == "sell":
                                # Only sell if we have positions
                                if symbol in portfolio.positions and portfolio.positions[symbol] > 0:
                                    adjusted_price = price * (1 - slippage)
                                    available_qty = portfolio.positions[symbol]
                                    sell_qty = min(signal.size_quote_usd / adjusted_price, available_qty)
                                    fee = sell_qty * adjusted_price * fee_rate
                                    
                                    if sell_qty > 0 and portfolio.execute_trade(symbol, "sell", sell_qty, adjusted_price, fee, strategy_name):
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
        equity_df.to_csv(OUT_DIR / "smart_equity_curve.csv")
        
        with open(OUT_DIR / "smart_results.json", "w") as f:
            json.dump(metrics, f, indent=2)
        
        if portfolio.trades:
            trades_df = pd.DataFrame(portfolio.trades)
            trades_df.to_csv(OUT_DIR / "smart_trades.csv", index=False)
        
        if portfolio.signals:
            signals_df = pd.DataFrame(portfolio.signals)
            signals_df.to_csv(OUT_DIR / "smart_signals.csv", index=False)
        
        # Print results
        print("\n" + "="*60)
        print("🧠 SMART AGGRESSIVE BACKTEST RESULTS")
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
        
        # Goal achievement check
        target_return = 300.0  # 300% return goal
        if metrics.get('total_return', 0) >= target_return:
            print(f"🎉 GOAL ACHIEVED! Target: {target_return}%, Actual: {metrics.get('total_return', 0):.2f}%")
        else:
            print(f"🎯 Goal Progress: {metrics.get('total_return', 0):.2f}% / {target_return}% ({(metrics.get('total_return', 0)/target_return)*100:.1f}%)")
        
        print(f"\n📁 Results saved to: {OUT_DIR}")
        
        logger.info("✅ Smart aggressive backtest completed successfully")
    else:
        logger.error("❌ No portfolio history generated")

def parse_args():
    parser = argparse.ArgumentParser(description="Smart Aggressive Crypto Trading Bot Backtest")
    parser.add_argument("--exchange", default="kraken", help="Exchange ID")
    parser.add_argument("--pairs", nargs="+", default=["BTC/USD"], help="Trading pairs")
    parser.add_argument("--timeframe", default="4h", help="Timeframe")
    parser.add_argument("--days", type=int, default=180, help="Days to backtest")
    parser.add_argument("--limit", type=int, default=2000, help="Max candles")
    parser.add_argument("--start", type=float, default=500.0, help="Starting capital")
    parser.add_argument("--redis-url", help="Redis Cloud URL")
    return parser.parse_args()

if __name__ == "__main__":
    try:
        args = parse_args()
        run_smart_aggressive_backtest(args)
    except KeyboardInterrupt:
        print("\nSmart aggressive backtest interrupted")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Smart aggressive backtest failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

