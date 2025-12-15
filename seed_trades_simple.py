#!/usr/bin/env python3
"""
Simple trade seeder - no complex dependencies
Publishes trades directly to Redis streams
"""
import sys
import time
import random
import json

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

try:
    import redis
except ImportError:
    print("ERROR: redis package not installed. Run: pip install redis")
    sys.exit(1)

# Redis connection
REDIS_URL = "rediss://default:&lt;REDIS_PASSWORD&gt;%2A%2A%24%24@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818"
CERT_PATH = r"C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem"

def generate_realistic_trades(count=100):
    """Generate realistic trade data with varied PnL"""

    pairs = ["BTC/USD", "ETH/USD", "SOL/USD", "AVAX/USD", "MATIC/USD", "LINK/USD"]
    sides = ["long", "short"]

    trades = []
    current_ts = int(time.time() * 1000) - (count * 60000)  # Start from 'count' minutes ago

    for i in range(count):
        pair = random.choice(pairs)
        side = random.choice(sides)

        # Generate realistic prices
        if pair == "BTC/USD":
            entry = random.uniform(42000, 48000)
            price_change_pct = random.uniform(-0.02, 0.03)  # -2% to +3%
        elif pair == "ETH/USD":
            entry = random.uniform(2200, 2800)
            price_change_pct = random.uniform(-0.025, 0.035)  # -2.5% to +3.5%
        elif pair == "SOL/USD":
            entry = random.uniform(90, 140)
            price_change_pct = random.uniform(-0.03, 0.04)  # -3% to +4%
        elif pair == "AVAX/USD":
            entry = random.uniform(35, 55)
            price_change_pct = random.uniform(-0.035, 0.045)  # -3.5% to +4.5%
        elif pair == "MATIC/USD":
            entry = random.uniform(0.7, 1.2)
            price_change_pct = random.uniform(-0.04, 0.05)  # -4% to +5%
        else:  # LINK/USD
            entry = random.uniform(12, 18)
            price_change_pct = random.uniform(-0.03, 0.04)  # -3% to +4%

        exit_price = entry * (1 + price_change_pct)

        # Position size varies
        qty = random.uniform(0.05, 0.5)

        # Calculate PnL
        if side == "long":
            pnl = (exit_price - entry) * qty
        else:
            pnl = (entry - exit_price) * qty

        # Add some commission/fees (reduces PnL slightly)
        fee = abs(entry * qty * 0.001)  # 0.1% fee
        pnl -= fee

        trade = {
            "id": f"seed_{int(time.time())}_{i:04d}",
            "ts": current_ts + (i * 60000),  # 1 minute apart
            "pair": pair,
            "side": side,
            "entry": round(entry, 2),
            "exit": round(exit_price, 2),
            "qty": round(qty, 6),
            "pnl": round(pnl, 2),
            "fee": round(fee, 2)
        }

        trades.append(trade)

    return trades

def publish_trades_to_redis(trades, client):
    """Publish trades directly to Redis stream"""

    published = 0

    print(f"\n📤 Publishing {len(trades)} trades to Redis...\n")

    for i, trade in enumerate(trades, 1):
        try:
            # Serialize trade to JSON
            trade_json = json.dumps(trade)

            # Publish to trades:closed stream
            msg_id = client.xadd(
                "trades:closed",
                {"json": trade_json},
                maxlen=10000,  # Keep last 10k trades
                approximate=True
            )

            published += 1

            # Print progress every 10 trades
            if i % 10 == 0 or i == len(trades):
                pnl_color = "🟢" if trade["pnl"] >= 0 else "🔴"
                print(f"{pnl_color} {i:3d}/{len(trades)}: {trade['pair']:9s} {trade['side']:5s} "
                      f"${trade['entry']:8,.2f} → ${trade['exit']:8,.2f} "
                      f"PnL: ${trade['pnl']:+8.2f}")

        except Exception as e:
            print(f"❌ Error publishing trade {i}: {e}")

    return published

def main():
    print("=" * 70)
    print("TRADE SEEDER - Generating Realistic PnL Data")
    print("=" * 70)

    # Connect to Redis
    print("\n1. Connecting to Redis Cloud...")
    try:
        client = redis.from_url(
            REDIS_URL,
            decode_responses=False,
            ssl_ca_certs=CERT_PATH,
            socket_connect_timeout=10,
            socket_timeout=10,
        )
        client.ping()
        print("   ✅ Connected successfully")
    except Exception as e:
        print(f"   ❌ Connection failed: {e}")
        sys.exit(1)

    # Generate trades
    print("\n2. Generating realistic trade data...")
    count = 100
    trades = generate_realistic_trades(count)

    # Calculate summary stats
    total_pnl = sum(t["pnl"] for t in trades)
    wins = sum(1 for t in trades if t["pnl"] > 0)
    losses = sum(1 for t in trades if t["pnl"] < 0)
    win_rate = (wins / count * 100) if count > 0 else 0

    print(f"   ✅ Generated {count} trades")
    print(f"   📊 Win Rate: {win_rate:.1f}% ({wins}W / {losses}L)")
    print(f"   💰 Total PnL: ${total_pnl:+,.2f}")
    print(f"   📈 Avg Winner: ${sum(t['pnl'] for t in trades if t['pnl'] > 0) / max(wins, 1):+.2f}")
    print(f"   📉 Avg Loser: ${sum(t['pnl'] for t in trades if t['pnl'] < 0) / max(losses, 1):+.2f}")

    # Publish to Redis
    print("\n3. Publishing to Redis streams...")
    published = publish_trades_to_redis(trades, client)

    # Verify
    print(f"\n4. Verifying...")
    stream_len = client.xlen(b"trades:closed")
    print(f"   ✅ Published {published} trades")
    print(f"   📊 Stream 'trades:closed' now has {stream_len} total messages")

    print("\n" + "=" * 70)
    print("✅ SUCCESS! Trades published to Redis")
    print("=" * 70)
    print("\n📋 NEXT STEPS:")
    print("\n1. Start the PnL aggregator to process these trades:")
    print("   conda activate crypto-bot")
    print("   python monitoring/pnl_aggregator.py")
    print("\n2. Check the aggregator processes all trades (watch the logs)")
    print("\n3. Verify the data:")
    print("   python check_pnl_data.py")
    print("\n4. Refresh your PnL charts - should now show a curve!")
    print("\n" + "=" * 70)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⏹️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
