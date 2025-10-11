"""
SLO Report Generator - Fixed Version

Generates one-shot SLO reports from Redis data for the last SLO_WINDOW_HOURS.
Reads from Redis streams and HLL counters populated by the monitoring system.

This is a standalone version that doesn't depend on the full config system.

Usage:
    python monitoring/slo_report_fixed.py --env .env.staging --out logs/
    python monitoring/slo_report_fixed.py --help

Outputs:
    - Markdown summary to stdout with PASS/FAIL badges
    - CSV file saved to logs/slo_report_<UTC_ISO>.csv with raw stats
"""

import argparse
import asyncio
import csv
import json
import logging
import os
import ssl
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from urllib.parse import urlparse

import redis

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# SLO Thresholds (Production Defaults)
P95_PUBLISH_LATENCY_MS = 500
MAX_STREAM_LAG_SEC = 1
UPTIME_TARGET = 0.995  # 99.5%
MAX_DUP_RATE = 0.001  # < 0.1%


@dataclass
class SLOReportData:
    """SLO report data structure"""
    window_hours: int
    total_signals: int
    unique_signals: int
    dup_rate: float
    p95_latency_ms: float
    stream_lag_p95_sec: float
    uptime_ratio: float
    breaches: List[str]
    warnings: List[str]
    timestamp: float
    environment: str


def get_effective_thresholds() -> Dict[str, Any]:
    """Get the effective SLO thresholds based on current environment."""
    # Check if staging environment
    is_staging_env = os.getenv("ENVIRONMENT", "").lower() in ["staging", "stage"]
    
    if is_staging_env:
        # Staging overrides - more lenient thresholds
        return {
            "p95_publish_latency_ms": P95_PUBLISH_LATENCY_MS * 2,  # 1000ms
            "max_stream_lag_sec": MAX_STREAM_LAG_SEC * 5,  # 5 seconds
            "uptime_target": 0.99,  # 99% (more lenient)
            "max_dup_rate": MAX_DUP_RATE * 2,  # 0.2%
        }
    else:
        return {
            "p95_publish_latency_ms": P95_PUBLISH_LATENCY_MS,
            "max_stream_lag_sec": MAX_STREAM_LAG_SEC,
            "uptime_target": UPTIME_TARGET,
            "max_dup_rate": MAX_DUP_RATE,
        }


def get_window_hours() -> int:
    """Get the SLO evaluation window in hours."""
    return int(os.getenv("SLO_WINDOW_HOURS", 72))


def is_staging() -> bool:
    """Determine if the system is running in staging environment."""
    return os.getenv("ENVIRONMENT", "").lower() in ["staging", "stage"]


class SLOReportGenerator:
    """
    Generates SLO reports from Redis data.
    """
    
    def __init__(self, redis_client: redis.Redis):
        """
        Initialize SLO report generator.
        
        Args:
            redis_client: Redis client instance
        """
        self.redis = redis_client
        self.logger = logger
        
    async def generate_report(self, window_hours: Optional[int] = None) -> SLOReportData:
        """
        Generate SLO report for the specified window.
        
        Args:
            window_hours: SLO window in hours (uses default if None)
            
        Returns:
            SLOReportData: Complete SLO report data
        """
        if window_hours is None:
            window_hours = get_window_hours()
        
        current_time = time.time()
        window_start = current_time - (window_hours * 3600)
        
        self.logger.info(f"Generating SLO report for last {window_hours} hours")
        self.logger.info(f"Window: {datetime.fromtimestamp(window_start, tz=timezone.utc).isoformat()} to {datetime.fromtimestamp(current_time, tz=timezone.utc).isoformat()}")
        
        # Collect all metrics
        total_signals, unique_signals = await self._collect_signal_metrics()
        dup_rate = self._calculate_duplicate_rate(total_signals, unique_signals)
        
        p95_latency_ms = await self._collect_latency_metrics(window_start)
        stream_lag_p95_sec = await self._collect_lag_metrics(window_start)
        uptime_ratio = await self._collect_uptime_metrics(window_start)
        
        # Evaluate SLOs
        breaches, warnings = self._evaluate_slos(
            p95_latency_ms, stream_lag_p95_sec, uptime_ratio, dup_rate
        )
        
        return SLOReportData(
            window_hours=window_hours,
            total_signals=total_signals,
            unique_signals=unique_signals,
            dup_rate=dup_rate,
            p95_latency_ms=p95_latency_ms,
            stream_lag_p95_sec=stream_lag_p95_sec,
            uptime_ratio=uptime_ratio,
            breaches=breaches,
            warnings=warnings,
            timestamp=current_time,
            environment="staging" if is_staging() else "production"
        )
    
    async def _collect_signal_metrics(self) -> Tuple[int, int]:
        """Collect total and unique signal counts from Redis."""
        try:
            # Get total signals count
            total_signals_raw = self.redis.get("slo:total_signals")
            if total_signals_raw is None:
                total_signals = 0
            else:
                total_signals = int(total_signals_raw.decode() if isinstance(total_signals_raw, bytes) else total_signals_raw)
            
            # Get unique signals count from HLL
            unique_signals_raw = self.redis.pfcount("slo:unique_signals")
            if unique_signals_raw is None:
                unique_signals = 0
            else:
                unique_signals = int(unique_signals_raw)
            
            self.logger.info(f"Signal metrics: {total_signals} total, {unique_signals} unique")
            return total_signals, unique_signals
            
        except Exception as e:
            self.logger.error(f"Failed to collect signal metrics: {e}")
            return 0, 0
    
    def _calculate_duplicate_rate(self, total_signals: int, unique_signals: int) -> float:
        """Calculate duplicate rate from total and unique signals."""
        if total_signals == 0:
            return 0.0
        
        dup_rate = 1.0 - (unique_signals / total_signals)
        return max(0.0, dup_rate)
    
    async def _collect_latency_metrics(self, window_start: float) -> float:
        """Collect P95 latency metrics from Redis stream."""
        try:
            # Read recent latency events
            events = self.redis.xrevrange("metrics:signals:e2e", count=1000)
            
            latencies = []
            for event_id, fields in events:
                try:
                    event_ts = int(fields.get(b"ts", b"0").decode()) / 1000.0
                    if event_ts < window_start:
                        break
                    
                    latency_ms = float(fields.get(b"ms", b"0").decode())
                    latencies.append(latency_ms)
                    
                except (ValueError, KeyError) as e:
                    self.logger.warning(f"Invalid latency event: {e}")
                    continue
            
            if not latencies:
                self.logger.warning("No latency data found in window")
                return 0.0
            
            # Calculate P95
            latencies.sort()
            p95_latency_ms = latencies[int(len(latencies) * 0.95)]
            
            self.logger.info(f"Latency metrics: {len(latencies)} samples, P95: {p95_latency_ms:.1f}ms")
            return p95_latency_ms
            
        except Exception as e:
            self.logger.error(f"Failed to collect latency metrics: {e}")
            return 0.0
    
    async def _collect_lag_metrics(self, window_start: float) -> float:
        """Collect P95 stream lag metrics from Redis stream."""
        try:
            # Read recent lag events
            events = self.redis.xrevrange("metrics:md:lag", count=1000)
            
            lag_values = []
            for event_id, fields in events:
                try:
                    event_ts = int(fields.get(b"ts", b"0").decode()) / 1000.0
                    if event_ts < window_start:
                        break
                    
                    lag_ms = float(fields.get(b"lag", b"0").decode())
                    lag_sec = lag_ms / 1000.0
                    lag_values.append(lag_sec)
                    
                except (ValueError, KeyError) as e:
                    self.logger.warning(f"Invalid lag event: {e}")
                    continue
            
            if not lag_values:
                self.logger.warning("No lag data found in window")
                return 0.0
            
            # Calculate P95
            lag_values.sort()
            p95_lag_sec = lag_values[int(len(lag_values) * 0.95)]
            
            self.logger.info(f"Lag metrics: {len(lag_values)} samples, P95: {p95_lag_sec:.1f}s")
            return p95_lag_sec
            
        except Exception as e:
            self.logger.error(f"Failed to collect lag metrics: {e}")
            return 0.0
    
    async def _collect_uptime_metrics(self, window_start: float) -> float:
        """Collect uptime ratio from bot:up key and historical data."""
        try:
            # Check current bot status
            uptime_data = self.redis.get("bot:up")
            current_time = time.time()
            
            if uptime_data is None:
                # Bot is down, check TTL to estimate recent uptime
                self.logger.warning("Bot appears to be down (no bot:up key)")
                return 0.0
            
            # Parse uptime data
            try:
                uptime_info = json.loads(uptime_data.decode() if isinstance(uptime_data, bytes) else uptime_data)
                start_time = int(uptime_info.get("start_time", current_time))
                
                # Calculate uptime ratio based on window
                window_duration = current_time - window_start
                uptime_duration = current_time - start_time
                
                # If bot started before window, use full window
                if start_time <= window_start:
                    uptime_ratio = 1.0
                else:
                    # Bot started during window
                    uptime_ratio = uptime_duration / window_duration
                
                # Cap at 1.0
                uptime_ratio = min(1.0, uptime_ratio)
                
                self.logger.info(f"Uptime metrics: {uptime_ratio:.3f} ({uptime_ratio:.1%})")
                return uptime_ratio
                
            except (json.JSONDecodeError, KeyError) as e:
                self.logger.warning(f"Invalid uptime data: {e}")
                return 0.0
            
        except Exception as e:
            self.logger.error(f"Failed to collect uptime metrics: {e}")
            return 0.0
    
    def _evaluate_slos(self, p95_latency_ms: float, stream_lag_p95_sec: float, 
                      uptime_ratio: float, dup_rate: float) -> Tuple[List[str], List[str]]:
        """Evaluate SLOs against thresholds and return breaches and warnings."""
        thresholds = get_effective_thresholds()
        breaches = []
        warnings = []
        
        # Check P95 latency
        latency_threshold = thresholds['p95_publish_latency_ms']
        if p95_latency_ms > latency_threshold:
            breaches.append(f"P95 latency {p95_latency_ms:.1f}ms > {latency_threshold}ms")
        elif p95_latency_ms > latency_threshold * 0.9:
            warnings.append(f"P95 latency {p95_latency_ms:.1f}ms approaching threshold")
        
        # Check stream lag
        lag_threshold = thresholds['max_stream_lag_sec']
        if stream_lag_p95_sec > lag_threshold:
            breaches.append(f"Stream lag P95 {stream_lag_p95_sec:.1f}s > {lag_threshold}s")
        elif stream_lag_p95_sec > lag_threshold * 0.9:
            warnings.append(f"Stream lag P95 {stream_lag_p95_sec:.1f}s approaching threshold")
        
        # Check uptime
        uptime_threshold = thresholds['uptime_target']
        if uptime_ratio < uptime_threshold:
            breaches.append(f"Uptime {uptime_ratio:.3f} < {uptime_threshold:.3f}")
        elif uptime_ratio < uptime_threshold * 1.1:
            warnings.append(f"Uptime {uptime_ratio:.3f} approaching threshold")
        
        # Check duplicate rate
        dup_threshold = thresholds['max_dup_rate']
        if dup_rate > dup_threshold:
            breaches.append(f"Duplicate rate {dup_rate:.4f} > {dup_threshold:.4f}")
        elif dup_rate > dup_threshold * 0.9:
            warnings.append(f"Duplicate rate {dup_rate:.4f} approaching threshold")
        
        return breaches, warnings
    
    def generate_markdown_report(self, data: SLOReportData) -> str:
        """Generate markdown report with PASS/FAIL badges."""
        # Determine overall status
        if len(data.breaches) == 0 and len(data.warnings) <= 1:
            overall_status = "PASS"
            status_badge = "![PASS](https://img.shields.io/badge/Status-PASS-brightgreen)"
        elif len(data.breaches) == 0:
            overall_status = "WARN"
            status_badge = "![WARN](https://img.shields.io/badge/Status-WARN-yellow)"
        else:
            overall_status = "FAIL"
            status_badge = "![FAIL](https://img.shields.io/badge/Status-FAIL-red)"
        
        # Format timestamp
        report_time = datetime.fromtimestamp(data.timestamp, tz=timezone.utc).isoformat()
        
        # Generate individual SLO status badges
        thresholds = get_effective_thresholds()
        
        latency_status = "PASS" if data.p95_latency_ms <= thresholds['p95_publish_latency_ms'] else "FAIL"
        lag_status = "PASS" if data.stream_lag_p95_sec <= thresholds['max_stream_lag_sec'] else "FAIL"
        uptime_status = "PASS" if data.uptime_ratio >= thresholds['uptime_target'] else "FAIL"
        dup_status = "PASS" if data.dup_rate <= thresholds['max_dup_rate'] else "FAIL"
        
        latency_badge = f"![{latency_status}](https://img.shields.io/badge/Latency-{latency_status}-{'brightgreen' if latency_status == 'PASS' else 'red'})"
        lag_badge = f"![{lag_status}](https://img.shields.io/badge/Lag-{lag_status}-{'brightgreen' if lag_status == 'PASS' else 'red'})"
        uptime_badge = f"![{uptime_status}](https://img.shields.io/badge/Uptime-{uptime_status}-{'brightgreen' if uptime_status == 'PASS' else 'red'})"
        dup_badge = f"![{dup_status}](https://img.shields.io/badge/Duplicates-{dup_status}-{'brightgreen' if dup_status == 'PASS' else 'red'})"
        
        # Build report
        report = f"""# SLO Report

{status_badge} **Overall Status: {overall_status}**

## Summary
- **Environment**: {data.environment.title()}
- **Window**: {data.window_hours} hours
- **Report Time**: {report_time}
- **Total Signals**: {data.total_signals:,}
- **Unique Signals**: {data.unique_signals:,}

## SLO Status

| Metric | Value | Threshold | Status |
|--------|-------|-----------|--------|
| P95 Latency | {data.p95_latency_ms:.1f}ms | {thresholds['p95_publish_latency_ms']}ms | {latency_badge} |
| Stream Lag P95 | {data.stream_lag_p95_sec:.1f}s | {thresholds['max_stream_lag_sec']}s | {lag_badge} |
| Uptime Ratio | {data.uptime_ratio:.3f} ({data.uptime_ratio:.1%}) | {thresholds['uptime_target']:.3f} ({thresholds['uptime_target']:.1%}) | {uptime_badge} |
| Duplicate Rate | {data.dup_rate:.4f} ({data.dup_rate:.2%}) | {thresholds['max_dup_rate']:.4f} ({thresholds['max_dup_rate']:.2%}) | {dup_badge} |

## Issues

"""
        
        if data.breaches:
            report += "### Breaches\n"
            for breach in data.breaches:
                report += f"- [FAIL] {breach}\n"
            report += "\n"
        
        if data.warnings:
            report += "### Warnings\n"
            for warning in data.warnings:
                report += f"- [WARN] {warning}\n"
            report += "\n"
        
        if not data.breaches and not data.warnings:
            report += "[PASS] No issues detected\n\n"
        
        report += f"""## Raw Data
- **Window Hours**: {data.window_hours}
- **Total Signals**: {data.total_signals}
- **Unique Signals**: {data.unique_signals}
- **Duplicate Rate**: {data.dup_rate:.6f}
- **P95 Latency (ms)**: {data.p95_latency_ms:.3f}
- **Stream Lag P95 (sec)**: {data.stream_lag_p95_sec:.3f}
- **Uptime Ratio**: {data.uptime_ratio:.6f}
- **Breaches**: {json.dumps(data.breaches)}
- **Warnings**: {json.dumps(data.warnings)}
- **Timestamp**: {data.timestamp}
- **Environment**: {data.environment}
"""
        
        return report
    
    def save_csv_report(self, data: SLOReportData, output_dir: str) -> str:
        """Save CSV report to specified directory."""
        try:
            # Ensure output directory exists
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)
            
            # Generate filename with UTC timestamp
            timestamp = datetime.fromtimestamp(data.timestamp, tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
            filename = f"slo_report_{timestamp}.csv"
            filepath = output_path / filename
            
            # Write CSV
            with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                
                # Write header
                writer.writerow([
                    'window_hours', 'total_signals', 'unique_signals', 'dup_rate',
                    'p95_latency_ms', 'stream_lag_p95_sec', 'uptime_ratio',
                    'breaches', 'warnings', 'timestamp', 'environment'
                ])
                
                # Write data
                writer.writerow([
                    data.window_hours,
                    data.total_signals,
                    data.unique_signals,
                    data.dup_rate,
                    data.p95_latency_ms,
                    data.stream_lag_p95_sec,
                    data.uptime_ratio,
                    json.dumps(data.breaches),
                    json.dumps(data.warnings),
                    data.timestamp,
                    data.environment
                ])
            
            self.logger.info(f"CSV report saved to: {filepath}")
            return str(filepath)
            
        except Exception as e:
            self.logger.error(f"Failed to save CSV report: {e}")
            raise


def create_redis_client(redis_url: str) -> redis.Redis:
    """
    Create Redis client with proper SSL support for Redis Cloud.
    
    Args:
        redis_url: Redis connection URL
        
    Returns:
        redis.Redis: Configured Redis client
    """
    try:
        if "redis-cloud.com" in redis_url:
            # Parse Redis Cloud URL for proper connection
            parsed = urlparse(redis_url)
            
            redis_kwargs = {
                "host": parsed.hostname,
                "port": parsed.port or 6379,
                "username": parsed.username or "default",
                "password": parsed.password,
                "ssl": True,
                "ssl_cert_reqs": ssl.CERT_REQUIRED,
                "decode_responses": False,
                "socket_timeout": 30,
                "socket_connect_timeout": 30,
                "retry_on_timeout": True,
            }
            
            # Add CA cert if provided
            ca_cert = os.getenv("REDIS_CA_CERT")
            if ca_cert and os.path.exists(ca_cert):
                redis_kwargs["ssl_ca_certs"] = ca_cert
            
            redis_client = redis.Redis(**redis_kwargs)
        else:
            # Standard Redis connection - convert to rediss if SSL needed
            if redis_url.startswith("redis://") and "redis-cloud.com" in redis_url:
                redis_url = redis_url.replace("redis://", "rediss://", 1)
            redis_client = redis.from_url(redis_url, ssl_cert_reqs=ssl.CERT_REQUIRED)
        
        # Test connection
        redis_client.ping()
        safe_url = redis_url.split("@")[-1] if "@" in redis_url else redis_url
        logger.info(f"Connected to Redis: {safe_url}")
        return redis_client
        
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        raise


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Generate SLO Report")
    parser.add_argument("--env", help="Environment file path")
    parser.add_argument("--out", default="logs", help="Output directory for CSV report")
    parser.add_argument("--redis-url", help="Redis URL")
    parser.add_argument("--window-hours", type=int, help="SLO window in hours (overrides SLO_WINDOW_HOURS env var)")
    parser.add_argument("--no-csv", action="store_true", help="Skip CSV output")
    parser.add_argument("--no-markdown", action="store_true", help="Skip markdown output")
    
    args = parser.parse_args()
    
    # Load environment variables
    if args.env:
        from dotenv import load_dotenv
        load_dotenv(args.env)
    
    # Override window hours if provided
    if args.window_hours:
        os.environ["SLO_WINDOW_HOURS"] = str(args.window_hours)
    
    # Get Redis URL
    redis_url = args.redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
    
    try:
        # Create Redis client
        redis_client = create_redis_client(redis_url)
        
        # Create report generator
        generator = SLOReportGenerator(redis_client)
        
        # Generate report
        report_data = await generator.generate_report()
        
        # Output markdown report
        if not args.no_markdown:
            markdown_report = generator.generate_markdown_report(report_data)
            print(markdown_report)
        
        # Save CSV report
        if not args.no_csv:
            csv_path = generator.save_csv_report(report_data, args.out)
            print(f"\nCSV report saved to: {csv_path}")
        
        # Exit with appropriate code
        if report_data.breaches:
            sys.exit(1)  # Fail if there are breaches
        elif report_data.warnings:
            sys.exit(2)  # Warning if there are warnings
        else:
            sys.exit(0)  # Success
            
    except Exception as e:
        logger.error(f"Failed to generate SLO report: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
