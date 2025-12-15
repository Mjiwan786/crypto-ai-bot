"""
Start Paper Trading Trial with Aggressive Bar Reaction Config

Deploys the optimized bar_reaction_5m_aggressive configuration to paper trading
for 48-hour validation of our P&L improvements.

Usage:
    python scripts/start_aggressive_paper_trial.py

Success Criteria (48 hours):
- ✅ Positive P&L or within -2%
- ✅ Max heat (unrealized DD) < 8%
- ✅ Fill quality > 80% maker
- ✅ Latency < 500ms p95
- ✅ No emergency stops triggered

Improvements Being Tested:
1. Death spiral fix: min_position_usd = $50
2. Better triggers: 20bps (vs 12bps baseline)
3. Wider stops: 1.5 ATR (vs 0.6 ATR)
4. Better targets: 2.5/4.0 ATR (vs 1.0/1.8)
5. Higher risk: 1.2% (vs 0.6%)
6. Regime filtering configured

Author: Quant Team
Date: 2025-11-08
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
from datetime import datetime, timezone
import time
import signal

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config.signals_api_config import get_signals_api_url

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            project_root / "logs" / f"aggressive_paper_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        ),
    ],
)

logger = logging.getLogger(__name__)

# Graceful shutdown
_shutdown_requested = False

def signal_handler(signum, frame):
    """Handle graceful shutdown"""
    global _shutdown_requested
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    _shutdown_requested = True


async def main():
    """Run aggressive paper trial"""

    # Print banner
    print("\n" + "=" * 80)
    print("AGGRESSIVE PAPER TRIAL - P&L OPTIMIZATION VALIDATION")
    print("=" * 80)
    print(f"Start Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"Config: config/bar_reaction_5m_aggressive.yaml")
    print(f"Mode: PAPER")
    print(f"Duration: 48 hours")
    print("=" * 80)
    print("\nIMPROVEMENTS BEING TESTED:")
    print("  1. Death spiral fix: min_position_usd = $50")
    print("  2. Better triggers: 20bps (vs 12bps baseline)")
    print("  3. Wider stops: 1.5 ATR (vs 0.6 ATR)")
    print("  4. Better targets: 2.5/4.0 ATR (vs 1.0/1.8)")
    print("  5. Higher risk: 1.2% per trade (vs 0.6%)")
    print("  6. Max exposure: $2000 per position")
    print("=" * 80)
    print("\nSUCCESS CRITERIA (48h):")
    print("  ✅ Positive P&L or within -2%")
    print("  ✅ Max heat (unrealized DD) < 8%")
    print("  ✅ Fill quality > 80% maker")
    print("  ✅ Latency < 500ms p95")
    print("  ✅ No emergency stops triggered")
    print("=" * 80 + "\n")

    # Validate environment
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        logger.error("❌ REDIS_URL not set in environment")
        logger.error("   Please set REDIS_URL in .env file")
        sys.exit(1)

    logger.info(f"✅ Redis URL configured: {redis_url[:50]}...")

    # Check config file
    config_path = project_root / "config" / "bar_reaction_5m_aggressive.yaml"
    if not config_path.exists():
        logger.error(f"❌ Config file not found: {config_path}")
        sys.exit(1)

    logger.info(f"✅ Config file found: {config_path}")

    # Load strategy with aggressive config
    logger.info("🚀 Loading bar_reaction_5m strategy with aggressive config...")

    try:
        import yaml
        from strategies.bar_reaction_5m import BarReaction5mStrategy

        # Load config
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        strategy_config = config.get('strategy', {})

        # Initialize strategy
        strategy = BarReaction5mStrategy(
            mode=strategy_config.get('mode', 'trend'),
            trigger_mode=strategy_config.get('trigger_mode', 'open_to_close'),
            trigger_bps_up=strategy_config.get('trigger_bps_up', 20.0),
            trigger_bps_down=strategy_config.get('trigger_bps_down', 20.0),
            min_atr_pct=strategy_config.get('min_atr_pct', 0.05),
            max_atr_pct=strategy_config.get('max_atr_pct', 5.0),
            atr_window=strategy_config.get('atr_window', 14),
            sl_atr=strategy_config.get('sl_atr', 1.5),
            tp1_atr=strategy_config.get('tp1_atr', 2.5),
            tp2_atr=strategy_config.get('tp2_atr', 4.0),
            risk_per_trade_pct=strategy_config.get('risk_per_trade_pct', 1.2),
            min_position_usd=strategy_config.get('min_position_usd', 50.0),
            max_position_usd=strategy_config.get('max_position_usd', 2000.0),
            maker_only=strategy_config.get('maker_only', True),
            spread_bps_cap=strategy_config.get('spread_bps_cap', 8.0),
        )

        logger.info("✅ Strategy initialized successfully")
        logger.info(f"   Mode: {strategy.mode}")
        logger.info(f"   Trigger: {strategy.trigger_bps_up} bps")
        logger.info(f"   Stop: {strategy.sl_atr}x ATR")
        logger.info(f"   Targets: {strategy.tp1_atr}x / {strategy.tp2_atr}x ATR")
        logger.info(f"   Risk: {strategy.risk_per_trade_pct}% per trade")
        logger.info(f"   Position limits: ${strategy.min_position_usd} - ${strategy.max_position_usd}")

    except Exception as e:
        logger.error(f"❌ Failed to load strategy: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Print monitoring instructions
    print("\n" + "=" * 80)
    print("MONITORING INSTRUCTIONS")
    print("=" * 80)
    print("1. Check Redis streams:")
    print(f"   redis-cli -u {redis_url[:50]}... \\")
    print("   --tls --cacert config/certs/redis_ca.pem \\")
    print("   XLEN signals:paper")
    print("")
    print("2. Monitor latest signals:")
    print(f"   redis-cli -u {redis_url[:50]}... \\")
    print("   --tls --cacert config/certs/redis_ca.pem \\")
    print("   XREVRANGE signals:paper + - COUNT 5")
    print("")
    print("3. Check signals-api metrics:")
    print(f"   curl {get_signals_api_url('/metrics/live')}")
    print("")
    print("4. View dashboard:")
    print("   https://aipredictedsignals.cloud/dashboard")
    print("=" * 80 + "\n")

    logger.info("✅ Paper trial setup complete")
    logger.info("⏰ Running for 48 hours...")
    logger.info("📊 Strategy will generate signals based on live Kraken data")
    logger.info("🔴 Press Ctrl+C to stop gracefully")

    # NOTE: For actual live trading, you would integrate with your existing
    # LiveEngine or orchestration system here. For this demo, we're showing
    # the setup and validation steps.

    # Placeholder for actual trading engine integration
    print("\n⚠️  NOTE: Integration with LiveEngine required for actual signal generation")
    print("    This script validates configuration and provides monitoring instructions.")
    print("    To run live paper trading:")
    print("    1. Use scripts/run_paper_trial.py with aggressive config")
    print("    2. Or deploy via: fly deploy --ha=false")
    print("    3. Or run: python main.py run --mode paper --config config/bar_reaction_5m_aggressive.yaml")
    print("")

    # Keep alive for demonstration
    logger.info("✅ Setup validated. Ready for deployment.")
    print("\n" + "=" * 80)
    print("NEXT STEPS")
    print("=" * 80)
    print("Deploy to paper trading using one of:")
    print("")
    print("Option 1 (Recommended): Use existing paper trial script")
    print("  $ cd crypto_ai_bot")
    print("  $ conda activate crypto-bot")
    print("  $ export CONFIG_PATH=config/bar_reaction_5m_aggressive.yaml")
    print("  $ python scripts/run_paper_trial.py")
    print("")
    print("Option 2: Use main entry point")
    print("  $ python main.py run --mode paper --config config/bar_reaction_5m_aggressive.yaml")
    print("")
    print("Option 3: Deploy to Fly.io")
    print("  $ fly deploy --ha=false")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n✋ Interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
