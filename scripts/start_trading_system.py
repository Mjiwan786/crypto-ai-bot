#!/usr/bin/env python3
"""
Crypto AI Bot - Trading System Startup Script

⚠️ LIVE TRADING WARNING:
This script can execute REAL trades with REAL money. Live trading requires:
- MODE=live (or --mode live)
- LIVE_TRADING_CONFIRMATION="I-accept-the-risk"
- Valid Kraken API credentials
- Proper risk management configuration

Paper trading (default) executes simulated trades only.

Usage examples:
  # Paper trading (default)
  python scripts/start_trading_system.py --mode paper

  # Live trading (requires confirmation)
  export MODE=live
  export LIVE_TRADING_CONFIRMATION="I-accept-the-risk"
  python scripts/start_trading_system.py --mode live

  # Dry run (validate only, don't start)
  python scripts/start_trading_system.py --mode paper --dry-run

  # Start with specific strategy
  python scripts/start_trading_system.py --mode paper --strategy momentum

  # Start with monitoring exporter
  python scripts/start_trading_system.py --mode paper --exporter
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Optional

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import system components
from config.unified_config_loader import get_config_loader
from orchestration.master_orchestrator import MasterOrchestrator

logger = logging.getLogger(__name__)

# --- Constants ---
READY = 0
NOT_READY = 1

REQUIRED_LIVE_CONFIRMATION = "I-accept-the-risk"


# --- Setup Functions ---


def setup_logging(mode: str, debug: bool = False) -> None:
    """Setup logging configuration"""
    level = logging.DEBUG if debug else logging.INFO

    # Create logs directory
    logs_dir = project_root / "logs"
    logs_dir.mkdir(exist_ok=True)

    # Configure logging
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(logs_dir / f"trading_system_{mode}.log"),
        ],
    )


def validate_live_mode() -> bool:
    """
    Validate live trading mode requirements.

    Returns:
        True if validation passes, False otherwise
    """
    logger.info("🔍 Validating live trading requirements...")

    issues = []

    # Check MODE environment variable
    mode = os.getenv("MODE")
    if mode != "live":
        issues.append("MODE environment variable must be 'live'")

    # Check LIVE_TRADING_CONFIRMATION
    confirmation = os.getenv("LIVE_TRADING_CONFIRMATION")
    if confirmation != REQUIRED_LIVE_CONFIRMATION:
        issues.append(
            f"LIVE_TRADING_CONFIRMATION must be '{REQUIRED_LIVE_CONFIRMATION}'"
        )

    # Check Kraken credentials
    kraken_key = os.getenv("KRAKEN_API_KEY")
    kraken_secret = os.getenv("KRAKEN_API_SECRET")

    if not kraken_key or not kraken_secret:
        issues.append("KRAKEN_API_KEY and KRAKEN_API_SECRET must be set")
    elif len(kraken_key) < 20 or len(kraken_secret) < 20:
        issues.append("Kraken credentials appear invalid (too short)")

    # Check Redis URL
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        issues.append("REDIS_URL must be set")

    if issues:
        logger.error("❌ Live trading validation failed:")
        for issue in issues:
            logger.error(f"   - {issue}")
        logger.error("")
        logger.error("Live trading is DISABLED for safety.")
        logger.error("Fix the issues above and try again.")
        return False

    logger.warning("⚠️  LIVE TRADING MODE ENABLED")
    logger.warning("⚠️  Real trades will be executed with real money")
    logger.warning("⚠️  Ensure risk management is properly configured")
    logger.info("✅ Live trading validation passed")

    return True


def mask_sensitive_value(key: str, value: str) -> str:
    """
    Mask sensitive configuration values.

    Args:
        key: Configuration key
        value: Configuration value

    Returns:
        Masked value
    """
    sensitive_keys = [
        "api_key",
        "api_secret",
        "password",
        "secret",
        "token",
        "credential",
    ]

    if any(sensitive in key.lower() for sensitive in sensitive_keys):
        if len(value) > 8:
            return f"{value[:4]}...{value[-4:]}"
        else:
            return "***"

    return value


def print_effective_config(config: dict) -> None:
    """
    Print effective configuration (with sensitive values masked).

    Args:
        config: Configuration dictionary
    """
    logger.info("=" * 60)
    logger.info("EFFECTIVE CONFIGURATION")
    logger.info("=" * 60)

    for key, value in sorted(config.items()):
        masked_value = mask_sensitive_value(key, str(value))
        logger.info(f"  {key}: {masked_value}")

    logger.info("=" * 60)
    logger.info("")


# --- Main System Manager ---


class TradingSystemManager:
    """Manages the complete trading system lifecycle"""

    def __init__(
        self,
        mode: str,
        config_path: str = "config/settings.yaml",
        strategy: Optional[str] = None,
        start_exporter: bool = False,
    ):
        self.mode = mode
        self.config_path = config_path
        self.strategy = strategy
        self.start_exporter = start_exporter
        self.orchestrator: Optional[MasterOrchestrator] = None
        self.running = False

    async def initialize(self) -> bool:
        """
        Initialize trading system.

        Returns:
            True if initialization successful, False otherwise
        """
        logger.info("🚀 Initializing trading system...")
        logger.info(f"   Mode: {self.mode}")
        logger.info(f"   Config: {self.config_path}")
        if self.strategy:
            logger.info(f"   Strategy: {self.strategy}")
        logger.info("")

        try:
            # Validate live mode if required
            if self.mode == "live":
                if not validate_live_mode():
                    return False

            # Load configuration
            logger.info("📋 Loading configuration...")
            config_loader = get_config_loader()

            environment = self.mode
            if self.mode == "paper":
                environment = "staging"  # Paper mode uses staging config
            elif self.mode == "live":
                environment = "production"

            system_config = config_loader.load_system_config(environment=environment)

            # Validate configuration
            issues = config_loader.validate_configuration(system_config)
            if issues:
                logger.error("❌ Configuration validation failed:")
                for issue in issues:
                    logger.error(f"   - {issue}")
                return False

            logger.info("✅ Configuration loaded and validated")
            logger.info("")

            # Print effective configuration
            config_summary = config_loader.get_config_summary(system_config)
            print_effective_config(config_summary)

            # Initialize orchestrator
            logger.info("🔧 Initializing master orchestrator...")
            self.orchestrator = MasterOrchestrator(config_path=self.config_path)

            if not await self.orchestrator.initialize():
                logger.error("❌ Failed to initialize orchestrator")
                return False

            logger.info("✅ Master orchestrator initialized")
            logger.info("")

            return True

        except Exception as e:
            logger.error(f"❌ Initialization failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def start(self) -> bool:
        """
        Start trading system.

        Returns:
            True if start successful, False otherwise
        """
        logger.info("▶️  Starting trading system...")

        try:
            if not self.orchestrator:
                logger.error("❌ Orchestrator not initialized")
                return False

            # Start orchestrator
            await self.orchestrator.start()
            self.running = True

            logger.info("✅ Trading system started successfully")
            logger.info("")
            logger.info("=" * 60)
            logger.info("TRADING SYSTEM IS NOW RUNNING")
            logger.info("=" * 60)
            logger.info(f"Mode: {self.mode.upper()}")
            logger.info("Press Ctrl+C to stop gracefully")
            logger.info("=" * 60)
            logger.info("")

            return True

        except Exception as e:
            logger.error(f"❌ Failed to start trading system: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def stop(self) -> None:
        """Stop trading system gracefully"""
        if not self.running:
            return

        logger.info("")
        logger.info("=" * 60)
        logger.info("STOPPING TRADING SYSTEM")
        logger.info("=" * 60)

        try:
            if self.orchestrator:
                logger.info("🛑 Stopping orchestrator...")
                await self.orchestrator.stop()
                self.orchestrator = None

            self.running = False
            logger.info("✅ Trading system stopped successfully")

        except Exception as e:
            logger.error(f"❌ Error stopping trading system: {e}")

    async def run(self) -> int:
        """
        Run trading system (initialize, start, and wait).

        Returns:
            Exit code (0=success, 1=failure)
        """
        try:
            # Initialize
            if not await self.initialize():
                return NOT_READY

            # Start
            if not await self.start():
                return NOT_READY

            # Setup signal handlers
            def signal_handler(signum, frame):
                logger.info(f"Received signal {signum}, initiating shutdown...")
                asyncio.create_task(self.stop())

            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)

            # Keep running
            try:
                while self.running:
                    await asyncio.sleep(1)
            except KeyboardInterrupt:
                logger.info("Received keyboard interrupt")

            # Stop
            await self.stop()

            return READY

        except Exception as e:
            logger.error(f"❌ Trading system failed: {e}")
            import traceback
            traceback.print_exc()
            await self.stop()
            return NOT_READY


# --- Main Entry Point ---


async def async_main(args: argparse.Namespace) -> int:
    """Async main entry point"""

    # Setup logging
    setup_logging(args.mode, debug=args.debug)

    logger.info("=" * 60)
    logger.info("CRYPTO AI BOT - TRADING SYSTEM")
    logger.info("=" * 60)
    logger.info("")

    # Dry run mode
    if args.dry_run:
        logger.info("🔍 DRY RUN MODE - Configuration validation only")
        logger.info("")

        # Just validate configuration
        try:
            config_loader = get_config_loader()
            environment = "staging" if args.mode == "paper" else "production"
            system_config = config_loader.load_system_config(environment=environment)

            issues = config_loader.validate_configuration(system_config)
            if issues:
                logger.error("❌ Configuration validation failed:")
                for issue in issues:
                    logger.error(f"   - {issue}")
                return NOT_READY

            logger.info("✅ Configuration validation passed")
            logger.info("✅ Dry run completed successfully")
            return READY

        except Exception as e:
            logger.error(f"❌ Dry run failed: {e}")
            return NOT_READY

    # Normal mode - start trading system
    manager = TradingSystemManager(
        mode=args.mode,
        config_path=args.config,
        strategy=args.strategy,
        start_exporter=args.exporter,
    )

    return await manager.run()


def main() -> int:
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Crypto AI Bot Trading System Startup",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Paper trading (default)
  python scripts/start_trading_system.py --mode paper

  # Live trading (requires confirmation)
  export MODE=live
  export LIVE_TRADING_CONFIRMATION="I-accept-the-risk"
  python scripts/start_trading_system.py --mode live

  # Dry run (validate only)
  python scripts/start_trading_system.py --mode paper --dry-run

  # Start with specific strategy
  python scripts/start_trading_system.py --mode paper --strategy momentum
        """,
    )

    parser.add_argument(
        "--mode",
        choices=["paper", "live"],
        default="paper",
        help="Trading mode (paper=simulated, live=real money)",
    )

    parser.add_argument(
        "--config",
        default="config/settings.yaml",
        help="Configuration file path",
    )

    parser.add_argument(
        "--strategy",
        choices=["breakout", "momentum", "mean_reversion", "regime_router"],
        help="Specific strategy to run",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate configuration only, don't start system",
    )

    parser.add_argument(
        "--exporter",
        action="store_true",
        help="Start Prometheus metrics exporter",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    try:
        return asyncio.run(async_main(args))
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user")
        return NOT_READY
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return NOT_READY


if __name__ == "__main__":
    raise SystemExit(main())
