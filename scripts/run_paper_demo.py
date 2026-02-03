#!/usr/bin/env python3
"""
Paper Trading Demo Runner - DEV/TEST ONLY

Generates real paper decisions and trades using the CANONICAL pipeline:
    Strategy -> TradeIntent -> Risk -> ExecutionDecision -> Trade -> Redis

This script:
- Uses the existing PaperEngine (not mocks)
- Feeds deterministic MarketSnapshots
- Publishes to real Redis streams
- Allows visual verification of /paper UI

Usage:
    python scripts/run_paper_demo.py

Requirements:
    - Redis running (localhost:6379 or REDIS_URL env var)
    - signals-api running (for UI verification)

NOT FOR PRODUCTION USE.
"""

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

# Add project paths for imports
project_root = Path(__file__).parent.parent
repo_root = project_root.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(repo_root / "shared_contracts"))

import redis.asyncio as redis

from shared_contracts import (
    Strategy,
    StrategyType,
    StrategySource,
    RiskProfile,
    MarketSnapshot,
)
from paper.engine import PaperEngine, PaperEngineConfig

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# =============================================================================
# DEMO CONFIGURATION
# =============================================================================

DEMO_CONFIG = {
    "bot_id": f"demo_bot_{uuid4().hex[:8]}",
    "account_id": f"demo_account_{uuid4().hex[:8]}",
    "user_id": "demo_user",
    "pair": "BTC/USD",
    "timeframe": "1h",
    # Risk limits (conservative for demo)
    "max_trades_per_day": 5,
    "max_position_size_usd": 100.0,
    "max_daily_loss_pct": 5.0,
    "starting_equity": 10000.0,
    # Execution settings
    "fees_bps": 10.0,
    "slippage_bps": 5.0,
}


# =============================================================================
# DETERMINISTIC PRICE DATA
# =============================================================================

def generate_ema_crossover_prices() -> list[list[float]]:
    """
    Generate deterministic price series that will trigger EMA crossovers.

    EMA Crossover uses:
    - fast_ema_period: 12
    - slow_ema_period: 26

    We need at least 29 closes (26 + 1 confirmation + 2 for crossover detection).

    Strategy:
    1. Start with downtrend (fast EMA < slow EMA)
    2. Create an upward move to cause bullish crossover
    3. Continue upward to potentially trigger another signal
    4. Optionally create a large position that exceeds limits (for rejection demo)

    Returns:
        List of [closes_list] for each snapshot
    """
    prices = []

    # Phase 1: Downtrend setup (20 bars)
    # Price slowly declining to establish fast_ema < slow_ema
    base_price = 50000.0
    for i in range(20):
        price = base_price - (i * 50)  # 50000 -> 49050
        prices.append(price)

    # Phase 2: Consolidation (5 bars)
    # Price stabilizes around 49000
    for i in range(5):
        prices.append(49000.0 + (i * 10))  # 49000 -> 49040

    # Phase 3: Bullish reversal (5 bars)
    # Strong upward move to trigger bullish crossover
    for i in range(5):
        prices.append(49100.0 + (i * 200))  # 49100 -> 49900

    # Phase 4: Continuation (5 bars)
    # Continued uptrend
    for i in range(5):
        prices.append(50000.0 + (i * 100))  # 50000 -> 50400

    # Phase 5: Pullback for potential second signal (5 bars)
    for i in range(5):
        prices.append(50400.0 - (i * 50))  # 50400 -> 50200

    # Phase 6: Strong breakout (5 bars)
    for i in range(5):
        prices.append(50200.0 + (i * 300))  # 50200 -> 51400

    return prices


def create_market_snapshots(closes: list[float], pair: str = "BTC/USD") -> list[MarketSnapshot]:
    """
    Create MarketSnapshot objects from price series.

    The EMA evaluator expects:
    - indicators['closes']: list of closing prices

    We'll create cumulative snapshots where each has all closes up to that point.
    """
    snapshots = []
    min_closes_for_ema = 29  # slow_ema(26) + confirmation(1) + 2

    for i in range(min_closes_for_ema, len(closes) + 1):
        closes_so_far = closes[:i]
        current_price = Decimal(str(closes_so_far[-1]))

        snapshot = MarketSnapshot(
            pair=pair,
            timestamp=datetime.now(timezone.utc),
            bid=current_price - Decimal("5"),
            ask=current_price + Decimal("5"),
            last_price=current_price,
            open=current_price,
            high=current_price + Decimal("50"),
            low=current_price - Decimal("50"),
            close=current_price,
            volume=Decimal("1000"),
            spread_bps=2.0,
            indicators={
                "closes": closes_so_far,
                "atr_14": 500.0,  # ATR for SL/TP calculation
            },
            regime="trending_up",
            volatility="normal",
        )
        snapshots.append(snapshot)

    return snapshots


# =============================================================================
# STRATEGY CREATION
# =============================================================================

def create_ema_strategy() -> Strategy:
    """
    Create EMA Crossover strategy with demo parameters.
    """
    return Strategy(
        strategy_id=f"ema_demo_{uuid4().hex[:8]}",
        name="EMA_Crossover_Demo",
        description="EMA 12/26 crossover strategy for paper trading demo",
        strategy_type=StrategyType.EMA_CROSSOVER,
        source=StrategySource.INDICATOR,
        parameters={
            "fast_ema_period": 12,
            "slow_ema_period": 26,
            "confirmation_bars": 1,
            "sl_pct": 2.0,
            "tp_pct": 4.0,
            "position_size_usd": 100.0,
        },
        timeframes=["1h"],
        supported_pairs=["BTC/USD"],
        risk_profile=RiskProfile(
            max_position_size_usd=DEMO_CONFIG["max_position_size_usd"],
            stop_loss_pct=2.0,
            take_profit_pct=4.0,
            max_daily_loss_usd=500.0,
            max_trades_per_day=DEMO_CONFIG["max_trades_per_day"],
            cooldown_seconds=0,
        ),
    )


# =============================================================================
# MAIN DEMO RUNNER
# =============================================================================

async def run_demo():
    """
    Run the paper trading demo.

    Pipeline: Strategy -> TradeIntent -> Risk -> ExecutionDecision -> Trade
    """
    print()
    print("=" * 70)
    print("  PAPER TRADING DEMO - DEV / TEST MODE")
    print("=" * 70)
    print()
    print("  This script uses the CANONICAL paper trading pipeline:")
    print("  Strategy -> TradeIntent -> Risk -> ExecutionDecision -> Trade")
    print()
    print("  All decisions and trades are published to Redis streams.")
    print("  Check /paper UI at http://localhost:3000/paper")
    print()
    print("=" * 70)
    print()

    # Connect to Redis
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    logger.info(f"Connecting to Redis: {redis_url}")

    try:
        redis_client = redis.from_url(redis_url, decode_responses=False)
        await redis_client.ping()
        logger.info("Redis connection established")
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        logger.error("Make sure Redis is running (e.g., in WSL: redis-server)")
        return 1

    # Create strategy
    strategy = create_ema_strategy()
    logger.info(f"Strategy: {strategy.name} ({strategy.strategy_type.value})")
    logger.info(f"Parameters: fast_ema=12, slow_ema=26, confirmation=1")

    # Create engine config
    config = PaperEngineConfig(
        bot_id=DEMO_CONFIG["bot_id"],
        account_id=DEMO_CONFIG["account_id"],
        user_id=DEMO_CONFIG["user_id"],
        strategy=strategy,
        pair=DEMO_CONFIG["pair"],
        starting_equity=DEMO_CONFIG["starting_equity"],
        max_position_size_usd=DEMO_CONFIG["max_position_size_usd"],
        max_trades_per_day=DEMO_CONFIG["max_trades_per_day"],
        max_daily_loss_pct=DEMO_CONFIG["max_daily_loss_pct"],
        fees_bps=DEMO_CONFIG["fees_bps"],
        slippage_bps=DEMO_CONFIG["slippage_bps"],
    )

    # Create paper engine
    engine = PaperEngine(redis_client=redis_client, config=config)

    logger.info(f"Bot ID: {config.bot_id}")
    logger.info(f"Account ID: {config.account_id}")
    logger.info(f"Pair: {config.pair}")
    logger.info(f"Risk Limits: max_position=${config.max_position_size_usd}, "
                f"max_trades/day={config.max_trades_per_day}, "
                f"max_daily_loss={config.max_daily_loss_pct}%")
    print()

    # Start engine
    started = await engine.start()
    if not started:
        logger.error(f"Engine failed to start: {engine.stopped_reason}")
        await redis_client.aclose()
        return 1

    logger.info("Paper engine started")
    print()
    print("-" * 70)
    print("  Processing market snapshots...")
    print("-" * 70)
    print()

    # Generate price data and snapshots
    closes = generate_ema_crossover_prices()
    snapshots = create_market_snapshots(closes, DEMO_CONFIG["pair"])

    logger.info(f"Generated {len(closes)} price points, {len(snapshots)} snapshots")
    print()

    # Stats tracking
    stats = {
        "ticks": 0,
        "signals": 0,
        "approved": 0,
        "rejected": 0,
        "trades": 0,
        "skipped": 0,
    }

    # Process snapshots
    for i, snapshot in enumerate(snapshots):
        stats["ticks"] += 1
        current_price = float(snapshot.last_price)

        # Process tick through canonical pipeline
        result = await engine.tick(snapshot)

        # Log result
        if result.blocked:
            logger.warning(f"[{i+1:02d}] BLOCKED: {result.block_reason}")
            break

        if result.skipped:
            stats["skipped"] += 1
            # Only log every 5th skip to reduce noise
            if (i + 1) % 5 == 0:
                logger.debug(f"[{i+1:02d}] Price: ${current_price:.2f} - No signal")
            continue

        # We have a signal!
        stats["signals"] += 1

        if result.decision:
            if result.decision.is_approved:
                stats["approved"] += 1
                if result.trade:
                    stats["trades"] += 1
                    logger.info(
                        f"[{i+1:02d}] APPROVED + EXECUTED | "
                        f"Price: ${current_price:.2f} | "
                        f"Side: {result.intent.side.value.upper()} | "
                        f"Trade ID: {result.trade.trade_id[:12]}..."
                    )
                else:
                    logger.info(
                        f"[{i+1:02d}] APPROVED | "
                        f"Price: ${current_price:.2f} | "
                        f"Side: {result.intent.side.value.upper()}"
                    )
            else:
                stats["rejected"] += 1
                reasons = result.decision.rejection_codes
                logger.info(
                    f"[{i+1:02d}] REJECTED | "
                    f"Price: ${current_price:.2f} | "
                    f"Side: {result.intent.side.value.upper()} | "
                    f"Reasons: {reasons}"
                )

        # Small delay between ticks for visual effect
        await asyncio.sleep(0.5)

    # Stop engine
    await engine.stop(reason="Demo complete")

    # Print summary
    print()
    print("-" * 70)
    print("  DEMO COMPLETE")
    print("-" * 70)
    print()
    print(f"  Ticks Processed:    {stats['ticks']}")
    print(f"  Signals Generated:  {stats['signals']}")
    print(f"  Approved:           {stats['approved']}")
    print(f"  Rejected:           {stats['rejected']}")
    print(f"  Trades Executed:    {stats['trades']}")
    print(f"  Skipped (no signal): {stats['skipped']}")
    print()
    print("  Check the /paper UI at: http://localhost:3000/paper")
    print()
    print("  Redis streams populated:")
    print(f"    - decisions:paper:BTC-USD")
    print(f"    - trades:paper:BTC-USD")
    print()
    print("=" * 70)
    print()

    # Cleanup
    await redis_client.aclose()

    return 0


def main():
    """Entry point."""
    print()
    print("*" * 70)
    print("*" + " " * 68 + "*")
    print("*" + "  DEV / DEMO MODE - NOT FOR PRODUCTION".center(68) + "*")
    print("*" + " " * 68 + "*")
    print("*" * 70)

    try:
        exit_code = asyncio.run(run_demo())
    except KeyboardInterrupt:
        print("\n\nDemo interrupted by user.")
        exit_code = 0
    except Exception as e:
        logger.exception(f"Demo failed: {e}")
        exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
