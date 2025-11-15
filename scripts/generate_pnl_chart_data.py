"""
Generate PnL chart data for the website from backtest results
Converts monthly backtest data to daily equity curve format
"""

import pandas as pd
import json
from datetime import datetime, timedelta
import os

def parse_currency(value):
    """Parse currency string like '$10,754.47' to float"""
    if isinstance(value, str):
        return float(value.replace('$', '').replace(',', '').replace('+', ''))
    return float(value)

def parse_percentage(value):
    """Parse percentage string like '+7.54%' to float"""
    if isinstance(value, str):
        return float(value.replace('%', '').replace('+', ''))
    return float(value)

def generate_pnl_chart_data():
    """
    Generate PnL chart data from backtest CSV

    Strategy: Build the full 12-month equity curve by working through
    each month and applying the P&L to build up from $10,000 initial capital
    """

    # Read the monthly backtest data
    csv_path = 'out/acquire_annual_snapshot.csv'
    df = pd.read_csv(csv_path)

    # CSV is in reverse chronological order - reverse it
    df = df.iloc[::-1].reset_index(drop=True)

    # Build the equity curve starting from $10,000
    chart_data = []
    cumulative_equity = 10000.0  # Initial capital

    print(f"Building equity curve from {len(df)} months of data...")

    for idx, row in df.iterrows():
        month_str = row['Month']
        net_pnl = parse_currency(row['Net P&L ($)'])

        # Parse month (format: "2025-11")
        year, month = map(int, month_str.split('-'))
        month_date = datetime(year, month, 1)

        # Calculate days in this month
        if month == 12:
            next_month_date = datetime(year + 1, 1, 1)
        else:
            next_month_date = datetime(year, month + 1, 1)
        days_in_month = (next_month_date - month_date).days

        # Starting equity for this month
        month_start_equity = cumulative_equity

        # Ending equity after this month's P&L
        month_end_equity = month_start_equity + net_pnl

        # Daily change (linear interpolation within month)
        daily_change = net_pnl / days_in_month if days_in_month > 0 else 0

        print(f"  {month_str}: ${month_start_equity:,.2f} -> ${month_end_equity:,.2f} (P&L: ${net_pnl:+,.2f})")

        # Generate daily data points for this month
        for day in range(days_in_month):
            current_date = month_date + timedelta(days=day)
            current_equity = month_start_equity + (daily_change * day)

            ts = int(current_date.timestamp())

            chart_data.append({
                'ts': ts,
                'equity': round(current_equity, 2),
                'daily_pnl': round(daily_change, 2),
                'month': month_str
            })

        # Update cumulative equity for next month
        cumulative_equity = month_end_equity

    # Add final data point at end of last month
    final_month_data = df.iloc[-1]
    final_year, final_month = map(int, final_month_data['Month'].split('-'))
    if final_month == 12:
        final_date = datetime(final_year + 1, 1, 1)
    else:
        final_date = datetime(final_year, final_month + 1, 1)

    chart_data.append({
        'ts': int(final_date.timestamp()),
        'equity': round(cumulative_equity, 2),
        'daily_pnl': 0,
        'month': final_month_data['Month']
    })

    # Calculate summary stats
    initial_equity = 10000.0
    final_equity = cumulative_equity
    total_return = ((final_equity - initial_equity) / initial_equity) * 100

    # Calculate max drawdown
    running_max = initial_equity
    max_drawdown = 0
    for point in chart_data:
        running_max = max(running_max, point['equity'])
        drawdown = ((point['equity'] - running_max) / running_max) * 100
        max_drawdown = min(max_drawdown, drawdown)

    # Get date range
    first_date = datetime.fromtimestamp(chart_data[0]['ts'])
    last_date = datetime.fromtimestamp(chart_data[-1]['ts'])

    metadata = {
        'generated_at': datetime.now().isoformat(),
        'source': 'acquire_annual_snapshot.csv',
        'period': f"{first_date.strftime('%b %Y')} - {last_date.strftime('%b %Y')}",
        'initial_equity': round(initial_equity, 2),
        'final_equity': round(final_equity, 2),
        'total_return_pct': round(total_return, 2),
        'max_drawdown_pct': round(max_drawdown, 2),
        'data_points': len(chart_data),
        'months': len(df),
        'disclaimer': 'Backtested performance. Past results do not guarantee future returns.'
    }

    output = {
        'metadata': metadata,
        'data': chart_data
    }

    # Write to JSON file
    output_path = 'out/pnl_chart_data.json'
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)

    print("\nGenerated PnL chart data:", output_path)
    print("   Data points:", len(chart_data))
    print("   Months:", len(df))
    print(f"   Period: {first_date.strftime('%b %Y')} - {last_date.strftime('%b %Y')}")
    print(f"   Initial equity: ${initial_equity:,.2f}")
    print(f"   Final equity: ${final_equity:,.2f}")
    print(f"   Total return: {total_return:+.2f}%")
    print(f"   Max drawdown: {max_drawdown:.2f}%")

    return output

if __name__ == '__main__':
    generate_pnl_chart_data()
