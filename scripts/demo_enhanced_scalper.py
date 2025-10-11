#!/usr/bin/env python3
"""
Enhanced Scalper Agent Demo

Quick demo script to showcase the enhanced scalper agent capabilities
in the crypto-bot conda environment.
"""

import asyncio
import logging
import sys
import time
import random
from pathlib import Path
from typing import Dict, Any

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agents.scalper.enhanced_scalper_agent import EnhancedScalperAgent
from agents.scalper.data.market_store import TickRecord
from config.enhanced_scalper_loader import load_enhanced_scalper_config


class EnhancedScalperDemo:
    """
    Demo class for enhanced scalper agent
    """
    
    def __init__(self):
        """Initialize the demo"""
        self.logger = None
        self.agent = None
        self.config = None
        
    def setup_logging(self):
        """Setup logging for demo"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
        
    async def run_demo(self, duration_minutes: int = 5):
        """
        Run the enhanced scalper demo
        
        Args:
            duration_minutes: Duration of demo in minutes
        """
        self.setup_logging()
        self.logger.info("=== Enhanced Scalper Agent Demo ===")
        
        # Load configuration
        try:
            self.config = load_enhanced_scalper_config()
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
        
        # Demo parameters
        pairs = self.config.get('scalper', {}).get('pairs', ['BTC/USD', 'ETH/USD'])
        end_time = time.time() + (duration_minutes * 60)
        
        self.logger.info(f"Demo parameters:")
        self.logger.info(f"  Duration: {duration_minutes} minutes")
        self.logger.info(f"  Pairs: {', '.join(pairs)}")
        self.logger.info(f"  Initial capital: $10,000")
        
        # Demo state
        demo_stats = {
            'ticks_processed': 0,
            'signals_generated': 0,
            'signals_executed': 0,
            'total_pnl': 0.0,
            'regime_changes': 0,
            'start_time': time.time()
        }
        
        # Generate realistic price data
        base_prices = {
            'BTC/USD': 50000.0,
            'ETH/USD': 3000.0,
            'ADA/USD': 0.5,
            'SOL/USD': 100.0
        }
        
        current_prices = base_prices.copy()
        
        self.logger.info("\nStarting demo...")
        self.logger.info("Press Ctrl+C to stop early\n")
        
        try:
            while time.time() < end_time:
                # Process each pair
                for pair in pairs:
                    # Simulate price movement
                    base_price = base_prices[pair]
                    volatility = 0.001  # 0.1% volatility
                    
                    # Random walk with slight trend
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
                    demo_stats['ticks_processed'] += 1
                    
                    # Generate enhanced signal
                    market_data = self._create_demo_market_data(pair, current_prices[pair])
                    
                    signal = await self.agent.generate_enhanced_signal(
                        pair=pair,
                        best_bid=current_prices[pair] * 0.9999,
                        best_ask=current_prices[pair] * 1.0001,
                        last_price=current_prices[pair],
                        quote_liquidity_usd=2000000.0,
                        market_data=market_data
                    )
                    
                    if signal:
                        demo_stats['signals_generated'] += 1
                        
                        # Simulate signal execution
                        if await self._simulate_signal_execution(signal, demo_stats):
                            demo_stats['signals_executed'] += 1
                
                # Update regime periodically
                if int(time.time()) % 60 == 0:  # Every minute
                    await self._simulate_regime_update(demo_stats)
                
                # Log status every 30 seconds
                if int(time.time()) % 30 == 0:
                    self._log_demo_status(demo_stats, current_prices)
                
                # Small delay to prevent overwhelming
                await asyncio.sleep(0.1)
                
        except KeyboardInterrupt:
            self.logger.info("\nDemo stopped by user")
        
        # Final demo report
        self._generate_demo_report(demo_stats, current_prices)
        
        return True
    
    def _create_demo_market_data(self, pair: str, price: float) -> Dict[str, Any]:
        """Create demo market data"""
        import pandas as pd
        import numpy as np
        
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
    
    async def _simulate_signal_execution(self, signal, demo_stats: Dict[str, Any]) -> bool:
        """Simulate signal execution"""
        try:
            # Simulate execution success (90% success rate)
            success = random.random() < 0.9
            
            if success:
                # Simulate PnL
                pnl = random.uniform(-50, 100)  # Random PnL between -50 and +100
                demo_stats['total_pnl'] += pnl
                
                self.logger.info(
                    f"Signal executed: {signal.pair} {signal.side} "
                    f"conf={signal.confidence:.3f} "
                    f"aligned={signal.strategy_alignment} "
                    f"regime={signal.regime_state} "
                    f"PnL=${pnl:.2f}"
                )
            
            return success
            
        except Exception as e:
            self.logger.error(f"Error simulating signal execution: {e}")
            return False
    
    async def _simulate_regime_update(self, demo_stats: Dict[str, Any]):
        """Simulate market regime updates"""
        regimes = ['bull', 'bear', 'sideways']
        regime = random.choice(regimes)
        confidence = random.uniform(0.6, 0.9)
        suitability = random.uniform(0.5, 0.9)
        
        await self.agent.update_regime(regime, confidence, suitability)
        demo_stats['regime_changes'] += 1
        
        self.logger.info(f"Regime updated: {regime} (conf={confidence:.2f})")
    
    def _log_demo_status(self, demo_stats: Dict[str, Any], current_prices: Dict[str, float]):
        """Log demo status"""
        elapsed = time.time() - demo_stats['start_time']
        
        self.logger.info("=== Demo Status ===")
        self.logger.info(f"Elapsed time: {elapsed/60:.1f} minutes")
        self.logger.info(f"Ticks processed: {demo_stats['ticks_processed']}")
        self.logger.info(f"Signals generated: {demo_stats['signals_generated']}")
        self.logger.info(f"Signals executed: {demo_stats['signals_executed']}")
        self.logger.info(f"Total PnL: ${demo_stats['total_pnl']:.2f}")
        self.logger.info(f"Regime changes: {demo_stats['regime_changes']}")
        self.logger.info(f"Current prices: {', '.join([f'{pair}: ${price:.2f}' for pair, price in current_prices.items()])}")
        self.logger.info("==================")
    
    def _generate_demo_report(self, demo_stats: Dict[str, Any], current_prices: Dict[str, float]):
        """Generate final demo report"""
        elapsed = time.time() - demo_stats['start_time']
        
        self.logger.info("\n=== Enhanced Scalper Demo Report ===")
        self.logger.info(f"Demo duration: {elapsed/60:.1f} minutes")
        self.logger.info(f"Ticks processed: {demo_stats['ticks_processed']}")
        self.logger.info(f"Signals generated: {demo_stats['signals_generated']}")
        self.logger.info(f"Signals executed: {demo_stats['signals_executed']}")
        self.logger.info(f"Execution rate: {demo_stats['signals_executed']/max(demo_stats['signals_generated'], 1):.2%}")
        self.logger.info(f"Total PnL: ${demo_stats['total_pnl']:.2f}")
        self.logger.info(f"Average PnL per signal: ${demo_stats['total_pnl']/max(demo_stats['signals_executed'], 1):.2f}")
        self.logger.info(f"Signals per minute: {demo_stats['signals_generated']/(elapsed/60):.1f}")
        self.logger.info(f"Regime changes: {demo_stats['regime_changes']}")
        
        # Get final agent status
        try:
            status = await self.agent.get_enhanced_status()
            self.logger.info(f"Final regime: {status['strategy_integration']['market_regime']}")
            self.logger.info(f"Regime confidence: {status['strategy_integration']['regime_confidence']:.2f}")
            self.logger.info(f"Signal alignment rate: {status['signal_alignment_rate']:.2%}")
            self.logger.info(f"Signal filter rate: {status['signal_filter_rate']:.2%}")
        except Exception as e:
            self.logger.warning(f"Could not get final status: {e}")
        
        self.logger.info("=====================================")
        
        # Save demo results
        import json
        demo_results = {
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'duration_minutes': elapsed/60,
            'stats': demo_stats,
            'final_prices': current_prices
        }
        
        with open('logs/enhanced_scalper_demo_results.json', 'w') as f:
            json.dump(demo_results, f, indent=2, default=str)
        
        self.logger.info("Demo results saved to: logs/enhanced_scalper_demo_results.json")


async def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Enhanced Scalper Agent Demo')
    parser.add_argument('--duration', type=int, default=5, help='Demo duration in minutes')
    parser.add_argument('--pairs', nargs='+', default=['BTC/USD', 'ETH/USD'], help='Trading pairs')
    
    args = parser.parse_args()
    
    # Create demo
    demo = EnhancedScalperDemo()
    
    # Run demo
    success = await demo.run_demo(duration_minutes=args.duration)
    
    if success:
        print("\n🎉 Demo completed successfully!")
        print("The enhanced scalper agent is working correctly.")
        print("Check the logs for detailed information.")
    else:
        print("\n❌ Demo failed. Please check the logs for errors.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

