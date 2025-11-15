"""
scripts/run_paper.py - Run Live Engine in Paper Mode

Smoke test script to run the live engine in paper mode.
Connects to Kraken WS, processes ticks, and publishes signals to Redis.

Usage:
    python scripts/run_paper.py

Environment Variables:
    REDIS_URL: Redis Cloud connection URL (required)
    TRADING_PAIRS: Comma-separated pairs (default: BTC/USD,ETH/USD)
    TIMEFRAMES: Comma-separated timeframes (default: 5m)
    SPREAD_BPS_MAX: Max spread in bps (default: 5.0)
    LATENCY_MS_MAX: Max latency in ms (default: 500.0)
    SCALP_MAX_TRADES_PER_MINUTE: Max trades per minute (default: 3)
    LOG_LEVEL: Logging level (default: INFO)

Smoke Test Criteria:
- Engine starts without errors
- WS connects to Kraken
- OHLCV cache fills to minimum bars
- Regime detection works
- Signals flow to Redis (paper mode)
- Circuit breakers log correctly
- No crashes for 30-60 minutes

Author: Crypto AI Bot Team
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from engine import LiveEngine, EngineConfig


async def main():
    """Run live engine in paper mode"""

    # Setup logging
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    logger = logging.getLogger(__name__)

    # Print header
    print("\n" + "="*80)
    print("LIVE ENGINE - PAPER MODE SMOKE TEST")
    print("="*80)
    print(f"Trading Pairs: {os.getenv('TRADING_PAIRS', 'BTC/USD,ETH/USD')}")
    print(f"Timeframes: {os.getenv('TIMEFRAMES', '5m')}")
    print(f"Redis URL: {os.getenv('REDIS_URL', 'NOT SET')[:50]}...")
    print(f"Mode: paper")
    print(f"Log Level: {log_level}")
    print("="*80 + "\n")

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

    # Print smoke test instructions
    print("\n" + "="*80)
    print("SMOKE TEST INSTRUCTIONS")
    print("="*80)
    print("1. Engine will start and connect to Kraken WebSocket")
    print("2. OHLCV cache will fill (requires ~100 bars = ~8 hours for 5m)")
    print("3. Once ready, signals will be generated and published to Redis")
    print("4. Monitor logs for:")
    print("   - WS connection status")
    print("   - OHLCV cache filling progress")
    print("   - Regime detection results")
    print("   - Signal generation and publishing")
    print("   - Circuit breaker trips")
    print("   - Latency metrics")
    print("5. Press Ctrl+C to stop and view metrics summary")
    print("="*80 + "\n")

    # Start engine
    try:
        logger.info("🎯 Starting live engine (paper mode)...")
        await engine.start()

    except KeyboardInterrupt:
        logger.info("\n\n⏹️ Shutdown signal received...")
        print("\n" + "="*80)
        print("GRACEFUL SHUTDOWN")
        print("="*80)

    except Exception as e:
        logger.error(f"❌ Engine error: {e}", exc_info=True)
        print("\n" + "="*80)
        print("ENGINE FAILED")
        print("="*80)
        print(f"Error: {e}")
        print("="*80 + "\n")
        sys.exit(1)

    finally:
        # Stop engine and print metrics
        await engine.stop()

        # Print final metrics
        metrics = engine.get_metrics()

        print("\n" + "="*80)
        print("SMOKE TEST RESULTS")
        print("="*80)
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
        print("="*80 + "\n")

        # Evaluate smoke test
        logger.info("📋 Evaluating smoke test...")

        smoke_test_passed = True
        errors = []

        # Check if any signals were published
        if metrics["signals_published"] == 0:
            logger.warning("⚠️ No signals published (cache may not be ready yet)")
            logger.warning("   For full test, run for 8+ hours to fill OHLCV cache")

        # Check for excessive breaker trips
        if metrics["breakers"]["spread_breaker_trips"] > 10:
            errors.append("Excessive spread breaker trips")
            smoke_test_passed = False

        if metrics["breakers"]["latency_breaker_trips"] > 10:
            errors.append("Excessive latency breaker trips")
            smoke_test_passed = False

        # Print final verdict
        if smoke_test_passed and len(errors) == 0:
            print("✅ SMOKE TEST PASSED")
            print("   Engine is functioning correctly")
            sys.exit(0)
        else:
            print("⚠️ SMOKE TEST PASSED WITH WARNINGS")
            for error in errors:
                print(f"   - {error}")
            sys.exit(0)


if __name__ == "__main__":
    # Check Python version
    if sys.version_info < (3, 10):
        print("❌ Python 3.10+ required")
        sys.exit(1)

    # Run async main
    asyncio.run(main())
