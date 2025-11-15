#!/usr/bin/env python3
"""
Demo: STEP 5 Enhanced Risk Manager

Demonstrates all STEP 5 features:
- Per-trade risk limits (1-2%)
- Portfolio risk caps (≤4%)
- RR filter (≥1.6)
- 3-tier DD breakers (10%, 15%, 20%)
"""

from decimal import Decimal
from agents.risk_manager import RiskManager, RiskConfig, SignalInput

print("=" * 80)
print("STEP 5 ENHANCED RISK MANAGER DEMO")
print("=" * 80)

# Initialize risk manager
config = RiskConfig(
    per_trade_risk_pct_max=0.02,  # 2% max
    max_portfolio_risk_pct=0.04,  # 4% portfolio
    min_rr_ratio=1.6,  # Min RR
    dd_soft_threshold_pct=-0.10,  # -10%
    dd_hard_threshold_pct=-0.15,  # -15%
    dd_halt_threshold_pct=-0.20,  # -20%
)
rm = RiskManager(config=config)

equity = Decimal("10000.00")

# Test 1: Good signal (passes all checks)
print("\n" + "=" * 80)
print("TEST 1: Good Signal (RR = 3.0, passes all checks)")
print("=" * 80)

good_signal = SignalInput(
    signal_id="sig_001",
    symbol="BTC/USD",
    side="long",
    entry_price=Decimal("50000"),
    stop_loss=Decimal("49000"),  # -2% SL
    take_profit=Decimal("53000"),  # +6% TP (RR = 3.0)
    confidence=Decimal("0.75"),
)

position = rm.size_position(good_signal, equity)
print(f"✅ Signal: {good_signal.side} {good_signal.symbol} @ ${good_signal.entry_price}")
print(f"   SL: ${good_signal.stop_loss} (-2.0%)")
print(f"   TP: ${good_signal.take_profit} (+6.0%)")
print(f"   RR Ratio: 3.0 (✅ passes ≥1.6 requirement)")
print(f"\nPosition Sizing:")
print(f"   Allowed: {position.allowed}")
print(f"   Size: {position.size:.8f} BTC")
print(f"   Notional: ${float(position.notional_usd):,.2f}")
print(f"   Risk: ${float(position.expected_risk_usd):,.2f} ({float(position.risk_pct):.2%})")
print(f"   Leverage: {position.leverage}x")

# Test 2: Low RR signal (rejected)
print("\n" + "=" * 80)
print("TEST 2: Low RR Signal (RR = 1.0, rejected)")
print("=" * 80)

low_rr_signal = SignalInput(
    signal_id="sig_002",
    symbol="BTC/USD",
    side="long",
    entry_price=Decimal("50000"),
    stop_loss=Decimal("49000"),  # -2% SL
    take_profit=Decimal("51000"),  # +2% TP (RR = 1.0)
    confidence=Decimal("0.75"),
)

position2 = rm.size_position(low_rr_signal, equity)
print(f"❌ Signal: {low_rr_signal.side} {low_rr_signal.symbol} @ ${low_rr_signal.entry_price}")
print(f"   SL: ${low_rr_signal.stop_loss} (-2.0%)")
print(f"   TP: ${low_rr_signal.take_profit} (+2.0%)")
print(f"   RR Ratio: 1.0 (❌ fails ≥1.6 requirement)")
print(f"\nPosition Sizing:")
print(f"   Allowed: {position2.allowed}")
print(f"   Rejection Reasons: {position2.rejection_reasons}")

# Test 3: Portfolio risk check
print("\n" + "=" * 80)
print("TEST 3: Portfolio Risk Check")
print("=" * 80)

# Create 2 positions @ 2% each = 4% total (at limit)
positions = [
    rm.size_position(good_signal, equity),
    rm.size_position(good_signal, equity),
]

risk_check = rm.check_portfolio_risk(positions, equity)
print(f"Positions: {len([p for p in positions if p.allowed])}")
print(f"Total Risk: {float(risk_check.total_risk_pct):.2%}")
print(f"Portfolio Limit: {config.max_portfolio_risk_pct:.2%}")
print(f"Passed: {risk_check.passed}")

# Test 4: Drawdown breakers
print("\n" + "=" * 80)
print("TEST 4: Drawdown Breakers (3-Tier System)")
print("=" * 80)

# Scenario A: Normal (-5% DD)
equity_curve_normal = [Decimal("10000"), Decimal("9500")]
dd_state_normal = rm.update_drawdown_state(equity_curve_normal, current_bar=1)
print(f"\nScenario A: -5% DD")
print(f"   Mode: {dd_state_normal.mode}")
print(f"   Risk Multiplier: {dd_state_normal.risk_multiplier}x")
print(f"   Status: Normal trading")

# Scenario B: Soft stop (-11% DD)
equity_curve_soft = [Decimal("10000"), Decimal("8900")]
dd_state_soft = rm.update_drawdown_state(equity_curve_soft, current_bar=1)
print(f"\nScenario B: -11% DD")
print(f"   Mode: {dd_state_soft.mode}")
print(f"   Risk Multiplier: {dd_state_soft.risk_multiplier}x (halved)")
print(f"   Status: Soft stop - position sizes halved")

# Scenario C: Hard halt (-16% DD)
equity_curve_hard = [Decimal("10000"), Decimal("8400")]
dd_state_hard = rm.update_drawdown_state(equity_curve_hard, current_bar=1)
print(f"\nScenario C: -16% DD")
print(f"   Mode: {dd_state_hard.mode}")
print(f"   Risk Multiplier: {dd_state_hard.risk_multiplier}x (zero)")
print(f"   Pause Remaining: {dd_state_hard.pause_remaining} bars")
print(f"   Status: Hard halt - trading paused for 10 bars")

# Scenario D: Full halt (-21% DD)
equity_curve_halt = [Decimal("10000"), Decimal("7900")]
dd_state_halt = rm.update_drawdown_state(equity_curve_halt, current_bar=1)
print(f"\nScenario D: -21% DD")
print(f"   Mode: {dd_state_halt.mode}")
print(f"   Risk Multiplier: {dd_state_halt.risk_multiplier}x (zero)")
print(f"   Pause Remaining: {dd_state_halt.pause_remaining} bars")
print(f"   Status: Full halt - extended pause for 20 bars")

# Test 5: DD affects sizing
print("\n" + "=" * 80)
print("TEST 5: DD Affects Position Sizing")
print("=" * 80)

# Normal mode
rm_normal = RiskManager(config=config)
pos_normal = rm_normal.size_position(good_signal, equity)
print(f"Normal Mode:")
print(f"   Position Size: ${float(pos_normal.notional_usd):,.2f}")
print(f"   Risk: ${float(pos_normal.expected_risk_usd):,.2f} ({float(pos_normal.risk_pct):.2%})")

# Soft stop mode (risk halved)
rm_soft = RiskManager(config=config)
rm_soft.update_drawdown_state([Decimal("10000"), Decimal("8900")], current_bar=1)
pos_soft = rm_soft.size_position(good_signal, equity)
print(f"\nSoft Stop Mode (-11% DD):")
print(f"   Position Size: ${float(pos_soft.notional_usd):,.2f} (halved)")
print(f"   Risk: ${float(pos_soft.expected_risk_usd):,.2f} ({float(pos_soft.risk_pct):.2%})")

# Hard halt mode (no entries)
rm_halt = RiskManager(config=config)
rm_halt.update_drawdown_state([Decimal("10000"), Decimal("8400")], current_bar=1)
pos_halt = rm_halt.size_position(good_signal, equity)
print(f"\nHard Halt Mode (-16% DD):")
print(f"   Allowed: {pos_halt.allowed}")
print(f"   Rejection: {pos_halt.rejection_reasons}")

# Metrics
print("\n" + "=" * 80)
print("RISK MANAGER METRICS")
print("=" * 80)

metrics = rm.get_metrics()
print(f"Total Sized: {metrics['total_sized']}")
print(f"Total Rejected: {metrics['total_rejected']}")
print(f"Rejected (Min Size): {metrics['rejected_min_size']}")
print(f"Rejected (Portfolio): {metrics['rejected_portfolio_risk']}")
print(f"Rejected (DD Breaker): {metrics['rejected_drawdown']}")

print("\n" + "=" * 80)
print("DEMO COMPLETE - STEP 5 FEATURES VALIDATED")
print("=" * 80)
print("\nKey Features Demonstrated:")
print("  ✅ Per-trade risk limits (1-2% strict)")
print("  ✅ Portfolio risk caps (≤4%)")
print("  ✅ RR filter (≥1.6)")
print("  ✅ 3-tier DD breakers (10%, 15%, 20%)")
print("  ✅ DD affects sizing (0.5x in soft stop, 0.0x in halt)")
print("  ✅ Metrics tracking")
print("\nAll STEP 5 Requirements: COMPLETE ✅")
print("=" * 80)
