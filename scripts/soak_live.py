#!/usr/bin/env python3
"""
Soak Test for Live Scalper
===========================

Runs live scalper for 30-60 minutes and tracks:
- Signals published per minute
- Average event_age_ms and ingest_lag_ms
- Wins/losses (paper trading P&L)
- Safety rail breaker trips
- Market activity and signal staleness

Exits non-zero if:
- avg event_age_ms > 2000ms
- breaker trips/min > threshold
- No signals for 10+ minutes when market active

Output: logs/soak_report.md
"""

import asyncio
import logging
import sys
import time
import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
import json

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agents.infrastructure.redis_client import RedisCloudClient, RedisCloudConfig
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class SoakMetrics:
    """Container for soak test metrics"""

    # Time tracking
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    duration_minutes: float = 0.0

    # Signal metrics
    total_signals: int = 0
    signals_per_minute: List[float] = field(default_factory=list)
    avg_signals_per_minute: float = 0.0

    # Freshness metrics
    event_ages_ms: List[int] = field(default_factory=list)
    ingest_lags_ms: List[int] = field(default_factory=list)
    avg_event_age_ms: float = 0.0
    avg_ingest_lag_ms: float = 0.0
    max_event_age_ms: int = 0
    max_ingest_lag_ms: int = 0

    # Clock drift
    clock_drift_warnings: int = 0

    # Queue metrics
    queue_depths: List[int] = field(default_factory=list)
    avg_queue_depth: float = 0.0
    max_queue_depth: int = 0
    signals_shed: int = 0

    # Market activity
    last_signal_time: Optional[float] = None
    max_signal_gap_seconds: float = 0.0
    signal_gaps_over_10min: int = 0

    # Paper trading P&L
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl_usd: float = 0.0
    win_rate_pct: float = 0.0

    # Safety rails
    breaker_trips: int = 0
    breaker_events: List[Dict] = field(default_factory=list)
    breaker_trips_per_minute: float = 0.0

    # Heartbeat tracking
    heartbeats_received: int = 0
    missed_heartbeats: int = 0
    last_heartbeat_time: Optional[float] = None

    # Failure conditions
    failures: List[str] = field(default_factory=list)

    def calculate_final_stats(self):
        """Calculate final statistics after test completes"""
        self.end_time = time.time()
        self.duration_minutes = (self.end_time - self.start_time) / 60.0

        # Average signals per minute
        if self.signals_per_minute:
            self.avg_signals_per_minute = sum(self.signals_per_minute) / len(self.signals_per_minute)

        # Freshness averages
        if self.event_ages_ms:
            self.avg_event_age_ms = sum(self.event_ages_ms) / len(self.event_ages_ms)
            self.max_event_age_ms = max(self.event_ages_ms)

        if self.ingest_lags_ms:
            self.avg_ingest_lag_ms = sum(self.ingest_lags_ms) / len(self.ingest_lags_ms)
            self.max_ingest_lag_ms = max(self.ingest_lags_ms)

        # Queue stats
        if self.queue_depths:
            self.avg_queue_depth = sum(self.queue_depths) / len(self.queue_depths)
            self.max_queue_depth = max(self.queue_depths)

        # Win rate
        if self.total_trades > 0:
            self.win_rate_pct = (self.winning_trades / self.total_trades) * 100.0

        # Breaker trips per minute
        if self.duration_minutes > 0:
            self.breaker_trips_per_minute = self.breaker_trips / self.duration_minutes

    def check_failure_conditions(self,
                                  max_event_age_ms: int = 2000,
                                  max_breaker_trips_per_min: float = 1.0,
                                  max_signal_gap_min: float = 10.0) -> bool:
        """
        Check if any failure conditions are met.

        Returns:
            True if test failed, False if passed
        """
        failed = False

        # Check average event age
        if self.avg_event_age_ms > max_event_age_ms:
            self.failures.append(
                f"FAIL: Average event age ({self.avg_event_age_ms:.1f}ms) exceeds "
                f"threshold ({max_event_age_ms}ms)"
            )
            failed = True

        # Check breaker trips rate
        if self.breaker_trips_per_minute > max_breaker_trips_per_min:
            self.failures.append(
                f"FAIL: Breaker trips per minute ({self.breaker_trips_per_minute:.2f}) "
                f"exceeds threshold ({max_breaker_trips_per_min})"
            )
            failed = True

        # Check signal gaps
        if self.signal_gaps_over_10min > 0:
            self.failures.append(
                f"FAIL: {self.signal_gaps_over_10min} signal gap(s) exceeding "
                f"{max_signal_gap_min} minutes detected"
            )
            failed = True

        return failed


class SoakTestMonitor:
    """Monitor for soak test metrics"""

    def __init__(self, redis_client: RedisCloudClient, duration_minutes: int = 30):
        self.redis = redis_client
        self.duration_minutes = duration_minutes
        self.metrics = SoakMetrics()
        self._running = False

        # Per-minute signal counters
        self.current_minute_signals = 0
        self.current_minute_start = time.time()

        # Stream keys to monitor
        self.pairs = ["BTC/USD", "ETH/USD", "SOL/USD", "LINK/USD"]
        self.timeframes = ["15s", "1m"]

        logger.info(f"SoakTestMonitor initialized (duration={duration_minutes}min)")

    async def start(self):
        """Start monitoring"""
        self._running = True
        self.metrics.start_time = time.time()

        logger.info(f"Starting soak test (duration={self.duration_minutes} minutes)")
        logger.info(f"Monitoring pairs: {self.pairs}")
        logger.info(f"Monitoring timeframes: {self.timeframes}")

        # Start monitoring tasks
        tasks = [
            asyncio.create_task(self._monitor_signals()),
            asyncio.create_task(self._monitor_heartbeats()),
            asyncio.create_task(self._monitor_risk_events()),
            asyncio.create_task(self._monitor_pnl()),
            asyncio.create_task(self._per_minute_counter()),
        ]

        # Wait for duration or until stopped
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=self.duration_minutes * 60,
            )
        except asyncio.TimeoutError:
            logger.info(f"Soak test duration ({self.duration_minutes}min) completed")
        finally:
            self._running = False

            # Cancel all tasks
            for task in tasks:
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

    async def _monitor_signals(self):
        """Monitor signal streams for freshness and volume"""
        logger.info("Signal monitor started")

        # Build list of signal streams to monitor
        signal_streams = []
        for pair in self.pairs:
            for tf in self.timeframes:
                stream_key = f"signals:paper:{pair.replace('/', '_')}:{tf}"
                signal_streams.append(stream_key)

        # Track last ID for each stream
        stream_positions = {stream: "0-0" for stream in signal_streams}

        while self._running:
            try:
                # Read new signals from all streams
                for stream_key in signal_streams:
                    try:
                        messages = await self.redis.xread(
                            {stream_key: stream_positions[stream_key]},
                            count=100,
                            block=100,  # 100ms timeout
                        )

                        if not messages:
                            continue

                        for stream, msgs in messages:
                            for msg_id, msg_data in msgs:
                                stream_positions[stream] = msg_id
                                await self._process_signal(msg_data)

                    except Exception as e:
                        logger.debug(f"Error reading {stream_key}: {e}")
                        continue

                await asyncio.sleep(0.1)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in signal monitor: {e}", exc_info=True)
                await asyncio.sleep(1)

    async def _process_signal(self, signal_data: Dict):
        """Process a signal message"""
        try:
            # Parse signal JSON
            signal_json = signal_data.get("signal", "{}")
            if isinstance(signal_json, bytes):
                signal_json = signal_json.decode("utf-8")

            signal = json.loads(signal_json)

            # Update counters
            self.metrics.total_signals += 1
            self.current_minute_signals += 1

            # Track signal timing
            now = time.time()
            if self.metrics.last_signal_time:
                gap_seconds = now - self.metrics.last_signal_time
                if gap_seconds > self.metrics.max_signal_gap_seconds:
                    self.metrics.max_signal_gap_seconds = gap_seconds

                # Check for 10+ minute gaps
                if gap_seconds > 600:  # 10 minutes
                    self.metrics.signal_gaps_over_10min += 1
                    logger.warning(f"Signal gap detected: {gap_seconds:.1f}s")

            self.metrics.last_signal_time = now

            # Extract freshness metrics if present
            ts_exchange = signal.get("ts_exchange")
            ts_server = signal.get("ts_server")

            if ts_exchange and ts_server:
                now_ms = int(time.time() * 1000)
                event_age_ms = now_ms - ts_exchange
                ingest_lag_ms = now_ms - ts_server

                self.metrics.event_ages_ms.append(event_age_ms)
                self.metrics.ingest_lags_ms.append(ingest_lag_ms)

                # Check for clock drift
                drift_ms = abs(ts_exchange - ts_server)
                if drift_ms > 2000:
                    self.metrics.clock_drift_warnings += 1
                    logger.warning(f"Clock drift detected: {drift_ms}ms")

        except Exception as e:
            logger.debug(f"Error processing signal: {e}")

    async def _monitor_heartbeats(self):
        """Monitor heartbeat stream"""
        logger.info("Heartbeat monitor started")

        last_id = "0-0"
        expected_interval_sec = 15.0

        while self._running:
            try:
                messages = await self.redis.xread(
                    {"metrics:scalper": last_id},
                    count=10,
                    block=1000,  # 1 second timeout
                )

                if not messages:
                    # Check for missed heartbeat
                    if self.metrics.last_heartbeat_time:
                        gap = time.time() - self.metrics.last_heartbeat_time
                        if gap > (expected_interval_sec * 2):
                            self.metrics.missed_heartbeats += 1
                            logger.warning(f"Missed heartbeat (gap={gap:.1f}s)")
                    continue

                for stream, msgs in messages:
                    for msg_id, msg_data in msgs:
                        last_id = msg_id

                        # Check if this is a heartbeat
                        if msg_data.get("kind") == "heartbeat":
                            await self._process_heartbeat(msg_data)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in heartbeat monitor: {e}", exc_info=True)
                await asyncio.sleep(1)

    async def _process_heartbeat(self, heartbeat_data: Dict):
        """Process a heartbeat message"""
        try:
            self.metrics.heartbeats_received += 1
            self.metrics.last_heartbeat_time = time.time()

            # Extract queue metrics
            queue_depth = int(heartbeat_data.get("queue_depth", 0))
            self.metrics.queue_depths.append(queue_depth)

            signals_shed = int(heartbeat_data.get("signals_shed", 0))
            if signals_shed > self.metrics.signals_shed:
                shed_count = signals_shed - self.metrics.signals_shed
                self.metrics.signals_shed = signals_shed
                logger.warning(f"Signals shed: {shed_count} (total={signals_shed})")

            logger.debug(
                f"Heartbeat: queue_depth={queue_depth}, "
                f"shed={signals_shed}"
            )

        except Exception as e:
            logger.debug(f"Error processing heartbeat: {e}")

    async def _monitor_risk_events(self):
        """Monitor risk event stream for breaker trips"""
        logger.info("Risk event monitor started")

        last_id = "0-0"

        while self._running:
            try:
                messages = await self.redis.xread(
                    {"risk:events": last_id},
                    count=10,
                    block=1000,
                )

                if not messages:
                    await asyncio.sleep(0.1)
                    continue

                for stream, msgs in messages:
                    for msg_id, msg_data in msgs:
                        last_id = msg_id
                        await self._process_risk_event(msg_data)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in risk monitor: {e}", exc_info=True)
                await asyncio.sleep(1)

    async def _process_risk_event(self, event_data: Dict):
        """Process a risk event (breaker trip)"""
        try:
            event_type = event_data.get("event_type", "")

            # Check if this is a breaker trip
            if "breaker" in event_type.lower() or "circuit" in event_type.lower():
                self.metrics.breaker_trips += 1
                self.metrics.breaker_events.append({
                    "time": time.time(),
                    "type": event_type,
                    "data": event_data,
                })
                logger.warning(f"Breaker trip detected: {event_type}")

        except Exception as e:
            logger.debug(f"Error processing risk event: {e}")

    async def _monitor_pnl(self):
        """Monitor P&L stream for paper trading results"""
        logger.info("P&L monitor started")

        last_id = "0-0"

        while self._running:
            try:
                messages = await self.redis.xread(
                    {"metrics:daily_pnl": last_id},
                    count=10,
                    block=1000,
                )

                if not messages:
                    await asyncio.sleep(0.1)
                    continue

                for stream, msgs in messages:
                    for msg_id, msg_data in msgs:
                        last_id = msg_id
                        await self._process_pnl(msg_data)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in P&L monitor: {e}", exc_info=True)
                await asyncio.sleep(1)

    async def _process_pnl(self, pnl_data: Dict):
        """Process P&L data"""
        try:
            # Extract P&L metrics
            total_trades = int(pnl_data.get("total_trades", 0))
            winning_trades = int(pnl_data.get("winning_trades", 0))
            losing_trades = int(pnl_data.get("losing_trades", 0))
            total_pnl = float(pnl_data.get("total_pnl_usd", 0.0))

            # Update metrics (only if new data)
            if total_trades > self.metrics.total_trades:
                self.metrics.total_trades = total_trades
                self.metrics.winning_trades = winning_trades
                self.metrics.losing_trades = losing_trades
                self.metrics.total_pnl_usd = total_pnl

                logger.info(
                    f"P&L update: {winning_trades}W/{losing_trades}L, "
                    f"PnL=${total_pnl:.2f}"
                )

        except Exception as e:
            logger.debug(f"Error processing P&L: {e}")

    async def _per_minute_counter(self):
        """Track signals per minute"""
        while self._running:
            try:
                await asyncio.sleep(60)  # Wait 1 minute

                # Record signals for this minute
                self.metrics.signals_per_minute.append(self.current_minute_signals)

                logger.info(
                    f"Signals this minute: {self.current_minute_signals}, "
                    f"Total: {self.metrics.total_signals}"
                )

                # Reset counter
                self.current_minute_signals = 0
                self.current_minute_start = time.time()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in per-minute counter: {e}")

    def generate_report(self, output_path: Path) -> str:
        """Generate markdown report"""
        logger.info(f"Generating report to {output_path}")

        # Calculate final stats
        self.metrics.calculate_final_stats()

        # Check failure conditions
        test_failed = self.metrics.check_failure_conditions()

        # Build report
        report_lines = []

        # Header
        report_lines.append("# Soak Test Report")
        report_lines.append("")
        report_lines.append(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report_lines.append(f"**Duration:** {self.metrics.duration_minutes:.1f} minutes")
        report_lines.append(f"**Status:** {'FAILED' if test_failed else 'PASSED'}")
        report_lines.append("")
        report_lines.append("---")
        report_lines.append("")

        # Test Summary
        report_lines.append("## Test Summary")
        report_lines.append("")
        if test_failed:
            report_lines.append("**RESULT: FAILED**")
            report_lines.append("")
            report_lines.append("### Failure Reasons:")
            for failure in self.metrics.failures:
                report_lines.append(f"- {failure}")
            report_lines.append("")
        else:
            report_lines.append("**RESULT: PASSED**")
            report_lines.append("")

        # Signal Metrics
        report_lines.append("## Signal Metrics")
        report_lines.append("")
        report_lines.append(f"- **Total Signals:** {self.metrics.total_signals}")
        report_lines.append(f"- **Average Signals/Min:** {self.metrics.avg_signals_per_minute:.2f}")
        report_lines.append(f"- **Max Signal Gap:** {self.metrics.max_signal_gap_seconds:.1f}s")
        report_lines.append(f"- **Signal Gaps >10min:** {self.metrics.signal_gaps_over_10min}")
        report_lines.append("")

        # Signals per minute chart
        if self.metrics.signals_per_minute:
            report_lines.append("### Signals Per Minute")
            report_lines.append("")
            report_lines.append("```")
            for i, count in enumerate(self.metrics.signals_per_minute, 1):
                bar = "#" * int(count / 2)  # Scale down for display
                report_lines.append(f"Min {i:2d}: {bar} ({count:.0f})")
            report_lines.append("```")
            report_lines.append("")

        # Freshness Metrics
        report_lines.append("## Freshness Metrics")
        report_lines.append("")
        report_lines.append(f"- **Avg Event Age:** {self.metrics.avg_event_age_ms:.1f}ms")
        report_lines.append(f"- **Max Event Age:** {self.metrics.max_event_age_ms}ms")
        report_lines.append(f"- **Avg Ingest Lag:** {self.metrics.avg_ingest_lag_ms:.1f}ms")
        report_lines.append(f"- **Max Ingest Lag:** {self.metrics.max_ingest_lag_ms}ms")
        report_lines.append(f"- **Clock Drift Warnings:** {self.metrics.clock_drift_warnings}")
        report_lines.append("")

        # Queue Metrics
        report_lines.append("## Queue Metrics")
        report_lines.append("")
        report_lines.append(f"- **Avg Queue Depth:** {self.metrics.avg_queue_depth:.1f}")
        report_lines.append(f"- **Max Queue Depth:** {self.metrics.max_queue_depth}")
        report_lines.append(f"- **Signals Shed:** {self.metrics.signals_shed}")
        report_lines.append("")

        # Paper Trading P&L
        report_lines.append("## Paper Trading P&L")
        report_lines.append("")
        report_lines.append(f"- **Total Trades:** {self.metrics.total_trades}")
        report_lines.append(f"- **Winning Trades:** {self.metrics.winning_trades}")
        report_lines.append(f"- **Losing Trades:** {self.metrics.losing_trades}")
        report_lines.append(f"- **Win Rate:** {self.metrics.win_rate_pct:.1f}%")
        report_lines.append(f"- **Total P&L:** ${self.metrics.total_pnl_usd:.2f}")
        report_lines.append("")

        # Safety Rails
        report_lines.append("## Safety Rails")
        report_lines.append("")
        report_lines.append(f"- **Breaker Trips:** {self.metrics.breaker_trips}")
        report_lines.append(f"- **Breaker Trips/Min:** {self.metrics.breaker_trips_per_minute:.3f}")
        report_lines.append("")

        if self.metrics.breaker_events:
            report_lines.append("### Breaker Events")
            report_lines.append("")
            for event in self.metrics.breaker_events:
                timestamp = datetime.fromtimestamp(event["time"]).strftime("%H:%M:%S")
                report_lines.append(f"- **{timestamp}:** {event['type']}")
            report_lines.append("")

        # Heartbeat Health
        report_lines.append("## Heartbeat Health")
        report_lines.append("")
        report_lines.append(f"- **Heartbeats Received:** {self.metrics.heartbeats_received}")
        report_lines.append(f"- **Missed Heartbeats:** {self.metrics.missed_heartbeats}")
        report_lines.append("")

        # Test Configuration
        report_lines.append("## Test Configuration")
        report_lines.append("")
        report_lines.append(f"- **Duration Target:** {self.duration_minutes} minutes")
        report_lines.append(f"- **Monitored Pairs:** {', '.join(self.pairs)}")
        report_lines.append(f"- **Monitored Timeframes:** {', '.join(self.timeframes)}")
        report_lines.append("")

        # Failure Thresholds
        report_lines.append("## Failure Thresholds")
        report_lines.append("")
        report_lines.append("- **Max Event Age:** 2000ms")
        report_lines.append("- **Max Breaker Trips/Min:** 1.0")
        report_lines.append("- **Max Signal Gap:** 10 minutes")
        report_lines.append("")

        # Footer
        report_lines.append("---")
        report_lines.append("")
        report_lines.append(f"**Generated:** {datetime.now().isoformat()}")
        report_lines.append("")

        # Write report
        report_content = "\n".join(report_lines)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report_content, encoding="utf-8")

        logger.info(f"Report written to {output_path}")

        return report_content


async def main():
    """Main entry point"""
    print("=" * 80)
    print("                    SOAK TEST - LIVE SCALPER")
    print("=" * 80)

    # Parse arguments
    duration_minutes = int(os.getenv("SOAK_DURATION_MINUTES", "30"))

    print(f"\nConfiguration:")
    print(f"  Duration: {duration_minutes} minutes")
    print(f"  Output: logs/soak_report.md")
    print("")

    # Load environment
    env_file = project_root / ".env.paper"
    if env_file.exists():
        load_dotenv(env_file)
        print(f"[OK] Loaded environment from: {env_file}")

    # Initialize Redis client
    redis_url = os.getenv("REDIS_URL")
    redis_ca_cert = os.getenv("REDIS_CA_CERT", "config/certs/redis_ca.pem")

    if not redis_url:
        print("\n[FAIL] REDIS_URL not set in environment")
        return 1

    print(f"[OK] Redis URL configured")

    # Connect to Redis
    print("\n[1/4] Connecting to Redis...")
    redis_config = RedisCloudConfig(
        url=redis_url,
        ca_cert_path=redis_ca_cert,
    )
    redis_client = RedisCloudClient(redis_config)

    try:
        await redis_client.connect()
        print("      [OK] Connected to Redis Cloud")
    except Exception as e:
        print(f"      [FAIL] Failed to connect to Redis: {e}")
        return 1

    # Initialize monitor
    print(f"\n[2/4] Initializing soak test monitor (duration={duration_minutes}min)...")
    monitor = SoakTestMonitor(redis_client, duration_minutes=duration_minutes)
    print("      [OK] Monitor initialized")

    # Start monitoring
    print(f"\n[3/4] Starting soak test...")
    print(f"      Monitoring for {duration_minutes} minutes...")
    print(f"      Press Ctrl+C to stop early")
    print("")

    try:
        await monitor.start()
    except KeyboardInterrupt:
        print("\n\n[STOPPED] Soak test interrupted by user")
    except Exception as e:
        logger.error(f"Soak test error: {e}", exc_info=True)
        return 1
    finally:
        await redis_client.aclose()

    # Generate report
    print(f"\n[4/4] Generating report...")
    output_path = project_root / "logs" / "soak_report.md"

    try:
        report = monitor.generate_report(output_path)
        print(f"      [OK] Report written to {output_path}")
    except Exception as e:
        logger.error(f"Failed to generate report: {e}", exc_info=True)
        return 1

    # Print summary
    print("\n" + "=" * 80)
    print("                    SOAK TEST SUMMARY")
    print("=" * 80)

    monitor.metrics.calculate_final_stats()
    test_failed = monitor.metrics.check_failure_conditions()

    print(f"\nDuration: {monitor.metrics.duration_minutes:.1f} minutes")
    print(f"Signals: {monitor.metrics.total_signals} ({monitor.metrics.avg_signals_per_minute:.1f}/min)")
    print(f"Avg Event Age: {monitor.metrics.avg_event_age_ms:.1f}ms")
    print(f"Avg Ingest Lag: {monitor.metrics.avg_ingest_lag_ms:.1f}ms")
    print(f"Breaker Trips: {monitor.metrics.breaker_trips} ({monitor.metrics.breaker_trips_per_minute:.3f}/min)")
    print(f"Signal Gaps >10min: {monitor.metrics.signal_gaps_over_10min}")
    print(f"P&L: ${monitor.metrics.total_pnl_usd:.2f} ({monitor.metrics.win_rate_pct:.1f}% win rate)")

    if test_failed:
        print(f"\nStatus: FAILED")
        print("\nFailure reasons:")
        for failure in monitor.metrics.failures:
            print(f"  - {failure}")
        print("\n" + "=" * 80)
        return 1
    else:
        print(f"\nStatus: PASSED")
        print("\n" + "=" * 80)
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
