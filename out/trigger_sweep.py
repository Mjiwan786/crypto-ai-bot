#!/usr/bin/env python3
"""
Trigger Threshold Sweep - Find Optimal Balance
Tests bar_reaction_5m with different trigger thresholds (5-20 bps)
to find the sweet spot between trade frequency and profitability.
"""

import subprocess
import json
import yaml
from pathlib import Path
import pandas as pd

# Test configuration
TRIGGER_BPS_RANGE = [5, 7, 9, 11, 13, 15, 17, 20]
BASE_CONFIG = Path("config/bar_reaction_5m.yaml")
TEMP_CONFIG = Path("config/bar_reaction_5m_temp.yaml")
OUTPUT_DIR = Path("out/trigger_sweep")
OUTPUT_DIR.mkdir(exist_ok=True)

results = []

print("="*80)
print("TRIGGER THRESHOLD PARAMETER SWEEP")
print("="*80)
print(f"Testing {len(TRIGGER_BPS_RANGE)} trigger values: {TRIGGER_BPS_RANGE}")
print()

for trigger_bps in TRIGGER_BPS_RANGE:
    print(f"\n{'='*80}")
    print(f"Testing trigger_bps = {trigger_bps}")
    print(f"{'='*80}")

    # Load base config
    with open(BASE_CONFIG) as f:
        config = yaml.safe_load(f)

    # Modify trigger threshold
    config['strategy']['trigger_bps_up'] = float(trigger_bps)
    config['strategy']['trigger_bps_down'] = float(trigger_bps)

    # Save temp config
    with open(TEMP_CONFIG, 'w') as f:
        yaml.dump(config, f)

    # Run backtest (suppress output except errors)
    try:
        result = subprocess.run(
            [
                "python", "scripts/run_backtest.py",
                "--strategy", "bar_reaction_5m",
                "--pairs", "BTC/USD",
                "--timeframe", "5m",
                "--lookback", "90d",
                "--capital", "10000"
            ],
            capture_output=True,
            text=True,
            timeout=120
        )

        # Parse output for key metrics
        output = result.stdout + result.stderr

        # Extract metrics from output
        metrics = {
            'trigger_bps': trigger_bps,
            'total_return_pct': None,
            'final_equity': None,
            'total_trades': None,
            'win_rate': None,
            'profit_factor': None,
            'max_drawdown_pct': None,
            'sharpe_ratio': None
        }

        for line in output.split('\n'):
            if 'Total Return:' in line:
                # Extract: Total Return: $-22.86 (-0.23%)
                parts = line.split('(')
                if len(parts) > 1:
                    pct_str = parts[1].split(')')[0].replace('%', '')
                    metrics['total_return_pct'] = float(pct_str)
            elif 'Final Equity:' in line:
                # Extract: Final Equity: $9,977.14
                parts = line.split('$')
                if len(parts) > 1:
                    equity_str = parts[1].replace(',', '').strip()
                    metrics['final_equity'] = float(equity_str)
            elif 'Total Trades:' in line:
                parts = line.split(':')
                if len(parts) > 1:
                    metrics['total_trades'] = int(parts[1].strip())
            elif 'Winning Trades:' in line and '(' in line:
                # Extract: Winning Trades: 0 (0.0%)
                parts = line.split('(')
                if len(parts) > 1:
                    pct_str = parts[1].split(')')[0].replace('%', '')
                    metrics['win_rate'] = float(pct_str)
            elif 'Profit Factor:' in line:
                parts = line.split(':')
                if len(parts) > 1:
                    try:
                        metrics['profit_factor'] = float(parts[1].strip())
                    except:
                        metrics['profit_factor'] = 0.0
            elif 'Max Drawdown:' in line and '(' in line:
                # Extract: Max Drawdown: $-9,921.06 (-99.21%)
                parts = line.split('(')
                if len(parts) > 1:
                    pct_str = parts[1].split(')')[0].replace('%', '')
                    metrics['max_drawdown_pct'] = float(pct_str)
            elif 'Sharpe Ratio:' in line:
                parts = line.split(':')
                if len(parts) > 1:
                    try:
                        metrics['sharpe_ratio'] = float(parts[1].strip())
                    except:
                        metrics['sharpe_ratio'] = 0.0

        results.append(metrics)

        # Print summary
        print(f"  Return: {metrics['total_return_pct']:+.2f}%  |  "
              f"Trades: {metrics['total_trades']}  |  "
              f"Win Rate: {metrics['win_rate']:.1f}%  |  "
              f"PF: {metrics['profit_factor']:.2f}")

    except subprocess.TimeoutExpired:
        print(f"  ⚠️  TIMEOUT (skipping)")
        results.append({'trigger_bps': trigger_bps, 'error': 'timeout'})
    except Exception as e:
        print(f"  ❌ ERROR: {e}")
        results.append({'trigger_bps': trigger_bps, 'error': str(e)})

# Clean up temp config
if TEMP_CONFIG.exists():
    TEMP_CONFIG.unlink()

# Save results
df = pd.DataFrame(results)
csv_path = OUTPUT_DIR / "trigger_sweep_results.csv"
df.to_csv(csv_path, index=False)

print(f"\n{'='*80}")
print("SWEEP COMPLETE")
print(f"{'='*80}")
print(f"\nResults saved to: {csv_path}")

# Print summary table
print("\n" + "="*80)
print("TRIGGER SWEEP RESULTS SUMMARY")
print("="*80)
print(df.to_string(index=False))

# Find best configuration
valid_results = df[df['total_trades'].notna() & (df['total_trades'] > 0)]
if len(valid_results) > 0:
    print(f"\n{'='*80}")
    print("BEST CONFIGURATIONS")
    print(f"{'='*80}")

    # Best by return
    best_return = valid_results.loc[valid_results['total_return_pct'].idxmax()]
    print(f"\nBest Return: trigger_bps={best_return['trigger_bps']:.0f}")
    print(f"  Return: {best_return['total_return_pct']:+.2f}%")
    print(f"  Trades: {best_return['total_trades']:.0f}")
    print(f"  Win Rate: {best_return['win_rate']:.1f}%")

    # Best by profit factor (if trades > 5)
    active_results = valid_results[valid_results['total_trades'] >= 5]
    if len(active_results) > 0:
        best_pf = active_results.loc[active_results['profit_factor'].idxmax()]
        print(f"\nBest Profit Factor (5+ trades): trigger_bps={best_pf['trigger_bps']:.0f}")
        print(f"  Return: {best_pf['total_return_pct']:+.2f}%")
        print(f"  Trades: {best_pf['total_trades']:.0f}")
        print(f"  Win Rate: {best_pf['win_rate']:.1f}%")
        print(f"  PF: {best_pf['profit_factor']:.2f}")

    # Best by Sharpe (if trades > 5)
    if len(active_results) > 0:
        best_sharpe = active_results.loc[active_results['sharpe_ratio'].idxmax()]
        print(f"\nBest Sharpe Ratio (5+ trades): trigger_bps={best_sharpe['trigger_bps']:.0f}")
        print(f"  Return: {best_sharpe['total_return_pct']:+.2f}%")
        print(f"  Trades: {best_sharpe['total_trades']:.0f}")
        print(f"  Sharpe: {best_sharpe['sharpe_ratio']:.2f}")

else:
    print("\n⚠️  No valid results found (all tests had 0 trades)")

print(f"\n{'='*80}\n")
