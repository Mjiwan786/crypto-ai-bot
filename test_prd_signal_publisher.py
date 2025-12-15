#!/usr/bin/env python3
"""
Test PRD-001 Compliant Signal Publisher

This script publishes a few test signals using the PRDPublisher to verify
that PRD-compliant signals can be published and consumed by signals-api.

Usage:
    conda activate crypto-bot
    python test_prd_signal_publisher.py
"""

import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from agents.infrastructure.prd_publisher import PRDPublisher, PRDSignal, PRDIndicators, PRDMetadata

# Load environment
load_dotenv(".env.paper", override=False)
load_dotenv(".env.prod", override=False)


async def publish_test_signals():
    """Publish a few PRD-compliant test signals"""
    
    # Get mode from environment
    mode = os.getenv("ENGINE_MODE", "paper")
    print(f"Mode: {mode}")
    print("=" * 80)
    
    # Create publisher
    publisher = PRDPublisher(mode=mode)
    
    try:
        # Connect to Redis
        print("Connecting to Redis...")
        await publisher.connect()
        print("[OK] Connected to Redis")
        
        # Test pairs
        test_pairs = ["BTC/USD", "ETH/USD"]
        
        for pair in test_pairs:
            print(f"\nPublishing test signal for {pair}...")
            
            # Create PRD-compliant signal
            signal = PRDSignal(
                pair=pair,
                side="LONG",
                strategy="SCALPER",
                regime="TRENDING_UP",
                entry_price=50000.0 if "BTC" in pair else 3000.0,
                take_profit=51000.0 if "BTC" in pair else 3100.0,
                stop_loss=49000.0 if "BTC" in pair else 2900.0,
                confidence=0.75,
                position_size_usd=150.0,
                indicators=PRDIndicators(
                    rsi_14=58.5,
                    macd_signal="BULLISH",
                    atr_14=425.80,
                    volume_ratio=1.23,
                ),
                metadata=PRDMetadata(
                    model_version="v2.1.0",
                    backtest_sharpe=1.85,
                    latency_ms=127,
                    strategy_tag="Scalper v2",
                    mode=mode,
                    timeframe="5m",
                ),
            )
            
            # Publish signal
            entry_id = await publisher.publish_signal(signal)
            
            if entry_id:
                print(f"  [OK] Published signal to {signal.get_stream_key(mode)}")
                print(f"  Entry ID: {entry_id}")
                print(f"  Signal ID: {signal.signal_id}")
                print(f"  Pair: {signal.pair}")
                print(f"  Side: {signal.side}")
                print(f"  Strategy: {signal.strategy}")
                print(f"  Entry Price: ${signal.entry_price:.2f}")
                print(f"  Confidence: {signal.confidence:.2%}")
            else:
                print(f"  [ERROR] Failed to publish signal")
        
        print("\n" + "=" * 80)
        print("Test signals published successfully!")
        print("\nRun verify_prd_compliance.py to verify the signals are PRD-compliant")
        
    except Exception as e:
        print(f"\n[ERROR] Failed to publish signals: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    finally:
        await publisher.close()


if __name__ == "__main__":
    asyncio.run(publish_test_signals())

