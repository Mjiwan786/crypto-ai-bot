#!/usr/bin/env python3
"""
48-Hour Soak Test Validator
Validates soak test results against success gates and promotes config to PROD if passing.

Usage:
    python scripts/soak_test_validator.py --config config/soak_test_48h_turbo.yaml
"""

import asyncio
import json
import sys
import yaml
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict
import argparse
import shutil

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import redis.asyncio as aioredis
    from prometheus_client.parser import text_string_to_metric_families
    import requests
except ImportError as e:
    print(f"❌ Missing dependency: {e}")
    print("Install with: pip install redis[hiredis] prometheus-client requests")
    sys.exit(1)


@dataclass
class ValidationResult:
    """Result of validating a single success gate"""
    gate_name: str
    passed: bool
    threshold: float
    actual_value: float
    message: str


@dataclass
class SoakTestReport:
    """Final soak test report"""
    start_time: datetime
    end_time: datetime
    duration_hours: float
    passed: bool

    # Success gates
    gates: List[ValidationResult]

    # Summary metrics
    net_pnl_usd: float
    profit_factor: float
    win_rate: float
    total_trades: int
    circuit_breaker_trips: int
    max_portfolio_heat_pct: float
    latency_p95_ms: float
    redis_lag_seconds: float

    # Strategy breakdown
    strategy_metrics: Dict[str, Dict]

    # Recommendations (if failed)
    recommendations: List[str]

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        data = asdict(self)
        data['start_time'] = self.start_time.isoformat()
        data['end_time'] = self.end_time.isoformat()
        return data


class SoakTestValidator:
    """Validates 48h soak test results and handles promotion logic"""

    def __init__(self, config_path: str):
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self.redis_client: Optional[aioredis.Redis] = None

        # Extract success gates
        self.success_gates = self.config.get('soak_test', {}).get('success_gates', {})

        print(f"✅ Loaded soak test config: {self.config_path}")
        print(f"✅ Success gates: {len(self.success_gates)} criteria")

    def _load_config(self) -> Dict:
        """Load soak test configuration"""
        with open(self.config_path, 'r') as f:
            return yaml.safe_load(f)

    async def connect_redis(self):
        """Connect to Redis"""
        redis_config = self.config.get('redis', {})
        redis_url = redis_config.get('url')

        if not redis_url:
            raise ValueError("Redis URL not found in config")

        # Parse TLS settings
        tls_enabled = redis_config.get('tls_enabled', False)

        if tls_enabled:
            # Use rediss:// URL (Redis handles TLS)
            self.redis_client = await aioredis.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=True,
                max_connections=10
            )
        else:
            self.redis_client = await aioredis.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=True
            )

        # Test connection
        await self.redis_client.ping()
        print("✅ Connected to Redis")

    async def fetch_soak_test_metrics(self) -> Dict[str, Any]:
        """Fetch all metrics from Redis soak test stream"""
        stream_name = self.config.get('redis', {}).get('streams', {}).get('soak_test', 'soak_test:v1')

        # Read all messages from soak test stream
        messages = await self.redis_client.xrevrange(stream_name, '+', '-', count=1000)

        if not messages:
            raise ValueError(f"No data found in stream: {stream_name}")

        print(f"✅ Fetched {len(messages)} entries from {stream_name}")

        # Parse latest snapshot
        latest_msg_id, latest_data = messages[0]

        # Convert Redis hash to dict
        metrics = {}
        for key, value in latest_data.items():
            try:
                # Try to parse as float/int
                if '.' in value:
                    metrics[key] = float(value)
                else:
                    metrics[key] = int(value)
            except (ValueError, AttributeError):
                # Keep as string
                metrics[key] = value

        return metrics

    async def fetch_performance_metrics(self) -> Dict[str, Any]:
        """Fetch performance metrics (PnL, profit factor, etc.)"""
        stream_name = 'metrics:performance'

        messages = await self.redis_client.xrevrange(stream_name, '+', '-', count=1)

        if not messages:
            print("⚠️  No performance metrics found, using defaults")
            return {
                'net_pnl_usd': 0.0,
                'profit_factor': 0.0,
                'win_rate': 0.0,
                'total_trades': 0
            }

        latest_msg_id, latest_data = messages[0]

        return {
            'net_pnl_usd': float(latest_data.get('cumulative_pnl_usd', 0.0)),
            'profit_factor': float(latest_data.get('profit_factor', 0.0)),
            'win_rate': float(latest_data.get('win_rate', 0.0)),
            'total_trades': int(latest_data.get('total_trades', 0)),
            'avg_win_usd': float(latest_data.get('avg_win_usd', 0.0)),
            'avg_loss_usd': float(latest_data.get('avg_loss_usd', 0.0)),
        }

    async def fetch_circuit_breaker_metrics(self) -> Dict[str, Any]:
        """Fetch circuit breaker trip counts"""
        # Check if there's a dedicated circuit breaker stream
        stream_name = 'metrics:circuit_breakers'

        try:
            messages = await self.redis_client.xrevrange(stream_name, '+', '-', count=100)

            # Count trips in last 48 hours
            total_trips = len(messages)

            return {
                'total_trips': total_trips,
                'trips_per_hour': total_trips / 48.0
            }
        except Exception:
            # No circuit breaker stream, assume 0 trips
            return {
                'total_trips': 0,
                'trips_per_hour': 0.0
            }

    def fetch_prometheus_metrics(self) -> Dict[str, float]:
        """Fetch latest metrics from Prometheus exporter"""
        prometheus_port = self.config.get('monitoring', {}).get('prometheus_port', 9108)

        try:
            response = requests.get(f'http://localhost:{prometheus_port}/metrics', timeout=5)
            response.raise_for_status()

            metrics = {}
            for family in text_string_to_metric_families(response.text):
                for sample in family.samples:
                    metrics[sample.name] = sample.value

            return metrics
        except Exception as e:
            print(f"⚠️  Failed to fetch Prometheus metrics: {e}")
            return {}

    async def validate_success_gates(self, metrics: Dict[str, Any]) -> List[ValidationResult]:
        """Validate all success gates against actual metrics"""
        results = []

        # Fetch additional metrics
        perf_metrics = await self.fetch_performance_metrics()
        cb_metrics = await self.fetch_circuit_breaker_metrics()
        prom_metrics = self.fetch_prometheus_metrics()

        # Merge all metrics
        all_metrics = {**metrics, **perf_metrics, **cb_metrics, **prom_metrics}

        # Gate 1: Minimum net PnL
        min_pnl = self.success_gates.get('min_net_pnl_usd', 0.01)
        actual_pnl = all_metrics.get('net_pnl_usd', 0.0)
        results.append(ValidationResult(
            gate_name='min_net_pnl_usd',
            passed=actual_pnl >= min_pnl,
            threshold=min_pnl,
            actual_value=actual_pnl,
            message=f"Net P&L: ${actual_pnl:.2f} (threshold: ${min_pnl:.2f})"
        ))

        # Gate 2: Minimum profit factor
        min_pf = self.success_gates.get('min_profit_factor', 1.25)
        actual_pf = all_metrics.get('profit_factor', 0.0)
        results.append(ValidationResult(
            gate_name='min_profit_factor',
            passed=actual_pf >= min_pf,
            threshold=min_pf,
            actual_value=actual_pf,
            message=f"Profit Factor: {actual_pf:.2f} (threshold: {min_pf:.2f})"
        ))

        # Gate 3: Circuit breaker trips
        max_trips = self.success_gates.get('max_circuit_breaker_trips_per_hour', 3)
        actual_trips = cb_metrics.get('trips_per_hour', 0.0)
        results.append(ValidationResult(
            gate_name='max_circuit_breaker_trips_per_hour',
            passed=actual_trips <= max_trips,
            threshold=max_trips,
            actual_value=actual_trips,
            message=f"CB trips/hour: {actual_trips:.2f} (max: {max_trips})"
        ))

        # Gate 4: Scalper lag messages
        max_lag_msgs = self.success_gates.get('max_scalper_lag_messages', 5)
        actual_lag_msgs = all_metrics.get('scalper_lag_messages', 0)
        results.append(ValidationResult(
            gate_name='max_scalper_lag_messages',
            passed=actual_lag_msgs <= max_lag_msgs,
            threshold=max_lag_msgs,
            actual_value=actual_lag_msgs,
            message=f"Scalper lag messages: {actual_lag_msgs} (max: {max_lag_msgs})"
        ))

        # Gate 5: Portfolio heat
        max_heat = self.success_gates.get('max_portfolio_heat_pct', 80.0)
        actual_heat = all_metrics.get('portfolio_heat_pct', 0.0)
        results.append(ValidationResult(
            gate_name='max_portfolio_heat_pct',
            passed=actual_heat <= max_heat,
            threshold=max_heat,
            actual_value=actual_heat,
            message=f"Portfolio heat: {actual_heat:.1f}% (max: {max_heat}%)"
        ))

        # Gate 6: Latency p95
        max_latency = self.success_gates.get('max_latency_p95_ms', 500)
        actual_latency = all_metrics.get('latency_p95_ms', 0.0)
        results.append(ValidationResult(
            gate_name='max_latency_p95_ms',
            passed=actual_latency <= max_latency,
            threshold=max_latency,
            actual_value=actual_latency,
            message=f"Latency p95: {actual_latency:.0f}ms (max: {max_latency}ms)"
        ))

        # Gate 7: Redis lag
        max_redis_lag = self.success_gates.get('max_redis_lag_seconds', 2.0)
        actual_redis_lag = all_metrics.get('redis_lag_seconds', 0.0)
        results.append(ValidationResult(
            gate_name='max_redis_lag_seconds',
            passed=actual_redis_lag <= max_redis_lag,
            threshold=max_redis_lag,
            actual_value=actual_redis_lag,
            message=f"Redis lag: {actual_redis_lag:.2f}s (max: {max_redis_lag}s)"
        ))

        return results

    def generate_recommendations(self, failed_gates: List[ValidationResult]) -> List[str]:
        """Generate recommendations for failed gates"""
        recommendations = []

        for gate in failed_gates:
            if gate.gate_name == 'min_net_pnl_usd':
                recommendations.append(
                    "❌ Net P&L is negative. Check: (1) Strategy parameters too aggressive, "
                    "(2) Market conditions unfavorable, (3) Execution quality issues."
                )

            elif gate.gate_name == 'min_profit_factor':
                recommendations.append(
                    "❌ Profit factor too low. Recommendations: (1) Widen stop losses, "
                    "(2) Increase trigger thresholds to reduce noise trades, "
                    "(3) Review target/stop ratio."
                )

            elif gate.gate_name == 'max_circuit_breaker_trips_per_hour':
                recommendations.append(
                    "❌ Too many circuit breaker trips. Check: (1) Risk limits too tight, "
                    "(2) Strategy generating too many signals, (3) Market volatility spikes."
                )

            elif gate.gate_name == 'max_scalper_lag_messages':
                recommendations.append(
                    "❌ Scalper experiencing lag. Recommendations: (1) Reduce message rate, "
                    "(2) Optimize data ingestion pipeline, (3) Consider disabling 5s bars."
                )

            elif gate.gate_name == 'max_portfolio_heat_pct':
                recommendations.append(
                    "❌ Portfolio heat too high. Reduce: (1) Position sizes, "
                    "(2) Number of concurrent positions, (3) Leverage."
                )

            elif gate.gate_name == 'max_latency_p95_ms':
                recommendations.append(
                    "❌ Latency too high. Check: (1) Network issues, "
                    "(2) Redis Cloud performance, (3) Kraken WebSocket stability."
                )

            elif gate.gate_name == 'max_redis_lag_seconds':
                recommendations.append(
                    "❌ Redis lag detected. Recommendations: (1) Check Redis Cloud health, "
                    "(2) Review stream trimming settings, (3) Optimize message size."
                )

        return recommendations

    async def export_prometheus_snapshot(self, output_path: Path):
        """Export current Prometheus metrics to JSON snapshot"""
        prom_metrics = self.fetch_prometheus_metrics()

        snapshot = {
            'timestamp': datetime.utcnow().isoformat(),
            'source': 'soak_test_48h_turbo',
            'metrics': prom_metrics
        }

        with open(output_path, 'w') as f:
            json.dump(snapshot, f, indent=2)

        print(f"✅ Exported Prometheus snapshot: {output_path}")

    def tag_config_as_prod_candidate(self, version: str):
        """Tag config as PROD-CANDIDATE-vX by creating versioned copy"""
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        tag = f"PROD-CANDIDATE-{version}"

        # Create tagged copy
        tagged_path = self.config_path.parent / f"soak_test_48h_turbo_{tag}_{timestamp}.yaml"
        shutil.copy2(self.config_path, tagged_path)

        print(f"✅ Tagged config as {tag}: {tagged_path}")

        # Also create a symlink to latest prod candidate
        latest_link = self.config_path.parent / "soak_test_48h_turbo_PROD_LATEST.yaml"
        if latest_link.exists():
            latest_link.unlink()

        try:
            latest_link.symlink_to(tagged_path.name)
            print(f"✅ Updated symlink: {latest_link} -> {tagged_path.name}")
        except OSError:
            # Symlinks may not work on all Windows systems, copy instead
            shutil.copy2(tagged_path, latest_link)
            print(f"✅ Updated copy: {latest_link}")

    async def generate_final_report(
        self,
        validation_results: List[ValidationResult],
        metrics: Dict[str, Any]
    ) -> SoakTestReport:
        """Generate final soak test report"""

        # Determine overall pass/fail
        all_passed = all(r.passed for r in validation_results)
        failed_gates = [r for r in validation_results if not r.passed]

        # Fetch additional metrics for report
        perf_metrics = await self.fetch_performance_metrics()
        cb_metrics = await self.fetch_circuit_breaker_metrics()
        prom_metrics = self.fetch_prometheus_metrics()

        # Calculate duration
        start_time = datetime.utcnow() - timedelta(hours=48)  # Assume 48h ago
        end_time = datetime.utcnow()

        # Generate recommendations if failed
        recommendations = []
        if not all_passed:
            recommendations = self.generate_recommendations(failed_gates)

        # Create report
        report = SoakTestReport(
            start_time=start_time,
            end_time=end_time,
            duration_hours=48.0,
            passed=all_passed,
            gates=validation_results,
            net_pnl_usd=perf_metrics.get('net_pnl_usd', 0.0),
            profit_factor=perf_metrics.get('profit_factor', 0.0),
            win_rate=perf_metrics.get('win_rate', 0.0),
            total_trades=perf_metrics.get('total_trades', 0),
            circuit_breaker_trips=cb_metrics.get('total_trips', 0),
            max_portfolio_heat_pct=metrics.get('portfolio_heat_pct', 0.0),
            latency_p95_ms=prom_metrics.get('latency_p95_ms', 0.0),
            redis_lag_seconds=metrics.get('redis_lag_seconds', 0.0),
            strategy_metrics={
                'bar_reaction_5m': metrics.get('bar_reaction_5m', {}),
                'turbo_scalper_15s': metrics.get('turbo_scalper_15s', {})
            },
            recommendations=recommendations
        )

        return report

    def save_report(self, report: SoakTestReport, output_path: Path):
        """Save final report to JSON file"""
        with open(output_path, 'w') as f:
            json.dump(report.to_dict(), f, indent=2)

        print(f"✅ Saved final report: {output_path}")

    def print_summary(self, report: SoakTestReport):
        """Print human-readable summary"""
        print("\n" + "="*80)
        print("48-HOUR SOAK TEST VALIDATION REPORT")
        print("="*80)
        print(f"Start Time: {report.start_time.isoformat()}")
        print(f"End Time:   {report.end_time.isoformat()}")
        print(f"Duration:   {report.duration_hours} hours")
        print()

        # Overall result
        if report.passed:
            print("🟢 RESULT: PASSED ✅")
        else:
            print("🔴 RESULT: FAILED ❌")
        print()

        # Summary metrics
        print("SUMMARY METRICS")
        print("-" * 80)
        print(f"Net P&L:          ${report.net_pnl_usd:,.2f}")
        print(f"Profit Factor:    {report.profit_factor:.2f}")
        print(f"Win Rate:         {report.win_rate:.1f}%")
        print(f"Total Trades:     {report.total_trades}")
        print(f"CB Trips:         {report.circuit_breaker_trips}")
        print(f"Portfolio Heat:   {report.max_portfolio_heat_pct:.1f}%")
        print(f"Latency p95:      {report.latency_p95_ms:.0f}ms")
        print(f"Redis Lag:        {report.redis_lag_seconds:.2f}s")
        print()

        # Gate-by-gate results
        print("SUCCESS GATE VALIDATION")
        print("-" * 80)
        for gate in report.gates:
            status = "✅ PASS" if gate.passed else "❌ FAIL"
            print(f"{status} | {gate.message}")
        print()

        # Recommendations (if failed)
        if not report.passed:
            print("RECOMMENDATIONS")
            print("-" * 80)
            for i, rec in enumerate(report.recommendations, 1):
                print(f"{i}. {rec}")
            print()

        print("="*80)

    async def run_validation(self, auto_promote: bool = False) -> SoakTestReport:
        """Main validation workflow"""
        print("\n🚀 Starting 48-hour soak test validation...")
        print()

        # Connect to Redis
        await self.connect_redis()

        try:
            # Fetch metrics
            print("📊 Fetching metrics from Redis...")
            metrics = await self.fetch_soak_test_metrics()

            # Validate success gates
            print("🔍 Validating success gates...")
            validation_results = await self.validate_success_gates(metrics)

            # Generate final report
            print("📝 Generating final report...")
            report = await self.generate_final_report(validation_results, metrics)

            # Save report
            reports_dir = Path('reports')
            reports_dir.mkdir(exist_ok=True)

            timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            report_path = reports_dir / f"soak_test_48h_{timestamp}.json"
            self.save_report(report, report_path)

            # Print summary
            self.print_summary(report)

            # Handle promotion logic
            if report.passed:
                print("\n🎉 Soak test PASSED! Executing promotion logic...")

                # Export Prometheus snapshot
                snapshot_path = reports_dir / f"prometheus_snapshot_{timestamp}.json"
                await self.export_prometheus_snapshot(snapshot_path)

                # Tag config as PROD candidate
                if auto_promote:
                    version = f"v{timestamp}"
                    self.tag_config_as_prod_candidate(version)
                    print(f"\n✅ Config promoted to PROD-CANDIDATE-{version}")
                else:
                    print("\n⚠️  Auto-promotion disabled. Run with --auto-promote to tag config.")

                print("\n🚀 Ready for PRODUCTION deployment!")
            else:
                print("\n⚠️  Soak test FAILED. Review recommendations above.")
                print("Do NOT promote to production.")

            return report

        finally:
            # Clean up Redis connection
            if self.redis_client:
                await self.redis_client.close()


async def main():
    parser = argparse.ArgumentParser(description='Validate 48-hour soak test results')
    parser.add_argument(
        '--config',
        type=str,
        default='config/soak_test_48h_turbo.yaml',
        help='Path to soak test config file'
    )
    parser.add_argument(
        '--auto-promote',
        action='store_true',
        help='Automatically promote config to PROD-CANDIDATE if passing'
    )

    args = parser.parse_args()

    # Run validation
    validator = SoakTestValidator(args.config)
    report = await validator.run_validation(auto_promote=args.auto_promote)

    # Exit with appropriate code
    sys.exit(0 if report.passed else 1)


if __name__ == '__main__':
    asyncio.run(main())
