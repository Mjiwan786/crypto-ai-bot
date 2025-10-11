"""
Trend Following Strategy Module

A modular, configurable trend following strategy that uses EMA crossovers,
ATR for volatility measurement, and volume confirmation signals.
"""

import pandas as pd
import talib
from typing import Dict, Any, Optional
from utils.logger import get_logger

logger = get_logger(__name__)


class TrendFollowingStrategy:
    """
    Trend Following Strategy Implementation
    
    Uses EMA crossovers as primary signal with ATR-based trend strength
    and volume confirmation for enhanced signal quality.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the trend following strategy with configuration.
        
        Args:
            config: Strategy configuration dictionary
        """
        self.config = config
        self.name = "trend_following"
        
        # Extract configuration with defaults
        self.ema_short = config.get('ema_short', 9)
        self.ema_long = config.get('ema_long', 21)
        self.atr_period = config.get('atr_period', 14)
        self.min_trend_strength = config.get('min_trend_strength', 0.3)
        
        # Entry conditions
        entry_conditions = config.get('entry_conditions', {})
        self.confirmation_bars = entry_conditions.get('confirmation_bars', 2)
        self.volume_ratio = entry_conditions.get('volume_ratio', 1.2)
        
        logger.info(f"Initialized {self.name} strategy with EMA({self.ema_short}, {self.ema_long})")
    
    def generate_signal(
        self, df: pd.DataFrame, config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Generate trading signal based on trend following logic.
        
        Args:
            df: OHLCV DataFrame with columns ['open', 'high', 'low', 'close', 'volume']
            config: Optional config override (uses instance config if None)
            
        Returns:
            Dictionary containing signal, confidence, and position_size
        """
        try:
            # Use provided config or fall back to instance config
            active_config = config or self.config
            
            # Validate input data
            if not self._validate_data(df):
                return self._no_signal("Insufficient or invalid data")
            
            # Calculate technical indicators
            indicators = self._calculate_indicators(df)
            
            # Generate base signal from EMA crossover
            base_signal = self._get_ema_signal(indicators)
            
            # Calculate trend strength using ATR
            trend_strength = self._calculate_trend_strength(df, indicators)
            
            # Volume confirmation
            volume_confirmed = self._check_volume_confirmation(df)
            
            # Combine signals and calculate confidence
            final_signal, confidence = self._combine_signals(
                base_signal, trend_strength, volume_confirmed, indicators
            )
            
            # Calculate position size based on confidence and volatility
            position_size = self._calculate_position_size(
                confidence, indicators.get('atr_normalized', 0.02)
            )
            
            result = {
                "signal": final_signal,
                "confidence": round(confidence, 4),
                "position_size": round(position_size, 4),
                "metadata": {
                    "trend_strength": round(trend_strength, 4),
                    "volume_confirmed": volume_confirmed,
                    "ema_short": round(indicators.get('ema_short', 0), 6),
                    "ema_long": round(indicators.get('ema_long', 0), 6),
                    "atr": round(indicators.get('atr', 0), 6)
                }
            }
            
            logger.debug(f"Generated signal: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Error generating signal: {str(e)}")
            return self._no_signal(f"Error: {str(e)}")
    
    def _validate_data(self, df: pd.DataFrame) -> bool:
        """Validate input DataFrame has required columns and sufficient data."""
        required_cols = ['open', 'high', 'low', 'close', 'volume']
        
        if df.empty or len(df) < max(self.ema_long, self.atr_period) + 10:
            return False
            
        if not all(col in df.columns for col in required_cols):
            return False
            
        # Check for NaN values in recent data
        recent_data = df.tail(10)
        if recent_data[required_cols].isnull().any().any():
            return False
            
        return True
    
    def _calculate_indicators(self, df: pd.DataFrame) -> Dict[str, float]:
        """Calculate all technical indicators needed for the strategy."""
        close = df['close'].values
        high = df['high'].values
        low = df['low'].values
        
        # Calculate EMAs
        ema_short = talib.EMA(close, timeperiod=self.ema_short)
        ema_long = talib.EMA(close, timeperiod=self.ema_long)
        
        # Calculate ATR for volatility
        atr = talib.ATR(high, low, close, timeperiod=self.atr_period)
        
        # Normalize ATR as percentage of price
        atr_normalized = atr[-1] / close[-1] if close[-1] > 0 else 0.02
        
        return {
            'ema_short': ema_short[-1],
            'ema_long': ema_long[-1],
            'ema_short_prev': ema_short[-2] if len(ema_short) > 1 else ema_short[-1],
            'ema_long_prev': ema_long[-2] if len(ema_long) > 1 else ema_long[-1],
            'atr': atr[-1],
            'atr_normalized': atr_normalized,
            'close': close[-1]
        }
    
    def _get_ema_signal(self, indicators: Dict[str, float]) -> str:
        """Generate base signal from EMA crossover."""
        ema_short = indicators['ema_short']
        ema_long = indicators['ema_long']
        ema_short_prev = indicators['ema_short_prev']
        ema_long_prev = indicators['ema_long_prev']
        
        # Current state
        bullish_cross = ema_short > ema_long
        
        # Previous state for confirmation
        prev_bullish = ema_short_prev > ema_long_prev
        
        # Look for crossover with confirmation
        if bullish_cross and not prev_bullish:
            return "buy"
        elif not bullish_cross and prev_bullish:
            return "sell"
        elif bullish_cross:
            return "hold_long"
        else:
            return "hold_short"
    
    def _calculate_trend_strength(self, df: pd.DataFrame, indicators: Dict[str, float]) -> float:
        """Calculate trend strength using EMA separation and ATR."""
        ema_short = indicators['ema_short']
        ema_long = indicators['ema_long']
        atr = indicators['atr']
        close = indicators['close']
        
        # EMA separation as percentage of price
        ema_separation = abs(ema_short - ema_long) / close if close > 0 else 0
        
        # Normalize by ATR to account for volatility
        trend_strength = ema_separation / (atr / close) if atr > 0 else 0
        
        # Cap at 1.0 for consistency
        return min(trend_strength, 1.0)
    
    def _check_volume_confirmation(self, df: pd.DataFrame) -> bool:
        """Check if volume confirms the signal."""
        if len(df) < 20:
            return True  # Default to True if insufficient data
            
        recent_volume = df['volume'].tail(5).mean()
        avg_volume = df['volume'].tail(20).mean()
        
        return recent_volume >= (avg_volume * self.volume_ratio)
    
    def _combine_signals(self, base_signal: str, trend_strength: float, 
                        volume_confirmed: bool, indicators: Dict[str, float]) -> tuple[str, float]:
        """Combine all signals and calculate confidence score."""
        
        # Base confidence from trend strength
        confidence = trend_strength
        
        # Adjust based on signal type
        if base_signal in ["buy", "sell"]:
            # Fresh signals get boosted confidence if trend is strong
            if trend_strength >= self.min_trend_strength:
                confidence = min(confidence * 1.2, 1.0)
            else:
                # Weak trend - reduce to hold
                base_signal = "hold"
                confidence = 0.3
        elif base_signal in ["hold_long", "hold_short"]:
            # Holding positions - moderate confidence
            confidence = confidence * 0.8
            base_signal = "hold"
        else:
            base_signal = "hold"
            confidence = 0.2
        
        # Volume confirmation boost
        if volume_confirmed:
            confidence = min(confidence * 1.1, 1.0)
        else:
            confidence = confidence * 0.9
        
        # Minimum confidence threshold
        if confidence < 0.3 and base_signal != "hold":
            base_signal = "hold"
            confidence = 0.3
        
        return base_signal, confidence
    
    def _calculate_position_size(self, confidence: float, volatility: float) -> float:
        """Calculate position size based on confidence and volatility."""
        # Base position size from config
        base_size = self.config.get('base_position_size', 0.05)
        
        # Adjust for confidence (0.5 to 1.5 multiplier)
        confidence_multiplier = 0.5 + (confidence * 1.0)
        
        # Adjust for volatility (reduce size in high volatility)
        volatility_multiplier = max(0.5, 1.0 - (volatility * 10))
        
        position_size = base_size * confidence_multiplier * volatility_multiplier
        
        # Cap position size
        max_position = self.config.get('max_position_size', 0.15)
        return min(position_size, max_position)
    
    def _no_signal(self, reason: str = "") -> Dict[str, Any]:
        """Return a no-signal response."""
        logger.warning(f"No signal generated: {reason}")
        return {
            "signal": "hold",
            "confidence": 0.0,
            "position_size": 0.0,
            "metadata": {
                "reason": reason,
                "strategy": self.name
            }
        }


# Factory function for easy instantiation
def create_trend_following_strategy(config: Dict[str, Any]) -> TrendFollowingStrategy:
    """Factory function to create a trend following strategy instance."""
    return TrendFollowingStrategy(config)


# Standalone function interface (alternative to class)
def generate_trend_following_signal(df: pd.DataFrame, config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Standalone function interface for trend following strategy.
    
    Args:
        df: OHLCV DataFrame
        config: Strategy configuration
        
    Returns:
        Signal dictionary
    """
    strategy = TrendFollowingStrategy(config)
    return strategy.generate_signal(df)


if __name__ == "__main__":
    # Development testing with synthetic data
    import random
    from datetime import datetime, timedelta
    
    # Create synthetic OHLCV data for testing
    def create_synthetic_data(num_candles: int = 100) -> pd.DataFrame:
        """Create synthetic OHLCV data for testing."""
        dates = [datetime.now() - timedelta(minutes=i) for i in range(num_candles)]
        dates.reverse()
        
        data = []
        price = 50000  # Starting price
        
        for i, date in enumerate(dates):
            # Simple trend with noise
            trend = 0.001 if i < num_candles // 2 else -0.001
            price_change = random.gauss(trend, 0.005)
            
            high = price * (1 + abs(price_change) + random.uniform(0.001, 0.003))
            low = price * (1 - abs(price_change) - random.uniform(0.001, 0.003))
            close = price * (1 + price_change)
            volume = random.uniform(100, 1000)
            
            data.append({
                'timestamp': date,
                'open': price,
                'high': high,
                'low': low,
                'close': close,
                'volume': volume
            })
            
            price = close
        
        return pd.DataFrame(data)
    
    # Test configuration (matching your YAML structure)
    test_config = {
        'ema_short': 5,
        'ema_long': 13,
        'atr_period': 10,
        'min_trend_strength': 0.3,
        'entry_conditions': {
            'confirmation_bars': 1,
            'volume_ratio': 1.2
        },
        'base_position_size': 0.03,
        'max_position_size': 0.08
    }
    
    # Generate test data
    df = create_synthetic_data(150)
    
    print("🧪 Testing Trend Following Strategy")
    print(f"Data shape: {df.shape}")
    print(f"Price range: ${df['close'].min():.2f} - ${df['close'].max():.2f}")
    print("-" * 50)
    
    # Test class interface
    strategy = TrendFollowingStrategy(test_config)
    result = strategy.generate_signal(df)
    
    print("📊 Strategy Result:")
    print(f"Signal: {result['signal']}")
    print(f"Confidence: {result['confidence']:.4f}")
    print(f"Position Size: {result['position_size']:.4f}")
    
    if 'metadata' in result:
        print("\n📈 Technical Indicators:")
        metadata = result['metadata']
        print(f"Trend Strength: {metadata.get('trend_strength', 'N/A')}")
        print(f"Volume Confirmed: {metadata.get('volume_confirmed', 'N/A')}")
        print(f"EMA Short: ${metadata.get('ema_short', 0):.2f}")
        print(f"EMA Long: ${metadata.get('ema_long', 0):.2f}")
        print(f"ATR: ${metadata.get('atr', 0):.2f}")
    
    # Test function interface
    print("\n🔄 Testing function interface...")
    func_result = generate_trend_following_signal(df, test_config)
    print(f"Function result matches class: {result == func_result}")
    
    print("\n✅ Test completed successfully!")