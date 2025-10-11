"""
Momentum Trading Strategy
Implements momentum-based trading using RSI, VWAP, and trailing stops
Integrates with the multi-agent crypto trading bot architecture
"""

import numpy as np
import pandas as pd
import talib
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

from mcp.schemas import Signal
from typing import Dict, Any

# Mock classes for compatibility
class MarketData:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

class PositionInfo:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)
from mcp.redis_manager import RedisManager
from utils.logger import get_logger

logger = get_logger(__name__)

@dataclass
class MomentumConfig:
    """Momentum strategy configuration"""
    rsi_period: int = 10
    vwap_window: int = 14
    rsi_range: Tuple[int, int] = (40, 70)
    vwap_gap: float = 0.01
    trailing_stop: float = 0.01
    min_volume_ratio: float = 1.2
    confirmation_candles: int = 2
    max_position_hold_hours: int = 24

class MomentumStrategy:
    """
    Momentum trading strategy that identifies trending moves using:
    - RSI for momentum confirmation
    - VWAP for price level validation
    - Dynamic trailing stops
    - Volume confirmation
    """
    
    def __init__(self, redis_manager: RedisManager, config: Dict):
        self.redis_manager = redis_manager
        self.config = MomentumConfig(**config.get('momentum', {}))
        self.strategy_name = "momentum"
        self.active_positions = {}
        self.signal_history = []
        self.performance_metrics = {
            'total_signals': 0,
            'profitable_trades': 0,
            'total_trades': 0,
            'avg_hold_time': 0,
            'max_drawdown': 0
        }
        
        logger.info(f"Momentum strategy initialized with RSI period: {self.config.rsi_period}")

    async def analyze_market(self, market_data: MarketData) -> Optional[Signal]:
        """
        Analyze market data and generate momentum-based trading signals
        
        Args:
            market_data: Current market data including OHLCV
            
        Returns:
            Signal if conditions are met, None otherwise
        """
        try:
            # Get historical data for technical analysis
            df = await self._get_market_dataframe(market_data.symbol)
            if df is None or len(df) < max(self.config.rsi_period, self.config.vwap_window) + 10:
                logger.warning(f"Insufficient data for {market_data.symbol}")
                return None

            # Calculate technical indicators
            indicators = await self._calculate_indicators(df)
            if not indicators:
                return None

            # Check for momentum signals
            signal = await self._evaluate_momentum_conditions(
                market_data, df, indicators
            )
            
            if signal:
                # Update performance tracking
                self.performance_metrics['total_signals'] += 1
                self.signal_history.append({
                    'timestamp': datetime.now(),
                    'symbol': market_data.symbol,
                    'signal': signal.action,
                    'price': market_data.price,
                    'confidence': signal.confidence
                })
                
                # Store signal in Redis for other agents
                await self._store_signal_in_redis(signal)
                
            return signal
            
        except Exception as e:
            logger.error(f"Error analyzing momentum for {market_data.symbol}: {e}")
            return None

    async def _get_market_dataframe(self, symbol: str) -> Optional[pd.DataFrame]:
        """Get historical market data as DataFrame"""
        try:
            # Fetch from Redis cache or external API
            cache_key = f"ohlcv:{symbol}:1h"
            cached_data = await self.redis_manager.get(cache_key)
            
            if cached_data:
                df = pd.DataFrame(cached_data)
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                df.set_index('timestamp', inplace=True)
                return df
            
            logger.warning(f"No cached data found for {symbol}")
            return None
            
        except Exception as e:
            logger.error(f"Error fetching dataframe for {symbol}: {e}")
            return None

    async def _calculate_indicators(self, df: pd.DataFrame) -> Optional[Dict]:
        """Calculate momentum indicators"""
        try:
            if len(df) < max(self.config.rsi_period, self.config.vwap_window):
                return None
                
            indicators = {}
            
            # RSI calculation
            indicators['rsi'] = talib.RSI(df['close'].values, timeperiod=self.config.rsi_period)
            
            # VWAP calculation
            indicators['vwap'] = await self._calculate_vwap(df, self.config.vwap_window)
            
            # Volume metrics
            indicators['volume_sma'] = talib.SMA(df['volume'].values, timeperiod=20)
            indicators['volume_ratio'] = df['volume'] / indicators['volume_sma']
            
            # Price momentum
            indicators['price_change'] = df['close'].pct_change(periods=5)
            indicators['volatility'] = df['close'].rolling(window=20).std()
            
            # Trend strength
            indicators['ema_short'] = talib.EMA(df['close'].values, timeperiod=8)
            indicators['ema_long'] = talib.EMA(df['close'].values, timeperiod=21)
            
            return indicators
            
        except Exception as e:
            logger.error(f"Error calculating indicators: {e}")
            return None

    async def _calculate_vwap(self, df: pd.DataFrame, window: int) -> np.ndarray:
        """Calculate Volume Weighted Average Price"""
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        return (typical_price * df['volume']).rolling(window=window).sum() / \
               df['volume'].rolling(window=window).sum()

    async def _evaluate_momentum_conditions(self, 
                                          market_data: MarketData, 
                                          df: pd.DataFrame, 
                                          indicators: Dict) -> Optional[Signal]:
        """Evaluate momentum trading conditions"""
        try:
            current_price = market_data.price
            latest_idx = -1
            
            # Get latest indicator values
            rsi = indicators['rsi'][latest_idx]
            vwap = indicators['vwap'][latest_idx]
            volume_ratio = indicators['volume_ratio'].iloc[latest_idx]
            price_change = indicators['price_change'].iloc[latest_idx]
            
            if np.isnan(rsi) or np.isnan(vwap):
                return None

            # Long momentum conditions
            long_conditions = await self._check_long_momentum(
                current_price, rsi, vwap, volume_ratio, price_change, indicators
            )
            
            # Short momentum conditions  
            short_conditions = await self._check_short_momentum(
                current_price, rsi, vwap, volume_ratio, price_change, indicators
            )
            
            if long_conditions['signal']:
                return Signal(
                    strategy=self.strategy_name,
                    symbol=market_data.symbol,
                    action="BUY",
                    price=current_price,
                    quantity=await self._calculate_position_size(market_data, "long"),
                    confidence=long_conditions['confidence'],
                    stop_loss=current_price * (1 - self.config.trailing_stop),
                    take_profit=current_price * (1 + self.config.trailing_stop * 2),
                    timestamp=datetime.now(),
                    metadata={
                        'rsi': rsi,
                        'vwap': vwap,
                        'volume_ratio': volume_ratio,
                        'price_change': price_change,
                        'strategy_type': 'momentum_long'
                    }
                )
            
            elif short_conditions['signal']:
                return Signal(
                    strategy=self.strategy_name,
                    symbol=market_data.symbol,
                    action="SELL",
                    price=current_price,
                    quantity=await self._calculate_position_size(market_data, "short"),
                    confidence=short_conditions['confidence'],
                    stop_loss=current_price * (1 + self.config.trailing_stop),
                    take_profit=current_price * (1 - self.config.trailing_stop * 2),
                    timestamp=datetime.now(),
                    metadata={
                        'rsi': rsi,
                        'vwap': vwap,
                        'volume_ratio': volume_ratio,
                        'price_change': price_change,
                        'strategy_type': 'momentum_short'
                    }
                )
                
            return None
            
        except Exception as e:
            logger.error(f"Error evaluating momentum conditions: {e}")
            return None

    async def _check_long_momentum(self, price: float, rsi: float, vwap: float,
                                  volume_ratio: float, price_change: float,
                                  indicators: Dict) -> Dict:
        """Check long momentum conditions"""
        conditions_met = 0
        total_conditions = 6
        
        # RSI in momentum range (not oversold/overbought)
        if self.config.rsi_range[0] <= rsi <= self.config.rsi_range[1]:
            conditions_met += 1
            
        # Price above VWAP with minimum gap
        if price > vwap * (1 + self.config.vwap_gap):
            conditions_met += 1
            
        # Volume confirmation
        if volume_ratio >= self.config.min_volume_ratio:
            conditions_met += 1
            
        # Positive price momentum
        if price_change > 0.001:  # 0.1% minimum move
            conditions_met += 1
            
        # EMA trend confirmation
        ema_short = indicators['ema_short'][-1]
        ema_long = indicators['ema_long'][-1]
        if ema_short > ema_long:
            conditions_met += 1
            
        # Recent momentum acceleration
        if len(indicators['price_change']) >= 3:
            recent_changes = indicators['price_change'].iloc[-3:].values
            if np.mean(recent_changes) > 0:
                conditions_met += 1
        
        confidence = conditions_met / total_conditions
        signal = confidence >= 0.75  # Need at least 75% of conditions
        
        return {'signal': signal, 'confidence': confidence}

    async def _check_short_momentum(self, price: float, rsi: float, vwap: float,
                                   volume_ratio: float, price_change: float,
                                   indicators: Dict) -> Dict:
        """Check short momentum conditions"""
        conditions_met = 0
        total_conditions = 6
        
        # RSI in momentum range
        if self.config.rsi_range[0] <= rsi <= self.config.rsi_range[1]:
            conditions_met += 1
            
        # Price below VWAP with minimum gap
        if price < vwap * (1 - self.config.vwap_gap):
            conditions_met += 1
            
        # Volume confirmation
        if volume_ratio >= self.config.min_volume_ratio:
            conditions_met += 1
            
        # Negative price momentum
        if price_change < -0.001:  # -0.1% minimum move
            conditions_met += 1
            
        # EMA trend confirmation
        ema_short = indicators['ema_short'][-1]
        ema_long = indicators['ema_long'][-1]
        if ema_short < ema_long:
            conditions_met += 1
            
        # Recent momentum acceleration (downward)
        if len(indicators['price_change']) >= 3:
            recent_changes = indicators['price_change'].iloc[-3:].values
            if np.mean(recent_changes) < 0:
                conditions_met += 1
        
        confidence = conditions_met / total_conditions
        signal = confidence >= 0.75
        
        return {'signal': signal, 'confidence': confidence}

    async def _calculate_position_size(self, market_data: MarketData, direction: str) -> float:
        """Calculate position size based on volatility and risk management"""
        try:
            # Get base position size from config
            base_size = 0.03  # 3% default
            
            # Adjust for volatility (lower volatility = larger position)
            volatility = await self._get_current_volatility(market_data.symbol)
            if volatility:
                volatility_adj = max(0.5, min(1.5, 1.0 / volatility))
                base_size *= volatility_adj
            
            # Apply maximum position limits
            max_position = 0.08  # 8% cap from config
            return min(base_size, max_position)
            
        except Exception as e:
            logger.error(f"Error calculating position size: {e}")
            return 0.03  # Default fallback

    async def _get_current_volatility(self, symbol: str) -> Optional[float]:
        """Get current volatility estimate"""
        try:
            cache_key = f"volatility:{symbol}"
            cached_vol = await self.redis_manager.get(cache_key)
            
            if cached_vol:
                return float(cached_vol)
            
            # Calculate from recent price data if not cached
            df = await self._get_market_dataframe(symbol)
            if df is not None and len(df) >= 20:
                volatility = df['close'].pct_change().rolling(window=20).std().iloc[-1]
                # Cache for 1 hour
                await self.redis_manager.set(cache_key, str(volatility), ex=3600)
                return volatility
                
        except Exception as e:
            logger.error(f"Error getting volatility for {symbol}: {e}")
            
        return None

    async def _store_signal_in_redis(self, signal: Signal):
        """Store generated signal in Redis for other agents"""
        try:
            signal_key = f"signals:momentum:{signal.symbol}:{int(signal.timestamp.timestamp())}"
            signal_data = {
                'strategy': signal.strategy,
                'symbol': signal.symbol,
                'action': signal.action,
                'price': signal.price,
                'quantity': signal.quantity,
                'confidence': signal.confidence,
                'timestamp': signal.timestamp.isoformat(),
                'metadata': signal.metadata
            }
            
            await self.redis_manager.set(signal_key, signal_data, ex=3600)  # 1 hour expiry
            
            # Also add to strategy-specific list
            list_key = f"momentum_signals:{signal.symbol}"
            await self.redis_manager.lpush(list_key, signal_data)
            await self.redis_manager.ltrim(list_key, 0, 100)  # Keep last 100 signals
            
        except Exception as e:
            logger.error(f"Error storing signal in Redis: {e}")

    async def update_position_management(self, position: PositionInfo) -> Optional[Dict]:
        """Update trailing stops and position management"""
        try:
            if position.symbol not in self.active_positions:
                self.active_positions[position.symbol] = {
                    'entry_price': position.entry_price,
                    'entry_time': datetime.now(),
                    'highest_price': position.entry_price,
                    'lowest_price': position.entry_price,
                    'trailing_stop': position.entry_price * (1 - self.config.trailing_stop)
                }
            
            pos_data = self.active_positions[position.symbol]
            current_price = position.current_price
            
            # Update price extremes
            if position.side == "long":
                if current_price > pos_data['highest_price']:
                    pos_data['highest_price'] = current_price
                    # Update trailing stop
                    pos_data['trailing_stop'] = current_price * (1 - self.config.trailing_stop)
                
                # Check if trailing stop hit
                if current_price <= pos_data['trailing_stop']:
                    return {'action': 'close', 'reason': 'trailing_stop_hit'}
                    
            else:  # short position
                if current_price < pos_data['lowest_price']:
                    pos_data['lowest_price'] = current_price
                    pos_data['trailing_stop'] = current_price * (1 + self.config.trailing_stop)
                
                if current_price >= pos_data['trailing_stop']:
                    return {'action': 'close', 'reason': 'trailing_stop_hit'}
            
            # Check maximum hold time
            if datetime.now() - pos_data['entry_time'] > timedelta(hours=self.config.max_position_hold_hours):
                return {'action': 'close', 'reason': 'max_hold_time_reached'}
            
            return None
            
        except Exception as e:
            logger.error(f"Error updating position management: {e}")
            return None

    async def get_strategy_performance(self) -> Dict:
        """Get current strategy performance metrics"""
        try:
            # Calculate win rate
            win_rate = 0
            if self.performance_metrics['total_trades'] > 0:
                win_rate = self.performance_metrics['profitable_trades'] / self.performance_metrics['total_trades']
            
            return {
                'strategy': self.strategy_name,
                'total_signals': self.performance_metrics['total_signals'],
                'total_trades': self.performance_metrics['total_trades'],
                'win_rate': win_rate,
                'active_positions': len(self.active_positions),
                'avg_confidence': np.mean([s.get('confidence', 0) for s in self.signal_history[-50:]]) if self.signal_history else 0,
                'last_signal_time': self.signal_history[-1]['timestamp'].isoformat() if self.signal_history else None
            }
            
        except Exception as e:
            logger.error(f"Error getting strategy performance: {e}")
            return {}

    async def cleanup_expired_positions(self):
        """Clean up expired or invalid positions"""
        try:
            current_time = datetime.now()
            expired_symbols = []
            
            for symbol, pos_data in self.active_positions.items():
                if current_time - pos_data['entry_time'] > timedelta(hours=self.config.max_position_hold_hours * 2):
                    expired_symbols.append(symbol)
            
            for symbol in expired_symbols:
                del self.active_positions[symbol]
                logger.info(f"Cleaned up expired position for {symbol}")
                
        except Exception as e:
            logger.error(f"Error cleaning up positions: {e}")

# Factory function for strategy initialization
def create_momentum_strategy(redis_manager: RedisManager, config: Dict) -> MomentumStrategy:
    """Factory function to create momentum strategy instance"""
    return MomentumStrategy(redis_manager, config)