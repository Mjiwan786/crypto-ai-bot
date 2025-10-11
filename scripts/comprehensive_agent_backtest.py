#!/usr/bin/env python3
"""
Working Crypto Trading Bot Backtest - Redis Fixed + Active Strategies
"""

import argparse
import json
import math
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional
import numpy as np
import pandas as pd
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1] if Path(__file__).parent.name == "scripts" else Path.cwd()
OUT_DIR = ROOT / "reports" / "comprehensive_backtest"
OUT_DIR.mkdir(parents=True, exist_ok=True)

class MarketRegimeDetector:
    """Detects market regime to filter strategy execution"""
    
    def __init__(self):
        self.regime_history = []
    
    def detect_regime(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Detect current market regime based on price action"""
        if len(df) < 50:
            return {"regime": "unknown", "confidence": 0.0, "volatility": "medium"}
        
        # Calculate indicators
        df_copy = df.copy()
        df_copy['sma_20'] = df_copy['close'].rolling(20).mean()
        df_copy['sma_50'] = df_copy['close'].rolling(50).mean()
        df_copy['atr'] = self.calculate_atr(df_copy, 14)
        df_copy['rsi'] = self.calculate_rsi(df_copy['close'], 14)
        df_copy['price_change'] = df_copy['close'].pct_change()
        
        current = df_copy.iloc[-1]
        
        # Trend detection
        trend_strength = (current['sma_20'] - current['sma_50']) / current['sma_50']
        price_above_sma20 = current['close'] > current['sma_20']
        price_above_sma50 = current['close'] > current['sma_50']
        
        # Volatility detection
        atr_pct = current['atr'] / current['close']
        volatility = "high" if atr_pct > 0.03 else "low" if atr_pct < 0.01 else "medium"
        
        # RSI extremes
        rsi_extreme = current['rsi'] < 30 or current['rsi'] > 70
        
        # Determine regime
        if abs(trend_strength) > 0.02 and price_above_sma20 == price_above_sma50:
            regime = "trending"
            confidence = min(0.9, abs(trend_strength) * 10)
        elif atr_pct < 0.015 and abs(trend_strength) < 0.01:
            regime = "sideways"
            confidence = 0.8
        elif volatility == "high" or rsi_extreme:
            regime = "volatile"
            confidence = 0.7
        else:
            regime = "neutral"
            confidence = 0.5
        
        return {
            "regime": regime,
            "confidence": confidence,
            "volatility": volatility,
            "trend_strength": trend_strength,
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
    
    def should_trade_strategy(self, strategy_name: str, regime: Dict[str, Any]) -> bool:
        """Determine if strategy should trade in current regime"""
        regime_type = regime["regime"]
        confidence = regime["confidence"]
        volatility = regime["volatility"]
        
        # Strategy-specific regime filters (less restrictive)
        if strategy_name == "scalping":
            # Disable scalping completely (0% win rate)
            return False
        
        elif strategy_name == "trend_following":
            # Trade in trending or neutral markets
            return regime_type in ["trending", "neutral"] and confidence > 0.4
        
        elif strategy_name == "sideways":
            # Trade in sideways or neutral markets
            return regime_type in ["sideways", "neutral"] and confidence > 0.4
        
        return True  # Default: allow trading

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

class RedisContextManager:
    """Fixed Redis Cloud SSL connection manager"""
    
    def __init__(self, redis_url: str, namespace: str = "backtest"):
        self.namespace = namespace
        self.connected = False
        
        if redis_url and redis_url.startswith(('redis://', 'rediss://')):
            try:
                import redis
                
                if redis_url.startswith('rediss://'):
                    # Fixed SSL connection for Redis Cloud
                    self.redis = redis.from_url(
                        redis_url,
                        decode_responses=True,
                        socket_connect_timeout=10,
                        ssl_cert_reqs=None,
                        ssl_ca_certs=None,
                        ssl_check_hostname=False
                    )
                else:
                    self.redis = redis.from_url(redis_url, decode_responses=True)
                
                # Test connection
                self.redis.ping()
                self.connected = True
                logger.info("✅ Connected to Redis Cloud")
                
                # Test operations
                test_key = f"{self.namespace}:test"
                self.redis.setex(test_key, 60, "working")
                result = self.redis.get(test_key)
                self.redis.delete(test_key)
                
                if result == "working":
                    logger.info("✅ Redis operations verified")
                else:
                    raise Exception("Redis test failed")
                    
            except Exception as e:
                logger.warning(f"Redis connection failed: {e}")
                logger.info("Using local memory storage")
                self.redis = {}
                self.connected = False
        else:
            self.redis = {}
            logger.info("Using local memory storage")
    
    def set_context(self, key: str, value: Any, expire_seconds: int = 3600):
        full_key = f"{self.namespace}:{key}"
        if self.connected:
            try:
                self.redis.setex(full_key, expire_seconds, json.dumps(value))
            except:
                self.redis[full_key] = value
        else:
            self.redis[full_key] = value
    
    def get_context(self, key: str) -> Optional[Any]:
        full_key = f"{self.namespace}:{key}"
        if self.connected:
            try:
                data = self.redis.get(full_key)
                return json.loads(data) if data else None
            except:
                return self.redis.get(full_key)
        return self.redis.get(full_key)

class Portfolio:
    def __init__(self, start_balance: float):
        self.start_balance = float(start_balance)
        self.cash = float(start_balance)
        self.positions = {}
        self.equity = float(start_balance)
        self.max_equity = float(start_balance)
        self.history = []
        self.trades = []
        self.signals = []

    def mark(self, prices: Dict[str, float], timestamp):
        equity = self.cash
        for symbol, qty in self.positions.items():
            if symbol in prices and qty != 0:
                equity += qty * prices[symbol]
        self.equity = float(equity)
        self.max_equity = max(self.max_equity, self.equity)
        self.history.append({
            "datetime": timestamp.isoformat(),
            "equity": self.equity,
            "cash": self.cash
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
                return True
        return False

class TrendFollowingStrategy:
    def __init__(self):
        self.name = "trend_following"
        self.positions = {}  # Track open positions: {symbol: {'entry_price': float, 'entry_time': datetime, 'qty': float}}
        self.regime_detector = MarketRegimeDetector()
    
    def generate_signal(self, df, context=None):
        if len(df) < 55:  # Need more data for regime detection
            return None
        
        context = context or {}
        symbol = context.get('symbol', 'UNKNOWN')
        max_position = context.get('max_position', 1000.0)
        current_price = df.iloc[-1]['close']
        
        # Market regime detection
        regime = self.regime_detector.detect_regime(df)
        if not self.regime_detector.should_trade_strategy(self.name, regime):
            return None
        
        # Calculate EMAs (matching config: 21/55)
        df_copy = df.copy()
        df_copy['ema_21'] = df_copy['close'].ewm(span=21).mean()
        df_copy['ema_55'] = df_copy['close'].ewm(span=55).mean()
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
            
            # Dynamic risk management based on volatility
            atr_pct = current['atr'] / current_price
            dynamic_tp = max(0.02, min(0.05, atr_pct * 2))  # 2-5% based on volatility
            dynamic_sl = max(0.01, min(0.03, atr_pct * 1.5))  # 1-3% based on volatility
            
            # Take profit with dynamic target
            if profit_pct >= dynamic_tp:
                del self.positions[symbol]
                return Signal(
                    strategy=self.name,
                    exchange="kraken",
                    symbol=symbol,
                    side='sell',
                    confidence=0.9,
                    size_quote_usd=position['qty'] * current_price,
                    meta={'signal_type': 'take_profit', 'profit_pct': profit_pct, 'dynamic_tp': dynamic_tp}
                )
            
            # Stop loss with dynamic target
            if profit_pct <= -dynamic_sl:
                del self.positions[symbol]
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
            if current['ema_21'] < current['ema_55']:
                del self.positions[symbol]
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
            ema_21_rising = current['ema_21'] > prev['ema_21']
            ema_55_rising = current['ema_55'] > prev['ema_55']
            above_ema = current['close'] > current['ema_21']
            volume_ok = current['volume'] > current['volume_ma'] * 0.8  # Higher volume requirement
            
            # Calculate trend strength
            ema_spread = (current['ema_21'] - current['ema_55']) / current['ema_55']
            trend_strength = abs(ema_spread)
            
            # Additional confirmation signals (less strict)
            rsi_not_overbought = current['rsi'] < 80  # Not extremely overbought
            price_momentum = (current['close'] - prev['close']) / prev['close'] > 0.0005  # Slight positive momentum
            regime_confirmation = regime['confidence'] > 0.4  # Lower confidence requirement
            
            # Enhanced entry conditions with multiple confirmations
            if (current['ema_21'] > current['ema_55'] and 
                ema_21_rising and above_ema and volume_ok and
                trend_strength > 0.001 and  # Reduced trend requirement
                rsi_not_overbought and price_momentum and regime_confirmation):
                
                # Dynamic position sizing based on trend strength and allocation
                base_size = max_position * 0.60  # 60% allocation (matching config)
                trend_multiplier = min(2.0, trend_strength * 1000)  # Scale with trend strength
                position_size = min(base_size * trend_multiplier, 600.0)  # Max $600 per trade
                qty = position_size / current_price
                
                # Track the position
                self.positions[symbol] = {
                    'entry_price': current_price,
                    'entry_time': df.index[-1],
                    'qty': qty
                }
                
                return Signal(
                    strategy=self.name,
                    exchange="kraken",
                    symbol=symbol,
                    side='buy',
                    confidence=min(0.9, 0.6 + trend_strength * 100),  # Higher confidence for stronger trends
                    size_quote_usd=position_size,
                    meta={'signal_type': 'trend_bullish', 'ema_spread': ema_spread, 'trend_strength': trend_strength}
                )
        
        return None

class BreakoutStrategy:
    def __init__(self):
        self.name = "breakout"
        self.positions = {}  # Track open positions
    
    def generate_signal(self, df, context=None):
        if len(df) < 20:
            return None
        
        context = context or {}
        symbol = context.get('symbol', 'UNKNOWN')
        max_position = context.get('max_position', 1000.0)
        current_price = df.iloc[-1]['close']
        
        df_copy = df.copy()
        lookback = 10
        df_copy['resistance'] = df_copy['high'].rolling(lookback).max()
        df_copy['support'] = df_copy['low'].rolling(lookback).min()
        df_copy['volume_ma'] = df_copy['volume'].rolling(10).mean()
        
        current = df_copy.iloc[-1]
        
        # Check for exit conditions first
        if symbol in self.positions:
            position = self.positions[symbol]
            entry_price = position['entry_price']
            profit_pct = (current_price - entry_price) / entry_price
            
            # Take profit at 3% gain (higher for breakout strategy)
            if profit_pct >= 0.03:
                del self.positions[symbol]
                return Signal(
                    strategy=self.name,
                    exchange="kraken",
                    symbol=symbol,
                    side='sell',
                    confidence=0.9,
                    size_quote_usd=position['qty'] * current_price,
                    meta={'signal_type': 'take_profit', 'profit_pct': profit_pct}
                )
            
            # Stop loss at 1.5% loss
            if profit_pct <= -0.015:
                del self.positions[symbol]
                return Signal(
                    strategy=self.name,
                    exchange="kraken",
                    symbol=symbol,
                    side='sell',
                    confidence=0.9,
                    size_quote_usd=position['qty'] * current_price,
                    meta={'signal_type': 'stop_loss', 'loss_pct': profit_pct}
                )
            
            # Exit if price falls back below breakout level
            if current_price < current['resistance'] * 0.998:
                del self.positions[symbol]
                return Signal(
                    strategy=self.name,
                    exchange="kraken",
                    symbol=symbol,
                    side='sell',
                    confidence=0.8,
                    size_quote_usd=position['qty'] * current_price,
                    meta={'signal_type': 'breakout_failure'}
                )
        
        # Entry conditions (only if no position)
        if symbol not in self.positions:
            resistance_break = current['close'] > current['resistance'] * 1.001
            volume_surge = current['volume'] > current['volume_ma'] * 1.2
            
            if resistance_break and volume_surge:
                position_size = min(max_position * 0.04, 180.0)
                qty = position_size / current_price
                
                # Track the position
                self.positions[symbol] = {
                    'entry_price': current_price,
                    'entry_time': df.index[-1],
                    'qty': qty,
                    'breakout_level': current['resistance']
                }
                
                return Signal(
                    strategy=self.name,
                    exchange="kraken",
                    symbol=symbol,
                    side='buy',
                    confidence=0.75,
                    size_quote_usd=position_size,
                    meta={'signal_type': 'resistance_breakout', 'breakout_level': current['resistance']}
                )
        
        return None

class MomentumStrategy:
    def __init__(self):
        self.name = "momentum"
        self.positions = {}  # Track open positions
    
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
        
        df_copy = df.copy()
        df_copy['rsi'] = self.calculate_rsi(df_copy['close'])
        df_copy['price_change_3'] = df_copy['close'].pct_change(3)
        df_copy['volume_ratio'] = df_copy['volume'] / df_copy['volume'].rolling(10).mean()
        
        current = df_copy.iloc[-1]
        
        # Check for exit conditions first
        if symbol in self.positions:
            position = self.positions[symbol]
            entry_price = position['entry_price']
            profit_pct = (current_price - entry_price) / entry_price
            
            # Take profit at 2.5% gain
            if profit_pct >= 0.025:
                del self.positions[symbol]
                return Signal(
                    strategy=self.name,
                    exchange="kraken",
                    symbol=symbol,
                    side='sell',
                    confidence=0.9,
                    size_quote_usd=position['qty'] * current_price,
                    meta={'signal_type': 'take_profit', 'profit_pct': profit_pct}
                )
            
            # Stop loss at 1.2% loss
            if profit_pct <= -0.012:
                del self.positions[symbol]
                return Signal(
                    strategy=self.name,
                    exchange="kraken",
                    symbol=symbol,
                    side='sell',
                    confidence=0.9,
                    size_quote_usd=position['qty'] * current_price,
                    meta={'signal_type': 'stop_loss', 'loss_pct': profit_pct}
                )
            
            # Exit on RSI overbought or momentum reversal
            if current['rsi'] > 80 or current['price_change_3'] < -0.01:
                del self.positions[symbol]
                return Signal(
                    strategy=self.name,
                    exchange="kraken",
                    symbol=symbol,
                    side='sell',
                    confidence=0.8,
                    size_quote_usd=position['qty'] * current_price,
                    meta={'signal_type': 'momentum_reversal', 'rsi': current['rsi']}
                )
        
        # Entry conditions (only if no position)
        if symbol not in self.positions:
            if (30 < current['rsi'] < 75 and
                current['price_change_3'] > 0.01 and
                current['volume_ratio'] > 1.0):
                
                position_size = min(max_position * 0.03, 150.0)
                qty = position_size / current_price
                
                # Track the position
                self.positions[symbol] = {
                    'entry_price': current_price,
                    'entry_time': df.index[-1],
                    'qty': qty
                }
                
                return Signal(
                    strategy=self.name,
                    exchange="kraken",
                    symbol=symbol,
                    side='buy',
                    confidence=0.65,
                    size_quote_usd=position_size,
                    meta={'signal_type': 'momentum_bullish', 'rsi': current['rsi']}
                )
        
        return None

class SidewaysStrategy:
    def __init__(self):
        self.name = "sideways"
        self.positions = {}  # Track open positions
        self.regime_detector = MarketRegimeDetector()
    
    def generate_signal(self, df, context=None):
        if len(df) < 50:  # Need more data for regime detection
            return None
        
        context = context or {}
        symbol = context.get('symbol', 'UNKNOWN')
        max_position = context.get('max_position', 1000.0)
        current_price = df.iloc[-1]['close']
        
        # Market regime detection
        regime = self.regime_detector.detect_regime(df)
        if not self.regime_detector.should_trade_strategy(self.name, regime):
            return None
        
        df_copy = df.copy()
        # Calculate Bollinger Bands for range detection
        df_copy['sma_20'] = df_copy['close'].rolling(20).mean()
        df_copy['std_20'] = df_copy['close'].rolling(20).std()
        df_copy['bb_upper'] = df_copy['sma_20'] + (df_copy['std_20'] * 2)
        df_copy['bb_lower'] = df_copy['sma_20'] - (df_copy['std_20'] * 2)
        df_copy['bb_width'] = (df_copy['bb_upper'] - df_copy['bb_lower']) / df_copy['sma_20']
        df_copy['rsi'] = self.calculate_rsi(df_copy['close'])
        
        current = df_copy.iloc[-1]
        
        # Check for exit conditions first
        if symbol in self.positions:
            position = self.positions[symbol]
            entry_price = position['entry_price']
            profit_pct = (current_price - entry_price) / entry_price
            
            # Take profit at 1.5% gain (tighter for sideways strategy)
            if profit_pct >= 0.015:
                del self.positions[symbol]
                return Signal(
                    strategy=self.name,
                    exchange="kraken",
                    symbol=symbol,
                    side='sell',
                    confidence=0.9,
                    size_quote_usd=position['qty'] * current_price,
                    meta={'signal_type': 'take_profit', 'profit_pct': profit_pct}
                )
            
            # Stop loss at 0.8% loss (tighter for sideways strategy)
            if profit_pct <= -0.008:
                del self.positions[symbol]
                return Signal(
                    strategy=self.name,
                    exchange="kraken",
                    symbol=symbol,
                    side='sell',
                    confidence=0.9,
                    size_quote_usd=position['qty'] * current_price,
                    meta={'signal_type': 'stop_loss', 'loss_pct': profit_pct}
                )
            
            # Exit if price moves outside range (trend developing)
            if current_price > current['bb_upper'] * 1.01 or current_price < current['bb_lower'] * 0.99:
                del self.positions[symbol]
                return Signal(
                    strategy=self.name,
                    exchange="kraken",
                    symbol=symbol,
                    side='sell',
                    confidence=0.8,
                    size_quote_usd=position['qty'] * current_price,
                    meta={'signal_type': 'range_breakout'}
                )
        
        # Entry conditions (only if no position and in sideways market)
        if symbol not in self.positions:
            # Enhanced sideways detection with regime confirmation (less strict)
            is_sideways = (current['bb_width'] < 0.06 and  # Higher volatility threshold
                          current_price > current['bb_lower'] * 1.01 and  # Above lower band
                          current_price < current['bb_upper'] * 0.99 and  # Below upper band
                          regime['regime'] in ['sideways', 'neutral'] and  # Regime confirmation
                          regime['confidence'] > 0.4)  # Lower confidence requirement
            
            # Buy near lower band with additional confirmations
            if (is_sideways and 
                current_price <= current['bb_lower'] * 1.01 and  # Closer to lower band
                current['rsi'] < 30 and  # More oversold
                current['rsi'] > 20):  # Not extremely oversold
                
                position_size = min(max_position * 0.02, 100.0)  # Smaller position for sideways
                qty = position_size / current_price
                
                # Track the position
                self.positions[symbol] = {
                    'entry_price': current_price,
                    'entry_time': df.index[-1],
                    'qty': qty
                }
                
                return Signal(
                    strategy=self.name,
                    exchange="kraken",
                    symbol=symbol,
                    side='buy',
                    confidence=0.7,
                    size_quote_usd=position_size,
                    meta={'signal_type': 'range_buy', 'bb_position': (current_price - current['bb_lower']) / (current['bb_upper'] - current['bb_lower'])}
                )
        
        return None
    
    def calculate_rsi(self, prices, period=14):
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

class ScalpingStrategy:
    def __init__(self):
        self.name = "scalping"
        self.positions = {}  # Track open positions
    
    def generate_signal(self, df, context=None):
        if len(df) < 20:
            return None
        
        context = context or {}
        symbol = context.get('symbol', 'UNKNOWN')
        max_position = context.get('max_position', 1000.0)
        current_price = df.iloc[-1]['close']
        
        df_copy = df.copy()
        # Calculate RSI for scalping signals
        df_copy['rsi'] = self.calculate_rsi(df_copy['close'], 14)
        df_copy['price_change'] = df_copy['close'].pct_change()
        df_copy['volume_ma'] = df_copy['volume'].rolling(10).mean()
        
        current = df_copy.iloc[-1]
        
        # Check for exit conditions first
        if symbol in self.positions:
            position = self.positions[symbol]
            entry_price = position['entry_price']
            profit_pct = (current_price - entry_price) / entry_price
            
            # Take profit at 0.2% gain (20 bps - increased from 10 bps)
            if profit_pct >= 0.002:
                del self.positions[symbol]
                return Signal(
                    strategy=self.name,
                    exchange="kraken",
                    symbol=symbol,
                    side='sell',
                    confidence=0.9,
                    size_quote_usd=position['qty'] * current_price,
                    meta={'signal_type': 'take_profit', 'profit_pct': profit_pct}
                )
            
            # Stop loss at 0.15% loss (15 bps - increased from 5 bps)
            if profit_pct <= -0.0015:
                del self.positions[symbol]
                return Signal(
                    strategy=self.name,
                    exchange="kraken",
                    symbol=symbol,
                    side='sell',
                    confidence=0.9,
                    size_quote_usd=position['qty'] * current_price,
                    meta={'signal_type': 'stop_loss', 'loss_pct': profit_pct}
                )
            
            # Time-based exit (max hold 120 seconds as per config)
            import time
            if hasattr(position, 'entry_time'):
                hold_seconds = (df.index[-1] - position['entry_time']).total_seconds()
                if hold_seconds > 120:
                    del self.positions[symbol]
                    return Signal(
                        strategy=self.name,
                        exchange="kraken",
                        symbol=symbol,
                        side='sell',
                        confidence=0.8,
                        size_quote_usd=position['qty'] * current_price,
                        meta={'signal_type': 'time_exit', 'hold_seconds': hold_seconds}
                    )
        
        # Entry conditions (only if no position)
        if symbol not in self.positions:
            # More selective scalping entry conditions
            if (current['rsi'] < 30 and  # More oversold (was 35)
                current['price_change'] > 0.001 and  # Stronger price momentum (was just > 0)
                current['volume'] > current['volume_ma'] * 1.5 and  # Higher volume requirement (was 1.2)
                current['rsi'] > 20):  # Not extremely oversold (avoid dead cat bounces)
                
                # Position sizing based on 0.40 allocation
                base_size = max_position * 0.40  # 40% allocation
                position_size = min(base_size * 0.1, 200.0)  # Smaller per trade for scalping
                qty = position_size / current_price
                
                # Track the position
                self.positions[symbol] = {
                    'entry_price': current_price,
                    'entry_time': df.index[-1],
                    'qty': qty
                }
                
                return Signal(
                    strategy=self.name,
                    exchange="kraken",
                    symbol=symbol,
                    side='buy',
                    confidence=0.8,
                    size_quote_usd=position_size,
                    meta={'signal_type': 'scalp_buy', 'rsi': current['rsi']}
                )
        
        return None
    
    def calculate_rsi(self, prices, period=14):
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

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

def run_backtest(args):
    """Main backtest execution"""
    fix_seeds(42)
    
    # Setup Redis
    context_manager = RedisContextManager(args.redis_url or "")
    
    # Initialize strategies - scalping disabled due to 0% win rate
    strategies = [
        ("trend_following", TrendFollowingStrategy()),
        ("sideways", SidewaysStrategy())
        # Scalping strategy disabled due to poor performance
    ]
    
    # Fetch market data
    logger.info("📊 Fetching market data...")
    market_data = {}
    
    # Calculate date range
    if args.days > 0:
        import datetime
        since_ms = int((datetime.datetime.utcnow() - datetime.timedelta(days=args.days + 50)).timestamp() * 1000)
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
    
    logger.info(f"🔍 Backtesting {len(test_index)} periods")
    
    # Initialize portfolio
    portfolio = Portfolio(args.start)
    
    # Trading parameters
    fee_rate = 0.0026  # Kraken fees
    slippage = 0.001   # 0.1% slippage
    min_confidence = 0.6  # Lowered confidence threshold
    
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
                if len(historical_data) < 15:  # Reduced minimum data requirement
                    continue
                
                # Generate signal
                context = {
                    "symbol": symbol,
                    "max_position": portfolio.equity * 0.1  # Increased max position
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
                        
                        # Execute trade with lower confidence threshold
                        if signal.confidence >= min_confidence and symbol in current_prices:
                            price = current_prices[symbol]
                            
                            if signal.side == "buy":
                                adjusted_price = price * (1 + slippage)
                                qty = signal.size_quote_usd / adjusted_price
                                fee = signal.size_quote_usd * fee_rate
                                
                                if portfolio.execute_trade(symbol, "buy", qty, adjusted_price, fee, strategy_name):
                                    trade_count += 1
                                    
                                    # Store in Redis
                                    context_manager.set_context(
                                        f"trade:{timestamp.isoformat()}:{symbol}",
                                        {
                                            "strategy": strategy_name,
                                            "side": signal.side,
                                            "price": adjusted_price,
                                            "qty": qty
                                        }
                                    )
                            
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
        
        # Store results in Redis
        context_manager.set_context("final_results", metrics, expire_seconds=86400)
        
        # Save files
        equity_df.to_csv(OUT_DIR / "equity_curve.csv")
        
        with open(OUT_DIR / "results.json", "w") as f:
            json.dump(metrics, f, indent=2)
        
        if portfolio.trades:
            trades_df = pd.DataFrame(portfolio.trades)
            trades_df.to_csv(OUT_DIR / "trades.csv", index=False)
        
        if portfolio.signals:
            signals_df = pd.DataFrame(portfolio.signals)
            signals_df.to_csv(OUT_DIR / "signals.csv", index=False)
        
        # Print results
        print("\n" + "="*60)
        print("ENHANCED BACKTEST RESULTS")
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
        print(f"\n📁 Results saved to: {OUT_DIR}")
        
        logger.info("✅ Enhanced backtest completed successfully")
    else:
        logger.error("❌ No portfolio history generated")

def parse_args():
    parser = argparse.ArgumentParser(description="Enhanced Crypto Trading Bot Backtest")
    parser.add_argument("--exchange", default="kraken", help="Exchange ID")
    parser.add_argument("--pairs", nargs="+", default=["BTC/USD"], help="Trading pairs")
    parser.add_argument("--timeframe", default="1h", help="Timeframe")
    parser.add_argument("--days", type=int, default=30, help="Days to backtest")
    parser.add_argument("--limit", type=int, default=2000, help="Max candles")
    parser.add_argument("--start", type=float, default=1000.0, help="Starting capital")
    parser.add_argument("--redis-url", help="Redis Cloud URL")
    return parser.parse_args()

if __name__ == "__main__":
    try:
        args = parse_args()
        run_backtest(args)
    except KeyboardInterrupt:
        print("\nBacktest interrupted")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Backtest failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)