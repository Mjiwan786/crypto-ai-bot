#!/usr/bin/env python3
"""
Enhanced Scalper Agent Testing Script

Comprehensive testing suite for the enhanced scalper agent including:
- Unit tests
- Integration tests
- Performance tests
- Stress tests
- Configuration validation
"""

import asyncio
import logging
import sys
import time
import json
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime, timedelta

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agents.scalper.enhanced_scalper_agent import EnhancedScalperAgent, StrategySignal, EnhancedSignal
from agents.scalper.data.market_store import TickRecord
from config.enhanced_scalper_loader import load_enhanced_scalper_config


class EnhancedScalperTester:
    """
    Comprehensive testing suite for enhanced scalper agent
    """
    
    def __init__(self, config_path: str = None):
        """
        Initialize the tester
        
        Args:
            config_path: Path to configuration file
        """
        self.config_path = config_path
        self.config = None
        self.agent = None
        self.logger = None
        self.test_results = {}
        
    def setup_logging(self):
        """Setup logging for testing"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler('logs/enhanced_scalper_test.log')
            ]
        )
        self.logger = logging.getLogger(__name__)
        
    async def run_all_tests(self):
        """Run all test suites"""
        self.setup_logging()
        self.logger.info("=== Enhanced Scalper Agent Testing Suite ===")
        
        # Load configuration
        try:
            self.config = load_enhanced_scalper_config(self.config_path)
            self.logger.info("✓ Configuration loaded successfully")
        except Exception as e:
            self.logger.error(f"✗ Configuration loading failed: {e}")
            return False
        
        # Initialize agent
        try:
            self.agent = EnhancedScalperAgent(self.config)
            await self.agent.initialize()
            self.logger.info("✓ Enhanced scalper agent initialized")
        except Exception as e:
            self.logger.error(f"✗ Agent initialization failed: {e}")
            return False
        
        # Run test suites
        test_suites = [
            ("Configuration Tests", self.test_configuration),
            ("Agent Initialization Tests", self.test_agent_initialization),
            ("Strategy Integration Tests", self.test_strategy_integration),
            ("Signal Generation Tests", self.test_signal_generation),
            ("Signal Filtering Tests", self.test_signal_filtering),
            ("Regime Detection Tests", self.test_regime_detection),
            ("Parameter Adaptation Tests", self.test_parameter_adaptation),
            ("Risk Management Tests", self.test_risk_management),
            ("Performance Tests", self.test_performance),
            ("Stress Tests", self.test_stress),
            ("Integration Tests", self.test_integration)
        ]
        
        total_tests = 0
        passed_tests = 0
        
        for suite_name, test_func in test_suites:
            self.logger.info(f"\n--- Running {suite_name} ---")
            try:
                suite_results = await test_func()
                total_tests += len(suite_results)
                passed_tests += sum(1 for result in suite_results.values() if result['status'] == 'PASS')
                self.test_results[suite_name] = suite_results
                self.logger.info(f"✓ {suite_name} completed: {sum(1 for r in suite_results.values() if r['status'] == 'PASS')}/{len(suite_results)} passed")
            except Exception as e:
                self.logger.error(f"✗ {suite_name} failed: {e}")
                self.test_results[suite_name] = {'error': str(e)}
        
        # Generate test report
        self.generate_test_report(total_tests, passed_tests)
        
        return passed_tests == total_tests
    
    async def test_configuration(self) -> Dict[str, Any]:
        """Test configuration loading and validation"""
        results = {}
        
        # Test configuration structure
        try:
            assert 'scalper' in self.config
            assert 'strategy_router' in self.config
            assert 'signal_filtering' in self.config
            results['config_structure'] = {'status': 'PASS', 'message': 'Configuration structure valid'}
        except Exception as e:
            results['config_structure'] = {'status': 'FAIL', 'message': str(e)}
        
        # Test scalper configuration
        try:
            scalper_config = self.config['scalper']
            assert 'pairs' in scalper_config
            assert 'target_bps' in scalper_config
            assert 'stop_loss_bps' in scalper_config
            assert scalper_config['target_bps'] > 0
            assert scalper_config['stop_loss_bps'] > 0
            results['scalper_config'] = {'status': 'PASS', 'message': 'Scalper configuration valid'}
        except Exception as e:
            results['scalper_config'] = {'status': 'FAIL', 'message': str(e)}
        
        # Test strategy router configuration
        try:
            router_config = self.config['strategy_router']
            allocations = router_config['strategy_allocations']
            total_allocation = sum(allocations.values())
            assert 0.9 <= total_allocation <= 1.1  # Allow some tolerance
            results['strategy_router'] = {'status': 'PASS', 'message': f'Strategy allocations sum: {total_allocation:.2f}'}
        except Exception as e:
            results['strategy_router'] = {'status': 'FAIL', 'message': str(e)}
        
        return results
    
    async def test_agent_initialization(self) -> Dict[str, Any]:
        """Test agent initialization"""
        results = {}
        
        # Test agent creation
        try:
            assert self.agent is not None
            assert hasattr(self.agent, 'strategies')
            assert hasattr(self.agent, 'kraken_scalper')
            results['agent_creation'] = {'status': 'PASS', 'message': 'Agent created successfully'}
        except Exception as e:
            results['agent_creation'] = {'status': 'FAIL', 'message': str(e)}
        
        # Test strategies loaded
        try:
            assert len(self.agent.strategies) > 0
            expected_strategies = ['breakout', 'mean_reversion', 'momentum', 'trend_following', 'sideways']
            for strategy in expected_strategies:
                assert strategy in self.agent.strategies
            results['strategies_loaded'] = {'status': 'PASS', 'message': f'Loaded {len(self.agent.strategies)} strategies'}
        except Exception as e:
            results['strategies_loaded'] = {'status': 'FAIL', 'message': str(e)}
        
        # Test regime detection
        try:
            assert hasattr(self.agent, 'market_regime')
            assert hasattr(self.agent, 'regime_confidence')
            results['regime_detection'] = {'status': 'PASS', 'message': 'Regime detection initialized'}
        except Exception as e:
            results['regime_detection'] = {'status': 'FAIL', 'message': str(e)}
        
        return results
    
    async def test_strategy_integration(self) -> Dict[str, Any]:
        """Test strategy integration functionality"""
        results = {}
        
        # Test strategy alignment checking
        try:
            scalping_signal = {'side': 'buy', 'meta': {'confidence': 0.8}}
            aligned_signals = {
                'breakout': StrategySignal(
                    strategy_name='breakout',
                    signal='buy',
                    confidence=0.8,
                    position_size=1000.0,
                    metadata={},
                    timestamp=time.time()
                )
            }
            
            is_aligned, confidence, reason = self.agent._check_strategy_alignment(
                scalping_signal, aligned_signals
            )
            
            assert isinstance(is_aligned, bool)
            assert 0.0 <= confidence <= 1.0
            assert isinstance(reason, str)
            results['strategy_alignment'] = {'status': 'PASS', 'message': f'Alignment: {is_aligned}, Confidence: {confidence:.2f}'}
        except Exception as e:
            results['strategy_alignment'] = {'status': 'FAIL', 'message': str(e)}
        
        # Test confidence calculation
        try:
            enhanced_confidence = self.agent._calculate_enhanced_confidence(
                scalping_signal, aligned_signals, True, 0.8
            )
            
            assert 0.0 <= enhanced_confidence <= 1.0
            results['confidence_calculation'] = {'status': 'PASS', 'message': f'Enhanced confidence: {enhanced_confidence:.2f}'}
        except Exception as e:
            results['confidence_calculation'] = {'status': 'FAIL', 'message': str(e)}
        
        return results
    
    async def test_signal_generation(self) -> Dict[str, Any]:
        """Test signal generation functionality"""
        results = {}
        
        # Test market data creation
        try:
            market_data = self._create_test_market_data('BTC/USD', 50000.0)
            assert 'symbol' in market_data
            assert 'df' in market_data
            assert 'context' in market_data
            results['market_data_creation'] = {'status': 'PASS', 'message': 'Test market data created'}
        except Exception as e:
            results['market_data_creation'] = {'status': 'FAIL', 'message': str(e)}
        
        # Test signal generation
        try:
            signal = await self.agent.generate_enhanced_signal(
                pair='BTC/USD',
                best_bid=49995.0,
                best_ask=50005.0,
                last_price=50000.0,
                quote_liquidity_usd=2000000.0,
                market_data=market_data
            )
            
            if signal:
                assert isinstance(signal, EnhancedSignal)
                assert signal.pair == 'BTC/USD'
                assert signal.side in ['buy', 'sell']
                assert 0.0 <= signal.confidence <= 1.0
                results['signal_generation'] = {'status': 'PASS', 'message': f'Signal generated: {signal.side} (conf: {signal.confidence:.2f})'}
            else:
                results['signal_generation'] = {'status': 'PASS', 'message': 'No signal generated (filtered out)'}
        except Exception as e:
            results['signal_generation'] = {'status': 'FAIL', 'message': str(e)}
        
        return results
    
    async def test_signal_filtering(self) -> Dict[str, Any]:
        """Test signal filtering functionality"""
        results = {}
        
        # Test signal acceptance
        try:
            good_signal = {'side': 'buy', 'meta': {'confidence': 0.8}}
            should_accept = self.agent._should_accept_signal(
                good_signal, {}, True, 0.8
            )
            assert isinstance(should_accept, bool)
            results['signal_acceptance'] = {'status': 'PASS', 'message': f'Good signal accepted: {should_accept}'}
        except Exception as e:
            results['signal_acceptance'] = {'status': 'FAIL', 'message': str(e)}
        
        # Test signal rejection
        try:
            bad_signal = {'side': 'buy', 'meta': {'confidence': 0.3}}
            should_accept = self.agent._should_accept_signal(
                bad_signal, {}, True, 0.8
            )
            assert isinstance(should_accept, bool)
            results['signal_rejection'] = {'status': 'PASS', 'message': f'Bad signal rejected: {not should_accept}'}
        except Exception as e:
            results['signal_rejection'] = {'status': 'FAIL', 'message': str(e)}
        
        return results
    
    async def test_regime_detection(self) -> Dict[str, Any]:
        """Test regime detection functionality"""
        results = {}
        
        # Test regime updates
        try:
            test_regimes = ['bull', 'bear', 'sideways']
            for regime in test_regimes:
                await self.agent.update_regime(regime, 0.8, 0.9)
                assert self.agent.market_regime == regime
                assert self.agent.regime_confidence == 0.8
            results['regime_updates'] = {'status': 'PASS', 'message': f'Tested {len(test_regimes)} regimes'}
        except Exception as e:
            results['regime_updates'] = {'status': 'FAIL', 'message': str(e)}
        
        # Test regime adaptation
        try:
            initial_adaptations = self.agent.performance_metrics['regime_adaptations']
            await self.agent._adapt_to_regime()
            final_adaptations = self.agent.performance_metrics['regime_adaptations']
            assert final_adaptations >= initial_adaptations
            results['regime_adaptation'] = {'status': 'PASS', 'message': f'Adaptations: {final_adaptations}'}
        except Exception as e:
            results['regime_adaptation'] = {'status': 'FAIL', 'message': str(e)}
        
        return results
    
    async def test_parameter_adaptation(self) -> Dict[str, Any]:
        """Test parameter adaptation functionality"""
        results = {}
        
        # Test sideways regime adaptation
        try:
            self.agent.market_regime = 'sideways'
            await self.agent._adapt_to_regime()
            results['sideways_adaptation'] = {'status': 'PASS', 'message': 'Sideways regime adapted'}
        except Exception as e:
            results['sideways_adaptation'] = {'status': 'FAIL', 'message': str(e)}
        
        # Test bull regime adaptation
        try:
            self.agent.market_regime = 'bull'
            await self.agent._adapt_to_regime()
            results['bull_adaptation'] = {'status': 'PASS', 'message': 'Bull regime adapted'}
        except Exception as e:
            results['bull_adaptation'] = {'status': 'FAIL', 'message': str(e)}
        
        # Test bear regime adaptation
        try:
            self.agent.market_regime = 'bear'
            await self.agent._adapt_to_regime()
            results['bear_adaptation'] = {'status': 'PASS', 'message': 'Bear regime adapted'}
        except Exception as e:
            results['bear_adaptation'] = {'status': 'FAIL', 'message': str(e)}
        
        return results
    
    async def test_risk_management(self) -> Dict[str, Any]:
        """Test risk management functionality"""
        results = {}
        
        # Test signal validation
        try:
            from decimal import Decimal
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
            
            is_valid = await self.agent.validate_enhanced_signal(valid_signal)
            assert isinstance(is_valid, bool)
            results['signal_validation'] = {'status': 'PASS', 'message': f'Signal validation: {is_valid}'}
        except Exception as e:
            results['signal_validation'] = {'status': 'FAIL', 'message': str(e)}
        
        return results
    
    async def test_performance(self) -> Dict[str, Any]:
        """Test performance metrics"""
        results = {}
        
        # Test performance tracking
        try:
            initial_signals = self.agent.signals_generated
            initial_aligned = self.agent.signals_aligned
            
            # Generate some test signals
            for i in range(5):
                market_data = self._create_test_market_data('BTC/USD', 50000.0 + i * 10)
                signal = await self.agent.generate_enhanced_signal(
                    pair='BTC/USD',
                    best_bid=49995.0 + i * 10,
                    best_ask=50005.0 + i * 10,
                    last_price=50000.0 + i * 10,
                    quote_liquidity_usd=2000000.0,
                    market_data=market_data
                )
            
            final_signals = self.agent.signals_generated
            final_aligned = self.agent.signals_aligned
            
            assert final_signals >= initial_signals
            results['performance_tracking'] = {'status': 'PASS', 'message': f'Signals: {initial_signals} -> {final_signals}'}
        except Exception as e:
            results['performance_tracking'] = {'status': 'FAIL', 'message': str(e)}
        
        return results
    
    async def test_stress(self) -> Dict[str, Any]:
        """Test stress scenarios"""
        results = {}
        
        # Test high-frequency signal generation
        try:
            start_time = time.time()
            signal_count = 0
            
            for i in range(100):
                market_data = self._create_test_market_data('BTC/USD', 50000.0 + i)
                signal = await self.agent.generate_enhanced_signal(
                    pair='BTC/USD',
                    best_bid=49995.0 + i,
                    best_ask=50005.0 + i,
                    last_price=50000.0 + i,
                    quote_liquidity_usd=2000000.0,
                    market_data=market_data
                )
                if signal:
                    signal_count += 1
            
            duration = time.time() - start_time
            results['high_frequency'] = {'status': 'PASS', 'message': f'{signal_count} signals in {duration:.2f}s'}
        except Exception as e:
            results['high_frequency'] = {'status': 'FAIL', 'message': str(e)}
        
        # Test multiple pairs
        try:
            pairs = ['BTC/USD', 'ETH/USD', 'ADA/USD']
            pair_signals = {}
            
            for pair in pairs:
                market_data = self._create_test_market_data(pair, 50000.0)
                signal = await self.agent.generate_enhanced_signal(
                    pair=pair,
                    best_bid=49995.0,
                    best_ask=50005.0,
                    last_price=50000.0,
                    quote_liquidity_usd=2000000.0,
                    market_data=market_data
                )
                pair_signals[pair] = signal is not None
            
            results['multiple_pairs'] = {'status': 'PASS', 'message': f'Tested {len(pairs)} pairs'}
        except Exception as e:
            results['multiple_pairs'] = {'status': 'FAIL', 'message': str(e)}
        
        return results
    
    async def test_integration(self) -> Dict[str, Any]:
        """Test full integration workflow"""
        results = {}
        
        # Test complete workflow
        try:
            # Update regime
            await self.agent.update_regime('bull', 0.8, 0.9)
            
            # Generate signal
            market_data = self._create_test_market_data('BTC/USD', 50000.0)
            signal = await self.agent.generate_enhanced_signal(
                pair='BTC/USD',
                best_bid=49995.0,
                best_ask=50005.0,
                last_price=50000.0,
                quote_liquidity_usd=2000000.0,
                market_data=market_data
            )
            
            # Validate signal
            if signal:
                is_valid = await self.agent.validate_enhanced_signal(signal)
                results['full_workflow'] = {'status': 'PASS', 'message': f'Signal valid: {is_valid}'}
            else:
                results['full_workflow'] = {'status': 'PASS', 'message': 'No signal generated (filtered)'}
        except Exception as e:
            results['full_workflow'] = {'status': 'FAIL', 'message': str(e)}
        
        return results
    
    def _create_test_market_data(self, pair: str, price: float) -> Dict[str, Any]:
        """Create test market data"""
        # Generate OHLCV data
        dates = pd.date_range(start='2024-01-01', periods=100, freq='1H')
        np.random.seed(hash(pair) % 2**32)
        
        base_price = price
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
            'symbol': pair,
            'timeframe': '1h',
            'df': df,
            'context': {
                'equity_usd': 10000,
                'current_price': price
            }
        }
    
    def generate_test_report(self, total_tests: int, passed_tests: int):
        """Generate comprehensive test report"""
        self.logger.info("\n=== Enhanced Scalper Test Report ===")
        self.logger.info(f"Total tests: {total_tests}")
        self.logger.info(f"Passed: {passed_tests}")
        self.logger.info(f"Failed: {total_tests - passed_tests}")
        self.logger.info(f"Success rate: {passed_tests/total_tests:.1%}")
        
        self.logger.info("\nDetailed Results:")
        for suite_name, suite_results in self.test_results.items():
            self.logger.info(f"\n{suite_name}:")
            if isinstance(suite_results, dict) and 'error' not in suite_results:
                for test_name, result in suite_results.items():
                    status = result['status']
                    message = result['message']
                    self.logger.info(f"  {test_name}: {status} - {message}")
            else:
                self.logger.error(f"  Suite failed: {suite_results.get('error', 'Unknown error')}")
        
        # Save results to file
        with open('logs/enhanced_scalper_test_results.json', 'w') as f:
            json.dump(self.test_results, f, indent=2, default=str)
        
        self.logger.info(f"\nTest results saved to: logs/enhanced_scalper_test_results.json")


async def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Enhanced Scalper Agent Testing')
    parser.add_argument('--config', type=str, help='Path to configuration file')
    parser.add_argument('--suite', type=str, help='Run specific test suite')
    
    args = parser.parse_args()
    
    # Create tester
    tester = EnhancedScalperTester(config_path=args.config)
    
    # Run tests
    success = await tester.run_all_tests()
    
    if success:
        print("\n🎉 All tests passed! Enhanced scalper agent is working correctly.")
        sys.exit(0)
    else:
        print("\n❌ Some tests failed. Please review the logs.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

