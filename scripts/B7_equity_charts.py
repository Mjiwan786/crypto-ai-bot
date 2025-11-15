#!/usr/bin/env python3
"""
B7 - Equity & Drawdown Chart Generator

Generates simple matplotlib charts from equity_*.json files showing:
- Equity curve
- Rolling max drawdown

Usage:
    python scripts/B7_equity_charts.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

REPORTS_DIR = project_root / "reports"


def load_equity_data(equity_file: Path) -> pd.DataFrame:
    """
    Load equity data from JSON file.

    Args:
        equity_file: Path to equity JSON file

    Returns:
        DataFrame with timestamp and equity columns
    """
    with open(equity_file, "r") as f:
        data = json.load(f)

    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.set_index("timestamp")

    return df


def calculate_drawdown(equity_series: pd.Series) -> pd.Series:
    """
    Calculate rolling max drawdown percentage.

    Args:
        equity_series: Series of equity values

    Returns:
        Series of drawdown percentages (negative values)
    """
    running_max = equity_series.expanding().max()
    drawdown = ((equity_series - running_max) / running_max) * 100
    return drawdown


def generate_chart(equity_file: Path) -> None:
    """
    Generate equity and drawdown chart from equity JSON file.

    Args:
        equity_file: Path to equity JSON file
    """
    # Extract pair name from filename
    # Format: equity_{strategy}_{pair}_{timeframe}.json
    # Example: equity_scalper_BTC_USD_1h.json -> BTC/USD
    filename = equity_file.stem  # Remove .json extension
    parts = filename.split("_")

    if len(parts) < 4:
        print(f"Warning: Unexpected filename format: {filename}")
        pair_name = filename
    else:
        # Reconstruct pair from parts (e.g., BTC_USD -> BTC/USD)
        pair_parts = parts[2:-1]  # Skip 'equity', 'strategy', and timeframe
        pair_name = "/".join(pair_parts)

    print(f"Generating chart for {pair_name}...")

    # Load data
    df = load_equity_data(equity_file)

    # Calculate drawdown
    df["drawdown"] = calculate_drawdown(df["equity"])

    # Create figure with 2 subplots
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

    # Plot equity curve
    ax1.plot(df.index, df["equity"])
    ax1.set_ylabel("Equity ($)")
    ax1.set_title(f"{pair_name} - Equity Curve")
    ax1.grid(True, alpha=0.3)

    # Plot drawdown
    ax2.plot(df.index, df["drawdown"])
    ax2.set_ylabel("Drawdown (%)")
    ax2.set_xlabel("Date")
    ax2.set_title(f"{pair_name} - Rolling Max Drawdown")
    ax2.grid(True, alpha=0.3)
    ax2.axhline(y=0, color="black", linestyle="-", linewidth=0.5)

    # Adjust layout
    plt.tight_layout()

    # Save figure
    output_file = REPORTS_DIR / f"equity_{pair_parts[0]}_{pair_parts[1]}.png"
    plt.savefig(output_file, dpi=150, bbox_inches="tight")
    plt.close()

    print(f"  Saved: {output_file}")


def main() -> int:
    """Main entry point"""
    print("=" * 60)
    print("B7 - EQUITY & DRAWDOWN CHART GENERATOR")
    print("=" * 60)
    print()

    # Find all equity JSON files
    equity_files = sorted(REPORTS_DIR.glob("equity_*.json"))

    if not equity_files:
        print("ERROR: No equity_*.json files found in reports/")
        return 1

    print(f"Found {len(equity_files)} equity file(s)")
    print()

    # Generate chart for each file
    for equity_file in equity_files:
        try:
            generate_chart(equity_file)
        except Exception as e:
            print(f"ERROR: Failed to generate chart for {equity_file.name}: {e}")
            continue

    print()
    print("=" * 60)
    print("[OK] Chart generation complete")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
