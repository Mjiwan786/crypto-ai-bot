#!/usr/bin/env python3
"""
Trade Analysis Script - Analyze trading performance from CSV or Redis streams

Usage:
    python analyze_trades.py --source csv --file trades.csv
    python analyze_trades.py --source redis --stream trades:executed
    python analyze_trades.py --source csv --file trades.csv --plot
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import redis
from urllib.parse import urlparse

def setup_logging():
    """Setup basic logging"""
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    return logging.getLogger(__name__)

logger = setup_logging()

class TradeAnalyzer:
    """Analyze trading performance from various sources"""
    
    def __init__(self):
        self.trades_data = []
        self.cumulative_pnl = []
        self.trade_returns = []
        
    def load_from_csv(self, file_path: str) -> pd.DataFrame:
        """Load trade data from CSV file"""
        logger.info(f"Loading trades from CSV: {file_path}")
        
        try:
            df = pd.read_csv(file_path)
            logger.info(f"Loaded {len(df)} trades from CSV")
            return df
        except Exception as e:
            logger.error(f"Failed to load CSV: {e}")
            sys.exit(1)
    
    async def load_from_redis(self, stream_name: str) -> pd.DataFrame:
        """Load trade data from Redis stream"""
        logger.info(f"Loading trades from Redis stream: {stream_name}")
        
        try:
            # Connect to Redis
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            parsed = urlparse(redis_url)
            use_ssl = parsed.scheme == "rediss"
            
            if use_ssl:
                import ssl
                ssl_context = ssl.create_default_context()
                ca_cert_path = os.getenv("REDIS_TLS_CERT_PATH", "/etc/ssl/certs/ca-certificates.crt")
                
                if os.path.exists(ca_cert_path):
                    ssl_context.load_verify_locations(ca_cert_path)
                
                client = redis.from_url(
                    redis_url,
                    ssl_cert_reqs=ssl.CERT_REQUIRED,
                    ssl_ca_certs=ca_cert_path,
                    decode_responses=True
                )
            else:
                client = redis.from_url(redis_url, decode_responses=True)
            
            # Test connection
            client.ping()
            logger.info("Connected to Redis successfully")
            
            # Read from stream
            trades = []
            try:
                # Read all messages from stream
                messages = client.xrange(stream_name, count=10000)  # Adjust count as needed
                
                for message_id, fields in messages:
                    try:
                        # Parse trade data from stream message
                        trade_data = self._parse_redis_trade(fields)
                        if trade_data:
                            trades.append(trade_data)
                    except Exception as e:
                        logger.warning(f"Failed to parse message {message_id}: {e}")
                        continue
                
                logger.info(f"Loaded {len(trades)} trades from Redis stream")
                
                if not trades:
                    logger.warning("No trades found in Redis stream")
                    return pd.DataFrame()
                
                return pd.DataFrame(trades)
                
            except redis.RedisError as e:
                logger.error(f"Redis stream error: {e}")
                sys.exit(1)
                
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            sys.exit(1)
    
    def _parse_redis_trade(self, fields: Dict[str, str]) -> Optional[Dict[str, Any]]:
        """Parse trade data from Redis stream fields"""
        try:
            # Expected fields in Redis stream
            required_fields = ['symbol', 'side', 'price', 'quantity', 'timestamp']
            
            # Check if all required fields are present
            if not all(field in fields for field in required_fields):
                return None
            
            # Parse numeric fields
            price = float(fields['price'])
            quantity = float(fields['quantity'])
            timestamp = fields['timestamp']
            
            # Calculate PnL if both buy and sell are present
            pnl = None
            if 'pnl' in fields:
                pnl = float(fields['pnl'])
            
            return {
                'symbol': fields['symbol'],
                'side': fields['side'],
                'price': price,
                'quantity': quantity,
                'timestamp': timestamp,
                'pnl': pnl,
                'strategy': fields.get('strategy', 'unknown')
            }
            
        except (ValueError, KeyError) as e:
            logger.warning(f"Failed to parse trade data: {e}")
            return None
    
    def calculate_metrics(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Calculate trading performance metrics"""
        if df.empty:
            logger.warning("No trade data to analyze")
            return {}
        
        logger.info("Calculating trading metrics...")
        
        # Group trades by symbol and strategy for analysis
        metrics = {}
        
        for (symbol, strategy), group in df.groupby(['symbol', 'strategy']):
            key = f"{symbol}_{strategy}"
            
            # Calculate trade pairs (buy/sell)
            buy_trades = group[group['side'] == 'buy'].sort_values('timestamp')
            sell_trades = group[group['side'] == 'sell'].sort_values('timestamp')
            
            if len(buy_trades) == 0 or len(sell_trades) == 0:
                continue
            
            # Match buy/sell pairs
            trade_pairs = []
            buy_idx = 0
            sell_idx = 0
            
            while buy_idx < len(buy_trades) and sell_idx < len(sell_trades):
                buy_trade = buy_trades.iloc[buy_idx]
                sell_trade = sell_trades.iloc[sell_idx]
                
                # Ensure sell comes after buy
                if sell_trade['timestamp'] > buy_trade['timestamp']:
                    pnl = sell_trade['price'] * sell_trade['quantity'] - buy_trade['price'] * buy_trade['quantity']
                    return_pct = (sell_trade['price'] - buy_trade['price']) / buy_trade['price']
                    
                    trade_pairs.append({
                        'buy_price': buy_trade['price'],
                        'sell_price': sell_trade['price'],
                        'quantity': buy_trade['quantity'],
                        'pnl': pnl,
                        'return_pct': return_pct,
                        'buy_time': buy_trade['timestamp'],
                        'sell_time': sell_trade['timestamp']
                    })
                    
                    buy_idx += 1
                    sell_idx += 1
                else:
                    sell_idx += 1
            
            if not trade_pairs:
                continue
            
            # Calculate metrics
            trade_pairs_df = pd.DataFrame(trade_pairs)
            
            total_trades = len(trade_pairs_df)
            winning_trades = trade_pairs_df[trade_pairs_df['pnl'] > 0]
            losing_trades = trade_pairs_df[trade_pairs_df['pnl'] <= 0]
            
            win_rate = len(winning_trades) / total_trades * 100 if total_trades > 0 else 0
            total_pnl = trade_pairs_df['pnl'].sum()
            avg_return = trade_pairs_df['return_pct'].mean() * 100 if total_trades > 0 else 0
            
            # Calculate max drawdown
            cumulative_pnl = trade_pairs_df['pnl'].cumsum()
            running_max = cumulative_pnl.expanding().max()
            drawdown = cumulative_pnl - running_max
            max_drawdown = drawdown.min()
            
            # Calculate average R (risk/reward ratio)
            avg_win = winning_trades['return_pct'].mean() * 100 if len(winning_trades) > 0 else 0
            avg_loss = abs(losing_trades['return_pct'].mean()) * 100 if len(losing_trades) > 0 else 0
            avg_r = avg_win / avg_loss if avg_loss > 0 else 0
            
            metrics[key] = {
                'symbol': symbol,
                'strategy': strategy,
                'total_trades': total_trades,
                'win_rate': win_rate,
                'total_pnl': total_pnl,
                'avg_return': avg_return,
                'max_drawdown': max_drawdown,
                'avg_r': avg_r,
                'avg_win': avg_win,
                'avg_loss': avg_loss,
                'max_win': trade_pairs_df['return_pct'].max() * 100,
                'max_loss': trade_pairs_df['return_pct'].min() * 100,
                'trades': trade_pairs_df
            }
        
        return metrics
    
    def print_summary(self, metrics: Dict[str, Any]):
        """Print readable summary of trading performance"""
        print("\n" + "="*80)
        print("📊 TRADING PERFORMANCE ANALYSIS")
        print("="*80)
        
        if not metrics:
            print("❌ No trade data to analyze")
            return
        
        # Overall summary
        total_trades = sum(m['total_trades'] for m in metrics.values())
        total_pnl = sum(m['total_pnl'] for m in metrics.values())
        avg_win_rate = np.mean([m['win_rate'] for m in metrics.values()])
        avg_r = np.mean([m['avg_r'] for m in metrics.values() if m['avg_r'] > 0])
        max_dd = min([m['max_drawdown'] for m in metrics.values()])
        
        print(f"\n📈 OVERALL PERFORMANCE:")
        print(f"   Total Trades: {total_trades:,}")
        print(f"   Win Rate: {avg_win_rate:.1f}%")
        print(f"   Total PnL: ${total_pnl:,.2f}")
        print(f"   Average R: {avg_r:.2f}")
        print(f"   Max Drawdown: ${max_dd:,.2f}")
        
        # Per strategy breakdown
        print(f"\n📊 STRATEGY BREAKDOWN:")
        print("-" * 80)
        
        for key, m in metrics.items():
            print(f"\n🎯 {m['symbol']} - {m['strategy'].upper()}:")
            print(f"   Trades: {m['total_trades']:,}")
            print(f"   Win Rate: {m['win_rate']:.1f}%")
            print(f"   PnL: ${m['total_pnl']:,.2f}")
            print(f"   Avg Return: {m['avg_return']:.2f}%")
            print(f"   Avg R: {m['avg_r']:.2f}")
            print(f"   Max DD: ${m['max_drawdown']:,.2f}")
            print(f"   Best Trade: {m['max_win']:.2f}%")
            print(f"   Worst Trade: {m['max_loss']:.2f}%")
        
        # Performance assessment
        print(f"\n🎯 PERFORMANCE ASSESSMENT:")
        print("-" * 80)
        
        if avg_win_rate >= 60:
            print("✅ Excellent win rate")
        elif avg_win_rate >= 50:
            print("⚠️  Moderate win rate")
        else:
            print("❌ Poor win rate")
        
        if avg_r >= 2.0:
            print("✅ Excellent risk/reward ratio")
        elif avg_r >= 1.5:
            print("⚠️  Good risk/reward ratio")
        else:
            print("❌ Poor risk/reward ratio")
        
        if max_dd >= -1000:
            print("✅ Low drawdown")
        elif max_dd >= -5000:
            print("⚠️  Moderate drawdown")
        else:
            print("❌ High drawdown")
    
    def plot_pnl(self, metrics: Dict[str, Any], output_path: str = "reports/last_pnl.png"):
        """Create PnL plot using matplotlib"""
        logger.info(f"Creating PnL plot: {output_path}")
        
        # Create reports directory
        Path("reports").mkdir(exist_ok=True)
        
        # Prepare data for plotting
        fig, axes = plt.subplots(2, 2, figsize=(15, 10))
        fig.suptitle('Trading Performance Analysis', fontsize=16, fontweight='bold')
        
        # 1. Cumulative PnL
        ax1 = axes[0, 0]
        for key, m in metrics.items():
            if not m['trades'].empty:
                cumulative_pnl = m['trades']['pnl'].cumsum()
                ax1.plot(cumulative_pnl.values, label=f"{m['symbol']} - {m['strategy']}", linewidth=2)
        ax1.set_title('Cumulative PnL')
        ax1.set_xlabel('Trade Number')
        ax1.set_ylabel('PnL ($)')
        ax1.grid(True, alpha=0.3)
        ax1.legend()
        
        # 2. Win Rate by Strategy
        ax2 = axes[0, 1]
        strategies = list(metrics.keys())
        win_rates = [m['win_rate'] for m in metrics.values()]
        bars = ax2.bar(strategies, win_rates, color=['green' if wr >= 50 else 'red' for wr in win_rates])
        ax2.set_title('Win Rate by Strategy')
        ax2.set_ylabel('Win Rate (%)')
        ax2.set_xticklabels(strategies, rotation=45, ha='right')
        ax2.axhline(y=50, color='black', linestyle='--', alpha=0.5)
        
        # Add value labels on bars
        for bar, rate in zip(bars, win_rates):
            height = bar.get_height()
            ax2.text(bar.get_x() + bar.get_width()/2., height + 1,
                    f'{rate:.1f}%', ha='center', va='bottom')
        
        # 3. PnL Distribution
        ax3 = axes[1, 0]
        all_pnl = []
        for m in metrics.values():
            if not m['trades'].empty:
                all_pnl.extend(m['trades']['pnl'].tolist())
        
        if all_pnl:
            ax3.hist(all_pnl, bins=30, alpha=0.7, color='blue', edgecolor='black')
            ax3.set_title('PnL Distribution')
            ax3.set_xlabel('PnL ($)')
            ax3.set_ylabel('Frequency')
            ax3.axvline(x=0, color='red', linestyle='--', alpha=0.7)
            ax3.grid(True, alpha=0.3)
        
        # 4. Drawdown
        ax4 = axes[1, 1]
        for key, m in metrics.items():
            if not m['trades'].empty:
                cumulative_pnl = m['trades']['pnl'].cumsum()
                running_max = cumulative_pnl.expanding().max()
                drawdown = cumulative_pnl - running_max
                ax4.plot(drawdown.values, label=f"{m['symbol']} - {m['strategy']}", linewidth=2)
        ax4.set_title('Drawdown')
        ax4.set_xlabel('Trade Number')
        ax4.set_ylabel('Drawdown ($)')
        ax4.grid(True, alpha=0.3)
        ax4.legend()
        
        plt.tight_layout()
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        logger.info(f"Plot saved to {output_path}")
        
        # Show plot if in interactive mode
        try:
            plt.show()
        except:
            pass  # Headless environment

async def main():
    """Main function"""
    parser = argparse.ArgumentParser(
        description="Analyze trading performance from CSV or Redis streams",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python analyze_trades.py --source csv --file trades.csv
  python analyze_trades.py --source redis --stream trades:executed
  python analyze_trades.py --source csv --file trades.csv --plot
        """
    )
    
    parser.add_argument(
        "--source",
        choices=["csv", "redis"],
        required=True,
        help="Data source: csv or redis"
    )
    
    parser.add_argument(
        "--file",
        help="CSV file path (required for csv source)"
    )
    
    parser.add_argument(
        "--stream",
        help="Redis stream name (required for redis source)"
    )
    
    parser.add_argument(
        "--plot",
        action="store_true",
        help="Generate PnL plot and save to reports/last_pnl.png"
    )
    
    args = parser.parse_args()
    
    # Validate arguments
    if args.source == "csv" and not args.file:
        logger.error("--file is required when using csv source")
        sys.exit(1)
    
    if args.source == "redis" and not args.stream:
        logger.error("--stream is required when using redis source")
        sys.exit(1)
    
    # Initialize analyzer
    analyzer = TradeAnalyzer()
    
    # Load data
    if args.source == "csv":
        df = analyzer.load_from_csv(args.file)
    else:  # redis
        df = await analyzer.load_from_redis(args.stream)
    
    if df.empty:
        logger.error("No trade data found")
        sys.exit(1)
    
    # Calculate metrics
    metrics = analyzer.calculate_metrics(df)
    
    # Print summary
    analyzer.print_summary(metrics)
    
    # Generate plot if requested
    if args.plot:
        analyzer.plot_pnl(metrics)
    
    logger.info("Analysis complete!")

if __name__ == "__main__":
    asyncio.run(main())