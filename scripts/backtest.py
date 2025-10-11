#!/usr/bin/env python
"""
Entry point for running backtests.

This stub illustrates how you might structure a backtest CLI that
accepts parameters from the command line, loads configuration and
executes a backtest using your strategy and agent implementations.

Replace the body of `main()` with your own backtest harness.
"""
import argparse

from config.loader import get_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a backtest")
    parser.add_argument("symbol", help="Trading pair symbol (e.g. BTCUSD)")
    parser.add_argument("--start", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", help="End date (YYYY-MM-DD)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = get_config()
    print(f"Running backtest for {args.symbol} with config:")
    for k, v in config.items():
        print(f"  {k} = {v}")
    # TODO: implement your backtest harness here
    print("Backtest complete (this is a stub)")


if __name__ == "__main__":
    main()
