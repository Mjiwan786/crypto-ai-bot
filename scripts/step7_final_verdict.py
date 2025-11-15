"""
STEP 7 Final Verdict (7F)

Compares baseline (ML OFF) with winner (ML ON, threshold 0.60) and produces PASS/FAIL verdict.
"""

import json

# Load baseline (OFF)
with open("out/ml_off_synthetic.json") as f:
    baseline = json.load(f)

# Load winner (ON with threshold 0.60 - adjusted for generalization)
with open("out/ml_generalization_test.json") as f:
    data = json.load(f)
    winner = data["adjusted"]  # Use the adjusted threshold (0.60)

# Calculate monthly ROI for baseline
baseline_monthly_roi = baseline["annualized_return_pct"] / 12.0

# Extract metrics
off_roi = baseline_monthly_roi
off_pf = baseline["profit_factor"]
off_dd = baseline["max_drawdown_pct"]
off_trades = baseline["total_trades"]

on_roi = winner["monthly_roi_pct"]
on_pf = winner["profit_factor"]
on_dd = winner["max_drawdown_pct"]
on_trades = winner["total_trades"]
threshold = winner["threshold"]

# Check PASS criteria
pf_improved = on_pf > off_pf
dd_improved = on_dd > off_dd  # Less negative is better
roi_pass = on_roi >= 10.0

pass_criteria = (pf_improved or dd_improved) and roi_pass

print("=" * 90)
print("STEP 7F: FINAL VERDICT")
print("=" * 90)
print()
print("Baseline (ML OFF):")
print(f"  Monthly ROI: {off_roi:.2f}%")
print(f"  Profit Factor: {off_pf:.2f}")
print(f"  Max DD: {off_dd:.1f}%")
print(f"  Trades: {off_trades}")
print()
print(f"Winner (ML ON, threshold={threshold}):")
print(f"  Monthly ROI: {on_roi:.2f}%")
print(f"  Profit Factor: {on_pf:.2f}")
print(f"  Max DD: {on_dd:.1f}%")
print(f"  Trades: {on_trades}")
print()
print("Criteria Check:")
print(f"  PF improved: {on_pf:.2f} > {off_pf:.2f} = {pf_improved} ({'PASS' if pf_improved else 'FAIL'})")
print(f"  DD improved: {on_dd:.1f}% > {off_dd:.1f}% = {dd_improved} ({'PASS' if dd_improved else 'FAIL'})")
print(f"  Monthly ROI >= 10%: {on_roi:.2f}% >= 10% = {roi_pass} ({'PASS' if roi_pass else 'FAIL'})")
print()
print(f"Overall: (PF_improved OR DD_improved) AND ROI_pass = {pass_criteria}")
print()
print("=" * 90)

if pass_criteria:
    verdict_line = f"STEP 7 PASS [PASS] -- ROI={on_roi:.2f}%, PF={on_pf:.2f}, DD={on_dd:.1f}%, Trades={on_trades} (th={threshold})"
    print(verdict_line)
else:
    # Determine what failed and suggest fix
    if not roi_pass:
        tweak = "Reduce threshold by 0.05"
        cmd = f"python scripts/run_backtest.py --ml on --min_alignment_confidence {threshold - 0.05:.2f}"
    elif not (pf_improved or dd_improved):
        tweak = "Increase threshold by 0.05"
        cmd = f"python scripts/run_backtest.py --ml on --min_alignment_confidence {threshold + 0.05:.2f}"
    else:
        tweak = "Re-tune features or model params"
        cmd = "python scripts/run_backtest.py --ml on"

    verdict_line = f"STEP 7 FAIL [FAIL] -- Next action: {tweak} (command: {cmd})"
    print(verdict_line)

print("=" * 90)
print()

# Save verdict to file
with open("out/step7_verdict.txt", "w") as f:
    f.write(verdict_line + "\n")

print("Verdict saved to: out/step7_verdict.txt")
print(f"Verdict line to append to TASKLOG.md:\n{verdict_line}")
