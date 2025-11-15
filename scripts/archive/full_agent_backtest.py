#!/usr/bin/env python3
from __future__ import annotations

"""
⚠️ SAFETY: No live trading unless MODE=live and confirmation set.
Complete Multi-Agent Crypto Trading Bot Ecosystem
Tests ALL agents working together: AI Engine, Signal Analyst, Risk Manager,
Execution Agent, Performance Monitor, and specialized agents
"""

import argparse
import json
import logging
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1] if Path(__file__).parent.name == "scripts" else Path.cwd()
OUT_DIR = ROOT / "reports" / "comprehensive_backtest"
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
    meta: Dict[str, Any] = field(default_factory=dict)

@dataclass
class MarketRegime:
    trend: str  # "bull", "bear", "sideways"
    volatility: str  # "low", "medium", "high"
    confidence: float
    indicators: Dict[str, float]

class RedisContextManager:
    """Advanced Redis Cloud context management for agent coordination"""
    
    def __init__(self, redis_url: str, namespace: str = "crypto_bot"):
        self.namespace = namespace
        self.connected = False
        
        if redis_url and redis_url.startswith(('redis://', 'rediss://')):
            try:
                import redis
                self.redis = redis.from_url(
                    redis_url,
                    decode_responses=True,
                    socket_connect_timeout=10,
                    ssl_cert_reqs=None,
                    ssl_ca_certs=None,
                    ssl_check_hostname=False
                )
                
                self.redis.ping()
                self.connected = True
                logger.info("🔗 AI Engine connected to Redis Cloud")
                
                # Initialize agent coordination channels
                self._setup_agent_channels()
                
            except Exception as e:
                logger.warning(f"Redis connection failed: {e}")
                self.redis = {}
                self.connected = False
        else:
            self.redis = {}
            logger.info("Using local memory for agent coordination")
    
    def _setup_agent_channels(self):
        """Setup communication channels between agents"""
        channels = [
            "signals", "regime_updates", "risk_alerts", 
            "performance_metrics", "execution_reports"
        ]
        for channel in channels:
            try:
                self.redis.delete(f"{self.namespace}:{channel}")
            except:
                pass
    
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
    
    def publish_agent_message(self, channel: str, message: Dict[str, Any]):
        """Publish message for agent coordination"""
        if self.connected:
            try:
                self.redis.publish(f"{self.namespace}:{channel}", json.dumps(message))
            except:
                pass

class AIEngine:
    """Central AI Engine - coordinates all agents and makes meta-decisions"""
    
    def __init__(self, context_manager: RedisContextManager):
        self.context = context_manager
        self.regime_detector = RegimeDetector()
        self.strategy_selector = StrategySelector()
        self.adaptive_learner = AdaptiveLearner()
        
        logger.info("🧠 AI Engine initialized")
    
    def analyze_market_state(self, market_data: Dict[str, pd.DataFrame], timestamp) -> Dict[str, Any]:
        """Comprehensive market analysis using all available data"""
        
        # Multi-timeframe regime detection
        regimes = {}
        overall_sentiment = []
        
        for symbol, df in market_data.items():
            regime = self.regime_detector.analyze_regime(df.loc[:timestamp])
            regimes[symbol] = regime
            
            # Store regime in context for other agents
            self.context.set_context(f"regime:{symbol}", {
                'trend': regime.trend,
                'volatility': regime.volatility,
                'confidence': regime.confidence,
                'indicators': regime.indicators,
                'timestamp': timestamp.isoformat()
            })
            
            overall_sentiment.append(regime.confidence if regime.trend == "bull" else -regime.confidence)
        
        # Calculate market-wide sentiment
        market_sentiment = np.mean(overall_sentiment) if overall_sentiment else 0.0
        
        # Determine optimal strategy allocation
        strategy_weights = self.strategy_selector.optimize_allocation(regimes, market_sentiment)
        
        # Store AI analysis for other agents
        ai_state = {
            'market_sentiment': market_sentiment,
            'dominant_regime': max(regimes.items(), key=lambda x: x[1].confidence)[1].trend if regimes else "sideways",
            'strategy_weights': strategy_weights,
            'risk_level': self._calculate_risk_level(regimes),
            'timestamp': timestamp.isoformat()
        }
        
        self.context.set_context("ai_engine_state", ai_state)
        self.context.publish_agent_message("regime_updates", ai_state)
        
        return ai_state
    
    def _calculate_risk_level(self, regimes: Dict[str, MarketRegime]) -> str:
        """Calculate overall market risk level"""
        if not regimes:
            return "medium"
        
        high_vol_count = sum(1 for r in regimes.values() if r.volatility == "high")
        total_count = len(regimes)
        
        if high_vol_count / total_count > 0.6:
            return "high"
        elif high_vol_count / total_count < 0.3:
            return "low"
        else:
            return "medium"

class RegimeDetector:
    """Advanced market regime detection using multiple indicators"""
    
    def __init__(self):
        self.lookback = 50
    
    def analyze_regime(self, df: pd.DataFrame) -> MarketRegime:
        if len(df) < self.lookback:
            return MarketRegime("sideways", "medium", 0.5, {})
        
        df = df.copy()
        
        # Calculate multiple timeframe indicators
        df['sma_20'] = df['close'].rolling(20).mean()
        df['sma_50'] = df['close'].rolling(50).mean()
        df['ema_12'] = df['close'].ewm(span=12).mean()
        df['ema_26'] = df['close'].ewm(span=26).mean()
        
        # Volatility indicators
        df['atr'] = self._calculate_atr(df, 14)
        df['bb_width'] = self._calculate_bb_width(df, 20)
        
        # Momentum indicators
        df['rsi'] = self._calculate_rsi(df['close'], 14)
        df['macd'] = df['ema_12'] - df['ema_26']
        df['macd_signal'] = df['macd'].ewm(span=9).mean()
        
        # Volume analysis
        df['volume_sma'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_sma']
        
        latest = df.iloc[-1]
        
        # Advanced trend determination
        trend_signals = []
        
        # Price vs moving averages
        if latest['close'] > latest['sma_20'] > latest['sma_50']:
            trend_signals.append(("bull", 0.8))
        elif latest['close'] < latest['sma_20'] < latest['sma_50']:
            trend_signals.append(("bear", 0.8))
        else:
            trend_signals.append(("sideways", 0.6))
        
        # MACD analysis
        if latest['macd'] > latest['macd_signal'] and latest['macd'] > 0:
            trend_signals.append(("bull", 0.7))
        elif latest['macd'] < latest['macd_signal'] and latest['macd'] < 0:
            trend_signals.append(("bear", 0.7))
        else:
            trend_signals.append(("sideways", 0.5))
        
        # RSI momentum
        if latest['rsi'] > 60:
            trend_signals.append(("bull", 0.6))
        elif latest['rsi'] < 40:
            trend_signals.append(("bear", 0.6))
        else:
            trend_signals.append(("sideways", 0.5))
        
        # Aggregate trend signals
        bull_score = sum(conf for trend, conf in trend_signals if trend == "bull")
        bear_score = sum(conf for trend, conf in trend_signals if trend == "bear")
        sideways_score = sum(conf for trend, conf in trend_signals if trend == "sideways")
        
        if bull_score > bear_score and bull_score > sideways_score:
            trend = "bull"
            confidence = min(bull_score / len(trend_signals), 1.0)
        elif bear_score > bull_score and bear_score > sideways_score:
            trend = "bear"
            confidence = min(bear_score / len(trend_signals), 1.0)
        else:
            trend = "sideways"
            confidence = min(sideways_score / len(trend_signals), 1.0)
        
        # Volatility classification
        atr_pct = latest['atr'] / latest['close']
        bb_width_norm = latest['bb_width'] / latest['close']
        
        if atr_pct > 0.04 or bb_width_norm > 0.15:
            volatility = "high"
        elif atr_pct < 0.02 and bb_width_norm < 0.08:
            volatility = "low"
        else:
            volatility = "medium"
        
        return MarketRegime(
            trend=trend,
            volatility=volatility,
            confidence=confidence,
            indicators={
                "rsi": float(latest['rsi']),
                "atr_pct": float(atr_pct),
                "bb_width": float(bb_width_norm),
                "macd": float(latest['macd']),
                "volume_ratio": float(latest['volume_ratio']),
                "sma_ratio": float(latest['sma_20'] / latest['sma_50'])
            }
        )
    
    def _calculate_atr(self, df: pd.DataFrame, period: int) -> pd.Series:
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        true_range = np.maximum(high_low, np.maximum(high_close, low_close))
        return true_range.rolling(period).mean()
    
    def _calculate_rsi(self, prices: pd.Series, period: int) -> pd.Series:
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))
    
    def _calculate_bb_width(self, df: pd.DataFrame, period: int) -> pd.Series:
        sma = df['close'].rolling(period).mean()
        std = df['close'].rolling(period).std()
        upper = sma + (std * 2)
        lower = sma - (std * 2)
        return upper - lower

class StrategySelector:
    """AI-powered strategy selection and allocation optimization"""
    
    def __init__(self):
        self.strategy_performance = {}
        
    def optimize_allocation(self, regimes: Dict[str, MarketRegime], market_sentiment: float) -> Dict[str, float]:
        """Dynamically optimize strategy allocation based on market conditions"""
        
        base_allocation = {
            'trend_following': 0.35,
            'breakout': 0.30,
            'momentum': 0.25,
            'mean_reversion': 0.10
        }
        
        # Adjust based on dominant regime
        if not regimes:
            return base_allocation
        
        dominant_trend = max(regimes.values(), key=lambda x: x.confidence).trend
        avg_volatility = np.mean([1 if r.volatility == "high" else 0.5 if r.volatility == "medium" else 0 
                                 for r in regimes.values()])
        
        adjusted = base_allocation.copy()
        
        # Bull market adjustments
        if dominant_trend == "bull" and market_sentiment > 0.3:
            adjusted['trend_following'] += 0.10
            adjusted['momentum'] += 0.05
            adjusted['mean_reversion'] -= 0.15
        
        # Bear market adjustments
        elif dominant_trend == "bear" and market_sentiment < -0.3:
            adjusted['mean_reversion'] += 0.15
            adjusted['trend_following'] -= 0.10
            adjusted['momentum'] -= 0.05
        
        # High volatility adjustments
        if avg_volatility > 0.7:
            adjusted['breakout'] += 0.10
            adjusted['trend_following'] -= 0.05
            adjusted['momentum'] -= 0.05
        
        # Normalize to sum to 1.0
        total = sum(adjusted.values())
        if total > 0:
            adjusted = {k: v/total for k, v in adjusted.items()}
        
        return adjusted

class AdaptiveLearner:
    """Learns from performance and adapts strategies"""
    
    def __init__(self):
        self.performance_history = []
        self.strategy_scores = {}
    
    def update_performance(self, strategy: str, return_pct: float, confidence: float):
        """Update strategy performance tracking"""
        score = return_pct * confidence
        if strategy not in self.strategy_scores:
            self.strategy_scores[strategy] = []
        self.strategy_scores[strategy].append(score)
        
        # Keep only recent performance (last 100 trades)
        if len(self.strategy_scores[strategy]) > 100:
            self.strategy_scores[strategy] = self.strategy_scores[strategy][-100:]

class SignalAnalyst:
    """Advanced signal analysis and filtering agent"""
    
    def __init__(self, context_manager: RedisContextManager):
        self.context = context_manager
        self.min_confidence = 0.65
        logger.info("📡 Signal Analyst Agent activated")
    
    def analyze_signal(self, signal: Signal, market_state: Dict[str, Any]) -> Optional[Signal]:
        """Advanced signal analysis with AI engine context"""
        
        # Get current market regime
        regime_data = self.context.get_context(f"regime:{signal.symbol}")
        if not regime_data:
            return None
        
        # Apply regime-based filters
        enhanced_signal = self._apply_regime_filters(signal, regime_data, market_state)
        if not enhanced_signal:
            return None
        
        # Apply confidence boosting based on market conditions
        enhanced_signal = self._boost_confidence(enhanced_signal, regime_data, market_state)
        
        # Final confidence check
        if enhanced_signal.confidence < self.min_confidence:
            return None
        
        # Log signal analysis
        self.context.set_context(f"signal_analysis:{signal.symbol}:{datetime.now().isoformat()}", {
            'original_confidence': signal.confidence,
            'enhanced_confidence': enhanced_signal.confidence,
            'regime': regime_data['trend'],
            'strategy': signal.strategy
        })
        
        return enhanced_signal
    
    def _apply_regime_filters(self, signal: Signal, regime: Dict[str, Any], market_state: Dict[str, Any]) -> Optional[Signal]:
        """Apply regime-specific signal filters"""
        
        # Bull market filters
        if regime['trend'] == 'bull' and signal.side == 'buy':
            signal.confidence *= 1.1  # Boost buy signals in bull markets
        elif regime['trend'] == 'bull' and signal.side == 'sell':
            signal.confidence *= 0.8  # Reduce sell signals in bull markets
        
        # Bear market filters
        elif regime['trend'] == 'bear' and signal.side == 'sell':
            signal.confidence *= 1.1  # Boost sell signals in bear markets
        elif regime['trend'] == 'bear' and signal.side == 'buy':
            signal.confidence *= 0.7  # Reduce buy signals in bear markets
        
        # High volatility filters
        if regime['volatility'] == 'high':
            signal.confidence *= 0.9  # Slightly reduce confidence in high vol
            signal.size_quote_usd *= 0.8  # Reduce position size
        
        return signal if signal.confidence > 0.4 else None
    
    def _boost_confidence(self, signal: Signal, regime: Dict[str, Any], market_state: Dict[str, Any]) -> Signal:
        """Apply confidence boosting based on multiple factors"""
        
        # Strategy-regime alignment bonus
        if signal.strategy == 'trend_following' and regime['trend'] != 'sideways':
            signal.confidence *= 1.05
        elif signal.strategy == 'breakout' and regime['volatility'] == 'high':
            signal.confidence *= 1.08
        elif signal.strategy == 'momentum' and abs(market_state.get('market_sentiment', 0)) > 0.5:
            signal.confidence *= 1.06
        
        # Volume confirmation
        if regime.get('indicators', {}).get('volume_ratio', 1) > 1.2:
            signal.confidence *= 1.03
        
        return signal

class RiskManager:
    """Advanced multi-layer risk management agent"""
    
    def __init__(self, context_manager: RedisContextManager, portfolio_ref):
        self.context = context_manager
        self.portfolio = portfolio_ref
        self.risk_metrics = {}
        logger.info("🛡️ Risk Manager Agent activated")
    
    def evaluate_risk(self, signal: Signal, market_state: Dict[str, Any]) -> Optional[Signal]:
        """Comprehensive risk evaluation"""
        
        # Portfolio-level risk checks
        if not self._check_portfolio_risk():
            self.context.publish_agent_message("risk_alerts", {
                'type': 'portfolio_risk_exceeded',
                'signal': signal.symbol,
                'timestamp': datetime.now().isoformat()
            })
            return None
        
        # Position concentration risk
        if not self._check_concentration_risk(signal):
            return None
        
        # Market regime risk adjustment
        signal = self._adjust_for_regime_risk(signal, market_state)
        
        # Dynamic position sizing
        signal = self._apply_dynamic_sizing(signal, market_state)
        
        # Update risk metrics
        self._update_risk_metrics(signal)
        
        return signal
    
    def _check_portfolio_risk(self) -> bool:
        """Check portfolio-level risk limits"""
        if self.portfolio.max_equity > 0:
            current_dd = (self.portfolio.equity / self.portfolio.max_equity) - 1.0
            if current_dd <= -0.15:  # 15% max drawdown
                return False
        return True
    
    def _check_concentration_risk(self, signal: Signal) -> bool:
        """Check position concentration limits"""
        # Get current position value
        current_positions = getattr(self.portfolio, 'positions', {})
        symbol_exposure = current_positions.get(signal.symbol, 0)
        
        # Check if new signal would exceed concentration limit (10% per symbol)
        max_symbol_exposure = self.portfolio.equity * 0.10
        if signal.side == 'buy' and symbol_exposure * 60000 > max_symbol_exposure:  # Rough BTC price
            return False
        
        return True
    
    def _adjust_for_regime_risk(self, signal: Signal, market_state: Dict[str, Any]) -> Signal:
        """Adjust signal based on regime risk"""
        risk_level = market_state.get('risk_level', 'medium')
        
        if risk_level == 'high':
            signal.size_quote_usd *= 0.7  # Reduce size in high risk
        elif risk_level == 'low':
            signal.size_quote_usd *= 1.2  # Increase size in low risk
        
        return signal
    
    def _apply_dynamic_sizing(self, signal: Signal, market_state: Dict[str, Any]) -> Signal:
        """Apply dynamic position sizing based on multiple factors"""
        
        # Base size as percentage of portfolio
        base_size_pct = 0.03  # 3%
        
        # Adjust based on confidence
        confidence_multiplier = signal.confidence / 0.75  # Normalize to confidence threshold
        
        # Adjust based on market conditions
        market_sentiment = market_state.get('market_sentiment', 0)
        sentiment_multiplier = 1.0 + (abs(market_sentiment) * 0.2)  # Up to 20% adjustment
        
        # Calculate final size
        final_size = self.portfolio.equity * base_size_pct * confidence_multiplier * sentiment_multiplier
        
        # Apply limits
        max_size = self.portfolio.equity * 0.08  # 8% max
        min_size = 50.0  # $50 minimum
        
        signal.size_quote_usd = max(min_size, min(final_size, max_size))
        
        return signal
    
    def _update_risk_metrics(self, signal: Signal):
        """Update risk tracking metrics"""
        self.risk_metrics[signal.symbol] = {
            'last_signal_size': signal.size_quote_usd,
            'last_confidence': signal.confidence,
            'timestamp': datetime.now().isoformat()
        }
        
        self.context.set_context("risk_metrics", self.risk_metrics)

class ExecutionAgent:
    """Advanced trade execution agent with market impact modeling"""
    
    def __init__(self, context_manager: RedisContextManager):
        self.context = context_manager
        self.execution_stats = {'fills': 0, 'rejections': 0}
        logger.info("⚡ Execution Agent activated")
    
    def execute_signal(self, signal: Signal, current_price: float, timestamp) -> Optional[Dict[str, Any]]:
        """Advanced execution with market impact and slippage modeling"""
        
        # Calculate market impact based on order size
        market_impact = self._calculate_market_impact(signal.size_quote_usd, current_price)
        
        # Apply slippage and fees
        base_slippage = 0.001  # 0.1%
        total_slippage = base_slippage + market_impact
        
        # Execution price
        if signal.side == 'buy':
            execution_price = current_price * (1 + total_slippage)
        else:
            execution_price = current_price * (1 - total_slippage)
        
        # Calculate quantities and fees
        quantity = signal.size_quote_usd / execution_price
        fee_rate = 0.0026  # Kraken taker fee
        fee = signal.size_quote_usd * fee_rate
        
        # Minimum order check
        if signal.size_quote_usd < 50.0:
            self.execution_stats['rejections'] += 1
            return None
        
        # Create execution report
        execution_report = {
            'timestamp': timestamp.isoformat(),
            'symbol': signal.symbol,
            'strategy': signal.strategy,
            'side': signal.side,
            'quantity': float(quantity),
            'price': float(execution_price),
            'notional': float(signal.size_quote_usd),
            'fee': float(fee),
            'slippage': float(total_slippage),
            'market_impact': float(market_impact),
            'confidence': float(signal.confidence),
            'meta': signal.meta
        }
        
        self.execution_stats['fills'] += 1
        
        # Store execution in context for performance analysis
        self.context.set_context(f"execution:{timestamp.isoformat()}:{signal.symbol}", execution_report)
        self.context.publish_agent_message("execution_reports", execution_report)
        
        return execution_report
    
    def _calculate_market_impact(self, order_size: float, price: float) -> float:
        """Calculate market impact based on order size"""
        # Simple market impact model: larger orders have higher impact
        order_value = order_size
        
        if order_value < 1000:
            return 0.0001  # 0.01% for small orders
        elif order_value < 5000:
            return 0.0002  # 0.02% for medium orders
        else:
            return 0.0005  # 0.05% for large orders

class PerformanceMonitor:
    """Real-time performance monitoring and analytics agent"""
    
    def __init__(self, context_manager: RedisContextManager):
        self.context = context_manager
        self.performance_history = []
        logger.info("📊 Performance Monitor Agent activated")
    
    def update_performance(self, portfolio, timestamp, market_prices):
        """Update performance metrics and analytics"""
        
        # Calculate current metrics
        if len(portfolio.history) > 1:
            equity_series = pd.Series([h['equity'] for h in portfolio.history])
            returns = equity_series.pct_change().fillna(0)
            
            # Real-time performance metrics
            current_return = (portfolio.equity / portfolio.start_balance) - 1.0
            volatility = returns.std() * math.sqrt(252 * 24) if len(returns) > 10 else 0
            sharpe = (returns.mean() / (returns.std() + 1e-9)) * math.sqrt(252 * 24) if len(returns) > 10 else 0
            max_drawdown = (equity_series / equity_series.cummax() - 1.0).min()
            
            performance_metrics = {
                'timestamp': timestamp.isoformat(),
                'current_return': float(current_return),
                'volatility': float(volatility),
                'sharpe_ratio': float(sharpe),
                'max_drawdown': float(max_drawdown),
                'equity': float(portfolio.equity),
                'total_trades': len(portfolio.trades),
                'win_rate': self._calculate_win_rate(portfolio.trades)
            }
            
            # Store metrics
            self.context.set_context("live_performance", performance_metrics)
            self.context.publish_agent_message("performance_metrics", performance_metrics)
            
            # Performance alerts
            if max_drawdown <= -0.10:  # 10% drawdown alert
                self.context.publish_agent_message("risk_alerts", {
                    'type': 'drawdown_alert',
                    'value': max_drawdown,
                    'timestamp': timestamp.isoformat()
                })
    
    def _calculate_win_rate(self, trades: List[Dict]) -> float:
        """Calculate current win rate"""
        if len(trades) < 2:
            return 0.0
        
        # Simple win rate calculation (assuming buy/sell pairs)
        wins = 0
        total_pairs = 0
        
        for i in range(0, len(trades) - 1, 2):
            if i + 1 < len(trades):
                buy_trade = trades[i]
                sell_trade = trades[i + 1]
                if (buy_trade.get('side') == 'buy' and sell_trade.get('side') == 'sell' and
                    sell_trade.get('price', 0) > buy_trade.get('price', 0)):
                    wins += 1
                total_pairs += 1
        
        return (wins / total_pairs) * 100 if total_pairs > 0 else 0.0

# Strategy implementations with enhanced AI integration
class EnhancedTrendFollowingStrategy:
    def __init__(self, context_manager: RedisContextManager):
        self.name = "trend_following"
        self.context = context_manager
    
    def generate_signal(self, df, context=None):
        if len(df) < 26:
            return None
        
        context = context or {}
        symbol = context.get('symbol', 'UNKNOWN')
        
        # Get AI engine state for enhanced decision making
        ai_state = self.context.get_context("ai_engine_state") or {}
        strategy_weight = ai_state.get('strategy_weights', {}).get(self.name, 0.35)
        
        # Enhanced EMA analysis
        df_copy = df.copy()
        df_copy['ema_12'] = df_copy['close'].ewm(span=12).mean()
        df_copy['ema_26'] = df_copy['close'].ewm(span=26).mean()
        df_copy['ema_50'] = df_copy['close'].ewm(span=50).mean()
        df_copy['volume_ma'] = df_copy['volume'].rolling(20).mean()
        
        current = df_copy.iloc[-1]
        prev = df_copy.iloc[-2]
        
        # AI-enhanced signal conditions
        trend_strength = abs(current['ema_12'] - current['ema_26']) / current['close']
        volume_confirmation = current['volume'] > current['volume_ma'] * 1.1
        
        # Generate signal with AI context
        if (current['ema_12'] > current['ema_26'] > current['ema_50'] and 
            prev['ema_12'] <= prev['ema_26'] and trend_strength > 0.005 and volume_confirmation):
            
            # AI-adjusted confidence
            base_confidence = 0.75
            ai_boost = strategy_weight * 0.2  # Up to 20% boost based on AI allocation
            
            return Signal(
                strategy=self.name,
                exchange="kraken",
                symbol=symbol,
                side='buy',
                confidence=min(base_confidence + ai_boost, 0.95),
                size_quote_usd=200.0,  # Base size, will be adjusted by risk manager
                meta={
                    'signal_type': 'trend_bullish_enhanced',
                    'trend_strength': trend_strength,
                    'ai_weight': strategy_weight,
                    'volume_ratio': current['volume'] / current['volume_ma']
                }
            )
        
        return None

class EnhancedBreakoutStrategy:
    def __init__(self, context_manager: RedisContextManager):
        self.name = "breakout"
        self.context = context_manager
    
    def generate_signal(self, df, context=None):
        if len(df) < 20:
            return None
        
        context = context or {}
        symbol = context.get('symbol', 'UNKNOWN')
        
        # Get regime data for enhanced breakout detection
        regime_data = self.context.get_context(f"regime:{symbol}") or {}
        volatility = regime_data.get('volatility', 'medium')
        
        df_copy = df.copy()
        lookback = 15 if volatility == 'high' else 20  # Adaptive lookback
        
        df_copy['resistance'] = df_copy['high'].rolling(lookback).max()
        df_copy['support'] = df_copy['low'].rolling(lookback).min()
        df_copy['volume_ma'] = df_copy['volume'].rolling(10).mean()
        df_copy['atr'] = df_copy['high'].subtract(df_copy['low']).rolling(14).mean()
        
        current = df_copy.iloc[-1]
        
        # Volatility-adjusted breakout threshold
        breakout_threshold = 1.002 if volatility == 'high' else 1.001
        volume_threshold = 1.3 if volatility == 'high' else 1.5
        
        # Enhanced breakout detection
        resistance_break = current['close'] > current['resistance'] * breakout_threshold
        volume_surge = current['volume'] > current['volume_ma'] * volume_threshold
        atr_confirmation = current['atr'] > df_copy['atr'].rolling(50).mean().iloc[-1]
        
        if resistance_break and volume_surge and atr_confirmation:
            confidence = 0.8 + (0.1 if volatility == 'high' else 0.0)
            
            return Signal(
                strategy=self.name,
                exchange="kraken",
                symbol=symbol,
                side='buy',
                confidence=confidence,
                size_quote_usd=180.0,
                meta={
                    'signal_type': 'resistance_breakout_enhanced',
                    'breakout_level': current['resistance'],
                    'volume_surge': current['volume'] / current['volume_ma'],
                    'regime_volatility': volatility
                }
            )
        
        return None

class EnhancedMomentumStrategy:
    def __init__(self, context_manager: RedisContextManager):
        self.name = "momentum"
        self.context = context_manager
    
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
        
        # Get market sentiment from AI engine
        ai_state = self.context.get_context("ai_engine_state") or {}
        market_sentiment = ai_state.get('market_sentiment', 0.0)
        
        df_copy = df.copy()
        df_copy['rsi'] = self.calculate_rsi(df_copy['close'])
        df_copy['price_change_5'] = df_copy['close'].pct_change(5)
        df_copy['volume_ratio'] = df_copy['volume'] / df_copy['volume'].rolling(20).mean()
        
        # Add momentum oscillator
        df_copy['momentum'] = df_copy['close'] / df_copy['close'].shift(10) - 1
        
        current = df_copy.iloc[-1]
        
        # Sentiment-adjusted momentum signals
        rsi_range = (35, 75) if market_sentiment > 0.3 else (25, 80)
        momentum_threshold = 0.01 if market_sentiment > 0.0 else 0.015
        
        # Enhanced momentum conditions
        if (rsi_range[0] < current['rsi'] < rsi_range[1] and 
            current['price_change_5'] > momentum_threshold and
            current['volume_ratio'] > 1.1 and
            current['momentum'] > 0.02):
            
            # Sentiment-boosted confidence
            base_confidence = 0.7
            sentiment_boost = abs(market_sentiment) * 0.15
            
            return Signal(
                strategy=self.name,
                exchange="kraken",
                symbol=symbol,
                side='buy',
                confidence=min(base_confidence + sentiment_boost, 0.9),
                size_quote_usd=150.0,
                meta={
                    'signal_type': 'momentum_bullish_enhanced',
                    'rsi': current['rsi'],
                    'momentum': current['momentum'],
                    'market_sentiment': market_sentiment
                }
            )
        
        return None

class Portfolio:
    """Enhanced portfolio with agent integration"""
    
    def __init__(self, start_balance: float, context_manager: RedisContextManager):
        self.start_balance = float(start_balance)
        self.cash = float(start_balance)
        self.positions = {}
        self.equity = float(start_balance)
        self.max_equity = float(start_balance)
        self.history = []
        self.trades = []
        self.signals = []
        self.context = context_manager

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
        
        # Store portfolio state in context for agents
        self.context.set_context("portfolio_state", {
            'equity': self.equity,
            'cash': self.cash,
            'positions': {k: float(v) for k, v in self.positions.items()},
            'max_equity': self.max_equity,
            'timestamp': timestamp.isoformat()
        })

    def execute_trade(self, execution_report: Dict[str, Any]) -> bool:
        """Execute trade from execution agent report"""
        symbol = execution_report['symbol']
        side = execution_report['side']
        qty = execution_report['quantity']
        price = execution_report['price']
        fee = execution_report['fee']
        
        if side == "buy":
            cost = qty * price + fee
            if cost <= self.cash:
                self.cash -= cost
                self.positions[symbol] = self.positions.get(symbol, 0) + qty
                self.trades.append(execution_report)
                return True
        elif side == "sell":
            current_position = self.positions.get(symbol, 0)
            if current_position >= qty:
                proceeds = qty * price - fee
                self.cash += proceeds
                self.positions[symbol] -= qty
                self.trades.append(execution_report)
                return True
        return False

def fetch_ohlcv_data(exchange_id: str, pair: str, timeframe: str, since_ms: Optional[int], limit: int):
    """Fetch OHLCV data from exchange"""
    try:
        import ccxt
        exchange = getattr(ccxt, exchange_id)()
        exchange.load_markets()
        
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
    """Calculate comprehensive performance metrics"""
    if len(equity_series) < 2:
        return {}
    
    returns = equity_series.pct_change().fillna(0.0)
    total_return = (equity_series.iloc[-1] / equity_series.iloc[0]) - 1.0
    
    if len(returns) > 1:
        volatility = returns.std() * math.sqrt(252 * 24)
        sharpe = returns.mean() / (volatility + 1e-9) * math.sqrt(252 * 24)
        sortino = returns.mean() / (returns[returns < 0].std() + 1e-9) * math.sqrt(252 * 24)
    else:
        volatility = sharpe = sortino = 0
    
    max_drawdown = (equity_series / equity_series.cummax() - 1.0).min()
    
    return {
        "total_return": round(total_return * 100, 2),
        "sharpe_ratio": round(sharpe, 3),
        "sortino_ratio": round(sortino, 3),
        "max_drawdown": round(max_drawdown * 100, 2),
        "volatility": round(volatility * 100, 2),
        "final_equity": round(float(equity_series.iloc[-1]), 2),
        "start_value": round(float(equity_series.iloc[0]), 2)
    }

def run_full_agent_backtest(args):
    """Run complete multi-agent ecosystem backtest"""
    fix_seeds(42)
    
    logger.info("🚀 Initializing Full Multi-Agent Ecosystem")
    logger.info("=" * 60)
    
    # Initialize Redis context manager
    context_manager = RedisContextManager(args.redis_url or "")
    
    # Initialize AI Engine and all agents
    ai_engine = AIEngine(context_manager)
    signal_analyst = SignalAnalyst(context_manager)
    execution_agent = ExecutionAgent(context_manager)
    
    # Initialize enhanced strategies with AI integration
    strategies = [
        ("trend_following", EnhancedTrendFollowingStrategy(context_manager)),
        ("breakout", EnhancedBreakoutStrategy(context_manager)),
        ("momentum", EnhancedMomentumStrategy(context_manager))
    ]
    
    logger.info("🧠 AI Engine: Activated")
    logger.info("📡 Signal Analyst: Activated") 
    logger.info("⚡ Execution Agent: Activated")
    logger.info(f"🎯 Enhanced Strategies: {len(strategies)} loaded")
    
    # Fetch market data
    logger.info("📊 Fetching market data...")
    market_data = {}
    
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
    
    # Align data and determine test period
    common_index = None
    for df in market_data.values():
        common_index = df.index if common_index is None else common_index.intersection(df.index)
    
    if args.days > 0:
        end_date = common_index[-1]
        start_date = end_date - pd.Timedelta(days=args.days)
        test_index = common_index[common_index >= start_date]
    else:
        test_index = common_index[-min(len(common_index), 1000):]
    
    logger.info(f"🔍 Full Agent Backtesting: {len(test_index)} periods")
    logger.info(f"⏰ Period: {test_index[0]} to {test_index[-1]}")
    
    # Initialize portfolio with agent integration
    portfolio = Portfolio(args.start, context_manager)
    risk_manager = RiskManager(context_manager, portfolio)
    performance_monitor = PerformanceMonitor(context_manager)
    
    logger.info("🛡️ Risk Manager: Activated")
    logger.info("📊 Performance Monitor: Activated")
    
    # Agent statistics
    agent_stats = {
        'ai_decisions': 0,
        'signals_generated': 0,
        'signals_filtered': 0,
        'risk_blocked': 0,
        'executions': 0,
        'regime_changes': 0
    }
    
    logger.info("\n🎬 Starting Multi-Agent Trading Simulation...")
    logger.info("=" * 60)
    
    # Main agent coordination loop
    for i, timestamp in enumerate(test_index):
        if i % 50 == 0:
            logger.info(f"🎯 Agent Cycle {i}/{len(test_index)} | "
                       f"Signals: {agent_stats['signals_generated']} | "
                       f"Executions: {agent_stats['executions']} | "
                       f"Regime Changes: {agent_stats['regime_changes']}")
        
        # Get current market prices
        current_prices = {}
        for symbol, df in market_data.items():
            if timestamp in df.index:
                current_prices[symbol] = float(df.at[timestamp, "close"])
        
        # AI Engine: Analyze market state and coordinate agents
        market_state = ai_engine.analyze_market_state(market_data, timestamp)
        agent_stats['ai_decisions'] += 1
        
        # Track regime changes
        if i > 0:
            prev_regime = context_manager.get_context("ai_engine_state")
            if prev_regime and prev_regime.get('dominant_regime') != market_state.get('dominant_regime'):
                agent_stats['regime_changes'] += 1
        
        # Update portfolio valuation
        portfolio.mark(current_prices, timestamp)
        
        # Performance Monitor: Real-time analytics
        performance_monitor.update_performance(portfolio, timestamp, current_prices)
        
        # Strategy Signal Generation with AI coordination
        for strategy_name, strategy in strategies:
            for symbol, df in market_data.items():
                if timestamp not in df.index:
                    continue
                
                historical_data = df.loc[:timestamp]
                if len(historical_data) < 20:
                    continue
                
                # Strategy generates signal
                try:
                    raw_signal = strategy.generate_signal(historical_data, {
                        'symbol': symbol,
                        'max_position': portfolio.equity * 0.1
                    })
                    
                    if raw_signal:
                        agent_stats['signals_generated'] += 1
                        
                        # Signal Analyst: Advanced filtering and enhancement
                        analyzed_signal = signal_analyst.analyze_signal(raw_signal, market_state)
                        if not analyzed_signal:
                            agent_stats['signals_filtered'] += 1
                            continue
                        
                        # Risk Manager: Multi-layer risk evaluation
                        risk_approved_signal = risk_manager.evaluate_risk(analyzed_signal, market_state)
                        if not risk_approved_signal:
                            agent_stats['risk_blocked'] += 1
                            continue
                        
                        # Execution Agent: Market-aware execution
                        if symbol in current_prices:
                            execution_report = execution_agent.execute_signal(
                                risk_approved_signal, current_prices[symbol], timestamp
                            )
                            
                            if execution_report:
                                # Portfolio executes the trade
                                if portfolio.execute_trade(execution_report):
                                    agent_stats['executions'] += 1
                                    
                                    # Store signal for analysis
                                    portfolio.signals.append({
                                        "timestamp": timestamp.isoformat(),
                                        "strategy": strategy_name,
                                        "symbol": symbol,
                                        "side": risk_approved_signal.side,
                                        "confidence": risk_approved_signal.confidence,
                                        "size_quote_usd": risk_approved_signal.size_quote_usd,
                                        "ai_enhanced": True
                                    })
                
                except Exception as e:
                    logger.debug(f"Agent error in {strategy_name}: {e}")
                    continue
    
    # Final portfolio valuation
    final_prices = {symbol: float(df.iloc[-1]["close"]) for symbol, df in market_data.items()}
    portfolio.mark(final_prices, test_index[-1])
    
    logger.info("\n🏁 Multi-Agent Simulation Complete!")
    logger.info("=" * 60)
    
    # Agent Performance Summary
    logger.info("🤖 AGENT PERFORMANCE SUMMARY:")
    logger.info(f"   🧠 AI Engine Decisions: {agent_stats['ai_decisions']}")
    logger.info(f"   📡 Signals Generated: {agent_stats['signals_generated']}")
    logger.info(f"   🔍 Signals Filtered: {agent_stats['signals_filtered']}")
    logger.info(f"   🛡️ Risk Blocks: {agent_stats['risk_blocked']}")
    logger.info(f"   ⚡ Successful Executions: {agent_stats['executions']}")
    logger.info(f"   🔄 Regime Changes: {agent_stats['regime_changes']}")
    
    # Calculate comprehensive results
    if portfolio.history:
        equity_df = pd.DataFrame(portfolio.history)
        equity_df["datetime"] = pd.to_datetime(equity_df["datetime"])
        equity_df.set_index("datetime", inplace=True)
        
        metrics = compute_performance_metrics(equity_df["equity"])
        
        # Enhanced metrics with agent data
        metrics.update({
            "total_trades": len(portfolio.trades),
            "total_signals": len(portfolio.signals),
            "agent_efficiency": round(agent_stats['executions'] / max(agent_stats['signals_generated'], 1), 3),
            "risk_filter_rate": round(agent_stats['risk_blocked'] / max(agent_stats['signals_generated'], 1), 3),
            "signal_filter_rate": round(agent_stats['signals_filtered'] / max(agent_stats['signals_generated'], 1), 3),
            "regime_adaptations": agent_stats['regime_changes'],
            "ai_coordination_score": round((agent_stats['executions'] * agent_stats['regime_changes']) / max(agent_stats['ai_decisions'], 1), 3)
        })
        
        # Calculate win rate
        if len(portfolio.trades) >= 2:
            profitable_trades = 0
            for i in range(0, len(portfolio.trades) - 1, 2):
                if i + 1 < len(portfolio.trades):
                    buy_trade = portfolio.trades[i]
                    sell_trade = portfolio.trades[i + 1]
                    if (buy_trade.get('side') == 'buy' and sell_trade.get('side') == 'sell' and
                        sell_trade.get('price', 0) > buy_trade.get('price', 0)):
                        profitable_trades += 1
            
            metrics["win_rate"] = round(profitable_trades / max(len(portfolio.trades) // 2, 1) * 100, 1)
        else:
            metrics["win_rate"] = 0
        
        # Store final results in Redis
        context_manager.set_context("final_agent_results", metrics, expire_seconds=86400)
        
        # Save comprehensive files
        equity_df.to_csv(OUT_DIR / "agent_equity_curve.csv")
        
        with open(OUT_DIR / "agent_results.json", "w") as f:
            json.dump(metrics, f, indent=2)
        
        if portfolio.trades:
            trades_df = pd.DataFrame(portfolio.trades)
            trades_df.to_csv(OUT_DIR / "agent_trades.csv", index=False)
        
        if portfolio.signals:
            signals_df = pd.DataFrame(portfolio.signals)
            signals_df.to_csv(OUT_DIR / "agent_signals.csv", index=False)
        
        # Agent analytics export
        agent_analytics = {
            'agent_stats': agent_stats,
            'execution_efficiency': metrics.get('agent_efficiency', 0),
            'risk_management_effectiveness': metrics.get('risk_filter_rate', 0),
            'ai_coordination_score': metrics.get('ai_coordination_score', 0)
        }
        
        with open(OUT_DIR / "agent_analytics.json", "w") as f:
            json.dump(agent_analytics, f, indent=2)
        
        # Comprehensive results display
        print("\n" + "="*80)
        print("🤖 COMPLETE MULTI-AGENT ECOSYSTEM RESULTS")
        print("="*80)
        print(f"💰 Total Return: {metrics.get('total_return', 0):.2f}%")
        print(f"📊 Sharpe Ratio: {metrics.get('sharpe_ratio', 0):.3f}")
        print(f"📈 Sortino Ratio: {metrics.get('sortino_ratio', 0):.3f}")
        print(f"📉 Max Drawdown: {metrics.get('max_drawdown', 0):.2f}%")
        print(f"🎯 Win Rate: {metrics.get('win_rate', 0):.1f}%")
        print(f"⚡ Volatility: {metrics.get('volatility', 0):.2f}%")
        print(f"💵 Final Equity: ${metrics.get('final_equity', 0):.2f}")
        print("\n🤖 AGENT COORDINATION METRICS:")
        print(f"🔄 Total Trades: {metrics.get('total_trades', 0)}")
        print(f"📡 Total Signals: {metrics.get('total_signals', 0)}")
        print(f"⚙️  Agent Efficiency: {metrics.get('agent_efficiency', 0):.3f}")
        print(f"🛡️ Risk Filter Rate: {metrics.get('risk_filter_rate', 0):.3f}")
        print(f"🧠 AI Coordination Score: {metrics.get('ai_coordination_score', 0):.3f}")
        print(f"🔄 Regime Adaptations: {metrics.get('regime_adaptations', 0)}")
        print(f"\n📁 Complete Results: {OUT_DIR}")
        print("   • agent_equity_curve.csv - Portfolio performance")
        print("   • agent_results.json - Performance metrics") 
        print("   • agent_trades.csv - Execution details")
        print("   • agent_signals.csv - Signal analysis")
        print("   • agent_analytics.json - Agent coordination data")
        
        logger.info("✅ Complete Multi-Agent Ecosystem Backtest Finished")
    else:
        logger.error("❌ No portfolio history generated")

def parse_args():
    parser = argparse.ArgumentParser(description="Complete Multi-Agent Crypto Trading Ecosystem")
    parser.add_argument("--exchange", default="kraken", help="Exchange ID")
    parser.add_argument("--pairs", nargs="+", default=["BTC/USD"], help="Trading pairs")
    parser.add_argument("--timeframe", default="1h", help="Timeframe")
    parser.add_argument("--days", type=int, default=30, help="Days to backtest")
    parser.add_argument("--limit", type=int, default=2000, help="Max candles")
    parser.add_argument("--start", type=float, default=1000.0, help="Starting capital")
    parser.add_argument("--redis-url", help="Redis Cloud URL")
    return parser.parse_args()

def main() -> int:
    """Main entry point."""
    try:
        args = parse_args()
        run_full_agent_backtest(args)
        return 0
    except KeyboardInterrupt:
        print("\nMulti-Agent backtest interrupted")
        return 130
    except Exception as e:
        logger.error(f"Multi-Agent backtest failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())