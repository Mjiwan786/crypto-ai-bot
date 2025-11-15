"""
Seed test data.

Generates synthetic data for development and testing. Real
implementations would insert data into the bot's data stores.

⚠️ SAFETY: No live trading unless MODE=live and confirmation set.
This script is for testing only and does not execute real trades.
"""
from __future__ import annotations

import logging

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def seed() -> int:
    logger.info("Seeding test data...")
    # TODO: implement data seeding logic
    logger.info("Test data seeding complete (stub)")
    return 0


def main() -> int:
    return seed()


if __name__ == "__main__":
    raise SystemExit(main())
