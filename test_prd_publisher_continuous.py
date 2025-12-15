#!/usr/bin/env python3
"""
Continuous PRD-Compliant Signal Publisher Test

This script uses PRDPublisher directly to publish test signals continuously
for 10 minutes, simulating what the engine should do.
"""

import asyncio
import os
import sys
import time
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

load_dotenv(project_root / ".env.paper", override=False)
load_dotenv(project_root / ".env.prod", override=False)

from agents.infrastructure.prd_publisher import PRDPublisher, PRDSignal, PRDIndicators, PRDMetadata
from agents.infrastructure.prd_publisher import PRDPnLUpdate
import random

MODE = os.getenv("ENGINE_MODE", "paper")
DURATION_SECONDS = 10 * 60  # 10 minutes
SIGNAL_INTERVAL = 30  # Publish signal every 30 seconds
PNL_INTERVAL = 60  # Publish PnL every 60 seconds

TRADING_PAIRS = ["BTC/USD", "ETH/USD", "SOL/USD"]
STRATEGIES = ["SCALPER", "TREND", "MEAN_REVERSION", "BREAKOUT"]
REGIMES = ["TRENDING_UP", "TRENDING_DOWN", "RANGING", "VOLATILE"]
SIDES = ["LONG", "SHORT"]


async def publish_continuous_signals():
    """Publish PRD-compliant signals continuously"""
    
    print("=" * 80)
    print("CONTINUOUS PRD-COMPLIANT SIGNAL PUBLISHER")
    print("=" * 80)
    print(f"Mode: {MODE}")
    print(f"Duration: {DURATION_SECONDS // 60} minutes")
    print(f"Signal interval: {SIGNAL_INTERVAL} seconds")
    print(f"PnL interval: {PNL_INTERVAL} seconds")
    print(f"Start time: {datetime.now(timezone.utc).isoformat()}")
    print()
    
    # Create publisher
    publisher = PRDPublisher(mode=MODE)
    
    try:
        # Connect to Redis
        print("Connecting to Redis...")
        await publisher.connect()
        print("[OK] Connected to Redis")
        print()
        
        start_time = time.time()
        signal_count = 0
        pnl_count = 0
        last_signal_time = 0
        last_pnl_time = 0
        
        # Initial equity
        current_equity = 10000.0
        realized_pnl = 0.0
        
        print("=" * 80)
        print("PUBLISHING SIGNALS AND PNL")
        print("=" * 80)
        print()
        
        while (time.time() - start_time) < DURATION_SECONDS:
            current_time = time.time()
            elapsed = current_time - start_time
            
            # Publish signal if interval has passed
            if (current_time - last_signal_time) >= SIGNAL_INTERVAL:
                pair = random.choice(TRADING_PAIRS)
                side = random.choice(SIDES)
                strategy = random.choice(STRATEGIES)
                regime = random.choice(REGIMES)
                
                # Generate realistic prices
                if "BTC" in pair:
                    base_price = 50000.0
                elif "ETH" in pair:
                    base_price = 3000.0
                else:
                    base_price = 100.0
                
                entry_price = base_price * (1 + random.uniform(-0.02, 0.02))
                
                if side == "LONG":
                    take_profit = entry_price * 1.02
                    stop_loss = entry_price * 0.98
                else:
                    take_profit = entry_price * 0.98
                    stop_loss = entry_price * 1.02
                
                signal = PRDSignal(
                    pair=pair,
                    side=side,
                    strategy=strategy,
                    regime=regime,
                    entry_price=entry_price,
                    take_profit=take_profit,
                    stop_loss=stop_loss,
                    confidence=random.uniform(0.6, 0.95),
                    position_size_usd=random.uniform(100.0, 500.0),
                    indicators=PRDIndicators(
                        rsi_14=random.uniform(30, 70),
                        macd_signal=random.choice(["BULLISH", "BEARISH", "NEUTRAL"]),
                        atr_14=base_price * 0.01,
                        volume_ratio=random.uniform(0.8, 1.5),
                    ),
                    metadata=PRDMetadata(
                        model_version="v2.1.0",
                        backtest_sharpe=random.uniform(1.5, 2.5),
                        latency_ms=random.randint(50, 200),
                        strategy_tag=f"{strategy} v2",
                        mode=MODE,
                        timeframe="5m",
                    ),
                )
                
                entry_id = await publisher.publish_signal(signal)
                if entry_id:
                    signal_count += 1
                    last_signal_time = current_time
                    print(f"[{int(elapsed)}s] Published signal #{signal_count}: {pair} {side} @ ${entry_price:.2f} (ID: {entry_id[:20]}...)")
            
            # Publish PnL if interval has passed
            if (current_time - last_pnl_time) >= PNL_INTERVAL:
                # Simulate PnL changes
                realized_pnl += random.uniform(-50.0, 100.0)
                current_equity = 10000.0 + realized_pnl
                
                pnl = PRDPnLUpdate(
                    equity=current_equity,
                    realized_pnl=realized_pnl,
                    unrealized_pnl=random.uniform(-20.0, 50.0),
                    num_positions=random.randint(0, 3),
                    drawdown_pct=min(0.0, (realized_pnl / 10000.0) * 100),
                )
                
                entry_id = await publisher.publish_pnl(pnl)
                if entry_id:
                    pnl_count += 1
                    last_pnl_time = current_time
                    print(f"[{int(elapsed)}s] Published PnL #{pnl_count}: Equity=${current_equity:.2f}, Realized=${realized_pnl:.2f} (ID: {entry_id[:20]}...)")
            
            # Sleep briefly
            await asyncio.sleep(1)
        
        print()
        print("=" * 80)
        print("PUBLISHING COMPLETE")
        print("=" * 80)
        print(f"Total signals published: {signal_count}")
        print(f"Total PnL updates published: {pnl_count}")
        print(f"Duration: {DURATION_SECONDS // 60} minutes")
        print(f"End time: {datetime.now(timezone.utc).isoformat()}")
        print()
        print("✅ Signals and PnL data are ready for signals-api consumption")
        
    except KeyboardInterrupt:
        print("\n\n[INTERRUPT] Publishing interrupted by user")
    except Exception as e:
        print(f"\n[ERROR] Failed to publish: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        await publisher.close()


if __name__ == "__main__":
    asyncio.run(publish_continuous_signals())

