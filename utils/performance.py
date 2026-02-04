"""
utils/performance.py

Performance tracking utilities for trading agents
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from decimal import Decimal
import redis.asyncio as redis


class PerformanceTracker:
    """
    Comprehensive performance tracking for trading agents
    
    Tracks:
    - Trade outcomes and P&L
    - Win rate and profit factor
    - Risk-adjusted returns (Sharpe ratio)
    - Execution quality metrics
    - Strategy attribution
    """
    
    def __init__(self, agent_name: str, redis_client: redis.Redis, metrics_stream: str):
        self.agent_name = agent_name
        self.redis_client = redis_client
        self.metrics_stream = metrics_stream
        self.logger = logging.getLogger(f"{__name__}.PerformanceTracker")
        
        # Performance data
        self.trades: List[Dict[str, Any]] = []
        self.daily_pnl = Decimal('0')
        self.total_pnl = Decimal('0')
        
        # Metrics cache
        self.metrics_cache: Dict[str, Any] = {}
        self.last_metrics_update = datetime.utcnow()
        
        # Configuration
        self.max_trades_history = 1000  # Keep last 1000 trades
        self.metrics_update_interval = 60  # Update metrics every 60 seconds
    
    async def track_trade(self, trade_data: Dict[str, Any]):
        """Track a completed trade"""
        try:
            # Standardize trade data
            trade = {
                'timestamp': trade_data.get('timestamp', datetime.utcnow().isoformat()),
                'pair': trade_data['pair'],
                'side': trade_data['side'],
                'entry_price': float(trade_data['entry_price']),
                'exit_price': float(trade_data.get('exit_price', trade_data['entry_price'])),
                'size': float(trade_data['size']),
                'pnl_usd': float(trade_data.get('pnl_usd', 0)),
                'pnl_bps': float(trade_data.get('pnl_bps', 0)),
                'hold_time_seconds': float(trade_data.get('hold_time_seconds', 0)),
                'fees_usd': float(trade_data.get('fees_usd', 0)),
                'slippage_bps': float(trade_data.get('slippage_bps', 0)),
                'strategy': trade_data.get('strategy', 'unknown'),
                'confidence': float(trade_data.get('confidence', 0.5)),
                'close_reason': trade_data.get('close_reason', 'unknown')
            }
            
            # Add to trades history
            self.trades.append(trade)
            
            # Maintain max history size
            if len(self.trades) > self.max_trades_history:
                self.trades = self.trades[-self.max_trades_history:]
            
            # Update P&L
            pnl_usd = Decimal(str(trade['pnl_usd']))
            self.total_pnl += pnl_usd
            
            # Update daily P&L (simplified - would need date tracking)
            self.daily_pnl += pnl_usd
            
            # Log trade
            self.logger.info(
                f"Trade tracked: {trade['pair']} {trade['side']} "
                f"P&L: {trade['pnl_bps']:.1f}bps (${trade['pnl_usd']:.2f})"
            )
            
            # Send to Redis stream
            await self._send_trade_to_stream(trade)
            
            # Update metrics if enough time has passed
            await self._maybe_update_metrics()
            
        except Exception as e:
            self.logger.error(f"Error tracking trade: {e}")
    
    async def _send_trade_to_stream(self, trade: Dict[str, Any]):
        """Send trade data to Redis stream"""
        try:
            stream_data = {
                'type': 'trade_completed',
                'agent': self.agent_name,
                'timestamp': trade['timestamp'],
                **{k: str(v) for k, v in trade.items()}
            }
            
            await self.redis_client.xadd(self.metrics_stream, stream_data)
            
        except Exception as e:
            self.logger.error(f"Error sending trade to stream: {e}")
    
    async def _maybe_update_metrics(self):
        """Update metrics if enough time has passed"""
        now = datetime.utcnow()
        if (now - self.last_metrics_update).total_seconds() >= self.metrics_update_interval:
            await self.update_metrics()
    
    async def update_metrics(self):
        """Calculate and update performance metrics"""
        try:
            if not self.trades:
                return
            
            # Basic metrics
            total_trades = len(self.trades)
            winning_trades = len([t for t in self.trades if t['pnl_usd'] > 0])
            losing_trades = len([t for t in self.trades if t['pnl_usd'] < 0])
            
            # Win rate
            win_rate = winning_trades / total_trades if total_trades > 0 else 0
            
            # P&L metrics
            total_profit = sum(t['pnl_usd'] for t in self.trades if t['pnl_usd'] > 0)
            total_loss = abs(sum(t['pnl_usd'] for t in self.trades if t['pnl_usd'] < 0))
            profit_factor = total_profit / total_loss if total_loss > 0 else float('inf')
            
            # Average trade metrics
            avg_trade_pnl = sum(t['pnl_usd'] for t in self.trades) / total_trades
            avg_winning_trade = total_profit / winning_trades if winning_trades > 0 else 0
            avg_losing_trade = -total_loss / losing_trades if losing_trades > 0 else 0
            
            # Hold time metrics
            avg_hold_time = sum(t['hold_time_seconds'] for t in self.trades) / total_trades
            
            # Execution quality
            avg_slippage = sum(t['slippage_bps'] for t in self.trades) / total_trades
            
            # Risk metrics (simplified)
            daily_returns = [t['pnl_usd'] for t in self.trades[-50:]]  # Last 50 trades
            if len(daily_returns) > 1:
                import statistics
                return_std = statistics.stdev(daily_returns)
                sharpe_ratio = (avg_trade_pnl / return_std) if return_std > 0 else 0
            else:
                sharpe_ratio = 0
            
            # Maximum drawdown (simplified)
            running_pnl = 0
            peak = 0
            max_drawdown = 0
            
            for trade in self.trades:
                running_pnl += trade['pnl_usd']
                if running_pnl > peak:
                    peak = running_pnl
                drawdown = peak - running_pnl
                if drawdown > max_drawdown:
                    max_drawdown = drawdown
            
            # Compile metrics
            self.metrics_cache = {
                'timestamp': datetime.utcnow().isoformat(),
                'agent': self.agent_name,
                'total_trades': total_trades,
                'winning_trades': winning_trades,
                'losing_trades': losing_trades,
                'win_rate': round(win_rate, 4),
                'profit_factor': round(profit_factor, 4),
                'total_pnl_usd': round(float(self.total_pnl), 2),
                'daily_pnl_usd': round(float(self.daily_pnl), 2),
                'avg_trade_pnl_usd': round(avg_trade_pnl, 2),
                'avg_winning_trade_usd': round(avg_winning_trade, 2),
                'avg_losing_trade_usd': round(avg_losing_trade, 2),
                'avg_hold_time_seconds': round(avg_hold_time, 1),
                'avg_slippage_bps': round(avg_slippage, 2),
                'sharpe_ratio': round(sharpe_ratio, 4),
                'max_drawdown_usd': round(max_drawdown, 2),
                'trades_last_hour': self._count_recent_trades(3600),
                'trades_last_day': self._count_recent_trades(86400)
            }
            
            # Send metrics to stream
            await self._send_metrics_to_stream()
            
            # Update timestamp
            self.last_metrics_update = datetime.utcnow()
            
            self.logger.debug(f"Metrics updated: WR={win_rate:.1%}, PF={profit_factor:.2f}")
            
        except Exception as e:
            self.logger.error(f"Error updating metrics: {e}")
    
    def _count_recent_trades(self, seconds_back: int) -> int:
        """Count trades in the last N seconds"""
        cutoff = datetime.utcnow() - timedelta(seconds=seconds_back)
        
        count = 0
        for trade in reversed(self.trades):  # Start from most recent
            trade_time = datetime.fromisoformat(trade['timestamp'].replace('Z', '+00:00'))
            if trade_time.replace(tzinfo=None) >= cutoff:
                count += 1
            else:
                break  # Trades are ordered, so we can stop here
        
        return count
    
    async def _send_metrics_to_stream(self):
        """Send updated metrics to Redis stream"""
        try:
            stream_data = {
                'type': 'performance_metrics',
                **{k: str(v) for k, v in self.metrics_cache.items()}
            }
            
            await self.redis_client.xadd(self.metrics_stream, stream_data)
            
        except Exception as e:
            self.logger.error(f"Error sending metrics to stream: {e}")
    
    async def get_metrics(self) -> Dict[str, Any]:
        """Get current performance metrics"""
        if not self.metrics_cache:
            await self.update_metrics()
        
        return self.metrics_cache.copy()
    
    async def get_trade_history(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get trade history"""
        if limit:
            return self.trades[-limit:]
        return self.trades.copy()
    
    async def reset_daily_metrics(self):
        """Reset daily tracking (call this at day start)"""
        self.daily_pnl = Decimal('0')
        self.logger.info("Daily metrics reset")
    
    async def get_strategy_attribution(self) -> Dict[str, Any]:
        """Get performance attribution by strategy"""
        try:
            strategy_stats = {}
            
            for trade in self.trades:
                strategy = trade.get('strategy', 'unknown')
                
                if strategy not in strategy_stats:
                    strategy_stats[strategy] = {
                        'trades': 0,
                        'wins': 0,
                        'losses': 0,
                        'total_pnl': 0,
                        'total_fees': 0
                    }
                
                stats = strategy_stats[strategy]
                stats['trades'] += 1
                stats['total_pnl'] += trade['pnl_usd']
                stats['total_fees'] += trade['fees_usd']
                
                if trade['pnl_usd'] > 0:
                    stats['wins'] += 1
                elif trade['pnl_usd'] < 0:
                    stats['losses'] += 1
            
            # Calculate derived metrics
            for strategy, stats in strategy_stats.items():
                if stats['trades'] > 0:
                    stats['win_rate'] = stats['wins'] / stats['trades']
                    stats['avg_pnl'] = stats['total_pnl'] / stats['trades']
                else:
                    stats['win_rate'] = 0
                    stats['avg_pnl'] = 0
            
            return strategy_stats
            
        except Exception as e:
            self.logger.error(f"Error calculating strategy attribution: {e}")
            return {}