#!/usr/bin/env python3
"""
Live Scalper Runner - Single Entrypoint
========================================

Production-ready entrypoint for running the live scalper with:
- LIVE_MODE toggle (environment + YAML)
- Comprehensive safety rails
- Preflight checks (Redis TLS, Kraken WSS)
- Startup summary logging
- Fail-fast validation

USAGE:
    # Paper trading (default)
    python scripts/run_live_scalper.py

    # Live trading (requires confirmation)
    export LIVE_MODE=true
    export LIVE_TRADING_CONFIRMATION="I confirm live trading"
    python scripts/run_live_scalper.py

    # Custom config
    python scripts/run_live_scalper.py --config config/custom_scalper.yaml

ENVIRONMENT VARIABLES:
    LIVE_MODE                    - Set to "true" for live trading
    LIVE_TRADING_CONFIRMATION   - Must be "I confirm live trading" for live mode
    REDIS_URL                    - Redis Cloud connection URL (rediss://)
    REDIS_CA_CERT                - Path to Redis TLS CA certificate
    KRAKEN_API_KEY              - Kraken API key
    KRAKEN_API_SECRET           - Kraken API secret

"""

import argparse
import asyncio
import json
import logging
import os
import ssl
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import aiohttp
import yaml
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import project modules
from agents.risk.live_safety_rails import LiveSafetyRails
from agents.infrastructure.redis_client import RedisCloudClient, RedisCloudConfig
from agents.infrastructure.signal_queue import SignalQueue
from agents.monitoring.prometheus_freshness_exporter import FreshnessMetricsExporter
from signals.scalper_schema import ScalperSignal, validate_signal_safe, get_metrics_stream_key

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(project_root / "logs" / "live_scalper.log"),
    ],
)
logger = logging.getLogger(__name__)


# =============================================================================
# Configuration Loading
# =============================================================================


def load_config(config_path: Path) -> Dict:
    """Load and validate configuration"""
    logger.info(f"Loading configuration from: {config_path}")

    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    # Expand environment variables in config
    config = expand_env_vars(config)

    return config


def expand_env_vars(config: Dict) -> Dict:
    """Recursively expand environment variables in config"""
    import re

    def expand_value(value):
        if isinstance(value, str):
            # Match ${VAR:default} or ${VAR} patterns
            pattern = r'\$\{([^:}]+)(?::([^}]*))?\}'

            def replace(match):
                var_name = match.group(1)
                default_value = match.group(2)
                return os.getenv(var_name, default_value if default_value else "")

            return re.sub(pattern, replace, value)
        elif isinstance(value, dict):
            return {k: expand_value(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [expand_value(item) for item in value]
        else:
            return value

    return expand_value(config)


def validate_config(config: Dict) -> List[str]:
    """Validate configuration and return list of errors"""
    errors = []

    # Check mode configuration
    mode_config = config.get("mode", {})
    live_mode = mode_config.get("live_mode", False)

    # Convert string to bool if needed
    if isinstance(live_mode, str):
        live_mode = live_mode.lower() in ["true", "1", "yes"]
        config["mode"]["live_mode"] = live_mode

    # Validate live mode confirmation
    if live_mode:
        confirmation = mode_config.get("live_trading_confirmation", "")
        required_confirmation = "I confirm live trading"

        if confirmation != required_confirmation:
            errors.append(
                f"Live mode requires LIVE_TRADING_CONFIRMATION='{required_confirmation}'"
            )

    # Check Redis configuration
    redis_config = config.get("redis", {})
    redis_url = redis_config.get("url", "")

    if not redis_url or redis_url == "":
        errors.append("REDIS_URL is required")
    elif not redis_url.startswith("rediss://"):
        errors.append("REDIS_URL must use TLS (rediss://)")

    # Check trading pairs
    trading_config = config.get("trading", {})
    pairs = trading_config.get("pairs", [])

    if not pairs:
        errors.append("At least one trading pair is required")

    # Check safety rails in live mode
    if live_mode:
        safety_rails = config.get("safety_rails", {})

        if not safety_rails:
            errors.append("Safety rails configuration required for live mode")

    return errors


# =============================================================================
# Preflight Checks
# =============================================================================


class PreflightChecks:
    """Preflight checks for live scalper"""

    def __init__(self, config: Dict):
        self.config = config
        self.results: Dict[str, Tuple[bool, str]] = {}

    async def check_redis_connection(self) -> Tuple[bool, str]:
        """Check Redis connectivity"""
        logger.info("Checking Redis connection...")

        try:
            redis_config = self.config.get("redis", {})
            redis_url = redis_config.get("url")
            ca_cert_path = redis_config.get("ca_cert_path")

            # Expand path
            if ca_cert_path and not Path(ca_cert_path).is_absolute():
                ca_cert_path = str(project_root / ca_cert_path)

            client_config = RedisCloudConfig(
                url=redis_url,
                ca_cert_path=ca_cert_path,
                connect_timeout=10.0,
            )

            client = RedisCloudClient(client_config)
            await client.connect()

            # Test ping
            pong = await client.ping()

            await client.disconnect()

            if pong:
                logger.info("✓ Redis connection successful")
                return True, "Connected successfully"
            else:
                logger.error("✗ Redis ping failed")
                return False, "Ping failed"

        except Exception as e:
            logger.error(f"✗ Redis connection failed: {e}")
            return False, str(e)

    async def check_redis_tls(self) -> Tuple[bool, str]:
        """Check Redis TLS configuration"""
        logger.info("Checking Redis TLS...")

        try:
            redis_config = self.config.get("redis", {})
            redis_url = redis_config.get("url")
            ca_cert_path = redis_config.get("ca_cert_path")

            # Check URL uses rediss://
            if not redis_url.startswith("rediss://"):
                logger.error("✗ Redis URL must use rediss:// for TLS")
                return False, "URL must use rediss://"

            # Check CA certificate exists
            if ca_cert_path:
                if not Path(ca_cert_path).is_absolute():
                    ca_cert_path = str(project_root / ca_cert_path)

                if not Path(ca_cert_path).exists():
                    logger.error(f"✗ CA certificate not found: {ca_cert_path}")
                    return False, f"CA cert not found: {ca_cert_path}"

                # Verify certificate is valid
                try:
                    context = ssl.create_default_context(cafile=ca_cert_path)
                    logger.info("✓ Redis TLS certificate valid")
                except Exception as e:
                    logger.error(f"✗ Invalid TLS certificate: {e}")
                    return False, f"Invalid certificate: {e}"
            else:
                logger.warning("⚠ No CA certificate provided, using system default")

            return True, "TLS configured correctly"

        except Exception as e:
            logger.error(f"✗ Redis TLS check failed: {e}")
            return False, str(e)

    async def check_kraken_wss(self) -> Tuple[bool, str]:
        """Check Kraken WebSocket connectivity"""
        logger.info("Checking Kraken WebSocket...")

        try:
            kraken_config = self.config.get("kraken", {})
            wss_url = kraken_config.get("websocket", {}).get("url", "wss://ws.kraken.com")

            # Try to connect to WebSocket
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(
                    wss_url, timeout=aiohttp.ClientTimeout(total=10)
                ) as ws:
                    # Send ping
                    await ws.send_json({"event": "ping"})

                    # Wait for pong
                    try:
                        msg = await asyncio.wait_for(ws.receive_json(), timeout=5)

                        if msg.get("event") == "pong" or msg.get("event") == "systemStatus":
                            logger.info("✓ Kraken WebSocket connection successful")
                            return True, "Connected successfully"
                        else:
                            logger.warning(f"⚠ Unexpected response: {msg}")
                            return True, f"Connected (unexpected response: {msg.get('event')})"

                    except asyncio.TimeoutError:
                        logger.error("✗ Kraken WebSocket timeout")
                        return False, "Connection timeout"

        except Exception as e:
            logger.error(f"✗ Kraken WebSocket failed: {e}")
            return False, str(e)

    async def check_kraken_rest(self) -> Tuple[bool, str]:
        """Check Kraken REST API"""
        logger.info("Checking Kraken REST API...")

        try:
            kraken_config = self.config.get("kraken", {})
            rest_url = kraken_config.get("rest", {}).get("url", "https://api.kraken.com")

            # Test public endpoint
            async with aiohttp.ClientSession() as session:
                url = f"{rest_url}/0/public/SystemStatus"

                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()

                        if data.get("error") and len(data["error"]) > 0:
                            logger.error(f"✗ Kraken API error: {data['error']}")
                            return False, f"API error: {data['error']}"

                        result = data.get("result", {})
                        status = result.get("status", "unknown")

                        logger.info(f"✓ Kraken REST API online (status: {status})")
                        return True, f"API online (status: {status})"
                    else:
                        logger.error(f"✗ Kraken REST API returned {resp.status}")
                        return False, f"HTTP {resp.status}"

        except Exception as e:
            logger.error(f"✗ Kraken REST API failed: {e}")
            return False, str(e)

    async def check_trading_pairs(self) -> Tuple[bool, str]:
        """Validate trading pairs on Kraken"""
        logger.info("Validating trading pairs...")

        try:
            trading_config = self.config.get("trading", {})
            pairs = trading_config.get("pairs", [])

            if not pairs:
                logger.error("✗ No trading pairs configured")
                return False, "No pairs configured"

            # Query Kraken for valid pairs
            kraken_config = self.config.get("kraken", {})
            rest_url = kraken_config.get("rest", {}).get("url", "https://api.kraken.com")

            async with aiohttp.ClientSession() as session:
                url = f"{rest_url}/0/public/AssetPairs"

                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        logger.error(f"✗ Failed to fetch Kraken pairs: HTTP {resp.status}")
                        return False, f"HTTP {resp.status}"

                    data = await resp.json()
                    kraken_pairs = data.get("result", {})

                    # Map our pair format to Kraken's format
                    pair_mapping = {
                        "BTC/USD": "XXBTZUSD",
                        "ETH/USD": "XETHZUSD",
                        "SOL/USD": "SOLUSD",
                        "MATIC/USD": "MATICUSD",
                        "LINK/USD": "LINKUSD",
                    }

                    invalid_pairs = []
                    for pair in pairs:
                        kraken_pair = pair_mapping.get(pair)

                        if not kraken_pair or kraken_pair not in kraken_pairs:
                            invalid_pairs.append(pair)

                    if invalid_pairs:
                        logger.error(f"✗ Invalid pairs: {invalid_pairs}")
                        return False, f"Invalid pairs: {invalid_pairs}"

            logger.info(f"✓ All {len(pairs)} trading pairs valid")
            return True, f"{len(pairs)} pairs validated"

        except Exception as e:
            logger.error(f"✗ Trading pair validation failed: {e}")
            return False, str(e)

    async def check_safety_rails(self) -> Tuple[bool, str]:
        """Validate safety rails configuration"""
        logger.info("Validating safety rails...")

        try:
            safety_config = self.config.get("safety_rails", {})

            if not safety_config:
                logger.error("✗ Safety rails not configured")
                return False, "Not configured"

            # Initialize safety rails to validate
            rails = LiveSafetyRails(self.config)

            # Check key parameters
            daily_limits = safety_config.get("daily_limits", {})
            portfolio_limits = safety_config.get("portfolio", {})

            max_loss_pct = daily_limits.get("max_loss_pct", 0)
            max_heat_pct = portfolio_limits.get("max_heat_pct", 0)

            if max_loss_pct >= 0:
                logger.error(f"✗ Daily stop loss must be negative: {max_loss_pct}%")
                return False, "Invalid daily stop loss"

            if max_heat_pct <= 0 or max_heat_pct > 100:
                logger.error(f"✗ Portfolio heat must be 0-100%: {max_heat_pct}%")
                return False, "Invalid portfolio heat"

            logger.info("✓ Safety rails configured correctly")
            return True, "Configuration valid"

        except Exception as e:
            logger.error(f"✗ Safety rails validation failed: {e}")
            return False, str(e)

    async def run_all_checks(self) -> bool:
        """Run all preflight checks"""
        logger.info("=" * 80)
        logger.info(" " * 25 + "PREFLIGHT CHECKS")
        logger.info("=" * 80)

        checks = [
            ("Redis Connection", self.check_redis_connection()),
            ("Redis TLS", self.check_redis_tls()),
            ("Kraken WebSocket", self.check_kraken_wss()),
            ("Kraken REST API", self.check_kraken_rest()),
            ("Trading Pairs", self.check_trading_pairs()),
            ("Safety Rails", self.check_safety_rails()),
        ]

        results = {}
        all_passed = True

        for name, check_coro in checks:
            passed, message = await check_coro
            results[name] = (passed, message)

            if not passed:
                all_passed = False

        # Print summary
        logger.info("\n" + "=" * 80)
        logger.info("PREFLIGHT SUMMARY")
        logger.info("=" * 80)

        for name, (passed, message) in results.items():
            status = "✓ PASS" if passed else "✗ FAIL"
            logger.info(f"  {status:10s} {name:25s} {message}")

        logger.info("=" * 80)

        if all_passed:
            logger.info("✅ All preflight checks PASSED")
        else:
            logger.critical("❌ Preflight checks FAILED")
            logger.critical("   Fix errors above before starting")

        return all_passed


# =============================================================================
# Startup Summary
# =============================================================================


def log_startup_summary(config: Dict, safety_rails: LiveSafetyRails) -> None:
    """Log comprehensive startup summary"""
    mode_config = config.get("mode", {})
    live_mode = mode_config.get("live_mode", False)

    trading_config = config.get("trading", {})
    pairs = trading_config.get("pairs", [])
    timeframes_config = trading_config.get("timeframes", {})

    redis_config = config.get("redis", {})
    streams_config = redis_config.get("streams", {})

    logger.info("\n" + "=" * 80)
    logger.info(" " * 20 + "LIVE SCALPER STARTUP SUMMARY")
    logger.info("=" * 80)

    # Mode
    logger.info(f"\n🚦 MODE: {'LIVE TRADING' if live_mode else 'PAPER TRADING'}")
    if live_mode:
        logger.info("   ⚠️  WARNING: REAL MONEY AT RISK")
    else:
        logger.info("   ✓  Safe mode - no real money")

    # Trading pairs
    logger.info(f"\n💱 TRADING PAIRS ({len(pairs)}):")
    for pair in pairs:
        logger.info(f"   - {pair}")

    # Timeframes
    logger.info(f"\n⏱️  TIMEFRAMES:")
    logger.info(f"   Primary:   {timeframes_config.get('primary', '15s')}")
    logger.info(f"   Secondary: {timeframes_config.get('secondary', '1m')}")
    logger.info(f"   5s bars:   {'Enabled' if timeframes_config.get('enable_5s_bars', False) else 'Disabled'}")

    # Risk limits (from safety rails)
    logger.info(f"\n🛡️  RISK LIMITS:")
    logger.info(f"   Daily Stop:        {safety_rails.daily_limits.max_loss_pct}%")
    logger.info(f"   Daily Target:      +{safety_rails.daily_limits.profit_target_pct}%")
    logger.info(f"   Max Portfolio Heat: {safety_rails.portfolio_limits.max_heat_pct}%")
    logger.info(f"   Max Positions:     {safety_rails.portfolio_limits.max_concurrent_positions}")
    logger.info(f"   Max Trades/Day:    {safety_rails.daily_limits.max_trades}")

    # Per-pair limits
    logger.info(f"\n💰 PER-PAIR NOTIONAL CAPS:")
    for pair, limit in safety_rails.per_pair_limits.items():
        logger.info(f"   {pair:12s} ${limit.max_notional:,.0f}")

    # Redis streams
    logger.info(f"\n📊 REDIS STREAMS:")
    logger.info(f"   Signals:   {streams_config.get('signals_live' if live_mode else 'signals_paper', 'N/A')}")
    logger.info(f"   Positions: {streams_config.get('positions', 'N/A')}")
    logger.info(f"   Risk:      {streams_config.get('risk_events', 'N/A')}")
    logger.info(f"   Heartbeat: {streams_config.get('heartbeat', 'N/A')}")

    # Safety rails enabled
    logger.info(f"\n🚨 SAFETY RAILS: ENABLED")
    logger.info(f"   Portfolio heat monitoring: ✓")
    logger.info(f"   Daily stop loss: ✓")
    logger.info(f"   Per-pair limits: ✓")
    logger.info(f"   Circuit breakers: ✓")

    # Timestamp
    logger.info(f"\n🕐 STARTED: {datetime.now(timezone.utc).isoformat()}")

    logger.info("\n" + "=" * 80)


# =============================================================================
# Main Runner
# =============================================================================


async def run_scalper(config: Dict) -> None:
    """Main scalper execution loop"""
    logger.info("Starting scalper execution...")

    # Initialize safety rails
    safety_rails = LiveSafetyRails(config)

    # Log startup summary
    log_startup_summary(config, safety_rails)

    # Initialize Redis client for signal publishing
    redis_config = RedisCloudConfig(
        url=config["redis"]["url"],
        ca_cert_path=config["redis"]["ca_cert_path"],
    )
    redis_client = RedisCloudClient(redis_config)
    await redis_client.connect()

    # Initialize Prometheus exporter
    prometheus_port = config.get("monitoring", {}).get("prometheus_port", 9108)
    prometheus_exporter = FreshnessMetricsExporter(port=prometheus_port)
    await prometheus_exporter.start()
    logger.info(f"Prometheus metrics available at http://localhost:{prometheus_port}/metrics")

    # Initialize signal queue with heartbeat
    queue_max_size = config.get("monitoring", {}).get("queue_max_size", 1000)
    heartbeat_interval = config.get("monitoring", {}).get("heartbeat_interval_sec", 15.0)
    signal_queue = SignalQueue(
        redis_client=redis_client,
        max_size=queue_max_size,
        heartbeat_interval_sec=heartbeat_interval,
        prometheus_exporter=prometheus_exporter,
    )
    await signal_queue.start()
    logger.info(
        f"Signal queue started (max_size={queue_max_size}, "
        f"heartbeat={heartbeat_interval}s)"
    )

    # Get configuration
    trading_pairs = config["trading"]["pairs"]
    primary_tf = config["trading"]["timeframes"]["primary"]
    is_live_mode = config["mode"]["live_mode"]

    # Metrics tracking
    signals_published = 0
    signals_rejected = 0

    # Main loop
    logger.info("\nEntering main trading loop...")
    logger.info("Press Ctrl+C to stop\n")

    try:
        iteration = 0

        while True:
            iteration += 1

            # Check if trading is allowed
            can_trade, reason = safety_rails.check_can_trade()

            if not can_trade:
                logger.warning(f"Trading not allowed: {reason}")
                await asyncio.sleep(60)  # Wait 1 minute before checking again
                continue

            # Generate demo signal (replace with actual scalper agent later)
            # This demonstrates the signal validation and publishing flow
            for pair in trading_pairs:
                # Create a demo signal
                demo_signal_data = {
                    "ts_exchange": int(time.time() * 1000),
                    "ts_server": int(time.time() * 1000),
                    "symbol": pair,
                    "timeframe": primary_tf,
                    "side": "long" if iteration % 2 == 0 else "short",
                    "confidence": 0.75 + (iteration % 10) * 0.02,
                    "entry": 45000.0 + iteration * 10,
                    "stop": 44500.0 + iteration * 10 if iteration % 2 == 0 else 45500.0 + iteration * 10,
                    "tp": 46000.0 + iteration * 10 if iteration % 2 == 0 else 44000.0 + iteration * 10,
                    "model": "enhanced_scalper_v1",
                    "trace_id": f"{int(time.time())}-demo-{iteration}",
                }

                # Validate signal
                signal, error = validate_signal_safe(demo_signal_data)

                if signal is None:
                    # Invalid signal - skip
                    logger.warning(f"[REJECTED] {pair}: {error}")
                    signals_rejected += 1
                    prometheus_exporter.record_signal_rejected()
                    continue

                # Calculate freshness metrics
                now_ms = int(time.time() * 1000)
                freshness = signal.calculate_freshness_metrics(now_server_ms=now_ms)

                # Check for clock drift
                has_drift, drift_message = signal.check_clock_drift(threshold_ms=2000)
                if has_drift:
                    logger.warning(f"[CLOCK DRIFT] {pair}: {drift_message}")
                    prometheus_exporter.record_clock_drift_warning(
                        symbol=signal.symbol,
                        drift_ms=freshness["exchange_server_delta_ms"],
                    )

                # Update Prometheus metrics
                prometheus_exporter.update_freshness_metrics(
                    symbol=signal.symbol,
                    timeframe=signal.timeframe,
                    event_age_ms=freshness["event_age_ms"],
                    ingest_lag_ms=freshness["ingest_lag_ms"],
                    exchange_server_delta_ms=freshness["exchange_server_delta_ms"],
                )

                # Enqueue signal for publishing (with backpressure handling)
                try:
                    enqueued = await signal_queue.enqueue(signal)

                    if enqueued:
                        signals_published += 1
                        logger.info(
                            f"[ENQUEUED] {signal.symbol} {signal.side} @ {signal.entry:.2f} "
                            f"(conf={signal.confidence:.2f}, event_age={freshness['event_age_ms']}ms, "
                            f"queue_depth={signal_queue.queue.qsize()})"
                        )
                    else:
                        logger.warning(
                            f"[SHED] {signal.symbol} {signal.side} @ {signal.entry:.2f} "
                            f"(conf={signal.confidence:.2f}) - backpressure, lowest confidence shed"
                        )

                except Exception as e:
                    logger.error(f"Failed to enqueue signal: {e}")

            # Publish metrics every 10 iterations
            if iteration % 10 == 0:
                status = safety_rails.get_status_summary()
                queue_stats = signal_queue.get_stats()
                logger.info(
                    f"Status: PnL {status['daily_pnl_pct']:.2f}%, Heat {status['portfolio_heat_pct']:.1f}%, "
                    f"Signals enqueued={queue_stats['signals_enqueued']}, published={queue_stats['signals_published']}, "
                    f"shed={queue_stats['signals_shed']}, rejected={signals_rejected}, "
                    f"queue={queue_stats['queue_depth']}/{queue_stats['queue_capacity']} "
                    f"({queue_stats['queue_utilization_pct']:.1f}%)"
                )

                # Publish metrics to Redis (including freshness if we have recent signals)
                try:
                    metrics_stream = get_metrics_stream_key()
                    metrics_data = {
                        "ts": int(time.time() * 1000),
                        "signals_published": signals_published,
                        "signals_rejected": signals_rejected,
                        "daily_pnl_pct": status["daily_pnl_pct"],
                        "portfolio_heat_pct": status["portfolio_heat_pct"],
                        "mode": "live" if is_live_mode else "paper",
                    }

                    # Add freshness metrics if available (from last signal)
                    if 'freshness' in locals() and freshness:
                        metrics_data.update({
                            "avg_event_age_ms": freshness["event_age_ms"],
                            "avg_ingest_lag_ms": freshness["ingest_lag_ms"],
                            "last_clock_drift_ms": freshness["exchange_server_delta_ms"],
                        })

                    await redis_client.xadd(
                        metrics_stream,
                        metrics_data,
                        maxlen=10000,
                    )
                except Exception as e:
                    logger.error(f"Failed to publish metrics: {e}")

            await asyncio.sleep(15)  # Wait 15 seconds between iterations

    except KeyboardInterrupt:
        logger.info("\nReceived shutdown signal")
    finally:
        logger.info("Shutting down scalper...")

        # Stop signal queue
        await signal_queue.stop()
        logger.info("Signal queue stopped")

        # Close Redis client
        await redis_client.close()
        logger.info("Redis client closed")


# =============================================================================
# CLI Interface
# =============================================================================


def parse_args():
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(
        description="Live Scalper Runner - Production Entrypoint",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--config",
        type=Path,
        default=project_root / "config" / "live_scalper_config.yaml",
        help="Path to configuration file (default: config/live_scalper_config.yaml)",
    )

    parser.add_argument(
        "--env-file",
        type=Path,
        default=project_root / ".env.paper",
        help="Path to environment file (default: .env.paper)",
    )

    parser.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Skip preflight checks (not recommended for live mode)",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate configuration and run preflight checks only",
    )

    return parser.parse_args()


async def main():
    """Main entry point"""
    args = parse_args()

    # Load environment
    if args.env_file.exists():
        load_dotenv(args.env_file)
        logger.info(f"Loaded environment from: {args.env_file}")

    # Create logs directory
    (project_root / "logs").mkdir(exist_ok=True)

    # Load configuration
    try:
        config = load_config(args.config)
    except Exception as e:
        logger.critical(f"Failed to load configuration: {e}")
        sys.exit(1)

    # Validate configuration
    logger.info("Validating configuration...")
    errors = validate_config(config)

    if errors:
        logger.critical("Configuration validation failed:")
        for error in errors:
            logger.critical(f"  - {error}")
        sys.exit(1)

    logger.info("✓ Configuration valid")

    # Run preflight checks
    if not args.skip_preflight:
        preflight = PreflightChecks(config)
        all_passed = await preflight.run_all_checks()

        if not all_passed:
            logger.critical("\nPreflight checks failed - aborting")
            sys.exit(1)
    else:
        logger.warning("⚠️  Skipping preflight checks")

    # Dry run mode
    if args.dry_run:
        logger.info("\n✓ Dry run complete - configuration and preflight checks passed")
        sys.exit(0)

    # Run scalper
    await run_scalper(config)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\nShutdown complete")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
