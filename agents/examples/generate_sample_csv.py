#!/usr/bin/env python3
"""
Generate Sample CSV Data

Creates sample OHLCV data in CSV format for testing backtest_one_pair.py.

Usage:
    python -m agents.examples.generate_sample_csv
    python -m agents.examples.generate_sample_csv --output my_data.csv --bars 2000
"""

import argparse
import csv
import random
from datetime import datetime, timedelta


def generate_sample_csv(output_path: str, num_bars: int, base_price: float):
    """Generate sample OHLCV CSV data"""
    print(f"Generating {num_bars} bars of sample data...")

    current_price = base_price
    current_time = datetime.now() - timedelta(hours=num_bars)

    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp', 'open', 'high', 'low', 'close', 'volume'])

        for i in range(num_bars):
            # Price movement with random walk
            price_change = random.gauss(0, current_price * 0.01)

            open_price = current_price
            close_price = current_price + price_change

            high_price = max(open_price, close_price) * (1 + abs(random.gauss(0, 0.005)))
            low_price = min(open_price, close_price) * (1 - abs(random.gauss(0, 0.005)))

            volume = random.uniform(10, 200)

            writer.writerow([
                int(current_time.timestamp()),
                f"{open_price:.2f}",
                f"{high_price:.2f}",
                f"{low_price:.2f}",
                f"{close_price:.2f}",
                f"{volume:.2f}"
            ])

            current_price = close_price
            current_time += timedelta(hours=1)

    print(f"✅ Sample data saved to: {output_path}")
    print(f"   Bars: {num_bars}")
    print(f"   Starting price: ${base_price:,.2f}")
    print(f"   Final price: ${current_price:,.2f}")
    print(f"\nUse with backtest:")
    print(f"  python -m agents.examples.backtest_one_pair --data {output_path}")


def main():
    parser = argparse.ArgumentParser(description='Generate sample OHLCV CSV data')
    parser.add_argument('--output', default='sample_data.csv', help='Output CSV path')
    parser.add_argument('--bars', type=int, default=1000, help='Number of bars')
    parser.add_argument('--base-price', type=float, default=50000.0, help='Starting price')

    args = parser.parse_args()
    generate_sample_csv(args.output, args.bars, args.base_price)


if __name__ == '__main__':
    main()
