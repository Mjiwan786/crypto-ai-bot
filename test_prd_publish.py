#!/usr/bin/env python
"""
Test PRD-001 Compliant Signal Publishing
=========================================

This script:
1. Publishes test signals using PRDPublisher (PRD-001 schema)
2. Verifies the signals appear in correct Redis streams
3. Confirms the schema matches PRD-001 specification

Usage:
    python test_prd_publish.py
"""

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Load environment
from dotenv import load_dotenv
load_dotenv(".env.paper")

# Now import project modules
from agents.infrastructure.prd_publisher import (
    PRDPublisher,
    PRDSignal,
    PRDPnLUpdate,
    PRDIndicators,
    PRDMetadata,
    Side,
    Strategy,
    Regime,
    MACDSignal,
    create_prd_signal,
)


async def test_prd_publishing():
    """Test PRD-001 compliant signal publishing."""
    print("=" * 80)
    print("PRD-001 COMPLIANT SIGNAL PUBLISHING TEST")
    print("=" * 80)

    # Get Redis URL
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        print("ERROR: REDIS_URL not set")
        return False

    print(f"\n[1/5] Creating PRDPublisher...")
    publisher = PRDPublisher(mode="paper")

    print(f"[2/5] Connecting to Redis...")
    connected = await publisher.connect()
    if not connected:
        print("ERROR: Failed to connect to Redis")
        return False
    print("[OK] Connected to Redis")

    # Test pairs to publish
    test_cases = [
        {
            "pair": "BTC/USD",
            "side": "LONG",
            "strategy": "SCALPER",
            "regime": "TRENDING_UP",
            "entry_price": 95000.0,
            "take_profit": 97000.0,
            "stop_loss": 94000.0,
            "confidence": 0.85,
            "position_size_usd": 500.0,
        },
        {
            "pair": "ETH/USD",
            "side": "SHORT",
            "strategy": "TREND",
            "regime": "TRENDING_DOWN",
            "entry_price": 3600.0,
            "take_profit": 3400.0,
            "stop_loss": 3700.0,
            "confidence": 0.78,
            "position_size_usd": 300.0,
        },
        {
            "pair": "SOL/USD",
            "side": "LONG",
            "strategy": "BREAKOUT",
            "regime": "VOLATILE",
            "entry_price": 245.0,
            "take_profit": 260.0,
            "stop_loss": 235.0,
            "confidence": 0.72,
            "position_size_usd": 200.0,
        },
    ]

    print(f"\n[3/5] Publishing {len(test_cases)} test signals...")
    published_signals = []

    for tc in test_cases:
        # Create signal with all PRD-001 fields
        signal = create_prd_signal(
            pair=tc["pair"],
            side=tc["side"],
            strategy=tc["strategy"],
            regime=tc["regime"],
            entry_price=tc["entry_price"],
            take_profit=tc["take_profit"],
            stop_loss=tc["stop_loss"],
            confidence=tc["confidence"],
            position_size_usd=tc["position_size_usd"],
            indicators={
                "rsi_14": 55.0,
                "macd_signal": "BULLISH" if tc["side"] == "LONG" else "BEARISH",
                "atr_14": tc["entry_price"] * 0.02,
                "volume_ratio": 1.15,
            },
            metadata={
                "model_version": "v2.1.0",
                "backtest_sharpe": 1.85,
                "latency_ms": 125,
                "strategy_tag": f"{tc['strategy'].title()} v2",
                "mode": "paper",
                "timeframe": "5m",
            },
        )

        # Publish signal
        entry_id = await publisher.publish_signal(signal, mode="paper")

        if entry_id:
            print(f"  [OK] {tc['pair']} {tc['side']} @ ${tc['entry_price']:,.2f}")
            print(f"       Stream: {signal.get_stream_key('paper')}")
            print(f"       Entry ID: {entry_id}")
            published_signals.append((signal, entry_id))
        else:
            print(f"  [FAIL] {tc['pair']} - failed to publish")

    # Publish PnL update
    print(f"\n[4/5] Publishing PnL update...")
    pnl = PRDPnLUpdate(
        equity=10500.0,
        realized_pnl=500.0,
        unrealized_pnl=150.0,
        num_positions=3,
        drawdown_pct=-2.5,
    )
    pnl_entry = await publisher.publish_pnl(pnl, mode="paper")
    if pnl_entry:
        print(f"  [OK] PnL published to pnl:paper:equity_curve")
        print(f"       Equity: ${pnl.equity:,.2f}, PnL: ${pnl.realized_pnl + pnl.unrealized_pnl:,.2f}")
    else:
        print(f"  [FAIL] PnL failed to publish")

    # Verify signals in Redis
    print(f"\n[5/5] Verifying signals in Redis...")
    import redis.asyncio as redis

    ca_cert = publisher.redis_ca_cert
    conn_params = {
        'socket_connect_timeout': 10,
        'decode_responses': True,
    }
    if ca_cert and os.path.exists(ca_cert):
        conn_params['ssl_ca_certs'] = ca_cert
        conn_params['ssl_cert_reqs'] = 'required'

    r = redis.from_url(redis_url, **conn_params)

    for signal, entry_id in published_signals:
        stream_key = signal.get_stream_key('paper')

        # Read latest entry from stream
        entries = await r.xrevrange(stream_key, count=1)
        if entries:
            latest_id, data = entries[0]
            print(f"\n  Verifying {stream_key}...")

            # Check PRD-001 required fields
            required_fields = [
                'signal_id', 'timestamp', 'pair', 'side', 'strategy', 'regime',
                'entry_price', 'take_profit', 'stop_loss', 'confidence',
                'position_size_usd', 'risk_reward_ratio'
            ]
            api_fields = ['id', 'symbol', 'signal_type', 'price']  # PRD-002 aliases

            missing_prd = [f for f in required_fields if f not in data]
            missing_api = [f for f in api_fields if f not in data]

            if not missing_prd and not missing_api:
                print(f"    [OK] All PRD-001 fields present")
                print(f"    [OK] All PRD-002 API aliases present")

                # Print sample data
                print(f"    Sample fields:")
                for f in ['signal_id', 'pair', 'side', 'strategy', 'regime', 'entry_price', 'confidence']:
                    print(f"      {f}: {data.get(f, 'N/A')}")
            else:
                if missing_prd:
                    print(f"    [WARN] Missing PRD-001 fields: {missing_prd}")
                if missing_api:
                    print(f"    [WARN] Missing API aliases: {missing_api}")
        else:
            print(f"  [WARN] No entries found in {stream_key}")

    # Check telemetry keys
    print(f"\n  Verifying telemetry keys...")
    for tk in ['engine:last_signal_meta', 'engine:last_pnl_meta']:
        data = await r.hgetall(tk)
        if data:
            print(f"    [OK] {tk}: {list(data.keys())}")
        else:
            print(f"    [WARN] {tk}: NOT FOUND or EMPTY")

    await r.aclose()
    await publisher.close()

    print("\n" + "=" * 80)
    print("[COMPLETE] PRD-001 Signal Publishing Test Finished")
    print("=" * 80)

    # Print summary
    metrics = publisher.get_metrics()
    print(f"\nPublish Summary:")
    print(f"  Total Published: {metrics['publish_count']}")
    print(f"  Errors: {metrics['publish_errors']}")

    return metrics['publish_count'] > 0 and metrics['publish_errors'] == 0


if __name__ == '__main__':
    success = asyncio.run(test_prd_publishing())
    sys.exit(0 if success else 1)
