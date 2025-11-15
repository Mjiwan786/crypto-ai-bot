"""
scripts/run_paper_trial.py - Paper Trading Trial (E2E with Metrics)

Runs 14-21 day paper trading trial with full E2E monitoring.
Integrates Prometheus metrics, latency tracking, and validation.

Usage:
    python scripts/run_paper_trial.py

Environment Variables:
    REDIS_URL: Redis Cloud connection URL (required)
    TRADING_PAIRS: Comma-separated pairs (default: BTC/USD,ETH/USD)
    TIMEFRAMES: Comma-separated timeframes (default: 5m)
    SPREAD_BPS_MAX: Max spread in bps (default: 5.0)
    LATENCY_MS_MAX: Max latency in ms (default: 500.0)
    METRICS_PORT: Prometheus port (default: 9108)
    LOG_LEVEL: Logging level (default: INFO)

DoD (Definition of Done):
- Paper trial: PF ≥1.5 or Win-rate ≥60%, DD ≤15%
- No missed publishes
- Latency p95 <500ms
- /metrics endpoint exposes:
  - signals_published_total
  - publish_latency_ms
  - breaker trip counters
  - stream lag metrics

Author: Crypto AI Bot Team
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from engine import LiveEngine, EngineConfig
from monitoring.metrics_exporter import (
    start_metrics_server,
    heartbeat,
    inc_signals_published,
    observe_publish_latency_ms,
    observe_stream_lag,
)


async def main():
    """Run paper trading trial with full E2E monitoring"""

    # Setup logging
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(
                project_root / "logs" / f"paper_trial_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
            ),
        ],
    )

    logger = logging.getLogger(__name__)

    # Print header
    print("\n" + "=" * 80)
    print("PAPER TRADING TRIAL - E2E DEPLOYMENT")
    print("=" * 80)
    print(f"Trading Pairs: {os.getenv('TRADING_PAIRS', 'BTC/USD,ETH/USD')}")
    print(f"Timeframes: {os.getenv('TIMEFRAMES', '5m')}")
    print(f"Redis URL: {os.getenv('REDIS_URL', 'NOT SET')[:50]}...")
    print(f"Mode: paper")
    print(f"Metrics Port: {os.getenv('METRICS_PORT', '9108')}")
    print(f"Log Level: {log_level}")
    print("=" * 80)
    print()
    print("Definition of Done (DoD):")
    print("  - Profit Factor ≥ 1.5 OR Win-rate ≥ 60%")
    print("  - Max Drawdown ≤ 15%")
    print("  - No missed publishes")
    print("  - Latency p95 < 500ms")
    print("  - Duration: 14-21 days")
    print("=" * 80 + "\n")

    # Validate environment
    if not os.getenv("REDIS_URL"):
        logger.error("❌ REDIS_URL not set in environment")
        logger.error("   Set REDIS_URL to your Redis Cloud connection string")
        logger.error("   Example: export REDIS_URL='rediss://default:pass@host:port'")
        sys.exit(1)

    # Check if Redis CA cert exists
    ca_cert_path = os.getenv(
        "REDIS_CA_CERT",
        str(project_root / "config" / "certs" / "redis_ca.pem")
    )
    if not os.path.exists(ca_cert_path):
        logger.warning(f"⚠️ Redis CA cert not found at: {ca_cert_path}")
        logger.warning("   TLS connection may fail")

    # Start Prometheus metrics server
    logger.info("🔧 Starting Prometheus metrics server...")
    try:
        metrics_port = int(os.getenv("METRICS_PORT", "9108"))
        metrics_addr = os.getenv("METRICS_ADDR", "0.0.0.0")
        start_metrics_server(addr=metrics_addr, port=metrics_port)
        logger.info(f"✅ Metrics server running on {metrics_addr}:{metrics_port}/metrics")
    except Exception as e:
        logger.error(f"❌ Failed to start metrics server: {e}")
        sys.exit(1)

    # Create engine config
    config = EngineConfig(
        mode="paper",
        ohlcv_window_size=300,
        min_bars_required=100,
        signal_cooldown_seconds=60,
    )

    logger.info("✅ Configuration loaded")
    logger.info(f"   Initial equity: ${config.initial_equity_usd}")
    logger.info(f"   Spread breaker: {config.spread_bps_max} bps")
    logger.info(f"   Latency breaker: {config.latency_ms_max} ms")
    logger.info(f"   Scalper throttle: {config.scalp_max_trades_per_minute} trades/min")
    logger.info(f"   Signal cooldown: {config.signal_cooldown_seconds}s")
    logger.info("")

    # Create engine
    logger.info("🚀 Creating live engine...")
    engine = LiveEngine(config=config)

    # Print deployment instructions
    print("\n" + "=" * 80)
    print("PAPER TRIAL DEPLOYMENT INSTRUCTIONS")
    print("=" * 80)
    print("1. Engine is now running in paper mode")
    print("2. Signals will be published to Redis stream: signals:paper")
    print("3. Prometheus metrics available at:")
    print(f"   http://localhost:{metrics_port}/metrics")
    print("4. Key metrics to monitor:")
    print("   - signals_published_total (should increment)")
    print("   - publish_latency_ms_bucket (p95 < 500ms)")
    print("   - ingestor_disconnects_total (should be 0)")
    print("   - redis_publish_errors_total (should be 0)")
    print("   - bot_heartbeat_seconds (should update)")
    print("5. Run for 14-21 days to meet DoD")
    print("6. Press Ctrl+C to stop and view metrics summary")
    print("=" * 80 + "\n")

    # Start heartbeat task
    async def metrics_heartbeat():
        """Update heartbeat metric every 30 seconds"""
        while True:
            heartbeat()
            await asyncio.sleep(30)

    heartbeat_task = asyncio.create_task(metrics_heartbeat())

    # Start engine
    try:
        logger.info("🎯 Starting paper trading trial...")
        logger.info("   This will run indefinitely until stopped (Ctrl+C)")
        logger.info("")
        await engine.start()

    except KeyboardInterrupt:
        logger.info("\n\n⏹️ Shutdown signal received...")
        print("\n" + "=" * 80)
        print("GRACEFUL SHUTDOWN")
        print("=" * 80)

    except Exception as e:
        logger.error(f"❌ Engine error: {e}", exc_info=True)
        print("\n" + "=" * 80)
        print("ENGINE FAILED")
        print("=" * 80)
        print(f"Error: {e}")
        print("=" * 80 + "\n")
        sys.exit(1)

    finally:
        # Cancel heartbeat task
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass

        # Stop engine and print metrics
        await engine.stop()

        # Print final metrics
        metrics = engine.get_metrics()

        print("\n" + "=" * 80)
        print("PAPER TRIAL SESSION SUMMARY")
        print("=" * 80)
        print(f"✅ Ticks processed: {metrics['ticks_processed']}")
        print(f"✅ Signals generated: {metrics['signals_generated']}")
        print(f"✅ Signals published: {metrics['signals_published']}")
        print(f"⚠️ Signals rejected: {metrics['signals_rejected']}")
        print(f"📊 Avg decision latency: {metrics['avg_decision_latency_ms']:.2f}ms")
        print(f"📊 Avg publish latency: {metrics['avg_publish_latency_ms']:.2f}ms")
        print("")
        print("Circuit Breakers:")
        for key, val in metrics["breakers"].items():
            icon = "⚠️" if val > 0 else "✅"
            print(f"  {icon} {key}: {val}")
        print("")
        print("Router:")
        for key, val in metrics["router"].items():
            if isinstance(val, (int, float)):
                print(f"  📌 {key}: {val}")
        print("=" * 80)
        print()
        print("Next Steps:")
        print("1. Validate paper trading performance:")
        print("   python scripts/validate_paper_trading.py --from-redis")
        print("2. Check Prometheus metrics for latency p95")
        print("3. Continue running for 14-21 days to meet DoD")
        print("4. If DoD met → Ready for LIVE")
        print("=" * 80 + "\n")


if __name__ == "__main__":
    # Check Python version
    if sys.version_info < (3, 10):
        print("❌ Python 3.10+ required")
        sys.exit(1)

    # Create logs directory if it doesn't exist
    logs_dir = Path(__file__).parent.parent / "logs"
    logs_dir.mkdir(exist_ok=True)

    # Run async main
    asyncio.run(main())
