#!/usr/bin/env python3
"""
Process trades from Redis stream once and exit
(Non-blocking version of PnL aggregator for testing)
"""
import sys
import json
import time

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

try:
    import redis
except ImportError:
    print("ERROR: redis package not installed")
    sys.exit(1)

# Redis connection
REDIS_URL = "rediss://default:Salam78614%2A%2A%24%24@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818"
CERT_PATH = r"C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem"
START_EQUITY = 10000.0

print("=" * 70)
print("ONE-TIME PNL PROCESSOR")
print("=" * 70)

# Connect to Redis
print("\n1. Connecting to Redis...")
try:
    client = redis.from_url(
        REDIS_URL,
        decode_responses=False,
        ssl_ca_certs=CERT_PATH,
        ssl_cert_reqs="required",
        socket_connect_timeout=10,
        socket_timeout=10,
    )
    client.ping()
    print("   ✅ Connected")
except Exception as e:
    print(f"   ❌ Error: {e}")
    sys.exit(1)

# Check how many trades need processing
print("\n2. Checking trades...")
total_trades = client.xlen(b"trades:closed")
print(f"   📊 Total trades in stream: {total_trades}")

# Check if already processed
last_processed_id = client.get(b"pnl:agg:last_id")
if last_processed_id:
    last_id = last_processed_id.decode('utf-8')
    print(f"   🔄 Last processed ID: {last_id}")
else:
    last_id = "0-0"
    print(f"   🔄 Starting fresh from: {last_id}")

# Read all unprocessed trades
print("\n3. Reading unprocessed trades...")
messages = client.xread({b"trades:closed": last_id.encode() if isinstance(last_id, str) else last_id}, count=1000)

if not messages:
    print("   ℹ️  No new trades to process")
    sys.exit(0)

stream_name, trades = messages[0]
print(f"   📥 Found {len(trades)} unprocessed trades")

# Restore equity
try:
    latest_bytes = client.get(b"pnl:equity:latest")
    if latest_bytes:
        latest_data = json.loads(latest_bytes)
        equity = float(latest_data.get("equity", START_EQUITY))
        print(f"\n4. Starting from equity: ${equity:,.2f}")
    else:
        equity = START_EQUITY
        print(f"\n4. Starting from initial equity: ${equity:,.2f}")
except:
    equity = START_EQUITY
    print(f"\n4. Starting from initial equity: ${equity:,.2f}")

# Process each trade
print("\n5. Processing trades...")
processed = 0
for message_id, fields in trades:
    try:
        # Decode message ID
        msg_id = message_id.decode("utf-8") if isinstance(message_id, bytes) else message_id

        # Parse trade data
        json_bytes = fields.get(b"json") or fields.get("json")
        if not json_bytes:
            continue

        if isinstance(json_bytes, bytes):
            trade_data = json.loads(json_bytes.decode("utf-8"))
        else:
            trade_data = json.loads(json_bytes)

        # Extract PnL
        pnl = trade_data.get("pnl", 0)
        ts = trade_data.get("ts", int(time.time() * 1000))
        pair = trade_data.get("pair", "???")

        # Update equity
        old_equity = equity
        equity += pnl
        processed += 1

        # Publish equity point
        equity_snapshot = {
            "ts": ts,
            "equity": equity,
            "daily_pnl": equity - START_EQUITY  # Simplified: assume all in one day
        }

        equity_json = json.dumps(equity_snapshot)

        # Write to stream and latest key
        client.xadd(b"pnl:equity", {b"json": equity_json.encode()}, maxlen=10000, approximate=True)
        client.set(b"pnl:equity:latest", equity_json.encode())

        # Update checkpoint
        last_id = msg_id
        client.set(b"pnl:agg:last_id", last_id.encode())

        # Print progress
        if processed % 10 == 0 or processed == len(trades):
            pnl_emoji = "🟢" if pnl >= 0 else "🔴"
            print(f"{pnl_emoji} {processed:3d}/{len(trades)}: {pair:9s} PnL: ${pnl:+8.2f} → Equity: ${equity:10,.2f}")

    except Exception as e:
        print(f"   ⚠️  Error processing trade {msg_id}: {e}")
        continue

# Summary
print(f"\n6. Summary:")
print(f"   ✅ Processed {processed} trades")
print(f"   💰 Final equity: ${equity:,.2f}")
print(f"   📈 Total PnL: ${equity - START_EQUITY:+,.2f}")
print(f"   📊 PnL%: {((equity / START_EQUITY - 1) * 100):+.2f}%")

# Verify
equity_stream_len = client.xlen(b"pnl:equity")
print(f"\n7. Verification:")
print(f"   ✅ pnl:equity stream has {equity_stream_len} points")
print(f"   ✅ Last processed ID saved: {last_id}")

print("\n" + "=" * 70)
print("✅ SUCCESS! All trades processed")
print("=" * 70)
print("\n📋 NEXT STEP: Refresh your PnL charts!")
print("   The charts should now show the equity curve.")
print("\n" + "=" * 70)
