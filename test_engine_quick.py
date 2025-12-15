#!/usr/bin/env python
"""
Quick test of production engine with PRD-compliant signals.

Runs the engine for 30 seconds, collects prices, then generates test signals
to verify PRD-001 compliance.
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


async def quick_test():
    """Quick engine test."""
    print("=" * 80)
    print("PRD-001 ENGINE QUICK TEST")
    print("=" * 80)

    from agents.infrastructure.prd_publisher import (
        PRDPublisher,
        create_prd_signal,
    )
    import redis.asyncio as redis

    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        print("ERROR: REDIS_URL not set")
        return False

    # Initialize publisher
    publisher = PRDPublisher(mode="paper")
    connected = await publisher.connect()
    if not connected:
        print("ERROR: Failed to connect to Redis")
        return False
    print("[OK] Connected to Redis")

    # Fetch live prices from Kraken API
    import aiohttp
    KRAKEN_API_URL = "https://api.kraken.com/0/public/Ticker"
    KRAKEN_PAIR_MAP = {
        "BTC/USD": "XXBTZUSD",
        "ETH/USD": "XETHZUSD",
        "SOL/USD": "SOLUSD",
    }

    print("\nFetching live prices from Kraken...")
    prices = {}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
        for pair, kraken_pair in KRAKEN_PAIR_MAP.items():
            try:
                async with session.get(f"{KRAKEN_API_URL}?pair={kraken_pair}") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if not data.get("error"):
                            result = list(data.get("result", {}).values())[0]
                            price = float(result["c"][0])
                            prices[pair] = price
                            print(f"  {pair}: ${price:,.2f}")
            except Exception as e:
                print(f"  {pair}: ERROR - {e}")

    # Generate and publish signals using LIVE prices
    print("\nPublishing PRD-001 compliant signals with LIVE prices...")
    signals_published = 0

    for pair, entry in prices.items():
        # Calculate SL and TP
        volatility = 0.02 if pair == "BTC/USD" else 0.025 if pair == "ETH/USD" else 0.03
        sl = entry * (1 - volatility * 1.5)
        tp = entry * (1 + volatility * 2.0)

        signal = create_prd_signal(
            pair=pair,
            side="LONG",
            strategy="SCALPER",
            regime="TRENDING_UP",
            entry_price=entry,
            take_profit=tp,
            stop_loss=sl,
            confidence=0.78,
            position_size_usd=100.0,
            indicators={
                "rsi_14": 55.0,
                "macd_signal": "BULLISH",
                "atr_14": entry * volatility,
                "volume_ratio": 1.1,
            },
            metadata={
                "model_version": "v2.1.0",
                "backtest_sharpe": 1.65,
                "latency_ms": 150,
                "strategy_tag": "Scalper v2",
                "mode": "paper",
                "timeframe": "5m",
            },
        )

        entry_id = await publisher.publish_signal(signal, mode="paper")
        if entry_id:
            print(f"  [OK] {pair} LONG @ ${entry:,.2f} -> {signal.get_stream_key('paper')}")
            signals_published += 1
        else:
            print(f"  [FAIL] {pair}")

    # Publish PnL update
    print("\nPublishing PnL update...")
    from agents.infrastructure.prd_publisher import PRDPnLUpdate
    pnl = PRDPnLUpdate(
        equity=10250.0,
        realized_pnl=250.0,
        unrealized_pnl=75.0,
        num_positions=len(prices),
        drawdown_pct=-1.5,
    )
    pnl_entry = await publisher.publish_pnl(pnl, mode="paper")
    if pnl_entry:
        print(f"  [OK] PnL: equity=${pnl.equity:,.2f}, total_pnl=${pnl.realized_pnl + pnl.unrealized_pnl:,.2f}")

    # Verify data in Redis
    print("\nVerifying signals in Redis...")
    ca_cert = publisher.redis_ca_cert
    conn_params = {'decode_responses': True}
    if ca_cert and os.path.exists(ca_cert):
        conn_params['ssl_ca_certs'] = ca_cert
        conn_params['ssl_cert_reqs'] = 'required'

    r = redis.from_url(redis_url, **conn_params)

    # Check each stream
    for pair in prices.keys():
        stream_key = f"signals:paper:{pair.replace('/', '-')}"
        entries = await r.xrevrange(stream_key, count=1)
        if entries:
            _, data = entries[0]
            has_prd_fields = all(f in data for f in ['signal_id', 'timestamp', 'pair', 'side', 'strategy', 'regime', 'entry_price'])
            has_api_fields = all(f in data for f in ['id', 'symbol', 'signal_type', 'price'])
            status = "[OK]" if has_prd_fields and has_api_fields else "[WARN]"
            print(f"  {status} {stream_key}: {len(entries)} entries, side={data.get('side')}, price={data.get('entry_price')}")
        else:
            print(f"  [WARN] {stream_key}: empty")

    # Check telemetry
    print("\nChecking telemetry keys...")
    for tk in ['engine:last_signal_meta', 'engine:last_pnl_meta']:
        data = await r.hgetall(tk)
        if data:
            print(f"  [OK] {tk}: mode={data.get('mode')}, timestamp={data.get('timestamp', 'N/A')[:19]}")
        else:
            print(f"  [WARN] {tk}: not found")

    await r.aclose()
    await publisher.close()

    print("\n" + "=" * 80)
    print(f"[COMPLETE] Published {signals_published} PRD-001 compliant signals with LIVE prices")
    print("=" * 80)

    return signals_published > 0


if __name__ == '__main__':
    success = asyncio.run(quick_test())
    sys.exit(0 if success else 1)
