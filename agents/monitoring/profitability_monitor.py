"""
Profitability Monitor & Auto-Adaptation Loop (Prompt 7)

Tracks rolling performance metrics and triggers auto-adaptation:
- If below target → trigger parameter tuning via autotune_full.py
- If above target → lock "protection mode"
- Expose metrics via Redis for signals-api and signals-site dashboard

Features:
- Rolling 7d and 30d metrics (ROI, PF, DD, Sharpe)
- Automated tuning trigger
- Protection mode activation
- Redis publishing for dashboard
- Historical tracking with trend analysis

Author: Crypto AI Bot Team
Date: 2025-11-09
"""

import os
import sys
import time
import json
import yaml
import subprocess
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass, asdict
from collections import deque
import asyncio

import numpy as np
import pandas as pd

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

try:
    import redis.asyncio as aioredis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logging.warning("redis-py not available, Redis features disabled")


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S'
)
logger = logging.getLogger(__name__)


# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class ProfitabilityMetrics:
    """Rolling profitability metrics."""

    # Time window
    window_days: int
    start_timestamp: int
    end_timestamp: int

    # Core metrics
    roi_pct: float  # Return on investment %
    profit_factor: float  # Gross profit / gross loss
    max_drawdown_pct: float  # Max peak-to-trough decline %
    sharpe_ratio: float  # Risk-adjusted returns

    # Trade statistics
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float

    # P&L
    gross_profit_usd: float
    gross_loss_usd: float
    net_pnl_usd: float

    # Additional
    avg_win_usd: float
    avg_loss_usd: float
    largest_win_usd: float
    largest_loss_usd: float

    # Equity curve
    initial_equity_usd: float
    final_equity_usd: float
    peak_equity_usd: float

    # Timestamp
    calculated_at: int


@dataclass
class PerformanceTargets:
    """Performance targets for triggering adaptations."""

    # Minimum acceptable metrics (trigger tuning if below)
    min_roi_pct_7d: float = 2.0  # ~8-10% monthly = 2% weekly
    min_roi_pct_30d: float = 8.0
    min_profit_factor: float = 1.4
    max_drawdown_pct: float = 10.0
    min_sharpe_ratio: float = 1.3

    # Protection mode triggers (lock profits if above)
    protection_roi_pct_7d: float = 5.0  # >5% weekly = great performance
    protection_roi_pct_30d: float = 15.0  # >15% monthly = exceptional
    protection_profit_factor: float = 2.0
    protection_sharpe_ratio: float = 2.0


@dataclass
class AdaptationSignal:
    """Signal to trigger adaptation action."""

    action: str  # "tune_parameters" or "enable_protection"
    reason: str
    triggered_at: int
    metrics_7d: ProfitabilityMetrics
    metrics_30d: ProfitabilityMetrics
    severity: str  # "low", "medium", "high"


# ============================================================================
# PROFITABILITY TRACKER
# ============================================================================

class ProfitabilityTracker:
    """Track and analyze rolling profitability metrics."""

    def __init__(
        self,
        initial_capital: float = 10000.0,
        max_history_days: int = 90,
    ):
        self.initial_capital = initial_capital
        self.max_history_days = max_history_days

        # Trade history (deque for efficient rolling window)
        self.trades: deque = deque(maxlen=10000)

        # Equity curve history
        self.equity_history: deque = deque(maxlen=10000)

        # Current equity
        self.current_equity = initial_capital

        # Performance targets
        self.targets = PerformanceTargets()

        logger.info(
            f"ProfitabilityTracker initialized with ${initial_capital:,.0f} capital"
        )

    def add_trade(
        self,
        timestamp: int,
        pair: str,
        pnl_usd: float,
        direction: str,
        entry_price: float,
        exit_price: float,
        position_size_usd: float,
    ):
        """Add a completed trade to history."""

        # Update equity
        self.current_equity += pnl_usd

        # Store trade
        trade = {
            'timestamp': timestamp,
            'pair': pair,
            'pnl_usd': pnl_usd,
            'direction': direction,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'position_size_usd': position_size_usd,
            'equity_after': self.current_equity,
        }
        self.trades.append(trade)

        # Store equity point
        self.equity_history.append({
            'timestamp': timestamp,
            'equity': self.current_equity,
        })

        # Trim old data (beyond max_history_days)
        cutoff_timestamp = timestamp - (self.max_history_days * 86400)

        while self.trades and self.trades[0]['timestamp'] < cutoff_timestamp:
            self.trades.popleft()

        while self.equity_history and self.equity_history[0]['timestamp'] < cutoff_timestamp:
            self.equity_history.popleft()

        logger.debug(
            f"Trade added: {pair} {direction} PnL=${pnl_usd:+.2f} "
            f"Equity=${self.current_equity:,.2f}"
        )

    def calculate_metrics(self, window_days: int) -> Optional[ProfitabilityMetrics]:
        """Calculate profitability metrics for a rolling window."""

        if not self.trades or not self.equity_history:
            logger.warning(f"No trades available for {window_days}d metrics")
            return None

        # Determine time window
        end_timestamp = int(time.time())
        start_timestamp = end_timestamp - (window_days * 86400)

        # Filter trades in window
        window_trades = [
            t for t in self.trades
            if start_timestamp <= t['timestamp'] <= end_timestamp
        ]

        if not window_trades:
            logger.warning(f"No trades in {window_days}d window")
            return None

        # Filter equity history in window
        window_equity = [
            e for e in self.equity_history
            if start_timestamp <= e['timestamp'] <= end_timestamp
        ]

        if not window_equity:
            logger.warning(f"No equity data in {window_days}d window")
            return None

        # Initial and final equity
        initial_equity = window_equity[0]['equity']
        final_equity = window_equity[-1]['equity']

        # P&L calculations
        gross_profit = sum(t['pnl_usd'] for t in window_trades if t['pnl_usd'] > 0)
        gross_loss = abs(sum(t['pnl_usd'] for t in window_trades if t['pnl_usd'] < 0))
        net_pnl = sum(t['pnl_usd'] for t in window_trades)

        # Trade statistics
        winning_trades = [t for t in window_trades if t['pnl_usd'] > 0]
        losing_trades = [t for t in window_trades if t['pnl_usd'] < 0]

        total_trades = len(window_trades)
        num_wins = len(winning_trades)
        num_losses = len(losing_trades)

        win_rate_pct = (num_wins / total_trades * 100) if total_trades > 0 else 0.0

        # Profit factor
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (
            float('inf') if gross_profit > 0 else 1.0
        )

        # Average win/loss
        avg_win = gross_profit / num_wins if num_wins > 0 else 0.0
        avg_loss = gross_loss / num_losses if num_losses > 0 else 0.0

        # Largest win/loss
        largest_win = max((t['pnl_usd'] for t in winning_trades), default=0.0)
        largest_loss = min((t['pnl_usd'] for t in losing_trades), default=0.0)

        # ROI
        roi_pct = ((final_equity - initial_equity) / initial_equity * 100)

        # Max drawdown
        peak_equity = initial_equity
        max_drawdown_pct = 0.0

        for equity_point in window_equity:
            equity = equity_point['equity']
            if equity > peak_equity:
                peak_equity = equity

            drawdown = (peak_equity - equity) / peak_equity * 100
            if drawdown > max_drawdown_pct:
                max_drawdown_pct = drawdown

        # Sharpe ratio
        if len(window_trades) >= 2:
            daily_returns = []
            prev_equity = initial_equity

            for equity_point in window_equity:
                daily_return = (equity_point['equity'] - prev_equity) / prev_equity
                daily_returns.append(daily_return)
                prev_equity = equity_point['equity']

            if daily_returns:
                mean_return = np.mean(daily_returns)
                std_return = np.std(daily_returns)

                # Annualized Sharpe (assuming ~365 equity points per year)
                sharpe_ratio = (mean_return / std_return * np.sqrt(365)) if std_return > 0 else 0.0
            else:
                sharpe_ratio = 0.0
        else:
            sharpe_ratio = 0.0

        # Create metrics object
        metrics = ProfitabilityMetrics(
            window_days=window_days,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            roi_pct=roi_pct,
            profit_factor=profit_factor,
            max_drawdown_pct=max_drawdown_pct,
            sharpe_ratio=sharpe_ratio,
            total_trades=total_trades,
            winning_trades=num_wins,
            losing_trades=num_losses,
            win_rate_pct=win_rate_pct,
            gross_profit_usd=gross_profit,
            gross_loss_usd=gross_loss,
            net_pnl_usd=net_pnl,
            avg_win_usd=avg_win,
            avg_loss_usd=avg_loss,
            largest_win_usd=largest_win,
            largest_loss_usd=largest_loss,
            initial_equity_usd=initial_equity,
            final_equity_usd=final_equity,
            peak_equity_usd=peak_equity,
            calculated_at=int(time.time()),
        )

        return metrics

    def check_adaptation_triggers(
        self,
        metrics_7d: Optional[ProfitabilityMetrics],
        metrics_30d: Optional[ProfitabilityMetrics],
    ) -> Optional[AdaptationSignal]:
        """Check if adaptation is needed based on performance."""

        if not metrics_7d and not metrics_30d:
            logger.warning("No metrics available to check adaptation triggers")
            return None

        # Use 30d metrics preferentially, fallback to 7d
        primary_metrics = metrics_30d if metrics_30d else metrics_7d
        window_label = "30d" if metrics_30d else "7d"

        # Check for protection mode triggers (above target performance)
        if metrics_7d and metrics_7d.roi_pct >= self.targets.protection_roi_pct_7d:
            return AdaptationSignal(
                action="enable_protection",
                reason=f"Exceptional 7d ROI: {metrics_7d.roi_pct:.2f}% (>= {self.targets.protection_roi_pct_7d}%)",
                triggered_at=int(time.time()),
                metrics_7d=metrics_7d,
                metrics_30d=metrics_30d or metrics_7d,
                severity="low",
            )

        if metrics_30d and metrics_30d.roi_pct >= self.targets.protection_roi_pct_30d:
            return AdaptationSignal(
                action="enable_protection",
                reason=f"Exceptional 30d ROI: {metrics_30d.roi_pct:.2f}% (>= {self.targets.protection_roi_pct_30d}%)",
                triggered_at=int(time.time()),
                metrics_7d=metrics_7d or metrics_30d,
                metrics_30d=metrics_30d,
                severity="low",
            )

        if primary_metrics.profit_factor >= self.targets.protection_profit_factor:
            return AdaptationSignal(
                action="enable_protection",
                reason=f"Exceptional {window_label} PF: {primary_metrics.profit_factor:.2f} (>= {self.targets.protection_profit_factor})",
                triggered_at=int(time.time()),
                metrics_7d=metrics_7d or primary_metrics,
                metrics_30d=metrics_30d or primary_metrics,
                severity="low",
            )

        # Check for tuning triggers (below target performance)
        failures = []

        if metrics_7d and metrics_7d.roi_pct < self.targets.min_roi_pct_7d:
            failures.append(f"7d ROI {metrics_7d.roi_pct:.2f}% < {self.targets.min_roi_pct_7d}%")

        if metrics_30d and metrics_30d.roi_pct < self.targets.min_roi_pct_30d:
            failures.append(f"30d ROI {metrics_30d.roi_pct:.2f}% < {self.targets.min_roi_pct_30d}%")

        if primary_metrics.profit_factor < self.targets.min_profit_factor:
            failures.append(f"{window_label} PF {primary_metrics.profit_factor:.2f} < {self.targets.min_profit_factor}")

        if primary_metrics.max_drawdown_pct > self.targets.max_drawdown_pct:
            failures.append(f"{window_label} MaxDD {primary_metrics.max_drawdown_pct:.2f}% > {self.targets.max_drawdown_pct}%")

        if primary_metrics.sharpe_ratio < self.targets.min_sharpe_ratio:
            failures.append(f"{window_label} Sharpe {primary_metrics.sharpe_ratio:.2f} < {self.targets.min_sharpe_ratio}")

        if failures:
            # Determine severity based on number of failures
            if len(failures) >= 3:
                severity = "high"
            elif len(failures) >= 2:
                severity = "medium"
            else:
                severity = "low"

            return AdaptationSignal(
                action="tune_parameters",
                reason=f"Performance below targets: {', '.join(failures)}",
                triggered_at=int(time.time()),
                metrics_7d=metrics_7d or primary_metrics,
                metrics_30d=metrics_30d or primary_metrics,
                severity=severity,
            )

        # No adaptation needed
        return None


# ============================================================================
# AUTO-ADAPTATION ENGINE
# ============================================================================

class AutoAdaptationEngine:
    """Execute adaptation actions based on performance signals."""

    def __init__(
        self,
        autotune_script_path: str = "scripts/autotune_full.py",
        protection_mode_config_path: str = "config/protection_mode.yaml",
        min_trades_for_tuning: int = 50,
        tuning_cooldown_hours: int = 24,
    ):
        self.autotune_script_path = Path(autotune_script_path)
        self.protection_mode_config_path = Path(protection_mode_config_path)
        self.min_trades_for_tuning = min_trades_for_tuning
        self.tuning_cooldown_hours = tuning_cooldown_hours

        # Last tuning timestamp
        self.last_tuning_timestamp: Optional[int] = None

        # Protection mode state
        self.protection_mode_enabled = False

        logger.info(
            f"AutoAdaptationEngine initialized: "
            f"autotune={self.autotune_script_path}, "
            f"protection={self.protection_mode_config_path}"
        )

    def execute_adaptation(
        self,
        signal: AdaptationSignal,
        dry_run: bool = False,
    ) -> bool:
        """Execute adaptation action."""

        logger.info(
            f"Executing adaptation: action={signal.action}, "
            f"severity={signal.severity}, reason={signal.reason}"
        )

        if signal.action == "tune_parameters":
            return self._trigger_parameter_tuning(signal, dry_run)

        elif signal.action == "enable_protection":
            return self._enable_protection_mode(signal, dry_run)

        else:
            logger.error(f"Unknown adaptation action: {signal.action}")
            return False

    def _trigger_parameter_tuning(
        self,
        signal: AdaptationSignal,
        dry_run: bool,
    ) -> bool:
        """Trigger autotune_full.py for parameter optimization."""

        # Check if enough trades
        if signal.metrics_30d.total_trades < self.min_trades_for_tuning:
            logger.warning(
                f"Insufficient trades for tuning: {signal.metrics_30d.total_trades} < {self.min_trades_for_tuning}"
            )
            return False

        # Check cooldown
        now = int(time.time())
        if self.last_tuning_timestamp:
            hours_since_last = (now - self.last_tuning_timestamp) / 3600
            if hours_since_last < self.tuning_cooldown_hours:
                logger.warning(
                    f"Tuning cooldown active: {hours_since_last:.1f}h < {self.tuning_cooldown_hours}h"
                )
                return False

        # Trigger autotune
        if dry_run:
            logger.info("[DRY RUN] Would trigger autotune_full.py")
            return True

        try:
            logger.info(f"Triggering autotune: {self.autotune_script_path}")

            # Run autotune_full.py as subprocess
            result = subprocess.run(
                [sys.executable, str(self.autotune_script_path)],
                capture_output=True,
                text=True,
                timeout=7200,  # 2 hour timeout
            )

            if result.returncode == 0:
                logger.info("Autotune completed successfully")
                self.last_tuning_timestamp = now
                return True
            else:
                logger.error(f"Autotune failed with code {result.returncode}")
                logger.error(f"Stderr: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            logger.error("Autotune timed out after 2 hours")
            return False

        except Exception as e:
            logger.error(f"Failed to trigger autotune: {e}")
            return False

    def _enable_protection_mode(
        self,
        signal: AdaptationSignal,
        dry_run: bool,
    ) -> bool:
        """Enable protection mode in config."""

        if dry_run:
            logger.info("[DRY RUN] Would enable protection mode")
            return True

        try:
            # Load protection mode config
            with open(self.protection_mode_config_path, 'r') as f:
                config = yaml.safe_load(f)

            # Enable protection mode
            config['enabled'] = True

            # Add metadata
            config['last_enabled'] = {
                'timestamp': int(time.time()),
                'reason': signal.reason,
                'metrics_7d': asdict(signal.metrics_7d),
                'metrics_30d': asdict(signal.metrics_30d),
            }

            # Write back
            with open(self.protection_mode_config_path, 'w') as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False)

            self.protection_mode_enabled = True
            logger.info(f"Protection mode enabled: {signal.reason}")
            return True

        except Exception as e:
            logger.error(f"Failed to enable protection mode: {e}")
            return False

    def disable_protection_mode(self, dry_run: bool = False) -> bool:
        """Disable protection mode."""

        if dry_run:
            logger.info("[DRY RUN] Would disable protection mode")
            return True

        try:
            with open(self.protection_mode_config_path, 'r') as f:
                config = yaml.safe_load(f)

            config['enabled'] = False

            with open(self.protection_mode_config_path, 'w') as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False)

            self.protection_mode_enabled = False
            logger.info("Protection mode disabled")
            return True

        except Exception as e:
            logger.error(f"Failed to disable protection mode: {e}")
            return False


# ============================================================================
# REDIS PUBLISHER
# ============================================================================

class RedisPublisher:
    """Publish profitability metrics to Redis for dashboard consumption."""

    def __init__(
        self,
        redis_url: Optional[str] = None,
        ssl_ca_cert: Optional[str] = None,
    ):
        self.redis_url = redis_url or os.getenv('REDIS_URL')
        self.ssl_ca_cert = ssl_ca_cert or os.getenv('REDIS_SSL_CA_CERT', 'config/certs/redis_ca.pem')

        self.redis_client: Optional[aioredis.Redis] = None

        if not REDIS_AVAILABLE:
            logger.warning("Redis not available, publishing disabled")

    async def connect(self):
        """Connect to Redis."""
        if not REDIS_AVAILABLE or not self.redis_url:
            return

        try:
            # Parse SSL settings
            ssl_config = None
            if self.redis_url.startswith('rediss://'):
                ssl_config = {
                    'ssl_ca_certs': self.ssl_ca_cert,
                    'ssl_cert_reqs': 'required',
                }

            self.redis_client = await aioredis.from_url(
                self.redis_url,
                decode_responses=True,
                ssl_ca_certs=ssl_config['ssl_ca_certs'] if ssl_config else None,
            )

            await self.redis_client.ping()
            logger.info("Connected to Redis for profitability publishing")

        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            self.redis_client = None

    async def publish_metrics(
        self,
        metrics_7d: Optional[ProfitabilityMetrics],
        metrics_30d: Optional[ProfitabilityMetrics],
        adaptation_signal: Optional[AdaptationSignal] = None,
    ):
        """Publish metrics to Redis streams."""

        if not self.redis_client:
            logger.debug("Redis client not available, skipping publish")
            return

        try:
            timestamp = int(time.time())

            # Publish 7d metrics
            if metrics_7d:
                await self.redis_client.xadd(
                    'profitability:metrics:7d',
                    asdict(metrics_7d),
                    maxlen=1000,  # Keep last 1000 entries
                )

                # Also set as latest
                await self.redis_client.set(
                    'profitability:latest:7d',
                    json.dumps(asdict(metrics_7d)),
                    ex=86400,  # 24 hour expiry
                )

            # Publish 30d metrics
            if metrics_30d:
                await self.redis_client.xadd(
                    'profitability:metrics:30d',
                    asdict(metrics_30d),
                    maxlen=1000,
                )

                await self.redis_client.set(
                    'profitability:latest:30d',
                    json.dumps(asdict(metrics_30d)),
                    ex=86400,
                )

            # Publish adaptation signal
            if adaptation_signal:
                signal_data = {
                    'action': adaptation_signal.action,
                    'reason': adaptation_signal.reason,
                    'severity': adaptation_signal.severity,
                    'triggered_at': adaptation_signal.triggered_at,
                }

                await self.redis_client.xadd(
                    'profitability:adaptation_signals',
                    signal_data,
                    maxlen=100,
                )

                # Also set as latest
                await self.redis_client.set(
                    'profitability:latest:signal',
                    json.dumps(signal_data),
                    ex=3600,  # 1 hour expiry
                )

            # Publish summary for dashboard
            summary = {
                'timestamp': timestamp,
                'roi_7d_pct': metrics_7d.roi_pct if metrics_7d else 0.0,
                'roi_30d_pct': metrics_30d.roi_pct if metrics_30d else 0.0,
                'pf_7d': metrics_7d.profit_factor if metrics_7d else 0.0,
                'pf_30d': metrics_30d.profit_factor if metrics_30d else 0.0,
                'dd_7d_pct': metrics_7d.max_drawdown_pct if metrics_7d else 0.0,
                'dd_30d_pct': metrics_30d.max_drawdown_pct if metrics_30d else 0.0,
                'sharpe_7d': metrics_7d.sharpe_ratio if metrics_7d else 0.0,
                'sharpe_30d': metrics_30d.sharpe_ratio if metrics_30d else 0.0,
                'adaptation_action': adaptation_signal.action if adaptation_signal else None,
            }

            await self.redis_client.set(
                'profitability:dashboard:summary',
                json.dumps(summary),
                ex=3600,
            )

            logger.debug("Published profitability metrics to Redis")

        except Exception as e:
            logger.error(f"Failed to publish metrics to Redis: {e}")

    async def close(self):
        """Close Redis connection."""
        if self.redis_client:
            await self.redis_client.close()


# ============================================================================
# PROFITABILITY MONITOR
# ============================================================================

class ProfitabilityMonitor:
    """
    Main profitability monitoring system.

    Integrates tracking, adaptation, and publishing.
    """

    def __init__(
        self,
        initial_capital: float = 10000.0,
        redis_url: Optional[str] = None,
        auto_adapt: bool = True,
        dry_run: bool = False,
    ):
        self.tracker = ProfitabilityTracker(initial_capital=initial_capital)
        self.engine = AutoAdaptationEngine()
        self.publisher = RedisPublisher(redis_url=redis_url)

        self.auto_adapt = auto_adapt
        self.dry_run = dry_run

        # Last metrics
        self.last_metrics_7d: Optional[ProfitabilityMetrics] = None
        self.last_metrics_30d: Optional[ProfitabilityMetrics] = None

        logger.info(
            f"ProfitabilityMonitor initialized: "
            f"auto_adapt={auto_adapt}, dry_run={dry_run}"
        )

    async def initialize(self):
        """Initialize async components."""
        await self.publisher.connect()

    async def update_and_check(self) -> Optional[AdaptationSignal]:
        """
        Update metrics and check for adaptation triggers.

        Call this periodically (e.g., after each trade or every N minutes).
        """

        # Calculate current metrics
        metrics_7d = self.tracker.calculate_metrics(window_days=7)
        metrics_30d = self.tracker.calculate_metrics(window_days=30)

        self.last_metrics_7d = metrics_7d
        self.last_metrics_30d = metrics_30d

        if metrics_7d:
            logger.info(
                f"7d Metrics: ROI={metrics_7d.roi_pct:+.2f}%, "
                f"PF={metrics_7d.profit_factor:.2f}, "
                f"DD={metrics_7d.max_drawdown_pct:.2f}%, "
                f"Sharpe={metrics_7d.sharpe_ratio:.2f}, "
                f"Trades={metrics_7d.total_trades}"
            )

        if metrics_30d:
            logger.info(
                f"30d Metrics: ROI={metrics_30d.roi_pct:+.2f}%, "
                f"PF={metrics_30d.profit_factor:.2f}, "
                f"DD={metrics_30d.max_drawdown_pct:.2f}%, "
                f"Sharpe={metrics_30d.sharpe_ratio:.2f}, "
                f"Trades={metrics_30d.total_trades}"
            )

        # Check for adaptation signals
        signal = self.tracker.check_adaptation_triggers(metrics_7d, metrics_30d)

        if signal:
            logger.info(
                f"Adaptation signal: action={signal.action}, "
                f"severity={signal.severity}, reason={signal.reason}"
            )

            # Execute adaptation if enabled
            if self.auto_adapt:
                success = self.engine.execute_adaptation(signal, dry_run=self.dry_run)
                if success:
                    logger.info("Adaptation executed successfully")
                else:
                    logger.warning("Adaptation execution failed")

        # Publish to Redis
        await self.publisher.publish_metrics(metrics_7d, metrics_30d, signal)

        return signal

    async def shutdown(self):
        """Shutdown monitor."""
        await self.publisher.close()


# ============================================================================
# SELF-CHECK
# ============================================================================

def self_check():
    """Self-check function for testing."""

    print("="*80)
    print("PROFITABILITY MONITOR - SELF CHECK")
    print("="*80)

    # Initialize tracker
    print("\n1. Initializing tracker with $10,000 capital...")
    tracker = ProfitabilityTracker(initial_capital=10000.0)
    print(f"   [OK] Initial equity: ${tracker.current_equity:,.2f}")

    # Simulate some trades
    print("\n2. Simulating 30 days of trades...")

    base_timestamp = int(time.time()) - (30 * 86400)  # 30 days ago

    # Simulate winning period (days 0-10)
    for day in range(10):
        for _ in range(3):  # 3 trades per day
            timestamp = base_timestamp + (day * 86400) + (_ * 3600)
            pnl = np.random.uniform(50, 150)  # Winning trades

            tracker.add_trade(
                timestamp=timestamp,
                pair="BTC/USD",
                pnl_usd=pnl,
                direction="long",
                entry_price=50000.0,
                exit_price=50100.0,
                position_size_usd=1000.0,
            )

    # Simulate mixed period (days 10-20)
    for day in range(10, 20):
        for _ in range(3):
            timestamp = base_timestamp + (day * 86400) + (_ * 3600)
            pnl = np.random.uniform(-100, 100)

            tracker.add_trade(
                timestamp=timestamp,
                pair="BTC/USD",
                pnl_usd=pnl,
                direction="long" if pnl > 0 else "short",
                entry_price=50000.0,
                exit_price=50100.0 if pnl > 0 else 49900.0,
                position_size_usd=1000.0,
            )

    # Simulate losing period (days 20-30)
    for day in range(20, 30):
        for _ in range(3):
            timestamp = base_timestamp + (day * 86400) + (_ * 3600)
            pnl = np.random.uniform(-150, -50)  # Losing trades

            tracker.add_trade(
                timestamp=timestamp,
                pair="BTC/USD",
                pnl_usd=pnl,
                direction="short",
                entry_price=50000.0,
                exit_price=49900.0,
                position_size_usd=1000.0,
            )

    print(f"   [OK] Simulated {len(tracker.trades)} trades")
    print(f"   [OK] Final equity: ${tracker.current_equity:,.2f}")

    # Calculate 7d metrics
    print("\n3. Calculating 7d metrics...")
    metrics_7d = tracker.calculate_metrics(window_days=7)

    if metrics_7d:
        print(f"   [OK] ROI: {metrics_7d.roi_pct:+.2f}%")
        print(f"   [OK] Profit Factor: {metrics_7d.profit_factor:.2f}")
        print(f"   [OK] Max Drawdown: {metrics_7d.max_drawdown_pct:.2f}%")
        print(f"   [OK] Sharpe Ratio: {metrics_7d.sharpe_ratio:.2f}")
        print(f"   [OK] Win Rate: {metrics_7d.win_rate_pct:.1f}%")
        print(f"   [OK] Total Trades: {metrics_7d.total_trades}")
    else:
        print("   [FAIL] Failed to calculate 7d metrics")
        return False

    # Calculate 30d metrics
    print("\n4. Calculating 30d metrics...")
    metrics_30d = tracker.calculate_metrics(window_days=30)

    if metrics_30d:
        print(f"   [OK] ROI: {metrics_30d.roi_pct:+.2f}%")
        print(f"   [OK] Profit Factor: {metrics_30d.profit_factor:.2f}")
        print(f"   [OK] Max Drawdown: {metrics_30d.max_drawdown_pct:.2f}%")
        print(f"   [OK] Sharpe Ratio: {metrics_30d.sharpe_ratio:.2f}")
        print(f"   [OK] Win Rate: {metrics_30d.win_rate_pct:.1f}%")
        print(f"   [OK] Total Trades: {metrics_30d.total_trades}")
    else:
        print("   [FAIL] Failed to calculate 30d metrics")
        return False

    # Check adaptation triggers
    print("\n5. Checking adaptation triggers...")
    signal = tracker.check_adaptation_triggers(metrics_7d, metrics_30d)

    if signal:
        print(f"   [OK] Signal detected: {signal.action}")
        print(f"   [OK] Reason: {signal.reason}")
        print(f"   [OK] Severity: {signal.severity}")
    else:
        print("   [OK] No adaptation signal (performance within targets)")

    # Test adaptation engine
    print("\n6. Testing adaptation engine (dry run)...")
    engine = AutoAdaptationEngine()

    if signal:
        success = engine.execute_adaptation(signal, dry_run=True)
        if success:
            print("   [OK] Adaptation execution test passed")
        else:
            print("   [FAIL] Adaptation execution test failed")
            return False
    else:
        print("   [OK] No signal to test (skipped)")

    print("\n" + "="*80)
    print("[PASS] SELF-CHECK PASSED!")
    print("="*80)
    print("\nProfitability Monitor is ready for production use.")
    print("\nNext steps:")
    print("1. Integrate with your trading system to add trades")
    print("2. Call update_and_check() periodically (e.g., every 5 minutes)")
    print("3. Monitor Redis streams for dashboard consumption")
    print("4. Review auto-adaptation actions in logs")

    return True


# ============================================================================
# MAIN
# ============================================================================

async def main():
    """Example usage of profitability monitor."""

    # Initialize monitor
    monitor = ProfitabilityMonitor(
        initial_capital=10000.0,
        redis_url=os.getenv('REDIS_URL'),
        auto_adapt=True,
        dry_run=False,  # Set to True to test without actual adaptations
    )

    await monitor.initialize()

    try:
        # Example: Monitor loop
        while True:
            # Update metrics and check for adaptations
            signal = await monitor.update_and_check()

            if signal:
                logger.info(f"Adaptation triggered: {signal.action}")

            # Sleep for 5 minutes
            await asyncio.sleep(300)

    except KeyboardInterrupt:
        logger.info("Shutting down profitability monitor...")

    finally:
        await monitor.shutdown()


if __name__ == '__main__':
    # Run self-check if no args, otherwise run main loop
    if len(sys.argv) == 1:
        success = self_check()
        sys.exit(0 if success else 1)
    else:
        asyncio.run(main())
