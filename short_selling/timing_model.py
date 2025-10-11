"""
Timing Model Module for Short Selling Operations

Provides market timing analysis for optimal entry and exit points
in short-selling strategies using technical indicators and market regime detection.
"""

from __future__ import annotations

import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum

try:
    from utils.logger import get_logger
except ImportError:
    def get_logger(name):
        return logging.getLogger(name)


class MarketRegime(str, Enum):
    """Market regime classifications."""
    BULL_STRONG = "bull_strong"
    BULL_WEAK = "bull_weak"
    SIDEWAYS = "sideways"
    BEAR_WEAK = "bear_weak"
    BEAR_STRONG = "bear_strong"
    VOLATILE = "volatile"


class TimingSignal(str, Enum):
    """Timing signal classifications."""
    STRONG_SHORT = "strong_short"
    WEAK_SHORT = "weak_short"
    NEUTRAL = "neutral"
    WEAK_LONG = "weak_long"
    STRONG_LONG = "strong_long"


@dataclass
class TimingAnalysis:
    """Market timing analysis result."""
    signal: TimingSignal
    confidence: float  # 0-1
    regime: MarketRegime
    entry_score: float  # 0-1, higher = better entry
    exit_score: float  # 0-1, higher = should exit
    hold_duration_est: timedelta
    key_levels: Dict[str, float]  # support/resistance levels
    indicators: Dict[str, float]  # Technical indicator values
    reasoning: List[str]  # Human-readable reasoning


@dataclass
class MarketState:
    """Current market state snapshot."""
    price: float
    volume_24h: float
    volatility: float
    trend_strength: float
    momentum: float
    mean_reversion_signal: float
    breakout_signal: float
    sentiment_score: float


class TimingModel:
    """
    Advanced timing model for short-selling operations.
    
    Combines technical analysis, market regime detection, and sentiment analysis
    to provide optimal entry and exit timing for short positions.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize TimingModel.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.logger = get_logger(__name__)
        
        # Timing model parameters
        timing_config = config.get("timing_model", {})
        self.lookback_periods = timing_config.get("lookback_periods", {
            "short": 24,    # 24 hours
            "medium": 168,  # 1 week
            "long": 720     # 30 days
        })
        
        self.trend_threshold = timing_config.get("trend_threshold", 0.02)
        self.volatility_threshold = timing_config.get("volatility_threshold", 0.05)
        self.volume_threshold = timing_config.get("volume_threshold", 1.5)  # 1.5x avg volume
        
        # Signal weighting
        self.indicator_weights = timing_config.get("indicator_weights", {
            "trend": 0.3,
            "momentum": 0.25,
            "mean_reversion": 0.2,
            "breakout": 0.15,
            "sentiment": 0.1
        })
    
    def analyze_timing(
        self,
        symbol: str,
        market_data: Dict[str, Any],
        price_history: Optional[List[Dict[str, Any]]] = None,
        sentiment_data: Optional[Dict[str, Any]] = None
    ) -> TimingAnalysis:
        """
        Analyze market timing for short entry/exit.
        
        Args:
            symbol: Trading pair symbol
            market_data: Current market data
            price_history: Historical price data
            sentiment_data: Market sentiment indicators
            
        Returns:
            Comprehensive timing analysis
        """
        try:
            # Extract current market state
            market_state = self._extract_market_state(market_data, price_history, sentiment_data)
            
            # Detect market regime
            regime = self._detect_market_regime(market_state, price_history)
            
            # Calculate technical indicators
            indicators = self._calculate_indicators(market_state, price_history)
            
            # Generate timing signals
            signal, confidence, reasoning = self._generate_signals(market_state, indicators, regime)
            
            # Calculate entry/exit scores
            entry_score = self._calculate_entry_score(signal, confidence, regime, indicators)
            exit_score = self._calculate_exit_score(signal, confidence, regime, indicators)
            
            # Estimate optimal hold duration
            hold_duration = self._estimate_hold_duration(regime, signal, indicators)
            
            # Identify key price levels
            key_levels = self._identify_key_levels(market_data, price_history)
            
            return TimingAnalysis(
                signal=signal,
                confidence=confidence,
                regime=regime,
                entry_score=entry_score,
                exit_score=exit_score,
                hold_duration_est=hold_duration,
                key_levels=key_levels,
                indicators=indicators,
                reasoning=reasoning
            )
            
        except Exception as e:
            self.logger.error(f"Error analyzing timing for {symbol}: {e}")
            return self._default_timing_analysis()
    
    def should_enter_short(self, analysis: TimingAnalysis, min_confidence: float = 0.6) -> bool:
        """
        Determine if now is a good time to enter a short position.
        
        Args:
            analysis: Timing analysis result
            min_confidence: Minimum confidence threshold
            
        Returns:
            True if should enter short
        """
        return (
            analysis.signal in [TimingSignal.STRONG_SHORT, TimingSignal.WEAK_SHORT] and
            analysis.confidence >= min_confidence and
            analysis.entry_score >= 0.6 and
            analysis.regime in [MarketRegime.BEAR_WEAK, MarketRegime.BEAR_STRONG, MarketRegime.VOLATILE]
        )
    
    def should_exit_short(self, analysis: TimingAnalysis, current_pnl: float = 0.0) -> bool:
        """
        Determine if should exit current short position.
        
        Args:
            analysis: Current timing analysis
            current_pnl: Current P&L of position (positive = profit)
            
        Returns:
            True if should exit
        """
        # Exit on signal reversal
        if analysis.signal in [TimingSignal.STRONG_LONG, TimingSignal.WEAK_LONG]:
            return True
        
        # Exit on high exit score
        if analysis.exit_score >= 0.7:
            return True
        
        # Exit on regime change to strong bull
        if analysis.regime == MarketRegime.BULL_STRONG:
            return True
        
        # Take profit on good gains
        if current_pnl > 0.05:  # 5% profit
            return True
        
        return False
    
    def _extract_market_state(
        self,
        market_data: Dict[str, Any],
        price_history: Optional[List[Dict[str, Any]]],
        sentiment_data: Optional[Dict[str, Any]]
    ) -> MarketState:
        """Extract current market state from data."""
        try:
            price = market_data.get("price", market_data.get("last", 0))
            volume_24h = market_data.get("volume_24h", market_data.get("baseVolume", 0))
            
            # Calculate basic metrics
            volatility = self._calculate_volatility(price_history) if price_history else 0.02
            trend_strength = self._calculate_trend_strength(price_history) if price_history else 0.0
            momentum = self._calculate_momentum(price_history) if price_history else 0.0
            
            # Technical signals
            mean_reversion_signal = self._calculate_mean_reversion(price_history) if price_history else 0.0
            breakout_signal = self._calculate_breakout_signal(price_history) if price_history else 0.0
            
            # Sentiment
            sentiment_score = sentiment_data.get("composite_score", 0.5) if sentiment_data else 0.5
            
            return MarketState(
                price=price,
                volume_24h=volume_24h,
                volatility=volatility,
                trend_strength=trend_strength,
                momentum=momentum,
                mean_reversion_signal=mean_reversion_signal,
                breakout_signal=breakout_signal,
                sentiment_score=sentiment_score
            )
            
        except Exception as e:
            self.logger.error(f"Error extracting market state: {e}")
            return MarketState(
                price=0, volume_24h=0, volatility=0.02, trend_strength=0,
                momentum=0, mean_reversion_signal=0, breakout_signal=0, sentiment_score=0.5
            )
    
    def _detect_market_regime(
        self,
        market_state: MarketState,
        price_history: Optional[List[Dict[str, Any]]]
    ) -> MarketRegime:
        """Detect current market regime."""
        try:
            trend = market_state.trend_strength
            volatility = market_state.volatility
            
            # High volatility regime
            if volatility > self.volatility_threshold * 2:
                return MarketRegime.VOLATILE
            
            # Trending regimes
            if abs(trend) > self.trend_threshold:
                if trend > 0:  # Uptrend
                    if trend > self.trend_threshold * 2:
                        return MarketRegime.BULL_STRONG
                    else:
                        return MarketRegime.BULL_WEAK
                else:  # Downtrend
                    if trend < -self.trend_threshold * 2:
                        return MarketRegime.BEAR_STRONG
                    else:
                        return MarketRegime.BEAR_WEAK
            
            # Sideways market
            return MarketRegime.SIDEWAYS
            
        except Exception:
            return MarketRegime.SIDEWAYS
    
    def _calculate_indicators(
        self,
        market_state: MarketState,
        price_history: Optional[List[Dict[str, Any]]]
    ) -> Dict[str, float]:
        """Calculate technical indicators."""
        indicators = {
            "rsi": self._calculate_rsi(price_history),
            "macd": self._calculate_macd(price_history),
            "bollinger_position": self._calculate_bollinger_position(price_history),
            "volume_ratio": self._calculate_volume_ratio(market_state, price_history),
            "price_momentum": market_state.momentum,
            "trend_strength": market_state.trend_strength
        }
        
        return {k: v for k, v in indicators.items() if v is not None}
    
    def _generate_signals(
        self,
        market_state: MarketState,
        indicators: Dict[str, float],
        regime: MarketRegime
    ) -> Tuple[TimingSignal, float, List[str]]:
        """Generate timing signals with confidence and reasoning."""
        reasoning = []
        signal_scores = []
        
        # Trend-based signals
        trend = market_state.trend_strength
        if trend < -self.trend_threshold:
            signal_scores.append(-abs(trend) * 2)  # Negative for short signal
            reasoning.append(f"Downtrend detected (strength: {trend:.3f})")
        elif trend > self.trend_threshold:
            signal_scores.append(abs(trend) * 2)  # Positive for long signal
            reasoning.append(f"Uptrend detected (strength: {trend:.3f})")
        
        # Momentum signals
        momentum = market_state.momentum
        if momentum < -0.02:
            signal_scores.append(-abs(momentum) * 10)
            reasoning.append(f"Negative momentum ({momentum:.3f})")
        elif momentum > 0.02:
            signal_scores.append(abs(momentum) * 10)
            reasoning.append(f"Positive momentum ({momentum:.3f})")
        
        # RSI signals
        rsi = indicators.get("rsi", 50)
        if rsi > 70:
            signal_scores.append(-0.5)  # Overbought = short signal
            reasoning.append(f"Overbought RSI ({rsi:.1f})")
        elif rsi < 30:
            signal_scores.append(0.5)  # Oversold = long signal
            reasoning.append(f"Oversold RSI ({rsi:.1f})")
        
        # Bollinger Band position
        bb_pos = indicators.get("bollinger_position", 0.5)
        if bb_pos > 0.8:
            signal_scores.append(-0.3)  # Near upper band = short signal
            reasoning.append("Price near Bollinger upper band")
        elif bb_pos < 0.2:
            signal_scores.append(0.3)  # Near lower band = long signal
            reasoning.append("Price near Bollinger lower band")
        
        # Aggregate signal
        if not signal_scores:
            return TimingSignal.NEUTRAL, 0.5, ["No clear signals"]
        
        avg_signal = sum(signal_scores) / len(signal_scores)
        confidence = min(abs(avg_signal), 1.0)
        
        # Convert to signal enum
        if avg_signal < -0.6:
            signal = TimingSignal.STRONG_SHORT
        elif avg_signal < -0.2:
            signal = TimingSignal.WEAK_SHORT
        elif avg_signal > 0.6:
            signal = TimingSignal.STRONG_LONG
        elif avg_signal > 0.2:
            signal = TimingSignal.WEAK_LONG
        else:
            signal = TimingSignal.NEUTRAL
        
        return signal, confidence, reasoning
    
    def _calculate_entry_score(
        self,
        signal: TimingSignal,
        confidence: float,
        regime: MarketRegime,
        indicators: Dict[str, float]
    ) -> float:
        """Calculate entry score for short positions."""
        base_score = 0.0
        
        # Signal strength
        if signal == TimingSignal.STRONG_SHORT:
            base_score = 0.8
        elif signal == TimingSignal.WEAK_SHORT:
            base_score = 0.6
        elif signal == TimingSignal.NEUTRAL:
            base_score = 0.4
        else:
            base_score = 0.2  # Long signals = poor short entry
        
        # Regime adjustment
        regime_multipliers = {
            MarketRegime.BEAR_STRONG: 1.2,
            MarketRegime.BEAR_WEAK: 1.1,
            MarketRegime.VOLATILE: 1.0,
            MarketRegime.SIDEWAYS: 0.9,
            MarketRegime.BULL_WEAK: 0.7,
            MarketRegime.BULL_STRONG: 0.5
        }
        
        base_score *= regime_multipliers.get(regime, 1.0)
        
        # Confidence adjustment
        base_score *= confidence
        
        return min(max(base_score, 0.0), 1.0)
    
    def _calculate_exit_score(
        self,
        signal: TimingSignal,
        confidence: float,
        regime: MarketRegime,
        indicators: Dict[str, float]
    ) -> float:
        """Calculate exit score for current short positions."""
        base_score = 0.0
        
        # Signal-based exit
        if signal in [TimingSignal.STRONG_LONG, TimingSignal.WEAK_LONG]:
            base_score = 0.7
        elif signal == TimingSignal.NEUTRAL:
            base_score = 0.4
        else:
            base_score = 0.2  # Short signals = don't exit yet
        
        # Regime-based exit
        if regime in [MarketRegime.BULL_STRONG, MarketRegime.BULL_WEAK]:
            base_score += 0.3
        
        # Technical indicator exits
        rsi = indicators.get("rsi", 50)
        if rsi < 30:  # Oversold = exit short
            base_score += 0.2
        
        bb_pos = indicators.get("bollinger_position", 0.5)
        if bb_pos < 0.2:  # Near lower band = exit short
            base_score += 0.2
        
        return min(max(base_score, 0.0), 1.0)
    
    def _estimate_hold_duration(
        self,
        regime: MarketRegime,
        signal: TimingSignal,
        indicators: Dict[str, float]
    ) -> timedelta:
        """Estimate optimal hold duration for short position."""
        base_hours = {
            MarketRegime.BEAR_STRONG: 72,    # 3 days
            MarketRegime.BEAR_WEAK: 48,      # 2 days
            MarketRegime.VOLATILE: 24,       # 1 day
            MarketRegime.SIDEWAYS: 36,       # 1.5 days
            MarketRegime.BULL_WEAK: 12,      # 0.5 days
            MarketRegime.BULL_STRONG: 6      # 0.25 days
        }.get(regime, 24)
        
        # Adjust based on signal strength
        if signal == TimingSignal.STRONG_SHORT:
            base_hours *= 1.5
        elif signal == TimingSignal.WEAK_SHORT:
            base_hours *= 1.2
        
        return timedelta(hours=base_hours)
    
    def _identify_key_levels(
        self,
        market_data: Dict[str, Any],
        price_history: Optional[List[Dict[str, Any]]]
    ) -> Dict[str, float]:
        """Identify key support and resistance levels."""
        current_price = market_data.get("price", market_data.get("last", 0))
        
        if not price_history or not current_price:
            return {
                "support": current_price * 0.98,
                "resistance": current_price * 1.02
            }
        
        try:
            prices = [candle.get("close", candle.get("price", 0)) for candle in price_history[-100:]]
            prices = [p for p in prices if p > 0]
            
            if not prices:
                return {
                    "support": current_price * 0.98,
                    "resistance": current_price * 1.02
                }
            
            # Simple support/resistance calculation
            recent_high = max(prices[-20:]) if len(prices) >= 20 else max(prices)
            recent_low = min(prices[-20:]) if len(prices) >= 20 else min(prices)
            
            # Calculate pivot levels
            pivot = (recent_high + recent_low + current_price) / 3
            resistance_1 = 2 * pivot - recent_low
            support_1 = 2 * pivot - recent_high
            
            return {
                "support": support_1,
                "resistance": resistance_1,
                "pivot": pivot,
                "recent_high": recent_high,
                "recent_low": recent_low
            }
            
        except Exception as e:
            self.logger.error(f"Error calculating key levels: {e}")
            return {
                "support": current_price * 0.98,
                "resistance": current_price * 1.02
            }
    
    # Technical Indicator Calculations
    def _calculate_volatility(self, price_history: List[Dict[str, Any]]) -> float:
        """Calculate historical volatility."""
        if not price_history or len(price_history) < 2:
            return 0.02
        
        try:
            prices = [candle.get("close", candle.get("price", 0)) for candle in price_history[-24:]]
            if len(prices) < 2:
                return 0.02
            
            returns = [(prices[i] / prices[i-1] - 1) for i in range(1, len(prices)) if prices[i-1] > 0]
            if not returns:
                return 0.02
            
            mean_return = sum(returns) / len(returns)
            variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
            
            return variance ** 0.5
            
        except Exception:
            return 0.02
    
    def _calculate_trend_strength(self, price_history: List[Dict[str, Any]]) -> float:
        """Calculate trend strength (-1 to 1, negative = downtrend)."""
        if not price_history or len(price_history) < 10:
            return 0.0
        
        try:
            prices = [candle.get("close", candle.get("price", 0)) for candle in price_history[-20:]]
            if len(prices) < 10:
                return 0.0
            
            # Simple linear regression slope
            n = len(prices)
            x_sum = sum(range(n))
            y_sum = sum(prices)
            xy_sum = sum(i * prices[i] for i in range(n))
            x2_sum = sum(i * i for i in range(n))
            
            slope = (n * xy_sum - x_sum * y_sum) / (n * x2_sum - x_sum * x_sum)
            
            # Normalize by average price
            avg_price = y_sum / n
            normalized_slope = slope / avg_price if avg_price > 0 else 0
            
            return max(-1.0, min(1.0, normalized_slope * 100))  # Scale to reasonable range
            
        except Exception:
            return 0.0
    
    def _calculate_momentum(self, price_history: List[Dict[str, Any]]) -> float:
        """Calculate price momentum."""
        if not price_history or len(price_history) < 5:
            return 0.0
        
        try:
            prices = [candle.get("close", candle.get("price", 0)) for candle in price_history[-5:]]
            if len(prices) < 5:
                return 0.0
            
            # 5-period momentum
            momentum = (prices[-1] / prices[0] - 1) if prices[0] > 0 else 0
            return max(-0.5, min(0.5, momentum))  # Cap at +/-50%
            
        except Exception:
            return 0.0
    
    def _calculate_mean_reversion(self, price_history: List[Dict[str, Any]]) -> float:
        """Calculate mean reversion signal."""
        if not price_history or len(price_history) < 20:
            return 0.0
        
        try:
            prices = [candle.get("close", candle.get("price", 0)) for candle in price_history[-20:]]
            if len(prices) < 20:
                return 0.0
            
            current_price = prices[-1]
            avg_price = sum(prices) / len(prices)
            
            # Distance from mean as percentage
            if avg_price > 0:
                deviation = (current_price - avg_price) / avg_price
                return -deviation  # Negative deviation = mean reversion up (bad for shorts)
            
            return 0.0
            
        except Exception:
            return 0.0
    
    def _calculate_breakout_signal(self, price_history: List[Dict[str, Any]]) -> float:
        """Calculate breakout signal."""
        if not price_history or len(price_history) < 20:
            return 0.0
        
        try:
            prices = [candle.get("close", candle.get("price", 0)) for candle in price_history[-20:]]
            if len(prices) < 20:
                return 0.0
            
            current_price = prices[-1]
            recent_high = max(prices[-10:])
            recent_low = min(prices[-10:])
            
            # Breakout above recent high = positive signal (bad for shorts)
            # Breakdown below recent low = negative signal (good for shorts)
            if recent_high > recent_low:
                range_position = (current_price - recent_low) / (recent_high - recent_low)
                return (range_position - 0.5) * 2  # Scale to -1 to 1
            
            return 0.0
            
        except Exception:
            return 0.0
    
    def _calculate_rsi(self, price_history: Optional[List[Dict[str, Any]]]) -> Optional[float]:
        """Calculate RSI indicator."""
        if not price_history or len(price_history) < 15:
            return None
        
        try:
            prices = [candle.get("close", candle.get("price", 0)) for candle in price_history[-15:]]
            if len(prices) < 15:
                return None
            
            # Calculate price changes
            changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]
            
            gains = [change if change > 0 else 0 for change in changes]
            losses = [-change if change < 0 else 0 for change in changes]
            
            avg_gain = sum(gains) / len(gains) if gains else 0
            avg_loss = sum(losses) / len(losses) if losses else 0
            
            if avg_loss == 0:
                return 100  # No losses = RSI 100
            
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            
            return rsi
            
        except Exception:
            return None
    
    def _calculate_macd(self, price_history: Optional[List[Dict[str, Any]]]) -> Optional[float]:
        """Calculate MACD indicator."""
        if not price_history or len(price_history) < 26:
            return None
        
        try:
            prices = [candle.get("close", candle.get("price", 0)) for candle in price_history[-26:]]
            if len(prices) < 26:
                return None
            
            # Simple MACD calculation (12-period EMA - 26-period EMA)
            ema_12 = self._calculate_ema(prices[-12:], 12)
            ema_26 = self._calculate_ema(prices, 26)
            
            if ema_12 is not None and ema_26 is not None:
                return ema_12 - ema_26
            
            return None
            
        except Exception:
            return None
    
    def _calculate_bollinger_position(self, price_history: Optional[List[Dict[str, Any]]]) -> Optional[float]:
        """Calculate position within Bollinger Bands."""
        if not price_history or len(price_history) < 20:
            return None
        
        try:
            prices = [candle.get("close", candle.get("price", 0)) for candle in price_history[-20:]]
            if len(prices) < 20:
                return None
            
            current_price = prices[-1]
            sma = sum(prices) / len(prices)
            
            # Calculate standard deviation
            variance = sum((price - sma) ** 2 for price in prices) / len(prices)
            std_dev = variance ** 0.5
            
            upper_band = sma + (2 * std_dev)
            lower_band = sma - (2 * std_dev)
            
            if upper_band > lower_band:
                position = (current_price - lower_band) / (upper_band - lower_band)
                return max(0.0, min(1.0, position))
            
            return 0.5
            
        except Exception:
            return None
    
    def _calculate_volume_ratio(
        self,
        market_state: MarketState,
        price_history: Optional[List[Dict[str, Any]]]
    ) -> Optional[float]:
        """Calculate current volume vs average volume ratio."""
        if not price_history or len(price_history) < 10:
            return None
        
        try:
            volumes = [candle.get("volume", 0) for candle in price_history[-10:]]
            avg_volume = sum(volumes) / len(volumes) if volumes else 1
            
            current_volume = market_state.volume_24h
            ratio = current_volume / avg_volume if avg_volume > 0 else 1.0
            
            return ratio
            
        except Exception:
            return None
    
    def _calculate_ema(self, prices: List[float], period: int) -> Optional[float]:
        """Calculate Exponential Moving Average."""
        if len(prices) < period:
            return None
        
        try:
            multiplier = 2 / (period + 1)
            ema = prices[0]  # Start with first price
            
            for price in prices[1:]:
                ema = (price * multiplier) + (ema * (1 - multiplier))
            
            return ema
            
        except Exception:
            return None
    
    def _default_timing_analysis(self) -> TimingAnalysis:
        """Return default timing analysis when calculation fails."""
        return TimingAnalysis(
            signal=TimingSignal.NEUTRAL,
            confidence=0.5,
            regime=MarketRegime.SIDEWAYS,
            entry_score=0.3,
            exit_score=0.5,
            hold_duration_est=timedelta(hours=24),
            key_levels={"support": 0, "resistance": 0},
            indicators={},
            reasoning=["Analysis failed, using defaults"]
        )