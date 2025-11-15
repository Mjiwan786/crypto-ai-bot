#!/usr/bin/env python3
"""
Live Signal Publisher Soak Test
================================

Runs a 30-60 minute soak test of the live signal publisher to validate:
- Sustained throughput
- Memory stability (no leaks)
- Latency consistency
- Error rate
- Health monitoring
- Signal schema compliance

USAGE:
    # 30-minute soak test
    python scripts/run_live_publisher_soak_test.py --duration 30

    # 60-minute soak test with detailed report
    python scripts/run_live_publisher_soak_test.py \
      --duration 60 \
      --report soak_test_report.json

    # Custom configuration
    python scripts/run_live_publisher_soak_test.py \
      --duration 45 \
      --mode paper \
      --pairs "BTC/USD,ETH/USD" \
      --rate 5.0

"""

import argparse
import asyncio
import json
import logging
import os
import psutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import aiohttp
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# =============================================================================
# Soak Test Configuration
# =============================================================================


@dataclass
class SoakTestConfig:
    """Soak test configuration"""

    duration_minutes: int = 30
    mode: str = "paper"
    trading_pairs: str = "BTC/USD,ETH/USD,SOL/USD,MATIC/USD,LINK/USD"
    max_signals_per_second: float = 5.0
    health_port: int = 8080
    validation_interval_sec: int = 60
    memory_check_interval_sec: int = 30
    report_file: Optional[Path] = None


# =============================================================================
# Soak Test Results
# =============================================================================


@dataclass
class SoakTestResult:
    """Soak test results and metrics"""

    start_time: float = field(default_factory=time.time)
    end_time: float = 0
    duration_minutes: int = 0

    # Publisher metrics
    total_signals_published: int = 0
    total_errors: int = 0
    signals_per_second_avg: float = 0

    # Latency metrics
    latency_p50_ms: List[float] = field(default_factory=list)
    latency_p95_ms: List[float] = field(default_factory=list)
    latency_p99_ms: List[float] = field(default_factory=list)

    # Memory metrics
    memory_rss_mb: List[float] = field(default_factory=list)
    memory_peak_mb: float = 0

    # Health checks
    health_checks_total: int = 0
    health_checks_healthy: int = 0
    health_checks_degraded: int = 0
    health_checks_failed: int = 0

    # Validation results
    validation_runs: int = 0
    total_signals_validated: int = 0
    valid_signals: int = 0
    invalid_signals: int = 0
    schema_errors: List[Dict] = field(default_factory=list)

    # SLO compliance
    slo_latency_violations: int = 0  # p95 >500ms
    slo_error_rate_violations: int = 0  # >0.1%

    def record_health_check(self, status: str) -> None:
        """Record health check result"""
        self.health_checks_total += 1

        if status == "healthy":
            self.health_checks_healthy += 1
        elif status == "degraded":
            self.health_checks_degraded += 1
        else:
            self.health_checks_failed += 1

    def record_memory(self, rss_mb: float) -> None:
        """Record memory usage"""
        self.memory_rss_mb.append(rss_mb)
        self.memory_peak_mb = max(self.memory_peak_mb, rss_mb)

    def record_latency(self, p50: float, p95: float, p99: float) -> None:
        """Record latency metrics"""
        self.latency_p50_ms.append(p50)
        self.latency_p95_ms.append(p95)
        self.latency_p99_ms.append(p99)

        # Check SLO violation (p95 <500ms)
        if p95 >= 500:
            self.slo_latency_violations += 1

    def finalize(self) -> None:
        """Finalize test results"""
        self.end_time = time.time()
        elapsed_sec = self.end_time - self.start_time

        if elapsed_sec > 0:
            self.signals_per_second_avg = self.total_signals_published / elapsed_sec

        # Check error rate SLO (<0.1%)
        if self.total_signals_published > 0:
            error_rate = self.total_errors / self.total_signals_published
            if error_rate > 0.001:  # 0.1%
                self.slo_error_rate_violations += 1

    def print_summary(self) -> None:
        """Print soak test summary"""
        print("\n" + "=" * 80)
        print(" " * 25 + "SOAK TEST SUMMARY")
        print("=" * 80)

        # Duration
        print(f"\n📅 Test Duration: {self.duration_minutes} minutes")
        print(f"   Start: {datetime.fromtimestamp(self.start_time).strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"   End:   {datetime.fromtimestamp(self.end_time).strftime('%Y-%m-%d %H:%M:%S')}")

        # Signal publication
        print(f"\n📊 Signal Publication:")
        print(f"   Total Published: {self.total_signals_published}")
        print(f"   Total Errors: {self.total_errors}")
        print(f"   Average Rate: {self.signals_per_second_avg:.2f} signals/sec")

        error_rate = 0
        if self.total_signals_published > 0:
            error_rate = (self.total_errors / self.total_signals_published) * 100

        print(f"   Error Rate: {error_rate:.3f}%")

        # Latency
        if self.latency_p95_ms:
            avg_p50 = sum(self.latency_p50_ms) / len(self.latency_p50_ms)
            avg_p95 = sum(self.latency_p95_ms) / len(self.latency_p95_ms)
            avg_p99 = sum(self.latency_p99_ms) / len(self.latency_p99_ms)
            max_p95 = max(self.latency_p95_ms)

            print(f"\n⏱️  Latency (Average):")
            print(f"   p50: {avg_p50:.2f}ms")
            print(f"   p95: {avg_p95:.2f}ms")
            print(f"   p99: {avg_p99:.2f}ms")
            print(f"   Peak p95: {max_p95:.2f}ms")

        # Memory
        if self.memory_rss_mb:
            avg_memory = sum(self.memory_rss_mb) / len(self.memory_rss_mb)
            min_memory = min(self.memory_rss_mb)

            print(f"\n💾 Memory Usage:")
            print(f"   Average: {avg_memory:.1f} MB")
            print(f"   Peak: {self.memory_peak_mb:.1f} MB")
            print(f"   Minimum: {min_memory:.1f} MB")
            print(f"   Growth: {self.memory_peak_mb - min_memory:.1f} MB")

        # Health checks
        print(f"\n❤️  Health Checks:")
        print(f"   Total: {self.health_checks_total}")
        print(f"   ✓ Healthy: {self.health_checks_healthy}")
        print(f"   ⚠ Degraded: {self.health_checks_degraded}")
        print(f"   ✗ Failed: {self.health_checks_failed}")

        health_uptime = 0
        if self.health_checks_total > 0:
            health_uptime = (self.health_checks_healthy / self.health_checks_total) * 100

        print(f"   Uptime: {health_uptime:.2f}%")

        # Validation
        if self.validation_runs > 0:
            print(f"\n✅ Signal Validation:")
            print(f"   Validation Runs: {self.validation_runs}")
            print(f"   Signals Validated: {self.total_signals_validated}")
            print(f"   Valid: {self.valid_signals}")
            print(f"   Invalid: {self.invalid_signals}")

            if self.total_signals_validated > 0:
                valid_pct = (self.valid_signals / self.total_signals_validated) * 100
                print(f"   Validation Pass Rate: {valid_pct:.2f}%")

        # SLO compliance
        print(f"\n🎯 SLO Compliance:")

        # Latency SLO
        if self.latency_p95_ms:
            latency_slo_pct = (
                ((len(self.latency_p95_ms) - self.slo_latency_violations) / len(self.latency_p95_ms))
                * 100
            )
            print(f"   Latency (p95 <500ms): {latency_slo_pct:.1f}% compliance")

            if self.slo_latency_violations > 0:
                print(f"     ⚠ {self.slo_latency_violations} violations")

        # Error rate SLO
        error_rate_slo = "PASS" if self.slo_error_rate_violations == 0 else "FAIL"
        print(f"   Error Rate (<0.1%): {error_rate_slo}")

        # Uptime SLO
        uptime_slo = "PASS" if health_uptime >= 99.9 else "FAIL"
        print(f"   Uptime (>99.9%): {uptime_slo} ({health_uptime:.2f}%)")

        # Overall pass/fail
        print(f"\n{'=' * 80}")

        all_slos_passed = (
            self.slo_latency_violations == 0
            and self.slo_error_rate_violations == 0
            and health_uptime >= 99.9
        )

        if all_slos_passed:
            print(" " * 30 + "✅ SOAK TEST PASSED")
        else:
            print(" " * 30 + "❌ SOAK TEST FAILED")

        print("=" * 80 + "\n")

    def to_dict(self) -> Dict:
        """Convert to dictionary for export"""
        return {
            "test_metadata": {
                "start_time": datetime.fromtimestamp(self.start_time).isoformat(),
                "end_time": datetime.fromtimestamp(self.end_time).isoformat(),
                "duration_minutes": self.duration_minutes,
            },
            "signals": {
                "total_published": self.total_signals_published,
                "total_errors": self.total_errors,
                "average_rate": round(self.signals_per_second_avg, 2),
                "error_rate_pct": round(
                    (self.total_errors / self.total_signals_published * 100)
                    if self.total_signals_published > 0
                    else 0,
                    3,
                ),
            },
            "latency": {
                "p50_avg": round(sum(self.latency_p50_ms) / len(self.latency_p50_ms), 2)
                if self.latency_p50_ms
                else 0,
                "p95_avg": round(sum(self.latency_p95_ms) / len(self.latency_p95_ms), 2)
                if self.latency_p95_ms
                else 0,
                "p99_avg": round(sum(self.latency_p99_ms) / len(self.latency_p99_ms), 2)
                if self.latency_p99_ms
                else 0,
                "p95_max": round(max(self.latency_p95_ms), 2) if self.latency_p95_ms else 0,
                "samples": self.latency_p95_ms,
            },
            "memory": {
                "average_mb": round(sum(self.memory_rss_mb) / len(self.memory_rss_mb), 1)
                if self.memory_rss_mb
                else 0,
                "peak_mb": round(self.memory_peak_mb, 1),
                "growth_mb": round(
                    self.memory_peak_mb - min(self.memory_rss_mb), 1
                )
                if self.memory_rss_mb
                else 0,
                "samples": self.memory_rss_mb,
            },
            "health": {
                "total_checks": self.health_checks_total,
                "healthy": self.health_checks_healthy,
                "degraded": self.health_checks_degraded,
                "failed": self.health_checks_failed,
                "uptime_pct": round(
                    (self.health_checks_healthy / self.health_checks_total * 100)
                    if self.health_checks_total > 0
                    else 0,
                    2,
                ),
            },
            "validation": {
                "runs": self.validation_runs,
                "total_validated": self.total_signals_validated,
                "valid": self.valid_signals,
                "invalid": self.invalid_signals,
                "pass_rate_pct": round(
                    (self.valid_signals / self.total_signals_validated * 100)
                    if self.total_signals_validated > 0
                    else 0,
                    2,
                ),
                "schema_errors": self.schema_errors,
            },
            "slo_compliance": {
                "latency_violations": self.slo_latency_violations,
                "error_rate_violations": self.slo_error_rate_violations,
                "latency_compliance_pct": round(
                    (
                        (len(self.latency_p95_ms) - self.slo_latency_violations)
                        / len(self.latency_p95_ms)
                        * 100
                    )
                    if self.latency_p95_ms
                    else 0,
                    1,
                ),
            },
        }


# =============================================================================
# Soak Test Runner
# =============================================================================


class SoakTestRunner:
    """Runs soak test for live signal publisher"""

    def __init__(self, config: SoakTestConfig):
        self.config = config
        self.result = SoakTestResult(duration_minutes=config.duration_minutes)
        self.publisher_process: Optional[subprocess.Popen] = None
        self.publisher_pid: Optional[int] = None
        self._shutdown_requested = False

    async def start_publisher(self) -> None:
        """Start the live signal publisher process"""
        logger.info("Starting live signal publisher...")

        # Build command
        cmd = [
            sys.executable,
            str(project_root / "live_signal_publisher.py"),
            "--mode", self.config.mode,
            "--pairs", self.config.trading_pairs,
            "--rate", str(self.config.max_signals_per_second),
            "--health-port", str(self.config.health_port),
        ]

        # Start process
        self.publisher_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        self.publisher_pid = self.publisher_process.pid

        logger.info(f"Publisher started with PID: {self.publisher_pid}")

        # Wait for publisher to start (check health)
        for i in range(30):  # 30 second timeout
            await asyncio.sleep(1)

            try:
                async with aiohttp.ClientSession() as session:
                    url = f"http://localhost:{self.config.health_port}/health"
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=2)) as resp:
                        if resp.status in [200, 503]:  # Either healthy or degraded is OK
                            logger.info("✓ Publisher is responding to health checks")
                            return
            except Exception:
                pass

        raise RuntimeError("Publisher failed to start within 30 seconds")

    async def stop_publisher(self) -> None:
        """Stop the publisher process"""
        if self.publisher_process:
            logger.info("Stopping publisher...")

            self.publisher_process.terminate()

            try:
                self.publisher_process.wait(timeout=10)
                logger.info("✓ Publisher stopped gracefully")
            except subprocess.TimeoutExpired:
                logger.warning("Publisher didn't stop gracefully, forcing kill")
                self.publisher_process.kill()
                self.publisher_process.wait()

    async def check_health(self) -> Dict:
        """Check publisher health"""
        try:
            async with aiohttp.ClientSession() as session:
                url = f"http://localhost:{self.config.health_port}/health"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    data = await resp.json()

                    # Record health check
                    status = data.get("status", "unknown")
                    self.result.record_health_check(status)

                    # Extract metrics
                    metrics = data.get("metrics", {})
                    self.result.total_signals_published = metrics.get("total_published", 0)
                    self.result.total_errors = metrics.get("total_errors", 0)

                    # Extract latency
                    latency = metrics.get("latency_ms", {})
                    gen_latency = latency.get("signal_generation", {})
                    redis_latency = latency.get("redis_publish", {})

                    # Use max of generation + redis latency for total
                    total_p50 = gen_latency.get("p50", 0) + redis_latency.get("p50", 0)
                    total_p95 = gen_latency.get("p95", 0) + redis_latency.get("p95", 0)
                    total_p99 = gen_latency.get("p99", 0) + redis_latency.get("p99", 0)

                    self.result.record_latency(total_p50, total_p95, total_p99)

                    return data

        except Exception as e:
            logger.error(f"Health check failed: {e}")
            self.result.record_health_check("failed")
            return {"status": "failed", "error": str(e)}

    async def check_memory(self) -> None:
        """Check publisher memory usage"""
        if not self.publisher_pid:
            return

        try:
            process = psutil.Process(self.publisher_pid)
            mem_info = process.memory_info()
            rss_mb = mem_info.rss / 1024 / 1024

            self.result.record_memory(rss_mb)

        except psutil.NoSuchProcess:
            logger.error("Publisher process not found")
        except Exception as e:
            logger.error(f"Memory check failed: {e}")

    async def validate_signals(self) -> None:
        """Run signal validation"""
        logger.info("Running signal validation...")

        try:
            # Import validator
            sys.path.insert(0, str(project_root / "scripts"))
            from validate_live_signals import LiveSignalValidator

            # Create validator
            validator = LiveSignalValidator(
                mode=self.config.mode,
                pairs=self.config.trading_pairs.split(","),
            )

            # Validate last 50 signals from each stream
            validation_result = await validator.validate_all(count=50)

            # Record results
            self.result.validation_runs += 1
            self.result.total_signals_validated += validation_result.total_signals
            self.result.valid_signals += validation_result.valid_signals
            self.result.invalid_signals += validation_result.invalid_signals
            self.result.schema_errors.extend(validation_result.schema_errors)

            logger.info(
                f"Validation complete: {validation_result.valid_signals}/{validation_result.total_signals} valid"
            )

        except Exception as e:
            logger.error(f"Validation failed: {e}", exc_info=True)

    async def run(self) -> SoakTestResult:
        """Run the soak test"""
        logger.info(f"Starting {self.config.duration_minutes}-minute soak test")

        # Start publisher
        await self.start_publisher()

        # Calculate intervals
        test_duration_sec = self.config.duration_minutes * 60
        health_check_interval = 10  # Check health every 10s

        # Calculate how many iterations
        total_iterations = test_duration_sec // health_check_interval

        try:
            for i in range(total_iterations):
                if self._shutdown_requested:
                    break

                # Calculate progress
                elapsed_sec = i * health_check_interval
                progress_pct = (elapsed_sec / test_duration_sec) * 100

                logger.info(
                    f"[{elapsed_sec//60}m {elapsed_sec%60}s / {self.config.duration_minutes}m] "
                    f"Progress: {progress_pct:.1f}%"
                )

                # Health check
                await self.check_health()

                # Memory check (every 30s)
                if i % (self.config.memory_check_interval_sec // health_check_interval) == 0:
                    await self.check_memory()

                # Validation (every 60s)
                if i % (self.config.validation_interval_sec // health_check_interval) == 0:
                    await self.validate_signals()

                # Wait for next iteration
                await asyncio.sleep(health_check_interval)

            # Final validation
            await self.validate_signals()

        except KeyboardInterrupt:
            logger.info("Soak test interrupted by user")
        finally:
            # Stop publisher
            await self.stop_publisher()

        # Finalize results
        self.result.finalize()

        return self.result


# =============================================================================
# CLI Interface
# =============================================================================


def parse_args():
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(
        description="Run soak test for live signal publisher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--duration",
        type=int,
        default=30,
        help="Test duration in minutes (default: 30)",
    )

    parser.add_argument(
        "--mode",
        choices=["paper", "live"],
        default="paper",
        help="Trading mode (default: paper)",
    )

    parser.add_argument(
        "--pairs",
        default="BTC/USD,ETH/USD,SOL/USD,MATIC/USD,LINK/USD",
        help="Comma-separated trading pairs",
    )

    parser.add_argument(
        "--rate",
        type=float,
        default=5.0,
        help="Max signals per second (default: 5.0)",
    )

    parser.add_argument(
        "--report",
        type=Path,
        help="Export report to JSON file",
    )

    parser.add_argument(
        "--env-file",
        type=Path,
        default=project_root / ".env.paper",
        help="Environment file (default: .env.paper)",
    )

    return parser.parse_args()


async def main():
    """Main entry point"""
    args = parse_args()

    # Load environment
    if args.env_file.exists():
        load_dotenv(args.env_file)
        logger.info(f"Loaded environment from {args.env_file}")

    # Create config
    config = SoakTestConfig(
        duration_minutes=args.duration,
        mode=args.mode,
        trading_pairs=args.pairs,
        max_signals_per_second=args.rate,
        report_file=args.report,
    )

    # Run soak test
    runner = SoakTestRunner(config)
    result = await runner.run()

    # Print summary
    result.print_summary()

    # Export report
    if args.report:
        report_data = result.to_dict()
        args.report.write_text(json.dumps(report_data, indent=2))
        logger.info(f"\n✓ Soak test report exported to: {args.report}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\nSoak test stopped")
        sys.exit(0)
