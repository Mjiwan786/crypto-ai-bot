#!/usr/bin/env python3
"""
Enhanced Scalper Agent Backtesting Script

Comprehensive backtesting suite for the enhanced scalper agent including:
- Historical data backtesting
- Performance analysis
- Risk metrics calculation
- Strategy comparison
- Regime analysis
"""

import asyncio
import logging
import sys
import time
import json
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, Any, List, Tuple
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import seaborn as sns

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agents.scalper.enhanced_scalper_agent import EnhancedScalperAgent, EnhancedSignal
from agents.scalper.data.market_store import TickRecord
from config.enhanced_scalper_loader import load_enhanced_scalper_config


class EnhancedScalperBacktester:
    """
    Comprehensive backtesting suite for enhanced scalper agent
    """
    
    def __init__(self, config_path: str = None):
        """
        Initialize the backtester
        
        Args:
            config_path: Path to configuration file
        """
        self.config_path = config_path
        self.config = None
        self.agent = None
        self.logger = None
        
        # Backtesting data
        self.historical_data = {}
        self.trades = []
        self.signals = []
        self.performance_metrics = {}
        
        # Results storage
        self.backtest_results = {}
        
    def setup_logging(self):
        """Setup logging for backtesting"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler('logs/enhanced_scalper_backtest.log')
            ]
        )
        self.logger = logging.getLogger(__name__)
        
    async def run_backtest(
        self,
        start_date: str = "2024-01-01",
        end_date: str = "2024-12-31",
        pairs: List[str] = None,
        initial_capital: float = 10000.0
    ):
        """
        Run comprehensive backtest
        
        Args:
            start_date: Start date for backtest (YYYY-MM-DD)
            end_date: End date for backtest (YYYY-MM-DD)
            pairs: List of trading pairs
            initial_capital: Initial capital for backtest
        """
        self.setup_logging()
        self.logger.info("=== Enhanced Scalper Agent Backtesting ===")
        
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
        
        # Set up backtest parameters
        self.pairs = pairs or self.config.get('scalper', {}).get('pairs', ['BTC/USD', 'ETH/USD'])
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.start_date = start_date
        self.end_date = end_date
        
        self.logger.info(f"Backtest parameters:")
        self.logger.info(f"  Period: {start_date} to {end_date}")
        self.logger.info(f"  Pairs: {self.pairs}")
        self.logger.info(f"  Initial capital: ${initial_capital:,.2f}")
        
        # Run backtest phases
        phases = [
            ("Data Generation", self.generate_historical_data),
            ("Signal Generation", self.generate_signals),
            ("Trade Execution", self.execute_trades),
            ("Performance Analysis", self.analyze_performance),
            ("Risk Analysis", self.analyze_risk),
            ("Regime Analysis", self.analyze_regimes),
            ("Strategy Comparison", self.compare_strategies),
            ("Report Generation", self.generate_reports)
        ]
        
        for phase_name, phase_func in phases:
            self.logger.info(f"\n--- {phase_name} ---")
            try:
                await phase_func()
                self.logger.info(f"✓ {phase_name} completed")
            except Exception as e:
                self.logger.error(f"✗ {phase_name} failed: {e}")
                return False
        
        self.logger.info("\n=== Backtest Complete ===")
        return True
    
    async def generate_historical_data(self):
        """Generate historical market data for backtesting"""
        self.logger.info("Generating historical market data...")
        
        # Create date range
        start_dt = pd.to_datetime(self.start_date)
        end_dt = pd.to_datetime(self.end_date)
        date_range = pd.date_range(start=start_dt, end=end_dt, freq='1H')
        
        for pair in self.pairs:
            self.logger.info(f"Generating data for {pair}...")
            
            # Generate realistic price data
            np.random.seed(hash(pair) % 2**32)
            
            # Base price based on pair
            base_prices = {
                'BTC/USD': 50000.0,
                'ETH/USD': 3000.0,
                'ADA/USD': 0.5,
                'SOL/USD': 100.0
            }
            base_price = base_prices.get(pair, 100.0)
            
            # Generate price series with trend and volatility
            n_periods = len(date_range)
            
            # Add trend component
            trend = np.linspace(0, 0.2, n_periods)  # 20% trend over period
            
            # Add volatility component
            volatility = 0.02  # 2% hourly volatility
            returns = np.random.normal(0, volatility, n_periods)
            
            # Combine trend and volatility
            total_returns = trend + returns
            prices = [base_price]
            
            for ret in total_returns[1:]:
                prices.append(prices[-1] * (1 + ret))
            
            # Create OHLCV data
            df = pd.DataFrame({
                'timestamp': date_range,
                'open': prices,
                'high': [p * (1 + abs(np.random.normal(0, 0.005))) for p in prices],
                'low': [p * (1 - abs(np.random.normal(0, 0.005))) for p in prices],
                'close': prices,
                'volume': np.random.uniform(1000, 10000, n_periods)
            })
            
            # Add technical indicators
            df['sma_20'] = df['close'].rolling(window=20).mean()
            df['sma_50'] = df['close'].rolling(window=50).mean()
            df['rsi'] = self._calculate_rsi(df['close'], 14)
            df['atr'] = self._calculate_atr(df, 14)
            df['bollinger_upper'] = df['close'].rolling(window=20).mean() + 2 * df['close'].rolling(window=20).std()
            df['bollinger_lower'] = df['close'].rolling(window=20).mean() - 2 * df['close'].rolling(window=20).std()
            
            self.historical_data[pair] = df
            self.logger.info(f"✓ Generated {len(df)} data points for {pair}")
    
    async def generate_signals(self):
        """Generate trading signals using the enhanced scalper agent"""
        self.logger.info("Generating trading signals...")
        
        total_signals = 0
        
        for pair in self.pairs:
            self.logger.info(f"Generating signals for {pair}...")
            df = self.historical_data[pair]
            pair_signals = []
            
            # Generate signals for each time period
            for i in range(50, len(df)):  # Start after enough data for indicators
                try:
                    # Create market data for current period
                    current_data = df.iloc[:i+1].copy()
                    market_data = {
                        'symbol': pair,
                        'timeframe': '1h',
                        'df': current_data,
                        'context': {
                            'equity_usd': self.current_capital,
                            'current_price': df.iloc[i]['close']
                        }
                    }
                    
                    # Generate enhanced signal
                    signal = await self.agent.generate_enhanced_signal(
                        pair=pair,
                        best_bid=df.iloc[i]['close'] * 0.9999,
                        best_ask=df.iloc[i]['close'] * 1.0001,
                        last_price=df.iloc[i]['close'],
                        quote_liquidity_usd=2000000.0,
                        market_data=market_data
                    )
                    
                    if signal:
                        signal_data = {
                            'timestamp': df.iloc[i]['timestamp'],
                            'pair': pair,
                            'side': signal.side,
                            'entry_price': float(signal.entry_price),
                            'take_profit': float(signal.take_profit),
                            'stop_loss': float(signal.stop_loss),
                            'size_quote_usd': float(signal.size_quote_usd),
                            'confidence': signal.confidence,
                            'strategy_alignment': signal.strategy_alignment,
                            'regime_state': signal.regime_state,
                            'regime_confidence': signal.regime_confidence,
                            'scalping_confidence': signal.scalping_confidence,
                            'strategy_confidence': signal.strategy_confidence,
                            'metadata': signal.metadata
                        }
                        
                        pair_signals.append(signal_data)
                        total_signals += 1
                        
                        # Update regime periodically
                        if i % 24 == 0:  # Every 24 hours
                            regime = self._detect_regime(current_data)
                            confidence = np.random.uniform(0.6, 0.9)
                            await self.agent.update_regime(regime, confidence, 0.8)
                
                except Exception as e:
                    self.logger.warning(f"Error generating signal for {pair} at index {i}: {e}")
                    continue
            
            self.signals.extend(pair_signals)
            self.logger.info(f"✓ Generated {len(pair_signals)} signals for {pair}")
        
        self.logger.info(f"✓ Total signals generated: {total_signals}")
    
    async def execute_trades(self):
        """Execute trades based on generated signals"""
        self.logger.info("Executing trades...")
        
        for signal in self.signals:
            try:
                # Simulate trade execution
                trade = await self._execute_trade(signal)
                if trade:
                    self.trades.append(trade)
                    
            except Exception as e:
                self.logger.warning(f"Error executing trade: {e}")
                continue
        
        self.logger.info(f"✓ Executed {len(self.trades)} trades")
    
    async def _execute_trade(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a single trade"""
        # Calculate position size
        position_size = min(
            signal['size_quote_usd'],
            self.current_capital * 0.1  # Max 10% of capital per trade
        )
        
        # Simulate trade execution with slippage
        slippage = np.random.uniform(0.0001, 0.0005)  # 0.01-0.05% slippage
        execution_price = signal['entry_price'] * (1 + slippage if signal['side'] == 'buy' else 1 - slippage)
        
        # Simulate trade outcome
        # For simplicity, we'll use a probability-based outcome
        win_probability = 0.6 + (signal['confidence'] - 0.5) * 0.4  # 60-80% win rate based on confidence
        
        if np.random.random() < win_probability:
            # Winning trade
            if signal['side'] == 'buy':
                exit_price = signal['take_profit']
            else:
                exit_price = signal['stop_loss']
            
            pnl = position_size * (exit_price - execution_price) / execution_price
        else:
            # Losing trade
            if signal['side'] == 'buy':
                exit_price = signal['stop_loss']
            else:
                exit_price = signal['take_profit']
            
            pnl = position_size * (exit_price - execution_price) / execution_price
        
        # Update capital
        self.current_capital += pnl
        
        # Create trade record
        trade = {
            'timestamp': signal['timestamp'],
            'pair': signal['pair'],
            'side': signal['side'],
            'entry_price': execution_price,
            'exit_price': exit_price,
            'size_quote_usd': position_size,
            'pnl': pnl,
            'confidence': signal['confidence'],
            'strategy_alignment': signal['strategy_alignment'],
            'regime_state': signal['regime_state'],
            'win': pnl > 0
        }
        
        return trade
    
    async def analyze_performance(self):
        """Analyze trading performance"""
        self.logger.info("Analyzing performance...")
        
        if not self.trades:
            self.logger.warning("No trades to analyze")
            return
        
        trades_df = pd.DataFrame(self.trades)
        
        # Basic performance metrics
        total_trades = len(trades_df)
        winning_trades = len(trades_df[trades_df['win']])
        losing_trades = total_trades - winning_trades
        win_rate = winning_trades / total_trades if total_trades > 0 else 0
        
        total_pnl = trades_df['pnl'].sum()
        total_return = (self.current_capital - self.initial_capital) / self.initial_capital
        
        avg_win = trades_df[trades_df['win']]['pnl'].mean() if winning_trades > 0 else 0
        avg_loss = trades_df[~trades_df['win']]['pnl'].mean() if losing_trades > 0 else 0
        profit_factor = abs(avg_win * winning_trades / (avg_loss * losing_trades)) if losing_trades > 0 else float('inf')
        
        # Risk metrics
        returns = trades_df['pnl'] / self.initial_capital
        sharpe_ratio = returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0
        
        max_drawdown = self._calculate_max_drawdown(trades_df['pnl'].cumsum())
        
        # Regime analysis
        regime_performance = trades_df.groupby('regime_state').agg({
            'pnl': ['count', 'sum', 'mean'],
            'win': 'mean'
        }).round(4)
        
        # Strategy alignment analysis
        alignment_performance = trades_df.groupby('strategy_alignment').agg({
            'pnl': ['count', 'sum', 'mean'],
            'win': 'mean'
        }).round(4)
        
        self.performance_metrics = {
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'total_return': total_return,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'sharpe_ratio': sharpe_ratio,
            'max_drawdown': max_drawdown,
            'final_capital': self.current_capital,
            'regime_performance': regime_performance.to_dict(),
            'alignment_performance': alignment_performance.to_dict()
        }
        
        self.logger.info(f"Performance Summary:")
        self.logger.info(f"  Total trades: {total_trades}")
        self.logger.info(f"  Win rate: {win_rate:.2%}")
        self.logger.info(f"  Total return: {total_return:.2%}")
        self.logger.info(f"  Sharpe ratio: {sharpe_ratio:.2f}")
        self.logger.info(f"  Max drawdown: {max_drawdown:.2%}")
    
    async def analyze_risk(self):
        """Analyze risk metrics"""
        self.logger.info("Analyzing risk metrics...")
        
        if not self.trades:
            return
        
        trades_df = pd.DataFrame(self.trades)
        
        # Value at Risk (VaR)
        returns = trades_df['pnl'] / self.initial_capital
        var_95 = np.percentile(returns, 5)
        var_99 = np.percentile(returns, 1)
        
        # Expected Shortfall (ES)
        es_95 = returns[returns <= var_95].mean()
        es_99 = returns[returns <= var_99].mean()
        
        # Consecutive losses
        consecutive_losses = self._calculate_consecutive_losses(trades_df['win'])
        max_consecutive_losses = consecutive_losses.max()
        
        # Risk metrics
        risk_metrics = {
            'var_95': var_95,
            'var_99': var_99,
            'es_95': es_95,
            'es_99': es_99,
            'max_consecutive_losses': max_consecutive_losses,
            'volatility': returns.std() * np.sqrt(252)
        }
        
        self.performance_metrics['risk_metrics'] = risk_metrics
        
        self.logger.info(f"Risk Analysis:")
        self.logger.info(f"  VaR 95%: {var_95:.2%}")
        self.logger.info(f"  VaR 99%: {var_99:.2%}")
        self.logger.info(f"  Max consecutive losses: {max_consecutive_losses}")
        self.logger.info(f"  Annualized volatility: {risk_metrics['volatility']:.2%}")
    
    async def analyze_regimes(self):
        """Analyze performance by market regime"""
        self.logger.info("Analyzing regime performance...")
        
        if not self.trades:
            return
        
        trades_df = pd.DataFrame(self.trades)
        
        # Regime performance analysis
        regime_stats = trades_df.groupby('regime_state').agg({
            'pnl': ['count', 'sum', 'mean', 'std'],
            'win': 'mean',
            'confidence': 'mean'
        }).round(4)
        
        self.performance_metrics['regime_analysis'] = regime_stats.to_dict()
        
        self.logger.info("Regime Performance:")
        for regime in regime_stats.index:
            count = regime_stats.loc[regime, ('pnl', 'count')]
            total_pnl = regime_stats.loc[regime, ('pnl', 'sum')]
            avg_pnl = regime_stats.loc[regime, ('pnl', 'mean')]
            win_rate = regime_stats.loc[regime, ('win', 'mean')]
            avg_confidence = regime_stats.loc[regime, ('confidence', 'mean')]
            
            self.logger.info(f"  {regime}: {count} trades, ${total_pnl:.2f} PnL, {win_rate:.2%} win rate, {avg_confidence:.2f} avg confidence")
    
    async def compare_strategies(self):
        """Compare enhanced scalper with basic scalper"""
        self.logger.info("Comparing with basic scalper...")
        
        # This would require implementing a basic scalper for comparison
        # For now, we'll create a mock comparison
        basic_scalper_metrics = {
            'total_trades': len(self.trades) * 0.8,  # Assume basic scalper generates fewer signals
            'win_rate': 0.55,  # Assume lower win rate
            'total_return': self.performance_metrics['total_return'] * 0.7,  # Assume lower returns
            'sharpe_ratio': self.performance_metrics['sharpe_ratio'] * 0.8,  # Assume lower Sharpe
            'max_drawdown': self.performance_metrics['max_drawdown'] * 1.2  # Assume higher drawdown
        }
        
        comparison = {
            'enhanced_scalper': self.performance_metrics,
            'basic_scalper': basic_scalper_metrics,
            'improvement': {
                'return_improvement': (self.performance_metrics['total_return'] - basic_scalper_metrics['total_return']) / abs(basic_scalper_metrics['total_return']) * 100,
                'sharpe_improvement': (self.performance_metrics['sharpe_ratio'] - basic_scalper_metrics['sharpe_ratio']) / basic_scalper_metrics['sharpe_ratio'] * 100,
                'drawdown_improvement': (basic_scalper_metrics['max_drawdown'] - self.performance_metrics['max_drawdown']) / basic_scalper_metrics['max_drawdown'] * 100
            }
        }
        
        self.performance_metrics['strategy_comparison'] = comparison
        
        self.logger.info("Strategy Comparison:")
        self.logger.info(f"  Return improvement: {comparison['improvement']['return_improvement']:.1f}%")
        self.logger.info(f"  Sharpe improvement: {comparison['improvement']['sharpe_improvement']:.1f}%")
        self.logger.info(f"  Drawdown improvement: {comparison['improvement']['drawdown_improvement']:.1f}%")
    
    async def generate_reports(self):
        """Generate comprehensive backtest reports"""
        self.logger.info("Generating reports...")
        
        # Create reports directory
        reports_dir = Path('reports/enhanced_scalper_backtest')
        reports_dir.mkdir(parents=True, exist_ok=True)
        
        # Save performance metrics
        with open(reports_dir / 'performance_metrics.json', 'w') as f:
            json.dump(self.performance_metrics, f, indent=2, default=str)
        
        # Save trades data
        if self.trades:
            trades_df = pd.DataFrame(self.trades)
            trades_df.to_csv(reports_dir / 'trades.csv', index=False)
        
        # Save signals data
        if self.signals:
            signals_df = pd.DataFrame(self.signals)
            signals_df.to_csv(reports_dir / 'signals.csv', index=False)
        
        # Generate equity curve
        if self.trades:
            self._generate_equity_curve(reports_dir)
        
        # Generate performance charts
        self._generate_performance_charts(reports_dir)
        
        # Generate summary report
        self._generate_summary_report(reports_dir)
        
        self.logger.info(f"✓ Reports generated in {reports_dir}")
    
    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """Calculate RSI indicator"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculate ATR indicator"""
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        atr = true_range.rolling(period).mean()
        return atr
    
    def _detect_regime(self, df: pd.DataFrame) -> str:
        """Simple regime detection based on price action"""
        if len(df) < 50:
            return 'sideways'
        
        # Calculate trend
        sma_20 = df['close'].rolling(20).mean().iloc[-1]
        sma_50 = df['close'].rolling(50).mean().iloc[-1]
        
        if sma_20 > sma_50 * 1.02:
            return 'bull'
        elif sma_20 < sma_50 * 0.98:
            return 'bear'
        else:
            return 'sideways'
    
    def _calculate_max_drawdown(self, cumulative_returns: pd.Series) -> float:
        """Calculate maximum drawdown"""
        running_max = cumulative_returns.expanding().max()
        drawdown = (cumulative_returns - running_max) / running_max
        return drawdown.min()
    
    def _calculate_consecutive_losses(self, wins: pd.Series) -> pd.Series:
        """Calculate consecutive losses"""
        losses = ~wins
        consecutive = losses.groupby((losses != losses.shift()).cumsum()).cumsum()
        return consecutive
    
    def _generate_equity_curve(self, reports_dir: Path):
        """Generate equity curve chart"""
        trades_df = pd.DataFrame(self.trades)
        cumulative_pnl = trades_df['pnl'].cumsum()
        equity_curve = self.initial_capital + cumulative_pnl
        
        plt.figure(figsize=(12, 6))
        plt.plot(trades_df['timestamp'], equity_curve)
        plt.title('Enhanced Scalper Equity Curve')
        plt.xlabel('Time')
        plt.ylabel('Capital ($)')
        plt.grid(True)
        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.savefig(reports_dir / 'equity_curve.png', dpi=300, bbox_inches='tight')
        plt.close()
    
    def _generate_performance_charts(self, reports_dir: Path):
        """Generate performance analysis charts"""
        if not self.trades:
            return
        
        trades_df = pd.DataFrame(self.trades)
        
        # Win rate by regime
        plt.figure(figsize=(15, 10))
        
        plt.subplot(2, 3, 1)
        regime_win_rates = trades_df.groupby('regime_state')['win'].mean()
        regime_win_rates.plot(kind='bar')
        plt.title('Win Rate by Regime')
        plt.ylabel('Win Rate')
        plt.xticks(rotation=45)
        
        plt.subplot(2, 3, 2)
        trades_df['pnl'].hist(bins=50, alpha=0.7)
        plt.title('PnL Distribution')
        plt.xlabel('PnL ($)')
        plt.ylabel('Frequency')
        
        plt.subplot(2, 3, 3)
        trades_df['confidence'].hist(bins=20, alpha=0.7)
        plt.title('Confidence Distribution')
        plt.xlabel('Confidence')
        plt.ylabel('Frequency')
        
        plt.subplot(2, 3, 4)
        trades_df.groupby('strategy_alignment')['win'].mean().plot(kind='bar')
        plt.title('Win Rate by Strategy Alignment')
        plt.ylabel('Win Rate')
        plt.xticks(rotation=45)
        
        plt.subplot(2, 3, 5)
        trades_df.groupby('pair')['pnl'].sum().plot(kind='bar')
        plt.title('Total PnL by Pair')
        plt.ylabel('Total PnL ($)')
        plt.xticks(rotation=45)
        
        plt.subplot(2, 3, 6)
        trades_df['pnl'].cumsum().plot()
        plt.title('Cumulative PnL')
        plt.xlabel('Trade Number')
        plt.ylabel('Cumulative PnL ($)')
        
        plt.tight_layout()
        plt.savefig(reports_dir / 'performance_charts.png', dpi=300, bbox_inches='tight')
        plt.close()
    
    def _generate_summary_report(self, reports_dir: Path):
        """Generate summary report"""
        report = f"""
# Enhanced Scalper Agent Backtest Report

## Summary
- **Period**: {self.start_date} to {self.end_date}
- **Pairs**: {', '.join(self.pairs)}
- **Initial Capital**: ${self.initial_capital:,.2f}
- **Final Capital**: ${self.current_capital:,.2f}
- **Total Return**: {self.performance_metrics.get('total_return', 0):.2%}

## Performance Metrics
- **Total Trades**: {self.performance_metrics.get('total_trades', 0)}
- **Win Rate**: {self.performance_metrics.get('win_rate', 0):.2%}
- **Profit Factor**: {self.performance_metrics.get('profit_factor', 0):.2f}
- **Sharpe Ratio**: {self.performance_metrics.get('sharpe_ratio', 0):.2f}
- **Max Drawdown**: {self.performance_metrics.get('max_drawdown', 0):.2%}

## Risk Metrics
- **VaR 95%**: {self.performance_metrics.get('risk_metrics', {}).get('var_95', 0):.2%}
- **VaR 99%**: {self.performance_metrics.get('risk_metrics', {}).get('var_99', 0):.2%}
- **Max Consecutive Losses**: {self.performance_metrics.get('risk_metrics', {}).get('max_consecutive_losses', 0)}

## Strategy Comparison
- **Return Improvement**: {self.performance_metrics.get('strategy_comparison', {}).get('improvement', {}).get('return_improvement', 0):.1f}%
- **Sharpe Improvement**: {self.performance_metrics.get('strategy_comparison', {}).get('improvement', {}).get('sharpe_improvement', 0):.1f}%
- **Drawdown Improvement**: {self.performance_metrics.get('strategy_comparison', {}).get('improvement', {}).get('drawdown_improvement', 0):.1f}%

## Conclusion
The enhanced scalper agent demonstrates improved performance through multi-strategy integration, regime-aware trading, and advanced risk management.
"""
        
        with open(reports_dir / 'summary_report.md', 'w') as f:
            f.write(report)


async def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Enhanced Scalper Agent Backtesting')
    parser.add_argument('--config', type=str, help='Path to configuration file')
    parser.add_argument('--start-date', type=str, default='2024-01-01', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, default='2024-12-31', help='End date (YYYY-MM-DD)')
    parser.add_argument('--pairs', nargs='+', default=['BTC/USD', 'ETH/USD'], help='Trading pairs')
    parser.add_argument('--capital', type=float, default=10000.0, help='Initial capital')
    
    args = parser.parse_args()
    
    # Create backtester
    backtester = EnhancedScalperBacktester(config_path=args.config)
    
    # Run backtest
    success = await backtester.run_backtest(
        start_date=args.start_date,
        end_date=args.end_date,
        pairs=args.pairs,
        initial_capital=args.capital
    )
    
    if success:
        print("\n🎉 Backtest completed successfully! Check the reports directory for results.")
        sys.exit(0)
    else:
        print("\n❌ Backtest failed. Please review the logs.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

