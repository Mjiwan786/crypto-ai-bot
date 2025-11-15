"""
Demo script for ATR-based risk model with partial exits and breakeven.

Shows how the ATR risk model improves profit factor through:
1. ATR-based stop loss and take profit levels
2. Partial profit taking at TP1 (50% position)
3. Moving stop to breakeven at +0.8R
4. Trailing stop after TP1 hit

Usage:
    python test_atr_risk_demo.py
"""

from decimal import Decimal
import pandas as pd
from strategies.atr_risk import (
    calculate_atr,
    calculate_atr_risk_levels,
    update_atr_risk_levels,
    ATRRiskConfig,
)


def demo_long_winning_trade():
    """Demo a winning long trade with ATR risk management."""
    print("\n" + "=" * 70)
    print("DEMO: LONG WINNING TRADE WITH ATR RISK")
    print("=" * 70)

    # Create sample OHLCV data
    df = pd.DataFrame(
        {
            "high": [
                101,
                103,
                105,
                104,
                106,
                108,
                107,
                109,
                111,
                110,
                112,
                114,
                113,
                115,
                117,
            ],
            "low": [99, 101, 103, 102, 104, 106, 105, 107, 109, 108, 110, 112, 111, 113, 115],
            "close": [
                100,
                102,
                104,
                103,
                105,
                107,
                106,
                108,
                110,
                109,
                111,
                113,
                112,
                114,
                116,
            ],
        }
    )

    # Calculate ATR
    atr = calculate_atr(df, period=14)
    print(f"\n1. ATR calculated: {atr:.2f}")

    # Setup trade
    config = ATRRiskConfig(
        sl_atr_multiple=Decimal("0.6"),
        tp1_atr_multiple=Decimal("1.0"),
        tp2_atr_multiple=Decimal("1.8"),
        trail_atr_multiple=Decimal("0.8"),
        breakeven_r=Decimal("0.8"),
        tp1_size_pct=Decimal("0.50"),
    )

    entry_price = Decimal("50000")
    levels = calculate_atr_risk_levels("long", entry_price, atr, config)

    print(f"\n2. Trade opened:")
    print(f"   Entry: ${entry_price:.2f}")
    print(f"   Stop Loss: ${levels.stop_loss:.2f} ({config.sl_atr_multiple}x ATR)")
    print(f"   TP1: ${levels.tp1_price:.2f} (take {config.tp1_size_pct*100:.0f}%)")
    print(f"   TP2: ${levels.tp2_price:.2f}")
    print(f"   Breakeven: ${levels.breakeven_price:.2f} (+{config.breakeven_r}R)")

    # Simulate price moving up
    prices = [
        Decimal("50001"),  # Price moves up
        Decimal("50002"),  # Still moving
        levels.breakeven_price + Decimal("1"),  # Hit breakeven trigger
        levels.tp1_price + Decimal("1"),  # Hit TP1
        levels.tp1_price + Decimal("5"),  # Continue up (trailing)
        levels.tp2_price + Decimal("1"),  # Hit TP2
    ]

    position_size = Decimal("1.0")  # Full position
    realized_pnl = Decimal("0")

    for i, price in enumerate(prices, 1):
        print(f"\n3.{i} Price: ${price:.2f}")

        result = update_atr_risk_levels("long", price, levels)

        if result.should_update_stop:
            print(f"   > Stop moved to ${result.new_stop:.2f}")
            if levels.stop_moved_to_be:
                print(f"   > BREAKEVEN PROTECTION ACTIVATED")

        if result.should_close_partial:
            close_qty = position_size * result.close_size_pct
            partial_pnl = (price - entry_price) * close_qty
            realized_pnl += partial_pnl
            position_size -= close_qty
            print(f"   > PARTIAL EXIT: Closed {result.close_size_pct*100:.0f}% at TP1")
            print(f"      P&L: ${partial_pnl:.2f}")
            print(f"      Remaining: {position_size*100:.0f}%")

        if result.should_close_full:
            full_pnl = (price - entry_price) * position_size
            realized_pnl += full_pnl
            print(f"   > FULL EXIT: {result.close_reason.upper()}")
            print(f"      P&L on remaining: ${full_pnl:.2f}")
            print(f"      TOTAL P&L: ${realized_pnl:.2f}")
            position_size = Decimal("0")
            break

    print("\n" + "=" * 70)


def demo_long_losing_trade():
    """Demo a losing long trade with ATR risk management."""
    print("\n" + "=" * 70)
    print("DEMO: LONG LOSING TRADE WITH ATR RISK (Stop Loss Hit)")
    print("=" * 70)

    # Create sample OHLCV data
    df = pd.DataFrame(
        {
            "high": [
                101,
                103,
                105,
                104,
                106,
                108,
                107,
                109,
                111,
                110,
                112,
                114,
                113,
                115,
                117,
            ],
            "low": [99, 101, 103, 102, 104, 106, 105, 107, 109, 108, 110, 112, 111, 113, 115],
            "close": [
                100,
                102,
                104,
                103,
                105,
                107,
                106,
                108,
                110,
                109,
                111,
                113,
                112,
                114,
                116,
            ],
        }
    )

    atr = calculate_atr(df, period=14)
    print(f"\n1. ATR calculated: {atr:.2f}")

    config = ATRRiskConfig()
    entry_price = Decimal("50000")
    levels = calculate_atr_risk_levels("long", entry_price, atr, config)

    print(f"\n2. Trade opened:")
    print(f"   Entry: ${entry_price:.2f}")
    print(f"   Stop Loss: ${levels.stop_loss:.2f}")

    # Price moves against us
    stop_price = levels.stop_loss - Decimal("1")
    print(f"\n3. Price drops to: ${stop_price:.2f}")

    result = update_atr_risk_levels("long", stop_price, levels)

    if result.should_close_full:
        position_size = Decimal("1.0")
        pnl = (stop_price - entry_price) * position_size
        print(f"   > STOP LOSS HIT")
        print(f"      P&L: ${pnl:.2f}")
        print(f"      Loss limited by ATR-based stop!")

    print("\n" + "=" * 70)


def demo_breakeven_protection():
    """Demo breakeven protection preventing a winner from becoming a loser."""
    print("\n" + "=" * 70)
    print("DEMO: BREAKEVEN PROTECTION (Winner -> Breakeven instead of Loser)")
    print("=" * 70)

    df = pd.DataFrame(
        {
            "high": [
                101,
                103,
                105,
                104,
                106,
                108,
                107,
                109,
                111,
                110,
                112,
                114,
                113,
                115,
                117,
            ],
            "low": [99, 101, 103, 102, 104, 106, 105, 107, 109, 108, 110, 112, 111, 113, 115],
            "close": [
                100,
                102,
                104,
                103,
                105,
                107,
                106,
                108,
                110,
                109,
                111,
                113,
                112,
                114,
                116,
            ],
        }
    )

    atr = calculate_atr(df, period=14)
    config = ATRRiskConfig()
    entry_price = Decimal("50000")
    levels = calculate_atr_risk_levels("long", entry_price, atr, config)

    print(f"\n1. Trade opened at ${entry_price:.2f}")
    print(f"   Initial stop: ${levels.stop_loss:.2f}")
    print(f"   Breakeven trigger: ${levels.breakeven_price:.2f}")

    # Price moves to breakeven trigger
    be_price = levels.breakeven_price + Decimal("1")
    print(f"\n2. Price rises to ${be_price:.2f}")
    result = update_atr_risk_levels("long", be_price, levels)

    if result.should_update_stop and levels.stop_moved_to_be:
        print(f"   > Stop moved to breakeven: ${levels.current_stop:.2f}")

    # Price reverses back to entry
    reversal_price = entry_price
    print(f"\n3. Price reverses to ${reversal_price:.2f}")
    result = update_atr_risk_levels("long", reversal_price, levels)

    if result.should_close_full:
        pnl = (reversal_price - entry_price) * Decimal("1.0")
        print(f"   > Position closed at breakeven")
        print(f"      P&L: ${pnl:.2f} (protected from loss!)")
        print(f"\n   WITHOUT breakeven protection:")
        print(f"      Position would still be open, risking full SL")

    print("\n" + "=" * 70)


def main():
    """Run all demo scenarios."""
    print("\n" + "=" * 70)
    print("ATR-BASED RISK MODEL DEMONSTRATION")
    print("=" * 70)
    print("\nThis demo shows how ATR risk management improves trading results:")
    print("  1. Dynamic stops based on market volatility (ATR)")
    print("  2. Partial exits lock in profits early (50% at TP1)")
    print("  3. Breakeven stops prevent winners from becoming losers")
    print("  4. Trailing stops maximize winning trades")

    demo_long_winning_trade()
    demo_long_losing_trade()
    demo_breakeven_protection()

    print("\n" + "=" * 70)
    print("KEY BENEFITS OF ATR RISK MODEL:")
    print("=" * 70)
    print("  [+] Tighter stops in low volatility -> Better RR ratio")
    print("  [+] Wider stops in high volatility -> Fewer false stops")
    print("  [+] Partial exits at TP1 -> Higher win rate, locked profits")
    print("  [+] Breakeven at +0.8R -> Protect small winners")
    print("  [+] Trailing stops -> Maximize big winners")
    print("  [+] Net effect -> Higher profit factor, lower drawdown")
    print("\n" + "=" * 70 + "\n")


if __name__ == "__main__":
    main()
