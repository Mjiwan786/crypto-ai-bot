#!/usr/bin/env python3
"""
Enhanced Scalper Agent Runner

Main script to run the enhanced scalper agent with multi-strategy integration.
Demonstrates all the recommended integrations and expected benefits.
"""

import asyncio
import logging
import signal
import sys
import time
from pathlib import Path
from typing import Any, Dict

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agents.scalper.data.market_store import TickRecord
from agents.scalper.enhanced_scalper_agent import EnhancedScalperAgent
from config.enhanced_scalper_loader import load_enhanced_scalper_config

# Import MCP components if available
try:
    from mcp.redis_manager import RedisManager
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False
    RedisManager = None


class EnhancedScalperRunner:
    """
    Enhanced Scalper Agent Runner
    
    Manages the lifecycle of the enhanced scalper agent and demonstrates
    all the recommended integrations.
    """
    
    def __init__(self, config_path: str = None):
        """
        Initialize the enhanced scalper runner
        
        Args:
            config_path: Path to configuration file
        """
        self.config_path = config_path
        self.config = None
        self.agent = None
        self.redis_manager = None
        self.logger = None
        self.running = False
        
        # Performance tracking
        self.start_time = None
        self.signals_generated = 0
        self.signals_executed = 0
        self.total_pnl = 0.0
        
    def setup_logging(self):
        """Setup logging configuration"""
        log_config = self.config.get('logging', {})
        
        logging.basicConfig(
            level=getattr(logging, log_config.get('level', 'INFO')),
            format=log_config.get('format', '%(asctime)s - %(name)s - %(levelname)s - %(message)s'),
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler(log_config.get('file', 'logs/enhanced_scalper.log'))
            ]
        )
        
        self.logger = logging.getLogger(__name__)
        self.logger.info("Enhanced Scalper Runner logging initialized")
    
    def setup_redis(self):
        """Setup Redis connection if available"""
        if not HAS_REDIS:
            self.logger.warning("Redis not available, running without persistence")
            return
        
        redis_config = self.config.get('redis', {})
        if not redis_config.get('enabled', False):
            self.logger.info("Redis disabled in configuration")
            return
        
        try:
            self.redis_manager = RedisManager(
                host=redis_config.get('host', 'localhost'),
                port=redis_config.get('port', 6379),
                db=redis_config.get('db', 0),
                password=redis_config.get('password')
            )
            self.logger.info("Redis connection established")
        except Exception as e:
            self.logger.error(f"Failed to connect to Redis: {e}")
            self.redis_manager = None
    
    async def initialize(self):
        """Initialize the enhanced scalper agent"""
        try:
            # Load configuration
            self.config = load_enhanced_scalper_config(self.config_path)
            self.logger.info("Configuration loaded successfully")
            
            # Setup logging
            self.setup_logging()
            
            # Setup Redis
            self.setup_redis()
            
            # Initialize enhanced scalper agent
            self.agent = EnhancedScalperAgent(
                config=self.config,
                redis_manager=self.redis_manager,
                logger=self.logger
            )
            
            await self.agent.initialize()
            self.logger.info("Enhanced Scalper Agent initialized successfully")
            
            # Log configuration summary
            self._log_configuration_summary()
            
        except Exception as e:
            self.logger.error(f"Failed to initialize enhanced scalper: {e}")
            raise
    
    def _log_configuration_summary(self):
        """Log configuration summary"""
        scalper_config = self.config.get('scalper', {})
        strategy_config = self.config.get('strategy_router', {})
        filter_config = self.config.get('signal_filtering', {})
        
        self.logger.info("=== Enhanced Scalper Configuration Summary ===")
        self.logger.info(f"Trading pairs: {scalper_config.get('pairs', [])}")
        self.logger.info(f"Target BPS: {scalper_config.get('target_bps', 10)}")
        self.logger.info(f"Stop loss BPS: {scalper_config.get('stop_loss_bps', 5)}")
        self.logger.info(f"Strategy allocations: {strategy_config.get('strategy_allocations', {})}")
        self.logger.info(f"Signal filtering enabled: {filter_config.get('require_alignment', False)}")
        self.logger.info(f"Min alignment confidence: {filter_config.get('min_alignment_confidence', 0.3)}")
        self.logger.info("=============================================")
    
    async def run_demo(self, duration_minutes: int = 10):
        """
        Run a demonstration of the enhanced scalper
        
        Args:
            duration_minutes: Duration to run the demo
        """
        self.logger.info(f"Starting enhanced scalper demo for {duration_minutes} minutes")
        
        self.running = True
        self.start_time = time.time()
        
        # Demo pairs
        demo_pairs = self.config.get('scalper', {}).get('pairs', ['BTC/USD', 'ETH/USD'])
        
        # Simulate market data
        await self._simulate_market_data(duration_minutes, demo_pairs)
        
        self.logger.info("Enhanced scalper demo completed")
        await self._log_performance_summary()
    
    async def _simulate_market_data(self, duration_minutes: int, pairs: list):
        """Simulate market data for demonstration"""
        import random

        
        end_time = time.time() + (duration_minutes * 60)
        
        # Generate realistic price data
        base_prices = {
            'BTC/USD': 50000.0,
            'ETH/USD': 3000.0,
            'ADA/USD': 0.5,
            'SOL/USD': 100.0
        }
        
        current_prices = base_prices.copy()
        
        while time.time() < end_time and self.running:
            try:
                for pair in pairs:
                    # Simulate price movement
                    base_price = base_prices[pair]
                    volatility = 0.001  # 0.1% volatility
                    
                    # Random walk with mean reversion
                    change = random.gauss(0, volatility)
                    current_prices[pair] *= (1 + change)
                    
                    # Generate tick data
                    tick = TickRecord(
                        timestamp=time.time(),
                        price=current_prices[pair],
                        volume=random.uniform(0.1, 2.0),
                        side=random.choice(['buy', 'sell'])
                    )
                    
                    # Feed tick to agent
                    await self.agent.on_tick(pair, tick)
                    
                    # Generate enhanced signal
                    market_data = self._create_mock_market_data(pair, current_prices[pair])
                    
                    signal = await self.agent.generate_enhanced_signal(
                        pair=pair,
                        best_bid=current_prices[pair] * 0.9999,
                        best_ask=current_prices[pair] * 1.0001,
                        last_price=current_prices[pair],
                        quote_liquidity_usd=2000000.0,
                        market_data=market_data
                    )
                    
                    if signal:
                        self.signals_generated += 1
                        self.logger.info(
                            f"Generated signal: {pair} {signal.side} "
                            f"conf={signal.confidence:.3f} "
                            f"aligned={signal.strategy_alignment} "
                            f"regime={signal.regime_state}"
                        )
                        
                        # Simulate signal execution
                        if await self._simulate_signal_execution(signal):
                            self.signals_executed += 1
                
                # Update regime periodically
                if int(time.time()) % 300 == 0:  # Every 5 minutes
                    await self._simulate_regime_update()
                
                # Log status periodically
                if int(time.time()) % 60 == 0:  # Every minute
                    await self._log_status_update()
                
                # Small delay to prevent overwhelming
                await asyncio.sleep(0.1)
                
            except Exception as e:
                self.logger.error(f"Error in market data simulation: {e}")
                await asyncio.sleep(1)
    
    def _create_mock_market_data(self, pair: str, price: float) -> Dict[str, Any]:
        """Create mock market data for strategies"""
        import numpy as np
        import pandas as pd
        
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
    
    async def _simulate_signal_execution(self, signal) -> bool:
        """Simulate signal execution"""
        try:
            # Validate signal
            is_valid = await self.agent.validate_enhanced_signal(signal)
            
            if not is_valid:
                self.logger.warning(f"Signal validation failed: {signal.signal_id}")
                return False
            
            # Simulate execution success (90% success rate)
            import random
            success = random.random() < 0.9
            
            if success:
                # Simulate PnL
                pnl = random.uniform(-50, 100)  # Random PnL between -50 and +100
                self.total_pnl += pnl
                
                self.logger.info(
                    f"Signal executed: {signal.signal_id} "
                    f"PnL=${pnl:.2f} Total=${self.total_pnl:.2f}"
                )
                
                # Notify agent of trade result
                self.agent.notify_trade_result(signal.pair, pnl)
            
            return success
            
        except Exception as e:
            self.logger.error(f"Error simulating signal execution: {e}")
            return False
    
    async def _simulate_regime_update(self):
        """Simulate market regime updates"""
        regimes = ['bull', 'bear', 'sideways']
        regime = random.choice(regimes)
        confidence = random.uniform(0.6, 0.9)
        suitability = random.uniform(0.5, 0.9)
        
        await self.agent.update_regime(regime, confidence, suitability)
        self.logger.info(f"Regime updated: {regime} (conf={confidence:.2f})")
    
    async def _log_status_update(self):
        """Log periodic status update"""
        status = await self.agent.get_enhanced_status()
        
        self.logger.info("=== Enhanced Scalper Status ===")
        self.logger.info(f"Signals generated: {self.signals_generated}")
        self.logger.info(f"Signals executed: {self.signals_executed}")
        self.logger.info(f"Execution rate: {self.signals_executed/max(self.signals_generated, 1):.2%}")
        self.logger.info(f"Total PnL: ${self.total_pnl:.2f}")
        self.logger.info(f"Market regime: {status['strategy_integration']['market_regime']}")
        self.logger.info(f"Regime confidence: {status['strategy_integration']['regime_confidence']:.2f}")
        self.logger.info(f"Signal alignment rate: {status['signal_alignment_rate']:.2%}")
        self.logger.info(f"Signal filter rate: {status['signal_filter_rate']:.2%}")
        self.logger.info("=============================")
    
    async def _log_performance_summary(self):
        """Log final performance summary"""
        duration = time.time() - self.start_time
        
        self.logger.info("=== Enhanced Scalper Performance Summary ===")
        self.logger.info(f"Runtime: {duration/60:.1f} minutes")
        self.logger.info(f"Signals generated: {self.signals_generated}")
        self.logger.info(f"Signals executed: {self.signals_executed}")
        self.logger.info(f"Execution rate: {self.signals_executed/max(self.signals_generated, 1):.2%}")
        self.logger.info(f"Total PnL: ${self.total_pnl:.2f}")
        self.logger.info(f"Average PnL per signal: ${self.total_pnl/max(self.signals_executed, 1):.2f}")
        self.logger.info(f"Signals per minute: {self.signals_generated/(duration/60):.1f}")
        
        # Get final agent status
        status = await self.agent.get_enhanced_status()
        self.logger.info(f"Final regime: {status['strategy_integration']['market_regime']}")
        self.logger.info(f"Strategy alignment rate: {status['signal_alignment_rate']:.2%}")
        self.logger.info(f"Signal filter rate: {status['signal_filter_rate']:.2%}")
        self.logger.info("===========================================")
    
    def stop(self):
        """Stop the enhanced scalper"""
        self.running = False
        self.logger.info("Enhanced scalper stopping...")


async def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Enhanced Scalper Agent Runner')
    parser.add_argument('--config', type=str, help='Path to configuration file')
    parser.add_argument('--duration', type=int, default=10, help='Demo duration in minutes')
    parser.add_argument('--pairs', nargs='+', default=['BTC/USD', 'ETH/USD'], help='Trading pairs')
    
    args = parser.parse_args()
    
    # Create runner
    runner = EnhancedScalperRunner(config_path=args.config)
    
    # Setup signal handlers
    def signal_handler(signum, frame):
        runner.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Initialize and run
        await runner.initialize()
        await runner.run_demo(duration_minutes=args.duration)
        
    except KeyboardInterrupt:
        runner.stop()
    except Exception as e:
        logging.error(f"Error running enhanced scalper: {e}")
        raise
    finally:
        logging.info("Enhanced scalper runner shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())

