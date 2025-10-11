"""
Test suite for Enhanced Scalper Agent

Comprehensive tests for the enhanced scalper agent with multi-strategy integration.
"""

import asyncio
import pytest
import pandas as pd
import numpy as np
from decimal import Decimal
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timedelta

# Import the enhanced scalper agent
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from agents.scalper.enhanced_scalper_agent import EnhancedScalperAgent, StrategySignal, EnhancedSignal
from agents.scalper.data.market_store import TickRecord


class TestEnhancedScalperAgent:
    """Test cases for Enhanced Scalper Agent"""
    
    @pytest.fixture
    def mock_config(self):
        """Mock configuration for testing"""
        return {
            'scalper': {
                'pairs': ['BTC/USD', 'ETH/USD'],
                'target_bps': 10,
                'stop_loss_bps': 5,
                'timeframe': '15s',
                'preferred_order_type': 'limit',
                'post_only': True,
                'hidden_orders': False,
                'max_slippage_bps': 4,
                'max_trades_per_minute': 4,
                'cooldown_after_loss_seconds': 90,
                'daily_trade_limit': 150,
                'max_hold_seconds': 120,
                'max_spread_bps': 3.0,
                'min_liquidity_usd': 1000000.0
            },
            'strategy_router': {
                'strategy_allocations': {
                    'breakout': 0.25,
                    'mean_reversion': 0.20,
                    'momentum': 0.25,
                    'trend_following': 0.30,
                    'sideways': 0.15
                },
                'min_confidence': 0.3,
                'high_confidence': 0.7
            },
            'signal_filtering': {
                'min_alignment_confidence': 0.3,
                'min_strategy_alignment': 0.6,
                'require_alignment': False,
                'min_regime_confidence': 0.3,
                'min_scalping_confidence': 0.5
            },
            'enhanced_validation': {
                'min_enhanced_confidence': 0.6,
                'min_regime_confidence': 0.4,
                'require_strategy_alignment': False
            },
            'regime_adaptation': {
                'sideways_target_bps': 8,
                'sideways_stop_bps': 4,
                'sideways_max_trades': 6,
                'bull_target_bps': 12,
                'bull_stop_bps': 6,
                'bull_max_trades': 4,
                'bear_target_bps': 12,
                'bear_stop_bps': 6,
                'bear_max_trades': 4
            },
            'strategies': {
                'breakout': {},
                'mean_reversion': {},
                'momentum': {},
                'trend_following': {},
                'sideways': {}
            }
        }
    
    @pytest.fixture
    def mock_market_data(self):
        """Mock market data for testing"""
        # Create mock OHLCV data
        dates = pd.date_range(start='2024-01-01', periods=100, freq='1H')
        np.random.seed(42)
        
        # Generate realistic price data
        base_price = 50000
        returns = np.random.normal(0, 0.02, 100)
        prices = [base_price]
        
        for ret in returns[1:]:
            prices.append(prices[-1] * (1 + ret))
        
        df = pd.DataFrame({
            'timestamp': dates,
            'open': prices,
            'high': [p * (1 + abs(np.random.normal(0, 0.01))) for p in prices],
            'low': [p * (1 - abs(np.random.normal(0, 0.01))) for p in prices],
            'close': prices,
            'volume': np.random.uniform(1000, 10000, 100)
        })
        
        return {
            'symbol': 'BTC/USD',
            'timeframe': '1h',
            'df': df,
            'context': {
                'equity_usd': 10000,
                'current_price': prices[-1]
            }
        }
    
    @pytest.fixture
    def mock_strategy_signals(self):
        """Mock strategy signals for testing"""
        return {
            'breakout': StrategySignal(
                strategy_name='breakout',
                signal='buy',
                confidence=0.8,
                position_size=1000.0,
                metadata={'breakout_level': 50000, 'atr': 500},
                timestamp=1234567890.0
            ),
            'trend_following': StrategySignal(
                strategy_name='trend_following',
                signal='buy',
                confidence=0.7,
                position_size=800.0,
                metadata={'ema_short': 50100, 'ema_long': 49900},
                timestamp=1234567890.0
            ),
            'mean_reversion': StrategySignal(
                strategy_name='mean_reversion',
                signal='sell',
                confidence=0.6,
                position_size=600.0,
                metadata={'zscore': -1.5, 'bollinger_mid': 50000},
                timestamp=1234567890.0
            )
        }
    
    @pytest.fixture
    async def enhanced_scalper(self, mock_config):
        """Create enhanced scalper agent for testing"""
        with patch('agents.scalper.enhanced_scalper_agent.KrakenScalperAgent'):
            with patch('agents.scalper.enhanced_scalper_agent.RegimeRouter'):
                with patch('agents.scalper.enhanced_scalper_agent.BreakoutStrategy'):
                    with patch('agents.scalper.enhanced_scalper_agent.MeanReversionStrategy'):
                        with patch('agents.scalper.enhanced_scalper_agent.MomentumStrategy'):
                            with patch('agents.scalper.enhanced_scalper_agent.TrendFollowingStrategy'):
                                with patch('agents.scalper.enhanced_scalper_agent.SidewaysStrategy'):
                                    agent = EnhancedScalperAgent(mock_config)
                                    await agent.initialize()
                                    return agent
    
    @pytest.mark.asyncio
    async def test_initialization(self, enhanced_scalper):
        """Test agent initialization"""
        assert enhanced_scalper is not None
        assert enhanced_scalper.market_regime == "unknown"
        assert enhanced_scalper.regime_confidence == 0.5
        assert len(enhanced_scalper.strategies) > 0
        assert enhanced_scalper.signals_generated == 0
    
    @pytest.mark.asyncio
    async def test_strategy_alignment_check(self, enhanced_scalper, mock_strategy_signals):
        """Test strategy alignment checking"""
        # Test aligned signals
        scalping_signal = {'side': 'buy', 'meta': {'confidence': 0.8}}
        aligned_signals = {
            'breakout': mock_strategy_signals['breakout'],
            'trend_following': mock_strategy_signals['trend_following']
        }
        
        is_aligned, confidence, reason = enhanced_scalper._check_strategy_alignment(
            scalping_signal, aligned_signals
        )
        
        assert is_aligned is True
        assert confidence > 0.5
        assert 'aligned' in reason
        
        # Test conflicting signals
        conflicting_signals = {
            'breakout': mock_strategy_signals['breakout'],
            'mean_reversion': mock_strategy_signals['mean_reversion']
        }
        
        is_aligned, confidence, reason = enhanced_scalper._check_strategy_alignment(
            scalping_signal, conflicting_signals
        )
        
        assert is_aligned is False
        assert confidence < 0.5
        assert 'conflicting' in reason
    
    def test_enhanced_confidence_calculation(self, enhanced_scalper, mock_strategy_signals):
        """Test enhanced confidence calculation"""
        scalping_signal = {
            'side': 'buy',
            'meta': {'confidence': 0.7}
        }
        
        strategy_signals = {
            'breakout': mock_strategy_signals['breakout'],
            'trend_following': mock_strategy_signals['trend_following']
        }
        
        is_aligned = True
        alignment_confidence = 0.8
        
        enhanced_confidence = enhanced_scalper._calculate_enhanced_confidence(
            scalping_signal, strategy_signals, is_aligned, alignment_confidence
        )
        
        assert 0.0 <= enhanced_confidence <= 1.0
        assert enhanced_confidence > scalping_signal['meta']['confidence']  # Should be boosted
    
    def test_signal_filtering(self, enhanced_scalper):
        """Test signal filtering logic"""
        scalping_signal = {
            'side': 'buy',
            'meta': {'confidence': 0.8}
        }
        
        strategy_signals = {}
        is_aligned = True
        alignment_confidence = 0.8
        
        # Test accepted signal
        should_accept = enhanced_scalper._should_accept_signal(
            scalping_signal, strategy_signals, is_aligned, alignment_confidence
        )
        assert should_accept is True
        
        # Test rejected signal (low confidence)
        low_confidence_signal = {
            'side': 'buy',
            'meta': {'confidence': 0.3}
        }
        
        should_accept = enhanced_scalper._should_accept_signal(
            low_confidence_signal, strategy_signals, is_aligned, alignment_confidence
        )
        assert should_accept is False
    
    @pytest.mark.asyncio
    async def test_regime_adaptation(self, enhanced_scalper):
        """Test regime-based parameter adaptation"""
        # Test sideways regime adaptation
        enhanced_scalper.market_regime = 'sideways'
        await enhanced_scalper._adapt_to_regime()
        
        # Test bull regime adaptation
        enhanced_scalper.market_regime = 'bull'
        await enhanced_scalper._adapt_to_regime()
        
        # Test bear regime adaptation
        enhanced_scalper.market_regime = 'bear'
        await enhanced_scalper._adapt_to_regime()
        
        # Verify adaptation occurred
        assert enhanced_scalper.performance_metrics['regime_adaptations'] > 0
    
    @pytest.mark.asyncio
    async def test_enhanced_signal_generation(self, enhanced_scalper, mock_market_data):
        """Test enhanced signal generation"""
        # Mock the scalping signal generation
        mock_scalping_signal = {
            'side': 'buy',
            'entry_price': '50000.0',
            'take_profit': '50050.0',
            'stop_loss': '49950.0',
            'size_quote_usd': '1000.0',
            'meta': {'confidence': 0.8, 'strength': 0.7},
            'signal_id': 'test_signal_123'
        }
        
        with patch.object(enhanced_scalper.kraken_scalper, 'generate_signal', 
                         return_value=mock_scalping_signal):
            with patch.object(enhanced_scalper, '_get_strategy_signals', 
                             return_value={}):
                
                signal = await enhanced_scalper.generate_enhanced_signal(
                    pair='BTC/USD',
                    best_bid=49995.0,
                    best_ask=50005.0,
                    last_price=50000.0,
                    quote_liquidity_usd=2000000.0,
                    market_data=mock_market_data
                )
                
                if signal:
                    assert isinstance(signal, EnhancedSignal)
                    assert signal.pair == 'BTC/USD'
                    assert signal.side == 'buy'
                    assert signal.confidence > 0.0
                    assert enhanced_scalper.signals_generated > 0
    
    @pytest.mark.asyncio
    async def test_enhanced_signal_validation(self, enhanced_scalper):
        """Test enhanced signal validation"""
        # Create a valid enhanced signal
        valid_signal = EnhancedSignal(
            pair='BTC/USD',
            side='buy',
            entry_price=Decimal('50000.0'),
            take_profit=Decimal('50050.0'),
            stop_loss=Decimal('49950.0'),
            size_quote_usd=Decimal('1000.0'),
            confidence=0.8,
            strategy_alignment=True,
            regime_state='bull',
            regime_confidence=0.7,
            scalping_confidence=0.8,
            strategy_confidence=0.7,
            metadata={'test': 'data'},
            signal_id='test_123'
        )
        
        # Mock the scalping validation
        with patch.object(enhanced_scalper.kraken_scalper, 'validate_signal', 
                         return_value=True):
            
            is_valid = await enhanced_scalper.validate_enhanced_signal(valid_signal)
            assert is_valid is True
        
        # Test invalid signal (low confidence)
        invalid_signal = valid_signal
        invalid_signal.confidence = 0.3
        
        is_valid = await enhanced_scalper.validate_enhanced_signal(invalid_signal)
        assert is_valid is False
    
    @pytest.mark.asyncio
    async def test_performance_metrics(self, enhanced_scalper):
        """Test performance metrics tracking"""
        # Generate some test signals
        enhanced_scalper.signals_generated = 10
        enhanced_scalper.signals_aligned = 7
        enhanced_scalper.signals_filtered = 3
        enhanced_scalper.performance_metrics['total_signals'] = 10
        enhanced_scalper.performance_metrics['aligned_signals'] = 7
        enhanced_scalper.performance_metrics['filtered_signals'] = 3
        
        status = await enhanced_scalper.get_enhanced_status()
        
        assert 'strategy_integration' in status
        assert 'performance_metrics' in status
        assert status['signal_alignment_rate'] == 0.7
        assert status['signal_filter_rate'] == 0.3
    
    @pytest.mark.asyncio
    async def test_tick_handling(self, enhanced_scalper):
        """Test tick data handling"""
        tick = TickRecord(
            timestamp=1234567890.0,
            price=50000.0,
            volume=1.5,
            side='buy'
        )
        
        with patch.object(enhanced_scalper.kraken_scalper, 'on_tick') as mock_on_tick:
            await enhanced_scalper.on_tick('BTC/USD', tick)
            mock_on_tick.assert_called_once_with('BTC/USD', tick)
    
    @pytest.mark.asyncio
    async def test_regime_update(self, enhanced_scalper):
        """Test regime update functionality"""
        with patch.object(enhanced_scalper, '_adapt_to_regime') as mock_adapt:
            await enhanced_scalper.update_regime('bull', 0.8, 0.9)
            
            assert enhanced_scalper.market_regime == 'bull'
            assert enhanced_scalper.regime_confidence == 0.8
            mock_adapt.assert_called_once()
    
    def test_strategy_signal_creation(self):
        """Test StrategySignal dataclass creation"""
        signal = StrategySignal(
            strategy_name='test_strategy',
            signal='buy',
            confidence=0.8,
            position_size=1000.0,
            metadata={'test': 'data'},
            timestamp=1234567890.0
        )
        
        assert signal.strategy_name == 'test_strategy'
        assert signal.signal == 'buy'
        assert signal.confidence == 0.8
        assert signal.position_size == 1000.0
    
    def test_enhanced_signal_creation(self):
        """Test EnhancedSignal dataclass creation"""
        signal = EnhancedSignal(
            pair='BTC/USD',
            side='buy',
            entry_price=Decimal('50000.0'),
            take_profit=Decimal('50050.0'),
            stop_loss=Decimal('49950.0'),
            size_quote_usd=Decimal('1000.0'),
            confidence=0.8,
            strategy_alignment=True,
            regime_state='bull',
            regime_confidence=0.7,
            scalping_confidence=0.8,
            strategy_confidence=0.7,
            metadata={'test': 'data'},
            signal_id='test_123'
        )
        
        assert signal.pair == 'BTC/USD'
        assert signal.side == 'buy'
        assert signal.confidence == 0.8
        assert signal.strategy_alignment is True
        assert signal.regime_state == 'bull'


class TestConfigurationLoader:
    """Test cases for configuration loading"""
    
    def test_config_loading(self):
        """Test configuration loading from file"""
        from config.enhanced_scalper_loader import EnhancedScalperConfigLoader
        
        # Test with default configuration
        loader = EnhancedScalperConfigLoader()
        config = loader.load_config()
        
        assert 'scalper' in config
        assert 'strategy_router' in config
        assert 'signal_filtering' in config
        assert 'enhanced_validation' in config
        assert 'regime_adaptation' in config
    
    def test_config_validation(self):
        """Test configuration validation"""
        from config.enhanced_scalper_loader import EnhancedScalperConfigLoader
        
        loader = EnhancedScalperConfigLoader()
        
        # Test valid configuration
        valid_config = {
            'scalper': {
                'pairs': ['BTC/USD'],
                'target_bps': 10,
                'stop_loss_bps': 5
            },
            'strategy_router': {
                'strategy_allocations': {
                    'breakout': 0.5,
                    'trend_following': 0.5
                }
            },
            'signal_filtering': {
                'min_alignment_confidence': 0.5
            },
            'regime_adaptation': {
                'sideways_target_bps': 8,
                'bull_target_bps': 12,
                'bear_target_bps': 12
            }
        }
        
        # Should not raise exception
        loader._validate_config(valid_config)
        
        # Test invalid configuration
        invalid_config = {
            'scalper': {
                'pairs': [],
                'target_bps': -1,
                'stop_loss_bps': 0
            }
        }
        
        with pytest.raises(ValueError):
            loader._validate_config(invalid_config)


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])

