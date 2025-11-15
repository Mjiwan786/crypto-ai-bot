"""
Bar Reaction System Runner

Wires together BarClock and BarReaction5M agent for production deployment.

Components:
- BarClock: Emits bar_close:5m events at precise 5-minute boundaries
- BarReaction5M: Handles events and generates signals
- Redis: Debouncing and state management

Features:
- Graceful shutdown on SIGTERM/SIGINT
- Resource cleanup
- Configuration loading from YAML
- Signal handler registration

Usage:
    python scripts/run_bar_reaction_system.py --config config/enhanced_scalper_config.yaml

Environment Variables:
    REDIS_URL: Redis Cloud connection URL (required)
    REDIS_CA_CERT: Path to CA certificate for TLS (optional)
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import redis.asyncio as redis

from agents.scheduler.bar_clock import BarClock, ClockConfig, setup_signal_handlers, BarCloseEvent
from agents.strategies.bar_reaction_5m import BarReaction5M
from config.enhanced_scalper_loader import EnhancedScalperConfigLoader


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BarReactionSystem:
    """
    Integrated system with BarClock + BarReaction5M.

    Coordinates clock events with strategy execution.
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        config: dict,
        pairs: list[str],
    ):
        """
        Initialize system.

        Args:
            redis_client: Async Redis client
            config: bar_reaction_5m configuration
            pairs: List of trading pairs
        """
        self.redis = redis_client
        self.config = config
        self.pairs = pairs

        # Create components
        self.clock = BarClock(
            redis_client=redis_client,
            pairs=pairs,
            config=ClockConfig(timeframe_minutes=5),
        )

        self.agent = BarReaction5M(
            config=config,
            redis_client=redis_client,
        )

        # Wire callbacks
        self._wire_callbacks()

        logger.info(f"BarReactionSystem initialized for {len(pairs)} pairs")

    def _wire_callbacks(self) -> None:
        """
        Register strategy callbacks with clock.

        Registers BarReaction5M.on_bar_close for each pair.
        """
        for pair in self.pairs:
            self.clock.register_callback(pair, self.agent.on_bar_close)

        logger.info(f"Wired {len(self.pairs)} callbacks to clock")

    async def run(self) -> None:
        """
        Run system (clock + strategy).

        Blocks until shutdown signal received.
        """
        logger.info("Starting BarReactionSystem")

        # Setup signal handlers for graceful shutdown
        setup_signal_handlers(self.clock)

        try:
            # Run clock (blocks until shutdown)
            await self.clock.run()

        except KeyboardInterrupt:
            logger.info("Received interrupt, shutting down")

        finally:
            await self.cleanup()

    async def cleanup(self) -> None:
        """
        Cleanup resources.

        Called on shutdown to clean up Redis, etc.
        """
        logger.info("Cleaning up system")

        # Cleanup clock
        await self.clock.cleanup()

        # Close Redis
        await self.redis.aclose()

        logger.info("Cleanup complete")


async def create_system(config_path: str, redis_url: str) -> BarReactionSystem:
    """
    Factory function to create BarReactionSystem.

    Args:
        config_path: Path to enhanced_scalper_config.yaml
        redis_url: Redis Cloud connection URL

    Returns:
        Initialized BarReactionSystem
    """
    # Load config
    loader = EnhancedScalperConfigLoader(config_path)
    full_config = loader.load_config()

    bar_reaction_config = full_config.get("bar_reaction_5m", {})

    if not bar_reaction_config.get("enabled", False):
        raise ValueError("bar_reaction_5m strategy not enabled in config")

    # Extract pairs
    pairs = bar_reaction_config.get("pairs", [])
    if not pairs:
        raise ValueError("No pairs configured for bar_reaction_5m")

    logger.info(f"Loaded config: {len(pairs)} pairs, mode={bar_reaction_config.get('mode')}")

    # Create Redis client
    redis_client = await redis.from_url(
        redis_url,
        encoding="utf-8",
        decode_responses=True,
    )

    # Test Redis connection
    try:
        await redis_client.ping()
        logger.info("Redis connection OK")
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")
        raise

    # Create system
    system = BarReactionSystem(
        redis_client=redis_client,
        config=bar_reaction_config,
        pairs=pairs,
    )

    return system


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Run bar reaction system")
    parser.add_argument(
        "--config",
        type=str,
        default="config/enhanced_scalper_config.yaml",
        help="Path to config file"
    )
    parser.add_argument(
        "--redis-url",
        type=str,
        default=os.getenv("REDIS_URL"),
        help="Redis Cloud URL (or use REDIS_URL env var)"
    )

    args = parser.parse_args()

    if not args.redis_url:
        logger.error("Redis URL not provided (use --redis-url or REDIS_URL env var)")
        sys.exit(1)

    try:
        # Create and run system
        system = await create_system(args.config, args.redis_url)
        await system.run()

    except Exception as e:
        logger.error(f"System error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
