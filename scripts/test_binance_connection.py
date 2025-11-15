"""
Test Binance Connection

Verifies that Binance API is accessible and returns data.

Usage:
    python scripts/test_binance_connection.py
"""

import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.infrastructure.binance_reader import BinanceReader

def main():
    print("=" * 60)
    print("Binance Connection Test")
    print("=" * 60)

    # Set feature flag
    os.environ["EXTERNAL_VENUE_READS"] = "binance"

    # Create reader
    print("\n1. Initializing Binance reader...")
    reader = BinanceReader()

    if not reader.enabled:
        print("   [FAIL] Binance reader is disabled!")
        print("   Set EXTERNAL_VENUE_READS=binance to enable")
        return False

    print("   [OK] Binance reader initialized")

    # Test liquidity snapshot
    print("\n2. Testing liquidity snapshot for BTC/USD...")
    try:
        snapshot = reader.get_liquidity_snapshot("BTC/USD", depth_levels=5)

        if snapshot:
            print("   [OK] Liquidity snapshot received:")
            print(f"      Best Bid: ${snapshot.best_bid:,.2f}")
            print(f"      Best Ask: ${snapshot.best_ask:,.2f}")
            print(f"      Spread: {snapshot.spread_bps:.2f} bps")
            print(f"      Bid Depth: ${snapshot.bid_depth_usd:,.0f}")
            print(f"      Ask Depth: ${snapshot.ask_depth_usd:,.0f}")
            print(f"      Imbalance: {snapshot.imbalance_ratio:.2%}")
        else:
            print("   [WARN] No liquidity data received")
            return False
    except Exception as e:
        print(f"   [FAIL] Error getting liquidity: {e}")
        return False

    # Test ticker
    print("\n3. Testing ticker for BTC/USD...")
    try:
        ticker = reader.get_ticker("BTC/USD")

        if ticker:
            print("   [OK] Ticker received:")
            print(f"      Last Price: ${ticker.last_price:,.2f}")
            print(f"      24h Volume: {ticker.volume_24h:,.2f} BTC")
            print(f"      24h Change: {ticker.price_change_24h_pct:+.2f}%")
            print(f"      Trades: {ticker.trades_count_24h:,}")
        else:
            print("   [WARN] No ticker data received")
    except Exception as e:
        print(f"   [WARN] Error getting ticker: {e}")

    # Test funding rate
    print("\n4. Testing funding rate for BTC/USD...")
    try:
        funding = reader.get_funding_rate("BTC/USD")

        if funding:
            print("   [OK] Funding rate received:")
            print(f"      Current Rate: {funding.funding_rate * 100:.4f}%")
            print(f"      Annualized: {funding.funding_rate_8h_annualized:.2f}%")
            print(f"      Mark Price: ${funding.mark_price:,.2f}")
        else:
            print("   [WARN] No funding data received")
    except Exception as e:
        print(f"   [WARN] Error getting funding: {e}")

    # Test all symbols
    print("\n5. Testing all symbols data collection...")
    try:
        symbols = ["BTC/USD", "ETH/USD"]
        all_data = reader.get_all_symbols_data(symbols)

        print(f"   [OK] Collected data for {len(all_data)} symbols:")
        for symbol, data in all_data.items():
            components = []
            if "liquidity" in data:
                components.append("liquidity")
            if "ticker" in data:
                components.append("ticker")
            if "funding" in data:
                components.append("funding")
            print(f"      {symbol}: {', '.join(components)}")
    except Exception as e:
        print(f"   [FAIL] Error collecting all data: {e}")
        return False

    print("\n" + "=" * 60)
    print("[SUCCESS] All tests passed! Binance connection is working.")
    print("=" * 60)

    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
