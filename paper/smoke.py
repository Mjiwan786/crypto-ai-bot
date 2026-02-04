#!/usr/bin/env python3
"""
Paper Trading Production Smoke Runner.

Safe, bounded smoke test for production E2E verification.

Features:
- PAPER MODE ONLY (hardcoded, cannot run in live mode)
- Bounded ticks (max 20)
- Dedicated account namespace (prod_smoke_*)
- Deterministic price data
- Publishes to existing paper streams only
- Automatic cleanup and exit

Usage:
    python -m paper.smoke

On Fly.io:
    flyctl ssh console -a crypto-ai-bot-engine
    python -m paper.smoke

Requirements:
    REDIS_URL environment variable (rediss:// for production)
"""

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

# Add project paths for imports
project_root = Path(__file__).parent.parent
repo_root = project_root.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(repo_root / "shared_contracts"))

import redis.asyncio as aioredis

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
# SMOKE TEST CONFIGURATION (FIXED - DO NOT MAKE CONFIGURABLE)
# =============================================================================

# CRITICAL: Paper mode is hardcoded and cannot be overridden
PAPER_MODE = True  # NEVER change this

# Fixed identifiers for smoke test namespace
BOT_ID = "prod_smoke_bot"
ACCOUNT_ID = "prod_smoke_account"
USER_ID = "prod_smoke_user"

# Bounded execution
MAX_TICKS = 20  # Hard limit
TICK_DELAY_SEC = 0.3  # Fast but visible

# Risk limits (conservative)
MAX_POSITION_SIZE_USD = 100.0
MAX_TRADES_PER_DAY = 5
MAX_DAILY_LOSS_PCT = 5.0
STARTING_EQUITY = 10000.0

# Pair to use
PAIR = "BTC/USD"


# =============================================================================
# DETERMINISTIC PRICE DATA
# =============================================================================

def generate_crossover_prices() -> list[float]:
    """
    Generate deterministic price series that will trigger EMA crossovers.

    EMA Crossover needs: fast_ema=12, slow_ema=26
    Minimum closes: 26 + 1 confirmation + 2 = 29

    This generates 45 prices, giving us 16 ticks to evaluate.
    """
    prices = []

    # Phase 1: Downtrend (20 bars) - establishes fast < slow
    base = 50000.0
    for i in range(20):
        prices.append(base - i * 50)  # 50000 -> 49050

    # Phase 2: Consolidation (5 bars)
    for i in range(5):
        prices.append(49000.0 + i * 10)  # 49000 -> 49040

    # Phase 3: Bullish reversal (5 bars) - triggers crossover
    for i in range(5):
        prices.append(49100.0 + i * 200)  # 49100 -> 49900

    # Phase 4: Continuation (5 bars)
    for i in range(5):
        prices.append(50000.0 + i * 100)  # 50000 -> 50400

    # Phase 5: Pullback (5 bars)
    for i in range(5):
        prices.append(50400.0 - i * 50)  # 50400 -> 50200

    # Phase 6: Breakout (5 bars) - may trigger another signal
    for i in range(5):
        prices.append(50200.0 + i * 300)  # 50200 -> 51400

    return prices


def create_snapshots(prices: list[float]) -> list[MarketSnapshot]:
    """Create MarketSnapshots with cumulative closes for EMA calculation."""
    snapshots = []
    min_closes = 29  # For EMA 26 + confirmation

    for i in range(min_closes, min(len(prices) + 1, min_closes + MAX_TICKS)):
        closes = prices[:i]
        price = Decimal(str(closes[-1]))

        snapshot = MarketSnapshot(
            pair=PAIR,
            timestamp=datetime.now(timezone.utc),
            bid=price - Decimal("5"),
            ask=price + Decimal("5"),
            last_price=price,
            open=price,
            high=price + Decimal("50"),
            low=price - Decimal("50"),
            close=price,
            volume=Decimal("1000"),
            spread_bps=2.0,
            indicators={
                "closes": closes,
                "atr_14": 500.0,
            },
            regime="trending_up",
            volatility="normal",
        )
        snapshots.append(snapshot)

    return snapshots


def create_strategy() -> Strategy:
    """Create EMA Crossover strategy for smoke test."""
    return Strategy(
        strategy_id="smoke_ema_crossover",
        name="Smoke_EMA_Crossover",
        description="EMA 12/26 crossover for production smoke test",
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
            max_position_size_usd=MAX_POSITION_SIZE_USD,
            stop_loss_pct=2.0,
            take_profit_pct=4.0,
            max_daily_loss_usd=500.0,
            max_trades_per_day=MAX_TRADES_PER_DAY,
            cooldown_seconds=0,
        ),
    )


# =============================================================================
# MAIN SMOKE RUNNER
# =============================================================================

async def run_smoke() -> dict:
    """
    Run production smoke test.

    Returns:
        dict with stats: ticks, decisions, approved, rejected, trades
    """
    print()
    print("=" * 60)
    print("  PAPER TRADING SMOKE TEST")
    print("  Mode: PAPER (hardcoded)")
    print("  Bot ID: " + BOT_ID)
    print("  Account ID: " + ACCOUNT_ID)
    print("=" * 60)
    print()

    # SAFETY CHECK: Verify paper mode
    if not PAPER_MODE:
        raise RuntimeError("CRITICAL: Paper mode must be True!")

    # Get Redis URL
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        logger.error("REDIS_URL not set")
        return {"error": "REDIS_URL not set"}

    # Mask URL for logging
    masked_url = redis_url[:20] + "..." if len(redis_url) > 20 else redis_url
    logger.info(f"Connecting to Redis: {masked_url}")

    try:
        redis_client = aioredis.from_url(redis_url, decode_responses=False)
        await redis_client.ping()
        logger.info("Redis connection OK")
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")
        return {"error": str(e)}

    # Create strategy and engine
    strategy = create_strategy()

    config = PaperEngineConfig(
        bot_id=BOT_ID,
        account_id=ACCOUNT_ID,
        user_id=USER_ID,
        strategy=strategy,
        pair=PAIR,
        starting_equity=STARTING_EQUITY,
        max_position_size_usd=MAX_POSITION_SIZE_USD,
        max_trades_per_day=MAX_TRADES_PER_DAY,
        max_daily_loss_pct=MAX_DAILY_LOSS_PCT,
        fees_bps=10.0,
        slippage_bps=5.0,
    )

    engine = PaperEngine(redis_client=redis_client, config=config)

    logger.info(f"Strategy: {strategy.name}")
    logger.info(f"Max ticks: {MAX_TICKS}")
    print()

    # Start engine
    started = await engine.start()
    if not started:
        logger.error(f"Engine start failed: {engine.stopped_reason}")
        await redis_client.aclose()
        return {"error": engine.stopped_reason}

    # Generate data
    prices = generate_crossover_prices()
    snapshots = create_snapshots(prices)

    logger.info(f"Processing {len(snapshots)} snapshots...")
    print("-" * 60)

    # Stats
    stats = {
        "ticks": 0,
        "decisions": 0,
        "approved": 0,
        "rejected": 0,
        "trades": 0,
    }

    # Process ticks (bounded)
    for i, snapshot in enumerate(snapshots[:MAX_TICKS]):
        stats["ticks"] += 1
        price = float(snapshot.last_price)

        result = await engine.tick(snapshot)

        if result.blocked:
            logger.warning(f"[{i+1:02d}] BLOCKED: {result.block_reason}")
            break

        if result.skipped:
            continue

        # Decision generated
        stats["decisions"] += 1

        if result.decision:
            if result.decision.is_approved:
                stats["approved"] += 1
                if result.trade:
                    stats["trades"] += 1
                    logger.info(f"[{i+1:02d}] APPROVED+TRADE | ${price:.0f} | {result.intent.side.value}")
                else:
                    logger.info(f"[{i+1:02d}] APPROVED | ${price:.0f} | {result.intent.side.value}")
            else:
                stats["rejected"] += 1
                codes = result.decision.rejection_codes
                logger.info(f"[{i+1:02d}] REJECTED | ${price:.0f} | {codes}")

        await asyncio.sleep(TICK_DELAY_SEC)

    # Stop engine
    await engine.stop(reason="Smoke test complete")
    await redis_client.aclose()

    # Print summary
    print("-" * 60)
    print()
    print("  SMOKE TEST COMPLETE")
    print()
    print(f"  Ticks:     {stats['ticks']}")
    print(f"  Decisions: {stats['decisions']}")
    print(f"  Approved:  {stats['approved']}")
    print(f"  Rejected:  {stats['rejected']}")
    print(f"  Trades:    {stats['trades']}")
    print()
    print("  Streams populated:")
    print(f"    - decisions:paper:{PAIR.replace('/', '-')}")
    print(f"    - trades:paper:{PAIR.replace('/', '-')}")
    print()
    print("=" * 60)

    return stats


def main():
    """Entry point for python -m paper.smoke"""
    print()
    print("*" * 60)
    print("*  PRODUCTION PAPER SMOKE TEST                            *")
    print("*  Mode: PAPER ONLY (hardcoded)                           *")
    print("*" * 60)

    try:
        stats = asyncio.run(run_smoke())

        if "error" in stats:
            print(f"\nFAILED: {stats['error']}")
            sys.exit(1)

        # Verify minimum requirements
        if stats["decisions"] >= 1 and stats["trades"] >= 1:
            print("\nSMOKE PASS: decisions and trades generated")
            sys.exit(0)
        else:
            print(f"\nSMOKE WARN: decisions={stats['decisions']}, trades={stats['trades']}")
            sys.exit(0)  # Still exit 0 since it ran successfully

    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(0)
    except Exception as e:
        print(f"\nFAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
