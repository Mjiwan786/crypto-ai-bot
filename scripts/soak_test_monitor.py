#!/usr/bin/env python3
"""
48-Hour Soak Test Monitor

Real-time monitoring and alerting for the soak test:
- Portfolio heat > 80%
- Latency > budget
- Redis lag > threshold
- Circuit breaker trips
- P&L tracking

Publishes alerts to:
- Discord webhook
- Redis metrics:alerts stream
- Prometheus alerts
- Console output

Usage:
    python scripts/soak_test_monitor.py --config config/soak_test_48h_turbo.yaml
"""

import os
import sys
import time
import json
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from pathlib import Path

import redis
import requests
import yaml
from prometheus_client import Gauge, Counter, start_http_server

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler('logs/soak_test_monitor.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# =============================================================================
# Prometheus Metrics
# =============================================================================

# Soak test metrics
soak_test_pnl_usd = Gauge('soak_test_pnl_usd', 'Soak test cumulative P&L')
soak_test_profit_factor = Gauge('soak_test_profit_factor', 'Soak test profit factor')
soak_test_portfolio_heat_pct = Gauge('soak_test_portfolio_heat_pct', 'Portfolio heat %')
soak_test_latency_p95_ms = Gauge('soak_test_latency_p95_ms', 'P95 latency in ms')
soak_test_redis_lag_sec = Gauge('soak_test_redis_lag_sec', 'Redis stream lag in seconds')
soak_test_circuit_breaker_trips = Counter('soak_test_circuit_breaker_trips_total', 'Circuit breaker trips', ['type'])
soak_test_alerts_fired = Counter('soak_test_alerts_fired_total', 'Alerts fired', ['type'])
soak_test_trades_total = Counter('soak_test_trades_total', 'Total trades', ['strategy'])


# =============================================================================
# Alert Types
# =============================================================================

@dataclass
class Alert:
    """Alert data structure"""
    timestamp: float
    severity: str  # 'warning', 'critical'
    type: str
    message: str
    value: float
    threshold: float
    details: Dict

    def to_dict(self):
        return asdict(self)


# =============================================================================
# Soak Test Monitor
# =============================================================================

class SoakTestMonitor:
    """
    Monitors soak test metrics and triggers alerts.
    """

    def __init__(self, config_path: str):
        """
        Initialize monitor.

        Args:
            config_path: Path to soak test config
        """
        self.config = self._load_config(config_path)
        self.redis_client = self._connect_redis()
        self.discord_webhook = os.getenv('DISCORD_WEBHOOK_URL')

        # Alert thresholds (from config)
        thresholds = self.config['monitoring']['alert_thresholds']
        self.heat_threshold = thresholds['portfolio_heat_pct']
        self.latency_threshold = thresholds['latency_p95_ms']
        self.lag_threshold = thresholds['redis_lag_seconds']
        self.breaker_threshold = thresholds['circuit_breaker_trips_per_hour']
        self.daily_loss_threshold = thresholds['daily_loss_pct']
        self.dd_threshold = thresholds['drawdown_pct']

        # State tracking
        self.start_time = time.time()
        self.alert_history: List[Alert] = []
        self.last_alert_times: Dict[str, float] = {}
        self.alert_cooldown_sec = 300  # 5 min cooldown per alert type

        # Metrics tracking
        self.initial_capital = self.config['bot']['paper_starting_capital_usd']
        self.current_equity = self.initial_capital
        self.peak_equity = self.initial_capital
        self.total_trades = 0
        self.circuit_breaker_trips = 0

        logger.info(f"SoakTestMonitor initialized with config: {config_path}")
        logger.info(f"Alert thresholds: heat={self.heat_threshold}%, "
                   f"latency={self.latency_threshold}ms, lag={self.lag_threshold}s")

    def _load_config(self, config_path: str) -> Dict:
        """Load soak test configuration"""
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)

    def _connect_redis(self) -> redis.Redis:
        """Connect to Redis Cloud with TLS"""
        redis_config = self.config['redis']

        return redis.Redis(
            host='redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com',
            port=19818,
            password='&lt;REDIS_PASSWORD&gt;**$$',
            ssl=True,
            ssl_ca_certs=redis_config['tls_ca_cert_path'],
            decode_responses=True,
            socket_timeout=5,
        )

    async def run(self):
        """Main monitoring loop"""
        logger.info("Starting 48-hour soak test monitoring...")
        logger.info(f"Start time: {datetime.now().isoformat()}")
        logger.info(f"End time: {(datetime.now() + timedelta(hours=48)).isoformat()}")

        # Start Prometheus metrics server
        start_http_server(9109, addr='0.0.0.0')
        logger.info("Prometheus metrics server started on :9109")

        # Send initial alert
        await self._send_alert(Alert(
            timestamp=time.time(),
            severity='info',
            type='soak_test_started',
            message='48-hour soak test monitoring started',
            value=0,
            threshold=0,
            details={'config': self.config['soak_test']['version']}
        ))

        # Main loop
        iteration = 0
        while True:
            iteration += 1
            elapsed_hours = (time.time() - self.start_time) / 3600

            # Check if 48 hours elapsed
            if elapsed_hours >= 48.0:
                logger.info("48 hours complete! Running final validation...")
                await self._finalize_soak_test()
                break

            try:
                # Fetch metrics
                metrics = await self._fetch_metrics()

                # Update Prometheus
                self._update_prometheus(metrics)

                # Check thresholds and alert
                await self._check_thresholds(metrics)

                # Log checkpoint every hour
                if iteration % 60 == 0:  # Every 60 iterations (1 hour)
                    await self._log_checkpoint(elapsed_hours, metrics)

            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}", exc_info=True)

            # Sleep for 60 seconds
            await asyncio.sleep(60)

    async def _fetch_metrics(self) -> Dict:
        """Fetch current metrics from Redis"""
        metrics = {}

        try:
            # 1. Performance metrics
            perf_stream = self.redis_client.xrevrange('metrics:performance', count=1)
            if perf_stream:
                msg_id, data = perf_stream[0]
                metrics['pnl_usd'] = float(data.get('total_pnl_usd', 0))
                metrics['current_equity'] = float(data.get('current_equity_usd', self.initial_capital))
                metrics['win_rate'] = float(data.get('win_rate', 0))
                metrics['total_trades'] = int(data.get('total_trades', 0))

                # Calculate profit factor
                avg_win = float(data.get('avg_win_usd', 0))
                avg_loss = float(data.get('avg_loss_usd', 1))
                win_rate = float(data.get('win_rate', 0))
                loss_rate = float(data.get('loss_rate', 1))

                if loss_rate > 0 and avg_loss > 0:
                    metrics['profit_factor'] = (win_rate * avg_win) / (loss_rate * avg_loss)
                else:
                    metrics['profit_factor'] = 0.0

            # 2. Circuit breaker trips (from logs or counter)
            breaker_key = 'soak_test:circuit_breaker_trips'
            metrics['circuit_breaker_trips'] = int(self.redis_client.get(breaker_key) or 0)

            # 3. Portfolio heat (mock - would come from risk manager)
            heat_key = 'portfolio:heat_pct'
            metrics['portfolio_heat_pct'] = float(self.redis_client.get(heat_key) or 0)

            # 4. Latency (from Prometheus or logs)
            # For now, check Redis PING latency as proxy
            start = time.time()
            self.redis_client.ping()
            metrics['redis_ping_ms'] = (time.time() - start) * 1000

            # 5. Stream lag
            # Check scalper signal stream age
            scalper_stream = self.redis_client.xrevrange('signals:scalper', count=1)
            if scalper_stream:
                msg_id, _ = scalper_stream[0]
                msg_timestamp_ms = int(msg_id.split('-')[0])
                now_ms = int(time.time() * 1000)
                metrics['redis_lag_sec'] = (now_ms - msg_timestamp_ms) / 1000.0
            else:
                metrics['redis_lag_sec'] = 0.0

            # 6. Drawdown
            self.current_equity = metrics.get('current_equity', self.initial_capital)
            self.peak_equity = max(self.peak_equity, self.current_equity)
            metrics['drawdown_pct'] = ((self.peak_equity - self.current_equity) / self.peak_equity) * 100

        except Exception as e:
            logger.error(f"Error fetching metrics: {e}")

        return metrics

    def _update_prometheus(self, metrics: Dict):
        """Update Prometheus gauges"""
        try:
            soak_test_pnl_usd.set(metrics.get('pnl_usd', 0))
            soak_test_profit_factor.set(metrics.get('profit_factor', 0))
            soak_test_portfolio_heat_pct.set(metrics.get('portfolio_heat_pct', 0))
            soak_test_latency_p95_ms.set(metrics.get('redis_ping_ms', 0))
            soak_test_redis_lag_sec.set(metrics.get('redis_lag_sec', 0))
        except Exception as e:
            logger.error(f"Error updating Prometheus: {e}")

    async def _check_thresholds(self, metrics: Dict):
        """Check metrics against thresholds and trigger alerts"""
        alerts = []

        # 1. Portfolio heat
        heat = metrics.get('portfolio_heat_pct', 0)
        if heat > self.heat_threshold:
            alerts.append(Alert(
                timestamp=time.time(),
                severity='critical',
                type='portfolio_heat_high',
                message=f'Portfolio heat {heat:.1f}% exceeds threshold {self.heat_threshold}%',
                value=heat,
                threshold=self.heat_threshold,
                details=metrics
            ))

        # 2. Latency
        latency = metrics.get('redis_ping_ms', 0)
        if latency > self.latency_threshold:
            alerts.append(Alert(
                timestamp=time.time(),
                severity='warning',
                type='latency_high',
                message=f'Latency {latency:.1f}ms exceeds threshold {self.latency_threshold}ms',
                value=latency,
                threshold=self.latency_threshold,
                details=metrics
            ))

        # 3. Redis lag
        lag = metrics.get('redis_lag_sec', 0)
        if lag > self.lag_threshold:
            alerts.append(Alert(
                timestamp=time.time(),
                severity='critical',
                type='redis_lag_high',
                message=f'Redis lag {lag:.1f}s exceeds threshold {self.lag_threshold}s',
                value=lag,
                threshold=self.lag_threshold,
                details=metrics
            ))

        # 4. Circuit breaker trips
        trips = metrics.get('circuit_breaker_trips', 0)
        elapsed_hours = (time.time() - self.start_time) / 3600
        trips_per_hour = trips / max(elapsed_hours, 0.1)
        if trips_per_hour > self.breaker_threshold:
            alerts.append(Alert(
                timestamp=time.time(),
                severity='warning',
                type='circuit_breaker_overused',
                message=f'Circuit breakers tripping {trips_per_hour:.1f}/hour, threshold {self.breaker_threshold}/hour',
                value=trips_per_hour,
                threshold=self.breaker_threshold,
                details={'total_trips': trips, 'elapsed_hours': elapsed_hours}
            ))

        # 5. Daily loss
        pnl = metrics.get('pnl_usd', 0)
        pnl_pct = (pnl / self.initial_capital) * 100
        if pnl_pct < -self.daily_loss_threshold:
            alerts.append(Alert(
                timestamp=time.time(),
                severity='critical',
                type='daily_loss_exceeded',
                message=f'Loss {pnl_pct:.2f}% exceeds daily threshold {self.daily_loss_threshold}%',
                value=pnl_pct,
                threshold=-self.daily_loss_threshold,
                details=metrics
            ))

        # 6. Drawdown
        dd = metrics.get('drawdown_pct', 0)
        if dd > self.dd_threshold:
            alerts.append(Alert(
                timestamp=time.time(),
                severity='critical',
                type='drawdown_exceeded',
                message=f'Drawdown {dd:.2f}% exceeds threshold {self.dd_threshold}%',
                value=dd,
                threshold=self.dd_threshold,
                details=metrics
            ))

        # Send alerts (with cooldown)
        for alert in alerts:
            await self._send_alert(alert)

    async def _send_alert(self, alert: Alert):
        """Send alert to all configured channels"""
        # Check cooldown
        now = time.time()
        last_alert_time = self.last_alert_times.get(alert.type, 0)
        if now - last_alert_time < self.alert_cooldown_sec:
            return  # Skip (cooldown active)

        # Update last alert time
        self.last_alert_times[alert.type] = now

        # Log alert
        logger.warning(f"ALERT [{alert.severity.upper()}] {alert.type}: {alert.message}")

        # Update Prometheus counter
        soak_test_alerts_fired.labels(type=alert.type).inc()

        # Store in history
        self.alert_history.append(alert)

        # Publish to Redis
        try:
            self.redis_client.xadd('metrics:alerts', alert.to_dict())
        except Exception as e:
            logger.error(f"Error publishing alert to Redis: {e}")

        # Send to Discord
        if self.discord_webhook:
            await self._send_discord_alert(alert)

    async def _send_discord_alert(self, alert: Alert):
        """Send alert to Discord webhook"""
        try:
            # Color based on severity
            color = 0xFF0000 if alert.severity == 'critical' else 0xFFA500

            payload = {
                "embeds": [{
                    "title": f"🚨 Soak Test Alert: {alert.type}",
                    "description": alert.message,
                    "color": color,
                    "fields": [
                        {"name": "Severity", "value": alert.severity.upper(), "inline": True},
                        {"name": "Value", "value": f"{alert.value:.2f}", "inline": True},
                        {"name": "Threshold", "value": f"{alert.threshold:.2f}", "inline": True},
                    ],
                    "timestamp": datetime.fromtimestamp(alert.timestamp).isoformat()
                }]
            }

            response = requests.post(self.discord_webhook, json=payload, timeout=5)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Error sending Discord alert: {e}")

    async def _log_checkpoint(self, elapsed_hours: float, metrics: Dict):
        """Log checkpoint report"""
        logger.info("=" * 80)
        logger.info(f"CHECKPOINT REPORT - Hour {elapsed_hours:.1f}/48")
        logger.info("=" * 80)
        logger.info(f"P&L: ${metrics.get('pnl_usd', 0):.2f}")
        logger.info(f"Equity: ${metrics.get('current_equity', 0):.2f}")
        logger.info(f"Profit Factor: {metrics.get('profit_factor', 0):.2f}")
        logger.info(f"Win Rate: {metrics.get('win_rate', 0):.1%}")
        logger.info(f"Total Trades: {metrics.get('total_trades', 0)}")
        logger.info(f"Portfolio Heat: {metrics.get('portfolio_heat_pct', 0):.1f}%")
        logger.info(f"Drawdown: {metrics.get('drawdown_pct', 0):.2f}%")
        logger.info(f"Latency: {metrics.get('redis_ping_ms', 0):.1f}ms")
        logger.info(f"Circuit Breakers: {metrics.get('circuit_breaker_trips', 0)} trips")
        logger.info(f"Alerts Fired: {len(self.alert_history)}")
        logger.info("=" * 80)

        # Publish checkpoint to Redis
        checkpoint = {
            'elapsed_hours': elapsed_hours,
            'timestamp': time.time(),
            **metrics
        }
        self.redis_client.xadd('soak_test:checkpoints', checkpoint)

    async def _finalize_soak_test(self):
        """Finalize soak test and validate success gates"""
        logger.info("=" * 80)
        logger.info("SOAK TEST COMPLETE - FINAL VALIDATION")
        logger.info("=" * 80)

        # Fetch final metrics
        final_metrics = await self._fetch_metrics()

        # Run validation
        from scripts.soak_test_validator import SoakTestValidator
        validator = SoakTestValidator(self.config, final_metrics, self.alert_history)
        passed, results = validator.validate()

        logger.info(f"Validation Result: {'PASS ✅' if passed else 'FAIL ❌'}")
        logger.info(f"Final Report: {results}")

        # Send final alert
        await self._send_alert(Alert(
            timestamp=time.time(),
            severity='info' if passed else 'critical',
            type='soak_test_completed',
            message=f'48-hour soak test completed: {"PASSED" if passed else "FAILED"}',
            value=1.0 if passed else 0.0,
            threshold=1.0,
            details=results
        ))


# =============================================================================
# Main
# =============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(description='48-hour soak test monitor')
    parser.add_argument('--config', required=True, help='Path to soak test config')
    args = parser.parse_args()

    # Run monitor
    monitor = SoakTestMonitor(args.config)
    asyncio.run(monitor.run())


if __name__ == '__main__':
    main()
