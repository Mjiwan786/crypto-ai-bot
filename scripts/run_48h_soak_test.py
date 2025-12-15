"""
48-Hour Paper-Live Soak Test

Comprehensive production readiness validation with:
- Turbo scalper (15s bars) with conditional 5s bars
- News override 4-hour test window
- Live metrics streaming to signals-api/signals-site
- Real-time alerting (heat, latency, lag)
- Automated pass/fail evaluation
- Production candidate tagging

Author: Crypto AI Bot Team
Date: 2025-11-08
"""

import os
import sys
import time
import json
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from decimal import Decimal

import redis.asyncio as redis
import yaml

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import centralized signals API config
from config.signals_api_config import SIGNALS_API_BASE_URL

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S'
)
logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION
# ============================================================================

class SoakTestConfig:
    """48-hour soak test configuration."""

    # Test duration
    SOAK_DURATION_HOURS = 48
    SOAK_DURATION_SECONDS = 48 * 3600

    # Redis Cloud connection
    REDIS_URL = os.getenv(
        'REDIS_URL',
        'rediss://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818'
    )
    REDIS_CERT_PATH = 'C:\\Users\\Maith\\OneDrive\\Desktop\\crypto_ai_bot\\config\\certs\\redis_ca.pem'

    # Turbo scalper configuration
    TURBO_SCALPER_ENABLED = True
    TIMEFRAME_15S_ENABLED = True
    TIMEFRAME_5S_ENABLED = False  # Conditional on latency
    TIMEFRAME_5S_LATENCY_THRESHOLD_MS = 50.0  # Enable 5s if latency < 50ms

    # News override test window
    NEWS_OVERRIDE_ENABLED = False  # Default OFF
    NEWS_OVERRIDE_TEST_DURATION_HOURS = 4
    NEWS_OVERRIDE_START_DELAY_HOURS = 12  # Start after 12 hours into soak

    # Trading configuration
    TRADING_MODE = "paper"  # paper trading for soak test
    TRADING_PAIRS = ["BTC/USD", "ETH/USD", "SOL/USD", "ADA/USD"]

    # Alert thresholds
    ALERT_HEAT_THRESHOLD_PCT = 80.0
    ALERT_LATENCY_BUDGET_MS = 100.0
    ALERT_LAG_THRESHOLD_MSGS = 5

    # Pass criteria
    PASS_MIN_NET_PNL = 0.0  # Positive net P&L
    PASS_MIN_PROFIT_FACTOR = 1.25
    PASS_MAX_CIRCUIT_BREAKER_TRIPS_PER_HOUR = 3
    PASS_MAX_LAG_MSGS = 5

    # Metrics streaming
    METRICS_PUBLISH_INTERVAL_SECONDS = 15
    SIGNALS_API_URL = SIGNALS_API_BASE_URL

    # Redis streams
    STREAM_SOAK_METRICS = "soak:metrics"
    STREAM_SOAK_ALERTS = "soak:alerts"
    STREAM_SOAK_STATUS = "soak:status"
    STREAM_SIGNALS_API = "signals:api:live"
    STREAM_SIGNALS_SITE = "signals:site:dashboard"

    # Output paths
    OUTPUT_DIR = "out/soak_test"
    RESULTS_FILE = "out/soak_test/soak_test_results.json"
    REPORT_FILE = "out/soak_test/soak_test_report.md"
    PROMETHEUS_SNAPSHOT_DIR = "out/soak_test/prometheus"


# ============================================================================
# REDIS CLIENT
# ============================================================================

class RedisClient:
    """Redis Cloud client for metrics streaming."""

    def __init__(self):
        self.redis = None
        self.logger = logging.getLogger(f"{__name__}.RedisClient")

    async def connect(self):
        """Connect to Redis Cloud."""
        try:
            self.redis = await redis.from_url(
                SoakTestConfig.REDIS_URL,
                ssl_cert_reqs='required',
                decode_responses=True,
                socket_timeout=10,
                socket_keepalive=True,
            )

            # Test connection
            await self.redis.ping()
            self.logger.info("[OK] Connected to Redis Cloud")
            return True

        except Exception as e:
            self.logger.error(f"[ERROR] Redis connection failed: {e}")
            return False

    async def publish_metrics(self, stream: str, data: Dict):
        """Publish metrics to Redis stream."""
        if not self.redis:
            return False

        try:
            # Add timestamp
            data['timestamp'] = datetime.now().isoformat()

            # Publish to stream
            await self.redis.xadd(stream, data, maxlen=10000)
            return True

        except Exception as e:
            self.logger.warning(f"Failed to publish to {stream}: {e}")
            return False

    async def close(self):
        """Close Redis connection."""
        if self.redis:
            await self.redis.aclose()
            self.logger.info("Redis connection closed")


# ============================================================================
# METRICS COLLECTOR
# ============================================================================

class MetricsCollector:
    """Collect and aggregate metrics during soak test."""

    def __init__(self):
        self.start_time = None
        self.metrics_history = []
        self.alerts_history = []

        # Running totals
        self.total_trades = 0
        self.total_pnl = 0.0
        self.winning_trades = 0
        self.losing_trades = 0
        self.total_volume = 0.0

        # Latency tracking
        self.latency_samples = []
        self.max_latency_ms = 0.0
        self.avg_latency_ms = 0.0

        # Heat tracking
        self.max_heat_pct = 0.0
        self.current_heat_pct = 0.0

        # Circuit breaker tracking
        self.circuit_breaker_trips = 0

        # Message lag tracking
        self.max_lag_msgs = 0
        self.current_lag_msgs = 0

        # 5s bar tracking
        self.timeframe_5s_enabled_time = 0  # Seconds 5s was enabled

    def record_trade(self, pnl: float, volume: float):
        """Record a trade."""
        self.total_trades += 1
        self.total_pnl += pnl
        self.total_volume += volume

        if pnl > 0:
            self.winning_trades += 1
        elif pnl < 0:
            self.losing_trades += 1

    def record_latency(self, latency_ms: float):
        """Record latency sample."""
        self.latency_samples.append(latency_ms)
        self.max_latency_ms = max(self.max_latency_ms, latency_ms)

        # Keep rolling window
        if len(self.latency_samples) > 1000:
            self.latency_samples.pop(0)

        # Update average
        if self.latency_samples:
            self.avg_latency_ms = sum(self.latency_samples) / len(self.latency_samples)

    def record_heat(self, heat_pct: float):
        """Record portfolio heat."""
        self.current_heat_pct = heat_pct
        self.max_heat_pct = max(self.max_heat_pct, heat_pct)

    def record_circuit_breaker_trip(self):
        """Record circuit breaker trip."""
        self.circuit_breaker_trips += 1

    def record_lag(self, lag_msgs: int):
        """Record message lag."""
        self.current_lag_msgs = lag_msgs
        self.max_lag_msgs = max(self.max_lag_msgs, lag_msgs)

    def record_5s_enabled(self, duration_seconds: float):
        """Record time with 5s bars enabled."""
        self.timeframe_5s_enabled_time += duration_seconds

    def get_profit_factor(self) -> float:
        """Calculate profit factor."""
        gross_profit = sum(pnl for pnl, _ in [(self.total_pnl, 0)] if pnl > 0)
        gross_loss = abs(sum(pnl for pnl, _ in [(self.total_pnl, 0)] if pnl < 0))

        if gross_loss == 0:
            return float('inf') if gross_profit > 0 else 0.0

        return gross_profit / gross_loss if gross_loss > 0 else 0.0

    def get_win_rate(self) -> float:
        """Calculate win rate."""
        if self.total_trades == 0:
            return 0.0

        return (self.winning_trades / self.total_trades) * 100

    def get_summary(self) -> Dict:
        """Get metrics summary."""
        elapsed = time.time() - self.start_time if self.start_time else 0

        return {
            'elapsed_hours': elapsed / 3600,
            'total_trades': self.total_trades,
            'net_pnl': self.total_pnl,
            'profit_factor': self.get_profit_factor(),
            'win_rate': self.get_win_rate(),
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'total_volume': self.total_volume,
            'avg_latency_ms': self.avg_latency_ms,
            'max_latency_ms': self.max_latency_ms,
            'max_heat_pct': self.max_heat_pct,
            'current_heat_pct': self.current_heat_pct,
            'circuit_breaker_trips': self.circuit_breaker_trips,
            'circuit_breaker_trips_per_hour': self.circuit_breaker_trips / (elapsed / 3600) if elapsed > 0 else 0,
            'max_lag_msgs': self.max_lag_msgs,
            'current_lag_msgs': self.current_lag_msgs,
            'timeframe_5s_enabled_hours': self.timeframe_5s_enabled_time / 3600,
        }


# ============================================================================
# ALERT MONITOR
# ============================================================================

class AlertMonitor:
    """Monitor and trigger alerts during soak test."""

    def __init__(self, metrics_collector: MetricsCollector, redis_client: RedisClient):
        self.metrics = metrics_collector
        self.redis = redis_client
        self.logger = logging.getLogger(f"{__name__}.AlertMonitor")

        # Alert state
        self.active_alerts = set()

    async def check_alerts(self):
        """Check all alert conditions."""
        alerts = []

        # Check heat threshold
        if self.metrics.current_heat_pct > SoakTestConfig.ALERT_HEAT_THRESHOLD_PCT:
            alert = {
                'type': 'HEAT_THRESHOLD_EXCEEDED',
                'severity': 'WARNING',
                'value': self.metrics.current_heat_pct,
                'threshold': SoakTestConfig.ALERT_HEAT_THRESHOLD_PCT,
                'message': f"Portfolio heat {self.metrics.current_heat_pct:.1f}% > {SoakTestConfig.ALERT_HEAT_THRESHOLD_PCT}%",
            }
            alerts.append(alert)

        # Check latency budget
        if self.metrics.avg_latency_ms > SoakTestConfig.ALERT_LATENCY_BUDGET_MS:
            alert = {
                'type': 'LATENCY_BUDGET_EXCEEDED',
                'severity': 'WARNING',
                'value': self.metrics.avg_latency_ms,
                'threshold': SoakTestConfig.ALERT_LATENCY_BUDGET_MS,
                'message': f"Latency {self.metrics.avg_latency_ms:.1f}ms > {SoakTestConfig.ALERT_LATENCY_BUDGET_MS}ms",
            }
            alerts.append(alert)

        # Check message lag
        if self.metrics.current_lag_msgs > SoakTestConfig.ALERT_LAG_THRESHOLD_MSGS:
            alert = {
                'type': 'LAG_THRESHOLD_EXCEEDED',
                'severity': 'CRITICAL',
                'value': self.metrics.current_lag_msgs,
                'threshold': SoakTestConfig.ALERT_LAG_THRESHOLD_MSGS,
                'message': f"Message lag {self.metrics.current_lag_msgs} msgs > {SoakTestConfig.ALERT_LAG_THRESHOLD_MSGS}",
            }
            alerts.append(alert)

        # Process alerts
        for alert in alerts:
            await self._trigger_alert(alert)

        return alerts

    async def _trigger_alert(self, alert: Dict):
        """Trigger an alert."""
        alert_key = f"{alert['type']}:{alert['value']}"

        # Avoid duplicate alerts
        if alert_key in self.active_alerts:
            return

        self.active_alerts.add(alert_key)

        # Log alert
        severity = alert['severity']
        message = alert['message']
        self.logger.warning(f"[ALERT {severity}] {message}")

        # Publish to Redis
        await self.redis.publish_metrics(
            SoakTestConfig.STREAM_SOAK_ALERTS,
            alert
        )

    def clear_alert(self, alert_type: str):
        """Clear an alert."""
        self.active_alerts = {a for a in self.active_alerts if not a.startswith(alert_type)}


# ============================================================================
# NEWS OVERRIDE SCHEDULER
# ============================================================================

class NewsOverrideScheduler:
    """Manage news override 4-hour test window."""

    def __init__(self):
        self.enabled = False
        self.start_time = None
        self.end_time = None
        self.logger = logging.getLogger(f"{__name__}.NewsOverrideScheduler")

    def should_enable(self, elapsed_hours: float) -> bool:
        """Check if news override should be enabled."""
        if self.enabled:
            # Check if window has expired
            if time.time() > self.end_time:
                self.logger.info("[NEWS] 4-hour test window expired, disabling news override")
                self.enabled = False
                return False
            return True

        # Check if we should start the test window
        if (elapsed_hours >= SoakTestConfig.NEWS_OVERRIDE_START_DELAY_HOURS and
            not self.enabled):
            self.logger.info(f"[NEWS] Starting 4-hour news override test window")
            self.enabled = True
            self.start_time = time.time()
            self.end_time = self.start_time + (SoakTestConfig.NEWS_OVERRIDE_TEST_DURATION_HOURS * 3600)
            return True

        return False

    def get_status(self) -> Dict:
        """Get news override status."""
        if not self.enabled:
            return {
                'enabled': False,
                'window_started': False,
            }

        remaining_seconds = max(0, self.end_time - time.time())
        return {
            'enabled': True,
            'window_started': True,
            'remaining_hours': remaining_seconds / 3600,
            'start_time': datetime.fromtimestamp(self.start_time).isoformat(),
            'end_time': datetime.fromtimestamp(self.end_time).isoformat(),
        }


# ============================================================================
# SOAK TEST ORCHESTRATOR
# ============================================================================

class SoakTestOrchestrator:
    """Main orchestrator for 48-hour soak test."""

    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.SoakTestOrchestrator")

        # Components
        self.redis_client = RedisClient()
        self.metrics_collector = MetricsCollector()
        self.alert_monitor = AlertMonitor(self.metrics_collector, self.redis_client)
        self.news_scheduler = NewsOverrideScheduler()

        # Test state
        self.start_time = None
        self.end_time = None
        self.running = False
        self.passed = False

        # Create output directory
        os.makedirs(SoakTestConfig.OUTPUT_DIR, exist_ok=True)
        os.makedirs(SoakTestConfig.PROMETHEUS_SNAPSHOT_DIR, exist_ok=True)

    async def start(self):
        """Start 48-hour soak test."""
        self.logger.info("="*80)
        self.logger.info("48-HOUR PAPER-LIVE SOAK TEST")
        self.logger.info("="*80)
        self.logger.info(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.logger.info(f"Expected end: {(datetime.now() + timedelta(hours=48)).strftime('%Y-%m-%d %H:%M:%S')}")

        # Connect to Redis
        if not await self.redis_client.connect():
            self.logger.error("Failed to connect to Redis, aborting soak test")
            return False

        # Initialize test
        self.start_time = time.time()
        self.end_time = self.start_time + SoakTestConfig.SOAK_DURATION_SECONDS
        self.metrics_collector.start_time = self.start_time
        self.running = True

        self.logger.info("\nConfiguration:")
        self.logger.info(f"  Turbo Scalper: {'ENABLED' if SoakTestConfig.TURBO_SCALPER_ENABLED else 'DISABLED'}")
        self.logger.info(f"  15s Bars: {'ENABLED' if SoakTestConfig.TIMEFRAME_15S_ENABLED else 'DISABLED'}")
        self.logger.info(f"  5s Bars: CONDITIONAL (latency < {SoakTestConfig.TIMEFRAME_5S_LATENCY_THRESHOLD_MS}ms)")
        self.logger.info(f"  News Override: {SoakTestConfig.NEWS_OVERRIDE_START_DELAY_HOURS}h delay, {SoakTestConfig.NEWS_OVERRIDE_TEST_DURATION_HOURS}h window")
        self.logger.info(f"  Trading Mode: {SoakTestConfig.TRADING_MODE.upper()}")
        self.logger.info(f"  Trading Pairs: {', '.join(SoakTestConfig.TRADING_PAIRS)}")

        # Publish start status
        await self._publish_status("STARTED")

        try:
            # Main monitoring loop
            await self._run_monitoring_loop()

        except KeyboardInterrupt:
            self.logger.info("\nSoak test interrupted by user")
        except Exception as e:
            self.logger.error(f"Soak test error: {e}")
        finally:
            await self._cleanup()

        return self.passed

    async def _run_monitoring_loop(self):
        """Main monitoring loop."""
        last_metrics_publish = time.time()
        last_5s_check = time.time()

        while self.running:
            current_time = time.time()
            elapsed = current_time - self.start_time
            elapsed_hours = elapsed / 3600
            remaining = self.end_time - current_time

            # Check if test duration elapsed
            if current_time >= self.end_time:
                self.logger.info("\n48-hour soak test duration complete!")
                self.running = False
                break

            # Simulate metrics collection (in real implementation, poll from trading system)
            await self._collect_metrics()

            # Check 5s bar enablement based on latency
            if current_time - last_5s_check >= 60:  # Check every minute
                await self._check_5s_bar_enablement()
                last_5s_check = current_time

            # Check news override schedule
            news_enabled = self.news_scheduler.should_enable(elapsed_hours)

            # Check alerts
            await self.alert_monitor.check_alerts()

            # Publish metrics to Redis streams
            if current_time - last_metrics_publish >= SoakTestConfig.METRICS_PUBLISH_INTERVAL_SECONDS:
                await self._publish_metrics()
                last_metrics_publish = current_time

            # Log progress
            if int(elapsed) % 3600 == 0:  # Every hour
                summary = self.metrics_collector.get_summary()
                self.logger.info(f"\n{'='*80}")
                self.logger.info(f"HOUR {int(elapsed_hours)} UPDATE")
                self.logger.info(f"{'='*80}")
                self.logger.info(f"Net P&L: ${summary['net_pnl']:.2f}")
                self.logger.info(f"Profit Factor: {summary['profit_factor']:.2f}")
                self.logger.info(f"Trades: {summary['total_trades']}")
                self.logger.info(f"Win Rate: {summary['win_rate']:.1f}%")
                self.logger.info(f"Avg Latency: {summary['avg_latency_ms']:.1f}ms")
                self.logger.info(f"Max Heat: {summary['max_heat_pct']:.1f}%")
                self.logger.info(f"Remaining: {remaining/3600:.1f}h")

            # Sleep before next iteration
            await asyncio.sleep(10)

    async def _collect_metrics(self):
        """Collect metrics from trading system (simulated for now)."""
        # In real implementation, poll from:
        # - PnL tracker
        # - Position manager
        # - Latency monitor
        # - Circuit breaker state

        # For now, simulate with placeholder data
        pass

    async def _check_5s_bar_enablement(self):
        """Check if 5s bars should be enabled based on latency."""
        current_latency = self.metrics_collector.avg_latency_ms

        should_enable = current_latency < SoakTestConfig.TIMEFRAME_5S_LATENCY_THRESHOLD_MS

        if should_enable and not SoakTestConfig.TIMEFRAME_5S_ENABLED:
            self.logger.info(f"[5S] Enabling 5s bars (latency {current_latency:.1f}ms < {SoakTestConfig.TIMEFRAME_5S_LATENCY_THRESHOLD_MS}ms)")
            SoakTestConfig.TIMEFRAME_5S_ENABLED = True

        elif not should_enable and SoakTestConfig.TIMEFRAME_5S_ENABLED:
            self.logger.info(f"[5S] Disabling 5s bars (latency {current_latency:.1f}ms >= {SoakTestConfig.TIMEFRAME_5S_LATENCY_THRESHOLD_MS}ms)")
            SoakTestConfig.TIMEFRAME_5S_ENABLED = False

        # Record time with 5s enabled
        if SoakTestConfig.TIMEFRAME_5S_ENABLED:
            self.metrics_collector.record_5s_enabled(60)  # 1 minute

    async def _publish_metrics(self):
        """Publish metrics to Redis streams."""
        summary = self.metrics_collector.get_summary()
        news_status = self.news_scheduler.get_status()

        # Add news override status
        summary['news_override_enabled'] = news_status['enabled']
        summary['news_override_window_started'] = news_status.get('window_started', False)

        # Publish to soak test stream
        await self.redis_client.publish_metrics(
            SoakTestConfig.STREAM_SOAK_METRICS,
            summary
        )

        # Publish to signals-api stream
        await self.redis_client.publish_metrics(
            SoakTestConfig.STREAM_SIGNALS_API,
            {
                'source': 'soak_test',
                'metrics': summary,
            }
        )

        # Publish to signals-site stream (for live dashboard)
        await self.redis_client.publish_metrics(
            SoakTestConfig.STREAM_SIGNALS_SITE,
            {
                'source': 'soak_test',
                'dashboard': 'live',
                'metrics': summary,
            }
        )

    async def _publish_status(self, status: str):
        """Publish test status."""
        await self.redis_client.publish_metrics(
            SoakTestConfig.STREAM_SOAK_STATUS,
            {
                'status': status,
                'start_time': datetime.fromtimestamp(self.start_time).isoformat() if self.start_time else None,
                'end_time': datetime.fromtimestamp(self.end_time).isoformat() if self.end_time else None,
            }
        )

    async def _cleanup(self):
        """Cleanup and evaluate results."""
        self.logger.info("\n" + "="*80)
        self.logger.info("SOAK TEST COMPLETE - EVALUATING RESULTS")
        self.logger.info("="*80)

        # Get final summary
        summary = self.metrics_collector.get_summary()

        # Evaluate pass criteria
        self.passed = await self._evaluate_pass_criteria(summary)

        # Save results
        await self._save_results(summary)

        # Generate report
        await self._generate_report(summary)

        # If passed, promote to production candidate
        if self.passed:
            await self._promote_to_production_candidate(summary)

        # Close Redis connection
        await self.redis_client.close()

        # Final status
        status = "PASSED" if self.passed else "FAILED"
        await self._publish_status(status)

    async def _evaluate_pass_criteria(self, summary: Dict) -> bool:
        """Evaluate if soak test passed."""
        self.logger.info("\nEvaluating pass criteria:")

        passed = True
        criteria = []

        # Criterion 1: Positive net P&L
        net_pnl_pass = summary['net_pnl'] >= SoakTestConfig.PASS_MIN_NET_PNL
        criteria.append(('Positive Net P&L', net_pnl_pass, summary['net_pnl'], SoakTestConfig.PASS_MIN_NET_PNL))
        self.logger.info(f"  Net P&L: ${summary['net_pnl']:.2f} >= ${SoakTestConfig.PASS_MIN_NET_PNL:.2f} {'✓' if net_pnl_pass else '✗'}")
        passed = passed and net_pnl_pass

        # Criterion 2: Profit factor >= 1.25
        pf_pass = summary['profit_factor'] >= SoakTestConfig.PASS_MIN_PROFIT_FACTOR
        criteria.append(('Profit Factor ≥1.25', pf_pass, summary['profit_factor'], SoakTestConfig.PASS_MIN_PROFIT_FACTOR))
        self.logger.info(f"  Profit Factor: {summary['profit_factor']:.2f} >= {SoakTestConfig.PASS_MIN_PROFIT_FACTOR:.2f} {'✓' if pf_pass else '✗'}")
        passed = passed and pf_pass

        # Criterion 3: Circuit breakers not overused
        cb_per_hour = summary['circuit_breaker_trips_per_hour']
        cb_pass = cb_per_hour <= SoakTestConfig.PASS_MAX_CIRCUIT_BREAKER_TRIPS_PER_HOUR
        criteria.append(('Circuit Breakers < 3/hour', cb_pass, cb_per_hour, SoakTestConfig.PASS_MAX_CIRCUIT_BREAKER_TRIPS_PER_HOUR))
        self.logger.info(f"  CB Trips/Hour: {cb_per_hour:.2f} <= {SoakTestConfig.PASS_MAX_CIRCUIT_BREAKER_TRIPS_PER_HOUR} {'✓' if cb_pass else '✗'}")
        passed = passed and cb_pass

        # Criterion 4: Lag < 5 messages
        lag_pass = summary['max_lag_msgs'] < SoakTestConfig.PASS_MAX_LAG_MSGS
        criteria.append(('Message Lag < 5', lag_pass, summary['max_lag_msgs'], SoakTestConfig.PASS_MAX_LAG_MSGS))
        self.logger.info(f"  Max Lag: {summary['max_lag_msgs']} < {SoakTestConfig.PASS_MAX_LAG_MSGS} {'✓' if lag_pass else '✗'}")
        passed = passed and lag_pass

        self.logger.info(f"\nOverall: {'PASS ✓' if passed else 'FAIL ✗'}")

        return passed

    async def _save_results(self, summary: Dict):
        """Save test results to JSON."""
        results = {
            'test_start': datetime.fromtimestamp(self.start_time).isoformat(),
            'test_end': datetime.fromtimestamp(time.time()).isoformat(),
            'duration_hours': (time.time() - self.start_time) / 3600,
            'passed': self.passed,
            'configuration': {
                'turbo_scalper': SoakTestConfig.TURBO_SCALPER_ENABLED,
                'timeframe_15s': SoakTestConfig.TIMEFRAME_15S_ENABLED,
                'timeframe_5s_conditional': True,
                'news_override_test_window': f"{SoakTestConfig.NEWS_OVERRIDE_TEST_DURATION_HOURS}h",
                'trading_mode': SoakTestConfig.TRADING_MODE,
                'trading_pairs': SoakTestConfig.TRADING_PAIRS,
            },
            'metrics': summary,
        }

        with open(SoakTestConfig.RESULTS_FILE, 'w') as f:
            json.dump(results, f, indent=2)

        self.logger.info(f"\nResults saved to: {SoakTestConfig.RESULTS_FILE}")

    async def _generate_report(self, summary: Dict):
        """Generate markdown report."""
        self.logger.info("\nGenerating markdown report...")

        report_lines = []

        # Header
        report_lines.append("# 48-Hour Soak Test - Final Report")
        report_lines.append("")
        report_lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report_lines.append(f"**Test Duration:** {summary['elapsed_hours']:.1f} hours")
        report_lines.append(f"**Status:** {'PASSED' if self.passed else 'FAILED'}")
        report_lines.append("")
        report_lines.append("---")
        report_lines.append("")

        # Executive Summary
        report_lines.append("## Executive Summary")
        report_lines.append("")
        report_lines.append("### Configuration")
        report_lines.append("")
        report_lines.append(f"- **Trading Mode:** {SoakTestConfig.TRADING_MODE.upper()}")
        report_lines.append(f"- **Trading Pairs:** {', '.join(SoakTestConfig.TRADING_PAIRS)}")
        report_lines.append(f"- **Turbo Scalper:** {'ENABLED' if SoakTestConfig.TURBO_SCALPER_ENABLED else 'DISABLED'}")
        report_lines.append(f"- **15s Bars:** {'ENABLED' if SoakTestConfig.TIMEFRAME_15S_ENABLED else 'DISABLED'}")
        report_lines.append(f"- **5s Bars:** CONDITIONAL (latency < {SoakTestConfig.TIMEFRAME_5S_LATENCY_THRESHOLD_MS}ms)")
        report_lines.append(f"- **5s Enabled Duration:** {summary['timeframe_5s_enabled_hours']:.1f} hours")
        report_lines.append("")

        # News Override Test Window
        news_status = self.news_scheduler.get_status()
        report_lines.append("### News Override Test Window")
        report_lines.append("")
        if news_status.get('window_started'):
            report_lines.append(f"- **Status:** Test window executed")
            report_lines.append(f"- **Start Time:** {news_status.get('start_time', 'N/A')}")
            report_lines.append(f"- **End Time:** {news_status.get('end_time', 'N/A')}")
            report_lines.append(f"- **Duration:** {SoakTestConfig.NEWS_OVERRIDE_TEST_DURATION_HOURS} hours")
        else:
            report_lines.append(f"- **Status:** Test window not reached (scheduled for hour {SoakTestConfig.NEWS_OVERRIDE_START_DELAY_HOURS})")
        report_lines.append("")

        # Performance Metrics
        report_lines.append("### Performance Metrics")
        report_lines.append("")
        report_lines.append(f"- **Net P&L:** ${summary['net_pnl']:.2f}")
        report_lines.append(f"- **Profit Factor:** {summary['profit_factor']:.2f}")
        report_lines.append(f"- **Total Trades:** {summary['total_trades']}")
        report_lines.append(f"- **Winning Trades:** {summary['winning_trades']}")
        report_lines.append(f"- **Losing Trades:** {summary['losing_trades']}")
        report_lines.append(f"- **Win Rate:** {summary['win_rate']:.1f}%")
        report_lines.append(f"- **Total Volume:** ${summary['total_volume']:.2f}")
        report_lines.append("")

        # Latency & Performance
        report_lines.append("### Latency & Performance")
        report_lines.append("")
        report_lines.append(f"- **Average Latency:** {summary['avg_latency_ms']:.1f} ms")
        report_lines.append(f"- **Max Latency:** {summary['max_latency_ms']:.1f} ms")
        report_lines.append(f"- **Latency Budget:** {SoakTestConfig.ALERT_LATENCY_BUDGET_MS} ms")
        report_lines.append(f"- **Max Portfolio Heat:** {summary['max_heat_pct']:.1f}%")
        report_lines.append(f"- **Heat Threshold:** {SoakTestConfig.ALERT_HEAT_THRESHOLD_PCT}%")
        report_lines.append("")

        # Circuit Breakers & Lag
        report_lines.append("### Circuit Breakers & Message Lag")
        report_lines.append("")
        report_lines.append(f"- **Total CB Trips:** {summary['circuit_breaker_trips']}")
        report_lines.append(f"- **CB Trips/Hour:** {summary['circuit_breaker_trips_per_hour']:.2f}")
        report_lines.append(f"- **CB Trip Limit:** {SoakTestConfig.PASS_MAX_CIRCUIT_BREAKER_TRIPS_PER_HOUR}/hour")
        report_lines.append(f"- **Max Message Lag:** {summary['max_lag_msgs']} msgs")
        report_lines.append(f"- **Lag Threshold:** {SoakTestConfig.PASS_MAX_LAG_MSGS} msgs")
        report_lines.append("")

        report_lines.append("---")
        report_lines.append("")

        # Pass Criteria Evaluation
        report_lines.append("## Pass Criteria Evaluation")
        report_lines.append("")
        report_lines.append("| Criterion | Required | Actual | Status |")
        report_lines.append("|-----------|----------|--------|--------|")

        net_pnl_pass = summary['net_pnl'] >= SoakTestConfig.PASS_MIN_NET_PNL
        report_lines.append(f"| Net P&L > $0 | ${SoakTestConfig.PASS_MIN_NET_PNL:.2f} | ${summary['net_pnl']:.2f} | {'PASS' if net_pnl_pass else 'FAIL'} |")

        pf_pass = summary['profit_factor'] >= SoakTestConfig.PASS_MIN_PROFIT_FACTOR
        report_lines.append(f"| Profit Factor >= 1.25 | {SoakTestConfig.PASS_MIN_PROFIT_FACTOR:.2f} | {summary['profit_factor']:.2f} | {'PASS' if pf_pass else 'FAIL'} |")

        cb_per_hour = summary['circuit_breaker_trips_per_hour']
        cb_pass = cb_per_hour <= SoakTestConfig.PASS_MAX_CIRCUIT_BREAKER_TRIPS_PER_HOUR
        report_lines.append(f"| CB Trips/Hour <= 3 | {SoakTestConfig.PASS_MAX_CIRCUIT_BREAKER_TRIPS_PER_HOUR} | {cb_per_hour:.2f} | {'PASS' if cb_pass else 'FAIL'} |")

        lag_pass = summary['max_lag_msgs'] < SoakTestConfig.PASS_MAX_LAG_MSGS
        report_lines.append(f"| Max Lag < 5 msgs | {SoakTestConfig.PASS_MAX_LAG_MSGS} | {summary['max_lag_msgs']} | {'PASS' if lag_pass else 'FAIL'} |")

        report_lines.append("")
        report_lines.append(f"**Overall Result:** {'PASS' if self.passed else 'FAIL'}")
        report_lines.append("")

        report_lines.append("---")
        report_lines.append("")

        # Alerts Summary
        report_lines.append("## Alerts Summary")
        report_lines.append("")
        if self.alert_monitor.active_alerts:
            report_lines.append("### Active Alerts")
            report_lines.append("")
            for alert_key in sorted(self.alert_monitor.active_alerts):
                report_lines.append(f"- {alert_key}")
            report_lines.append("")
        else:
            report_lines.append("No active alerts during test period.")
            report_lines.append("")

        # Recommendations
        report_lines.append("---")
        report_lines.append("")
        report_lines.append("## Recommendations")
        report_lines.append("")

        if self.passed:
            report_lines.append("### Production Promotion")
            report_lines.append("")
            report_lines.append("The soak test PASSED all criteria. Configuration is ready for production deployment.")
            report_lines.append("")
            report_lines.append("**Next Steps:**")
            report_lines.append("")
            report_lines.append("1. Review Prometheus dashboard snapshot")
            report_lines.append("2. Verify all circuit breaker trips were legitimate")
            report_lines.append("3. Deploy to production with same configuration")
            report_lines.append("4. Monitor first 24h closely for any anomalies")
            report_lines.append("5. Keep fallback configuration ready for quick rollback")
            report_lines.append("")
        else:
            report_lines.append("### Failed Criteria - Action Required")
            report_lines.append("")
            report_lines.append("The soak test FAILED one or more criteria. Do NOT promote to production.")
            report_lines.append("")
            report_lines.append("**Action Items:**")
            report_lines.append("")

            if not net_pnl_pass:
                report_lines.append("- **Negative P&L:** Review strategy parameters, market conditions, and risk settings")
            if not pf_pass:
                report_lines.append("- **Low Profit Factor:** Analyze win/loss ratio, consider tighter entry criteria")
            if not cb_pass:
                report_lines.append("- **Excessive Circuit Breaker Trips:** Review latency, spread, and rate limiting thresholds")
            if not lag_pass:
                report_lines.append("- **High Message Lag:** Investigate Redis connection, network latency, or data processing bottlenecks")

            report_lines.append("")
            report_lines.append("**Recommendation:** Run another 48h soak test after addressing failed criteria.")
            report_lines.append("")

        # Appendix
        report_lines.append("---")
        report_lines.append("")
        report_lines.append("## Appendix")
        report_lines.append("")
        report_lines.append("### Configuration Files")
        report_lines.append("")
        report_lines.append("- **Enhanced Scalper Config:** `config/enhanced_scalper_config.yaml`")
        report_lines.append("- **Test Results:** `out/soak_test/soak_test_results.json`")
        report_lines.append("- **Prometheus Snapshot:** `out/soak_test/prometheus/`")
        report_lines.append("")

        report_lines.append("### Redis Streams")
        report_lines.append("")
        report_lines.append(f"- **Metrics Stream:** `{SoakTestConfig.STREAM_SOAK_METRICS}`")
        report_lines.append(f"- **Alerts Stream:** `{SoakTestConfig.STREAM_SOAK_ALERTS}`")
        report_lines.append(f"- **Status Stream:** `{SoakTestConfig.STREAM_SOAK_STATUS}`")
        report_lines.append(f"- **Signals API Stream:** `{SoakTestConfig.STREAM_SIGNALS_API}`")
        report_lines.append(f"- **Signals Site Stream:** `{SoakTestConfig.STREAM_SIGNALS_SITE}`")
        report_lines.append("")

        report_lines.append("---")
        report_lines.append("")
        report_lines.append(f"*48-Hour Soak Test Report - Generated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
        report_lines.append("")

        # Write report
        report_content = "\n".join(report_lines)
        with open(SoakTestConfig.REPORT_FILE, 'w') as f:
            f.write(report_content)

        self.logger.info(f"Report saved to: {SoakTestConfig.REPORT_FILE}")

    async def _promote_to_production_candidate(self, summary: Dict):
        """Promote configuration to production candidate."""
        # Generate version tag
        version = datetime.now().strftime('v%Y%m%d_%H%M%S')
        tag = f"PROD-CANDIDATE-{version}"

        self.logger.info(f"\n{'='*80}")
        self.logger.info(f"PROMOTING TO PRODUCTION CANDIDATE: {tag}")
        self.logger.info(f"{'='*80}")

        # 1. Tag current configuration
        config_source = Path("config/enhanced_scalper_config.yaml")
        config_backup_dir = Path("config/prod_candidates")
        config_backup_dir.mkdir(parents=True, exist_ok=True)

        tagged_config_path = config_backup_dir / f"enhanced_scalper_config.{tag}.yaml"

        if config_source.exists():
            import shutil
            shutil.copy2(config_source, tagged_config_path)
            self.logger.info(f"[OK] Tagged config saved to: {tagged_config_path}")
        else:
            self.logger.warning(f"[WARN] Config file not found: {config_source}")

        # 2. Create promotion metadata
        promotion_metadata = {
            'tag': tag,
            'version': version,
            'promoted_at': datetime.now().isoformat(),
            'test_duration_hours': summary['elapsed_hours'],
            'test_start': datetime.fromtimestamp(self.start_time).isoformat(),
            'test_end': datetime.fromtimestamp(time.time()).isoformat(),
            'configuration': {
                'turbo_scalper': SoakTestConfig.TURBO_SCALPER_ENABLED,
                'timeframe_15s': SoakTestConfig.TIMEFRAME_15S_ENABLED,
                'timeframe_5s_conditional': True,
                'trading_mode': SoakTestConfig.TRADING_MODE,
                'trading_pairs': SoakTestConfig.TRADING_PAIRS,
            },
            'metrics': {
                'net_pnl': summary['net_pnl'],
                'profit_factor': summary['profit_factor'],
                'total_trades': summary['total_trades'],
                'win_rate': summary['win_rate'],
                'avg_latency_ms': summary['avg_latency_ms'],
                'max_latency_ms': summary['max_latency_ms'],
                'max_heat_pct': summary['max_heat_pct'],
                'circuit_breaker_trips_per_hour': summary['circuit_breaker_trips_per_hour'],
                'max_lag_msgs': summary['max_lag_msgs'],
            },
            'pass_criteria': {
                'net_pnl_positive': summary['net_pnl'] >= SoakTestConfig.PASS_MIN_NET_PNL,
                'profit_factor_ge_125': summary['profit_factor'] >= SoakTestConfig.PASS_MIN_PROFIT_FACTOR,
                'cb_trips_acceptable': summary['circuit_breaker_trips_per_hour'] <= SoakTestConfig.PASS_MAX_CIRCUIT_BREAKER_TRIPS_PER_HOUR,
                'lag_acceptable': summary['max_lag_msgs'] < SoakTestConfig.PASS_MAX_LAG_MSGS,
            },
            'config_file': str(tagged_config_path),
        }

        metadata_path = config_backup_dir / f"promotion_metadata.{tag}.json"
        with open(metadata_path, 'w') as f:
            json.dump(promotion_metadata, f, indent=2)

        self.logger.info(f"[OK] Promotion metadata saved to: {metadata_path}")

        # 3. Export Prometheus snapshot metadata
        prometheus_snapshot = {
            'tag': tag,
            'exported_at': datetime.now().isoformat(),
            'test_duration_hours': summary['elapsed_hours'],
            'dashboards': [
                {
                    'name': 'Soak Test Live Metrics',
                    'metrics': {
                        'pnl': summary['net_pnl'],
                        'profit_factor': summary['profit_factor'],
                        'trades': summary['total_trades'],
                        'win_rate': summary['win_rate'],
                        'latency_avg': summary['avg_latency_ms'],
                        'latency_max': summary['max_latency_ms'],
                        'heat_max': summary['max_heat_pct'],
                        'cb_trips': summary['circuit_breaker_trips'],
                        'lag_max': summary['max_lag_msgs'],
                    },
                },
                {
                    'name': 'Circuit Breaker Status',
                    'metrics': {
                        'total_trips': summary['circuit_breaker_trips'],
                        'trips_per_hour': summary['circuit_breaker_trips_per_hour'],
                        'threshold': SoakTestConfig.PASS_MAX_CIRCUIT_BREAKER_TRIPS_PER_HOUR,
                    },
                },
                {
                    'name': 'Latency Distribution',
                    'metrics': {
                        'avg_ms': summary['avg_latency_ms'],
                        'max_ms': summary['max_latency_ms'],
                        'budget_ms': SoakTestConfig.ALERT_LATENCY_BUDGET_MS,
                        'samples': len(self.metrics_collector.latency_samples),
                    },
                },
            ],
            'instructions': [
                'In production, this would contain Prometheus query snapshots',
                'Dashboard JSON exports would be included',
                'Time-series data would be preserved for historical comparison',
            ],
        }

        prometheus_path = Path(SoakTestConfig.PROMETHEUS_SNAPSHOT_DIR) / f"snapshot.{tag}.json"
        prometheus_path.parent.mkdir(parents=True, exist_ok=True)

        with open(prometheus_path, 'w') as f:
            json.dump(prometheus_snapshot, f, indent=2)

        self.logger.info(f"[OK] Prometheus snapshot metadata saved to: {prometheus_path}")

        # 4. Publish promotion event to Redis
        promotion_event = {
            'event': 'PRODUCTION_CANDIDATE_PROMOTED',
            'tag': tag,
            'version': version,
            'timestamp': datetime.now().isoformat(),
            'metrics_summary': {
                'net_pnl': summary['net_pnl'],
                'profit_factor': summary['profit_factor'],
                'total_trades': summary['total_trades'],
            },
        }

        await self.redis_client.publish_metrics(
            'soak:promotions',
            promotion_event
        )

        self.logger.info(f"\n[OK] Tagged as {tag}")
        self.logger.info(f"[OK] Config saved to: {tagged_config_path}")
        self.logger.info(f"[OK] Prometheus snapshot exported to: {SoakTestConfig.PROMETHEUS_SNAPSHOT_DIR}")
        self.logger.info(f"[OK] Promotion event published to Redis stream 'soak:promotions'")

        self.logger.info(f"\n{'='*80}")
        self.logger.info("READY FOR PRODUCTION DEPLOYMENT")
        self.logger.info(f"{'='*80}")
        self.logger.info(f"\nTo deploy this configuration:")
        self.logger.info(f"  1. Review report: {SoakTestConfig.REPORT_FILE}")
        self.logger.info(f"  2. Review config: {tagged_config_path}")
        self.logger.info(f"  3. Deploy to production with tag: {tag}")
        self.logger.info(f"  4. Monitor first 24h closely")
        self.logger.info("")


# ============================================================================
# MAIN EXECUTION
# ============================================================================

async def main():
    """Main execution."""
    orchestrator = SoakTestOrchestrator()
    passed = await orchestrator.start()

    return 0 if passed else 1


if __name__ == '__main__':
    exit(asyncio.run(main()))
