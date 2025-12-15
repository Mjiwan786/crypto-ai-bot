#!/usr/bin/env python3
"""
Quick script to diagnose PNL chart issues - check Redis data
"""
import os
import sys
import redis
import json

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# Redis connection from environment
REDIS_URL = os.getenv("REDIS_URL")
if not REDIS_URL:
    print("ERROR: REDIS_URL environment variable not set!")
    sys.exit(1)
CERT_PATH = os.getenv("REDIS_CA_CERT", r"C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem")

print("=" * 70)
print("PNL DATA DIAGNOSTIC")
print("=" * 70)

try:
    # Connect to Redis
    print("\n1. Connecting to Redis Cloud...")
    client = redis.from_url(
        REDIS_URL,
        decode_responses=True,
        ssl_ca_certs=CERT_PATH,
        socket_connect_timeout=10,
        socket_timeout=10,
    )
    client.ping()
    print("   ✅ Connected successfully")

    # Check trades:closed stream
    print("\n2. Checking trades:closed stream...")
    try:
        trades_len = client.xlen("trades:closed")
        print(f"   📊 Stream length: {trades_len} trades")

        if trades_len > 0:
            # Get last 5 trades
            last_trades = client.xrevrange("trades:closed", count=5)
            print(f"\n   Last 5 trades:")
            for trade_id, trade_data in last_trades:
                if 'json' in trade_data:
                    trade_obj = json.loads(trade_data['json'])
                    pnl = trade_obj.get('pnl', 0)
                    ts = trade_obj.get('ts', 0)
                    pair = trade_obj.get('pair', 'N/A')
                    print(f"   - ID: {trade_id[:20]}... | PnL: ${pnl:+.2f} | Pair: {pair}")
        else:
            print("   ⚠️ WARNING: No trades found in stream!")

    except Exception as e:
        print(f"   ❌ Error: {e}")

    # Check pnl:equity stream
    print("\n3. Checking pnl:equity stream...")
    try:
        equity_len = client.xlen("pnl:equity")
        print(f"   📈 Stream length: {equity_len} equity points")

        if equity_len > 0:
            # Get last 5 equity points
            last_equity = client.xrevrange("pnl:equity", count=5)
            print(f"\n   Last 5 equity points:")
            for eq_id, eq_data in last_equity:
                if 'json' in eq_data:
                    eq_obj = json.loads(eq_data['json'])
                    equity = eq_obj.get('equity', 0)
                    daily_pnl = eq_obj.get('daily_pnl', 0)
                    print(f"   - Equity: ${equity:,.2f} | Daily PnL: ${daily_pnl:+.2f}")
        else:
            print("   ⚠️ WARNING: No equity data found in stream!")

    except Exception as e:
        print(f"   ❌ Error: {e}")

    # Check pnl:equity:latest
    print("\n4. Checking pnl:equity:latest key...")
    try:
        latest = client.get("pnl:equity:latest")
        if latest:
            latest_obj = json.loads(latest)
            equity = latest_obj.get('equity', 0)
            daily_pnl = latest_obj.get('daily_pnl', 0)
            ts = latest_obj.get('ts', 0)
            print(f"   💰 Current Equity: ${equity:,.2f}")
            print(f"   📊 Daily PnL: ${daily_pnl:+.2f}")
            print(f"   ⏰ Timestamp: {ts}")
        else:
            print("   ⚠️ WARNING: No latest equity data found!")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # Check if aggregator is running
    print("\n5. Checking PnL aggregator state...")
    try:
        last_id = client.get("pnl:agg:last_id")
        if last_id:
            print(f"   🔄 Last processed ID: {last_id}")
        else:
            print("   ⚠️ WARNING: No aggregator checkpoint found - aggregator may not have run yet!")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # Check stats (if available)
    print("\n6. Checking PnL statistics...")
    try:
        win_rate = client.get("pnl:stats:win_rate")
        sharpe = client.get("pnl:stats:sharpe")
        max_dd = client.get("pnl:stats:max_drawdown")

        if win_rate:
            print(f"   📈 Win Rate: {float(win_rate)*100:.1f}%")
        if sharpe:
            print(f"   📉 Sharpe Ratio: {sharpe}")
        if max_dd:
            print(f"   💥 Max Drawdown: ${max_dd}")

        if not any([win_rate, sharpe, max_dd]):
            print("   ℹ️  No statistics available (pandas disabled or no data)")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # Summary and recommendations
    print("\n" + "=" * 70)
    print("DIAGNOSIS & RECOMMENDATIONS")
    print("=" * 70)

    trades_exist = trades_len > 0 if 'trades_len' in locals() else False
    equity_exists = equity_len > 0 if 'equity_len' in locals() else False
    latest_exists = latest is not None if 'latest' in locals() else False

    if not trades_exist:
        print("\n❌ ROOT CAUSE: No trade data found!")
        print("\n📋 SOLUTION:")
        print("   1. Check if your trading system is publishing trades to 'trades:closed'")
        print("   2. Verify the publisher is configured correctly")
        print("   3. Run a backtest or paper trading session to generate trades")
        print("   4. Or seed test data: python scripts/seed_closed_trades.py --count 100")

    elif not equity_exists:
        print("\n❌ ROOT CAUSE: PnL aggregator not running or not processing trades!")
        print("\n📋 SOLUTION:")
        print("   1. Start the PnL aggregator:")
        print("      conda activate crypto-bot")
        print("      python monitoring/pnl_aggregator.py")
        print("   2. Or check if aggregator process crashed - check logs")
        print("   3. Verify REDIS_URL environment variable is set correctly")

    elif not latest_exists:
        print("\n⚠️ WARNING: Aggregator may have issues publishing equity data")
        print("\n📋 SOLUTION:")
        print("   1. Restart the PnL aggregator")
        print("   2. Check aggregator logs for errors")

    else:
        print("\n✅ Data looks good! If charts still show flat line:")
        print("\n📋 POSSIBLE ISSUES:")
        print("   1. Chart is showing wrong time range (check date filters)")
        print("   2. All PnL values are the same (check if trades have actual PnL variation)")
        print("   3. Frontend not fetching data correctly (check API/query)")
        print("   4. Y-axis scale issue (check if equity range is too small)")
        print(f"\n   Current equity: ${equity:,.2f}")
        print(f"   Total data points: {equity_len}")

    print("\n" + "=" * 70)

except Exception as e:
    print(f"\n❌ FATAL ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
