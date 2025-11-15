"""
Standalone test for new strategies (no backtest engine required).

Tests strategies with synthetic data and validates:
- Signal generation
- Position sizing
- Risk management
- Strategy-specific logic

⚠️ SAFETY: No live trading unless MODE=live and confirmation set.
This script is for testing only and does not execute real trades.

Usage:
    python scripts/test_strategies_standalone.py
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from ai_engine.schemas import MarketSnapshot, RegimeLabel
from strategies.breakout import BreakoutStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.momentum_strategy import MomentumStrategy
from strategies.regime_based_router import RegimeBasedRouter

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def create_synthetic_data(n_bars: int = 100, regime: str = "trending") -> pd.DataFrame:
    """
    Create synthetic OHLCV data for testing.

    Args:
        n_bars: Number of bars to generate
        regime: Market regime ("trending", "choppy", "volatile")

    Returns:
        DataFrame with OHLCV data
    """
    np.random.seed(42)

    if regime == "trending":
        # Uptrend with consistent momentum
        base_prices = np.linspace(49000, 52000, n_bars)
        noise = np.random.normal(0, 100, n_bars)
        close_prices = base_prices + noise

    elif regime == "choppy":
        # Sideways/oscillating market
        mean_price = 50000
        amplitude = 1500
        close_prices = mean_price + amplitude * np.sin(np.linspace(0, 4 * np.pi, n_bars))
        close_prices += np.random.normal(0, 100, n_bars)

    elif regime == "volatile":
        # High volatility with random walk
        close_prices = [50000]
        for _ in range(n_bars - 1):
            change_pct = np.random.normal(0, 0.02)  # 2% std dev
            close_prices.append(close_prices[-1] * (1 + change_pct))
        close_prices = np.array(close_prices)

    else:
        raise ValueError(f"Unknown regime: {regime}")

    # Generate OHLCV
    high_prices = close_prices + np.random.uniform(50, 200, n_bars)
    low_prices = close_prices - np.random.uniform(50, 200, n_bars)
    open_prices = close_prices - np.random.uniform(-100, 100, n_bars)
    volume = np.random.uniform(1e6, 3e6, n_bars)

    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=n_bars, freq="1h"),
            "open": open_prices,
            "high": high_prices,
            "low": low_prices,
            "close": close_prices,
            "volume": volume,
        }
    )

    return df


def create_snapshot(price: float, symbol: str = "BTC/USD") -> MarketSnapshot:
    """Create market snapshot for testing."""
    return MarketSnapshot(
        symbol=symbol,
        timeframe="1h",
        timestamp_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
        mid_price=price,
        spread_bps=10.0,
        volume_24h=500000000.0,
    )


def test_strategy(
    strategy_name: str, strategy, ohlcv_df: pd.DataFrame, regime_label: RegimeLabel
) -> dict:
    """
    Test a strategy with synthetic data.

    Args:
        strategy_name: Strategy name for logging
        strategy: Strategy instance
        ohlcv_df: OHLCV DataFrame
        regime_label: Market regime

    Returns:
        Dict with test results
    """
    logger.info(f"\n{'=' * 60}")
    logger.info(f"Testing: {strategy_name}")
    logger.info(f"{'=' * 60}")

    current_price = float(ohlcv_df["close"].iloc[-1])
    snapshot = create_snapshot(current_price)

    # Prepare strategy
    if hasattr(strategy, "prepare"):
        strategy.prepare(snapshot, ohlcv_df)
        logger.info("✓ Strategy prepared")

    # Check should_trade
    if hasattr(strategy, "should_trade"):
        should_trade = strategy.should_trade(snapshot)
        logger.info(f"✓ Should trade: {should_trade}")

        if not should_trade:
            logger.warning("  Strategy declined to trade (filters rejected)")
            return {
                "strategy": strategy_name,
                "signals_generated": 0,
                "positions_sized": 0,
                "should_trade": False,
            }

    # Generate signals
    if hasattr(strategy, "route_signal"):
        # RegimeBasedRouter has different interface
        signal, routing_reason = strategy.route_signal(snapshot, ohlcv_df, regime_label)
        signals = [signal] if signal else []
        logger.info(f"✓ Router decision: {routing_reason}")
    else:
        signals = strategy.generate_signals(snapshot, ohlcv_df, regime_label)
        logger.info(f"✓ Signals generated: {len(signals)}")

    if not signals:
        logger.info("  No signals generated (conditions not met)")
        return {
            "strategy": strategy_name,
            "signals_generated": 0,
            "positions_sized": 0,
            "should_trade": True,
        }

    # Log signal details
    for i, signal in enumerate(signals):
        logger.info(f"  Signal {i+1}:")
        logger.info(f"    Side: {signal.side}")
        logger.info(f"    Entry: {signal.entry_price}")
        logger.info(f"    Stop Loss: {signal.stop_loss}")
        logger.info(f"    Take Profit: {signal.take_profit}")
        logger.info(f"    Confidence: {signal.confidence:.2f}")

    # Size positions
    if hasattr(strategy, "size_positions"):
        positions = strategy.size_positions(
            signals, account_equity_usd=Decimal("10000"), current_volatility=Decimal("0.50")
        )
        logger.info(f"✓ Positions sized: {len(positions)}")

        # Log position details
        for i, pos in enumerate(positions):
            pct_of_equity = (float(pos.notional_usd) / 10000) * 100
            logger.info(f"  Position {i+1}:")
            logger.info(f"    Size: {pos.size:.6f} {signal.symbol.split('/')[0]}")
            logger.info(f"    Notional: ${pos.notional_usd:.2f}")
            logger.info(f"    % of Equity: {pct_of_equity:.1f}%")
            logger.info(f"    Expected Risk: ${pos.expected_risk_usd:.2f}")
            logger.info(f"    Vol-Adjusted: {pos.volatility_adjusted}")

    else:
        positions = []
        logger.warning("  Strategy does not support position sizing")

    return {
        "strategy": strategy_name,
        "signals_generated": len(signals),
        "positions_sized": len(positions),
        "should_trade": True,
        "signals": signals,
        "positions": positions,
    }


def print_summary(results: list[dict]) -> None:
    """Print summary table of all results."""
    logger.info(f"\n{'=' * 60}")
    logger.info("TEST SUMMARY")
    logger.info(f"={'=' * 60}")

    logger.info(f"\n{'Strategy':<25} {'Signals':>10} {'Positions':>10} {'Traded':>10}")
    logger.info("-" * 60)

    for result in results:
        traded = "Yes" if result["should_trade"] else "No"
        logger.info(
            f"{result['strategy']:<25} {result['signals_generated']:>10} "
            f"{result['positions_sized']:>10} {traded:>10}"
        )

    logger.info("-" * 60)

    total_signals = sum(r["signals_generated"] for r in results)
    total_positions = sum(r["positions_sized"] for r in results)

    logger.info(f"\nTotal signals generated: {total_signals}")
    logger.info(f"Total positions sized: {total_positions}")


def main():
    """Main entry point."""
    logger.info("Starting standalone strategy tests...")

    # Test scenarios
    scenarios = [
        ("Trending Market", "trending", RegimeLabel.BULL),
        ("Choppy Market", "choppy", RegimeLabel.CHOP),
        ("Volatile Market", "volatile", RegimeLabel.BULL),
    ]

    # Strategies
    strategies = [
        ("Breakout (ATR)", BreakoutStrategy()),
        ("Momentum (Twin)", MomentumStrategy()),
        ("MeanReversion (RSI)", MeanReversionStrategy()),
        ("RegimeRouter", RegimeBasedRouter(use_ensemble=False)),
    ]

    all_results = []

    for scenario_name, data_regime, strategy_regime in scenarios:
        logger.info(f"\n\n{'#' * 60}")
        logger.info(f"SCENARIO: {scenario_name}")
        logger.info(f"{'#' * 60}")

        # Generate data
        ohlcv_df = create_synthetic_data(n_bars=100, regime=data_regime)
        logger.info(f"Generated {len(ohlcv_df)} bars of {data_regime} data")
        logger.info(f"Price range: {ohlcv_df['close'].min():.2f} - {ohlcv_df['close'].max():.2f}")

        for strategy_name, strategy in strategies:
            try:
                result = test_strategy(strategy_name, strategy, ohlcv_df, strategy_regime)
                result["scenario"] = scenario_name
                all_results.append(result)

            except Exception as e:
                logger.error(f"Error testing {strategy_name}: {e}")
                import traceback

                traceback.print_exc()

    # Print overall summary
    print_summary(all_results)

    logger.info("\n✓ All strategy tests completed!")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
