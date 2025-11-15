#!/usr/bin/env python3
"""
Demo script for microstructure filters.

Tests rolling notional, spread, depth imbalance, and time window filters
across various market conditions.
"""

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config.microstructure_config import (
    load_microstructure_gate_config,
    override_time_window,
    parse_trade_window_arg,
)
from strategies.microstructure import MicrostructureGate


def print_section(title: str) -> None:
    """Print section header."""
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def print_test(description: str, allowed: bool, reasons: list) -> None:
    """Print test result."""
    status = "[ALLOW]" if allowed else "[REJECT]"
    print(f"\n{status} {description}")
    for reason in reasons:
        print(f"  - {reason}")


def main():
    """Run microstructure filter demo."""
    print("\n" + "=" * 60)
    print("MICROSTRUCTURE FILTERS DEMO")
    print("=" * 60)

    # Test 1: Load configuration
    print_section("Test 1: Load Configuration from YAML")

    config_path = project_root / "config" / "settings.yaml"
    config = load_microstructure_gate_config(config_path)

    print(f"[+] Loaded config from {config_path}")
    print(f"    Default min notional: ${config.default_min_notional_1m_usd:,.0f}")
    print(f"    Default max spread: {config.default_max_spread_bps}bps")
    print(f"    Default max imbalance: {config.default_max_depth_imbalance:.2f}")
    print(f"    Pair configs: {len(config.pair_configs)}")

    for symbol, pair_config in config.pair_configs.items():
        print(f"      {symbol}: notional=${pair_config.min_notional_1m_usd:,.0f}, spread={pair_config.max_spread_bps}bps")

    print(f"    Time window enabled: {config.time_window.enabled}")

    # Test 2: Create gate and add trade volume
    print_section("Test 2: Rolling Notional Filter (1-minute window)")

    gate = MicrostructureGate(config)
    now = time.time()

    # Simulate trades for BTC/USD over last minute
    print("[+] Simulating trade volume for BTC/USD:")
    trades = [
        (now - 50, 15000.0),
        (now - 40, 25000.0),
        (now - 30, 35000.0),
        (now - 20, 20000.0),
        (now - 10, 30000.0),
    ]

    total_notional = 0
    for ts, notional in trades:
        gate.add_trade("BTC/USD", notional, ts)
        total_notional += notional
        print(f"    T-{int(now - ts)}s: ${notional:,.0f}")

    print(f"    Total 1m notional: ${total_notional:,.0f}")

    btc_config = config.get_pair_config("BTC/USD")
    print(f"    BTC/USD threshold: ${btc_config.min_notional_1m_usd:,.0f}")
    print(f"    Status: {'PASS' if total_notional >= btc_config.min_notional_1m_usd else 'FAIL'}")

    # Test 3: Good market conditions
    print_section("Test 3: Good Market Conditions (All Checks Pass)")

    allowed, reasons = gate.check_can_enter(
        symbol="BTC/USD",
        bid=50000.0,
        ask=50010.0,  # 2 bps spread
        bid_volume=1000.0,
        ask_volume=1000.0,  # Perfectly balanced
        current_time=now,
        is_entry=True,
    )

    print_test(
        "BTC/USD - tight spread, balanced book, good volume",
        allowed,
        reasons,
    )

    # Test 4: Wide spread
    print_section("Test 4: Wide Spread (Rejection)")

    allowed, reasons = gate.check_can_enter(
        symbol="BTC/USD",
        bid=50000.0,
        ask=50100.0,  # 20 bps spread (max is 5bps for BTC/USD)
        bid_volume=1000.0,
        ask_volume=1000.0,
        current_time=now,
        is_entry=True,
    )

    print_test(
        "BTC/USD - wide spread (20bps > 5bps max)",
        allowed,
        reasons,
    )

    # Test 5: Depth imbalance
    print_section("Test 5: Depth Imbalance (Rejection)")

    allowed, reasons = gate.check_can_enter(
        symbol="BTC/USD",
        bid=50000.0,
        ask=50010.0,
        bid_volume=8000.0,  # 80% bids
        ask_volume=2000.0,  # 20% asks
        current_time=now,
        is_entry=True,
    )

    print_test(
        "BTC/USD - bid-heavy book (80/20 > 65/35 max)",
        allowed,
        reasons,
    )

    # Test 6: Low volume
    print_section("Test 6: Low Rolling Notional (Rejection)")

    # Create new gate without prior volume
    gate_low_volume = MicrostructureGate(config)

    # Add only small trades
    gate_low_volume.add_trade("ETH/USD", 5000.0, now - 30)
    gate_low_volume.add_trade("ETH/USD", 3000.0, now - 10)

    allowed, reasons = gate_low_volume.check_can_enter(
        symbol="ETH/USD",
        bid=3000.0,
        ask=3002.0,
        bid_volume=500.0,
        ask_volume=500.0,
        current_time=now,
        is_entry=True,
    )

    eth_config = config.get_pair_config("ETH/USD")
    print_test(
        f"ETH/USD - low volume ($8,000 < ${eth_config.min_notional_1m_usd:,.0f} required)",
        allowed,
        reasons,
    )

    # Test 7: Always allow exits
    print_section("Test 7: Exits Always Allowed (24/7 Position Management)")

    # Even with terrible conditions (wide spread, imbalanced, low volume)
    allowed, reasons = gate_low_volume.check_can_enter(
        symbol="ETH/USD",
        bid=3000.0,
        ask=3100.0,  # Wide spread
        bid_volume=9000.0,  # Very imbalanced
        ask_volume=1000.0,
        current_time=now,
        is_entry=False,  # EXIT, not entry
    )

    print_test(
        "ETH/USD - exit with terrible conditions (always allowed)",
        allowed,
        reasons,
    )

    # Test 8: Time window filtering
    print_section("Test 8: Time Window Filtering (CLI Override)")

    # Enable time window via CLI (12:00-22:00 UTC)
    config_with_window = override_time_window(
        config, enabled=True, start_hour=12, end_hour=22
    )

    gate_windowed = MicrostructureGate(config_with_window)

    # Add volume
    for ts, notional in trades:
        gate_windowed.add_trade("BTC/USD", notional, ts)

    # Simulate different times
    print("\n[+] Testing different UTC hours:")

    # Create timestamps for different hours
    base_date = datetime(2025, 1, 15, tzinfo=timezone.utc)

    test_hours = [
        (8, "08:00 UTC - Before window"),
        (12, "12:00 UTC - Window start"),
        (15, "15:00 UTC - Inside window"),
        (21, "21:00 UTC - Near window end"),
        (22, "22:00 UTC - After window"),
        (2, "02:00 UTC - Night hours"),
    ]

    for hour, description in test_hours:
        test_time = base_date.replace(hour=hour).timestamp()

        allowed, reasons = gate_windowed.check_can_enter(
            symbol="BTC/USD",
            bid=50000.0,
            ask=50010.0,
            bid_volume=1000.0,
            ask_volume=1000.0,
            current_time=test_time,
            is_entry=True,
        )

        status = "ALLOW" if allowed else "REJECT"
        print(f"  [{status}] {description}")
        # Only show time reason
        time_reason = [r for r in reasons if r.startswith("time:")][0]
        print(f"         {time_reason}")

    # Test 9: Pair-specific vs default thresholds
    print_section("Test 9: Pair-Specific vs Default Thresholds")

    # BTC/USD (has custom config)
    btc_cfg = config.get_pair_config("BTC/USD")
    print(f"[+] BTC/USD (custom config):")
    print(f"    Min notional: ${btc_cfg.min_notional_1m_usd:,.0f}")
    print(f"    Max spread: {btc_cfg.max_spread_bps}bps")
    print(f"    Max imbalance: {btc_cfg.max_depth_imbalance:.2f}")

    # SOL/USD (no custom config, uses defaults)
    sol_cfg = config.get_pair_config("SOL/USD")
    print(f"\n[+] SOL/USD (default config):")
    print(f"    Min notional: ${sol_cfg.min_notional_1m_usd:,.0f}")
    print(f"    Max spread: {sol_cfg.max_spread_bps}bps")
    print(f"    Max imbalance: {sol_cfg.max_depth_imbalance:.2f}")

    # Test 10: CLI argument parsing
    print_section("Test 10: CLI Argument Parsing")

    test_args = [
        "12-22",
        "14-20",
        "0-23",  # Full day
        "22-6",  # Wrap around midnight
    ]

    print("[+] Parsing --trade_window arguments:")
    for arg in test_args:
        try:
            start, end = parse_trade_window_arg(arg)
            print(f"    '{arg}' -> {start:02d}:00 to {end:02d}:00 UTC")
        except ValueError as e:
            print(f"    '{arg}' -> ERROR: {e}")

    # Summary
    print_section("Summary")

    print("""
Microstructure filters provide liquidity and timing gates for 24/7 trading:

1. Rolling Notional Filter
   - Tracks 1-minute rolling volume in USD
   - Pair-specific thresholds (BTC/USD: $100k, ETH/USD: $75k, default: $50k)
   - Prevents trading in thin markets

2. Spread Filter
   - Checks bid-ask spread in basis points
   - Pair-specific limits (BTC/USD: 5bps, ETH/USD: 8bps, default: 10bps)
   - Avoids wide spreads that eat into profits

3. Depth Imbalance Filter
   - Measures orderbook bid/ask balance
   - Rejects if imbalance > threshold (e.g., 70/30 split)
   - Prevents trading into one-sided books

4. Time Window Filter (Optional)
   - Restricts entries to specific UTC hours (e.g., 12:00-22:00)
   - Exits always allowed (24/7 position management)
   - Configurable via YAML or CLI --trade_window flag
   - Can restrict specific symbols (e.g., only USD pairs)

All filters:
- Configurable via config/settings.yaml
- Overridable via CLI
- Always allow exits (reduce-only 24/7)
- Pair-specific or default thresholds

Usage:
  python scripts/start_trading_system.py --mode paper --trade_window 12-22
    """)

    print("=" * 60)
    print("[PASS] Microstructure Filters Demo Complete")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n[FAIL] Demo failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
