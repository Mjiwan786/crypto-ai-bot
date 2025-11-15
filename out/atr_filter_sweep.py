#!/usr/bin/env python3
"""
ATR Filter Sweep - Test if volatility filters are too restrictive
Tests different min_atr_pct thresholds to see if this is blocking trades.
"""

import subprocess
import json
import yaml
from pathlib import Path
import pandas as pd

# Test configuration - focus on min_atr_pct since we have low volatility period
MIN_ATR_PCT_RANGE = [0.01, 0.03, 0.05, 0.08, 0.10, 0.15, 0.20]
BASE_CONFIG = Path("config/bar_reaction_5m.yaml")
TEMP_CONFIG = Path("config/bar_reaction_5m_temp.yaml")
OUTPUT_DIR = Path("out/trigger_sweep")
OUTPUT_DIR.mkdir(exist_ok=True)

results = []

print("="*80)
print("MIN ATR FILTER PARAMETER SWEEP")
print("="*80)
print(f"Testing {len(MIN_ATR_PCT_RANGE)} min_atr_pct values: {MIN_ATR_PCT_RANGE}")
print("Using aggressive trigger_bps=5 to maximize potential trades")
print()

for min_atr in MIN_ATR_PCT_RANGE:
    print(f"\n{'='*80}")
    print(f"Testing min_atr_pct = {min_atr:.2f}%")
    print(f"{'='*80}")

    # Load base config
    with open(BASE_CONFIG) as f:
        config = yaml.safe_load(f)

    # Modify ATR filter and use aggressive trigger
    config['strategy']['min_atr_pct'] = float(min_atr)
    config['strategy']['trigger_bps_up'] = 5.0  # Very aggressive
    config['strategy']['trigger_bps_down'] = 5.0

    # Save temp config
    with open(TEMP_CONFIG, 'w') as f:
        yaml.dump(config, f)

    # Run backtest
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

        output = result.stdout + result.stderr

        # Extract metrics
        metrics = {
            'min_atr_pct': min_atr,
            'total_return_pct': None,
            'final_equity': None,
            'total_trades': None,
            'win_rate': None,
            'profit_factor': None,
            'max_drawdown_pct': None,
        }

        for line in output.split('\n'):
            if 'Total Return:' in line and '(' in line:
                parts = line.split('(')
                if len(parts) > 1:
                    pct_str = parts[1].split(')')[0].replace('%', '')
                    metrics['total_return_pct'] = float(pct_str)
            elif 'Final Equity:' in line and '$' in line:
                parts = line.split('$')
                if len(parts) > 1:
                    equity_str = parts[1].replace(',', '').strip()
                    metrics['final_equity'] = float(equity_str)
            elif 'Total Trades:' in line:
                parts = line.split(':')
                if len(parts) > 1:
                    metrics['total_trades'] = int(parts[1].strip())
            elif 'Winning Trades:' in line and '(' in line:
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

        results.append(metrics)

        # Print summary
        print(f"  Return: {metrics['total_return_pct']:+.2f}%  |  "
              f"Trades: {metrics['total_trades']}  |  "
              f"Win Rate: {metrics['win_rate']:.1f}%  |  "
              f"PF: {metrics['profit_factor']:.2f}")

    except Exception as e:
        print(f"  ❌ ERROR: {e}")
        results.append({'min_atr_pct': min_atr, 'error': str(e)})

# Clean up
if TEMP_CONFIG.exists():
    TEMP_CONFIG.unlink()

# Save results
df = pd.DataFrame(results)
csv_path = OUTPUT_DIR / "atr_filter_sweep_results.csv"
df.to_csv(csv_path, index=False)

print(f"\n{'='*80}")
print("ATR FILTER SWEEP COMPLETE")
print(f"{'='*80}")
print(f"\nResults saved to: {csv_path}")

print("\n" + "="*80)
print("ATR FILTER SWEEP RESULTS")
print("="*80)
print(df.to_string(index=False))

# Analysis
valid_results = df[df['total_trades'].notna()]
if len(valid_results) > 0:
    trade_increase = valid_results['total_trades'].max() - valid_results['total_trades'].min()
    print(f"\n✓ Trade count range: {valid_results['total_trades'].min():.0f} to {valid_results['total_trades'].max():.0f}")
    if trade_increase > 0:
        print(f"✓ Lowering min_atr_pct increased trades by {trade_increase:.0f}")
        best = valid_results.loc[valid_results['total_return_pct'].idxmax()]
        print(f"\nBest result: min_atr_pct={best['min_atr_pct']:.2f}%")
        print(f"  Return: {best['total_return_pct']:+.2f}%")
        print(f"  Trades: {best['total_trades']:.0f}")
        print(f"  Win Rate: {best['win_rate']:.1f}%")
    else:
        print("⚠️  min_atr_pct filter is NOT the limiting factor")
        print("   All thresholds produce the same trade count")

print(f"\n{'='*80}\n")
